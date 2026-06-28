"""Server configuration with DEV/PROD separation (M1-W1-SEC-01 foundation)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Load ai_server/.env regardless of the process working directory (server runs from repo root).
_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Environment(StrEnum):
    DEV = "development"
    PROD = "production"
    TEST = "test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    environment: Environment = Environment.DEV

    # CORS — restricted by environment. PROD must be configured explicitly.
    cors_origins_dev: list[str] = ["http://localhost", "http://127.0.0.1", "null"]
    cors_origins_prod: list[str] = []

    # Limits / timeouts
    rate_limit_requests: int = 100
    rate_limit_window_s: int = 60
    max_request_size_mb: int = 10
    request_timeout_s: int = 30

    # LLM provider keys. Trial uses ANTHROPIC only (founder decision 2026-06-12).
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""

    # Which gateway profile config to load. Empty -> configs/models.json (offline mock default).
    # Set MODELS_CONFIG_PATH=configs/models.anthropic.json to go live on Claude Sonnet.
    models_config_path: str = ""

    @property
    def cors_origins(self) -> list[str]:
        if self.environment == Environment.PROD:
            if not self.cors_origins_prod:
                raise ValueError("CORS origins must be configured for production")
            return self.cors_origins_prod
        return self.cors_origins_dev


@lru_cache
def get_settings() -> Settings:
    return Settings()
