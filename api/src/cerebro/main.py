from fastapi import FastAPI

from cerebro import __version__
from cerebro.config import get_config


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(title="cerebro-agent", version=__version__)

    @app.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "cerebro-agent",
            "version": __version__,
            "environment": config.environment,
            "phase": "screenshot-vision",
        }

    return app


app = create_app()
