"""Proof-of-fitness certificate (ADR-011) — the design-as-proof spine.

These tests prove three things: (1) the Specification is composed GENERALLY from functional intent
(the same rules certify a mug, a box, a bored cylinder, an attached handle), (2) the certificate's
verdicts are correct, and (3) the certificate is independently RE-CHECKABLE — tampering with a
verdict is caught (the proof-carrying property). No kernel/Fusion dependency.
"""

from __future__ import annotations

import pytest

from ai_server.services.genome.certificate import certify, check, recheck
from ai_server.services.genome.grammar import Feature, FeatureType, Genome
from ai_server.services.genome.library import build_ir
from ai_server.services.genome.spec import Specification, derive_specification, evaluate


class _Part:
    """A lightweight stand-in for PartPlan — spec/certify read attributes via getattr."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _solid(*features):
    g = Genome(part_id="body", features=list(features))
    _, solid = build_ir(g)
    return g, solid


def _mug():
    g, solid = _solid(Feature(id="b", type=FeatureType.HOLLOW_CYLINDER,
                              params={"diameter": 80, "height": 95, "wall": 4},
                              options={"opening": "top"}))
    part = _Part(id="body", object_type="cylindrical", hollow=True, opening="top",
                 bore=False, purpose="hold a hot drink")
    return part, g, solid


# --------------------------------------------------------------------------- evaluate (the core)


@pytest.mark.parametrize("op,measured,target,expect", [
    (">", 5, 0, "satisfied"), (">", 0, 0, "violated"),
    (">=", 4, 4, "satisfied"), (">=", 3, 4, "violated"),
    ("<=", 0.8, 1.0, "satisfied"), ("<=", 1.2, 1.0, "violated"),
    ("==", "top", "top", "satisfied"), ("==", "top", "both", "violated"),
    ("==", True, True, "satisfied"), ("!=", "a", "b", "satisfied"),
])
def test_evaluate_ops(op, measured, target, expect):
    status, got, _margin = evaluate("m", op, target, {"m": measured})
    assert status == expect and got == measured


def test_evaluate_missing_metric_is_unverifiable():
    status, measured, margin = evaluate("absent", ">", 0, {"present": 1})
    assert status == "unverifiable" and measured is None and margin is None


def test_margin_is_signed_distance():
    _s, _m, margin = evaluate("wall_mm", ">=", 1.0, {"wall_mm": 4.0})
    assert margin == pytest.approx(3.0)             # 3mm inside the requirement
    _s2, _m2, margin2 = evaluate("wall_mm", ">=", 1.0, {"wall_mm": 0.5})
    assert margin2 == pytest.approx(-0.5)           # 0.5mm short


# --------------------------------------------------------------------- general spec derivation


def test_mug_spec_is_composed_from_function():
    part, g, solid = _mug()
    spec = derive_specification(part, g, solid)
    kinds = {r.kind for r in spec.requirements}
    ids = {r.id.split(".", 1)[1] for r in spec.requirements}  # drop the part-id prefix
    assert {"geometric", "functional", "manufacturing"} <= kinds
    assert {"func.hollow", "func.capacity", "func.opening", "mfg.min_wall", "geom.solid"} <= ids


def test_solid_box_spec_has_no_hollow_or_capacity_requirements():
    g, solid = _solid(Feature(id="b", type=FeatureType.SOLID_BOX,
                              params={"length": 50, "width": 30, "height": 20}))
    part = _Part(id="body", object_type="prismatic", hollow=False)
    spec = derive_specification(part, g, solid)
    ids = {r.id.split(".", 1)[1] for r in spec.requirements}
    assert "geom.solid" in ids
    assert "func.hollow" not in ids and "func.capacity" not in ids  # generality: no vessel rules


def test_bored_cylinder_spec_requires_the_bore():
    g, solid = _solid(Feature(id="b", type=FeatureType.SOLID_CYLINDER,
                              params={"diameter": 40, "height": 60}),
                      Feature(id="h", type=FeatureType.BORE, params={"bore_diameter": 10}))
    part = _Part(id="body", object_type="cylindrical", bore=True, purpose="engine cylinder")
    spec = derive_specification(part, g, solid)
    assert any(r.id.endswith("func.bore") for r in spec.requirements)


# --------------------------------------------------------------------------- certify verdicts


def test_mug_is_certified_fit():
    part, g, solid = _mug()
    cert = certify(part, g, solid)
    assert cert.ok
    assert all(o.status == "satisfied" for o in cert.obligations if o.severity == "must")
    # the capacity is actually computed (an ~80x95 mug holds a few hundred ml)
    cap = next(o for o in cert.obligations if o.requirement_id.endswith("func.capacity"))
    assert cap.measured > 100_000  # mm^3 (> 100 ml)


def test_declared_hollow_but_built_solid_is_not_certified():
    # a part the user said must be HOLLOW, realized as a solid cylinder -> functional violation
    g, solid = _solid(Feature(id="b", type=FeatureType.SOLID_CYLINDER,
                              params={"diameter": 80, "height": 95}))
    part = _Part(id="body", hollow=True, purpose="cup")
    cert = certify(part, g, solid)
    assert not cert.ok
    assert any(o.requirement_id.endswith("func.hollow") and o.status == "violated"
               for o in cert.obligations)


def test_opening_mismatch_is_caught():
    g, solid = _solid(Feature(id="b", type=FeatureType.HOLLOW_CYLINDER,
                              params={"diameter": 80, "height": 95, "wall": 4},
                              options={"opening": "top"}))
    part = _Part(id="body", hollow=True, opening="both")  # wants both ends open; built open-top
    cert = certify(part, g, solid)
    assert not cert.ok
    assert any(o.requirement_id.endswith("func.opening") and o.status == "violated"
               for o in cert.obligations)


def test_attached_handle_seating_is_a_requirement():
    g, solid = _solid(Feature(id="h", type=FeatureType.LOOP_HANDLE,
                              params={"loop_width": 35, "loop_height": 80,
                                      "bar_thickness": 9, "loop_depth": 10}))
    part = _Part(id="handle")
    seated = certify(part, g, solid, seat_gap_mm=0.0)
    floating = certify(part, g, solid, seat_gap_mm=12.0)
    assert any(o.requirement_id.endswith("spatial.seated") for o in seated.obligations)
    assert seated.ok and not floating.ok


def test_thin_wall_fails_manufacturability():
    g, solid = _solid(Feature(id="b", type=FeatureType.HOLLOW_CYLINDER,
                              params={"diameter": 80, "height": 95, "wall": 0.3},
                              options={"opening": "top"}))
    part = _Part(id="body", hollow=True, opening="top")
    cert = certify(part, g, solid, process="injection")  # injection needs >= 1.0 mm
    assert not cert.ok
    assert any(o.requirement_id.endswith("mfg.min_wall") and o.status == "violated"
               for o in cert.obligations)


# ---------------------------------------------------------- the proof-carrying re-check (the moat)


def test_honest_certificate_re_verifies():
    part, g, solid = _mug()
    cert = certify(part, g, solid).to_dict()
    result = recheck(cert)
    assert result.consistent and result.checked == len([o for o in cert["obligations"]])


def test_recheck_catches_a_flipped_verdict():
    g, solid = _solid(Feature(id="b", type=FeatureType.SOLID_CYLINDER,
                              params={"diameter": 80, "height": 95}))
    cert = certify(_Part(id="body", hollow=True), g, solid).to_dict()  # hollow violated
    assert not cert["ok"]
    # forge a pass: flip the violated verdicts and claim overall ok
    for o in cert["obligations"]:
        if o["status"] == "violated":
            o["status"] = "satisfied"
    cert["ok"] = True
    result = recheck(cert)
    assert not result.consistent
    assert any("does not follow" in result.summary() or "evidence gives" in d
               for d in result.discrepancies)


def test_recheck_catches_a_faked_overall_ok():
    part, g, solid = _mug()
    cert = certify(part, g, solid).to_dict()  # genuinely ok
    # tamper ONLY the headline ok to False while obligations all say satisfied
    cert["ok"] = False
    result = recheck(cert)
    assert not result.consistent
    assert any("overall ok" in d for d in result.discrepancies)


def test_recheck_catches_a_dropped_obligation():
    part, g, solid = _mug()
    cert = certify(part, g, solid).to_dict()
    cert["obligations"] = cert["obligations"][:-1]  # silently drop a check
    result = recheck(cert)
    assert not result.consistent
    assert any("not certified (no obligation)" in d for d in result.discrepancies)


def test_recheck_catches_an_obligation_with_no_requirement():
    part, g, solid = _mug()
    cert = certify(part, g, solid).to_dict()
    cert["obligations"].append({"requirement_id": "body.ghost.req", "status": "satisfied",
                                "kind": "functional", "description": "x", "measured": 1,
                                "target": 0, "op": ">", "margin": 1, "severity": "must",
                                "tier": "proved"})
    result = recheck(cert)
    assert not result.consistent
    assert any("no matching requirement" in d for d in result.discrepancies)


def test_specification_roundtrips_through_dict():
    part, g, solid = _mug()
    spec = derive_specification(part, g, solid)
    back = Specification.from_dict(spec.to_dict())
    assert back.part_id == spec.part_id
    assert [r.id for r in back.requirements] == [r.id for r in spec.requirements]
    # re-checking a certificate built from the round-tripped spec still works
    from ai_server.services.genome.spec import evidence as gather
    cert = check(back, gather(part, g, solid)).to_dict()
    assert recheck(cert).consistent


# --------------------------------------------------------- end to end through the codegen service


async def test_codegen_attaches_a_recheckable_certificate():
    """The full pipeline: a mug plan -> CodeGenService -> a result carrying a re-checkable
    certificate proving the part meets its spec. No LLM call (deterministic genome family)."""
    from ai_server.config import Settings
    from ai_server.gateway import build_gateway
    from ai_server.models import ComplexityClass, ObjectPlan, PartPlan
    from ai_server.services.codegen import CodeGenService

    mug = PartPlan(id="body", name="Body", family="hollow_cylinder", object_type="cylindrical",
                   features=[], hollow=True, opening="top", purpose="hold a hot drink")
    plan = ObjectPlan(object_name="mug", summary="a mug",
                      complexity_class=ComplexityClass.IN_SCOPE, parts=[mug], confidence=0.8)
    resp = await CodeGenService(build_gateway(settings=Settings())).generate(plan, "body", {})
    assert resp.result is not None
    cert = resp.result.certificate
    assert cert is not None and cert["ok"] is True
    assert recheck(cert).consistent                       # independently re-verifiable
    ids = {o["requirement_id"].split(".", 1)[1] for o in cert["obligations"]}
    assert {"func.hollow", "func.opening", "mfg.min_wall"} <= ids  # meaningful, general obligations
