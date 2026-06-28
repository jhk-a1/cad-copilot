"""Shared test fixtures.

Tests are offline and deterministic: they must NOT pick up a developer's live `ai_server/.env`
(which may point the gateway at a real Anthropic key). Force the mock gateway here — an env var
set in the process overrides the `.env` file in pydantic-settings — and clear the cached settings.
"""

from __future__ import annotations

import os

os.environ["MODELS_CONFIG_PATH"] = ""  # -> offline mock config, never the live Anthropic one
os.environ["ANTHROPIC_API_KEY"] = ""   # no real key in tests, regardless of .env
os.environ["ENVIRONMENT"] = "test"     # disables the rate limiter so the suite isn't throttled

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ai_server.config import get_settings  # noqa: E402
from ai_server.main import app  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
