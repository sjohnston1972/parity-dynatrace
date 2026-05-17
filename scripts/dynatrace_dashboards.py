"""Provision ten themed Parity dashboards on the Dynatrace tenant.

The catalog in ``deliverables/metrics.md`` enumerates ~140 self metrics
plus ~140 network-device metric definitions. Building one tile per
metric would produce hundreds of tiles per dashboard — useless.
Instead this module groups the metrics by operator persona:

  1.  Parity API & HTTP          (metrics.md §1)
  2.  Parity MCP & Gemini AI     (§2, §3)
  3.  Parity Pipeline            (§4 snapshots, §6 findings,
                                   §7 incidents, §8 approvals)
  4.  Parity Containers + Process (§5, §14)
  5.  Parity DT Integration self-stats (§11)
  6.  Parity Database + Inventory (§12, §13)
  7.  Network · Interfaces       (§16)
  8.  Network · Routing & BGP & OSPF (§17, §18, §19)
  9.  Network · L2 (ARP/VLAN/STP/HSRP/VRF) (§20-§24)
 10.  Network · Platform & Hardware (§25)

Each dashboard reads the parity-self event stream that
``self_monitor`` and ``device_metrics_emitter`` write every minute /
every snapshot, so they work today with no extra ingest path.

The original ``parity-dynatrace-dashboard-v1`` (Network Remediation
Activity) and ``parity-self-monitor-dashboard-v1`` are unchanged —
they stay as the executive-summary surfaces.

Import + call ``provision_all_dashboards()`` from
``scripts/dynatrace_setup.py::main`` to push the lot.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

APPS = (os.environ.get("DT_ENVIRONMENT") or "").rstrip("/")
TOKEN = os.environ.get("DT_PLATFORM_TOKEN") or ""


def _hdr() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _log(msg: str) -> None:
    print(msg, flush=True)


# ── Tile helpers ─────────────────────────────────────────────


def _kpi(title: str, query: str, label: str) -> dict:
    return {
        "type": "data",
        "title": title,
        "query": query,
        "visualization": "singleValue",
        "visualizationSettings": {
            "singleValue": {"label": label, "showLabel": True}
        },
    }


def _line(title: str, query: str) -> dict:
    return {"type": "data", "title": title, "query": query,
            "visualization": "lineChart"}


def _bar(title: str, query: str) -> dict:
    return {"type": "data", "title": title, "query": query,
            "visualization": "barChart"}


def _pie(title: str, query: str) -> dict:
    return {"type": "data", "title": title, "query": query,
            "visualization": "pieChart"}


def _honey(title: str, query: str) -> dict:
    return {"type": "data", "title": title, "query": query,
            "visualization": "honeycomb"}


def _table(title: str, query: str) -> dict:
    return {"type": "data", "title": title, "query": query,
            "visualization": "table"}


def _md(content: str) -> dict:
    return {"type": "markdown", "content": content}


def _dql_self(metric_name: str, *, lookback: str = "-1h",
              by: str = "`parity.self.hostname`",
              agg: str = "avg") -> str:
    """Common pattern: timeseries of a parity-self metric value."""
    return (
        f'fetch events, from:{lookback} '
        f'| filter source == "parity-self" '
        f'and `parity.self.metric_name` == "{metric_name}" '
        f'| makeTimeseries v = {agg}(toDouble(`parity.self.value`)), '
        f'by: {{ {by} }}, interval: 5m'
    )


def _dql_self_rollup_sum(field: str, *, lookback: str = "-1h") -> str:
    """Sum of a rollup-event field across the window."""
    return (
        f'fetch events, from:{lookback} '
        f'| filter source == "parity-self" '
        f'and `parity.self.category` == "rollup" '
        f'| summarize n = sum(toLong(`parity.self.{field}`))'
    )


# ── 1. Parity API & HTTP ─────────────────────────────────────


def _parity_http_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Parity · API & HTTP\n\n"
            "Inbound HTTP traffic to the Parity backend — request rate, "
            "error rate, latency, and per-path breakdown. Source: "
            "`source==parity-self` events written by the `request_metrics"
            "_middleware` and the 60s rollup loop in "
            "`backend/services/self_monitor.py`."
        ),
        "1": _kpi("Requests · last hour",
                  _dql_self_rollup_sum("http_requests_60s"), "requests"),
        "2": _kpi("5xx errors · last hour",
                  _dql_self_rollup_sum("http_errors_60s"), "errors"),
        "3": _kpi("Avg latency · last hour",
                  'fetch events, from:-1h | filter source == "parity-self" '
                  'and `parity.self.category` == "rollup" '
                  '| summarize ms = avg(toDouble(`parity.self.http_avg_latency_ms`))',
                  "ms"),
        "4": _kpi("Path coverage · last hour",
                  'fetch events, from:-1h | filter source == "parity-self" '
                  'and `parity.self.category` == "http-by-path" '
                  '| summarize p = countDistinctExact(`parity.self.path`)',
                  "paths"),
        "5": _line("Requests / errors trend",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "rollup" '
                   '| makeTimeseries '
                   'requests = sum(toLong(`parity.self.http_requests_60s`)), '
                   'errors = sum(toLong(`parity.self.http_errors_60s`)), '
                   'interval: 5m'),
        "6": _line("Avg / max latency (ms)",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "rollup" '
                   '| makeTimeseries '
                   'avg_ms = avg(toDouble(`parity.self.http_avg_latency_ms`)), '
                   'interval: 5m'),
        "7": _bar("Top 10 paths · 1h request volume",
                  'fetch events, from:-1h | filter source == "parity-self" '
                  'and `parity.self.category` == "http-by-path" '
                  '| summarize n = sum(toLong(`parity.self.value`)), '
                  'by: { `parity.self.path` } | sort n desc | limit 10'),
        "8": _table("Latest 25 backend events",
                    'fetch events, from:-1h | filter source == "parity-self" '
                    'and `parity.self.category` == "rollup" '
                    '| sort timestamp desc | limit 25 '
                    '| fields timestamp, '
                    '`parity.self.http_requests_60s`, '
                    '`parity.self.http_errors_60s`, '
                    '`parity.self.http_avg_latency_ms`'),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 6, "h": 3},
        "2": {"x": 6, "y": 2, "w": 6, "h": 3},
        "3": {"x": 12, "y": 2, "w": 6, "h": 3},
        "4": {"x": 18, "y": 2, "w": 6, "h": 3},
        "5": {"x": 0, "y": 5, "w": 12, "h": 6},
        "6": {"x": 12, "y": 5, "w": 12, "h": 6},
        "7": {"x": 0, "y": 11, "w": 24, "h": 6},
        "8": {"x": 0, "y": 17, "w": 24, "h": 7},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── 2. Parity MCP & Gemini AI ────────────────────────────────


def _parity_ai_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Parity · MCP & Gemini AI\n\n"
            "Activity of the two AI-adjacent layers: MCP tool calls "
            "(every reach into Dynatrace from the backend) and Gemini "
            "calls (every reasoning step). Token spend is the cost line."
        ),
        "1": _kpi("MCP calls · last hour",
                  _dql_self_rollup_sum("mcp_calls_60s"), "mcp calls"),
        "2": _kpi("MCP errors · last hour",
                  _dql_self_rollup_sum("mcp_errors_60s"), "errors"),
        "3": _kpi("Gemini calls · last hour",
                  _dql_self_rollup_sum("gemini_calls_60s"), "gemini calls"),
        "4": _kpi("Gemini tokens · last hour",
                  _dql_self_rollup_sum("gemini_tokens_60s"), "tokens"),
        "5": _line("MCP / Gemini call volume",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "rollup" '
                   '| makeTimeseries '
                   'mcp = sum(toLong(`parity.self.mcp_calls_60s`)), '
                   'gemini = sum(toLong(`parity.self.gemini_calls_60s`)), '
                   'interval: 5m'),
        "6": _line("Avg latency (ms) · MCP vs Gemini",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "rollup" '
                   '| makeTimeseries '
                   'mcp_ms = avg(toDouble(`parity.self.mcp_avg_latency_ms`)), '
                   'gemini_ms = avg(toDouble(`parity.self.gemini_avg_latency_ms`)), '
                   'interval: 5m'),
        "7": _bar("Top MCP tools · 1h call volume",
                  'fetch events, from:-1h | filter source == "parity-self" '
                  'and `parity.self.category` == "mcp-by-tool" '
                  '| summarize n = sum(toLong(`parity.self.value`)), '
                  'by: { `parity.self.tool` } | sort n desc | limit 12'),
        "8": _line("Gemini token spend · trend",
                   'fetch events, from:-24h | filter source == "parity-self" '
                   'and `parity.self.category` == "rollup" '
                   '| makeTimeseries '
                   'tokens = sum(toLong(`parity.self.gemini_tokens_60s`)), '
                   'interval: 15m'),
        "9": _kpi("Error rate · MCP",
                  'fetch events, from:-1h | filter source == "parity-self" '
                  'and `parity.self.category` == "rollup" '
                  '| summarize '
                  'rate = (sum(toDouble(`parity.self.mcp_errors_60s`)) * 100.0) '
                  '/ if(sum(toDouble(`parity.self.mcp_calls_60s`)) > 0, '
                  'sum(toDouble(`parity.self.mcp_calls_60s`)), 1.0)',
                  "%"),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 5, "h": 3},
        "2": {"x": 5, "y": 2, "w": 5, "h": 3},
        "3": {"x": 10, "y": 2, "w": 5, "h": 3},
        "4": {"x": 15, "y": 2, "w": 5, "h": 3},
        "9": {"x": 20, "y": 2, "w": 4, "h": 3},
        "5": {"x": 0, "y": 5, "w": 12, "h": 6},
        "6": {"x": 12, "y": 5, "w": 12, "h": 6},
        "7": {"x": 0, "y": 11, "w": 12, "h": 7},
        "8": {"x": 12, "y": 11, "w": 12, "h": 7},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── 3. Parity Pipeline (snapshots, findings, incidents, approvals) ──


def _parity_pipeline_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Parity · Pipeline\n\n"
            "End-to-end detect → reason → approve → execute → resolve "
            "lifecycle. Pulls snapshot events, finding events "
            "(CUSTOM_DEPLOYMENT, source=parity), and approval/execution "
            "self-monitor events. The single best place to ask 'is the "
            "Parity loop working right now?'"
        ),
        "1": _kpi("Snapshots · last hour",
                  _dql_self_rollup_sum("snapshots_60s"), "snapshots"),
        "2": _kpi("Findings open (rollup)",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "findings-rollup" '
                  '| dedup {timestamp}, sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`))',
                  "findings"),
        "3": _kpi("Findings raised · 24h",
                  'fetch events, from:-24h | filter source == "parity" '
                  'and parity.action == "created" '
                  '| summarize n = count()',
                  "raised"),
        "4": _kpi("Approvals pending",
                  'fetch events, from:-24h | filter source == "parity-self" '
                  'and `parity.self.category` == "approval" '
                  '| summarize approved = countIf(`parity.self.action` == "approved"), '
                  'queued = countIf(`parity.self.action` == "queued") '
                  '| fieldsAdd pending = queued - approved | fields pending',
                  "pending"),
        "5": _line("Snapshot duration (s) · avg",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "rollup" '
                   '| makeTimeseries '
                   'avg_s = avg(toDouble(`parity.self.snapshot_avg_duration_s`)), '
                   'interval: 5m'),
        "6": _line("Lifecycle moments · 24h",
                   'fetch events, from:-24h | filter source == "parity" '
                   '| makeTimeseries n = count(), by: { parity.action }, '
                   'interval: 30m'),
        "7": _bar("Findings by category · 24h",
                  'fetch events, from:-24h | filter source == "parity" '
                  'and isNotNull(parity.category) '
                  '| summarize n = count(), by: { parity.category } '
                  '| sort n desc'),
        "8": _bar("Approvals & execution outcomes · 24h",
                  'fetch events, from:-24h | filter source == "parity-self" '
                  'and in(`parity.self.category`, "approval", "execution") '
                  '| filter isNotNull(`parity.self.action`) '
                  '| summarize n = count(), '
                  'by: { `parity.self.category`, `parity.self.action` } '
                  '| sort n desc'),
        "9": _table("Latest 25 lifecycle events",
                    'fetch events, from:-24h | filter source == "parity" '
                    '| sort timestamp desc | limit 25 '
                    '| fields timestamp, parity.action, parity.severity, '
                    'parity.category, parity.device, parity.title'),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 6, "h": 3},
        "2": {"x": 6, "y": 2, "w": 6, "h": 3},
        "3": {"x": 12, "y": 2, "w": 6, "h": 3},
        "4": {"x": 18, "y": 2, "w": 6, "h": 3},
        "5": {"x": 0, "y": 5, "w": 12, "h": 6},
        "6": {"x": 12, "y": 5, "w": 12, "h": 6},
        "7": {"x": 0, "y": 11, "w": 12, "h": 6},
        "8": {"x": 12, "y": 11, "w": 12, "h": 6},
        "9": {"x": 0, "y": 17, "w": 24, "h": 7},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── 4. Parity Containers + Process ───────────────────────────


def _parity_containers_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Parity · Containers & Process\n\n"
            "Per-container Docker stats from the backend's "
            "`_collect_container_stats` (one event per parity-* "
            "container per minute) and the Python process self-stats "
            "from `_collect_process_stats`."
        ),
        "1": _kpi("Containers monitored",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "container" '
                  '| dedup {`parity.self.container_name`} '
                  '| summarize n = count()',
                  "containers"),
        "2": _kpi("Backend CPU %",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "process" '
                  '| dedup {timestamp}, sort:{timestamp desc} '
                  '| limit 1 | fields v = toDouble(`parity.self.process_cpu_pct`) '
                  '| summarize v = avg(v)',
                  "%"),
        "3": _kpi("Backend RSS (MB)",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "process" '
                  '| dedup {timestamp}, sort:{timestamp desc} '
                  '| limit 1 | fields v = toDouble(`parity.self.process_rss_mb`) '
                  '| summarize v = avg(v)',
                  "MB"),
        "4": _kpi("Asyncio tasks",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "process" '
                  '| dedup {timestamp}, sort:{timestamp desc} '
                  '| limit 1 | fields v = toLong(`parity.self.process_asyncio_tasks`) '
                  '| summarize v = sum(v)',
                  "tasks"),
        "5": _line("Container CPU % · per container",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "container" '
                   '| makeTimeseries '
                   'cpu = avg(toDouble(`parity.self.cpu_pct`)), '
                   'by: { `parity.self.container_name` }, interval: 5m'),
        "6": _line("Container memory (MB) · per container",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "container" '
                   '| makeTimeseries '
                   'mem = avg(toDouble(`parity.self.mem_mb`)), '
                   'by: { `parity.self.container_name` }, interval: 5m'),
        "7": _line("Backend process · CPU / RSS / threads",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "process" '
                   '| makeTimeseries '
                   'cpu = avg(toDouble(`parity.self.process_cpu_pct`)), '
                   'rss = avg(toDouble(`parity.self.process_rss_mb`)), '
                   'threads = avg(toDouble(`parity.self.process_threads`)), '
                   'interval: 5m'),
        "8": _line("Backend host disk %",
                   'fetch events, from:-24h | filter source == "parity-self" '
                   'and `parity.self.category` == "process" '
                   '| makeTimeseries '
                   'pct = avg(toDouble(`parity.self.disk_pct_used`)), '
                   'interval: 30m'),
        "9": _table("Container status · current",
                    'fetch events, from:-15m | filter source == "parity-self" '
                    'and `parity.self.category` == "container" '
                    '| dedup {`parity.self.container_name`}, '
                    'sort:{timestamp desc} '
                    '| fields `parity.self.container_name`, '
                    '`parity.self.container_status`, '
                    '`parity.self.container_health`, `parity.self.cpu_pct`, '
                    '`parity.self.mem_mb`, `parity.self.restarts`'),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 6, "h": 3},
        "2": {"x": 6, "y": 2, "w": 6, "h": 3},
        "3": {"x": 12, "y": 2, "w": 6, "h": 3},
        "4": {"x": 18, "y": 2, "w": 6, "h": 3},
        "5": {"x": 0, "y": 5, "w": 12, "h": 6},
        "6": {"x": 12, "y": 5, "w": 12, "h": 6},
        "7": {"x": 0, "y": 11, "w": 12, "h": 6},
        "8": {"x": 12, "y": 11, "w": 12, "h": 6},
        "9": {"x": 0, "y": 17, "w": 24, "h": 7},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── 5. Parity DT Integration self-stats ──────────────────────


def _parity_dt_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Parity · Dynatrace Integration\n\n"
            "Round-trip health of the writer pipeline: events sent vs "
            "rejected, capability scopes that are live, and the "
            "delivery latency. The 'is Davis actually receiving our "
            "stuff?' dashboard."
        ),
        "1": _kpi("Events sent · running total",
                  'fetch events, from:-24h | filter source == "parity-self" '
                  'and `parity.self.category` == "process" '
                  '| dedup {timestamp}, sort:{timestamp desc} | limit 1 '
                  '| fields v = toLong(`parity.self.dt_events_sent`) '
                  '| summarize v = sum(v)',
                  "events"),
        "2": _kpi("Events rejected · running total",
                  'fetch events, from:-24h | filter source == "parity-self" '
                  'and `parity.self.category` == "process" '
                  '| dedup {timestamp}, sort:{timestamp desc} | limit 1 '
                  '| fields v = toLong(`parity.self.dt_events_rejected`) '
                  '| summarize v = sum(v)',
                  "rejected"),
        "3": _kpi("DT events ingested · 24h (this stream)",
                  'fetch events, from:-24h '
                  '| filter source in ("parity", "parity-self") '
                  '| summarize n = count()',
                  "events"),
        "4": _kpi("Distinct source streams",
                  'fetch events, from:-24h '
                  '| filter startsWith(source, "parity") '
                  '| summarize n = countDistinctExact(source)',
                  "sources"),
        "5": _line("DT events sent vs rejected · trend",
                   'fetch events, from:-24h | filter source == "parity-self" '
                   'and `parity.self.category` == "process" '
                   '| makeTimeseries '
                   'sent = avg(toLong(`parity.self.dt_events_sent`)), '
                   'rejected = avg(toLong(`parity.self.dt_events_rejected`)), '
                   'interval: 15m'),
        "6": _pie("Event volume · last hour by source",
                  'fetch events, from:-1h '
                  '| filter startsWith(source, "parity") '
                  '| summarize n = count(), by: { source }'),
        "7": _bar("Event volume · last hour by category",
                  'fetch events, from:-1h '
                  '| filter source == "parity-self" '
                  '| summarize n = count(), by: { `parity.self.category` } '
                  '| sort n desc | limit 12'),
        "8": _table("Latest 20 parity-self events",
                    'fetch events, from:-1h '
                    '| filter source == "parity-self" '
                    '| sort timestamp desc | limit 20 '
                    '| fields timestamp, `parity.self.category`, '
                    '`parity.self.metric_name`, `parity.self.value`'),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 6, "h": 3},
        "2": {"x": 6, "y": 2, "w": 6, "h": 3},
        "3": {"x": 12, "y": 2, "w": 6, "h": 3},
        "4": {"x": 18, "y": 2, "w": 6, "h": 3},
        "5": {"x": 0, "y": 5, "w": 12, "h": 6},
        "6": {"x": 12, "y": 5, "w": 12, "h": 6},
        "7": {"x": 0, "y": 11, "w": 12, "h": 6},
        "8": {"x": 12, "y": 11, "w": 12, "h": 6},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── 6. Parity Database + Inventory ───────────────────────────


def _parity_db_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Parity · Database & Inventory\n\n"
            "Backend Postgres pool + Chroma vector store + device "
            "inventory. All metrics from the 'process' rollup category "
            "in `self_monitor.py`."
        ),
        "1": _kpi("Findings · total in DB",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "process" '
                  '| dedup {timestamp}, sort:{timestamp desc} | limit 1 '
                  '| fields v = toLong(`parity.self.findings_total`) '
                  '| summarize v = sum(v)',
                  "rows"),
        "2": _kpi("Incidents · open",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "process" '
                  '| dedup {timestamp}, sort:{timestamp desc} | limit 1 '
                  '| fields v = toLong(`parity.self.incidents_open`) '
                  '| summarize v = sum(v)',
                  "incidents"),
        "3": _kpi("Approvals · pending",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "process" '
                  '| dedup {timestamp}, sort:{timestamp desc} | limit 1 '
                  '| fields v = toLong(`parity.self.approvals_pending`) '
                  '| summarize v = sum(v)',
                  "pending"),
        "4": _kpi("Inventory · devices",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "process" '
                  '| dedup {timestamp}, sort:{timestamp desc} | limit 1 '
                  '| fields v = toLong(`parity.self.inventory_devices_total`) '
                  '| summarize v = sum(v)',
                  "devices"),
        "5": _line("DB pool · checked-out connections",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "process" '
                   '| makeTimeseries '
                   'checked_out = avg(toDouble(`parity.self.db_pool_checked_out`)), '
                   'size = avg(toDouble(`parity.self.db_pool_size`)), '
                   'interval: 5m'),
        "6": _line("Findings · open trend (24h)",
                   'fetch events, from:-24h | filter source == "parity-self" '
                   'and `parity.self.category` == "process" '
                   '| makeTimeseries '
                   'open = avg(toDouble(`parity.self.findings_open`)), '
                   'total = avg(toDouble(`parity.self.findings_total`)), '
                   'interval: 30m'),
        "7": _line("Findings open by severity",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "findings-rollup" '
                   '| makeTimeseries '
                   'critical = avg(toDouble(`parity.self.by_critical`)), '
                   'high = avg(toDouble(`parity.self.by_high`)), '
                   'medium = avg(toDouble(`parity.self.by_medium`)), '
                   'low = avg(toDouble(`parity.self.by_low`)), '
                   'interval: 15m'),
        "8": _line("Inventory device count · trend",
                   'fetch events, from:-24h | filter source == "parity-self" '
                   'and `parity.self.category` == "process" '
                   '| makeTimeseries '
                   'devices = avg(toDouble(`parity.self.inventory_devices_total`)), '
                   'interval: 30m'),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 6, "h": 3},
        "2": {"x": 6, "y": 2, "w": 6, "h": 3},
        "3": {"x": 12, "y": 2, "w": 6, "h": 3},
        "4": {"x": 18, "y": 2, "w": 6, "h": 3},
        "5": {"x": 0, "y": 5, "w": 12, "h": 6},
        "6": {"x": 12, "y": 5, "w": 12, "h": 6},
        "7": {"x": 0, "y": 11, "w": 12, "h": 6},
        "8": {"x": 12, "y": 11, "w": 12, "h": 6},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── 7. Network · Interfaces ──────────────────────────────────


def _net_interfaces_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Network · Interfaces\n\n"
            "Per-snapshot interface state across the fleet (16 access "
            "switches + 2 DC routers + 4 site routers + firewall). "
            "Source: `parity-self` events from "
            "`device_metrics_emitter._emit_interface`."
        ),
        "1": _kpi("Interfaces oper-up · current",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.intf.oper_up" '
                  '| dedup {`parity.self.hostname`, `parity.self.interface`}, '
                  'sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`))',
                  "interfaces"),
        # FAULT signal: admin-up but oper-down. A pure oper-down count
        # also captures interfaces the operator deliberately shut, which
        # are not failures. This joins admin_up + oper_up per interface
        # and only counts the cases where admin says "should be up" AND
        # oper says "actually down".
        "2": _kpi("Interfaces DOWN (admin-up + oper-down)",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and in(`parity.self.metric_name`, '
                  '"parity.net.intf.admin_up", "parity.net.intf.oper_up") '
                  '| dedup {`parity.self.hostname`, `parity.self.interface`, '
                  '`parity.self.metric_name`}, sort:{timestamp desc} '
                  '| summarize v = max(toLong(`parity.self.value`)), '
                  'by: {`parity.self.hostname`, `parity.self.interface`, '
                  '`parity.self.metric_name`} '
                  '| fieldsAdd metric = `parity.self.metric_name` '
                  '| summarize admin = sumIf(v, metric == "parity.net.intf.admin_up"), '
                  'oper = sumIf(v, metric == "parity.net.intf.oper_up"), '
                  'by: {`parity.self.hostname`, `parity.self.interface`} '
                  '| filter admin == 1 and oper == 0 '
                  '| summarize n = count()',
                  "down"),
        "3": _kpi("Interfaces ADMIN-SHUT (intentional)",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.intf.admin_up" '
                  '| dedup {`parity.self.hostname`, `parity.self.interface`}, '
                  'sort:{timestamp desc} '
                  '| filter toLong(`parity.self.value`) == 0 '
                  '| summarize n = count()',
                  "shut"),
        "4": _kpi("Devices reporting",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "net-interface" '
                  '| summarize n = countDistinctExact(`parity.self.hostname`)',
                  "devices"),
        "5": _line("Interface utilization (% in/out) · top 12",
                   'fetch events, from:-1h | filter source == "parity-self" '
                   'and in(`parity.self.metric_name`, '
                   '"parity.net.intf.in_utilization_pct", '
                   '"parity.net.intf.out_utilization_pct") '
                   '| fieldsAdd '
                   'label = concat(`parity.self.hostname`, " / ", '
                   '`parity.self.interface`, " ", `parity.self.metric_name`) '
                   '| makeTimeseries '
                   'util = avg(toDouble(`parity.self.value`)), '
                   'by: { label }, interval: 5m'),
        "6": _line("Interface errors (in + out) · trend",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and in(`parity.self.metric_name`, '
                   '"parity.net.intf.in_errors", '
                   '"parity.net.intf.out_errors") '
                   '| makeTimeseries '
                   'err = sum(toLong(`parity.self.value`)), '
                   'by: { `parity.self.metric_name` }, interval: 15m'),
        "7": _bar("Interfaces per device · count",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.intf.oper_up" '
                  '| dedup {`parity.self.hostname`, `parity.self.interface`}, '
                  'sort:{timestamp desc} '
                  '| summarize n = count(), '
                  'by: { `parity.self.hostname` } | sort n desc'),
        # Only show FAULT-state interfaces (operator wants up but they're
        # down). Excludes admin-down which are intentionally inactive.
        "8": _table("Interfaces currently DOWN as a fault (admin-up + oper-down)",
                    'fetch events, from:-15m | filter source == "parity-self" '
                    'and in(`parity.self.metric_name`, '
                    '"parity.net.intf.admin_up", "parity.net.intf.oper_up") '
                    '| dedup {`parity.self.hostname`, `parity.self.interface`, '
                    '`parity.self.metric_name`}, sort:{timestamp desc} '
                    '| summarize v = max(toLong(`parity.self.value`)), '
                    'by: {`parity.self.hostname`, `parity.self.interface`, '
                    '`parity.self.metric_name`} '
                    '| fieldsAdd metric = `parity.self.metric_name` '
                    '| summarize '
                    'admin = sumIf(v, metric == "parity.net.intf.admin_up"), '
                    'oper = sumIf(v, metric == "parity.net.intf.oper_up"), '
                    'by: {`parity.self.hostname`, `parity.self.interface`} '
                    '| filter admin == 1 and oper == 0 '
                    '| fields `parity.self.hostname`, `parity.self.interface` '
                    '| sort `parity.self.hostname` asc'),
        "9": _bar("Top 10 interfaces by errors",
                  'fetch events, from:-1h | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.intf.in_errors" '
                  '| dedup {`parity.self.hostname`, `parity.self.interface`}, '
                  'sort:{timestamp desc} '
                  '| fieldsAdd '
                  'label = concat(`parity.self.hostname`, "/", `parity.self.interface`) '
                  '| summarize errs = max(toLong(`parity.self.value`)), '
                  'by: { label } | sort errs desc | limit 10'),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 6, "h": 3},
        "2": {"x": 6, "y": 2, "w": 6, "h": 3},
        "3": {"x": 12, "y": 2, "w": 6, "h": 3},
        "4": {"x": 18, "y": 2, "w": 6, "h": 3},
        "5": {"x": 0, "y": 5, "w": 24, "h": 6},
        "6": {"x": 0, "y": 11, "w": 12, "h": 6},
        "7": {"x": 12, "y": 11, "w": 12, "h": 6},
        "8": {"x": 0, "y": 17, "w": 12, "h": 7},
        "9": {"x": 12, "y": 17, "w": 12, "h": 7},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── 8. Network · Routing & BGP & OSPF ────────────────────────


def _net_routing_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Network · Routing, BGP & OSPF\n\n"
            "Control-plane truth across the fleet. BGP and OSPF "
            "adjacency state, RIB sizes, prefix counts. Source: "
            "`device_metrics_emitter._emit_bgp / _emit_ospf / "
            "_emit_routing`."
        ),
        "1": _kpi("BGP peers Established",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.bgp.peer.state" '
                  '| dedup {`parity.self.hostname`, `parity.self.peer_ip`}, '
                  'sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`))',
                  "peers"),
        "2": _kpi("BGP peers NOT Established",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.bgp.peer.state" '
                  '| dedup {`parity.self.hostname`, `parity.self.peer_ip`}, '
                  'sort:{timestamp desc} '
                  '| filter toLong(`parity.self.value`) == 0 '
                  '| summarize n = count()',
                  "peers"),
        "3": _kpi("OSPF neighbors FULL",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.ospf.neighbors.full" '
                  '| dedup {`parity.self.hostname`, `parity.self.area`}, '
                  'sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`))',
                  "neighbors"),
        "4": _kpi("RIB · total routes (sum)",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.routing.routes.total" '
                  '| dedup {`parity.self.hostname`, `parity.self.vrf`, '
                  '`parity.self.afi`}, sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`))',
                  "routes"),
        "5": _line("RIB size · per device trend",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.metric_name` == "parity.net.routing.routes.total" '
                   '| makeTimeseries '
                   'routes = sum(toLong(`parity.self.value`)), '
                   'by: { `parity.self.hostname` }, interval: 15m'),
        "6": _line("BGP prefixes received · per peer trend",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.metric_name` == "parity.net.bgp.peer.prefixes_received" '
                   '| fieldsAdd '
                   'label = concat(`parity.self.hostname`, " <- ", `parity.self.peer_ip`) '
                   '| makeTimeseries '
                   'pfx = avg(toLong(`parity.self.value`)), '
                   'by: { label }, interval: 15m'),
        "7": _honey("BGP peer state · current",
                    'fetch events, from:-15m | filter source == "parity-self" '
                    'and `parity.self.metric_name` == "parity.net.bgp.peer.state" '
                    '| dedup {`parity.self.hostname`, `parity.self.peer_ip`}, '
                    'sort:{timestamp desc} '
                    '| summarize est = sum(toLong(`parity.self.value`)), '
                    'total = count(), by: { `parity.self.hostname` } '
                    '| sort total desc'),
        "8": _bar("Routes by protocol · 1h",
                  'fetch events, from:-1h | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.routing.routes.by_protocol" '
                  '| dedup {`parity.self.hostname`, `parity.self.protocol`}, '
                  'sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`)), '
                  'by: { `parity.self.protocol` } | sort n desc'),
        "9": _table("BGP peers currently NOT Established",
                    'fetch events, from:-15m | filter source == "parity-self" '
                    'and `parity.self.metric_name` == "parity.net.bgp.peer.state" '
                    '| dedup {`parity.self.hostname`, `parity.self.peer_ip`}, '
                    'sort:{timestamp desc} '
                    '| filter toLong(`parity.self.value`) == 0 '
                    '| fields `parity.self.hostname`, `parity.self.peer_ip`, '
                    '`parity.self.peer_as`, `parity.self.state`'),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 6, "h": 3},
        "2": {"x": 6, "y": 2, "w": 6, "h": 3},
        "3": {"x": 12, "y": 2, "w": 6, "h": 3},
        "4": {"x": 18, "y": 2, "w": 6, "h": 3},
        "5": {"x": 0, "y": 5, "w": 12, "h": 6},
        "6": {"x": 12, "y": 5, "w": 12, "h": 6},
        "7": {"x": 0, "y": 11, "w": 8, "h": 6},
        "8": {"x": 8, "y": 11, "w": 16, "h": 6},
        "9": {"x": 0, "y": 17, "w": 24, "h": 7},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── 9. Network · L2 (ARP/VLAN/STP/HSRP/VRF) ──────────────────


def _net_l2_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Network · L2 (ARP / VLAN / STP / HSRP / VRF)\n\n"
            "Layer-2 + edge protocol health. ARP table sizes, VLAN "
            "states, spanning-tree posture, FHRP active/standby. "
            "Source: `device_metrics_emitter._emit_arp / _emit_vlan / "
            "_emit_spanning_tree / _emit_hsrp / _emit_vrf`."
        ),
        "1": _kpi("ARP entries · sum across fleet",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.arp.entries.total" '
                  '| dedup {`parity.self.hostname`, `parity.self.interface`}, '
                  'sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`))',
                  "entries"),
        "2": _kpi("ARP incomplete · fleet",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.arp.entries.incomplete" '
                  '| dedup {`parity.self.hostname`}, sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`))',
                  "incomplete"),
        "3": _kpi("VLANs active · fleet",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.vlan.active" '
                  '| dedup {`parity.self.hostname`}, sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`))',
                  "vlans"),
        "4": _kpi("HSRP groups · fleet",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.hsrp.groups" '
                  '| dedup {`parity.self.hostname`}, sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`))',
                  "groups"),
        "5": _line("ARP entries · trend per device",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.metric_name` == "parity.net.arp.entries.total" '
                   '| makeTimeseries '
                   'entries = sum(toLong(`parity.self.value`)), '
                   'by: { `parity.self.hostname` }, interval: 15m'),
        "6": _line("STP topology changes · per device",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.metric_name` == "parity.net.stp.topology_changes" '
                   '| makeTimeseries '
                   'tc = max(toLong(`parity.self.value`)), '
                   'by: { `parity.self.hostname` }, interval: 15m'),
        "7": _bar("VLAN counts · per switch",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and in(`parity.self.metric_name`, '
                  '"parity.net.vlan.active", "parity.net.vlan.suspended") '
                  '| dedup {`parity.self.hostname`, `parity.self.metric_name`}, '
                  'sort:{timestamp desc} '
                  '| summarize n = sum(toLong(`parity.self.value`)), '
                  'by: { `parity.self.hostname`, `parity.self.metric_name` } '
                  '| sort n desc'),
        "8": _pie("HSRP groups · by state",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.hsrp.state" '
                  '| dedup {`parity.self.hostname`, `parity.self.interface`, '
                  '`parity.self.group_id`}, sort:{timestamp desc} '
                  '| summarize n = count(), by: { `parity.self.state` }'),
        "9": _table("ARP duplicate IPs (security signal)",
                    'fetch events, from:-1h | filter source == "parity-self" '
                    'and `parity.self.metric_name` == "parity.net.arp.duplicate_ip_detected" '
                    '| filter toLong(`parity.self.value`) > 0 '
                    '| fields timestamp, `parity.self.hostname`, '
                    '`parity.self.value`'),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 6, "h": 3},
        "2": {"x": 6, "y": 2, "w": 6, "h": 3},
        "3": {"x": 12, "y": 2, "w": 6, "h": 3},
        "4": {"x": 18, "y": 2, "w": 6, "h": 3},
        "5": {"x": 0, "y": 5, "w": 12, "h": 6},
        "6": {"x": 12, "y": 5, "w": 12, "h": 6},
        "7": {"x": 0, "y": 11, "w": 12, "h": 6},
        "8": {"x": 12, "y": 11, "w": 12, "h": 6},
        "9": {"x": 0, "y": 17, "w": 24, "h": 6},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── 10. Network · Platform & Hardware ────────────────────────


def _net_platform_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Network · Platform & Hardware\n\n"
            "Device-level health: uptime, IOS version, hardware modules. "
            "Source: `device_metrics_emitter._emit_platform`. CPU/memory/"
            "fan/PSU/temperature metrics are partial today — depends on "
            "what Genie's `platform` learn returns for the device's "
            "IOS-XE version."
        ),
        "1": _kpi("Devices reporting platform · current",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "net-platform" '
                  '| summarize n = countDistinctExact(`parity.self.hostname`)',
                  "devices"),
        "2": _kpi("Min uptime · across fleet (s)",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.platform.uptime_s" '
                  '| dedup {`parity.self.hostname`}, sort:{timestamp desc} '
                  '| summarize v = min(toLong(`parity.self.value`))',
                  "sec"),
        "3": _kpi("Modules OK · sum",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.platform.modules.ok" '
                  '| dedup {`parity.self.hostname`}, sort:{timestamp desc} '
                  '| summarize v = sum(toLong(`parity.self.value`))',
                  "modules"),
        "4": _kpi("Modules total · sum",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.metric_name` == "parity.net.platform.modules.total" '
                  '| dedup {`parity.self.hostname`}, sort:{timestamp desc} '
                  '| summarize v = sum(toLong(`parity.self.value`))',
                  "modules"),
        "5": _line("Device uptime · per device",
                   'fetch events, from:-24h | filter source == "parity-self" '
                   'and `parity.self.metric_name` == "parity.net.platform.uptime_s" '
                   '| makeTimeseries '
                   'uptime = max(toLong(`parity.self.value`)), '
                   'by: { `parity.self.hostname` }, interval: 1h'),
        "6": _table("Device images · IOS version per device",
                    'fetch events, from:-15m | filter source == "parity-self" '
                    'and `parity.self.metric_name` == "parity.net.platform.image" '
                    '| dedup {`parity.self.hostname`}, sort:{timestamp desc} '
                    '| fields `parity.self.hostname`, `parity.self.image`, '
                    '`parity.self.version`'),
        "7": _table("Device serial numbers",
                    'fetch events, from:-15m | filter source == "parity-self" '
                    'and `parity.self.metric_name` == "parity.net.platform.serial" '
                    '| dedup {`parity.self.hostname`}, sort:{timestamp desc} '
                    '| fields `parity.self.hostname`, `parity.self.serial`'),
        "8": _table("Last reload reason · per device",
                    'fetch events, from:-24h | filter source == "parity-self" '
                    'and `parity.self.metric_name` == "parity.net.platform.last_reload_reason" '
                    '| dedup {`parity.self.hostname`}, sort:{timestamp desc} '
                    '| fields `parity.self.hostname`, `parity.self.reason`'),
        "9": _bar("Modules · OK vs total per device",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and in(`parity.self.metric_name`, '
                  '"parity.net.platform.modules.ok", '
                  '"parity.net.platform.modules.total") '
                  '| dedup {`parity.self.hostname`, `parity.self.metric_name`}, '
                  'sort:{timestamp desc} '
                  '| summarize v = max(toLong(`parity.self.value`)), '
                  'by: { `parity.self.hostname`, `parity.self.metric_name` } '
                  '| sort `parity.self.hostname` asc'),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 6, "h": 3},
        "2": {"x": 6, "y": 2, "w": 6, "h": 3},
        "3": {"x": 12, "y": 2, "w": 6, "h": 3},
        "4": {"x": 18, "y": 2, "w": 6, "h": 3},
        "5": {"x": 0, "y": 5, "w": 24, "h": 6},
        "6": {"x": 0, "y": 11, "w": 12, "h": 6},
        "7": {"x": 12, "y": 11, "w": 12, "h": 6},
        "8": {"x": 0, "y": 17, "w": 12, "h": 6},
        "9": {"x": 12, "y": 17, "w": 12, "h": 6},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── 11. Network · SNMP (real-time counters from pysnmp poller) ─


def _net_snmp_dashboard() -> dict[str, Any]:
    tiles = {
        "0": _md(
            "# Network · SNMP (real-time)\n\n"
            "Continuous 60s SNMPv2c polling of all 19 devices via the "
            "in-backend `snmp_poller` service (replacement for the AG-hosted "
            "SNMP Generic extension — see deliverables/snmp_integration.md "
            "for why). Metrics land as native Dynatrace timeseries (not "
            "events), so DQL uses `timeseries <metric>` not `fetch events`. "
            "Dimensions: `device_label`, `device_ip`, `site`, `if_index`, "
            "`if_descr`, `source=dt-snmp`."
        ),
        "1": _kpi(
            "Devices polled · last 5m",
            'timeseries by:{device_label}, n=sum(parity.snmp.if.operStatus), '
            'from:-5m | summarize devices = count()',
            "devices",
        ),
        # IF-MIB convention: 1 = up, 2 = down. Admin-down interfaces
        # (operator-shut) shouldn't count as a fault. The real "fault"
        # signal is adminStatus==1 AND operStatus==2.
        "2": _kpi(
            "Interfaces DOWN as a fault (admin-up + oper-down)",
            'timeseries by:{device_label, if_index}, '
            'admin=max(parity.snmp.if.adminStatus), '
            'oper=max(parity.snmp.if.operStatus), from:-5m '
            '| filter arrayLast(admin) == 1 and arrayLast(oper) == 2 '
            '| summarize n = count()',
            "down",
        ),
        "3": _kpi(
            "Devices with CPU > 50% · last 5m",
            'timeseries by:{device_label}, cpu=avg(parity.snmp.cisco.cpu_5min), '
            'from:-5m | filter arrayAvg(cpu) > 50 | summarize n = count()',
            "devices",
        ),
        "4": _kpi(
            "Total interface errors · last 15m",
            'timeseries err=sum(parity.snmp.if.inErrors)+sum(parity.snmp.if.outErrors), '
            'from:-15m | summarize total = sum(arrayLast(err))',
            "errors",
        ),
        "5": _line(
            "Interface in/out octets · top 10 by total throughput",
            'timeseries by:{device_label, if_descr}, '
            'in_bytes=sum(parity.snmp.if.inOctets), '
            'out_bytes=sum(parity.snmp.if.outOctets), '
            'from:-1h, interval:5m'
        ),
        "6": _line(
            "Device CPU 5-min average · per device",
            'timeseries by:{device_label}, '
            'cpu=avg(parity.snmp.cisco.cpu_5min), from:-1h, interval:5m'
        ),
        "7": _line(
            "Memory used (bytes) · per device",
            'timeseries by:{device_label}, '
            'mem=avg(parity.snmp.cisco.mem_used_bytes), from:-1h, interval:5m'
        ),
        "8": _bar(
            "Interface errors · top 10 by device/interface (1h)",
            'timeseries by:{device_label, if_descr}, '
            'errs=sum(parity.snmp.if.inErrors)+sum(parity.snmp.if.outErrors), '
            'from:-1h | summarize total = sum(arrayLast(errs)), '
            'by:{device_label, if_descr} '
            '| sort total desc | limit 10'
        ),
        "9": _line(
            "Device uptime (sysUptime in TimeTicks) · trend",
            'timeseries by:{device_label}, '
            'up=max(parity.snmp.sysUptime), from:-24h, interval:1h'
        ),
    }
    layouts = {
        "0": {"x": 0, "y": 0, "w": 24, "h": 2},
        "1": {"x": 0, "y": 2, "w": 6, "h": 3},
        "2": {"x": 6, "y": 2, "w": 6, "h": 3},
        "3": {"x": 12, "y": 2, "w": 6, "h": 3},
        "4": {"x": 18, "y": 2, "w": 6, "h": 3},
        "5": {"x": 0, "y": 5, "w": 24, "h": 6},
        "6": {"x": 0, "y": 11, "w": 12, "h": 6},
        "7": {"x": 12, "y": 11, "w": 12, "h": 6},
        "8": {"x": 0, "y": 17, "w": 12, "h": 7},
        "9": {"x": 12, "y": 17, "w": 12, "h": 7},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


# ── Upsert machinery ─────────────────────────────────────────


THEMED_DASHBOARDS: list[tuple[str, str, Any]] = [
    ("parity-themed-http-v1",       "Parity · API & HTTP",              _parity_http_dashboard),
    ("parity-themed-ai-v1",         "Parity · MCP & Gemini AI",         _parity_ai_dashboard),
    ("parity-themed-pipeline-v1",   "Parity · Pipeline",                _parity_pipeline_dashboard),
    ("parity-themed-containers-v1", "Parity · Containers & Process",    _parity_containers_dashboard),
    ("parity-themed-dt-v1",         "Parity · Dynatrace Integration",   _parity_dt_dashboard),
    ("parity-themed-db-v1",         "Parity · Database & Inventory",    _parity_db_dashboard),
    ("parity-net-interfaces-v1",    "Network · Interfaces",             _net_interfaces_dashboard),
    ("parity-net-routing-v1",       "Network · Routing, BGP, OSPF",     _net_routing_dashboard),
    ("parity-net-l2-v1",            "Network · L2 (ARP/VLAN/STP/HSRP)", _net_l2_dashboard),
    ("parity-net-platform-v1",      "Network · Platform & Hardware",    _net_platform_dashboard),
    ("parity-net-snmp-v1",          "Network · SNMP (real-time)",       _net_snmp_dashboard),
]


def _find_existing_doc(external_id: str) -> dict | None:
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


def _upsert(external_id: str, name: str, builder) -> str:
    """Idempotent dashboard upsert; returns the dashboard URL or ''."""
    content_blob = json.dumps(builder())
    existing = _find_existing_doc(external_id)
    if existing:
        doc_id = existing["id"]
        r = httpx.patch(
            f"{APPS}/platform/document/v1/documents/{doc_id}",
            headers=_hdr(),
            params={"optimistic-locking-version": str(existing.get("version", 1))},
            files={
                "name": (None, name),
                "content": ("content.json", content_blob, "application/json"),
            },
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL update {name!r}: {r.status_code} {r.text[:200]}")
            return ""
    else:
        r = httpx.post(
            f"{APPS}/platform/document/v1/documents",
            headers=_hdr(),
            files={
                "name": (None, name),
                "type": (None, "dashboard"),
                "externalId": (None, external_id),
                "content": ("content.json", content_blob, "application/json"),
            },
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL create {name!r}: {r.status_code} {r.text[:200]}")
            return ""
        doc_id = r.json()["id"]
    return f"{APPS}/ui/apps/dynatrace.dashboards/dashboard/{doc_id}"


def provision_all_dashboards() -> list[tuple[str, str]]:
    """Push every themed dashboard and return [(name, url), ...]."""
    out: list[tuple[str, str]] = []
    for external_id, name, builder in THEMED_DASHBOARDS:
        url = _upsert(external_id, name, builder)
        if url:
            _log(f"  OK {name:<42} {url}")
        out.append((name, url))
    return out


if __name__ == "__main__":
    if not APPS or not TOKEN:
        raise SystemExit(
            "DT_ENVIRONMENT and DT_PLATFORM_TOKEN must be set in env"
        )
    _log(f"Provisioning {len(THEMED_DASHBOARDS)} themed dashboards on {APPS}")
    provision_all_dashboards()
