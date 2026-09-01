"""AgentRunner port; the concrete Agents SDK implementation is a later vertical slice."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from cerebro.agent.models import AgentUsage, Confidence, PaymentIdentification


@dataclass(frozen=True)
class TranscriptAttachment:
    slack_file_id: str
    name: str | None
    mimetype: str
    size: int


@dataclass(frozen=True)
class TranscriptMessage:
    direction: str
    text: str | None
    event_at: datetime
    sender_slack_user_id: str | None
    attachments: tuple[TranscriptAttachment, ...] = ()


@dataclass(frozen=True)
class AgentRunInput:
    run_id: UUID
    slack_channel_id: str
    slack_thread_ts: str
    requester_slack_user_id: str
    transcript: tuple[TranscriptMessage, ...]
    image_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class AgentRunResult:
    identification: PaymentIdentification
    steps: list[dict[str, Any]] = field(default_factory=list)
    usage: AgentUsage = field(default_factory=AgentUsage)


class AgentRunner(Protocol):
    async def run(self, run_input: AgentRunInput) -> AgentRunResult: ...


class FakeAgentRunner:
    """Deterministic test double; it never reaches Slack, Azure, or Ruuf data."""

    def __init__(self, result: AgentRunResult | None = None) -> None:
        self.calls: list[AgentRunInput] = []
        self.result = result or AgentRunResult(
            identification=PaymentIdentification(
                confidence=Confidence.UNKNOWN,
                investigation_summary="No live investigation adapter is configured.",
                unable_to_verify=["customer", "account receivable"],
            )
        )

    async def run(self, run_input: AgentRunInput) -> AgentRunResult:
        self.calls.append(run_input)
        return self.result


_runner: AgentRunner = FakeAgentRunner()


def get_agent_runner() -> AgentRunner:
    return _runner


def set_agent_runner(runner: AgentRunner) -> None:
    global _runner
    _runner = runner
