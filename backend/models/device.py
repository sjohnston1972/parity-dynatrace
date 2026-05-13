"""Pydantic schemas for devices."""

from datetime import datetime

from pydantic import BaseModel


class DeviceBase(BaseModel):
    hostname: str
    management_ip: str
    platform: str
    device_type: str
    grafana_source: str | None = None
    tags: dict | None = None


class DeviceCreate(DeviceBase):
    pass


class DeviceRead(DeviceBase):
    id: str
    first_seen: datetime
    last_seen: datetime
    last_refreshed: datetime | None = None

    model_config = {"from_attributes": True}
