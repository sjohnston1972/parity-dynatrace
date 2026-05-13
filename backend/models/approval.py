"""Pydantic schemas for approvals."""

from datetime import datetime

from pydantic import BaseModel


class ApprovalAction(BaseModel):
    approved_by: str | None = None
    approved_via: str | None = None  # web, slack, jira
    notes: str | None = None


class FindingContext(BaseModel):
    id: str
    title: str
    severity: str
    affected_entity: str | None = None
    agent_model: str | None = None


class RecommendationContext(BaseModel):
    id: str
    action: str | None = None
    action_description: str | None = None
    commands: list | None = None
    rollback_commands: list | None = None
    risk_level: str | None = None
    reasoning: str | None = None
    agent_model: str | None = None


class DeviceContext(BaseModel):
    id: str
    hostname: str


class ApprovalDetail(BaseModel):
    id: str
    recommendation_id: str
    status: str
    approved_by: str | None = None
    approved_via: str | None = None
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    execution_result: dict | None = None
    notes: str | None = None
    jira_key: str | None = None
    jira_url: str | None = None
    created_at: datetime
    finding: FindingContext | None = None
    recommendation: RecommendationContext | None = None
    device: DeviceContext | None = None
