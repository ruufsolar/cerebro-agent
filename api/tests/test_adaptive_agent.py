import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from agents import ModelSettings
from agents.items import ModelResponse, TResponseStreamEvent
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from cerebro.agent import shared_memory
from cerebro.agent.data_tools import (
    EmptyInvestigationData,
    KnowledgeQuery,
    MemoryRecallQuery,
    PaymentCandidateQuery,
    ToolObservation,
)
from cerebro.agent.models import (
    AgentStep,
    AgentUsage,
    CompletionReason,
    Confidence,
    GeneralAnswer,
    IdentificationOutcome,
    PaymentIdentification,
    RequestKind,
)
from cerebro.agent.openai_runner import ModelRoute, OpenAIAgentsRunner, RouteCertainty, RunState
from cerebro.agent.runner import (
    AgentRunInput,
    AgentRunResult,
    GeneralAgentRunResult,
    TranscriptMessage,
)
from cerebro.agent.turns import SpecialistTurns, TurnLimitedModel
from cerebro.config import AppConfig
from cerebro.slack.rendering import render_identification

KNOWLEDGE = str(Path(__file__).parents[2] / "knowledge")


class ScriptedModel(Model):
    def __init__(self, *, correction_at: int | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.correction_at = correction_at

    async def get_response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.calls.append(kwargs)
        turn = len(self.calls)
        if turn == self.correction_at:
            output = {
                "answer": "Cambio al flujo de pagos.",
                "route_correction": "payment_identification",
            }
        elif kwargs["tools"]:
            return ModelResponse(
                output=[
                    ResponseFunctionToolCall(
                        type="function_call",
                        call_id=f"call_{turn}",
                        name="read_finops_knowledge",
                        arguments='{"request":{"topic":"limitations"}}',
                    )
                ],
                usage=Usage(requests=1, input_tokens=10, output_tokens=4),
                response_id=None,
            )
        else:
            output = (
                {"outcome": "ambiguous", "clarification_question": "¿Cuál es la fecha del pago?"}
                if self.correction_at
                else {"answer": "Terminé mi revisión."}
            )
        return ModelResponse(
            output=[
                ResponseOutputMessage(
                    id=f"msg_{turn}",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[
                        ResponseOutputText(
                            type="output_text", text=json.dumps(output), annotations=[]
                        )
                    ],
                )
            ],
            usage=Usage(requests=1, input_tokens=10, output_tokens=4),
            response_id=None,
        )

    def stream_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[TResponseStreamEvent]:
        raise NotImplementedError


def run_input(text: str = "Consulta de FinOps") -> AgentRunInput:
    return AgentRunInput(
        run_id=uuid4(),
        slack_channel_id="C_TEST",
        slack_thread_ts="1.1",
        requester_slack_user_id="U_TEST",
        trigger_slack_message_ts="1.1",
        transcript=(TranscriptMessage("inbound", text, datetime.now(UTC), "U_TEST", "1.1"),),
    )


@pytest.mark.parametrize("correction_at", [None, 8, 13])
async def test_real_sdk_shares_fourteen_turns_and_reserves_final_answer(
    monkeypatch: pytest.MonkeyPatch,
    correction_at: int | None,
) -> None:
    model = ScriptedModel(correction_at=correction_at)
    # Advance virtual elapsed time between provider calls, not during one call. This would
    # trip the retired 180-second whole-investigation timeout, without a slow wall-clock test.
    loop = asyncio.get_running_loop()
    original_time = loop.time
    elapsed = 0.0
    monkeypatch.setattr(loop, "time", lambda: original_time() + elapsed)

    class SlowInvestigationData(EmptyInvestigationData):
        async def read_finops_knowledge(self, request: KnowledgeQuery) -> ToolObservation:
            nonlocal elapsed
            elapsed += 31
            await asyncio.sleep(0)
            return await super().read_finops_knowledge(request)

    runner = OpenAIAgentsRunner(
        AppConfig(
            azure_openai_api_key="synthetic",
            azure_openai_endpoint="https://example.invalid",
            knowledge_dir=KNOWLEDGE,
        ),
        data=SlowInvestigationData(),
        shared_memory_enabled=False,
    )

    async def route(items: object) -> tuple[ModelRoute, AgentUsage, AgentStep]:
        return (
            ModelRoute(request_kind=RequestKind.GENERAL, certainty=RouteCertainty.CERTAIN),
            AgentUsage(turns=1, input_tokens=5, output_tokens=2),
            AgentStep(type="request_classified", name="general"),
        )

    monkeypatch.setattr(runner, "_route", route)
    monkeypatch.setattr(runner, "_model", lambda: model)
    try:
        result = await runner.run(run_input())
    finally:
        await runner.close()
    assert len(model.calls) == 14
    assert elapsed > 180
    assert model.calls[-1]["tools"] == []
    assert model.calls[-1]["model_settings"].tool_choice == "none"
    assert all(call["model_settings"].max_tokens is None for call in model.calls)
    assert all(call["model_settings"].timeout == 180 for call in model.calls)
    assert result.usage.turns == 15  # one router + fourteen specialist calls
    assert result.usage.input_tokens == 145
    assert result.usage.output_tokens == 58
    assert isinstance(result, AgentRunResult if correction_at else GeneralAgentRunResult)
    assert len([step for step in result.steps if step.type == "route_correction"]) == bool(
        correction_at
    )


async def test_final_turn_cannot_execute_even_a_misbehaving_models_tool_call() -> None:
    from agents.exceptions import MaxTurnsExceeded

    model = ScriptedModel()
    budget = SpecialistTurns(2, used=2)
    wrapper = TurnLimitedModel(model, budget)
    with pytest.raises(MaxTurnsExceeded):
        await wrapper.get_response(model_settings=ModelSettings(), tools=[])
    assert model.calls == []


def test_removed_caps_and_legacy_question_default() -> None:
    config = AppConfig()
    assert config.max_agent_turns == 14
    assert config.provider_request_timeout_seconds == 180
    assert not {"max_tool_calls", "agent_timeout_seconds", "azure_max_output_tokens"} & set(
        AppConfig.model_fields
    )
    result = PaymentIdentification(
        confidence=Confidence.UNKNOWN, investigation_summary="Sin certeza."
    )
    assert result.clarification_question is None
    result.clarification_question = "¿Cuál es la fecha de la transferencia?"
    rendered = render_identification(AgentRunResult(identification=result))
    assert result.clarification_question in rendered
    assert len(rendered.splitlines()) <= 4
    assert len(rendered.split()) <= 75


async def test_truncated_search_cannot_establish_no_customer() -> None:
    state = RunState()

    async def search(request: object) -> ToolObservation:
        value = ToolObservation(source="payment_candidates", available=True, summary="Truncado")
        value.audit.truncated = True
        return value

    await state.invoke(
        "search_payment_candidates", PaymentCandidateQuery(transferor_name="Ana Prado"), search
    )
    assert not state.candidate_search_conclusive


async def test_targeted_memory_recall_is_guidance_with_safe_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cerebro.memory_client import Memory

    class MemoryStub:
        async def recall(self, query: str, *, limit: int) -> list[Memory]:
            assert query == "joins de terceros" and limit == 5
            return [
                Memory(
                    "m1",
                    "Busca ops.payer_reference; confirma el esquema.",
                    "short",
                    "procedure",
                    None,
                    None,
                    None,
                )
            ]

    async def load() -> shared_memory.MemoryContext:
        return shared_memory.MemoryContext("brief", "shared-memory-42")

    monkeypatch.setattr(shared_memory, "client", lambda: MemoryStub())
    monkeypatch.setattr(shared_memory, "load", load)
    state = RunState()
    raw = await state.invoke(
        "recall_shared_memory", MemoryRecallQuery(query="joins de terceros"), shared_memory.recall
    )
    assert "ops.payer_reference" in raw
    assert not state.evidence and not state.verified_candidates
    assert "ops.payer_reference" not in str(state.calls)
    assert isinstance(state.calls[0].output, dict)
    assert state.calls[0].output["memory_ids"] == ["m1"]


async def test_payment_loads_existing_memory_but_gets_no_memory_write_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    captured: list[Any] = []

    async def load() -> shared_memory.MemoryContext:
        return shared_memory.MemoryContext(
            "Try the declared payer relationship.", "shared-memory-9"
        )

    async def run(agent: Any, *args: Any, **kwargs: Any) -> Any:
        captured.append(agent)
        from cerebro.agent.openai_runner import ModelIdentification

        output = (
            ModelRoute(
                request_kind=RequestKind.PAYMENT_IDENTIFICATION, certainty=RouteCertainty.CERTAIN
            )
            if len(captured) == 1
            else ModelIdentification(outcome=IdentificationOutcome.AMBIGUOUS)
        )
        return SimpleNamespace(
            final_output_as=lambda *a, **k: output,
            raw_responses=[],
            context_wrapper=SimpleNamespace(
                usage=Usage(requests=1, input_tokens=1, output_tokens=1)
            ),
        )

    monkeypatch.setattr(shared_memory, "load", load)
    monkeypatch.setattr("cerebro.agent.openai_runner.Runner.run", run)
    runner = OpenAIAgentsRunner(
        AppConfig(azure_openai_api_key="synthetic", knowledge_dir=KNOWLEDGE)
    )
    try:
        result = await runner.run(run_input("Identifica este pago"))
    finally:
        await runner.close()
    assert "Try the declared" in captured[1].instructions
    names = {tool.name for tool in captured[1].tools}
    assert "recall_shared_memory" in names and "remember_shared_memory" not in names
    assert result.knowledge_version is not None
    assert result.knowledge_version.endswith("+shared-memory-9")


async def test_route_clarification_does_not_investigate(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = OpenAIAgentsRunner(AppConfig(knowledge_dir=KNOWLEDGE, azure_openai_api_key="fake"))

    async def route(items: object) -> tuple[ModelRoute, AgentUsage, AgentStep]:
        return (
            ModelRoute(
                request_kind=RequestKind.GENERAL,
                certainty=RouteCertainty.UNCERTAIN,
                clarify=True,
                clarification_question="¿Qué necesitas investigar?",
            ),
            AgentUsage(turns=1),
            AgentStep(type="request_classified", name="clarification"),
        )

    async def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("a routing clarification must not investigate or read memory")

    monkeypatch.setattr(runner, "_route", route)
    monkeypatch.setattr(runner, "_run_payment", forbidden)
    monkeypatch.setattr(runner, "_run_general", forbidden)
    monkeypatch.setattr(shared_memory, "load", forbidden)
    try:
        result = await runner.run(run_input("¿Me ayudas?"))
    finally:
        await runner.close()
    assert isinstance(result, GeneralAgentRunResult)
    assert result.response.answer == "¿Qué necesitas investigar?"
    assert result.usage.turns == 1 and result.tool_calls == ()


async def test_unavailable_memory_does_not_manufacture_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shared_memory, "client", lambda: None)
    state = RunState()
    result = json.loads(
        await state.invoke(
            "recall_shared_memory",
            MemoryRecallQuery(query="tablas de identidad"),
            shared_memory.recall,
        )
    )
    assert not result["available"]
    assert not state.evidence and not state.candidate_order_ids


async def test_second_route_correction_never_starts_a_third_specialist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = OpenAIAgentsRunner(
        AppConfig(knowledge_dir=KNOWLEDGE, azure_openai_api_key="fake"),
        shared_memory_enabled=False,
    )
    calls: list[str] = []

    async def route(items: object) -> tuple[ModelRoute, AgentUsage, AgentStep]:
        return (
            ModelRoute(request_kind=RequestKind.GENERAL, certainty=RouteCertainty.CERTAIN),
            AgentUsage(turns=1),
            AgentStep(type="request_classified"),
        )

    async def general(items: object, state: RunState, instructions: str) -> GeneralAgentRunResult:
        calls.append("general")
        state.requested_route = RequestKind.PAYMENT_IDENTIFICATION
        return GeneralAgentRunResult(
            response=GeneralAnswer(answer="Cambio de flujo."), usage=AgentUsage(turns=1)
        )

    async def payment(items: object, state: RunState, instructions: str) -> AgentRunResult:
        calls.append("payment")
        state.requested_route = RequestKind.GENERAL
        return AgentRunResult(
            identification=PaymentIdentification(
                confidence=Confidence.UNKNOWN, investigation_summary="No sé."
            ),
            usage=AgentUsage(turns=1),
        )

    monkeypatch.setattr(runner, "_route", route)
    monkeypatch.setattr(runner, "_run_general", general)
    monkeypatch.setattr(runner, "_run_payment", payment)
    try:
        result = await runner.run(run_input())
    finally:
        await runner.close()
    assert calls == ["general", "payment"]
    assert result.completion_reason == CompletionReason.TURN_LIMIT
    assert result.usage.turns == 3
