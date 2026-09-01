from datetime import UTC, datetime
from uuid import uuid4

from cerebro.agent.models import Confidence
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
