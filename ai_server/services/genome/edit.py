"""Bidirectional, incremental editing (ADR-016, breakthrough Pillar P7) — edit in words, nothing breaks.

The most valuable thing about real engineering CAD is an EDITABLE model that carries intent — and the
industry's worst unsolved pain is the topological-naming problem: edit an upstream feature and
downstream references break on regeneration. Three never-connected fields fix it together —
bidirectional transformations / LENSES (Foster et al.; symmetric & edit lenses), self-adjusting /
INCREMENTAL computation (Acar), and PERSISTENT topological identity (Kripac). Here the design's
editable view is its parameters; a `Lens` maps genome <-> parameters with the well-behaved laws, an
`Edit` is a delta applied to that view, feature IDs are PERSISTENT across edits (so references never
break), and only the touched parameters change (incremental). A small deterministic parser maps
common natural-language edits to deltas; the LLM is the open-ended path on top.

Pure and offline. The lens laws (GetPut / PutGet / PutPut) are tested, as is the persistent-identity
guarantee at both the genome and the IR (user-parameter name) level.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .grammar import Genome
from .library import resolved

# holes that are structural/integer, not dimensions — a global "make it bigger" must not scale them
_NON_SCALABLE = {"sides", "pattern_rows", "pattern_columns", "bend_angle"}


# --------------------------------------------------------------------------- the lens (BX)


def parameters(genome: Genome) -> dict[str, float]:
    """The editable VIEW (lens `get`): every feature's resolved holes, keyed ``<feature_id>.<hole>``.
    Persistent identity: the keys are the stable feature IDs, so an edit names the same thing across
    regenerations."""
    out: dict[str, float] = {}
    for f in genome.features:
        for hole, value in resolved(f).items():
            out[f"{f.id}.{hole}"] = float(value)
    return out


def with_parameters(genome: Genome, params: dict[str, float]) -> Genome:
    """Lens `put`: write a parameter view back onto the genome, PRESERVING every feature id, type and
    option (only hole values change). Missing keys keep their current resolved value."""
    new_feats = []
    for f in genome.features:
        holes = {h: float(params.get(f"{f.id}.{h}", v)) for h, v in resolved(f).items()}
        new_feats.append(f.model_copy(update={"params": holes}))
    return genome.model_copy(update={"features": new_feats})


# --------------------------------------------------------------------------- edits (deltas)


@dataclass(frozen=True)
class Edit:
    """A delta on the parameter view. ``target`` is a hole name, a ``feature.hole`` key, or ``*`` for
    every dimension. ``op`` is set | scale | delta."""

    target: str
    op: str
    value: float
    note: str = ""


def _apply_op(current: float, op: str, value: float) -> float:
    if op == "set":
        return value
    if op == "scale":
        return current * value
    if op == "delta":
        return current + value
    return current


def apply_edit(genome: Genome, edit: Edit) -> Genome:
    """Apply one edit to the parameter view and return a NEW genome (same feature ids = no broken
    references). Incremental: only matching holes change; a ``*`` scale skips structural holes."""
    params = parameters(genome)
    for key in list(params):
        _fid, hole = key.split(".", 1)
        hit = edit.target == key or edit.target == hole or (
            edit.target == "*" and edit.op == "scale" and hole not in _NON_SCALABLE)
        if hit:
            params[key] = max(0.01, round(_apply_op(params[key], edit.op, edit.value), 4))
    return with_parameters(genome, params)


def changed(before: dict[str, float], after: dict[str, float]) -> dict[str, tuple[float, float]]:
    """The minimal delta between two parameter views (what an incremental rebuild must recompute)."""
    return {k: (before[k], after[k]) for k in before
            if k in after and abs(before[k] - after[k]) > 1e-9}


# --------------------------------------------------------------- natural-language edit parsing

# phrase -> (candidate holes in priority order, op, factor). The first hole present in the genome wins.
_PHRASES: tuple[tuple[tuple[str, ...], tuple[str, ...], str, float], ...] = (
    (("thicker", "thicken", "beefier"), ("wall", "bar_thickness", "thickness"), "scale", 1.25),
    (("thinner",), ("wall", "bar_thickness", "thickness"), "scale", 0.8),
    (("taller", "higher", "longer"), ("height", "loop_height"), "scale", 1.2),
    (("shorter",), ("height", "loop_height"), "scale", 0.83),
    (("wider", "fatter"), ("diameter", "width", "loop_width", "radius"), "scale", 1.2),
    (("narrower", "slimmer"), ("diameter", "width", "loop_width", "radius"), "scale", 0.83),
    (("deeper",), ("height", "depth"), "scale", 1.2),
    (("bigger", "larger", "scale up", "scale it up", "grow"), ("*",), "scale", 1.1),
    (("smaller", "scale down", "shrink"), ("*",), "scale", 0.9),
)


def parse_edit(text: str, genome: Genome) -> Edit | None:
    """Map a natural-language edit to a structured `Edit` over this genome's holes (deterministic
    baseline; the LLM handles anything outside these patterns). Returns None if nothing matches."""
    t = text.strip().lower()
    holes = {k.split(".", 1)[1] for k in parameters(genome)}

    # "set X to N" / "X = N" / "make X N mm"
    m = re.search(r"(?:set|make)?\s*([a-z_]+)\s*(?:=|to|at)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:mm)?", t)
    if m and m.group(1) in holes:
        return Edit(m.group(1), "set", float(m.group(2)), note=text.strip())

    # "N% bigger/smaller"
    pct = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%\s*(bigger|larger|smaller)", t)
    if pct:
        f = float(pct.group(1)) / 100.0
        factor = 1.0 + f if pct.group(2) in ("bigger", "larger") else 1.0 - f
        return Edit("*", "scale", round(factor, 4), note=text.strip())

    for words, candidates, op, factor in _PHRASES:
        if any(w in t for w in words):
            if candidates == ("*",):
                return Edit("*", op, factor, note=text.strip())
            hole = next((h for h in candidates if h in holes), None)
            if hole is not None:
                return Edit(hole, op, factor, note=text.strip())
    return None


def edit_genome(genome: Genome, text: str) -> tuple[Genome, Edit | None]:
    """Parse and apply a natural-language edit; return (new genome, the edit) or (unchanged, None)."""
    edit = parse_edit(text, genome)
    return (apply_edit(genome, edit), edit) if edit is not None else (genome, None)


# ---------------------------------------------- open-ended edits (dimensions + texture + geometry)


@dataclass(frozen=True)
class EditResult:
    """An interpreted edit: dimension deltas + an optional new texture pattern + features to add."""

    dim_edits: tuple[Edit, ...] = ()
    pattern: str | None = None        # a new motif name / h(u,v) expression, or None to keep
    add_features: tuple[str, ...] = ()  # e.g. ('fillet',) to round the edges
    note: str = ""

    @property
    def empty(self) -> bool:
        return not (self.dim_edits or self.pattern or self.add_features)


def interpret_edit(text: str, genome: Genome, part=None) -> EditResult:
    """Interpret ANY natural-language edit into structured changes — dimensions, surface texture
    (relief / density / a different motif or a custom function), and geometry (round / bevel edges).
    Deterministic baseline; the LLM is the open-ended path on top. Far beyond a fixed dim parser."""
    t = " " + text.strip().lower() + " "
    holes = {k.split(".", 1)[1] for k in parameters(genome)}
    has_tex = any(h.startswith("pattern_") for h in holes)
    edits: list[Edit] = []
    pattern: str | None = None
    add: list[str] = []

    base = parse_edit(text, genome)            # a plain dimension edit (thicker / bigger / set X)
    if base is not None:
        edits.append(base)

    if has_tex:                                # texture RELIEF
        if any(w in t for w in ("sharper", "bolder", "stronger", "crisper", "pronounced",
                                "spiky", "spikier", "deeper texture", "deeper scale")):
            edits.append(Edit("pattern_depth", "scale", 1.5, note="bolder texture"))
        elif any(w in t for w in ("softer", "subtler", "gentler", "shallower", "flatter",
                                  "smoother texture")):
            edits.append(Edit("pattern_depth", "scale", 0.6, note="softer texture"))
        if any(w in t for w in ("finer", "denser", "tighter", "busier")):  # texture DENSITY
            edits += [Edit("pattern_columns", "scale", 1.4), Edit("pattern_rows", "scale", 1.4)]
        elif any(w in t for w in ("coarser", "sparser", "fewer")):
            edits += [Edit("pattern_columns", "scale", 0.72), Edit("pattern_rows", "scale", 0.72)]

    # a different MOTIF / pattern: a named motif, a common phrase (wave/ripple/spiral/…), or a spiky
    # custom function — covered by the texture phrase resolver
    from .texture import pattern_from_text

    pattern = pattern_from_text(text)

    # GEOMETRY: round / bevel the edges
    if any(w in t for w in ("round", "rounded", "fillet")) and "around" not in t:
        add.append("fillet")
    if any(w in t for w in ("chamfer", "bevel", "bevelled", "beveled")):
        add.append("chamfer")

    return EditResult(tuple(edits), pattern, tuple(add), note=text.strip())


# the geometry features an edit may add (a closed allow-list — the LLM can't invent operations)
_EDIT_FEATURES = {"fillet", "chamfer", "bore", "hole"}


def edit_result_from_llm(candidate: dict, genome: Genome) -> EditResult:
    """Validate an LLM's structured edit into a SAFE `EditResult` — drop any dimension that names an
    unknown hole or a bad op, whitelist the features, and pass the pattern through (resolve_motif /
    compile_field sandbox it). So the open-ended LLM edit can never produce an unsafe operation."""
    holes = {k.split(".", 1)[1] for k in parameters(genome)}
    edits: list[Edit] = []
    for d in candidate.get("dimensions") or []:
        hole, op, val = d.get("hole"), d.get("op"), d.get("value")
        if (hole in holes and op in ("set", "scale", "delta")
                and isinstance(val, (int, float)) and not isinstance(val, bool)):
            edits.append(Edit(hole, op, float(val)))
    pattern = (candidate.get("pattern") or "").strip() or None
    add = tuple(f for f in (candidate.get("add_features") or [])
                if isinstance(f, str) and f.strip().lower() in _EDIT_FEATURES)
    return EditResult(tuple(edits), pattern, add, note=str(candidate.get("message") or ""))
