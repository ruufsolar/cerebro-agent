import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from procrastinate.jobs import Status as JobStatus
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from cerebro.config import GlobalMode, get_config
from cerebro.db.enums import (
    ConversationState,
    DeliveryStatus,
    RunStatus,
    SlackEventDisposition,
    SlackOutputKind,
)
from cerebro.db.models import AgentRun, Conversation, RuntimeHeartbeat, SlackEvent, SlackOutput
from cerebro.db.session import open_session
from cerebro.jobs.app import app
from cerebro.jobs.enqueue import enqueue_agent_run, enqueue_slack_event, enqueue_slack_output
from cerebro.observability import log_event
from cerebro.slack.pipeline import deliver_output, execute_run
from cerebro.slack.service import process_stored_event

logger = logging.getLogger(__name__)


@app.task(name="cerebro.jobs.tasks.process_slack_event", queue="control")
async def process_slack_event(event_id: str) -> None:
    await process_stored_event(UUID(event_id))


@app.task(name="cerebro.jobs.tasks.execute_agent_run", queue="agent")
async def execute_agent_run(run_id: str) -> None:
    await execute_run(UUID(run_id))


@app.task(name="cerebro.jobs.tasks.deliver_slack_output", queue="control")
async def deliver_slack_output(output_id: str) -> None:
    await deliver_output(UUID(output_id))


@app.periodic(cron="* * * * *", periodic_id="durable-recovery")
@app.task(name="cerebro.jobs.tasks.recover_pending_work", queue="control")
async def recover_pending_work(timestamp: int) -> None:
    """Close commit/enqueue gaps after a crash. Queue locks make this safe to repeat."""
    del timestamp
    await recover_interrupted_jobs()
    async with open_session() as session:
        events = list(
            (
                await session.scalars(
                    select(SlackEvent).where(
                        SlackEvent.disposition.in_(
                            [SlackEventDisposition.RECEIVED, SlackEventDisposition.QUEUED]
                        )
                    )
                )
            ).all()
        )
        runs = list(
            (
                await session.scalars(select(AgentRun).where(AgentRun.status == RunStatus.QUEUED))
            ).all()
        )
        outputs = list(
            (
                await session.scalars(
                    select(SlackOutput).where(SlackOutput.status == DeliveryStatus.PENDING)
                )
            ).all()
        )
    for event in events:
        await enqueue_slack_event(event.id)
    for run in runs:
        await enqueue_agent_run(run.id, run.conversation_id)
    for output in outputs:
        await enqueue_slack_output(output.id)
    if events or runs or outputs:
        log_event(
            logger,
            "pending_work_recovered",
            recovered_events=len(events),
            recovered_runs=len(runs),
            recovered_outputs=len(outputs),
        )


async def recover_interrupted_jobs() -> None:
    """Release dead-worker locks; never replay an investigation's memory side effects."""
    stalled = await app.job_manager.get_stalled_jobs(seconds_since_heartbeat=60)
    for job in stalled:
        if not job.task_name.startswith("cerebro.jobs.tasks.") or job.id is None:
            continue
        if job.task_name == "cerebro.jobs.tasks.execute_agent_run":
            async with open_session() as session:
                run = await session.get(
                    AgentRun, UUID(str(job.task_kwargs["run_id"])), with_for_update=True
                )
                if run and run.status == RunStatus.RUNNING:
                    run.status = RunStatus.FAILED
                    run.error_code = "worker_interrupted"
                    run.error_detail = "worker_heartbeat_expired"
                    run.finished_at = datetime.now(UTC)
                    conversation = await session.get(Conversation, run.conversation_id)
                    if conversation:
                        conversation.state = ConversationState.FAILED
                        if get_config().global_mode == GlobalMode.ENABLED:
                            await session.execute(
                                insert(SlackOutput)
                                .values(
                                    conversation_id=conversation.id,
                                    agent_run_id=run.id,
                                    slack_channel_id=conversation.slack_channel_id,
                                    slack_thread_ts=conversation.slack_thread_ts,
                                    idempotency_key=f"agent-run:{run.id}:error",
                                    body=(
                                        "La respuesta se interrumpió. "
                                        "Puedes pedirme que lo intente de nuevo."
                                    ),
                                    kind=SlackOutputKind.ERROR,
                                    status=DeliveryStatus.PENDING,
                                )
                                .on_conflict_do_nothing(
                                    index_elements=[SlackOutput.idempotency_key]
                                )
                            )
                    await session.commit()
        # Finalize only after domain state is committed: another recovery closes either gap.
        await app.job_manager.finish_job_by_id_async(job.id, JobStatus.FAILED, delete_job=False)


@app.periodic(cron="*/5 * * * *", periodic_id="operational-watchdog")
@app.task(name="cerebro.jobs.tasks.operational_watchdog", queue="control")
async def operational_watchdog(timestamp: int) -> None:
    """Emit aggregate local warnings without copying customer content out of Cerebro."""
    del timestamp
    now = datetime.now(UTC)
    async with open_session() as session:
        stale_events = await session.scalar(
            select(func.count())
            .select_from(SlackEvent)
            .where(
                SlackEvent.disposition.in_(
                    [SlackEventDisposition.RECEIVED, SlackEventDisposition.QUEUED]
                ),
                SlackEvent.received_at < now - timedelta(minutes=2),
            )
        )
        stale_queued_runs = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(
                AgentRun.status == RunStatus.QUEUED,
                AgentRun.created_at < now - timedelta(minutes=5),
            )
        )
        stale_running_runs = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(
                AgentRun.status == RunStatus.RUNNING,
                AgentRun.started_at < now - timedelta(seconds=240),
            )
        )
        stale_outputs = await session.scalar(
            select(func.count())
            .select_from(SlackOutput)
            .where(
                SlackOutput.status == DeliveryStatus.PENDING,
                SlackOutput.created_at < now - timedelta(minutes=2),
            )
        )
        failed_runs = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(
                AgentRun.status == RunStatus.FAILED,
                AgentRun.finished_at >= now - timedelta(minutes=5),
            )
        )
        failed_events = await session.scalar(
            select(func.count())
            .select_from(SlackEvent)
            .where(
                SlackEvent.disposition == SlackEventDisposition.FAILED,
                SlackEvent.received_at >= now - timedelta(minutes=5),
            )
        )
        failed_outputs = await session.scalar(
            select(func.count())
            .select_from(SlackOutput)
            .where(
                SlackOutput.status == DeliveryStatus.FAILED,
                SlackOutput.updated_at >= now - timedelta(minutes=5),
            )
        )
        stale_components = await session.scalar(
            select(func.count())
            .select_from(RuntimeHeartbeat)
            .where(
                (RuntimeHeartbeat.status != "running")
                | (RuntimeHeartbeat.last_seen_at < now - timedelta(seconds=45))
            )
        )
    values = {
        "stale_events": stale_events or 0,
        "stale_queued_runs": stale_queued_runs or 0,
        "stale_outputs": stale_outputs or 0,
        "failed_count": (failed_runs or 0) + (failed_events or 0) + (failed_outputs or 0),
        "stale_components": stale_components or 0,
    }
    log_event(
        logger,
        "operational_watchdog",
        level=logging.WARNING if any(values.values()) else logging.INFO,
        **values,
    )
    if stale_running_runs:
        log_event(
            logger,
            "long_running_investigations",
            level=logging.INFO,
            stale_running_runs=stale_running_runs,
        )
