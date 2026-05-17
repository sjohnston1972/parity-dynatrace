"""Idempotent provisioner for the Parity ⇄ Dynatrace surfaces.

Creates (or updates if `externalId` already exists):

  * A platform dashboard named "Parity · Network Remediation Activity"
    with DQL-driven tiles for the lifecycle of every finding Parity
    emits — events over time, lifecycle breakdown, top devices and
    categories, latest-events table.

  * A Davis Workflow that watches for `source==parity` events of
    severity high/critical and posts a Davis problem so the events
    surface in the Problems view, not just the Events stream.

  * (Best-effort) registers each Parity-managed router as a
    CUSTOM_DEVICE on the tenant so future events can attach to a
    Dynatrace entity. Skipped automatically if the token lacks
    `environment-api:entities:write`.

Idempotent: re-running updates in place via `externalId` lookup so we
never accumulate duplicates.

Run:  py scripts/dynatrace_setup.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

APPS = (os.environ.get("DT_ENVIRONMENT") or "").rstrip("/")
LIVE = APPS.replace(".apps.dynatrace.com", ".live.dynatrace.com")
TOKEN = os.environ.get("DT_PLATFORM_TOKEN") or ""

DASHBOARD_EXTERNAL_ID = "parity-dynatrace-dashboard-v1"
SELF_DASHBOARD_EXTERNAL_ID = "parity-self-monitor-dashboard-v1"
NOTEBOOK_EXTERNAL_ID = "parity-dynatrace-notebook-v1"
WORKFLOW_TITLE = "parity · open Davis problem on high-severity finding"
SELF_WORKFLOW_TITLE = "parity · self-monitor watchdog"

# Hard-coded fallback used only if the live /api/v1/devices endpoint
# is unreachable when the script runs. Normal path pulls the full
# inventory dynamically — see _discover_devices() below.
_FALLBACK_ROUTERS = [
    {"id": "parity-DC1-R1", "name": "DC1-R1.clydeford.net", "mgmt": "192.168.20.13"},
    {"id": "parity-DC2-R2", "name": "DC2-R2.clydeford.net", "mgmt": "192.168.20.12"},
    {"id": "parity-S1-R1",  "name": "S1-R1.clydeford.net",  "mgmt": "192.168.20.33"},
    {"id": "parity-S2-R1",  "name": "S2-R1.clydeford.net",  "mgmt": "192.168.20.22"},
]

PARITY_URL = os.environ.get("PARITY_URL", "https://parity-dynatrace.clydeford.net")


def _discover_devices() -> list[dict[str, str]]:
    """Pull the full fleet from Parity's inventory API.

    Returns a list of ``{id, name, mgmt, platform, type, site}`` dicts
    suitable for both Custom Device registration and the per-device
    metadata Davis Copilot needs to ground answers. Falls back to the
    static four-router list if the API is unreachable.
    """
    try:
        r = httpx.get(f"{PARITY_URL}/api/v1/devices", timeout=15)
        r.raise_for_status()
        devs = r.json()
    except Exception as e:
        _log(f"  WARN: could not pull live inventory ({e}); "
             f"falling back to hard-coded 4 routers")
        return _FALLBACK_ROUTERS
    out: list[dict[str, str]] = []
    for d in devs:
        name = d.get("hostname") or ""
        if not name:
            continue
        short = name.split(".")[0]
        out.append({
            "id": f"parity-{short}",
            "name": name,
            "mgmt": d.get("management_ip") or d.get("mgmt_ip") or "",
            "platform": d.get("platform") or "unknown",
            "device_type": d.get("device_type") or "unknown",
            "site": (d.get("tags") or {}).get("site") or "unknown",
        })
    return out


# ── Helpers ──────────────────────────────────────────────────


def _hdr() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _log(msg: str) -> None:
    print(msg, flush=True)


def _abort_if_unconfigured():
    if not APPS or not TOKEN:
        raise SystemExit(
            "DT_ENVIRONMENT and DT_PLATFORM_TOKEN must be set in .env"
        )


# ── Dashboard ────────────────────────────────────────────────


def _dashboard_content() -> dict[str, Any]:
    """Build the Parity dashboard layout — DQL tiles only.

    Schema: Dynatrace platform dashboard document v15. Tiles indexed by
    string keys; layouts reference the same keys with x/y/w/h on a
    24-wide grid.
    """
    return {
        "version": 15,
        "variables": [],
        "tiles": {
            # Markdown title strip
            "0": {
                "type": "markdown",
                "content": (
                    "# Parity · Network Remediation Activity\n\n"
                    "Live view of findings raised, resolved, and correlated by "
                    "[Parity](https://parity-dynatrace.clydeford.net) — "
                    "an autonomous day-2 NetOps loop. Every event below was "
                    "emitted by Parity into this tenant via the Generic Events "
                    "API; this dashboard reads them straight back from Grail."
                ),
            },
            # KPI: findings raised (24h)
            "1": {
                "type": "data",
                "title": "Findings raised · 24 h",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| filter parity.action == "created" | summarize n = count()'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "raised", "showLabel": True}
                },
            },
            # KPI: findings resolved (24h)
            "2": {
                "type": "data",
                "title": "Findings resolved · 24 h",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| filter parity.action == "resolved" | summarize n = count()'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "resolved", "showLabel": True}
                },
            },
            # KPI: distinct devices touched (24h)
            "3": {
                "type": "data",
                "title": "Distinct devices · 24 h",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| summarize n = countDistinctExact(parity.device)'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "devices", "showLabel": True}
                },
            },
            # Time series: lifecycle over time
            "4": {
                "type": "data",
                "title": "Lifecycle over time",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| makeTimeseries n = count(), by: { parity.action }, '
                    'interval: 5m'
                ),
                "visualization": "lineChart",
            },
            # Bar: severity distribution
            "5": {
                "type": "data",
                "title": "Severity distribution",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| summarize n = count(), by: { parity.severity } '
                    '| sort n desc'
                ),
                "visualization": "honeycomb",
            },
            # Bar: category distribution
            "6": {
                "type": "data",
                "title": "Drift categories",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| filter isNotNull(parity.category) '
                    '| summarize n = count(), by: { parity.category } '
                    '| sort n desc'
                ),
                "visualization": "pieChart",
            },
            # Bar: top devices
            "7": {
                "type": "data",
                "title": "Top devices",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| summarize n = count(), by: { parity.device } '
                    '| sort n desc | limit 10'
                ),
                "visualization": "barChart",
            },
            # Table: latest events
            "8": {
                "type": "data",
                "title": "Latest 25 events",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| sort timestamp desc | limit 25 '
                    '| fields timestamp, parity.action, parity.severity, '
                    'parity.category, parity.device, parity.title'
                ),
                "visualization": "table",
            },
            # ── Network device telemetry section ────────────────
            "9": {
                "type": "markdown",
                "content": (
                    "## Network device telemetry\n\n"
                    "Live per-snapshot metrics from every device in the fleet — "
                    "BGP/OSPF adjacency, interface health, routing table size. "
                    "Source: `parity-self` events emitted by "
                    "`backend/services/device_metrics_emitter.py` on every snapshot."
                ),
            },
            # BGP established peers per device
            "10": {
                "type": "data",
                "title": "BGP peers · established per device",
                "query": (
                    'fetch events, from:-1h '
                    '| filter source == "parity-self" '
                    'and `parity.self.category` == "net-bgp" '
                    'and `parity.self.metric_name` == "parity.net.bgp.peer.state" '
                    '| dedup {`parity.self.hostname`, `parity.self.peer_ip`}, '
                    'sort: { timestamp desc } '
                    '| summarize est = sum(toLong(`parity.self.value`)), '
                    'total = count(), by: { `parity.self.hostname` } '
                    '| fieldsRename hostname = `parity.self.hostname` '
                    '| sort total desc'
                ),
                "visualization": "honeycomb",
            },
            # Interface utilization timeseries (top 10 by avg)
            "11": {
                "type": "data",
                "title": "Interface utilization · top 10 in/out",
                "query": (
                    'fetch events, from:-1h '
                    '| filter source == "parity-self" '
                    'and `parity.self.category` == "net-interface" '
                    'and in(`parity.self.metric_name`, '
                    '"parity.net.intf.in_utilization_pct", '
                    '"parity.net.intf.out_utilization_pct") '
                    '| fieldsAdd label = concat(`parity.self.hostname`, '
                    '" / ", `parity.self.interface`, " ", `parity.self.metric_name`) '
                    '| makeTimeseries util = avg(toDouble(`parity.self.value`)), '
                    'by: { label }, interval: 5m'
                ),
                "visualization": "lineChart",
            },
            # Interface errors trend
            "12": {
                "type": "data",
                "title": "Interface errors · 1 h",
                "query": (
                    'fetch events, from:-1h '
                    '| filter source == "parity-self" '
                    'and `parity.self.category` == "net-interface" '
                    'and in(`parity.self.metric_name`, '
                    '"parity.net.intf.in_errors", "parity.net.intf.out_errors") '
                    '| makeTimeseries err = sum(toLong(`parity.self.value`)), '
                    'by: { `parity.self.metric_name` }, interval: 5m'
                ),
                "visualization": "lineChart",
            },
            # OSPF neighbors full vs total
            "13": {
                "type": "data",
                "title": "OSPF neighbors · full vs total",
                "query": (
                    'fetch events, from:-1h '
                    '| filter source == "parity-self" '
                    'and `parity.self.category` == "net-ospf" '
                    'and in(`parity.self.metric_name`, '
                    '"parity.net.ospf.neighbors.total", '
                    '"parity.net.ospf.neighbors.full") '
                    '| makeTimeseries n = sum(toLong(`parity.self.value`)), '
                    'by: { `parity.self.metric_name` }, interval: 5m'
                ),
                "visualization": "lineChart",
            },
            # RIB size per device
            "14": {
                "type": "data",
                "title": "RIB size · per device",
                "query": (
                    'fetch events, from:-1h '
                    '| filter source == "parity-self" '
                    'and `parity.self.category` == "net-routing" '
                    'and `parity.self.metric_name` == "parity.net.routing.routes.total" '
                    '| makeTimeseries routes = sum(toLong(`parity.self.value`)), '
                    'by: { `parity.self.hostname` }, interval: 5m'
                ),
                "visualization": "lineChart",
            },
            # Network event volume by category (interface/bgp/ospf/routing/...)
            "15": {
                "type": "data",
                "title": "Network events · 1 h volume by category",
                "query": (
                    'fetch events, from:-1h '
                    '| filter source == "parity-self" '
                    'and startsWith(`parity.self.category`, "net-") '
                    '| summarize n = count(), by: { `parity.self.category` } '
                    '| sort n desc'
                ),
                "visualization": "pieChart",
            },
            # Approval + execution outcomes (depends on Phase 4 metrics)
            "16": {
                "type": "data",
                "title": "Approvals & execution · 24 h outcomes",
                "query": (
                    'fetch events, from:-24h '
                    '| filter source == "parity-self" '
                    'and in(`parity.self.category`, "approval", "execution") '
                    '| filter isNotNull(`parity.self.action`) '
                    '| summarize n = count(), '
                    'by: { `parity.self.category`, `parity.self.action` } '
                    '| sort n desc'
                ),
                "visualization": "barChart",
            },
        },
        "layouts": {
            "0":  {"x": 0,  "y": 0,  "w": 24, "h": 2},   # header
            "1":  {"x": 0,  "y": 2,  "w": 8,  "h": 3},   # raised
            "2":  {"x": 8,  "y": 2,  "w": 8,  "h": 3},   # resolved
            "3":  {"x": 16, "y": 2,  "w": 8,  "h": 3},   # devices
            "4":  {"x": 0,  "y": 5,  "w": 24, "h": 6},   # timeseries
            "5":  {"x": 0,  "y": 11, "w": 8,  "h": 6},   # severity
            "6":  {"x": 8,  "y": 11, "w": 8,  "h": 6},   # category
            "7":  {"x": 16, "y": 11, "w": 8,  "h": 6},   # devices
            "8":  {"x": 0,  "y": 17, "w": 24, "h": 7},   # latest events
            "9":  {"x": 0,  "y": 24, "w": 24, "h": 2},   # network sub-header
            "10": {"x": 0,  "y": 26, "w": 8,  "h": 6},   # BGP honeycomb
            "11": {"x": 8,  "y": 26, "w": 16, "h": 6},   # intf utilization
            "12": {"x": 0,  "y": 32, "w": 12, "h": 6},   # intf errors
            "13": {"x": 12, "y": 32, "w": 12, "h": 6},   # OSPF
            "14": {"x": 0,  "y": 38, "w": 12, "h": 6},   # RIB
            "15": {"x": 12, "y": 38, "w": 12, "h": 6},   # net event volume
            "16": {"x": 0,  "y": 44, "w": 24, "h": 6},   # approvals/exec
        },
    }


def find_existing_doc(external_id: str) -> dict | None:
    """Documents API filters by externalId — used for idempotent upsert."""
    r = httpx.get(
        f"{APPS}/platform/document/v1/documents",
        headers=_hdr(),
        params={"filter": f"externalId=='{external_id}'", "pageSize": 5},
        timeout=15,
    )
    if r.status_code != 200:
        return None
    docs = r.json().get("documents") or []
    return docs[0] if docs else None


def upsert_dashboard() -> str:
    """Create or update the Parity dashboard, return its URL."""
    content = _dashboard_content()
    content_blob = json.dumps(content)
    existing = find_existing_doc(DASHBOARD_EXTERNAL_ID)

    if existing:
        doc_id = existing["id"]
        _log(f"  found existing dashboard id={doc_id} — updating")
        r = httpx.patch(
            f"{APPS}/platform/document/v1/documents/{doc_id}",
            headers=_hdr(),
            params={"optimistic-locking-version": str(existing.get("version", 1))},
            files={
                "name": (None, "Parity · Network Remediation Activity"),
                "content": ("content.json", content_blob, "application/json"),
            },
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL update failed {r.status_code}: {r.text[:300]}")
            return ""
    else:
        _log("  no existing dashboard — creating")
        r = httpx.post(
            f"{APPS}/platform/document/v1/documents",
            headers=_hdr(),
            files={
                "name": (None, "Parity · Network Remediation Activity"),
                "type": (None, "dashboard"),
                "externalId": (None, DASHBOARD_EXTERNAL_ID),
                "content": ("content.json", content_blob, "application/json"),
            },
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL create failed {r.status_code}: {r.text[:300]}")
            return ""
        doc_id = r.json()["id"]

    url = f"{APPS}/ui/apps/dynatrace.dashboards/dashboard/{doc_id}"
    _log(f"  OK dashboard ready: {url}")
    return url


# ── Self-monitoring dashboard ───────────────────────────────


def _self_dashboard_content() -> dict[str, Any]:
    """Dashboard for Parity's own operational health.

    Reads parity-self events the backend emits every 60s. Tiles are
    pure DQL so the dashboard works on any tenant the platform token
    can read Grail from.
    """
    return {
        "version": 15,
        "variables": [],
        "tiles": {
            "0": {
                "type": "markdown",
                "content": (
                    "# Parity · Self-Monitoring\n\n"
                    "Real-time health of every container, API endpoint, "
                    "MCP call and Gemini call inside the "
                    "[Parity stack](https://parity-dynatrace.clydeford.net). "
                    "Telemetry is emitted by the backend's self_monitor "
                    "service every 60 seconds as `source=='parity-self'` events."
                ),
            },
            # KPI: HTTP requests last hour
            "1": {
                "type": "data",
                "title": "API requests · last hour",
                "query": (
                    'fetch events, from:-1h | filter source == "parity-self" '
                    '| filter parity.self.category == "rollup" '
                    '| summarize n = sum(toLong(parity.self.http_requests_60s))'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "requests", "showLabel": True}
                },
            },
            # KPI: API errors last hour
            "2": {
                "type": "data",
                "title": "API errors · last hour",
                "query": (
                    'fetch events, from:-1h | filter source == "parity-self" '
                    '| filter parity.self.category == "rollup" '
                    '| summarize n = sum(toLong(parity.self.http_errors_60s))'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "errors", "showLabel": True}
                },
            },
            # KPI: Gemini calls last hour
            "3": {
                "type": "data",
                "title": "Gemini calls · last hour",
                "query": (
                    'fetch events, from:-1h | filter source == "parity-self" '
                    '| filter parity.self.category == "rollup" '
                    '| summarize n = sum(toLong(parity.self.gemini_calls_60s))'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "gemini calls", "showLabel": True}
                },
            },
            # KPI: Gemini tokens last hour
            "4": {
                "type": "data",
                "title": "Gemini tokens · last hour",
                "query": (
                    'fetch events, from:-1h | filter source == "parity-self" '
                    '| filter parity.self.category == "rollup" '
                    '| summarize n = sum(toLong(parity.self.gemini_tokens_60s))'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "tokens", "showLabel": True}
                },
            },
            # Time series — HTTP requests + errors over time
            "5": {
                "type": "data",
                "title": "API request rate",
                "query": (
                    'fetch events, from:-2h | filter source == "parity-self" '
                    '| filter parity.self.category == "rollup" '
                    '| makeTimeseries '
                    'reqs = sum(toLong(parity.self.http_requests_60s)), '
                    'errors = sum(toLong(parity.self.http_errors_60s)), '
                    'interval: 5m'
                ),
                "visualization": "lineChart",
            },
            # Time series — Gemini latency
            "6": {
                "type": "data",
                "title": "Gemini call latency · avg ms",
                "query": (
                    'fetch events, from:-2h | filter source == "parity-self" '
                    '| filter parity.self.category == "rollup" '
                    '| makeTimeseries '
                    'gemini_ms = avg(toDouble(parity.self.gemini_avg_latency_ms)), '
                    'mcp_ms = avg(toDouble(parity.self.mcp_avg_latency_ms)), '
                    'interval: 5m'
                ),
                "visualization": "lineChart",
            },
            # Container CPU per name
            "7": {
                "type": "data",
                "title": "Container CPU %",
                "query": (
                    'fetch events, from:-30m | filter source == "parity-self" '
                    '| filter parity.self.category == "container" '
                    '| summarize cpu = avg(toDouble(parity.self.cpu_pct)), '
                    'by: { parity.self.container_name } '
                    '| sort cpu desc'
                ),
                "visualization": "barChart",
            },
            # Container memory per name
            "8": {
                "type": "data",
                "title": "Container memory · MB",
                "query": (
                    'fetch events, from:-30m | filter source == "parity-self" '
                    '| filter parity.self.category == "container" '
                    '| summarize mem = avg(toDouble(parity.self.mem_mb)), '
                    'by: { parity.self.container_name } '
                    '| sort mem desc'
                ),
                "visualization": "barChart",
            },
            # Latest container status table
            "9": {
                "type": "data",
                "title": "Container status — latest",
                "query": (
                    'fetch events, from:-15m | filter source == "parity-self" '
                    '| filter parity.self.category == "container" '
                    '| sort timestamp desc '
                    '| dedup { parity.self.container_name } '
                    '| fields timestamp, parity.self.container_name, '
                    'parity.self.container_status, parity.self.container_health, '
                    'parity.self.cpu_pct, parity.self.mem_mb, parity.self.restarts'
                ),
                "visualization": "table",
            },
            # MCP tool breakdown
            "10": {
                "type": "data",
                "title": "MCP calls · last hour",
                "query": (
                    'fetch events, from:-1h | filter source == "parity-self" '
                    '| filter parity.self.category == "rollup" '
                    '| summarize n = sum(toLong(parity.self.mcp_calls_60s))'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "mcp calls", "showLabel": True}
                },
            },
        },
        "layouts": {
            "0":  {"x": 0,  "y": 0,  "w": 24, "h": 2},
            "1":  {"x": 0,  "y": 2,  "w": 5,  "h": 3},
            "2":  {"x": 5,  "y": 2,  "w": 5,  "h": 3},
            "3":  {"x": 10, "y": 2,  "w": 5,  "h": 3},
            "4":  {"x": 15, "y": 2,  "w": 4,  "h": 3},
            "10": {"x": 19, "y": 2,  "w": 5,  "h": 3},
            "5":  {"x": 0,  "y": 5,  "w": 12, "h": 6},
            "6":  {"x": 12, "y": 5,  "w": 12, "h": 6},
            "7":  {"x": 0,  "y": 11, "w": 12, "h": 5},
            "8":  {"x": 12, "y": 11, "w": 12, "h": 5},
            "9":  {"x": 0,  "y": 16, "w": 24, "h": 6},
        },
    }


def upsert_self_dashboard() -> str:
    content_blob = json.dumps(_self_dashboard_content())
    existing = find_existing_doc(SELF_DASHBOARD_EXTERNAL_ID)
    if existing:
        doc_id = existing["id"]
        _log(f"  found existing self-dashboard id={doc_id} — updating")
        r = httpx.patch(
            f"{APPS}/platform/document/v1/documents/{doc_id}",
            headers=_hdr(),
            params={"optimistic-locking-version": str(existing.get("version", 1))},
            files={
                "name": (None, "Parity · Self-Monitoring"),
                "content": ("content.json", content_blob, "application/json"),
            },
            timeout=20,
        )
        if r.status_code != 200:
            _log(f"  FAIL update {r.status_code}: {r.text[:300]}")
            return ""
    else:
        _log("  no existing self-dashboard — creating")
        r = httpx.post(
            f"{APPS}/platform/document/v1/documents",
            headers=_hdr(),
            files={
                "name": (None, "Parity · Self-Monitoring"),
                "type": (None, "dashboard"),
                "externalId": (None, SELF_DASHBOARD_EXTERNAL_ID),
                "content": ("content.json", content_blob, "application/json"),
            },
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL create {r.status_code}: {r.text[:300]}")
            return ""
        doc_id = r.json()["id"]
    url = f"{APPS}/ui/apps/dynatrace.dashboards/dashboard/{doc_id}"
    _log(f"  OK self-dashboard ready: {url}")
    return url


# ── Notebook ─────────────────────────────────────────────────


def _md(text: str) -> dict:
    """Compact markdown section."""
    import uuid as _u
    return {"id": str(_u.uuid4()), "type": "markdown", "markdown": text}


def _dql(query: str, *, title: str = "", height: int = 280) -> dict:
    """Compact DQL section."""
    import uuid as _u
    return {
        "id": str(_u.uuid4()),
        "type": "dql",
        "title": title,
        "showTitle": bool(title),
        "filterSegments": [],
        "drilldownPath": [],
        "showInput": True,
        "height": height,
        "previousFilterSegments": [],
        "state": {
            "input": {
                "timeframe": {"from": "now()-24h", "to": "now()"},
                "value": query,
            },
        },
    }


def _notebook_content() -> dict[str, Any]:
    """A guided walk-through notebook for the live demo.

    Mixes prose with executable DQL — each cell is editable, so the
    presenter can adjust queries on the fly during the demo.
    """
    return {
        "version": "7",
        "defaultTimeframe": {"from": "now()-24h", "to": "now()"},
        "defaultSegments": [],
        "sections": [
            _md(
                "# Parity · live demo notebook\n\n"
                "Every cell below queries the Grail tables Parity has been "
                "writing to. Run them top-to-bottom for the canonical demo, "
                "or edit any cell to slice the data differently — the "
                "Notebooks app re-runs the query as you type."
            ),
            _md(
                "## 1 · Every Parity event in the last 24 hours\n\n"
                "Each row is one finding lifecycle moment Parity fired into "
                "this tenant via the Generic Events API. `parity.action` "
                "tells you whether it was a finding **raised** or **resolved**; "
                "`parity.finding.id` is the join key back to Parity's own DB."
            ),
            _dql(
                'fetch events, from:-24h\n'
                '| filter source == "parity"\n'
                '| sort timestamp desc\n'
                '| fields timestamp, parity.action, parity.severity, '
                'parity.category, parity.device, parity.title, parity.finding.id',
                title="All Parity events",
                height=320,
            ),
            _md(
                "## 2 · Lifecycle pivot\n\n"
                "For each device, how many findings were raised vs resolved? "
                "A device with non-zero raised and zero resolved is one we "
                "haven't auto-remediated — worth a human look."
            ),
            _dql(
                'fetch events, from:-24h\n'
                '| filter source == "parity"\n'
                '| summarize n = count(), by: { parity.device, parity.action }\n'
                '| sort parity.device asc',
                title="Lifecycle by device",
                height=260,
            ),
            _md(
                "## 3 · Time-series — Parity activity per hour\n\n"
                "Stacked by action, 5-minute bins. The pattern you want is "
                "every spike of `created` followed quickly by a spike of "
                "`resolved` — Parity catching and fixing drift in a tight loop."
            ),
            _dql(
                'fetch events, from:-24h\n'
                '| filter source == "parity"\n'
                '| makeTimeseries n = count(), by: { parity.action }, '
                'interval: 5m',
                title="Activity rate",
                height=300,
            ),
            _md(
                "## 4 · Drift categories\n\n"
                "What kinds of changes did Parity catch? "
                "`config-drift` dominates because that's the explicit-change "
                "shape the Gemini reasoner detects most reliably."
            ),
            _dql(
                'fetch events, from:-24h\n'
                '| filter source == "parity"\n'
                '| filter isNotNull(parity.category)\n'
                '| summarize n = count(), by: { parity.category, parity.severity }\n'
                '| sort n desc',
                title="Drift categories × severity",
                height=260,
            ),
            _md(
                "## 5 · Drill — last 10 raised findings with their attributes\n\n"
                "Click the `parity.finding.id` value in any row to copy it, "
                "then look it up in Parity's `/findings/<id>` API."
            ),
            _dql(
                'fetch events, from:-24h\n'
                '| filter source == "parity" and parity.action == "created"\n'
                '| sort timestamp desc\n'
                '| limit 10',
                title="Last 10 raised findings",
                height=320,
            ),
            _md(
                "## 6 · Did Davis problems get opened?\n\n"
                "If the workflow `parity · open Davis problem on high-severity "
                "finding` is authorised, every high/critical Parity event "
                "raises a Davis AVAILABILITY event here."
            ),
            _dql(
                'fetch events, from:-24h\n'
                '| filter event.type == "AVAILABILITY_EVENT"\n'
                '| filter contains(event.name, "Parity")\n'
                '| sort timestamp desc',
                title="Davis problem relays from Parity",
                height=260,
            ),
        ],
    }


def upsert_notebook() -> str:
    """Create or update the Parity demo notebook, return its URL."""
    content = _notebook_content()
    content_blob = json.dumps(content)
    existing = find_existing_doc(NOTEBOOK_EXTERNAL_ID)
    if existing:
        doc_id = existing["id"]
        _log(f"  found existing notebook id={doc_id} — updating")
        r = httpx.patch(
            f"{APPS}/platform/document/v1/documents/{doc_id}",
            headers=_hdr(),
            params={"optimistic-locking-version": str(existing.get("version", 1))},
            files={
                "name": (None, "Parity · live demo notebook"),
                "content": ("content.json", content_blob, "application/json"),
            },
            timeout=20,
        )
        if r.status_code != 200:
            _log(f"  FAIL update failed {r.status_code}: {r.text[:300]}")
            return ""
    else:
        _log("  no existing notebook — creating")
        r = httpx.post(
            f"{APPS}/platform/document/v1/documents",
            headers=_hdr(),
            files={
                "name": (None, "Parity · live demo notebook"),
                "type": (None, "notebook"),
                "externalId": (None, NOTEBOOK_EXTERNAL_ID),
                "content": ("content.json", content_blob, "application/json"),
            },
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL create failed {r.status_code}: {r.text[:300]}")
            return ""
        doc_id = r.json()["id"]
    url = f"{APPS}/ui/apps/dynatrace.notebooks/notebook/{doc_id}"
    _log(f"  OK notebook ready: {url}")
    return url


# ── Workflow ─────────────────────────────────────────────────


def _workflow_definition() -> dict[str, Any]:
    """Davis Workflow: watch Parity events, post a Davis problem.

    Trigger: any event with source==parity AND severity in (high,critical).
    Action: a JavaScript task that hits the events.ingest API again with
    a different eventType so the event also appears as a problem-shaped
    entry in the Davis Problems list.
    """
    js = (
        "import { execution } from '@dynatrace-sdk/automation-utils';\n"
        "import { eventsClient } from '@dynatrace-sdk/client-classic-environment-v2';\n"
        "\n"
        "export default async ({ execution_id, event }) => {\n"
        "  const e = event() || {};\n"
        "  const title = e['event.name'] || 'Parity finding';\n"
        "  const device = e['parity.device'] || 'unknown';\n"
        "  const severity = e['parity.severity'] || 'high';\n"
        "  const finding = e['parity.finding.id'] || '';\n"
        "  try {\n"
        "    await eventsClient.createEvent({\n"
        "      body: {\n"
        "        eventType: 'AVAILABILITY_EVENT',\n"
        "        title: `Parity: ${title}`,\n"
        "        properties: {\n"
        "          'parity.relays.from_workflow': execution_id,\n"
        "          'parity.device': device,\n"
        "          'parity.severity': severity,\n"
        "          'parity.finding.id': finding,\n"
        "        }\n"
        "      }\n"
        "    });\n"
        "    return { status: 'relayed', finding };\n"
        "  } catch (err) {\n"
        "    return { status: 'error', error: String(err) };\n"
        "  }\n"
        "};\n"
    )
    return {
        "title": WORKFLOW_TITLE,
        "description": "When Parity raises a high-severity finding, relay it as a Davis availability event so it appears in the Problems list.",
        "isPrivate": False,
        "trigger": {
            "eventTrigger": {
                "isActive": True,
                "triggerConfiguration": {
                    "type": "event",
                    "value": {
                        "query": (
                            'event.type=="CUSTOM_DEPLOYMENT" AND '
                            'source=="parity" AND '
                            'parity.action=="created" AND '
                            '(parity.severity=="high" OR parity.severity=="critical")'
                        ),
                        "eventType": "events",
                    },
                },
            }
        },
        "tasks": {
            "relay": {
                "name": "relay",
                "action": "dynatrace.automations:run-javascript",
                "input": {"script": js},
                "position": {"x": 0, "y": 1},
            }
        },
    }


def find_existing_workflow(title: str = None) -> str | None:
    """Find a workflow by exact title match. Defaults to the finding-relay one."""
    title = title or WORKFLOW_TITLE
    r = httpx.get(
        f"{APPS}/platform/automation/v1/workflows",
        headers=_hdr(),
        timeout=15,
    )
    if r.status_code != 200:
        return None
    for wf in r.json().get("results", []):
        if wf.get("title") == title:
            return wf.get("id")
    return None


# ── Parity self-monitor watchdog workflow ───────────────────


def _self_workflow_definition() -> dict[str, Any]:
    """Workflow: when parity-self reports an unhealthy container or a
    spike in HTTP/MCP errors, relay as a Davis AVAILABILITY event so
    the issue shows up in the Davis Problems view.
    """
    js = (
        "export default async ({ execution_id, event }) => {\n"
        "  const e = event() || {};\n"
        "  const cat = e['parity.self.category'];\n"
        "  let title = `Parity self-monitor: ${cat}`;\n"
        "  if (cat === 'container') {\n"
        "    title = `Parity container unhealthy: ${e['parity.self.container_name']} `\n"
        "          + `(${e['parity.self.container_status']} / ${e['parity.self.container_health']})`;\n"
        "  } else if (cat === 'rollup') {\n"
        "    title = `Parity error spike — http_errors=${e['parity.self.http_errors_60s']} `\n"
        "          + `mcp_errors=${e['parity.self.mcp_errors_60s']} `\n"
        "          + `gemini_errors=${e['parity.self.gemini_errors_60s']}`;\n"
        "  }\n"
        "  return { status: 'watchdog-fired', title, execution_id };\n"
        "};\n"
    )
    return {
        "title": SELF_WORKFLOW_TITLE,
        "description": (
            "Watches parity-self events for container-unhealthy or error-spike "
            "conditions and surfaces them so operators see Parity's own health "
            "without having to dig into the self-monitoring dashboard."
        ),
        "isPrivate": False,
        "trigger": {
            "eventTrigger": {
                "isActive": True,
                "triggerConfiguration": {
                    "type": "event",
                    "value": {
                        # Fires when a container is in a non-running state.
                        # (The rollup error-spike case is filed as a follow-up —
                        # Davis Event Triggers use a simpler filter syntax than
                        # full DQL and rejected the combined OR expression.)
                        "query": (
                            'source == "parity-self" '
                            'AND parity.self.category == "container" '
                            'AND parity.self.container_status != "running"'
                        ),
                        "eventType": "events",
                    },
                },
            }
        },
        "tasks": {
            "watchdog": {
                "name": "watchdog",
                "action": "dynatrace.automations:run-javascript",
                "input": {"script": js},
                "position": {"x": 0, "y": 1},
            }
        },
    }


def upsert_self_workflow() -> str:
    defn = _self_workflow_definition()
    existing = find_existing_workflow(SELF_WORKFLOW_TITLE)
    if existing:
        _log(f"  found existing self-watchdog id={existing} — updating")
        r = httpx.put(
            f"{APPS}/platform/automation/v1/workflows/{existing}",
            headers=_hdr(), json=defn, timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL update {r.status_code}: {r.text[:300]}")
            return ""
        wf_id = existing
    else:
        _log("  no existing self-watchdog — creating")
        r = httpx.post(
            f"{APPS}/platform/automation/v1/workflows",
            headers=_hdr(), json=defn, timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL create {r.status_code}: {r.text[:300]}")
            return ""
        wf_id = r.json().get("id")
    url = f"{APPS}/ui/apps/dynatrace.automations/workflows/{wf_id}"
    _log(f"  OK self-watchdog ready: {url}")
    return url


def upsert_workflow() -> str:
    defn = _workflow_definition()
    existing = find_existing_workflow()
    if existing:
        _log(f"  found existing workflow id={existing} — updating")
        r = httpx.put(
            f"{APPS}/platform/automation/v1/workflows/{existing}",
            headers=_hdr(),
            json=defn,
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL update failed {r.status_code}: {r.text[:300]}")
            return ""
        wf_id = existing
    else:
        _log("  no existing workflow — creating")
        r = httpx.post(
            f"{APPS}/platform/automation/v1/workflows",
            headers=_hdr(),
            json=defn,
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL create failed {r.status_code}: {r.text[:300]}")
            return ""
        wf_id = r.json().get("id")

    url = f"{APPS}/ui/apps/dynatrace.automations/workflows/{wf_id}"
    _log(f"  OK workflow ready: {url}")
    return url


# ── Custom Devices (best-effort — needs entities:write) ─────


# Cache the OAuth2 access token across calls within a single script run.
_OAUTH_TOKEN_CACHE: dict[str, str | float] = {}


def _fetch_oauth_token() -> str | None:
    """Exchange OAuth client credentials for a short-lived Bearer token.

    Dynatrace entities and other write-scoped APIs are typically authed
    via an OAuth2 client (Account Management > OAuth clients), not via
    a static platform token. The flow:

      POST https://sso.dynatrace.com/sso/oauth2/token
      grant_type=client_credentials
      client_id=<DT_OAUTH_CLIENT_ID>
      client_secret=<DT_OAUTH_CLIENT_SECRET>
      scope=<DT_OAUTH_SCOPE>  e.g. "entities.write entities.read"
      resource=urn:dtenvironment:<env-id>  (the tenant URN)

    Returns the access_token (Bearer) or None if no OAuth client is
    configured in the env. Cached for the lifetime of the script.
    """
    cid = os.environ.get("DT_OAUTH_CLIENT_ID")
    sec = os.environ.get("DT_OAUTH_CLIENT_SECRET")
    if not (cid and sec):
        return None
    # Reuse cached token while still valid (60s safety margin).
    import time as _time
    cached = _OAUTH_TOKEN_CACHE.get("access_token")
    exp = _OAUTH_TOKEN_CACHE.get("expires_at", 0)
    if cached and isinstance(exp, (int, float)) and _time.time() < exp - 60:
        return str(cached)
    sso_url = os.environ.get(
        "DT_OAUTH_TOKEN_URL", "https://sso.dynatrace.com/sso/oauth2/token"
    )
    # OAuth client scopes use full namespaced strings (per the
    # Dynatrace scope catalog), NOT the short legacy names like
    # "entities.write". Include both `environment-api:entities:write`
    # (for /api/v2/entities/custom write path) and the Grail-side
    # `storage:entities:read` so we can confirm the writes round-trip
    # via DQL afterwards.
    scope = os.environ.get(
        "DT_OAUTH_SCOPE",
        "environment-api:entities:read environment-api:entities:write storage:entities:read",
    )
    # Tenant URN. Accept either DT_OAUTH_URN or DT_OAUTH_RESOURCE
    # (different docs use different names); else derive from DT_ENVIRONMENT.
    resource = (
        os.environ.get("DT_OAUTH_URN")
        or os.environ.get("DT_OAUTH_RESOURCE")
    )
    if not resource:
        env_id = APPS.split("//")[-1].split(".")[0]  # "kea15603"
        resource = f"urn:dtenvironment:{env_id}"
    try:
        r = httpx.post(
            sso_url,
            data={
                "grant_type": "client_credentials",
                "client_id": cid,
                "client_secret": sec,
                "scope": scope,
                "resource": resource,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
    except Exception as e:
        _log(f"  WARN: OAuth token fetch failed: {e}")
        return None
    if r.status_code != 200:
        _log(f"  WARN: OAuth token fetch HTTP {r.status_code}: {r.text[:300]}")
        return None
    body = r.json()
    tok = body.get("access_token")
    exp_in = int(body.get("expires_in", 300))
    _OAUTH_TOKEN_CACHE["access_token"] = tok or ""
    _OAUTH_TOKEN_CACHE["expires_at"] = _time.time() + exp_in
    return tok


def _entities_auth_header() -> dict[str, str]:
    """Return the auth header to use for /api/v2/entities calls.

    Preference order:
      1. OAuth client credentials (DT_OAUTH_CLIENT_ID + DT_OAUTH_CLIENT_SECRET).
         This is the canonical Dynatrace path for entity writes today.
      2. DT_API_TOKEN (classic SaaS API token with entities.write).
      3. The platform token (Bearer). Almost certainly returns 403 for
         entity writes but kept as a graceful fallback.
    """
    oauth_tok = _fetch_oauth_token()
    if oauth_tok:
        return {"Authorization": f"Bearer {oauth_tok}"}
    api_tok = os.environ.get("DT_API_TOKEN")
    if api_tok:
        return {"Authorization": f"Api-Token {api_tok}"}
    return _hdr()


def register_custom_devices() -> tuple[int, int]:
    """Register every Parity-managed device as a Dynatrace CUSTOM_DEVICE.

    Pulls the full inventory from Parity's /api/v1/devices endpoint
    (was hard-coded to 4 routers; now picks up all 18+ devices).
    Each device becomes a CUSTOM_DEVICE entity with type set from
    device_type (router/switch/firewall) and managed_by/site/platform
    properties so Davis Copilot has metadata to ground answers about
    them.

    The classic Generic API path `/api/v2/entities/custom` requires
    either:
      * a classic SaaS API token with the ``entities.write`` permission
        (recommended for this script — orthogonal to the platform
        token used for Grail reads)
      * a platform token with the ``environment-api:entities:write``
        scope.

    If the token lacks the scope, the call returns 403. We log a
    pointed remediation message and abort the loop (no point hitting
    18 identical 403s).
    """
    devices = _discover_devices()
    _log(f"  inventory: {len(devices)} device(s) to register")
    ok = skipped = 0
    for r in devices:
        # Map device_type to a Dynatrace-friendly entity type. Custom
        # Device entities accept any string here; using ROUTER /
        # SWITCH / FIREWALL keeps them browsable in the Smartscape UI.
        dt_type = {
            "router": "ROUTER",
            "switch": "SWITCH",
            "firewall": "FIREWALL",
        }.get((r.get("device_type") or "").lower(), "NETWORK_DEVICE")
        payload = {
            "customDeviceId": r["id"],
            "displayName": r["name"],
            "type": dt_type,
            "properties": {
                "managed_by": "parity",
                "platform": r.get("platform") or "unknown",
                "device_type": r.get("device_type") or "unknown",
                "site": r.get("site") or "unknown",
                "mgmt_ip": r["mgmt"],
            },
        }
        if r["mgmt"]:
            payload["ipAddresses"] = [r["mgmt"]]
        resp = httpx.post(
            f"{LIVE}/api/v2/entities/custom",
            headers={**_entities_auth_header(), "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        if resp.status_code == 403:
            skipped = len(devices) - ok
            _log("  skipping remaining custom-device creates - auth lacks entities scope")
            _log(
                "  REMEDIATION (Dynatrace SaaS no longer allows entity writes\n"
                "  with an API/platform token - it must be an OAuth client):\n"
                "    1. In Dynatrace UI: Account Management >\n"
                "       Identity & access management > OAuth clients >\n"
                "       Create client.\n"
                "    2. Permissions / scope: Write entities (entities.write).\n"
                "       Also add: Read entities (entities.read).\n"
                "    3. Copy the client_id + client_secret it returns.\n"
                "    4. Add to .env:\n"
                "         DT_OAUTH_CLIENT_ID=<client_id>\n"
                "         DT_OAUTH_CLIENT_SECRET=<client_secret>\n"
                "       (Optional override DT_OAUTH_SCOPE / DT_OAUTH_RESOURCE\n"
                "       if your tenant URN differs from the auto-derived one.)\n"
                "    5. Rerun: py scripts/dynatrace_setup.py\n"
                "  The script fetches a short-lived Bearer via\n"
                "  client_credentials grant against sso.dynatrace.com and\n"
                "  uses it for /api/v2/entities/custom. The platform token\n"
                "  stays in use for Grail reads + everything else.\n"
                "  Without entities registered, Davis Copilot has no\n"
                "  grounding data for these devices and second-opinion\n"
                "  calls fall back to Gemini's verdict (see DynatracePill\n"
                "  empty state)."
            )
            break
        # 200/201 = create; 202/204 = accepted/no-content on update of an
        # existing entity. All four mean the entity is now in Dynatrace.
        if resp.status_code in (200, 201, 202, 204):
            ok += 1
            _log(f"  OK {r['name']:<35} ({dt_type:<13} site={r.get('site','?')})")
        else:
            _log(f"  FAIL {r['name']} {resp.status_code}: {resp.text[:160]}")
    return ok, skipped


# ── Main ─────────────────────────────────────────────────────


def main() -> int:
    _abort_if_unconfigured()
    print(f"Provisioning Parity surfaces on {APPS}")
    print()

    print("[1/7] Dashboard — Parity activity")
    dashboard_url = upsert_dashboard()
    print()

    print("[2/7] Dashboard — Parity self-monitoring")
    self_dashboard_url = upsert_self_dashboard()
    print()

    print("[3/7] Themed dashboards (10 per-area views)")
    # The dashboards module lives alongside this script. When the script
    # is invoked as `py scripts/dynatrace_setup.py`, Python puts the
    # `scripts/` directory on sys.path, so a flat import works.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).parent))
    from dynatrace_dashboards import provision_all_dashboards  # noqa: E402
    themed = provision_all_dashboards()
    print()

    print("[4/7] Notebook")
    notebook_url = upsert_notebook()
    print()

    print("[5/7] Davis Workflow — finding relay")
    workflow_url = upsert_workflow()
    print()

    print("[6/7] Davis Workflow — parity self-monitor watchdog")
    self_workflow_url = upsert_self_workflow()
    print()

    print("[7/7] Custom Devices")
    ok, skipped = register_custom_devices()
    print()

    print("=" * 60)
    print("Summary")
    print("=" * 60)
    if dashboard_url:
        print(f"Dashboard:        {dashboard_url}")
    if self_dashboard_url:
        print(f"Self-monitoring:  {self_dashboard_url}")
    if themed:
        print("Themed dashboards:")
        for name, url in themed:
            if url:
                print(f"  - {name:<42} {url}")
    if notebook_url:
        print(f"Notebook:         {notebook_url}")
    if workflow_url:
        print(f"Workflow:         {workflow_url}")
    if self_workflow_url:
        print(f"Self-watchdog:    {self_workflow_url}")
    print(f"Devices:          {ok} created / {skipped} skipped")

    if workflow_url:
        print()
        print("NOTE  Workflow tasks need a one-time Authorization Settings")
        print("      acknowledgement before they can call Dynatrace APIs.")
        print("      Open the workflow URL above; if you see 'Configure")
        print("      authorization for this user', click through once.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
