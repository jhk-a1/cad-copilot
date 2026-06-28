"""Surface texture as a displacement FIELD over the wall — the robust substrate (Pillar A).

The recurring `NO_TARGET_BODY` failure is structural: B-rep cut+pattern features are *partial*
operations — a cut on a curved wall must FIND a target and re-knit topology, and on tangent/thin
geometry it fails unpredictably. The cross-domain research (implicit/FRep, additive-manufacturing
fuzzy-skin, graphics displacement mapping) converged on the same fix: represent surface texture as
a scalar HEIGHT FIELD ``h(theta, z)`` over the wall's own ``(theta, z)`` parameterisation and
DISPLACE the boundary along its normal. This is pointwise evaluation — there is no boolean, so
there is no target body to miss. "200 scales" becomes one field, O(1) in robustness whatever the
count (Cook 1984 displacement; Reyes dice-then-displace 1987; Perlin 1985; Worley 1996; Brunton
"Displaced SDFs for AM" SIGGRAPH 2021).

Output is a CLOSED, watertight, manifold triangle mesh band that hugs the wall: an outer textured
surface at ``R + h``, an inner surface set slightly INSIDE the wall (so it merges with the B-rep
core), and top/bottom caps. A valid closed mesh is *always* importable as a Fusion mesh body — it
cannot fail the way a feature boolean does. The B-rep mug stays editable; the texture is a
regenerable field whose period/depth/overlap remain genome knobs.

Pure geometry, no Fusion / no kernel dependency: fully offline-verifiable (see tests).
"""

from __future__ import annotations

import ast
import math
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass

# --------------------------------------------------------------------------- the height field


def _frac(x: float) -> float:
    return x - math.floor(x)


# how many rows tall each scale is — > 1 so a scale OVERLAPS the one below it (imbrication)
_SCALE_TALL = 1.7
_LIP = 0.18  # fraction of the scale (from its free edge) that is the raised overhang lip


def _scale_plate(au: float, av: float) -> float:
    """One overlapping scale's height profile, 0..1. ``au`` in [-1,1] across the scale width; ``av``
    in [0,1] up the scale with 0 at the FREE (exposed, bottom) edge and 1 at the BURIED (top) edge.

    The scale is a rounded fan — widest at the free edge, tapering to a point where it tucks under the
    row above — that is RAISED across its body with a sharp LIP at the free edge and a fade into the
    surface at the buried top. Stacked with overlap (and a max), the lip of each scale overhangs the
    scale below it, which is what reads as imbricated armour rather than a field of bumps.
    """
    if av <= 0.0 or av >= 1.0:
        return 0.0
    half_w = math.sqrt(max(0.0, 1.0 - av * av))   # rounded fan: full width at the free edge -> point
    if half_w <= 1e-6 or abs(au) >= half_w:
        return 0.0
    across = math.sqrt(max(0.0, 1.0 - (au / half_w) ** 2))  # rounded across the width
    if av < _LIP:
        vertical = av / _LIP                       # the lip: a sharp rise from the surface at the edge
    else:
        vertical = 1.0 - (av - _LIP) / (1.0 - _LIP)  # fade from the lip ridge into the buried top
    return across * max(0.0, vertical)


# =============================================================================== motif library
#
# A MOTIF is a height field over the wall's own (u, v) chart, returning 0..1 (the mesh generator
# applies amplitude + the rim/base fade). u in [0,1) runs around the circumference (periodic, so the
# wrap is seamless when `cols` is integer); v in [0,1] runs up the textured band. Each motif tiles
# `cols` times around and `rows` up. This is the GENERAL surface-texture layer: ANY pattern is just a
# height function here, all riding the same robust displacement-field-to-watertight-mesh substrate.
# Scales is one entry among many.


def _tri(x: float) -> float:
    """Triangle wave, 0..1 (peak at the half-cell)."""
    return 1.0 - 2.0 * abs(_frac(x) - 0.5)


def _smooth01(x: float) -> float:
    """Smoothstep on a 0..1 value (rounds a profile)."""
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def _hash01(i: int, j: int) -> float:
    """Deterministic pseudo-random 0..1 from two integer cell coords (for irregular motifs)."""
    n = (int(i) * 73856093) ^ (int(j) * 19349663)
    n &= 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177
    n &= 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0


