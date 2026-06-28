"""Intent service (M1-W3-BE-05) — object -> parts planning on the LLM gateway.

This is the first pipeline stage to move off the keyword placeholder and onto a real model.
The design keeps the system runnable with no API keys:

  * provider == "mock" (the default until credits land): delegate to the deterministic
    `placeholder.plan_object` templates — input-sensitive, offline, what eval/the palette use.
  * any real provider: prompt the model for an ObjectPlan via the gateway's structured output,
    then run it through a server-side **family gate** before returning.

The family gate is the accuracy guarantee on top of the model (ADR-002, "refuse or decompose,
never guess"): whatever the model proposes, we only keep parts whose family we can actually
build. Unbuildable parts are dropped and the plan is downgraded to `decompose` (some parts
buildable) or `out_of_scope` (none), with an honest clarifying question — the product never
pretends it can build geometry it can't. Every failure path (gateway error, schema-invalid
candidate, empty result) falls back to the deterministic planner so the endpoint never 500s.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import ValidationError

from ..gateway import LLMGateway, Message, build_gateway, sanitize_schema
from ..models import Clarification, ComplexityClass, ObjectPlan
from . import placeholder
from .genome.intent_expand import REQUIREMENTS_PROMPT
from .placeholder import SUPPORTED_FAMILIES

_log = logging.getLogger("cad_copilot")

INTENT_PROFILE = "INTENT"

_SYSTEM_PROMPT = (
    "You are the planning stage of CAD-Copilot, a parametric CAD assistant for Autodesk Fusion.\n"
    "Given a natural-language description of an OBJECT, decompose it into the list of PARTS needed "
    "to build it as parametric solids. DECOMPOSE — do not refuse. A single-part object is a "
    "one-part plan; a complex object becomes several parts (a park slide = ladder + platform + "
    "slide chute + side rails + support legs).\n\n"
    "For each part give: id (stable slug), name (UI label), family, object_type, features, "
    "operations_likely, count. Choose a FAMILY:\n"
    f"  - one of {', '.join(sorted(SUPPORTED_FAMILIES))} when the part is essentially that shape "
    "(these build from exact, fast templates), OR\n"
    "  - a short snake_case descriptive family for any other shape (e.g. 'hexagonal_prism', "
    "'curved_chute', 'ring', 'tapered_leg', 'triangular_gusset') — these are generated "
    "geometrically by the next stage. Always pick the closest buildable decomposition rather than "
    "refusing.\n"
    "Use a SOLID template family (box/cylinder/l_bracket) only for genuinely solid parts. If a part "
    "is HOLLOW / has a cavity / open interior (a mug, cup, pipe, container, shelled box), use a "
    "descriptive family (e.g. 'hollow_cylinder', 'open_box', 'pipe') so it is built with real walls.\n"
    "complexity_class: in_scope (single part), decompose (multiple parts), or out_of_scope ONLY if "
    "the request is not a physical object at all (then give a clarifying question and no parts).\n"
    "Holes, fillets, chamfers, AND surface textures/patterns are FEATURES of the part they sit on — "
    "NEVER separate parts. Set the part's `pattern` field to add a surface texture: a named motif "
    "(scales | knurl | studs/dots/dimples | ribs/flutes | rings | grooves | hex/honeycomb | "
    "weave/basket | bumps/pebbled), OR — for ANY pattern not in that list — a height-field EXPRESSION "
    "h(u,v) in [0,1] (u,v in [0,1] over the wall; cols,rows tile it), using sin cos sqrt abs frac tri "
    "saw noise min max pow clamp smoothstep step mix sign + - * / % ** and pi/tau. E.g. spiky "
    "downward scales -> 'pow(1-frac(v*rows),3)*(1-abs(2*frac(u*cols)-1))'; diagonal ripples -> "
    "'0.5+0.5*sin((u*cols+v*rows)*tau)'. So you can render literally any pattern on any wall. Set "
    "`pattern` ONLY when the user EXPLICITLY asks for a surface texture/finish on that part (e.g. "
    "'knurled grip', 'dragon-scale mug', 'hexagonal pattern', 'diamond-textured handle'). Leave "
    "`pattern` EMPTY ('') for every plain mechanical or structural part — a piston, cylinder barrel, "
    "shaft, gear, blade, bracket, housing, crankcase, clip or slider is BARE metal unless the user "
    "asked to texture it. Incidental words like 'ring', 'thread', 'groove', 'channel', 'grip', 'rib' "
    "in a part NAME do NOT mean a surface texture — never add a pattern just because of the name. "
    "A scaled mug body is ONE part with a 'scale pattern' feature; do not also make a 'scale tile' "
    "part. Keep the decomposition minimal: only truly distinct components are separate parts.\n"
    "ASSEMBLY: the main/body part sits at position [0,0,0]. For every part that PHYSICALLY ATTACHES "
    "to another, give an `attachment` instead of guessing coordinates: {to:<part id>, where:'side'|"
    "'wall'|'top'|'rim'|'bottom'|'front'|'back'|'left'|'right', height_frac:0..1, angle:deg}. The "
    "engine SOLVES the mate so the part seats on the host's surface (a handle: {to:'body', "
    "where:'side', height_frac:0.5}; a lid: {to:'body', where:'rim'}; a spout: {to:'body', "
    "where:'side', height_frac:0.8}). Only use position [x,y,z] (mm) for a free-standing part that "
    "does not attach. Z is up.\n"
    "FUNCTION — reason about what each part is FOR so it is built to serve its purpose, and give:\n"
    "  - shape: the primitive that best realizes it — box, cylinder, prism, cone, sphere, torus, "
    "wedge, loft (a blended transition), sweep (a bend/elbow/hook), l_bracket, or handle.\n"
    "  - hollow: true if the part needs an internal cavity (a cup, a tank, an engine block).\n"
    "  - opening: if hollow, where it opens by FUNCTION — 'top' (cup/bowl/glass), 'both' (pipe/tube), "
    "'none' (sealed). A cup with a closed top is NOT a cup; meeting the purpose includes the opening.\n"
    "  - bore: true if it needs a central axial through-hole (an engine cylinder, a bushing, a spacer).\n"
    "  - purpose: one line on what the part must do.\n"
    "Examples: a coffee mug body -> shape cylinder, hollow true, opening top; a funnel -> shape cone; "
    "a ball bearing -> shape sphere; a pipe elbow -> shape sweep; an engine block -> shape box, hollow "
    "true, with bored cylinders; an O-ring -> shape torus.\n"
    "Set confidence in [0,1] and a one-line summary. Keep every number SHORT — at most 2 decimals "
    "(confidence 0.85, never 0.85000…). Return ONLY the structured object plan.\n\n"
    + REQUIREMENTS_PROMPT
)


def _user_prompt(text: str) -> str:
    return f'Object to build:\n"""{text.strip()}"""'


# Map the model's family wording onto our canonical families (it uses reasonable synonyms).
_FAMILY_SYNONYMS = {
    "box": "box", "rectangular": "box", "rectangular_prism": "box", "prismatic": "box",
    "plate": "box", "block": "box", "cube": "box", "slab": "box", "panel": "box",
    "cylinder": "cylinder", "cylindrical": "cylinder", "tube": "cylinder", "pipe": "cylinder",
    "rod": "cylinder", "disc": "cylinder", "disk": "cylinder", "round": "cylinder",
    "l_bracket": "l_bracket", "lbracket": "l_bracket", "bracket": "l_bracket", "angle": "l_bracket",
    "angle_bracket": "l_bracket", "l_angle": "l_bracket",
}


def _canonical_family(family: str) -> str:
    key = family.strip().lower().replace(" ", "_").replace("-", "_")
    return _FAMILY_SYNONYMS.get(key, key)


# Map the model's feature wording onto the canonical names the schedule/drawing/codegen use.
_FEATURE_SYNONYMS = {
    "hole": "holes", "holes": "holes", "mounting_holes": "holes", "through_holes": "holes",
    "thru_holes": "holes", "bolt_holes": "holes", "drill_holes": "holes", "counterbores": "holes",
    "fillet": "filleted_edges", "fillets": "filleted_edges", "filleted_edges": "filleted_edges",
    "rounded": "filleted_edges", "rounded_edges": "filleted_edges", "round_edges": "filleted_edges",
    "chamfer": "chamfered_edges", "chamfers": "chamfered_edges", "chamfered": "chamfered_edges",
    "chamfered_edges": "chamfered_edges",
}


def _canonical_features(features: list[str]) -> list[str]:
    out: list[str] = []
    for f in features:
        canon = _FEATURE_SYNONYMS.get(f.strip().lower().replace(" ", "_").replace("-", "_"), f)
        if canon not in out:
            out.append(canon)
    return out


def _enforce_family_gate(plan: ObjectPlan) -> ObjectPlan:
    """Normalize part wording and keep the plan self-consistent.

    The product builds ANY part now (known families from templates, the rest via LLM codegen), so
    this no longer drops parts — it just maps known synonyms onto the canonical families (so the
    fast templates kick in) and refuses only when there are genuinely no parts.
    """
    normalized = [
        p.model_copy(update={"family": _canonical_family(p.family),
                             "features": _canonical_features(p.features)})
        for p in plan.parts
    ]
    if normalized:
        return plan.model_copy(update={"parts": normalized})

    # no parts at all -> not a buildable object; ask instead of claiming a plan
    return plan.model_copy(update={
        "parts": [],
        "complexity_class": ComplexityClass.OUT_OF_SCOPE,
        "clarifications_needed": [*plan.clarifications_needed, Clarification(
            question="What physical object would you like to build?")],
    })


class IntentService:
    """Object -> parts planning. Real model when configured, deterministic templates offline."""

    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    def _provider(self) -> str:
        return self._gateway.profiles.get(INTENT_PROFILE, {}).get("provider", "mock")

    async def plan(self, text: str) -> ObjectPlan:
        if self._provider() == "mock":
            return placeholder.plan_object(text)

        try:
            result = await self._gateway.generate_structured(
                messages=[Message("system", _SYSTEM_PROMPT), Message("user", _user_prompt(text))],
                schema=sanitize_schema(ObjectPlan.model_json_schema()),
                profile=INTENT_PROFILE,
                n=1,
            )
        except Exception:  # never 500 the endpoint — fall back to deterministic planning
            _log.exception("intent gateway call failed; using deterministic fallback")
            return placeholder.plan_object(text)

        if not result.candidates:
            return placeholder.plan_object(text)
        return self._coerce(result.candidates[0], text)

    def _coerce(self, candidate: dict, text: str) -> ObjectPlan:
        try:
            plan = ObjectPlan.model_validate(candidate)
        except ValidationError:
            _log.warning("intent model returned a schema-invalid plan; using fallback")
            return placeholder.plan_object(text)
        return _enforce_family_gate(plan)


@lru_cache
def get_intent_service() -> IntentService:
    """Process-wide service over the configured gateway (FastAPI dependency)."""
    return IntentService(build_gateway())
