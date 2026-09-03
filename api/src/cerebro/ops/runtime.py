"""Runtime component heartbeats shared by the web readiness endpoint and processes."""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from cerebro import __version__
from cerebro.config import AppConfig, get_config
from cerebro.db.models import RuntimeHeartbeat
from cerebro.db.session import open_session
from cerebro.observability import log_event

logger = logging.getLogger(__name__)


class RuntimeComponent(StrEnum):
    SLACK = "slack"
    CONTROL_WORKER = "control-worker"
    AGENT_WORKER = "agent-worker"


PILOT_COMPONENTS = (
    RuntimeComponent.SLACK,
    RuntimeComponent.CONTROL_WORKER,
    RuntimeComponent.AGENT_WORKER,
)


async def touch_heartbeat(
    component: RuntimeComponent,
    instance_id: str,
    *,
    status: str = "running",
    detail_code: str | None = None,
) -> None:
    now = datetime.now(UTC)
    statement = insert(RuntimeHeartbeat).values(
        component=component.value,
        instance_id=instance_id,
        status=status,
        version=__version__,
        started_at=now,
        last_seen_at=now,
        detail_code=detail_code,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[RuntimeHeartbeat.component],
        set_={
            "instance_id": instance_id,
            "status": status,
            "version": __version__,
            "last_seen_at": now,
            "detail_code": detail_code,
            "started_at": now,
        },
        where=(RuntimeHeartbeat.instance_id != instance_id),
    )
    async with open_session() as session:
        result = await session.execute(statement)
        if getattr(result, "rowcount", 0) == 0:
            await session.execute(
                update(RuntimeHeartbeat)
                .where(
                    RuntimeHeartbeat.component == component.value,
                    RuntimeHeartbeat.instance_id == instance_id,
                )
                .values(status=status, last_seen_at=now, detail_code=detail_code)
            )
        await session.commit()


async def _heartbeat_loop(
    component: RuntimeComponent,
    instance_id: str,
    config: AppConfig,
    stopped: asyncio.Event,
) -> None:
    while not stopped.is_set():
        try:
            await touch_heartbeat(component, instance_id)
        except Exception as exc:
            log_event(
                logger,
                "heartbeat_failed",
                level=logging.WARNING,
                component=component,
                instance_id=instance_id,
                error_type=type(exc).__name__,
            )
        try:
            await asyncio.wait_for(stopped.wait(), timeout=config.runtime_heartbeat_seconds)
        except TimeoutError:
            continue


@asynccontextmanager
async def maintain_heartbeat(
    component: RuntimeComponent, config: AppConfig | None = None
) -> AsyncIterator[str]:
    config = config or get_config()
    instance_id = uuid4().hex[:16]
    stopped = asyncio.Event()
    await touch_heartbeat(component, instance_id)
    task = asyncio.create_task(
        _heartbeat_loop(component, instance_id, config, stopped),
        name=f"cerebro-heartbeat-{component.value}",
    )
    try:
        yield instance_id
    finally:
        stopped.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        with suppress(Exception):
            await touch_heartbeat(component, instance_id, status="stopped")


async def component_health(
    components: Iterable[RuntimeComponent], *, stale_seconds: int
) -> dict[str, str]:
    names = [component.value for component in components]
    async with open_session() as session:
        rows = list(
            (
                await session.scalars(
                    select(RuntimeHeartbeat).where(RuntimeHeartbeat.component.in_(names))
                )
            ).all()
        )
    by_name = {row.component: row for row in rows}
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    result: dict[str, str] = {}
    for name in names:
        row = by_name.get(name)
        if row is None:
            result[name] = "missing"
        elif row.status != "running":
            result[name] = "stopped"
        elif row.last_seen_at < cutoff:
            result[name] = "stale"
        else:
            result[name] = "ok"
    return result
