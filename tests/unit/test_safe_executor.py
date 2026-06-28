"""Unit tests for the Safe Executor's pure compile core (M1-W3-UI-04).

The Fusion-runtime half (`SafeExecutor.execute`) can only run inside Fusion, so it is verified
live. The IR→ops compiler, the single mm→cm conversion, and every defensive error path are pure
and tested here. The final test closes the loop: the IR the server actually emits (after the IR
Validator passes it) must compile cleanly into executor ops — the full safety chain end to end.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# Load the add-in module by path — it has no module-level `adsk` import, like design_gate.
# Register in sys.modules before exec so @dataclass can resolve its own module's annotations.
_PATH = Path(__file__).resolve().parents[2] / "fusion_addin" / "core" / "safe_executor.py"
_spec = importlib.util.spec_from_file_location("safe_executor", _PATH)
safe_executor = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = safe_executor
_spec.loader.exec_module(safe_executor)

compile_ir = safe_executor.compile_ir
compare_geometry = safe_executor.compare_geometry
ExecutionError = safe_executor.ExecutionError


def _param(cid, name, value):
    return {"id": cid, "type": "CREATE_USER_PARAMETER",
            "params": {"name": name, "value": value, "unit": "mm"}, "depends_on": [], "produces": None}


def box_ir() -> dict:
    return {
        "version": "2.1.0", "units": "mm",
        "commands": [
            _param(0, "box_length", 50), _param(1, "box_width", 30), _param(2, "box_height", 20),
            {"id": 3, "type": "CREATE_SKETCH", "params": {"plane": "XY"},
             "depends_on": [], "produces": "sketch_0"},
            {"id": 4, "type": "ADD_RECTANGLE",
             "params": {"sketch_ref": "sketch_0", "corner1": [0, 0],
                        "width": "box_length", "height": "box_width"},
             "depends_on": [3], "produces": "profile_0"},
            {"id": 5, "type": "CLOSE_SKETCH", "params": {"sketch_ref": "sketch_0"},
             "depends_on": [4], "produces": None},
            {"id": 6, "type": "EXTRUDE",
             "params": {"profile_ref": "profile_0", "distance": "box_height", "operation": "new_body"},
             "depends_on": [5], "produces": "body_0"},
        ],
        "rollback_points": [3, 5],
        "expected_geometry": {"bbox_mm": [50, 30, 20], "volume_mm3": 30000, "key_dims": {}},
    }


def cylinder_ir() -> dict:
    return {
        "version": "2.1.0", "units": "mm",
        "commands": [
            _param(0, "c_diameter", 25), _param(1, "c_height", 40),
            {"id": 2, "type": "CREATE_SKETCH", "params": {"plane": "XY"},
             "depends_on": [], "produces": "sketch_0"},
            {"id": 3, "type": "ADD_CIRCLE",
             "params": {"sketch_ref": "sketch_0", "center": [0, 0], "diameter": "c_diameter"},
             "depends_on": [2], "produces": "profile_0"},
            {"id": 4, "type": "CLOSE_SKETCH", "params": {"sketch_ref": "sketch_0"},
             "depends_on": [3], "produces": None},
            {"id": 5, "type": "EXTRUDE",
             "params": {"profile_ref": "profile_0", "distance": "c_height", "operation": "new_body"},
             "depends_on": [4], "produces": "body_0"},
        ],
        "rollback_points": [2, 4], "expected_geometry": {"bbox_mm": [25, 25, 40]},
    }


# --------------------------------------------------------------------------- units

def test_mm_to_cm() -> None:
    assert safe_executor.mm_to_cm(50) == 5.0
    assert safe_executor.mm_to_cm(0) == 0.0


# --------------------------------------------------------------------------- compile box

def test_box_compiles_to_expected_ops() -> None:
    ops = compile_ir(box_ir())
    kinds = [type(o).__name__ for o in ops]
    assert kinds == ["CreateParam", "CreateParam", "CreateParam",
                     "CreateSketch", "AddRectangle", "CloseSketch", "Extrude"]

    rect = ops[4]
    assert (rect.width_cm, rect.height_cm) == (5.0, 3.0)  # 50mm, 30mm -> cm
    assert rect.corner_cm == (0.0, 0.0)

    extrude = ops[6]
    assert extrude.distance_cm == 2.0  # 20mm
    assert extrude.distance_expression == "box_height"  # bound to the user parameter by name
    assert extrude.operation == "new_body"


def test_user_parameter_expression_is_mm() -> None:
    first = compile_ir(box_ir())[0]
    assert first.name == "box_length"
    assert first.value_mm == 50.0
    assert first.expression == "50.0 mm"


def test_cylinder_circle_diameter_converts() -> None:
    ops = compile_ir(cylinder_ir())
    circle = next(o for o in ops if type(o).__name__ == "AddCircle")
    assert circle.diameter_cm == 2.5  # 25mm


# --------------------------------------------------------------------------- defensive errors

def test_non_mm_units_rejected() -> None:
    ir = box_ir()
    ir["units"] = "cm"
    with pytest.raises(ExecutionError):
        compile_ir(ir)


def test_empty_ir_rejected() -> None:
    with pytest.raises(ExecutionError):
        compile_ir({"units": "mm", "commands": []})


def test_unresolved_parameter_rejected() -> None:
    ir = box_ir()
    ir["commands"][6]["params"]["distance"] = "not_a_param"
    with pytest.raises(ExecutionError):
        compile_ir(ir)


def test_unsupported_command_rejected() -> None:
    ir = box_ir()
    # LOFT is not in the executor vocabulary yet -> must reject rather than silently skip
    ir["commands"].append({"id": 7, "type": "LOFT", "params": {},
                           "depends_on": [6], "produces": None})
    with pytest.raises(ExecutionError):
        compile_ir(ir)


# --------------------------------------------------------------------------- full safety chain

def test_server_emitted_ir_is_executor_compilable() -> None:
    """The IR the server produces (and the IR Validator passes) must compile to executor ops."""
    from ai_server.services import placeholder

    for text, part, dims in [
        ("a box", "box", {"length": 50, "width": 30, "height": 20}),
        ("a cylinder", "cylinder", {"diameter": 25, "height": 40}),
        ("an l-bracket", "l_bracket", {"leg_a": 50, "leg_b": 30, "thickness": 5, "depth": 40}),
    ]:
        plan = placeholder.plan_object(text)
        response = placeholder.generate_part_code(plan, part, dims)
        assert response.result is not None, "server refused a valid part"
        ops = compile_ir(response.result.command_ir.model_dump())
        assert any(type(o).__name__ == "Extrude" for o in ops)


def test_l_bracket_ir_compiles_with_six_lines() -> None:
    from ai_server.services import placeholder

    plan = placeholder.plan_object("an l-bracket")
    ir = placeholder.generate_part_code(
        plan, "l_bracket", {"leg_a": 50, "leg_b": 30, "thickness": 5, "depth": 40}
    ).result.command_ir.model_dump()
    ops = compile_ir(ir)
    assert sum(1 for o in ops if type(o).__name__ == "AddLine") == 6


# --------------------------------------------------------------------------- full vocabulary

def test_compile_handles_full_ir_vocabulary() -> None:
    """The executor compiles the whole IR vocabulary, not just primitives (ADR-005 generality)."""
    ir = {"units": "mm", "commands": [
        {"id": 0, "type": "CREATE_USER_PARAMETER", "params": {"name": "d", "value": 10, "unit": "mm"}},
        {"id": 1, "type": "CREATE_SKETCH", "params": {"plane": "XY"}, "produces": "sketch_0"},
        {"id": 2, "type": "ADD_CIRCLE",
         "params": {"sketch_ref": "sketch_0", "center": [0, 0], "diameter": "d"}, "produces": "profile_0"},
        {"id": 3, "type": "ADD_ARC",
         "params": {"sketch_ref": "sketch_0", "start": [0, 0], "mid": [1, 1], "end": [2, 0]}},
        {"id": 4, "type": "CLOSE_SKETCH", "params": {"sketch_ref": "sketch_0"}},
        {"id": 5, "type": "REVOLVE",
         "params": {"profile_ref": "profile_0", "angle": 360, "axis": "y", "operation": "new_body"},
         "produces": "body_0"},
        {"id": 6, "type": "FILLET", "params": {"body_ref": "body_0", "radius": 2}},
        {"id": 7, "type": "CHAMFER", "params": {"body_ref": "body_0", "distance": 1}},
        {"id": 8, "type": "SHELL", "params": {"body_ref": "body_0", "thickness": 1}},
        {"id": 9, "type": "HOLE", "params": {"body_ref": "body_0", "positions": [[5, 5], [10, 5]], "diameter": 3}},
        {"id": 10, "type": "ADD_CONSTRAINT", "params": {"sketch_ref": "sketch_0"}},
    ]}
    kinds = [type(o).__name__ for o in compile_ir(ir)]
    for expected in ("AddArc", "Revolve", "Fillet", "Chamfer", "Shell", "Hole"):
        assert expected in kinds, f"{expected} not compiled"


def test_box_with_holes_ir_compiles_to_hole_cut() -> None:
    from ai_server.services import placeholder

    plan = placeholder.plan_object("a box with mounting holes")
    ir = placeholder.generate_part_code(
        plan, plan.parts[0].id,
        {"length": 50, "width": 30, "height": 20, "hole_diameter": 6, "hole_count": 4},
    ).result.command_ir.model_dump()
    holes = [o for o in compile_ir(ir) if type(o).__name__ == "Hole"]
    assert len(holes) == 1
    assert len(holes[0].centers_cm) == 4
    assert holes[0].diameter_cm == pytest.approx(0.6)  # 6 mm -> cm


# --------------------------------------------------------------------------- general verifier

def test_compare_geometry_accepts_match() -> None:
    ok, bbox_err, vol_err = compare_geometry(30000, [50, 30, 20],
                                             {"bbox_mm": [50, 30, 20], "volume_mm3": 30000})
    assert ok and bbox_err == 0 and vol_err == 0


def test_compare_geometry_rejects_bbox_mismatch() -> None:
    ok, bbox_err, _ = compare_geometry(30000, [80, 30, 20],
                                       {"bbox_mm": [50, 30, 20], "volume_mm3": 30000})
    assert not ok and bbox_err == pytest.approx(30.0)


def test_compare_geometry_rejects_volume_mismatch() -> None:
    ok, _, vol_err = compare_geometry(40000, [50, 30, 20],
                                      {"bbox_mm": [50, 30, 20], "volume_mm3": 30000})
    assert not ok and vol_err > 0.2


def test_compare_geometry_skips_without_expectation() -> None:
    assert compare_geometry(123, [1, 2, 3], {})[0] is True


# --------------------------------------------------------------------------- Design-Genome IR

def test_genome_mug_body_ir_compiles_to_executor_ops() -> None:
    """The full chain for the new engine: a hollow, dragon-scale mug body genome -> validated IR ->
    executor ops, including the new SHELL (hollow) and the robust CREATE_MESH_BODY texture skin."""
    from ai_server.models import PartPlan
    from ai_server.services.genome import plan_genome, synthesize

    CreateMeshBody = safe_executor.CreateMeshBody

    part = PartPlan(id="body", name="Body", family="hollow_cylinder",
                    object_type="cylindrical", features=["dragon_scales"])
    result = synthesize(plan_genome(part))
    assert result.ok
    ops = compile_ir(result.ir.model_dump(mode="json"))
    op_names = {type(o).__name__ for o in ops}
    assert "Shell" in op_names          # the body is genuinely hollowed
    assert "Extrude" in op_names
    # ADR-010: the scales are a robust watertight mesh skin (a displacement field), never per-feature
    # boolean cuts/patterns — so they cannot hit NO_TARGET_BODY and are cosmetic/non-fatal (optional)
    assert "CreateMeshBody" in op_names
    assert "Pattern" not in op_names
    skin = next(o for o in ops if isinstance(o, CreateMeshBody))
    assert skin.optional and len(skin.triangles) % 3 == 0 and len(skin.vertices_mm) % 3 == 0


def _mesh_body_ir(vertices_mm, triangles) -> dict:
    return {"version": "2.1.0", "units": "mm", "commands": [
        {"id": 0, "type": "CREATE_MESH_BODY",
         "params": {"name": "skin", "vertices_mm": vertices_mm, "triangles": triangles},
         "depends_on": [], "produces": None}]}


def test_create_mesh_body_compiles_to_optional_op() -> None:
    """A valid mesh skin compiles to a CreateMeshBody op that is cosmetic/non-fatal (optional)."""
    verts = [0, 0, 0, 10, 0, 0, 0, 10, 0, 0, 0, 10]  # a tetrahedron
    tris = [0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3]
    ops = compile_ir(_mesh_body_ir(verts, tris))
    assert len(ops) == 1
    op = ops[0]
    assert type(op).__name__ == "CreateMeshBody"
    assert op.optional and op.name == "skin"
    # the executor's STL builder produces a well-formed binary STL (80 hdr + count + 50/triangle)
    stl = safe_executor._binary_stl_from_flat(op.vertices_mm, op.triangles)
    assert len(stl) == 84 + 50 * (len(tris) // 3)


@pytest.mark.parametrize("verts,tris", [
    ([0, 0, 0, 1, 0, 0], [0, 1, 2]),            # too few vertices / length not % 3
    ([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1]),       # triangle list length not % 3
    ([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 9]),    # index out of range
])
def test_create_mesh_body_rejects_malformed_payload(verts, tris) -> None:
    with pytest.raises(ExecutionError):
        compile_ir(_mesh_body_ir(verts, tris))


def test_general_primitive_irs_compile_to_executor_ops() -> None:
    """cone (tapered extrude), prism (polygon), loft (offset section) all compile cleanly."""
    from ai_server.services.genome import Feature, FeatureType, Genome, synthesize

    def ops_for(ftype):
        r = synthesize(Genome(part_id="p", features=[Feature(id="p", type=ftype)]))
        return compile_ir(r.ir.model_dump(mode="json"))

    cone = ops_for(FeatureType.CONE)
    extr = next(o for o in cone if type(o).__name__ == "Extrude")
    assert extr.taper_deg != 0  # a real taper -> cone

    prism = ops_for(FeatureType.PRISM)
    poly = next(o for o in prism if type(o).__name__ == "AddPolygon")
    assert poly.sides >= 3

    loft = ops_for(FeatureType.LOFT)
    assert any(type(o).__name__ == "Loft" for o in loft)
    assert any(type(o).__name__ == "CreateSketch" and o.offset_cm for o in loft)  # offset section
