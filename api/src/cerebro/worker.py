import argparse
import asyncio
from typing import Literal, cast

from cerebro.agent.runner import close_agent_runner, start_agent_runner
from cerebro.config import get_config
from cerebro.db.session import dispose_engine
from cerebro.jobs.app import app
from cerebro.jobs.schema import ensure_procrastinate_schema
from cerebro.observability import configure_logging
from cerebro.ops.runtime import RuntimeComponent, maintain_heartbeat
from cerebro.slack.gateway import close_slack_gateway
from cerebro.slack.images import close_slack_file_client, sweep_abandoned_image_directories

WorkerRole = Literal["control", "agent"]


async def main(role: WorkerRole) -> None:
    config = get_config()
    configure_logging(f"{role}-worker", config)
    ensure_procrastinate_schema()
    if role == "agent":
        sweep_abandoned_image_directories()
        await start_agent_runner()
    component = (
        RuntimeComponent.AGENT_WORKER if role == "agent" else RuntimeComponent.CONTROL_WORKER
    )
    try:
        async with app.open_async(), maintain_heartbeat(component, config):
            await app.run_worker_async(
                queues=[role],
                concurrency=config.worker_concurrency,
                name=f"cerebro-{role}",
                shutdown_graceful_timeout=240,
            )
    finally:
        if role == "agent":
            await close_agent_runner()
            await close_slack_file_client()
        await close_slack_gateway()
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("control", "agent"), required=True)
    args = parser.parse_args()
    asyncio.run(main(cast(WorkerRole, args.role)))
