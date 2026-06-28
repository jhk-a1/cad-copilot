"""The Design-Genome grammar (ADR-007) — a typed, CLOSED feature vocabulary.

The LLM (or the deterministic planner) emits a `Genome`: an ordered list of typed `Feature`s with
HOLES (named dimensions with defaults + bounds) instead of raw geometry. The grammar is *closed*:

  * a genome has exactly ONE primary feature (it creates the body), and it comes first;
  * every other feature is a MODIFIER applied to that body;
  * a feature's params must be a subset of the holes its type declares — unknown params are
    rejected, missing ones are defaulted.

So an invalid feature tree is (largely) unrepresentable. Compilation (`compiler.py`) turns a genome
into the validated Command IR, with every hole a `CREATE_USER_PARAMETER` the user can dimension.

This module is the data model + closure validation only. Feasibility of VALUES (wall < radius, …)
is the solver/CEGIS gate's job (`solver.py`, `cegis.py`); building geometry is `library.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field

from ...models.common import StrictModel


class FeatureType(StrEnum):
    # primaries (each creates the part's body)
    SOLID_BOX = "solid_box"
    HOLLOW_BOX = "hollow_box"
    SOLID_CYLINDER = "solid_cylinder"
    HOLLOW_CYLINDER = "hollow_cylinder"
    L_BRACKET = "l_bracket"
    LOOP_HANDLE = "loop_handle"
    # general primitives — the vocabulary the LLM composes for ANY shape (not an object list)
    CONE = "cone"
    PRISM = "prism"
    SPHERE = "sphere"
    TORUS = "torus"
    WEDGE = "wedge"
    LOFT = "loft"
    SWEEP = "sweep"
    # modifiers (refine the body)
    SURFACE_PATTERN = "surface_pattern"
    FILLET = "fillet"
    CHAMFER = "chamfer"
    BORE = "bore"  # a central axial through-hole (engine cylinder, bushing, spacer)


@dataclass(frozen=True)
class HoleSpec:
    """One dimensionable hole: a named parameter with a default and feasible bounds."""

    name: str
    default: float
    lo: float
    hi: float
    integer: bool = False


@dataclass(frozen=True)
class FeatureSpec:
    primary: bool
    holes: tuple[HoleSpec, ...]

    @property
    def hole_names(self) -> set[str]:
        return {h.name for h in self.holes}

    def hole(self, name: str) -> HoleSpec | None:
        return next((h for h in self.holes if h.name == name), None)


def _h(name: str, default: float, lo: float, hi: float, integer: bool = False) -> HoleSpec:
    return HoleSpec(name, default, lo, hi, integer)


# The closed vocabulary. Hole names are globally distinctive (so a part's user-parameter names,
# f"{part_id}_{hole}", never clash and humanize into clear dimension labels).
FEATURE_SPECS: dict[FeatureType, FeatureSpec] = {
    FeatureType.SOLID_BOX: FeatureSpec(True, (
        _h("length", 50, 0.1, 5000), _h("width", 30, 0.1, 5000), _h("height", 20, 0.1, 5000))),
    FeatureType.HOLLOW_BOX: FeatureSpec(True, (
        _h("length", 80, 0.5, 5000), _h("width", 60, 0.5, 5000), _h("height", 50, 0.5, 5000),
        _h("wall", 3, 0.2, 500))),
    FeatureType.SOLID_CYLINDER: FeatureSpec(True, (
        _h("diameter", 25, 0.1, 5000), _h("height", 40, 0.1, 5000))),
    FeatureType.HOLLOW_CYLINDER: FeatureSpec(True, (
        _h("diameter", 80, 0.5, 5000), _h("height", 95, 0.5, 5000), _h("wall", 4, 0.2, 500))),
    FeatureType.L_BRACKET: FeatureSpec(True, (
        _h("leg_a", 50, 0.5, 5000), _h("leg_b", 30, 0.5, 5000),
        _h("thickness", 5, 0.2, 500), _h("depth", 40, 0.5, 5000))),
    FeatureType.LOOP_HANDLE: FeatureSpec(True, (
        _h("loop_width", 35, 1, 2000), _h("loop_height", 80, 1, 2000),
        _h("bar_thickness", 9, 0.5, 500), _h("loop_depth", 10, 0.5, 500))),
    FeatureType.CONE: FeatureSpec(True, (
        _h("bottom_diameter", 50, 0.5, 5000), _h("top_diameter", 25, 0.1, 5000),
        _h("height", 50, 0.5, 5000))),
    FeatureType.PRISM: FeatureSpec(True, (
        _h("sides", 6, 3, 24, integer=True), _h("radius", 20, 0.5, 2500),
        _h("height", 50, 0.5, 5000))),
    FeatureType.SPHERE: FeatureSpec(True, (_h("diameter", 40, 0.5, 5000),)),
    FeatureType.TORUS: FeatureSpec(True, (
        _h("ring_diameter", 50, 1, 5000), _h("tube_diameter", 12, 0.5, 2000))),
    FeatureType.WEDGE: FeatureSpec(True, (
        _h("width", 50, 0.5, 5000), _h("depth", 40, 0.5, 5000), _h("height", 30, 0.5, 5000))),
    FeatureType.LOFT: FeatureSpec(True, (
        _h("bottom_diameter", 50, 0.5, 5000), _h("top_width", 40, 0.5, 5000),
        _h("top_depth", 40, 0.5, 5000), _h("height", 60, 0.5, 5000))),
    FeatureType.SWEEP: FeatureSpec(True, (
        _h("profile_diameter", 12, 0.3, 2000), _h("bend_radius", 40, 1, 5000),
        _h("bend_angle", 90, 1, 360))),
    FeatureType.SURFACE_PATTERN: FeatureSpec(False, (
        _h("pattern_columns", 16, 1, 512, integer=True),
        _h("pattern_rows", 6, 1, 256, integer=True),
        _h("pattern_size", 10, 0.2, 500),
        _h("pattern_depth", 1.5, 0.05, 200),
        _h("pattern_row_spacing", 12, 0.2, 1000))),
    FeatureType.FILLET: FeatureSpec(False, (_h("fillet_radius", 3, 0.05, 500),)),
    FeatureType.CHAMFER: FeatureSpec(False, (_h("chamfer_size", 1.5, 0.05, 500),)),
    FeatureType.BORE: FeatureSpec(False, (_h("bore_diameter", 10, 0.2, 4000),)),
}

PRIMARY_TYPES = {t for t, s in FEATURE_SPECS.items() if s.primary}
MODIFIER_TYPES = {t for t, s in FEATURE_SPECS.items() if not s.primary}


class Feature(StrictModel):
    """One typed feature with hole values. Unspecified holes are defaulted by the solver."""

    id: str = Field(..., description="Stable feature id, unique within the genome")
    type: FeatureType
    params: dict[str, float] = Field(default_factory=dict, description="hole name -> value")
    options: dict[str, str] = Field(
        default_factory=dict,
        description="Non-numeric FUNCTIONAL aspects that change topology, not size. Notably "
        "'opening' for hollow vessels: 'top' (cup/mug/bowl), 'bottom', 'both' (pipe/tube), 'none' "
        "(sealed). Function determines topology, so the part actually serves its purpose.",
    )
    anchor: str | None = Field(
        default=None,
        description="Intent-named attachment (e.g. 'side_wall'). Records design intent for the "
        "edit-propagation moat; v1 realizes placement via the part's assembly position.",
    )


class Genome(StrictModel):
    """A correct-by-construction feature program for ONE part."""

    part_id: str
    features: list[Feature] = Field(default_factory=list)

    @property
    def primary(self) -> Feature | None:
        return next((f for f in self.features if FEATURE_SPECS[f.type].primary), None)


def validate_genome(genome: Genome) -> list[str]:
    """Closure check: return a list of structural errors ([] means well-formed).

    Guarantees the *shape* of the tree (one primary first, modifiers after, known holes only).
    VALUE feasibility is the solver/CEGIS gate, not here.
    """
    errors: list[str] = []
    feats = genome.features
    if not feats:
        return ["genome has no features"]

    ids: set[str] = set()
    for f in feats:
        if f.id in ids:
            errors.append(f"duplicate feature id {f.id!r}")
        ids.add(f.id)

    primaries = [f for f in feats if FEATURE_SPECS[f.type].primary]
    if len(primaries) == 0:
        errors.append("genome has no primary feature (needs exactly one body-creating feature)")
    elif len(primaries) > 1:
        errors.append(f"genome has {len(primaries)} primary features; exactly one is allowed")
    elif not FEATURE_SPECS[feats[0].type].primary:
        errors.append("the primary feature must come first")

    for f in feats:
        spec = FEATURE_SPECS[f.type]
        for k in f.params:
            if k not in spec.hole_names:
                errors.append(f"feature {f.id!r} ({f.type}) has unknown hole {k!r}")
    return errors
