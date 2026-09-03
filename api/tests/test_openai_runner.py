import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from agents import RunConfig
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError, ModelRefusalError
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI
from PIL import Image

from cerebro.agent.data_tools import (
    EmptyInvestigationData,
    InvestigationCandidate,
    PaymentCandidateQuery,
    ToolObservation,
    VerifyCandidateQuery,
)
from cerebro.agent.models import (
    CompletionReason,
    Confidence,
    EvidenceKind,
    EvidencePolarity,
    EvidenceSignal,
    EvidenceSource,
    EvidenceStrength,
    IdentificationOutcome,
)
from cerebro.agent.openai_runner import (
    ModelCandidate,
    ModelIdentification,
    OpenAIAgentsRunner,
    RunState,
    ToolBudgetExceeded,
    build_agent_runner,
    build_input_items,
    normalize_azure_base_url,
)
from cerebro.agent.runner import (
    AgentRunFailure,
    AgentRunInput,
    FakeAgentRunner,
    TranscriptAttachment,
    TranscriptMessage,
)
from cerebro.config import AppConfig

ORDER_UUID = UUID("50000000-0000-0000-0000-000000000001")
RECEIVABLE_UUID = UUID("a0000000-0000-0000-0000-000000000001")
ORDER_ID = str(ORDER_UUID)
RECEIVABLE_ID = str(RECEIVABLE_UUID)


def make_input(messages: tuple[TranscriptMessage, ...]) -> AgentRunInput:
    return AgentRunInput(
        run_id=uuid4(),
        slack_channel_id="C1",
        slack_thread_ts="1.1",
        requester_slack_user_id="U1",
        transcript=messages,
        trigger_slack_message_ts="trigger",
    )


def test_azure_url_and_automatic_backend_selection() -> None:
    assert normalize_azure_base_url("https://example.openai.azure.com") == (
        "https://example.openai.azure.com/openai/v1/"
    )
    assert isinstance(build_agent_runner(AppConfig()), FakeAgentRunner)
    with pytest.raises(ValueError, match="must be set together"):
        build_agent_runner(AppConfig(azure_openai_endpoint="https://example.test"))


def test_tool_amount_schema_is_azure_compatible_and_runtime_value_is_decimal() -> None:
    candidate_schema = PaymentCandidateQuery.model_json_schema()
    verification_schema = VerifyCandidateQuery.model_json_schema()

    assert candidate_schema["properties"]["amount"] == {
        "anyOf": [{"type": "number"}, {"type": "null"}],
        "default": None,
        "title": "Amount",
    }
    assert verification_schema["properties"]["amount"] == {
        "anyOf": [{"type": "number"}, {"type": "null"}],
        "default": None,
        "title": "Amount",
    }
    assert PaymentCandidateQuery.model_validate({"amount": 700000}).amount == Decimal("700000")
    with pytest.raises(ValueError):
        VerifyCandidateQuery.model_validate({"order_id": str(ORDER_UUID), "amount": 0})


async def test_responses_default_and_chat_fallback_use_exact_deployment() -> None:
    responses = OpenAIAgentsRunner(
        AppConfig(
            azure_openai_endpoint="https://example.test",
            azure_openai_api_key="test",
            azure_deployment_main="gpt-5-6-luna",
        )
    )
    chat = OpenAIAgentsRunner(
        AppConfig(
            azure_openai_endpoint="https://example.test",
            azure_openai_api_key="test",
            azure_deployment_main="gpt-5-6-luna",
            azure_openai_use_responses=False,
        )
    )
    try:
        responses_model = responses._model()
        chat_model = chat._model()
        assert isinstance(responses_model, OpenAIResponsesModel)
        assert isinstance(chat_model, OpenAIChatCompletionsModel)
        assert responses_model.model == "gpt-5-6-luna"
        assert chat_model.model == "gpt-5-6-luna"
    finally:
        await responses.close()
        await chat.close()


