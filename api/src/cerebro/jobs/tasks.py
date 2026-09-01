import logging
from uuid import UUID

from sqlalchemy import select

from cerebro.db.enums import DeliveryStatus, RunStatus, SlackEventDisposition
from cerebro.db.models import AgentRun, SlackEvent, SlackOutput
from cerebro.db.session import open_session
from cerebro.jobs.app import app
from cerebro.jobs.enqueue import enqueue_agent_run, enqueue_slack_event, enqueue_slack_output
from cerebro.slack.pipeline import deliver_output, execute_run
from cerebro.slack.service import process_stored_event

logger = logging.getLogger(__name__)


@app.task(name="cerebro.jobs.tasks.foundation_noop")
async def foundation_noop() -> None:
    logger.info("cerebro worker is operational")


@app.task(name="cerebro.jobs.tasks.process_slack_event")
async def process_slack_event(event_id: str) -> None:
    await process_stored_event(UUID(event_id))


@app.task(name="cerebro.jobs.tasks.execute_agent_run")
async def execute_agent_run(run_id: str) -> None:
    await execute_run(UUID(run_id))


@app.task(name="cerebro.jobs.tasks.deliver_slack_output")
async def deliver_slack_output(output_id: str) -> None:
    await deliver_output(UUID(output_id))


@app.periodic(cron="* * * * *", periodic_id="durable-recovery")
@app.task(name="cerebro.jobs.tasks.recover_pending_work")
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
