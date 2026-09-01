from typing import Any

import pytest
from sqlalchemy import func, select

from cerebro.agent.models import (
    AgentUsage,
    CompletionReason,
    Confidence,
    PaymentIdentification,
    ToolAuditRecord,
)
from cerebro.agent.runner import AgentRunResult, FakeAgentRunner, set_agent_runner
from cerebro.config import get_config
from cerebro.db.enums import DeliveryStatus, RunStatus, SlackEventDisposition, SlackOutputKind
from cerebro.db.models import (
    AgentRun,
    Conversation,
    Feedback,
    Message,
    SlackEvent,
    SlackOutput,
    ToolCall,
)
from cerebro.db.session import open_session
from cerebro.jobs.tasks import recover_pending_work
from cerebro.slack.events import normalize_event
from cerebro.slack.gateway import set_slack_gateway
from cerebro.slack.pipeline import deliver_output, execute_run
from cerebro.slack.service import process_stored_event, receive_event


class FakeSlackGateway:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str, str]] = []
        self.posts: list[tuple[str, str, str, str]] = []

    async def set_status(self, channel: str, thread_ts: str, status: str) -> None:
        self.statuses.append((channel, thread_ts, status))

    async def clear_status(self, channel: str, thread_ts: str) -> None:
        self.statuses.append((channel, thread_ts, ""))

    async def post_message(
        self, channel: str, thread_ts: str, text: str, client_msg_id: str
    ) -> str:
        self.posts.append((channel, thread_ts, text, client_msg_id))
        return f"200.{len(self.posts)}"

    async def close(self) -> None:
        return None


class FailingSlackGateway(FakeSlackGateway):
    def __init__(self, *, fail_status: bool = False, fail_posts: bool = False) -> None:
        super().__init__()
        self.fail_status = fail_status
        self.fail_posts = fail_posts

    async def set_status(self, channel: str, thread_ts: str, status: str) -> None:
        if self.fail_status:
            raise RuntimeError("status unavailable")
        await super().set_status(channel, thread_ts, status)

    async def post_message(
        self, channel: str, thread_ts: str, text: str, client_msg_id: str
    ) -> str:
        self.posts.append((channel, thread_ts, text, client_msg_id))
        if self.fail_posts:
            raise RuntimeError("post unavailable")
        return f"200.{len(self.posts)}"


def message_envelope(
    event_id: str, *, event_type: str = "app_mention", ts: str = "100.1", text: str = "pago"
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": event_type,
        "channel": "C1",
        "channel_type": "channel",
        "ts": ts,
        "user": "U1",
        "text": text,
    }
    if event_type == "message":
        event["thread_ts"] = "100.1"
    return {"event_id": event_id, "team_id": "T1", "event": event}


def reaction_envelope(
    event_id: str, event_type: str, reaction: str, message_ts: str
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "team_id": "T1",
        "event": {
            "type": event_type,
            "reaction": reaction,
            "user": "U2",
            "item": {"type": "message", "channel": "C1", "ts": message_ts},
        },
    }


async def store_and_process(body: dict[str, Any]) -> None:
    event_id = await receive_event(normalize_event(body, bot_user_id="BOT", config=get_config()))
    assert event_id is not None
    await process_stored_event(event_id)


