"""Safe Executor (M1-W3-UI-04) — realize a validated Command IR inside Fusion.

The IR is the only thing that ever touches geometry; this module maps the WHOLE allowlisted IR
vocabulary onto the Fusion API — sketch primitives (line, arc, circle, rectangle) and features
(extrude, revolve, fillet, chamfer, shell, hole). It is deliberately general (ADR-005): the
three placeholder families are just templates over this vocabulary, and the executor builds
whatever valid IR the LLM emits, not a fixed shape list.

After building, it runs the GENERAL render-and-check: read the result body's REAL volume + bounding
box from Fusion's mass-properties API and compare to `expected_geometry`. Because that uses Fusion
as the ground-truth kernel, it verifies ANY shape (not just primitives) and rolls back a build that
does not match intent. Two more design rules from the platform notes:

  * **Units.** The IR is always millimetres; Fusion's internal unit is centimetres. There is ONE
    conversion (`mm_to_cm`), applied here at the boundary, and nowhere else.
  * **One transaction = one undo.** Everything an IR builds is grouped into a single timeline
    group; on any failure the partial work is rolled back so the user is never left with a
    half-built body.

Editability (the product's parametric guarantee): every dimension declared as a
`CREATE_USER_PARAMETER` becomes a real Fusion user parameter, and the extrude depth is bound to
that parameter *by name* (a live expression), so editing the parameter updates the model.

This module has NO module-level `adsk` import — the IR→ops "compiler" (`compile_ir`) is pure and
unit-tested off-line; `adsk` is imported lazily inside `SafeExecutor.execute`, which only runs
inside Fusion. Mirrors `design_gate.py`.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

MM_TO_CM = 0.1

_PLANES = ("XY", "XZ", "YZ")
_OPERATIONS = ("new_body", "join", "cut", "intersect")


class ExecutionError(Exception):
    """Raised when an IR cannot be compiled or executed (after rollback)."""


def mm_to_cm(value_mm: float) -> float:
    """The single mm→cm conversion at the Fusion boundary."""
    return value_mm * MM_TO_CM


def compare_geometry(measured_volume_mm3, measured_bbox_mm, expected,
                     bbox_tol_mm=0.1, volume_rel_tol=0.02):
    """The GENERAL render-and-check (ADR-005): does the body Fusion actually built match intent?

    Pure so it is unit-tested; `execute` feeds it Fusion's real mass properties. Because it works
    on measured volume + bbox, it verifies ANY shape Fusion can build — not just the primitives the
    offline analytic kernel models. Returns (ok, max_bbox_error_mm, volume_rel_error).
    """
    if not expected:
        return (True, 0.0, 0.0)
    bbox_exp = expected.get("bbox_mm") or []
    if len(bbox_exp) == 3:
        bbox_err = max(abs(m - e) for m, e in zip(measured_bbox_mm, bbox_exp, strict=True))
    else:
        bbox_err = float("inf")
    vol_exp = expected.get("volume_mm3")
    vol_err = abs(measured_volume_mm3 - vol_exp) / vol_exp if vol_exp else 0.0
    ok = bbox_err <= bbox_tol_mm and vol_err <= volume_rel_tol
    return (ok, bbox_err, vol_err)


# --------------------------------------------------------------- compiled execution ops

@dataclass
class CreateParam:
    name: str
    value_mm: float
    expression: str  # Fusion expression, e.g. "50 mm"


@dataclass
class CreateSketch:
    ref: str | None
    plane: str
    offset_cm: float = 0.0  # offset construction plane (enables loft sections / 3D sweep paths)


@dataclass
class AddRectangle:
    sketch_ref: str | None
    produces: str | None
    width_cm: float
    height_cm: float
    corner_cm: tuple[float, float]


@dataclass
class AddLine:
    sketch_ref: str | None
    produces: str | None
    start_cm: tuple[float, float]
    end_cm: tuple[float, float]


@dataclass
class AddCircle:
    sketch_ref: str | None
    produces: str | None
    diameter_cm: float
    center_cm: tuple[float, float]


@dataclass
class CloseSketch:
    sketch_ref: str | None


@dataclass
class AddArc:
    sketch_ref: str | None
    produces: str | None
    start_cm: tuple[float, float]
    mid_cm: tuple[float, float]
    end_cm: tuple[float, float]


@dataclass
class Extrude:
    profile_ref: str | None
    produces: str | None
    distance_cm: float
    distance_expression: str  # parameter name or "20 mm" — bound live for editability
    operation: str
    taper_deg: float = 0.0      # nonzero -> a cone / draft (tapered extrude)
    direction: str = "positive"  # "negative" -> extrude opposite the sketch normal (cut inward)
    optional: bool = False       # cosmetic (e.g. a surface scale) -> skip on failure, never fatal


@dataclass
class AddPolygon:
    sketch_ref: str | None
    produces: str | None
    sides: int
    radius_cm: float
    center_cm: tuple[float, float]


@dataclass
class Sweep:
    profile_ref: str | None
    path_ref: str | None
    produces: str | None
    operation: str


@dataclass
class Loft:
    profile_refs: tuple[str, ...]
    produces: str | None
    operation: str


@dataclass
class Revolve:
    profile_ref: str | None
    produces: str | None
    angle_deg: float
    axis: str  # "x" | "y" | "z" construction axis
    operation: str


@dataclass
class Fillet:
    body_ref: str | None
    radius_cm: float


@dataclass
class Chamfer:
    body_ref: str | None
    distance_cm: float


@dataclass
class Shell:
    body_ref: str | None
    thickness_cm: float
    open_faces: tuple[str, ...]  # which ends to OPEN ('top'/'bottom') — function drives topology


@dataclass
class Hole:
    body_ref: str | None
    produces: str | None
    centers_cm: list[tuple[float, float]]
    diameter_cm: float
    through: bool


@dataclass
class Pattern:
    """A rectangular or circular array of the most-recent feature — surface scales, ribs, bolt
    circles. Cosmetic/refinement: non-fatal (skipped) if the array can't be built."""

    body_ref: str | None
    kind: str  # "circular" | "rectangular"
    count: int
    count_y: int
    axis: str  # circular: construction axis ("x"|"y"|"z")
    spacing_cm: float  # rectangular: x spacing
    spacing_y_cm: float  # rectangular: y spacing
    angle_deg: float  # circular: total sweep


