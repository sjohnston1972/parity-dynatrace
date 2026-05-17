"""Dashboard metrics endpoint — aggregates live device health from snapshots."""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from db.postgres import get_db
from db.tables import Device, Finding, Setting, Snapshot

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics")
async def dashboard_metrics(db: AsyncSession = Depends(get_db)):
    """Aggregate device health metrics for the overview dashboard.

    Sources data from:
    - Device inventory (from Grafana)
    - Latest *successful* snapshot per device
    - Unmonitored interface settings
    - Recent findings
    """
    # All devices
    result = await db.execute(select(Device).order_by(Device.hostname))
    devices = list(result.scalars().all())

    # Latest successful snapshot per device
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

    # Load unmonitored interface settings
    um_keys = [f"unmonitored:{d.id}" for d in devices]
    unmonitored_map: dict[str, set[str]] = {}
    if um_keys:
        result = await db.execute(select(Setting).where(Setting.key.in_(um_keys)))
        for setting in result.scalars().all():
            dev_id = setting.key.split(":", 1)[1]
            unmonitored_map[dev_id] = set(setting.value.get("interfaces", []))

    # Aggregate metrics
    total_devices = len(devices)
    devices_with_snapshots = 0
    intf_up = 0
    intf_down = 0              # FAULT: admin-up + oper-down
    intf_admin_shut = 0        # operator-shut, intentional
    intf_total = 0
    bgp_established = 0
    bgp_down = 0
    bgp_total = 0
    total_routes = 0
    total_vlans = 0
    total_arp = 0

    device_summaries = []

    for device in devices:
        snap = snapshots.get(device.id)
        um = unmonitored_map.get(device.id, set())
        summary = {
            "id": device.id,
            "hostname": device.hostname,
            "management_ip": device.management_ip,
            "platform": device.platform,
            "device_type": device.device_type,
            "has_snapshot": False,
            "interfaces_up": 0,
            "interfaces_down": 0,            # FAULT: admin-up + oper-down
            "interfaces_admin_shut": 0,      # operator-shut, not a fault
            "interfaces_total": 0,
            "bgp_established": 0,
            "bgp_down": 0,
        }

        if not snap or not isinstance(snap.snapshot_data, dict):
            device_summaries.append(summary)
            continue

        devices_with_snapshots += 1
        summary["has_snapshot"] = True
        data = snap.snapshot_data

        # Interfaces (excluding unmonitored).
        # An interface is a FAULT only when admin=enabled AND
        # oper_status != "up". Admin-shutdown interfaces are
        # intentionally inactive (operator did that on purpose) and
        # were inflating the "down" count by treating them as bugs.
        interfaces = data.get("interface", {})
        if isinstance(interfaces, dict):
            for name, idata in interfaces.items():
                if not isinstance(idata, dict) or name in um:
                    continue
                intf_total += 1
                summary["interfaces_total"] += 1
                admin_up = bool(idata.get("enabled"))
                oper_up = idata.get("oper_status") == "up"
                if oper_up:
                    intf_up += 1
                    summary["interfaces_up"] += 1
                elif not admin_up:
                    # Operator-shut on purpose — not a fault, not "down".
                    intf_admin_shut += 1
                    summary["interfaces_admin_shut"] += 1
                else:
                    intf_down += 1
                    summary["interfaces_down"] += 1

        # BGP
        bgp = data.get("bgp", {})
        if isinstance(bgp, dict):
            for instance in bgp.get("instance", {}).values():
                if not isinstance(instance, dict):
                    continue
                for vrf in instance.get("vrf", {}).values():
                    if not isinstance(vrf, dict):
                        continue
                    for ndata in vrf.get("neighbor", {}).values():
                        if not isinstance(ndata, dict):
                            continue
                        bgp_total += 1
                        state = ndata.get("session_state", "")
                        if state == "Established":
                            bgp_established += 1
                            summary["bgp_established"] += 1
                        else:
                            bgp_down += 1
                            summary["bgp_down"] += 1

        # Routes
        routing = data.get("routing", {})
        if isinstance(routing, dict):
            for vrf in routing.get("vrf", {}).values():
                if not isinstance(vrf, dict):
                    continue
                for af in vrf.get("address_family", {}).values():
                    if not isinstance(af, dict):
                        continue
                    total_routes += len(af.get("routes", {}))

        # VLANs
        vlan = data.get("vlan", {})
        if isinstance(vlan, dict):
            total_vlans += len(vlan.get("vlans", {}))

        # ARP
        arp = data.get("arp", {})
        if isinstance(arp, dict):
            for iface in arp.get("interfaces", {}).values():
                if isinstance(iface, dict):
                    total_arp += len((iface.get("ipv4") or {}).get("neighbors", {}))

        device_summaries.append(summary)

    # Active findings only — same staleness filter as /findings/incidents/list.
    # A finding whose snapshot_id is not the device's latest successful
    # snapshot represents a symptom that was NOT re-detected — i.e. resolved.
    # Counting those would make the Network Health tile lie about a fix the
    # operator already applied.
    latest_sq2 = (
        select(Snapshot.device_id, func.max(Snapshot.created_at).label("max_ts"))
        .where(func.array_length(Snapshot.features_learned, 1) > 0)
        .group_by(Snapshot.device_id)
        .subquery()
    )
    latest_snap_q = await db.execute(
        select(Snapshot.id, Snapshot.device_id)
        .join(
            latest_sq2,
            (Snapshot.device_id == latest_sq2.c.device_id)
            & (Snapshot.created_at == latest_sq2.c.max_ts),
        )
    )
    latest_ids = {row[1]: row[0] for row in latest_snap_q.all()}

    all_findings_q = await db.execute(
        select(Finding.severity, Finding.category, Finding.title,
               Finding.device_id, Finding.snapshot_id, Finding.affected_entity,
               Finding.requires_remediation, Finding.evidence)
        .where(Finding.requires_remediation == True)  # noqa: E712 — SQLAlchemy needs ==
    )
    finding_counts: dict[str, int] = {}
    finding_categories: dict[str, int] = {}
    # Per-tile counts: which finding categories should make which tile
    # show a "needs attention" badge. We don't have explicit "routes
    # affected" or "ARP entries lost" metrics in the snapshot data —
    # they're consequences of routing-category findings. Surface those
    # finding counts on the Routes/ARP tiles so the dashboard reflects
    # the cascade visually, not just on Interfaces/BGP.
    routing_affected = 0
    arp_explicit = 0          # findings that *literally* mention ARP
    interface_affected = 0
    bgp_affected = 0
    for sev, cat, title, dev_id, snap_id, aff, _req, evidence in all_findings_q.all():
        # Skip findings whose snapshot is no longer the device's latest —
        # those are stale (snapshot rotated; the issue may have resolved).
        if dev_id is not None and latest_ids.get(dev_id) != snap_id and snap_id is not None:
            continue
        # Skip explicitly resolved findings even if requires_remediation
        # wasn't flipped (downstream observations get resolved via the
        # evidence.resolved marker rather than requires_remediation).
        if isinstance(evidence, dict) and evidence.get("resolved"):
            continue
        finding_counts[sev] = finding_counts.get(sev, 0) + 1
        cat_l = (cat or "").lower()
        finding_categories[cat_l] = finding_categories.get(cat_l, 0) + 1
        # Build a wide haystack — title, affected entity, evidence keys
        # and values. Dynatrace stub problems carry their fingerprint
        # in evidence.displayName (e.g. BGP_NEIGHBOR_DOWN); the reasoner
        # carries paths like bgp.instance... and routing.vrf... in
        # evidence.diff_paths.
        haystack_parts = [
            (title or ""), (aff or ""), (cat or ""),
        ]
        if isinstance(evidence, dict):
            haystack_parts.append(evidence.get("displayName") or "")
            haystack_parts.append(evidence.get("category") or "")
            paths = evidence.get("diff_paths") or []
            if isinstance(paths, list):
                haystack_parts.extend(str(p) for p in paths[:8])
        haystack = " ".join(haystack_parts).lower()

        is_bgp = (
            cat_l == "bgp-adjacency"
            or "bgp" in cat_l
            or "bgp" in haystack
        )
        is_routing = (
            cat_l in ("routing", "routing-change")
            or "route" in haystack
            or "prefix" in haystack
        )
        is_interface = (
            cat_l in ("interface", "interface-state")
            or "interface_error_storm" in haystack
            or "loopback" in haystack
            or "gigabitethernet" in haystack
            or "interfaces." in haystack
        )
        is_arp = "arp" in haystack
        is_config_drift = cat_l == "config-drift"

        # config-drift inherits the planes it touches via its evidence
        # paths, which already populate is_bgp / is_routing above.

        if is_bgp:
            bgp_affected += 1
            # A BGP issue inherently affects the route table — losing a
            # neighbour wipes every prefix learned from that peer.
            # Bump the Routes tile too unless we're already counting it
            # via is_routing on the same finding.
            if not is_routing:
                routing_affected += 1
        if is_routing:
            routing_affected += 1
        if is_interface:
            interface_affected += 1
        if is_arp:
            arp_explicit += 1
        # A pure config-drift finding without a more specific signal
        # still warrants an interface badge — interface config is the
        # most common kind of drift.
        if is_config_drift and not (is_bgp or is_routing or is_arp or is_interface):
            interface_affected += 1

    # ARP entries live on interfaces; an interface going down or a
    # routing disruption usually wipes ARP entries downstream of the
    # break. Surface a badge if we have either an explicit ARP finding
    # OR any routing/interface finding — the operator should see the
    # ARP plane is being touched, even if the classifier didn't write
    # an ARP-specific finding for it.
    arp_affected = arp_explicit or routing_affected or interface_affected

    return {
        "devices": {
            "total": total_devices,
            "with_snapshots": devices_with_snapshots,
            "without_snapshots": total_devices - devices_with_snapshots,
        },
        "interfaces": {
            "up": intf_up,
            "down": intf_down,            # FAULT: admin-up + oper-down
            "admin_shut": intf_admin_shut, # operator-shut, intentional
            "total": intf_total,
        },
        "bgp": {
            "established": bgp_established,
            "down": bgp_down,
            "total": bgp_total,
            "affected": bgp_affected,
        },
        "routing": {
            "routes": total_routes,
            "vlans": total_vlans,
            "arp_entries": total_arp,
            # Counts of currently-active findings that touch each tile's
            # subject. Frontend uses these to render "N affected" badges
            # on the Routes / ARP tiles, mirroring the existing "N down"
            # badges on the Interfaces / BGP tiles.
            "routes_affected": routing_affected,
            "arp_affected": arp_affected,
            "interface_affected": interface_affected,
        },
        "findings": finding_counts,
        "findings_by_category": finding_categories,
        "device_summaries": device_summaries,
    }
