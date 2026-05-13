"""Add incident correlation fields to findings.

Revision ID: 005
Revises: 004
Create Date: 2026-05-10
"""
from alembic import op
import sqlalchemy as sa


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("findings", sa.Column("incident_id", sa.String(36), nullable=True))
    op.add_column("findings", sa.Column("is_root_cause", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("findings", sa.Column("correlation_reason", sa.Text(), nullable=True))
    op.create_index("ix_findings_incident_id", "findings", ["incident_id"])


def downgrade():
    op.drop_index("ix_findings_incident_id", "findings")
    op.drop_column("findings", "correlation_reason")
    op.drop_column("findings", "is_root_cause")
    op.drop_column("findings", "incident_id")
