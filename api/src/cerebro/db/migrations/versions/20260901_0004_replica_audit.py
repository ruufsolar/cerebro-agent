"""Add safe replica-query audit fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0004"
down_revision: str | Sequence[str] | None = "20260901_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tool_call", sa.Column("query_fingerprint", sa.Text(), nullable=True))
    op.add_column(
        "tool_call",
        sa.Column("referenced_relations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("tool_call", sa.Column("row_count", sa.Integer(), nullable=True))
    op.add_column("tool_call", sa.Column("truncated", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_call", "truncated")
    op.drop_column("tool_call", "row_count")
    op.drop_column("tool_call", "referenced_relations")
    op.drop_column("tool_call", "query_fingerprint")
