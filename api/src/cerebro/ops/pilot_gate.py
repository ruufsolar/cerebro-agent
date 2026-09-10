"""Feedback quality reporting; the legacy pilot command keeps its original defaults."""

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from statistics import mean, median
from typing import Any

from sqlalchemy import select

from cerebro.agent.models import (
    Confidence,
    IdentificationOutcome,
    PaymentIdentification,
    RequestKind,
)
from cerebro.db.enums import DeliveryStatus, RunStatus, SlackOutputKind
from cerebro.db.models import AgentRun, Feedback, Message, SlackOutput, ToolCall
from cerebro.db.session import dispose_engine, open_session
from cerebro.ops.metrics import nearest_rank

EXPECTED_CASES = 10
MIN_IMAGE_CASES = 4
MAX_MEDIAN_SECONDS = 60
MAX_P95_SECONDS = 120
MAX_AVERAGE_INPUT_TOKENS = 50_000
MAX_AVERAGE_OUTPUT_TOKENS = 1_000
MAX_RUN_INPUT_TOKENS = 100_000
MAX_RUN_OUTPUT_TOKENS = 2_000

_SOURCE_TO_TOOL = {
    "payment_candidates": "search_payment_candidates",
    "candidate_verification": "verify_payment_candidate",
    "vambe": "search_vambe_messages",
}


@dataclass(frozen=True)
class QualityPolicy:
    expected_cases: int | None = EXPECTED_CASES
    min_image_cases: int = MIN_IMAGE_CASES
    min_positive_rate: float = 0.9

    def __post_init__(self) -> None:
        if self.expected_cases is not None and self.expected_cases < 1:
            raise ValueError("sample size must be positive")
        if self.min_image_cases < 0 or not 0 <= self.min_positive_rate <= 1:
            raise ValueError("invalid quality thresholds")


@dataclass(frozen=True)
class PilotRow:
    run: AgentRun
    trigger: Message
    outputs: list[SlackOutput]
    feedback: list[Feedback]
    tools: list[ToolCall]


DEFAULT_POLICY = QualityPolicy()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _image_downloaded(run: AgentRun) -> int:
    for step in run.steps or []:
        if isinstance(step, dict) and step.get("type") == "image_ingestion":
            value = step.get("downloaded")
            return value if isinstance(value, int) and value >= 0 else 0
    return 0


def _response_length_error(result: PaymentIdentification, body: str) -> bool:
    lines = len([line for line in body.splitlines() if line.strip()])
    words = len(body.split())
    if result.outcome is IdentificationOutcome.MATCHED:
        return lines > 6 or words > (130 if result.alternatives else 110)
    if result.outcome is IdentificationOutcome.OUT_OF_SCOPE:
        return lines > 2 or words > 40
    return lines > 4 or words > (130 if result.alternatives else 75)


def _unsupported(result: PaymentIdentification, tools: list[ToolCall]) -> bool:
    evidence = {item.evidence_id: item for item in result.evidence}
    successful_tools = {tool.tool_name for tool in tools if tool.status == "succeeded"}
    customers = [
        customer
        for customer in [result.recommended_customer, *result.alternatives]
        if customer is not None
    ]
    for customer in customers:
        if not customer.evidence_ids:
            return True
        for evidence_id in customer.evidence_ids:
            signal = evidence.get(evidence_id)
            if signal is None or signal.order_id != customer.order_id:
                return True
            expected_tool = _SOURCE_TO_TOOL.get(signal.source.value)
            if expected_tool is None or expected_tool not in successful_tools:
                return True
    return False


def _effective_feedback(items: list[Feedback]) -> tuple[str, list[str]]:
    reactions = {item.reaction for item in items if item.is_active}
    cheese = "cheese_wedge" in reactions
    plug = "electric_plug" in reactions
    if cheese and plug:
        return "conflict", ["feedback_conflict"]
    if plug:
        return "negative", []
    if cheese:
        return "positive", []
    return "missing", ["feedback_missing"]


