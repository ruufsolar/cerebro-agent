from cerebro.db import models  # noqa: F401
from cerebro.db.base import Base


def test_foundation_schema_contains_auditable_agent_state() -> None:
    assert set(Base.metadata.tables) == {
        "agent_run",
        "conversation",
        "feedback",
        "message",
        "slack_event",
        "slack_output",
        "tool_call",
    }
