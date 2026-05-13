"""Snapshot-schedule endpoints — CRUD plus run-now."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from models.schedule import ScheduleCreate, ScheduleRead, ScheduleUpdate
from services import schedule_service

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _attach_next_run(read_obj: ScheduleRead) -> ScheduleRead:
    next_run = schedule_service.get_next_run_time(read_obj.id)
    if next_run is not None:
        read_obj.next_run_at = next_run
    return read_obj


@router.get("", response_model=list[ScheduleRead])
async def list_all(db: AsyncSession = Depends(get_db)):
    rows = await schedule_service.list_schedules(db)
    out = [ScheduleRead.model_validate(r) for r in rows]
    return [_attach_next_run(o) for o in out]


@router.post("", response_model=ScheduleRead, status_code=201)
async def create(body: ScheduleCreate, db: AsyncSession = Depends(get_db)):
    sched = await schedule_service.create_schedule(
        db,
        name=body.name,
        cron_expr=body.cron_expr,
        device_ids=body.device_ids,
        features=body.features,
        enabled=body.enabled,
    )
    return _attach_next_run(ScheduleRead.model_validate(sched))


@router.get("/{schedule_id}", response_model=ScheduleRead)
async def retrieve(schedule_id: str, db: AsyncSession = Depends(get_db)):
    sched = await schedule_service.get_schedule(db, schedule_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _attach_next_run(ScheduleRead.model_validate(sched))


@router.patch("/{schedule_id}", response_model=ScheduleRead)
async def update(schedule_id: str, body: ScheduleUpdate, db: AsyncSession = Depends(get_db)):
    fields = body.model_dump(exclude_unset=True)
    sched = await schedule_service.update_schedule(db, schedule_id, **fields)
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _attach_next_run(ScheduleRead.model_validate(sched))


@router.delete("/{schedule_id}")
async def remove(schedule_id: str, db: AsyncSession = Depends(get_db)):
    ok = await schedule_service.delete_schedule(db, schedule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"deleted": schedule_id}


@router.post("/{schedule_id}/run")
async def run_now(schedule_id: str, db: AsyncSession = Depends(get_db)):
    sched = await schedule_service.get_schedule(db, schedule_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    asyncio.create_task(schedule_service.run_schedule_now(schedule_id))
    return {"started": schedule_id}
