import asyncio
import logging

from cerebro.agent.runner import close_agent_runner, start_agent_runner
from cerebro.db.session import dispose_engine
from cerebro.jobs.app import app
from cerebro.jobs.schema import ensure_procrastinate_schema
from cerebro.slack.gateway import close_slack_gateway

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def main() -> None:
    ensure_procrastinate_schema()
    await start_agent_runner()
    try:
        async with app.open_async():
            await app.run_worker_async()
    finally:
        await close_agent_runner()
        await close_slack_gateway()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