def motif_scales(u: float, v: float, cols: int, rows: int) -> float:
    """Imbricated (overlapping) scales: each scale is ~`_SCALE_TALL` rows tall so it overlaps the one
    below, alternate rows offset half a column; the max-of-candidates makes the upper scale's lip
    overhang the lower — armour, not a field of domes."""
    ucol, vrow = u * cols, v * rows
    base = math.floor(vrow)
    best = 0.0
    for r in (base, base - 1):
        av = (vrow - r) / _SCALE_TALL
        if av <= 0.0 or av >= 1.0:
            continue
        au = 2.0 * _frac(ucol + (0.5 if r % 2 else 0.0)) - 1.0
        best = max(best, _scale_plate(au, av))
    return best


def motif_knurl(u: float, v: float, cols: int, rows: int) -> float:
    """Diamond knurl — two crossing diagonal ridge families make raised pyramids (a machined grip)."""
    return _tri(u * cols + v * rows) * _tri(u * cols - v * rows)


def motif_studs(u: float, v: float, cols: int, rows: int) -> float:
    """A grid of rounded studs / dots / pimples."""
    du, dv = 2.0 * _frac(u * cols) - 1.0, 2.0 * _frac(v * rows) - 1.0
    return _smooth01(1.0 - (du * du + dv * dv))


def motif_ribs(u: float, v: float, cols: int, rows: int) -> float:
    """Vertical ribs / flutes running up the wall (rounded ridges around the circumference)."""
    du = 2.0 * _frac(u * cols) - 1.0
    return _smooth01(1.0 - du * du)


def motif_rings(u: float, v: float, cols: int, rows: int) -> float:
    """Horizontal rings / ridges around the wall (rounded ridges up the height)."""
    dv = 2.0 * _frac(v * rows) - 1.0
    return _smooth01(1.0 - dv * dv)


def motif_grooves(u: float, v: float, cols: int, rows: int) -> float:
    """Sharp vertical V-flutes (crisp ridges, deeper valleys than `ribs`)."""
    return 1.0 - abs(2.0 * _frac(u * cols) - 1.0)


def motif_hex(u: float, v: float, cols: int, rows: int) -> float:
    """Honeycomb / hex-packed cells (brick-offset rounded mesas)."""
    row = math.floor(v * rows)
    cu = _frac(u * cols + (0.5 if row % 2 else 0.0))
    cv = _frac(v * rows)
    du, dv = 2.0 * cu - 1.0, 2.0 * cv - 1.0
    return _smooth01(1.0 - 0.8 * (du * du + dv * dv))


def motif_weave(u: float, v: float, cols: int, rows: int) -> float:
    """Basket-weave: cells alternate vertical / horizontal strands (an over-under woven look)."""
    cell = math.floor(u * cols) + math.floor(v * rows)
    if cell % 2 == 0:
        d = 2.0 * _frac(u * cols) - 1.0       # vertical strand
    else:
        d = 2.0 * _frac(v * rows) - 1.0       # horizontal strand
    return _smooth01(1.0 - d * d)


def motif_bumps(u: float, v: float, cols: int, rows: int) -> float:
    """Irregular organic bumps (a pebbled / hammered skin) — jittered domes over a 3x3 cell search so
    bumps blend across cell edges and wrap seamlessly in u."""
    x, y = u * cols, v * rows
    ci, cj = math.floor(x), math.floor(y)
    best = 0.0
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            gi, gj = (ci + di) % cols, cj + dj            # periodic hash in u
            ox, oy = _hash01(gi, gj), _hash01(gi + 31, gj + 17)
            rad = 0.45 + 0.35 * _hash01(gi + 3, gj + 7)
            hh = 0.55 + 0.45 * _hash01(gi + 5, gj + 9)
            dx, dy = x - ((ci + di) + ox), y - ((cj + dj) + oy)
            best = max(best, _smooth01(1.0 - (dx * dx + dy * dy) / (rad * rad)) * hh)
    return best


