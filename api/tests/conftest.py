import os
from collections.abc import AsyncIterator, Iterator
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from procrastinate import PsycopgConnector
from procrastinate.testing import InMemoryConnector
from sqlalchemy import delete

from cerebro.agent.runner import FakeAgentRunner, set_agent_runner
from cerebro.config import get_config
from cerebro.db.models import (
    AgentRun,
    Conversation,
    Feedback,
    Message,
    RuntimeHeartbeat,
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
    test_url = os.environ.get("CEREBRO_TEST_DATABASE_URL")
    if not test_url:
        pytest.skip("requires a disposable CEREBRO_TEST_DATABASE_URL")
    if not urlparse(test_url).path.rstrip("/").endswith("_test"):
        pytest.fail("destructive fixtures require a database name ending in _test")
    patch = pytest.MonkeyPatch()
    patch.setenv("CEREBRO_DATABASE_URL", test_url)
    get_config.cache_clear()
    await dispose_engine()
    try:
        with job_app.replace_connector(PsycopgConnector(conninfo=test_url)):
            async with open_session() as session:
                for model in (
                    RuntimeHeartbeat,
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
    finally:
        patch.undo()
        set_agent_runner(FakeAgentRunner())
        set_slack_gateway(None)
        set_slack_file_client(None)
        get_config.cache_clear()
        await dispose_engine()
