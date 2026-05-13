"""Pydantic schemas for findings."""

from datetime import datetime

from pydantic import BaseModel, Field


class FindingRead(BaseModel):
    id: str
    # snapshot_id / device_id are NULL for findings ingested from external
    # sources (Dynatrace MCP). source + external_id below distinguish them.
    snapshot_id: str | None = None
    device_id: str | None = None
    source: str = "pyats"
    external_id: str | None = None
    category: str
    severity: str
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    description: str
    affected_entity: str
    evidence: dict | None = None
    requires_remediation: bool
    agent_model: str | None = None
    tokens_used: int | None = None
    incident_id: str | None = None
    is_root_cause: bool = False
    correlation_reason: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
