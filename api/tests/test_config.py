from cerebro.config import AppConfig, GlobalMode


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


def test_database_driver_urls_are_derived() -> None:
    config = AppConfig(database_url="postgresql://user:secret@db.example/cerebro")

    assert config.sqlalchemy_url.startswith("postgresql+asyncpg://")
    assert config.alembic_url.startswith("postgresql+psycopg://")
