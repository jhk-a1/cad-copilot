"""Accurate multi-view drafting for box & cylinder parts (M1-W4).

Replaces the schematic SVGs with geometry that is PROPORTIONAL to the part's real dimensions:
a 100x20 box draws a wide-short front view, a 20x80 box a narrow-tall one, holes sit at their
true positions, and the isometric is a real projection. One shared scale (mm -> view units) is
used across front/top/right so a 50 mm edge is the same length in every view — the
engineering-drawing convention.

This is analytic projection of the same exact primitives the geometry kernel measures
(services/geometry.py), so the preview and the verifier agree. The dimension lines, hole groups,
and `data-ref` highlight hooks are preserved exactly so the panel highlighting keeps working.
build123d/OCP-rendered drafting for arbitrary geometry is deferred with the kernel (post-trial).
"""

from __future__ import annotations

import math

_COS30 = math.cos(math.radians(30))
_SIN30 = 0.5

# Orthographic views share this canvas + scale; the iso has its own.
ORTHO_VIEW = "0 0 160 116"
ISO_VIEW = "0 0 130 116"
AX, AY = 30, 20           # top-left anchor of the outline within an ortho view
AVAIL_W, AVAIL_H = 104, 60  # space the outline may occupy (rest is for dimension lines)

_OPEN = '<g fill="currentColor" stroke="currentColor" stroke-width="1" font-size="9">'


# --------------------------------------------------------------------------- svg helpers

