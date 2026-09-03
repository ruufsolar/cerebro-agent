import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select

from cerebro.db.enums import DeliveryStatus, RunStatus, SlackEventDisposition
from cerebro.db.models import AgentRun, RuntimeHeartbeat, SlackEvent, SlackOutput
from cerebro.db.session import open_session
from cerebro.jobs.app import app
from cerebro.jobs.enqueue import enqueue_agent_run, enqueue_slack_event, enqueue_slack_output
from cerebro.observability import log_event
from cerebro.slack.pipeline import deliver_output, execute_run
from cerebro.slack.service import process_stored_event

logger = logging.getLogger(__name__)


@app.task(name="cerebro.jobs.tasks.foundation_noop", queue="control")
async def foundation_noop() -> None:
    log_event(logger, "worker_operational", queue="control")


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
        "stale_running_runs": stale_running_runs or 0,
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