def test_transcript_is_structured_truncated_and_attachment_safe() -> None:
    messages = tuple(
        TranscriptMessage(
            direction="outbound" if index == 30 else "inbound",
            text=f"message-{index}",
            event_at=datetime.now(UTC),
            sender_slack_user_id="U1",
            slack_message_ts=f"message-{index}",
            attachments=(TranscriptAttachment("F1", "secret.png", "image/png", 42),)
            if index == 30
            else (),
        )
        for index in range(31)
    )
    items = build_input_items(make_input(messages))
    assert len(items) == 30
    assert items[0]["content"] == "message-1"
    assert items[-1]["role"] == "assistant"
    assert "captura(s) histórica(s)" in items[-1]["content"]
    assert "secret.png" not in items[-1]["content"]
    assert "F1" not in items[-1]["content"]


def test_only_triggering_message_receives_high_detail_data_url(tmp_path: Path) -> None:
    screenshot = tmp_path / "payment.png"
    Image.new("RGB", (10, 10), "white").save(screenshot, format="PNG")
    messages = (
        TranscriptMessage(
            direction="inbound",
            text="captura anterior",
            event_at=datetime.now(UTC),
            sender_slack_user_id="U1",
            slack_message_ts="previous",
            attachments=(TranscriptAttachment("F0", None, "image/png", 20),),
        ),
        TranscriptMessage(
            direction="inbound",
            text="identifica este pago",
            event_at=datetime.now(UTC),
            sender_slack_user_id="U1",
            slack_message_ts="trigger",
            attachments=(TranscriptAttachment("F1", None, "image/png", 20),),
        ),
    )
    run_input = make_input(messages)
    run_input = replace(run_input, image_paths=(screenshot,))

    items = build_input_items(run_input)

    assert isinstance(items[0]["content"], str)
    assert "histórica" in items[0]["content"]
    content = items[1]["content"]
    assert isinstance(content, list)
    assert content[0] == {
        "type": "input_text",
        "text": (
            "identifica este pago\n"
            "[El mensaje actual incluye 1 captura(s); usa solamente las imágenes "
            "adjuntas a este turno.]"
        ),
    }
    assert content[1]["type"] == "input_image"
    assert content[1]["detail"] == "high"
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert str(screenshot) not in repr(items)


async def test_empty_backend_is_explicitly_unavailable() -> None:
    result = await EmptyInvestigationData().search_payment_candidates(
        PaymentCandidateQuery(transferor_name="María")
    )
    assert result.available is False
    assert result.candidates == []


async def test_tool_budget_and_candidate_ledger() -> None:
    state = RunState(max_tool_calls=1)

    async def lookup(request: PaymentCandidateQuery) -> ToolObservation:
        del request
        return ToolObservation(
            source="fixture",
            available=True,
            summary="match",
            candidates=[
                InvestigationCandidate(
                    customer_name="María",
                    order_id=ORDER_UUID,
                    evidence=[
                        EvidenceSignal(
                            kind=EvidenceKind.CUSTOMER_NAME,
                            source=EvidenceSource.PAYMENT_CANDIDATES,
                            polarity=EvidencePolarity.SUPPORTING,
                            strength=EvidenceStrength.MEDIUM,
                            description="El nombre coincide.",
                            order_id=ORDER_ID,
                        )
                    ],
                )
            ],
        )

    raw = await state.invoke(
        "search_payment_candidates", PaymentCandidateQuery(transferor_name="María"), lookup
    )
    assert state.candidate_order_ids == {ORDER_ID}
    assert list(state.evidence) == ["ev_001"]
    assert json.loads(raw)["candidates"][0]["evidence"][0]["evidence_id"] == "ev_001"
    assert state.calls[0].output == {
        "source": "fixture",
        "available": True,
        "candidate_count": 1,
        "row_count": None,
        "truncated": None,
        "limitation_count": 0,
        "evidence_kinds": {"customer_name": 1},
    }
    with pytest.raises(ToolBudgetExceeded):
        await state.invoke(
            "search_payment_candidates", PaymentCandidateQuery(transferor_name="otra"), lookup
        )


