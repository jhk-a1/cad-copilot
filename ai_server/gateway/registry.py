"""Build an LLMGateway from configs/models.json + the server settings.

Backends are constructed once and shared. Provider keys come from Settings (env). Switching a
profile's model is a one-line edit in configs/models.json — no code change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from .base import Backend, LLMGateway
from .providers.anthropic_backend import AnthropicBackend
from .providers.google_backend import GoogleBackend
from .providers.mock import MockBackend
from .providers.openai_backend import OpenAIBackend

_DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "models.json"


def load_profiles(path: Path | None = None) -> dict[str, dict[str, Any]]:
    data = json.loads((path or _DEFAULT_CONFIG).read_text())
    return data["profiles"]


def build_backends(settings: Settings | None = None) -> dict[str, Backend]:
    s = settings or get_settings()
    return {
        "mock": MockBackend(),
        "anthropic": AnthropicBackend(api_key=s.anthropic_api_key or None),
        "openai": OpenAIBackend(api_key=s.openai_api_key or None),
        "google": GoogleBackend(api_key=s.google_api_key or None),
    }


def _resolve_config_path(config_path: Path | None, settings: Settings) -> Path | None:
    """Explicit arg wins; else the MODELS_CONFIG_PATH setting (relative to the repo root)."""
    if config_path is not None:
        return config_path
    if settings.models_config_path:
        p = Path(settings.models_config_path)
        return p if p.is_absolute() else _DEFAULT_CONFIG.parent.parent / p
    return None  # -> _DEFAULT_CONFIG (offline mock)


def build_gateway(
    config_path: Path | None = None, settings: Settings | None = None
) -> LLMGateway:
    s = settings or get_settings()
    return LLMGateway(load_profiles(_resolve_config_path(config_path, s)), build_backends(s))
