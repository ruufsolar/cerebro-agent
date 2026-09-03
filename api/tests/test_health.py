from httpx import ASGITransport, AsyncClient

from cerebro.main import create_app


async def test_health_reports_agents_sdk_service() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "cerebro-agent",
        "version": "0.1.0",
        "environment": "local",
        "phase": "payment-identification-pilot",
    }


async def test_ready_reports_foundation_dependencies(clean_database: None) -> None:
    del clean_database
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {
        "database": "ok",
        "alembic": "ok",
        "jobs": "ok",
    }
