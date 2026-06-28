"""Unit tests for accurate multi-view drafting (M1-W4).

The point of this module is that the outline is PROPORTIONAL to the real dimensions (a wide box
draws wide), holes sit at true positions, and the dimension/highlight hooks survive. These tests
pin the proportionality and the preserved structure.
"""

from __future__ import annotations

import re

import pytest

from ai_server.services import drawing

pytestmark = pytest.mark.unit


def _first_rect_wh(svg: str) -> tuple[float, float]:
    m = re.search(r'<rect[^>]*width="([\d.]+)"[^>]*height="([\d.]+)"', svg)
    assert m, "no rect found in view"
    return float(m.group(1)), float(m.group(2))


def test_box_front_outline_is_proportional_wide() -> None:
    svgs = drawing.box_views({"length": 100, "width": 20, "height": 20}, set())
    w, h = _first_rect_wh(svgs["front"])
    assert w / h == pytest.approx(100 / 20, rel=0.02)  # wide-short front (L:H = 5:1)
    assert w > h


def test_box_front_outline_is_proportional_tall() -> None:
    svgs = drawing.box_views({"length": 20, "width": 20, "height": 80}, set())
    w, h = _first_rect_wh(svgs["front"])
    assert h > w  # narrow-tall front (H >> L)


def test_box_top_proportions_track_length_and_width() -> None:
    svgs = drawing.box_views({"length": 60, "width": 30, "height": 10}, set())
    w, h = _first_rect_wh(svgs["top"])
    assert w / h == pytest.approx(60 / 30, rel=0.02)  # top view is L x W


def test_all_four_views_wrapped_and_highlightable() -> None:
    svgs = drawing.box_views({"length": 50, "width": 30, "height": 20}, set())
    assert set(svgs) == {"front", "top", "right", "iso"}
    for svg in svgs.values():
        assert svg.startswith("<svg") and "currentColor" in svg
    assert "data-ref" in svgs["front"]  # dimensions stay highlightable
    assert "polygon" in svgs["iso"]     # real isometric projection


def test_box_holes_drawn_at_true_count_and_grouped() -> None:
    d = {"length": 50, "width": 30, "height": 20, "hole_edge_x": 10, "hole_edge_y": 10,
         "hole_spacing_x": 30, "hole_spacing_y": 10, "hole_diameter": 6, "hole_count": 4}
    top = drawing.box_views(d, {"holes"})["top"]
    assert top.count("<circle") == 4
    assert 'data-ref="ref_hole_diameter"' in top
    assert 'data-ref="ref_hole_spacing_x"' in top


def test_cylinder_top_is_circle_front_is_rect() -> None:
    svgs = drawing.cylinder_views({"diameter": 25, "height": 40}, set())
    assert "<circle" in svgs["top"]
    fw, fh = _first_rect_wh(svgs["front"])
    assert fw / fh == pytest.approx(25 / 40, rel=0.02)  # front profile is D x H


def test_cylinder_bore_drawn_when_holes_feature() -> None:
    svgs = drawing.cylinder_views({"diameter": 25, "height": 40, "bore_diameter": 10}, {"holes"})
    assert 'data-ref="ref_bore_diameter"' in svgs["top"]


def test_l_bracket_front_is_six_vertex_l_polygon() -> None:
    svgs = drawing.l_bracket_views({"leg_a": 50, "leg_b": 30, "thickness": 5, "depth": 40}, set())
    assert set(svgs) == {"front", "top", "right", "iso"}
    front = svgs["front"]
    m = re.search(r'data-ref="ref_leg_a" points="([^"]+)"', front)
    assert m, "L outline not found in front view"
    assert len(m.group(1).split()) == 6  # the L profile has six vertices
    assert "data-ref" in front and "currentColor" in front


def test_l_bracket_holes_drawn_with_count() -> None:
    d = {"leg_a": 50, "leg_b": 30, "thickness": 5, "depth": 40,
         "hole_edge": 10, "hole_diameter": 6, "hole_count": 3}
    top = drawing.l_bracket_views(d, {"holes"})["top"]
    assert top.count("<circle") == 3
    assert 'data-ref="ref_hole_diameter"' in top
