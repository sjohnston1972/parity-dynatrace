"""Build topology graph from device inventory and snapshot data."""

import ipaddress

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.tables import Device, Setting, Snapshot

log = structlog.get_logger()


def _short_intf(name: str) -> str:
    """Shorten interface names for display: GigabitEthernet0/1 → Gi0/1."""
    replacements = [
        ("GigabitEthernet", "Gi"),
        ("FastEthernet", "Fa"),
        ("TenGigabitEthernet", "Te"),
        ("Loopback", "Lo"),
        ("Vlan", "Vl"),
        ("Port-channel", "Po"),
        ("Ethernet", "Eth"),
    ]
    for full, short in replacements:
        if name.startswith(full):
            return short + name[len(full):]
    return name


async def build_topology(db: AsyncSession) -> dict:
    """Build topology graphs from the latest snapshot per device.

    Returns three separate edge lists for independent topology views:
      - bgp_edges: BGP peering relationships
      - subnet_edges: Shared L3 subnets
      - l2_edges: Layer 2 adjacencies (ARP/MAC based)

    Returns {"nodes": [...], "bgp_edges": [...], "subnet_edges": [...], "l2_edges": [...]}.
    """
    # Fetch all devices
    result = await db.execute(select(Device).order_by(Device.hostname))
    devices = list(result.scalars().all())

    if not devices:
        return {"nodes": [], "bgp_edges": [], "l2_segments": []}

    # Fetch latest *successful* snapshot per device (has features_learned).
    latest_sq = (
        select(Snapshot.device_id, func.max(Snapshot.created_at).label("max_ts"))
        .where(func.array_length(Snapshot.features_learned, 1) > 0)
        .group_by(Snapshot.device_id)
        .subquery()
    )
    result = await db.execute(
        select(Snapshot)
        .join(
            latest_sq,
            (Snapshot.device_id == latest_sq.c.device_id)
            & (Snapshot.created_at == latest_sq.c.max_ts),
        )
    )
    snapshots = {s.device_id: s for s in result.scalars().all()}

    # ── Shared data structures ──────────────────────────────────
    ip_to_device: dict[str, str] = {}
    ip_to_intf: dict[str, tuple[str, str]] = {}  # IP → (device_id, intf_name)
    device_subnets: dict[str, list[tuple[str, str, str]]] = {}  # dev → [(ip, subnet, intf)]
    mac_to_device: dict[str, tuple[str, str]] = {}  # MAC → (device_id, intf_name)

    for device in devices:
        snap = snapshots.get(device.id)
        if not snap or not isinstance(snap.snapshot_data, dict):
            continue
        interfaces = snap.snapshot_data.get("interface", {})
        if not isinstance(interfaces, dict):
            continue

        for intf_name, intf_data in interfaces.items():
            if not isinstance(intf_data, dict):
                continue

            # Register MAC → device for L2 discovery
            mac = intf_data.get("mac_address") or intf_data.get("phys_address")
            if mac:
                mac_to_device[mac.lower().replace(".", "")] = (device.id, intf_name)

            if not intf_data.get("enabled") or intf_data.get("oper_status") != "up":
                continue
            ipv4 = intf_data.get("ipv4", {})
            if not isinstance(ipv4, dict):
                continue
            for addr_str in ipv4:
                ip = addr_str.split("/")[0]
                ip_to_device[ip] = device.id
                ip_to_intf[ip] = (device.id, intf_name)
                try:
                    iface = ipaddress.ip_interface(addr_str if "/" in addr_str else f"{addr_str}/24")
                    subnet_str = str(iface.network)
                except ValueError:
                    parts = ip.split(".")
                    subnet_str = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24" if len(parts) == 4 else ip
                device_subnets.setdefault(device.id, []).append((ip, subnet_str, intf_name))

        if device.management_ip:
            ip_to_device[device.management_ip] = device.id

    # ── BGP edges ───────────────────────────────────────────────
    bgp_edges: list[dict] = []
    bgp_edge_set: set[tuple[str, str]] = set()

    for device in devices:
        snap = snapshots.get(device.id)
        if not snap or not isinstance(snap.snapshot_data, dict):
            continue
        bgp = snap.snapshot_data.get("bgp", {})
        if not isinstance(bgp, dict):
            continue

        for instance in bgp.get("instance", {}).values():
            if not isinstance(instance, dict):
                continue
            for vrf_name, vrf in instance.get("vrf", {}).items():
                if not isinstance(vrf, dict):
                    continue
                for neighbor_ip, ndata in vrf.get("neighbor", {}).items():
                    if not isinstance(ndata, dict):
                        continue
                    peer_device_id = ip_to_device.get(neighbor_ip)
                    if not peer_device_id or peer_device_id == device.id:
                        continue

                    pair = tuple(sorted([device.id, peer_device_id]))
                    if pair in bgp_edge_set:
                        continue
                    bgp_edge_set.add(pair)

                    state = ndata.get("session_state", "Unknown")
                    health = "optimal" if state == "Established" else "critical"

                    peer_info = ip_to_intf.get(neighbor_ip)
                    to_intf = _short_intf(peer_info[1]) if peer_info else ""

                    from_intf = ""
                    link_subnet = ""
                    for lip, lsub, lname in device_subnets.get(device.id, []):
                        try:
                            if ipaddress.ip_address(neighbor_ip) in ipaddress.ip_network(lsub, strict=False):
                                from_intf = _short_intf(lname)
                                link_subnet = lsub
                                break
                        except ValueError:
                            continue

                    bgp_edges.append({
                        "from": device.id,
                        "to": peer_device_id,
                        "type": "bgp",
                        "health": health,
                        "label": f"eBGP AS{ndata.get('remote_as', '?')}",
                        "session_state": state,
                        "from_intf": from_intf,
                        "to_intf": to_intf,
                        "subnet": link_subnet,
                    })

    # ── Layer 2 segments (ARP/MAC, grouped by subnet) ─────────
    # Build segments: for each subnet, collect the devices that can see
    # each other via ARP on that subnet.  The frontend renders each
    # segment as a hub node with spoke edges to the member devices.

    def _normalise_mac(mac: str) -> str:
        return mac.lower().replace(".", "").replace(":", "").replace("-", "")

    # subnet_str → { device_id: { intf, ip, mac } }
    segment_map: dict[str, dict[str, dict]] = {}

    for device in devices:
        snap = snapshots.get(device.id)
        if not snap or not isinstance(snap.snapshot_data, dict):
            continue
        arp = snap.snapshot_data.get("arp", {})
        if not isinstance(arp, dict):
            continue

        arp_interfaces = arp.get("interfaces", {})
        for intf_name, intf_arp in arp_interfaces.items():
            if not isinstance(intf_arp, dict):
                continue

            # Determine this interface's subnet
            intf_subnet = ""
            for lip, lsub, lname in device_subnets.get(device.id, []):
                if lname == intf_name:
                    intf_subnet = lsub
                    break
            if not intf_subnet or intf_subnet.startswith("192.168.20."):
                continue

            neighbors = intf_arp.get("ipv4", {}).get("neighbors", {})
            if not isinstance(neighbors, dict):
                continue

            # Track which known devices appear on this subnet via ARP
            seen_peers = set()
            for neighbor_ip, ndata in neighbors.items():
                if not isinstance(ndata, dict):
                    continue
                remote_mac = ndata.get("link_layer_address", "")
                if not remote_mac:
                    continue
                norm_mac = _normalise_mac(remote_mac)
                peer = mac_to_device.get(norm_mac)
                if not peer or peer[0] == device.id:
                    continue
                seen_peers.add((peer[0], peer[1], neighbor_ip, remote_mac))

            if not seen_peers:
                continue

            # Add self to segment
            seg = segment_map.setdefault(intf_subnet, {})
            if device.id not in seg:
                # Find own IP on this subnet
                own_ip = ""
                for lip, lsub, lname in device_subnets.get(device.id, []):
                    if lsub == intf_subnet and lname == intf_name:
                        own_ip = lip
                        break
                seg[device.id] = {
                    "device_id": device.id,
                    "intf": _short_intf(intf_name),
                    "ip": own_ip,
                }

            # Add peers to segment
            for peer_dev_id, peer_intf, peer_ip, peer_mac in seen_peers:
                if peer_dev_id not in seg:
                    seg[peer_dev_id] = {
                        "device_id": peer_dev_id,
                        "intf": _short_intf(peer_intf),
                        "ip": peer_ip,
                        "mac": peer_mac,
                    }

    # Convert to list, filtering segments with fewer than 2 members
    l2_segments: list[dict] = []
    for subnet_str, members_dict in segment_map.items():
        if len(members_dict) < 2:
            continue
        l2_segments.append({
            "id": f"seg:{subnet_str}",
            "subnet": subnet_str,
            "members": list(members_dict.values()),
        })

    # ── Nodes ───────────────────────────────────────────────────
    unmonitored_keys = [f"unmonitored:{d.id}" for d in devices]
    unmonitored_map: dict[str, set[str]] = {}
    if unmonitored_keys:
        result = await db.execute(
            select(Setting).where(Setting.key.in_(unmonitored_keys))
        )
        for setting in result.scalars().all():
            dev_id = setting.key.split(":", 1)[1]
            unmonitored_map[dev_id] = set(setting.value.get("interfaces", []))

    nodes = []
    for device in devices:
        snap = snapshots.get(device.id)
        intf_up = 0
        intf_total = 0
        um = unmonitored_map.get(device.id, set())
        if snap and isinstance(snap.snapshot_data, dict):
            interfaces = snap.snapshot_data.get("interface", {})
            if isinstance(interfaces, dict):
                for _name, data in interfaces.items():
                    if isinstance(data, dict):
                        if _name in um:
                            continue
                        intf_total += 1
                        if data.get("oper_status") == "up":
                            intf_up += 1

        has_snapshot = snap is not None and isinstance(snap.snapshot_data, dict) and "error" not in snap.snapshot_data
        node_type = device.device_type or "unknown"

        nodes.append({
            "id": device.id,
            "hostname": device.hostname.split(".")[0],
            "hostname_fqdn": device.hostname,
            "management_ip": device.management_ip,
            "platform": device.platform,
            "device_type": node_type,
            "has_snapshot": has_snapshot,
            "interfaces_up": intf_up,
            "interfaces_total": intf_total,
            "tags": device.tags or {},
        })

    log.info(
        "topology_built",
        nodes=len(nodes),
        bgp_edges=len(bgp_edges),
        l2_segments=len(l2_segments),
    )
    return {
        "nodes": nodes,
        "bgp_edges": bgp_edges,
        "l2_segments": l2_segments,
    }
