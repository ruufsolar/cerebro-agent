"""Cerebro's bridge to the shared memory of Ruuf's agents.

Every case here drives the real client through a mock transport, so what is
tested is the requests Cerebro actually sends and what it does with what comes
back — including the two answers that matter most: nothing configured, and a
platform that is not answering.
"""

import httpx
import pytest

from cerebro.agent import shared_memory
from cerebro.agent.data_tools import SharedMemoryNote, safe_input_summary
from cerebro.memory_client import AsyncMemoryClient, Credentials

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
        assert "no respondió" in observation.summary


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

    async def test_the_audit_row_records_the_shape_and_not_the_memory(self) -> None:
        # The content is already in the store; an audit row does not need a
        # second copy of it.
        summary = safe_input_summary(SharedMemoryNote(content="Una cosa aprendida", kind="rule"))
        assert summary == {"kind": "rule", "characters": len("Una cosa aprendida")}
