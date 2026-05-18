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
            "lifecycle. Pulls per-snapshot events, finding events "
            "(CUSTOM_DEPLOYMENT, source=parity), and approval/execution "
            "self-monitor events. The single best place to ask 'is the "
            "Parity loop working right now?'"
        ),
        # Snapshots · count the per-snapshot events directly (one per
        # successful snapshot). The rollup field snapshots_60s is the
        # ring counter for the LAST 60s — almost always 0 between
        # scheduled runs which is misleading on a "last hour" KPI.
        "1": _kpi("Snapshots · last hour",
                  'fetch events, from:-1h | filter source == "parity-self" '
                  'and `parity.self.category` == "snapshot" '
                  '| summarize n = count()',
                  "snapshots"),
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
        # Pending approvals · latest rollup value (the process-category
        # event includes approvals_pending which is the live DB count).
        # The previous "queued - approved" calc went negative because we
        # never instrumented `queued` events — only approved/denied/etc.
        "4": _kpi("Approvals pending",
                  'fetch events, from:-15m | filter source == "parity-self" '
                  'and `parity.self.category` == "process" '
                  '| sort timestamp desc | limit 1 '
                  '| fields v = toLong(`parity.self.approvals_pending`) '
                  '| summarize n = sum(v)',
                  "pending"),
        # NEW: snapshot duration trend (per-snapshot event carries
        # duration_s, more accurate than the rollup average which
        # truncates to 0 between scheduled runs).
        "5": _line("Snapshot duration (s) · per-snapshot",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "snapshot" '
                   '| makeTimeseries '
                   'dur_s = avg(toDouble(`parity.self.duration_s`)), '
                   'interval: 5m'),
        # NEW: snapshot size (size_bytes is on every per-snapshot
        # event) — total bytes written per interval = disk-impact proxy.
        "6": _line("Snapshot size (bytes) · sum per 15m",
                   'fetch events, from:-6h | filter source == "parity-self" '
                   'and `parity.self.category` == "snapshot" '
                   '| makeTimeseries '
                   'bytes = sum(toLong(`parity.self.size_bytes`)), '
                   'interval: 15m'),
        # NEW: golden snapshot fleet coverage. Each golden snapshot
        # fires a per-snapshot event with triggered_by =
        # "post-execution-fixed-device" or similar; the rollup is a
        # one-shot startup metric — the DB is authoritative. We read
        # via the Parity API in a separate side-tile (here we just
        # show the count of distinct devices that have golden events
        # in 24h, which approximates fleet coverage).
        "7": _kpi("Golden snapshot devices · 24h",
                  'fetch events, from:-24h | filter source == "parity-self" '
                  'and `parity.self.category` == "snapshot" '
                  'and contains(`parity.self.triggered_by`, "fixed-device") '
                  '| summarize n = countDistinctExact(`parity.self.device`)',
                  "devices"),
        "8": _line("Lifecycle moments · 24h",
                   'fetch events, from:-24h | filter source == "parity" '
                   '| makeTimeseries n = count(), by: { parity.action }, '
                   'interval: 30m'),
        "9": _bar("Findings by category · 24h",
                  'fetch events, from:-24h | filter source == "parity" '
                  'and isNotNull(parity.category) '
                  '| summarize n = count(), by: { parity.category } '
                  '| sort n desc'),
        "10": _bar("Approvals & execution outcomes · 24h",
                   'fetch events, from:-24h | filter source == "parity-self" '
                   'and in(`parity.self.category`, "approval", "execution") '
                   '| filter isNotNull(`parity.self.action`) '
                   '| summarize n = count(), '
                   'by: { `parity.self.category`, `parity.self.action` } '
                   '| sort n desc'),
        "11": _table("Latest 25 lifecycle events",
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
        "5": {"x": 0, "y": 5, "w": 8, "h": 6},
        "6": {"x": 8, "y": 5, "w": 8, "h": 6},
        "7": {"x": 16, "y": 5, "w": 8, "h": 6},
        "8": {"x": 0, "y": 11, "w": 24, "h": 5},
        "9": {"x": 0, "y": 16, "w": 12, "h": 5},
        "10": {"x": 12, "y": 16, "w": 12, "h": 5},
        "11": {"x": 0, "y": 21, "w": 24, "h": 7},
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


# ── Per-site dashboards (5 total: SITE1-4 + DCs) ─────────────


def _site_dashboard(site_label: str, site_filter: list[str],
                    device_list_md: str) -> dict[str, Any]:
    """Build a per-site dashboard.

    Two DQL gotchas learned the hard way:

    1. `timeseries` does NOT take a dimension filter via the
       `filter:` kwarg. That kwarg is reserved for entity-style
       filters. Dimension filters (e.g. `site == "SITE1"`) MUST be
       applied as a post-`|` pipe step, and the dimension itself
       MUST appear in `by:{...}` first so the column is in scope.

    2. CISCO-PROCESS-MIB (CPU) and CISCO-MEMORY-POOL-MIB are not
       implemented on IOSv lab images — they return 0. HOST-RESOURCES
       also unsupported. So CPU/memory tiles would always be empty;
       omitted here and called out in the markdown header.
    """
    # `site in ("SITE1","SITE2")` post-pipe filter.
    site_clause = (
        "in(site, " + ", ".join(f'"{s}"' for s in site_filter) + ")"
        if len(site_filter) > 1
        else f'site == "{site_filter[0]}"'
    )
    tiles = {
        "0": _md(
            f"# {site_label}\n\n"
            f"Live SNMPv2c view of every device in this site. Polled "
            f"every 60s by `backend/services/snmp_poller.py` with the "
            f"`readonly` community; metrics land in Grail as "
            f"`parity.snmp.*` with `device_label`, `device_ip`, `site`, "
            f"`if_descr`, `peer_ip` dimensions.\n\n"
            f"**Devices:** {device_list_md}\n\n"
            f"_Note: IOSv lab routers do not implement CISCO-PROCESS-MIB "
            f"or CISCO-MEMORY-POOL-MIB, so per-device CPU/memory tiles "
            f"are not shown — that data is unavailable from SNMP on "
            f"these images._"
        ),
        # KPI strip
        "1": _kpi(
            "Devices reporting · last 5m",
            f'timeseries by:{{device_label, site}}, '
            f'n=sum(parity.snmp.if.operStatus), from:-5m '
            f'| filter {site_clause} '
            f'| summarize devices = count()',
            "devices",
        ),
        "2": _kpi(
            "Interfaces operational",
            f'timeseries by:{{device_label, if_index, site}}, '
            f'oper=max(parity.snmp.if.operStatus), from:-5m '
            f'| filter {site_clause} '
            f'| filter arrayLast(oper) == 1 '
            f'| summarize n = count()',
            "up",
        ),
        "3": _kpi(
            "Interfaces DOWN as fault",
            f'timeseries by:{{device_label, if_index, site}}, '
            f'admin=max(parity.snmp.if.adminStatus), '
            f'oper=max(parity.snmp.if.operStatus), from:-5m '
            f'| filter {site_clause} '
            f'| filter arrayLast(admin) == 1 and arrayLast(oper) == 2 '
            f'| summarize n = count()',
            "down",
        ),
        "4": _kpi(
            "BGP peers Established",
            f'timeseries by:{{device_label, peer_ip, site}}, '
            f'state=max(parity.snmp.bgp.peerState), from:-5m '
            f'| filter {site_clause} '
            f'| filter arrayLast(state) == 6 '
            f'| summarize n = count()',
            "peers",
        ),
        # Interface stats — main charts
        "5": _line(
            "Interface throughput · per device/interface (in+out bytes)",
            f'timeseries by:{{device_label, if_descr, site}}, '
            f'in_b=sum(parity.snmp.if.inOctets), '
            f'out_b=sum(parity.snmp.if.outOctets), '
            f'from:-1h, interval:5m '
            f'| filter {site_clause}'
        ),
        "6": _line(
            "Interface errors trend (in + out)",
            f'timeseries by:{{device_label, site}}, '
            f'err_in=sum(parity.snmp.if.inErrors), '
            f'err_out=sum(parity.snmp.if.outErrors), '
            f'from:-6h, interval:15m '
            f'| filter {site_clause}'
        ),
        "7": _bar(
            "Interface errors · top 10 by device/interface (1h)",
            f'timeseries by:{{device_label, if_descr, site}}, '
            f'e_in=sum(parity.snmp.if.inErrors), '
            f'e_out=sum(parity.snmp.if.outErrors), '
            f'from:-1h '
            f'| filter {site_clause} '
            f'| summarize total = sum(arrayLast(e_in)) + sum(arrayLast(e_out)), '
            f'by:{{device_label, if_descr}} '
            f'| sort total desc | limit 10'
        ),
        # BGP detail
        "8": _table(
            "BGP peers · current state per device",
            f'timeseries by:{{device_label, peer_ip, peer_as, site}}, '
            f'state=max(parity.snmp.bgp.peerState), '
            f'updates_in=max(parity.snmp.bgp.peerInUpdates), '
            f'updates_out=max(parity.snmp.bgp.peerOutUpdates), '
            f'from:-5m '
            f'| filter {site_clause} '
            f'| fieldsAdd '
            f'state_label = if(arrayLast(state) == 6, "Established", '
            f'else: if(arrayLast(state) == 5, "OpenConfirm", '
            f'else: if(arrayLast(state) == 4, "OpenSent", '
            f'else: if(arrayLast(state) == 3, "Active", '
            f'else: if(arrayLast(state) == 2, "Connect", else: "Idle"))))) '
            f'| fields device_label, peer_ip, peer_as, state_label, '
            f'in_updates=arrayLast(updates_in), '
            f'out_updates=arrayLast(updates_out) '
            f'| sort device_label asc, peer_ip asc'
        ),
        # Uptime
        "9": _table(
            "Device uptime · current (sysUptime ticks → days)",
            f'timeseries by:{{device_label, site}}, '
            f'up=max(parity.snmp.sysUptime), from:-5m '
            f'| filter {site_clause} '
            f'| fieldsAdd ticks = arrayLast(up) '
            f'| fieldsAdd uptime_days = round(ticks / 100.0 / 86400.0, decimals: 2) '
            f'| fields device_label, uptime_days '
            f'| sort device_label asc'
        ),
        # Per-interface admin/oper state
        "10": _table(
            "Interfaces · current admin/oper state",
            f'timeseries by:{{device_label, if_descr, site}}, '
            f'admin=max(parity.snmp.if.adminStatus), '
            f'oper=max(parity.snmp.if.operStatus), from:-5m '
            f'| filter {site_clause} '
            f'| fieldsAdd '
            f'admin_s = if(arrayLast(admin) == 1, "up", else: "down"), '
            f'oper_s = if(arrayLast(oper) == 1, "up", else: "down") '
            f'| fields device_label, if_descr, admin_s, oper_s '
            f'| sort device_label asc, if_descr asc'
        ),
        # Davis-correlated Problems for this site's devices.
        # Source: SNMP-poller transitions emit an AVAILABILITY_EVENT
        # bound to the CUSTOM_DEVICE entity → Davis correlates and
        # opens a Problem with affected_entity_names containing the
        # device hostname (e.g. "S1-R1.clydeford.net"). We filter on
        # that, NOT on event.name (which Davis rewrites to generic
        # labels like "Multiple infrastructure problems").
        "11": _kpi(
            "Open Davis Problems · last 24h",
            f'fetch dt.davis.problems, from:-24h '
            f'| filter event.status == "ACTIVE" '
            f'| filter {affected_entities_clause(site_filter)} '
            f'| summarize n = count()',
            "problems",
        ),
        "12": _table(
            "Davis Problems · this site (last 24h)",
            f'fetch dt.davis.problems, from:-24h '
            f'| filter {affected_entities_clause(site_filter)} '
            f'| fields '
            f'when = event.start, '
            f'name = event.name, '
            f'status = event.status, '
            f'category = event.category, '
            f'affected = affected_entity_names '
            f'| sort when desc | limit 25'
        ),
        # Parity SNMP transition events feeding Davis (raw view —
        # useful even before Davis has fully correlated them).
        "13": _table(
            "SNMP transition events fed to Davis · this site (last 6h)",
            f'fetch events, from:-6h '
            f'| filter source == "parity" '
            f'and `parity.snmp.transition` == "true" '
            f'and {parity_site_clause(site_filter)} '
            f'| fields '
            f'when = timestamp, '
            f'device = `parity.device`, '
            f'action = `parity.action`, '
            f'severity = `parity.severity`, '
            f'category = `parity.category`, '
            f'title = `parity.title` '
            f'| sort when desc | limit 30'
        ),
    }
    layouts = {
        "0":  {"x": 0,  "y": 0,  "w": 24, "h": 3},
        "1":  {"x": 0,  "y": 3,  "w": 5,  "h": 3},
        "2":  {"x": 5,  "y": 3,  "w": 5,  "h": 3},
        "3":  {"x": 10, "y": 3,  "w": 5,  "h": 3},
        "4":  {"x": 15, "y": 3,  "w": 5,  "h": 3},
        "11": {"x": 20, "y": 3,  "w": 4,  "h": 3},
        "5":  {"x": 0,  "y": 6,  "w": 24, "h": 6},
        "6":  {"x": 0,  "y": 12, "w": 12, "h": 6},
        "7":  {"x": 12, "y": 12, "w": 12, "h": 6},
        "12": {"x": 0,  "y": 18, "w": 24, "h": 6},
        "13": {"x": 0,  "y": 24, "w": 24, "h": 6},
        "8":  {"x": 0,  "y": 30, "w": 14, "h": 8},
        "9":  {"x": 14, "y": 30, "w": 10, "h": 4},
        "10": {"x": 14, "y": 34, "w": 10, "h": 8},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


def site_label_short(site_filter: list[str]) -> str:
    """For SITE1/2/3/4 → "S1"/"S2"/...; for DC1/DC2 → "DC".
    Used by the Davis problems tile to fuzzy-match event names
    that include the device hostname (e.g. "S1-R1 · BGP peer ...").
    """
    s = site_filter[0]
    if s.startswith("SITE"):
        return "S" + s[-1] + "-"
    if s.startswith("DC"):
        return "DC"
    return s


# ── OneAgent APM dashboard ───────────────────────────────────


def _parity_oneagent_dashboard() -> dict[str, Any]:
    """Dashboard fed entirely by OneAgent auto-instrumentation on
    parity-backend / parity-dt-mcp / parity-dt-mcp-real.

    All tiles filter by the `[Environment]parity` tag that compose
    applies via DT_TAGS at container start, so they pick up new
    Parity containers automatically as OneAgent registers them.
    No in-app instrumentation involved — pure Smartscape data.
    """
    # Reusable: filter clauses for tagged entities. OneAgent encodes
    # the `parity` tag as the string "[Environment]parity" in the
    # entity's `tags` array; in("...", array) is the only working
    # membership form on this tenant per the DQL gotchas memory.
    PARITY_PG = 'in("[Environment]parity", entityAttr(dt.entity.process_group_instance, "tags"))'
    PARITY_SVC = 'in("[Environment]parity", entityAttr(dt.entity.service, "tags"))'

    tiles = {
        "0": _md(
            "# Parity · OneAgent APM\n\n"
            "**Auto-instrumented** by Dynatrace OneAgent baked into "
            "`parity-backend`, `parity-dt-mcp`, and `parity-dt-mcp-real` "
            "at image build time. Every HTTP call, DB query, MCP "
            "invocation, and subprocess gets traced end-to-end with "
            "zero in-app instrumentation. Tiles filter on the "
            "`[Environment]parity` tag set by `DT_TAGS` in "
            "`docker-compose.yml`, so new Parity containers light up "
            "here automatically as OneAgent registers them.\n\n"
            "For the full topology view → open **Smartscape** in the "
            "Hosts app and search `parity`. For per-request waterfalls "
            "→ open **Distributed Traces** and filter on the same tag."
        ),
        # KPI strip
        "1": _kpi(
            "Process groups monitored",
            'fetch dt.entity.process_group_instance '
            '| filter in("[Environment]parity", tags) '
            '| summarize n = count()',
            "processes",
        ),
        "2": _kpi(
            "Services discovered",
            'fetch dt.entity.service '
            '| filter in("[Environment]parity", tags) '
            '| summarize n = count()',
            "services",
        ),
        "3": _kpi(
            "Requests · last 1h",
            f'timeseries by:{{dt.entity.service}}, '
            f'n=sum(dt.service.request.count), from:-1h '
            f'| filter {PARITY_SVC} '
            f'| summarize total = sum(arraySum(n))',
            "requests",
        ),
        "4": _kpi(
            "Failed requests · last 1h",
            f'timeseries by:{{dt.entity.service}}, '
            f'n=sum(dt.service.request.failure_count), from:-1h '
            f'| filter {PARITY_SVC} '
            f'| summarize total = sum(arraySum(n))',
            "failures",
        ),
        # Process CPU + memory per container
        "5": _line(
            "Process CPU · per Parity container",
            f'timeseries by:{{dt.entity.process_group_instance}}, '
            f'cpu=avg(dt.process.cpu.usage), from:-1h, interval:1m '
            f'| filter {PARITY_PG}'
        ),
        "6": _line(
            "Process memory (working set) · per container",
            f'timeseries by:{{dt.entity.process_group_instance}}, '
            f'mem=avg(dt.process.memory.workingset), from:-1h, interval:1m '
            f'| filter {PARITY_PG}'
        ),
        # Service request volume + latency
        "7": _line(
            "Service request rate · per minute",
            f'timeseries by:{{dt.entity.service}}, '
            f'rps=sum(dt.service.request.count), from:-1h, interval:1m '
            f'| filter {PARITY_SVC}'
        ),
        "8": _line(
            "Service response time · P95 (µs)",
            f'timeseries by:{{dt.entity.service}}, '
            f'p95=percentile(dt.service.request.response_time, 95), '
            f'from:-1h, interval:5m '
            f'| filter {PARITY_SVC}'
        ),
        "9": _line(
            "Service failure rate · per minute",
            f'timeseries by:{{dt.entity.service}}, '
            f'fail=sum(dt.service.request.failure_count), from:-1h, '
            f'interval:1m '
            f'| filter {PARITY_SVC}'
        ),
        # Tables
        "10": _table(
            "Top called services · last 1h",
            f'timeseries by:{{dt.entity.service}}, '
            f'n=sum(dt.service.request.count), from:-1h '
            f'| filter {PARITY_SVC} '
            f'| fieldsAdd total = arraySum(n) '
            f'| fields service = dt.entity.service, requests = total '
            f'| sort requests desc | limit 10'
        ),
        "11": _table(
            "Process inventory · current",
            'fetch dt.entity.process_group_instance '
            '| filter in("[Environment]parity", tags) '
            '| fields name = entity.name, tech = softwareTechnologies, '
            '  tags '
            '| limit 20'
        ),
        # Smartscape pointer note (markdown only — no DQL)
        "12": _md(
            "## Where to find the rest of the OneAgent data\n\n"
            "- **Smartscape topology** — Hosts app → top-right → "
            "*Smartscape*. Filter `parity` to see the relationship "
            "graph between Parity processes, postgres, chromadb, the "
            "Vertex AI endpoint, and the lab devices.\n"
            "- **Distributed traces** — Observe → *Distributed traces*, "
            "filter `tag:parity`. Every API call traced end-to-end.\n"
            "- **Service flow** — Observe → *Services* → click any "
            "Parity service → *Service flow* shows the call graph "
            "with inlined response times.\n"
            "- **Davis Problems** — surface on the per-site dashboards "
            "via the entity-bound `AVAILABILITY_EVENT` path; OneAgent "
            "also opens its own problems on app-level anomalies "
            "(slow requests, error-rate spikes, GC pressure)."
        ),
    }
    layouts = {
        "0":  {"x": 0,  "y": 0,  "w": 24, "h": 3},
        "1":  {"x": 0,  "y": 3,  "w": 6,  "h": 3},
        "2":  {"x": 6,  "y": 3,  "w": 6,  "h": 3},
        "3":  {"x": 12, "y": 3,  "w": 6,  "h": 3},
        "4":  {"x": 18, "y": 3,  "w": 6,  "h": 3},
        "5":  {"x": 0,  "y": 6,  "w": 12, "h": 6},
        "6":  {"x": 12, "y": 6,  "w": 12, "h": 6},
        "7":  {"x": 0,  "y": 12, "w": 12, "h": 6},
        "8":  {"x": 12, "y": 12, "w": 12, "h": 6},
        "9":  {"x": 0,  "y": 18, "w": 24, "h": 5},
        "10": {"x": 0,  "y": 23, "w": 12, "h": 7},
        "11": {"x": 12, "y": 23, "w": 12, "h": 7},
        "12": {"x": 0,  "y": 30, "w": 24, "h": 4},
    }
    return {"version": 15, "variables": [], "tiles": tiles, "layouts": layouts}


_SITE_DEVICES: dict[str, list[str]] = {
    "SITE1": ["S1-R1", "S1-R2", "S1-S1", "S1-S2"],
    "SITE2": ["S2-R1", "S2-R2", "S2-S1", "S2-S2"],
    "SITE3": ["S3-R1", "S3-R2", "S3-S1", "S3-S2"],
    "SITE4": ["S4-R1", "S4-R2", "S4-S1", "S4-S2"],
    "DC1":   ["DC1-R1"],
    "DC2":   ["DC2-R2"],
}


def affected_entities_clause(site_filter: list[str]) -> str:
    """Build a DQL clause matching a Davis problem whose
    `affected_entity_names` array contains a device from this site.
    Davis entity names are FQDNs like "S1-R1.clydeford.net" so we
    have to enumerate each member.

    DQL's only array-membership function in this tenant is
    `in(<literal>, <array>)` — `arrayJoin`, `arrayContains` and
    lambda `->` filters are all rejected as "no such function".
    """
    hostnames: list[str] = []
    for s in site_filter:
        for short in _SITE_DEVICES.get(s, []):
            hostnames.append(f"{short}.clydeford.net")
    if not hostnames:
        return "false"
    return (
        "(" + " or ".join(
            f'in("{h}", affected_entity_names)' for h in hostnames
        ) + ")"
    )


def parity_site_clause(site_filter: list[str]) -> str:
    """DQL `parity.site` filter for the events table (parity-emitted
    SNMP transitions tag the dimension as `parity.site`)."""
    if len(site_filter) == 1:
        return f'`parity.site` == "{site_filter[0]}"'
    return "in(`parity.site`, " + ", ".join(f'"{s}"' for s in site_filter) + ")"


# Five concrete site dashboards. Site values match the inventory
# `tags.site` field used by snmp_poller's _discover_devices and
# carried as the `site` SNMP dimension on every emitted metric.

def _site1_dashboard() -> dict[str, Any]:
    return _site_dashboard(
        "SITE1 · S1-R1 / S1-R2 / S1-S1 / S1-S2",
        ["SITE1"],
        "S1-R1, S1-R2 (routers); S1-S1, S1-S2 (switches)",
    )


def _site2_dashboard() -> dict[str, Any]:
    return _site_dashboard(
        "SITE2 · S2-R1 / S2-R2 / S2-S1 / S2-S2",
        ["SITE2"],
        "S2-R1, S2-R2 (routers); S2-S1, S2-S2 (switches)",
    )


def _site3_dashboard() -> dict[str, Any]:
    return _site_dashboard(
        "SITE3 · S3-R1 / S3-R2 / S3-S1 / S3-S2",
        ["SITE3"],
        "S3-R1, S3-R2 (routers); S3-S1, S3-S2 (switches)",
    )


def _site4_dashboard() -> dict[str, Any]:
    return _site_dashboard(
        "SITE4 · S4-R1 / S4-R2 / S4-S1 / S4-S2",
        ["SITE4"],
        "S4-R1, S4-R2 (routers); S4-S1, S4-S2 (switches)",
    )


def _dcs_dashboard() -> dict[str, Any]:
    return _site_dashboard(
        "Data Centres · DC1-R1 + DC2-R2",
        ["DC1", "DC2"],
        "DC1-R1 (DC1), DC2-R2 (DC2)",
    )


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
    ("parity-site-1-v1",            "Site · SITE1 (S1-R1/R2/S1/S2)",    _site1_dashboard),
    ("parity-site-2-v1",            "Site · SITE2 (S2-R1/R2/S1/S2)",    _site2_dashboard),
    ("parity-site-3-v1",            "Site · SITE3 (S3-R1/R2/S1/S2)",    _site3_dashboard),
    ("parity-site-4-v1",            "Site · SITE4 (S4-R1/R2/S1/S2)",    _site4_dashboard),
    ("parity-site-dcs-v1",          "Site · Data Centres (DC1+DC2)",    _dcs_dashboard),
    ("parity-oneagent-v1",          "Parity · OneAgent APM",            _parity_oneagent_dashboard),
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
