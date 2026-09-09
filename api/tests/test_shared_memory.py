"""Cerebro's bridge to the shared memory of Ruuf's agents.

Every case here drives the real client through a mock transport, so what is
tested is the requests Cerebro actually sends and what it does with what comes
back — including the two answers that matter most: nothing configured, and a
platform that is not answering.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import get_args

import httpx
import pytest

from cerebro.agent import shared_memory
from cerebro.agent.data_tools import SharedMemoryNote, safe_input_summary
from cerebro.memory_client import AsyncMemoryClient, Credentials

STORED = {"id": "1", "content": "Algo aprendido hoy", "tier": "short_term"}

BRIEF = {
    "stable": "Eres Cerebro, el agente de FinOps de RUUF.",
    "volatile": "Ops pidió no cerrar una identificación con sólo una captura.",
    "memory_clock": 31,
}


def _client(handler: object) -> AsyncMemoryClient:
    transport = httpx.MockTransport(handler)  # pyright: ignore[reportArgumentType]
    return AsyncMemoryClient(
        "cerebro",
        Credentials(base_url="https://agents.test", static_token="token"),
        client=httpx.AsyncClient(transport=transport),
    )


@pytest.fixture(autouse=True)
def _forget_client() -> None:
    shared_memory.client.cache_clear()
    shared_memory.forget()


def _counting(response: httpx.Response) -> tuple[AsyncMemoryClient, list[httpx.Request]]:
    """A client that answers with `response` and keeps every request, so a test
    can assert on how many times the platform was actually asked."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return _client(handle), seen


def _counting_briefs(write: httpx.Response) -> tuple[AsyncMemoryClient, list[httpx.Request]]:
    """The same, for a test that writes: the writes get `write`, and only the
    brief requests are counted."""
    briefs: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/memories"):
            return write
        briefs.append(request)
        return httpx.Response(200, json=BRIEF)

    return _client(handle), briefs


def _then_unreachable() -> Callable[[httpx.Request], httpx.Response]:
    """Answers the first request and refuses every one after it."""
    answered = False

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal answered
        if answered:
            raise httpx.ConnectError("connection refused", request=request)
        answered = True
        return httpx.Response(200, json=BRIEF)

    return handle


def _age(seconds: float) -> None:
    """Move the cached brief that far into the past, so the next `load` sees the
    age it would have after that long without touching the clock."""
    cached = shared_memory._brief
    assert cached is not None
    shared_memory._brief = replace(cached, fetched_at=cached.fetched_at - seconds)


class TestWithoutTheStore:
    async def test_no_configuration_means_no_block_and_no_tool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A deployment without shared memory is a deployment without one, not a
        # failure: Cerebro answers exactly as it did before.
        monkeypatch.delenv("RUUF_AGENTS_URL", raising=False)
        assert shared_memory.client() is None
        assert await shared_memory.load() is None

    async def test_an_unreachable_platform_is_no_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        monkeypatch.setattr(shared_memory, "client", lambda: _client(refuse))
        assert await shared_memory.load() is None

    async def test_a_failed_write_says_so_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            shared_memory, "client", lambda: _client(lambda request: httpx.Response(500))
        )
        observation = await shared_memory.remember(SharedMemoryNote(content="Algo aprendido hoy"))
        assert observation.available is False
        # What the tool knows is that nothing was stored. Why is the client's
        # log line, not a cause to guess at in front of ops.
        assert "no quedó guardado" in observation.summary


class TestTheBlockAboveThePrompt:
    async def test_it_carries_the_memories_and_the_warning_about_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            shared_memory,
            "client",
            lambda: _client(lambda request: httpx.Response(200, json=BRIEF)),
        )
        context = await shared_memory.load()

        assert context is not None
        assert BRIEF["volatile"] in context.text
        # The store is written by Ruufians and by other agents; Cerebro already
        # treats Slack text that way and this gets the same treatment.
        assert "mandan tus reglas" in context.text

    async def test_the_version_identifies_the_store_the_run_saw(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            shared_memory,
            "client",
            lambda: _client(lambda request: httpx.Response(200, json=BRIEF)),
        )
        context = await shared_memory.load()

        assert context is not None
        assert context.version == "shared-memory-31"

    async def test_it_asks_for_a_budget_that_cannot_crowd_out_the_policy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=BRIEF)

        monkeypatch.setattr(shared_memory, "client", lambda: _client(handle))
        await shared_memory.load()

        assert seen[0].url.path == "/api/agents/cerebro/brief"
        assert seen[0].url.params["token_budget"] == "4000"


