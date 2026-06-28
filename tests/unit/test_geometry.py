"""Unit tests for the geometry kernel + render-and-check verifier (ADR-001).

Two things matter: the analytic measurements are EXACT (the reason we chose analytic over a
voxel kernel), and the render-check actually CATCHES a geometry that disagrees with its declared
dimensions — that catch is the accuracy guarantee for when real LLM codegen lands.
"""

from __future__ import annotations

import math

import pytest

from ai_server.models import ExpectedGeometry
from ai_server.services import placeholder
from ai_server.services.geometry import (
    Box,
    Cylinder,
    LBracket,
    WithHoles,
    check_geometry,
    iou,
    realize,
)

pytestmark = pytest.mark.unit


def _box_ir(length=50, width=30, height=20):
    plan = placeholder.plan_object("a box")
    return placeholder.generate_part_code(
        plan, "box", {"length": length, "width": width, "height": height}
    ).result.command_ir


def _cylinder_ir(diameter=25, height=40):
    plan = placeholder.plan_object("a cylinder")
    return placeholder.generate_part_code(
        plan, "cylinder", {"diameter": diameter, "height": height}
    ).result.command_ir


def _l_bracket_ir(leg_a=50, leg_b=30, thickness=5, depth=40):
    plan = placeholder.plan_object("an l-bracket")
    return placeholder.generate_part_code(
        plan, "l_bracket",
        {"leg_a": leg_a, "leg_b": leg_b, "thickness": thickness, "depth": depth},
    ).result.command_ir


# --------------------------------------------------------------------------- exact solids

def test_box_volume_and_bbox_exact() -> None:
    b = Box(width=50, depth=30, height=20)
    assert b.volume_mm3 == 30000
    assert b.bbox_mm == (50, 30, 20)
    assert b.contains(25, 15, 10) and not b.contains(60, 15, 10)


def test_cylinder_volume_and_bbox_exact() -> None:
    c = Cylinder(diameter=25, height=40)
    assert c.volume_mm3 == pytest.approx(math.pi * 12.5**2 * 40)
    assert c.bbox_mm == (25, 25, 40)
    assert c.contains(0, 0, 20) and not c.contains(13, 0, 20)  # 13mm > 12.5mm radius


def test_l_bracket_volume_and_bbox_exact() -> None:
    lb = LBracket(leg_a=50, leg_b=30, thickness=5, depth=40)
    assert lb.volume_mm3 == 5 * (50 + 30 - 5) * 40  # thickness*(a+b-t)*depth = 15000
    assert lb.bbox_mm == (50, 30, 40)
    assert lb.contains(40, 2, 20)         # in the horizontal leg
    assert lb.contains(2, 25, 20)         # in the vertical leg
    assert not lb.contains(40, 25, 20)    # the missing inner corner of the L


# --------------------------------------------------------------------------- IoU

def test_iou_identical_is_one() -> None:
    assert iou(Box(10, 10, 10), Box(10, 10, 10)) == 1.0


def test_iou_subset_is_ratio() -> None:
    # a 5-wide box fully inside a 10-wide box -> intersection/union = 500/1000 = 0.5
    assert iou(Box(5, 10, 10), Box(10, 10, 10)) == pytest.approx(0.5, abs=0.03)


# --------------------------------------------------------------------------- realize

def test_realize_box() -> None:
    solid = realize(_box_ir(50, 30, 20))
    assert isinstance(solid, Box)
    assert solid.bbox_mm == (50, 30, 20)


def test_realize_cylinder() -> None:
    solid = realize(_cylinder_ir(25, 40))
    assert isinstance(solid, Cylinder)
    assert solid.diameter == 25 and solid.height == 40


def test_realize_l_bracket() -> None:
    solid = realize(_l_bracket_ir(50, 30, 5, 40))
    assert isinstance(solid, LBracket)
    assert solid.bbox_mm == (50, 30, 40)


def test_check_passes_for_l_bracket() -> None:
    check = check_geometry(_l_bracket_ir())
    assert check.realized and check.ok
    assert check.measured_volume_mm3 == 5 * (50 + 30 - 5) * 40


def test_box_with_holes_subtracts_real_volume() -> None:
    """Holes are real cut geometry: the measured volume is the blank minus the bores."""
    plan = placeholder.plan_object("a box with mounting holes")
    ir = placeholder.generate_part_code(
        plan, plan.parts[0].id,
        {"length": 50, "width": 30, "height": 20, "hole_diameter": 6,
         "hole_edge_x": 10, "hole_edge_y": 10, "hole_spacing_x": 30, "hole_spacing_y": 10,
         "hole_count": 4},
    ).result.command_ir
    solid = realize(ir)
    assert isinstance(solid, WithHoles)
    assert solid.volume_mm3 == pytest.approx(50 * 30 * 20 - 4 * math.pi * 9 * 20)
    assert solid.bbox_mm == (50, 30, 20)  # holes do not change the bounding box
    check = check_geometry(ir)
    assert check.realized and check.ok


# --------------------------------------------------------------------------- render-and-check

def test_check_passes_for_consistent_box() -> None:
    check = check_geometry(_box_ir(50, 30, 20))
    assert check.realized and check.ok
    assert check.measured_volume_mm3 == 30000
    assert check.max_bbox_error_mm < 0.1
    assert "ok" in check.message


def test_check_catches_dimensional_mismatch() -> None:
    # Simulate a generation bug: the IR's commands build a 50x30x20 box, but its declared
    # expected_geometry claims a different size. The verifier must reject it.
    ir = _box_ir(50, 30, 20)
    tampered = ir.model_copy(update={
        "expected_geometry": ExpectedGeometry(bbox_mm=[80, 30, 20], volume_mm3=48000),
    })
    check = check_geometry(tampered)
    assert check.realized and not check.ok
    assert check.max_bbox_error_mm == pytest.approx(30.0)  # 80 vs measured 50
    assert "MISMATCH" in check.message


def test_check_skipped_for_unrealized_family() -> None:
    # l_bracket has no box/cylinder profile path yet -> skipped, never a false verdict.
    ir = _box_ir()
    stripped = ir.model_copy(update={"commands": [c for c in ir.commands
                                                  if c.type.value != "EXTRUDE"]})
    check = check_geometry(stripped)
    assert not check.realized and check.ok
