"""Environment configuration loader.

Centralises access to environment variables defined in the PRD.
Values are loaded once at import time; tests can monkeypatch
`app.config.settings` to override behaviour.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env if present (no-op in production where env vars are injected).
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH, override=False)


@dataclass
class Settings:
    port: int
    enable_llm: bool
    gemini_api_key: str
    llm_timeout: float
    log_level: str

    @property
    def llm_enabled(self) -> bool:
        """LLM is only active if both flag and key are set."""
        return self.enable_llm and bool(self.gemini_api_key.strip())


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    return Settings(
        port=int(os.getenv("PORT", "8000")),
        enable_llm=_bool(os.getenv("ENABLE_LLM"), True),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        llm_timeout=float(os.getenv("LLM_TIMEOUT", "8")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )


settings = load_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("queuestorm")
