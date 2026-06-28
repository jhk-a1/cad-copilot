"""Generate the CAD-Copilot Bench cases (M1-W1-EVAL-01).

Deterministic generator → bench/cases/<slice>.json. Each case is the ground truth for one
prompt: golden dimensions, expected geometry, and the behavior the product SHOULD exhibit
(generate / clarify / decompose / refuse). The bench encodes INTENDED product behavior, so
cases the current placeholder pipeline can't yet satisfy (extended families, hard refusals)
are expected to score low now and rise as real engines land — that gap is the point of a
baseline.

Run:  python bench/build_cases.py    (re-emits the JSON; deterministic, no randomness)
"""

from __future__ import annotations

import json
import math
from pathlib import Path

CASES_DIR = Path(__file__).parent / "cases"

FAMILY_DIMS: dict[str, dict[str, float]] = {
    "box": {"length": 50, "width": 30, "height": 20},
    "cylinder": {"diameter": 25, "height": 40},
    "l_bracket": {"leg_a": 50, "leg_b": 30, "thickness": 5, "depth": 40},
}


def _bbox(family: str, d: dict[str, float]) -> list[float] | None:
    if family == "box":
        return [d["length"], d["width"], d["height"]]
    if family == "cylinder":
        return [d["diameter"], d["diameter"], d["height"]]
    if family == "l_bracket":
        return [d["leg_a"], d["depth"], d["leg_b"]]
    return None


def _volume(family: str, d: dict[str, float]) -> float | None:
    if family == "box":
        return d["length"] * d["width"] * d["height"]
    if family == "cylinder":
        return math.pi * (d["diameter"] / 2) ** 2 * d["height"]
    return None


def _case(cid: str, slice_: str, family: str, prompt: str, behavior: str, **extra) -> dict:
    dims = extra.pop("golden_dimensions", FAMILY_DIMS.get(family, {}))
    exp_geo = None
    if behavior in ("generate", "decompose") and family in FAMILY_DIMS:
        exp_geo = {"bbox_mm": _bbox(family, dims), "volume_mm3": _volume(family, dims), "tolerance_mm": 0.1}
    case = {
        "id": cid,
        "slice": slice_,
        "family": family,
        "prompt": prompt,
        "clarification_answers": extra.pop("clarification_answers", None),
        "golden_dimensions": dims if behavior in ("generate", "decompose") else {},
        "expected_geometry": exp_geo,
        "reference_solid": None,  # built by the kernel later (M2-W6) for IoU/CD
        "expected_behavior": behavior,
        "notes": extra.pop("notes", ""),
    }
    return case


def mvp_families() -> list[dict]:
    cases: list[dict] = []
    paraphrases = {
        "box": ["a box", "make a rectangular block", "create a box 50 by 30 by 20 mm", "I need a simple cuboid"],
        "cylinder": ["a cylinder", "make a round rod", "create a 25mm diameter cylinder 40mm tall", "a tube"],
        "l_bracket": ["an L-bracket", "make an angle bracket", "create an L shaped bracket", "an L profile bracket"],
    }
    for family, prompts in paraphrases.items():
        for i, p in enumerate(prompts):
            cases.append(_case(f"mvp_{family}_{i:02d}", "mvp_families", family, p, "generate"))
    # with features
    cases.append(_case("mvp_box_fillet", "mvp_families", "box", "a box with rounded edges", "generate",
                       notes="filleted_edges feature"))
    cases.append(_case("mvp_box_holes", "mvp_families", "box", "a box with mounting holes", "generate",
                       notes="holes feature"))
    cases.append(_case("mvp_cyl_cham", "mvp_families", "cylinder", "a cylinder with chamfered top", "generate",
                       notes="chamfer feature"))
    return cases