def _n(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _wrap(viewbox: str, body: str) -> str:
    return f'<svg viewBox="{viewbox}" xmlns="http://www.w3.org/2000/svg">{_OPEN}{body}</g></svg>'


def _rect(x, y, w, h) -> str:
    return (f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" '
            f'fill="none" stroke-width="1.4"/>')


def _dim_h(x1, x2, y, label, ref) -> str:
    mid = (x1 + x2) / 2
    return (f'<g data-ref="ref_{ref}">'
            f'<line x1="{_n(x1)}" y1="{_n(y - 4)}" x2="{_n(x1)}" y2="{_n(y + 4)}"/>'
            f'<line x1="{_n(x2)}" y1="{_n(y - 4)}" x2="{_n(x2)}" y2="{_n(y + 4)}"/>'
            f'<line x1="{_n(x1)}" y1="{_n(y)}" x2="{_n(x2)}" y2="{_n(y)}"/>'
            f'<text x="{_n(mid)}" y="{_n(y + 11)}" text-anchor="middle">{label}</text></g>')


def _dim_v(y1, y2, x, label, ref, right=True) -> str:
    mid = (y1 + y2) / 2
    tx = x + 6 if right else x - 6
    anchor = "start" if right else "end"
    return (f'<g data-ref="ref_{ref}">'
            f'<line x1="{_n(x - 4)}" y1="{_n(y1)}" x2="{_n(x + 4)}" y2="{_n(y1)}"/>'
            f'<line x1="{_n(x - 4)}" y1="{_n(y2)}" x2="{_n(x + 4)}" y2="{_n(y2)}"/>'
            f'<line x1="{_n(x)}" y1="{_n(y1)}" x2="{_n(x)}" y2="{_n(y2)}"/>'
            f'<text x="{_n(tx)}" y="{_n(mid + 3)}" text-anchor="{anchor}">{label}</text></g>')


def _note(x, y, label, ref) -> str:
    return f'<g data-ref="ref_{ref}"><text x="{_n(x)}" y="{_n(y)}">{label}</text></g>'


# --------------------------------------------------------------------------- box

def _box_scale(length: float, width: float, height: float) -> float:
    # horizontal extents across views: L (front/top), W (right); vertical: H (front/right), W (top)
    return min(AVAIL_W / max(length, width), AVAIL_H / max(height, width))


def _box_iso(length: float, width: float, height: float) -> str:
    def proj(x, y, z):
        return ((x - y) * _COS30, (x + y) * _SIN30 - z)

    pts = [proj(0, 0, 0), proj(length, 0, 0), proj(length, width, 0), proj(0, width, 0),
           proj(0, 0, height), proj(length, 0, height), proj(length, width, height), proj(0, width, height)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    scale = min(92 / span_x, 80 / span_y) if span_x and span_y else 1.0
    ox = 65 - (min(xs) + span_x / 2) * scale
    oy = 58 - (min(ys) + span_y / 2) * scale
    a, b, c, d, e, f, g, h = [(ox + x * scale, oy + y * scale) for x, y in pts]

    def poly(*corners):
        return ('<polygon points="' + " ".join(f"{_n(x)},{_n(y)}" for x, y in corners)
                + '" fill="none" stroke-width="1.2"/>')

    return poly(e, f, g, h) + poly(a, b, f, e) + poly(b, c, g, f)  # top, front, right faces


def box_views(d: dict[str, float], features: set[str]) -> dict[str, str]:
    length = float(d.get("length", 50))
    width = float(d.get("width", 30))
    height = float(d.get("height", 20))
    s = _box_scale(length, width, height)

    # front (L x H)
    fw, fh = length * s, height * s
    front = (_rect(AX, AY, fw, fh)
             + _dim_h(AX, AX + fw, AY + fh + 14, "L", "length")
             + _dim_v(AY, AY + fh, AX + fw + 12, "H", "height"))
    if "filleted_edges" in features:
        r = max(5.0, float(d.get("fillet_radius", 3)) * s)
        front += (f'<g data-ref="ref_fillet_radius">'
                  f'<path d="M{_n(AX)} {_n(AY + r)} A {_n(r)} {_n(r)} 0 0 1 {_n(AX + r)} {_n(AY)}" '
                  f'fill="none"/><text x="{_n(AX - 10)}" y="{_n(AY - 4)}">R</text></g>')
    if "chamfered_edges" in features:
        front += (f'<g data-ref="ref_chamfer_size">'
                  f'<line x1="{_n(AX + fw - 7)}" y1="{_n(AY)}" x2="{_n(AX + fw)}" y2="{_n(AY + 7)}"/>'
                  f'<text x="{_n(AX + fw + 4)}" y="{_n(AY - 2)}">C</text></g>')

    # top (L x W) with holes at their true positions
    tw, th = length * s, width * s
    top = (_rect(AX, AY, tw, th)
           + _dim_h(AX, AX + tw, AY + th + 14, "L", "length")
           + _dim_v(AY, AY + th, AX + tw + 12, "W", "width"))
    if "holes" in features:
        top += _box_holes(d, s, th)

    # right (W x H)
    rw, rh = width * s, height * s
    right = (_rect(AX, AY, rw, rh)
             + _dim_h(AX, AX + rw, AY + rh + 14, "W", "width")
             + _dim_v(AY, AY + rh, AX + rw + 12, "H", "height"))

    return {"front": _wrap(ORTHO_VIEW, front), "top": _wrap(ORTHO_VIEW, top),
            "right": _wrap(ORTHO_VIEW, right), "iso": _wrap(ISO_VIEW, _box_iso(length, width, height))}


def _box_holes(d: dict[str, float], s: float, th: float) -> str:
    ex, ey = float(d.get("hole_edge_x", 10)), float(d.get("hole_edge_y", 10))
    sx, sy = float(d.get("hole_spacing_x", 30)), float(d.get("hole_spacing_y", 10))
    dia, count = float(d.get("hole_diameter", 6)), int(d.get("hole_count", 4))
    r = max(1.6, dia / 2 * s)
    xs = [AX + ex * s, AX + (ex + sx) * s]
    ys = [AY + ey * s, AY + (ey + sy) * s]
    circles = "".join(f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(r)}" fill="none"/>'
                      for x in xs for y in ys)
    return (f'<g data-ref="ref_hole_diameter">{circles}</g>'
            + _dim_h(AX, xs[0], AY + th + 26, "Xe", "hole_edge_x")
            + _dim_h(xs[0], xs[1], AY + th + 34, "Sx", "hole_spacing_x")
            + _dim_v(AY, ys[0], AX - 8, "Ye", "hole_edge_y", right=False)
            + _dim_v(ys[0], ys[1], AX - 8, "Sy", "hole_spacing_y", right=False)
            + _note(AX + max(xs) - AX + 36, AY - 6, f"{count}x Ø", "hole_count"))


# --------------------------------------------------------------------------- cylinder

def cylinder_views(d: dict[str, float], features: set[str]) -> dict[str, str]:
    dia = float(d.get("diameter", 25))
    height = float(d.get("height", 40))
    s = min(AVAIL_W / dia, AVAIL_H / max(height, dia))

    fw, fh = dia * s, height * s
    front = (_rect(AX, AY, fw, fh)
             + _dim_h(AX, AX + fw, AY + fh + 14, "Ø", "diameter")
             + _dim_v(AY, AY + fh, AX + fw + 12, "H", "height"))
    if "chamfered_edges" in features:
        front += (f'<g data-ref="ref_chamfer_size">'
                  f'<line x1="{_n(AX + fw - 7)}" y1="{_n(AY)}" x2="{_n(AX + fw)}" y2="{_n(AY + 7)}"/>'
                  f'<text x="{_n(AX + fw + 4)}" y="{_n(AY - 2)}">C</text></g>')

    cd = dia * s
    cx, cy = AX + cd / 2, AY + cd / 2
    top = (f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(cd / 2)}" fill="none" stroke-width="1.4"/>'
           + _dim_h(AX, AX + cd, AY + cd + 14, "Ø", "diameter"))
    if "holes" in features:  # cylinder "holes" feature = a central bore
        br = max(1.6, float(d.get("bore_diameter", 10)) / 2 * s)
        top += (f'<g data-ref="ref_bore_diameter"><circle cx="{_n(cx)}" cy="{_n(cy)}" '
                f'r="{_n(br)}" fill="none"/></g>' + _note(cx + cd / 2 + 4, AY - 2, "bore Ø", "bore_diameter"))

    right = (_rect(AX, AY, fw, fh)
             + _dim_v(AY, AY + fh, AX + fw + 12, "H", "height"))
    if "holes" in features:
        right += (f'<g data-ref="ref_bore_depth">'
                  f'<line x1="{_n(AX + fw / 2)}" y1="{_n(AY)}" x2="{_n(AX + fw / 2)}" y2="{_n(AY + fh)}" '
                  f'stroke-dasharray="3 2"/><text x="{_n(AX + fw / 2 + 4)}" y="{_n(AY + fh / 2)}">d</text></g>')

    return {"front": _wrap(ORTHO_VIEW, front), "top": _wrap(ORTHO_VIEW, top),
            "right": _wrap(ORTHO_VIEW, right), "iso": _wrap(ISO_VIEW, _cylinder_iso(dia, height))}


