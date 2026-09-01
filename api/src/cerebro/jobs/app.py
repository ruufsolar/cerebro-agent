import procrastinate

from cerebro.config import get_config


def _make_app() -> procrastinate.App:
    return procrastinate.App(
        connector=procrastinate.PsycopgConnector(conninfo=get_config().procrastinate_conninfo),
        import_paths=["cerebro.jobs.tasks"],
    )


app = _make_app()
