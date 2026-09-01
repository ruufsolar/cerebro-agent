import logging
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from cerebro.agent.models import Confidence, PaymentIdentification
from cerebro.agent.runner import (
    AgentRunInput,
    TranscriptAttachment,
    TranscriptMessage,
    get_agent_runner,
)
from cerebro.config import GlobalMode, get_config
from cerebro.db.enums import (
    ConversationState,
    DeliveryStatus,
    RunStatus,
    SlackOutputKind,
)
from cerebro.db.models import AgentRun, Conversation, Message, SlackOutput
from cerebro.db.session import open_session
from cerebro.jobs.enqueue import enqueue_slack_output
from cerebro.slack.gateway import get_slack_gateway

logger = logging.getLogger(__name__)


def render_identification(result: PaymentIdentification) -> str:
    confidence = {
        Confidence.HIGH: "alta",
        Confidence.MEDIUM: "media",
        Confidence.LOW: "baja",
        Confidence.UNKNOWN: "no sé",
    }[result.confidence]
    lines = [
        "🧪 *Respuesta de prueba — la investigación en datos reales aún no está habilitada.*",
        f"*Confianza:* {confidence}",
    ]
    if result.recommended_customer:
        candidate = result.recommended_customer
        lines.append(f"*Cliente recomendado:* <{candidate.crm_url}|{candidate.customer_name}>")
    else:
        lines.append("*Cliente recomendado:* no encontré un cliente.")
    if result.account_receivable_summary:
        lines.append(f"*Cuenta por cobrar:* {result.account_receivable_summary}")
    lines.append(
        "No consulté el monolito, Vambe, correos ni la réplica en este slice; "
        "por lo tanto no puedo verificar a quién corresponde el pago todavía."
    )
    if result.alternatives:
        alternatives = ", ".join(candidate.customer_name for candidate in result.alternatives)
        lines.append(f"*Alternativas:* {alternatives}")
    return "\n".join(lines)


def _attachments(metadata: list[dict[str, object]] | None) -> tuple[TranscriptAttachment, ...]:
    if not metadata:
        return ()
    result: list[TranscriptAttachment] = []
    for item in metadata:
        file_id = item.get("id")
        mimetype = item.get("mimetype")
        size = item.get("size")
        if (
            not isinstance(file_id, str)
            or not isinstance(mimetype, str)
            or not isinstance(size, int)
        ):
            continue
        result.append(
            TranscriptAttachment(
                slack_file_id=file_id,
                name=str(item["name"]) if item.get("name") else None,
                mimetype=mimetype,
                size=size,
            )
        )
    return tuple(result)


async def _clear_status(channel: str, thread_ts: str) -> None:
    try:
        await get_slack_gateway().clear_status(channel, thread_ts)
    except Exception:
        logger.warning("could not clear Slack thread status", exc_info=True)


