"""Dependency-free liveness and local-state readiness checks."""

from typing import Any

from sqlalchemy import text

from cerebro.config import AppConfig, ReadinessProfile, get_config
from cerebro.db.session import open_session
from cerebro.ops.runtime import PILOT_COMPONENTS, component_health

MIGRATION_HEAD = "20260902_0005"


async def readiness_report(config: AppConfig | None = None) -> tuple[bool, dict[str, Any]]:
    config = config or get_config()
    checks: dict[str, Any] = {
        "database": "unavailable",
        "alembic": "unavailable",
        "jobs": "unavailable",
    }
    try:
        async with open_session() as session:
            await session.execute(text("SELECT 1"))
            checks["database"] = "ok"
            version = await session.scalar(text("SELECT version_num FROM alembic_version"))
            checks["alembic"] = "ok" if version == MIGRATION_HEAD else "outdated"
            jobs = await session.scalar(text("SELECT to_regclass('procrastinate_jobs')"))
            checks["jobs"] = "ok" if jobs else "missing"
    except Exception as exc:
        checks["error_code"] = f"database_{type(exc).__name__}"

    if config.readiness_profile is ReadinessProfile.PILOT:
        checks["pilot_configuration"] = "ok" if config.pilot_configuration_ready else "incomplete"
        try:
            checks["components"] = await component_health(
                PILOT_COMPONENTS, stale_seconds=config.runtime_stale_seconds
            )
        except Exception as exc:
            checks["components"] = {"status": "unavailable"}
            checks["component_error_code"] = type(exc).__name__

    foundation_ready = all(checks[name] == "ok" for name in ("database", "alembic", "jobs"))
    pilot_ready = True
    if config.readiness_profile is ReadinessProfile.PILOT:
        component_checks = checks.get("components", {})
        pilot_ready = (
            checks["pilot_configuration"] == "ok"
            and bool(component_checks)
            and all(value == "ok" for value in component_checks.values())
        )
    ready = foundation_ready and pilot_ready
    return ready, {
        "status": "ready" if ready else "not_ready",
        "profile": config.readiness_profile,
        "checks": checks,
    }
