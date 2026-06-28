"""Open-ended understanding (ADR-015, breakthrough Pillar P1-full) — formalise the unsaid.

The deterministic frames (ADR-012) understand a seed of object classes. This layer removes the
ceiling: the planning model reasons about the requirements an expert assumes for ANY object and
emits each as a `RequirementSpec` — a predicate in a CLOSED grammar (`<metric> <op> <target>` over an
allow-listed metric vocabulary). This module is the *correct-by-construction filter*: it validates
each proposal against the vocabulary and the metric's type, DROPPING anything unprovable, and turns
the survivors into checkable `Requirement`s the certificate (ADR-011) proves. So the LLM's
open-ended reasoning still yields only machine-checkable obligations — autoformalization, scoped to
what we can verify. Pure and offline (the LLM proposes; this validates).
"""

from __future__ import annotations

from .spec import Requirement

# the metric vocabulary the model may use, with each metric's value TYPE. Mirrors spec.evidence keys
# so every formalised requirement is checkable against the realized solid.
_NUMERIC = {"volume_mm3", "capacity_mm3", "wall_mm", "bbox_x_mm", "bbox_y_mm", "bbox_z_mm",
            "stability_ratio", "handle_aperture_mm", "seat_gap_mm"}
_BOOL = {"is_hollow", "has_bore", "cavity_reachable", "through_connected", "has_coupling"}
_ENUM = {"opening": {"top", "bottom", "both", "none"}}

METRIC_VOCAB: set[str] = _NUMERIC | _BOOL | set(_ENUM)
OP_VOCAB = {">", ">=", "<", "<=", "==", "!="}


def _parse_target(metric: str, raw: str):
    """Parse the text target against the metric's type, or return None if it doesn't fit."""
    raw = (raw or "").strip()
    if metric in _NUMERIC:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if metric in _BOOL:
        low = raw.lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        return None
    if metric in _ENUM:
        return raw.lower() if raw.lower() in _ENUM[metric] else None
    return None


def validate(spec, part_id: str, index: int) -> Requirement | None:
    """Validate one `RequirementSpec` into a checkable `Requirement`, or None if it isn't provable.

    Correct-by-construction: unknown metric, bad operator, a comparison that doesn't fit the metric's
    type (e.g. ``>`` on a bool/enum), or an unparseable target -> dropped, so a hallucinated
    requirement can never enter the certificate.
    """
    metric = getattr(spec, "metric", None)
    op = getattr(spec, "op", None)
    if metric not in METRIC_VOCAB or op not in OP_VOCAB:
        return None
    if (metric in _BOOL or metric in _ENUM) and op not in ("==", "!="):
        return None  # bool/enum metrics only support equality
    target = _parse_target(metric, getattr(spec, "target", ""))
    if target is None:
        return None
    desc = (getattr(spec, "description", "") or "").strip() or f"{metric} {op} {target}"
    return Requirement(id=f"{part_id}.expert.{index}_{metric}", kind="expert", description=desc,
                       metric=metric, op=op, target=target, severity="should", tier="proved",
                       provenance="expert inference (formalised from intent)")


def proposals_to_requirements(part) -> list[Requirement]:
    """Validate a part's formalised `requirements` into checkable obligations (drops the unprovable)."""
    out: list[Requirement] = []
    pid = getattr(part, "id", None) or "part"
    for i, rs in enumerate(getattr(part, "requirements", None) or []):
        req = validate(rs, pid, i)
        if req is not None:
            out.append(req)
    return out


# prompt fragment appended to the intent system prompt so the model formalises the unsaid -----------
REQUIREMENTS_PROMPT = (
    "UNDERSTAND THE UNSAID — for each part, also fill `requirements`: the implied engineering "
    "requirements an expert assumes that the user did NOT state, each a CHECKABLE predicate "
    "{metric, op, target, description}. Use ONLY these metrics:\n"
    "  numbers (mm or mm^3): capacity_mm3, wall_mm, volume_mm3, bbox_x_mm, bbox_y_mm, bbox_z_mm, "
    "stability_ratio (min base / height), handle_aperture_mm, seat_gap_mm;\n"
    "  booleans: is_hollow, has_bore, cavity_reachable, through_connected, has_coupling;\n"
    "  enum: opening (top|bottom|both|none).\n"
    "op is one of > >= < <= == != (use == or != for booleans/enums). target is text "
    "('150000', 'true', 'top'). Example for a mug: "
    "{metric:'capacity_mm3', op:'>=', target:'250000', description:'holds a normal mug serving'}, "
    "{metric:'stability_ratio', op:'>=', target:'0.35', description:'wont tip over'}, "
    "{metric:'wall_mm', op:'>=', target:'2', description:'food-safe, sturdy wall'}. Give the few that "
    "matter; omit any you cannot express with the metrics above. If a design-critical choice is "
    "genuinely ambiguous (and would change the geometry), add ONE high-value clarifying question to "
    "clarifications_needed rather than guessing."
)
