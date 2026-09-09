from cerebro.config import AppConfig, GlobalMode, ReadinessProfile


def test_config_is_safe_by_default() -> None:
    config = AppConfig()

    assert config.global_mode is GlobalMode.OFF
    assert config.payment_writes_enabled is False
    assert config.hold_writes_enabled is False
    assert config.external_tracing_enabled is False
    assert config.live_agent_ready is False
    assert config.azure_agent_ready is False
    assert config.azure_agent_partially_configured is False
    assert config.slack_ready is False
    assert config.azure_deployment_main == "gpt-5-6-sol"
    assert config.azure_deployment_small == "gpt-5-6-sol"
    assert config.router_reasoning_effort == "low"
    assert config.general_max_words == 180
    assert config.readiness_profile is ReadinessProfile.FOUNDATION
    assert config.worker_concurrency == 2
    assert config.runtime_heartbeat_seconds == 15
    assert config.runtime_stale_seconds == 45


def test_slack_shell_readiness_only_requires_slack_tokens() -> None:
    config = AppConfig(slack_app_token="xapp-test", slack_bot_token="xoxb-test")

    assert config.slack_ready is True
    assert config.live_agent_ready is False


def test_azure_readiness_requires_endpoint_key_and_deployment() -> None:
    partial = AppConfig(azure_openai_endpoint="https://example.test")
    ready = AppConfig(
        azure_openai_endpoint="https://example.test",
        azure_openai_api_key="secret",
    )

    assert partial.azure_agent_partially_configured is True
    assert partial.azure_agent_ready is False
    assert ready.azure_agent_partially_configured is False
    assert ready.azure_agent_ready is True


def test_pilot_configuration_rejects_an_empty_azure_deployment() -> None:
    config = AppConfig(
        slack_app_token="xapp-test",
        slack_bot_token="xoxb-test",
        azure_openai_endpoint="https://example.test",
        azure_openai_api_key="secret",
        azure_deployment_main="",
        read_replica_url="postgresql://readonly@replica.invalid/monolith?sslmode=require",
    )

    assert config.live_agent_ready is False
    assert config.pilot_configuration_ready is False


def test_pilot_configuration_rejects_an_empty_router_deployment() -> None:
    config = AppConfig(
        slack_app_token="xapp-test",
        slack_bot_token="xoxb-test",
        azure_openai_endpoint="https://example.test",
        azure_openai_api_key="secret",
        azure_deployment_small="",
        read_replica_url="postgresql://readonly@replica.invalid/monolith?sslmode=require",
    )

    assert config.azure_agent_ready is False
    assert config.live_agent_ready is False
    assert config.pilot_configuration_ready is False


def test_database_driver_urls_are_derived() -> None:
    config = AppConfig(database_url="postgresql://user:secret@db.example/cerebro")

    assert config.sqlalchemy_url.startswith("postgresql+asyncpg://")
    assert config.alembic_url.startswith("postgresql+psycopg://")


def test_bank_ingestion_is_off_by_default() -> None:
    config = AppConfig()

    assert config.bank_ingestion_enabled is False
    assert config.bank_ingestion_ready is False
    assert config.bank_ingestion_jwks_uri == ""


def test_bank_ingestion_derives_the_authentik_key_set_from_the_issuer() -> None:
    config = AppConfig(
        bank_ingestion_enabled=True,
        bank_ingestion_issuer="https://auth.ruuf.solar/application/o/monolith/",
        bank_ingestion_audience="cerebro-bank-movements",
        bank_ingestion_client_id="monolith-bank-movements",
    )

    assert config.bank_ingestion_jwks_uri == (
        "https://auth.ruuf.solar/application/o/monolith/jwks/"
    )
    assert config.bank_ingestion_ready is True


def test_bank_ingestion_key_set_can_be_overridden() -> None:
    config = AppConfig(
        bank_ingestion_enabled=True,
        bank_ingestion_issuer="https://auth.ruuf.solar/application/o/monolith/",
        bank_ingestion_audience="cerebro-bank-movements",
        bank_ingestion_client_id="monolith-bank-movements",
        bank_ingestion_jwks_url="https://auth.ruuf.solar/keys.json",
    )

    assert config.bank_ingestion_jwks_uri == "https://auth.ruuf.solar/keys.json"


def test_bank_ingestion_is_not_ready_without_something_to_validate_against() -> None:
    """The enabled flag alone must never be enough: an endpoint that served requests with
    no issuer, audience, or authorized client would be an unauthenticated payment endpoint."""
    complete = {
        "bank_ingestion_enabled": True,
        "bank_ingestion_issuer": "https://auth.ruuf.solar/application/o/monolith/",
        "bank_ingestion_audience": "cerebro-bank-movements",
        "bank_ingestion_client_id": "monolith-bank-movements",
    }

    assert AppConfig(**complete).bank_ingestion_ready is True
    for missing in ("bank_ingestion_issuer", "bank_ingestion_audience", "bank_ingestion_client_id"):
        assert AppConfig(**{**complete, missing: ""}).bank_ingestion_ready is False
