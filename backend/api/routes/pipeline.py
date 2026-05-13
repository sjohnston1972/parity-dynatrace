"""Pipeline execution and status endpoints."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.graph import run_pipeline
from db.postgres import get_db
from db.tables import AgentRun, Snapshot
from services.activity import activity_bus

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class PipelineRunRequest(BaseModel):
    snapshot_id: str


class PipelineRunResult(BaseModel):
    snapshot_id: str
    device_hostname: str
    findings_count: int
    recommendations_count: int
    escalated: bool
    errors: list[str]
    tokens_used: dict


@router.post("/run", response_model=PipelineRunResult)
async def run_pipeline_endpoint(
    body: PipelineRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger the LangGraph pipeline for a snapshot."""
    result = await db.execute(select(Snapshot).where(Snapshot.id == body.snapshot_id))
    snapshot = result.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    # Load the device
    from db.tables import Device

    result = await db.execute(select(Device).where(Device.id == snapshot.device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found for snapshot")

    # Compute diff against previous snapshot for change detection
    from services.snapshot_engine import get_snapshot_diff

    diff_result = await get_snapshot_diff(db, snapshot.id)
    snapshot_diff = diff_result.get("changes", {})

    final_state = await run_pipeline(
        db=db,
        snapshot_id=snapshot.id,
        device_id=device.id,
        device_hostname=device.hostname,
        device_platform=device.platform,
        raw_snapshot=snapshot.snapshot_data,
        snapshot_diff=snapshot_diff,
    )

    return PipelineRunResult(
        snapshot_id=snapshot.id,
        device_hostname=device.hostname,
        findings_count=len(final_state.get("findings", [])),
        recommendations_count=len(final_state.get("recommendations", [])),
        escalated=final_state.get("escalate_to_opus", False),
        errors=final_state.get("errors", []),
        tokens_used=final_state.get("tokens_used", {}),
    )


@router.get("/status")
async def pipeline_status(db: AsyncSession = Depends(get_db)):
    """Current pipeline status — most recent runs."""
    result = await db.execute(
        select(AgentRun).order_by(AgentRun.started_at.desc()).limit(10)
    )
    runs = result.scalars().all()
    return [
        {
            "id": r.id,
            "snapshot_id": r.snapshot_id,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "total_tokens_used": r.total_tokens_used,
            "models_used": r.models_used,
            "errors": r.errors,
            "state": r.graph_state,
        }
        for r in runs
    ]


@router.get("/stats")
async def pipeline_stats(db: AsyncSession = Depends(get_db)):
    """Aggregate token usage and run statistics."""
    result = await db.execute(
        select(
            func.count(AgentRun.id).label("total_runs"),
            func.sum(AgentRun.total_tokens_used).label("total_tokens"),
            func.avg(AgentRun.total_tokens_used).label("avg_tokens_per_run"),
        )
    )
    row = result.one()
    return {
        "total_runs": row.total_runs or 0,
        "total_tokens": row.total_tokens or 0,
        "avg_tokens_per_run": round(row.avg_tokens_per_run or 0, 1),
    }


@router.get("/activity")
async def pipeline_activity():
    """Snapshot of current and recent pipeline activity."""
    return activity_bus.get_snapshot()


@router.get("/activity/stream")
async def pipeline_activity_stream():
    """SSE stream of real-time pipeline activity events."""
    import json

    async def event_generator():
        q = activity_bus.subscribe()
        try:
            # Send initial state
            snapshot = activity_bus.get_snapshot()
            yield f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"event: activity\ndata: {json.dumps(event.to_dict())}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            activity_bus.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