async def test_model_candidates_require_tool_support_and_url_is_application_owned() -> None:
    config = AppConfig(
        azure_openai_endpoint="https://example.test",
        azure_openai_api_key="test",
    )
    client = AsyncOpenAI(api_key="test", base_url="https://example.test/v1/")
    runner = OpenAIAgentsRunner(config, client=client)
    signal = EvidenceSignal(
        evidence_id="ev_001",
        kind=EvidenceKind.EXACT_ADDRESS,
        source=EvidenceSource.CANDIDATE_VERIFICATION,
        polarity=EvidencePolarity.SUPPORTING,
        strength=EvidenceStrength.STRONG,
        description="La glosa coincide con la dirección completa de instalación.",
        order_id=ORDER_ID,
        account_receivable_id=RECEIVABLE_ID,
    )
    output = ModelIdentification(
        outcome=IdentificationOutcome.MATCHED,
        recommended_customer=ModelCandidate(
            order_id=ORDER_ID,
            account_receivable_id=RECEIVABLE_ID,
            evidence_ids=[signal.evidence_id],
        ),
    )
    try:
        unsupported = runner._map_output(output, RunState(max_tool_calls=1))
        supported_state = RunState(max_tool_calls=1, candidate_order_ids={ORDER_ID})
        verified = InvestigationCandidate(
            customer_name="María Solar",
            order_id=ORDER_UUID,
            account_receivable_id=RECEIVABLE_UUID,
            account_receivable_summary="cash; saldo pendiente 700000 CLP",
            outstanding_amount=Decimal("700000"),
            currency="CLP",
            evidence=[signal],
            verified=True,
        )
        supported_state.candidates[(ORDER_ID, RECEIVABLE_ID)] = verified
        supported_state.verified_candidates[(ORDER_ID, RECEIVABLE_ID)] = verified
        supported_state.evidence[signal.evidence_id] = signal
        supported = runner._map_output(output, supported_state)
    finally:
        await runner.close()
    assert unsupported.confidence is Confidence.UNKNOWN
    assert unsupported.outcome is IdentificationOutcome.AMBIGUOUS
    assert supported.outcome is IdentificationOutcome.MATCHED
    assert supported.recommended_customer is not None
    assert supported.recommended_customer.customer_name == "María Solar"
    assert supported.recommended_customer.crm_url.endswith(f"/{ORDER_ID}")
    assert supported.account_receivable_summary == "cash; saldo pendiente 700000 CLP"


@pytest.mark.parametrize(
    ("kinds", "expected_outcome", "expected_confidence"),
    [
        (
            [EvidenceKind.CUSTOMER_NAME],
            IdentificationOutcome.MATCHED,
            Confidence.MEDIUM,
        ),
        (
            [EvidenceKind.EXACT_OUTSTANDING],
            IdentificationOutcome.AMBIGUOUS,
            Confidence.UNKNOWN,
        ),
        (
            [EvidenceKind.CUSTOMER_NAME, EvidenceKind.CURRENCY_MISMATCH],
            IdentificationOutcome.AMBIGUOUS,
            Confidence.UNKNOWN,
        ),
    ],
)
async def test_application_owns_confidence_and_abstention(
    kinds: list[EvidenceKind],
    expected_outcome: IdentificationOutcome,
    expected_confidence: Confidence,
) -> None:
    signals = [
        EvidenceSignal(
            evidence_id=f"ev_{index:03d}",
            kind=kind,
            source=EvidenceSource.CANDIDATE_VERIFICATION,
            polarity=(
                EvidencePolarity.CONTRADICTING
                if kind is EvidenceKind.CURRENCY_MISMATCH
                else EvidencePolarity.SUPPORTING
            ),
            strength=(
                EvidenceStrength.STRONG
                if kind is EvidenceKind.CURRENCY_MISMATCH
                else EvidenceStrength.MEDIUM
            ),
            description=f"Evidencia canónica {kind.value}.",
            order_id=ORDER_ID,
            account_receivable_id=RECEIVABLE_ID,
        )
        for index, kind in enumerate(kinds, start=1)
    ]
    candidate = InvestigationCandidate(
        customer_name="María Solar",
        order_id=ORDER_UUID,
        account_receivable_id=RECEIVABLE_UUID,
        account_receivable_summary="saldo pendiente 700000 CLP",
        evidence=signals,
        verified=True,
    )
    state = RunState(max_tool_calls=1)
    state.candidates[(ORDER_ID, RECEIVABLE_ID)] = candidate
    state.verified_candidates[(ORDER_ID, RECEIVABLE_ID)] = candidate
    state.evidence = {signal.evidence_id: signal for signal in signals}
    output = ModelIdentification(
        outcome=IdentificationOutcome.MATCHED,
        recommended_customer=ModelCandidate(
            order_id=ORDER_ID,
            account_receivable_id=RECEIVABLE_ID,
            evidence_ids=[signal.evidence_id for signal in signals],
        ),
    )
    runner = OpenAIAgentsRunner(
        AppConfig(azure_openai_endpoint="https://example.test", azure_openai_api_key="test"),
        client=AsyncOpenAI(api_key="test", base_url="https://example.test/v1/"),
    )
    try:
        result = runner._map_output(output, state)
    finally:
        await runner.close()

    assert result.outcome is expected_outcome
    assert result.confidence is expected_confidence


