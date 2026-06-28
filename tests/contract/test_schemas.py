"""Contract tests: golden JSON round-trips + constrained-decoding subset lint (v2.1.0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_server.models import (
    CodeGenResponse,
    CommandIR,
    ObjectPlan,
    ObjectRequest,
    PartDrawing,
    Refusal,
)

GOLDEN = Path(__file__).parent / "golden"

# JSON-Schema keywords NOT supported by frontier-model constrained decoding.
# (anyOf is allowed — it's how nullable fields render.)
DISALLOWED_KEYWORDS = {
    "patternProperties",
    "propertyNames",
    "if",
    "then",
    "else",
    "$dynamicRef",
    "$recursiveRef",
    "dependentSchemas",
}


@pytest.mark.contract
@pytest.mark.parametrize(
    ("filename", "model"),
    [
        ("object_request.json", ObjectRequest),
        ("object_plan.json", ObjectPlan),
        ("refusal.json", Refusal),
    ],
)
def test_golden_roundtrip(filename: str, model: type) -> None:
    golden = json.loads((GOLDEN / filename).read_text())
    obj = model.model_validate(golden)
    assert obj.model_dump(mode="json") == golden


@pytest.mark.contract
def test_intent_output_schema_is_anthropic_strict_clean() -> None:
    """Regression guard: the planning-stage structured-output schema must be Anthropic-strict-clean —
    EVERY object node locked to additionalProperties:false. An open dict (dict[str,X]) anywhere in
    ObjectPlan makes the live `/api/object/plan` call 400 and silently fall back to the keyword
    planner (which refuses real objects). Caught here, not in production."""
    from ai_server.gateway import sanitize_schema
    from ai_server.gateway.schema_minimal import strictify

    schema = strictify(sanitize_schema(ObjectPlan.model_json_schema()))
    offenders: list[str] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and node.get("additionalProperties") is not False:
                offenders.append(path)
            for k, v in node.items():
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(schema, "root")
    assert offenders == [], f"open-dict / unlocked object nodes break strict structured output: {offenders}"


def _walk(schema: object, found: set[str]) -> None:
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in DISALLOWED_KEYWORDS:
                found.add(key)
            _walk(value, found)
    elif isinstance(schema, list):
        for item in schema:
            _walk(item, found)


@pytest.mark.contract
@pytest.mark.parametrize(
    "model",
    [ObjectPlan, PartDrawing, CommandIR, CodeGenResponse, Refusal],
)
def test_schema_in_supported_subset(model: type) -> None:
    """Generation schemas must stay inside the constrained-decoding-safe subset."""
    schema = model.model_json_schema()
    found: set[str] = set()
    _walk(schema, found)
    assert not found, f"{model.__name__} uses unsupported JSON-Schema keywords: {found}"


@pytest.mark.contract
def test_command_ir_units_are_mm() -> None:
    """The IR contract guarantees millimetres; the executor converts to cm."""
    assert CommandIR(commands=[]).units == "mm"
