"""Deterministic genome planner — PartPlan -> Genome, no LLM call (ADR-007).

Maps a planned part (its family + features) onto a correct-by-construction genome. This is what
lets the engine build the mug (hollow body + scale pattern + loop handle) OFFLINE, with zero API
spend, fully covered by tests. For families it doesn't recognize it returns None, and codegen falls
back to the live LLM-genome path (`prompt.py`) or the legacy raw-IR path — so generality is
preserved without pretending the offline planner knows every shape.
"""

from __future__ import annotations

from .grammar import Feature, FeatureType, Genome

# family (canonical, snake_case) -> primary feature type
_PRIMARY_BY_FAMILY: dict[str, FeatureType] = {
    "box": FeatureType.SOLID_BOX, "cube": FeatureType.SOLID_BOX, "block": FeatureType.SOLID_BOX,
    "plate": FeatureType.SOLID_BOX, "slab": FeatureType.SOLID_BOX, "panel": FeatureType.SOLID_BOX,
    "cylinder": FeatureType.SOLID_CYLINDER, "rod": FeatureType.SOLID_CYLINDER,
    "disc": FeatureType.SOLID_CYLINDER, "disk": FeatureType.SOLID_CYLINDER,
    "l_bracket": FeatureType.L_BRACKET, "bracket": FeatureType.L_BRACKET,
    "hollow_cylinder": FeatureType.HOLLOW_CYLINDER, "cup": FeatureType.HOLLOW_CYLINDER,
    "mug": FeatureType.HOLLOW_CYLINDER, "mug_body": FeatureType.HOLLOW_CYLINDER,
    "body": FeatureType.HOLLOW_CYLINDER, "tube": FeatureType.HOLLOW_CYLINDER,
    "pipe": FeatureType.HOLLOW_CYLINDER, "vase": FeatureType.HOLLOW_CYLINDER,
    "beaker": FeatureType.HOLLOW_CYLINDER, "glass": FeatureType.HOLLOW_CYLINDER,
    "bowl": FeatureType.HOLLOW_CYLINDER, "dish": FeatureType.HOLLOW_CYLINDER,
    "pot": FeatureType.HOLLOW_CYLINDER, "jar": FeatureType.HOLLOW_CYLINDER,
    "can": FeatureType.HOLLOW_CYLINDER, "canister": FeatureType.HOLLOW_CYLINDER,
    "tank": FeatureType.HOLLOW_CYLINDER, "drum": FeatureType.HOLLOW_CYLINDER,
    "barrel": FeatureType.HOLLOW_CYLINDER, "bucket": FeatureType.HOLLOW_CYLINDER,
    "bottle": FeatureType.HOLLOW_CYLINDER, "flask": FeatureType.HOLLOW_CYLINDER,
    "tumbler": FeatureType.HOLLOW_CYLINDER, "sleeve": FeatureType.HOLLOW_CYLINDER,
    "hollow_box": FeatureType.HOLLOW_BOX, "open_box": FeatureType.HOLLOW_BOX,
    "container": FeatureType.HOLLOW_BOX, "tray": FeatureType.HOLLOW_BOX, "box_open": FeatureType.HOLLOW_BOX,
    "enclosure": FeatureType.HOLLOW_BOX, "case": FeatureType.HOLLOW_BOX, "bin": FeatureType.HOLLOW_BOX,
    "handle": FeatureType.LOOP_HANDLE, "curved_handle": FeatureType.LOOP_HANDLE,
    "loop_handle": FeatureType.LOOP_HANDLE, "loop": FeatureType.LOOP_HANDLE,
    "grip": FeatureType.LOOP_HANDLE, "ear": FeatureType.LOOP_HANDLE,
}

