"""Geometry kernel + render-and-check verifier (ADR-001's geometric verifier, primitive tier).

ADR-001 makes accuracy the product of a *verifier*, not model size: every generated IR is
realized into a solid and checked before it is trusted. This module is the primitive-family
tier of that verifier.

Why pure-Python analytic geometry, not OpenCASCADE (build123d/OCP):
  * The supported families (box, cylinder, l_bracket) are simple enough that analytic formulas
    give EXACT volume and bounding box — not the voxel approximation a kernel would give. For
    accuracy-paramount work, exact beats approximate.
  * OCP has no real Python 3.14 wheel yet (only `-proxy`/`-novtk` shims) and pulls ~35 packages
    (scipy/scikit-learn/ipython). Disproportionate for the trial. Deferred to post-trial, when
    we need booleans/fillets on arbitrary geometry (ADR: recorded in DECISIONS change log).

`realize` turns a CommandIR into a `Solid`; `check_geometry` is the render-and-check the codegen
stage runs (measured vs expected, within the dimensional gate). `iou` is the voxel-overlap
primitive the eval harness will use to score realized-vs-reference shape agreement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..models import CommandIR, IRCommandType

# Tolerances — the dimensional gate (PROJECT_MEMORY: dimensional error < 0.1 mm).
BBOX_TOL_MM = 0.1
VOLUME_REL_TOL = 1e-3


# --------------------------------------------------------------------------- solids

class Solid:
    """Minimal solid: exact volume + axis-aligned bbox, plus point-membership for IoU."""

    family = "solid"

    @property
    def volume_mm3(self) -> float:
        raise NotImplementedError

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        raise NotImplementedError

    @property
    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """(min_xyz, max_xyz) in mm."""
        raise NotImplementedError

    def contains(self, x: float, y: float, z: float) -> bool:
        raise NotImplementedError


@dataclass
class Box(Solid):
    width: float   # x (mm)
    depth: float   # y (mm)
    height: float  # z (mm)
    family = "box"

    @property
    def volume_mm3(self) -> float:
        return self.width * self.depth * self.height

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        return (self.width, self.depth, self.height)

    @property
    def bounds(self):
        return ((0.0, 0.0, 0.0), (self.width, self.depth, self.height))

    def contains(self, x, y, z) -> bool:
        return 0.0 <= x <= self.width and 0.0 <= y <= self.depth and 0.0 <= z <= self.height


@dataclass
class Cylinder(Solid):
    diameter: float  # mm
    height: float    # mm (axis = z)
    family = "cylinder"

    @property
    def radius(self) -> float:
        return self.diameter / 2.0

    @property
    def volume_mm3(self) -> float:
        return math.pi * self.radius**2 * self.height

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        return (self.diameter, self.diameter, self.height)

    @property
    def bounds(self):
        r = self.radius
        return ((-r, -r, 0.0), (r, r, self.height))

    def contains(self, x, y, z) -> bool:
        return (x * x + y * y) <= self.radius**2 and 0.0 <= z <= self.height


@dataclass
class LBracket(Solid):
    leg_a: float     # x extent (horizontal leg length, mm)
    leg_b: float     # y extent (vertical leg height, mm)
    thickness: float
    depth: float     # z extent
    family = "l_bracket"

    @property
    def volume_mm3(self) -> float:
        # area of the L = thickness * (leg_a + leg_b - thickness); the overlap square is counted once
        return self.thickness * (self.leg_a + self.leg_b - self.thickness) * self.depth

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        return (self.leg_a, self.leg_b, self.depth)

    @property
    def bounds(self):
        return ((0.0, 0.0, 0.0), (self.leg_a, self.leg_b, self.depth))

    def contains(self, x, y, z) -> bool:
        if not (0.0 <= z <= self.depth):
            return False
        horizontal = 0.0 <= x <= self.leg_a and 0.0 <= y <= self.thickness
        vertical = 0.0 <= x <= self.thickness and 0.0 <= y <= self.leg_b
        return horizontal or vertical


@dataclass
class WithHoles(Solid):
    """A base solid with through-holes (along z) subtracted — a small CSG so featured parts
    are measured as the real holed geometry, not the blank stock."""

    base: Solid
    holes: list[tuple[float, float, float]]  # (center_x, center_y, radius) in mm

    @property
    def family(self) -> str:
        return f"{self.base.family}+holes"

    @property
    def _depth(self) -> float:
        (_, _, z0), (_, _, z1) = self.base.bounds
        return z1 - z0

    @property
    def volume_mm3(self) -> float:
        removed = sum(math.pi * r * r * self._depth for _, _, r in self.holes)
        return self.base.volume_mm3 - removed

    @property
    def bbox_mm(self):
        return self.base.bbox_mm

    @property
    def bounds(self):
        return self.base.bounds

    def contains(self, x, y, z) -> bool:
        if not self.base.contains(x, y, z):
            return False
        return not any((x - cx) ** 2 + (y - cy) ** 2 <= r * r for cx, cy, r in self.holes)


@dataclass
class HollowCylinder(Solid):
    """A shelled cylinder — the Design-Genome hollow_cylinder fragment (cup/mug/pipe body).

    FUNCTION drives topology: `open_top`/`open_bottom` say which ends are open, so a cup is open at
    the top (cavity reaches the rim), a pipe is open at both ends, a sealed canister is closed. The
    cavity is shrunk by `wall` on the radius and by `wall` only at each CLOSED end. Exact volume so
    render-check VERIFIES the part actually serves its purpose, not just that it is hollow.
    """

    outer_diameter: float
    height: float
    wall: float
    open_top: bool = True       # a hollow vessel is open by default — a closed cup is the rare case
    open_bottom: bool = False
    family = "hollow_cylinder"

    @property
    def outer_radius(self) -> float:
        return self.outer_diameter / 2.0

    @property
    def inner_radius(self) -> float:
        return max(0.0, self.outer_radius - self.wall)

    @property
    def _cavity_z(self) -> tuple[float, float]:
        z0 = 0.0 if self.open_bottom else self.wall
        z1 = self.height if self.open_top else self.height - self.wall
        return z0, max(z0, z1)

    @property
    def inner_height(self) -> float:
        z0, z1 = self._cavity_z
        return z1 - z0

    @property
    def volume_mm3(self) -> float:
        outer = math.pi * self.outer_radius**2 * self.height
        inner = math.pi * self.inner_radius**2 * self.inner_height
        return outer - inner

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        return (self.outer_diameter, self.outer_diameter, self.height)

    @property
    def bounds(self):
        r = self.outer_radius
        return ((-r, -r, 0.0), (r, r, self.height))

    def contains(self, x, y, z) -> bool:
        if not ((x * x + y * y) <= self.outer_radius**2 and 0.0 <= z <= self.height):
            return False
        z0, z1 = self._cavity_z
        in_cavity = (x * x + y * y) < self.inner_radius**2 and z0 < z < z1
        return not in_cavity


@dataclass
class HollowBox(Solid):
    """A shelled box — the hollow_box fragment (open container / tray / sealed enclosure).

    FUNCTION drives topology via `open_top`/`open_bottom` (a tray/container is open at the top).
    """

    width: float
    depth: float
    height: float
    wall: float
    open_top: bool = True
    open_bottom: bool = False
    family = "hollow_box"

    @property
    def _cavity_z(self) -> tuple[float, float]:
        z0 = 0.0 if self.open_bottom else self.wall
        z1 = self.height if self.open_top else self.height - self.wall
        return z0, max(z0, z1)

    @property
    def volume_mm3(self) -> float:
        outer = self.width * self.depth * self.height
        iw = max(0.0, self.width - 2 * self.wall)
        id_ = max(0.0, self.depth - 2 * self.wall)
        z0, z1 = self._cavity_z
        return outer - iw * id_ * (z1 - z0)

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        return (self.width, self.depth, self.height)

    @property
    def bounds(self):
        return ((0.0, 0.0, 0.0), (self.width, self.depth, self.height))

    def contains(self, x, y, z) -> bool:
        if not (0.0 <= x <= self.width and 0.0 <= y <= self.depth and 0.0 <= z <= self.height):
            return False
        z0, z1 = self._cavity_z
        in_cavity = (self.wall < x < self.width - self.wall
                     and self.wall < y < self.depth - self.wall
                     and z0 < z < z1)
        return not in_cavity


# --- general primitives (the vocabulary the LLM composes — not a fixed object list) -------

@dataclass
class Frustum(Solid):
    """A cone / tapered cylinder (funnel, nozzle, tapered cup) — exact, render-check verifiable."""

    bottom_diameter: float
    top_diameter: float
    height: float
    family = "frustum"

    @property
    def _rb(self) -> float:
        return self.bottom_diameter / 2.0

    @property
    def _rt(self) -> float:
        return self.top_diameter / 2.0

    @property
    def volume_mm3(self) -> float:
        return math.pi * self.height / 3.0 * (self._rb**2 + self._rb * self._rt + self._rt**2)

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        d = max(self.bottom_diameter, self.top_diameter)
        return (d, d, self.height)

    @property
    def bounds(self):
        r = max(self._rb, self._rt)
        return ((-r, -r, 0.0), (r, r, self.height))

    def _radius_at(self, z: float) -> float:
        return self._rb + (self._rt - self._rb) * (z / self.height if self.height else 0.0)

    def contains(self, x, y, z) -> bool:
        if not (0.0 <= z <= self.height):
            return False
        r = self._radius_at(z)
        return (x * x + y * y) <= r * r


def _polygon_vertices(sides: int, circumradius: float) -> list[tuple[float, float]]:
    """Regular n-gon vertices, first vertex at +x. Shared by the kernel and the executor so the
    realized prism matches its expected geometry exactly."""
    return [(circumradius * math.cos(2 * math.pi * i / sides),
             circumradius * math.sin(2 * math.pi * i / sides)) for i in range(sides)]


@dataclass
class RegularPrism(Solid):
    """An n-sided prism (hex/oct post, nut blank, faceted column) — exact volume + bbox."""

    sides: int
    circumradius: float
    height: float
    family = "prism"

    @property
    def _verts(self):
        return _polygon_vertices(self.sides, self.circumradius)

    @property
    def volume_mm3(self) -> float:
        area = 0.5 * self.sides * self.circumradius**2 * math.sin(2 * math.pi / self.sides)
        return area * self.height

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        xs = [v[0] for v in self._verts]
        ys = [v[1] for v in self._verts]
        return (max(xs) - min(xs), max(ys) - min(ys), self.height)

    @property
    def bounds(self):
        xs = [v[0] for v in self._verts]
        ys = [v[1] for v in self._verts]
        return ((min(xs), min(ys), 0.0), (max(xs), max(ys), self.height))

    def contains(self, x, y, z) -> bool:
        if not (0.0 <= z <= self.height):
            return False
        verts = self._verts
        inside = False
        n = len(verts)
        j = n - 1
        for i in range(n):
            xi, yi = verts[i]
            xj, yj = verts[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside


@dataclass
class Sphere(Solid):
    """A ball / dome. REVOLVE-built, so render-check is advisory offline (verified live in Fusion)."""

    diameter: float
    family = "sphere"

    @property
    def _r(self) -> float:
        return self.diameter / 2.0

    @property
    def volume_mm3(self) -> float:
        return 4.0 / 3.0 * math.pi * self._r**3

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        return (self.diameter, self.diameter, self.diameter)

    @property
    def bounds(self):
        r = self._r
        return ((-r, -r, -r), (r, r, r))

    def contains(self, x, y, z) -> bool:
        return (x * x + y * y + z * z) <= self._r**2


@dataclass
class Torus(Solid):
    """A ring / o-ring / round handle. REVOLVE-built — advisory offline, verified live."""

    ring_diameter: float   # diameter of the centre circle (axis to tube centre = ring_diameter/2)
    tube_diameter: float
    family = "torus"

    @property
    def _rr(self) -> float:
        return self.ring_diameter / 2.0

    @property
    def _rt(self) -> float:
        return self.tube_diameter / 2.0

    @property
    def volume_mm3(self) -> float:
        return 2.0 * math.pi**2 * self._rr * self._rt**2

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        outer = 2.0 * (self._rr + self._rt)
        return (outer, outer, self.tube_diameter)

    @property
    def bounds(self):
        o = self._rr + self._rt
        return ((-o, -o, -self._rt), (o, o, self._rt))

    def contains(self, x, y, z) -> bool:
        d = math.sqrt(x * x + y * y) - self._rr
        return (d * d + z * z) <= self._rt**2


@dataclass
class Wedge(Solid):
    """A right-triangular prism (ramp, gusset, slide chute) — exact."""

    width: float    # x
    depth: float    # y (extrusion)
    height: float   # z
    family = "wedge"

    @property
    def volume_mm3(self) -> float:
        return 0.5 * self.width * self.height * self.depth

    @property
    def bbox_mm(self) -> tuple[float, float, float]:
        return (self.width, self.depth, self.height)

    @property
    def bounds(self):
        return ((0.0, 0.0, 0.0), (self.width, self.depth, self.height))

    def contains(self, x, y, z) -> bool:
        if not (0.0 <= x <= self.width and 0.0 <= y <= self.depth and 0.0 <= z <= self.height):
            return False
        return z <= self.height * (1.0 - x / self.width)


# --------------------------------------------------------------------------- realize

def _params(ir: CommandIR) -> dict[str, float]:
    table: dict[str, float] = {}
    for c in ir.commands:
        if c.type is IRCommandType.CREATE_USER_PARAMETER:
            name, value = c.params.get("name"), c.params.get("value")
            if isinstance(name, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
                table[name] = float(value)
    return table


def _resolve(value: object, params: dict[str, float]) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return params.get(value)
    return None


def _first(ir: CommandIR, kind: IRCommandType):
    return next((c for c in ir.commands if c.type is kind), None)


def _by_suffix(params: dict[str, float], suffix: str) -> float | None:
    for name, value in params.items():
        if name == suffix or name.endswith("_" + suffix):
            return value
    return None


def _base_solid(ir: CommandIR, params: dict[str, float], height: float) -> Solid | None:
    poly = _first(ir, IRCommandType.ADD_POLYGON)
    if poly is not None:
        sides = poly.params.get("sides")
        radius = _resolve(poly.params.get("radius"), params)
        if isinstance(sides, (int, float)) and not isinstance(sides, bool) and sides >= 3 and radius:
            return RegularPrism(sides=int(sides), circumradius=radius, height=height)

    rect = _first(ir, IRCommandType.ADD_RECTANGLE)
    if rect is not None:
        w = _resolve(rect.params.get("width"), params)
        d = _resolve(rect.params.get("height"), params)  # rectangle "height" is the y-extent (depth)
        if w and d:
            return Box(width=w, depth=d, height=height)

    circle = _first(ir, IRCommandType.ADD_CIRCLE)
    if circle is not None:
        dia = _resolve(circle.params.get("diameter"), params)
        if dia:
            return Cylinder(diameter=dia, height=height)

    # l_bracket: an L profile (built from ADD_LINE) extruded by depth (= the extrude distance)
    leg_a = _by_suffix(params, "leg_a")
    leg_b = _by_suffix(params, "leg_b")
    thickness = _by_suffix(params, "thickness")
    if leg_a and leg_b and thickness:
        return LBracket(leg_a=leg_a, leg_b=leg_b, thickness=thickness, depth=height)
    return None


def _holes(ir: CommandIR, params: dict[str, float]) -> list[tuple[float, float, float]]:
    hole = _first(ir, IRCommandType.HOLE)
    if hole is None:
        return []
    dia = _resolve(hole.params.get("diameter"), params)
    positions = hole.params.get("positions") or []
    if dia is None or not isinstance(positions, list):
        return []
    out: list[tuple[float, float, float]] = []
    for p in positions:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            out.append((float(p[0]), float(p[1]), dia / 2.0))
    return out


def _shell(ir: CommandIR, params: dict[str, float]) -> tuple[float, bool, bool] | None:
    """Return (wall, open_top, open_bottom) for the SHELL command, or None. `open_faces` carries
    which ends the part is open at — the functional topology (a cup is open at the top)."""
    shell = _first(ir, IRCommandType.SHELL)
    if shell is None:
        return None
    wall = _resolve(shell.params.get("thickness"), params)
    if wall is None or wall <= 0:
        return None
    faces = shell.params.get("open_faces")
    faces = [str(f).lower() for f in faces] if isinstance(faces, list) else []
    return wall, ("top" in faces or "both" in faces), ("bottom" in faces or "both" in faces)


def _hollow(base: Solid, wall: float, open_top: bool, open_bottom: bool) -> Solid | None:
    """Wrap a primitive as its shelled (hollow) counterpart — the Design-Genome hollow fragments."""
    if isinstance(base, Cylinder):
        return HollowCylinder(outer_diameter=base.diameter, height=base.height, wall=wall,
                              open_top=open_top, open_bottom=open_bottom)
    if isinstance(base, Box):
        return HollowBox(width=base.width, depth=base.depth, height=base.height, wall=wall,
                         open_top=open_top, open_bottom=open_bottom)
    return None


def realize(ir: CommandIR) -> Solid | None:
    """Build an exact Solid from the IR. None for families the analytic kernel can't model yet.

    None is honest "can't measure this off-Fusion" (fillets, revolves, lofts, …) — never a false
    verdict. In the real product these are verified online against Fusion's own mass properties
    (ADR-005); this analytic kernel is the offline/CI tier and stays primitive-only on purpose.

    Hollow shapes (a primitive + SHELL — the Design-Genome hollow_cylinder/hollow_box fragments)
    are realized EXACTLY so render-check verifies the cavity, not the blank stock.
    """
    params = _params(ir)
    extrude = _first(ir, IRCommandType.EXTRUDE)
    if extrude is None:
        return None
    height = _resolve(extrude.params.get("distance"), params)
    if height is None or height <= 0:
        return None

    base = _base_solid(ir, params, height)
    if base is None:
        return None

    # a tapered extrude of a circle is a cone / frustum (composes with a later bore/hole)
    taper = _resolve(extrude.params.get("taper"), params)
    if isinstance(base, Cylinder) and taper:
        rt = base.radius + height * math.tan(math.radians(taper))
        if rt > 0:
            base = Frustum(bottom_diameter=base.diameter, top_diameter=2 * rt, height=height)

    shell = _shell(ir, params)
    if shell is not None:
        wall, open_top, open_bottom = shell
        hollow = _hollow(base, wall, open_top, open_bottom)
        if hollow is not None:
            return hollow

    holes = _holes(ir, params)
    return WithHoles(base, holes) if holes else base


# --------------------------------------------------------------------------- IoU

def iou(a: Solid, b: Solid, n: int = 40) -> float:
    """Voxel intersection-over-union of two solids on a shared n^3 grid. Pure Python."""
    (ax0, ay0, az0), (ax1, ay1, az1) = a.bounds
    (bx0, by0, bz0), (bx1, by1, bz1) = b.bounds
    x0, y0, z0 = min(ax0, bx0), min(ay0, by0), min(az0, bz0)
    x1, y1, z1 = max(ax1, bx1), max(ay1, by1), max(az1, bz1)
    dx, dy, dz = (x1 - x0) / n, (y1 - y0) / n, (z1 - z0) / n
    if dx <= 0 or dy <= 0 or dz <= 0:
        return 0.0

    inter = union = 0
    for i in range(n):
        x = x0 + (i + 0.5) * dx
        for j in range(n):
            y = y0 + (j + 0.5) * dy
            for k in range(n):
                z = z0 + (k + 0.5) * dz
                ina, inb = a.contains(x, y, z), b.contains(x, y, z)
                if ina or inb:
                    union += 1
                    if ina and inb:
                        inter += 1
    return inter / union if union else 0.0


# --------------------------------------------------------------------------- render-and-check

@dataclass
class GeometryCheck:
    realized: bool                         # could the kernel build this family?
    ok: bool                               # measured matches expected within tolerance
    family: str | None
    measured_volume_mm3: float | None
    measured_bbox_mm: list[float] | None
    max_bbox_error_mm: float
    volume_rel_error: float
    message: str


def check_geometry(ir: CommandIR) -> GeometryCheck:
    """Render-and-check (ADR-001): realize the IR and confirm it matches expected_geometry.

    Realizable families are measured exactly and gated at <0.1 mm. Unrealizable families are
    skipped (realized=False, ok=True) — they are verified by other means until the kernel grows.
    """
    solid = realize(ir)
    if solid is None:
        return GeometryCheck(False, True, None, None, None, 0.0, 0.0,
                             "render-check skipped: kernel does not realize this family yet")

    vol = solid.volume_mm3
    bbox = list(solid.bbox_mm)
    eg = ir.expected_geometry
    if eg is None:
        return GeometryCheck(True, True, solid.family, vol, bbox, 0.0, 0.0,
                             f"render-check: {solid.family} volume {vol:.3f} mm^3 (no expectation)")

    bbox_err = (max(abs(m - e) for m, e in zip(bbox, eg.bbox_mm, strict=True))
                if len(eg.bbox_mm) == 3 else math.inf)
    vol_err = abs(vol - eg.volume_mm3) / eg.volume_mm3 if eg.volume_mm3 else 0.0
    ok = bbox_err <= BBOX_TOL_MM and vol_err <= VOLUME_REL_TOL
    verdict = "ok" if ok else "MISMATCH"
    return GeometryCheck(
        True, ok, solid.family, vol, bbox, bbox_err, vol_err,
        f"render-check {verdict}: {solid.family} volume {vol:.3f} mm^3, "
        f"max bbox error {bbox_err:.4f} mm, volume error {vol_err * 100:.3f}%",
    )
