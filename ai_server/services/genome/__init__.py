"""Design-Genome generation engine (ADR-007).

Kernel-CEGIS over a correct-by-construction genome: the LLM/planner proposes a typed feature program
with holes; a solver fills the holes onto the feasible manifold; a compiler turns it into the
validated Command IR; and a feasibility-gated loop verifies it against the geometry kernel. Invalid
geometry is structurally impossible; dimensions are solved, not guessed.

Public surface:
  * `plan_genome(part)`          deterministic PartPlan -> Genome (offline, no LLM)
  * `synthesize(genome, holes)`  the Kernel-CEGIS loop -> CegisResult(ir | refusal)
  * `Genome`, `Feature`, `FeatureType`  the grammar
  * `SYSTEM_PROMPT`, `parse_genome`     the live LLM-genome path
"""

from __future__ import annotations

from .cegis import CegisResult, synthesize
from .functional import unmet_requirements
from .grammar import (
    FEATURE_SPECS,
    Feature,
    FeatureType,
    Genome,
    validate_genome,
)
from .planner import plan_genome
from .prompt import SYSTEM_PROMPT, parse_genome, user_prompt

__all__ = [
    "FEATURE_SPECS",
    "CegisResult",
    "Feature",
    "FeatureType",
    "Genome",
    "SYSTEM_PROMPT",
    "parse_genome",
    "plan_genome",
    "synthesize",
    "unmet_requirements",
    "user_prompt",
    "validate_genome",
]
