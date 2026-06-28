"""Specification spine (ADR-011, breakthrough Pillar P0) — the part's intent as checkable obligations.

The whole text-to-CAD field generates geometry and *hopes*. The breakthrough reframe: a design is a
**(specification, model, proof)** triple. This module is the SPECIFICATION half — a typed set of
REQUIREMENTS the part must satisfy, each one a self-contained, deterministically-checkable predicate
``(metric op target)``. The requirements are not a per-object hard-coded list; they are **composed
generally** from the part's functional intent (hollow? opening? bore? attached?) plus its geometry
and chosen process — so the same rules certify a mug, a bracket, an engine cylinder, or anything
else. This is what lets the next module ship a re-checkable certificate of fitness.

A `Requirement` is intentionally tiny and self-describing so a third party can re-evaluate it without
trusting us (the proof-carrying property): the checker and the independent re-checker share ONE
evaluation function (`evaluate`). No kernel/Fusion dependency — pure, offline-verifiable.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..geometry import HollowBox, HollowCylinder, Solid, WithHoles
from .grammar import FeatureType, Genome

# tolerances / defaults the spec leans on
SEAT_TOL_MM = 1.0          # a part "seats" on its host if its gap to the surface is within this
_ATTACHING_PRIMARIES = {FeatureType.LOOP_HANDLE}

_OPS = {">", ">=", "<", "<=", "==", "!="}


# --------------------------------------------------------------------------- the model


@dataclass(frozen=True)
class Requirement:
    """One checkable obligation: ``<metric> <op> <target>``.

    Self-contained so it can be serialized into a certificate and re-evaluated independently.
    ``severity`` "must" gates fitness; "should" is advisory. ``tier`` records the strength of the
    guarantee ("proved" = exact predicate, "tested" = measured, "bounded" = numeric bound).
    """

    id: str
    kind: str            # "geometric" | "functional" | "manufacturing" | "spatial"
    description: str
    metric: str          # evidence key to read
    op: str              # one of _OPS
    target: float | int | bool | str
    severity: str = "must"
    tier: str = "proved"
    provenance: str = ""  # WHY this requirement exists (the intent it came from)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "description": self.description,
                "metric": self.metric, "op": self.op, "target": self.target,
                "severity": self.severity, "tier": self.tier, "provenance": self.provenance}

    @staticmethod
    def from_dict(d: dict) -> Requirement:
        return Requirement(id=d["id"], kind=d["kind"], description=d["description"],
                           metric=d["metric"], op=d["op"], target=d["target"],
                           severity=d.get("severity", "must"), tier=d.get("tier", "proved"),
                           provenance=d.get("provenance", ""))


@dataclass(frozen=True)
class Assumption:
    """One line of the assumption ledger: where a requirement came from, so it is auditable.

    ``source`` is "stated" (the user declared it), "inferred" (an object frame implied it - the
    UNSAID that the understanding layer recovered), or "derived" (computed from geometry/process).
    """

    requirement_id: str
    source: str
    description: str
    provenance: str

    def to_dict(self) -> dict:
        return {"requirement_id": self.requirement_id, "source": self.source,
                "description": self.description, "provenance": self.provenance}


@dataclass(frozen=True)
class Specification:
    """The full set of obligations a part must satisfy to be 'fit', plus the assumption ledger."""

    part_id: str
    requirements: tuple[Requirement, ...]
    object_type: str = ""
    purpose: str = ""
    frame: str = ""
    assumptions: tuple[Assumption, ...] = ()

    def musts(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if r.severity == "must")

    def to_dict(self) -> dict:
        return {"part_id": self.part_id, "object_type": self.object_type, "purpose": self.purpose,
                "frame": self.frame, "requirements": [r.to_dict() for r in self.requirements],
                "assumptions": [a.to_dict() for a in self.assumptions]}

    @staticmethod
    def from_dict(d: dict) -> Specification:
        return Specification(
            part_id=d.get("part_id", ""),
            requirements=tuple(Requirement.from_dict(r) for r in d.get("requirements", [])),
            object_type=d.get("object_type", ""), purpose=d.get("purpose", ""),
            frame=d.get("frame", ""),
            assumptions=tuple(Assumption(a["requirement_id"], a["source"], a["description"],
                                         a["provenance"]) for a in d.get("assumptions", [])))


# --------------------------------------------------------------------- shared evaluation


def evaluate(metric: str, op: str, target, evidence: dict) -> tuple[str, object, float | None]:
    """Evaluate one predicate against the evidence. Used by BOTH the checker and the independent
    re-checker, so a certificate's verdicts are reproducible.

    Returns (status, measured, margin): status in {satisfied, violated, unverifiable}; measured is
    the evidence value (or None if absent -> unverifiable); margin is a signed number where positive
    means 'inside the requirement by this much' and negative 'outside by this much' (None for
    non-numeric comparisons).
    """
    if metric not in evidence:
        return ("unverifiable", None, None)
    measured = evidence[metric]
    numeric = isinstance(measured, (int, float)) and not isinstance(measured, bool) \
        and isinstance(target, (int, float)) and not isinstance(target, bool)

    if op == "==":
        ok = measured == target
        margin = -(abs(measured - target)) if numeric else None
    elif op == "!=":
        ok = measured != target
        margin = None
    elif numeric and op == ">":
        ok, margin = measured > target, float(measured - target)
    elif numeric and op == ">=":
        ok, margin = measured >= target, float(measured - target)
    elif numeric and op == "<":
        ok, margin = measured < target, float(target - measured)
    elif numeric and op == "<=":
        ok, margin = measured <= target, float(target - measured)
    else:
        # a comparison that doesn't apply to these types (e.g. ">" on a string) -> can't verify
        return ("unverifiable", measured, None)
    return ("satisfied" if ok else "violated", measured, margin)


# --------------------------------------------------------------- evidence extraction


def _is_hollow(solid: Solid | None) -> bool:
    return isinstance(solid, (HollowCylinder, HollowBox))


def _capacity_mm3(solid: Solid | None) -> float | None:
    """Usable internal cavity volume of a hollow vessel (what it can hold), else None.

    General over the hollow primitives: the cavity is the inner cross-section times the cavity
    height (which depends on which ends are open/closed)."""
    import math
    if isinstance(solid, HollowCylinder):
        inner_r = max(0.0, solid.outer_radius - solid.wall)
        z0 = 0.0 if solid.open_bottom else solid.wall
        z1 = solid.height if solid.open_top else solid.height - solid.wall
        return math.pi * inner_r * inner_r * max(0.0, z1 - z0)
    if isinstance(solid, HollowBox):
        iw = max(0.0, solid.width - 2 * solid.wall)
        idp = max(0.0, solid.depth - 2 * solid.wall)
        z0 = 0.0 if solid.open_bottom else solid.wall
        z1 = solid.height if solid.open_top else solid.height - solid.wall
        return iw * idp * max(0.0, z1 - z0)
    return None


def _opening_built(solid: Solid | None) -> str | None:
    """The opening actually built into a hollow solid: 'top'/'bottom'/'both'/'none' (else None)."""
    if not isinstance(solid, (HollowCylinder, HollowBox)):
        return None
    top, bottom = solid.open_top, solid.open_bottom
    if top and bottom:
        return "both"
    if top:
        return "top"
    if bottom:
        return "bottom"
    return "none"


def _wall_mm(solid: Solid | None) -> float | None:
    w = getattr(solid, "wall", None)
    return float(w) if isinstance(w, (int, float)) else None


def _has_bore(genome: Genome, solid: Solid | None) -> bool:
    if any(f.type is FeatureType.BORE for f in genome.features):
        return True
    return isinstance(solid, WithHoles)


def _attaches(part, genome: Genome) -> bool:
    if getattr(part, "attachment", None) is not None:
        return True
    primary = genome.primary
    return bool(primary and primary.type in _ATTACHING_PRIMARIES)


def _stability_ratio(solid: Solid | None) -> float | None:
    """Footprint-to-height ratio: min(base extent) / height. A proxy for tip stability (a tall, thin
    object tips easily). General over any solid via its bounding box."""
    if solid is None:
        return None
    bx, by, bz = solid.bbox_mm
    if bz <= 0:
        return None
    return round(min(bx, by) / bz, 4)


def _handle_aperture_mm(genome: Genome) -> float | None:
    """The clear opening a loop handle offers the fingers (min inner span), from the genome holes."""
    primary = genome.primary
    if primary is None or primary.type is not FeatureType.LOOP_HANDLE:
        return None
    from .library import resolved

    h = resolved(primary)
    return round(min(h["loop_width"], h["loop_height"]) - 2.0 * h["bar_thickness"], 4)


def evidence(part, genome: Genome, solid: Solid | None, *, process: str = "fdm",
             seat_gap_mm: float | None = None) -> dict:
    """Measured/derived facts about the realized part — the WITNESS the certificate is checked
    against. Pulled from the analytic kernel solid (the intent) offline; the live read-back supplies
    the same keys from the actual Fusion model. General over all solid types."""
    ev: dict = {"process": process}
    if solid is not None:
        ev["volume_mm3"] = round(solid.volume_mm3, 4)
        bx, by, bz = solid.bbox_mm
        ev["bbox_x_mm"], ev["bbox_y_mm"], ev["bbox_z_mm"] = round(bx, 4), round(by, 4), round(bz, 4)
    ev["is_hollow"] = _is_hollow(solid)
    cap = _capacity_mm3(solid)
    if cap is not None:
        ev["capacity_mm3"] = round(cap, 4)
    wall = _wall_mm(solid)
    if wall is not None:
        ev["wall_mm"] = wall
    opened = _opening_built(solid)
    if opened is not None:
        ev["opening"] = opened
    ev["has_bore"] = _has_bore(genome, solid)
    ratio = _stability_ratio(solid)
    if ratio is not None:
        ev["stability_ratio"] = ratio
    aperture = _handle_aperture_mm(genome)
    if aperture is not None:
        ev["handle_aperture_mm"] = aperture
    seated = None
    if seat_gap_mm is not None:
        ev["seat_gap_mm"] = round(float(seat_gap_mm), 4)
        seated = float(seat_gap_mm) <= SEAT_TOL_MM
    # qualitative behaviour facts (ADR-013): does the function's flow chain physically close?
    opened = ev.get("opening")
    ev["cavity_reachable"] = bool(ev.get("is_hollow") and opened not in (None, "none")
                                  and ev.get("capacity_mm3", 0) > 0)
    ev["through_connected"] = bool(opened == "both" or ev.get("has_bore"))
    ev["has_coupling"] = bool(ev.get("has_bore") or seated)
    return ev


# --------------------------------------------------------------- requirement derivation


def derive_specification(part, genome: Genome, solid: Solid | None, *,
                         process: str = "fdm") -> Specification:
    """Compose the requirement set GENERALLY from the part's functional intent + geometry + process.

    This is the anti-'keyword list' move: requirements follow from PROPERTIES (is it hollow? what
    opening does its function need? is it attached? what process?), so any object is specified by the
    same rules. The result is the contract the certificate proves the model against.
    """
    from .dfm import PROCESSES

    pid = getattr(part, "id", None) or getattr(part, "name", None) or "part"
    purpose = (getattr(part, "purpose", "") or "")
    otype = (getattr(part, "object_type", "") or "")
    reqs: list[Requirement] = []

    # -- geometric: it must be a real, positive-volume solid that fits its envelope --------------
    if solid is not None:
        reqs.append(Requirement(f"{pid}.geom.solid", "geometric",
                                "is a real solid with positive material volume",
                                "volume_mm3", ">", 0.0, "must", "proved", "valid geometry"))

    # -- functional: composed from the declared FUNCTION (generalises unmet_requirements) --------
    if bool(getattr(part, "hollow", False)):
        reqs.append(Requirement(f"{pid}.func.hollow", "functional",
                                "is hollow — has an internal cavity",
                                "is_hollow", "==", True, "must", "proved", "declared hollow"))
        reqs.append(Requirement(f"{pid}.func.capacity", "functional",
                                "the cavity can actually hold contents (capacity > 0)",
                                "capacity_mm3", ">", 0.0, "must", "proved", "a vessel must contain"))
    want_open = (getattr(part, "opening", "") or "").strip().lower()
    if want_open:
        reqs.append(Requirement(f"{pid}.func.opening", "functional",
                                f"opening is {want_open!r}, as its function requires",
                                "opening", "==", want_open, "must", "proved",
                                f"function needs a {want_open} opening"))
    if bool(getattr(part, "bore", False)):
        reqs.append(Requirement(f"{pid}.func.bore", "functional",
                                "has the required central bore (through-hole)",
                                "has_bore", "==", True, "must", "proved", "declared bore"))

    # -- manufacturing: composed from the chosen process -----------------------------------------
    if _wall_mm(solid) is not None:
        proc = PROCESSES.get(process, PROCESSES["fdm"])
        reqs.append(Requirement(f"{pid}.mfg.min_wall", "manufacturing",
                                f"wall is manufacturable by {proc.name} (>= {proc.min_wall_mm:g} mm)",
                                "wall_mm", ">=", proc.min_wall_mm, "must", "proved",
                                f"process={proc.name}"))

    # -- spatial: an attached part must SEAT on its host (generalises the spatial certificate) ----
    if _attaches(part, genome):
        reqs.append(Requirement(f"{pid}.spatial.seated", "spatial",
                                "seats on its host surface (gap ~ 0, not floating)",
                                "seat_gap_mm", "<=", SEAT_TOL_MM, "must", "tested",
                                "an attached part must contact its host"))

    # -- understanding (ADR-012): merge the requirements the object's FRAME implies (the unsaid) ----
    from .function_model import behavior_requirements
    from .understanding import expand

    exp = expand(part, genome)
    by_id = {r.id: r for r in reqs}                 # explicitly-derived requirements win on collision
    for fr in exp.requirements:
        by_id.setdefault(fr.id, fr)
    # -- function gate (ADR-013): the behaviour obligations the part's FUNCTION must realise --------
    for br in behavior_requirements(part, genome):
        by_id.setdefault(br.id, br)
    # -- open-ended understanding (ADR-015): requirements the model FORMALISED from intent ----------
    from .intent_expand import proposals_to_requirements

    for er in proposals_to_requirements(part):
        by_id.setdefault(er.id, er)
    final = tuple(by_id.values())
    ledger = tuple(Assumption(r.id, _source(r, part), r.description, r.provenance) for r in final)
    return Specification(part_id=pid, requirements=final, object_type=otype, purpose=purpose,
                         frame=exp.frame, assumptions=ledger)


def _source(req: Requirement, part) -> str:
    """Classify where a requirement came from for the assumption ledger (stated/inferred/derived)."""
    suffix = req.id.split(".", 1)[1] if "." in req.id else req.id
    if suffix == "func.hollow":
        return "stated" if bool(getattr(part, "hollow", False)) else "inferred"
    if suffix == "func.opening":
        return "stated" if (getattr(part, "opening", "") or "").strip() else "inferred"
    if suffix == "func.bore":
        return "stated" if bool(getattr(part, "bore", False)) else "inferred"
    if suffix in ("geom.solid", "func.capacity", "mfg.min_wall", "spatial.seated"):
        return "derived"
    return "inferred"  # erg.*, useful_capacity, food_safe_wall, frame-inferred openings, etc.
