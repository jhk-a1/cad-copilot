"""Schema utilities for the gateway.

`minimal_instance` builds a schema-valid stub from a JSON Schema (the constrained-decoding-safe
subset our contracts use). The mock backend uses it to produce valid offline output for ANY
contract model, so the whole pipeline runs and tests without API keys.

`sanitize_schema` strips JSON-Schema keywords that some providers' constrained decoding rejects
(numeric/length/format constraints), so the same contract schema can be sent to any backend.
"""

from __future__ import annotations

from typing import Any

_UNSUPPORTED_CONSTRAINT_KEYS = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
    "format",
}


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in schema:
        ref = schema["$ref"]  # "#/$defs/Name"
        name = ref.split("/")[-1]
        return root.get("$defs", {}).get(name, {})
    return schema


def minimal_instance(schema: dict[str, Any], root: dict[str, Any] | None = None) -> Any:
    """Build the simplest value that validates against `schema` (subset we use)."""
    root = root or schema
    schema = _resolve(schema, root)

    # nullable union (X | None) renders as anyOf with a null branch
    if "anyOf" in schema:
        branches = schema["anyOf"]
        if any(b.get("type") == "null" for b in branches):
            return None
        return minimal_instance(branches[0], root)
    # pydantic v2 may wrap an enum/$ref field in allOf when it carries a description
    if "allOf" in schema and "enum" not in schema:
        return minimal_instance(schema["allOf"][0], root)
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    if "default" in schema and schema.get("type") not in ("object", "array"):
        return schema["default"]

    t = schema.get("type")
    if t == "object":
        out: dict[str, Any] = {}
        for name, sub in schema.get("properties", {}).items():
            out[name] = minimal_instance(sub, root)
        return out
    if t == "array":
        return []
    if t == "string":
        return ""
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    if t == "null":
        return None
    return None


def sanitize_schema(schema: Any) -> Any:
    """Recursively drop constraint keywords unsupported by provider constrained decoding."""
    if isinstance(schema, dict):
        return {
            k: sanitize_schema(v)
            for k, v in schema.items()
            if k not in _UNSUPPORTED_CONSTRAINT_KEYS
        }
    if isinstance(schema, list):
        return [sanitize_schema(v) for v in schema]
    return schema


def strictify(schema: Any) -> Any:
    """Make a schema safe for Anthropic strict structured output (output_config.format).

    Two rules, applied to every object that defines `properties`:
      * `additionalProperties: false` — required by strict mode (a schema without it 400s).
      * every property is listed in `required` — otherwise the model can DODGE a field by emitting
        `null` (e.g. `parts: null` on an ObjectPlan), which then collapses to a degenerate plan.
        Optional fields stay nullable (their schema is `anyOf:[T, null]`), so "required + nullable"
        still lets the model send null where that is genuinely meant — it just can't omit the key.
    Map-style objects (where `additionalProperties` is already a schema) keep their value schema.
    """
    if isinstance(schema, list):
        return [strictify(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: strictify(v) for k, v in schema.items()}
    if out.get("type") == "object" and "properties" in out:
        if "additionalProperties" not in out:
            out["additionalProperties"] = False
        out["required"] = list(out["properties"].keys())
    return out
