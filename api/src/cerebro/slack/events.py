from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cerebro.config import AppConfig


class SlackEventKind(StrEnum):
    MENTION = "mention"
    THREAD_MESSAGE = "thread_message"
    REACTION_ADDED = "reaction_added"
    REACTION_REMOVED = "reaction_removed"
    IGNORED = "ignored"


@dataclass(frozen=True)
class NormalizedSlackEvent:
    slack_event_id: str
    event_type: str
    kind: SlackEventKind
    payload: dict[str, Any]
    ignore_reason: str | None = None


def _safe_images(files: object, config: AppConfig) -> list[dict[str, Any]]:
    if not isinstance(files, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in files:
        if len(result) >= config.max_images or not isinstance(raw, dict):
            break
        mimetype = raw.get("mimetype")
        size = raw.get("size")
        file_id = raw.get("id")
        if (
            not isinstance(mimetype, str)
            or not mimetype.startswith("image/")
            or not isinstance(size, int)
            or size > config.max_image_bytes
            or not isinstance(file_id, str)
        ):
            continue
        result.append(
            {
                "id": file_id,
                "name": raw.get("name") if isinstance(raw.get("name"), str) else None,
                "mimetype": mimetype,
                "size": size,
            }
        )
    return result


def _ignored(event_id: str, event_type: str, reason: str) -> NormalizedSlackEvent:
    return NormalizedSlackEvent(
        slack_event_id=event_id,
        event_type=event_type,
        kind=SlackEventKind.IGNORED,
        payload={"event_id": event_id, "event_type": event_type, "ignore_reason": reason},
        ignore_reason=reason,
    )


def normalize_event(
    body: dict[str, Any], *, bot_user_id: str | None, config: AppConfig
) -> NormalizedSlackEvent:
    """Reduce a Slack envelope to the only fields Cerebro is allowed to retain."""
    event_id = body.get("event_id")
    event = body.get("event")
    if not isinstance(event_id, str) or not isinstance(event, dict):
        return _ignored(str(event_id or "missing"), "unknown", "invalid_envelope")

    event_type = event.get("type")
    if not isinstance(event_type, str):
        return _ignored(event_id, "unknown", "missing_event_type")

    if event_type in {"reaction_added", "reaction_removed"}:
        item = event.get("item")
        reaction = event.get("reaction")
        user = event.get("user")
        if (
            not isinstance(item, dict)
            or item.get("type") != "message"
            or reaction not in {"cheese_wedge", "electric_plug"}
            or not isinstance(user, str)
        ):
            return _ignored(event_id, event_type, "unsupported_reaction")
        channel = item.get("channel")
        message_ts = item.get("ts")
        if not isinstance(channel, str) or not isinstance(message_ts, str):
            return _ignored(event_id, event_type, "invalid_reaction_item")
        kind = (
            SlackEventKind.REACTION_ADDED
            if event_type == "reaction_added"
            else SlackEventKind.REACTION_REMOVED
        )
        return NormalizedSlackEvent(
            slack_event_id=event_id,
            event_type=event_type,
            kind=kind,
            payload={
                "event_id": event_id,
                "event_type": event_type,
                "team_id": body.get("team_id"),
                "channel": channel,
                "message_ts": message_ts,
                "user": user,
                "reaction": reaction,
            },
        )

    if event_type not in {"app_mention", "message"}:
        return _ignored(event_id, event_type, "unsupported_event_type")
    if event.get("channel_type") not in {None, "channel", "group"}:
        return _ignored(event_id, event_type, "unsupported_channel_type")
    if event.get("subtype") is not None or event.get("bot_id") is not None:
        return _ignored(event_id, event_type, "non_human_message")

    user = event.get("user")
    channel = event.get("channel")
    message_ts = event.get("ts")
    text = event.get("text")
    if not all(isinstance(value, str) for value in (user, channel, message_ts)):
        return _ignored(event_id, event_type, "invalid_message")
    if event_type == "message":
        if not isinstance(event.get("thread_ts"), str):
            return _ignored(event_id, event_type, "message_outside_thread")
        if bot_user_id and isinstance(text, str) and f"<@{bot_user_id}>" in text:
            return _ignored(event_id, event_type, "duplicate_mention_delivery")

    root_ts = event.get("thread_ts") or message_ts
    kind = SlackEventKind.MENTION if event_type == "app_mention" else SlackEventKind.THREAD_MESSAGE
    return NormalizedSlackEvent(
        slack_event_id=event_id,
        event_type=event_type,
        kind=kind,
        payload={
            "event_id": event_id,
            "event_type": event_type,
            "team_id": body.get("team_id"),
            "channel": channel,
            "message_ts": message_ts,
            "thread_ts": root_ts,
            "user": user,
            "text": text if isinstance(text, str) else "",
            "files": _safe_images(event.get("files"), config),
        },
    )
