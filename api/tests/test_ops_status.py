from datetime import UTC, datetime
from uuid import uuid4

from cerebro.db.enums import DeliveryStatus, RunStatus, SlackEventDisposition
from cerebro.db.models import AgentRun, Conversation, Message, SlackEvent, SlackOutput, ToolCall
from cerebro.db.session import open_session
from cerebro.ops.status import collect_status


async def test_status_is_aggregate_and_never_surfaces_retained_content(clean_database) -> None:
    sentinel = (
        "customer@example.com RUT 12.345.678-9 account 123456789 "
        "https://files.slack.com/private xoxb-secret"
    )
    now = datetime.now(UTC)
    conversation_id = uuid4()
    message_id = uuid4()
    run_id = uuid4()
    async with open_session() as session:
        session.add(
            SlackEvent(
                slack_event_id="event-safe-status",
                event_type="app_mention",
                payload={"text": sentinel, "image": "data:image/png;base64,secret"},
                disposition=SlackEventDisposition.FAILED,
                error=sentinel,
            )
        )
        session.add(
            Conversation(
                id=conversation_id,
                slack_channel_id="channel-private",
                slack_thread_ts="thread-private",
                requester_slack_user_id="user-private",
                latest_question=sentinel,
            )
        )
        await session.commit()
        session.add(
            Message(
                id=message_id,
                conversation_id=conversation_id,
                slack_channel_id="channel-private",
                slack_message_ts="message-private",
                slack_thread_ts="thread-private",
                sender_slack_user_id="user-private",
                direction="inbound",
                text=sentinel,
                raw={"private": sentinel},
                event_at=now,
            )
        )
        await session.commit()
        session.add(
            AgentRun(
                id=run_id,
                conversation_id=conversation_id,
                trigger_message_id=message_id,
                status=RunStatus.FAILED,
                error_code="runner_error",
                error_detail=sentinel,
            )
        )
        await session.commit()
        session.add(
            ToolCall(
                agent_run_id=run_id,
                sequence=1,
                tool_name="run_readonly_sql",
                status="failed",
                input={"query": f"SELECT '{sentinel}'"},
                error=sentinel,
            )
        )
        session.add(
            SlackOutput(
                conversation_id=conversation_id,
                agent_run_id=run_id,
                slack_channel_id="channel-private",
                slack_thread_ts="thread-private",
                idempotency_key="status-safe-output",
                body=sentinel,
                status=DeliveryStatus.FAILED,
                last_error=sentinel,
            )
        )
        await session.commit()

    report = await collect_status(24)
    encoded = str(report)

    assert report["queues"].keys() == {"control", "agent"}
    assert report["failures"] == {
        "runs": {"runner_error": 1},
        "events": 1,
        "outputs": 1,
    }
    for forbidden in (
        "customer@example.com",
        "12.345.678-9",
        "123456789",
        "files.slack.com",
        "xoxb-secret",
        "SELECT",
        "data:image",
        "channel-private",
    ):
        assert forbidden not in encoded
