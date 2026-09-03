import procrastinate
from procrastinate.schema import SchemaManager
from sqlalchemy import create_engine, text

from cerebro.config import get_config
from cerebro.observability import configure_logging


def ensure_procrastinate_schema() -> None:
    """Apply Procrastinate's schema once; safe to call on every worker start."""
    config = get_config()
    engine = create_engine(config.alembic_url)
    with engine.connect() as connection:
        exists = connection.execute(text("SELECT to_regclass('procrastinate_jobs')")).scalar()
    engine.dispose()
    if exists:
        return

    connector = procrastinate.SyncPsycopgConnector(conninfo=config.procrastinate_conninfo)
    connector.open()
    try:
        SchemaManager(connector=connector).apply_schema()
    finally:
        connector.close()


if __name__ == "__main__":
    configure_logging("job-schema")
    ensure_procrastinate_schema()
