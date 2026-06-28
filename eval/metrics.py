"""Scoring functions for the eval harness. Pure functions over endpoint JSON."""

from __future__ import annotations

from typing import Any

from ai_server.models import CodeGenResponse, CommandIR
from ai_server.services.geometry import (
    Box,
    Cylinder,
    LBracket,
    Solid,
    WithHoles,
    check_geometry,
    iou,
    realize,
)
from ai_server.services.placeholder import hole_layout


def derive_plan_behavior(plan: dict[str, Any]) -> str:
    """Classify what the planner actually did: generate / clarify / decompose / refuse."""
    cc = plan.get("complexity_class")
    if cc == "decompose":
        return "decompose"
    if cc == "out_of_scope":
        return "clarify" if plan.get("clarifications_needed") else "refuse"
    # in_scope
    if not plan.get("parts"):
        return "clarify"
    return "generate"


def ir_schema_valid(codegen: dict[str, Any]) -> bool:
    """A codegen response is contract-valid if it parses (a refusal counts — it's valid)."""
    try:
        resp = CodeGenResponse.model_validate(codegen)
    except Exception:
        return False
    if resp.result is None:
        return resp.refusal is not None
    try:
        CommandIR.model_validate(resp.result.command_ir.model_dump())
        return True
    except Exception:
        return False


def user_parameter_values(command_ir: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for cmd in command_ir.get("commands", []):
        if cmd.get("type") == "CREATE_USER_PARAMETER":
            p = cmd.get("params", {})
            try:
                out[str(p.get("name"))] = float(p.get("value"))
            except (TypeError, ValueError):
                continue
    return out


def dimensional_error(command_ir: dict[str, Any], golden: dict[str, float]) -> float | None:
    """Max abs error (mm) between entered dims and what the IR honors. None = not applicable.

    A dimension that doesn't appear in the IR (as a part-prefixed userParameter or in
    expected_geometry.key_dims) yields inf, so it fails any tolerance.
    """
    if not golden:
        return None
    params = user_parameter_values(command_ir)
    key_dims = {
        k: float(v) for k, v in (command_ir.get("expected_geometry") or {}).get("key_dims", {}).items()
    }
    worst = 0.0
    for key, value in golden.items():
        found: float | None = None
        for name, val in params.items():
            if name == key or name.endswith("_" + key):
                found = val
                break
        if found is None:
            found = key_dims.get(key)
        if found is None:
            return float("inf")
        worst = max(worst, abs(found - float(value)))
    return worst


# ----------------------------------------------------------------- kernel-based metrics


def render_check_ok(command_ir: dict[str, Any]) -> bool | None:
    """Realize the IR and confirm it matches its own expected_geometry (<0.1mm gate).

    None when the kernel can't yet realize this family (l_bracket/holes) — not a failure.
    """
    check = check_geometry(CommandIR.model_validate(command_ir))
    return check.ok if check.realized else None


def _reference_solid(family: str, golden: dict[str, float], features: list[str]) -> Solid | None:
    """The intended target solid built from the case's family + golden dimensions + features."""
    if not golden:
        return None
    if family == "box" and {"length", "width", "height"} <= golden.keys():
        box = Box(width=golden["length"], depth=golden["width"], height=golden["height"])
        if "holes" in features:
            centres, dia = hole_layout(golden, golden["length"], golden["width"])
            return WithHoles(box, [(cx, cy, dia / 2) for cx, cy in centres])
        return box
    if family == "cylinder" and {"diameter", "height"} <= golden.keys():
        return Cylinder(diameter=golden["diameter"], height=golden["height"])
    if family == "l_bracket" and {"leg_a", "leg_b", "thickness", "depth"} <= golden.keys():
        return LBracket(leg_a=golden["leg_a"], leg_b=golden["leg_b"],
                        thickness=golden["thickness"], depth=golden["depth"])
    return None


def kernel_iou(command_ir: dict[str, Any], family: str, golden: dict[str, float],
               features: list[str] | None = None) -> float | None:
    """Voxel IoU between the realized solid and the intended reference. None if N/A.

    Measures whether the generated geometry is the RIGHT SHAPE/SIZE — the real accuracy signal
    once the model infers dimensions instead of being handed them. The reference models the same
    features (e.g. holes), so a correctly-built holed box scores 1.0 and a wrong one does not.
    """
    reference = _reference_solid(family, golden, features or [])
    realized = realize(CommandIR.model_validate(command_ir))
    if reference is None or realized is None:
        return None
    return round(iou(realized, reference), 4)
