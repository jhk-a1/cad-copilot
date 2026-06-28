"""Placeholder services — deterministic, contract-valid stubs (Contract v2.1.0, ADR-004).

Exercise the full object -> parts -> multi-view drawing -> per-part Command IR flow end to
end so the add-in, UI, and eval harness can be built/tested before the real engines land:
  - Object planner (LLM + complexity gate)        -> M1-W3-BE-05
  - Per-part multi-view drawing (LLM + kernel)    -> M1-W4-BE-06
  - Per-part code generation (RAG + verifier)     -> M2-W5..W7

Logic here is intentionally simple keyword/template matching. NOT the real pipeline. SVGs are
schematic placeholders; real engineering-accurate multi-view drafting comes with the kernel.

NOTE (ADR-004): the input is an OBJECT decomposed into PARTS, each verified via a multi-view
(front/top/right + iso) drawing dimensioned the way an engineer would — EVERY feature that is
present is dimensioned (overall sizes, each hole's diameter + position + spacing + count, fillet
radii, chamfers, bores), grouped by feature. The schedule below is derived from the part's
features so the dimension panel shows everything needed to fully define the part.
"""

from __future__ import annotations

import math

from ..models import (
    Clarification,
    CodeGenResponse,
    CodeGenResult,
    CommandIR,
    ComplexityClass,
    DimensionSlot,
    DrawingView,
    ExecutionStep,
    ExpectedGeometry,
    IRCommand,
    IRCommandType,
    ObjectPlan,
    PartDrawing,
    PartPlan,
    Refusal,
    RefusalReason,
    Unit,
    ViewType,
)
from . import drawing
from .command_ir import IRValidator
from .geometry import check_geometry

SUPPORTED_FAMILIES = {"box", "cylinder", "l_bracket"}

_VALIDATOR = IRValidator()

_KEYWORDS = {
    "box": ("prismatic", ["box", "cube", "rectangular", "block", "plate"]),
    "cylinder": ("cylindrical", ["cylinder", "tube", "pipe", "rod", "disc", "disk"]),
    "l_bracket": ("bracket", ["bracket", "l-bracket", "angle", "l shape", "l-shape"]),
}


# --------------------------------------------------------------------------- Stage 1: plan


def plan_object(text: str) -> ObjectPlan:
    """Decompose an OBJECT into the PARTS needed to build it. Real version: M1-W3-BE-05."""
    t = text.lower().strip()

    if not t:
        return ObjectPlan(
            object_name="",
            summary="",
            complexity_class=ComplexityClass.OUT_OF_SCOPE,
            clarifications_needed=[Clarification(question="What object would you like to create?")],
            confidence=0.1,
        )

    if "stand" in t or "holder" in t:
        return ObjectPlan(
            object_name="phone stand",
            summary="A phone stand: a flat base with an upright back.",
            parts=[
                PartPlan(id="base", name="Base", family="box", object_type="prismatic",
                         features=["holes"], operations_likely=["sketch", "extrude"]),
                PartPlan(id="upright", name="Upright", family="box", object_type="prismatic",
                         features=["filleted_edges"], operations_likely=["sketch", "extrude"]),
            ],
            complexity_class=ComplexityClass.IN_SCOPE,
            assembly_notes="Upright sits on the rear edge of the base (positioning is later scope).",
            confidence=0.6,
        )

    for family, (object_type, kws) in _KEYWORDS.items():
        if any(kw in t for kw in kws):
            label = family.replace("_", " ")
            return ObjectPlan(
                object_name=label,
                summary=f"A single {label}.",
                parts=[
                    PartPlan(id=family, name=label.title(), family=family,
                             object_type=object_type, features=_detect_features(t),
                             operations_likely=["sketch", "extrude"])
                ],
                complexity_class=ComplexityClass.IN_SCOPE,
                confidence=0.7,
            )

    return ObjectPlan(
        object_name="unknown",
        summary="",
        complexity_class=ComplexityClass.OUT_OF_SCOPE,
        clarifications_needed=[
            Clarification(
                question="That object isn't something I can build yet. Which of these is closest?",
                options=sorted(SUPPORTED_FAMILIES),
            )
        ],
        confidence=0.2,
    )