MOTIFS = {
    "scales": motif_scales, "knurl": motif_knurl, "studs": motif_studs, "ribs": motif_ribs,
    "rings": motif_rings, "grooves": motif_grooves, "hex": motif_hex, "weave": motif_weave,
    "bumps": motif_bumps,
}
# map the words a user / the planner might use onto a motif (general intent -> pattern)
_MOTIF_SYNONYMS = {
    "scale": "scales", "scales": "scales", "dragon": "scales", "fish": "scales", "armor": "scales",
    "armour": "scales", "imbricate": "scales", "shingle": "scales",
    "knurl": "knurl", "knurling": "knurl", "knurled": "knurl", "diamond": "knurl", "grip": "knurl",
    "crosshatch": "knurl",
    "stud": "studs", "studs": "studs", "studded": "studs", "dot": "studs", "dots": "studs",
    "dimple": "studs", "dimpled": "studs", "pimple": "studs", "polka": "studs",
    "rib": "ribs", "ribs": "ribs", "ribbed": "ribs", "flute": "ribs", "fluted": "ribs",
    "ring": "rings", "rings": "rings", "ringed": "rings", "ridge": "rings", "thread": "rings",
    "groove": "grooves", "grooves": "grooves", "grooved": "grooves", "channel": "grooves",
    "hex": "hex", "hexagon": "hex", "hexagonal": "hex", "honeycomb": "hex", "comb": "hex",
    "weave": "weave", "woven": "weave", "basket": "weave", "basketweave": "weave", "wicker": "weave",
    "bump": "bumps", "bumps": "bumps", "bumpy": "bumps", "pebble": "bumps", "pebbled": "bumps",
    "hammered": "bumps", "rough": "bumps", "organic": "bumps", "texture": "bumps", "noise": "bumps",
}


# =================================================== ANY pattern as a math FUNCTION (universal)
#
# A named motif is just a preset; the universal path is a height-field EXPRESSION h(u,v) the user or
# the LLM can write for ANY pattern, simple to arbitrarily complex. We evaluate it in a SANDBOX — a
# strict whitelist over the Python AST (only math: the allow-listed functions, +-*/%**, the vars
# u,v,cols,rows, numeric constants, and ternaries/comparisons). No names, attributes, calls, imports
# or subscripts outside the whitelist, so an expression can never do anything but arithmetic. This is
# the same "closed grammar, correct by construction" discipline as the IR — open-ended yet safe.


def _wrap01(x: float) -> float:
    return 0.0 if x != x else max(0.0, min(1.0, float(x)))  # NaN-safe clamp to [0,1]


def _smoothstep(a: float, b: float, x: float) -> float:
    t = _wrap01((x - a) / (b - a)) if b != a else 0.0
    return t * t * (3.0 - 2.0 * t)


def _hashf(x: float, y: float) -> float:
    n = math.sin(x * 127.1 + y * 311.7) * 43758.5453
    return n - math.floor(n)


def _vnoise(x: float, y: float) -> float:
    """Smooth value noise in [0,1] (bilinear blend of corner hashes) — for organic patterns."""
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = x - xi, y - yi
    ux, uy = xf * xf * (3 - 2 * xf), yf * yf * (3 - 2 * yf)
    a, b = _hashf(xi, yi), _hashf(xi + 1, yi)
    c, d = _hashf(xi, yi + 1), _hashf(xi + 1, yi + 1)
    return (a * (1 - ux) + b * ux) * (1 - uy) + (c * (1 - ux) + d * ux) * uy


# the math vocabulary an expression may call (everything pure, no side effects)
_FIELD_FUNCS: dict[str, Callable] = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos,
    "atan": math.atan, "atan2": math.atan2, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "exp": math.exp, "log": lambda x: math.log(abs(x)) if x else 0.0, "sqrt": lambda x: math.sqrt(abs(x)),
    "abs": abs, "floor": math.floor, "ceil": math.ceil, "round": round, "min": min, "max": max,
    "pow": lambda a, b: math.copysign(abs(a) ** b, a) if a else 0.0, "hypot": math.hypot,
    "fmod": math.fmod, "sign": lambda x: (x > 0) - (x < 0),
    "frac": _frac, "fract": _frac, "tri": _tri, "saw": _frac,
    "sq": lambda x: 1.0 if _frac(x) < 0.5 else 0.0, "pulse": lambda x, w: 1.0 if _frac(x) < w else 0.0,
    "clamp": lambda x, a, b: max(a, min(b, x)), "step": lambda e, x: 1.0 if x >= e else 0.0,
    "smoothstep": _smoothstep, "mix": lambda a, b, t: a * (1 - t) + b * t,
    "lerp": lambda a, b, t: a * (1 - t) + b * t, "smooth01": _smooth01,
    "dist": math.hypot, "noise": _vnoise, "hash": _hashf, "pi": math.pi, "e": math.e, "tau": math.tau,
}
_FIELD_VARS = {"u", "v", "cols", "rows"}
_ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp, ast.Call,
    ast.IfExp, ast.Compare, ast.BoolOp, ast.And, ast.Or,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
)


