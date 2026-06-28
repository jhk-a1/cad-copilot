"""Function gate (ADR-013, breakthrough Pillar P3) — does the design actually WORK?

A model can be a valid solid and still be functionally dead: a faucet that won't flow, a cup you
can't fill, a latch that won't move. No text-to-CAD system checks this — the frontier "verifies" by
showing a vision model a picture and asking if it looks right. The 40-year-old, sound answer is
QUALITATIVE PHYSICS + FUNCTION-BEHAVIOR-STRUCTURE (de Kleer & Brown; Forbus QPT; Kuipers QSIM; Gero
FBS; Stone & Wood's Functional Basis): decompose the intended FUNCTION into flow verbs, then check
that the STRUCTURE realises the BEHAVIOR — qualitatively, from geometry, before trusting the build.

This module is GENERAL by construction: functions are inferred from purpose + structure (not object
names), and each function maps to a checkable *teleological* predicate — "to contain, the cavity must
be reachable to fill/empty"; "to convey, a through-path must exist"; "to support, it must stand";
"to couple, it must have a join"; "to actuate, it must have a degree of freedom". These become
behaviour requirements the certificate (ADR-011) proves, with the evidence computed analytically.

Pure and offline.
"""

from __future__ import annotations

from .grammar import FeatureType, Genome
from .spec import Requirement

# the Functional Basis (Stone & Wood), grouped by the flow each function acts on. Verbs are matched
# against the part's stated purpose; structure supplies the rest. General, not an object table.
FUNCTIONS: dict[str, dict] = {
    "contain": {"flow": "material",
                "verbs": ("contain", "store", "hold", "collect", "carry", "keep", "fill")},
    "convey": {"flow": "material",
               "verbs": ("channel", "convey", "conduct", "transport", "guide", "transfer",
                         "pour", "flow", "duct", "pipe", "drain", "vent")},
    "support": {"flow": "force",
                "verbs": ("support", "stabilise", "stabilize", "bear", "stand", "hold up", "rest")},
    "couple": {"flow": "force",
               "verbs": ("couple", "join", "attach", "secure", "fasten", "connect", "grip",
                         "mount", "clamp", "hang")},
    "actuate": {"flow": "motion",
                "verbs": ("actuate", "move", "rotate", "slide", "hinge", "pivot", "swing",
                          "transmit", "linkage", "mechanism")},
}


def _text(part) -> str:
    bits = [getattr(part, a, "") or "" for a in ("object_type", "purpose", "name")]
    return " ".join(str(b) for b in bits).lower()


def infer_functions(part, genome: Genome) -> set[str]:
    """Infer the functions a part must perform, from its stated purpose AND its structure.

    General: purpose verbs map to Functional-Basis functions; structure adds the rest (a hollow body
    must contain; an open-both or bored body conveys; an attached part couples). No object lookup."""
    text = _text(part)
    types = [f.type for f in genome.features]
    hollow = bool(getattr(part, "hollow", False)) or any(
        t in (FeatureType.HOLLOW_CYLINDER, FeatureType.HOLLOW_BOX) for t in types)
    opening = (getattr(part, "opening", "") or "").strip().lower()
    has_bore = FeatureType.BORE in types
    attaches = getattr(part, "attachment", None) is not None or (
        genome.primary is not None and genome.primary.type is FeatureType.LOOP_HANDLE)

    funcs: set[str] = set()
    # text verbs, but 'contain' and 'couple' are GEOMETRY-anchored: a part's purpose describing how it
    # relates to OTHER parts (a mug body whose blurb mentions "the handle attaches") must not make the
    # body a coupler, and a handle that "holds" the mug is not a container. So those two come only from
    # this part's own structure below — text supplies the rest (support / convey / actuate).
    for fn, spec in FUNCTIONS.items():
        if fn == "contain":
            continue
        if any(v in text for v in spec["verbs"]):
            if fn == "couple" and hollow:
                continue
            funcs.add(fn)

    # structural inference (what THIS part's geometry implies)
    if hollow:
        funcs.add("contain")
    if opening == "both" or has_bore:
        funcs.add("convey")
    if attaches:
        funcs.add("couple")
    return funcs


# each function -> the checkable behaviour predicate that the structure must realise to perform it
_BEHAVIOUR = {
    "contain": Requirement("", "behavior", "to contain, the cavity must be reachable to fill/empty",
                           "cavity_reachable", "==", True, "should", "tested",
                           "a containment function needs a reachable cavity"),
    "convey": Requirement("", "behavior", "to convey, a through-path must exist for the flow",
                          "through_connected", "==", True, "should", "tested",
                          "a conveyance function needs a connected path"),
    "support": Requirement("", "behavior", "to support a load, it must stand stably",
                           "stability_ratio", ">=", 0.30, "should", "tested",
                           "a support function needs a stable stance"),
    "couple": Requirement("", "behavior", "to couple, it must have a join (seated mate or fastening)",
                          "has_coupling", "==", True, "should", "tested",
                          "a coupling function needs a join"),
}


def behavior_requirements(part, genome: Genome) -> list[Requirement]:
    """The behaviour obligations implied by the part's functions — the teleological chain that must
    close for the design to actually work. Merged into the Specification and proven by the certificate.

    'actuate' is handled separately (mobility) at the assembly level; a single rigid part can't move,
    so we don't impose it here — the compositional/mobility layer (ADR-014, dfm) owns mechanisms.
    """
    pid = getattr(part, "id", None) or getattr(part, "name", None) or "part"
    out: list[Requirement] = []
    for fn in sorted(infer_functions(part, genome)):
        tmpl = _BEHAVIOUR.get(fn)
        if tmpl is None:
            continue
        out.append(Requirement(id=f"{pid}.behavior.{fn}", kind=tmpl.kind,
                               description=tmpl.description, metric=tmpl.metric, op=tmpl.op,
                               target=tmpl.target, severity=tmpl.severity, tier=tmpl.tier,
                               provenance=tmpl.provenance))
    return out


__all__ = ["FUNCTIONS", "infer_functions", "behavior_requirements"]
