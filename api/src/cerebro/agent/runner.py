"""AgentRunner port and process-local runner lifecycle."""

import inspect
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from cerebro.agent.models import (
    AgentStep,
    AgentUsage,
    CompletionReason,
    Confidence,
    PaymentIdentification,
    ToolAuditRecord,
)


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
    steps: tuple[AgentStep, ...] = ()
    usage: AgentUsage = field(default_factory=AgentUsage)
    prompt_version: str | None = None
    knowledge_version: str | None = None
    completion_reason: CompletionReason = CompletionReason.COMPLETED
    tool_calls: tuple[ToolAuditRecord, ...] = ()


class AgentRunFailure(RuntimeError):
    """Fatal runner failure carrying the safe audit accumulated before it failed."""

    def __init__(
        self,
        message: str,
        *,
        tool_calls: tuple[ToolAuditRecord, ...] = (),
        prompt_version: str | None = None,
        knowledge_version: str | None = None,
    ) -> None:
        super().__init__(message)
        self.tool_calls = tool_calls
        self.prompt_version = prompt_version
        self.knowledge_version = knowledge_version


class AgentRunner(Protocol):
    async def start(self) -> None: ...

    async def run(self, run_input: AgentRunInput) -> AgentRunResult: ...

    async def close(self) -> None: ...


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

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


_runner: AgentRunner | None = None


def get_agent_runner() -> AgentRunner:
    global _runner
    if _runner is None:
        from cerebro.agent.openai_runner import build_agent_runner

        _runner = build_agent_runner()
    return _runner


def set_agent_runner(runner: AgentRunner | None) -> None:
    global _runner
    _runner = runner


async def close_agent_runner() -> None:
    global _runner
    runner = _runner
    _runner = None
    if runner is None:
        return
    close = getattr(runner, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def start_agent_runner() -> AgentRunner:
    runner = get_agent_runner()
    start = getattr(runner, "start", None)
    if start is not None:
        result = start()
        if inspect.isawaitable(result):
            await result
    return runner
