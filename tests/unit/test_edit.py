"""Bidirectional / incremental editing (ADR-016) — edit in words, references never break.

Proves the lens laws (the parameter view round-trips), that natural-language edits map to deltas,
that edits are incremental (only the touched parameter changes), and the PERSISTENT-IDENTITY
guarantee: feature ids AND the IR's user-parameter names are unchanged across an edit, so downstream
references can't break (the topological-naming problem, at the parameter level).
"""

from __future__ import annotations

from ai_server.services.genome.edit import (
    Edit,
    apply_edit,
    changed,
    edit_genome,
    interpret_edit,
    parameters,
    parse_edit,
    with_parameters,
)
from ai_server.services.genome.grammar import Feature, FeatureType, Genome
from ai_server.services.genome.library import build_ir

T = FeatureType


def _mug():
    return Genome(part_id="body", features=[Feature(id="b", type=T.HOLLOW_CYLINDER,
                  params={"diameter": 80, "height": 95, "wall": 4}, options={"opening": "top"})])


# --------------------------------------------------------------------------- lens laws


def test_getput_law():  # put(get(g)) leaves the view unchanged
    g = _mug()
    assert parameters(with_parameters(g, parameters(g))) == parameters(g)


def test_putget_law():  # get(put(g, p)) == p
    g = _mug()
    p = dict(parameters(g))
    p["b.wall"] = 6.0
    assert parameters(with_parameters(g, p)) == p


def test_putput_law():  # put(put(g, p1), p2) == put(g, p2)
    g = _mug()
    p1 = {**parameters(g), "b.wall": 6.0}
    p2 = {**parameters(g), "b.wall": 7.0}
    assert parameters(with_parameters(with_parameters(g, p1), p2)) == parameters(with_parameters(g, p2))


def test_put_preserves_identity_type_and_options():
    g = _mug()
    g2 = with_parameters(g, {**parameters(g), "b.wall": 5.0})
    assert [f.id for f in g2.features] == ["b"]
    assert g2.features[0].type is T.HOLLOW_CYLINDER
    assert g2.features[0].options.get("opening") == "top"


# --------------------------------------------------------------------------- edits


def test_apply_edit_ops():
    g = _mug()
    assert parameters(apply_edit(g, Edit("wall", "set", 3.0)))["b.wall"] == 3.0
    assert parameters(apply_edit(g, Edit("wall", "scale", 2.0)))["b.wall"] == 8.0
    assert parameters(apply_edit(g, Edit("wall", "delta", 1.5)))["b.wall"] == 5.5


def test_edit_is_incremental():
    g = _mug()
    g2 = apply_edit(g, Edit("wall", "scale", 1.25))
    delta = changed(parameters(g), parameters(g2))
    assert set(delta) == {"b.wall"}            # ONLY the wall changed; diameter/height untouched


def test_global_scale_skips_structural_holes():
    g = Genome(part_id="p", features=[Feature(id="b", type=T.PRISM,
               params={"sides": 6, "radius": 12, "height": 8})])
    g2 = apply_edit(g, Edit("*", "scale", 1.2))
    assert parameters(g2)["b.radius"] == 14.4 and parameters(g2)["b.sides"] == 6.0  # sides unchanged


# --------------------------------------------------------------------------- NL parsing


def test_parse_natural_language_edits():
    g = _mug()
    assert parse_edit("make the wall thicker", g) == Edit("wall", "scale", 1.25, "make the wall thicker")
    assert parse_edit("make it taller", g).target == "height"
    assert parse_edit("a bit wider please", g).target == "diameter"
    assert parse_edit("set wall to 3", g) == Edit("wall", "set", 3.0, "set wall to 3")
    big = parse_edit("make it 20% bigger", g)
    assert big.target == "*" and big.op == "scale" and big.value == 1.2
    assert parse_edit("paint it red", g) is None      # nothing dimensional -> no edit


# --------------------------------------------------- persistent identity (refs never break)


def test_edit_preserves_feature_ids_and_ir_parameter_names():
    g = _mug()
    g2, edit = edit_genome(g, "make the wall thicker")
    assert edit is not None
    assert [f.id for f in g.features] == [f.id for f in g2.features]   # persistent feature identity
    names_before = {c.params["name"] for c in build_ir(g)[0].commands
                    if c.type.value == "CREATE_USER_PARAMETER"}
    names_after = {c.params["name"] for c in build_ir(g2)[0].commands
                   if c.type.value == "CREATE_USER_PARAMETER"}
    assert names_before == names_after        # IR user-parameter names stable -> references hold


def test_edit_genome_no_match_returns_unchanged():
    g = _mug()
    g2, edit = edit_genome(g, "make it sparkle")
    assert edit is None and parameters(g2) == parameters(g)


