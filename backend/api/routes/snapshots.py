"""Snapshot CRUD and trigger endpoints."""

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db, async_session
from db.tables import Setting
from models.snapshot import SnapshotDetail, SnapshotDiff, SnapshotRead, SnapshotTrigger
from services import snapshot_engine

router = APIRouter(prefix="/snapshots", tags=["snapshots"])
log = structlog.get_logger()

SNAP_STATUS_KEY = "snapshot_status"


async def _read_status(db: AsyncSession) -> dict:
    result = await db.execute(select(Setting).where(Setting.key == SNAP_STATUS_KEY))
    row = result.scalar_one_or_none()
    return row.value if row else {"running": False}


async def _write_status(db: AsyncSession, value: dict):
    result = await db.execute(select(Setting).where(Setting.key == SNAP_STATUS_KEY))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(Setting(key=SNAP_STATUS_KEY, value=value))
    await db.commit()


async def _run_snapshot_background(
    device_id: str | None,
    *,
    device_ids: list[str] | None = None,
    features: list[str] | None = None,
    triggered_by: str = "manual",
):
    """Run snapshot in the background, updating status in the settings table.

    Either pass a single ``device_id`` (legacy/manual) or a list of
    ``device_ids`` (scheduler).  ``features`` overrides the default per-device
    feature list when provided.
    """
    async with async_session() as db:
        started = datetime.now(timezone.utc)
        try:
            # Count target devices for progress tracking
            from db.tables import Device as DeviceModel
            if device_ids:
                dev_count_result = await db.execute(
                    select(DeviceModel).where(DeviceModel.id.in_(device_ids))
                )
                total_devices = len(dev_count_result.scalars().all())
            elif device_id:
                dev_count_result = await db.execute(
                    select(DeviceModel).where(DeviceModel.id == device_id)
                )
                total_devices = len(dev_count_result.scalars().all())
            else:
                dev_count_result = await db.execute(select(DeviceModel))
                total_devices = len(dev_count_result.scalars().all())

            await _write_status(db, {
                "running": True,
                "started_at": started.isoformat(),
                "device_id": device_id,
                "triggered_by": triggered_by,
                "devices_done": 0,
                "devices_total": total_devices,
                "current_device": None,
            })

            async def _on_progress(done: int, total: int, hostname: str):
                await _write_status(db, {
                    "running": True,
                    "started_at": started.isoformat(),
                    "device_id": device_id,
                    "triggered_by": triggered_by,
                    "devices_done": done,
                    "devices_total": total,
                    "current_device": hostname,
                })

            # Multi-device path runs each device sequentially through take_snapshot.
            if device_ids:
                results = []
                for did in device_ids:
                    part = await snapshot_engine.take_snapshot(
                        db, device_id=did, features=features,
                        triggered_by=triggered_by, on_progress=_on_progress,
                    )
                    results.extend(part)
            else:
                results = await snapshot_engine.take_snapshot(
                    db, device_id=device_id, features=features,
                    triggered_by=triggered_by, on_progress=_on_progress,
                )
            finished = datetime.now(timezone.utc)

            # Build per-device breakdown
            # Eager-load device hostnames
            dev_ids = [s.device_id for s in results]
            dev_map = {}
            if dev_ids:
                from db.tables import Device
                dev_result = await db.execute(
                    select(Device).where(Device.id.in_(dev_ids))
                )
                dev_map = {d.id: d.hostname.split(".")[0] for d in dev_result.scalars().all()}

            per_device = []
            ok_devices = 0
            failed_devices = 0
            total_duration = 0.0
            successful_snapshots = []
            for s in results:
                has_error = "error" in (s.snapshot_data or {})
                features = s.features_learned or []
                if has_error:
                    failed_devices += 1
                else:
                    ok_devices += 1
                    successful_snapshots.append(s)
                total_duration += s.duration_seconds or 0
                per_device.append({
                    "hostname": dev_map.get(s.device_id, s.device_id[:8]),
                    "features": len(features),
                    "ok": not has_error,
                })

            await _write_status(db, {
                "running": False,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "result": "ok" if failed_devices == 0 else "partial",
                "devices_total": len(results),
                "devices_ok": ok_devices,
                "devices_failed": failed_devices,
                "per_device": per_device,
                "duration": round(total_duration, 1),
            })

            # Auto-trigger the LangGraph pipeline for each successful snapshot
            if successful_snapshots:
                log.info("pipeline_auto_trigger", count=len(successful_snapshots))
                from agents.graph import run_pipeline
                from services.correlation import (
                    apply_correlation,
                    create_incident_approvals,
                    generate_incident_remediations,
                )

                from services.snapshot_engine import get_snapshot_diff

                # In multi-device mode, defer BOTH per-device Sonnet remediation
                # AND approval/Jira/Slack so the correlation step can collapse
                # cascade duplicates into one incident first. Then we run a
                # single Sonnet call per incident root, and a single approval
                # per incident — instead of N copies of each.
                multi_device = len(successful_snapshots) > 1
                completed_snapshot_ids: list[str] = []

                for snap in successful_snapshots:
                    try:
                        hostname = dev_map.get(snap.device_id, "unknown")
                        # Load device for platform info
                        dev_result2 = await db.execute(
                            select(Device).where(Device.id == snap.device_id)
                        )
                        dev = dev_result2.scalar_one_or_none()
                        platform = dev.platform if dev else "unknown"

                        # Compute diff for change-aware analysis
                        diff_result = await get_snapshot_diff(db, snap.id)
                        snapshot_diff = diff_result.get("changes", {})

                        await run_pipeline(
                            db=db,
                            snapshot_id=snap.id,
                            device_id=snap.device_id,
                            device_hostname=hostname,
                            device_platform=platform,
                            raw_snapshot=snap.snapshot_data,
                            snapshot_diff=snapshot_diff,
                            create_approvals=not multi_device,
                            defer_remediation=multi_device,
                        )
                        completed_snapshot_ids.append(snap.id)
                        log.info("pipeline_auto_complete", hostname=hostname)
                    except Exception as pipe_err:
                        log.error("pipeline_auto_failed",
                                  hostname=dev_map.get(snap.device_id, snap.device_id[:8]),
                                  error=str(pipe_err))

                # Cross-device correlation → per-incident Sonnet → per-incident
                # approval/Jira. Skipped for single-device runs (no cascade).
                if multi_device and completed_snapshot_ids:
                    try:
                        incidents = await apply_correlation(db, completed_snapshot_ids)
                        await generate_incident_remediations(db, incidents)
                        await create_incident_approvals(db, incidents)
                        await db.commit()
                    except Exception as corr_err:
                        log.error("correlation_failed", error=str(corr_err))
        except Exception as e:
            log.error("background_snapshot_failed", error=str(e))
            await _write_status(db, {
                "running": False,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "result": "error",
                "error": str(e),
            })


