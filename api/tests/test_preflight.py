import httpx

from cerebro.config import AppConfig, ReadinessProfile
from cerebro.ops import preflight


def _serve_jwks(monkeypatch, handler) -> None:
    """Answer the key-set request in process, without reaching auth.ruuf.solar."""
    real_client = httpx.AsyncClient

    def fake_client(**kwargs):
        return real_client(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(preflight.httpx, "AsyncClient", fake_client)


async def test_foundation_preflight_reports_only_safe_categories(monkeypatch) -> None:
    async def ok() -> str:
        return "ok"

    async def storage(_config) -> str:
        return "ok"

    monkeypatch.setattr(preflight, "_database_check", ok)
    monkeypatch.setattr(preflight, "_temporary_storage_check", storage)

    report = await preflight.run_preflight(ReadinessProfile.FOUNDATION, False)

    assert report == {
        "status": "ok",
        "profile": ReadinessProfile.FOUNDATION,
        "live_provider": False,
        "checks": {"database": "ok", "temporary_storage": "ok"},
    }


async def test_preflight_redacts_dependency_exception_details(monkeypatch) -> None:
    async def failure() -> str:
        raise RuntimeError("customer@example.com xoxb-secret")

    async def storage(_config) -> str:
        return "ok"

    monkeypatch.setattr(preflight, "_database_check", failure)
    monkeypatch.setattr(preflight, "_temporary_storage_check", storage)

    report = await preflight.run_preflight(ReadinessProfile.FOUNDATION, False)

    assert report["checks"]["database"] == "failed_RuntimeError"
    assert "customer@example.com" not in str(report)
    assert "xoxb-secret" not in str(report)


async def test_preflight_skips_bank_ingestion_when_the_ingress_is_off(monkeypatch) -> None:
    async def ok() -> str:
        return "ok"

    async def storage(_config) -> str:
        return "ok"

    monkeypatch.setattr(preflight, "_database_check", ok)
    monkeypatch.setattr(preflight, "_temporary_storage_check", storage)

    report = await preflight.run_preflight(ReadinessProfile.FOUNDATION, False)

    assert "bank_ingestion" not in report["checks"]


async def test_preflight_fails_an_enabled_ingress_that_cannot_validate_tokens(
    monkeypatch,
) -> None:
    """An enabled ingress with no issuer to check against must be reported, not skipped."""
    config = AppConfig(bank_ingestion_enabled=True)

    assert await preflight._bank_ingestion_check(config) == "incomplete"


async def test_preflight_reads_the_authentik_key_set(monkeypatch) -> None:
    config = AppConfig(
        bank_ingestion_enabled=True,
        bank_ingestion_issuer="https://auth.ruuf.solar/application/o/cerebro/",
        bank_ingestion_audience="cerebro-bank-movements",
        bank_ingestion_client_id="monolith-bank-movements",
    )
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json={"keys": [{"kid": "k1"}]})

    _serve_jwks(monkeypatch, handler)

    assert await preflight._bank_ingestion_check(config) == "ok"
    assert requested == ["https://auth.ruuf.solar/application/o/cerebro/jwks/"]


async def test_preflight_reports_an_unusable_key_set(monkeypatch) -> None:
    config = AppConfig(
        bank_ingestion_enabled=True,
        bank_ingestion_issuer="https://auth.ruuf.solar/application/o/cerebro/",
        bank_ingestion_audience="cerebro-bank-movements",
        bank_ingestion_client_id="monolith-bank-movements",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    _serve_jwks(monkeypatch, handler)

    assert await preflight._bank_ingestion_check(config) == "jwks_http_404"
