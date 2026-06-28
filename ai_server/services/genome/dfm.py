"""Manufacturability, fit & mobility gates (ADR-010, Pillars C+D) — pre-empting the failures that
complex, real objects raise BEFORE they reach Fusion.

The Design-Genome already refuses geometry whose *purpose* is unmet. As objects gain mating parts,
mechanisms and manufacturing intent, "valid solid" is no longer "good part". The cross-domain
research (DFM/GD&T; ISO-286 fits; mechanical constraint solving / Grübler–Kutzbach) gives three more
checkable gates, all pure functions of the genome's parameters — so they run offline, with no kernel:

  * **Manufacturability** — process-physical predicates (min wall, min feature, internal radius,
    draft) as inequalities. An unmoldable / unmachinable part is flagged with a numeric margin.
  * **Fit** — ISO-286 limits-and-fits: does a hole+shaft pair actually assemble with the intended
    clearance/interference? Tolerances computed from the standard IT formula (reproduces the
    textbook tables), so "will an H7/g6 Ø20 slide?" gets a correct yes with the clearance band.
  * **Mobility** — Grübler–Kutzbach + loop counting on the mate graph: is the assembly a rigid
    structure (M=0), a mechanism (M≥1), or over-constrained (M<0)? Tree-by-tree placement silently
    breaks on kinematic LOOPS (a four-bar, a hinge) — this names them before we build.

Everything here is advisory-or-refusing in the same spirit as the functional gate, and fully
offline-testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ===========================================================================================
# Manufacturability (DFM)
# ===========================================================================================


@dataclass(frozen=True)
class Process:
    """A manufacturing process and its hard geometric limits (mm / deg). Defaults are conservative
    industry rules of thumb (Bralla; Boothroyd-Dewhurst; common 3D-print/CNC guidance)."""

    name: str
    min_wall_mm: float
    min_feature_mm: float
    min_internal_radius_mm: float
    needs_draft: bool
    min_draft_deg: float


PROCESSES: dict[str, Process] = {
    "fdm": Process("fdm", min_wall_mm=0.8, min_feature_mm=0.8, min_internal_radius_mm=0.0,
                   needs_draft=False, min_draft_deg=0.0),
    "resin": Process("resin", min_wall_mm=0.5, min_feature_mm=0.3, min_internal_radius_mm=0.0,
                     needs_draft=False, min_draft_deg=0.0),
    "cnc": Process("cnc", min_wall_mm=0.8, min_feature_mm=0.5, min_internal_radius_mm=0.5,
                   needs_draft=False, min_draft_deg=0.0),
    "injection": Process("injection", min_wall_mm=1.0, min_feature_mm=0.5, min_internal_radius_mm=0.5,
                         needs_draft=True, min_draft_deg=0.5),
}


@dataclass(frozen=True)
class Finding:
    """One manufacturability check: severity in {ok, warn, fail} with a numeric margin where it
    makes sense (negative margin = how far INTO violation)."""

    rule: str
    severity: str
    message: str
    margin_mm: float | None = None


@dataclass
class DfmCertificate:
    process: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.severity == "fail" for f in self.findings)

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    def summary(self) -> str:
        fails = [f for f in self.findings if f.severity == "fail"]
        if fails:
            return "DFM FAIL (" + self.process + ") - " + "; ".join(f.message for f in fails)
        warns = self.warnings
        if warns:
            return "DFM OK (" + self.process + ") with warnings - " + "; ".join(f.message for f in warns)
        return "DFM OK (" + self.process + ") - all checks pass"


def manufacturability_certificate(*, process: str = "fdm", wall_mm: float | None = None,
                                  min_feature_mm: float | None = None,
                                  internal_radius_mm: float | None = None,
                                  draft_deg: float | None = None) -> DfmCertificate:
    """Check the genome's makeability against a process. Each argument is a measured/derived genome
    quantity; ``None`` means "not applicable to this part" and is skipped (not a failure)."""
    proc = PROCESSES.get(process, PROCESSES["fdm"])
    cert = DfmCertificate(process=proc.name)

    if wall_mm is not None:
        margin = round(wall_mm - proc.min_wall_mm, 4)
        cert.findings.append(Finding(
            "min_wall", "ok" if margin >= 0 else "fail",
            f"wall {wall_mm:g}mm vs min {proc.min_wall_mm:g}mm", margin))
    if min_feature_mm is not None:
        margin = round(min_feature_mm - proc.min_feature_mm, 4)
        cert.findings.append(Finding(
            "min_feature", "ok" if margin >= 0 else "fail",
            f"feature {min_feature_mm:g}mm vs min {proc.min_feature_mm:g}mm", margin))
    if internal_radius_mm is not None and proc.min_internal_radius_mm > 0:
        margin = round(internal_radius_mm - proc.min_internal_radius_mm, 4)
        # a sharp internal corner is a WARN for CNC (needs a tool radius), not an outright fail
        sev = "ok" if margin >= 0 else ("warn" if process == "cnc" else "fail")
        cert.findings.append(Finding(
            "internal_radius", sev,
            f"internal radius {internal_radius_mm:g}mm vs min {proc.min_internal_radius_mm:g}mm", margin))
    if proc.needs_draft:
        d = draft_deg or 0.0
        margin = round(d - proc.min_draft_deg, 4)
        cert.findings.append(Finding(
            "draft", "ok" if margin >= 0 else "warn",
            f"draft {d:g}deg vs min {proc.min_draft_deg:g}deg for {proc.name}", margin))
    return cert


# ===========================================================================================
# ISO-286 limits & fits
# ===========================================================================================

# standard size bands (mm), upper bound exclusive at the boundary per ISO convention
_SIZE_BANDS = [(0, 3), (3, 6), (6, 10), (10, 18), (18, 30), (30, 50), (50, 80),
               (80, 120), (120, 180), (180, 250), (250, 315), (315, 400), (400, 500)]
# IT grade -> multiple of the standard tolerance factor i (ISO 286, grades IT5..IT12)
_IT_MULT = {5: 7, 6: 10, 7: 16, 8: 25, 9: 40, 10: 64, 11: 100, 12: 160}


def _band(nominal_mm: float) -> tuple[float, float]:
    for lo, hi in _SIZE_BANDS:
        if lo < nominal_mm <= hi:
            return (lo, hi)
    return _SIZE_BANDS[-1]


def _D(nominal_mm: float) -> float:
    lo, hi = _band(nominal_mm)
    lo = lo or 1.0  # the 0-3 band uses ~1mm as its geometric-mean lower bound (ISO convention)
    return math.sqrt(lo * hi)


def it_tolerance_um(nominal_mm: float, grade: int) -> float:
    """The IT-grade tolerance in microns, from the ISO-286 standard tolerance factor
    i = 0.45*cbrt(D) + 0.001*D. Reproduces the published IT tables (e.g. IT7@Ø20 = 21µm)."""
    D = _D(nominal_mm)
    i = 0.45 * D ** (1.0 / 3.0) + 0.001 * D
    return round(_IT_MULT[grade] * i)


def _shaft_fundamental_dev_um(nominal_mm: float, letter: str, grade: int) -> float:
    """Fundamental deviation (microns) for a shaft tolerance position (ISO 286-1 formulas).

    Clearance letters give the UPPER deviation es (<=0); transition/interference letters give the
    LOWER deviation ei (>=0). Returns the *fundamental* (zero-line-nearest) deviation; the other
    bound is one IT grade away."""
    D = _D(nominal_mm)
    upper = {  # es (negative), clearance side
        "h": 0.0,
        "g": -2.5 * D ** 0.34,
        "f": -5.5 * D ** 0.41,
        "e": -11.0 * D ** 0.41,
        "d": -16.0 * D ** 0.44,
    }
    if letter in upper:
        return round(upper[letter])
    lower = {  # ei (positive), interference / transition side
        "k": 0.6 * D ** (1.0 / 3.0),
        "n": 5.0 * D ** 0.34,
        "p": it_tolerance_um(nominal_mm, 7) + 0.0,  # p ~ +IT7 above the zero line (hole-basis press)
    }
    if letter in lower:
        return round(lower[letter])
    raise ValueError(f"shaft letter {letter!r} not supported (have h,g,f,e,d,k,n,p)")


@dataclass(frozen=True)
class Fit:
    nominal_mm: float
    hole: str          # e.g. "H7"
    shaft: str         # e.g. "g6"
    hole_limits_um: tuple[float, float]   # (lower, upper) deviation in microns
    shaft_limits_um: tuple[float, float]
    min_clearance_um: float   # +ve = clearance, -ve = interference
    max_clearance_um: float
    kind: str          # "clearance" | "transition" | "interference"

    def summary(self) -> str:
        return (f"{self.hole}/{self.shaft} Ø{self.nominal_mm:g}: {self.kind} fit, "
                f"clearance {self.min_clearance_um:g}..{self.max_clearance_um:g} µm")


def iso_fit(nominal_mm: float, hole: str = "H7", shaft: str = "g6") -> Fit:
    """Classify a hole-basis ISO-286 fit and return its clearance band (microns).

    Only hole letter 'H' (EI=0) is supported (the standard hole-basis system). Shaft letters:
    h,g,f,e,d (clearance) and k,n,p (transition/interference). Reproduces textbook values, e.g.
    H7/g6 Ø20 -> clearance 7..41 µm.
    """
    if not hole.startswith("H"):
        raise ValueError("only hole-basis fits (hole letter 'H') are supported")
    hole_grade = int(hole[1:])
    sletter, shaft_grade = shaft[0], int(shaft[1:])
    hole_it = it_tolerance_um(nominal_mm, hole_grade)
    shaft_it = it_tolerance_um(nominal_mm, shaft_grade)
    hole_lo, hole_hi = 0.0, float(hole_it)                  # H: EI=0, ES=+IT
    fund = _shaft_fundamental_dev_um(nominal_mm, sletter, shaft_grade)
    if sletter in ("h", "g", "f", "e", "d"):               # es is the fundamental (<=0)
        shaft_hi = fund
        shaft_lo = fund - shaft_it
    else:                                                  # ei is the fundamental (>=0)
        shaft_lo = fund
        shaft_hi = fund + shaft_it
    min_clear = round(hole_lo - shaft_hi)                  # tightest: smallest hole, largest shaft
    max_clear = round(hole_hi - shaft_lo)                  # loosest: largest hole, smallest shaft
    if min_clear >= 0:
        kind = "clearance"
    elif max_clear <= 0:
        kind = "interference"
    else:
        kind = "transition"
    return Fit(nominal_mm, hole, shaft, (hole_lo, hole_hi), (shaft_lo, shaft_hi),
               min_clear, max_clear, kind)


# ===========================================================================================
# Mobility / mate-network (Grübler–Kutzbach + loop counting)
# ===========================================================================================

# joint degrees of freedom (relative motion a joint permits between two links)
JOINT_DOF = {
    "fixed": 0, "weld": 0, "rigid": 0,
    "revolute": 1, "pin": 1, "hinge": 1, "prismatic": 1, "slider": 1, "helical": 1, "screw": 1,
    "cylindrical": 2,
    "planar": 3, "spherical": 3, "ball": 3,
    "point": 5,
}


@dataclass(frozen=True)
class Joint:
    a: str            # link id
    b: str            # link id
    kind: str         # see JOINT_DOF


@dataclass
class MobilityCertificate:
    mobility: int     # M (Grübler–Kutzbach)
    links: int        # n (including ground)
    joints: int       # j
    loops: int        # independent kinematic loops
    classification: str  # "structure" | "mechanism" | "over-constrained"
    ok: bool
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        base = (f"mobility M={self.mobility} ({self.classification}); "
                f"{self.links} links, {self.joints} joints, {self.loops} loop(s)")
        return base + (" - " + "; ".join(self.notes) if self.notes else "")


def _components(links: set[str], joints: list[Joint]) -> int:
    parent = {n: n for n in links}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for j in joints:
        if j.a in parent and j.b in parent:
            parent[find(j.a)] = find(j.b)
    return len({find(n) for n in links})


def analyze_mechanism(links: set[str], joints: list[Joint], *, planar: bool = False,
                      expected: str = "structure") -> MobilityCertificate:
    """Grübler–Kutzbach mobility + loop analysis of a mate network.

    ``links`` includes ground; ``expected`` in {"structure","mechanism"} sets what "ok" means. A
    structure should be M=0 (rigid); a mechanism should be M≥1. M<0 is over-constrained (the
    tree-based one-by-one placer would silently fail or freeze a mechanism solid). Loops are the
    cyclomatic number of the mate graph — any loop is where naive tree placement breaks (a four-bar,
    a hinge), and must be solved by simultaneous loop closure.
    """
    n = len(links)
    j = len(joints)
    f_sum = sum(JOINT_DOF.get(jt.kind, 1) for jt in joints)
    dof_per_body = 3 if planar else 6
    mobility = dof_per_body * (n - 1 - j) + f_sum
    comps = _components(links, joints)
    loops = j - n + comps  # cyclomatic number (per-component sum)

    notes: list[str] = []
    if mobility < 0:
        classification = "over-constrained"
        notes.append(f"{-mobility} redundant constraint(s) — remove a mate or relax a fit")
    elif mobility == 0:
        classification = "structure"
    else:
        classification = "mechanism"
        notes.append(f"{mobility} degree(s) of freedom of motion")
    if loops > 0:
        notes.append(f"{loops} kinematic loop(s) need simultaneous loop closure (not tree placement)")
    if comps > 1:
        notes.append(f"{comps} disconnected component(s) — {comps - 1} part(s) not attached to ground")

    ok = (classification == "structure") if expected == "structure" else (mobility >= 1)
    if comps > 1 and expected == "structure":
        ok = False
    return MobilityCertificate(mobility, n, j, max(0, loops), classification, ok, notes)