@router.get("/status")
async def snapshot_status(db: AsyncSession = Depends(get_db)):
    """Return current snapshot run status.

    If a snapshot has been 'running' for more than 30 minutes, it is
    assumed to have crashed (e.g. container restart) and is auto-reset.
    """
    status = await _read_status(db)
    if status.get("running") and status.get("started_at"):
        started = datetime.fromisoformat(status["started_at"])
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        if elapsed > 1800:  # 30 minutes
            log.warning("snapshot_stale_reset", elapsed=elapsed)
            status = {
                "running": False,
                "started_at": status["started_at"],
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "result": "error",
                "error": "Snapshot timed out (exceeded 30 minutes)",
            }
            await _write_status(db, status)
    return status


@router.delete("/status")
async def clear_snapshot_status(db: AsyncSession = Depends(get_db)):
    """Clear the last-run snapshot status (does not affect actual snapshot rows).

    Refuses if a snapshot is currently running so the live progress view isn't lost.
    """
    current = await _read_status(db)
    if current.get("running"):
        raise HTTPException(status_code=409, detail="Snapshot is currently running")
    await _write_status(db, {"running": False})
    return {"cleared": True}


async def _wait_then_run_snapshot(device_id: str | None) -> None:
    """Wait for any in-progress snapshot to finish, then run this one.

    Replaces the old 409-Conflict-on-busy behaviour. Manual or scheduled
    snapshot requests are now queued (well, serialised — no real queue is
    needed since most callers only stack 1 deep) instead of dropped.
    """
    poll_interval = 5
    max_wait = 1800  # 30 min hard cap
    waited = 0
    while waited < max_wait:
        async with async_session() as db:
            status = await _read_status(db)
        if not status.get("running"):
            break
        await asyncio.sleep(poll_interval)
        waited += poll_interval
    if waited >= max_wait:
        log.warning("queued_snapshot_abandoned", device_id=device_id, waited=waited)
        return
    await _run_snapshot_background(device_id)


