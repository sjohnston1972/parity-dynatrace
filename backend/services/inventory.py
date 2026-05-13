"""Device inventory service — syncs Grafana devices into PostgreSQL."""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.tables import Device
from integrations.grafana import grafana_client

log = structlog.get_logger()


async def refresh_inventory(db: AsyncSession) -> list[Device]:
    """Pull devices from Grafana and upsert into PostgreSQL.

    last_refreshed = when we last synced the inventory list (system signal).
    last_seen      = timestamp of the most recent telemetry point Grafana has
                     for this device (per-device liveness signal).

    Returns the full list of devices after refresh.
    """
    discovered = await grafana_client.discover_devices()
    now = datetime.now(timezone.utc)

    for d in discovered:
        result = await db.execute(
            select(Device).where(Device.hostname == d["hostname"])
        )
        existing = result.scalar_one_or_none()
        # If Grafana didn't return a per-device timestamp, fall back to "now":
        # the device showed up in the inventory query, which means Telegraf
        # has at least some recent data for it.
        device_last_seen = d.get("last_seen") or now

        if existing:
            existing.management_ip = d["management_ip"]
            existing.platform = d["platform"]
            existing.device_type = d["device_type"]
            existing.grafana_source = d["grafana_source"]
            existing.tags = d["tags"]
            existing.last_seen = device_last_seen
            existing.last_refreshed = now
            log.info("device_updated", hostname=d["hostname"])
        else:
            device = Device(
                hostname=d["hostname"],
                management_ip=d["management_ip"],
                platform=d["platform"],
                device_type=d["device_type"],
                grafana_source=d["grafana_source"],
                tags=d["tags"],
                last_seen=device_last_seen,
                last_refreshed=now,
            )
            db.add(device)
            log.info("device_created", hostname=d["hostname"])

    await db.commit()

    result = await db.execute(select(Device).order_by(Device.hostname))
    return list(result.scalars().all())


async def list_devices(db: AsyncSession) -> list[Device]:
    result = await db.execute(select(Device).order_by(Device.hostname))
    return list(result.scalars().all())


async def get_device(db: AsyncSession, device_id: str) -> Device | None:
    result = await db.execute(select(Device).where(Device.id == device_id))
    return result.scalar_one_or_none()
