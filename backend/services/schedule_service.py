"""Snapshot-schedule service — DB CRUD + APScheduler job lifecycle."""

from datetime import datetime, timezone

import structlog
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import async_session
from db.tables import Setting, SnapshotSchedule

log = structlog.get_logger()

# Set by services.scheduler.start() once the scheduler exists.
_apscheduler = None


def bind_scheduler(scheduler) -> None:
    """Attach the running APScheduler instance so we can manage jobs."""
    global _apscheduler
    _apscheduler = scheduler


def _job_id(schedule_id: str) -> str:
    return f"snapshot_schedule:{schedule_id}"


# ── CRUD ─────────────────────────────────────────────────────────────


async def list_schedules(db: AsyncSession) -> list[SnapshotSchedule]:
    result = await db.execute(select(SnapshotSchedule).order_by(SnapshotSchedule.created_at.desc()))
    return list(result.scalars().all())


async def get_schedule(db: AsyncSession, schedule_id: str) -> SnapshotSchedule | None:
    result = await db.execute(select(SnapshotSchedule).where(SnapshotSchedule.id == schedule_id))
    return result.scalar_one_or_none()


async def create_schedule(
    db: AsyncSession,
    *,
    name: str,
    cron_expr: str,
    device_ids: list[str],
    features: list[str],
    enabled: bool,
) -> SnapshotSchedule:
    sched = SnapshotSchedule(
        name=name,
        cron_expr=cron_expr,
        device_ids=device_ids,
        features=features,
        enabled=enabled,
    )
    db.add(sched)
    await db.commit()
    await db.refresh(sched)
    if enabled:
        _register_job(sched)
    return sched


async def update_schedule(
    db: AsyncSession, schedule_id: str, **fields
) -> SnapshotSchedule | None:
    sched = await get_schedule(db, schedule_id)
    if not sched:
        return None
    for key, value in fields.items():
        if value is not None:
            setattr(sched, key, value)
    await db.commit()
    await db.refresh(sched)

    _unregister_job(sched.id)
    if sched.enabled:
        _register_job(sched)
    return sched


async def delete_schedule(db: AsyncSession, schedule_id: str) -> bool:
    sched = await get_schedule(db, schedule_id)
    if not sched:
        return False
    _unregister_job(sched.id)
    await db.delete(sched)
    await db.commit()
    return True


# ── Scheduler integration ────────────────────────────────────────────


def _register_job(sched: SnapshotSchedule) -> None:
    if _apscheduler is None:
        log.warning("schedule_register_no_scheduler", schedule_id=sched.id)
        return
    try:
        trigger = CronTrigger.from_crontab(sched.cron_expr)
    except Exception as exc:
        log.error("schedule_invalid_cron", schedule_id=sched.id, cron=sched.cron_expr, error=str(exc))
        return
    _apscheduler.add_job(
        _run_schedule,
        trigger=trigger,
        id=_job_id(sched.id),
        args=[sched.id],
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    log.info("schedule_registered", schedule_id=sched.id, cron=sched.cron_expr)


def _unregister_job(schedule_id: str) -> None:
    if _apscheduler is None:
        return
    try:
        _apscheduler.remove_job(_job_id(schedule_id))
        log.info("schedule_unregistered", schedule_id=schedule_id)
    except Exception:
        pass  # job might not exist


async def reload_all_schedules() -> None:
    """Read every enabled schedule from the DB and (re)register its job."""
    if _apscheduler is None:
        return
    async with async_session() as db:
        schedules = await list_schedules(db)
    for s in schedules:
        if s.enabled:
            _register_job(s)


def get_next_run_time(schedule_id: str) -> datetime | None:
    if _apscheduler is None:
        return None
    job = _apscheduler.get_job(_job_id(schedule_id))
    return job.next_run_time if job else None


# ── Job execution ────────────────────────────────────────────────────


async def _run_schedule(schedule_id: str) -> None:
    """Fired by APScheduler. Skips if a snapshot is already running."""
    async with async_session() as db:
        sched = await get_schedule(db, schedule_id)
        if not sched:
            log.warning("schedule_run_missing", schedule_id=schedule_id)
            return

        # Skip if any snapshot is currently running.
        result = await db.execute(select(Setting).where(Setting.key == "snapshot_status"))
        row = result.scalar_one_or_none()
        if row and row.value.get("running"):
            log.info("scheduled_snapshot_skipped", schedule_id=schedule_id, reason="another_run_active")
            sched.last_run_at = datetime.now(timezone.utc)
            sched.last_result = "skipped"
            sched.last_error = "Another snapshot was already running"
            await db.commit()
            return

        sched.last_run_at = datetime.now(timezone.utc)
        sched.last_result = "running"
        sched.last_error = None
        await db.commit()

    # Delegate to the same workflow used by the manual route — handles
    # status tracking, progress events, and post-snapshot ADK reasoner trigger.
    from api.routes.snapshots import _run_snapshot_background

    overall_ok = True
    last_err: str | None = None
    try:
        await _run_snapshot_background(
            device_id=None,
            device_ids=sched.device_ids if sched.device_ids else None,
            features=sched.features if sched.features else None,
            triggered_by=f"schedule:{sched.name}",
        )
    except Exception as exc:
        overall_ok = False
        last_err = str(exc)
        log.error("scheduled_snapshot_error", schedule_id=schedule_id, error=str(exc))

    async with async_session() as db:
        sched = await get_schedule(db, schedule_id)
        if sched:
            sched.last_result = "ok" if overall_ok else "error"
            sched.last_error = last_err
            await db.commit()

    log.info("scheduled_snapshot_done", schedule_id=schedule_id, ok=overall_ok)


async def run_schedule_now(schedule_id: str) -> None:
    """Manually trigger a schedule outside of its cron cadence."""
    await _run_schedule(schedule_id)
