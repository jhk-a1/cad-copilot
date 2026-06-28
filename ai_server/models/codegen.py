"""Per-part code generation contract (POST /api/codegen/generate) — Stage 4, v2.1.0.

Generates a validated Command IR for ONE part of the object, or a refusal. Each part builds
independently; positioning parts into an assembly is later scope (ADR-004).
"""

from __future__ import annotations

from pydantic import Field

from .command_ir import CommandIR
from .common import Refusal, StrictModel
from .object_plan import ObjectPlan


class ExecutionStep(StrictModel):
    step: int
    operation: str
    entity_ref: str | None = None


class CodeGenRequest(StrictModel):
    object_plan: ObjectPlan
    part_id: str = Field(..., description="Which part to generate code for")
    dimensions: dict[str, float] = Field(
        ..., description="User-entered dimensions in mm — used verbatim, never re-guessed"
    )
    drawing_data: dict[str, object] | None = None


class CodeGenResult(StrictModel):
    """Successful generation for one part."""

    part_id: str
    command_ir: CommandIR
    code: str = Field(..., description="Readable Fusion-API Python for display/debug (not exec'd)")
    operations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    execution_order: list[ExecutionStep] = Field(default_factory=list)
    placement: dict[str, object] | None = Field(
        default=None,
        description="Solved attachment transform (ADR-008): {mount, target} connector frames the "
        "executor aligns so the part seats on its host's surface. None -> use the part's position.",
    )
    certificate: dict[str, object] | None = Field(
        default=None,
        description="Proof-of-fitness certificate (ADR-011): the part's Specification, the evidence, "
        "and per-obligation verdicts (satisfied/violated). Self-contained and independently "
        "re-checkable (genome.certificate.recheck) without trusting the generator.",
    )


class CodeGenResponse(StrictModel):
    """Exactly one of `result` or `refusal` is set (HTTP 200 either way)."""

    result: CodeGenResult | None = None
    refusal: Refusal | None = None