@pytest.mark.parametrize(
    ("mode", "expected_runs", "expected_outputs", "expected_statuses"),
    [
        ("off", 0, 0, 0),
        ("shadow", 1, 0, 0),
        ("review", 1, 1, 1),
        ("apply", 1, 1, 1),
    ],
)
async def test_mode_gate_has_no_slack_effect_in_off_or_shadow(
    clean_database: None,
    memory_jobs: Any,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_runs: int,
    expected_outputs: int,
    expected_statuses: int,
) -> None:
    del clean_database, memory_jobs
    monkeypatch.setenv("CEREBRO_GLOBAL_MODE", mode)
    get_config.cache_clear()
    gateway = FakeSlackGateway()
    set_slack_gateway(gateway)

    event_id = await receive_event(
        normalize_event(message_envelope("Ev-mode"), bot_user_id="BOT", config=get_config())
    )
    assert event_id is not None
    if mode != "off":
        await process_stored_event(event_id)
        async with open_session() as session:
            run_id = await session.scalar(select(AgentRun.id))
        assert run_id is not None
        await execute_run(run_id)

    async with open_session() as session:
        run_count = await session.scalar(select(func.count()).select_from(AgentRun))
        output_count = await session.scalar(select(func.count()).select_from(SlackOutput))
        event = await session.get(SlackEvent, event_id)

    assert run_count == expected_runs
    assert output_count == expected_outputs
    assert len(gateway.statuses) == expected_statuses
    assert event is not None
    if mode == "off":
        assert event.disposition == SlackEventDisposition.IGNORED


