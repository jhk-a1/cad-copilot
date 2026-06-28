"""Unit tests for the IntentService (M1-W3-BE-05).

Two paths matter: the deterministic offline fallback (mock provider) must keep the pipeline
working without keys, and the real-gateway path must validate + family-gate whatever the model
returns. The real path is exercised by pointing the INTENT profile at a scripted MockBackend
under a non-mock provider name — no API key, fully deterministic.
"""

from __future__ import annotations

import pytest

from ai_server.gateway import build_gateway
from ai_server.gateway.base import LLMGateway
from ai_server.gateway.providers.mock import MockBackend
from ai_server.models import ComplexityClass
from ai_server.services.intent import IntentService

pytestmark = pytest.mark.unit

_MODEL = "test-intent"


def gateway_returning(plan: dict) -> LLMGateway:
    """A gateway whose INTENT profile points at a scripted mock under a real-looking provider."""
    backend = MockBackend()
    backend.script(_MODEL, plan)
    profiles = {"INTENT": {"provider": "anthropic", "model": _MODEL, "params": {}}}
    return LLMGateway(profiles, {"anthropic": backend, "mock": MockBackend()})


def valid_plan(**over) -> dict:
    plan = {
        "object_name": "widget",
        "summary": "a small test widget",
        "parts": [
            {"id": "body", "name": "Body", "family": "box", "object_type": "prismatic",
             "features": ["holes"], "operations_likely": ["sketch", "extrude"], "count": 1},
        ],
        "complexity_class": "in_scope",
        "clarifications_needed": [],
        "assembly_notes": None,
        "confidence": 0.8,
    }
    plan.update(over)
    return plan


# --------------------------------------------------------------------------- offline fallback


async def test_offline_provider_uses_deterministic_templates() -> None:
    # default config -> INTENT provider is "mock" -> delegate to the placeholder planner
    svc = IntentService(build_gateway())
    plan = await svc.plan("a phone stand")
    assert plan.object_name == "phone stand"
    assert {p.id for p in plan.parts} == {"base", "upright"}
    assert plan.complexity_class is ComplexityClass.IN_SCOPE


# --------------------------------------------------------------------------- real gateway path


async def test_real_provider_returns_model_plan() -> None:
    svc = IntentService(gateway_returning(valid_plan()))
    plan = await svc.plan("a widget with a box body")
    assert plan.object_name == "widget"
    assert [p.family for p in plan.parts] == ["box"]
    assert plan.complexity_class is ComplexityClass.IN_SCOPE


async def test_novel_family_parts_are_kept_for_llm_codegen() -> None:
    # a buildable box AND a novel 'gear' -> BOTH kept (gear builds via LLM codegen, not dropped)
    plan_dict = valid_plan(complexity_class="decompose", parts=[
        {"id": "plate", "name": "Plate", "family": "box", "object_type": "prismatic",
         "features": [], "operations_likely": ["sketch", "extrude"], "count": 1},
        {"id": "gear", "name": "Gear", "family": "gear", "object_type": "gear",
         "features": [], "operations_likely": [], "count": 1},
    ])
    svc = IntentService(gateway_returning(plan_dict))
    plan = await svc.plan("a geared plate")
    assert [p.family for p in plan.parts] == ["box", "gear"]  # nothing dropped
    assert plan.complexity_class is ComplexityClass.DECOMPOSE


async def test_no_parts_becomes_out_of_scope() -> None:
    # only an empty plan (not a physical object) is refused now
    svc = IntentService(gateway_returning(valid_plan(parts=[], complexity_class="in_scope")))
    plan = await svc.plan("the meaning of life")
    assert plan.parts == []
    assert plan.complexity_class is ComplexityClass.OUT_OF_SCOPE
    assert plan.clarifications_needed


async def test_family_synonym_is_normalized_to_canonical() -> None:
    # the model often uses a synonym; the gate should map it onto a supported family, not drop it
    plan_dict = valid_plan(parts=[
        {"id": "body", "name": "Body", "family": "rectangular_prism", "object_type": "prismatic",
         "features": [], "operations_likely": [], "count": 1},
    ])
    svc = IntentService(gateway_returning(plan_dict))
    plan = await svc.plan("a rectangular block")
    assert [p.family for p in plan.parts] == ["box"]  # normalized, not dropped
    assert plan.complexity_class is ComplexityClass.IN_SCOPE


async def test_feature_synonyms_are_normalized() -> None:
    plan_dict = valid_plan(parts=[
        {"id": "body", "name": "Body", "family": "box", "object_type": "prismatic",
         "features": ["mounting_holes", "rounded_edges"], "operations_likely": [], "count": 1},
    ])
    svc = IntentService(gateway_returning(plan_dict))
    plan = await svc.plan("a box with bolt holes and rounded corners")
    assert plan.parts[0].features == ["holes", "filleted_edges"]  # canonical names downstream uses


async def test_in_scope_with_no_parts_is_made_out_of_scope() -> None:
    # the model sometimes returns in_scope with an empty parts list — never return that contradiction
    svc = IntentService(gateway_returning(valid_plan(parts=[], complexity_class="in_scope")))
    plan = await svc.plan("a widget")
    assert plan.parts == []
    assert plan.complexity_class is ComplexityClass.OUT_OF_SCOPE
    assert plan.clarifications_needed


async def test_schema_invalid_candidate_falls_back() -> None:
    # missing required fields -> ObjectPlan.model_validate raises -> deterministic fallback
    svc = IntentService(gateway_returning({"object_name": "broken"}))
    plan = await svc.plan("a box")
    assert plan.object_name == "box"  # came from the placeholder planner, not the model
    assert plan.parts and plan.parts[0].family == "box"