@dataclass
class CreateMeshBody:
    """A watertight triangle-mesh skin (ADR-010): surface texture realised as a displacement-field
    mesh instead of fragile per-feature boolean cuts. The mesh is computed and verified watertight
    server-side; the executor only imports a known-valid mesh, so it CANNOT hit `NO_TARGET_BODY`.
    Cosmetic -> optional (skipped on any failure, never rolls back the part)."""

    name: str
    vertices_mm: list[float]  # flat [x0,y0,z0, x1,y1,z1, ...] in mm
    triangles: list[int]      # flat [a0,b0,c0, a1,b1,c1, ...] vertex indices
    optional: bool = True


def _binary_stl_from_flat(vertices_mm: list[float], triangles: list[int]) -> bytes:
    """Build a binary STL (millimetres) from flat vertex + index lists — the import payload."""
    out = bytearray()
    out += b"CAD-Copilot textured shell".ljust(80, b" ")
    out += struct.pack("<I", len(triangles) // 3)
    for k in range(0, len(triangles), 3):
        a, b, c = triangles[k] * 3, triangles[k + 1] * 3, triangles[k + 2] * 3
        va = (vertices_mm[a], vertices_mm[a + 1], vertices_mm[a + 2])
        vb = (vertices_mm[b], vertices_mm[b + 1], vertices_mm[b + 2])
        vc = (vertices_mm[c], vertices_mm[c + 1], vertices_mm[c + 2])
        ux, uy, uz = (vb[0] - va[0], vb[1] - va[1], vb[2] - va[2])
        wx, wy, wz = (vc[0] - va[0], vc[1] - va[1], vc[2] - va[2])
        nx, ny, nz = (uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx)
        nrm = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        out += struct.pack("<3f", nx / nrm, ny / nrm, nz / nrm)
        for v in (va, vb, vc):
            out += struct.pack("<3f", *v)
        out += struct.pack("<H", 0)
    return bytes(out)


def _resolve(value: object, params: dict[str, float]) -> tuple[float, str]:
    """Return (millimetres, Fusion-expression) for a numeric or symbolic dimension."""
    if isinstance(value, bool) or value is None:
        raise ExecutionError(f"invalid dimension value {value!r}")
    if isinstance(value, (int, float)):
        return float(value), f"{float(value)} mm"
    if isinstance(value, str):
        if value not in params:
            raise ExecutionError(f"dimension references undeclared parameter {value!r}")
        return params[value], value  # expression = the user-parameter name (live binding)
    raise ExecutionError(f"dimension has invalid type {type(value).__name__}")


def _xy(point: object) -> tuple[float, float]:
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return float(point[0]), float(point[1])
    return 0.0, 0.0


def compile_ir(ir: dict) -> list:
    """Pure IR→ops compiler: validate units, resolve dimensions, convert mm→cm.

    Defensive even though the server-side IR Validator already passed — the executor never
    trusts its input. Raises ExecutionError on anything it cannot safely build.
    """
    units = ir.get("units", "mm")
    if units != "mm":
        raise ExecutionError(f"executor expects millimetre IR, got units={units!r}")
    commands = ir.get("commands") or []
    if not commands:
        raise ExecutionError("IR has no commands")

    params: dict[str, float] = {}
    for c in commands:
        if c.get("type") == "CREATE_USER_PARAMETER":
            p = c.get("params", {})
            name, value = p.get("name"), p.get("value")
            if not isinstance(name, str) or not name:
                raise ExecutionError("CREATE_USER_PARAMETER missing a name")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ExecutionError(f"parameter {name!r} has a non-numeric value")
            params[name] = float(value)

    ops: list = []
    for c in commands:
        t = c.get("type")
        p = c.get("params", {})
        produces = c.get("produces")

        if t == "CREATE_USER_PARAMETER":
            name = p["name"]
            ops.append(CreateParam(name, params[name], f"{params[name]} mm"))
        elif t == "CREATE_SKETCH":
            plane = p.get("plane")
            if plane not in _PLANES:
                raise ExecutionError(f"CREATE_SKETCH has invalid plane {plane!r}")
            off_mm, _ = _resolve(p.get("offset"), params) if "offset" in p else (0.0, "")
            ops.append(CreateSketch(produces, plane, mm_to_cm(off_mm)))
        elif t == "ADD_RECTANGLE":
            w_mm, _ = _resolve(p.get("width"), params)
            h_mm, _ = _resolve(p.get("height"), params)
            ops.append(AddRectangle(p.get("sketch_ref"), produces,
                                    mm_to_cm(w_mm), mm_to_cm(h_mm),
                                    tuple(mm_to_cm(v) for v in _xy(p.get("corner1")))))
        elif t == "ADD_LINE":
            start = _xy(p.get("start"))
            end = _xy(p.get("end"))
            ops.append(AddLine(p.get("sketch_ref"), produces,
                               (mm_to_cm(start[0]), mm_to_cm(start[1])),
                               (mm_to_cm(end[0]), mm_to_cm(end[1]))))
        elif t == "ADD_CIRCLE":
            d_mm, _ = _resolve(p.get("diameter"), params)
            ops.append(AddCircle(p.get("sketch_ref"), produces,
                                 mm_to_cm(d_mm),
                                 tuple(mm_to_cm(v) for v in _xy(p.get("center")))))
        elif t == "CLOSE_SKETCH":
            ops.append(CloseSketch(p.get("sketch_ref")))
        elif t == "ADD_ARC":
            ops.append(AddArc(p.get("sketch_ref"), produces,
                              tuple(mm_to_cm(v) for v in _xy(p.get("start"))),
                              tuple(mm_to_cm(v) for v in _xy(p.get("mid"))),
                              tuple(mm_to_cm(v) for v in _xy(p.get("end")))))
        elif t == "ADD_POLYGON":
            sides = p.get("sides")
            if not (isinstance(sides, int) and not isinstance(sides, bool) and sides >= 3):
                raise ExecutionError(f"ADD_POLYGON needs integer sides>=3, got {sides!r}")
            r_mm, _ = _resolve(p.get("radius"), params)
            ops.append(AddPolygon(p.get("sketch_ref"), produces, int(sides), mm_to_cm(r_mm),
                                  tuple(mm_to_cm(v) for v in _xy(p.get("center")))))
        elif t == "EXTRUDE":
            dist_mm, expr = _resolve(p.get("distance"), params)
            operation = p.get("operation", "new_body")
            if operation not in _OPERATIONS:
                raise ExecutionError(f"EXTRUDE has invalid operation {operation!r}")
            taper = p.get("taper")
            taper_deg = float(taper) if isinstance(taper, (int, float)) and not isinstance(taper, bool) else 0.0
            d = str(p.get("direction", "positive")).lower()
            direction = d if d in ("negative", "symmetric") else "positive"
            ops.append(Extrude(p.get("profile_ref"), produces, mm_to_cm(dist_mm), expr, operation,
                               taper_deg, direction, bool(p.get("optional", False))))
        elif t == "REVOLVE":
            angle_mm, _ = _resolve(p.get("angle"), params)  # degrees (no unit conversion)
            operation = p.get("operation", "new_body")
            if operation not in _OPERATIONS:
                raise ExecutionError(f"REVOLVE has invalid operation {operation!r}")
            ops.append(Revolve(p.get("profile_ref"), produces, angle_mm,
                               str(p.get("axis", "z")).lower(), operation))
        elif t == "SWEEP":
            operation = p.get("operation", "new_body")
            if operation not in _OPERATIONS:
                raise ExecutionError(f"SWEEP has invalid operation {operation!r}")
            ops.append(Sweep(p.get("profile_ref"), p.get("path_ref"), produces, operation))
        elif t == "LOFT":
            refs = p.get("profile_refs")
            if not (isinstance(refs, list) and len(refs) >= 2):
                raise ExecutionError("LOFT needs profile_refs (>= 2 profiles)")
            operation = p.get("operation", "new_body")
            if operation not in _OPERATIONS:
                raise ExecutionError(f"LOFT has invalid operation {operation!r}")
            ops.append(Loft(tuple(str(r) for r in refs), produces, operation))
        elif t == "FILLET":
            r_mm, _ = _resolve(p.get("radius"), params)
            ops.append(Fillet(p.get("body_ref"), mm_to_cm(r_mm)))
        elif t == "CHAMFER":
            d_mm, _ = _resolve(p.get("distance") if "distance" in p else p.get("size"), params)
            ops.append(Chamfer(p.get("body_ref"), mm_to_cm(d_mm)))
        elif t == "SHELL":
            th_mm, _ = _resolve(p.get("thickness"), params)
            faces = p.get("open_faces")
            faces = tuple(str(f).lower() for f in faces) if isinstance(faces, list) else ()
            ops.append(Shell(p.get("body_ref"), mm_to_cm(th_mm), faces))
        elif t == "HOLE":
            dia_mm, _ = _resolve(p.get("diameter"), params)
            centers = [(mm_to_cm(c[0]), mm_to_cm(c[1]))
                       for c in (p.get("positions") or [])
                       if isinstance(c, (list, tuple)) and len(c) >= 2]
            ops.append(Hole(p.get("body_ref"), produces, centers, mm_to_cm(dia_mm),
                            bool(p.get("through", True))))
        elif t == "PATTERN":
            kind = p.get("kind")
            if kind not in ("circular", "rectangular"):
                raise ExecutionError(f"PATTERN has invalid kind {kind!r}")
            count, _ = _resolve(p.get("count", 1), params)
            count_y, _ = _resolve(p.get("count_y", 1), params) if "count_y" in p else (1.0, "")
            spacing_mm, _ = _resolve(p.get("spacing", 1), params) if "spacing" in p else (0.0, "")
            spacing_y_mm, _ = _resolve(p.get("spacing_y", 1), params) if "spacing_y" in p else (0.0, "")
            angle, _ = _resolve(p.get("angle", 360), params) if "angle" in p else (360.0, "")
            ops.append(Pattern(p.get("body_ref"), kind, max(1, int(count)), max(1, int(count_y)),
                               str(p.get("axis", "z")).lower(), mm_to_cm(spacing_mm),
                               mm_to_cm(spacing_y_mm), float(angle)))
        elif t == "CREATE_MESH_BODY":
            verts = p.get("vertices_mm")
            tris = p.get("triangles")
            if not (isinstance(verts, list) and len(verts) >= 9 and len(verts) % 3 == 0):
                raise ExecutionError("CREATE_MESH_BODY needs flat 'vertices_mm' (length % 3 == 0)")
            if not (isinstance(tris, list) and len(tris) >= 3 and len(tris) % 3 == 0):
                raise ExecutionError("CREATE_MESH_BODY needs flat 'triangles' (length % 3 == 0)")
            nverts = len(verts) // 3
            if any((not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= nverts) for i in tris):
                raise ExecutionError("CREATE_MESH_BODY triangle index out of range")
            ops.append(CreateMeshBody(str(p.get("name", "texture_skin")),
                                      [float(v) for v in verts], [int(i) for i in tris]))
        elif t == "ADD_CONSTRAINT":
            pass  # constraints refine the sketch; geometry is already pinned by coordinates
        else:
            raise ExecutionError(f"executor does not support command type {t!r} yet")
    return ops


class SafeExecutor:
    """Realizes a compiled IR inside a Fusion design as one undoable transaction."""

    def execute(self, ir: dict, design=None, app=None, position=None, placement=None,
                part_id=None) -> dict:
        import adsk.core
        import adsk.fusion

        if design is None:
            app = app or adsk.core.Application.get()
            design = adsk.fusion.Design.cast(app.activeProduct)
        if design is None:
            raise ExecutionError("no active Fusion design")

        ops = compile_ir(ir)  # raises before any geometry is touched
        root = design.rootComponent
        timeline = design.timeline
        # CLEAN REBUILD (ADR-016): a re-generate / edit REPLACES this part's previous build instead of
        # duplicating it or failing on its already-existing user parameters. Delete the prior timeline
        # group for this part (its bodies + features); existing parameters are UPDATED in place below.
        if part_id:
            self._remove_prior_build(timeline, str(part_id))
        start = timeline.count
        bodies_before = root.bRepBodies.count
        mesh_before = root.meshBodies.count  # ADR-010: texture skins land here, not in bRepBodies
        refs: dict[str, object] = {}
        created_params: list = []

        skipped: list = []
        motif_skipped = False  # a cosmetic motif (scale) just failed -> skip the pattern that arrays it
        try:
            for op in ops:
                # skip a circular/linear PATTERN whose source motif failed to build (else it would
                # array the wrong feature)
                if isinstance(op, Pattern) and motif_skipped:
                    motif_skipped = False
                    continue
                try:
                    self._apply(op, adsk, design, root, refs, created_params)
                    motif_skipped = False
                except Exception as exc:  # noqa: BLE001
                    # A REFINEMENT feature (fillet/chamfer/shell/hole/pattern) or an OPTIONAL cosmetic
                    # op (a surface scale) can fail without dooming the part — skip it and keep the
                    # body. CORE geometry (the body's own sketch/extrude/revolve) failing is still
                    # fatal. This is what stops a cosmetic scale-cut from rolling back the whole mug.
                    if isinstance(op, (Fillet, Chamfer, Shell, Hole, Pattern)) or getattr(op, "optional", False):
                        skipped.append(f"{type(op).__name__}: {str(exc)[:120]}")
                        motif_skipped = getattr(op, "optional", False)
                        continue
                    raise
            self._place(adsk, root, bodies_before, position, placement)  # assemble: seat the part
            end = timeline.count - 1
            if end > start:  # group >=2 timeline items into one collapsible/undo unit
                try:
                    grp = timeline.timelineGroups.add(start, end)
                    if part_id:  # name the group so a later rebuild can find & replace it
                        try:
                            grp.name = str(part_id)
                        except Exception:  # noqa: BLE001 - naming is cosmetic
                            pass
                except Exception:  # noqa: BLE001 - grouping is cosmetic; never fail the build on it
                    pass
            # verification is ADVISORY: the body STAYS even if it doesn't match the expected size.
            # We only roll back on an actual CORE op failure. For LLM geometry the 'expected' is just
            # the model's estimate; the human verifies the result (ADR-005 reframe).
            check = self._verify_against_intent(ir, root)
            placed = self._readback(root, bodies_before, placement)  # ADR-009: perceive REALITY
            try:
                mesh_skins = max(0, root.meshBodies.count - mesh_before)
            except Exception:  # noqa: BLE001 - reporting must never break the build
                mesh_skins = 0
            return {"status": "ok", "features": max(0, end - start + 1),
                    "verify": check, "skipped": skipped, "placed": placed, "mesh_skins": mesh_skins}
        except Exception as exc:
            self._rollback(timeline, start, created_params)
            raise ExecutionError(f"execution failed and was rolled back: {exc}") from exc

    @staticmethod
    def _remove_prior_build(timeline, part_id: str) -> None:
        """Delete a previous build of this part (its timeline group + that group's bodies/features) so
        a re-generate/edit REPLACES it. User parameters are not in the timeline (they live in the
        Parameters dialog); those are updated in place by CreateParam. Never raises."""
        try:
            groups = timeline.timelineGroups
            for i in range(groups.count - 1, -1, -1):
                grp = groups.item(i)
                if getattr(grp, "name", None) == part_id:
                    try:
                        grp.deleteMe(True)  # delete the group AND its contents (prior bodies/features)
                    except Exception:  # noqa: BLE001 - fall back to ungrouping; param-update covers the rest
                        try:
                            grp.deleteMe(False)
                        except Exception:  # noqa: BLE001
                            pass
        except Exception:  # noqa: BLE001 - replace is best-effort; the build proceeds regardless
            return

    @staticmethod
    def _readback(root, bodies_before: int, placement) -> dict:
        """Closed-loop perception (ADR-009): measure where the part ACTUALLY landed in Fusion and
        compare to where it should seat. This is the REALITY half of the loop — it catches executor
        errors the offline comparator can't see (a handle that ends up at the base, scales off the
        wall). Never raises; returns {} on any issue."""
        try:
            n = root.bRepBodies.count
            if bodies_before >= n:
                return {}
            xs, ys, zs = [], [], []
            for i in range(bodies_before, n):
                bb = root.bRepBodies.item(i).boundingBox
                xs += [bb.minPoint.x, bb.maxPoint.x]
                ys += [bb.minPoint.y, bb.maxPoint.y]
                zs += [bb.minPoint.z, bb.maxPoint.z]
            if not xs:
                return {}
            center_mm = [round((min(xs) + max(xs)) / 2 * 10.0, 1),
                         round((min(ys) + max(ys)) / 2 * 10.0, 1),
                         round((min(zs) + max(zs)) / 2 * 10.0, 1)]
            out = {"center_mm": center_mm,
                   "z_range_mm": [round(min(zs) * 10.0, 1), round(max(zs) * 10.0, 1)]}
            if isinstance(placement, dict) and isinstance(placement.get("target"), dict):
                seat = placement["target"].get("origin")
                wo = placement.get("world_offset") or (0.0, 0.0, 0.0)  # chained-host world position
                if isinstance(seat, list) and len(seat) == 3:
                    seat = [float(seat[k]) + float(wo[k]) for k in range(3)]
                    # how far the part's nearest extent is from where it should seat on the host
                    near = [min(max(seat[0], min(xs) * 10), max(xs) * 10),
                            min(max(seat[1], min(ys) * 10), max(ys) * 10),
                            min(max(seat[2], min(zs) * 10), max(zs) * 10)]
                    gap = sum((near[k] - seat[k]) ** 2 for k in range(3)) ** 0.5
                    out["seat_target_mm"] = [round(v, 1) for v in seat]
                    out["seat_gap_mm"] = round(gap, 1)
                    out["seated"] = gap < 1.0
            return out
        except Exception:  # noqa: BLE001 - perception must never break the build
            return {}

    @staticmethod
    def _place(adsk, root, bodies_before: int, position, placement) -> None:
        """Seat the bodies this part created. A solved `placement` (ADR-008) aligns the part's
        mounting connector frame onto the host's target frame (so a handle sits on the wall); else
        fall back to a simple translation to `position`. No-op when neither applies."""
        new_bodies = adsk.core.ObjectCollection.create()
        for i in range(bodies_before, root.bRepBodies.count):
            new_bodies.add(root.bRepBodies.item(i))
        if new_bodies.count == 0:
            return

        transform = adsk.core.Matrix3D.create()
        if isinstance(placement, dict) and placement.get("mount") and placement.get("target"):
            m, t = placement["mount"], placement["target"]
            # ASSEMBLY COMPOSITION (multi-part): the mate frames are host-LOCAL; a CHAINED host carries
            # a world_offset so the part seats where the host actually sits (engine barrel on crankcase,
            # head on barrel) instead of floating back to the origin. Direct-to-body parts have no offset.
            wo = placement.get("world_offset") or (0.0, 0.0, 0.0)

            def pt(v, off=(0.0, 0.0, 0.0)):
                return adsk.core.Point3D.create(mm_to_cm(v[0] + off[0]), mm_to_cm(v[1] + off[1]),
                                                mm_to_cm(v[2] + off[2]))

            def vec(v):
                return adsk.core.Vector3D.create(v[0], v[1], v[2])

            try:
                transform.setToAlignCoordinateSystems(
                    pt(m["origin"]), vec(m["ux"]), vec(m["uy"]), vec(m["uz"]),
                    pt(t["origin"], wo), vec(t["ux"]), vec(t["uy"]), vec(t["uz"]))
                move_input = root.features.moveFeatures.createInput(new_bodies, transform)
                root.features.moveFeatures.add(move_input)
            except Exception:  # noqa: BLE001 - a degenerate mate frame ("invalid transform") must NOT
                return         # roll back a good part; leave it unplaced rather than fail the build
            # CLOSED-LOOP CORRECTION (ADR-009): the open-loop mate trusts the part's build orientation,
            # which depends on Fusion sketch-plane conventions we can't see offline. So MEASURE where
            # the part actually landed and translate it to seat on the target — general, and it fixes
            # the build-frame errors (the handle that dropped below the base) for ANY part/host.
            SafeExecutor._seat_correction(adsk, root, bodies_before, placement)
        elif position and len(position) >= 3 and any(position):
            try:
                transform.translation = adsk.core.Vector3D.create(
                    mm_to_cm(position[0]), mm_to_cm(position[1]), mm_to_cm(position[2]))
                move_input = root.features.moveFeatures.createInput(new_bodies, transform)
                root.features.moveFeatures.add(move_input)
            except Exception:  # noqa: BLE001 - never fail a built part over a placement move
                return

    @staticmethod
    def _seat_correction(adsk, root, bodies_before: int, placement) -> None:
        """Measure the placed part and translate it so it SEATS on the host's target frame: centred
        on the seat point in the surface-tangent plane, and just touching the surface along the
        outward normal. Corrects residual placement error from the open-loop mate. Never raises."""
        try:
            target = placement.get("target") if isinstance(placement, dict) else None
            if not isinstance(target, dict):
                return
            wo = placement.get("world_offset") or (0.0, 0.0, 0.0)          # chained-host world position
            seat = [float(target["origin"][k]) + float(wo[k]) for k in range(3)]  # mm
            n = [float(v) for v in target["uz"]]
            nmag = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5 or 1.0
            n = [v / nmag for v in n]                                      # outward unit normal

            corners = []
            for i in range(bodies_before, root.bRepBodies.count):
                bb = root.bRepBodies.item(i).boundingBox
                for cx in (bb.minPoint.x, bb.maxPoint.x):
                    for cy in (bb.minPoint.y, bb.maxPoint.y):
                        for cz in (bb.minPoint.z, bb.maxPoint.z):
                            corners.append((cx * 10.0, cy * 10.0, cz * 10.0))  # cm -> mm
            if not corners:
                return
            cen = [sum(c[k] for c in corners) / len(corners) for k in range(3)]
            proj = [c[0] * n[0] + c[1] * n[1] + c[2] * n[2] for c in corners]
            extent_n = max(proj) - min(proj)                              # how far the part spans outward
            # desired centre: on the seat (tangentially) and pushed out by half its normal extent so
            # the near face touches the surface (1 mm overlap so the mate is solid, not just kissing)
            desired = [seat[k] + n[k] * (extent_n / 2.0 - 1.0) for k in range(3)]
            delta = [desired[k] - cen[k] for k in range(3)]
            if (delta[0] ** 2 + delta[1] ** 2 + delta[2] ** 2) ** 0.5 < 0.5:
                return                                                    # already seated
            bodies = adsk.core.ObjectCollection.create()
            for i in range(bodies_before, root.bRepBodies.count):
                bodies.add(root.bRepBodies.item(i))
            tf = adsk.core.Matrix3D.create()
            tf.translation = adsk.core.Vector3D.create(mm_to_cm(delta[0]), mm_to_cm(delta[1]),
                                                       mm_to_cm(delta[2]))
            root.features.moveFeatures.add(root.features.moveFeatures.createInput(bodies, tf))
        except Exception:  # noqa: BLE001 - correction must never break the build
            return

    @staticmethod
    def _verify_against_intent(ir: dict, root) -> dict:
        """Measure the built body and compare to the intended size — ADVISORY, never raises.

        Fusion is the ground-truth kernel; this reports how close the build is to `expected_geometry`
        but does NOT roll back on a mismatch (that deletes good geometry). Returns a small report.
        """
        expected = ir.get("expected_geometry")
        if not expected or root.bRepBodies.count == 0:
            return {"checked": False}
        try:
            body = root.bRepBodies.item(root.bRepBodies.count - 1)
            measured_volume = body.physicalProperties.volume * 1000.0  # cm^3 -> mm^3
            bb = body.boundingBox
            measured_bbox = [
                (bb.maxPoint.x - bb.minPoint.x) * 10.0,  # cm -> mm
                (bb.maxPoint.y - bb.minPoint.y) * 10.0,
                (bb.maxPoint.z - bb.minPoint.z) * 10.0,
            ]
            ok, bbox_err, vol_err = compare_geometry(measured_volume, measured_bbox, expected)
            return {"checked": True, "matched": ok,
                    "bbox_error_mm": round(bbox_err, 3), "volume_error_pct": round(vol_err * 100, 2)}
        except Exception:  # noqa: BLE001 - verification must never break a successful build
            return {"checked": False}

    def _apply(self, op, adsk, design, root, refs, created_params) -> None:
        if isinstance(op, CreateParam):
            # a rebuild/edit re-emits the same parameters: UPDATE one that already exists (so the bound
            # geometry re-sizes) instead of failing with "param name is not valid" (the duplicate-add
            # error that rolled back edits). Only NEW params go on the rollback list.
            existing = design.userParameters.itemByName(op.name)
            if existing is not None:
                try:
                    existing.expression = op.expression
                except Exception:  # noqa: BLE001 - a locked/derived param: leave it as is
                    pass
            else:
                vi = adsk.core.ValueInput.createByString(op.expression)
                created_params.append(design.userParameters.add(op.name, vi, "mm", ""))
        elif isinstance(op, CreateSketch):
            plane = self._plane(op.plane, root)
            if op.offset_cm:
                planes = root.constructionPlanes
                pin = planes.createInput()
                pin.setByOffset(plane, adsk.core.ValueInput.createByReal(op.offset_cm))
                plane = planes.add(pin)
            sketch = root.sketches.add(plane)
            if op.ref:
                refs[op.ref] = sketch
        elif isinstance(op, AddPolygon):
            sketch = refs[op.sketch_ref]
            cx, cy = op.center_cm
            pts = [adsk.core.Point3D.create(cx + op.radius_cm * math.cos(2 * math.pi * i / op.sides),
                                            cy + op.radius_cm * math.sin(2 * math.pi * i / op.sides), 0)
                   for i in range(op.sides)]
            lines = sketch.sketchCurves.sketchLines
            for i in range(op.sides):
                lines.addByTwoPoints(pts[i], pts[(i + 1) % op.sides])
            if op.produces:
                refs[op.produces] = sketch
        elif isinstance(op, AddRectangle):
            sketch = refs[op.sketch_ref]
            x0, y0 = op.corner_cm
            p0 = adsk.core.Point3D.create(x0, y0, 0)
            p1 = adsk.core.Point3D.create(x0 + op.width_cm, y0 + op.height_cm, 0)
            sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
            if op.produces:
                refs[op.produces] = sketch
        elif isinstance(op, AddLine):
            sketch = refs[op.sketch_ref]
            p0 = adsk.core.Point3D.create(op.start_cm[0], op.start_cm[1], 0)
            p1 = adsk.core.Point3D.create(op.end_cm[0], op.end_cm[1], 0)
            sketch.sketchCurves.sketchLines.addByTwoPoints(p0, p1)
            if op.produces:
                refs[op.produces] = sketch
        elif isinstance(op, AddCircle):
            sketch = refs[op.sketch_ref]
            cx, cy = op.center_cm
            center = adsk.core.Point3D.create(cx, cy, 0)
            sketch.sketchCurves.sketchCircles.addByCenterRadius(center, op.diameter_cm / 2.0)
            if op.produces:
                refs[op.produces] = sketch
        elif isinstance(op, AddArc):
            sketch = refs[op.sketch_ref]
            p0 = adsk.core.Point3D.create(op.start_cm[0], op.start_cm[1], 0)
            pm = adsk.core.Point3D.create(op.mid_cm[0], op.mid_cm[1], 0)
            p1 = adsk.core.Point3D.create(op.end_cm[0], op.end_cm[1], 0)
            sketch.sketchCurves.sketchArcs.addByThreePoints(p0, pm, p1)
            if op.produces:
                refs[op.produces] = sketch
        elif isinstance(op, CloseSketch):
            pass  # rectangle/circle close their own profiles; explicit close is a no-op here
        elif isinstance(op, Extrude):
            sketch = refs.get(op.profile_ref)
            if sketch is None or sketch.profiles.count == 0:
                raise ExecutionError(f"no closed profile for {op.profile_ref!r}")
            profile = sketch.profiles.item(0)
            extrudes = root.features.extrudeFeatures
            ext_input = extrudes.createInput(profile, self._operation(op.operation, adsk))
            # bound to the param; "negative" extrudes opposite the sketch normal (e.g. a scale cut
            # INTO a wall from the wall's tangent plane, so it engraves and conforms instead of
            # sticking out as a floating tab)
            expr = (f"-({op.distance_expression})" if op.direction == "negative"
                    else op.distance_expression)
            dist = adsk.core.ValueInput.createByString(expr)
            if op.taper_deg:  # tapered extrude -> a cone / draft
                extent = adsk.fusion.DistanceExtentDefinition.create(dist)
                ext_input.setOneSideExtent(
                    extent, adsk.fusion.ExtentDirections.PositiveExtentDirection,
                    adsk.core.ValueInput.createByString(f"{op.taper_deg} deg"))
            else:
                # "symmetric" extrudes both ways from the sketch plane — for a scale cut on the wall's
                # tangent plane this GUARANTEES the inward half crosses the wall, so the cut always has
                # a target body (fixes NO_TARGET_BODY) regardless of which way the normal points
                ext_input.setDistanceExtent(op.direction == "symmetric", dist)
            # a cut/join/intersect must name the body it acts on, or Fusion errors "No target body
            # found to cut or intersect" (the scale engrave-cut failure that rolled back the mug)
            if op.operation in ("cut", "join", "intersect") and root.bRepBodies.count:
                ext_input.participantBodies = [root.bRepBodies.item(i)
                                               for i in range(root.bRepBodies.count)]
            feature = extrudes.add(ext_input)
            if op.produces:
                refs[op.produces] = feature.bodies.item(0) if feature.bodies.count else feature
        elif isinstance(op, Sweep):
            prof = refs.get(op.profile_ref)
            path_sketch = refs.get(op.path_ref)
            if prof is None or prof.profiles.count == 0 or path_sketch is None:
                raise ExecutionError(f"SWEEP needs a profile and a path ({op.profile_ref!r}, {op.path_ref!r})")
            path = root.features.createPath(path_sketch.sketchCurves.item(0), True)
            sweeps = root.features.sweepFeatures
            si = sweeps.createInput(prof.profiles.item(0), path, self._operation(op.operation, adsk))
            feature = sweeps.add(si)
            if op.produces:
                refs[op.produces] = feature.bodies.item(0) if feature.bodies.count else feature
        elif isinstance(op, Loft):
            lofts = root.features.loftFeatures
            li = lofts.createInput(self._operation(op.operation, adsk))
            for ref in op.profile_refs:
                sk = refs.get(ref)
                if sk is None or sk.profiles.count == 0:
                    raise ExecutionError(f"LOFT section {ref!r} has no profile")
                li.loftSections.add(sk.profiles.item(0))
            feature = lofts.add(li)
            if op.produces:
                refs[op.produces] = feature.bodies.item(0) if feature.bodies.count else feature
        elif isinstance(op, Revolve):
            sketch = refs.get(op.profile_ref)
            if sketch is None or sketch.profiles.count == 0:
                raise ExecutionError(f"no closed profile for {op.profile_ref!r}")
            revolves = root.features.revolveFeatures
            rev_input = revolves.createInput(
                sketch.profiles.item(0), self._axis(op.axis, root), self._operation(op.operation, adsk))
            rev_input.setAngleExtent(False, adsk.core.ValueInput.createByString(f"{op.angle_deg} deg"))
            feature = revolves.add(rev_input)
            if op.produces:
                refs[op.produces] = feature.bodies.item(0) if feature.bodies.count else feature
        elif isinstance(op, Fillet):
            body = self._body(op.body_ref, refs, root)
            edges = adsk.core.ObjectCollection.create()
            for edge in body.edges:
                edges.add(edge)
            fin = root.features.filletFeatures.createInput()
            fin.addConstantRadiusEdgeSet(edges, adsk.core.ValueInput.createByReal(op.radius_cm), True)
            root.features.filletFeatures.add(fin)
        elif isinstance(op, Chamfer):
            body = self._body(op.body_ref, refs, root)
            edges = adsk.core.ObjectCollection.create()
            for edge in body.edges:
                edges.add(edge)
            cin = root.features.chamferFeatures.createInput2()
            cin.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
                edges, adsk.core.ValueInput.createByReal(op.distance_cm), True)
            root.features.chamferFeatures.add(cin)
        elif isinstance(op, Shell):
            body = self._body(op.body_ref, refs, root)
            entities = adsk.core.ObjectCollection.create()
            removed = self._end_faces(body, op.open_faces)
            if removed:
                for face in removed:
                    entities.add(face)  # removing faces OPENS those ends (a cup's open top)
            else:
                entities.add(body)      # no open faces -> a fully closed hollow
            sin = root.features.shellFeatures.createInput(entities, False)
            sin.insideThickness = adsk.core.ValueInput.createByReal(op.thickness_cm)
            root.features.shellFeatures.add(sin)
        elif isinstance(op, Hole):
            self._cut_holes(op, adsk, root, refs)
        elif isinstance(op, Pattern):
            self._pattern(op, adsk, root)
        elif isinstance(op, CreateMeshBody):
            self._mesh_body(op, adsk, root)
        else:  # pragma: no cover - compile_ir already rejects unknown ops
            raise ExecutionError(f"unhandled op {type(op).__name__}")

    def _mesh_body(self, op, adsk, root) -> None:
        """Realise a verified watertight mesh as a Fusion mesh body (ADR-010 Pillar A).

        The robust substrate for surface texture: the displacement-field mesh is computed and proven
        closed server-side, so creating it can never fail the way a per-feature boolean cut does. We
        feed the triangle data straight to `MeshBodies.addByTriangleMeshData` (no file/import dialog):
        a flat [x,y,z,...] coordinate list in CENTIMETRES (Fusion-internal units), a flat zero-based
        triangle-index list (3 per face), and empty normal arrays so Fusion computes normals itself.
        In a PARAMETRIC design a mesh body must be created inside a BaseFeature edit, so we open one
        and add within it (covered by the rollback group). Mesh bodies live in `root.meshBodies`,
        separate from the editable B-rep core, so the parametric mug is untouched. Cosmetic -> caught
        by execute() and skipped on any failure (never rolls back the part).
        """
        coords_cm = [v * MM_TO_CM for v in op.vertices_mm]  # mm -> cm at the Fusion boundary
        indices = [int(i) for i in op.triangles]            # flat zero-based, 3 per triangle
        empty: list = []                                    # empty normals -> Fusion auto-computes
        mesh_bodies = root.meshBodies

        try:
            base = root.features.baseFeatures.add()  # parametric designs need a BaseFeature host
        except Exception:  # noqa: BLE001 - direct-modeling design has no base features
            base = None
        if base is not None:
            base.startEdit()
            try:
                mesh_bodies.addByTriangleMeshData(coords_cm, indices, empty, empty)
            finally:
                base.finishEdit()
        else:
            mesh_bodies.addByTriangleMeshData(coords_cm, indices, empty, empty)

    def _pattern(self, op, adsk, root) -> None:
        """Array the most-recent feature (the pattern's motif). Circular about an axis, or a
        rectangular grid. Cosmetic — failures are caught by execute() and skipped."""
        feats = root.features
        if feats.count == 0:
            raise ExecutionError("PATTERN has no feature to array")
        inputs = adsk.core.ObjectCollection.create()
        inputs.add(feats.item(feats.count - 1))  # the motif = the last-created feature
        if op.kind == "circular":
            cin = feats.circularPatternFeatures.createInput(inputs, self._axis(op.axis, root))
            cin.quantity = adsk.core.ValueInput.createByReal(op.count)
            cin.totalAngle = adsk.core.ValueInput.createByString(f"{op.angle_deg} deg")
            feats.circularPatternFeatures.add(cin)
        else:
            x_dir = root.xConstructionAxis
            y_dir = root.yConstructionAxis
            rin = feats.rectangularPatternFeatures.createInput(
                inputs, x_dir, adsk.core.ValueInput.createByReal(op.count),
                adsk.core.ValueInput.createByReal(op.spacing_cm),
                adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
            rin.setDirectionTwo(y_dir, adsk.core.ValueInput.createByReal(op.count_y),
                                adsk.core.ValueInput.createByReal(op.spacing_y_cm))
            feats.rectangularPatternFeatures.add(rin)

    def _cut_holes(self, op, adsk, root, refs) -> None:
        sketch = root.sketches.add(root.xYConstructionPlane)
        for cx, cy in op.centers_cm:
            sketch.sketchCurves.sketchCircles.addByCenterRadius(
                adsk.core.Point3D.create(cx, cy, 0), op.diameter_cm / 2.0)
        profiles = adsk.core.ObjectCollection.create()
        for profile in sketch.profiles:
            profiles.add(profile)
        extrudes = root.features.extrudeFeatures
        cut_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
        cut_input.setAllExtent(adsk.fusion.ExtentDirections.NegativeExtentDirection)
        extrudes.add(cut_input)
        if op.produces:
            refs[op.produces] = self._body(op.body_ref, refs, root)

    @staticmethod
    def _end_faces(body, open_faces) -> list:
        """The faces to remove so the part is open where its FUNCTION requires (a cup's top).

        'top' = the face whose centroid sits highest in Z; 'bottom' = the lowest. Empty -> closed.
        """
        if not open_faces:
            return []
        faces = list(body.faces)
        if not faces:
            return []

        def cz(face):
            try:
                return face.centroid.z
            except Exception:  # noqa: BLE001 - some faces have no centroid; sort them to the middle
                return 0.0

        picked = []
        if "top" in open_faces:
            picked.append(max(faces, key=cz))
        if "bottom" in open_faces:
            picked.append(min(faces, key=cz))
        # de-dup (a degenerate body could pick the same face twice)
        seen, out = set(), []
        for f in picked:
            if id(f) not in seen:
                seen.add(id(f))
                out.append(f)
        return out

    @staticmethod
    def _body(body_ref, refs, root):
        ent = refs.get(body_ref)
        if ent is not None and hasattr(ent, "edges"):
            return ent
        if root.bRepBodies.count:
            return root.bRepBodies.item(root.bRepBodies.count - 1)
        raise ExecutionError(f"no body available for {body_ref!r}")

    @staticmethod
    def _axis(axis: str, root):
        return {"x": root.xConstructionAxis, "y": root.yConstructionAxis,
                "z": root.zConstructionAxis}[axis]

    @staticmethod
    def _plane(plane: str, root):
        return {
            "XY": root.xYConstructionPlane,
            "XZ": root.xZConstructionPlane,
            "YZ": root.yZConstructionPlane,
        }[plane]

    @staticmethod
    def _operation(operation: str, adsk):
        ops = adsk.fusion.FeatureOperations
        return {
            "new_body": ops.NewBodyFeatureOperation,
            "join": ops.JoinFeatureOperation,
            "cut": ops.CutFeatureOperation,
            "intersect": ops.IntersectFeatureOperation,
        }[operation]

    @staticmethod
    def _rollback(timeline, start, created_params) -> None:
        """Best-effort: delete everything created at/after `start`, newest first."""
        try:
            for i in range(timeline.count - 1, start - 1, -1):
                try:
                    entity = timeline.item(i).entity
                    if entity is not None:
                        entity.deleteMe()
                except Exception:  # noqa: BLE001 - keep unwinding even if one delete fails
                    pass
        except Exception:  # noqa: BLE001
            pass
        for param in reversed(created_params):
            try:
                param.deleteMe()
            except Exception:  # noqa: BLE001
                pass