def _detect_features(t: str) -> list[str]:
    features: list[str] = []
    if "fillet" in t or "round" in t:
        features.append("filleted_edges")
    if "chamfer" in t:
        features.append("chamfered_edges")
    if "hole" in t or "bolt" in t or "mount" in t:
        features.append("holes")
    return features


def _find_part(plan: ObjectPlan, part_id: str) -> PartPlan | None:
    return next((p for p in plan.parts if p.id == part_id), None)


# ----------------------------------------------------------- Stage 2: dimension schedule


def _slot(sid, label, default, ref, group, *, lo=0.1, hi=3000, unit=Unit.MM):
    return DimensionSlot(id=sid, label=label, default_value=default, unit=unit,
                         min_value=lo, max_value=hi, geometry_ref="ref_" + ref, group=group)


def _schedule(part: PartPlan) -> list[DimensionSlot]:
    """Everything an engineer would dimension for this part, derived from its features."""
    feats = set(part.features)
    s: list[DimensionSlot] = []

    if part.family == "box":
        s += [_slot("length", "Length", 50, "length", "Overall"),
              _slot("width", "Width (depth)", 30, "width", "Overall"),
              _slot("height", "Height", 20, "height", "Overall")]
        if "filleted_edges" in feats:
            s.append(_slot("fillet_radius", "Edge fillet radius", 3, "fillet_radius", "Fillets", hi=200))
        if "chamfered_edges" in feats:
            s.append(_slot("chamfer_size", "Edge chamfer", 1, "chamfer_size", "Chamfers", hi=200))
        if "holes" in feats:
            s += [_slot("hole_diameter", "Hole diameter", 6, "hole_diameter", "Mounting holes", hi=500),
                  _slot("hole_edge_x", "Edge distance (X)", 10, "hole_edge_x", "Mounting holes"),
                  _slot("hole_edge_y", "Edge distance (Y)", 10, "hole_edge_y", "Mounting holes"),
                  _slot("hole_spacing_x", "Spacing (X)", 30, "hole_spacing_x", "Mounting holes"),
                  _slot("hole_spacing_y", "Spacing (Y)", 10, "hole_spacing_y", "Mounting holes"),
                  _slot("hole_count", "Hole count", 4, "hole_count", "Mounting holes", lo=1, hi=64)]

    elif part.family == "cylinder":
        s += [_slot("diameter", "Diameter", 25, "diameter", "Overall"),
              _slot("height", "Height", 40, "height", "Overall")]
        if "chamfered_edges" in feats:
            s.append(_slot("chamfer_size", "End chamfer", 1, "chamfer_size", "Chamfers", hi=200))
        if "holes" in feats:
            s += [_slot("bore_diameter", "Bore diameter", 10, "bore_diameter", "Bore", hi=500),
                  _slot("bore_depth", "Bore depth", 40, "bore_depth", "Bore")]

    elif part.family == "l_bracket":
        s += [_slot("leg_a", "Leg A length", 50, "leg_a", "Overall"),
              _slot("leg_b", "Leg B length", 30, "leg_b", "Overall"),
              _slot("thickness", "Thickness", 5, "thickness", "Overall", hi=500),
              _slot("depth", "Depth", 40, "depth", "Overall")]
        if "filleted_edges" in feats:
            s.append(_slot("inner_radius", "Inner fillet radius", 4, "inner_radius", "Fillets", hi=200))
        if "holes" in feats:
            s += [_slot("hole_diameter", "Hole diameter", 6, "hole_diameter", "Holes", hi=500),
                  _slot("hole_edge", "Edge distance", 10, "hole_edge", "Holes"),
                  _slot("hole_count", "Holes per leg", 1, "hole_count", "Holes", lo=1, hi=16)]

    else:  # LLM-generated family: an overall bounding box + whatever features are present
        s += [_slot("length", "Overall length", 50, "length", "Overall"),
              _slot("width", "Overall width", 40, "width", "Overall"),
              _slot("height", "Overall height", 30, "height", "Overall")]
        if "filleted_edges" in feats:
            s.append(_slot("fillet_radius", "Edge fillet radius", 3, "fillet_radius", "Fillets", hi=200))
        if "chamfered_edges" in feats:
            s.append(_slot("chamfer_size", "Edge chamfer", 1, "chamfer_size", "Chamfers", hi=200))
        if "holes" in feats:
            s += [_slot("hole_diameter", "Hole diameter", 6, "hole_diameter", "Holes", hi=500),
                  _slot("hole_count", "Hole count", 2, "hole_count", "Holes", lo=1, hi=64)]
    return s


