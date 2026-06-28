"""Anthropic backend — structured outputs via output_config.format (verified June 2026).

Wired and ready; UNTESTED LIVE (built before API keys were available — see M1-W1-OPS-01).
Shapes verified against the claude-api reference:
  * Structured output: output_config={"format": {"type": "json_schema", "schema": <subset>}}.
  * Anthropic has no native `n` — N candidates = N parallel requests (asyncio.gather).
  * Claude Fable 5: thinking always on (omit `thinking`); temperature/top_p/top_k 400 if sent;
    refusals are opt-in to recover via server-side fallbacks -> we enable fallback to Opus 4.8.
The SDK strips unsupported schema constraints client-side; we also sanitize_schema defensively.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ..base import Message, Usage, estimate_cost
from ..schema_minimal import sanitize_schema, strictify

_FALLBACK_BETA = "server-side-fallback-2026-06-01"
_FALLBACK_MODEL = "claude-opus-4-8"


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text — tolerant of code fences / stray prose (non-strict mode).

    Strict structured output returns clean JSON; non-strict generation (used for schemas strict mode
    can't carry, e.g. the open-dict Command IR) may wrap it. Take the outermost {...}.
    """
    s = text.strip()
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        s = s[start : end + 1]
    return json.loads(s)


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._client: Any = None

    def _client_or_raise(self) -> Any:
        if self._client is None:
            try:
                import anthropic  # lazy — keeps add-in/server import light, optional dep
            except ImportError as e:  # pragma: no cover - exercised only without the dep
                raise RuntimeError(
                    "Anthropic backend selected but the 'anthropic' package is not installed. "
                    "pip install anthropic, or point the profile at the 'mock' provider."
                ) from e
            self._client = (
                anthropic.AsyncAnthropic(api_key=self._api_key)
                if self._api_key
                else anthropic.AsyncAnthropic()
            )
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
        is_fable = model.startswith("claude-fable")

        # Strict structured output requires additionalProperties:false everywhere, so it CANNOT carry
        # schemas with open dicts (the Command IR). Such profiles set structured:false -> we ask for
        # JSON in the prompt and parse it (the IR Validator is the real safety net downstream).
        structured = params.get("structured", True)

        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        user_blocks: list[dict[str, Any]] = []
        for img in images or []:
            user_blocks.append(
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}}
            )
        user_text = "\n\n".join(m.content for m in messages if m.role == "user")
        user_blocks.append({"type": "text", "text": user_text})

        request: dict[str, Any] = {
            "model": model,
            "max_tokens": params.get("max_tokens", 8192),
            "messages": [{"role": "user", "content": user_blocks}],
        }
        if structured:
            request["output_config"] = {
                "format": {"type": "json_schema", "schema": strictify(sanitize_schema(schema))}
            }
        else:
            schema_hint = json.dumps(sanitize_schema(schema), separators=(",", ":"))
            system = (system or "") + (
                "\n\nRespond with ONLY one valid JSON object — no markdown, no code fences, no prose. "
                "It must conform to this JSON Schema:\n" + schema_hint
            )
        if system:
            request["system"] = system
        if "effort" in params:
            request.setdefault("output_config", {})["effort"] = params["effort"]
        # temperature is rejected on Fable 5 / Opus 4.8 / 4.7 — only send to models that accept it.
        if "temperature" in params and not is_fable and not model.startswith("claude-opus-4"):
            request["temperature"] = params["temperature"]
        if is_fable:
            request["betas"] = [_FALLBACK_BETA]
            request["fallbacks"] = [{"model": _FALLBACK_MODEL}]

        async def _one() -> tuple[dict[str, Any] | None, Usage]:
            create = client.beta.messages.create if is_fable else client.messages.create
            resp = await create(**request)
            usage = Usage(
                input_tokens=getattr(resp.usage, "input_tokens", 0),
                output_tokens=getattr(resp.usage, "output_tokens", 0),
                cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            )
            usage.cost_usd = estimate_cost(model, usage.input_tokens, usage.output_tokens)
            if getattr(resp, "stop_reason", None) == "refusal":
                return None, usage
            text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
            if text is None:
                return None, usage
            try:
                return _extract_json(text), usage
            except (json.JSONDecodeError, ValueError):
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
