"""Aggregate local operational status without customer or conversation content."""

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from cerebro.db.enums import DeliveryStatus, RunStatus, SlackEventDisposition
from cerebro.db.models import AgentRun, Feedback, RuntimeHeartbeat, SlackEvent, SlackOutput
from cerebro.db.session import dispose_engine, open_session
from cerebro.ops.metrics import latency_summary


async def collect_status(hours: int) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    async with open_session() as session:
        runs = list(
            (await session.scalars(select(AgentRun).where(AgentRun.created_at >= since))).all()
        )
        outputs = list(
            (
                await session.scalars(select(SlackOutput).where(SlackOutput.created_at >= since))
            ).all()
        )
        events = list(
            (await session.scalars(select(SlackEvent).where(SlackEvent.received_at >= since))).all()
        )
        feedback = list(
            (
                await session.scalars(
                    select(Feedback).where(
                        Feedback.created_at >= since, Feedback.is_active.is_(True)
                    )
                )
            ).all()
        )
        heartbeats = list((await session.scalars(select(RuntimeHeartbeat))).all())
        queue_rows = list(
            (
                await session.execute(
                    text(
                        """
                        SELECT queue_name, status::text, count(*)
                        FROM procrastinate_jobs
                        WHERE queue_name IN ('control', 'agent')
                          AND status::text IN ('todo', 'doing')
                        GROUP BY queue_name, status
                        """
                    )
                )
            ).all()
        )

    outcomes = Counter()
    image_failures = 0
    for run in runs:
        structured = run.structured_result or {}
        outcome = structured.get("outcome")
        if isinstance(outcome, str):
            outcomes[outcome] += 1
        snapshot = run.input_snapshot or {}
        ingestion = snapshot.get("image_ingestion", {})
        if isinstance(ingestion, dict):
            requested = ingestion.get("requested", 0)
            downloaded = ingestion.get("downloaded", 0)
            if isinstance(requested, int) and isinstance(downloaded, int):
                image_failures += max(0, requested - downloaded)

    latencies = [run.latency_ms / 1_000 for run in runs if run.latency_ms is not None]
    queue_counts: dict[str, dict[str, int]] = {
        "control": {"queued": 0, "running": 0},
        "agent": {"queued": 0, "running": 0},
    }
    for queue_name, status, count in queue_rows:
        queue = queue_counts.get(str(queue_name))
        if queue is not None:
            queue["queued" if status == "todo" else "running"] = int(count)

    run_failures = Counter(
        run.error_code or "uncategorized" for run in runs if run.status == RunStatus.FAILED
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_hours": hours,
        "runs": dict(sorted(Counter(run.status for run in runs).items())),
        "outcomes": dict(sorted(outcomes.items())),
        "events": dict(sorted(Counter(event.disposition for event in events).items())),
        "outputs": dict(sorted(Counter(output.status for output in outputs).items())),
        "feedback": dict(sorted(Counter(item.sentiment for item in feedback).items())),
        "queues": queue_counts,
        "failures": {
            "runs": dict(sorted(run_failures.items())),
            "events": sum(event.disposition == SlackEventDisposition.FAILED for event in events),
            "outputs": sum(output.status == DeliveryStatus.FAILED for output in outputs),
        },
        "latency": latency_summary(latencies),
        "usage": {
            "input_tokens": sum(run.input_tokens or 0 for run in runs),
            "output_tokens": sum(run.output_tokens or 0 for run in runs),
            "turns": sum(run.turns or 0 for run in runs),
            "tool_calls": sum(run.tool_calls or 0 for run in runs),
        },
        "image_attachments_unprocessed": image_failures,
        "components": {
            row.component: {
                "status": row.status,
                "version": row.version,
                "last_seen_at": row.last_seen_at.isoformat(),
            }
            for row in heartbeats
        },
    }


def _print_human(report: dict[str, Any]) -> None:
    print(f"window_hours={report['window_hours']}")
    for key in (
        "queues",
        "runs",
        "failures",
        "outcomes",
        "events",
        "outputs",
        "feedback",
        "latency",
        "usage",
    ):
        print(f"{key}={json.dumps(report[key], sort_keys=True)}")
    print(f"image_attachments_unprocessed={report['image_attachments_unprocessed']}")
    print(f"components={json.dumps(report['components'], sort_keys=True)}")


async def _run(hours: int, json_output: bool) -> int:
    try:
        try:
            report = await collect_status(hours)
        except Exception as exc:
            error = {"status": "failed", "error_code": f"failed_{type(exc).__name__}"}
            if json_output:
                print(json.dumps(error, sort_keys=True))
            else:
                print(f"status=failed error_code={error['error_code']}")
            return 2
        if json_output:
            print(json.dumps(report, sort_keys=True))
        else:
            _print_human(report)
        return 0
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()
    if args.hours < 1 or args.hours > 24 * 90:
        parser.error("--hours must be between 1 and 2160")
    raise SystemExit(asyncio.run(_run(args.hours, args.json_output)))


if __name__ == "__main__":
    main()