async def test_no_customer_requires_a_conclusive_available_search() -> None:
    runner = OpenAIAgentsRunner(
        AppConfig(azure_openai_endpoint="https://example.test", azure_openai_api_key="test"),
        client=AsyncOpenAI(api_key="test", base_url="https://example.test/v1/"),
    )
    output = ModelIdentification(outcome=IdentificationOutcome.NO_CUSTOMER_FOUND)
    amount_only = RunState(
        max_tool_calls=1,
        candidate_search_succeeded=True,
        candidate_search_count=0,
        candidate_search_conclusive=False,
    )
    identity_search = RunState(
        max_tool_calls=1,
        candidate_search_succeeded=True,
        candidate_search_count=0,
        candidate_search_conclusive=True,
    )
    try:
        ambiguous = runner._map_output(output, amount_only)
        no_customer = runner._map_output(output, identity_search)
    finally:
        await runner.close()

    assert ambiguous.outcome is IdentificationOutcome.AMBIGUOUS
    assert no_customer.outcome is IdentificationOutcome.NO_CUSTOMER_FOUND


async def test_no_customer_cannot_hide_a_candidate_from_an_earlier_search() -> None:
    state = RunState(max_tool_calls=2)

    async def search_with_candidate(request: PaymentCandidateQuery) -> ToolObservation:
        del request
        return ToolObservation(
            source="payment_candidates",
            available=True,
            summary="candidate",
            candidates=[
                InvestigationCandidate(
                    customer_name="Cliente",
                    order_id=ORDER_UUID,
                    account_receivable_id=RECEIVABLE_UUID,
                )
            ],
        )

    async def empty_search(request: PaymentCandidateQuery) -> ToolObservation:
        del request
        return ToolObservation(source="payment_candidates", available=True, summary="empty")

    await state.invoke(
        "search_payment_candidates",
        PaymentCandidateQuery(transferor_name="Cliente"),
        search_with_candidate,
    )
    await state.invoke(
        "search_payment_candidates",
        PaymentCandidateQuery(glosa_or_address="otra señal"),
        empty_search,
    )

    assert state.candidate_search_count == 1
    assert state.candidate_search_conclusive is True


