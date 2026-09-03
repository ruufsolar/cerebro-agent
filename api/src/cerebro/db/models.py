from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cerebro.db.base import Base, TimestampMixin
from cerebro.db.enums import (
    ConversationState,
    DeliveryStatus,
    RunStatus,
    SlackEventDisposition,
    SlackOutputKind,
)


class SlackEvent(Base):
    """Raw event envelope retained for idempotency and bounded debugging."""

    __tablename__ = "slack_event"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slack_event_id: Mapped[str] = mapped_column(Text, unique=True)
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    disposition: Mapped[str] = mapped_column(Text, default=SlackEventDisposition.RECEIVED)
    received_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    processed_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_slack_event_received", text("received_at DESC")),
        Index("ix_slack_event_disposition", "disposition"),
    )


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversation"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slack_channel_id: Mapped[str] = mapped_column(Text)
    slack_thread_ts: Mapped[str] = mapped_column(Text)
    requester_slack_user_id: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, default=ConversationState.OPEN)
    latest_question: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "slack_channel_id", "slack_thread_ts", name="uq_conversation_slack_thread"
        ),
        Index("ix_conversation_state_updated", "state", text("updated_at DESC")),
    )


class Message(TimestampMixin, Base):
    __tablename__ = "message"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id"))
    slack_channel_id: Mapped[str] = mapped_column(Text)
    slack_message_ts: Mapped[str] = mapped_column(Text)
    slack_thread_ts: Mapped[str] = mapped_column(Text)
    sender_slack_user_id: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, default="text")
    text: Mapped[str | None] = mapped_column(Text)
    file_metadata: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    event_at: Mapped[datetime]

    __table_args__ = (
        UniqueConstraint("slack_channel_id", "slack_message_ts", name="uq_message_slack_identity"),
        Index("ix_message_conversation_event", "conversation_id", "event_at"),
    )


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_run"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id"))
    trigger_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("message.id"))
    status: Mapped[str] = mapped_column(Text, default=RunStatus.QUEUED)
    input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    steps: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    structured_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_message: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    knowledge_version: Mapped[str | None] = mapped_column(Text)
    completion_reason: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    turns: Mapped[int | None] = mapped_column(Integer)
    tool_calls: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    error_code: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("trigger_message_id", name="uq_agent_run_trigger_message"),
        Index("ix_agent_run_conversation_created", "conversation_id", text("created_at DESC")),
        Index("ix_agent_run_status", "status"),
    )


class ToolCall(Base):
    __tablename__ = "tool_call"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_run.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    query_fingerprint: Mapped[str | None] = mapped_column(Text)
    referenced_relations: Mapped[list[str] | None] = mapped_column(JSONB)
    row_count: Mapped[int | None] = mapped_column(Integer)
    truncated: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("agent_run_id", "sequence", name="uq_tool_call_run_sequence"),
        Index("ix_tool_call_run", "agent_run_id"),
    )


class SlackOutput(TimestampMixin, Base):
    __tablename__ = "slack_output"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id"))
    agent_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_run.id"))
    slack_channel_id: Mapped[str] = mapped_column(Text)
    slack_thread_ts: Mapped[str] = mapped_column(Text)
    slack_message_ts: Mapped[str | None] = mapped_column(Text, unique=True)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, default=SlackOutputKind.INVESTIGATION)
    status: Mapped[str] = mapped_column(Text, default=DeliveryStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None]

    __table_args__ = (Index("ix_slack_output_status", "status"),)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id"))
    agent_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_run.id"))
    slack_channel_id: Mapped[str] = mapped_column(Text)
    slack_message_ts: Mapped[str] = mapped_column(Text)
    slack_user_id: Mapped[str] = mapped_column(Text)
    reaction: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=text("now()")
    )

    __table_args__ = (
        UniqueConstraint(
            "slack_channel_id",
            "slack_message_ts",
            "slack_user_id",
            "reaction",
            name="uq_feedback_reaction",
        ),
        Index("ix_feedback_run", "agent_run_id"),
    )


class RuntimeHeartbeat(Base):
    """Non-customer runtime presence used by the pilot readiness check."""

    __tablename__ = "runtime_heartbeat"

    component: Mapped[str] = mapped_column(Text, primary_key=True)
    instance_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    last_seen_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    detail_code: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_runtime_heartbeat_last_seen", "last_seen_at"),)
