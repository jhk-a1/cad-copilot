"""Understanding layer (ADR-012) — inferring what a thing SHOULD be, then proving it.

These tests prove the layer is GENERAL (resolution by keyword + functional inference + a generic
fallback, organized by inheritance — not a lookup table) and that the inferred requirements flow into
the Specification and are PROVEN by the certificate, with an auditable stated/inferred/derived ledger.
"""

from __future__ import annotations

import pytest

from ai_server.services.genome.certificate import certify
from ai_server.services.genome.grammar import Feature, FeatureType, Genome
from ai_server.services.genome.library import build_ir
from ai_server.services.genome.spec import derive_specification
from ai_server.services.genome.understanding import FRAMES, expand, resolve_frame


class _Part:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _hollow_cyl(diameter=80, height=95, wall=4, opening="top"):
    g = Genome(part_id="body", features=[Feature(id="b", type=FeatureType.HOLLOW_CYLINDER,
               params={"diameter": diameter, "height": height, "wall": wall},
               options={"opening": opening})])
    _, solid = build_ir(g)
    return g, solid


# --------------------------------------------------------------------------- frame resolution


@pytest.mark.parametrize("name,expected", [
    ("coffee mug", "drinkware"), ("a tall glass", "drinkware"), ("travel tumbler", "drinkware"),
    ("storage box", "container"), ("water pipe", "pipe"), ("a grab handle", "handle"),
    ("serving tray", "flatware"), ("dinner plate", "flatware"),
    ("mounting bracket", "structural"), ("wall support", "structural"),
    ("widget", "object"), ("frobnicator", "object"),  # unknown -> generic fallback (general)
])
def test_resolve_frame_by_keyword(name, expected):
    assert resolve_frame(_Part(name=name)).name == expected


def test_bracket_infers_fastening_provision():
    # a mounting bracket should have fastening holes; an L-bracket without a bore -> advisory flag
    g = Genome(part_id="br", features=[Feature(id="b", type=FeatureType.L_BRACKET,
               params={"leg_a": 50, "leg_b": 50, "thickness": 5, "depth": 40})])
    _, solid = build_ir(g)
    part = _Part(id="br", name="mounting bracket", family="l_bracket")
    cert = certify(part, g, solid)
    assert cert.spec.frame == "structural"
    assert any(a.requirement_id.endswith("func.fastening") and a.source == "inferred"
               for a in cert.spec.assumptions)


def test_resolve_frame_by_functional_inference_without_keywords():
    # no object keyword in the name, but the FUNCTION (hollow + open both ends) implies a pipe
    assert resolve_frame(_Part(name="xz-9", family="hollow_cylinder", hollow=True,
                               opening="both")).name == "pipe"
    # hollow + a drink purpose -> drinkware even though the name is opaque
    assert resolve_frame(_Part(name="part-7", hollow=True, purpose="hold a cold drink")).name == "drinkware"
    # hollow with no other signal -> container
    assert resolve_frame(_Part(name="thing", hollow=True)).name == "container"
    # nothing at all -> the generic object frame
    assert resolve_frame(_Part(name="thing")).name == "object"


def test_specificity_wins_drinkware_over_container():
    # 'mug' (drinkware) is deeper than 'box' (container); the most specific frame is chosen
    assert resolve_frame(_Part(name="mug box")).name == "drinkware"


def test_expand_walks_the_inheritance_chain():
    # a drinkware inherits vessel's stable-base and container's hollow/capacity
    exp = expand(_Part(id="body", name="mug"))
    suffixes = {r.id.split(".", 1)[1] for r in exp.requirements}
    assert exp.frame == "drinkware"
    assert {"func.hollow", "func.capacity", "erg.stable_base",
            "func.useful_capacity", "mfg.food_safe_wall", "func.opening"} <= suffixes


# --------------------------------------------------- the unsaid becomes proven obligations


def test_mug_infers_and_proves_unstated_requirements():
    g, solid = _hollow_cyl()
    # the user states only hollow + open-top; the rest must be INFERRED and proven
    part = _Part(id="body", name="Coffee Mug", family="hollow_cylinder",
                 hollow=True, opening="top", purpose="hold a hot coffee")
    cert = certify(part, g, solid)
    assert cert.spec.frame == "drinkware"
    ids = {o.requirement_id.split(".", 1)[1] for o in cert.obligations}
    assert {"erg.stable_base", "func.useful_capacity", "mfg.food_safe_wall"} <= ids
    # all inferred requirements are satisfied for a normal mug -> still certified fit
    assert cert.ok
    inferred = [a for a in cert.spec.assumptions if a.source == "inferred"]
    assert len(inferred) >= 3


def test_assumption_ledger_classifies_sources():
    g, solid = _hollow_cyl()
    part = _Part(id="body", name="mug", hollow=True, opening="top", purpose="coffee")
    spec = derive_specification(part, g, solid)
    src = {a.requirement_id.split(".", 1)[1]: a.source for a in spec.assumptions}
    assert src["func.hollow"] == "stated"          # the user declared hollow
    assert src["func.opening"] == "stated"         # the user declared the opening
    assert src["mfg.min_wall"] == "derived"        # from the process
    assert src["erg.stable_base"] == "inferred"    # the frame implied it (the unsaid)
    assert src["func.useful_capacity"] == "inferred"


def test_inferred_requirements_are_advisory_not_gating():
    # a tiny espresso cup holds < 150 ml: useful_capacity (a 'should') is violated, but the part is
    # still certified fit because all MUST obligations pass — understanding informs, doesn't block
    g, solid = _hollow_cyl(diameter=40, height=40, wall=3)
    part = _Part(id="body", name="espresso cup", hollow=True, opening="top", purpose="espresso")
    cert = certify(part, g, solid)
    assert cert.ok                                  # musts all pass
    assert any(o.requirement_id.endswith("func.useful_capacity") and o.status == "violated"
               for o in cert.advisories)
    assert "advice:" in cert.summary()


def test_handle_graspability_is_inferred_and_flagged_when_tight():
    g = Genome(part_id="handle", features=[Feature(id="h", type=FeatureType.LOOP_HANDLE,
               params={"loop_width": 35, "loop_height": 80, "bar_thickness": 9, "loop_depth": 10})])
    _, solid = build_ir(g)  # loop_handle has no analytic solid; aperture comes from the genome
    part = _Part(id="handle", name="Handle", family="loop_handle")
    cert = certify(part, g, solid, seat_gap_mm=0.0)  # seated, so the must passes
    assert cert.spec.frame == "handle"
    # inner aperture = min(35,80) - 2*9 = 17 mm < 20 mm finger clearance -> advisory
    assert any(o.requirement_id.endswith("erg.graspable") and o.status == "violated"
               for o in cert.advisories)
    assert cert.ok  # still fit (graspability is advisory)


def test_generic_object_adds_no_inferred_requirements():
    # a featureless part (a plain solid block, no function) gets only derived obligations -> the
    # generic fallback adds no inferred noise
    g = Genome(part_id="body", features=[Feature(id="b", type=FeatureType.SOLID_BOX,
               params={"length": 40, "width": 40, "height": 40})])
    _, solid = build_ir(g)
    part = _Part(id="body", name="blorp", object_type="unknown")  # opaque, no function
    spec = derive_specification(part, g, solid)
    assert spec.frame == "object"
    assert not any(a.source == "inferred" for a in spec.assumptions)


def test_frames_form_a_valid_inheritance_tree():
    for f in FRAMES.values():
        assert f.parent is None or f.parent in FRAMES  # no dangling parents
