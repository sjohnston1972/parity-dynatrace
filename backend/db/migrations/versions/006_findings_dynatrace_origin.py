"""Allow Dynatrace-origin findings: nullable snapshot_id/device_id, add source.

pyATS-origin findings always have a (snapshot_id, device_id) pair. Findings
ingested from Dynatrace (e.g. Davis problems) may have neither — a synthetic
monitor problem has no device, and no Parity-side snapshot is involved.

Revision ID: 006
Revises: 005
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    # Relax FK columns to NULL-allowed
    op.alter_column("findings", "snapshot_id", existing_type=sa.String(36), nullable=True)
    op.alter_column("findings", "device_id", existing_type=sa.String(36), nullable=True)

    # New 'source' enum-ish text column distinguishes ingestion paths.
    # Backfill existing rows to 'pyats'.
    op.add_column(
        "findings",
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'pyats'"),
        ),
    )
    op.create_index("ix_findings_source", "findings", ["source"])

    # Dedup key for Dynatrace problems: same problemId should not produce a
    # second finding on re-ingest. Use a string column indexed (unique would
    # be too strict — different sources could collide).
    op.add_column(
        "findings",
        sa.Column("external_id", sa.String(255), nullable=True),
    )
    op.create_index("ix_findings_external_id", "findings", ["external_id"])


def downgrade():
    op.drop_index("ix_findings_external_id", "findings")
    op.drop_column("findings", "external_id")
    op.drop_index("ix_findings_source", "findings")
    op.drop_column("findings", "source")
    op.alter_column("findings", "device_id", existing_type=sa.String(36), nullable=False)
    op.alter_column("findings", "snapshot_id", existing_type=sa.String(36), nullable=False)