def extended_families() -> list[dict]:
    """Intended-supported but not yet built by the placeholder — expected low baseline."""
    specs = [
        ("ext_plate_holes_00", "box", "a plate with a pattern of holes"),
        ("ext_plate_holes_01", "box", "a flat mounting plate with four bolt holes"),
        ("ext_container_00", "cylinder", "a shelled container"),
        ("ext_container_01", "cylinder", "a hollow cup-like container with thin walls"),
        ("ext_flange_00", "cylinder", "a flanged revolve part"),
        ("ext_flange_01", "cylinder", "a round flange with a central bore"),
        ("ext_slot_00", "l_bracket", "a slotted bracket"),
        ("ext_slot_01", "l_bracket", "an L-bracket with slotted holes"),
    ]
    return [_case(cid, "extended_families", fam, prompt, "generate", notes="extended family — engine pending")
            for cid, fam, prompt in specs]


def dimension_fidelity() -> list[dict]:
    """Exact dims must survive to userParameters within 0.1 mm."""
    cases = []
    variants = [
        ("dim_box_00", "box", "a box 80mm x 40mm x 15mm", {"length": 80, "width": 40, "height": 15}),
        ("dim_box_01", "box", "a 100 by 25 by 25 mm bar", {"length": 100, "width": 25, "height": 25}),
        ("dim_box_02", "box", "a thin plate 200mm x 150mm x 3mm", {"length": 200, "width": 150, "height": 3}),
        ("dim_cyl_00", "cylinder", "a cylinder 12mm diameter 60mm tall", {"diameter": 12, "height": 60}),
        ("dim_cyl_01", "cylinder", "a 50mm diameter disc 5mm thick", {"diameter": 50, "height": 5}),
        ("dim_box_03", "box", "a 30mm cube", {"length": 30, "width": 30, "height": 30}),
    ]
    for cid, fam, prompt, dims in variants:
        cases.append(_case(cid, "dimension_fidelity", fam, prompt, "generate", golden_dimensions=dims))
    return cases


def edge_cases() -> list[dict]:
    return [
        _case("edge_minimal_box", "edge_cases", "box", "box", "generate", notes="minimal input"),
        _case("edge_minimal_cyl", "edge_cases", "cylinder", "cylinder", "generate", notes="minimal input"),
        _case("edge_empty", "edge_cases", "box", "", "clarify", notes="empty -> must clarify, not guess"),
        _case("edge_extreme_small", "edge_cases", "box", "a 0.5mm cube", "generate",
              golden_dimensions={"length": 0.5, "width": 0.5, "height": 0.5}, notes="extreme small"),
        _case("edge_extreme_large", "edge_cases", "box", "a 2 meter long beam 100mm square", "generate",
              golden_dimensions={"length": 2000, "width": 100, "height": 100}, notes="extreme large"),
        _case("edge_unit_inch", "edge_cases", "box", "a box 2 inches by 1 inch by half an inch", "generate",
              notes="imperial units — server normalizes to mm"),
        _case("edge_ambiguous", "edge_cases", "box", "make me something cool", "clarify",
              notes="ambiguous -> clarify"),
    ]


def refusal_correctness() -> list[dict]:
    """Out-of-scope objects must NOT produce wrong geometry — clarify or refuse."""
    prompts = [
        ("ref_dragon", "a dragon statue"),
        ("ref_face", "a human face sculpture"),
        ("ref_gear", "a 24-tooth involute spur gear"),
        ("ref_engine", "a working car engine"),
        ("ref_assembly", "a full gearbox assembly with shafts and bearings"),
        ("ref_organic", "an organic flowing vase with curved surfaces"),
        ("ref_nonsense", "asdfghjkl qwerty"),
        ("ref_threads", "an M8 threaded bolt with hex head"),
    ]
    return [_case(cid, "refusal_correctness", "unsupported", prompt, "clarify",
                  notes="out of scope -> must not fabricate geometry") for cid, prompt in prompts]


def main() -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    slices = {
        "mvp_families": mvp_families(),
        "extended_families": extended_families(),
        "dimension_fidelity": dimension_fidelity(),
        "edge_cases": edge_cases(),
        "refusal_correctness": refusal_correctness(),
    }
    total = 0
    for name, cases in slices.items():
        (CASES_DIR / f"{name}.json").write_text(json.dumps(cases, indent=2) + "\n")
        total += len(cases)
        print(f"{name}: {len(cases)} cases")
    print(f"TOTAL: {total} cases (target 200 — grows as families/engines land)")


if __name__ == "__main__":
    main()
