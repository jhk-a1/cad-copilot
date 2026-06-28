"""Function gate (ADR-013) — qualitative "does it WORK", general over any object.

Proves functions are inferred from purpose + structure (not object names), the behaviour obligations
are merged into the certificate, and a functionally-DEAD design (a sealed cup you can't fill) is
caught — the "valid solid but doesn't work" failure no text-to-CAD system detects.
"""

from __future__ import annotations

from ai_server.services.genome.certificate import certify
from ai_server.services.genome.function_model import behavior_requirements, infer_functions
from ai_server.services.genome.grammar import Feature, FeatureType, Genome
from ai_server.services.genome.library import build_ir

T = FeatureType


class _Part:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _sol(*feats):
    g = Genome(part_id="p", features=list(feats))
    _, solid = build_ir(g)
    return g, solid


def test_functions_inferred_from_purpose_and_structure():
    hollow, _ = _sol(Feature(id="b", type=T.HOLLOW_CYLINDER,
                     params={"diameter": 80, "height": 95, "wall": 4}, options={"opening": "top"}))
    # hollow structure -> contain, even without a purpose verb
    assert "contain" in infer_functions(_Part(id="p", hollow=True), hollow)
    # 'contain' and 'couple' are GEOMETRY-anchored: a hollow part's blurb mentioning attachment must
    # NOT make it a coupler (the live mug-body bug)
    assert "couple" not in infer_functions(
        _Part(id="p", hollow=True, purpose="holds coffee; the handle attaches to it"), hollow)
    # a NON-hollow part may take its function from its purpose verbs
    solid, _ = _sol(Feature(id="b", type=T.L_BRACKET,
                    params={"leg_a": 50, "leg_b": 50, "thickness": 5, "depth": 40}))
    assert "support" in infer_functions(_Part(id="p", purpose="support a shelf"), solid)
    assert "couple" in infer_functions(_Part(id="p", purpose="fasten two plates"), solid)


def test_pipe_conveys_and_contains():
    g, s = _sol(Feature(id="b", type=T.HOLLOW_CYLINDER,
                        params={"diameter": 40, "height": 120, "wall": 3}, options={"opening": "both"}))
    part = _Part(id="p", name="conduit", hollow=True, opening="both", purpose="convey water")
    funcs = infer_functions(part, g)
    assert {"contain", "convey"} <= funcs
    cert = certify(part, g, s)
    beh = {o.requirement_id.split(".", 1)[1]: o.status for o in cert.obligations if o.kind == "behavior"}
    assert beh.get("behavior.convey") == "satisfied" and beh.get("behavior.contain") == "satisfied"


def test_functionally_dead_sealed_container_is_caught():
    # hollow but with NO opening: a valid solid, but you can't fill it -> behaviour violation
    g, s = _sol(Feature(id="b", type=T.HOLLOW_CYLINDER,
                        params={"diameter": 80, "height": 95, "wall": 4}, options={"opening": "none"}))
    part = _Part(id="p", name="cup", hollow=True, purpose="hold a drink")
    cert = certify(part, g, s)
    dead = next(o for o in cert.obligations if o.requirement_id.endswith("behavior.contain"))
    assert dead.status == "violated" and dead.measured is False


def test_attached_handle_must_couple():
    g, s = _sol(Feature(id="h", type=T.LOOP_HANDLE,
                        params={"loop_width": 35, "loop_height": 80, "bar_thickness": 9, "loop_depth": 10}))
    part = _Part(id="h", name="handle")
    assert "couple" in infer_functions(part, g)
    cert = certify(part, g, s, seat_gap_mm=0.0)  # seated -> has a join
    couple = next(o for o in cert.obligations if o.requirement_id.endswith("behavior.couple"))
    assert couple.status == "satisfied"


def test_behavior_requirements_are_advisory():
    # behaviour obligations inform; they are 'should' (the hard functional gating lives in the
    # stated intent requirements), so they never block a fit verdict on their own
    g, _ = _sol(Feature(id="b", type=T.HOLLOW_CYLINDER,
                        params={"diameter": 80, "height": 95, "wall": 4}, options={"opening": "top"}))
    reqs = behavior_requirements(_Part(id="p", hollow=True, purpose="hold coffee"), g)
    assert reqs and all(r.severity == "should" and r.kind == "behavior" for r in reqs)


def test_solid_part_with_no_function_has_no_behavior_obligations():
    g, s = _sol(Feature(id="b", type=T.SPHERE, params={"diameter": 30}))
    part = _Part(id="p", name="ball")  # no function verbs, no hollow/bore/attach
    assert infer_functions(part, g) == set()
    cert = certify(part, g, s)
    assert not [o for o in cert.obligations if o.kind == "behavior"]
