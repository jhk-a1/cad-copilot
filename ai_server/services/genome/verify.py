"""Spatial comparator (ADR-009) — the closed-loop perception the pipeline was missing.

Seven cross-domain fields (robotics visual servoing, physics contact mechanics, predictive coding /
active inference, and the text-to-CAD SOTA sweep) converged on one thing: a generator cannot trust
its output until it MEASURES the result's spatial RELATIONS against intent and corrects. The whole
"offline-right, live-wrong, blind" pattern comes from checking a body's VOLUME but never whether a
part actually CONTACTS its host or a feature actually sits ON a surface. Physics gives the exact
predicate: a part is correctly seated iff the gap to its host surface is ~0 (not floating) with no
deep interpenetration — the "contact certificate".

This module measures those relations on the analytic kernel, so the engine PERCEIVES whether the
handle seats on the wall and the scales sit on the surface — before it ships geometry blind. It
verifies INTENT (the genome's spatial design); the add-in's live read-back verifies REALITY (Fusion).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..geometry import Box, Cylinder, Frustum, HollowBox, HollowCylinder, Solid

ON_SURFACE_TOL_MM = 0.6  # within this of the surface counts as "seated / on-surface"


@dataclass(frozen=True)
class Residual:
    """One measured spatial relation. value_mm: + = gap (floating), - = penetration, 0 = touching."""

    relation: str   # "attach:seat" | "feature:on_surface" | ...
    ok: bool
    value_mm: float
    message: str


def _radius(solid: Solid) -> float | None:
    if isinstance(solid, HollowCylinder):
        return solid.outer_radius
    if isinstance(solid, Cylinder):
        return solid.radius
    if isinstance(solid, Frustum):
        return max(solid._rb, solid._rt)
    return None


def surface_distance(solid: Solid, p: tuple[float, float, float]) -> float:
    """Approx distance from point p to the solid's OUTER surface: + outside, - inside, 0 on it.

    Exact enough for the relations we gate on (on-surface ~0, floating > tol, buried < -tol) for the
    analytic host families (cylinder/hollow-cylinder/cone walls + caps, box faces)."""
    x, y, z = p
    r = _radius(solid)
    if r is not None:  # axial body: lateral wall + end caps
        h = getattr(solid, "height", 2 * r)
        rho = math.hypot(x, y)
        if 0.0 <= z <= h:
            lateral = abs(rho - r)              # distance to the curved wall
            cap = min(z, h - z)                 # distance to nearest cap (inside the z-range)
            inside = rho <= r
            return -min(lateral, cap) if inside else lateral
        # outside the z-range: distance to the nearer rim circle
        dz = z - h if z > h else -z
        dr = max(0.0, rho - r)
        return math.hypot(dr, dz)
    if isinstance(solid, (Box, HollowBox)):
        w, d, hh = solid.width, solid.depth, solid.height
        inside = 0 <= x <= w and 0 <= y <= d and 0 <= z <= hh
        if inside:
            return -min(x, w - x, y, d - y, z, hh - z)
        dx = max(x - w, 0.0, -x)
        dy = max(y - d, 0.0, -y)
        dz = max(z - hh, 0.0, -z)
        return math.hypot(dx, dy, dz)
    # families we can't model -> unknown; report 0 (do not raise a false alarm)
    return 0.0


def on_surface(solid: Solid, p: tuple[float, float, float], tol: float = ON_SURFACE_TOL_MM) -> bool:
    return abs(surface_distance(solid, p)) <= tol


def attach_seat_residual(host_solid: Solid, placement: dict | None,
                         position: list[float] | None, part_id: str) -> Residual:
    """Does the part actually seat on the host's surface (contact), or float / bury itself?

    A mate places the part's mounting frame onto the host's target frame — so the seat point is the
    target origin; we measure its distance to the host surface. A position-placed part is checked for
    floating: how far the placed origin is from the host surface.
    """
    if isinstance(placement, dict) and isinstance(placement.get("target"), dict):
        seat = placement["target"].get("origin")
        if isinstance(seat, list) and len(seat) == 3:
            gap = surface_distance(host_solid, tuple(seat))
            ok = abs(gap) <= ON_SURFACE_TOL_MM
            verdict = ("seats on the host surface (contact)" if ok else
                       "FLOATS off the host" if gap > 0 else "is buried inside the host")
            return Residual("attach:seat", ok, round(gap, 3),
                            f"{part_id}: {verdict} (gap {gap:.2f} mm)")
    if position and len(position) >= 3 and any(position):
        gap = surface_distance(host_solid, tuple(float(v) for v in position[:3]))
        ok = gap <= ON_SURFACE_TOL_MM  # a free position that lands on/inside the host is at least in contact
        return Residual("attach:seat", ok, round(gap, 3),
                        f"{part_id}: positioned {gap:.2f} mm from the host surface"
                        + ("" if ok else " — likely FLOATING; prefer an attachment"))
    return Residual("attach:seat", True, 0.0, f"{part_id}: free-standing (no host)")


def feature_seat_residuals(host_solid: Solid, seats: list[tuple[float, float, float]],
                           label: str = "feature") -> list[Residual]:
    """Each surface-feature seat point must lie ON the host surface (else it floats as a tangent tab)."""
    out: list[Residual] = []
    for i, p in enumerate(seats):
        d = surface_distance(host_solid, p)
        out.append(Residual("feature:on_surface", abs(d) <= ON_SURFACE_TOL_MM, round(d, 3),
                            f"{label}[{i}] {'on the wall' if abs(d) <= ON_SURFACE_TOL_MM else 'OFF the wall'}"
                            f" (gap {d:.2f} mm)"))
    return out


def certificate(residuals: list[Residual]) -> str:
    """A short human-readable spatial certificate for the build result."""
    if not residuals:
        return "spatial: nothing to check"
    bad = [r for r in residuals if not r.ok]
    if not bad:
        return "spatial OK: " + "; ".join(r.message for r in residuals[:4])
    return "spatial WARNING: " + "; ".join(r.message for r in bad[:4])
