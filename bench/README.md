# CAD-Copilot Bench

The in-house benchmark and the published accuracy methodology. **Accuracy is the paramount,
non-negotiable requirement** — this measuring stick is built before the engines it measures, and
no engine change ships without a bench run (plan §4, ADR-001). No competitor publishes accuracy
numbers; publishing ours is a deliberate competitive weapon.

## What a case is

Each case (in `cases/<slice>.json`) encodes the **intended product behavior** for one prompt:

```json
{
  "id": "mvp_box_00", "slice": "mvp_families", "family": "box",
  "prompt": "a box", "clarification_answers": null,
  "golden_dimensions": {"length": 50, "width": 30, "height": 20},
  "expected_geometry": {"bbox_mm": [50,30,20], "volume_mm3": 30000, "tolerance_mm": 0.1},
  "reference_solid": null,
  "expected_behavior": "generate"
}
```

`expected_behavior` ∈ `generate | clarify | decompose | refuse`. Cases encode what the product
*should* do — so cases the current placeholder pipeline can't yet satisfy (extended families,
hard refusals) score low now and rise as real engines land. **That gap is the point of a baseline.**

## Slices

| Slice | Tests |
|---|---|
| `mvp_families` | box / cylinder / L-bracket — plain, with features, paraphrases |
| `extended_families` | plate-with-holes, shelled container, flange, slotted bracket (engine pending) |
| `dimension_fidelity` | exact entered dims must survive to userParameters within 0.1 mm |
| `edge_cases` | minimal input, extreme dims, unit mixes, ambiguous → clarify |
| `refusal_correctness` | out-of-scope objects must NOT fabricate geometry |

## Metrics

| Metric | Meaning | Status |
|---|---|---|
| `behavior_accuracy` | planner classified the request correctly | live |
| `ir_validity` | codegen response is contract-valid (a refusal counts) | live |
| `generation_rate` | generate-cases that returned a Command IR | live |
| `dimensional_accuracy` | entered dims honored within 0.1 mm | live |
| `views_ok_rate` | part drawing returns front/top/right/iso | live |
| `iou` / `chamfer` / kernel execution | geometric fidelity vs reference solid | **pending M2-W6** (geometry kernel) |

## Run

```bash
python -m eval.run                                       # full bench -> eval/results/
python -m eval.run --slices mvp_families dimension_fidelity
python -m eval.run --baseline bench/baseline_scorecard.json   # CI regression gate (fail >2pt drop)
python bench/build_cases.py                              # regenerate cases (deterministic)
```

## Baseline (placeholder pipeline, mock gateway)

`bench/baseline_scorecard.json` — 44 cases. behavior 81.8 / ir-validity 100 / generation 77.8 /
dims 100 / views 100. The extended-families and l-bracket gaps are the documented placeholder
limits the real LLM engines (M1-W3+) and geometry kernel (M2-W6) close. Bench grows toward the
~200-case target as families and engines land.
