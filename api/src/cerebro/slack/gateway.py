from typing import Any, Protocol

from slack_sdk.web.async_client import AsyncWebClient

from cerebro.config import get_config


class SlackGateway(Protocol):
    async def set_status(self, channel: str, thread_ts: str, status: str) -> None: ...

    async def clear_status(self, channel: str, thread_ts: str) -> None: ...

    async def post_message(
        self, channel: str, thread_ts: str, text: str, client_msg_id: str
    ) -> str: ...

    async def close(self) -> None: ...


class SlackSdkGateway:
    def __init__(self, client: Any | None = None) -> None:
        self._client: Any = client or AsyncWebClient(token=get_config().slack_bot_token)

    async def set_status(self, channel: str, thread_ts: str, status: str) -> None:
        await self._client.assistant_threads_setStatus(
            channel_id=channel,
            thread_ts=thread_ts,
            status=status,
        )

    async def clear_status(self, channel: str, thread_ts: str) -> None:
        await self.set_status(channel, thread_ts, "")

    async def post_message(
        self, channel: str, thread_ts: str, text: str, client_msg_id: str
    ) -> str:
        response = await self._client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=text,
            client_msg_id=client_msg_id,
        )
        timestamp = response.get("ts")
        if not isinstance(timestamp, str):
            raise RuntimeError("Slack chat.postMessage returned no timestamp")
        return timestamp

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()
            return
        session = getattr(self._client, "session", None)
        if session is not None and not session.closed:
            await session.close()


_gateway: SlackGateway | None = None


def get_slack_gateway() -> SlackGateway:
    global _gateway
    if _gateway is None:
        _gateway = SlackSdkGateway()
    return _gateway


def set_slack_gateway(gateway: SlackGateway | None) -> None:
    global _gateway
    _gateway = gateway


async def close_slack_gateway() -> None:
    global _gateway
    if _gateway is not None:
        await _gateway.close()
        _gateway = None
