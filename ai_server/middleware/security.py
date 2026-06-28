"""Security middleware (M1-W1-SEC-01) — guards before the server faces real users.

Three layers, cheap and in-process (a single-process trial; not a distributed limiter):
  * RequestSizeLimitMiddleware — reject oversized bodies early (Content-Length) -> 413.
  * RateLimitMiddleware — fixed-window per client IP -> 429 with Retry-After. Disabled in tests.
  * SecurityHeadersMiddleware — conservative response headers.
Refusals/errors use the typed error envelope (models/errors.py) so clients get a stable shape.
"""

from __future__ import annotations

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..models.errors import make_error

# Liveness/meta endpoints are never rate limited (health checks, root).
_EXEMPT_PATHS = {"/", "/health", "/health/"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                size = None
            if size is not None and size > self._max_bytes:
                err = make_error("E1003", f"Request body exceeds the {self._max_bytes}-byte limit.")
                return JSONResponse(status_code=413, content=err.model_dump())
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window-ish per-client limiter (sliding list of hit timestamps)."""

    def __init__(self, app, limit: int, window_s: int, enabled: bool = True) -> None:
        super().__init__(app)
        self._limit = limit
        self._window = window_s
        self._enabled = enabled
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if not self._enabled or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self._window
        recent = [t for t in self._hits[client] if t > cutoff]

        if len(recent) >= self._limit:
            retry_after = max(1, int(self._window - (now - recent[0])) + 1)
            err = make_error("E9001", "Rate limit exceeded — slow down and retry shortly.")
            err.error.retry_after = retry_after
            return JSONResponse(status_code=429, content=err.model_dump(),
                                headers={"Retry-After": str(retry_after)})

        recent.append(now)
        self._hits[client] = recent
        return await call_next(request)
