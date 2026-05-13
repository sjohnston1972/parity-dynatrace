"""Add Jira fields to approvals table.

Revision ID: 002
Revises: 001
Create Date: 2026-03-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("jira_issue_key", sa.String(50)))
    op.add_column("approvals", sa.Column("jira_issue_url", sa.String(500)))


def downgrade() -> None:
    op.drop_column("approvals", "jira_issue_url")
    op.drop_column("approvals", "jira_issue_key")