class TestTheCache:
    async def test_a_second_run_does_not_ask_the_platform_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, seen = _counting(httpx.Response(200, json=BRIEF))
        monkeypatch.setattr(shared_memory, "client", lambda: client)

        first = await shared_memory.load()
        second = await shared_memory.load()

        assert len(seen) == 1
        assert first is not None and second is not None
        # The same bytes, which is also what a provider caching a prompt prefix
        # needs to keep hitting its cache.
        assert first.text == second.text

    async def test_the_brief_is_read_again_once_it_is_old(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, seen = _counting(httpx.Response(200, json=BRIEF))
        monkeypatch.setattr(shared_memory, "client", lambda: client)

        await shared_memory.load()
        _age(shared_memory.BRIEF_TTL_SECONDS + 1)
        await shared_memory.load()

        assert len(seen) == 2

    async def test_a_write_puts_the_next_run_back_on_the_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # What Cerebro just learned is in the volatile block immediately; making
        # ops wait out the TTL for it would look like the write had not worked.
        client, briefs = _counting_briefs(httpx.Response(201, json=STORED))
        monkeypatch.setattr(shared_memory, "client", lambda: client)

        await shared_memory.load()
        await shared_memory.remember(SharedMemoryNote(content="Algo aprendido hoy"))
        await shared_memory.load()

        assert len(briefs) == 2

    async def test_a_failed_write_leaves_the_cached_brief_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, briefs = _counting_briefs(httpx.Response(422))
        monkeypatch.setattr(shared_memory, "client", lambda: client)

        await shared_memory.load()
        await shared_memory.remember(SharedMemoryNote(content="Algo aprendido hoy"))
        await shared_memory.load()

        assert len(briefs) == 1

    async def test_an_outage_keeps_serving_the_brief_it_last_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(_then_unreachable())
        monkeypatch.setattr(shared_memory, "client", lambda: client)
        good = await shared_memory.load()
        _age(shared_memory.BRIEF_TTL_SECONDS + 1)
        during_outage = await shared_memory.load()

        assert good is not None
        assert during_outage is not None
        assert during_outage.text == good.text

    async def test_a_long_outage_stops_pretending_the_brief_is_current(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(_then_unreachable())
        monkeypatch.setattr(shared_memory, "client", lambda: client)
        await shared_memory.load()
        _age(shared_memory.BRIEF_MAX_STALE_SECONDS + 1)

        assert await shared_memory.load() is None


class TestWriting:
    async def test_it_reports_the_text_the_platform_stored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The platform masks identifiers, so what came back is what was kept —
        # and that is what the model should be told.
        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                201,
                json={"id": "1", "content": "Escribir a [correo]", "tier": "short_term"},
            )

        monkeypatch.setattr(shared_memory, "client", lambda: _client(handle))
        observation = await shared_memory.remember(
            SharedMemoryNote(content="Escribir a juan@ruuf.solar", kind="procedure")
        )

        assert observation.available is True
        assert "[correo]" in observation.summary

    def test_the_kinds_offered_are_the_kinds_the_platform_stores(self) -> None:
        # `MemoryKind` in ruufsolar/gru. Offering a fourth kind here is a 422 the
        # model cannot see: the write is refused and the learning is lost.
        assert get_args(SharedMemoryNote.model_fields["kind"].annotation) == (
            "fact",
            "procedure",
            "rule",
        )

    async def test_the_audit_row_records_the_shape_and_not_the_memory(self) -> None:
        # The content is already in the store; an audit row does not need a
        # second copy of it.
        summary = safe_input_summary(SharedMemoryNote(content="Una cosa aprendida", kind="rule"))
        assert summary == {"kind": "rule", "characters": len("Una cosa aprendida")}
