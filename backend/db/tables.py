"""SQLAlchemy ORM table definitions."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.postgres import Base


def new_id() -> str:
    return str(uuid.uuid4())


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    hostname: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    management_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False)
    grafana_source: Mapped[str | None] = mapped_column(String(255))
    tags: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # last_seen is the timestamp of the most recent telemetry point Grafana
    # has for this device — set explicitly by the inventory service.
    # No onupdate trigger: row updates must NOT clobber this signal.
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_refreshed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="device")
    findings: Mapped[list["Finding"]] = relationship(back_populates="device")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id"), nullable=False
    )
    snapshot_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    features_learned: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    triggered_by: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    # The per-device baseline marker. Exactly one snapshot per device is
    # golden at any given time; others compare against it via
    # get_snapshot_diff(mode='golden'). Manually blessed via the bless
    # API, or auto-re-blessed after a verified remediation.
    is_golden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    device: Mapped["Device"] = relationship(back_populates="snapshots")
    findings: Mapped[list["Finding"]] = relationship(back_populates="snapshot")
    agent_runs: Mapped[list["AgentRun"]] = relationship(back_populates="snapshot")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # snapshot_id and device_id are NULL for findings ingested from external
    # sources like Dynatrace (no pyATS snapshot involved). source/external_id
    # below distinguish ingestion paths — see migration 006.
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("snapshots.id"), nullable=True
    )
    device_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("devices.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="pyats")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    affected_entity: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    requires_remediation: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_model: Mapped[str | None] = mapped_column(String(100))
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    # Correlation: findings sharing an incident_id describe the same network event
    # observed from multiple devices. is_root_cause marks the primary one.
    incident_id: Mapped[str | None] = mapped_column(String(36), index=True)
    is_root_cause: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    correlation_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    snapshot: Mapped["Snapshot"] = relationship(back_populates="findings")
    device: Mapped["Device"] = relationship(back_populates="findings")
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="finding"
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    finding_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("findings.id"), nullable=False
    )
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    commands: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    rollback_commands: Mapped[list[dict] | None] = mapped_column(JSONB)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    agent_model: Mapped[str | None] = mapped_column(String(100))
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    finding: Mapped["Finding"] = relationship(back_populates="recommendations")
    approval: Mapped["Approval | None"] = relationship(back_populates="recommendation")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recommendation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recommendations.id"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending, approved, denied, executed, failed, expired
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_via: Mapped[str | None] = mapped_column(String(20))  # web, slack, jira
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_result: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    jira_issue_key: Mapped[str | None] = mapped_column(String(50))
    jira_issue_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    recommendation: Mapped["Recommendation"] = relationship(back_populates="approval")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SnapshotSchedule(Base):
    __tablename__ = "snapshot_schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False)
    device_ids: Mapped[list[str]] = mapped_column(ARRAY(String(36)), nullable=False, default=list)
    features: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("snapshots.id"), nullable=False
    )
    graph_state: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_tokens_used: Mapped[int | None] = mapped_column(Integer)
    models_used: Mapped[dict | None] = mapped_column(JSONB)
    errors: Mapped[dict | None] = mapped_column(JSONB)

    snapshot: Mapped["Snapshot"] = relationship(back_populates="agent_runs")
