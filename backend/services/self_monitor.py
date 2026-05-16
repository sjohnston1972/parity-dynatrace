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
