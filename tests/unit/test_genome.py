"""Tests for the Design-Genome generation engine (ADR-007).

Covers the whole correct-by-construction stack: grammar closure, the deterministic planner, the
hole solver + DRC feasibility, the fragment library + compiler, the Kernel-CEGIS loop, and the
live-path genome parser. The headline guarantees: a hollow body is render-check VERIFIED hollow,
invalid geometry is structurally impossible, and a malformed genome is refused, never emitted.
"""

from __future__ import annotations

import math

import pytest

from ai_server.models import PartPlan
from ai_server.services.command_ir import IRValidator
from ai_server.services.genome import (
    Feature,
    FeatureType,
    Genome,
    parse_genome,
    plan_genome,
    synthesize,
    unmet_requirements,
    validate_genome,
)
from ai_server.services.genome.library import build_ir
from ai_server.services.genome.solver import solve

V = IRValidator()


def _part(pid, family, features=(), object_type="part", **fn):
    return PartPlan(id=pid, name=pid.title(), family=family, object_type=object_type,
                    features=list(features), **fn)


# --------------------------------------------------------------------------- grammar closure

def test_well_formed_genome_passes_closure():
    g = Genome(part_id="c", features=[Feature(id="c", type=FeatureType.SOLID_CYLINDER)])
    assert validate_genome(g) == []


def test_no_primary_is_rejected():
    g = Genome(part_id="x", features=[Feature(id="f", type=FeatureType.FILLET)])
    assert any("primary" in e for e in validate_genome(g))


def test_two_primaries_is_rejected():
    g = Genome(part_id="x", features=[
        Feature(id="a", type=FeatureType.SOLID_BOX),
        Feature(id="b", type=FeatureType.SOLID_CYLINDER)])
    assert any("primary" in e for e in validate_genome(g))


def test_primary_must_come_first():
    g = Genome(part_id="x", features=[
        Feature(id="f", type=FeatureType.FILLET),
        Feature(id="b", type=FeatureType.SOLID_BOX)])
    assert any("first" in e for e in validate_genome(g))


def test_unknown_hole_is_rejected():
    g = Genome(part_id="x", features=[
        Feature(id="b", type=FeatureType.SOLID_BOX, params={"radius": 5})])
    assert any("unknown hole" in e for e in validate_genome(g))


def test_duplicate_feature_id_is_rejected():
    g = Genome(part_id="x", features=[
        Feature(id="a", type=FeatureType.SOLID_BOX),
        Feature(id="a", type=FeatureType.FILLET)])
    assert any("duplicate" in e for e in validate_genome(g))


# --------------------------------------------------------------------------- planner

def test_planner_maps_hollow_and_handle():
    assert plan_genome(_part("body", "hollow_cylinder")).primary.type is FeatureType.HOLLOW_CYLINDER
    assert plan_genome(_part("h", "curved_handle")).primary.type is FeatureType.LOOP_HANDLE
    assert plan_genome(_part("b", "box")).primary.type is FeatureType.SOLID_BOX
    assert plan_genome(_part("m", "mug")).primary.type is FeatureType.HOLLOW_CYLINDER


def test_planner_keyword_fallback():
    # family not in the table but a known keyword -> still resolved
    assert plan_genome(_part("p", "coffee_tumbler", object_type="hollow vessel")) is not None


def test_planner_routes_surface_texture_to_modifier_not_part():
    g = plan_genome(_part("body", "hollow_cylinder", features=["dragon_scales"]))
    types = [f.type for f in g.features]
    assert types == [FeatureType.HOLLOW_CYLINDER, FeatureType.SURFACE_PATTERN]


def test_planner_returns_none_for_unknown_family():
    assert plan_genome(_part("w", "dragon_wing", object_type="organic")) is None


# --------------------------------------------------------------------------- solver / DRC

def test_solver_fills_defaults():
    g = Genome(part_id="c", features=[Feature(id="c", type=FeatureType.SOLID_CYLINDER)])
    solved, notes = solve(g, {})
    assert solved.features[0].params["diameter"] == 25
    assert notes == []


