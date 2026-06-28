"""Compositional assembly (ADR-014) — typed interfaces + system-level proof, general.

Proves parts compose only when their interface TYPES match, the whole assembly is checked at the
SYSTEM level (connected + rigid via Grübler–Kutzbach), and the object-level certificate is
independently re-checkable — beyond the pairwise mates every other assembler stops at.
"""

from __future__ import annotations

from ai_server.models import ComplexityClass, ObjectPlan, PartPlan
from ai_server.services.genome.assembly import (
    Port,
    build_assembly_spec,
    certify_assembly,
    compatible,
    ports_of,
)
from ai_server.services.genome.certificate import recheck
from ai_server.services.genome.planner import plan_genome


def _body():
    return PartPlan(id="body", name="Body", family="hollow_cylinder", object_type="cylindrical",
                    features=[], hollow=True, opening="top", purpose="hold coffee")


def _handle():
    return PartPlan(id="handle", name="Handle", family="loop_handle", object_type="cylindrical",
                    features=[], attachment={"to": "body", "where": "side", "height_frac": 0.5})


def _mug_plan(extra=None):
    parts = [_body(), _handle()] + (extra or [])
    return ObjectPlan(object_name="Coffee Mug", summary="mug",
                      complexity_class=ComplexityClass.IN_SCOPE, parts=parts, confidence=0.9)


# --------------------------------------------------------------------------- typed ports


def test_ports_are_derived_from_geometry():
    body_ports = {(p.kind, p.role) for p in ports_of(plan_genome(_body()))}
    assert ("surface_round", "host") in body_ports and ("rim", "host") in body_ports
    handle_ports = {(p.kind, p.role) for p in ports_of(plan_genome(_handle()))}
    assert ("mount", "plug") in handle_ports  # the handle presents a plug to mate onto a surface


def test_interface_compatibility_is_a_typed_relation():
    assert compatible(Port("m", "mount", "plug"), Port("w", "surface_round", "host"))
    assert compatible(Port("s", "shaft", "plug"), Port("b", "bore", "host"))
    assert not compatible(Port("m", "mount", "plug"), Port("b", "bore", "host"))


# --------------------------------------------------------------- system-level certificate


def test_mug_is_a_certified_rigid_assembly():
    cert = certify_assembly(_mug_plan())
    ids = {o.requirement_id.split(".", 1)[1] for o in cert.obligations}
    assert any(i.startswith("assembly.iface") for i in ids)
    assert "assembly.connected" in ids and "assembly.rigid" in ids
    assert cert.ok
    assert recheck(cert.to_dict()).consistent          # the object certificate is re-checkable


def test_interface_obligation_records_the_matched_types():
    cert = certify_assembly(_mug_plan())
    iface = next(o for o in cert.obligations if "assembly.iface" in o.requirement_id)
    assert iface.status == "satisfied"
    assert "mount" in iface.description and "surface_round" in iface.description


def test_floating_part_breaks_connectivity():
    # a decoration that attaches to nothing and sits away from the body -> a disconnected component
    knob = PartPlan(id="knob", name="Knob", family="sphere", object_type="round",
                    features=[], position=[80, 0, 0])
    cert = certify_assembly(_mug_plan(extra=[knob]))
    conn = next(o for o in cert.obligations if o.requirement_id.endswith("assembly.connected"))
    assert conn.status == "violated" and not cert.ok


def test_single_part_object_has_no_assembly_obligations():
    plan = ObjectPlan(object_name="Ball", summary="a ball",
                      complexity_class=ComplexityClass.IN_SCOPE, confidence=0.9,
                      parts=[PartPlan(id="b", name="Ball", family="sphere", object_type="round",
                                      features=[])])
    spec, _ev = build_assembly_spec(plan)
    assert not spec.requirements      # nothing to compose -> no assembly obligations


def test_assembly_endpoint_returns_a_recheckable_certificate(client):
    plan = _mug_plan().model_dump(mode="json")
    r = client.post("/api/codegen/assembly", json=plan)
    assert r.status_code == 200
    cert = r.json()
    assert cert["ok"] is True
    assert recheck(cert).consistent
