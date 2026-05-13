"""Topology view data endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from db.tables import Setting
from services.topology import build_topology

router = APIRouter(prefix="/topology", tags=["topology"])

LAYOUT_KEY_PREFIX = "topology_layout"
VALID_VIEWS = {"bgp", "l2"}


class TopologyLayout(BaseModel):
    positions: dict = {}
    zones: list = []


@router.get("")
async def get_topology(db: AsyncSession = Depends(get_db)):
    return await build_topology(db)


@router.get("/layout/{view}")
async def get_layout(view: str, db: AsyncSession = Depends(get_db)):
    if view not in VALID_VIEWS:
        view = "bgp"
    key = f"{LAYOUT_KEY_PREFIX}:{view}"
    result = await db.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    if not row:
        # Fall back to legacy key for BGP view
        if view == "bgp":
            result = await db.execute(select(Setting).where(Setting.key == LAYOUT_KEY_PREFIX))
            row = result.scalar_one_or_none()
        if not row:
            return {"positions": {}, "zones": []}
    return row.value


@router.put("/layout/{view}")
async def save_layout(view: str, layout: TopologyLayout, db: AsyncSession = Depends(get_db)):
    if view not in VALID_VIEWS:
        view = "bgp"
    key = f"{LAYOUT_KEY_PREFIX}:{view}"
    result = await db.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    data = layout.model_dump()
    if row:
        row.value = data
    else:
        db.add(Setting(key=key, value=data))
    await db.commit()
    return data


# Legacy endpoints for backwards compatibility
@router.get("/layout")
async def get_layout_legacy(db: AsyncSession = Depends(get_db)):
    return await get_layout("bgp", db)


@router.put("/layout")
async def save_layout_legacy(layout: TopologyLayout, db: AsyncSession = Depends(get_db)):
    return await save_layout("bgp", layout, db)