async def test_only_verified_competitors_can_force_ambiguity() -> None:
    runner = OpenAIAgentsRunner(
        AppConfig(azure_openai_endpoint="https://example.test", azure_openai_api_key="test"),
        client=AsyncOpenAI(api_key="test", base_url="https://example.test/v1/"),
    )
    chosen_signal = EvidenceSignal(
        evidence_id="ev_001",
        kind=EvidenceKind.CUSTOMER_NAME,
        source=EvidenceSource.CANDIDATE_VERIFICATION,
        polarity=EvidencePolarity.SUPPORTING,
        strength=EvidenceStrength.MEDIUM,
        description="El nombre coincide.",
        order_id=ORDER_ID,
        account_receivable_id=RECEIVABLE_ID,
    )
    other_order = UUID("50000000-0000-0000-0000-000000000002")
    other_receivable = UUID("a0000000-0000-0000-0000-000000000002")
    other_signal = chosen_signal.model_copy(
        update={
            "evidence_id": "ev_002",
            "order_id": str(other_order),
            "account_receivable_id": str(other_receivable),
        }
    )
    chosen = InvestigationCandidate(
        customer_name="Cliente elegido",
        order_id=ORDER_UUID,
        account_receivable_id=RECEIVABLE_UUID,
        evidence=[chosen_signal],
        verified=True,
    )
    unverified = InvestigationCandidate(
        customer_name="Candidato sin verificar",
        order_id=other_order,
        account_receivable_id=other_receivable,
        evidence=[other_signal],
        verified=False,
    )
    state = RunState(max_tool_calls=1)
    state.candidates[(ORDER_ID, RECEIVABLE_ID)] = chosen
    state.candidates[(str(other_order), str(other_receivable))] = unverified
    state.verified_candidates[(ORDER_ID, RECEIVABLE_ID)] = chosen
    state.evidence = {"ev_001": chosen_signal, "ev_002": other_signal}
    output = ModelIdentification(
        outcome=IdentificationOutcome.MATCHED,
        recommended_customer=ModelCandidate(
            order_id=ORDER_ID,
            account_receivable_id=RECEIVABLE_ID,
            evidence_ids=["ev_001"],
        ),
    )
    try:
        result = runner._map_output(output, state)
    finally:
        await runner.close()

    assert result.outcome is IdentificationOutcome.MATCHED


def test_evidence_deduplication_keeps_equal_signals_for_distinct_candidates() -> None:
    first = EvidenceSignal(
        evidence_id="ev_001",
        kind=EvidenceKind.CUSTOMER_NAME,
        source=EvidenceSource.PAYMENT_CANDIDATES,
        polarity=EvidencePolarity.SUPPORTING,
        strength=EvidenceStrength.MEDIUM,
        description="El nombre coincide.",
        order_id=ORDER_ID,
        account_receivable_id=RECEIVABLE_ID,
    )
    second = first.model_copy(
        update={
            "evidence_id": "ev_002",
            "order_id": "50000000-0000-0000-0000-000000000002",
            "account_receivable_id": "a0000000-0000-0000-0000-000000000002",
        }
    )
    repeated_after_verification = first.model_copy(update={"evidence_id": "ev_003"})

    assert OpenAIAgentsRunner._deduplicate_signals(
        [first, second, repeated_after_verification]
    ) == [first, second, repeated_after_verification]


async def test_only_verification_tool_authorizes_a_recommendation() -> None:
    state = RunState(max_tool_calls=2)

    async def verify(request: VerifyCandidateQuery) -> ToolObservation:
        return ToolObservation(
            source="candidate_verification",
            available=True,
            summary="verified",
            candidates=[
                InvestigationCandidate(
                    customer_name="María Solar",
                    order_id=request.order_id,
                    account_receivable_id=RECEIVABLE_UUID,
                    account_receivable_summary="saldo pendiente 700000 CLP",
                    verified=True,
                )
            ],
        )

    await state.invoke(
        "verify_payment_candidate",
        VerifyCandidateQuery(order_id=ORDER_UUID, amount=Decimal("700000")),
        verify,
    )
    assert (ORDER_ID, RECEIVABLE_ID) in state.verified_candidates


async def test_failed_tool_becomes_unavailable_observation_and_safe_audit() -> None:
    state = RunState(max_tool_calls=1)

    async def fail(request: PaymentCandidateQuery) -> ToolObservation:
        del request
        raise ValueError("customer@example.test must not enter the audit row")

    raw_observation = await state.invoke(
        "search_payment_candidates",
        PaymentCandidateQuery(email="customer@example.test"),
        fail,
    )

    observation = json.loads(raw_observation)
    assert observation["available"] is False
    assert "customer@example.test" not in raw_observation
    assert state.calls[0].input == {"has_email": True}
    assert state.calls[0].error == "ValueError"