def _poly(points, ref=None, sw="1.2") -> str:
    pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in points)
    r = f' data-ref="ref_{ref}"' if ref else ""
    return f'<polygon{r} points="{pts}" fill="none" stroke-width="{sw}"/>'


def l_bracket_views(d: dict[str, float], features: set[str]) -> dict[str, str]:
    a = float(d.get("leg_a", 50))
    b = float(d.get("leg_b", 30))
    t = float(d.get("thickness", 5))
    depth = float(d.get("depth", 40))
    s = min(AVAIL_W / max(a, depth), AVAIL_H / max(b, depth))
    verts = [(0, 0), (a, 0), (a, t), (t, t), (t, b), (0, b)]

    # front: the L profile (model y is up, SVG y is down -> flip about the bottom edge)
    bottom = AY + b * s

    def fpt(mx, my):
        return (AX + mx * s, bottom - my * s)

    front = (_poly([fpt(*v) for v in verts], ref="leg_a")
             + _dim_h(AX, AX + a * s, bottom + 14, "A", "leg_a")
             + _dim_v(AY, bottom, AX - 8, "B", "leg_b", right=False)
             + _dim_h(AX, AX + t * s, AY - 6, "t", "thickness"))
    if "filleted_edges" in features:
        r = max(5.0, float(d.get("inner_radius", 4)) * s)
        ix, iy = fpt(t, t)
        front += (f'<g data-ref="ref_inner_radius">'
                  f'<path d="M{_n(ix)} {_n(iy + r)} A {_n(r)} {_n(r)} 0 0 1 {_n(ix + r)} {_n(iy)}" '
                  f'fill="none"/><text x="{_n(ix + r + 2)}" y="{_n(iy + r)}">r</text></g>')

    # top: leg_a x depth rectangle (looking down the vertical leg)
    tw, th = a * s, depth * s
    top = (_rect(AX, AY, tw, th)
           + _dim_h(AX, AX + tw, AY + th + 14, "A", "leg_a")
           + _dim_v(AY, AY + th, AX + tw + 12, "D", "depth"))
    if "holes" in features:
        top += _l_bracket_holes(d, s, tw, th)

    # right: depth x leg_b rectangle
    rw, rh = depth * s, b * s
    right = (_rect(AX, AY, rw, rh)
             + _dim_h(AX, AX + rw, AY + rh + 14, "D", "depth")
             + _dim_v(AY, AY + rh, AX + rw + 12, "B", "leg_b"))

    return {"front": _wrap(ORTHO_VIEW, front), "top": _wrap(ORTHO_VIEW, top),
            "right": _wrap(ORTHO_VIEW, right), "iso": _wrap(ISO_VIEW, _l_bracket_iso(a, b, t, depth))}


