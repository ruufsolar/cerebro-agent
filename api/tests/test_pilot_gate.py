from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cerebro.agent.models import (
    Confidence,
    CustomerCandidate,
    EvidenceKind,
    EvidencePolarity,
    EvidenceSignal,
    EvidenceSource,
    EvidenceStrength,
    IdentificationOutcome,
    PaymentIdentification,
)
from cerebro.db.enums import DeliveryStatus, RunStatus, SlackOutputKind
from cerebro.db.models import AgentRun, Feedback, Message, SlackOutput, ToolCall
from cerebro.ops.pilot_gate import PilotRow, grade_rows


def _case(index: int, *, image: bool = False) -> PilotRow:
    now = datetime.now(UTC) + timedelta(minutes=index)
    conversation_id = uuid4()
    run_id = uuid4()
    output_ts = f"{now.timestamp() + 30:.6f}"
    result = PaymentIdentification(
        outcome=IdentificationOutcome.NO_CUSTOMER_FOUND,
        confidence=Confidence.UNKNOWN,
        investigation_summary="La búsqueda válida no encontró candidatos elegibles.",
    )
    trigger = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        slack_channel_id="pilot",
        slack_message_ts=f"{now.timestamp():.6f}",
        slack_thread_ts=f"{now.timestamp():.6f}",
        sender_slack_user_id="user",
        direction="inbound",
        kind="text",
        text=None,
        event_at=now,
    )
    run = AgentRun(
        id=run_id,
        conversation_id=conversation_id,
        trigger_message_id=trigger.id,
        status=RunStatus.SUCCEEDED,
        structured_result=result.model_dump(mode="json"),
        output_message="🧪 *Piloto.*\n*Resultado:* no encontré un cliente.",
        prompt_version="payment-identification-slice5-v1",
        knowledge_version="payment-identification-knowledge-v3",
        completion_reason="completed",
        model="gpt-5-6-luna",
        input_tokens=10_000,
        output_tokens=200,
        steps=[{"type": "image_ingestion", "downloaded": 1 if image else 0}],
    )
    output = SlackOutput(
        id=uuid4(),
        conversation_id=conversation_id,
        agent_run_id=run_id,
        slack_channel_id="pilot",
        slack_thread_ts=trigger.slack_thread_ts,
        slack_message_ts=output_ts,
        idempotency_key=f"run:{run_id}",
        body=run.output_message,
        kind=SlackOutputKind.INVESTIGATION,
        status=DeliveryStatus.SENT,
        attempts=1,
        sent_at=now + timedelta(seconds=30),
    )
    feedback = Feedback(
        id=uuid4(),
        conversation_id=conversation_id,
        agent_run_id=run_id,
        slack_channel_id="pilot",
        slack_message_ts=output_ts,
        slack_user_id="reviewer",
        reaction="cheese_wedge",
        sentiment="positive",
        is_active=True,
    )
    return PilotRow(run, trigger, [output], [feedback], [])


def test_ten_case_pilot_passes_with_balanced_limits() -> None:
    report = grade_rows([_case(index, image=index < 4) for index in range(10)])

    assert report["passed"] is True
    assert report["score"] == "10/10"
    assert report["deployment"] == "gpt-5-6-luna"
    assert report["positive_cases"] == 10
    assert report["image_cases"] == 4
    assert report["latency"] == {"median_seconds": 30.0, "p95_seconds": 30.0}


def test_pilot_rejects_latency_and_feedback_conflict() -> None:
    rows = [_case(index, image=index < 4) for index in range(10)]
    rows[-1].outputs[0].sent_at = rows[-1].trigger.event_at + timedelta(seconds=121)
    rows[0].feedback.append(
        Feedback(
            id=uuid4(),
            conversation_id=rows[0].run.conversation_id,
            agent_run_id=rows[0].run.id,
            slack_channel_id="pilot",
            slack_message_ts=rows[0].outputs[0].slack_message_ts or "",
            slack_user_id="reviewer",
            reaction="electric_plug",
            sentiment="negative",
            is_active=True,
        )
    )

    report = grade_rows(rows)

    assert report["passed"] is False
    assert "p95_latency" in report["errors"]
    assert "feedback_conflict" in report["cases"][0]["errors"]


def test_pilot_rejects_customer_claim_without_successful_source_tool() -> None:
    rows = [_case(index, image=index < 4) for index in range(10)]
    evidence = EvidenceSignal(
        evidence_id="ev_001",
        kind=EvidenceKind.EXACT_ADDRESS,
        source=EvidenceSource.CANDIDATE_VERIFICATION,
        polarity=EvidencePolarity.SUPPORTING,
        strength=EvidenceStrength.STRONG,
        description="Dirección verificada.",
        order_id="order-synthetic",
    )
    matched = PaymentIdentification(
        outcome=IdentificationOutcome.MATCHED,
        recommended_customer=CustomerCandidate(
            customer_name="Cliente sintético",
            order_id="order-synthetic",
            crm_url="https://example.invalid/order-synthetic",
            reason="Dirección verificada.",
            evidence_ids=["ev_001"],
        ),
        account_receivable_summary="Saldo sintético.",
        confidence=Confidence.HIGH,
        investigation_summary="La dirección coincide.",
        evidence=[evidence],
    )
    rows[0].run.structured_result = matched.model_dump(mode="json")
    rows[0].run.output_message = "🧪 *Piloto.*\n*Resultado:* coincidencia — confianza alta."

    report = grade_rows(rows)

    assert report["passed"] is False
    assert "unsupported_evidence" in report["cases"][0]["errors"]