def _textured_mug():
    return Genome(part_id="body", features=[
        Feature(id="body", type=T.HOLLOW_CYLINDER,
                params={"diameter": 80, "height": 95, "wall": 4}, options={"opening": "top"}),
        Feature(id="body_surface_pattern", type=T.SURFACE_PATTERN, anchor="body",
                options={"motif": "scales"})])


def test_interpret_edit_handles_texture_relief_and_density():
    g = _textured_mug()
    deeper = interpret_edit("make the scales sharper and bolder", g)
    assert any(e.target == "pattern_depth" and e.value > 1 for e in deeper.dim_edits)
    finer = interpret_edit("make the texture finer", g)
    assert {e.target for e in finer.dim_edits} >= {"pattern_columns", "pattern_rows"}


def test_interpret_edit_changes_the_motif_or_to_a_custom_function():
    g = _textured_mug()
    assert interpret_edit("change it to knurled", g).pattern == "knurl"
    assert interpret_edit("make it hexagonal", g).pattern == "hex"
    # "spiky" maps to a custom height-field EXPRESSION (the universal function texture)
    spiky = interpret_edit("make the scales spikier pointing down", g).pattern
    assert spiky and ("frac" in spiky and "pow" in spiky)


def test_interpret_edit_rounds_or_bevels_edges():
    g = Genome(part_id="h", features=[Feature(id="h", type=T.LOOP_HANDLE,
               params={"loop_width": 35, "loop_height": 80, "bar_thickness": 9, "loop_depth": 10})])
    assert "fillet" in interpret_edit("round the edges of the handle", g).add_features
    assert "chamfer" in interpret_edit("bevel the edges", g).add_features


def test_interpret_edit_still_does_plain_dimension_edits():
    g = _textured_mug()
    r = interpret_edit("make the wall thicker", g)
    assert any(e.target == "wall" for e in r.dim_edits)


def test_unrecognised_edit_is_empty():
    assert interpret_edit("paint it gold and sing to it", _textured_mug()).empty


def test_llm_edit_output_is_validated_and_sanitised():
    """Whatever the LLM emits is re-validated server-side: unknown holes, bad values, and
    non-whitelisted features are dropped, so an open-ended edit can never be unsafe."""
    from ai_server.services.genome.edit import edit_result_from_llm

    g = _textured_mug()
    candidate = {
        "dimensions": [{"hole": "wall", "op": "scale", "value": 1.3},
                       {"hole": "BOGUS", "op": "set", "value": 5},        # unknown hole -> dropped
                       {"hole": "pattern_depth", "op": "set", "value": "x"}],  # bad value -> dropped
        "pattern": "hex", "add_features": ["fillet", "laser_cannon"], "message": "ok"}
    r = edit_result_from_llm(candidate, g)
    assert {e.target for e in r.dim_edits} == {"wall"}
    assert r.pattern == "hex"
    assert r.add_features == ("fillet",)               # 'laser_cannon' is not an allowed feature


def test_edit_endpoint_texture_change_returns_pattern_and_features(client):
    from ai_server.models import ComplexityClass, ObjectPlan, PartPlan

    plan = ObjectPlan(object_name="Mug", summary="a mug", complexity_class=ComplexityClass.IN_SCOPE,
                      confidence=0.9, parts=[PartPlan(id="body", name="Body",
                      family="hollow_cylinder", object_type="cylindrical", features=["dragon_scales"],
                      hollow=True, opening="top")])
    body = {"object_plan": plan.model_dump(mode="json"), "part_id": "body",
            "text": "make it knurled and round the edges",
            "dimensions": {"body_diameter": 80, "body_height": 95, "body_wall": 4}}
    r = client.post("/api/codegen/edit", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["edited"] is True
    assert out["pattern"] == "knurl"                 # texture motif changed
    assert "fillet" in out["features"]               # an edge fillet was added


def test_edit_endpoint_applies_a_natural_language_edit(client):
    from ai_server.models import ComplexityClass, ObjectPlan, PartPlan

    plan = ObjectPlan(object_name="Mug", summary="a mug", complexity_class=ComplexityClass.IN_SCOPE,
                      confidence=0.9, parts=[PartPlan(id="body", name="Body",
                      family="hollow_cylinder", object_type="cylindrical", features=[],
                      hollow=True, opening="top")])
    body = {"object_plan": plan.model_dump(mode="json"), "part_id": "body",
            "text": "make the wall thicker",
            "dimensions": {"body_diameter": 80, "body_height": 95, "body_wall": 4}}
    r = client.post("/api/codegen/edit", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["edited"] is True
    assert out["dimensions"]["body_wall"] > 4              # thicker
    assert "body_wall" in out["dimensions"]                 # same parameter NAME -> references hold