def test_solver_applies_user_dimensions():
    g = Genome(part_id="c", features=[Feature(id="c", type=FeatureType.SOLID_CYLINDER)])
    solved, _ = solve(g, {"diameter": 100, "height": 40})
    assert solved.features[0].params["diameter"] == 100


def test_solver_clamps_out_of_bounds_with_counterexample():
    g = Genome(part_id="c", features=[Feature(id="c", type=FeatureType.SOLID_CYLINDER)])
    solved, notes = solve(g, {"diameter": -5})
    assert solved.features[0].params["diameter"] > 0
    assert any("diameter" in n for n in notes)


def test_solver_drc_thins_an_over_thick_wall():
    g = Genome(part_id="cup", features=[Feature(id="cup", type=FeatureType.HOLLOW_CYLINDER)])
    solved, notes = solve(g, {"diameter": 80, "height": 95, "wall": 999})
    wall = solved.features[0].params["wall"]
    assert wall <= 0.45 * 80  # thinned onto the feasible manifold (<= 0.45x the body)
    assert any("wall" in n for n in notes)


# --------------------------------------------------------------------------- library / compiler

@pytest.mark.parametrize("ftype", [
    FeatureType.SOLID_BOX, FeatureType.HOLLOW_BOX, FeatureType.SOLID_CYLINDER,
    FeatureType.HOLLOW_CYLINDER, FeatureType.L_BRACKET, FeatureType.LOOP_HANDLE,
])
def test_every_primary_compiles_to_valid_ir(ftype):
    solved, _ = solve(Genome(part_id="p", features=[Feature(id="p", type=ftype)]), {})
    ir, _solid = build_ir(solved)
    assert V.validate(ir).valid, ftype


def test_hollow_cylinder_is_verified_hollow():
    g = Genome(part_id="cup", features=[Feature(id="cup", type=FeatureType.HOLLOW_CYLINDER)])
    solved, _ = solve(g, {"diameter": 80, "height": 100, "wall": 4})
    ir, solid = build_ir(solved)
    # default is OPEN-TOP (a cup): cavity reaches the rim, closed only at the bottom (one wall)
    outer = math.pi * 40**2 * 100
    inner = math.pi * 36**2 * (100 - 4)
    assert solid.volume_mm3 == pytest.approx(outer - inner)
    assert solid.volume_mm3 < outer  # genuinely hollow, not a blob


# --------------------------------------------------------------------------- function -> topology

def test_cup_is_open_top_so_it_can_hold_anything():
    g = plan_genome(_part("cup", "cup", object_type="cylindrical"))
    assert g.primary.options["opening"] == "top"
    shell = next(c for c in build_ir(solve(g, {})[0])[0].commands if c.type.value == "SHELL")
    assert shell.params["open_faces"] == ["top"]


def test_pipe_is_open_both_ends():
    g = plan_genome(_part("p", "pipe", object_type="cylindrical"))
    assert g.primary.options["opening"] == "both"
    shell = next(c for c in build_ir(solve(g, {})[0])[0].commands if c.type.value == "SHELL")
    assert set(shell.params["open_faces"]) == {"top", "bottom"}


def test_sealed_vessel_stays_closed():
    g = plan_genome(_part("t", "tank", object_type="sealed"))
    assert g.primary.options["opening"] == "none"
    shell = next(c for c in build_ir(solve(g, {})[0])[0].commands if c.type.value == "SHELL")
    assert shell.params["open_faces"] == []


def test_open_top_removes_more_material_than_closed():
    from ai_server.services.geometry import HollowCylinder
    open_top = HollowCylinder(80, 100, 4, open_top=True)
    closed = HollowCylinder(80, 100, 4, open_top=False)
    assert open_top.volume_mm3 < closed.volume_mm3  # the open cavity reaches the rim


