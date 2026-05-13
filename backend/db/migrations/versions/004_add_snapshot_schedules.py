"""Add snapshot_schedules table.

Revision ID: 004
Revises: 003
Create Date: 2026-04-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "snapshot_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("cron_expr", sa.String(64), nullable=False),
        sa.Column(
            "device_ids",
            sa.dialects.postgresql.ARRAY(sa.String(36)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "features",
            sa.dialects.postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_result", sa.String(32)),
        sa.Column("last_error", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("snapshot_schedules")
