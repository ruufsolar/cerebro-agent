from uuid import UUID

from procrastinate.exceptions import AlreadyEnqueued

from cerebro.jobs.app import app


async def enqueue_slack_event(event_id: UUID) -> bool:
    try:
        await app.configure_task(
            "cerebro.jobs.tasks.process_slack_event",
            queueing_lock=f"slack-event:{event_id}",
        ).defer_async(event_id=str(event_id))
    except AlreadyEnqueued:
        return False
    return True


async def enqueue_agent_run(run_id: UUID, conversation_id: UUID) -> bool:
    try:
        await app.configure_task(
            "cerebro.jobs.tasks.execute_agent_run",
            queueing_lock=f"agent-run:{run_id}",
            lock=f"conversation:{conversation_id}",
        ).defer_async(run_id=str(run_id))
    except AlreadyEnqueued:
        return False
    return True


async def enqueue_slack_output(output_id: UUID) -> bool:
    try:
        await app.configure_task(
            "cerebro.jobs.tasks.deliver_slack_output",
            queueing_lock=f"slack-output:{output_id}",
        ).defer_async(output_id=str(output_id))
    except AlreadyEnqueued:
        return False
    return True
