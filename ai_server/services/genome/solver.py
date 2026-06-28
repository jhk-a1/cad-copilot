"""Hole solver — fill a genome's holes and keep them on the feasible manifold (ADR-007).

This is the "fill the holes" half of the synthesis analogy: the LLM/planner proposes which feature
and rough values; the solver resolves every hole (user value > existing > spec default) and then
enforces feasibility (the EDA design-rule-check half): clamp each hole to its bounds, and apply the
cross-hole rules that keep geometry buildable (a shell wall thinner than the radius, a fillet smaller
than the body, a surface dimple shallower than the wall). Each clamp is reported as a *counterexample*
note so the CEGIS loop (and the user) can see exactly what was repaired — convergence, not silent
coercion.
"""

from __future__ import annotations

from .grammar import FEATURE_SPECS, Feature, FeatureType, Genome


def _primary_extent(genome: Genome) -> float:
    """The smallest characteristic dimension of the body — the budget for fillets/chamfers/dimples."""
    pf = genome.primary
    if pf is None:
        return 0.0
    p = _filled(pf)
    t = pf.type
    if t in (FeatureType.SOLID_BOX, FeatureType.HOLLOW_BOX):
        return min(p["length"], p["width"], p["height"])
    if t in (FeatureType.SOLID_CYLINDER, FeatureType.HOLLOW_CYLINDER):
        return min(p["diameter"], p["height"])
    if t is FeatureType.L_BRACKET:
        return min(p["leg_a"], p["leg_b"], p["depth"])
    if t is FeatureType.LOOP_HANDLE:
        return min(p["loop_width"], p["loop_height"], p["loop_depth"])
    if t is FeatureType.CONE:
        return min(p["bottom_diameter"], p["top_diameter"], p["height"])
    if t is FeatureType.PRISM:
        return min(2 * p["radius"], p["height"])
    if t is FeatureType.SPHERE:
        return p["diameter"]
    if t is FeatureType.TORUS:
        return p["tube_diameter"]
    if t is FeatureType.WEDGE:
        return min(p["width"], p["depth"], p["height"])
    if t is FeatureType.LOFT:
        return min(p["bottom_diameter"], p["top_width"], p["top_depth"], p["height"])
    if t is FeatureType.SWEEP:
        return min(p["profile_diameter"], p["bend_radius"])
    return 0.0


def _primary_wall(genome: Genome) -> float | None:
    pf = genome.primary
    if pf is not None and pf.type in (FeatureType.HOLLOW_BOX, FeatureType.HOLLOW_CYLINDER):
        return _filled(pf).get("wall")
    return None


def _filled(feature: Feature) -> dict[str, float]:
    spec = FEATURE_SPECS[feature.type]
    out = {h.name: h.default for h in spec.holes}
    out.update({k: float(v) for k, v in feature.params.items() if k in out})
    return out


def solve(genome: Genome, holes: dict[str, float]) -> tuple[Genome, list[str]]:
    """Resolve + clamp all holes. `holes` maps hole NAME (prefix already stripped) -> user value.

    Returns (solved genome, counterexample notes). Notes are human-readable repair records.
    """
    notes: list[str] = []

    # 1. resolve: user value overrides existing param overrides default
    resolved_feats: list[Feature] = []
    for f in genome.features:
        spec = FEATURE_SPECS[f.type]
        vals = {h.name: h.default for h in spec.holes}
        vals.update({k: float(v) for k, v in f.params.items() if k in vals})
        for h in spec.holes:
            if h.name in holes:
                vals[h.name] = float(holes[h.name])
        # 2. clamp each hole to its bounds (+ integer rounding)
        for h in spec.holes:
            v = vals[h.name]
            if h.integer:
                v = float(round(v))
            cv = min(max(v, h.lo), h.hi)
            if cv != v:
                notes.append(f"{f.id}.{h.name}: {v:g} -> {cv:g} (out of [{h.lo:g}, {h.hi:g}])")
            vals[h.name] = cv
        resolved_feats.append(f.model_copy(update={"params": vals}))

    solved = genome.model_copy(update={"features": resolved_feats})

    # 3. cross-hole feasibility (the DRC rules that keep geometry buildable)
    extent = _primary_extent(solved)
    wall = _primary_wall(solved)
    repaired: list[Feature] = []
    for f in solved.features:
        vals = dict(f.params)
        if f.type in (FeatureType.HOLLOW_CYLINDER, FeatureType.HOLLOW_BOX):
            cap = 0.45 * extent
            if vals["wall"] > cap:
                notes.append(f"{f.id}.wall: {vals['wall']:g} -> {cap:.3g} (must be < 0.45x body)")
                vals["wall"] = round(cap, 4)
        elif f.type is FeatureType.LOOP_HANDLE:
            cap = 0.45 * min(vals["loop_width"], vals["loop_height"])
            if vals["bar_thickness"] > cap:
                notes.append(f"{f.id}.bar_thickness: {vals['bar_thickness']:g} -> {cap:.3g}"
                             " (must be < 0.45x loop)")
                vals["bar_thickness"] = round(cap, 4)
        elif f.type is FeatureType.FILLET:
            cap = 0.49 * extent
            if extent > 0 and vals["fillet_radius"] > cap:
                notes.append(f"{f.id}.fillet_radius: {vals['fillet_radius']:g} -> {cap:.3g}"
                             " (must be < 0.49x body)")
                vals["fillet_radius"] = round(cap, 4)
        elif f.type is FeatureType.CHAMFER:
            cap = 0.49 * extent
            if extent > 0 and vals["chamfer_size"] > cap:
                notes.append(f"{f.id}.chamfer_size: {vals['chamfer_size']:g} -> {cap:.3g}"
                             " (must be < 0.49x body)")
                vals["chamfer_size"] = round(cap, 4)
        elif f.type is FeatureType.SURFACE_PATTERN and wall is not None:
            cap = 0.8 * wall
            if vals["pattern_depth"] > cap:
                notes.append(f"{f.id}.pattern_depth: {vals['pattern_depth']:g} -> {cap:.3g}"
                             " (must not pierce the wall)")
                vals["pattern_depth"] = round(cap, 4)
        repaired.append(f.model_copy(update={"params": vals}))

    return solved.model_copy(update={"features": repaired}), notes
