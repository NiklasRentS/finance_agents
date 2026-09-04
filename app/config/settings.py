"""Application configuration loaded exclusively from environment variables."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AppEnv(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class LlmProvider(StrEnum):
    OLLAMA = "ollama"
    NONE = "none"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = AppEnv.LOCAL
    log_level: str = "INFO"
    log_format: str = "console"

    postgres_user: str = "finance"
    postgres_password: SecretStr = SecretStr("change_me_locally")
    postgres_db: str = "finance_agents"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    sec_user_agent: str = "finance_agents/0.1 (contact@example.com)"
    sec_requests_per_second: float = 8.0

    fred_api_key: SecretStr | None = None

    llm_provider: LlmProvider = LlmProvider.OLLAMA
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    llm_timeout_seconds: int = 600
    llm_temperature: float = 0.1

    max_cost_usd_per_run: float = 0.0
    max_external_requests_per_run: int = 400

    cache_dir: Path = Path("data/cache")
    cache_enabled: bool = True

    fmp_api_key: SecretStr | None = None
    finnhub_api_key: SecretStr | None = None
    tiingo_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None

    http_timeout_seconds: float = Field(default=30.0, gt=0)
    http_max_retries: int = Field(default=3, ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """SQLAlchemy connection URL for the Postgres instance."""
        pwd = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{pwd}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cache_path(self) -> Path:
        path = self.cache_dir
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()
