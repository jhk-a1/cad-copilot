"""Feature-fragment library — the tested, correct-by-construction building blocks (ADR-007).

Each genome `Feature` compiles to a *fragment*: a short run of Command IR that is well-formed by
construction (it always passes the IR Validator) and, for primaries we can model analytically, an
exact kernel `Solid` so render-and-check VERIFIES the geometry rather than trusting the model.

The labor split the cross-domain research prescribed: the LLM proposes WHICH fragment and the hole
VALUES; this library owns the exact geometry. A hollow cylinder is therefore *always* hollow (it is
an extrude + shell the kernel realizes as a `HollowCylinder`), a handle is *always* a closed loop —
the model can no longer emit a tangent-revolve blob, because it never authors the geometry.
"""

from __future__ import annotations

import math

from ...models import CommandIR, ExpectedGeometry, IRCommand, IRCommandType
from ..geometry import (
    Box,
    Cylinder,
    Frustum,
    HollowBox,
    HollowCylinder,
    LBracket,
    RegularPrism,
    Solid,
    Sphere,
    Torus,
    Wedge,
)
from .grammar import FEATURE_SPECS, Feature, FeatureType, Genome

T = IRCommandType


class _Ctx:
    """Accumulates IR commands with running ids and entity refs as fragments are appended."""

    def __init__(self, part_id: str) -> None:
        self.part_id = part_id
        self._id = 0
        self._sk = 0
        self._pf = 0
        self._bd = 0
        self.declared: dict[str, float] = {}
        self.body_ref: str | None = None
        self.commands: list[IRCommand] = []

    def _nid(self) -> int:
        i = self._id
        self._id += 1
        return i

    def param(self, hole: str, value: float) -> str:
        """Declare a user parameter (a genome hole) once; return its global name for references."""
        name = f"{self.part_id}_{hole}"
        if name not in self.declared:
            self.declared[name] = float(value)
            self.commands.append(IRCommand(id=self._nid(), type=T.CREATE_USER_PARAMETER,
                                           params={"name": name, "value": float(value), "unit": "mm"}))
        return name

    def add(self, type_: IRCommandType, params: dict, produces: str | None = None) -> IRCommand:
        c = IRCommand(id=self._nid(), type=type_, params=params, produces=produces)
        self.commands.append(c)
        return c

    def sketch_ref(self) -> str:
        self._sk += 1
        return f"sketch_{self._sk - 1}"

    def profile_ref(self) -> str:
        self._pf += 1
        return f"profile_{self._pf - 1}"

    def make_body_ref(self) -> str:
        self._bd += 1
        self.body_ref = f"body_{self._bd - 1}"
        return self.body_ref


def resolved(feature: Feature) -> dict[str, float]:
    """Hole values for a feature: its params, with the spec defaults filling any gaps."""
    spec = FEATURE_SPECS[feature.type]
    out = {h.name: h.default for h in spec.holes}
    for k, v in feature.params.items():
        if k in out:
            out[k] = float(v)
    return out


# --------------------------------------------------------------------------- primaries

def _extrude_profile(ctx: _Ctx, profile_ref: str, sketch_ref: str, distance: str) -> str:
    ctx.add(T.CLOSE_SKETCH, {"sketch_ref": sketch_ref})
    body = ctx.make_body_ref()
    ctx.add(T.EXTRUDE, {"profile_ref": profile_ref, "distance": distance, "operation": "new_body"},
            produces=body)
    return body


