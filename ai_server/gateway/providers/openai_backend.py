"""OpenAI-compatible backend — structured outputs via response_format json_schema.

Serves both the OpenAI provider and the SAMPLER profile's open-weight endpoints (set
`base_url` to a DeepSeek/MiniMax-class OpenAI-compatible server). UNTESTED LIVE (no keys yet).
OpenAI supports native `n`, so one request yields N candidates.

Note: OpenAI strict json_schema requires every property in `required`; our contract has
nullable-optional fields, so strict mode may need schema massaging (a documented follow-up).
"""

from __future__ import annotations

import json
from typing import Any

from ..base import Message, Usage, estimate_cost
from ..schema_minimal import sanitize_schema


class OpenAIBackend:
    name = "openai"

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client: Any = None

    def _client_or_raise(self) -> Any:
        if self._client is None:
            try:
                import openai  # lazy, optional dep
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "OpenAI backend selected but the 'openai' package is not installed."
                ) from e
            kwargs: dict[str, Any] = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = openai.AsyncOpenAI(**kwargs)
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

        msgs: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user" and images:
                content: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
                for img in images:
                    content.append(
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}
                    )
                msgs.append({"role": "user", "content": content})
            else:
                msgs.append({"role": m.role, "content": m.content})

        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "structured_output", "schema": sanitize_schema(schema), "strict": True},
        }
        kwargs: dict[str, Any] = {"model": model, "messages": msgs, "response_format": response_format, "n": n}
        if "temperature" in params:
            kwargs["temperature"] = params["temperature"]

        resp = await client.chat.completions.create(**kwargs)
        candidates: list[dict[str, Any]] = []
        failures = 0
        for choice in resp.choices:
            try:
                candidates.append(json.loads(choice.message.content))
            except (json.JSONDecodeError, TypeError):
                failures += 1
        usage = Usage(
            input_tokens=getattr(resp.usage, "prompt_tokens", 0),
            output_tokens=getattr(resp.usage, "completion_tokens", 0),
        )
        usage.cost_usd = estimate_cost(model, usage.input_tokens, usage.output_tokens)
        return candidates, usage, failures
