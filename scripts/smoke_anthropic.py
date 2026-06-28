"""Live smoke test for the Anthropic gateway (run after putting your key in ai_server/.env).

    ./.venv/Scripts/python.exe scripts/smoke_anthropic.py

Makes ONE small real call (a few hundred tokens, a fraction of a cent) asking Claude Sonnet for a
schema-valid JSON object. Confirms the key works AND that structured output works end-to-end — the
one thing the Anthropic backend had never exercised live. Prints tokens + cost, or a clear error.
"""

from __future__ import annotations

import asyncio

from ai_server.config import Settings
from ai_server.gateway.base import Message
from ai_server.gateway.registry import build_gateway


async def main() -> int:
    settings = Settings()
    key = settings.anthropic_api_key
    if not key or key.startswith("PASTE_"):
        print("[FAIL] No key found. Paste your real key into ai_server/.env "
              "(ANTHROPIC_API_KEY=sk-ant-...) and re-run.")
        return 1

    gateway = build_gateway(settings=settings)
    profile = gateway.profiles["INTENT"]
    print(f"profile INTENT -> {profile['provider']} / {profile['model']}")
    print(f"key -> {key[:7]}...{key[-4:]} (length {len(key)})")

    schema = {
        "type": "object",
        "properties": {"shape": {"type": "string"}, "sides": {"type": "integer"}},
        "required": ["shape", "sides"],
    }
    try:
        result = await gateway.generate_structured(
            [
                Message("system", "You output only the requested JSON object."),
                Message("user", "Describe a triangle: its shape name and number of sides."),
            ],
            schema,
            profile="INTENT",
            n=1,
        )
    except Exception as exc:  # noqa: BLE001 - surface the raw error for first-run debugging
        print(f"[FAIL] LIVE CALL FAILED: {type(exc).__name__}: {exc}")
        print("  (If this is a 4xx about request shape, the backend needs a tweak vs the "
              "current Anthropic API -- that's the thing this test exists to catch.)")
        return 1

    u = result.usage
    print(f"tokens in/out: {u.input_tokens}/{u.output_tokens} | cost ${u.cost_usd:.6f} "
          f"| latency {u.latency_ms:.0f} ms")
    if result.candidates and isinstance(result.candidates[0], dict):
        print(f"[OK] STRUCTURED OUTPUT OK -- candidate: {result.candidates[0]}")
        return 0
    print(f"[FAIL] no valid JSON candidate (schema_failures={result.schema_failures})")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