@router.post("", response_model=list[SnapshotRead])
async def trigger_snapshot(
    body: SnapshotTrigger | None = None,
    db: AsyncSession = Depends(get_db),
):
    device_id = body.device_id if body else None

    # If one is already running, queue ours behind it (no 409). Polls every
    # 5s until the in-progress run finishes, then starts the new one. The
    # response returns immediately either way.
    status = await _read_status(db)
    if status.get("running"):
        log.info("snapshot_queued", device_id=device_id, current_device=status.get("current_device"))
        asyncio.create_task(_wait_then_run_snapshot(device_id))
        return []

    asyncio.create_task(_run_snapshot_background(device_id))
    return []


@router.get("", response_model=list[SnapshotRead])
async def list_snapshots(
    device_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    return await snapshot_engine.list_snapshots(db, device_id=device_id, limit=limit, offset=offset)


@router.get("/{snapshot_id}", response_model=SnapshotDetail)
async def get_snapshot(snapshot_id: str, db: AsyncSession = Depends(get_db)):
    snapshot = await snapshot_engine.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


@router.delete("/{snapshot_id}")
async def delete_snapshot(snapshot_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a snapshot and all linked findings, recommendations, approvals, and agent runs."""
    from db.tables import AgentRun, Approval, Finding, Recommendation, Snapshot

    snapshot = await snapshot_engine.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    # Delete linked findings → recommendations → approvals
    findings = await db.execute(select(Finding).where(Finding.snapshot_id == snapshot_id))
    for f in findings.scalars().all():
        recs = await db.execute(select(Recommendation).where(Recommendation.finding_id == f.id))
        for r in recs.scalars().all():
            apprs = await db.execute(select(Approval).where(Approval.recommendation_id == r.id))
            for a in apprs.scalars().all():
                await db.delete(a)
            await db.delete(r)
        await db.delete(f)

    # Delete agent runs
    runs = await db.execute(select(AgentRun).where(AgentRun.snapshot_id == snapshot_id))
    for run in runs.scalars().all():
        await db.delete(run)

    await db.delete(snapshot)
    await db.commit()

    # Clean vector store
    from db.vector import delete_by_snapshot
    delete_by_snapshot(snapshot_id)

    return {"deleted": snapshot_id}


class BulkDeleteRequest(BaseModel):
    ids: list[str]


@router.post("/bulk-delete")
async def bulk_delete_snapshots(body: BulkDeleteRequest, db: AsyncSession = Depends(get_db)):
    """Delete a set of snapshots (and their linked findings/recommendations/approvals/agent runs)."""
    from db.tables import AgentRun, Approval, Finding, Recommendation, Snapshot
    from db.vector import delete_by_snapshot

    if not body.ids:
        return {"deleted": [], "missing": []}

    result = await db.execute(select(Snapshot).where(Snapshot.id.in_(body.ids)))
    found = {s.id: s for s in result.scalars().all()}
    missing = [i for i in body.ids if i not in found]

    for sid, snapshot in found.items():
        findings = await db.execute(select(Finding).where(Finding.snapshot_id == sid))
        for f in findings.scalars().all():
            recs = await db.execute(select(Recommendation).where(Recommendation.finding_id == f.id))
            for r in recs.scalars().all():
                apprs = await db.execute(select(Approval).where(Approval.recommendation_id == r.id))
                for a in apprs.scalars().all():
                    await db.delete(a)
                await db.delete(r)
            await db.delete(f)
        runs = await db.execute(select(AgentRun).where(AgentRun.snapshot_id == sid))
        for run in runs.scalars().all():
            await db.delete(run)
        await db.delete(snapshot)

    await db.commit()

    for sid in found:
        delete_by_snapshot(sid)

    return {"deleted": list(found.keys()), "missing": missing}


@router.delete("")
async def delete_all_snapshots(db: AsyncSession = Depends(get_db)):
    """Delete ALL snapshots and all linked data."""
    from db.tables import AgentRun, Approval, Finding, Recommendation, Snapshot

    # Clear all approvals → recommendations → findings → agent_runs → snapshots
    await db.execute(select(Approval))  # warm cache
    for table in [Approval, Recommendation, Finding, AgentRun, Snapshot]:
        result = await db.execute(select(table))
        for row in result.scalars().all():
            await db.delete(row)

    await db.commit()

    # Wipe the entire vector collection
    try:
        from db.chromadb import chroma_client
        chroma_client.delete_collection("historical_findings")
    except Exception:
        pass

    return {"deleted": "all"}


@router.get("/{snapshot_id}/diff", response_model=SnapshotDiff)
async def get_snapshot_diff(snapshot_id: str, db: AsyncSession = Depends(get_db)):
    diff = await snapshot_engine.get_snapshot_diff(db, snapshot_id)
    if "error" in diff:
        raise HTTPException(status_code=404, detail=diff["error"])
    return diff
