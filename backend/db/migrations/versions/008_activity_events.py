"""Persistent activity_events table - the durable backup behind
services.activity.ActivityBus so the Pipeline page's Reasoner &
Engine Status panel survives backend rebuilds.

Bus stays the realtime path (in-memory + SSE); only completed and
failed events write here. On startup the bus calls hydrate_from_db
to backfill the in-memory ring.

Revision ID: 008
Revises: 007
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bus_id", sa.String(32), nullable=False),
        sa.Column("pipeline_run", sa.String(64), nullable=False),
        sa.Column("node", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("model_tier", sa.String(16), nullable=False),
        sa.Column("device", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_activity_events_completed_at",
        "activity_events",
        ["completed_at"],
    )
    op.create_index(
        "ix_activity_events_pipeline_run",
        "activity_events",
        ["pipeline_run"],
    )
    op.create_index(
        "ix_activity_events_bus_id",
        "activity_events",
        ["bus_id"],
    )


def downgrade():
    op.drop_index("ix_activity_events_bus_id", table_name="activity_events")
    op.drop_index("ix_activity_events_pipeline_run", table_name="activity_events")
    op.drop_index("ix_activity_events_completed_at", table_name="activity_events")
    op.drop_table("activity_events")
