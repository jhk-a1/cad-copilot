"""Mock backend — deterministic, schema-valid output with no API key.

Default behavior: return N copies of `minimal_instance(schema)` (valid by construction).
Tests can register canned responses per model via `script()` for deterministic assertions.
This lets the whole pipeline + eval harness run offline until real keys land.
"""

from __future__ import annotations

from typing import Any

from ..base import Usage
from ..schema_minimal import minimal_instance


class MockBackend:
    name = "mock"

    def __init__(self) -> None:
        self._scripts: dict[str, dict[str, Any]] = {}

    def script(self, model: str, response: dict[str, Any]) -> None:
        """Register a canned response for a given model id (test helper)."""
        self._scripts[model] = response

    async def generate(
        self,
        messages,
        schema: dict[str, Any],
        params: dict[str, Any],
        n: int,
        images: list[str] | None,
    ) -> tuple[list[dict[str, Any]], Usage, int]:
        model = params.get("model", "mock")
        if model in self._scripts:
            base = self._scripts[model]
            candidates = [dict(base) for _ in range(n)]
        else:
            candidates = [minimal_instance(schema) for _ in range(n)]
        return candidates, Usage(), 0
