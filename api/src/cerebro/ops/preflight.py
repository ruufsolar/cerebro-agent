"""Preflight configuration and dependency checks for foundation and pilot operation."""

import argparse
import asyncio
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy import text

from cerebro.agent.data_tools import EmptyInvestigationData
from cerebro.agent.openai_runner import OpenAIAgentsRunner
from cerebro.agent.runner import AgentRunInput, TranscriptMessage
from cerebro.config import AppConfig, ReadinessProfile, get_config
from cerebro.db.session import dispose_engine, open_session
from cerebro.observability import configure_logging
from cerebro.ops.readiness import MIGRATION_HEAD
from cerebro.replica.database import ReplicaDatabase
from cerebro.replica.scope import load_knowledge


async def _database_check() -> str:
    async with open_session() as session:
        await session.execute(text("SELECT 1"))
        version = await session.scalar(text("SELECT version_num FROM alembic_version"))
        jobs = await session.scalar(text("SELECT to_regclass('procrastinate_jobs')"))
    if version != MIGRATION_HEAD:
        return "schema_outdated"
    if not jobs:
        return "jobs_schema_missing"
    return "ok"


async def _temporary_storage_check(config: AppConfig) -> str:
    root = Path(config.image_temp_root)

    def create_probe() -> None:
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise RuntimeError("temporary image root is not a directory")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, stat.S_IRWXU)
        metadata = root.stat()
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise RuntimeError("temporary image root is not private")
        with TemporaryDirectory(prefix="preflight-", dir=root) as directory:
            probe = Path(directory) / "probe"
            probe.write_bytes(b"ok")
            os.chmod(probe, 0o600)

    await asyncio.to_thread(create_probe)
    return "ok"


async def _slack_check(config: AppConfig) -> str:
    client = AsyncWebClient(token=config.slack_bot_token)
    try:
        response = await client.auth_test()
        return "ok" if response.get("ok") else "authentication_failed"
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            await close()
        else:
            session = getattr(client, "session", None)
            if session is not None and not session.closed:
                await session.close()


async def _replica_check(config: AppConfig) -> str:
    database = ReplicaDatabase(config, load_knowledge(config.knowledge_dir))
    try:
        await database.start()
        return "ok"
    finally:
        await database.close()


async def _provider_check(config: AppConfig) -> str:
    runner = OpenAIAgentsRunner(config, data=EmptyInvestigationData())
    now = datetime.now(UTC)
    try:
        await runner.run(
            AgentRunInput(
                run_id=uuid4(),
                slack_channel_id="preflight",
                slack_thread_ts="preflight",
                requester_slack_user_id="preflight",
                transcript=(
                    TranscriptMessage(
                        direction="inbound",
                        text="Identifica este pago sintético sin datos de clientes: CLP 1.",
                        event_at=now,
                        sender_slack_user_id="preflight",
                        slack_message_ts="preflight",
                    ),
                ),
                trigger_slack_message_ts="preflight",
            )
        )
        return "ok"
    finally:
        await runner.close()


async def run_preflight(profile: ReadinessProfile, live_provider: bool) -> dict[str, Any]:
    config = get_config().model_copy(update={"readiness_profile": profile})
    checks: dict[str, str] = {}
    operations = {
        "database": lambda: _database_check(),
        "temporary_storage": lambda: _temporary_storage_check(config),
    }
    if profile is ReadinessProfile.PILOT:
        checks["configuration"] = "ok" if config.pilot_configuration_ready else "incomplete"
        operations.update(
            {
                "slack": lambda: _slack_check(config),
                "replica": lambda: _replica_check(config),
            }
        )
    if live_provider:
        operations["azure_provider"] = lambda: _provider_check(config)

    for name, operation in operations.items():
        try:
            checks[name] = await operation()
        except Exception as exc:
            checks[name] = f"failed_{type(exc).__name__}"
    return {
        "status": "ok" if checks and all(value == "ok" for value in checks.values()) else "failed",
        "profile": profile,
        "live_provider": live_provider,
        "checks": checks,
    }


async def _run(profile: ReadinessProfile, live_provider: bool, json_output: bool) -> int:
    configure_logging("preflight")
    try:
        report = await run_preflight(profile, live_provider)
        if json_output:
            print(json.dumps(report, sort_keys=True))
        else:
            print(f"preflight={report['status']} profile={profile.value}")
            for name, status in report["checks"].items():
                print(f"{name}={status}")
        return 0 if report["status"] == "ok" else 1
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=tuple(item.value for item in ReadinessProfile),
        default=ReadinessProfile.FOUNDATION.value,
    )
    parser.add_argument("--live-provider", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(_run(ReadinessProfile(args.profile), args.live_provider, args.json_output))
    )


if __name__ == "__main__":
    main()
