"""Run Slice 5's synthetic release gate without Slack or production customer data."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import uuid4

from PIL import Image, ImageDraw

from cerebro.agent.data_tools import FixtureInvestigationData
from cerebro.agent.models import Confidence, IdentificationOutcome
from cerebro.agent.openai_runner import OpenAIAgentsRunner
from cerebro.agent.runner import (
    AgentRunInput,
    AgentRunResult,
    ImageIngestion,
    TranscriptMessage,
)
from cerebro.config import get_config
from cerebro.evals.corpus import EvalCase, load_corpus
from cerebro.ops.metrics import latency_summary
from cerebro.slack.pipeline import render_identification


def grade_case(case: EvalCase, result: AgentRunResult, rendered: str) -> list[str]:
    errors: list[str] = []
    identification = result.identification
    actual_order = (
        identification.recommended_customer.order_id
        if identification.recommended_customer
        else None
    )
    if identification.outcome is not case.expected_outcome:
        errors.append(f"outcome:{identification.outcome}")
    if actual_order != case.expected_order_id:
        errors.append(f"order:{actual_order}")
    if identification.confidence is not case.expected_confidence:
        errors.append(f"confidence:{identification.confidence}")

    alternative_orders = {item.order_id for item in identification.alternatives}
    if not alternative_orders <= set(case.allowed_alternative_order_ids):
        errors.append("alternatives:unexpected")

    evidence_kinds = {item.kind for item in identification.evidence}
    if not set(case.required_evidence_kinds) <= evidence_kinds:
        errors.append("evidence:required_missing")
    if set(case.forbidden_evidence_kinds) & evidence_kinds:
        errors.append("evidence:forbidden_present")

    tool_names = {item.tool_name for item in result.tool_calls}
    if not set(case.required_tools) <= tool_names:
        errors.append("tools:required_missing")
    if set(case.forbidden_tools) & tool_names:
        errors.append("tools:forbidden_present")

    evidence_by_id = {item.evidence_id: item for item in identification.evidence}
    customers = [
        item
        for item in [identification.recommended_customer, *identification.alternatives]
        if item is not None
    ]
    for customer in customers:
        if not customer.evidence_ids or any(
            evidence_id not in evidence_by_id for evidence_id in customer.evidence_ids
        ):
            errors.append("unsupported:evidence_reference")
            continue
        if any(
            evidence_by_id[evidence_id].order_id != customer.order_id
            for evidence_id in customer.evidence_ids
        ):
            errors.append("unsupported:cross_candidate_evidence")

    lowered = rendered.casefold()
    if any(claim.casefold() in lowered for claim in case.forbidden_claims):
        errors.append("claims:forbidden")

    lines = len([line for line in rendered.splitlines() if line.strip()])
    words = len(rendered.split())
    if identification.outcome is IdentificationOutcome.MATCHED:
        if lines > 6 or words > (130 if identification.alternatives else 110):
            errors.append("format:too_verbose")
    elif identification.outcome is IdentificationOutcome.OUT_OF_SCOPE:
        if lines > 2 or words > 40:
            errors.append("format:too_verbose")
    elif lines > 4 or words > (130 if identification.alternatives else 75):
        errors.append("format:too_verbose")
    return errors


def _write_screenshot(path: Path, lines: list[str]) -> None:
    image = Image.new("RGB", (1_200, max(420, 90 * (len(lines) + 1))), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((60, 60 + index * 90), line, fill="black")
    image.save(path, format="PNG")


async def _run_case(case: EvalCase) -> tuple[AgentRunResult, str, int]:
    config = get_config()
    runner = OpenAIAgentsRunner(config, data=FixtureInvestigationData(case.observations))
    try:
        with TemporaryDirectory(prefix="cerebro-eval-") as temporary_directory:
            image_paths: tuple[Path, ...] = ()
            ingestion = ImageIngestion()
            if case.image_text:
                screenshot = Path(temporary_directory) / "synthetic-bank-payment.png"
                _write_screenshot(screenshot, case.image_text)
                image_paths = (screenshot,)
                ingestion = ImageIngestion(requested=1, metadata_accepted=1, downloaded=1)
            started = monotonic()
            result = await runner.run(
                AgentRunInput(
                    run_id=uuid4(),
                    slack_channel_id="eval",
                    slack_thread_ts=case.id,
                    requester_slack_user_id="eval",
                    transcript=(
                        TranscriptMessage(
                            direction="inbound",
                            text=case.prompt,
                            event_at=datetime.now(UTC),
                            sender_slack_user_id="eval",
                            slack_message_ts=case.id,
                        ),
                    ),
                    trigger_slack_message_ts=case.id,
                    image_paths=image_paths,
                    image_ingestion=ingestion,
                )
            )
            duration_ms = int((monotonic() - started) * 1_000)
            return result, render_identification(result, ingestion), duration_ms
    finally:
        await runner.close()


async def run_live(json_output: Path | None = None, case_ids: set[str] | None = None) -> int:
    config = get_config()
    if not config.azure_agent_ready:
        raise SystemExit("Azure endpoint, API key, and Luna deployment are required for --live")
    corpus = load_corpus()
    cases = [case for case in corpus.cases if case_ids is None or case.id in case_ids]
    if not cases:
        raise SystemExit("No evaluation cases matched --case")
    rows: list[dict[str, object]] = []
    correct = 0
    wrong_high = 0
    unsupported = 0
    durations: list[float] = []
    input_tokens: list[int] = []
    output_tokens: list[int] = []
    for case in cases:
        result, rendered, duration_ms = await _run_case(case)
        durations.append(duration_ms / 1_000)
        if result.usage.input_tokens is not None:
            input_tokens.append(result.usage.input_tokens)
        if result.usage.output_tokens is not None:
            output_tokens.append(result.usage.output_tokens)
        errors = grade_case(case, result, rendered)
        actual_order = (
            result.identification.recommended_customer.order_id
            if result.identification.recommended_customer
            else None
        )
        passed = not errors
        correct += passed
        wrong_high += (
            result.identification.confidence is Confidence.HIGH
            and actual_order != case.expected_order_id
        )
        unsupported += any(item.startswith("unsupported:") for item in errors)
        rows.append(
            {
                "id": case.id,
                "passed": passed,
                "outcome": result.identification.outcome,
                "confidence": result.identification.confidence,
                "order_id": actual_order,
                "model": result.usage.model,
                "duration_ms": duration_ms,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "errors": errors,
            }
        )
        print(
            f"{'PASS' if passed else 'FAIL'} {case.id}: "
            f"outcome={result.identification.outcome} "
            f"confidence={result.identification.confidence} "
            f"order={actual_order} errors={','.join(errors) or '-'}"
        )
    required_correct = 17 if case_ids is None else len(cases)
    passed = correct >= required_correct and wrong_high == 0 and unsupported == 0
    report = {
        "corpus_version": corpus.version,
        "deployment": config.azure_deployment_main,
        "cases": len(cases),
        "required_correct": required_correct,
        "correct": correct,
        "wrong_high_confidence": wrong_high,
        "unsupported_claims": unsupported,
        "latency": latency_summary(durations),
        "usage": {
            "input_tokens": sum(input_tokens),
            "output_tokens": sum(output_tokens),
            "average_input_tokens": round(sum(input_tokens) / len(input_tokens), 2)
            if input_tokens
            else None,
            "average_output_tokens": round(sum(output_tokens) / len(output_tokens), 2)
            if output_tokens
            else None,
        },
        "passed": passed,
        "results": rows,
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    print(encoded)
    if json_output:
        await asyncio.to_thread(json_output.write_text, encoded + "\n", encoding="utf-8")
    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Call Azure with synthetic tools")
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run one named case (repeatable); intended for live diagnostics",
    )
    parser.add_argument("--json-output", type=Path, help="Write a machine-readable gate report")
    args = parser.parse_args()
    corpus = load_corpus()
    if len(corpus.cases) != 20:
        raise SystemExit(f"Slice 5 requires exactly 20 cases; found {len(corpus.cases)}")
    if not args.live:
        print(f"Validated 20 synthetic cases ({corpus.version}); use --live to run Luna.")
        return
    requested = set(args.case_ids) if args.case_ids else None
    if requested:
        known = {case.id for case in corpus.cases}
        unknown = sorted(requested - known)
        if unknown:
            raise SystemExit(f"Unknown evaluation case(s): {', '.join(unknown)}")
    raise SystemExit(asyncio.run(run_live(args.json_output, requested)))


if __name__ == "__main__":
    main()
