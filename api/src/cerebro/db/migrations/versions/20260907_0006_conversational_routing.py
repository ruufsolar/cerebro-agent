"""Add the routed request kind to agent runs.

Revision ID: 20260907_0006
Revises: 20260902_0005
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0006"
down_revision: str | Sequence[str] | None = "20260902_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_run",
        sa.Column(
            "request_kind",
            sa.Text(),
            server_default="payment_identification",
            nullable=False,
        ),
    )
    op.create_index("ix_agent_run_request_kind", "agent_run", ["request_kind"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_request_kind", table_name="agent_run")
    op.drop_column("agent_run", "request_kind")
