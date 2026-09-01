"""Run `python -m cerebro.evals.run --live` with synthetic data and Azure credentials."""

import argparse
import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from cerebro.agent.data_tools import FixtureInvestigationData
from cerebro.agent.openai_runner import OpenAIAgentsRunner
from cerebro.agent.runner import AgentRunInput, TranscriptMessage
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
                        ),
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
            result.identification.confidence == case.expected_confidence
            and actual_order == case.expected_order_id
        )
        failures += not passed
        print(
            f"{'PASS' if passed else 'FAIL'} {case.id}: "
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
