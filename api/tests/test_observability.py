import json
import logging

from cerebro.observability import SafeFormatter


def test_safe_formatter_drops_arbitrary_messages_and_exception_text() -> None:
    sentinel = "customer@example.com xoxb-super-secret https://files.slack.com/private"
    record = logging.LogRecord(
        name="third.party",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=sentinel,
        args=(),
        exc_info=None,
    )

    encoded = SafeFormatter(json_output=True).format(record)
    payload = json.loads(encoded)

    assert sentinel not in encoded
    assert "customer@example.com" not in encoded
    assert payload["event"] == "third_party_log"
    assert payload["logger"] == "third.party"


def test_safe_formatter_allowlists_and_redacts_structured_values() -> None:
    record = logging.LogRecord(
        name="cerebro.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="ignored",
        args=(),
        exc_info=None,
    )
    record.cerebro_event = "run_failed"
    record.cerebro_fields = {
        "error_type": "RuntimeError",
        "model": "https://secret.invalid",
        "customer_name": "Never print me",
    }

    payload = json.loads(SafeFormatter(json_output=True).format(record))

    assert payload["error_type"] == "RuntimeError"
    assert payload["model"] == "[redacted]"
    assert "customer_name" not in payload