# ----------------------------------------------------------- Stage 2: dimensioned views
# All accurate, proportional view rendering lives in services/drawing.py.

_VIEW_BUILDERS = {
    "box": drawing.box_views,
    "cylinder": drawing.cylinder_views,
    "l_bracket": drawing.l_bracket_views,
}


def generate_part_drawing(plan: ObjectPlan, part_id: str) -> PartDrawing | Refusal:
    part = _find_part(plan, part_id)
    if part is None:
        return Refusal(reason_code=RefusalReason.OUT_OF_SCOPE,
                       message=f"No part '{part_id}' in this object plan.", diagnostics={"part_id": part_id})
    # Known families render exact views; a novel (LLM-generated) family gets a bounding-box preview
    # — its true geometry is produced at codegen and verified in 3D.
    builder = _VIEW_BUILDERS.get(part.family, drawing.box_views)
    slots = _schedule(part)
    svgs = builder({s.id: s.default_value for s in slots}, set(part.features))
    views = [
        DrawingView(view=ViewType.FRONT, svg=svgs["front"], dimension_refs=[s.id for s in slots]),
        DrawingView(view=ViewType.TOP, svg=svgs["top"]),
        DrawingView(view=ViewType.RIGHT, svg=svgs["right"]),
        DrawingView(view=ViewType.ISO, svg=svgs["iso"]),
    ]
    return PartDrawing(part_id=part.id, part_name=part.name, family=part.family, views=views,
                       dimension_slots=slots, geometry_map={s.id: s.geometry_ref for s in slots})


# ----------------------------------------------------------------- Stage 4: per-part code


def generate_part_code(plan: ObjectPlan, part_id: str, dimensions: dict[str, float]) -> CodeGenResponse:
    """Per-part Command IR. box + cylinder implemented; l_bracket pending (M2). Real: M2-W5."""
    part = _find_part(plan, part_id)
    if part is None:
        return _refuse(f"No part '{part_id}' in this object plan.", part_id=part_id)
    if part.family == "box":
        return _box_code(part, dimensions)
    if part.family == "cylinder":
        return _cylinder_code(part, dimensions)
    if part.family == "l_bracket":
        return _l_bracket_code(part, dimensions)
    return _refuse(f"I can't generate a '{part.family}' part yet.", family=part.family)


def _refuse(message: str, **diagnostics: str) -> CodeGenResponse:
    return CodeGenResponse(
        refusal=Refusal(reason_code=RefusalReason.OUT_OF_SCOPE, message=message, diagnostics=diagnostics)
    )


def _box_code(part: PartPlan, dimensions: dict[str, float]) -> CodeGenResponse:
    length = float(dimensions.get("length", 50))
    width = float(dimensions.get("width", 30))
    height = float(dimensions.get("height", 20))
    p = part.id
    commands = [
        IRCommand(id=0, type=IRCommandType.CREATE_USER_PARAMETER,
                  params={"name": f"{p}_length", "value": length, "unit": "mm"}),
        IRCommand(id=1, type=IRCommandType.CREATE_USER_PARAMETER,
                  params={"name": f"{p}_width", "value": width, "unit": "mm"}),
        IRCommand(id=2, type=IRCommandType.CREATE_USER_PARAMETER,
                  params={"name": f"{p}_height", "value": height, "unit": "mm"}),
        IRCommand(id=3, type=IRCommandType.CREATE_SKETCH, params={"plane": "XY"}, produces="sketch_0"),
        IRCommand(id=4, type=IRCommandType.ADD_RECTANGLE,
                  params={"sketch_ref": "sketch_0", "corner1": [0, 0],
                          "width": f"{p}_length", "height": f"{p}_width"},
                  depends_on=[3], produces="profile_0"),
        IRCommand(id=5, type=IRCommandType.CLOSE_SKETCH, params={"sketch_ref": "sketch_0"}, depends_on=[4]),
        IRCommand(id=6, type=IRCommandType.EXTRUDE,
                  params={"profile_ref": "profile_0", "distance": f"{p}_height", "operation": "new_body"},
                  depends_on=[5], produces="body_0"),
    ]
    volume = length * width * height

    if "holes" in part.features:
        positions, hole_dia = hole_layout(dimensions, length, width)
        if positions:
            commands.append(IRCommand(
                id=7, type=IRCommandType.HOLE,
                params={"body_ref": "body_0", "positions": positions, "diameter": hole_dia,
                        "depth": f"{p}_height", "through": True},
                depends_on=[6], produces="body_0_holes"))
            volume -= len(positions) * math.pi * (hole_dia / 2) ** 2 * height

    ir = CommandIR(
        commands=commands,
        rollback_points=[3, 5],
        expected_geometry=ExpectedGeometry(
            bbox_mm=[length, width, height], volume_mm3=volume,
            key_dims={"length": length, "width": width, "height": height},
        ),
    )
    return _result(part.id, ir, ["sketch", "extrude"])


