"""Pydantic schemas for snapshots."""

from datetime import datetime

from pydantic import BaseModel


class SnapshotTrigger(BaseModel):
    device_id: str | None = None  # None = all devices


class SnapshotRead(BaseModel):
    id: str
    device_id: str
    features_learned: list[str] | None = None
    triggered_by: str | None = None
    created_at: datetime
    duration_seconds: float | None = None
    is_golden: bool = False

    model_config = {"from_attributes": True}


class SnapshotDetail(SnapshotRead):
    snapshot_data: dict


class SnapshotDiff(BaseModel):
    snapshot_id: str
    previous_snapshot_id: str | None
    changes: dict