# keyword fallbacks when the exact family isn't in the table (order matters: hollow before solid)
_KEYWORD_PRIMARY: list[tuple[tuple[str, ...], FeatureType]] = [
    (("handle", "grip", "loop"), FeatureType.LOOP_HANDLE),
    (("hollow", "cup", "mug", "tube", "pipe", "vase", "beaker", "bowl", "dish", "pot", "jar",
      "can", "canister", "tank", "drum", "barrel", "bucket", "bottle", "flask", "tumbler",
      "vessel", "container"), FeatureType.HOLLOW_CYLINDER),
    (("tray", "open box", "enclosure", "case", "bin"), FeatureType.HOLLOW_BOX),
    (("cylinder", "rod", "round", "disc", "disk"), FeatureType.SOLID_CYLINDER),
    (("bracket", "angle"), FeatureType.L_BRACKET),
    (("box", "block", "cube", "plate", "slab", "panel"), FeatureType.SOLID_BOX),
]


def _primary_for(family: str, object_type: str) -> FeatureType | None:
    key = family.strip().lower().replace(" ", "_").replace("-", "_")
    if key in _PRIMARY_BY_FAMILY:
        return _PRIMARY_BY_FAMILY[key]
    hay = f"{family} {object_type}".lower()
    for words, ftype in _KEYWORD_PRIMARY:
        if any(w in hay for w in words):
            return ftype
    return None


# FUNCTION → topology: which end(s) a hollow vessel is open at, by what the object IS FOR.
_HOLLOW_TYPES = {FeatureType.HOLLOW_CYLINDER, FeatureType.HOLLOW_BOX}


def _opening_for(family: str, object_type: str) -> str:
    """A hollow part's functional opening. Vessels (cup/mug/bowl/container) are OPEN-TOP — that is
    what makes them usable; pipes/tubes are open at BOTH ends; sealed bodies are closed ('none')."""
    hay = f"{family} {object_type}".lower().replace("_", " ")
    if any(w in hay for w in ("pipe", "tube", "conduit", "sleeve", "through", "duct", "straw")):
        return "both"
    if any(w in hay for w in ("sealed", "tank", "canister", "capsule", "enclosed", "airtight",
                              "closed", "bottle")):
        return "none"  # 'bottle' is closed except its neck — neck is a later refinement
    return "top"  # cup, mug, glass, bowl, vase, beaker, jar, tray, open box, generic vessel


# The model's reasoned `shape` field -> a genome primary. This is the GENERALISATION path: the LLM
# decides the shape from the object's function, for ANY object; the family keyword map below is only
# a fallback for when no shape was reasoned (offline/mock/legacy plans).
_SHAPE_TO_PRIMARY: dict[str, FeatureType] = {
    "box": FeatureType.SOLID_BOX, "cuboid": FeatureType.SOLID_BOX, "block": FeatureType.SOLID_BOX,
    "plate": FeatureType.SOLID_BOX, "slab": FeatureType.SOLID_BOX, "panel": FeatureType.SOLID_BOX,
    "cylinder": FeatureType.SOLID_CYLINDER, "rod": FeatureType.SOLID_CYLINDER,
    "disc": FeatureType.SOLID_CYLINDER, "shaft": FeatureType.SOLID_CYLINDER,
    "prism": FeatureType.PRISM, "polygon": FeatureType.PRISM, "hex": FeatureType.PRISM,
    "cone": FeatureType.CONE, "frustum": FeatureType.CONE, "taper": FeatureType.CONE,
    "funnel": FeatureType.CONE, "nozzle": FeatureType.CONE,
    "sphere": FeatureType.SPHERE, "ball": FeatureType.SPHERE, "dome": FeatureType.SPHERE,
    "torus": FeatureType.TORUS, "ring": FeatureType.TORUS, "donut": FeatureType.TORUS,
    "wedge": FeatureType.WEDGE, "ramp": FeatureType.WEDGE, "gusset": FeatureType.WEDGE,
    "chute": FeatureType.WEDGE,
    "loft": FeatureType.LOFT, "transition": FeatureType.LOFT, "adapter": FeatureType.LOFT,
    "sweep": FeatureType.SWEEP, "bend": FeatureType.SWEEP, "elbow": FeatureType.SWEEP,
    "hook": FeatureType.SWEEP, "pipe_bend": FeatureType.SWEEP,
    "l_bracket": FeatureType.L_BRACKET, "bracket": FeatureType.L_BRACKET, "angle": FeatureType.L_BRACKET,
    "handle": FeatureType.LOOP_HANDLE, "grip": FeatureType.LOOP_HANDLE, "loop": FeatureType.LOOP_HANDLE,
}

