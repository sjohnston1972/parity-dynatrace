"""Tool registry for the Parity chat assistant.

Each tool is:
  - a JSON schema describing its name + input shape (sent to Claude)
  - an async handler that executes against the database / device /
    ChromaDB and returns a string (sent back to Claude as a tool_result)

Read-only by design. Tools that change device state (approve, execute,
deny config changes) are intentionally NOT exposed — those operations
go through the explicit Approval UI with full audit trail.

The one quasi-write tool, ``trigger_snapshot``, only enqueues a
snapshot job; it doesn't touch any device's running config.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Awaitable, Callable

import httpx
import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.tables import Approval, Device, Finding, Recommendation, Snapshot

log = structlog.get_logger()

API_INTERNAL = "http://localhost:8000/api/v1"

# Commands we'll forward to a device via pyATS in `run_show_command`.
# Anything else (config, reload, clear, write, copy, ...) is rejected.
_SAFE_CMD_PREFIXES = (
    "show ", "ping ", "traceroute ", "trace ",
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


async def _resolve_device(db: AsyncSession, hostname: str) -> Device | None:
    """Match a device by full hostname OR short name (case-insensitive)."""
    if not hostname:
        return None
    exact = await db.execute(select(Device).where(Device.hostname == hostname))
    dev = exact.scalar_one_or_none()
    if dev:
        return dev
    short = hostname.split(".")[0].lower()
    all_devs = await db.execute(select(Device))
    for d in all_devs.scalars().all():
        if d.hostname.split(".")[0].lower() == short:
            return d
    return None


async def _latest_snapshot_per_device(db: AsyncSession) -> dict[str, Snapshot]:
    latest_sq = (
        select(Snapshot.device_id, func.max(Snapshot.created_at).label("max_ts"))
        .where(func.array_length(Snapshot.features_learned, 1) > 0)
        .group_by(Snapshot.device_id)
        .subquery()
    )
    res = await db.execute(
        select(Snapshot)
        .join(
            latest_sq,
            (Snapshot.device_id == latest_sq.c.device_id)
            & (Snapshot.created_at == latest_sq.c.max_ts),
        )
    )
    return {s.device_id: s for s in res.scalars().all()}


def _summarise_snapshot(snap: Snapshot, hostname: str) -> str:
    """Compact text summary of a pyATS snapshot."""
    if not snap or not isinstance(snap.snapshot_data, dict):
        return f"{hostname}: no snapshot data"
    data = snap.snapshot_data
    parts = [f"{hostname} (snapshot {snap.created_at.isoformat()})"]

    intfs = data.get("interface", {})
    if isinstance(intfs, dict):
        ups = downs = 0
        intf_lines = []
        for name, idata in intfs.items():
            if not isinstance(idata, dict):
                continue
            oper = idata.get("oper_status", "?")
            if oper == "up":
                ups += 1
            else:
                downs += 1
            ipv4 = idata.get("ipv4", {})
            ips = list(ipv4.keys()) if isinstance(ipv4, dict) else []
            counters = idata.get("counters") or {}
            errs = (counters.get("in_errors", 0) or 0) + (counters.get("out_errors", 0) or 0)
            line = f"  {name}: {oper}"
            if ips:
                line += f" [{', '.join(ips)}]"
            if errs:
                line += f" errors={errs}"
            intf_lines.append(line)
        parts.append(f"interfaces: {ups} up / {downs} down / {ups+downs} total")
        parts.extend(intf_lines)

    bgp = data.get("bgp", {})
    if isinstance(bgp, dict):
        nbrs = []
        for inst in bgp.get("instance", {}).values():
            if not isinstance(inst, dict):
                continue
            for vrf in inst.get("vrf", {}).values():
                if not isinstance(vrf, dict):
                    continue
                for nip, ndata in vrf.get("neighbor", {}).items():
                    if not isinstance(ndata, dict):
                        continue
                    nbrs.append(
                        f"  {nip} AS{ndata.get('remote_as', '?')} "
                        f"{ndata.get('session_state', '?')}"
                    )
        if nbrs:
            parts.append(f"bgp neighbours ({len(nbrs)}):")
            parts.extend(nbrs)

    routing = data.get("routing", {})
    if isinstance(routing, dict):
        for vrf_name, vrf in routing.get("vrf", {}).items():
            if not isinstance(vrf, dict):
                continue
            for af_name, af in vrf.get("address_family", {}).items():
                if isinstance(af, dict):
                    routes = af.get("routes", {})
                    parts.append(f"routes ({vrf_name}/{af_name}): {len(routes)}")

    plat = data.get("platform", {})
    if isinstance(plat, dict):
        v = plat.get("version") or plat.get("os") or ""
        ut = plat.get("uptime", "")
        if v or ut:
            parts.append(f"platform: {v} uptime={ut}")

    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────────────
# Tool handlers — each returns a string result
# ──────────────────────────────────────────────────────────────────────


async def t_list_devices(db: AsyncSession, _: dict) -> str:
    res = await db.execute(select(Device).order_by(Device.hostname))
    devs = list(res.scalars().all())
    if not devs:
        return "No devices in inventory."
    lines = [f"{len(devs)} devices:"]
    for d in devs:
        lines.append(f"  {d.hostname.split('.')[0]:14} {d.management_ip:15} {d.platform:10} {d.device_type}")
    return "\n".join(lines)


async def t_get_device_snapshot(db: AsyncSession, args: dict) -> str:
    dev = await _resolve_device(db, args.get("hostname", ""))
    if not dev:
        return f"Device '{args.get('hostname')}' not found. Use list_devices to see available devices."
    snaps = await _latest_snapshot_per_device(db)
    snap = snaps.get(dev.id)
    if not snap:
        return f"{dev.hostname}: no snapshot collected yet. Use trigger_snapshot to collect one."
    return _summarise_snapshot(snap, dev.hostname)


async def t_list_findings(db: AsyncSession, args: dict) -> str:
    severity = args.get("severity")
    category = args.get("category")
    hostname = args.get("device_hostname")
    limit = int(args.get("limit") or 20)

    # Active-only filter
    snaps = await _latest_snapshot_per_device(db)
    latest_ids = {dev_id: s.id for dev_id, s in snaps.items()}

    q = select(Finding).order_by(desc(Finding.created_at))
    if severity:
        q = q.where(Finding.severity == severity)
    if category:
        q = q.where(Finding.category == category)
    if hostname:
        dev = await _resolve_device(db, hostname)
        if dev:
            q = q.where(Finding.device_id == dev.id)
    res = await db.execute(q)
    rows = list(res.scalars().all())
    active = [f for f in rows if latest_ids.get(f.device_id) == f.snapshot_id][:limit]

    if not active:
        return f"No active findings match (severity={severity}, category={category}, device={hostname})."

    # Build hostname lookup
    dev_q = await db.execute(select(Device.id, Device.hostname))
    host_map = {row[0]: row[1].split(".")[0] for row in dev_q.all()}

    lines = [f"{len(active)} active finding(s):"]
    for f in active:
        host = host_map.get(f.device_id, "?")
        lines.append(
            f"  [{f.severity:8}] {host:12} {f.category:10} "
            f"id={f.id[:8]} root={f.is_root_cause} \"{f.title[:80]}\""
        )
    return "\n".join(lines)


async def t_list_incidents(db: AsyncSession, _: dict) -> str:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API_INTERNAL}/findings/incidents/list")
        r.raise_for_status()
        incidents = r.json()
    if not incidents:
        return "No active incidents."
    lines = [f"{len(incidents)} active incident(s):"]
    for inc in incidents:
        kind = "CORRELATED" if inc.get("is_correlated") else "solo"
        sev = inc.get("max_severity", "?")
        n = inc.get("finding_count", 0)
        d = inc.get("affected_device_count", 0)
        title = inc.get("root_cause", {}).get("title", "?")[:80]
        devs = ", ".join(inc.get("affected_devices") or [])
        rec = inc.get("recommendation") or {}
        appr_status = (rec.get("approval") or {}).get("status", "no-approval")
        lines.append(f"  [{sev:8}] {kind:11} {n} findings on {d} devices [{appr_status}]")
        lines.append(f"      root: {title}")
        lines.append(f"      devices: {devs}")
        if rec.get("action"):
            lines.append(f"      proposed fix: {rec['action'][:120]}")
    return "\n".join(lines)


async def t_get_finding(db: AsyncSession, args: dict) -> str:
    fid = args.get("finding_id")
    if not fid:
        return "finding_id required."
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API_INTERNAL}/findings/{fid}")
    if r.status_code == 404:
        return f"Finding {fid} not found."
    r.raise_for_status()
    f = r.json()
    dev = f.get("device") or {}
    parts = [
        f"FINDING {f.get('id')}",
        f"  title:        {f.get('title')}",
        f"  severity:     {f.get('severity')}    confidence: {f.get('confidence')}",
        f"  category:     {f.get('category')}",
        f"  device:       {dev.get('hostname')} ({dev.get('management_ip')})",
        f"  affected:     {f.get('affected_entity')}",
        f"  is_root:      {f.get('is_root_cause')}    incident: {f.get('incident_id')}",
        f"  description:  {f.get('description', '')[:600]}",
    ]
    ev = f.get("evidence") or {}
    if ev:
        parts.append(f"  evidence:     {json.dumps(ev)[:400]}")
    recs = f.get("recommendations") or []
    for r_ in recs:
        appr = r_.get("approval") or {}
        parts.append(
            f"  recommendation: {r_.get('action_description', '')[:200]}\n"
            f"      commands: {r_.get('commands')}\n"
            f"      risk: {r_.get('risk_level')}    approval status: {appr.get('status', 'none')}    jira: {appr.get('jira_issue_key')}"
        )
    linked = f.get("linked_findings") or []
    if linked:
        parts.append(f"  linked findings ({len(linked)}):")
        for lf in linked:
            parts.append(f"    {lf.get('device_hostname')}: {lf.get('title', '')[:80]}")
    return "\n".join(parts)


async def t_list_pending_approvals(db: AsyncSession, _: dict) -> str:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API_INTERNAL}/approvals")
        r.raise_for_status()
        ap = r.json()
    if not ap:
        return "No pending approvals."
    lines = [f"{len(ap)} pending approval(s):"]
    for a in ap:
        f = a.get("finding") or {}
        rec = a.get("recommendation") or {}
        dev = a.get("device") or {}
        lines.append(
            f"  id={a['id'][:8]} jira={a.get('jira_key', 'none')} "
            f"[{f.get('severity', '?'):8}] {dev.get('hostname', '?').split('.')[0]:12} "
            f"\"{f.get('title', '?')[:80]}\""
        )
        cmds = rec.get("commands") or []
        if cmds:
            lines.append(f"      commands: {cmds}")
        if rec.get("reasoning"):
            lines.append(f"      reasoning: {rec['reasoning'][:300]}")
    return "\n".join(lines)


async def t_recent_executions(db: AsyncSession, args: dict) -> str:
    limit = int(args.get("limit") or 10)
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API_INTERNAL}/approvals/history")
        r.raise_for_status()
        history = r.json()
    rows = [a for a in history if a.get("status") in ("executed", "failed", "denied")][:limit]
    if not rows:
        return "No execution history."
    lines = [f"{len(rows)} recent execution(s):"]
    for a in rows:
        f = a.get("finding") or {}
        dev = a.get("device") or {}
        er = a.get("execution_result") or {}
        ok = er.get("success")
        lines.append(
            f"  {a.get('executed_at', '?')[:19]} {a['status']:9} {dev.get('hostname','?').split('.')[0]:12} "
            f"jira={a.get('jira_key','none')} \"{f.get('title','?')[:60]}\""
            + (f" success={ok}" if ok is not None else "")
        )
    return "\n".join(lines)


async def t_get_topology(db: AsyncSession, _: dict) -> str:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API_INTERNAL}/topology")
        r.raise_for_status()
        topo = r.json()
    nodes = topo.get("nodes", [])
    bgp_edges = topo.get("bgp_edges", [])
    l2 = topo.get("l2_segments", [])
    node_map = {n["id"]: n["hostname"] for n in nodes}

    lines = [
        f"Topology: {len(nodes)} devices, {len(bgp_edges)} BGP peering edges, {len(l2)} L2 segments",
        "",
        "BGP edges:",
    ]
    for e in bgp_edges:
        a = node_map.get(e.get("from"), e.get("from", "?")[:8])
        b = node_map.get(e.get("to"), e.get("to", "?")[:8])
        lines.append(
            f"  {a} ({e.get('from_intf', '?')}) <-> {b} ({e.get('to_intf', '?')}) "
            f"AS{e.get('label', '?')} [{e.get('health', '?')}]"
        )
    if l2:
        lines.append("")
        lines.append("L2 segments:")
        for s in l2:
            members = [m.get("device_id") for m in s.get("members", [])]
            host_names = [node_map.get(mid, mid[:8]) for mid in members]
            lines.append(f"  subnet {s.get('subnet')}: {', '.join(host_names)}")
    return "\n".join(lines)


async def t_get_dashboard(db: AsyncSession, _: dict) -> str:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API_INTERNAL}/dashboard/metrics")
        r.raise_for_status()
        m = r.json()
    return (
        f"Dashboard:\n"
        f"  devices: {m['devices'].get('with_snapshots', 0)}/{m['devices'].get('total', 0)} with snapshots\n"
        f"  interfaces: {m['interfaces'].get('up', 0)}/{m['interfaces'].get('total', 0)} up "
        f"({m['interfaces'].get('down', 0)} down)\n"
        f"  bgp sessions: {m['bgp'].get('established', 0)}/{m['bgp'].get('total', 0)} established\n"
        f"  routes: {m['routing'].get('routes', 0)}\n"
        f"  arp entries: {m['routing'].get('arp_entries', 0)}\n"
        f"  vlans: {m['routing'].get('vlans', 0)}\n"
        f"  active findings by severity: {m.get('findings', {})}"
    )


async def t_search_history(db: AsyncSession, args: dict) -> str:
    """Semantic search over historical findings (ChromaDB)."""
    from db.vector import _get_collection  # lazy import

    query = args.get("query", "")
    if not query:
        return "query required."
    limit = int(args.get("limit") or 5)
    try:
        coll = _get_collection()
        if coll.count() == 0:
            return "Vector store is empty — no historical findings to search."
        result = coll.query(query_texts=[query], n_results=limit)
    except Exception as e:
        return f"Vector search failed: {e}"

    if not result or not result.get("ids") or not result["ids"][0]:
        return f"No historical findings match \"{query}\"."

    # Resolve hostnames for the matched findings' device_ids
    dev_q = await db.execute(select(Device.id, Device.hostname))
    host_map = {row[0]: row[1].split(".")[0] for row in dev_q.all()}

    lines = [f"{len(result['ids'][0])} match(es) for \"{query}\":"]
    for i, fid in enumerate(result["ids"][0]):
        meta = result.get("metadatas", [[]])[0][i] if result.get("metadatas") else {}
        dist = result["distances"][0][i] if result.get("distances") else None
        doc = result.get("documents", [[]])[0][i] if result.get("documents") else ""
        host = host_map.get(meta.get("device_id", ""), "?")
        sev = meta.get("severity", "?")
        cat = meta.get("category", "?")
        lines.append(
            f"  finding {fid[:8]} {host:12} [{sev:8}] {cat:10} dist={dist:.3f if dist is not None else '?'}"
        )
        first_line = doc.split("\n", 1)[0]
        lines.append(f"      {first_line[:120]}")
    return "\n".join(lines)


async def t_trigger_snapshot(db: AsyncSession, args: dict) -> str:
    hostname = args.get("hostname")
    body: dict = {}
    if hostname:
        dev = await _resolve_device(db, hostname)
        if not dev:
            return f"Device '{hostname}' not found."
        body["device_id"] = dev.id
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API_INTERNAL}/snapshots", json=body)
    if r.status_code >= 400:
        return f"Snapshot trigger failed: HTTP {r.status_code}"
    target = hostname or "all devices"
    return (
        f"Snapshot triggered for {target}. The pipeline runs in the background "
        f"(typically 3-15 minutes for full network). Use list_findings or "
        f"list_incidents shortly to see results."
    )


async def t_run_show_command(db: AsyncSession, args: dict) -> str:
    hostname = args.get("hostname", "")
    command = (args.get("command") or "").strip()
    if not hostname or not command:
        return "Both hostname and command are required."
    if not any(command.lower().startswith(p) for p in _SAFE_CMD_PREFIXES):
        return (
            f"Refusing to run \"{command}\". Only diagnostic commands "
            f"(show / ping / traceroute) are allowed via chat — config "
            f"changes go through the explicit Approval flow."
        )
    dev = await _resolve_device(db, hostname)
    if not dev:
        return f"Device '{hostname}' not found."

    # Run via pyATS in a thread so we don't block the event loop
    from services.execution_engine import _send_commands_sync
    try:
        result = await asyncio.to_thread(_send_commands_sync, dev, [command])
    except Exception as e:
        return f"Failed to run command on {dev.hostname}: {e}"

    outputs = result.get("outputs") or []
    if not outputs:
        return f"{dev.hostname}: command returned no output."
    o = outputs[0]
    body = o.get("output", "")
    # Cap large outputs so we don't blow Claude's context
    if len(body) > 6000:
        body = body[:6000] + "\n... [truncated]"
    return f"$ {command}\n{body}"


# ──────────────────────────────────────────────────────────────────────
# Tool registry: name → (json schema, handler)
# ──────────────────────────────────────────────────────────────────────


HandlerT = Callable[[AsyncSession, dict], Awaitable[str]]


TOOLS: list[dict] = [
    {
        "name": "list_devices",
        "description": "List every device in inventory with hostname, mgmt IP, platform (iosxe/fortinet), and type (router/switch/firewall). Use this when you need to know what devices exist.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_device_snapshot",
        "description": "Get the latest pyATS snapshot summary for one device — interfaces with state and IPs, BGP/OSPF neighbours and session states, routes per VRF, platform info. Call this when the user asks about a specific device or you need to investigate a finding.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hostname": {
                    "type": "string",
                    "description": "Device hostname, full or short (e.g. 'S1-R1' or 'S1-R1.clydeford.net').",
                }
            },
            "required": ["hostname"],
        },
    },
    {
        "name": "list_findings",
        "description": "List active findings (open issues detected by the AI pipeline). Active = symptom present in the device's latest snapshot. Filter by severity, category, or device. Default limit 20.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                "category": {"type": "string", "enum": ["interface", "routing", "security", "performance"]},
                "device_hostname": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "list_incidents",
        "description": "List active incidents (correlated finding groups). Each incident is one network event observed across one or more devices, with a single root cause and a single recommendation. This is usually more useful than list_findings.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_finding",
        "description": "Get full detail for one finding — device context, evidence, AI reasoning, recommendation commands, approval status, linked findings in the same incident.",
        "input_schema": {
            "type": "object",
            "properties": {"finding_id": {"type": "string"}},
            "required": ["finding_id"],
        },
    },
    {
        "name": "list_pending_approvals",
        "description": "List remediations awaiting human approval — proposed CLI commands, risk level, AI reasoning, Jira ticket key.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "recent_executions",
        "description": "List recent execution history (approvals that were executed, failed, or denied) so the operator can see what's been done lately.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "get_topology",
        "description": "Get the discovered network topology — devices, BGP peering edges (with from/to interfaces and AS), and L2 segments (shared subnets via ARP). Use to understand how devices connect.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_dashboard_metrics",
        "description": "Get the headline dashboard counts — interfaces up/down, BGP sessions, routes, ARP, VLANs, active findings by severity.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_historical_findings",
        "description": "Semantic search over historical findings (active or resolved) in the ChromaDB vector store. Use to answer 'have we seen this before?' or 'find findings about route flapping'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "trigger_snapshot",
        "description": "Trigger a fresh pyATS snapshot of a device (or omit hostname to snapshot all devices). Returns immediately; the pipeline runs in the background. After 3-15 minutes use list_findings/list_incidents to see new results.",
        "input_schema": {
            "type": "object",
            "properties": {"hostname": {"type": "string", "description": "Optional — omit to snapshot all devices"}},
        },
    },
    {
        "name": "run_show_command",
        "description": "Run a diagnostic command on a device via pyATS and return the output. ONLY show, ping, traceroute commands are accepted — config changes are blocked. Use to verify current state when the snapshot is stale.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hostname": {"type": "string"},
                "command": {"type": "string", "description": "Must start with 'show', 'ping', or 'traceroute'."},
            },
            "required": ["hostname", "command"],
        },
    },
]


HANDLERS: dict[str, HandlerT] = {
    "list_devices": t_list_devices,
    "get_device_snapshot": t_get_device_snapshot,
    "list_findings": t_list_findings,
    "list_incidents": t_list_incidents,
    "get_finding": t_get_finding,
    "list_pending_approvals": t_list_pending_approvals,
    "recent_executions": t_recent_executions,
    "get_topology": t_get_topology,
    "get_dashboard_metrics": t_get_dashboard,
    "search_historical_findings": t_search_history,
    "trigger_snapshot": t_trigger_snapshot,
    "run_show_command": t_run_show_command,
}


async def execute_tool(db: AsyncSession, name: str, args: dict) -> str:
    """Run a tool by name. Always returns a string (never raises) so the
    Claude loop can keep going even if a tool errors out."""
    handler = HANDLERS.get(name)
    if not handler:
        return f"Unknown tool: {name}"
    try:
        return await handler(db, args or {})
    except Exception as e:
        log.exception("chat_tool_failed", tool=name, args=args)
        return f"Tool '{name}' failed: {e}"
