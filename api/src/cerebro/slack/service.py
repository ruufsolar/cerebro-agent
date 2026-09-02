import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cerebro.config import GlobalMode, get_config
from cerebro.db.enums import (
    ConversationState,
    RunStatus,
    SlackEventDisposition,
    SlackOutputKind,
)
from cerebro.db.models import AgentRun, Conversation, Feedback, Message, SlackEvent, SlackOutput
from cerebro.db.session import open_session
from cerebro.jobs.enqueue import enqueue_agent_run, enqueue_slack_event, enqueue_slack_output
from cerebro.slack.events import NormalizedSlackEvent, SlackEventKind

logger = logging.getLogger(__name__)


def _event_time(message_ts: str) -> datetime:
    try:
        return datetime.fromtimestamp(float(message_ts), tz=UTC)
    except ValueError:
        return datetime.now(UTC)


async def receive_event(event: NormalizedSlackEvent) -> UUID | None:
    """Persist once, then enqueue. Slack listeners call this only after ACK."""
    config = get_config()
    ignored = event.kind == SlackEventKind.IGNORED or config.global_mode == GlobalMode.OFF
    values = {
        "slack_event_id": event.slack_event_id,
        "event_type": event.event_type,
        "payload": {**event.payload, "kind": event.kind},
        "disposition": (
            SlackEventDisposition.IGNORED if ignored else SlackEventDisposition.RECEIVED
        ),
        "processed_at": datetime.now(UTC) if ignored else None,
    }
    async with open_session() as session:
        statement = (
            insert(SlackEvent)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[SlackEvent.slack_event_id])
            .returning(SlackEvent.id)
        )
        event_id = await session.scalar(statement)
        await session.commit()
    if event_id is None or ignored:
        return event_id
    if await enqueue_slack_event(event_id):
        async with open_session() as session:
            stored = await session.get(SlackEvent, event_id)
            if stored and stored.disposition == SlackEventDisposition.RECEIVED:
                stored.disposition = SlackEventDisposition.QUEUED
                await session.commit()
    return event_id


async def _upsert_conversation(
    session: AsyncSession, payload: dict[str, Any], *, create: bool
) -> UUID | None:
    channel = str(payload["channel"])
    thread_ts = str(payload["thread_ts"])
    if not create:
        return await session.scalar(
            select(Conversation.id).where(
                Conversation.slack_channel_id == channel,
                Conversation.slack_thread_ts == thread_ts,
            )
        )
    statement = (
        insert(Conversation)
        .values(
            slack_channel_id=channel,
            slack_thread_ts=thread_ts,
            requester_slack_user_id=str(payload["user"]),
            latest_question=str(payload.get("text") or ""),
            state=ConversationState.OPEN,
        )
        .on_conflict_do_update(
            constraint="uq_conversation_slack_thread",
            set_={"latest_question": str(payload.get("text") or "")},
        )
        .returning(Conversation.id)
    )
    return await session.scalar(statement)


async def _store_trigger(
    session: AsyncSession, conversation_id: UUID, payload: dict[str, Any]
) -> tuple[UUID | None, UUID | None]:
    file_metadata = payload.get("files") or []
    message_statement = (
        insert(Message)
        .values(
            conversation_id=conversation_id,
            slack_channel_id=str(payload["channel"]),
            slack_message_ts=str(payload["message_ts"]),
            slack_thread_ts=str(payload["thread_ts"]),
            sender_slack_user_id=str(payload["user"]),
            direction="inbound",
            kind="image" if file_metadata else "text",
            text=str(payload.get("text") or ""),
            file_metadata=file_metadata or None,
            raw={
                "event_type": payload.get("event_type"),
                "image_count": len(file_metadata),
                "attachment_summary": payload.get("attachment_summary")
                or {
                    "requested": len(file_metadata),
                    "accepted": len(file_metadata),
                    "rejected": 0,
                },
            },
            event_at=_event_time(str(payload["message_ts"])),
        )
        .on_conflict_do_nothing(constraint="uq_message_slack_identity")
        .returning(Message.id)
    )
    message_id = await session.scalar(message_statement)
    if message_id is None:
        return None, None
    run_statement = (
        insert(AgentRun)
        .values(
            conversation_id=conversation_id,
            trigger_message_id=message_id,
            status=RunStatus.QUEUED,
        )
        .on_conflict_do_nothing(constraint="uq_agent_run_trigger_message")
        .returning(AgentRun.id)
    )
    return message_id, await session.scalar(run_statement)