# shapes that become a HOLLOW variant when the part needs a cavity
_HOLLOWABLE = {FeatureType.SOLID_CYLINDER: FeatureType.HOLLOW_CYLINDER,
               FeatureType.SOLID_BOX: FeatureType.HOLLOW_BOX}


# words in a part's features that UNAMBIGUOUSLY mean a surface FINISH -> add a texture motif. Kept
# TIGHT on purpose: the broad earlier list (ring/thread/grip/ridge/channel/fin…) matched incidental
# part words and textured engine cylinders, blade channels and clips that should be bare. A deliberate
# texture now comes from the part's explicit `pattern` field (see plan_genome); this is only the
# backup for clearly-a-finish feature words. Substring match, so 'scaled'/'knurled'/'ribbed' all hit.
_TEXTURE_WORDS = (
    "scale", "knurl", "emboss", "engrav", "dimple", "texture", "pattern", "guilloche",
    "hex", "honeycomb", "weav", "woven", "basket", "groove", "fluted", "fluting", "pebble",
    "hammered", "crosshatch", "ribbed", "shingle", "studded",
)


def _modifiers_for(features: list[str]) -> list[FeatureType]:
    fs = " ".join(features).lower()
    mods: list[FeatureType] = []
    if any(w in fs for w in _TEXTURE_WORDS):
        mods.append(FeatureType.SURFACE_PATTERN)
    if any(w in fs for w in ("fillet", "round")):
        mods.append(FeatureType.FILLET)
    if "chamfer" in fs:
        mods.append(FeatureType.CHAMFER)
    return mods


def _shape_primary(shape: str, hollow: bool) -> FeatureType | None:
    key = shape.strip().lower().replace(" ", "_").replace("-", "_")
    primary = _SHAPE_TO_PRIMARY.get(key)
    if primary is not None and hollow and primary in _HOLLOWABLE:
        return _HOLLOWABLE[primary]
    return primary


def plan_genome(part) -> Genome | None:
    """PartPlan -> Genome. Routes by the model's REASONED function first (shape/hollow/opening/bore),
    so it generalises to ANY object; falls back to the family keyword map only when no function was
    reasoned (offline/mock). Returns None if neither can place the part (then the LLM-genome path runs).
    """
    object_type = getattr(part, "object_type", "")
    shape = getattr(part, "shape", "") or ""
    hollow = bool(getattr(part, "hollow", False))
    opening = (getattr(part, "opening", "") or "").strip().lower()
    bore = bool(getattr(part, "bore", False))

    # 1. GENERAL path: the model reasoned an explicit shape.
    primary = _shape_primary(shape, hollow)
    # 2. fallback: infer from the family keyword map.
    if primary is None:
        primary = _primary_for(part.family, object_type)
        if primary is None:
            return None
        if primary in _HOLLOW_TYPES:
            hollow = True
    if primary in _HOLLOW_TYPES:
        hollow = True

    options = {}
    if primary in _HOLLOW_TYPES:
        options = {"opening": opening or _opening_for(part.family, object_type)}

    feats = [Feature(id=part.id, type=primary, options=options)]
    mods = _modifiers_for(list(part.features))
    if bore and primary not in _HOLLOW_TYPES:  # a bore on a solid body (engine cylinder, bushing)
        mods.append(FeatureType.BORE)
    # the texture motif: an explicit `pattern` (a named motif OR a custom h(u,v) expression) wins,
    # else the pattern word(s) in `features`. An explicit pattern also triggers the texture itself.
    pattern = (getattr(part, "pattern", "") or "").strip()
    if pattern and FeatureType.SURFACE_PATTERN not in mods:
        mods.append(FeatureType.SURFACE_PATTERN)
    motif_text = pattern or " ".join(part.features)
    for mod in mods:
        opts = {"motif": motif_text} if mod is FeatureType.SURFACE_PATTERN else {}
        feats.append(Feature(id=f"{part.id}_{mod.value}", type=mod, anchor="body", options=opts))
    return Genome(part_id=part.id, features=feats)
