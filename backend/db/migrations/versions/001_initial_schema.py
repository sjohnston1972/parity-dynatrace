"""Initial schema — all core tables.

Revision ID: 001
Revises: None
Create Date: 2026-03-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("hostname", sa.String(255), unique=True, nullable=False),
        sa.Column("management_ip", sa.String(45), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("device_type", sa.String(50), nullable=False),
        sa.Column("grafana_source", sa.String(255)),
        sa.Column("tags", JSONB, server_default="{}"),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("last_refreshed", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("devices.id"),
            nullable=False,
        ),
        sa.Column("snapshot_data", JSONB, nullable=False),
        sa.Column("features_learned", ARRAY(sa.String)),
        sa.Column("triggered_by", sa.String(50)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("duration_seconds", sa.Float),
    )

    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey("snapshots.id"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("devices.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("affected_entity", sa.String(255), nullable=False),
        sa.Column("evidence", JSONB),
        sa.Column("requires_remediation", sa.Boolean, default=False),
        sa.Column("agent_model", sa.String(100)),
        sa.Column("tokens_used", sa.Integer),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "finding_id",
            sa.String(36),
            sa.ForeignKey("findings.id"),
            nullable=False,
        ),
        sa.Column("action_description", sa.Text, nullable=False),
        sa.Column("commands", JSONB, nullable=False),
        sa.Column("rollback_commands", JSONB),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("reasoning", sa.Text, nullable=False),
        sa.Column("agent_model", sa.String(100)),
        sa.Column("tokens_used", sa.Integer),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "recommendation_id",
            sa.String(36),
            sa.ForeignKey("recommendations.id"),
            unique=True,
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_via", sa.String(20)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("execution_result", JSONB),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey("snapshots.id"),
            nullable=False,
        ),
        sa.Column("graph_state", JSONB),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("total_tokens_used", sa.Integer),
        sa.Column("models_used", JSONB),
        sa.Column("errors", JSONB),
    )


def downgrade() -> None:
    op.drop_table("agent_runs")
    op.drop_table("approvals")
    op.drop_table("recommendations")
    op.drop_table("findings")
    op.drop_table("snapshots")
    op.drop_table("devices")