@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (TimeoutError(), CompletionReason.TIMEOUT),
        (MaxTurnsExceeded("limit"), CompletionReason.TURN_LIMIT),
        (ToolBudgetExceeded("limit"), CompletionReason.TOOL_LIMIT),
        (ModelRefusalError("refused"), CompletionReason.REFUSAL),
        (ModelBehaviorError("bad"), CompletionReason.INVALID_OUTPUT),
    ],
)
async def test_safe_sdk_outcomes_return_unknown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exception: Exception,
    reason: CompletionReason,
) -> None:
    async def fail(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise exception

    monkeypatch.setattr("cerebro.agent.openai_runner.Runner.run", fail)
    (tmp_path / "payment-identification-policy.md").write_text("No adivines.", encoding="utf-8")
    (tmp_path / "data-scope.yaml").write_text("version: 1\n", encoding="utf-8")
    config = AppConfig(
        azure_openai_endpoint="https://example.test",
        azure_openai_api_key="test",
        knowledge_dir=str(tmp_path),
    )
    runner = OpenAIAgentsRunner(
        config,
        client=AsyncOpenAI(api_key="test", base_url="https://example.test/v1/"),
    )
    try:
        result = await runner.run(
            make_input(
                (
                    TranscriptMessage(
                        direction="inbound",
                        text="pago",
                        event_at=datetime.now(UTC),
                        sender_slack_user_id="U1",
                    ),
                )
            )
        )
    finally:
        await runner.close()
    assert result.identification.confidence is Confidence.UNKNOWN
    assert result.completion_reason is reason
    assert result.prompt_version == "payment-identification-slice5-v1"


async def test_success_records_usage_and_disables_sensitive_tracing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class FakeSdkResult:
        def __init__(self) -> None:
            self.context_wrapper = SimpleNamespace(
                usage=SimpleNamespace(input_tokens=120, output_tokens=30, requests=2)
            )
            self.raw_responses = [object(), object()]

        @staticmethod
        def final_output_as(output_type: type[ModelIdentification], **kwargs: object) -> object:
            del output_type, kwargs
            return ModelIdentification(
                outcome=IdentificationOutcome.AMBIGUOUS,
            )

    async def succeed(*args: object, **kwargs: object) -> object:
        captured["agent"] = args[0]
        captured.update(kwargs)
        return FakeSdkResult()

    monkeypatch.setattr("cerebro.agent.openai_runner.Runner.run", succeed)
    (tmp_path / "payment-identification-policy.md").write_text("No adivines.", encoding="utf-8")
    (tmp_path / "data-scope.yaml").write_text("version: 1\n", encoding="utf-8")
    config = AppConfig(
        azure_openai_endpoint="https://example.test",
        azure_openai_api_key="test",
        knowledge_dir=str(tmp_path),
    )
    runner = OpenAIAgentsRunner(
        config,
        client=AsyncOpenAI(api_key="test", base_url="https://example.test/v1/"),
    )
    try:
        result = await runner.run(
            make_input(
                (
                    TranscriptMessage(
                        direction="inbound",
                        text="pago",
                        event_at=datetime.now(UTC),
                        sender_slack_user_id="U1",
                    ),
                )
            )
        )
    finally:
        await runner.close()

    run_config = cast(RunConfig, captured["run_config"])
    assert run_config.tracing_disabled is True
    assert run_config.trace_include_sensitive_data is False
    assert captured["max_turns"] == 8
    assert result.usage.model == "gpt-5-6-luna"
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 30
    assert result.usage.turns == 2
    assert result.completion_reason is CompletionReason.COMPLETED


async def test_provider_failures_propagate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fail(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("cerebro.agent.openai_runner.Runner.run", fail)
    (tmp_path / "payment-identification-policy.md").write_text("No adivines.", encoding="utf-8")
    (tmp_path / "data-scope.yaml").write_text("version: 1\n", encoding="utf-8")
    runner = OpenAIAgentsRunner(
        AppConfig(
            azure_openai_endpoint="https://example.test",
            azure_openai_api_key="test",
            knowledge_dir=str(tmp_path),
        ),
        client=AsyncOpenAI(api_key="test", base_url="https://example.test/v1/"),
    )
    try:
        with pytest.raises(
            AgentRunFailure, match="agent provider/runtime failure: RuntimeError"
        ) as failure:
            await runner.run(make_input(()))
        assert isinstance(failure.value.__cause__, RuntimeError)
        assert str(failure.value.__cause__) == "provider unavailable"
    finally:
        await runner.close()
