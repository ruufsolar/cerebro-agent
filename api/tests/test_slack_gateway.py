from typing import Any

import pytest

from cerebro.slack.gateway import SlackSdkGateway


class FakeWebClient:
    def __init__(self) -> None:
        self.status_calls: list[dict[str, Any]] = []
        self.message_calls: list[dict[str, Any]] = []
        self.closed = False

    async def assistant_threads_setStatus(self, **kwargs: Any) -> dict[str, bool]:
        self.status_calls.append(kwargs)
        return {"ok": True}

    async def chat_postMessage(self, **kwargs: Any) -> dict[str, str | bool]:
        self.message_calls.append(kwargs)
        return {"ok": True, "ts": "200.300"}

    async def close(self) -> None:
        self.closed = True


async def test_gateway_uses_root_thread_status_and_deterministic_message_id() -> None:
    client = FakeWebClient()
    gateway = SlackSdkGateway(client)

    await gateway.set_status("C1", "100.200", "Investigando…")
    await gateway.clear_status("C1", "100.200")
    timestamp = await gateway.post_message("C1", "100.200", "respuesta", "uuid-1")
    await gateway.close()

    assert client.status_calls == [
        {"channel_id": "C1", "thread_ts": "100.200", "status": "Investigando…"},
        {"channel_id": "C1", "thread_ts": "100.200", "status": ""},
    ]
    assert client.message_calls == [
        {
            "channel": "C1",
            "thread_ts": "100.200",
            "text": "respuesta",
            "client_msg_id": "uuid-1",
        }
    ]
    assert timestamp == "200.300"
    assert client.closed is True


async def test_gateway_rejects_a_post_without_slack_timestamp() -> None:
    client = FakeWebClient()

    async def post_without_timestamp(**kwargs: Any) -> dict[str, bool]:
        client.message_calls.append(kwargs)
        return {"ok": True}

    client.chat_postMessage = post_without_timestamp  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="no timestamp"):
        await SlackSdkGateway(client).post_message("C1", "100.200", "respuesta", "uuid-1")
