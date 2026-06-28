"""Eval harness: drive the real pipeline per case, score, aggregate per slice."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import metrics

GATE_TOLERANCE_MM = 0.1
VIEWS_EXPECTED = {"front", "top", "right", "iso"}
CASES_DIR = Path(__file__).resolve().parents[1] / "bench" / "cases"


def load_cases(slices: list[str] | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(CASES_DIR.glob("*.json")):
        if slices and path.stem not in slices:
            continue
        cases.extend(json.loads(path.read_text()))
    return cases


def run_case(client: Any, case: dict[str, Any]) -> dict[str, Any]:
    """Run one case through object-plan -> sketch -> codegen and score it."""
    rec: dict[str, Any] = {
        "id": case["id"],
        "slice": case["slice"],
        "family": case["family"],
        "expected_behavior": case["expected_behavior"],
        # kernel metrics: iou + render-check live for box/cylinder; chamfer pending (surface sampling)
        "iou": None,
        "render_check_ok": None,
        "chamfer": None,
    }

    context = None
    if case.get("clarification_answers"):
        context = {"clarification_answers": case["clarification_answers"]}

    t0 = time.perf_counter()
    plan = client.post("/api/object/plan", json={"text": case["prompt"], "context": context}).json()
    rec["plan_latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    actual = metrics.derive_plan_behavior(plan)
    rec["actual_behavior"] = actual
    rec["behavior_correct"] = actual == case["expected_behavior"]

    rec["ir_valid"] = None
    rec["generation_completed"] = None
    rec["dim_error_mm"] = None
    rec["dim_pass"] = None
    rec["views_ok"] = None

    if actual in ("generate", "decompose") and plan.get("parts"):
        part = plan["parts"][0]
        part_id = part["id"]

        sketch = client.post(
            "/api/sketch/generate",
            json={"object_plan": plan, "part_id": part_id, "user_feedback": None},
        ).json()
        if "views" in sketch:
            rec["views_ok"] = {v["view"] for v in sketch["views"]} == VIEWS_EXPECTED

        codegen = client.post(
            "/api/codegen/generate",
            json={"object_plan": plan, "part_id": part_id, "dimensions": case.get("golden_dimensions") or {}},
        ).json()
        rec["ir_valid"] = metrics.ir_schema_valid(codegen)
        result = codegen.get("result")
        rec["generation_completed"] = result is not None
        if result:
            golden = case.get("golden_dimensions") or {}
            err = metrics.dimensional_error(result["command_ir"], golden)
            rec["dim_error_mm"] = None if err is None else (round(err, 4) if err != float("inf") else "inf")
            rec["dim_pass"] = err is None or err <= GATE_TOLERANCE_MM
            rec["render_check_ok"] = metrics.render_check_ok(result["command_ir"])
            rec["iou"] = metrics.kernel_iou(
                result["command_ir"], case["family"], golden, part.get("features"))

    return rec


def _bool_rate(records: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in records if r.get(key) is not None]
    if not vals:
        return None
    return round(100.0 * sum(1 for v in vals if v) / len(vals), 1)


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    plan_latencies = [r["plan_latency_ms"] for r in records if r.get("plan_latency_ms") is not None]
    generate_cases = [r for r in records if r["expected_behavior"] in ("generate", "decompose")]
    ious = [r["iou"] for r in records if r.get("iou") is not None]
    return {
        "count": len(records),
        "behavior_accuracy": _bool_rate(records, "behavior_correct"),
        "ir_validity": _bool_rate(records, "ir_valid"),
        "generation_rate": _bool_rate(generate_cases, "generation_completed"),
        "dimensional_accuracy": _bool_rate(records, "dim_pass"),
        "render_check_rate": _bool_rate(records, "render_check_ok"),
        "iou_mean": round(sum(ious) / len(ious), 3) if ious else None,
        "views_ok_rate": _bool_rate(records, "views_ok"),
        "plan_latency_ms_mean": round(sum(plan_latencies) / len(plan_latencies), 2) if plan_latencies else None,
        "plan_latency_ms_max": round(max(plan_latencies), 2) if plan_latencies else None,
    }


def run(client: Any, slices: list[str] | None = None) -> dict[str, Any]:
    cases = load_cases(slices)
    records = [run_case(client, c) for c in cases]
    by_slice: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_slice.setdefault(r["slice"], []).append(r)
    return {
        "version": "1.0",
        "measured": "placeholder pipeline (mock gateway)",
        "kernel_metrics_status": "render-check + IoU live for box/cylinder (analytic kernel); "
        "chamfer + l_bracket/holes pending",
        "overall": _summarize(records),
        "slices": {name: _summarize(recs) for name, recs in sorted(by_slice.items())},
        "cases": records,
    }
