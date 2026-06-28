"""LLM-genome path (ADR-007) — the live model proposes a GENOME, never raw geometry.

When the planner doesn't recognize a part's family, the model is asked for a `Genome` in the closed
grammar (structure + holes only). We parse it defensively and run it through closure validation; the
deterministic compiler + Kernel-CEGIS loop do the rest. The model thus does only what it is good at —
choosing a feature and rough sizes — and can never emit an invalid build program.
"""

from __future__ import annotations

import json

from .grammar import FEATURE_SPECS, Genome, validate_genome


def _catalog() -> str:
    lines = []
    for ftype, spec in FEATURE_SPECS.items():
        kind = "PRIMARY" if spec.primary else "modifier"
        holes = ", ".join(h.name for h in spec.holes) or "(none)"
        lines.append(f"  {ftype.value} [{kind}] holes: {holes}")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are the geometry stage of CAD-Copilot. You do NOT draw geometry. You emit a GENOME: a "
    "short, typed feature program for ONE part, and a constrained solver + CAD kernel turn it into "
    "exact, valid, editable geometry. Units are millimetres.\n\n"
    "Output ONLY this JSON:\n"
    '{"part_id":"<id>","features":[{"id":"<fid>","type":"<feature_type>",'
    '"params":{"<hole>":<number>},"options":{"opening":"top"},"anchor":"body"|null}]}\n\n'
    "Rules (the genome is validated; an invalid one is rejected):\n"
    "  - EXACTLY ONE primary feature, and it MUST be first (it creates the body). Modifiers follow.\n"
    "  - Use ONLY these feature types and ONLY their holes (any value you omit gets a sensible "
    "default; pick the closest type rather than inventing one):\n"
    f"{_catalog()}\n"
    "  - SERVE THE PURPOSE. Pick HOLLOW types for anything with a cavity/open interior, and set "
    'options.opening to match what the object is FOR: "top" for a cup/mug/bowl/glass/vase/'
    'container/tray (you drink/pour/fill from the open top), "both" for a pipe/tube/sleeve (open '
    'at both ends), "none" only for a genuinely sealed body (a tank/canister). A cup is NOT a cup '
    "if its top is closed — the opening is part of meeting the request.\n"
    "  - Pick loop_handle for a handle/grip. Put surface textures (scales, knurl, ribs, studs) as a "
    "surface_pattern MODIFIER on the body — never as a separate part.\n"
    "  - params values are millimetres (counts are integers). Keep numbers <= 2 decimals.\n"
    "Return ONLY the JSON genome. No prose, no markdown."
)


def user_prompt(object_name: str, summary: str, part) -> str:
    feats = ", ".join(part.features) or "none"
    return (
        f"Object: {object_name} - {summary}\n"
        f"Build this PART as a genome: id={part.id!r}, name={part.name!r}, "
        f"family={part.family!r}, features=[{feats}].\n"
        f"Use part_id={part.id!r} and put the body feature first."
    )


def parse_genome(candidate: object, part_id: str) -> Genome | None:
    """Defensively parse an LLM genome candidate; return a well-formed Genome or None."""
    data = candidate
    if isinstance(data, str):
        try:
            data = json.loads(_extract_json(data))
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    data.setdefault("part_id", part_id)
    try:
        genome = Genome.model_validate(data)
    except Exception:  # noqa: BLE001 - any schema mismatch -> no genome
        return None
    if validate_genome(genome):
        return None
    return genome


def _extract_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t
        t = t[4:] if t.lower().startswith("json") else t
    start, end = t.find("{"), t.rfind("}")
    return t[start:end + 1] if start != -1 and end != -1 else t