def test_every_dimension_becomes_a_user_parameter():
    g = plan_genome(_part("body", "hollow_cylinder", features=["scales"]))
    solved, _ = solve(g, {})
    ir, _ = build_ir(solved)
    names = [c.params["name"] for c in ir.commands if c.type.value == "CREATE_USER_PARAMETER"]
    # body dims + the pattern's dimensionable parameters, all prefixed by the part id
    assert "body_diameter" in names and "body_wall" in names
    assert any(n.startswith("body_pattern_") for n in names)
    assert all(n.startswith("body_") for n in names)


def test_surface_pattern_is_one_robust_mesh_skin_not_fragile_cuts():
    # ADR-010: surface texture is a single watertight displacement-field MESH skin on the wall, NOT
    # N per-feature boolean cuts (the path that died with NO_TARGET_BODY). This is the robustness fix.
    g = plan_genome(_part("body", "hollow_cylinder", features=["knurling"]))
    solved, _ = solve(g, {})
    ir, _ = build_ir(solved)
    skins = [c for c in ir.commands if c.type.value == "CREATE_MESH_BODY"]
    assert len(skins) == 1                                   # one field op, not many fragile cuts
    # NO fragile boolean cut / circular pattern remains — that was the bottleneck being removed
    cuts = [c for c in ir.commands if c.type.value == "EXTRUDE" and c.params.get("operation") == "cut"]
    assert not cuts and not [c for c in ir.commands if c.type.value == "PATTERN"]
    p = skins[0].params
    assert len(p["vertices_mm"]) % 3 == 0 and len(p["triangles"]) % 3 == 0  # well-formed mesh payload
    assert p["triangle_count"] > 200


# --------------------------------------------------------------------------- Kernel-CEGIS loop

def test_cegis_returns_verified_ir_for_a_clean_genome():
    g = plan_genome(_part("body", "hollow_cylinder"))
    r = synthesize(g)
    assert r.ok and r.ir is not None
    assert r.render_check.realized and r.render_check.ok  # the cavity is verified


def test_cegis_converges_on_infeasible_input():
    g = Genome(part_id="cup", features=[Feature(id="cup", type=FeatureType.HOLLOW_CYLINDER)])
    r = synthesize(g, {"wall": 999})
    assert r.ok                      # it still produced a buildable part...
    assert r.counterexamples         # ...by repairing the infeasible wall (visible to the user)


def test_cegis_refuses_a_malformed_genome():
    g = Genome(part_id="x", features=[Feature(id="f", type=FeatureType.FILLET)])
    r = synthesize(g)
    assert not r.ok and r.ir is None and "primary" in r.refusal


def test_cegis_user_dimensions_change_the_geometry():
    g = plan_genome(_part("c", "cylinder"))
    small = synthesize(g, {"c_diameter": 10, "c_height": 10})
    big = synthesize(g, {"diameter": 200, "height": 200})
    assert big.ir.expected_geometry.volume_mm3 > small.ir.expected_geometry.volume_mm3


# --------------------------------------------------------------------------- live-path parser

def test_parse_genome_accepts_a_good_genome():
    data = {"features": [{"id": "b", "type": "hollow_cylinder", "params": {"diameter": 70}}]}
    g = parse_genome(data, "body")
    assert g is not None and g.part_id == "body"
    assert g.primary.type is FeatureType.HOLLOW_CYLINDER


def test_parse_genome_rejects_a_malformed_one():
    # two primaries -> closure failure -> None (never reaches the kernel)
    data = {"features": [{"id": "a", "type": "solid_box"}, {"id": "b", "type": "solid_cylinder"}]}
    assert parse_genome(data, "x") is None


def test_parse_genome_tolerates_fenced_json_text():
    text = '```json\n{"features":[{"id":"b","type":"solid_box"}]}\n```'
    assert parse_genome(text, "b") is not None


# --------------------------------------------------------------------------- general vocabulary

@pytest.mark.parametrize("ftype", [
    FeatureType.CONE, FeatureType.PRISM, FeatureType.SPHERE, FeatureType.TORUS,
    FeatureType.WEDGE, FeatureType.LOFT, FeatureType.SWEEP,
])
def test_general_primitive_compiles_to_valid_ir(ftype):
    r = synthesize(Genome(part_id="p", features=[Feature(id="p", type=ftype)]))
    assert r.ok and V.validate(r.ir).valid, ftype