async def execute_run(run_id: UUID) -> None:
    config = get_config()
    async with open_session() as session:
        run = await session.get(AgentRun, run_id, with_for_update=True)
        if run is None or run.status != RunStatus.QUEUED:
            return
        conversation = await session.get(Conversation, run.conversation_id)
        trigger = await session.get(Message, run.trigger_message_id)
        assert conversation is not None and trigger is not None
        stored_messages = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.event_at, Message.created_at)
                )
            ).all()
        )
        transcript = tuple(
            TranscriptMessage(
                direction=message.direction,
                text=message.text,
                event_at=message.event_at,
                sender_slack_user_id=message.sender_slack_user_id,
                attachments=_attachments(message.file_metadata),
            )
            for message in stored_messages
        )
        runner_input = AgentRunInput(
            run_id=run.id,
            slack_channel_id=conversation.slack_channel_id,
            slack_thread_ts=conversation.slack_thread_ts,
            requester_slack_user_id=conversation.requester_slack_user_id,
            transcript=transcript,
            image_paths=(),
        )
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        run.input_snapshot = {
            "messages": [
                {
                    "direction": message.direction,
                    "text": message.text,
                    "event_at": message.event_at.isoformat(),
                    "sender_slack_user_id": message.sender_slack_user_id,
                    "image_count": len(message.attachments),
                }
                for message in transcript
            ],
            "image_paths": [],
        }
        await session.commit()

    posts_to_slack = config.global_mode in {GlobalMode.REVIEW, GlobalMode.APPLY}
    if posts_to_slack:
        try:
            await get_slack_gateway().set_status(
                runner_input.slack_channel_id,
                runner_input.slack_thread_ts,
                "Investigando el pago…",
            )
        except Exception:
            logger.warning("could not set Slack thread status", exc_info=True)

    started = monotonic()
    try:
        result = await get_agent_runner().run(runner_input)
        body = render_identification(result.identification)
        output_id: UUID | None = None
        async with open_session() as session:
            run = await session.get(AgentRun, run_id, with_for_update=True)
            assert run is not None
            trigger = await session.get(Message, run.trigger_message_id)
            assert trigger is not None
            newer_message = await session.scalar(
                select(Message.id)
                .where(
                    Message.conversation_id == run.conversation_id,
                    Message.direction == "inbound",
                    Message.event_at > trigger.event_at,
                )
                .limit(1)
            )
            conversation = await session.get(Conversation, run.conversation_id)
            assert conversation is not None
            if newer_message is not None:
                run.status = RunStatus.CANCELLED
                run.finished_at = datetime.now(UTC)
                conversation.state = ConversationState.RUNNING
                await session.commit()
                if posts_to_slack:
                    await _clear_status(runner_input.slack_channel_id, runner_input.slack_thread_ts)
                return
            run.status = RunStatus.SUCCEEDED
            run.structured_result = result.identification.model_dump(mode="json")
            run.steps = result.steps
            run.output_message = body
            run.model = result.usage.model
            run.input_tokens = result.usage.input_tokens
            run.output_tokens = result.usage.output_tokens
            run.turns = result.usage.turns
            run.tool_calls = result.usage.tool_calls
            run.latency_ms = int((monotonic() - started) * 1_000)
            run.finished_at = datetime.now(UTC)
            conversation.state = ConversationState.ANSWERED
            if posts_to_slack:
                statement = (
                    insert(SlackOutput)
                    .values(
                        conversation_id=conversation.id,
                        agent_run_id=run.id,
                        slack_channel_id=conversation.slack_channel_id,
                        slack_thread_ts=conversation.slack_thread_ts,
                        idempotency_key=f"agent-run:{run.id}:investigation",
                        body=body,
                        kind=SlackOutputKind.INVESTIGATION,
                        status=DeliveryStatus.PENDING,
                    )
                    .on_conflict_do_nothing(index_elements=[SlackOutput.idempotency_key])
                    .returning(SlackOutput.id)
                )
                output_id = await session.scalar(statement)
            await session.commit()
        if output_id:
            await enqueue_slack_output(output_id)
    except Exception as exc:
        logger.exception("agent run %s failed", run_id)
        output_id = None
        async with open_session() as session:
            run = await session.get(AgentRun, run_id, with_for_update=True)
            if run:
                run.status = RunStatus.FAILED
                run.error_code = "runner_error"
                run.error_detail = str(exc)[:2_000]
                run.finished_at = datetime.now(UTC)
                conversation = await session.get(Conversation, run.conversation_id)
                if conversation:
                    conversation.state = ConversationState.FAILED
                    if posts_to_slack:
                        statement = (
                            insert(SlackOutput)
                            .values(
                                conversation_id=conversation.id,
                                agent_run_id=run.id,
                                slack_channel_id=conversation.slack_channel_id,
                                slack_thread_ts=conversation.slack_thread_ts,
                                idempotency_key=f"agent-run:{run.id}:error",
                                body=(
                                    "No pude completar esta respuesta de prueba. "
                                    "FinOps debe revisar el pago manualmente."
                                ),
                                kind=SlackOutputKind.ERROR,
                                status=DeliveryStatus.PENDING,
                            )
                            .on_conflict_do_nothing(index_elements=[SlackOutput.idempotency_key])
                            .returning(SlackOutput.id)
                        )
                        output_id = await session.scalar(statement)
                await session.commit()
        if posts_to_slack:
            await _clear_status(runner_input.slack_channel_id, runner_input.slack_thread_ts)
        if output_id:
            await enqueue_slack_output(output_id)


async def deliver_output(output_id: UUID) -> None:
    config = get_config()
    async with open_session() as session:
        output = await session.get(SlackOutput, output_id, with_for_update=True)
        if output is None or output.status != DeliveryStatus.PENDING:
            return
        output.attempts += 1
        await session.commit()
        channel = output.slack_channel_id
        thread_ts = output.slack_thread_ts
        body = output.body
        client_msg_id = str(output.id)
        conversation_id = output.conversation_id
    try:
        message_ts = await get_slack_gateway().post_message(channel, thread_ts, body, client_msg_id)
    except Exception as exc:
        logger.warning("Slack output %s delivery failed", output_id, exc_info=True)
        permanently_failed = False
        async with open_session() as session:
            output = await session.get(SlackOutput, output_id, with_for_update=True)
            if output:
                output.last_error = str(exc)[:2_000]
                if output.attempts >= config.slack_delivery_max_attempts:
                    output.status = DeliveryStatus.FAILED
                    permanently_failed = True
                await session.commit()
        if permanently_failed:
            await _clear_status(channel, thread_ts)
        return

    async with open_session() as session:
        output = await session.get(SlackOutput, output_id, with_for_update=True)
        if output is None or output.status == DeliveryStatus.SENT:
            return
        output.status = DeliveryStatus.SENT
        output.slack_message_ts = message_ts
        output.sent_at = datetime.now(UTC)
        output.last_error = None
        statement = (
            insert(Message)
            .values(
                conversation_id=conversation_id,
                slack_channel_id=channel,
                slack_message_ts=message_ts,
                slack_thread_ts=thread_ts,
                sender_slack_user_id=None,
                direction="outbound",
                kind=output.kind,
                text=body,
                file_metadata=None,
                raw=None,
                event_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(constraint="uq_message_slack_identity")
        )
        await session.execute(statement)
        await session.commit()