async def _load_rows(channel: str, since: datetime, until: datetime) -> list[PilotRow]:
    async with open_session() as session:
        pairs = list(
            (
                await session.execute(
                    select(AgentRun, Message)
                    .join(Message, AgentRun.trigger_message_id == Message.id)
                    .where(
                        Message.slack_channel_id == channel,
                        Message.event_at >= since,
                        Message.event_at <= until,
                        AgentRun.request_kind == RequestKind.PAYMENT_IDENTIFICATION,
                    )
                    .order_by(Message.event_at, AgentRun.created_at)
                )
            ).all()
        )
        rows: list[PilotRow] = []
        for run, trigger in pairs:
            outputs = list(
                (
                    await session.scalars(
                        select(SlackOutput).where(SlackOutput.agent_run_id == run.id)
                    )
                ).all()
            )
            investigation_timestamps = [
                output.slack_message_ts
                for output in outputs
                if output.kind == SlackOutputKind.INVESTIGATION and output.slack_message_ts
            ]
            feedback = []
            if investigation_timestamps:
                feedback = list(
                    (
                        await session.scalars(
                            select(Feedback).where(
                                Feedback.slack_channel_id == channel,
                                Feedback.slack_message_ts.in_(investigation_timestamps),
                                Feedback.is_active.is_(True),
                            )
                        )
                    ).all()
                )
            tools = list(
                (
                    await session.scalars(select(ToolCall).where(ToolCall.agent_run_id == run.id))
                ).all()
            )
            rows.append(PilotRow(run, trigger, outputs, feedback, tools))
        return rows


def grade_rows(rows: list[PilotRow], policy: QualityPolicy = DEFAULT_POLICY) -> dict[str, Any]:
    rows = [
        row for row in rows if row.run.request_kind in {None, RequestKind.PAYMENT_IDENTIFICATION}
    ]
    cases: list[dict[str, Any]] = []
    latencies: list[float] = []
    input_tokens: list[int] = []
    output_tokens: list[int] = []
    positive = 0
    negative_high = 0
    image_cases = 0

    for index, row in enumerate(rows, start=1):
        errors: list[str] = []
        run = row.run
        investigation_outputs = [
            output for output in row.outputs if output.kind == SlackOutputKind.INVESTIGATION
        ]
        sent = [output for output in investigation_outputs if output.status == DeliveryStatus.SENT]
        if len(investigation_outputs) != 1:
            errors.append("investigation_output_count")
        if len(sent) != 1 or sent[0].sent_at is None:
            errors.append("investigation_not_delivered")
        elif sent[0].body != (run.output_message or ""):
            errors.append("delivered_output_mismatch")
        if run.status != RunStatus.SUCCEEDED:
            errors.append("run_not_succeeded")
        if run.completion_reason == "timeout":
            errors.append("run_timeout")

        result: PaymentIdentification | None = None
        try:
            result = PaymentIdentification.model_validate(run.structured_result)
        except Exception:
            errors.append("invalid_structured_result")
        if result is not None:
            if _unsupported(result, row.tools):
                errors.append("unsupported_evidence")
            delivered_body = sent[0].body if len(sent) == 1 else run.output_message or ""
            if _response_length_error(result, delivered_body):
                errors.append("response_too_verbose")

        feedback, feedback_errors = _effective_feedback(row.feedback)
        errors.extend(feedback_errors)
        if feedback == "positive":
            positive += 1
        if feedback == "negative" and result and result.confidence is Confidence.HIGH:
            negative_high += 1
            errors.append("negative_high_confidence")

        downloaded = _image_downloaded(run)
        if downloaded > 0:
            image_cases += 1
        if sent and sent[0].sent_at:
            latency = max(0.0, (sent[0].sent_at - row.trigger.event_at).total_seconds())
            latencies.append(latency)
        if run.input_tokens is None or run.output_tokens is None:
            errors.append("usage_missing")
        else:
            input_tokens.append(run.input_tokens)
            output_tokens.append(run.output_tokens)
            if run.input_tokens > MAX_RUN_INPUT_TOKENS:
                errors.append("input_token_max")
            if run.output_tokens > MAX_RUN_OUTPUT_TOKENS:
                errors.append("output_token_max")

        cases.append(
            {
                "case": f"case_{index:02d}",
                "feedback": feedback,
                "image_used": downloaded > 0,
                "errors": sorted(set(errors)),
            }
        )

    aggregate_errors: list[str] = []
    expected_cases = policy.expected_cases if policy.expected_cases is not None else len(rows)
    if not rows or len(rows) != expected_cases:
        aggregate_errors.append("case_count")
    if image_cases < policy.min_image_cases:
        aggregate_errors.append("image_case_count")
    if positive < ceil(policy.min_positive_rate * expected_cases):
        aggregate_errors.append("positive_case_count")
    if negative_high:
        aggregate_errors.append("negative_high_confidence")

    median_latency = median(latencies) if latencies else None
    p95_latency = nearest_rank(latencies, 0.95)
    average_input = mean(input_tokens) if input_tokens else None
    average_output = mean(output_tokens) if output_tokens else None
    if len(latencies) != expected_cases:
        aggregate_errors.append("latency_missing")
    elif median_latency is not None and median_latency > MAX_MEDIAN_SECONDS:
        aggregate_errors.append("median_latency")
    if p95_latency is None or p95_latency > MAX_P95_SECONDS:
        aggregate_errors.append("p95_latency")
    if len(input_tokens) != expected_cases or average_input is None:
        aggregate_errors.append("input_usage_missing")
    elif average_input > MAX_AVERAGE_INPUT_TOKENS:
        aggregate_errors.append("average_input_tokens")
    if len(output_tokens) != expected_cases or average_output is None:
        aggregate_errors.append("output_usage_missing")
    elif average_output > MAX_AVERAGE_OUTPUT_TOKENS:
        aggregate_errors.append("average_output_tokens")

    versions = {
        "models": sorted({run.run.model for run in rows if run.run.model}),
        "prompts": sorted({run.run.prompt_version for run in rows if run.run.prompt_version}),
        "knowledge": sorted(
            {run.run.knowledge_version for run in rows if run.run.knowledge_version}
        ),
    }
    passed = not aggregate_errors and all(not case["errors"] for case in cases)
    models = versions["models"]
    return {
        "passed": passed,
        "policy": {
            "expected_cases": policy.expected_cases,
            "min_image_cases": policy.min_image_cases,
            "min_positive_rate": policy.min_positive_rate,
        },
        "score": f"{positive}/{len(rows)}",
        "case_count": len(rows),
        "positive_cases": positive,
        "image_cases": image_cases,
        "negative_high_confidence": negative_high,
        "latency": {
            "median_seconds": round(median_latency, 3) if median_latency is not None else None,
            "p95_seconds": round(p95_latency, 3) if p95_latency is not None else None,
        },
        "usage": {
            "average_input_tokens": round(average_input, 2) if average_input is not None else None,
            "average_output_tokens": round(average_output, 2)
            if average_output is not None
            else None,
            "max_input_tokens": max(input_tokens, default=None),
            "max_output_tokens": max(output_tokens, default=None),
        },
        "deployment": models[0] if len(models) == 1 else ("mixed" if models else None),
        "versions": versions,
        "errors": sorted(set(aggregate_errors)),
        "cases": cases,
    }


