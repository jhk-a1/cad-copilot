"""Unit tests for the security middleware (M1-W1-SEC-01)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_server.middleware.security import (
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
)

pytestmark = pytest.mark.unit


def _tiny_app(middleware, **kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(middleware, **kwargs)

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    @app.post("/echo")
    def echo(payload: dict) -> dict:
        return {"ok": True}

    return app


# --------------------------------------------------------------------------- rate limit

def test_rate_limit_blocks_after_limit() -> None:
    client = TestClient(_tiny_app(RateLimitMiddleware, limit=3, window_s=60, enabled=True))
    codes = [client.get("/ping").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_rate_limit_429_carries_retry_after() -> None:
    client = TestClient(_tiny_app(RateLimitMiddleware, limit=1, window_s=60, enabled=True))
    client.get("/ping")
    blocked = client.get("/ping")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.json()["error"]["code"] == "E9001"


def test_rate_limit_disabled_passes_through() -> None:
    client = TestClient(_tiny_app(RateLimitMiddleware, limit=1, window_s=60, enabled=False))
    assert all(client.get("/ping").status_code == 200 for _ in range(5))


# --------------------------------------------------------------------------- size limit

def test_size_limit_rejects_oversized_body() -> None:
    client = TestClient(_tiny_app(RequestSizeLimitMiddleware, max_bytes=50))
    r = client.post("/echo", json={"x": "y" * 500})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "E1003"


def test_size_limit_allows_small_body() -> None:
    client = TestClient(_tiny_app(RequestSizeLimitMiddleware, max_bytes=10_000))
    assert client.post("/echo", json={"x": "y"}).status_code == 200


# --------------------------------------------------------------------------- headers

def test_security_headers_present(client) -> None:
    r = client.get("/health/")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
