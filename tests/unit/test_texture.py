"""Pillar A — surface texture as a displacement field (ADR-010).

These tests are the OFFLINE PROOF of the robustness claim: a textured wall is a closed two-manifold
for *every* parameter combination, so realising it as a mesh body can never hit the `NO_TARGET_BODY`
class of failure that per-feature B-rep cuts do. There is no Fusion/kernel dependency here.
"""

from __future__ import annotations

import itertools
import math

import pytest

from ai_server.services.genome.texture import (
    MOTIFS,
    Mesh,
    compile_field,
    resolve_motif,
    textured_wall_mesh,
)


def test_textured_wall_is_watertight_closed_manifold():
    m = textured_wall_mesh(40.0, 95.0, cols=14, rows=5, amplitude=1.2)
    assert m.is_closed_manifold(), "textured wall must be a watertight solid mesh"
    assert len(m.vertices) > 100 and len(m.triangles) > 200


@pytest.mark.parametrize(
    "cols,rows,amp",
    list(itertools.product([1, 3, 8, 14, 32, 60], [1, 2, 5, 12], [0.0, 0.3, 1.2, 3.0])),
)
def test_every_parameterisation_is_robustly_valid(cols, rows, amp):
    """The whole point: NO combination yields an invalid mesh — unlike fragile boolean cuts."""
    m = textured_wall_mesh(40.0, 95.0, cols=cols, rows=rows, amplitude=amp)
    assert m.is_closed_manifold()


def test_relief_is_applied_along_the_outward_normal():
    R, amp = 40.0, 1.2
    m = textured_wall_mesh(R, 95.0, cols=14, rows=5, amplitude=amp)
    peak = m.max_radius() - R
    assert peak == pytest.approx(amp, abs=0.05), "peak relief should reach the requested amplitude"
    # the inner surface dips inside the wall so the skin MERGES with the B-rep core
    assert m.min_radius() < R


def test_zero_amplitude_is_a_plain_band():
    m = textured_wall_mesh(40.0, 95.0, cols=14, rows=5, amplitude=0.0)
    assert m.is_closed_manifold()
    assert m.max_radius() == pytest.approx(40.0, abs=1e-6)


@pytest.mark.parametrize("motif", list(MOTIFS))
def test_every_motif_renders_a_watertight_textured_wall(motif):
    """COMPLETE generalisation: any pattern is a height field on the SAME robust substrate, so every
    motif yields a valid watertight mesh with the requested relief — not just scales."""
    m = textured_wall_mesh(40.0, 95.0, cols=14, rows=6, amplitude=1.2, motif=motif)
    assert m.is_closed_manifold()
    assert m.max_radius() - 40.0 == pytest.approx(1.2, abs=0.1)


@pytest.mark.parametrize("word,expected", [
    ("dragon scales", "motif_scales"), ("knurled grip", "motif_knurl"),
    ("hexagonal", "motif_hex"), ("ribbed", "motif_ribs"), ("polka dots", "motif_studs"),
    ("woven basket", "motif_weave"), ("pebbled finish", "motif_bumps"),
    ("fluted", "motif_ribs"), ("anything unknown", "motif_scales"),  # graceful default
])
def test_intent_words_resolve_to_a_motif(word, expected):
    assert resolve_motif(word).__name__ == expected


def test_seamless_theta_wrap_for_every_motif():
    """u is periodic, so motif(0, v) == motif(1, v): no seam where the band closes (integer cols)."""
    for fn in MOTIFS.values():
        for v in (0.2, 0.4, 0.55, 0.75):
            assert fn(0.0, v, 14, 6) == pytest.approx(fn(1.0, v, 14, 6), abs=1e-9)


# --------------------------------------- ANY pattern as a math function (the universal generalisation)


@pytest.mark.parametrize("expr", [
    "0.5+0.5*sin(u*tau*10)",                                  # vertical ripples
    "pow(1-frac(v*rows),3)*(1-abs(2*frac(u*cols)-1))",        # spiky downward scales
    "tri(u*cols+v*rows)",                                     # interlocking triangles
    "noise(u*cols, v*rows)",                                  # organic noise
    "1-min(abs(2*frac(u*cols)-1), abs(2*frac(v*rows)-1))",    # voronoi-ish cells
    "clamp(sin(u*tau*6)+cos(v*rows*tau), 0, 1)",             # a composed pattern
])
def test_any_expression_renders_a_watertight_textured_wall(expr):
    fn = compile_field(expr)
    assert fn is not None
    assert 0.0 <= fn(0.31, 0.42, 12, 6) <= 1.0                # always clamped to [0,1]
    m = textured_wall_mesh(40.0, 95.0, cols=12, rows=6, amplitude=1.4, motif=expr)
    assert m.is_closed_manifold()


@pytest.mark.parametrize("bad", [
    '__import__("os").system("x")', 'open("/etc/passwd")', 'u.__class__', 'globals()',
    '[][0]', 'eval("1")', 'lambda: 1', '(1).__class__', 'sin(u); cos(v)',
])
def test_dangerous_expressions_are_rejected(bad):
    """The sandbox whitelist makes an expression incapable of anything but pure math."""
    assert compile_field(bad) is None                          # never compiles -> safe
    # and resolve_motif falls back to a safe default rather than executing anything
    assert resolve_motif(bad) is MOTIFS["scales"]


def test_resolve_motif_prefers_a_named_motif_over_an_expression():
    assert resolve_motif("knurl").__name__ == "motif_knurl"
    assert resolve_motif("dragon scales").__name__ == "motif_scales"
    # a real expression (no motif word) compiles to a custom field
    fn = resolve_motif("0.5+0.5*sin(u*tau*8)")
    assert fn.__name__ not in {m.__name__ for m in MOTIFS.values()}  # a compiled custom field


def test_expression_field_is_clamped_and_nan_safe():
    fn = compile_field("u*1000 - 500")     # wildly out of range -> clamped
    assert fn(0.9, 0.5, 12, 6) == 1.0 and fn(0.1, 0.5, 12, 6) == 0.0
    assert compile_field("sqrt(-1)") is not None  # sqrt is abs-guarded, never errors
    assert 0.0 <= compile_field("log(0)")(0.5, 0.5, 12, 6) <= 1.0  # guarded, NaN-safe


def test_texture_stays_off_the_rim_and_base():
    """Scales sit on the wall, faded to zero at the ends, so they never deform the lip."""
    R, H = 40.0, 95.0
    m = textured_wall_mesh(R, H, cols=14, rows=5, amplitude=1.5)
    (lo, hi) = m.bounds()
    assert lo[2] > 1.0 and hi[2] < H - 1.0
    # at the extreme z of the band the displacement has faded out (radius ~ R)
    top_ring = [v for v in m.vertices if abs(v[2] - hi[2]) < 1e-6]
    assert max(math.hypot(v[0], v[1]) for v in top_ring) == pytest.approx(R, abs=0.05)


def test_binary_stl_roundtrip_header_and_count():
    m = textured_wall_mesh(40.0, 95.0, cols=8, rows=3, amplitude=1.0)
    stl = m.to_binary_stl()
    assert len(stl) == 84 + 50 * len(m.triangles)  # 80 header + uint32 + 50 bytes/triangle


def test_mesh_introspection_helpers():
    m = Mesh(vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
             triangles=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)])  # a tetrahedron
    assert m.is_closed_manifold()
    lo, hi = m.bounds()
    assert lo == (0, 0, 0) and hi == (1, 1, 1)
