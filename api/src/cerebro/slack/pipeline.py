import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cerebro.agent.models import (
    Confidence,
    CustomerCandidate,
    IdentificationOutcome,
    PaymentIdentification,
    ToolAuditRecord,
)
from cerebro.agent.runner import (
    AgentRunFailure,
    AgentRunInput,
    AgentRunResult,
    ImageIngestion,
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
from cerebro.db.models import AgentRun, Conversation, Message, SlackOutput, ToolCall
from cerebro.db.session import open_session
from cerebro.jobs.enqueue import enqueue_slack_output
from cerebro.observability import log_event
from cerebro.slack.gateway import get_slack_gateway
from cerebro.slack.images import ImageBatch, ingest_trigger_images

logger = logging.getLogger(__name__)


async def _persist_tool_calls(
    session: AsyncSession, run_id: UUID, calls: tuple[ToolAuditRecord, ...]
) -> None:
    for call in calls:
        statement = (
            insert(ToolCall)
            .values(
                agent_run_id=run_id,
                sequence=call.sequence,
                tool_name=call.tool_name,
                status=call.status,
                input=_bounded_json(call.input),
                output=_bounded_json(call.output),
                duration_ms=call.duration_ms,
                error=call.error[:2_000] if call.error else None,
                query_fingerprint=call.query_fingerprint,
                referenced_relations=call.referenced_relations or None,
                row_count=call.row_count,
                truncated=call.truncated,
            )
            .on_conflict_do_nothing(index_elements=[ToolCall.agent_run_id, ToolCall.sequence])
        )
        await session.execute(statement)


def render_identification(
    run_result: AgentRunResult, image_ingestion: ImageIngestion | None = None
) -> str:
    result = run_result.identification
    confidence = {
        Confidence.HIGH: "alta",
        Confidence.MEDIUM: "media",
        Confidence.LOW: "baja",
        Confidence.UNKNOWN: "no sé",
    }[result.confidence]
    if run_result.prompt_version and "slice5" in run_result.prompt_version:
        banner = "🧪 *Slice 5 — piloto con datos reales e imágenes; sin escrituras.*"
    elif run_result.prompt_version and "slice4" in run_result.prompt_version:
        banner = "🧪 *Slice 4 — datos reales y capturas; sin correo ni escrituras.*"
    elif run_result.prompt_version and "slice3" in run_result.prompt_version:
        banner = "🧪 *Slice 3 — vista previa con datos reales; sin imágenes, correo ni escrituras.*"
    elif run_result.prompt_version:
        banner = (
            "🧪 *Slice 2 — razonamiento en vivo; las fuentes reales de Ruuf "
            "aún no están conectadas.*"
        )
    else:
        banner = (
            "🧪 *Respuesta de prueba — la investigación en datos reales aún no está habilitada.*"
        )
    if result.outcome is IdentificationOutcome.OUT_OF_SCOPE:
        return "\n".join([banner, f"*Resultado:* {_clip_words(result.investigation_summary, 25)}"])

    image_note = ""
    if image_ingestion and image_ingestion.unprocessed:
        image_note = (
            f"{image_ingestion.unprocessed}/{image_ingestion.requested} capturas no procesadas"
        )
    unable = list(result.unable_to_verify)
    if image_note and image_note not in unable:
        unable.append(image_note)
    pending = ", ".join(_clip_words(item, 5) for item in unable[:3])

    if result.outcome is IdentificationOutcome.MATCHED and result.recommended_customer:
        candidate = result.recommended_customer
        lines = [
            banner,
            f"*Resultado:* coincidencia — confianza {confidence}.",
            f"*Cliente:* {_customer_link(candidate)}",
        ]
        if result.account_receivable_summary:
            lines.append(f"*Cuenta:* {_clip_words(result.account_receivable_summary, 16)}")
        lines.append(f"*Por qué:* {_clip_words(result.investigation_summary, 34)}")
        tail: list[str] = []
        if pending:
            tail.append(f"*No pude verificar:* {pending}")
        if result.alternatives:
            tail.append(f"*Alternativas:* {_render_alternatives(result, max_reason_words=4)}")
        if tail:
            lines.append(" · ".join(tail))
        return "\n".join(lines)

    if result.outcome is IdentificationOutcome.NO_CUSTOMER_FOUND:
        lines = [
            banner,
            "*Resultado:* no encontré un cliente.",
            f"*Por qué:* {_clip_words(result.investigation_summary, 24)}",
        ]
        if pending:
            lines.append(f"*No pude verificar:* {pending}")
        return "\n".join(lines)

    lines = [
        banner,
        "*Resultado:* no sé; FinOps debe revisar el pago.",
        f"*Por qué:* {_clip_words(result.investigation_summary, 24)}",
    ]
    details: list[str] = []
    if result.alternatives:
        details.append(f"*Opciones:* {_render_alternatives(result, max_reason_words=4)}")
    if pending:
        details.append(f"*Falta:* {pending}")
    if details:
        lines.append(" · ".join(details))
    return "\n".join(lines)


def _clip_words(value: str, limit: int) -> str:
    words = value.split()
    if len(words) <= limit:
        return value.strip()
    return " ".join(words[:limit]).rstrip(".,;:") + "…"


def _render_alternatives(result: PaymentIdentification, *, max_reason_words: int) -> str:
    return "; ".join(
        (
            _customer_link(candidate, max_name_words=5)
            + (f" — {_clip_words(candidate.reason, max_reason_words)}" if candidate.reason else "")
        )
        for candidate in result.alternatives[:3]
    )


def _customer_link(candidate: CustomerCandidate, *, max_name_words: int = 8) -> str:
    customer_name = _clip_words(candidate.customer_name, max_name_words)
    return f"<{candidate.crm_url}|{customer_name}>"


def _bounded_json(
    value: dict[str, object] | list[object] | None,
) -> dict[str, object] | list[object] | None:
    if value is None:
        return None
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) <= 8_000:
        return value
    return {"truncated": True, "preview": encoded[:7_500]}


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
    except Exception as exc:
        log_event(
            logger,
            "slack_status_clear_failed",
            level=logging.WARNING,
            error_type=type(exc).__name__,
        )