def test_cone_and_prism_are_kernel_verified():
    for ftype in (FeatureType.CONE, FeatureType.PRISM):
        r = synthesize(Genome(part_id="p", features=[Feature(id="p", type=ftype)]))
        assert r.render_check.realized and r.render_check.ok, ftype  # exact, not advisory


def test_prism_sides_is_structural_not_a_dimension_slot():
    g = Genome(part_id="p", features=[Feature(id="p", type=FeatureType.PRISM, params={"sides": 8})])
    ir, _ = build_ir(solve(g, {})[0])
    poly = next(c for c in ir.commands if c.type.value == "ADD_POLYGON")
    assert poly.params["sides"] == 8
    names = [c.params["name"] for c in ir.commands if c.type.value == "CREATE_USER_PARAMETER"]
    assert not any("sides" in n for n in names)  # topology, not a length the user dimensions


# --------------------------------------------------------- functional routing (generalisation)

def test_shape_field_drives_the_build_not_a_family_list():
    # family is gibberish the keyword map has never seen, but the model reasoned shape='cone'
    part = _part("x", "flibbertigibbet", object_type="weird", shape="cone")
    assert plan_genome(part).primary.type is FeatureType.CONE


def test_hollow_and_opening_come_from_function():
    part = _part("b", "thing", shape="cylinder", hollow=True, opening="top")
    g = plan_genome(part)
    assert g.primary.type is FeatureType.HOLLOW_CYLINDER
    assert g.primary.options["opening"] == "top"


def test_pipe_function_opens_both_ends_via_fields():
    part = _part("p", "thing", shape="cylinder", hollow=True, opening="both")
    assert plan_genome(part).primary.options["opening"] == "both"


def test_bore_adds_a_verified_central_hole():
    part = _part("c", "thing", shape="cylinder", bore=True)
    g = plan_genome(part)
    assert [f.type for f in g.features] == [FeatureType.SOLID_CYLINDER, FeatureType.BORE]
    r = synthesize(g)
    assert r.ok and r.render_check.realized and r.render_check.ok  # cylinder-with-bore, verified
    assert any(c.type.value == "HOLE" for c in r.ir.commands)


@pytest.mark.parametrize("shape,expected", [
    ("sphere", FeatureType.SPHERE), ("ball", FeatureType.SPHERE),
    ("cone", FeatureType.CONE), ("funnel", FeatureType.CONE),
    ("prism", FeatureType.PRISM), ("torus", FeatureType.TORUS), ("ring", FeatureType.TORUS),
    ("wedge", FeatureType.WEDGE), ("elbow", FeatureType.SWEEP), ("adapter", FeatureType.LOFT),
])
def test_shape_vocabulary_maps_to_primitives(shape, expected):
    assert plan_genome(_part("p", "x", shape=shape)).primary.type is expected


# ------------------------------------------------------ functional-verification gate (purpose met)

def test_functional_gate_flags_a_solid_built_for_a_hollow_part():
    part = _part("cup", "thing", shape="cylinder", hollow=True)
    solid = Genome(part_id="cup", features=[Feature(id="cup", type=FeatureType.SOLID_CYLINDER)])
    assert any("HOLLOW" in u for u in unmet_requirements(part, solid))


def test_functional_gate_passes_when_purpose_is_met():
    part = _part("cup", "thing", shape="cylinder", hollow=True, opening="top")
    assert unmet_requirements(part, plan_genome(part)) == []


def test_functional_gate_flags_missing_bore():
    part = _part("c", "thing", shape="cylinder", bore=True)
    no_bore = Genome(part_id="c", features=[Feature(id="c", type=FeatureType.SOLID_CYLINDER)])
    assert any("BORE" in u for u in unmet_requirements(part, no_bore))


# ----------------------------------------------------- connector-frame attachment (joints)

