"""Privacy-safe structured application logging.

Handlers intentionally ignore arbitrary log messages and exception strings. Cerebro emits
operational facts through ``log_event``; third-party records are reduced to logger/level only.
"""

import json
import logging
import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from cerebro.config import AppConfig, get_config

_ALLOWED_FIELDS = {
    "agent_run_id",
    "attempts",
    "component",
    "completion_reason",
    "confidence",
    "conversation_id",
    "count",
    "delivery_status",
    "disposition",
    "duration_ms",
    "environment",
    "error_code",
    "error_type",
    "event_id",
    "failed_count",
    "image_count",
    "input_tokens",
    "instance_id",
    "knowledge_version",
    "model",
    "outcome",
    "output_id",
    "output_tokens",
    "prompt_version",
    "queue",
    "recovered_events",
    "recovered_outputs",
    "recovered_runs",
    "run_status",
    "slack_event_type",
    "stale_components",
    "stale_events",
    "stale_outputs",
    "stale_queued_runs",
    "stale_running_runs",
    "state",
    "tool_calls",
    "turns",
    "worker_role",
}
_SENSITIVE = re.compile(
    r"(?:xox[baprs]-|xapp-|sk-|https?://|data:image|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})",
    re.IGNORECASE,
)


def _safe_value(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, UUID | Enum):
        value = str(value)
    elif not isinstance(value, str):
        value = type(value).__name__
    value = value[:160]
    return "[redacted]" if _SENSITIVE.search(value) else value


def _safe_fields(values: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    return {
        key: _safe_value(value)
        for key, value in values.items()
        if key in _ALLOWED_FIELDS and value is not None
    }


class SafeFormatter(logging.Formatter):
    def __init__(self, *, json_output: bool) -> None:
        super().__init__()
        self.json_output = json_output

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "cerebro_event", None)
        if not isinstance(event, str):
            event = (
                "third_party_log" if not record.name.startswith("cerebro") else "application_log"
            )
        elif _SENSITIVE.search(event):
            event = "redacted_event"
        fields = getattr(record, "cerebro_fields", {})
        safe = _safe_fields(fields) if isinstance(fields, dict) else {}
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": event[:80],
            **safe,
        }
        if self.json_output:
            return json.dumps(payload, separators=(",", ":"), sort_keys=True)
        details = " ".join(f"{key}={value}" for key, value in safe.items())
        return f"{payload['timestamp']} {record.levelname} {record.name} {event}" + (
            f" {details}" if details else ""
        )


def configure_logging(component: str, config: AppConfig | None = None) -> None:
    config = config or get_config()
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(json_output=config.log_format == "json"))
    root.addHandler(handler)
    root.setLevel(config.log_level.upper())
    for logger_name in ("aiohttp", "asyncio", "httpx", "openai", "slack_bolt", "slack_sdk"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    log_event(
        logging.getLogger("cerebro.runtime"),
        "process_started",
        component=component,
        environment=config.environment,
    )


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    logger.log(
        level,
        event,
        extra={"cerebro_event": event, "cerebro_fields": _safe_fields(fields)},
    )