async def test_event_message_run_output_and_delivery_are_idempotent(
    clean_database: None,
    memory_jobs: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del clean_database, memory_jobs
    monkeypatch.setenv("CEREBRO_GLOBAL_MODE", "review")
    get_config.cache_clear()
    gateway = FakeSlackGateway()
    set_slack_gateway(gateway)
    normalized = normalize_event(
        message_envelope("Ev-once"), bot_user_id="BOT", config=get_config()
    )

    event_id = await receive_event(normalized)
    duplicate_id = await receive_event(normalized)
    assert event_id is not None
    assert duplicate_id is None
    await process_stored_event(event_id)
    await process_stored_event(event_id)
    async with open_session() as session:
        run_id = await session.scalar(select(AgentRun.id))
    assert run_id is not None
    await execute_run(run_id)
    await execute_run(run_id)
    async with open_session() as session:
        output_id = await session.scalar(select(SlackOutput.id))
    assert output_id is not None
    await deliver_output(output_id)
    await deliver_output(output_id)

    async with open_session() as session:
        counts = [
            await session.scalar(select(func.count()).select_from(model))
            for model in (SlackEvent, Conversation, AgentRun, SlackOutput)
        ]
        inbound = await session.scalar(
            select(func.count()).select_from(Message).where(Message.direction == "inbound")
        )
        outbound = await session.scalar(
            select(func.count()).select_from(Message).where(Message.direction == "outbound")
        )
    assert counts == [1, 1, 1, 1]
    assert inbound == 1
    assert outbound == 1
    assert len(gateway.posts) == 1
    assert gateway.posts[0][0:2] == ("C1", "100.1")
    assert gateway.posts[0][3] == str(output_id)


async def test_unknown_thread_followup_is_ignored(
    clean_database: None,
    memory_jobs: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del clean_database, memory_jobs
    monkeypatch.setenv("CEREBRO_GLOBAL_MODE", "review")
    get_config.cache_clear()

    await store_and_process(
        message_envelope("Ev-unknown", event_type="message", ts="100.2", text="hola")
    )

    async with open_session() as session:
        event = await session.scalar(select(SlackEvent))
        conversation_count = await session.scalar(select(func.count()).select_from(Conversation))
    assert event is not None
    assert event.disposition == SlackEventDisposition.IGNORED
    assert conversation_count == 0


async def test_newer_thread_message_cancels_stale_run(
    clean_database: None,
    memory_jobs: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del clean_database, memory_jobs
    monkeypatch.setenv("CEREBRO_GLOBAL_MODE", "review")
    get_config.cache_clear()
    set_slack_gateway(FakeSlackGateway())
    await store_and_process(message_envelope("Ev-first", ts="100.1"))
    await store_and_process(
        message_envelope("Ev-second", event_type="message", ts="100.2", text="más contexto")
    )
    async with open_session() as session:
        runs = list((await session.scalars(select(AgentRun).order_by(AgentRun.created_at))).all())
    assert len(runs) == 2

    await execute_run(runs[0].id)
    await execute_run(runs[1].id)

    async with open_session() as session:
        statuses = list((await session.scalars(select(AgentRun.status))).all())
        output_count = await session.scalar(select(func.count()).select_from(SlackOutput))
    assert statuses == [RunStatus.CANCELLED, RunStatus.SUCCEEDED]
    assert output_count == 1


async def test_feedback_is_scoped_and_plug_flavor_is_not_recursive(
    clean_database: None,
    memory_jobs: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del clean_database, memory_jobs
    monkeypatch.setenv("CEREBRO_GLOBAL_MODE", "review")
    get_config.cache_clear()
    gateway = FakeSlackGateway()
    set_slack_gateway(gateway)
    await store_and_process(message_envelope("Ev-root"))
    async with open_session() as session:
        run_id = await session.scalar(select(AgentRun.id))
    assert run_id is not None
    await execute_run(run_id)
    async with open_session() as session:
        investigation = await session.scalar(
            select(SlackOutput).where(SlackOutput.kind == SlackOutputKind.INVESTIGATION)
        )
    assert investigation is not None
    await deliver_output(investigation.id)

    await store_and_process(
        reaction_envelope("Ev-cheese", "reaction_added", "cheese_wedge", "200.1")
    )
    plug = reaction_envelope("Ev-plug", "reaction_added", "electric_plug", "200.1")
    await store_and_process(plug)
    duplicate_plug = await receive_event(
        normalize_event(plug, bot_user_id="BOT", config=get_config())
    )
    assert duplicate_plug is None
    await store_and_process(
        reaction_envelope("Ev-unplug", "reaction_removed", "electric_plug", "200.1")
    )

    async with open_session() as session:
        feedback = list((await session.scalars(select(Feedback).order_by(Feedback.reaction))).all())
        flavor = await session.scalar(
            select(SlackOutput).where(SlackOutput.kind == SlackOutputKind.FEEDBACK_FLAVOR)
        )
    assert [(row.reaction, row.is_active) for row in feedback] == [
        ("cheese_wedge", True),
        ("electric_plug", False),
    ]
    assert flavor is not None
    await deliver_output(flavor.id)

    await store_and_process(
        reaction_envelope("Ev-flavor-plug", "reaction_added", "electric_plug", "200.2")
    )
    async with open_session() as session:
        flavor_count = await session.scalar(
            select(func.count())
            .select_from(SlackOutput)
            .where(SlackOutput.kind == SlackOutputKind.FEEDBACK_FLAVOR)
        )
    assert flavor_count == 1


async def test_shadow_records_feedback_without_flavor_reply(
    clean_database: None,
    memory_jobs: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del clean_database, memory_jobs
    monkeypatch.setenv("CEREBRO_GLOBAL_MODE", "review")
    get_config.cache_clear()
    gateway = FakeSlackGateway()
    set_slack_gateway(gateway)
    await store_and_process(message_envelope("Ev-shadow-root"))
    async with open_session() as session:
        run_id = await session.scalar(select(AgentRun.id))
    assert run_id is not None
    await execute_run(run_id)
    async with open_session() as session:
        investigation = await session.scalar(select(SlackOutput))
    assert investigation is not None
    await deliver_output(investigation.id)

    monkeypatch.setenv("CEREBRO_GLOBAL_MODE", "shadow")
    get_config.cache_clear()
    await store_and_process(
        reaction_envelope("Ev-shadow-plug", "reaction_added", "electric_plug", "200.1")
    )

    async with open_session() as session:
        feedback_count = await session.scalar(select(func.count()).select_from(Feedback))
        flavor_count = await session.scalar(
            select(func.count())
            .select_from(SlackOutput)
            .where(SlackOutput.kind == SlackOutputKind.FEEDBACK_FLAVOR)
        )
    assert feedback_count == 1
    assert flavor_count == 0


async def test_status_failure_is_nonfatal_and_delivery_retries_are_bounded(
    clean_database: None,
    memory_jobs: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del clean_database, memory_jobs
    monkeypatch.setenv("CEREBRO_GLOBAL_MODE", "review")
    get_config.cache_clear()
    gateway = FailingSlackGateway(fail_status=True, fail_posts=True)
    set_slack_gateway(gateway)
    await store_and_process(message_envelope("Ev-retry"))
    async with open_session() as session:
        run_id = await session.scalar(select(AgentRun.id))
    assert run_id is not None

    await execute_run(run_id)
    async with open_session() as session:
        output_id = await session.scalar(select(SlackOutput.id))
        run_status = await session.scalar(select(AgentRun.status))
    assert output_id is not None
    assert run_status == RunStatus.SUCCEEDED

    for _ in range(3):
        await deliver_output(output_id)

    async with open_session() as session:
        output = await session.get(SlackOutput, output_id)
    assert output is not None
    assert output.status == DeliveryStatus.FAILED
    assert output.attempts == 3
    assert len(gateway.posts) == 3


async def test_recovery_reenqueues_commit_to_job_gaps(
    clean_database: None,
    memory_jobs: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del clean_database
    monkeypatch.setenv("CEREBRO_GLOBAL_MODE", "review")
    get_config.cache_clear()
    set_slack_gateway(FakeSlackGateway())
    event_id = await receive_event(
        normalize_event(message_envelope("Ev-recovery"), bot_user_id="BOT", config=get_config())
    )
    assert event_id is not None

    memory_jobs.reset()
    await recover_pending_work(timestamp=0)
    assert [job["task_name"] for job in memory_jobs.jobs.values()] == [
        "cerebro.jobs.tasks.process_slack_event"
    ]

    await process_stored_event(event_id)
    async with open_session() as session:
        run = await session.scalar(select(AgentRun))
    assert run is not None
    memory_jobs.reset()
    await recover_pending_work(timestamp=1)
    assert [job["task_name"] for job in memory_jobs.jobs.values()] == [
        "cerebro.jobs.tasks.execute_agent_run"
    ]

    await execute_run(run.id)
    async with open_session() as session:
        output = await session.scalar(select(SlackOutput))
    assert output is not None
    memory_jobs.reset()
    await recover_pending_work(timestamp=2)
    assert [job["task_name"] for job in memory_jobs.jobs.values()] == [
        "cerebro.jobs.tasks.deliver_slack_output"
    ]


async def test_agents_sdk_metadata_and_tool_audit_are_persisted(
    clean_database: None,
    memory_jobs: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del clean_database, memory_jobs
    monkeypatch.setenv("CEREBRO_GLOBAL_MODE", "shadow")
    get_config.cache_clear()
    set_agent_runner(
        FakeAgentRunner(
            AgentRunResult(
                identification=PaymentIdentification(
                    confidence=Confidence.UNKNOWN,
                    investigation_summary="Fuentes sintéticas sin coincidencias.",
                ),
                usage=AgentUsage(model="gpt-5-6-sol", input_tokens=100, output_tokens=20, turns=2),
                prompt_version="payment-identification-slice3-v1",
                knowledge_version="1",
                completion_reason=CompletionReason.COMPLETED,
                tool_calls=(
                    ToolAuditRecord(
                        sequence=1,
                        tool_name="search_customer_identity",
                        status="succeeded",
                        input={"query": "María"},
                        output={"available": False, "candidates": []},
                        duration_ms=4,
                    ),
                ),
            )
        )
    )
    await store_and_process(message_envelope("Ev-audit"))
    async with open_session() as session:
        run_id = await session.scalar(select(AgentRun.id))
    assert run_id is not None

    await execute_run(run_id)

    async with open_session() as session:
        run = await session.get(AgentRun, run_id)
        tool_call = await session.scalar(select(ToolCall))
    assert run is not None
    assert run.prompt_version == "payment-identification-slice3-v1"
    assert run.knowledge_version == "1"
    assert run.completion_reason == CompletionReason.COMPLETED
    assert run.model == "gpt-5-6-sol"
    assert tool_call is not None
    assert tool_call.tool_name == "search_customer_identity"
    assert tool_call.output == {"available": False, "candidates": []}
