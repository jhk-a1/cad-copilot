"""IR Validator (M1-W3-BE-04) — the semantic gate between generation and execution.

Frontier models are strong at *intent* and weak at *validity*: they emit IR that parses but
is semantically broken (dangling refs, cycles, a profile extruded before its sketch closes,
a symbolic dimension that was never declared). Pydantic guarantees the IR is well-*typed*;
this validator guarantees it is well-*formed as a build program* before anything reaches
Fusion. Nothing that fails here is ever executed (ADR-002: accuracy is non-negotiable — we
refuse rather than emit wrong geometry).

The checks, in order:
  1. units are millimetres (the executor's single conversion assumption)
  2. command ids are unique; the dependency graph is a DAG (no cycles, no dangling/self deps)
  3. every consumed entity ref (sketch/profile/body/edge) is produced by an earlier command
  4. per-command params are well-formed (valid plane/operation; positive, declared dimensions)
  5. symbolic dimensions resolve to a CREATE_USER_PARAMETER (no free-floating names)
  6. a profile is only extruded/revolved after its sketch is closed
  7. expected_geometry is internally sane; rollback points are real command ids

Errors block execution; warnings are advisory (surfaced to the user, build still proceeds).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...models import CommandIR, IRCommand, IRCommandType

# --- allowlisted enum values for free-form param fields ----------------------------------
_PLANES = {"XY", "XZ", "YZ"}
_OPERATIONS = {"new_body", "join", "cut", "intersect"}

# params naming an entity that must have been produced by an earlier command
_REF_KEYS = ("sketch_ref", "profile_ref", "body_ref", "edge_ref", "face_ref", "path_ref")

# scalar params that must be a positive number OR the name of a declared user parameter
_DIMENSION_KEYS = (
    "width", "height", "distance", "radius", "diameter", "depth",
    "length", "leg_a", "leg_b", "thickness", "size", "angle", "value",
)

# which entity ref each command type is required to consume
_REQUIRED_REF = {
    IRCommandType.ADD_LINE: "sketch_ref",
    IRCommandType.ADD_CIRCLE: "sketch_ref",
    IRCommandType.ADD_RECTANGLE: "sketch_ref",
    IRCommandType.ADD_ARC: "sketch_ref",
    IRCommandType.ADD_POLYGON: "sketch_ref",
    IRCommandType.ADD_CONSTRAINT: "sketch_ref",
    IRCommandType.CLOSE_SKETCH: "sketch_ref",
    IRCommandType.EXTRUDE: "profile_ref",
    IRCommandType.REVOLVE: "profile_ref",
    IRCommandType.SWEEP: "profile_ref",
}

_SKETCH_GEOMETRY = {
    IRCommandType.ADD_LINE, IRCommandType.ADD_CIRCLE,
    IRCommandType.ADD_RECTANGLE, IRCommandType.ADD_ARC, IRCommandType.ADD_POLYGON,
}


@dataclass(frozen=True)
class Issue:
    """A single validation finding, with a stable machine code for diagnostics/telemetry."""

    code: str
    message: str
    command_id: int | None = None


@dataclass
class ValidationReport:
    valid: bool
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def error_codes(self) -> set[str]:
        return {i.code for i in self.errors}

    def summary(self) -> str:
        return "; ".join(f"{i.code}: {i.message}" for i in self.errors)


class IRValidator:
    """Stateless. `validate(ir)` returns a full report (it does not stop at the first error)."""

    def validate(self, ir: CommandIR) -> ValidationReport:
        errors: list[Issue] = []
        warnings: list[Issue] = []
        cmds = ir.commands

        if ir.units != "mm":
            errors.append(Issue("IR_UNITS", f"IR units must be 'mm', got {ir.units!r}"))
        if not cmds:
            errors.append(Issue("IR_EMPTY", "IR has no commands"))
            return ValidationReport(False, errors, warnings)

        # --- ids, dependency graph -------------------------------------------------------
        id_set: set[int] = set()
        for c in cmds:
            if c.id in id_set:
                errors.append(Issue("IR_DUP_ID", f"duplicate command id {c.id}", c.id))
            id_set.add(c.id)
        index = {c.id: i for i, c in enumerate(cmds)}

        for c in cmds:
            for d in c.depends_on:
                if d == c.id:
                    errors.append(Issue("IR_SELF_DEP", f"command {c.id} depends on itself", c.id))
                elif d not in id_set:
                    errors.append(Issue("IR_BAD_DEP", f"command {c.id} depends on missing id {d}", c.id))
                elif index[d] >= index[c.id]:
                    errors.append(Issue("IR_DEP_ORDER",
                                        f"command {c.id} depends on later command {d}", c.id))
        if self._has_cycle(cmds, id_set):
            errors.append(Issue("IR_DAG_CYCLE", "dependency graph contains a cycle"))

        # --- declared parameters and produced entities -----------------------------------
        declared: set[str] = set()
        for c in cmds:
            if c.type is IRCommandType.CREATE_USER_PARAMETER:
                name = c.params.get("name")
                if isinstance(name, str) and name:
                    declared.add(name)

        produced: dict[str, IRCommand] = {}
        for c in cmds:
            if c.produces:
                if c.produces in produced:
                    errors.append(Issue("IR_DUP_PRODUCES",
                                        f"entity ref {c.produces!r} produced more than once", c.id))
                else:
                    produced[c.produces] = c

        # --- per-command checks ----------------------------------------------------------
        for c in cmds:
            self._check_command(c, declared, produced, index, errors, warnings)

        # --- sketch lifecycle: extrude/revolve only after the sketch is closed -----------
        self._check_lifecycle(cmds, produced, index, errors)

        # --- expected geometry sanity ----------------------------------------------------
        self._check_expected_geometry(ir, errors, warnings)

        # --- rollback points must be real command ids ------------------------------------
        for rp in ir.rollback_points:
            if rp not in id_set:
                errors.append(Issue("IR_ROLLBACK_BAD", f"rollback point {rp} is not a command id"))

        return ValidationReport(not errors, errors, warnings)

    # ----------------------------------------------------------------------------- helpers

    def _check_command(self, c, declared, produced, index, errors, warnings) -> None:
        t, p = c.type, c.params

        # required entity ref present?
        req = _REQUIRED_REF.get(t)
        if req is not None and req not in p:
            errors.append(Issue("IR_MISSING_REF", f"{t} requires '{req}'", c.id))

        # every entity ref that *is* present must resolve to an earlier producer
        for k in _REF_KEYS:
            if k in p:
                ref = p[k]
                if not isinstance(ref, str) or ref not in produced:
                    errors.append(Issue("IR_UNRESOLVED_REF",
                                        f"{t}: {k}={ref!r} is not produced by any command", c.id))
                elif index[produced[ref].id] >= index[c.id]:
                    errors.append(Issue("IR_REF_ORDER",
                                        f"{t}: {k}={ref!r} is used before it is produced", c.id))

        # dimension scalars: positive number, or the name of a declared user parameter
        for k in _DIMENSION_KEYS:
            if k in p:
                self._check_dimension(t, c.id, k, p[k], declared, errors)

        # type-specific structure
        if t is IRCommandType.CREATE_USER_PARAMETER:
            name = p.get("name")
            if not isinstance(name, str) or not name:
                errors.append(Issue("IR_BAD_PARAM", "CREATE_USER_PARAMETER needs a non-empty 'name'", c.id))
            if "value" not in p:
                errors.append(Issue("IR_BAD_PARAM", "CREATE_USER_PARAMETER needs a 'value'", c.id))
            unit = p.get("unit", "mm")
            if unit != "mm":
                warnings.append(Issue("IR_PARAM_UNIT",
                                      f"parameter {name!r} unit is {unit!r}; executor expects mm", c.id))
        elif t is IRCommandType.CREATE_SKETCH:
            if p.get("plane") not in _PLANES:
                errors.append(Issue("IR_BAD_PLANE",
                                    f"CREATE_SKETCH plane must be one of {sorted(_PLANES)}", c.id))
            if not c.produces:
                warnings.append(Issue("IR_NO_PRODUCES", "CREATE_SKETCH should produce a sketch ref", c.id))
        elif t in _SKETCH_GEOMETRY:
            if t is IRCommandType.ADD_RECTANGLE and not ("width" in p and "height" in p):
                errors.append(Issue("IR_BAD_PARAM", "ADD_RECTANGLE needs 'width' and 'height'", c.id))
            if t is IRCommandType.ADD_CIRCLE and not ("diameter" in p or "radius" in p):
                errors.append(Issue("IR_BAD_PARAM", "ADD_CIRCLE needs 'diameter' or 'radius'", c.id))
            if t is IRCommandType.ADD_POLYGON:
                sides = p.get("sides")
                if not (isinstance(sides, int) and not isinstance(sides, bool) and sides >= 3):
                    errors.append(Issue("IR_BAD_PARAM", "ADD_POLYGON needs integer 'sides' >= 3", c.id))
                if not ("radius" in p or "diameter" in p):
                    errors.append(Issue("IR_BAD_PARAM", "ADD_POLYGON needs 'radius' or 'diameter'", c.id))
            if t in (IRCommandType.ADD_RECTANGLE, IRCommandType.ADD_CIRCLE,
                     IRCommandType.ADD_POLYGON) and not c.produces:
                warnings.append(Issue("IR_NO_PRODUCES", f"{t} should produce a profile ref", c.id))
        elif t in (IRCommandType.EXTRUDE, IRCommandType.REVOLVE):
            op = p.get("operation", "new_body")
            if op not in _OPERATIONS:
                errors.append(Issue("IR_BAD_OPERATION",
                                    f"{t} operation {op!r} not in {sorted(_OPERATIONS)}", c.id))
            need = "distance" if t is IRCommandType.EXTRUDE else "angle"
            if need not in p:
                errors.append(Issue("IR_BAD_PARAM", f"{t} needs '{need}'", c.id))
        elif t is IRCommandType.SWEEP:
            if "path_ref" not in p:
                errors.append(Issue("IR_BAD_PARAM", "SWEEP needs a 'path_ref'", c.id))
        elif t is IRCommandType.LOFT:
            refs = p.get("profile_refs")
            if not (isinstance(refs, list) and len(refs) >= 2):
                errors.append(Issue("IR_BAD_PARAM", "LOFT needs 'profile_refs' (>= 2 profiles)", c.id))
            else:
                for r in refs:
                    if not isinstance(r, str) or r not in produced:
                        errors.append(Issue("IR_UNRESOLVED_REF",
                                            f"LOFT profile_ref {r!r} is not produced", c.id))
        elif t in (IRCommandType.FILLET, IRCommandType.CHAMFER):
            if not any(k in p for k in ("edge_ref", "edges", "edge_refs")):
                warnings.append(Issue("IR_NO_EDGE", f"{t} has no edge selection", c.id))
        elif t is IRCommandType.SHELL and "thickness" not in p:
            errors.append(Issue("IR_BAD_PARAM", "SHELL needs 'thickness'", c.id))
        elif t is IRCommandType.HOLE and "diameter" not in p:
            errors.append(Issue("IR_BAD_PARAM", "HOLE needs 'diameter'", c.id))
        elif t is IRCommandType.PATTERN:
            if p.get("kind") not in ("circular", "rectangular"):
                errors.append(Issue("IR_BAD_PARAM",
                                    "PATTERN needs kind 'circular' or 'rectangular'", c.id))
            self._check_count(c.id, p.get("count"), declared, errors)
        elif t is IRCommandType.CREATE_MESH_BODY:
            self._check_mesh_body(c.id, p, errors)

    @staticmethod
    def _check_dimension(t, cid, key, v, declared, errors) -> None:
        if isinstance(v, bool):  # bool is an int subclass — reject explicitly
            errors.append(Issue("IR_BAD_PARAM", f"{t}: '{key}' must be a number or parameter name", cid))
        elif isinstance(v, (int, float)):
            if v <= 0:
                errors.append(Issue("IR_NONPOSITIVE", f"{t}: '{key}'={v} must be > 0", cid))
        elif isinstance(v, str):
            if v not in declared:
                errors.append(Issue("IR_UNDECLARED_PARAM",
                                    f"{t}: '{key}' references undeclared parameter {v!r}", cid))
        else:
            errors.append(Issue("IR_BAD_PARAM", f"{t}: '{key}' has invalid type {type(v).__name__}", cid))

    @staticmethod
    def _check_mesh_body(cid, p, errors) -> None:
        """A mesh skin must be a structurally valid triangle soup: flat 3*N vertex floats, flat 3*M
        triangle ints, and every index in range. (Watertightness is guaranteed by the server-side
        generator; here we just guard the wire payload.)"""
        verts = p.get("vertices_mm")
        tris = p.get("triangles")
        if not isinstance(verts, list) or len(verts) < 9 or len(verts) % 3 != 0:
            errors.append(Issue("IR_BAD_PARAM",
                                "CREATE_MESH_BODY needs 'vertices_mm' (flat list, length % 3 == 0)", cid))
            return
        if not isinstance(tris, list) or len(tris) < 3 or len(tris) % 3 != 0:
            errors.append(Issue("IR_BAD_PARAM",
                                "CREATE_MESH_BODY needs 'triangles' (flat index list, length % 3 == 0)", cid))
            return
        nverts = len(verts) // 3
        if any((not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= nverts) for i in tris):
            errors.append(Issue("IR_BAD_PARAM",
                                "CREATE_MESH_BODY triangle index out of range", cid))

    @staticmethod
    def _check_count(cid, v, declared, errors) -> None:
        """A pattern/feature count: a positive integer, or the name of a declared user parameter."""
        if isinstance(v, bool) or v is None:
            errors.append(Issue("IR_BAD_PARAM", "PATTERN 'count' must be a positive integer", cid))
        elif isinstance(v, (int, float)):
            if v < 1:
                errors.append(Issue("IR_NONPOSITIVE", f"PATTERN 'count'={v} must be >= 1", cid))
        elif isinstance(v, str):
            if v not in declared:
                errors.append(Issue("IR_UNDECLARED_PARAM",
                                    f"PATTERN 'count' references undeclared parameter {v!r}", cid))
        else:
            errors.append(Issue("IR_BAD_PARAM", "PATTERN 'count' has invalid type", cid))

    @staticmethod
    def _check_lifecycle(cmds, produced, index, errors) -> None:
        closes = [c for c in cmds if c.type is IRCommandType.CLOSE_SKETCH]
        for c in cmds:
            if c.type not in (IRCommandType.EXTRUDE, IRCommandType.REVOLVE):
                continue
            ref = c.params.get("profile_ref")
            prod = produced.get(ref) if isinstance(ref, str) else None
            if prod is None:
                continue  # already reported as unresolved/missing
            sketch_ref = prod.params.get("sketch_ref")
            if not isinstance(sketch_ref, str):
                continue
            closed = any(
                cl.params.get("sketch_ref") == sketch_ref and index[cl.id] < index[c.id]
                for cl in closes
            )
            if not closed:
                errors.append(Issue("IR_SKETCH_NOT_CLOSED",
                                    f"{c.type}: sketch {sketch_ref!r} (profile {ref!r}) "
                                    f"is not closed before the feature", c.id))

    @staticmethod
    def _check_expected_geometry(ir, errors, warnings) -> None:
        eg = ir.expected_geometry
        if eg is None:
            return
        if len(eg.bbox_mm) != 3:
            errors.append(Issue("IR_GEO_BBOX", "expected_geometry.bbox_mm must be [dx, dy, dz]"))
        elif any((not isinstance(v, (int, float)) or v <= 0) for v in eg.bbox_mm):
            errors.append(Issue("IR_GEO_BBOX", "expected_geometry bbox extents must all be > 0"))
        if eg.volume_mm3 is not None and eg.volume_mm3 <= 0:
            warnings.append(Issue("IR_GEO_VOLUME", "expected_geometry.volume_mm3 is not positive"))
        for name, val in eg.key_dims.items():
            if val <= 0:
                warnings.append(Issue("IR_GEO_DIM", f"expected key dimension {name!r} is not positive"))

    @staticmethod
    def _has_cycle(cmds, id_set) -> bool:
        dep = {c.id: [d for d in c.depends_on if d in id_set] for c in cmds}
        WHITE, GRAY, BLACK = 0, 1, 2
        color = dict.fromkeys(dep, WHITE)

        def visit(start: int) -> bool:
            stack = [(start, iter(dep[start]))]
            color[start] = GRAY
            while stack:
                node, it = stack[-1]
                advanced = False
                for nxt in it:
                    if color[nxt] == GRAY:
                        return True
                    if color[nxt] == WHITE:
                        color[nxt] = GRAY
                        stack.append((nxt, iter(dep[nxt])))
                        advanced = True
                        break
                if not advanced:
                    color[node] = BLACK
                    stack.pop()
            return False

        return any(color[c.id] == WHITE and visit(c.id) for c in cmds)