def test_pilot_accepts_grounded_customer_claim() -> None:
    row = _case(0, image=True)
    evidence = EvidenceSignal(
        evidence_id="ev_001",
        kind=EvidenceKind.EXACT_ADDRESS,
        source=EvidenceSource.CANDIDATE_VERIFICATION,
        polarity=EvidencePolarity.SUPPORTING,
        strength=EvidenceStrength.STRONG,
        description="Dirección verificada.",
        order_id="order-synthetic",
    )
    result = PaymentIdentification(
        outcome=IdentificationOutcome.MATCHED,
        recommended_customer=CustomerCandidate(
            customer_name="Cliente sintético",
            order_id="order-synthetic",
            crm_url="https://example.invalid/order-synthetic",
            reason="Dirección verificada.",
            evidence_ids=["ev_001"],
        ),
        account_receivable_summary="Saldo sintético.",
        confidence=Confidence.HIGH,
        investigation_summary="La dirección coincide.",
        evidence=[evidence],
    )
    row.run.structured_result = result.model_dump(mode="json")
    row.tools.append(
        ToolCall(
            id=uuid4(),
            agent_run_id=row.run.id,
            sequence=1,
            tool_name="verify_payment_candidate",
            status="succeeded",
        )
    )

    report = grade_rows([row, *[_case(index, image=index < 3) for index in range(1, 10)]])

    assert "unsupported_evidence" not in report["cases"][0]["errors"]


def test_pilot_rejects_missing_cases_images_labels_and_usage_limits() -> None:
    rows = [_case(index, image=index < 3) for index in range(9)]
    rows[0].feedback.clear()
    for row in rows:
        row.run.input_tokens = 50_001
        row.run.output_tokens = 1_001
    rows[1].run.input_tokens = 100_001
    rows[1].run.output_tokens = 2_001

    report = grade_rows(rows)

    assert report["passed"] is False
    assert {
        "case_count",
        "image_case_count",
        "positive_case_count",
        "latency_missing",
        "input_usage_missing",
        "output_usage_missing",
    } <= set(report["errors"])
    assert "feedback_missing" in report["cases"][0]["errors"]
    assert "input_token_max" in report["cases"][1]["errors"]
    assert "output_token_max" in report["cases"][1]["errors"]


def test_pilot_rejects_average_token_limits() -> None:
    rows = [_case(index, image=index < 4) for index in range(10)]
    for row in rows:
        row.run.input_tokens = 50_001
        row.run.output_tokens = 1_001

    report = grade_rows(rows)

    assert "average_input_tokens" in report["errors"]
    assert "average_output_tokens" in report["errors"]


def test_pilot_rejects_failed_timeout_delivery_and_duplicate_output() -> None:
    rows = [_case(index, image=index < 4) for index in range(10)]
    rows[0].run.status = RunStatus.FAILED
    rows[0].run.completion_reason = "timeout"
    rows[0].outputs[0].status = DeliveryStatus.FAILED
    rows[0].outputs.append(
        SlackOutput(
            id=uuid4(),
            conversation_id=rows[0].run.conversation_id,
            agent_run_id=rows[0].run.id,
            slack_channel_id="pilot",
            slack_thread_ts=rows[0].trigger.slack_thread_ts,
            slack_message_ts="duplicate",
            idempotency_key="duplicate",
            body=rows[0].run.output_message or "",
            kind=SlackOutputKind.INVESTIGATION,
            status=DeliveryStatus.SENT,
            sent_at=rows[0].trigger.event_at + timedelta(seconds=20),
        )
    )

    report = grade_rows(rows)

    assert {
        "investigation_output_count",
        "run_not_succeeded",
        "run_timeout",
    } <= set(report["cases"][0]["errors"])


def test_pilot_grades_the_delivered_body_and_rejects_mismatch_or_verbosity() -> None:
    rows = [_case(index, image=index < 4) for index in range(10)]
    rows[0].outputs[0].body = "palabra " * 140

    report = grade_rows(rows)

    assert "delivered_output_mismatch" in report["cases"][0]["errors"]
    assert "response_too_verbose" in report["cases"][0]["errors"]


def test_pilot_rejects_negative_high_confidence_match() -> None:
    rows = [_case(index, image=index < 4) for index in range(10)]
    evidence = EvidenceSignal(
        evidence_id="ev_001",
        kind=EvidenceKind.EXACT_ADDRESS,
        source=EvidenceSource.CANDIDATE_VERIFICATION,
        polarity=EvidencePolarity.SUPPORTING,
        strength=EvidenceStrength.STRONG,
        description="Dirección verificada.",
        order_id="order-synthetic",
    )
    rows[0].run.structured_result = PaymentIdentification(
        outcome=IdentificationOutcome.MATCHED,
        recommended_customer=CustomerCandidate(
            customer_name="Cliente sintético",
            order_id="order-synthetic",
            crm_url="https://example.invalid/order-synthetic",
            reason="Dirección verificada.",
            evidence_ids=["ev_001"],
        ),
        account_receivable_summary="Saldo sintético.",
        confidence=Confidence.HIGH,
        investigation_summary="La dirección coincide.",
        evidence=[evidence],
    ).model_dump(mode="json")
    rendered = "🧪 *Piloto.*\n*Resultado:* coincidencia — confianza alta."
    rows[0].run.output_message = rendered
    rows[0].outputs[0].body = rendered
    rows[0].feedback[0].reaction = "electric_plug"
    rows[0].feedback[0].sentiment = "negative"
    rows[0].tools.append(
        ToolCall(
            id=uuid4(),
            agent_run_id=rows[0].run.id,
            sequence=1,
            tool_name="verify_payment_candidate",
            status="succeeded",
        )
    )

    report = grade_rows(rows)

    assert report["negative_high_confidence"] == 1
    assert "negative_high_confidence" in report["errors"]
    assert "negative_high_confidence" in report["cases"][0]["errors"]
