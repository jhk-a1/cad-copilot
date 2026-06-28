"""Unit tests for the eval harness (M1-W2-EVAL-02)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_server.main import app
from ai_server.services import placeholder
from eval import compare, harness, metrics

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- metrics


def test_derive_plan_behavior() -> None:
    assert metrics.derive_plan_behavior({"complexity_class": "decompose"}) == "decompose"
    assert metrics.derive_plan_behavior({"complexity_class": "in_scope", "parts": [{"id": "box"}]}) == "generate"
    assert metrics.derive_plan_behavior({"complexity_class": "in_scope", "parts": []}) == "clarify"
    assert (
        metrics.derive_plan_behavior({"complexity_class": "out_of_scope", "clarifications_needed": [{"q": "?"}]})
        == "clarify"
    )
    assert metrics.derive_plan_behavior({"complexity_class": "out_of_scope", "clarifications_needed": []}) == "refuse"


def test_ir_schema_valid() -> None:
    plan = placeholder.plan_object("a box")
    good = placeholder.generate_part_code(plan, "box", {"length": 50, "width": 30, "height": 20}).model_dump()
    assert metrics.ir_schema_valid(good) is True
    # a valid refusal is still contract-valid (asking for a part not in the plan)
    box_plan = placeholder.plan_object("a box")
    refusal = placeholder.generate_part_code(box_plan, "not_a_part", {}).model_dump()
    assert refusal["refusal"] is not None
    assert metrics.ir_schema_valid(refusal) is True
    # neither result nor refusal -> not valid for our purposes
    assert metrics.ir_schema_valid({"result": None, "refusal": None}) is False


def test_dimensional_error() -> None:
    plan = placeholder.plan_object("a box")
    ir = placeholder.generate_part_code(plan, "box", {"length": 50, "width": 30, "height": 20}).result.command_ir
    ir_d = ir.model_dump()
    assert metrics.dimensional_error(ir_d, {"length": 50, "width": 30, "height": 20}) == pytest.approx(0.0)
    assert metrics.dimensional_error(ir_d, {}) is None  # not applicable
    assert metrics.dimensional_error(ir_d, {"nonexistent": 5}) == float("inf")  # missing dim fails


# --------------------------------------------------------------------------- harness


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_run_case_generate(client: TestClient) -> None:
    case = {
        "id": "t_box", "slice": "mvp_families", "family": "box", "prompt": "a box",
        "expected_behavior": "generate", "golden_dimensions": {"length": 50, "width": 30, "height": 20},
        "clarification_answers": None,
    }
    rec = harness.run_case(client, case)
    assert rec["behavior_correct"] is True
    assert rec["ir_valid"] is True
    assert rec["generation_completed"] is True
    assert rec["dim_pass"] is True
    assert rec["views_ok"] is True
    # analytic kernel now measures geometry: realized box matches the golden-dim reference
    assert rec["render_check_ok"] is True
    assert rec["iou"] == pytest.approx(1.0)


def test_run_case_refusal(client: TestClient) -> None:
    case = {
        "id": "t_dragon", "slice": "refusal_correctness", "family": "unsupported", "prompt": "a dragon statue",
        "expected_behavior": "clarify", "golden_dimensions": {}, "clarification_answers": None,
    }
    rec = harness.run_case(client, case)
    assert rec["behavior_correct"] is True
    assert rec["generation_completed"] is None  # nothing built for out-of-scope


def test_full_run_produces_scorecard(client: TestClient) -> None:
    card = harness.run(client, slices=["mvp_families"])
    assert card["overall"]["count"] > 0
    assert card["overall"]["ir_validity"] == 100.0
    assert "mvp_families" in card["slices"]


# --------------------------------------------------------------------------- compare


def test_find_regressions() -> None:
    base = {"overall": {"behavior_accuracy": 90.0, "ir_validity": 100.0}}
    worse = {"overall": {"behavior_accuracy": 85.0, "ir_validity": 100.0}}
    same = {"overall": {"behavior_accuracy": 89.0, "ir_validity": 100.0}}
    regs = compare.find_regressions(base, worse, threshold=2.0)
    assert len(regs) == 1 and regs[0]["metric"] == "behavior_accuracy"
    assert compare.find_regressions(base, same, threshold=2.0) == []  # 1pt drop is within threshold
