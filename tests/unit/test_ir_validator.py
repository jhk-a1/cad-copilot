"""Unit tests for the IR Validator (M1-W3-BE-04).

Each case starts from a known-good box IR and mutates exactly one thing, asserting the
matching error code fires. The validator is the gate that keeps malformed build programs
from ever reaching Fusion, so its failure modes are tested as carefully as its happy path.
"""

from __future__ import annotations

import pytest

from ai_server.models import CommandIR, ExpectedGeometry, IRCommand, IRCommandType
from ai_server.services.command_ir import IRValidator

T = IRCommandType
pytestmark = pytest.mark.unit


def good_commands() -> list[IRCommand]:
    """A canonical, valid box program: 3 params -> sketch -> rectangle -> close -> extrude."""
    return [
        IRCommand(id=0, type=T.CREATE_USER_PARAMETER, params={"name": "box_length", "value": 50, "unit": "mm"}),
        IRCommand(id=1, type=T.CREATE_USER_PARAMETER, params={"name": "box_width", "value": 30, "unit": "mm"}),
        IRCommand(id=2, type=T.CREATE_USER_PARAMETER, params={"name": "box_height", "value": 20, "unit": "mm"}),
        IRCommand(id=3, type=T.CREATE_SKETCH, params={"plane": "XY"}, produces="sketch_0"),
        IRCommand(id=4, type=T.ADD_RECTANGLE,
                  params={"sketch_ref": "sketch_0", "corner1": [0, 0],
                          "width": "box_length", "height": "box_width"},
                  depends_on=[3], produces="profile_0"),
        IRCommand(id=5, type=T.CLOSE_SKETCH, params={"sketch_ref": "sketch_0"}, depends_on=[4]),
        IRCommand(id=6, type=T.EXTRUDE,
                  params={"profile_ref": "profile_0", "distance": "box_height", "operation": "new_body"},
                  depends_on=[5], produces="body_0"),
    ]


def good_ir(commands=None, **over) -> CommandIR:
    return CommandIR(
        commands=commands if commands is not None else good_commands(),
        rollback_points=over.pop("rollback_points", [3, 5]),
        expected_geometry=over.pop(
            "expected_geometry",
            ExpectedGeometry(bbox_mm=[50, 30, 20], volume_mm3=30000,
                             key_dims={"length": 50, "width": 30, "height": 20}),
        ),
        **over,
    )


V = IRValidator()


# --------------------------------------------------------------------------- happy path


def test_canonical_box_ir_is_valid() -> None:
    report = V.validate(good_ir())
    assert report.valid, report.summary()
    assert report.errors == []
    assert report.warnings == []


def test_canonical_cylinder_ir_is_valid() -> None:
    cmds = [
        IRCommand(id=0, type=T.CREATE_USER_PARAMETER, params={"name": "c_diameter", "value": 25, "unit": "mm"}),
        IRCommand(id=1, type=T.CREATE_USER_PARAMETER, params={"name": "c_height", "value": 40, "unit": "mm"}),
        IRCommand(id=2, type=T.CREATE_SKETCH, params={"plane": "XY"}, produces="sketch_0"),
        IRCommand(id=3, type=T.ADD_CIRCLE,
                  params={"sketch_ref": "sketch_0", "center": [0, 0], "diameter": "c_diameter"},
                  depends_on=[2], produces="profile_0"),
        IRCommand(id=4, type=T.CLOSE_SKETCH, params={"sketch_ref": "sketch_0"}, depends_on=[3]),
        IRCommand(id=5, type=T.EXTRUDE,
                  params={"profile_ref": "profile_0", "distance": "c_height", "operation": "new_body"},
                  depends_on=[4], produces="body_0"),
    ]
    report = V.validate(good_ir(commands=cmds, rollback_points=[2, 4],
                                expected_geometry=ExpectedGeometry(bbox_mm=[25, 25, 40])))
    assert report.valid, report.summary()


# --------------------------------------------------------------------------- structure