async def _process_message(session: AsyncSession, event: SlackEvent) -> tuple[UUID, UUID] | None:
    payload = event.payload
    is_mention = event.event_type == "app_mention"
    conversation_id = await _upsert_conversation(session, payload, create=is_mention)
    if conversation_id is None:
        event.disposition = SlackEventDisposition.IGNORED
        event.processed_at = datetime.now(UTC)
        return None
    _, run_id = await _store_trigger(session, conversation_id, payload)
    event.disposition = SlackEventDisposition.PROCESSED
    event.processed_at = datetime.now(UTC)
    if run_id is None:
        return None
    conversation = await session.get(Conversation, conversation_id)
    assert conversation is not None
    conversation.state = ConversationState.RUNNING
    conversation.latest_question = str(payload.get("text") or "")
    return run_id, conversation_id


async def _process_reaction(session: AsyncSession, event: SlackEvent) -> UUID | None:
    payload = event.payload
    output = await session.scalar(
        select(SlackOutput).where(
            SlackOutput.slack_channel_id == str(payload["channel"]),
            SlackOutput.slack_message_ts == str(payload["message_ts"]),
            SlackOutput.kind == SlackOutputKind.INVESTIGATION,
        )
    )
    if output is None:
        event.disposition = SlackEventDisposition.IGNORED
        event.processed_at = datetime.now(UTC)
        return None
    added = event.event_type == "reaction_added"
    reaction = str(payload["reaction"])
    identity = (
        Feedback.slack_channel_id == str(payload["channel"]),
        Feedback.slack_message_ts == str(payload["message_ts"]),
        Feedback.slack_user_id == str(payload["user"]),
        Feedback.reaction == reaction,
    )
    if added:
        feedback_statement = (
            insert(Feedback)
            .values(
                conversation_id=output.conversation_id,
                agent_run_id=output.agent_run_id,
                slack_channel_id=str(payload["channel"]),
                slack_message_ts=str(payload["message_ts"]),
                slack_user_id=str(payload["user"]),
                reaction=reaction,
                sentiment="positive" if reaction == "cheese_wedge" else "negative",
                is_active=True,
            )
            .on_conflict_do_update(
                constraint="uq_feedback_reaction",
                set_={"is_active": True, "updated_at": datetime.now(UTC)},
            )
        )
        await session.execute(feedback_statement)
    else:
        existing = await session.scalar(select(Feedback).where(*identity))
        if existing:
            existing.is_active = False
    output_id: UUID | None = None
    if (
        added
        and reaction == "electric_plug"
        and get_config().global_mode in {GlobalMode.REVIEW, GlobalMode.APPLY}
    ):
        flavor_statement = (
            insert(SlackOutput)
            .values(
                conversation_id=output.conversation_id,
                agent_run_id=output.agent_run_id,
                slack_channel_id=output.slack_channel_id,
                slack_thread_ts=output.slack_thread_ts,
                idempotency_key=(
                    f"feedback:{payload['channel']}:{payload['message_ts']}:"
                    f"{payload['user']}:electric_plug"
                ),
                body="Arrrrgghhh ⚡️☠️",
                kind=SlackOutputKind.FEEDBACK_FLAVOR,
                status="pending",
            )
            .on_conflict_do_nothing(index_elements=[SlackOutput.idempotency_key])
            .returning(SlackOutput.id)
        )
        output_id = await session.scalar(flavor_statement)
    event.disposition = SlackEventDisposition.PROCESSED
    event.processed_at = datetime.now(UTC)
    return output_id


async def process_stored_event(event_id: UUID) -> None:
    run_to_enqueue: tuple[UUID, UUID] | None = None
    output_to_enqueue: UUID | None = None
    try:
        async with open_session() as session:
            event = await session.get(SlackEvent, event_id, with_for_update=True)
            if event is None or event.disposition in {
                SlackEventDisposition.PROCESSED,
                SlackEventDisposition.IGNORED,
            }:
                return
            if event.event_type in {"app_mention", "message"}:
                run_to_enqueue = await _process_message(session, event)
            elif event.event_type in {"reaction_added", "reaction_removed"}:
                output_to_enqueue = await _process_reaction(session, event)
            else:
                event.disposition = SlackEventDisposition.IGNORED
                event.processed_at = datetime.now(UTC)
            await session.commit()
    except Exception as exc:
        logger.exception("failed to process Slack event %s", event_id)
        async with open_session() as session:
            event = await session.get(SlackEvent, event_id)
            if event:
                event.disposition = SlackEventDisposition.FAILED
                event.error = str(exc)[:2_000]
                await session.commit()
        raise
    if run_to_enqueue:
        await enqueue_agent_run(*run_to_enqueue)
    if output_to_enqueue:
        await enqueue_slack_output(output_to_enqueue)