def _attachment_summary(trigger: Message) -> tuple[int, int]:
    raw = trigger.raw if isinstance(trigger.raw, dict) else {}
    summary = raw.get("attachment_summary")
    if not isinstance(summary, dict):
        accepted = len(trigger.file_metadata or [])
        return accepted, 0
    requested = summary.get("requested")
    rejected = summary.get("rejected")
    return (
        requested
        if isinstance(requested, int) and requested >= 0
        else len(trigger.file_metadata or []),
        rejected if isinstance(rejected, int) and rejected >= 0 else 0,
    )


async def _cancel_if_stale(run_id: UUID) -> bool:
    async with open_session() as session:
        run = await session.get(AgentRun, run_id, with_for_update=True)
        if run is None:
            return True
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
        if newer_message is None:
            return False
        run.status = RunStatus.CANCELLED
        run.finished_at = datetime.now(UTC)
        conversation = await session.get(Conversation, run.conversation_id)
        if conversation:
            conversation.state = ConversationState.RUNNING
        await session.commit()

    log_event(
        logger,
        "agent_run_cancelled",
        agent_run_id=run_id,
        conversation_id=run.conversation_id,
        run_status=RunStatus.CANCELLED,
    )
    return True


@asynccontextmanager
async def _run_images(
    *,
    run_id: UUID,
    attachments: tuple[TranscriptAttachment, ...],
    requested: int,
    rejected: int,
    supports_image_input: bool,
) -> AsyncIterator[ImageBatch]:
    if supports_image_input and attachments:
        async with ingest_trigger_images(
            run_id=run_id,
            attachments=attachments,
            requested=requested,
            rejected=rejected,
        ) as batch:
            yield batch
        return
    failures = ()
    if requested:
        failures = (
            "no_accepted_images" if supports_image_input else "runner_does_not_support_images",
        )
    yield ImageBatch(
        paths=(),
        ingestion=ImageIngestion(
            requested=requested,
            metadata_accepted=len(attachments),
            downloaded=0,
            rejected=rejected,
            failure_categories=failures,
        ),
    )


def _append_image_limitation(
    result: AgentRunResult, image_ingestion: ImageIngestion
) -> AgentRunResult:
    if image_ingestion.unprocessed == 0:
        return result
    note = f"{image_ingestion.unprocessed}/{image_ingestion.requested} capturas no procesadas"
    unable = list(result.identification.unable_to_verify)
    if note not in unable:
        unable.append(note)
    identification = result.identification.model_copy(update={"unable_to_verify": unable})
    return replace(result, identification=identification)


