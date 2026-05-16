"""Pydantic schemas for findings."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# Phrases Davis Copilot returns when it rejects an ungrounded prompt.
# These rejections were getting persisted to evidence.davis_assessment
# and shown verbatim in the UI as if they were the Davis verdict —
# misleading the operator. We strip them on read so the empty-state
# message ("No Davis Copilot assessment attached") shows instead.
# The new prompt + retry in dynatrace_reasoner.py prevents this for
# newly-raised findings; this strip cleans up historical data.
_DAVIS_REJECTION_MARKERS = (
    "valid question",
    "rephrase",
    "additional context",
    "more information",
    "doesn't seem",
    "does not seem",
)


def _is_davis_rejection(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _DAVIS_REJECTION_MARKERS)


def strip_rejection_assessment(evidence: dict | None) -> dict | None:
    """Drop ``davis_assessment`` when it contains a Davis rejection.

    Returns a shallow copy so the underlying ORM JSONB object is not
    mutated. Used by the FindingRead validator and by the manual
    incidents/list projection.
    """
    if not isinstance(evidence, dict):
        return evidence
    da = evidence.get("davis_assessment")
    if isinstance(da, str) and _is_davis_rejection(da):
        return {k: v for k, v in evidence.items() if k != "davis_assessment"}
    return evidence


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
    # Set to True when a finding is returned by ``include_recent_hours``
    # but its symptom is no longer present in the latest snapshot — i.e.
    # auto-resolved / superseded. UI uses this to badge the row.
    stale: bool = False

    model_config = {"from_attributes": True}

    @field_validator("evidence", mode="before")
    @classmethod
    def _strip_rejection(cls, v):
        return strip_rejection_assessment(v)
