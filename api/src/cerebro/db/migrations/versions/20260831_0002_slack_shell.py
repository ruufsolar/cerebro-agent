"""Add durable Slack shell state.

Revision ID: 20260831_0002
Revises: 20260828_0001
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0002"
down_revision: str | Sequence[str] | None = "20260828_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "slack_event",
        sa.Column(
            "disposition",
            sa.Text(),
            server_default="received",
            nullable=False,
        ),
    )
    op.create_index("ix_slack_event_disposition", "slack_event", ["disposition"])
    op.add_column(
        "slack_output",
        sa.Column(
            "kind",
            sa.Text(),
            server_default="investigation",
            nullable=False,
        ),
    )
    op.alter_column("slack_output", "agent_run_id", nullable=True)
    op.create_unique_constraint("uq_agent_run_trigger_message", "agent_run", ["trigger_message_id"])


def downgrade() -> None:
    op.drop_constraint("uq_agent_run_trigger_message", "agent_run", type_="unique")
    op.alter_column("slack_output", "agent_run_id", nullable=False)
    op.drop_column("slack_output", "kind")
    op.drop_index("ix_slack_event_disposition", table_name="slack_event")
    op.drop_column("slack_event", "disposition")
