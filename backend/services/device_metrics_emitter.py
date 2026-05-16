"""Per-snapshot network device metrics emitter.

Walks the structured pyATS/Genie snapshot dict (``snapshot.snapshot_data``)
and pushes one Davis event per metric data-point through
``DynatraceWriter.emit_self_metric``. Metric naming follows
``parity.net.<feature>.<measure>`` exactly as documented in
``metrics.md`` sections 16-25 (interface, OSPF, BGP, routing, ARP, VLAN,
spanning-tree, HSRP, VRF, platform).

Design constraints:

* **Best-effort** — any exception is caught and logged at debug, never
  surfaced to the caller. Snapshot persistence must succeed even if the
  emitter blows up.
* **Idempotent** — emitting twice on the same snapshot produces the same
  per-metric events. Davis dedupes on payload by default.
* **Paced** — Dynatrace's events ingest has a soft cap; we throttle to
  ~50 events/s using small ``asyncio.sleep`` gaps to keep snapshots of
  large switches from getting rate-limited.
* **Defensive** — Genie output for some features (Platform, Hsrp, Ospf
  on classic IOS) is opaque (no ``.info``) and arrives as a string. The
  walker silently skips any feature whose value isn't a dict.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from integrations.dynatrace import dynatrace_writer

log = structlog.get_logger()


# Pace events to stay under ~50/s.  20 ms between calls = 50/s ceiling.
_PACE_SLEEP_S = 0.02


async def _emit(category: str, **props: Any) -> int:
    """Fire one Davis event; return 1 on attempt (not on confirmed delivery).

    We pace every emission regardless of writer.configured because the
    sleep is cheap and lets the function still serve as a count budget
    for offline / dry-run scenarios.
    """
    try:
        await dynatrace_writer.emit_self_metric(category, **props)
    except Exception as e:  # pragma: no cover — best-effort
        log.debug("device_metric_emit_failed", category=category, error=str(e))
    await asyncio.sleep(_PACE_SLEEP_S)
    return 1


def _as_dict(v: Any) -> dict | None:
    """Return v if it's a non-empty dict, else None.

    Genie objects without ``.info`` get persisted as ``str(object)`` which
    is useless for metric extraction — silently skip those.
    """
    if isinstance(v, dict) and v:
        return v
    return None


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _bool_gauge(v: Any) -> int:
    return 1 if v else 0


# ── Per-feature emitters ──────────────────────────────────────


async def _emit_interface(hostname: str, intf_section: dict) -> int:
    """Emit interface-level gauges & counters.

    Genie interface dict: key = interface name, value = dict with
    enabled, oper_status, mtu, bandwidth, counters{...}, ipv4{...},
    vlan, encapsulation, etc.
    """
    n = 0
    for ifname, attrs in intf_section.items():
        a = _as_dict(attrs)
        if not a:
            continue
        base = {"hostname": hostname, "interface": ifname}

        admin = a.get("enabled")
        if admin is not None:
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.admin_up",
                value=_bool_gauge(admin),
                **base,
            )
        oper = a.get("oper_status")
        if oper is not None:
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.oper_up",
                value=_bool_gauge(str(oper).lower() == "up"),
                oper_status=oper,
                **base,
            )
        if "bandwidth" in a:
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.bandwidth_kbps",
                value=_to_int(a.get("bandwidth")),
                **base,
            )
        if "mtu" in a:
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.mtu",
                value=_to_int(a.get("mtu")),
                **base,
            )
        # Duplex / speed (rare on labs but cheap to emit when present)
        if "duplex_mode" in a:
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.duplex_full",
                value=_bool_gauge(str(a.get("duplex_mode")).lower() == "full"),
                duplex=a.get("duplex_mode"),
                **base,
            )
        if "port_speed" in a:
            # Genie reports things like "auto", "100mbps" — only emit numeric.
            spd = a.get("port_speed")
            try:
                spd_mbps = int("".join(c for c in str(spd) if c.isdigit()) or 0)
            except ValueError:
                spd_mbps = 0
            if spd_mbps:
                n += await _emit(
                    "net-interface",
                    metric_name="parity.net.intf.speed_mbps",
                    value=spd_mbps,
                    **base,
                )
        # Encapsulation as a discrete event property — emit as gauge=1 with prop.
        encap = _as_dict(a.get("encapsulation"))
        if encap and encap.get("encapsulation"):
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.encapsulation",
                value=1,
                encap=encap.get("encapsulation"),
                **base,
            )
        # IP address counts
        ipv4 = _as_dict(a.get("ipv4"))
        if ipv4 is not None:
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.ipv4.addresses",
                value=len(ipv4),
                **base,
            )
        ipv6 = _as_dict(a.get("ipv6"))
        if ipv6 is not None:
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.ipv6.addresses",
                value=len(ipv6),
                **base,
            )
        # VLAN context (switches)
        if "vlan" in a:
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.vlan",
                value=_to_int(a.get("vlan")),
                **base,
            )
        if "trunk_vlans" in a:
            tv = a.get("trunk_vlans")
            try:
                allowed = len(str(tv).split(","))
            except Exception:
                allowed = 0
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.trunk_allowed_count",
                value=allowed,
                **base,
            )
        if "native_vlan" in a:
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.trunk_native_vlan",
                value=_to_int(a.get("native_vlan")),
                **base,
            )
        # Port-channel membership marker
        pc = _as_dict(a.get("port_channel"))
        if pc is not None:
            n += await _emit(
                "net-interface",
                metric_name="parity.net.intf.port_channel.bundled",
                value=_bool_gauge(pc.get("port_channel_member")),
                **base,
            )

        # Counters
        ctrs = _as_dict(a.get("counters"))
        if ctrs:
            counter_map = {
                "in_octets": "parity.net.intf.in_octets",
                "out_octets": "parity.net.intf.out_octets",
                "in_pkts": "parity.net.intf.in_pkts",
                "out_pkts": "parity.net.intf.out_pkts",
                "in_errors": "parity.net.intf.in_errors",
                "out_errors": "parity.net.intf.out_errors",
                "in_discards": "parity.net.intf.in_discards",
                "out_discards": "parity.net.intf.out_discards",
                "in_crc_errors": "parity.net.intf.crc_errors",
                "in_broadcast_pkts": "parity.net.intf.broadcasts_in",
                "in_multicast_pkts": "parity.net.intf.multicasts_in",
                "rx_runts": "parity.net.intf.runts",
                "rx_giants": "parity.net.intf.giants",
                "in_collision_frame": "parity.net.intf.collisions",
            }
            for src_key, metric in counter_map.items():
                if src_key in ctrs:
                    n += await _emit(
                        "net-interface",
                        metric_name=metric,
                        value=_to_int(ctrs.get(src_key)),
                        **base,
                    )
            # Utilization (derived) when both rate + bandwidth are present.
            rate = _as_dict(ctrs.get("rate"))
            bw_kbps = _to_int(a.get("bandwidth"))
            if rate and bw_kbps > 0:
                in_bps = _to_int(rate.get("in_rate"))
                out_bps = _to_int(rate.get("out_rate"))
                # bandwidth is in kbps for Cisco; convert to bps for ratio
                bw_bps = bw_kbps * 1000
                if in_bps:
                    n += await _emit(
                        "net-interface",
                        metric_name="parity.net.intf.in_utilization_pct",
                        value=round((in_bps / bw_bps) * 100, 2),
                        **base,
                    )
                if out_bps:
                    n += await _emit(
                        "net-interface",
                        metric_name="parity.net.intf.out_utilization_pct",
                        value=round((out_bps / bw_bps) * 100, 2),
                        **base,
                    )
    return n


async def _emit_ospf(hostname: str, ospf_section: dict) -> int:
    """Emit OSPF neighbor / area counts.

    Genie OSPF dict shape (approx): {"vrf": {<vrf>: {"address_family":
    {"ipv4": {"instance": {<pid>: {"areas": {<area>:
    {"interfaces": {<intf>: {"neighbors": {<rid>: {"state": "full"}}}}}}}}}}}}.
    Many lab snapshots don't expose this (Genie returns an opaque Ospf
    object without .info) — we silently skip when the structure isn't a
    dict.
    """
    n = 0
    vrfs = _as_dict(ospf_section.get("vrf"))
    if not vrfs:
        return 0
    processes_seen = 0
    for vrf_name, vrf_blob in vrfs.items():
        af = _as_dict(_as_dict(vrf_blob).get("address_family") if _as_dict(vrf_blob) else None)
        if not af:
            continue
        for af_name, af_blob in af.items():
            instances = _as_dict(_as_dict(af_blob).get("instance") if _as_dict(af_blob) else None)
            if not instances:
                continue
            for pid, inst in instances.items():
                inst_d = _as_dict(inst)
                if not inst_d:
                    continue
                processes_seen += 1
                areas = _as_dict(inst_d.get("areas"))
                if not areas:
                    continue
                n += await _emit(
                    "net-ospf",
                    metric_name="parity.net.ospf.areas",
                    value=len(areas),
                    hostname=hostname,
                    process_id=str(pid),
                    vrf=vrf_name,
                )
                for area_name, area_blob in areas.items():
                    a = _as_dict(area_blob)
                    if not a:
                        continue
                    intfs = _as_dict(a.get("interfaces"))
                    neighbors_total = 0
                    neighbors_full = 0
                    if intfs:
                        for ifname, iblob in intfs.items():
                            id = _as_dict(iblob)
                            if not id:
                                continue
                            neighbors = _as_dict(id.get("neighbors"))
                            if not neighbors:
                                continue
                            for rid, nb in neighbors.items():
                                nb_d = _as_dict(nb) or {}
                                state = str(nb_d.get("state", "")).lower()
                                neighbors_total += 1
                                if "full" in state:
                                    neighbors_full += 1
                                n += await _emit(
                                    "net-ospf",
                                    metric_name="parity.net.ospf.neighbors.state",
                                    value=_bool_gauge("full" in state),
                                    hostname=hostname,
                                    peer_router_id=str(rid),
                                    interface=ifname,
                                    state=state or "unknown",
                                    area=str(area_name),
                                    vrf=vrf_name,
                                )
                    n += await _emit(
                        "net-ospf",
                        metric_name="parity.net.ospf.neighbors.total",
                        value=neighbors_total,
                        hostname=hostname,
                        process_id=str(pid),
                        area=str(area_name),
                        vrf=vrf_name,
                    )
                    n += await _emit(
                        "net-ospf",
                        metric_name="parity.net.ospf.neighbors.full",
                        value=neighbors_full,
                        hostname=hostname,
                        area=str(area_name),
                        vrf=vrf_name,
                    )
    if processes_seen:
        n += await _emit(
            "net-ospf",
            metric_name="parity.net.ospf.processes",
            value=processes_seen,
            hostname=hostname,
        )
    return n


async def _emit_bgp(hostname: str, bgp_section: dict) -> int:
    """Emit BGP per-peer state + rollup counters.

    Shape: bgp.instance.<id>.vrf.<vrf>.neighbor.<peer_ip>.session_state
    plus address_family.<afi>.prefixes.total_entries.
    """
    n = 0
    instances = _as_dict(bgp_section.get("instance"))
    if not instances:
        return 0
    for inst_id, inst_blob in instances.items():
        inst_d = _as_dict(inst_blob)
        if not inst_d:
            continue
        local_as = inst_d.get("bgp_id")
        vrfs = _as_dict(inst_d.get("vrf"))
        if not vrfs:
            continue
        for vrf_name, vrf_blob in vrfs.items():
            vrf_d = _as_dict(vrf_blob)
            if not vrf_d:
                continue
            if local_as is not None:
                n += await _emit(
                    "net-bgp",
                    metric_name="parity.net.bgp.local_as",
                    value=_to_int(local_as),
                    hostname=hostname,
                    vrf=vrf_name,
                )
            neighbors = _as_dict(vrf_d.get("neighbor"))
            if not neighbors:
                continue
            total = 0
            established = 0
            af_totals: dict[str, dict[str, int]] = {}
            for peer_ip, nb in neighbors.items():
                nb_d = _as_dict(nb)
                if not nb_d:
                    continue
                total += 1
                state = str(nb_d.get("session_state", "")).lower()
                is_est = state == "established"
                if is_est:
                    established += 1
                base = {
                    "hostname": hostname,
                    "peer_ip": peer_ip,
                    "vrf": vrf_name,
                    "peer_as": str(nb_d.get("remote_as", "")),
                }
                n += await _emit(
                    "net-bgp",
                    metric_name="parity.net.bgp.peer.state",
                    value=_bool_gauge(is_est),
                    state=state or "unknown",
                    **base,
                )
                # Hold/keepalive timers if present
                timers = _as_dict(nb_d.get("bgp_negotiated_keepalive_timers"))
                if timers:
                    if "hold_time" in timers:
                        n += await _emit(
                            "net-bgp",
                            metric_name="parity.net.bgp.peer.holdtime_s",
                            value=_to_int(timers.get("hold_time")),
                            **base,
                        )
                    if "keepalive_interval" in timers:
                        n += await _emit(
                            "net-bgp",
                            metric_name="parity.net.bgp.peer.keepalive_s",
                            value=_to_int(timers.get("keepalive_interval")),
                            **base,
                        )
                # Per-AF prefix counts
                afs = _as_dict(nb_d.get("address_family"))
                if afs:
                    for af_name, af_blob in afs.items():
                        af_d = _as_dict(af_blob)
                        if not af_d:
                            continue
                        prefixes = _as_dict(af_d.get("prefixes"))
                        path = _as_dict(af_d.get("path"))
                        recv = _to_int(prefixes.get("total_entries")) if prefixes else 0
                        sent = _to_int(path.get("total_entries")) if path else 0
                        if prefixes is not None:
                            n += await _emit(
                                "net-bgp",
                                metric_name="parity.net.bgp.peer.prefixes_received",
                                value=recv,
                                afi_safi=af_name,
                                **base,
                            )
                        if path is not None:
                            n += await _emit(
                                "net-bgp",
                                metric_name="parity.net.bgp.peer.prefixes_sent",
                                value=sent,
                                afi_safi=af_name,
                                **base,
                            )
                        bucket = af_totals.setdefault(af_name, {"total": 0, "best": 0})
                        bucket["total"] += recv
                        bucket["best"] += sent
                # Message counters
                msgs = _as_dict(_as_dict(nb_d.get("bgp_neighbor_counters")).get("messages")
                                if _as_dict(nb_d.get("bgp_neighbor_counters")) else None)
                if msgs:
                    sent_msgs = _as_dict(msgs.get("sent")) or {}
                    recv_msgs = _as_dict(msgs.get("received")) or {}
                    total_in = sum(_to_int(v) for v in recv_msgs.values())
                    total_out = sum(_to_int(v) for v in sent_msgs.values())
                    n += await _emit(
                        "net-bgp",
                        metric_name="parity.net.bgp.peer.messages_in",
                        value=total_in,
                        **base,
                    )
                    n += await _emit(
                        "net-bgp",
                        metric_name="parity.net.bgp.peer.messages_out",
                        value=total_out,
                        **base,
                    )
            # Per-vrf rollups
            for af_name, bucket in af_totals.items():
                n += await _emit(
                    "net-bgp",
                    metric_name="parity.net.bgp.rib.prefixes.total",
                    value=bucket["total"],
                    hostname=hostname,
                    vrf=vrf_name,
                    afi_safi=af_name,
                )
                n += await _emit(
                    "net-bgp",
                    metric_name="parity.net.bgp.rib.prefixes.best",
                    value=bucket["best"],
                    hostname=hostname,
                    vrf=vrf_name,
                    afi_safi=af_name,
                )
                n += await _emit(
                    "net-bgp",
                    metric_name="parity.net.bgp.peers.total",
                    value=total,
                    hostname=hostname,
                    vrf=vrf_name,
                    afi_safi=af_name,
                )
                n += await _emit(
                    "net-bgp",
                    metric_name="parity.net.bgp.peers.established",
                    value=established,
                    hostname=hostname,
                    vrf=vrf_name,
                    afi_safi=af_name,
                )
    return n


async def _emit_routing(hostname: str, routing_section: dict) -> int:
    """Per-VRF / per-AF route counts."""
    n = 0
    vrfs = _as_dict(routing_section.get("vrf"))
    if not vrfs:
        return 0
    for vrf_name, vrf_blob in vrfs.items():
        afs = _as_dict(_as_dict(vrf_blob).get("address_family") if _as_dict(vrf_blob) else None)
        if not afs:
            continue
        for af_name, af_blob in afs.items():
            routes = _as_dict(_as_dict(af_blob).get("routes") if _as_dict(af_blob) else None)
            if routes is None:
                continue
            by_proto: dict[str, int] = {}
            next_hops: set[str] = set()
            max_ecmp = 0
            default_present = 0
            for cidr, route_blob in routes.items():
                r = _as_dict(route_blob) or {}
                proto = str(r.get("source_protocol") or "unknown")
                by_proto[proto] = by_proto.get(proto, 0) + 1
                if cidr in ("0.0.0.0/0", "::/0"):
                    default_present = 1
                nh = _as_dict(r.get("next_hop"))
                if nh:
                    nhl = _as_dict(nh.get("next_hop_list"))
                    if nhl:
                        max_ecmp = max(max_ecmp, len(nhl))
                        for entry in nhl.values():
                            ed = _as_dict(entry) or {}
                            if ed.get("next_hop"):
                                next_hops.add(str(ed["next_hop"]))
            n += await _emit(
                "net-routing",
                metric_name="parity.net.routing.routes.total",
                value=len(routes),
                hostname=hostname,
                vrf=vrf_name,
                afi=af_name,
            )
            n += await _emit(
                "net-routing",
                metric_name="parity.net.routing.default_route_present",
                value=default_present,
                hostname=hostname,
                vrf=vrf_name,
                afi=af_name,
            )
            n += await _emit(
                "net-routing",
                metric_name="parity.net.routing.next_hops.total",
                value=len(next_hops),
                hostname=hostname,
                vrf=vrf_name,
                afi=af_name,
            )
            n += await _emit(
                "net-routing",
                metric_name="parity.net.routing.ecmp_paths.max",
                value=max_ecmp,
                hostname=hostname,
                vrf=vrf_name,
                afi=af_name,
            )
            for proto, count in by_proto.items():
                n += await _emit(
                    "net-routing",
                    metric_name="parity.net.routing.routes.by_protocol",
                    value=count,
                    hostname=hostname,
                    vrf=vrf_name,
                    afi=af_name,
                    protocol=proto,
                )
    return n


async def _emit_arp(hostname: str, arp_section: dict) -> int:
    """ARP table sizes per interface / vrf."""
    n = 0
    intfs = _as_dict(arp_section.get("interfaces"))
    if not intfs:
        return 0
    total = 0
    static = 0
    incomplete = 0
    ip_seen: dict[str, set[str]] = {}
    for ifname, iblob in intfs.items():
        id_ = _as_dict(iblob)
        if not id_:
            continue
        ipv4 = _as_dict(id_.get("ipv4"))
        if not ipv4:
            continue
        neighbors = _as_dict(ipv4.get("neighbors"))
        if not neighbors:
            continue
        n += await _emit(
            "net-arp",
            metric_name="parity.net.arp.entries.total",
            value=len(neighbors),
            hostname=hostname,
            interface=ifname,
        )
        for ip, nb in neighbors.items():
            nb_d = _as_dict(nb) or {}
            total += 1
            origin = str(nb_d.get("origin") or "").lower()
            if origin == "static":
                static += 1
            mac = nb_d.get("link_layer_address")
            if mac is None or str(mac).lower() in ("incomplete", "incomp"):
                incomplete += 1
            if mac:
                ip_seen.setdefault(ip, set()).add(str(mac))
    n += await _emit(
        "net-arp",
        metric_name="parity.net.arp.entries.static",
        value=static,
        hostname=hostname,
    )
    n += await _emit(
        "net-arp",
        metric_name="parity.net.arp.entries.incomplete",
        value=incomplete,
        hostname=hostname,
    )
    dup = sum(1 for macs in ip_seen.values() if len(macs) > 1)
    if dup:
        n += await _emit(
            "net-arp",
            metric_name="parity.net.arp.duplicate_ip_detected",
            value=dup,
            hostname=hostname,
        )
    return n


async def _emit_vlan(hostname: str, vlan_section: dict) -> int:
    """VLAN totals (switches only)."""
    n = 0
    vlans = _as_dict(vlan_section.get("vlans"))
    if not vlans:
        return 0
    active = 0
    suspended = 0
    orphaned = 0
    for vid, vblob in vlans.items():
        vd = _as_dict(vblob) or {}
        state = str(vd.get("state") or "").lower()
        if state == "active":
            active += 1
        elif state == "suspended":
            suspended += 1
        ports = vd.get("interfaces") or []
        if isinstance(ports, list) and not ports and state == "active":
            orphaned += 1
        n += await _emit(
            "net-vlan",
            metric_name="parity.net.vlan.ports_assigned",
            value=len(ports) if isinstance(ports, list) else 0,
            hostname=hostname,
            vlan_id=str(vid),
        )
    n += await _emit(
        "net-vlan",
        metric_name="parity.net.vlan.total",
        value=len(vlans),
        hostname=hostname,
    )
    n += await _emit(
        "net-vlan",
        metric_name="parity.net.vlan.active",
        value=active,
        hostname=hostname,
    )
    n += await _emit(
        "net-vlan",
        metric_name="parity.net.vlan.suspended",
        value=suspended,
        hostname=hostname,
    )
    n += await _emit(
        "net-vlan",
        metric_name="parity.net.vlan.spans_orphaned",
        value=orphaned,
        hostname=hostname,
    )
    return n


async def _emit_spanning_tree(hostname: str, stp_section: dict) -> int:
    """STP per-instance state (switches only)."""
    n = 0
    if "error" in stp_section:
        return 0
    mode = stp_section.get("mode") or stp_section.get("global", {}).get("bpdu_mode") if isinstance(stp_section.get("global"), dict) else None
    if mode:
        n += await _emit(
            "net-stp",
            metric_name="parity.net.stp.mode",
            value=1,
            hostname=hostname,
            mode=str(mode),
        )
    # Common shapes: stp_section["pvst"|"rapid_pvst"|"mst"] -> instance -> vlan_id|mst_id
    for mode_key in ("pvst", "rapid_pvst", "mst"):
        mode_blob = _as_dict(stp_section.get(mode_key))
        if not mode_blob:
            continue
        instances_blob = _as_dict(mode_blob.get("mst_instances")) or _as_dict(mode_blob.get("vlans")) or _as_dict(mode_blob.get("instances"))
        if not instances_blob:
            continue
        n += await _emit(
            "net-stp",
            metric_name="parity.net.stp.instances",
            value=len(instances_blob),
            hostname=hostname,
            mode=mode_key,
        )
        for vid, vblob in instances_blob.items():
            vd = _as_dict(vblob) or {}
            interfaces = _as_dict(vd.get("interfaces")) or {}
            forwarding = blocking = alternate = 0
            for _ifname, ifd in interfaces.items():
                ifd_d = _as_dict(ifd) or {}
                st = str(ifd_d.get("port_state") or ifd_d.get("state") or "").lower()
                if "forward" in st:
                    forwarding += 1
                elif "block" in st:
                    blocking += 1
                elif "altern" in st:
                    alternate += 1
            n += await _emit(
                "net-stp",
                metric_name="parity.net.stp.ports.forwarding",
                value=forwarding,
                hostname=hostname,
                vlan_id=str(vid),
            )
            n += await _emit(
                "net-stp",
                metric_name="parity.net.stp.ports.blocking",
                value=blocking,
                hostname=hostname,
                vlan_id=str(vid),
            )
            n += await _emit(
                "net-stp",
                metric_name="parity.net.stp.ports.alternate",
                value=alternate,
                hostname=hostname,
                vlan_id=str(vid),
            )
            tc = vd.get("topology_changes") or vd.get("topo_changes")
            if tc is not None:
                n += await _emit(
                    "net-stp",
                    metric_name="parity.net.stp.topology_changes",
                    value=_to_int(tc),
                    hostname=hostname,
                    vlan_id=str(vid),
                )
            is_root = vd.get("root_of_the_spanning_tree") or vd.get("root_bridge")
            if is_root is not None:
                n += await _emit(
                    "net-stp",
                    metric_name="parity.net.stp.root_for_vlan",
                    value=_bool_gauge(is_root),
                    hostname=hostname,
                    vlan_id=str(vid),
                )
    return n


async def _emit_hsrp(hostname: str, hsrp_section: dict) -> int:
    """HSRP per-group state (routers / L3 switches)."""
    n = 0
    # Genie HSRP commonly nests as hsrp.<interface>.address_family.<af>.version.<v>.groups.<gid>
    intfs = _as_dict(hsrp_section)
    if not intfs:
        return 0
    groups_count = 0
    for ifname, iblob in intfs.items():
        id_ = _as_dict(iblob)
        if not id_:
            continue
        # Walk through the address_family / version / groups maze
        afs = _as_dict(id_.get("address_family"))
        if not afs:
            continue
        for af_name, af_blob in afs.items():
            versions = _as_dict(_as_dict(af_blob).get("version") if _as_dict(af_blob) else None)
            if not versions:
                continue
            for vnum, vblob in versions.items():
                groups = _as_dict(_as_dict(vblob).get("groups") if _as_dict(vblob) else None)
                if not groups:
                    continue
                for gid, gblob in groups.items():
                    gd = _as_dict(gblob) or {}
                    groups_count += 1
                    state = str(gd.get("hsrp_router_state") or gd.get("state") or "").lower()
                    n += await _emit(
                        "net-hsrp",
                        metric_name="parity.net.hsrp.state",
                        value=_bool_gauge(state == "active"),
                        hostname=hostname,
                        group_id=str(gid),
                        interface=ifname,
                        state=state or "unknown",
                    )
                    if "priority" in gd:
                        n += await _emit(
                            "net-hsrp",
                            metric_name="parity.net.hsrp.priority",
                            value=_to_int(gd.get("priority")),
                            hostname=hostname,
                            group_id=str(gid),
                            interface=ifname,
                        )
                    if "preempt" in gd:
                        n += await _emit(
                            "net-hsrp",
                            metric_name="parity.net.hsrp.preempt",
                            value=_bool_gauge(gd.get("preempt")),
                            hostname=hostname,
                            group_id=str(gid),
                            interface=ifname,
                        )
    if groups_count:
        n += await _emit(
            "net-hsrp",
            metric_name="parity.net.hsrp.groups",
            value=groups_count,
            hostname=hostname,
        )
    return n


async def _emit_vrf(hostname: str, vrf_section: dict) -> int:
    """VRF inventory."""
    n = 0
    vrfs = _as_dict(vrf_section.get("vrfs"))
    if not vrfs:
        return 0
    n += await _emit(
        "net-vrf",
        metric_name="parity.net.vrf.total",
        value=len(vrfs),
        hostname=hostname,
    )
    for vrf_name, vblob in vrfs.items():
        vd = _as_dict(vblob) or {}
        afs = _as_dict(vd.get("address_family")) or {}
        n += await _emit(
            "net-vrf",
            metric_name="parity.net.vrf.afi_count",
            value=len(afs),
            hostname=hostname,
            vrf=vrf_name,
        )
        # interfaces_per_vrf — Genie sometimes nests as vd["interfaces"] list
        ifs = vd.get("interfaces")
        if isinstance(ifs, (list, dict)):
            n += await _emit(
                "net-vrf",
                metric_name="parity.net.vrf.interfaces_per_vrf",
                value=len(ifs),
                hostname=hostname,
                vrf=vrf_name,
            )
        rd = vd.get("route_distinguisher") or vd.get("rd")
        if rd:
            n += await _emit(
                "net-vrf",
                metric_name="parity.net.vrf.rd",
                value=1,
                hostname=hostname,
                vrf=vrf_name,
                rd=str(rd),
            )
    return n


async def _emit_platform(hostname: str, platform_section: dict) -> int:
    """Platform / hardware health.

    Genie Platform shapes vary wildly by NOS. We pull the common keys
    and skip anything missing.
    """
    n = 0
    # Common top-level keys: chassis, slot, image, version, hostname,
    # uptime_in_seconds, main_mem, sw_version, config_register
    if "uptime_in_seconds" in platform_section:
        n += await _emit(
            "net-platform",
            metric_name="parity.net.platform.uptime_s",
            value=_to_int(platform_section.get("uptime_in_seconds")),
            hostname=hostname,
        )
    img = platform_section.get("image") or platform_section.get("os")
    ver = platform_section.get("version") or platform_section.get("sw_version") or platform_section.get("os_version")
    if img or ver:
        n += await _emit(
            "net-platform",
            metric_name="parity.net.platform.image",
            value=1,
            hostname=hostname,
            version=str(ver or "unknown"),
            image=str(img or "unknown"),
        )
    if "chassis_sn" in platform_section or "serial_number" in platform_section:
        sn = platform_section.get("chassis_sn") or platform_section.get("serial_number")
        n += await _emit(
            "net-platform",
            metric_name="parity.net.platform.serial",
            value=1,
            hostname=hostname,
            serial=str(sn),
        )
    if "config_register" in platform_section:
        n += await _emit(
            "net-platform",
            metric_name="parity.net.platform.config_register",
            value=1,
            hostname=hostname,
            config_register=str(platform_section.get("config_register")),
        )
    if "last_reload_reason" in platform_section:
        n += await _emit(
            "net-platform",
            metric_name="parity.net.platform.last_reload_reason",
            value=1,
            hostname=hostname,
            reason=str(platform_section.get("last_reload_reason")),
        )
    # CPU / memory totals (Genie 'main_mem' = bytes; iosxe specific)
    if "main_mem" in platform_section:
        n += await _emit(
            "net-platform",
            metric_name="parity.net.platform.memory_used_bytes",
            value=_to_int(platform_section.get("main_mem")),
            hostname=hostname,
            pool="main",
        )
    # Module / PSU / fan rollups (nested under 'slot' or 'chassis')
    slots = _as_dict(platform_section.get("slot"))
    if slots:
        modules_total = modules_ok = 0
        for slot_kind, slot_blob in slots.items():
            sd = _as_dict(slot_blob)
            if not sd:
                continue
            for _name, _entry in sd.items():
                ed = _as_dict(_entry) or {}
                modules_total += 1
                state = str(ed.get("state") or ed.get("operational_state") or "").lower()
                if state in ("ok", "ready", "active"):
                    modules_ok += 1
        if modules_total:
            n += await _emit(
                "net-platform",
                metric_name="parity.net.platform.modules.total",
                value=modules_total,
                hostname=hostname,
            )
            n += await _emit(
                "net-platform",
                metric_name="parity.net.platform.modules.ok",
                value=modules_ok,
                hostname=hostname,
            )
    return n


# ── Dispatch table ────────────────────────────────────────────


_EMITTERS = {
    "interface": _emit_interface,
    "ospf": _emit_ospf,
    "bgp": _emit_bgp,
    "routing": _emit_routing,
    "arp": _emit_arp,
    "vlan": _emit_vlan,
    "spanning_tree": _emit_spanning_tree,
    "hsrp": _emit_hsrp,
    "vrf": _emit_vrf,
    "platform": _emit_platform,
}


async def emit_device_metrics(snapshot_data: dict, hostname: str) -> int:
    """Walk a snapshot and emit one Davis event per metric data-point.

    Returns the total count of metrics attempted (not confirmed delivered).
    Skips any feature whose value isn't a dict — happens when Genie
    returns an opaque object on classic IOS for hsrp/ospf/platform.

    Best-effort: an exception in a single feature handler is logged and
    the remaining features still run.
    """
    if not isinstance(snapshot_data, dict) or not snapshot_data:
        return 0
    start = time.monotonic()
    total = 0
    per_feature: dict[str, int] = {}
    for feature, handler in _EMITTERS.items():
        section = snapshot_data.get(feature)
        section_dict = _as_dict(section)
        if section_dict is None:
            continue
        try:
            count = await handler(hostname, section_dict)
        except Exception as e:
            log.debug(
                "device_metric_feature_failed",
                hostname=hostname,
                feature=feature,
                error=str(e),
            )
            count = 0
        per_feature[feature] = count
        total += count
    log.info(
        "device_metrics_emitted",
        hostname=hostname,
        total=total,
        per_feature=per_feature,
        elapsed_s=round(time.monotonic() - start, 2),
    )
    return total