def _has_usable_evidence(run_input: AgentRunInput) -> bool:
    if run_input.image_paths:
        return True
    for message in run_input.transcript:
        if message.direction != "inbound" or not message.text:
            continue
        text = re.sub(r"<@[^>]+>", "", message.text).strip()
        if text:
            return True
    return False


async def execute_run(run_id: UUID) -> None:
    config = get_config()
    async with open_session() as session:
        run = await session.get(AgentRun, run_id, with_for_update=True)
        if run is None or run.status != RunStatus.QUEUED:
            return
        conversation = await session.get(Conversation, run.conversation_id)
        trigger = await session.get(Message, run.trigger_message_id)
        assert conversation is not None and trigger is not None
        newer_message = await session.scalar(
            select(Message.id)
            .where(
                Message.conversation_id == run.conversation_id,
                Message.direction == "inbound",
                Message.event_at > trigger.event_at,
            )
            .limit(1)
        )
        if newer_message is not None:
            run.status = RunStatus.CANCELLED
            run.finished_at = datetime.now(UTC)
            conversation.state = ConversationState.RUNNING
            await session.commit()
            return
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
                slack_message_ts=message.slack_message_ts,
                attachments=_attachments(message.file_metadata),
            )
            for message in stored_messages
        )
        trigger_attachments = _attachments(trigger.file_metadata)
        requested_images, rejected_images = _attachment_summary(trigger)
        channel = conversation.slack_channel_id
        thread_ts = conversation.slack_thread_ts
        requester = conversation.requester_slack_user_id
        trigger_ts = trigger.slack_message_ts
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        run.input_snapshot = {
            "messages": [
                {
                    "direction": message.direction,
                    "text": message.text,
                    "event_at": message.event_at.isoformat(),
                    "sender_slack_user_id": message.sender_slack_user_id,
                    "slack_message_ts": message.slack_message_ts,
                    "image_count": len(message.attachments),
                }
                for message in transcript
            ],
            "image_ingestion": {
                "requested": requested_images,
                "metadata_accepted": len(trigger_attachments),
                "downloaded": 0,
                "rejected": rejected_images,
                "failure_categories": [],
            },
        }
        await session.commit()

    log_event(
        logger,
        "agent_run_started",
        agent_run_id=run_id,
        conversation_id=conversation.id,
        run_status=RunStatus.RUNNING,
    )

    posts_to_slack = config.global_mode in {GlobalMode.REVIEW, GlobalMode.APPLY}
    runner = get_agent_runner()
    if posts_to_slack:
        try:
            await get_slack_gateway().set_status(
                channel,
                thread_ts,
                "Investigando el pago…",
            )
        except Exception as exc:
            log_event(
                logger,
                "slack_status_set_failed",
                level=logging.WARNING,
                agent_run_id=run_id,
                error_type=type(exc).__name__,
            )

    started = monotonic()
    try:
        async with _run_images(
            run_id=run_id,
            attachments=trigger_attachments,
            requested=requested_images,
            rejected=rejected_images,
            supports_image_input=bool(getattr(runner, "supports_image_input", False)),
        ) as image_batch:
            runner_input = AgentRunInput(
                run_id=run_id,
                slack_channel_id=channel,
                slack_thread_ts=thread_ts,
                requester_slack_user_id=requester,
                transcript=transcript,
                trigger_slack_message_ts=trigger_ts,
                image_paths=image_batch.paths,
                image_ingestion=image_batch.ingestion,
            )
            async with open_session() as session:
                stored_run = await session.get(AgentRun, run_id, with_for_update=True)
                assert stored_run is not None
                snapshot = dict(stored_run.input_snapshot or {})
                snapshot["image_ingestion"] = {
                    "requested": image_batch.ingestion.requested,
                    "metadata_accepted": image_batch.ingestion.metadata_accepted,
                    "downloaded": image_batch.ingestion.downloaded,
                    "rejected": image_batch.ingestion.rejected,
                    "failure_categories": list(image_batch.ingestion.failure_categories),
                }
                stored_run.input_snapshot = snapshot
                await session.commit()
            if await _cancel_if_stale(run_id):
                if posts_to_slack:
                    await _clear_status(channel, thread_ts)
                return
            if _has_usable_evidence(runner_input):
                result = await runner.run(runner_input)
            else:
                result = AgentRunResult(
                    identification=PaymentIdentification(
                        confidence=Confidence.UNKNOWN,
                        investigation_summary=(
                            "No quedó texto ni una captura válida para investigar el pago."
                        ),
                        unable_to_verify=["cliente", "cuenta por cobrar", "evidencia del pago"],
                    ),
                    prompt_version="payment-identification-slice5-v1",
                )
            result = _append_image_limitation(result, image_batch.ingestion)
        body = render_identification(result, image_batch.ingestion)
        output_id: UUID | None = None
        if await _cancel_if_stale(run_id):
            if posts_to_slack:
                await _clear_status(channel, thread_ts)
            return
        async with open_session() as session:
            run = await session.get(AgentRun, run_id, with_for_update=True)
            assert run is not None
            conversation = await session.get(Conversation, run.conversation_id)
            assert conversation is not None
            run.status = RunStatus.SUCCEEDED
            run.structured_result = result.identification.model_dump(mode="json")
            run.steps = [
                {
                    "type": "image_ingestion",
                    "requested": image_batch.ingestion.requested,
                    "metadata_accepted": image_batch.ingestion.metadata_accepted,
                    "downloaded": image_batch.ingestion.downloaded,
                    "rejected": image_batch.ingestion.rejected,
                    "failure_categories": list(image_batch.ingestion.failure_categories),
                },
                *[step.model_dump(mode="json") for step in result.steps],
                *[
                    {
                        "type": "tool_call",
                        "name": call.tool_name,
                        "status": call.status,
                    }
                    for call in result.tool_calls
                ],
            ]
            run.output_message = body
            run.prompt_version = result.prompt_version
            run.knowledge_version = result.knowledge_version
            run.completion_reason = result.completion_reason
            run.model = result.usage.model
            run.input_tokens = result.usage.input_tokens
            run.output_tokens = result.usage.output_tokens
            run.turns = result.usage.turns
            run.tool_calls = result.usage.tool_calls
            run.latency_ms = int((monotonic() - started) * 1_000)
            run.finished_at = datetime.now(UTC)
            conversation.state = ConversationState.ANSWERED
            await _persist_tool_calls(session, run.id, result.tool_calls)
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
        log_event(
            logger,
            "agent_run_completed",
            agent_run_id=run_id,
            conversation_id=conversation.id,
            run_status=RunStatus.SUCCEEDED,
            outcome=result.identification.outcome,
            confidence=result.identification.confidence,
            completion_reason=result.completion_reason,
            model=result.usage.model,
            prompt_version=result.prompt_version,
            knowledge_version=result.knowledge_version,
            duration_ms=int((monotonic() - started) * 1_000),
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            turns=result.usage.turns,
            tool_calls=result.usage.tool_calls,
            image_count=image_batch.ingestion.downloaded,
        )
        if output_id:
            await enqueue_slack_output(output_id)
    except Exception as exc:
        log_event(
            logger,
            "agent_run_failed",
            level=logging.ERROR,
            agent_run_id=run_id,
            run_status=RunStatus.FAILED,
            error_type=type(exc).__name__,
            error_code="runner_error",
        )
        output_id = None
        async with open_session() as session:
            run = await session.get(AgentRun, run_id, with_for_update=True)
            if run:
                if isinstance(exc, AgentRunFailure):
                    run.prompt_version = exc.prompt_version
                    run.knowledge_version = exc.knowledge_version
                    run.tool_calls = len(exc.tool_calls)
                    run.steps = [
                        {"type": "tool_call", "name": call.tool_name, "status": call.status}
                        for call in exc.tool_calls
                    ]
                    await _persist_tool_calls(session, run.id, exc.tool_calls)
                run.status = RunStatus.FAILED
                run.error_code = "runner_error"
                run.error_detail = type(exc).__name__
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
            await _clear_status(channel, thread_ts)
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
        log_event(
            logger,
            "slack_output_delivery_failed",
            level=logging.WARNING,
            output_id=output_id,
            error_type=type(exc).__name__,
        )
        permanently_failed = False
        async with open_session() as session:
            output = await session.get(SlackOutput, output_id, with_for_update=True)
            if output:
                output.last_error = type(exc).__name__
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
    log_event(
        logger,
        "slack_output_sent",
        output_id=output_id,
        delivery_status=DeliveryStatus.SENT,
    )