def _validate_field(node) -> None:
    """Strict whitelist walk — anything outside pure math raises, so an expression is always safe."""
    if not isinstance(node, _ALLOWED_NODES):
        raise ValueError(f"disallowed expression element: {type(node).__name__}")
    if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
        raise ValueError("only numeric constants are allowed")
    if isinstance(node, ast.Name) and node.id not in _FIELD_VARS and node.id not in _FIELD_FUNCS:
        raise ValueError(f"unknown name {node.id!r}")
    if isinstance(node, ast.Call):
        if not (isinstance(node.func, ast.Name) and node.func.id in _FIELD_FUNCS):
            raise ValueError("only allow-listed math functions may be called")
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
    for child in ast.iter_child_nodes(node):
        _validate_field(child)


def compile_field(expr: str) -> Callable[[float, float, int, int], float] | None:
    """Compile a height-field expression h(u,v) into a safe callable, or None if it isn't valid pure
    math. ``u,v`` are 0..1 over the wall; ``cols,rows`` are the tiling counts. Result clamped to [0,1].
    """
    try:
        tree = ast.parse(expr, mode="eval")
        _validate_field(tree)
        code = compile(tree, "<field>", "eval")
    except (SyntaxError, ValueError):
        return None
    consts = {k: v for k, v in _FIELD_FUNCS.items() if not callable(v) or k in ("pi", "e", "tau")}

    def fn(u: float, v: float, cols: int, rows: int) -> float:
        env = {"u": u, "v": v, "cols": cols, "rows": rows, **_FIELD_FUNCS, **consts}
        try:
            return _wrap01(eval(code, {"__builtins__": {}}, env))  # noqa: S307 - sandboxed AST
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return 0.0
    return fn


# common pattern PHRASES -> a height-field expression, so a natural-language texture description (the
# form the planning model actually writes) resolves even when it isn't one of the named motifs.
# a grid of SHARP outward cones (thorns/spikes) — tall at each cell centre, falling to 0 at the
# edges, raised to a power for a needle tip. Reads unambiguously as spikes (the old upward ramp did
# not). dist() is hypot over the cell-local (-1..1) coords.
_SPIKY_FIELD = "pow(max(0,1-dist(2*frac(u*cols)-1,2*frac(v*rows)-1)),2.5)"
_PHRASE_FIELDS = {
    "wave": "0.5+0.5*sin((u*cols+v*rows)*tau)", "wavy": "0.5+0.5*sin(v*rows*tau*2)",
    "ripple": "0.5+0.5*sin(v*rows*tau*2)", "ripples": "0.5+0.5*sin(v*rows*tau*2)",
    "spiral": "0.5+0.5*sin(u*tau*cols+v*rows*2.5)", "swirl": "0.5+0.5*sin(u*tau*cols+v*rows*2.5)",
    "zigzag": "tri(u*cols+v*rows)", "chevron": "tri(u*cols+v*rows)", "herringbone": "tri(u*cols+v*rows)",
    "lattice": "max(tri(u*cols),tri(v*rows))", "grid": "max(1-abs(2*frac(u*cols)-1),1-abs(2*frac(v*rows)-1))",
    "wood": "0.5+0.5*sin(v*rows*tau+noise(u*4,v*rows)*4)", "grain": "0.5+0.5*sin(v*rows*tau+noise(u*4,v*rows)*4)",
    "spiky": _SPIKY_FIELD, "spikier": _SPIKY_FIELD, "spike": _SPIKY_FIELD, "spikes": _SPIKY_FIELD,
    "pointed": _SPIKY_FIELD, "pointy": _SPIKY_FIELD, "thorn": _SPIKY_FIELD, "thorns": _SPIKY_FIELD,
    "studded": "studs",
}


