"""Regression check: compare a scorecard against a baseline; fail on gate-metric drops.

Used in CI on engine-touching changes (M1-W2-EVAL-02). Default threshold 2 points matches
the plan's no-regression rule.
"""

from __future__ import annotations

from typing import Any

GATE_METRICS = (
    "behavior_accuracy",
    "ir_validity",
    "generation_rate",
    "dimensional_accuracy",
    "render_check_rate",
    "views_ok_rate",
)


def find_regressions(
    baseline: dict[str, Any], current: dict[str, Any], threshold: float = 2.0
) -> list[dict[str, Any]]:
    """Return overall gate metrics that dropped by more than `threshold` points."""
    out: list[dict[str, Any]] = []
    b = baseline.get("overall", {})
    c = current.get("overall", {})
    for metric in GATE_METRICS:
        bv, cv = b.get(metric), c.get(metric)
        if bv is None or cv is None:
            continue
        if bv - cv > threshold:
            out.append({"metric": metric, "baseline": bv, "current": cv, "drop": round(bv - cv, 1)})
    return out