def test_units_must_be_mm() -> None:
    assert "IR_UNITS" in V.validate(good_ir(units="cm")).error_codes


def test_empty_ir_is_rejected() -> None:
    assert "IR_EMPTY" in V.validate(good_ir(commands=[])).error_codes


def test_duplicate_id() -> None:
    cmds = good_commands()
    cmds[1] = IRCommand(id=0, type=T.CREATE_USER_PARAMETER, params={"name": "dup", "value": 1, "unit": "mm"})
    assert "IR_DUP_ID" in V.validate(good_ir(commands=cmds)).error_codes


def test_dependency_on_missing_id() -> None:
    cmds = good_commands()
    cmds[6].depends_on = [99]
    assert "IR_BAD_DEP" in V.validate(good_ir(commands=cmds)).error_codes


def test_self_dependency() -> None:
    cmds = good_commands()
    cmds[6].depends_on = [6]
    assert "IR_SELF_DEP" in V.validate(good_ir(commands=cmds)).error_codes


def test_dependency_cycle() -> None:
    # make 3 and 4 depend on each other -> cycle
    cmds = good_commands()
    cmds[3].depends_on = [4]
    cmds[4].depends_on = [3]
    assert "IR_DAG_CYCLE" in V.validate(good_ir(commands=cmds)).error_codes


# --------------------------------------------------------------------------- references


def test_unresolved_profile_ref() -> None:
    cmds = good_commands()
    cmds[6].params["profile_ref"] = "profile_404"
    assert "IR_UNRESOLVED_REF" in V.validate(good_ir(commands=cmds)).error_codes


def test_missing_required_ref() -> None:
    cmds = good_commands()
    del cmds[6].params["profile_ref"]
    assert "IR_MISSING_REF" in V.validate(good_ir(commands=cmds)).error_codes


def test_ref_used_before_produced() -> None:
    # move the extrude (consumes profile_0) before the rectangle that produces it
    cmds = good_commands()
    cmds[4], cmds[6] = cmds[6], cmds[4]
    codes = V.validate(good_ir(commands=cmds)).error_codes
    assert "IR_REF_ORDER" in codes


# --------------------------------------------------------------------------- parameters


def test_undeclared_symbolic_dimension() -> None:
    cmds = good_commands()
    cmds[6].params["distance"] = "box_heigth"  # typo: never declared
    assert "IR_UNDECLARED_PARAM" in V.validate(good_ir(commands=cmds)).error_codes


def test_nonpositive_numeric_dimension() -> None:
    cmds = good_commands()
    cmds[0].params["value"] = -5
    assert "IR_NONPOSITIVE" in V.validate(good_ir(commands=cmds)).error_codes


def test_bad_plane() -> None:
    cmds = good_commands()
    cmds[3].params["plane"] = "QQ"
    assert "IR_BAD_PLANE" in V.validate(good_ir(commands=cmds)).error_codes


def test_bad_operation() -> None:
    cmds = good_commands()
    cmds[6].params["operation"] = "frobnicate"
    assert "IR_BAD_OPERATION" in V.validate(good_ir(commands=cmds)).error_codes


# --------------------------------------------------------------------------- lifecycle


def test_extrude_before_sketch_closed() -> None:
    # drop the CLOSE_SKETCH; extrude now references an unclosed sketch's profile
    cmds = good_commands()
    cmds = [c for c in cmds if c.type is not T.CLOSE_SKETCH]
    cmds[-1].depends_on = [4]  # extrude depends on the rectangle directly
    assert "IR_SKETCH_NOT_CLOSED" in V.validate(good_ir(commands=cmds)).error_codes


# --------------------------------------------------------------------------- bookkeeping


def test_bad_rollback_point() -> None:
    assert "IR_ROLLBACK_BAD" in V.validate(good_ir(rollback_points=[3, 999])).error_codes


def test_negative_expected_bbox() -> None:
    eg = ExpectedGeometry(bbox_mm=[50, -30, 20])
    assert "IR_GEO_BBOX" in V.validate(good_ir(expected_geometry=eg)).error_codes
