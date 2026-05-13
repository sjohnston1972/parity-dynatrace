"""Pydantic schemas for remediation recommendations."""

from datetime import datetime

from pydantic import BaseModel


class RecommendationRead(BaseModel):
    id: str
    finding_id: str
    action_description: str
    commands: list[dict]
    rollback_commands: list[dict] | None = None
    risk_level: str
    reasoning: str
    agent_model: str | None = None
    tokens_used: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
