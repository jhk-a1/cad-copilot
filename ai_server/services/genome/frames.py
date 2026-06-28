"""Connector frames + mate alignment (ADR-008) — relational attachment, not guessed coordinates.

The cross-domain research (mechanical mate-connectors, molecular docking, ARtiCAD's connector
contract) all say the same thing: a part attaches to another by **aligning a named local frame on
its surface to a named frame on the host's surface**, and the kernel SOLVES the rigid transform —
you never guess an [x,y,z]. So a mug handle rides on the wall at grip height regardless of the body's
radius, because its mounting frame is solved against the body's wall frame.

Every primitive has ANALYTIC surfaces (a cylinder wall is already (theta, z) with a closed-form
normal), so all of this is exact and offline — no mesh field solver needed. A `Frame` is an origin +
a right-handed orthonormal basis whose `uz` is the mating normal. `align(mount, target)` returns the
rigid transform mapping the part's mounting frame onto the host's target frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..geometry import (
    Box,
    Cylinder,
    Frustum,
    HollowBox,
    HollowCylinder,
    Solid,
    Sphere,
)

Vec = tuple[float, float, float]


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vec) -> Vec:
    n = _norm(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n > 1e-12 else (0.0, 0.0, 1.0)


@dataclass(frozen=True)
class Frame:
    """A local coordinate frame on a surface: origin + right-handed basis; `uz` is the mating normal."""

    origin: Vec
    ux: Vec
    uy: Vec
    uz: Vec

    @staticmethod
    def from_normal_up(origin: Vec, normal: Vec, up: Vec) -> Frame:
        uz = _unit(normal)
        ux = _unit(_cross(up, uz))
        if _norm(ux) < 1e-9:  # up parallel to normal -> pick any perpendicular
            ux = _unit(_cross((1.0, 0.0, 0.0), uz))
            if _norm(ux) < 1e-9:
                ux = _unit(_cross((0.0, 1.0, 0.0), uz))
        uy = _cross(uz, ux)
        return Frame(origin, ux, uy, uz)

    def as_dict(self) -> dict:
        return {"origin": list(self.origin), "ux": list(self.ux),
                "uy": list(self.uy), "uz": list(self.uz)}


@dataclass(frozen=True)
class Placement:
    """The solved attachment: align the part's `mount` frame onto the host's `target` frame."""

    mount: Frame
    target: Frame

    def as_dict(self) -> dict:
        return {"mount": self.mount.as_dict(), "target": self.target.as_dict()}

    def apply(self, p: Vec) -> Vec:
        """Map a point from the part's local space to its placed position (for offline verification)."""
        # express p in the mount basis, then re-embed in the target basis
        d = _sub(p, self.mount.origin)
        local = (_dot(d, self.mount.ux), _dot(d, self.mount.uy), _dot(d, self.mount.uz))
        return _add(self.target.origin,
                    _add(_add(_scale(self.target.ux, local[0]), _scale(self.target.uy, local[1])),
                         _scale(self.target.uz, local[2])))


# --------------------------------------------------------------- host connector frames

_AXIAL = (Cylinder, HollowCylinder, Frustum, Sphere)


def _radius(solid: Solid) -> float:
    if isinstance(solid, HollowCylinder):
        return solid.outer_radius
    if isinstance(solid, Cylinder):
        return solid.radius
    if isinstance(solid, Frustum):
        return max(solid._rb, solid._rt)
    if isinstance(solid, Sphere):
        return solid._r
    if isinstance(solid, (Box, HollowBox)):
        return min(solid.width, solid.depth) / 2.0
    return 10.0


def _height(solid: Solid) -> float:
    return getattr(solid, "height", _radius(solid) * 2.0)


def host_connector(solid: Solid, where: str, height_frac: float = 0.5, angle_deg: float = 0.0) -> Frame:
    """A named frame on the HOST's surface to attach to. `where`: side/wall/grip, top/rim/lid,
    bottom/base, or a box face (front/back/left/right/top/bottom)."""
    w = (where or "side").strip().lower()
    if isinstance(solid, (Box, HollowBox)):
        return _box_face(solid, w)
    h = _height(solid)
    r = _radius(solid)
    if w in ("top", "rim", "lid", "mouth", "up"):
        return Frame.from_normal_up((0.0, 0.0, h), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    if w in ("bottom", "base", "foot", "down"):
        return Frame.from_normal_up((0.0, 0.0, 0.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0))
    # side / wall: a frame on the curved wall at the given height and angle
    a = math.radians(angle_deg)
    z = max(0.0, min(1.0, height_frac)) * h
    normal = (math.cos(a), math.sin(a), 0.0)
    origin = (r * math.cos(a), r * math.sin(a), z)
    return Frame.from_normal_up(origin, normal, (0.0, 0.0, 1.0))


def _box_face(solid: Solid, where: str) -> Frame:
    w, d, h = solid.width, solid.depth, solid.height
    faces = {
        "top": ((w / 2, d / 2, h), (0, 0, 1), (1, 0, 0)),
        "bottom": ((w / 2, d / 2, 0), (0, 0, -1), (1, 0, 0)),
        "front": ((w / 2, 0, h / 2), (0, -1, 0), (0, 0, 1)),
        "back": ((w / 2, d, h / 2), (0, 1, 0), (0, 0, 1)),
        "left": ((0, d / 2, h / 2), (-1, 0, 0), (0, 0, 1)),
        "right": ((w, d / 2, h / 2), (1, 0, 0), (0, 0, 1)),
    }
    o, n, up = faces.get(where, faces["front"] if where in ("side", "wall") else faces["top"])
    return Frame.from_normal_up(o, n, up)


# --------------------------------------------------------------- part mounting frames

def part_mounting(primary_type: str, dims: dict[str, float]) -> Frame:
    """The frame on the ATTACHING part that should land on the host connector. Depends on the part
    type: a handle mounts at the centre of its back edge (bulging outward); most parts mount at the
    centre of their bottom face."""
    t = primary_type
    if t == "loop_handle":
        depth = dims.get("loop_depth", 10.0)
        height = dims.get("loop_height", 80.0)
        # back-edge centre at local x=0; uz = +X (the bulge direction, away from the wall)
        return Frame.from_normal_up((0.0, depth / 2.0, height / 2.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    if t in ("sphere",):
        d = dims.get("diameter", 40.0)
        return Frame.from_normal_up((0.0, 0.0, -d / 2.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0))
    # default: bottom-face centre, mating normal pointing down (sits ON the host face)
    return Frame.from_normal_up((0.0, 0.0, 0.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0))


def align(mount: Frame, target: Frame) -> Placement:
    """The placement that seats the part's mounting frame onto the host's target frame."""
    return Placement(mount=mount, target=target)


def solve_placement(host_solid: Solid, part_primary_type: str, part_dims: dict[str, float],
                    spec: dict) -> Placement:
    """Solve a part's attachment: align its mounting frame to the host's named connector frame."""
    where = str(spec.get("where", "side"))
    height_frac = float(spec.get("height_frac", 0.5) or 0.5)
    angle = float(spec.get("angle", 0.0) or 0.0)
    target = host_connector(host_solid, where, height_frac, angle)
    mount = part_mounting(part_primary_type, part_dims)
    return align(mount, target)
