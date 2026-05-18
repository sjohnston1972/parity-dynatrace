"""Parity — FastAPI application entry point."""

import logging
import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from api.routes import approvals, chat, dashboard, devices, dynatrace, execution, findings, health, llm, pipeline, schedules, snapshots, topology
from db.postgres import engine
from services import scheduler

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

log = structlog.get_logger()


async def _reset_stale_snapshot_status():
    """Clear any 'running' snapshot status left over from a previous process."""
    from db.postgres import async_session
    from db.tables import Setting
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(select(Setting).where(Setting.key == "snapshot_status"))
        row = result.scalar_one_or_none()
        if row and row.value.get("running"):
            log.warning("snapshot_status_reset_on_startup")
            row.value = {
                "running": False,
                "result": "error",
                "error": "Process restarted while snapshot was running",
            }
            await db.commit()


async def _reset_orphaned_approvals():
    """Mark any 'approved' (executing) approvals as failed on startup.

    If the container restarted while an execution was in-flight, the
    asyncio.create_task was lost.  These approvals would otherwise be
    stuck in 'approved' forever.
    """
    from db.postgres import async_session
    from db.tables import Approval
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(
            select(Approval).where(Approval.status == "approved")
        )
        stuck = result.scalars().all()
        for a in stuck:
            a.status = "failed"
            a.execution_result = {"error": "Execution lost — container restarted before completion"}
            log.warning("orphaned_approval_reset", approval_id=a.id)
        if stuck:
            await db.commit()
            log.info("orphaned_approvals_fixed", count=len(stuck))


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _asyncio
    from services.self_monitor import run_forever as _sm_run, stop as _sm_stop
    log.info("parity_starting")
    await _reset_stale_snapshot_status()
    await _reset_orphaned_approvals()
    # Refresh inventory immediately on startup so devices have fresh
    # last_seen/last_refreshed timestamps the moment the API comes up.
    # Don't rely on the scheduler's first fire — if APScheduler has any
    # hiccup, we'd otherwise stay stale until someone clicks refresh.
    await scheduler.refresh_inventory_now()
    scheduler.start()
    await scheduler.load_persistent_schedules()
    # Hydrate the in-memory activity bus from the persisted
    # activity_events table so the Pipeline page's Reasoner & Engine
    # Status panel isn't blank after every rebuild. Best-effort —
    # missing table or DB hiccup logs at debug and continues.
    from services.activity import hydrate_from_db as _act_hydrate
    try:
        await _act_hydrate(limit=100)
    except Exception as e:
        log.warning("activity_hydrate_skipped", error=str(e))
    # Background self-monitor — pushes container/API/MCP/Gemini stats
    # to Dynatrace every 60s as parity-self events.
    sm_task = _asyncio.create_task(_sm_run(60))
    log.info("self_monitor_task_started")
    # SNMP poller — replacement for the AG-hosted SNMP Generic extension
    # (blocked because Dynatrace's AG installer requires systemd, which
    # standard Docker containers don't provide). Polls every 60s, pushes
    # parity.snmp.* metrics to Dynatrace via /api/v2/metrics/ingest with
    # the OAuth client. Set PARITY_SNMP_DISABLED=1 to turn it off.
    from services.snmp_poller import run_forever as _snmp_run, stop as _snmp_stop
    snmp_task = _asyncio.create_task(_snmp_run())
    log.info("snmp_poller_task_started")
    yield
    _sm_stop()
    _snmp_stop()
    sm_task.cancel()
    snmp_task.cancel()
    scheduler.shutdown()
    await engine.dispose()
    log.info("parity_shutdown")


app = FastAPI(
    title="Parity",
    description="AI-augmented network operations platform",
    version="0.1.0",
    lifespan=lifespan,
)

# OpenTelemetry init — fills the FastAPI/ASGI gap that OneAgent's
# Python deep monitoring v1.337 doesn't cover. Auto-instruments
# FastAPI/SQLAlchemy/asyncpg/httpx and exports OTLP spans to
# Dynatrace. No-ops cleanly when OTEL_ENDPOINT/PARITY_OTEL_TOKEN
# aren't set, so dev runs without the tenant config still work.
from integrations.otel import init_otel  # noqa: E402
init_otel(app)

# Self-monitor request middleware — captures per-request latency / status
# into bounded ring buffers so the periodic emitter can roll them up.
from services.self_monitor import request_metrics_middleware  # noqa: E402
app.middleware("http")(request_metrics_middleware())

app.include_router(health.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(devices.router, prefix="/api/v1")
app.include_router(snapshots.router, prefix="/api/v1")
app.include_router(findings.router, prefix="/api/v1")
app.include_router(approvals.router, prefix="/api/v1")
app.include_router(topology.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(dynatrace.router, prefix="/api/v1")
app.include_router(llm.router, prefix="/api/v1")
app.include_router(pipeline.router, prefix="/api/v1")
app.include_router(execution.router, prefix="/api/v1")
app.include_router(schedules.router, prefix="/api/v1")
