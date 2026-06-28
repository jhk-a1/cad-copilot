"""Unit tests for the LLM Gateway (M1-W2-BE-03) — exercised offline via the mock backend."""

from __future__ import annotations

import pytest

from ai_server.config import Settings
from ai_server.gateway import (
    LLMGateway,
    Message,
    build_gateway,
    minimal_instance,
    sanitize_schema,
)
from ai_server.gateway.base import estimate_cost
from ai_server.gateway.providers.anthropic_backend import AnthropicBackend
from ai_server.gateway.providers.mock import MockBackend
from ai_server.models import CodeGenResponse, CommandIR, ObjectPlan, PartDrawing

pytestmark = pytest.mark.unit


# --------------------------------------------------------- config selection (trial = Anthropic)


def test_default_config_is_offline_mock() -> None:
    gw = build_gateway(settings=Settings())
    assert all(p["provider"] == "mock" for p in gw.profiles.values())


def test_anthropic_trial_config_is_sonnet_and_has_no_fable() -> None:
    gw = build_gateway(settings=Settings(models_config_path="configs/models.anthropic.json"))
    profiles = gw.profiles
    assert all(p["provider"] == "anthropic" for p in profiles.values())  # Anthropic only
    assert profiles["IR_CODEGEN"]["model"] == "claude-sonnet-4-6"        # Sonnet keeps it cheap
    assert profiles["SAMPLER"]["model"] == "claude-haiku-4-5"            # cheapest for best-of-N
    assert "fable" not in str(profiles).lower()                          # Fable is unavailable


@pytest.mark.parametrize("model", [ObjectPlan, PartDrawing, CommandIR, CodeGenResponse])
def test_minimal_instance_validates_against_contract(model: type) -> None:
    """The mock's schema-minimal output must parse as the real contract model."""
    instance = minimal_instance(model.model_json_schema())
    model.model_validate(instance)  # raises if invalid


def test_strictify_enforces_anthropic_strict_rules() -> None:
    from ai_server.gateway.schema_minimal import strictify

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "parts": {"type": "array", "items": {"type": "object",
                                                 "properties": {"id": {"type": "string"}}}},
        },
    }
    out = strictify(schema)
    assert out["additionalProperties"] is False
    assert set(out["required"]) == {"name", "parts"}          # every property required (no dodging)
    item = out["properties"]["parts"]["items"]
    assert item["additionalProperties"] is False and item["required"] == ["id"]  # recurses


def test_sanitize_strips_unsupported_constraints() -> None:
    schema = {
        "type": "object",
        "properties": {
            "x": {"type": "number", "minimum": 0, "maximum": 1},
            "y": {"type": "string", "maxLength": 5, "pattern": "^a$"},
        },
    }
    out = sanitize_schema(schema)
    assert out["properties"]["x"] == {"type": "number"}
    assert out["properties"]["y"] == {"type": "string"}


def test_estimate_cost_uses_pricing_table() -> None:
    # claude-fable-5: $10/$50 per M tokens
    assert estimate_cost("claude-fable-5", 1_000_000, 1_000_000) == pytest.approx(60.0)
    assert estimate_cost("unknown-model", 1000, 1000) == 0.0


async def test_gateway_returns_n_valid_candidates() -> None:
    gw = build_gateway()  # default config -> all mock
    schema = CommandIR.model_json_schema()
    result = await gw.generate_structured(
        [Message("system", "You generate IR."), Message("user", "make a box")],
        schema,
        profile="IR_CODEGEN",
        n=5,
    )
    assert len(result.candidates) == 5
    assert result.schema_failures == 0
    assert result.provider == "mock"
    assert result.model == "mock-codegen"
    assert result.usage.latency_ms >= 0
    for candidate in result.candidates:
        CommandIR.model_validate(candidate)  # mock output is schema-valid


async def test_scripted_mock_override() -> None:
    backend = MockBackend()
    backend.script("m", {"hello": "world"})
    gw = LLMGateway({"P": {"provider": "mock", "model": "m"}}, {"mock": backend})
    result = await gw.generate_structured([Message("user", "x")], {"type": "object"}, profile="P", n=3)
    assert result.candidates == [{"hello": "world"}] * 3


async def test_unknown_profile_raises() -> None:
    gw = build_gateway()
    with pytest.raises(KeyError, match="Unknown profile"):
        await gw.generate_structured([Message("user", "x")], {}, profile="NOPE")


async def test_unknown_provider_raises() -> None:
    gw = LLMGateway({"P": {"provider": "ghost", "model": "m"}}, {"mock": MockBackend()})
    with pytest.raises(KeyError, match="No backend"):
        await gw.generate_structured([Message("user", "x")], {}, profile="P")


def test_anthropic_backend_builds_a_client_with_a_key() -> None:
    """With the SDK installed and a key, the backend constructs a client (no network call)."""
    backend = AnthropicBackend(api_key="sk-ant-test-not-real")
    client = backend._client_or_raise()
    assert client is not None


def test_default_config_has_all_profiles() -> None:
    gw = build_gateway()
    assert set(gw.profiles) == {"INTENT", "SKETCH", "IR_CODEGEN", "SAMPLER", "VISION_JUDGE"}
