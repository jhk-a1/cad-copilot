"""LLM Gateway core — provider abstraction with structured outputs (M1-W2-BE-03).

Model selection is config, not code: the frontier leaderboard changed three times in the
six months before this was written. `generate_structured` returns N schema-valid candidates
plus telemetry; the verifier (M2) decides which to keep. Anthropic has no native `n`
parameter, so N candidates = N parallel requests (handled per-backend).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# Verified pricing (USD per 1M tokens, input/output) — claude-api skill, June 2026.
# Open-weight + non-Anthropic frontier are rough order-of-magnitude from deep research.
PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-5.2": (5.0, 30.0),
    "gemini-3.1-pro": (2.0, 12.0),
    "deepseek-v4": (0.30, 1.20),
    "minimax-m3": (0.30, 1.20),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = PRICING.get(model)
    if rates is None:
        return 0.0
    return input_tokens / 1e6 * rates[0] + output_tokens / 1e6 * rates[1]


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    def merge(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            latency_ms=max(self.latency_ms, other.latency_ms),
        )


@dataclass
class LLMResult:
    candidates: list[dict[str, Any]]
    usage: Usage
    profile: str
    provider: str
    model: str
    schema_failures: int = 0  # candidates dropped for schema-invalidity (≈0 with constrained decoding)


@runtime_checkable
class Backend(Protocol):
    name: str

    async def generate(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        params: dict[str, Any],
        n: int,
        images: list[str] | None,
    ) -> tuple[list[dict[str, Any]], Usage, int]:
        """Return (candidates, usage, schema_failures)."""
        ...


class LLMGateway:
    """One interface; backends swappable by config.

    profiles: {profile_name: {"provider": str, "model": str, "params": {...}}}
    backends: {provider_name: Backend}
    """

    def __init__(self, profiles: dict[str, dict[str, Any]], backends: dict[str, Backend]) -> None:
        self._profiles = profiles
        self._backends = backends

    @property
    def profiles(self) -> dict[str, dict[str, Any]]:
        return self._profiles

    async def generate_structured(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        *,
        profile: str,
        n: int = 1,
        images: list[str] | None = None,
    ) -> LLMResult:
        if profile not in self._profiles:
            raise KeyError(f"Unknown profile '{profile}'. Known: {sorted(self._profiles)}")
        prof = self._profiles[profile]
        provider = prof["provider"]
        backend = self._backends.get(provider)
        if backend is None:
            raise KeyError(f"No backend registered for provider '{provider}'")

        params = {**prof.get("params", {}), "model": prof["model"]}
        t0 = time.perf_counter()
        candidates, usage, failures = await backend.generate(messages, schema, params, n, images)
        usage.latency_ms = (time.perf_counter() - t0) * 1000
        return LLMResult(
            candidates=candidates,
            usage=usage,
            profile=profile,
            provider=provider,
            model=prof["model"],
            schema_failures=failures,
        )