def test_handle_seats_on_the_host_wall_not_floating():
    from ai_server.services.genome.frames import align, host_connector, part_mounting
    from ai_server.services.geometry import HollowCylinder
    body = HollowCylinder(80, 100, 4)  # R = 40
    pl = align(part_mounting("loop_handle", {"loop_depth": 10, "loop_height": 80}),
               host_connector(body, "side", height_frac=0.5))
    seat = pl.apply(pl.mount.origin)          # the handle's mounting point...
    assert math.hypot(seat[0], seat[1]) == pytest.approx(40.0)   # ...lands ON the wall (radius = R)
    assert seat[2] == pytest.approx(50.0)     # at mid-height
    tip = pl.apply((35, 5, 40))               # the bulge points radially outward, off the wall
    assert math.hypot(tip[0], tip[1]) > 40.0


def test_attachment_solves_a_placement_through_codegen():
    import asyncio

    from ai_server.config import Settings
    from ai_server.gateway import build_gateway
    from ai_server.models import ComplexityClass, ObjectPlan
    from ai_server.services.codegen import CodeGenService

    svc = CodeGenService(build_gateway(settings=Settings()))
    plan = ObjectPlan(
        object_name="mug", summary="", complexity_class=ComplexityClass.DECOMPOSE, confidence=0.9,
        parts=[
            _part("body", "hollow_cylinder", object_type="cylindrical", shape="cylinder", hollow=True),
            _part("handle", "curved_handle", object_type="handle", shape="handle",
                  attachment={"to": "body", "where": "side", "height_frac": 0.5}),
        ])
    handle = asyncio.run(svc.generate(plan, "handle", {}))
    body = asyncio.run(svc.generate(plan, "body", {}))
    assert handle.result.placement is not None                      # the handle is mated...
    target = handle.result.placement["target"]["origin"]
    assert math.hypot(target[0], target[1]) == pytest.approx(40.0)  # ...onto the body wall
    assert body.result.placement is None                            # free-standing body: no mate


def test_chained_attachment_composes_world_offset_so_parts_stack():
    # Multi-part assembly (the engine/box-cutter failure): crankcase <- barrel <- head. Every mate is
    # solved against its host AT THE ORIGIN; without composition the head floats back down to the
    # crankcase. The world_offset must lift each part by where its host ACTUALLY sits, so parts stack.
    import asyncio

    from ai_server.config import Settings
    from ai_server.gateway import build_gateway
    from ai_server.models import ComplexityClass, ObjectPlan
    from ai_server.services.codegen import CodeGenService, _world_offset

    svc = CodeGenService(build_gateway(settings=Settings()))
    plan = ObjectPlan(
        object_name="engine", summary="", complexity_class=ComplexityClass.DECOMPOSE, confidence=0.9,
        parts=[
            _part("crankcase", "cylinder", object_type="cylindrical", shape="cylinder"),
            _part("barrel", "cylinder", object_type="cylindrical", shape="cylinder",
                  attachment={"to": "crankcase", "where": "top"}),
            _part("head", "cylinder", object_type="cylindrical", shape="cylinder",
                  attachment={"to": "barrel", "where": "top"}),
        ])
    barrel = asyncio.run(svc.generate(plan, "barrel", {}))
    head = asyncio.run(svc.generate(plan, "head", {}))

    assert barrel.result.placement is not None
    assert "world_offset" not in barrel.result.placement       # sits straight on the crankcase (origin)

    wo = head.result.placement["world_offset"]                 # head rides the barrel, which is lifted
    expected = _world_offset(plan, plan.parts[1])              # where the barrel's local origin sits
    assert wo[2] == pytest.approx(expected[2])
    assert wo[2] > 1.0                                          # genuinely lifted, not floating down


# ----------------------------------------------------- surface features on the right wall

