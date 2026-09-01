"""Background scheduler — periodic jobs (inventory refresh, etc.)."""

from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from db.postgres import async_session
from services import approval_service, inventory, schedule_service

log = structlog.get_logger()

_scheduler: AsyncIOScheduler | None = None

# How often the expire_stale sweep runs. Independent of
# approval_expiry_hours (which controls the TTL itself) — this is just
# the polling cadence for the sweep.
APPROVAL_EXPIRY_CHECK_MINUTES = 15


async def refresh_inventory_now() -> int:
    """Run a single inventory refresh and return the device count.

    Logs both success and failure. Safe to call from lifespan startup
    and from the scheduled job — never raises.
    """
    try:
        async with async_session() as db:
            devices = await inventory.refresh_inventory(db)
        log.info("inventory_refresh_ok", count=len(devices))
        return len(devices)
    except Exception as exc:
        log.error("inventory_refresh_failed", error=str(exc))
        return 0


async def _scheduled_inventory_refresh() -> None:
    await refresh_inventory_now()


async def expire_approvals_now() -> int:
    """Run a single expire_stale sweep and return the number expired.

    Logs both success and failure. Safe to call from the scheduled job
    (and anywhere else convenience calls for it) — never raises.
    """
    try:
        async with async_session() as db:
            count = await approval_service.expire_stale(db)
        log.info("approval_expiry_sweep_ok", expired=count)
        return count
    except Exception as exc:
        log.error("approval_expiry_sweep_failed", error=str(exc))
        return 0


async def _scheduled_expire_approvals() -> None:
    await expire_approvals_now()


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    # Start the scheduler BEFORE adding jobs. APScheduler's "tentatively
    # added before start" path has bitten us: jobs go into the store but
    # the wakeup loop never picks them up. Adding after start is the
    # documented safe path and gives us a real next_run_time immediately.
    _scheduler.start()

    interval_minutes = settings.inventory_refresh_minutes
    _scheduler.add_job(
        _scheduled_inventory_refresh,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="inventory_refresh",
        # Fire one full interval after start. Lifespan does a synchronous
        # refresh on boot so we don't need an immediate first fire here.
        next_run_time=datetime.now(timezone.utc).replace(microsecond=0)
        + _interval_offset(interval_minutes),
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    _scheduler.add_job(
        _scheduled_expire_approvals,
        trigger=IntervalTrigger(minutes=APPROVAL_EXPIRY_CHECK_MINUTES),
        id="approval_expiry_sweep",
        # Same "add after start" pattern as inventory_refresh above.
        next_run_time=datetime.now(timezone.utc).replace(microsecond=0)
        + _interval_offset(APPROVAL_EXPIRY_CHECK_MINUTES),
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    schedule_service.bind_scheduler(_scheduler)
    log.info(
        "scheduler_started",
        inventory_refresh_minutes=interval_minutes,
        next_inventory_run=str(_scheduler.get_job("inventory_refresh").next_run_time),
        approval_expiry_check_minutes=APPROVAL_EXPIRY_CHECK_MINUTES,
        next_approval_expiry_run=str(
            _scheduler.get_job("approval_expiry_sweep").next_run_time
        ),
    )


def _interval_offset(minutes: int):
    from datetime import timedelta
    return timedelta(minutes=minutes)


async def load_persistent_schedules() -> None:
    """Re-register snapshot schedules from the DB after startup.

    Tolerates a missing ``snapshot_schedules`` table so the app can boot
    in environments where the migration hasn't been applied yet.
    """
    try:
        await schedule_service.reload_all_schedules()
    except Exception as exc:
        log.warning("schedule_load_skipped", error=str(exc))


def shutdown() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    log.info("scheduler_stopped")