def pattern_from_text(text: str) -> str | None:
    """A motif name / expression for any TEXT that describes a surface texture, else None. Covers the
    named motifs (and synonyms) + common phrases (wave, ripple, spiral, zigzag, wood, spiky, …)."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    for w in words:                       # a specific descriptor (wave, spiky, wood, …) wins first
        if w in _PHRASE_FIELDS:
            return _PHRASE_FIELDS[w]
    for w in words:
        if w in _MOTIF_SYNONYMS:
            return _MOTIF_SYNONYMS[w]
    return None


def resolve_motif(spec: str):
    """Resolve a pattern spec to a height function — UNIVERSAL: a named motif (or synonym), a common
    pattern PHRASE, OR a height-field math EXPRESSION h(u,v) for a custom pattern, default scales."""
    key = (spec or "").strip()
    named = pattern_from_text(key)
    if named is not None:
        fn = compile_field(named)
        if fn is not None:                # a phrase mapped to an expression
            return fn
        if named in MOTIFS:               # a named motif
            return MOTIFS[named]
    if key.lower() in MOTIFS:
        return MOTIFS[key.lower()]
    fn = compile_field(key)               # not a name/phrase -> try it as a custom h(u,v) expression
    return fn if fn is not None else MOTIFS["scales"]


# --------------------------------------------------------------------------- the mesh


@dataclass(frozen=True)
class Mesh:
    """A triangle mesh: vertices in mm, triangles as index triples. Geometry only."""

    vertices: list[tuple[float, float, float]]
    triangles: list[tuple[int, int, int]]

    # -- introspection used by tests / verification -------------------------------------------
    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        zs = [v[2] for v in self.vertices]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def max_radius(self) -> float:
        return max(math.hypot(v[0], v[1]) for v in self.vertices)

    def min_radius(self) -> float:
        return min(math.hypot(v[0], v[1]) for v in self.vertices)

    def is_closed_manifold(self) -> bool:
        """True iff every undirected edge is shared by exactly two triangles.

        A closed two-manifold is watertight and *always* a valid solid mesh body — this is the
        offline proof that the texture can never produce the `NO_TARGET_BODY` class of failure.
        """
        edges: dict[tuple[int, int], int] = {}
        for a, b, c in self.triangles:
            for i, j in ((a, b), (b, c), (c, a)):
                key = (i, j) if i < j else (j, i)
                edges[key] = edges.get(key, 0) + 1
        return bool(edges) and all(count == 2 for count in edges.values())

    # -- export --------------------------------------------------------------------------------
    def to_binary_stl(self) -> bytes:
        """Binary STL — the robust, slicer-grade interchange the executor imports as a mesh body."""
        tris = self.triangles
        out = bytearray()
        out += b"CAD-Copilot textured shell".ljust(80, b" ")
        out += struct.pack("<I", len(tris))
        for a, b, c in tris:
            va, vb, vc = self.vertices[a], self.vertices[b], self.vertices[c]
            ux, uy, uz = (vb[0] - va[0], vb[1] - va[1], vb[2] - va[2])
            wx, wy, wz = (vc[0] - va[0], vc[1] - va[1], vc[2] - va[2])
            nx, ny, nz = (uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx)
            nrm = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            out += struct.pack("<3f", nx / nrm, ny / nrm, nz / nrm)
            for vx in (va, vb, vc):
                out += struct.pack("<3f", *vx)
            out += struct.pack("<H", 0)
        return bytes(out)


def textured_wall_mesh(radius: float, height: float, *, cols: int, rows: int,
                       amplitude: float, motif: str = "scales", n_theta: int | None = None,
                       base_margin: float | None = None, inner_inset: float = 0.6) -> Mesh:
    """A closed mesh band hugging a cylindrical wall, displaced outward by ANY motif's height field.

    Robust by construction: the result is a closed two-manifold (verified in tests), so realising it
    as a Fusion mesh body cannot fail the way per-feature cuts do. ``radius`` is the outer wall
    radius (mm); the band spans the wall height minus a margin so the texture sits on the wall, not
    the rim. ``cols`` (integer) tiles around -> seamless theta wrap; ``rows`` climb the wall.
    ``motif`` names the pattern (scales | knurl | studs | ribs | rings | grooves | hex | weave |
    bumps, or any synonym) — the SAME robust substrate renders all of them.
    """
    cols = max(1, int(round(cols)))
    rows = max(1, int(round(rows)))
    amplitude = max(0.0, float(amplitude))
    motif_fn = resolve_motif(motif)
    if base_margin is None:
        base_margin = max(amplitude * 2.0, min(height * 0.12, 6.0))
    z_lo = base_margin
    z_hi = height - base_margin
    if z_hi <= z_lo:  # very short wall: texture the middle 60%
        z_lo, z_hi = height * 0.2, height * 0.8
    # sampling density: enough angular + vertical samples to resolve a motif's edges/lips without
    # aliasing, and at least a smooth cylinder.
    if n_theta is None:
        n_theta = max(64, cols * 8)
    n_z = max(rows * 14, 16)
    inner_r = max(0.1, radius - inner_inset)
    edge_fade = 0.18  # fraction of the band over which the texture fades into the clean rim/base

    verts: list[tuple[float, float, float]] = []
    outer: list[list[int]] = []  # [j][i] -> vertex index on the textured outer surface
    inner: list[list[int]] = []  # [j][i] -> vertex index on the inner (merge) surface
    for j in range(n_z + 1):
        z = z_lo + (z_hi - z_lo) * (j / n_z)
        v = (z - z_lo) / (z_hi - z_lo)
        edge = min(v, 1.0 - v) / max(1e-6, edge_fade)
        fade = max(0.0, min(1.0, edge))
        orow: list[int] = []
        irow: list[int] = []
        for i in range(n_theta):
            theta = 2.0 * math.pi * (i / n_theta)
            h = amplitude * fade * motif_fn(i / n_theta, v, cols, rows)
            ro = radius + h
            orow.append(len(verts))
            verts.append((ro * math.cos(theta), ro * math.sin(theta), z))
            irow.append(len(verts))
            verts.append((inner_r * math.cos(theta), inner_r * math.sin(theta), z))
        outer.append(orow)
        inner.append(irow)

    tris: list[tuple[int, int, int]] = []

    def quad(a: int, b: int, c: int, d: int) -> None:
        # a-b-c-d counter-clockwise as seen from outside -> two triangles
        tris.append((a, b, c))
        tris.append((a, c, d))

    for j in range(n_z):
        for i in range(n_theta):
            i2 = (i + 1) % n_theta
            # outer textured surface (normals point outward)
            quad(outer[j][i], outer[j][i2], outer[j + 1][i2], outer[j + 1][i])
            # inner surface (reverse winding so its normals point inward)
            quad(inner[j][i], inner[j + 1][i], inner[j + 1][i2], inner[j][i2])
    # top and bottom caps: connect outer<->inner rings to close the band into a solid
    for i in range(n_theta):
        i2 = (i + 1) % n_theta
        quad(outer[n_z][i], outer[n_z][i2], inner[n_z][i2], inner[n_z][i])      # top
        quad(inner[0][i], inner[0][i2], outer[0][i2], outer[0][i])              # bottom
    return Mesh(vertices=verts, triangles=tris)


def mesh_body_params(mesh: Mesh, *, name: str = "texture_skin") -> dict:
    """Flatten a mesh into a compact CREATE_MESH_BODY param payload (mm).

    Vertices become a flat ``[x0,y0,z0, x1,y1,z1, ...]`` list (rounded to 3 dp -> micron precision)
    and triangles a flat index list. The executor rebuilds the mesh body from these — the geometry
    is computed and *verified watertight* server-side, so the executor only realises a known-valid
    mesh (it can never hit the per-feature boolean failure).
    """
    verts: list[float] = []
    for x, y, z in mesh.vertices:
        verts += [round(x, 3), round(y, 3), round(z, 3)]
    tris: list[int] = []
    for a, b, c in mesh.triangles:
        tris += [a, b, c]
    return {"name": name, "vertices_mm": verts, "triangles": tris,
            "vertex_count": len(mesh.vertices), "triangle_count": len(mesh.triangles)}
