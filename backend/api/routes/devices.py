"""Device inventory endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from db.tables import Setting, Snapshot
from models.device import DeviceRead
from services import inventory

router = APIRouter(prefix="/devices", tags=["devices"])


class UnmonitoredUpdate(BaseModel):
    interfaces: list[str]


@router.get("", response_model=list[DeviceRead])
async def list_devices(db: AsyncSession = Depends(get_db)):
    return await inventory.list_devices(db)


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(device_id: str, db: AsyncSession = Depends(get_db)):
    device = await inventory.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.get("/{device_id}/snapshot")
async def get_device_latest_snapshot(device_id: str, db: AsyncSession = Depends(get_db)):
    """Return the latest successful snapshot data for a device."""
    from sqlalchemy import func as sa_func
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.device_id == device_id)
        .where(sa_func.array_length(Snapshot.features_learned, 1) > 0)
        .order_by(Snapshot.created_at.desc())
        .limit(1)
    )
    snap = result.scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshots for this device")
    return {
        "id": snap.id,
        "device_id": snap.device_id,
        "snapshot_data": snap.snapshot_data,
        "features_learned": snap.features_learned,
        "created_at": snap.created_at.isoformat(),
        "duration_seconds": snap.duration_seconds,
    }


@router.get("/{device_id}/unmonitored")
async def get_unmonitored(device_id: str, db: AsyncSession = Depends(get_db)):
    """Return list of interface names marked as unmonitored for this device."""
    key = f"unmonitored:{device_id}"
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    return {"interfaces": setting.value.get("interfaces", []) if setting else []}


@router.put("/{device_id}/unmonitored")
async def set_unmonitored(
    device_id: str, body: UnmonitoredUpdate, db: AsyncSession = Depends(get_db)
):
    """Set the list of unmonitored interfaces for a device."""
    key = f"unmonitored:{device_id}"
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = {"interfaces": body.interfaces}
    else:
        db.add(Setting(key=key, value={"interfaces": body.interfaces}))
    await db.commit()
    return {"interfaces": body.interfaces}


@router.post("/refresh", response_model=list[DeviceRead])
async def refresh_devices(db: AsyncSession = Depends(get_db)):
    return await inventory.refresh_inventory(db)
