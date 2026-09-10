import logging
from contextlib import asynccontextmanager
from typing import Any

import pytest

from cerebro.jobs.app import app


def test_control_and_agent_tasks_are_isolated_by_queue() -> None:
    app.perform_import_paths()

    assert app.tasks["cerebro.jobs.tasks.process_slack_event"].queue == "control"
    assert app.tasks["cerebro.jobs.tasks.deliver_slack_output"].queue == "control"
    assert app.tasks["cerebro.jobs.tasks.recover_pending_work"].queue == "control"
    assert app.tasks["cerebro.jobs.tasks.operational_watchdog"].queue == "control"
    assert app.tasks["cerebro.jobs.tasks.execute_agent_run"].queue == "agent"


@pytest.mark.parametrize("stale_workers, level", [(0, logging.INFO), (1, logging.WARNING)])
async def test_watchdog_uses_worker_health_not_investigation_age(
    monkeypatch: pytest.MonkeyPatch,
    stale_workers: int,
    level: int,
) -> None:
    from cerebro.jobs import tasks

    # Only two long-running investigations; a stale worker independently changes severity.
    counts = iter([0, 0, 2, 0, 0, 0, 0, stale_workers])
    events: list[tuple[str, dict[str, Any]]] = []

    class Session:
        async def scalar(self, query: object) -> int:
            return next(counts)

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(tasks, "open_session", session)
    monkeypatch.setattr(
        tasks, "log_event", lambda logger, event, **fields: events.append((event, fields))
    )
    await tasks.operational_watchdog(0)
    assert events[0][0] == "operational_watchdog"
    assert events[0][1]["level"] == level
    assert events[1][0] == "long_running_investigations"
    assert events[1][1]["level"] == logging.INFO
