from cerebro.config import ReadinessProfile
from cerebro.ops import preflight


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
