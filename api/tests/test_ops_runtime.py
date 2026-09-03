from datetime import UTC, datetime, timedelta

from cerebro.config import AppConfig, GlobalMode, ReadinessProfile, get_config
from cerebro.db.models import RuntimeHeartbeat
from cerebro.db.session import open_session
from cerebro.ops.readiness import readiness_report
from cerebro.ops.runtime import (
    RuntimeComponent,
    component_health,
    maintain_heartbeat,
    touch_heartbeat,
)


async def test_runtime_heartbeat_is_upserted_and_reports_health(clean_database) -> None:
    await touch_heartbeat(RuntimeComponent.SLACK, "instance-one")
    await touch_heartbeat(RuntimeComponent.SLACK, "instance-one")

    health = await component_health([RuntimeComponent.SLACK], stale_seconds=45)
    assert health == {"slack": "ok"}

    async with open_session() as session:
        row = await session.get(RuntimeHeartbeat, "slack")
        assert row is not None
        row.last_seen_at = datetime.now(UTC) - timedelta(seconds=60)
        await session.commit()

    health = await component_health([RuntimeComponent.SLACK], stale_seconds=45)
    assert health == {"slack": "stale"}


async def test_runtime_heartbeat_marks_graceful_shutdown(clean_database) -> None:
    config = AppConfig(database_url=get_config().database_url)

    async with maintain_heartbeat(RuntimeComponent.CONTROL_WORKER, config):
        assert await component_health([RuntimeComponent.CONTROL_WORKER], stale_seconds=45) == {
            "control-worker": "ok"
        }

    assert await component_health([RuntimeComponent.CONTROL_WORKER], stale_seconds=45) == {
        "control-worker": "stopped"
    }


async def test_foundation_readiness_does_not_require_runtime_components(clean_database) -> None:
    ready, report = await readiness_report(
        AppConfig(
            database_url=get_config().database_url,
            readiness_profile=ReadinessProfile.FOUNDATION,
        )
    )

    assert ready is True
    assert report["status"] == "ready"
    assert "components" not in report["checks"]


async def test_pilot_readiness_requires_complete_config_and_fresh_components(
    clean_database,
) -> None:
    config = AppConfig(
        database_url=get_config().database_url,
        readiness_profile=ReadinessProfile.PILOT,
        slack_app_token="xapp-test",
        slack_bot_token="xoxb-test",
        azure_openai_endpoint="https://azure.invalid",
        azure_openai_api_key="secret",
        read_replica_url="postgresql://readonly@replica.invalid/monolith?sslmode=require",
        global_mode=GlobalMode.OFF,
    )
    for component in RuntimeComponent:
        await touch_heartbeat(component, f"instance-{component.value}")

    ready, report = await readiness_report(config)

    assert ready is True
    assert report["checks"]["pilot_configuration"] == "ok"
    assert set(report["checks"]["components"].values()) == {"ok"}


async def test_pilot_readiness_rejects_enabled_business_writes(clean_database) -> None:
    config = AppConfig(
        database_url=get_config().database_url,
        readiness_profile=ReadinessProfile.PILOT,
        payment_writes_enabled=True,
    )

    ready, report = await readiness_report(config)

    assert ready is False
    assert report["checks"]["pilot_configuration"] == "incomplete"
