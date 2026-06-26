"""Runtime configuration for QueueStorm Investigator."""
from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed configuration with safe offline defaults."""

    app_name: str = "QueueStorm Investigator"
    environment: str = "production"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"

    # The core service is deliberately rules-first and works with no external key.
    enable_llm: bool = False
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    llm_timeout: float = Field(
        default=8.0,
        gt=0,
        le=15,
        validation_alias=AliasChoices("LLM_TIMEOUT", "LLM_TIMEOUT_SECONDS"),
    )

    # Guardrails for a small, predictable API surface.
    max_complaint_chars: int = Field(default=6000, ge=100, le=20000)
    max_transactions: int = Field(default=25, ge=1, le=100)
    high_value_bdt: float = Field(default=50000.0, ge=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
