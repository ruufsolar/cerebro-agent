"""Run `python -m cerebro.evals.run --live` with synthetic data and Azure credentials."""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from PIL import Image, ImageDraw

from cerebro.agent.data_tools import FixtureInvestigationData
from cerebro.agent.openai_runner import OpenAIAgentsRunner
from cerebro.agent.runner import AgentRunInput, ImageIngestion, TranscriptMessage
from cerebro.config import get_config
from cerebro.evals.corpus import load_corpus


async def run_live() -> int:
    config = get_config()
    if not config.azure_agent_ready:
        raise SystemExit("Azure endpoint, API key, and main deployment are required for --live")
    corpus = load_corpus()
    failures = 0
    for case in corpus.cases:
        runner = OpenAIAgentsRunner(
            config,
            data=FixtureInvestigationData(case.observations),
        )
        try:
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
                )
            )
        finally:
            await runner.close()
        actual_order = (
            result.identification.recommended_customer.order_id
            if result.identification.recommended_customer
            else None
        )
        passed = (
            result.identification.confidence == case.expected_confidence
            and actual_order == case.expected_order_id
        )
        failures += not passed
        print(
            f"{'PASS' if passed else 'FAIL'} {case.id}: "
            f"confidence={result.identification.confidence} order={actual_order}"
        )
    vision_case = next(case for case in corpus.cases if case.id == "address_glosa_match")
    with TemporaryDirectory(prefix="cerebro-vision-eval-") as temporary_directory:
        screenshot = Path(temporary_directory) / "synthetic-bank-payment.png"
        image = Image.new("RGB", (1_200, 500), "white")
        draw = ImageDraw.Draw(image)
        draw.text((60, 70), "Transferencia recibida", fill="black")
        draw.text((60, 170), "Monto: $1.500.000 CLP", fill="black")
        draw.text((60, 270), "Glosa: Los Aromos 1234", fill="black")
        draw.text((60, 370), "Fecha: 01-09-2026", fill="black")
        image.save(screenshot, format="PNG")
        runner = OpenAIAgentsRunner(
            config,
            data=FixtureInvestigationData(vision_case.observations),
        )
        try:
            result = await runner.run(
                AgentRunInput(
                    run_id=uuid4(),
                    slack_channel_id="eval",
                    slack_thread_ts="synthetic_vision",
                    requester_slack_user_id="eval",
                    transcript=(
                        TranscriptMessage(
                            direction="inbound",
                            text="Identifica el pago de esta captura sintética.",
                            event_at=datetime.now(UTC),
                            sender_slack_user_id="eval",
                            slack_message_ts="synthetic_vision",
                        ),
                    ),
                    trigger_slack_message_ts="synthetic_vision",
                    image_paths=(screenshot,),
                    image_ingestion=ImageIngestion(
                        requested=1,
                        metadata_accepted=1,
                        downloaded=1,
                    ),
                )
            )
        finally:
            await runner.close()
        actual_order = (
            result.identification.recommended_customer.order_id
            if result.identification.recommended_customer
            else None
        )
        passed = (
            result.identification.confidence == vision_case.expected_confidence
            and actual_order == vision_case.expected_order_id
        )
        failures += not passed
        print(
            f"{'PASS' if passed else 'FAIL'} synthetic_vision: "
            f"confidence={result.identification.confidence} order={actual_order}"
        )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Call Azure with synthetic tools")
    args = parser.parse_args()
    corpus = load_corpus()
    if not args.live:
        print(
            f"Validated {len(corpus.cases)} synthetic cases ({corpus.version}); use --live to run."
        )
        return
    raise SystemExit(asyncio.run(run_live()))


if __name__ == "__main__":
    main()
