"""Add runtime component heartbeats.

Revision ID: 20260902_0005
Revises: 20260901_0004
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0005"
down_revision: str | Sequence[str] | None = "20260901_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_heartbeat",
        sa.Column("component", sa.Text(), nullable=False),
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("detail_code", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("component"),
    )
    op.create_index("ix_runtime_heartbeat_last_seen", "runtime_heartbeat", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_runtime_heartbeat_last_seen", table_name="runtime_heartbeat")
    op.drop_table("runtime_heartbeat")
