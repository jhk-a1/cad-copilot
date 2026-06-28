"""Open-ended understanding (ADR-015) — the LLM formalises the unsaid into CHECKABLE requirements.

Proves the correct-by-construction filter (a hallucinated/unprovable requirement can never enter the
certificate) and that a validly-formalised requirement flows into the spec and is proven — so the
understanding generalises to ANY object via the model's reasoning while staying machine-checkable.
"""

from __future__ import annotations

from ai_server.models import RequirementSpec
from ai_server.services.genome.certificate import certify
from ai_server.services.genome.grammar import Feature, FeatureType, Genome
from ai_server.services.genome.intent_expand import proposals_to_requirements, validate
from ai_server.services.genome.library import build_ir


class _Part:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _mug():
    g = Genome(part_id="body", features=[Feature(id="b", type=FeatureType.HOLLOW_CYLINDER,
               params={"diameter": 80, "height": 95, "wall": 4}, options={"opening": "top"})])
    _, solid = build_ir(g)
    return g, solid


def _spec(metric, op, target):
    return RequirementSpec(metric=metric, op=op, target=target, description="x")


def test_valid_proposal_becomes_a_checkable_requirement():
    req = validate(_spec("capacity_mm3", ">=", "250000"), "body", 0)
    assert req is not None and req.metric == "capacity_mm3" and req.op == ">=" and req.target == 250000.0
    assert req.severity == "should" and req.kind == "expert"


def test_correct_by_construction_filter_drops_the_unprovable():
    assert validate(_spec("vibes", ">=", "5"), "p", 0) is None              # unknown metric
    assert validate(_spec("capacity_mm3", "~=", "5"), "p", 0) is None        # bad operator
    assert validate(_spec("is_hollow", ">", "true"), "p", 0) is None         # bool needs ==/!=
    assert validate(_spec("opening", "==", "sideways"), "p", 0) is None       # not a valid enum value
    assert validate(_spec("capacity_mm3", ">=", "lots"), "p", 0) is None      # unparseable number


def test_bool_and_enum_targets_parse():
    assert validate(_spec("is_hollow", "==", "true"), "p", 0).target is True
    assert validate(_spec("opening", "==", "TOP"), "p", 0).target == "top"


def test_proposals_filter_keeps_only_the_provable():
    part = _Part(id="body", requirements=[
        _spec("capacity_mm3", ">=", "250000"),   # ok
        _spec("magic", "==", "yes"),             # dropped
        _spec("wall_mm", ">=", "2"),             # ok
    ])
    reqs = proposals_to_requirements(part)
    assert {r.metric for r in reqs} == {"capacity_mm3", "wall_mm"}


def test_formalised_requirement_is_proven_by_the_certificate():
    g, solid = _mug()
    part = _Part(id="body", name="mug", hollow=True, opening="top", purpose="coffee",
                 requirements=[_spec("capacity_mm3", ">=", "250000"),
                               _spec("stability_ratio", ">=", "0.35")])
    cert = certify(part, g, solid)
    proven = {o.requirement_id.split(".", 1)[1]: o.status for o in cert.obligations
              if o.kind == "expert"}
    assert proven.get("expert.0_capacity_mm3") == "satisfied"   # ~370 ml >= 250 ml
    assert proven.get("expert.1_stability_ratio") == "satisfied"
    # the ledger marks them inferred (the unsaid, made explicit)
    assert any(a.source == "inferred" and "expert" in a.requirement_id for a in cert.spec.assumptions)


def test_a_formalised_requirement_can_fail_and_advise():
    g, solid = _mug()  # holds ~370 ml
    part = _Part(id="body", name="mug", hollow=True, opening="top",
                 requirements=[_spec("capacity_mm3", ">=", "600000")])  # demands 600 ml
    cert = certify(part, g, solid)
    o = next(o for o in cert.obligations if o.requirement_id.endswith("expert.0_capacity_mm3"))
    assert o.status == "violated"           # surfaced as advice (should), doesn't gate
    assert cert.ok                          # musts still pass
