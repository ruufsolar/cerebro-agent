import asyncio
import logging
from typing import Any

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.app.async_app import AsyncApp

from cerebro.config import get_config
from cerebro.jobs.app import app as job_app
from cerebro.observability import configure_logging, log_event
from cerebro.ops.runtime import RuntimeComponent, maintain_heartbeat
from cerebro.slack.events import normalize_event
from cerebro.slack.service import receive_event

logger = logging.getLogger(__name__)


async def _receive(body: dict[str, Any], context: Any, ack: Any) -> None:
    await ack()
    try:
        bot_user_id = getattr(context, "bot_user_id", None)
        normalized = normalize_event(
            body,
            bot_user_id=bot_user_id if isinstance(bot_user_id, str) else None,
            config=get_config(),
        )
        await receive_event(normalized)
        log_event(logger, "slack_event_accepted", slack_event_type=normalized.event_type)
    except Exception as exc:
        log_event(
            logger,
            "slack_event_receive_failed",
            level=logging.ERROR,
            error_type=type(exc).__name__,
        )


def build_slack_app() -> AsyncApp:
    config = get_config()
    if not config.slack_ready:
        raise RuntimeError("CEREBRO_SLACK_APP_TOKEN and CEREBRO_SLACK_BOT_TOKEN are required")
    slack_app = AsyncApp(token=config.slack_bot_token)
    for event_type in (
        "app_mention",
        "assistant_thread_context_changed",
        "assistant_thread_started",
        "message",
        "reaction_added",
        "reaction_removed",
    ):
        slack_app.event(event_type)(_receive)
    return slack_app


async def main() -> None:
    config = get_config()
    configure_logging("slack", config)
    handler = AsyncSocketModeHandler(build_slack_app(), config.slack_app_token)
    async with job_app.open_async(), maintain_heartbeat(RuntimeComponent.SLACK, config):
        await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
