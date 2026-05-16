"""Self-monitoring telemetry — Parity reporting on itself to Dynatrace.

Every 60 seconds (configurable) the collector samples:

* Docker container health for every container in this compose stack
  — name, status, restart count, CPU %, memory MB, network bytes
  if the docker socket is reachable from inside the backend container.
* Recent HTTP request counts + latency + error rate captured by the
  ``RequestMetricsMiddleware`` ring buffer.
* MCP tool call counts + latency captured by ``mcp_counters``.
* Gemini call counts + latency + total tokens captured by
  ``gemini_counters``.
* Snapshot/pyATS counts (snapshots taken since boot, by result).

Each sample is emitted as one ``CUSTOM_INFO`` Davis event with
``source == "parity-self"`` and a stable ``parity.self.category`` so
the self-monitoring dashboard can pivot cleanly on category.

The collector is best-effort end-to-end — a Davis outage, a missing
docker socket, or a transient exception in one collector path never
blocks the others and never takes down the backend.
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any

import httpx
import structlog

from config import settings

log = structlog.get_logger()


# Process boot time — used so parity.process.uptime_s reflects the
# backend's lifetime independent of container start time, which is
# what container.uptime_s already covers in the docker category.
_PROCESS_START_MONOTONIC = time.monotonic()


# ── Dynatrace writer self-stats counters ────────────────────
# Incremented from dynatrace_writer._post_event on success / failure
# paths so the writer can be observed via the same self-monitor tick
# without circular imports. Plain int counters — read on each tick,
# never reset (Dynatrace can rate them on the chart side if needed).
dt_events_sent_counter: int = 0
dt_events_rejected_counter: int = 0


def dt_events_record(success: bool) -> None:
    """Bump the writer counters from inside dynatrace_writer._post_event."""
    global dt_events_sent_counter, dt_events_rejected_counter
    if success:
        dt_events_sent_counter += 1
    else:
        dt_events_rejected_counter += 1


# ── Lightweight counters (used by middleware + wrapped clients) ─

class RingCounter:
    """Bounded ring of (timestamp, value) samples for last-60-second views."""

    def __init__(self, window_seconds: float = 60.0, capacity: int = 4096):
        self._buf: deque[tuple[float, float]] = deque(maxlen=capacity)
        self._window = window_seconds

    def add(self, value: float = 1.0) -> None:
        self._buf.append((time.monotonic(), value))

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._window
        while self._buf and self._buf[0][0] < cutoff:
            self._buf.popleft()

    def count(self) -> int:
        self._prune()
        return len(self._buf)

    def sum(self) -> float:
        self._prune()
        return sum(v for _, v in self._buf)

    def avg(self) -> float:
        self._prune()
        return (sum(v for _, v in self._buf) / len(self._buf)) if self._buf else 0.0

    def max(self) -> float:
        self._prune()
        return max((v for _, v in self._buf), default=0.0)


# Counters used by the middleware and by wrapped clients.
http_request_counter = RingCounter()
http_error_counter = RingCounter()
http_latency_counter = RingCounter()

mcp_call_counter = RingCounter()
mcp_error_counter = RingCounter()
mcp_latency_counter = RingCounter()

gemini_call_counter = RingCounter()
gemini_error_counter = RingCounter()
gemini_latency_counter = RingCounter()
gemini_token_counter = RingCounter()

# Snapshot ring — every completed snapshot adds {device, duration_s, feature_count}
snapshot_counter = RingCounter()
snapshot_duration_counter = RingCounter()
snapshot_features_counter = RingCounter()


# Per-path / per-tool tallies — bucketed labels for richer DQL.
http_by_path: dict[str, RingCounter] = defaultdict(RingCounter)
mcp_by_tool: dict[str, RingCounter] = defaultdict(RingCounter)


# ── HTTP middleware ─────────────────────────────────────────


def request_metrics_middleware():
    """FastAPI middleware factory — captures per-request latency + status."""
    from fastapi import Request

    async def middleware(request: Request, call_next):
        start = time.monotonic()
        path = request.url.path
        try:
            response = await call_next(request)
            elapsed_ms = (time.monotonic() - start) * 1000
            http_request_counter.add()
            http_latency_counter.add(elapsed_ms)
            http_by_path[path].add()
            if response.status_code >= 500:
                http_error_counter.add()
            return response
        except Exception as exc:
            http_request_counter.add()
            http_error_counter.add()
            raise exc

    return middleware


# ── Wrapped client helpers ──────────────────────────────────


@asynccontextmanager
async def mcp_call_timed(tool_name: str):
    """Wrap an MCP call so the counters track success/failure + latency."""
    start = time.monotonic()
    failed = False
    try:
        yield
    except Exception:
        failed = True
        mcp_error_counter.add()
        raise
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000
        mcp_call_counter.add()
        mcp_latency_counter.add(elapsed_ms)
        mcp_by_tool[tool_name].add()
        if not failed:
            log.debug("mcp_call_timed", tool=tool_name, ms=int(elapsed_ms))


@asynccontextmanager
async def gemini_call_timed(model: str | None = None):
    """Wrap a Gemini call so the counters track success/failure + latency."""
    start = time.monotonic()
    try:
        yield
    except Exception:
        gemini_error_counter.add()
        raise
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000
        gemini_call_counter.add()
        gemini_latency_counter.add(elapsed_ms)
        log.debug("gemini_call_timed", model=model, ms=int(elapsed_ms))


def gemini_record_tokens(tokens: int) -> None:
    if tokens > 0:
        gemini_token_counter.add(float(tokens))


def snapshot_record(duration_seconds: float, feature_count: int, *,
                    device_hostname: str = "", size_bytes: int = 0,
                    triggered_by: str = "manual") -> None:
    """Record one completed snapshot. Also fires a per-snapshot event."""
    snapshot_counter.add()
    if duration_seconds:
        snapshot_duration_counter.add(float(duration_seconds))
    if feature_count:
        snapshot_features_counter.add(float(feature_count))
    # Fire-and-forget event to Davis so each snapshot is queryable
    # individually (size, duration, device, trigger).
    try:
        import asyncio as _aio
        from integrations.dynatrace import dynatrace_writer
        coro = dynatrace_writer.emit_self_metric(
            "snapshot",
            device=device_hostname or "unknown",
            duration_s=round(duration_seconds, 2),
            feature_count=int(feature_count),
            size_bytes=int(size_bytes),
            triggered_by=triggered_by,
        )
        try:
            loop = _aio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # No running loop (sync caller from a worker thread) — just drop
            coro.close()
    except Exception:
        pass


# ── Docker container sampler ────────────────────────────────


def _collect_container_stats() -> list[dict[str, Any]]:
    """Return per-container stats if the docker socket is reachable.

    Quiet failure: returns an empty list on any error (socket not
    mounted, permission denied, docker daemon down). The other
    collectors continue working.
    """
    try:
        import docker  # imported lazily — keeps startup quick
    except Exception:
        return []
    try:
        client = docker.from_env(timeout=4)
        out: list[dict[str, Any]] = []
        for c in client.containers.list(all=True, filters={"name": "parity-"}):
            try:
                # `stats(stream=False)` is one-shot — fast and lightweight.
                s = c.stats(stream=False) or {}
                cpu = _calc_cpu_pct(s)
                mem = s.get("memory_stats", {}) or {}
                mem_usage_mb = (mem.get("usage", 0) or 0) / (1024 * 1024)
                mem_limit_mb = (mem.get("limit", 0) or 0) / (1024 * 1024)
                # Restart count from the container attrs
                attrs = c.attrs or {}
                restarts = ((attrs.get("RestartCount") or 0)
                            if isinstance(attrs.get("RestartCount"), int) else 0)
                out.append({
                    "name": c.name,
                    "status": c.status,
                    "health": (attrs.get("State", {}).get("Health", {}).get("Status")
                               if isinstance(attrs.get("State"), dict) else None),
                    "cpu_pct": round(cpu, 2),
                    "mem_mb": round(mem_usage_mb, 1),
                    "mem_limit_mb": round(mem_limit_mb, 1),
                    "restarts": restarts,
                })
            except Exception as e:
                log.debug("container_stats_per_failed", container=c.name, error=str(e))
        return out
    except Exception as e:
        log.debug("docker_stats_unavailable", error=str(e))
        return []


def _calc_cpu_pct(stats: dict) -> float:
    try:
        cpu = stats.get("cpu_stats", {}) or {}
        precpu = stats.get("precpu_stats", {}) or {}
        cpu_total = cpu.get("cpu_usage", {}).get("total_usage", 0)
        precpu_total = precpu.get("cpu_usage", {}).get("total_usage", 0)
        sys_now = cpu.get("system_cpu_usage", 0)
        sys_prev = precpu.get("system_cpu_usage", 0)
        cpus = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage") or [1])
        delta_cpu = cpu_total - precpu_total
        delta_sys = sys_now - sys_prev
        if delta_sys > 0 and delta_cpu > 0:
            return (delta_cpu / delta_sys) * cpus * 100.0
    except Exception:
        pass
    return 0.0


# ── Process / disk / DB / findings / inventory samplers ─────


def _collect_process_stats() -> dict[str, Any]:
    """Sample the backend Python process via psutil + gc.

    Every metric is best-effort — psutil import failure or an unreadable
    /proc entry must not break the rest of the snapshot.
    """
    out: dict[str, Any] = {
        "uptime_s": round(time.monotonic() - _PROCESS_START_MONOTONIC, 1),
    }
    try:
        import psutil  # lazy import keeps startup fast
        proc = psutil.Process(os.getpid())
        # cpu_percent with interval=None returns the value since the last
        # call — the first call after process boot returns 0.0, which is
        # accurate enough for a 60s tick.
        out["cpu_pct"] = round(proc.cpu_percent(interval=None), 2)
        try:
            out["rss_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
        except Exception:
            out["rss_mb"] = 0.0
        try:
            out["threads"] = int(proc.num_threads())
        except Exception:
            out["threads"] = 0
        try:
            # num_fds is POSIX-only; on Windows fall back to num_handles.
            out["fds_open"] = int(getattr(proc, "num_fds", lambda: getattr(
                proc, "num_handles", lambda: 0)())())
        except Exception:
            out["fds_open"] = 0
    except Exception as e:
        log.debug("psutil_unavailable", error=str(e))
    # asyncio task count — only meaningful when called from inside the loop
    try:
        out["asyncio_tasks"] = len(asyncio.all_tasks())
    except RuntimeError:
        out["asyncio_tasks"] = 0
    # gc counters: a 3-tuple of per-generation collection counts
    try:
        counts = gc.get_count()
        out["gc_gen0"] = int(counts[0])
        out["gc_gen1"] = int(counts[1]) if len(counts) > 1 else 0
        out["gc_gen2"] = int(counts[2]) if len(counts) > 2 else 0
    except Exception:
        pass
    return out


def _collect_disk_stats() -> dict[str, Any]:
    """psutil.disk_usage on the root mount — covers parity-pgdata volume."""
    try:
        import psutil
        d = psutil.disk_usage("/")
        return {
            "used_gb": round(d.used / (1024 ** 3), 2),
            "free_gb": round(d.free / (1024 ** 3), 2),
            "pct_used": round(d.percent, 1),
        }
    except Exception as e:
        log.debug("disk_stats_unavailable", error=str(e))
        return {}


def _collect_db_pool_stats() -> dict[str, Any]:
    """Read SQLAlchemy async engine pool sizing — synchronous, no I/O."""
    try:
        from db.postgres import engine
        pool = engine.pool
        return {
            "pool_size": int(pool.size()),
            "pool_checked_out": int(pool.checkedout()),
        }
    except Exception as e:
        log.debug("db_pool_stats_unavailable", error=str(e))
        return {}


async def _collect_db_counts() -> dict[str, Any]:
    """One-shot DB queries for findings / incidents / approvals / inventory."""
    out: dict[str, Any] = {}
    try:
        from sqlalchemy import func, select
        from db.postgres import async_session
        from db.tables import Approval, Device, Finding

        async with async_session() as s:
            try:
                out["findings_total"] = int(
                    (await s.execute(select(func.count(Finding.id)))).scalar() or 0
                )
            except Exception as e:
                log.debug("findings_total_failed", error=str(e))
            try:
                out["findings_open"] = int(
                    (await s.execute(
                        select(func.count(Finding.id))
                        .where(Finding.requires_remediation.is_(True))
                    )).scalar() or 0
                )
            except Exception as e:
                log.debug("findings_open_failed", error=str(e))
            try:
                out["incidents_open"] = int(
                    (await s.execute(
                        select(func.count(func.distinct(Finding.incident_id)))
                        .where(Finding.requires_remediation.is_(True))
                        .where(Finding.incident_id.is_not(None))
                    )).scalar() or 0
                )
            except Exception as e:
                log.debug("incidents_open_failed", error=str(e))
            try:
                out["approvals_pending"] = int(
                    (await s.execute(
                        select(func.count(Approval.id))
                        .where(Approval.status == "pending")
                    )).scalar() or 0
                )
            except Exception as e:
                log.debug("approvals_pending_failed", error=str(e))
            try:
                out["inventory_devices_total"] = int(
                    (await s.execute(select(func.count(Device.id)))).scalar() or 0
                )
            except Exception as e:
                log.debug("inventory_total_failed", error=str(e))
    except Exception as e:
        log.debug("db_counts_unavailable", error=str(e))
    return out


# ── Snapshot of all telemetry as a single payload ───────────


def gather_snapshot() -> dict[str, Any]:
    """One-shot collect of every metric the self-monitor tracks."""
    return {
        "http": {
            "requests_60s": http_request_counter.count(),
            "errors_60s": http_error_counter.count(),
            "avg_latency_ms": round(http_latency_counter.avg(), 1),
            "max_latency_ms": round(http_latency_counter.max(), 1),
            "by_path": {p: c.count() for p, c in list(http_by_path.items())[:20]},
        },
        "mcp": {
            "calls_60s": mcp_call_counter.count(),
            "errors_60s": mcp_error_counter.count(),
            "avg_latency_ms": round(mcp_latency_counter.avg(), 1),
            "by_tool": {t: c.count() for t, c in list(mcp_by_tool.items())[:20]},
        },
        "gemini": {
            "calls_60s": gemini_call_counter.count(),
            "errors_60s": gemini_error_counter.count(),
            "avg_latency_ms": round(gemini_latency_counter.avg(), 1),
            "tokens_60s": int(gemini_token_counter.sum()),
        },
        "containers": _collect_container_stats(),
        # Process / disk / DB pool are synchronous one-shots — DB row
        # counts run async inside _emit_self_to_dynatrace so we can
        # await them cleanly.
        "process": _collect_process_stats(),
        "disk": _collect_disk_stats(),
        "db_pool": _collect_db_pool_stats(),
        "dt_writer": {
            "events_sent": dt_events_sent_counter,
            "events_rejected": dt_events_rejected_counter,
        },
    }


# ── Periodic emitter ────────────────────────────────────────


async def _emit_self_to_dynatrace(snapshot: dict[str, Any]) -> None:
    from integrations.dynatrace import dynatrace_writer

    # Top-level rollup so a single DQL query gets everything.
    await dynatrace_writer.emit_self_metric(
        "rollup",
        http_requests_60s=snapshot["http"]["requests_60s"],
        http_errors_60s=snapshot["http"]["errors_60s"],
        http_avg_latency_ms=snapshot["http"]["avg_latency_ms"],
        mcp_calls_60s=snapshot["mcp"]["calls_60s"],
        mcp_errors_60s=snapshot["mcp"]["errors_60s"],
        mcp_avg_latency_ms=snapshot["mcp"]["avg_latency_ms"],
        gemini_calls_60s=snapshot["gemini"]["calls_60s"],
        gemini_errors_60s=snapshot["gemini"]["errors_60s"],
        gemini_avg_latency_ms=snapshot["gemini"]["avg_latency_ms"],
        gemini_tokens_60s=snapshot["gemini"]["tokens_60s"],
        snapshots_60s=snapshot_counter.count(),
        snapshot_avg_duration_s=round(snapshot_duration_counter.avg(), 2),
        snapshot_total_features_60s=int(snapshot_features_counter.sum()),
        container_count=len(snapshot["containers"]),
    )

    # Per-container event so the dashboard can pivot by container name.
    for c in snapshot["containers"]:
        await dynatrace_writer.emit_self_metric(
            "container",
            container_name=c["name"],
            container_status=c["status"],
            container_health=c.get("health") or "n/a",
            cpu_pct=c["cpu_pct"],
            mem_mb=c["mem_mb"],
            mem_limit_mb=c["mem_limit_mb"],
            restarts=c["restarts"],
        )

    # Single "process" category event — collapses every cheap one-shot
    # signal (Python runtime, host disk, DB pool, DB counts, DT writer
    # counters, inventory) into one Davis event so the self-monitor
    # dashboard can pivot the lot with a single
    #   filter parity.self.category == "process"
    proc = snapshot.get("process") or {}
    disk = snapshot.get("disk") or {}
    db_pool = snapshot.get("db_pool") or {}
    dt = snapshot.get("dt_writer") or {}
    db_counts = await _collect_db_counts()

    props: dict[str, Any] = {}
    # Process / Python runtime (section 14)
    for k in ("cpu_pct", "rss_mb", "threads", "fds_open", "uptime_s",
              "asyncio_tasks", "gc_gen0", "gc_gen1", "gc_gen2"):
        if k in proc:
            props[f"process_{k}"] = proc[k]
    # Host disk (section 5 candidates)
    for k in ("used_gb", "free_gb", "pct_used"):
        if k in disk:
            props[f"disk_{k}"] = disk[k]
    # DB pool + counts (section 12, 6, 7, 13)
    for k in ("pool_size", "pool_checked_out"):
        if k in db_pool:
            props[f"db_{k}"] = db_pool[k]
    for k, v in db_counts.items():
        props[k] = v
    # DT writer self-stats (section 11)
    props["dt_events_sent"] = dt.get("events_sent", 0)
    props["dt_events_rejected"] = dt.get("events_rejected", 0)

    if props:
        await dynatrace_writer.emit_self_metric("process", **props)


_RUN = False


async def run_forever(interval_seconds: int = 60) -> None:
    """Forever loop emitting self-monitor snapshots every N seconds.

    Started from the FastAPI lifespan so it stops cleanly with the app.
    """
    global _RUN
    if _RUN:
        log.info("self_monitor_already_running")
        return
    _RUN = True
    log.info("self_monitor_start", interval_seconds=interval_seconds)
    try:
        while _RUN:
            try:
                snap = gather_snapshot()
                await _emit_self_to_dynatrace(snap)
            except Exception as e:
                log.warning("self_monitor_tick_failed", error=str(e))
            await asyncio.sleep(interval_seconds)
    finally:
        log.info("self_monitor_stop")


def stop() -> None:
    global _RUN
    _RUN = False
