"""Google Gemini backend — structured output via response_schema / JSON mime type.

UNTESTED LIVE (no keys yet). Uses the google-genai async client. Gemini has no native `n`,
so N candidates = N parallel requests. Best vision-per-dollar -> default VISION_JUDGE choice.
Cap context to keep cost in the <=200K tier (pricing doubles above; verified June 2026).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ..base import Message, Usage, estimate_cost
from ..schema_minimal import sanitize_schema


class GoogleBackend:
    name = "google"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._client: Any = None

    def _client_or_raise(self) -> Any:
        if self._client is None:
            try:
                from google import genai  # lazy, optional dep
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "Google backend selected but the 'google-genai' package is not installed."
                ) from e
            self._client = genai.Client(api_key=self._api_key) if self._api_key else genai.Client()
        return self._client

    async def generate(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        params: dict[str, Any],
        n: int,
        images: list[str] | None,
    ) -> tuple[list[dict[str, Any]], Usage, int]:
        client = self._client_or_raise()
        model = params["model"]

        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        user_text = "\n\n".join(m.content for m in messages if m.role == "user")
        parts: list[Any] = [user_text]
        for img in images or []:
            import base64

            parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64decode(img)}})

        config: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": sanitize_schema(schema),
        }
        if system:
            config["system_instruction"] = system
        if "temperature" in params:
            config["temperature"] = params["temperature"]

        async def _one() -> tuple[dict[str, Any] | None, Usage]:
            resp = await client.aio.models.generate_content(model=model, contents=parts, config=config)
            meta = getattr(resp, "usage_metadata", None)
            usage = Usage(
                input_tokens=getattr(meta, "prompt_token_count", 0) if meta else 0,
                output_tokens=getattr(meta, "candidates_token_count", 0) if meta else 0,
            )
            usage.cost_usd = estimate_cost(model, usage.input_tokens, usage.output_tokens)
            try:
                return json.loads(resp.text), usage
            except (json.JSONDecodeError, AttributeError, TypeError):
                return None, usage

        results = await asyncio.gather(*[_one() for _ in range(n)])
        candidates: list[dict[str, Any]] = []
        total = Usage()
        failures = 0
        for cand, usage in results:
            total = total.merge(usage)
            if cand is None:
                failures += 1
            else:
                candidates.append(cand)
        return candidates, total, failures
