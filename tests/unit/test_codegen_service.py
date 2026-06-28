"""Unit tests for the CodeGenService (build-anything path).

Known families use exact templates; novel families go to the LLM with a validator-feedback retry
loop. The LLM path is exercised offline by scripting a mock backend under a non-mock provider.
"""

from __future__ import annotations

import pytest

from ai_server.config import Settings
from ai_server.gateway import build_gateway
from ai_server.gateway.base import LLMGateway
from ai_server.gateway.providers.mock import MockBackend
from ai_server.models import ComplexityClass, ObjectPlan, PartPlan
from ai_server.services.codegen import CodeGenService

pytestmark = pytest.mark.unit

_MODEL = "test-ir"


def _plan(family: str) -> ObjectPlan:
    return ObjectPlan(
        object_name="o", summary="s", complexity_class=ComplexityClass.IN_SCOPE,
        parts=[PartPlan(id="p", name="P", family=family, object_type="t", features=[])],
        confidence=0.8,
    )


def _gateway_returning(ir_dict: dict) -> LLMGateway:
    backend = MockBackend()
    backend.script(_MODEL, ir_dict)
    profiles = {"IR_CODEGEN": {"provider": "anthropic", "model": _MODEL, "params": {}}}
    return LLMGateway(profiles, {"anthropic": backend, "mock": MockBackend()})


def _valid_box_ir() -> dict:
    return {
        "version": "2.1.0", "units": "mm",
        "commands": [
            {"id": 0, "type": "CREATE_USER_PARAMETER",
             "params": {"name": "p_d", "value": 50, "unit": "mm"}, "depends_on": [], "produces": None},
            {"id": 1, "type": "CREATE_SKETCH", "params": {"plane": "XY"},
             "depends_on": [], "produces": "sketch_0"},
            {"id": 2, "type": "ADD_RECTANGLE",
             "params": {"sketch_ref": "sketch_0", "corner1": [0, 0], "width": "p_d", "height": 30},
             "depends_on": [1], "produces": "profile_0"},
            {"id": 3, "type": "CLOSE_SKETCH", "params": {"sketch_ref": "sketch_0"},
             "depends_on": [2], "produces": None},
            {"id": 4, "type": "EXTRUDE",
             "params": {"profile_ref": "profile_0", "distance": 20, "operation": "new_body"},
             "depends_on": [3], "produces": "body_0"},
        ],
        "rollback_points": [1, 3],
        "expected_geometry": {"bbox_mm": [50, 30, 20], "volume_mm3": 30000, "key_dims": {}},
    }


def test_template_only_for_simple_parts() -> None:
    from ai_server.models import PartPlan
    from ai_server.services.codegen import template_suffices

    simple = PartPlan(id="p", name="P", family="cylinder", object_type="t", features=["holes"])
    assert template_suffices(simple) is True
    # a 'cylinder' that is hollow/embossed is NOT a template cylinder -> must go to the LLM
    rich = PartPlan(id="p", name="P", family="cylinder", object_type="t",
                    features=["hollow interior with wall thickness", "embossed scale pattern"])
    assert template_suffices(rich) is False
    assert template_suffices(PartPlan(id="p", name="P", family="curved_chute",
                                      object_type="t", features=[])) is False


async def test_known_family_uses_exact_template() -> None:
    # box is a template family -> deterministic generator, no LLM call (works under the mock config)
    svc = CodeGenService(build_gateway(settings=Settings()))
    resp = await svc.generate(_plan("box"), "p", {"length": 50, "width": 30, "height": 20})
    assert resp.result is not None
    names = {c.params["name"] for c in resp.result.command_ir.commands
             if c.type.value == "CREATE_USER_PARAMETER"}
    assert names == {"p_length", "p_width", "p_height"}


async def test_novel_family_offline_refuses() -> None:
    # novel family + mock provider (no real model) -> honest refusal
    svc = CodeGenService(build_gateway(settings=Settings()))
    resp = await svc.generate(_plan("curved_chute"), "p", {})
    assert resp.refusal is not None
    assert "live model" in resp.refusal.message


async def test_novel_family_llm_builds_with_advisory() -> None:
    svc = CodeGenService(_gateway_returning(_valid_box_ir()))
    resp = await svc.generate(_plan("curved_chute"), "p", {"length": 100})
    assert resp.result is not None  # LLM IR passed the validator -> built
    assert resp.result.warnings  # carries a render-check / advisory note


async def test_novel_family_invalid_ir_refuses_after_retries() -> None:
    # the model keeps returning an empty (invalid) IR -> validator rejects every attempt -> refuse
    svc = CodeGenService(_gateway_returning({"version": "2.1.0", "units": "mm", "commands": []}))
    resp = await svc.generate(_plan("curved_chute"), "p", {})
    assert resp.refusal is not None
    assert "attempts" in resp.refusal.message


# --------------------------------------------------- parametric flow: structure -> user dimensions


def test_dimension_slots_are_derived_from_ir_parameters() -> None:
    from ai_server.models import CommandIR
    from ai_server.services.codegen import dimension_slots_from_ir

    slots = dimension_slots_from_ir(CommandIR.model_validate(_valid_box_ir()), "p")
    assert [s.id for s in slots] == ["p_d"]          # every user parameter -> one slot
    assert slots[0].default_value == 50
    assert slots[0].label == "D"                     # 'p_d' humanized (part-id prefix stripped)


async def test_base_ir_substitutes_user_dimensions_without_a_model_call() -> None:
    # novel part + carried base_ir -> the user's value is substituted; no live model needed
    svc = CodeGenService(build_gateway(settings=Settings()))  # mock gateway; base_ir path skips it
    resp = await svc.generate(_plan("curved_chute"), "p", {"p_d": 80}, base_ir=_valid_box_ir())
    assert resp.result is not None
    param = next(c for c in resp.result.command_ir.commands
                 if c.type.value == "CREATE_USER_PARAMETER" and c.params["name"] == "p_d")
    assert param.params["value"] == 80  # exact: the geometry now uses the user's dimension


# ---------------------------------------------- Design-Genome path (ADR-007), fully offline

async def test_hollow_part_builds_offline_via_genome() -> None:
    # a hollow_cylinder is NOT a template family, yet the genome planner builds it deterministically
    # with NO live model — render-check VERIFIES the cavity (not a vague solid).
    svc = CodeGenService(build_gateway(settings=Settings()))
    plan = _plan("hollow_cylinder")
    base_ir, slots = await svc.generate_parametric(plan, plan.parts[0])
    assert base_ir is not None and slots  # parametric structure + dimension slots, offline
    resp = await svc.generate(plan, "p", {})
    assert resp.result is not None
    assert any("render-check ok" in w for w in resp.result.warnings)  # geometry verified


async def test_genome_applies_user_dimensions_offline() -> None:
    svc = CodeGenService(build_gateway(settings=Settings()))
    plan = _plan("hollow_cylinder")
    resp = await svc.generate(plan, "p", {"p_diameter": 120, "p_height": 150, "p_wall": 5})
    body_dia = next(c for c in resp.result.command_ir.commands
                    if c.params.get("name") == "p_diameter")
    assert body_dia.params["value"] == 120  # user's dimension drove the geometry, no model call
