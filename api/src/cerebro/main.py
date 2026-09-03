from fastapi import FastAPI
from fastapi.responses import JSONResponse

from cerebro import __version__
from cerebro.config import get_config
from cerebro.observability import configure_logging
from cerebro.ops.readiness import readiness_report


def create_app() -> FastAPI:
    config = get_config()
    configure_logging("web", config)
    app = FastAPI(title="cerebro-agent", version=__version__)

    @app.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "cerebro-agent",
            "version": __version__,
            "environment": config.environment,
            "phase": "payment-identification-pilot",
        }

    @app.get("/ready", tags=["operations"])
    async def ready() -> JSONResponse:
        is_ready, report = await readiness_report(config)
        return JSONResponse(report, status_code=200 if is_ready else 503)

    return app


app = create_app()
