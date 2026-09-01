"""Add Agents SDK run metadata.

Revision ID: 20260901_0003
Revises: 20260831_0002
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0003"
down_revision: str | Sequence[str] | None = "20260831_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_run", sa.Column("knowledge_version", sa.Text(), nullable=True))
    op.add_column("agent_run", sa.Column("completion_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_run", "completion_reason")
    op.drop_column("agent_run", "knowledge_version")
