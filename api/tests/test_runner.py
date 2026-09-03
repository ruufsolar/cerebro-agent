from datetime import UTC, datetime
from uuid import uuid4

from cerebro.agent.models import (
    Confidence,
    CustomerCandidate,
    IdentificationOutcome,
    PaymentIdentification,
)
from cerebro.agent.runner import AgentRunInput, FakeAgentRunner, TranscriptMessage


async def test_fake_runner_is_deterministic_and_records_calls() -> None:
    runner = FakeAgentRunner()
    request = AgentRunInput(
        run_id=uuid4(),
        slack_channel_id="C123",
        slack_thread_ts="123.456",
        requester_slack_user_id="U123",
        transcript=(
            TranscriptMessage(
                direction="inbound",
                text="¿A qué cliente le corresponde este pago?",
                event_at=datetime.now(UTC),
                sender_slack_user_id="U123",
            ),
        ),
    )

    result = await runner.run(request)

    assert runner.calls == [request]
    assert result.identification.confidence is Confidence.UNKNOWN
    assert result.identification.recommended_customer is None
    assert runner.supports_image_input is False


def test_legacy_result_without_outcome_remains_readable() -> None:
    result = PaymentIdentification.model_validate(
        {
            "recommended_customer": CustomerCandidate(
                customer_name="Cliente",
                order_id="order-1",
                crm_url="https://example.test/order-1",
                reason="Evidencia anterior.",
            ).model_dump(),
            "account_receivable_summary": "Saldo anterior",
            "confidence": "high",
            "investigation_summary": "Resultado persistido antes de Slice 5.",
        }
    )

    assert result.outcome is IdentificationOutcome.MATCHED
