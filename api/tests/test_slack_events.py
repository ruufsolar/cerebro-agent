from typing import Any

import pytest

from cerebro.config import AppConfig
from cerebro.slack.events import SlackEventKind, normalize_event


def envelope(event_type: str, **event: Any) -> dict[str, Any]:
    return {
        "event_id": "Ev-1",
        "team_id": "T-1",
        "event": {"type": event_type, **event},
    }


@pytest.mark.parametrize("channel_type", ["channel", "group"])
def test_root_mention_accepts_public_and_private_channels(channel_type: str) -> None:
    result = normalize_event(
        envelope(
            "app_mention",
            channel="C1",
            channel_type=channel_type,
            ts="100.2",
            user="U1",
            text="<@BOT> identifica esto",
        ),
        bot_user_id="BOT",
        config=AppConfig(),
    )

    assert result.kind is SlackEventKind.MENTION
    assert result.payload["thread_ts"] == "100.2"


def test_mention_inside_thread_keeps_root_thread() -> None:
    result = normalize_event(
        envelope(
            "app_mention",
            channel="C1",
            channel_type="channel",
            ts="100.3",
            thread_ts="100.1",
            user="U1",
            text="<@BOT> más contexto",
        ),
        bot_user_id="BOT",
        config=AppConfig(),
    )

    assert result.kind is SlackEventKind.MENTION
    assert result.payload["thread_ts"] == "100.1"


def test_human_thread_followup_is_accepted() -> None:
    result = normalize_event(
        envelope(
            "message",
            channel="C1",
            channel_type="group",
            ts="100.4",
            thread_ts="100.1",
            user="U1",
            text="el monto es 100.000",
        ),
        bot_user_id="BOT",
        config=AppConfig(),
    )

    assert result.kind is SlackEventKind.THREAD_MESSAGE


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        ({"channel_type": "im", "thread_ts": "1"}, "unsupported_channel_type"),
        ({"channel_type": "channel"}, "message_outside_thread"),
        ({"channel_type": "channel", "thread_ts": "1", "bot_id": "B"}, "non_human_message"),
        (
            {"channel_type": "channel", "thread_ts": "1", "subtype": "message_changed"},
            "non_human_message",
        ),
        (
            {"channel_type": "channel", "thread_ts": "1", "text": "<@BOT> hola"},
            "duplicate_mention_delivery",
        ),
    ],
)
def test_unsupported_messages_are_ignored(event: dict[str, Any], reason: str) -> None:
    message = {"channel": "C1", "ts": "2", "user": "U1", "text": "hola", **event}
    result = normalize_event(
        envelope("message", **message),
        bot_user_id="BOT",
        config=AppConfig(),
    )

    assert result.kind is SlackEventKind.IGNORED
    assert result.ignore_reason == reason


def test_only_bounded_image_metadata_is_retained() -> None:
    result = normalize_event(
        envelope(
            "app_mention",
            channel="C1",
            channel_type="channel",
            ts="100.2",
            user="U1",
            text="pago",
            files=[
                {
                    "id": "F1",
                    "name": "cartola.png",
                    "mimetype": "image/png",
                    "size": 200,
                    "url_private": "https://secret.example/file",
                    "thumb_360": "https://secret.example/thumb",
                },
                {"id": "F2", "mimetype": "application/pdf", "size": 100},
                {"id": "F3", "mimetype": "image/jpeg", "size": 10_000},
            ],
        ),
        bot_user_id="BOT",
        config=AppConfig(max_image_bytes=1_024),
    )

    assert result.payload["files"] == [
        {"id": "F1", "name": "cartola.png", "mimetype": "image/png", "size": 200}
    ]
    assert "secret.example" not in repr(result.payload)


@pytest.mark.parametrize("reaction", ["cheese_wedge", "electric_plug"])
def test_supported_reactions_are_normalized(reaction: str) -> None:
    result = normalize_event(
        envelope(
            "reaction_added",
            reaction=reaction,
            user="U1",
            item={"type": "message", "channel": "C1", "ts": "10.2"},
        ),
        bot_user_id="BOT",
        config=AppConfig(),
    )

    assert result.kind is SlackEventKind.REACTION_ADDED


def test_unknown_reaction_is_ignored() -> None:
    result = normalize_event(
        envelope(
            "reaction_added",
            reaction="eyes",
            user="U1",
            item={"type": "message", "channel": "C1", "ts": "10.2"},
        ),
        bot_user_id="BOT",
        config=AppConfig(),
    )

    assert result.kind is SlackEventKind.IGNORED


@pytest.mark.parametrize(
    "event_type", ["assistant_thread_started", "assistant_thread_context_changed"]
)
def test_assistant_panel_events_are_explicitly_ignored(event_type: str) -> None:
    result = normalize_event(
        envelope(event_type, channel_id="D1", thread_ts="10.1"),
        bot_user_id="BOT",
        config=AppConfig(),
    )

    assert result.kind is SlackEventKind.IGNORED
    assert result.ignore_reason == "unsupported_event_type"