def _solid_cylinder(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid:
    p = resolved(f)
    dia = ctx.param("diameter", p["diameter"])
    h = ctx.param("height", p["height"])
    sk = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XY"}, produces=sk)
    pf = ctx.profile_ref()
    ctx.add(T.ADD_CIRCLE, {"sketch_ref": sk, "center": [0, 0], "diameter": dia}, produces=pf)
    _extrude_profile(ctx, pf, sk, h)
    return Cylinder(diameter=p["diameter"], height=p["height"])


def _opening(f: Feature) -> tuple[list[str], bool, bool]:
    """Resolve the functional opening of a hollow vessel into (open_faces, open_top, open_bottom).

    Default is OPEN-TOP — a hollow vessel (cup/mug/bowl/container) is open by its purpose; a closed
    hollow is the rare, explicit case ('none')."""
    opening = (f.options.get("opening") or "top").lower()
    open_faces = {"top": ["top"], "bottom": ["bottom"], "both": ["top", "bottom"],
                  "none": [], "closed": []}.get(opening, ["top"])
    return open_faces, ("top" in open_faces), ("bottom" in open_faces)


def _hollow_cylinder(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid:
    p = resolved(f)
    _solid_cylinder(ctx, f, None)
    wall = ctx.param("wall", p["wall"])
    open_faces, open_top, open_bottom = _opening(f)
    ctx.add(T.SHELL, {"body_ref": ctx.body_ref, "thickness": wall, "open_faces": open_faces})
    return HollowCylinder(outer_diameter=p["diameter"], height=p["height"], wall=p["wall"],
                          open_top=open_top, open_bottom=open_bottom)


def _solid_box(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid:
    p = resolved(f)
    length = ctx.param("length", p["length"])
    width = ctx.param("width", p["width"])
    height = ctx.param("height", p["height"])
    sk = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XY"}, produces=sk)
    pf = ctx.profile_ref()
    ctx.add(T.ADD_RECTANGLE, {"sketch_ref": sk, "corner1": [0, 0], "width": length, "height": width},
            produces=pf)
    _extrude_profile(ctx, pf, sk, height)
    return Box(width=p["length"], depth=p["width"], height=p["height"])


def _hollow_box(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid:
    p = resolved(f)
    _solid_box(ctx, f, None)
    body = ctx.body_ref
    wall = ctx.param("wall", p["wall"])
    open_faces, open_top, open_bottom = _opening(f)
    ctx.add(T.SHELL, {"body_ref": body, "thickness": wall, "open_faces": open_faces})
    return HollowBox(width=p["length"], depth=p["width"], height=p["height"], wall=p["wall"],
                     open_top=open_top, open_bottom=open_bottom)


def _l_bracket(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid:
    p = resolved(f)
    leg_a, leg_b = p["leg_a"], p["leg_b"]
    thickness, depth = p["thickness"], p["depth"]
    ctx.param("leg_a", leg_a)
    ctx.param("leg_b", leg_b)
    ctx.param("thickness", thickness)
    depth_p = ctx.param("depth", depth)
    sk = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XY"}, produces=sk)
    verts = [(0, 0), (leg_a, 0), (leg_a, thickness), (thickness, thickness),
             (thickness, leg_b), (0, leg_b)]
    pf = ctx.profile_ref()
    for i in range(6):
        start, end = verts[i], verts[(i + 1) % 6]
        ctx.add(T.ADD_LINE, {"sketch_ref": sk, "start": list(start), "end": list(end)},
                produces=pf if i == 5 else None)
    _extrude_profile(ctx, pf, sk, depth_p)
    return LBracket(leg_a=leg_a, leg_b=leg_b, thickness=thickness, depth=depth)


def _loop_handle(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid | None:
    """A closed rectangular loop (frame) — the handle. The OUTER size is live-parametric; the inner
    cut-out is recomputed from the holes each codegen. Geometry is advisory (no kernel verdict)."""
    p = resolved(f)
    w, h, bar, depth = p["loop_width"], p["loop_height"], p["bar_thickness"], p["loop_depth"]
    wname = ctx.param("loop_width", w)
    hname = ctx.param("loop_height", h)
    ctx.param("bar_thickness", bar)
    dname = ctx.param("loop_depth", depth)
    # outer rectangle -> slab
    sk0 = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XZ"}, produces=sk0)
    pf0 = ctx.profile_ref()
    ctx.add(T.ADD_RECTANGLE, {"sketch_ref": sk0, "corner1": [0, 0], "width": wname, "height": hname},
            produces=pf0)
    _extrude_profile(ctx, pf0, sk0, dname)
    # inner rectangle -> cut, leaving a frame (literal coords, regenerated from holes)
    iw, ih = max(0.1, w - 2 * bar), max(0.1, h - 2 * bar)
    sk1 = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XZ"}, produces=sk1)
    pf1 = ctx.profile_ref()
    ctx.add(T.ADD_RECTANGLE, {"sketch_ref": sk1, "corner1": [round(bar, 4), round(bar, 4)],
                              "width": round(iw, 4), "height": round(ih, 4)}, produces=pf1)
    ctx.add(T.CLOSE_SKETCH, {"sketch_ref": sk1})
    ctx.add(T.EXTRUDE, {"profile_ref": pf1, "distance": dname, "operation": "cut"})
    return None  # advisory: the loop is not analytically verified (honest)


# --------------------------------------------------------------- general primitives

def _cone(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid:
    """A cone / frustum (funnel, nozzle, tapered cup) — a tapered extrude. Kernel-exact."""
    p = resolved(f)
    bd, td, h = p["bottom_diameter"], p["top_diameter"], p["height"]
    bdname = ctx.param("bottom_diameter", bd)
    ctx.param("top_diameter", td)  # surfaced for dimensioning; the taper below realizes it
    hname = ctx.param("height", h)
    sk = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XY"}, produces=sk)
    pf = ctx.profile_ref()
    ctx.add(T.ADD_CIRCLE, {"sketch_ref": sk, "center": [0, 0], "diameter": bdname}, produces=pf)
    ctx.add(T.CLOSE_SKETCH, {"sketch_ref": sk})
    taper = math.degrees(math.atan(((td - bd) / 2.0) / h)) if h else 0.0
    body = ctx.make_body_ref()
    ctx.add(T.EXTRUDE, {"profile_ref": pf, "distance": hname, "operation": "new_body",
                        "taper": round(taper, 4)}, produces=body)
    return Frustum(bottom_diameter=bd, top_diameter=td, height=h)


def _prism(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid:
    """A regular n-sided prism (hex/oct post, nut blank). sides is structural (a literal)."""
    p = resolved(f)
    sides = max(3, int(round(p["sides"])))
    r, h = p["radius"], p["height"]
    rname = ctx.param("radius", r)
    hname = ctx.param("height", h)
    sk = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XY"}, produces=sk)
    pf = ctx.profile_ref()
    ctx.add(T.ADD_POLYGON, {"sketch_ref": sk, "center": [0, 0], "sides": sides, "radius": rname},
            produces=pf)
    ctx.add(T.CLOSE_SKETCH, {"sketch_ref": sk})
    body = ctx.make_body_ref()
    ctx.add(T.EXTRUDE, {"profile_ref": pf, "distance": hname, "operation": "new_body"}, produces=body)
    return RegularPrism(sides=sides, circumradius=r, height=h)


def _sphere(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid:
    """A ball / dome — revolve a half-disk about the axis. Geometry verified live (advisory offline)."""
    p = resolved(f)
    d = p["diameter"]
    r = d / 2.0
    dname = ctx.param("diameter", d)
    sk = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XZ"}, produces=sk)
    ctx.add(T.ADD_ARC, {"sketch_ref": sk, "start": [0, round(-r, 4)], "mid": [round(r, 4), 0],
                        "end": [0, round(r, 4)]})
    pf = ctx.profile_ref()
    ctx.add(T.ADD_LINE, {"sketch_ref": sk, "start": [0, round(r, 4)], "end": [0, round(-r, 4)]},
            produces=pf)
    ctx.add(T.CLOSE_SKETCH, {"sketch_ref": sk})
    body = ctx.make_body_ref()
    ctx.add(T.REVOLVE, {"profile_ref": pf, "angle": 360, "axis": "z", "operation": "new_body"},
            produces=body)
    _ = dname  # diameter surfaced for dimensioning; coords regenerate per codegen
    return Sphere(diameter=d)


def _torus(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid:
    """A ring / o-ring / round handle — revolve an offset circle 360 deg. Advisory offline."""
    p = resolved(f)
    rd, tubed = p["ring_diameter"], p["tube_diameter"]
    ctx.param("ring_diameter", rd)
    tdname = ctx.param("tube_diameter", tubed)
    sk = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XZ"}, produces=sk)
    pf = ctx.profile_ref()
    ctx.add(T.ADD_CIRCLE, {"sketch_ref": sk, "center": [round(rd / 2.0, 4), 0], "diameter": tdname},
            produces=pf)
    ctx.add(T.CLOSE_SKETCH, {"sketch_ref": sk})
    body = ctx.make_body_ref()
    ctx.add(T.REVOLVE, {"profile_ref": pf, "angle": 360, "axis": "z", "operation": "new_body"},
            produces=body)
    return Torus(ring_diameter=rd, tube_diameter=tubed)


def _wedge(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid:
    """A right-triangular prism (ramp, gusset, chute) — a triangle extruded. Advisory offline."""
    p = resolved(f)
    w, depth, h = p["width"], p["depth"], p["height"]
    ctx.param("width", w)
    dname = ctx.param("depth", depth)
    ctx.param("height", h)
    sk = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XZ"}, produces=sk)
    ctx.add(T.ADD_LINE, {"sketch_ref": sk, "start": [0, 0], "end": [round(w, 4), 0]})
    ctx.add(T.ADD_LINE, {"sketch_ref": sk, "start": [round(w, 4), 0], "end": [0, round(h, 4)]})
    pf = ctx.profile_ref()
    ctx.add(T.ADD_LINE, {"sketch_ref": sk, "start": [0, round(h, 4)], "end": [0, 0]}, produces=pf)
    ctx.add(T.CLOSE_SKETCH, {"sketch_ref": sk})
    body = ctx.make_body_ref()
    ctx.add(T.EXTRUDE, {"profile_ref": pf, "distance": dname, "operation": "new_body"}, produces=body)
    return Wedge(width=w, depth=depth, height=h)


def _loft(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid | None:
    """A blended transition (round bottom -> rectangular top: an adapter/duct). Advisory offline."""
    p = resolved(f)
    bd, tw, td, h = p["bottom_diameter"], p["top_width"], p["top_depth"], p["height"]
    bdname = ctx.param("bottom_diameter", bd)
    twname = ctx.param("top_width", tw)
    tdname = ctx.param("top_depth", td)
    hname = ctx.param("height", h)
    sk0 = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XY"}, produces=sk0)
    pf0 = ctx.profile_ref()
    ctx.add(T.ADD_CIRCLE, {"sketch_ref": sk0, "center": [0, 0], "diameter": bdname}, produces=pf0)
    ctx.add(T.CLOSE_SKETCH, {"sketch_ref": sk0})
    sk1 = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XY", "offset": hname}, produces=sk1)
    pf1 = ctx.profile_ref()
    ctx.add(T.ADD_RECTANGLE, {"sketch_ref": sk1, "corner1": [round(-tw / 2, 4), round(-td / 2, 4)],
                              "width": twname, "height": tdname}, produces=pf1)
    ctx.add(T.CLOSE_SKETCH, {"sketch_ref": sk1})
    body = ctx.make_body_ref()
    ctx.add(T.LOFT, {"profile_refs": [pf0, pf1], "operation": "new_body"}, produces=body)
    return None


def _sweep(ctx: _Ctx, f: Feature, _solid: Solid | None) -> Solid | None:
    """A circular section swept along a circular arc — a bend / elbow / hook / round handle.

    Built as a PARTIAL revolve of an offset circle (robust: the profile never touches the axis),
    which is a swept tube along an arc. Advisory offline."""
    p = resolved(f)
    tubed, br, angle = p["profile_diameter"], p["bend_radius"], p["bend_angle"]
    tdname = ctx.param("profile_diameter", tubed)
    ctx.param("bend_radius", br)
    # bend_angle is structural (degrees), not a mm dimension -> a literal, not a user parameter
    sk = ctx.sketch_ref()
    ctx.add(T.CREATE_SKETCH, {"plane": "XZ"}, produces=sk)
    pf = ctx.profile_ref()
    ctx.add(T.ADD_CIRCLE, {"sketch_ref": sk, "center": [round(br, 4), 0], "diameter": tdname},
            produces=pf)
    ctx.add(T.CLOSE_SKETCH, {"sketch_ref": sk})
    body = ctx.make_body_ref()
    ctx.add(T.REVOLVE, {"profile_ref": pf, "angle": round(angle, 4), "axis": "z",
                        "operation": "new_body"}, produces=body)
    return None


# --------------------------------------------------------------------------- modifiers

def _wall_info(solid: Solid | None) -> tuple[float, float] | None:
    """(outer_radius, height) for a round-walled host, else None — where a wrap pattern can go."""
    if isinstance(solid, HollowCylinder):
        return solid.outer_radius, solid.height
    if isinstance(solid, Cylinder):
        return solid.radius, solid.height
    if isinstance(solid, Frustum):
        return min(solid._rb, solid._rt), solid.height
    return None


def _surface_pattern(ctx: _Ctx, f: Feature, solid: Solid | None) -> Solid | None:
    """Surface scales/knurl/studs on the curved wall as a DISPLACEMENT FIELD (ADR-010, Pillar A).

    The breakthrough from the cross-domain robustness research: surface texture is not N fragile
    boolean cuts — it is a scalar HEIGHT FIELD h(theta, z) over the wall's own parameterisation,
    realised as a single watertight MESH skin displaced along the wall normal (graphics displacement
    mapping; additive-manufacturing fuzzy skin; implicit/FRep). A closed mesh is *always* valid, so
    this can never hit `NO_TARGET_BODY` — the failure that killed the per-feature cut+pattern path
    (5 of 6 rows died unpredictably). "200 scales" becomes one field, O(1) in robustness.

    The editable parametric B-rep (the mug body) is untouched; the texture is a regenerable field
    whose columns/rows/relief stay genome holes. We still DECLARE those as user parameters for
    dimensioning, then emit one CREATE_MESH_BODY whose verified-watertight mesh the executor imports
    as a mesh body (separate from the B-rep core). Cosmetic -> optional/non-fatal in the executor.
    """
    from .texture import mesh_body_params, textured_wall_mesh

    p = resolved(f)
    cols = int(round(p["pattern_columns"]))
    rows = int(round(p["pattern_rows"]))
    relief = float(p["pattern_depth"])  # raised-scale relief (mm) along the outward normal
    # surface the texture knobs as editable user parameters (dimensioning / live edit intent)
    ctx.param("pattern_columns", cols)
    ctx.param("pattern_rows", rows)
    ctx.param("pattern_depth", relief)
    ctx.param("pattern_size", float(p["pattern_size"]))
    ctx.param("pattern_row_spacing", float(p["pattern_row_spacing"]))

    info = _wall_info(solid)
    if info is None:  # only wrap round walls for now; skip honestly rather than place wrongly
        return solid
    radius, height = info
    # the MOTIF (scales | knurl | studs | ribs | hex | weave | bumps | …) is chosen from intent; the
    # SAME robust displacement-field-to-watertight-mesh substrate renders any of them. General.
    motif = (f.options.get("motif") or "scales")
    mesh = textured_wall_mesh(radius, height, cols=cols, rows=rows, amplitude=relief, motif=motif)
    ctx.add(T.CREATE_MESH_BODY, mesh_body_params(mesh, name=f"{ctx.part_id}_texture"))
    return solid


def _bore(ctx: _Ctx, f: Feature, solid: Solid | None) -> Solid | None:
    """A central axial through-hole (engine cylinder, bushing). Kernel-verified via WithHoles."""
    from ..geometry import WithHoles
    dia = ctx.param("bore_diameter", resolved(f)["bore_diameter"])
    ctx.add(T.HOLE, {"body_ref": ctx.body_ref, "positions": [[0, 0]], "diameter": dia, "through": True})
    if solid is not None:
        return WithHoles(solid, [(0.0, 0.0, ctx.declared[dia] / 2.0)])
    return solid


def _fillet(ctx: _Ctx, f: Feature, solid: Solid | None) -> Solid | None:
    r = ctx.param("fillet_radius", resolved(f)["fillet_radius"])
    ctx.add(T.FILLET, {"body_ref": ctx.body_ref, "radius": r})
    return solid


def _chamfer(ctx: _Ctx, f: Feature, solid: Solid | None) -> Solid | None:
    d = ctx.param("chamfer_size", resolved(f)["chamfer_size"])
    ctx.add(T.CHAMFER, {"body_ref": ctx.body_ref, "distance": d})
    return solid


_BUILDERS = {
    FeatureType.SOLID_BOX: _solid_box,
    FeatureType.HOLLOW_BOX: _hollow_box,
    FeatureType.SOLID_CYLINDER: _solid_cylinder,
    FeatureType.HOLLOW_CYLINDER: _hollow_cylinder,
    FeatureType.L_BRACKET: _l_bracket,
    FeatureType.LOOP_HANDLE: _loop_handle,
    FeatureType.CONE: _cone,
    FeatureType.PRISM: _prism,
    FeatureType.SPHERE: _sphere,
    FeatureType.TORUS: _torus,
    FeatureType.WEDGE: _wedge,
    FeatureType.LOFT: _loft,
    FeatureType.SWEEP: _sweep,
    FeatureType.SURFACE_PATTERN: _surface_pattern,
    FeatureType.FILLET: _fillet,
    FeatureType.CHAMFER: _chamfer,
    FeatureType.BORE: _bore,
}


def build_ir(genome: Genome) -> tuple[CommandIR, Solid | None]:
    """Compile a (validated, solved) genome into Command IR + the primary's exact kernel solid.

    expected_geometry comes from that solid, so render-and-check compares the realized IR against
    the very shape the genome intends — a real verification, not the model's own estimate.
    """
    ctx = _Ctx(genome.part_id)
    solid: Solid | None = None
    rollback = []
    for feat in genome.features:
        before = len(ctx.commands)
        solid = _BUILDERS[feat.type](ctx, feat, solid)
        rollback.append(ctx.commands[before].id if len(ctx.commands) > before else 0)
    eg = None
    if solid is not None:
        eg = ExpectedGeometry(bbox_mm=list(solid.bbox_mm), volume_mm3=solid.volume_mm3,
                              key_dims={})
    ir = CommandIR(commands=ctx.commands, rollback_points=sorted(set(rollback)), expected_geometry=eg)
    return ir, solid
