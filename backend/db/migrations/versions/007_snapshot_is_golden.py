"""Add is_golden flag to snapshots — the per-device baseline marker.

Golden snapshots are the reference state ("what should this device look
like right now?") that the reasoner diffs against in *addition* to the
immediately-previous snapshot. The verifier uses the golden diff after
remediation to declare a finding truly resolved — empty rolling-diff
just means nothing changed in the last interval, but empty golden-diff
means we're back to the sanctioned baseline.

Bootstrap: on upgrade we bless the oldest features-learned snapshot per
device so existing data has a baseline to compare against. Subsequent
snapshots become golden either manually (POST /snapshots/{id}/bless)
or automatically after a verified remediation.

Revision ID: 007
Revises: 006
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "snapshots",
        sa.Column(
            "is_golden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index("ix_snapshots_is_golden", "snapshots", ["is_golden"])
    op.create_index(
        "ix_snapshots_device_golden",
        "snapshots",
        ["device_id", "is_golden"],
        postgresql_where=sa.text("is_golden = true"),
    )

    # Bootstrap: bless the oldest features-learned snapshot per device.
    # This gives every existing device a baseline without operator action,
    # and subsequent reasoning has something meaningful to diff against.
    op.execute(
        """
        UPDATE snapshots s
           SET is_golden = true
          FROM (
              SELECT DISTINCT ON (device_id) id
                FROM snapshots
               WHERE array_length(features_learned, 1) > 0
               ORDER BY device_id, created_at ASC
          ) AS firsts
         WHERE s.id = firsts.id
        """
    )


def downgrade():
    op.drop_index("ix_snapshots_device_golden", table_name="snapshots")
    op.drop_index("ix_snapshots_is_golden", table_name="snapshots")
    op.drop_column("snapshots", "is_golden")
