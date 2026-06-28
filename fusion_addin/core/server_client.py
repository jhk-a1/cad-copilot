"""Server client — stdlib only (Python 3.14, no native wheels in the add-in).

All network calls live on the Python side (not in palette JS) to sidestep the Qt
web-browser's CORS restrictions. Requests run on a worker thread so the Fusion UI
never blocks.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any


class ServerClient:
    def __init__(self, base_url: str = "http://localhost:8000", timeout_s: int = 110) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def check_connection(self) -> bool:
        try:
            return self._request("GET", "/health/").get("status") == "healthy"
        except Exception:
            return False

    def parse_intent(self, text: str, context: dict | None = None) -> dict[str, Any]:
        return self._request("POST", "/api/intent/parse", {"text": text, "context": context})

    def generate_sketch(self, intent: dict, feedback: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST", "/api/sketch/generate", {"intent": intent, "user_feedback": feedback}
        )

    def generate_code(self, intent: dict, dimensions: dict) -> dict[str, Any]:
        return self._request(
            "POST", "/api/codegen/generate", {"intent": intent, "dimensions": dimensions}
        )

    def _request(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "X-API-Version": "2.0.0"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Cannot reach AI server at {self.base_url}: {e.reason}") from e

    def request_async(
        self,
        fn: Callable[[], dict[str, Any]],
        on_done: Callable[[dict[str, Any] | None, Exception | None], None],
    ) -> None:
        """Run a request off the UI thread; deliver result/error to on_done."""

        def _worker() -> None:
            try:
                on_done(fn(), None)
            except Exception as exc:  # delivered to caller, never crashes Fusion
                on_done(None, exc)

        threading.Thread(target=_worker, daemon=True).start()
