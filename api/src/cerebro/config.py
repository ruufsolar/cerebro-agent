from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GlobalMode(StrEnum):
    """Highest level of autonomy allowed by the running process."""

    OFF = "off"
    SHADOW = "shadow"
    REVIEW = "review"
    APPLY = "apply"


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CEREBRO_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql://cerebro@127.0.0.1:5432/cerebro"
    read_replica_url: str = ""
    allow_non_replica_readonly_db: bool = False
    sql_max_connections: int = Field(default=5, ge=1, le=10)
    sql_max_output_bytes: int = Field(default=65_536, ge=4_096, le=262_144)

    slack_bot_token: str = ""
    slack_app_token: str = ""

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    # These are Azure deployment names, not necessarily catalog model identifiers.
    azure_deployment_main: str = "gpt-5-6-sol"
    azure_deployment_small: str = "gpt-5-6-luna"
    azure_openai_use_responses: bool = True
    azure_reasoning_effort: str = "medium"
    azure_max_output_tokens: int = Field(default=4_096, ge=256, le=32_768)

    global_mode: GlobalMode = GlobalMode.OFF
    payment_writes_enabled: bool = False
    hold_writes_enabled: bool = False

    max_agent_turns: int = Field(default=8, ge=1, le=30)
    max_tool_calls: int = Field(default=20, ge=1, le=100)
    agent_timeout_seconds: int = Field(default=180, ge=10, le=900)
    sql_statement_timeout_seconds: int = Field(default=15, ge=1, le=60)
    sql_max_rows: int = Field(default=200, ge=1, le=1_000)
    max_images: int = Field(default=4, ge=1, le=10)
    max_image_bytes: int = Field(default=8 * 1024 * 1024, ge=1_024)
    slack_delivery_max_attempts: int = Field(default=3, ge=1, le=10)

    crm_finops_base_url: str = "https://tutu.ruuf.cl/account-receivables/crm-finops"
    knowledge_dir: str = "../knowledge"
    posthog_api_key: str = ""
    posthog_host: str = "https://us.i.posthog.com"
    external_tracing_enabled: bool = False
    public_url: str = "http://localhost:8000"

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    @property
    def alembic_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    @property
    def replica_ready(self) -> bool:
        return bool(self.read_replica_url)

    @property
    def procrastinate_conninfo(self) -> str:
        return self.database_url

    @property
    def live_agent_ready(self) -> bool:
        return all(
            (
                self.slack_bot_token,
                self.slack_app_token,
                self.azure_openai_endpoint,
                self.azure_openai_api_key,
                self.read_replica_url,
            )
        )

    @property
    def azure_agent_ready(self) -> bool:
        return bool(
            self.azure_openai_endpoint and self.azure_openai_api_key and self.azure_deployment_main
        )

    @property
    def azure_agent_partially_configured(self) -> bool:
        values = (self.azure_openai_endpoint, self.azure_openai_api_key)
        return any(values) and not all(values)

    @property
    def slack_ready(self) -> bool:
        return bool(self.slack_bot_token and self.slack_app_token)


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