def _l_bracket_holes(d: dict[str, float], s: float, tw: float, th: float) -> str:
    edge = float(d.get("hole_edge", 10))
    count = max(1, int(d.get("hole_count", 1)))
    dia = float(d.get("hole_diameter", 6))
    r = max(1.6, dia / 2 * s)
    cy = AY + th / 2
    if count == 1:
        xs = [AX + tw / 2]
    else:
        step = (tw - 2 * edge * s) / (count - 1)
        xs = [AX + edge * s + i * step for i in range(count)]
    circles = "".join(f'<circle cx="{_n(x)}" cy="{_n(cy)}" r="{_n(r)}" fill="none"/>' for x in xs)
    return (f'<g data-ref="ref_hole_diameter">{circles}</g>'
            + _dim_h(AX, AX + edge * s, AY + th + 26, "e", "hole_edge")
            + _note(AX + tw + 2, AY - 4, f"{count}x Ø", "hole_count"))


def _l_bracket_iso(a: float, b: float, t: float, depth: float) -> str:
    verts = [(0, 0), (a, 0), (a, t), (t, t), (t, b), (0, b)]
    si = min(78 / max(a, b), 54 / max(a, b))
    kx, ky = depth * si * 0.5 * _COS30, depth * si * 0.5 * _SIN30

    def fp(mx, my):
        return (24 + mx * si, 92 - my * si)

    front = [fp(*v) for v in verts]
    back = [(x + kx, y - ky) for x, y in front]
    connectors = "".join(
        f'<line x1="{_n(fx)}" y1="{_n(fy)}" x2="{_n(bx)}" y2="{_n(by)}"/>'
        for (fx, fy), (bx, by) in zip(front, back, strict=True)
    )
    return _poly(front) + _poly(back) + connectors


def _cylinder_iso(dia: float, height: float) -> str:
    s = min(80 / dia, 80 / height)
    rx = dia / 2 * s
    ry = max(3.0, rx * 0.38)
    h = height * s
    cx, top_y = 65, max(24, 58 - h / 2)
    bot_y = top_y + h
    return (f'<ellipse cx="{_n(cx)}" cy="{_n(top_y)}" rx="{_n(rx)}" ry="{_n(ry)}" '
            f'fill="none" stroke-width="1.2"/>'
            f'<line x1="{_n(cx - rx)}" y1="{_n(top_y)}" x2="{_n(cx - rx)}" y2="{_n(bot_y)}"/>'
            f'<line x1="{_n(cx + rx)}" y1="{_n(top_y)}" x2="{_n(cx + rx)}" y2="{_n(bot_y)}"/>'
            f'<path d="M{_n(cx - rx)} {_n(bot_y)} A {_n(rx)} {_n(ry)} 0 0 0 {_n(cx + rx)} {_n(bot_y)}" '
            f'fill="none" stroke-width="1.2"/>')