async def run_gate(
    channel: str, since: datetime, until: datetime, policy: QualityPolicy = DEFAULT_POLICY
) -> dict[str, Any]:
    if since > until:
        raise ValueError("since must be before until")
    return grade_rows(await _load_rows(channel, since, until), policy)


def _print_human(report: dict[str, Any]) -> None:
    print(f"quality_report={'pass' if report['passed'] else 'fail'}")
    print(
        f"cases={report['case_count']} score={report['score']} "
        f"images={report['image_cases']} negative_high={report['negative_high_confidence']}"
    )
    print(f"latency={json.dumps(report['latency'], sort_keys=True)}")
    print(f"usage={json.dumps(report['usage'], sort_keys=True)}")
    print(f"versions={json.dumps(report['versions'], sort_keys=True)}")
    print(f"deployment={report['deployment'] or '-'}")
    if report["errors"]:
        print(f"errors={','.join(report['errors'])}")
    for case in report["cases"]:
        print(
            f"{case['case']} feedback={case['feedback']} image={str(case['image_used']).lower()} "
            f"errors={','.join(case['errors']) or '-'}"
        )


async def _run(args: argparse.Namespace) -> int:
    try:
        try:
            report = await run_gate(
                args.channel,
                _parse_datetime(args.since),
                _parse_datetime(args.until),
                QualityPolicy(args.sample_size, args.min_image_cases, args.min_positive_rate),
            )
        except ValueError:
            raise
        except Exception as exc:
            error = {"passed": False, "error_code": f"failed_{type(exc).__name__}"}
            if args.json_output:
                print(json.dumps(error, sort_keys=True))
            else:
                print(f"pilot_gate=error error_code={error['error_code']}")
            return 2
        if args.json_output:
            print(json.dumps(report, sort_keys=True))
        else:
            _print_human(report)
        return 0 if report["passed"] else 1
    finally:
        await dispose_engine()


def main(*, flexible: bool = False) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", required=True)
    parser.add_argument("--since", required=True, help="ISO-8601 timestamp with timezone")
    parser.add_argument(
        "--until", default=datetime.now(UTC).isoformat(), help="ISO-8601 timestamp with timezone"
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--sample-size", type=int, default=None if flexible else EXPECTED_CASES)
    parser.add_argument("--min-image-cases", type=int, default=0 if flexible else MIN_IMAGE_CASES)
    parser.add_argument("--min-positive-rate", type=float, default=0.9)
    args = parser.parse_args()
    try:
        code = asyncio.run(_run(args))
    except ValueError as exc:
        parser.error(str(exc))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
