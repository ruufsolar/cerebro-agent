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
        "phase": "screenshot-vision",
    }
