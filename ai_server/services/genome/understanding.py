"""Understanding layer (ADR-012, breakthrough Pillar P1) — inferring what a thing SHOULD be.

A request is radically under-specified: "a coffee mug" leaves unstated a dozen requirements an
expert just *knows* — it must stand without tipping, hold a useful volume, have a food-safe wall, a
graspable handle. This module is the **frame system** (Fillmore frame semantics): an object class is
a frame with typed REQUIREMENT TEMPLATES it implies, arranged by INHERITANCE (object -> container ->
vessel -> drinkware). Resolving a part to its frame and walking the inheritance chain yields the full
set of *implied* requirements — which feed the Specification (ADR-011) so the certificate proves not
just what the user *stated* but what the object *should be*. Each inference is recorded in an
assumption ledger (stated / inferred / derived) so it is auditable and overridable, never a black box.

Generality is structural, not a lookup table: resolution combines keyword match, functional-field
inference (hollow + open-both -> pipe), and a generic fallback, so EVERY object gets a principled
expansion — known or not. The frames here are a seed; the mechanism generalises.

Pure and offline. Frame requirements are advisory by default ("should") — they inform and are proven,
but do not gate fitness — while explicitly-stated intent stays gating ("must").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .grammar import FeatureType, Genome
from .spec import Requirement

# words that signal food/drink contact (so a vessel becomes food-safe drinkware)
_DRINK_FOOD = ("drink", "coffee", "tea", "water", "beverage", "juice", "milk", "mug", "cup",
               "glass", "tumbler", "food", "soup", "bowl", "kitchen", "thermos", "flask")


@dataclass(frozen=True)
class RequirementTemplate:
    """A requirement a frame implies, resolved against a part into a concrete `Requirement`."""

    suffix: str
    kind: str
    description: str
    metric: str
    op: str
    target: float | int | bool | str
    severity: str = "should"
    tier: str = "proved"
    provenance: str = ""

    def resolve(self, part_id: str, frame_name: str) -> Requirement:
        prov = self.provenance or f"a {frame_name} implies this"
        return Requirement(id=f"{part_id}.{self.suffix}", kind=self.kind,
                           description=self.description, metric=self.metric, op=self.op,
                           target=self.target, severity=self.severity, tier=self.tier,
                           provenance=prov)


@dataclass(frozen=True)
class Frame:
    """An object class: its parent (inheritance), the words that evoke it, and what it implies."""

    name: str
    parent: str | None
    keywords: tuple[str, ...] = ()
    requires: tuple[RequirementTemplate, ...] = ()


def _rt(*a, **k) -> RequirementTemplate:
    return RequirementTemplate(*a, **k)


# the frame hierarchy (a seed; resolution + fallback make it general) --------------------------
FRAMES: dict[str, Frame] = {
    "object": Frame("object", None),
    "container": Frame(
        "container", "object",
        keywords=("container", "box", "bin", "tank", "holder", "case", "tub", "canister", "reservoir"),
        requires=(
            _rt("func.hollow", "functional", "is hollow - a container holds contents",
                "is_hollow", "==", True, "should", "proved", "a container must contain"),
            _rt("func.capacity", "functional", "the cavity can hold contents (capacity > 0)",
                "capacity_mm3", ">", 0.0, "should", "proved", "a container must contain"),
        )),
    "vessel": Frame(
        "vessel", "container",
        keywords=("vessel", "jar", "jug", "pitcher", "vase", "pot", "bucket", "pail", "bowl"),
        requires=(
            _rt("erg.stable_base", "geometric",
                "stands stably without tipping (footprint vs height >= 0.3)",
                "stability_ratio", ">=", 0.30, "should", "tested",
                "a free-standing vessel must not tip over"),
        )),
    "drinkware": Frame(
        "drinkware", "vessel",
        keywords=("mug", "cup", "glass", "tumbler", "beaker", "thermos", "flask", "stein", "goblet"),
        requires=(
            _rt("func.opening", "functional", "is open at the top to drink from",
                "opening", "==", "top", "should", "proved", "you drink from the top"),
            _rt("func.useful_capacity", "functional", "holds a useful drink volume (>= 150 ml)",
                "capacity_mm3", ">=", 150000.0, "should", "proved", "drinkware must hold a serving"),
            _rt("mfg.food_safe_wall", "manufacturing",
                "wall is food-safe and sturdy (>= 1.0 mm)",
                "wall_mm", ">=", 1.0, "should", "proved", "food contact / durability"),
        )),
    "pipe": Frame(
        "pipe", "container",
        keywords=("pipe", "tube", "conduit", "duct", "hose", "sleeve", "channel"),
        requires=(
            _rt("func.opening", "functional", "is open at both ends to convey flow",
                "opening", "==", "both", "should", "proved", "a pipe conveys through both ends"),
        )),
    "handle": Frame(
        "handle", "object",
        keywords=("handle", "grip", "knob", "hook"),
        requires=(
            _rt("erg.graspable", "geometric", "the grip opening fits fingers (>= 20 mm clear)",
                "handle_aperture_mm", ">=", 20.0, "should", "tested", "a handle must fit the hand"),
        )),
    "flatware": Frame(
        "flatware", "object",
        keywords=("tray", "plate", "dish", "platter", "coaster", "saucer"),
        requires=(
            _rt("erg.flat_stable", "geometric", "sits flat and stable (wide footprint vs height)",
                "stability_ratio", ">=", 0.8, "should", "tested", "flatware must lie flat and stable"),
        )),
    "structural": Frame(
        "structural", "object",
        keywords=("bracket", "mount", "support", "gusset", "clamp", "hanger", "fastener"),
        requires=(
            _rt("func.fastening", "functional", "has fastening provision (mounting holes)",
                "has_bore", "==", True, "should", "proved", "a mount needs fastening points"),
        )),
}


def _depth(name: str) -> int:
    d, cur = 0, FRAMES.get(name)
    while cur is not None and cur.parent is not None:
        d += 1
        cur = FRAMES.get(cur.parent)
    return d


def _text(part) -> str:
    # resolve from SEMANTIC intent (what the object IS / is FOR), not from `family` — which is the
    # genome's geometry primitive (e.g. 'solid_box') and would falsely match keywords like 'box'.
    bits = [getattr(part, a, "") or "" for a in ("object_type", "purpose", "name")]
    return " ".join(str(b) for b in bits).lower()


# a part's OWN geometry primitive is the authority on what it IS — so a handle stays a handle even
# inside a "coffee mug" plan whose text would otherwise drag every part toward 'drinkware'.
_PRIMARY_FRAME = {
    FeatureType.LOOP_HANDLE: "handle",
    FeatureType.L_BRACKET: "structural",
}


def resolve_frame(part, genome: Genome | None = None) -> Frame:
    """Resolve a part to its most-specific frame. The part's own GEOMETRY (genome primary) is the
    authority — a loop_handle is a handle, a hollow vessel is a container family — and intent text
    only SPECIALISES within that (drink vs pipe). This keeps per-part understanding correct inside a
    multi-part object. Falls back to text + a generic frame when there is no genome (general)."""
    primary = genome.primary if genome is not None else None
    if primary is not None:
        pt = primary.type
        if pt in _PRIMARY_FRAME:
            return FRAMES[_PRIMARY_FRAME[pt]]
        if pt in (FeatureType.HOLLOW_CYLINDER, FeatureType.HOLLOW_BOX):
            return _vessel_frame(part)
        # a solid primitive (box/cylinder/sphere/cone/prism): only a structural/flatware frame if the
        # INTENT clearly says so; otherwise the generic object frame (no spurious 'container').
    return _text_frame(part)


def _vessel_frame(part) -> Frame:
    """Specialise a hollow vessel by intent: pipe (open both / pipe words), drinkware (drink/food), or
    a plain vessel."""
    text = _text(part)
    opening = (getattr(part, "opening", "") or "").strip().lower()
    if opening == "both" or any(w in text for w in ("pipe", "tube", "conduit", "duct", "hose")):
        return FRAMES["pipe"]
    if any(w in text for w in _DRINK_FOOD):
        return FRAMES["drinkware"]
    return FRAMES["vessel"]


def _text_frame(part) -> Frame:
    """Keyword + functional-field inference + generic fallback (used when geometry isn't decisive)."""
    text = _text(part)
    candidates: list[str] = [name for name, f in FRAMES.items()
                             if any(kw in text for kw in f.keywords)]
    hollow = bool(getattr(part, "hollow", False))
    opening = (getattr(part, "opening", "") or "").strip().lower()
    if hollow and opening == "both":
        candidates.append("pipe")
    elif hollow and any(w in text for w in _DRINK_FOOD):
        candidates.append("drinkware")
    elif hollow:
        candidates.append("container")
    if not candidates:
        return FRAMES["object"]
    return FRAMES[max(candidates, key=_depth)]


@dataclass
class Expansion:
    """The result of understanding a part: the implied requirements + the resolved frame name."""

    frame: str
    requirements: list[Requirement] = field(default_factory=list)


def expand(part, genome: Genome | None = None) -> Expansion:
    """Walk the resolved frame's inheritance chain and instantiate every implied requirement.

    A child frame overrides a parent's requirement with the same suffix (most-specific wins), so a
    drinkware's open-TOP requirement supersedes a generic container's. The result is merged into the
    Specification by `derive_specification`, which also classifies each as stated/inferred/derived.
    """
    frame = resolve_frame(part, genome)
    pid = getattr(part, "id", None) or getattr(part, "name", None) or "part"

    # collect templates root -> leaf so the leaf (most specific) wins on suffix collisions
    chain: list[Frame] = []
    cur: Frame | None = frame
    while cur is not None:
        chain.append(cur)
        cur = FRAMES.get(cur.parent) if cur.parent else None
    chain.reverse()

    by_suffix: dict[str, Requirement] = {}
    for fr in chain:
        for tmpl in fr.requires:
            by_suffix[tmpl.suffix] = tmpl.resolve(pid, frame.name)
    return Expansion(frame=frame.name, requirements=list(by_suffix.values()))
