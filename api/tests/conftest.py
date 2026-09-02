import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from procrastinate.testing import InMemoryConnector
from sqlalchemy import delete

from cerebro.agent.runner import FakeAgentRunner, set_agent_runner
from cerebro.config import get_config
from cerebro.db.models import (
    AgentRun,
    Conversation,
    Feedback,
    Message,
    SlackEvent,
    SlackOutput,
    ToolCall,
)
from cerebro.db.session import dispose_engine, open_session
from cerebro.jobs.app import app as job_app
from cerebro.slack.gateway import set_slack_gateway
from cerebro.slack.images import set_slack_file_client


@pytest.fixture
def memory_jobs() -> Iterator[InMemoryConnector]:
    connector = InMemoryConnector()
    with job_app.replace_connector(connector):
        yield connector


@pytest_asyncio.fixture
async def clean_database() -> AsyncIterator[None]:
    if not os.environ.get("CEREBRO_DATABASE_URL"):
        pytest.skip("requires CEREBRO_DATABASE_URL and an Alembic-upgraded PostgreSQL")
    get_config.cache_clear()
    await dispose_engine()
    async with open_session() as session:
        for model in (
            Feedback,
            SlackOutput,
            ToolCall,
            AgentRun,
            Message,
            Conversation,
            SlackEvent,
        ):
            await session.execute(delete(model))
        await session.commit()
    yield
    set_agent_runner(FakeAgentRunner())
    set_slack_gateway(None)
    set_slack_file_client(None)
    get_config.cache_clear()
    await dispose_engine()
