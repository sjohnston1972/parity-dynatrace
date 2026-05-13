"""Pydantic schemas for snapshot schedules."""

from datetime import datetime

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator


class ScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    cron_expr: str = Field(..., min_length=1, max_length=64)
    device_ids: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("cron_expr")
    @classmethod
    def _valid_cron(cls, v: str) -> str:
        try:
            CronTrigger.from_crontab(v.strip())
        except Exception as exc:
            raise ValueError(f"Invalid cron expression: {exc}") from exc
        return v.strip()


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    cron_expr: str | None = Field(default=None, min_length=1, max_length=64)
    device_ids: list[str] | None = None
    features: list[str] | None = None
    enabled: bool | None = None

    @field_validator("cron_expr")
    @classmethod
    def _valid_cron(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            CronTrigger.from_crontab(v.strip())
        except Exception as exc:
            raise ValueError(f"Invalid cron expression: {exc}") from exc
        return v.strip()


class ScheduleRead(BaseModel):
    id: str
    name: str
    cron_expr: str
    device_ids: list[str]
    features: list[str]
    enabled: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_result: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