def test_scales_land_on_the_wall_as_a_displacement_mesh_skin():
    # ADR-010: dragon scales become a watertight displacement-field mesh hugging the wall, verified
    # offline — the body stays verified, and the texture is a robust mesh (no NO_TARGET_BODY path).
    g = plan_genome(_part("body", "hollow_cylinder", features=["dragon_scales"],
                          object_type="cylindrical", shape="cylinder", hollow=True))
    r = synthesize(g)
    skins = [c for c in r.ir.commands if c.type.value == "CREATE_MESH_BODY"]
    assert len(skins) == 1                      # the scales are one field op on the wall
    assert r.render_check.ok                    # the hollow body itself stays verified
    # the mesh actually hugs the wall: its peak radius exceeds the wall (raised relief) but is bounded
    verts = skins[0].params["vertices_mm"]
    radii = [(verts[i] ** 2 + verts[i + 1] ** 2) ** 0.5 for i in range(0, len(verts), 3)]
    assert max(radii) > 40.0 and max(radii) < 60.0   # outer wall ~R + a few mm of scale relief


def test_scales_emit_no_fragile_boolean_features():
    # the whole point of the robustness fix: there is NO per-feature boolean cut or pattern left to
    # fail. The texture cannot produce the NO_TARGET_BODY class of failure because it is a closed mesh.
    g = plan_genome(_part("body", "hollow_cylinder", features=["dragon_scales"],
                          object_type="cylindrical", shape="cylinder", hollow=True))
    r = synthesize(g)
    cuts = [c for c in r.ir.commands if c.type.value == "EXTRUDE" and c.params.get("operation") == "cut"]
    patterns = [c for c in r.ir.commands if c.type.value == "PATTERN"]
    assert not cuts and not patterns
    assert [c for c in r.ir.commands if c.type.value == "CREATE_MESH_BODY"]  # texture is a mesh skin


# ------------------------------------------------ closed-loop spatial comparator (ADR-009)

def test_comparator_confirms_a_seated_handle():
    from ai_server.services.genome.frames import align, host_connector, part_mounting
    from ai_server.services.genome.verify import attach_seat_residual
    from ai_server.services.geometry import HollowCylinder
    body = HollowCylinder(80, 95, 4)
    pl = align(part_mounting("loop_handle", {"loop_depth": 10, "loop_height": 80}),
               host_connector(body, "side", 0.5)).as_dict()
    r = attach_seat_residual(body, pl, None, "handle")
    assert r.ok and abs(r.value_mm) < 0.6      # the comparator PERCEIVES it seats on the wall


def test_comparator_detects_a_floating_part():
    from ai_server.services.genome.verify import attach_seat_residual
    from ai_server.services.geometry import HollowCylinder
    body = HollowCylinder(80, 95, 4)            # R = 40
    r = attach_seat_residual(body, None, [200, 0, 40], "handle")  # placed far off the body
    assert not r.ok and r.value_mm > 100        # perceived as FLOATING


def test_comparator_detects_scales_off_the_wall():
    import math

    from ai_server.services.genome.verify import feature_seat_residuals
    from ai_server.services.geometry import HollowCylinder
    body = HollowCylinder(80, 95, 4)
    off_wall = [(60 * math.cos(a), 60 * math.sin(a), 30) for a in (0.0, 1.0)]  # 20mm off (radius 60)
    residuals = feature_seat_residuals(body, off_wall)
    assert all(not r.ok for r in residuals)     # tangent-tab scales caught as OFF the wall


async def test_handle_default_attaches_even_without_an_explicit_attachment():
    # the live bug: the planner emitted no attachment and the handle dropped to the base.
    # A handle-like part must DEFAULT-attach to the body, and the certificate must perceive the seat.
    from ai_server.config import Settings
    from ai_server.gateway import build_gateway
    from ai_server.models import ComplexityClass, ObjectPlan
    from ai_server.services.codegen import CodeGenService
    svc = CodeGenService(build_gateway(settings=Settings()))
    plan = ObjectPlan(
        object_name="mug", summary="", complexity_class=ComplexityClass.DECOMPOSE, confidence=0.9,
        parts=[
            _part("body", "hollow_cylinder", object_type="cylindrical", shape="cylinder", hollow=True),
            _part("handle", "curved_handle", object_type="handle", shape="handle"),  # NO attachment
        ])
    resp = await svc.generate(plan, "handle", {})
    assert resp.result.placement is not None                        # default-attached
    assert any("seats on the host" in w for w in resp.result.warnings)  # certificate perceives it
