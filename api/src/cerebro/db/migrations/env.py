from alembic import context
from sqlalchemy import engine_from_config, pool

from cerebro.config import get_config
from cerebro.db import models  # noqa: F401
from cerebro.db.base import Base
from cerebro.observability import configure_logging

config = context.config
configure_logging("migration", get_config())

target_metadata = Base.metadata


def include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    """Leave Procrastinate's independently managed schema out of Alembic diffs."""
    del object_, reflected, compare_to
    return not (type_ == "table" and name is not None and name.startswith("procrastinate_"))


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_config().alembic_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": _url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
