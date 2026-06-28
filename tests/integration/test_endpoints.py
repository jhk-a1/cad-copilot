"""Integration tests: exercise the full object->parts->multi-view contract (v2.1.0)."""

from __future__ import annotations

import math

import pytest

pytestmark = pytest.mark.integration


def test_health(client) -> None:
    r = client.get("/health/")
    assert r.status_code == 200
    assert r.json()["contract_version"] == "2.1.0"


def test_root(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["contract_version"] == "2.1.0"


# ----------------------------------------------------------------- Stage 1: object plan


def test_plan_single_part_box(client) -> None:
    r = client.post("/api/object/plan", json={"text": "make a box 50x30x20"})
    assert r.status_code == 200
    plan = r.json()
    assert plan["complexity_class"] == "in_scope"
    assert len(plan["parts"]) == 1
    assert plan["parts"][0]["family"] == "box"


def test_plan_multi_part_object(client) -> None:
    """Describe an OBJECT -> AI decomposes into multiple parts (ADR-004)."""
    r = client.post("/api/object/plan", json={"text": "a phone stand"})
    assert r.status_code == 200
    plan = r.json()
    assert plan["object_name"] == "phone stand"
    assert len(plan["parts"]) == 2
    assert {p["id"] for p in plan["parts"]} == {"base", "upright"}
    assert all(p["family"] == "box" for p in plan["parts"])
    assert plan["complexity_class"] == "in_scope"


def test_plan_refuses_unknown_object(client) -> None:
    r = client.post("/api/object/plan", json={"text": "a dragon statue"})
    assert r.status_code == 200
    plan = r.json()
    assert plan["complexity_class"] == "out_of_scope"
    assert plan["parts"] == []
    assert plan["clarifications_needed"]  # asks instead of guessing


# ----------------------------------------------------------------- Stage 2: part drawing


def _plan(client, text: str) -> dict:
    return client.post("/api/object/plan", json={"text": text}).json()


def test_box_drawing_has_all_views(client) -> None:
    plan = _plan(client, "a box")
    r = client.post(
        "/api/sketch/generate",
        json={"object_plan": plan, "part_id": "box", "user_feedback": None},
    )
    assert r.status_code == 200
    drawing = r.json()
    views = {v["view"] for v in drawing["views"]}
    assert views == {"front", "top", "right", "iso"}
    slot_ids = {s["id"] for s in drawing["dimension_slots"]}
    assert {"length", "width", "height"} <= slot_ids
    # dimensions are highlightable on the orthographic views (iso is pictorial only)
    front = next(v for v in drawing["views"] if v["view"] == "front")
    assert "data-ref" in front["svg"]


def test_box_with_holes_full_dimension_schedule(client) -> None:
    """Every feature present is dimensioned, grouped like an engineering schedule (ADR-004)."""
    plan = _plan(client, "a box with mounting holes and rounded edges")
    r = client.post(
        "/api/sketch/generate", json={"object_plan": plan, "part_id": "box", "user_feedback": None}
    )
    slots = r.json()["dimension_slots"]
    ids = {s["id"] for s in slots}
    groups = {s["group"] for s in slots}
    assert {
        "length", "width", "height",
        "hole_diameter", "hole_edge_x", "hole_edge_y", "hole_spacing_x", "hole_spacing_y", "hole_count",
        "fillet_radius",
    } <= ids
    assert {"Overall", "Mounting holes", "Fillets"} <= groups


def test_cylinder_drawing_top_view_is_circle(client) -> None:
    plan = _plan(client, "a cylinder")
    r = client.post(
        "/api/sketch/generate",
        json={"object_plan": plan, "part_id": "cylinder", "user_feedback": None},
    )
    assert r.status_code == 200
    drawing = r.json()
    top = next(v for v in drawing["views"] if v["view"] == "top")
    assert "circle" in top["svg"]


def test_drawing_unknown_part_refuses(client) -> None:
    plan = _plan(client, "a box")
    r = client.post(
        "/api/sketch/generate",
        json={"object_plan": plan, "part_id": "does_not_exist", "user_feedback": None},
    )
    assert r.status_code == 200
    assert r.json()["reason_code"] == "OUT_OF_SCOPE"


# ----------------------------------------------------------------- Stage 4: per-part code


def test_codegen_box_part_produces_valid_ir(client) -> None:
    plan = _plan(client, "a box")
    r = client.post(
        "/api/codegen/generate",
        json={"object_plan": plan, "part_id": "box",
              "dimensions": {"length": 50, "width": 30, "height": 20}},
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result is not None
    assert result["part_id"] == "box"
    ir = result["command_ir"]
    assert ir["version"] == "2.1.0"
    assert ir["units"] == "mm"
    assert ir["expected_geometry"]["volume_mm3"] == 50 * 30 * 20
    # dimensions become named userParameters, prefixed by part id (no cross-part collision)
    param_names = {
        c["params"]["name"] for c in ir["commands"] if c["type"] == "CREATE_USER_PARAMETER"
    }
    assert param_names == {"box_length", "box_width", "box_height"}
    assert any(c["type"] == "EXTRUDE" and c["produces"] == "body_0" for c in ir["commands"])


def test_codegen_box_reports_render_check(client) -> None:
    """The render-and-check verifier (ADR-001) runs in the pipeline and reports on the result."""
    plan = _plan(client, "a box")
    r = client.post(
        "/api/codegen/generate",
        json={"object_plan": plan, "part_id": "box",
              "dimensions": {"length": 50, "width": 30, "height": 20}},
    )
    warnings = r.json()["result"]["warnings"]
    assert any("render-check ok" in w for w in warnings)


def test_codegen_cylinder_part_volume(client) -> None:
    plan = _plan(client, "a cylinder")
    r = client.post(
        "/api/codegen/generate",
        json={"object_plan": plan, "part_id": "cylinder",
              "dimensions": {"diameter": 25, "height": 40}},
    )
    assert r.status_code == 200
    ir = r.json()["result"]["command_ir"]
    expected = math.pi * (25 / 2) ** 2 * 40
    assert ir["expected_geometry"]["volume_mm3"] == pytest.approx(expected)
    assert any(c["type"] == "ADD_CIRCLE" for c in ir["commands"])


def test_codegen_l_bracket_produces_valid_ir(client) -> None:
    plan = _plan(client, "an l-bracket")
    r = client.post(
        "/api/codegen/generate",
        json={"object_plan": plan, "part_id": "l_bracket",
              "dimensions": {"leg_a": 50, "leg_b": 30, "thickness": 5, "depth": 40}},
    )
    result = r.json()["result"]
    assert result is not None  # l_bracket now generates (no longer refused)
    ir = result["command_ir"]
    names = {c["params"]["name"] for c in ir["commands"] if c["type"] == "CREATE_USER_PARAMETER"}
    assert names == {"l_bracket_leg_a", "l_bracket_leg_b", "l_bracket_thickness", "l_bracket_depth"}
    assert sum(1 for c in ir["commands"] if c["type"] == "ADD_LINE") == 6
    assert ir["expected_geometry"]["volume_mm3"] == 5 * (50 + 30 - 5) * 40
    assert any("render-check ok" in w for w in result["warnings"])


def test_multipart_object_each_part_builds_without_param_collision(client) -> None:
    """Both boxes of the phone stand build; userParameters are part-prefixed."""
    plan = _plan(client, "a phone stand")
    all_params: list[str] = []
    for part in plan["parts"]:
        r = client.post(
            "/api/codegen/generate",
            json={"object_plan": plan, "part_id": part["id"],
                  "dimensions": {"length": 80, "width": 60, "height": 8}},
        )
        ir = r.json()["result"]["command_ir"]
        all_params += [
            c["params"]["name"] for c in ir["commands"] if c["type"] == "CREATE_USER_PARAMETER"
        ]
    assert "base_length" in all_params and "upright_length" in all_params
    assert len(all_params) == len(set(all_params))  # no collisions across parts


def test_websocket_progress_echo(client) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"hello": "world"})
        msg = ws.receive_json()
        assert msg["type"] == "PROGRESS"
        assert msg["stage"] == "COMPLETE"
