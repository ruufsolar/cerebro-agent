from contextlib import asynccontextmanager

import pytest

from cerebro import worker
from cerebro.config import get_config
from cerebro.ops.runtime import RuntimeComponent


@pytest.mark.parametrize(
    ("role", "component", "starts_agent"),
    [
        ("control", RuntimeComponent.CONTROL_WORKER, False),
        ("agent", RuntimeComponent.AGENT_WORKER, True),
    ],
)
async def test_worker_role_isolation_and_bounded_concurrency(
    monkeypatch, role, component, starts_agent
) -> None:
    calls: list[tuple[str, object]] = []

    @asynccontextmanager
    async def context(*_args, **_kwargs):
        yield

    def heartbeat_context(actual_component, _config):
        calls.append(("heartbeat", actual_component))
        return context()

    async def run_worker_async(**kwargs) -> None:
        calls.append(("run", kwargs))

    async def async_call(name: str) -> None:
        calls.append((name, None))

    monkeypatch.setattr(worker, "ensure_procrastinate_schema", lambda: None)
    monkeypatch.setattr(worker, "maintain_heartbeat", heartbeat_context)
    monkeypatch.setattr(worker.app, "open_async", context)
    monkeypatch.setattr(worker.app, "run_worker_async", run_worker_async)
    monkeypatch.setattr(
        worker,
        "start_agent_runner",
        lambda: async_call("start_agent"),
    )
    monkeypatch.setattr(
        worker,
        "close_agent_runner",
        lambda: async_call("close_agent"),
    )
    monkeypatch.setattr(
        worker,
        "close_slack_file_client",
        lambda: async_call("close_files"),
    )
    monkeypatch.setattr(
        worker,
        "close_slack_gateway",
        lambda: async_call("close_slack"),
    )
    monkeypatch.setattr(
        worker,
        "dispose_engine",
        lambda: async_call("dispose"),
    )
    monkeypatch.setattr(
        worker,
        "sweep_abandoned_image_directories",
        lambda: calls.append(("sweep", None)),
    )
    get_config.cache_clear()

    await worker.main(role)

    run = next(value for name, value in calls if name == "run")
    assert isinstance(run, dict)
    assert run["queues"] == [role]
    assert run["concurrency"] == 2
    assert run["shutdown_graceful_timeout"] == 240
    assert (("start_agent", None) in calls) is starts_agent
    assert (("sweep", None) in calls) is starts_agent
    assert (("close_agent", None) in calls) is starts_agent
    assert (("close_files", None) in calls) is starts_agent
    assert run["name"] == f"cerebro-{role}"
    assert ("heartbeat", component) in calls