def hole_layout(dimensions: dict[str, float], length: float, width: float):
    """Real mounting-hole centres (mm) from the dimension schedule — a 2-col x N-row grid.

    Shared by codegen (to emit the HOLE cut) and the eval reference solid (to build the intended
    holed box), so a correctly-built part scores IoU 1.0 and a mis-placed one does not.
    """
    dia = float(dimensions.get("hole_diameter", 6))
    ex = float(dimensions.get("hole_edge_x", 10))
    ey = float(dimensions.get("hole_edge_y", 10))
    sx = float(dimensions.get("hole_spacing_x", max(0.0, length - 2 * ex)))
    sy = float(dimensions.get("hole_spacing_y", max(0.0, width - 2 * ey)))
    count = max(1, int(dimensions.get("hole_count", 4)))
    rows = max(1, count // 2)
    centres = []
    for r in range(rows):
        y = ey + (sy * r / max(1, rows - 1) if rows > 1 else 0)
        centres.append([round(ex, 4), round(y, 4)])
        if len(centres) < count:
            centres.append([round(ex + sx, 4), round(y, 4)])
    return centres[:count], dia


def _cylinder_code(part: PartPlan, dimensions: dict[str, float]) -> CodeGenResponse:
    diameter = float(dimensions.get("diameter", 25))
    height = float(dimensions.get("height", 40))
    p = part.id
    ir = CommandIR(
        commands=[
            IRCommand(id=0, type=IRCommandType.CREATE_USER_PARAMETER,
                      params={"name": f"{p}_diameter", "value": diameter, "unit": "mm"}),
            IRCommand(id=1, type=IRCommandType.CREATE_USER_PARAMETER,
                      params={"name": f"{p}_height", "value": height, "unit": "mm"}),
            IRCommand(id=2, type=IRCommandType.CREATE_SKETCH, params={"plane": "XY"}, produces="sketch_0"),
            IRCommand(id=3, type=IRCommandType.ADD_CIRCLE,
                      params={"sketch_ref": "sketch_0", "center": [0, 0], "diameter": f"{p}_diameter"},
                      depends_on=[2], produces="profile_0"),
            IRCommand(id=4, type=IRCommandType.CLOSE_SKETCH, params={"sketch_ref": "sketch_0"}, depends_on=[3]),
            IRCommand(id=5, type=IRCommandType.EXTRUDE,
                      params={"profile_ref": "profile_0", "distance": f"{p}_height", "operation": "new_body"},
                      depends_on=[4], produces="body_0"),
        ],
        rollback_points=[2, 4],
        expected_geometry=ExpectedGeometry(
            bbox_mm=[diameter, diameter, height],
            volume_mm3=math.pi * (diameter / 2) ** 2 * height,
            key_dims={"diameter": diameter, "height": height},
        ),
    )
    return _result(part.id, ir, ["sketch", "extrude"])


def _l_bracket_code(part: PartPlan, dimensions: dict[str, float]) -> CodeGenResponse:
    leg_a = float(dimensions.get("leg_a", 50))
    leg_b = float(dimensions.get("leg_b", 30))
    thickness = float(dimensions.get("thickness", 5))
    depth = float(dimensions.get("depth", 40))
    p = part.id
    # L-profile vertices (mm), counter-clockwise, corner at the origin
    verts = [(0, 0), (leg_a, 0), (leg_a, thickness), (thickness, thickness),
             (thickness, leg_b), (0, leg_b)]
    commands = [
        IRCommand(id=0, type=IRCommandType.CREATE_USER_PARAMETER,
                  params={"name": f"{p}_leg_a", "value": leg_a, "unit": "mm"}),
        IRCommand(id=1, type=IRCommandType.CREATE_USER_PARAMETER,
                  params={"name": f"{p}_leg_b", "value": leg_b, "unit": "mm"}),
        IRCommand(id=2, type=IRCommandType.CREATE_USER_PARAMETER,
                  params={"name": f"{p}_thickness", "value": thickness, "unit": "mm"}),
        IRCommand(id=3, type=IRCommandType.CREATE_USER_PARAMETER,
                  params={"name": f"{p}_depth", "value": depth, "unit": "mm"}),
        IRCommand(id=4, type=IRCommandType.CREATE_SKETCH, params={"plane": "XY"}, produces="sketch_0"),
    ]
    # six lines forming the closed L loop; the last one carries the profile ref
    for i in range(6):
        start, end = verts[i], verts[(i + 1) % 6]
        commands.append(IRCommand(
            id=5 + i, type=IRCommandType.ADD_LINE,
            params={"sketch_ref": "sketch_0", "start": list(start), "end": list(end)},
            depends_on=[4 if i == 0 else 4 + i],
            produces="profile_0" if i == 5 else None,
        ))
    commands.append(IRCommand(id=11, type=IRCommandType.CLOSE_SKETCH,
                              params={"sketch_ref": "sketch_0"}, depends_on=[10]))
    commands.append(IRCommand(id=12, type=IRCommandType.EXTRUDE,
                              params={"profile_ref": "profile_0", "distance": f"{p}_depth",
                                      "operation": "new_body"},
                              depends_on=[11], produces="body_0"))
    ir = CommandIR(
        commands=commands,
        rollback_points=[4, 11],
        expected_geometry=ExpectedGeometry(
            bbox_mm=[leg_a, leg_b, depth],
            volume_mm3=thickness * (leg_a + leg_b - thickness) * depth,
            key_dims={"leg_a": leg_a, "leg_b": leg_b, "thickness": thickness, "depth": depth},
        ),
    )
    return _result(part.id, ir, ["sketch", "extrude"])


def _result(part_id: str, ir: CommandIR, operations: list[str]) -> CodeGenResponse:
    # The IR Validator (M1-W3-BE-04) is the gate: invalid geometry is refused, never emitted.
    report = _VALIDATOR.validate(ir)
    if not report.valid:
        return CodeGenResponse(
            refusal=Refusal(
                reason_code=RefusalReason.VERIFIER_REJECTED,
                message="The generated build program failed safety validation and was not emitted.",
                diagnostics={"errors": report.summary(), "codes": ", ".join(sorted(report.error_codes))},
            )
        )
    # Render-and-check (ADR-001): realize the IR and confirm it matches the expected geometry.
    check = check_geometry(ir)
    if check.realized and not check.ok:
        return CodeGenResponse(
            refusal=Refusal(
                reason_code=RefusalReason.VERIFIER_REJECTED,
                message="The generated geometry did not match its expected dimensions.",
                diagnostics={
                    "render_check": check.message,
                    "max_bbox_error_mm": f"{check.max_bbox_error_mm:.4f}",
                },
            )
        )
    warnings = [i.message for i in report.warnings]
    if check.realized:
        warnings.append(check.message)
    return CodeGenResponse(
        result=CodeGenResult(
            part_id=part_id,
            command_ir=ir,
            code=f"# Display code for part '{part_id}' (not executed). Fusion units = cm.\n",
            operations=operations,
            warnings=warnings,
            execution_order=[
                ExecutionStep(step=1, operation="create_sketch", entity_ref="sketch_0"),
                ExecutionStep(step=2, operation="add_profile", entity_ref="profile_0"),
                ExecutionStep(step=3, operation="extrude", entity_ref="body_0"),
            ],
        )
    )
