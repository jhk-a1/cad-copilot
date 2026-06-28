"""CLI: run the bench against the live app (in-process) and write a scorecard.

  python -m eval.run                         # full bench -> eval/results/
  python -m eval.run --slices mvp_families   # one slice
  python -m eval.run --baseline bench/baseline_scorecard.json   # also check regressions
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _force_offline_mock() -> None:
    """Default the bench to the offline mock gateway, so a developer's live `ai_server/.env`
    can't silently bill per case (and so results stay comparable to the mock-built baseline).
    Pass --live to run against the configured real provider instead."""
    os.environ["MODELS_CONFIG_PATH"] = ""
    from ai_server.config import get_settings

    get_settings.cache_clear()

RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval" / "results"


def _markdown(scorecard: dict[str, Any]) -> str:
    cols = [
        "count",
        "behavior_accuracy",
        "ir_validity",
        "generation_rate",
        "dimensional_accuracy",
        "render_check_rate",
        "iou_mean",
        "views_ok_rate",
        "plan_latency_ms_mean",
    ]
    lines = [
        "# CAD-Copilot Bench Scorecard",
        "",
        f"Measured: {scorecard['measured']}",
        f"Kernel metrics: {scorecard['kernel_metrics_status']}",
        "",
        "| scope | " + " | ".join(cols) + " |",
        "|" + "---|" * (len(cols) + 1),
    ]

    def row(scope: str, s: dict[str, Any]) -> str:
        return "| " + scope + " | " + " | ".join(str(s.get(c)) for c in cols) + " |"

    lines.append(row("**overall**", scorecard["overall"]))
    for name, s in scorecard["slices"].items():
        lines.append(row(name, s))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slices", nargs="*", default=None)
    parser.add_argument("--out", default=str(RESULTS_DIR))
    parser.add_argument("--baseline", default=None, help="scorecard JSON to check regressions against")
    parser.add_argument("--threshold", type=float, default=2.0)
    parser.add_argument("--live", action="store_true",
                        help="run against the configured real provider (spends money); default is mock")
    args = parser.parse_args()

    if not args.live:
        _force_offline_mock()
    else:
        print("WARNING: --live runs every case against the real provider (this costs money).")

    from fastapi.testclient import TestClient

    from ai_server.main import app

    from . import compare, harness

    client = TestClient(app)
    scorecard = harness.run(client, args.slices)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scorecard.json").write_text(json.dumps(scorecard, indent=2) + "\n")
    (out_dir / "scorecard.md").write_text(_markdown(scorecard))

    print(_markdown(scorecard))
    print(f"scorecard -> {out_dir / 'scorecard.json'}")

    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text())
        regressions = compare.find_regressions(baseline, scorecard, args.threshold)
        if regressions:
            print("\nREGRESSIONS:")
            for r in regressions:
                print(f"  {r['metric']}: {r['baseline']} -> {r['current']} (drop {r['drop']})")
            return 1
        print(f"\nNo regressions vs baseline (threshold {args.threshold} pts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
