"""Shared types for API Contract v2.0.0.

Schemas here (and across this package) are deliberately kept inside the JSON-Schema
subset supported by frontier-model constrained decoding (object / array / string /
number / boolean / enum / required). No patternProperties, no recursive $ref tricks,
no conditional schemas. A CI "subset linter" (task M1-W1-BE-02) enforces this; keep it
true by construction here.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "2.1.0"


class Unit(StrEnum):
    """Display/entry units. Internal IR is always millimetres; Fusion is centimetres."""

    MM = "mm"
    CM = "cm"
    IN = "in"


class ComplexityClass(StrEnum):
    """Intent complexity gate outcome — the 'refuse or decompose, never guess' rule."""

    IN_SCOPE = "in_scope"
    DECOMPOSE = "decompose"
    OUT_OF_SCOPE = "out_of_scope"


class RefusalReason(StrEnum):
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    BELOW_CONFIDENCE = "BELOW_CONFIDENCE"
    VERIFIER_REJECTED = "VERIFIER_REJECTED"


class StrictModel(BaseModel):
    """Base model: forbid unknown fields so contract drift is caught loudly."""

    model_config = ConfigDict(extra="forbid")


class Refusal(StrictModel):
    """First-class refusal — returned with HTTP 200, NOT an error.

    The product refuses or decomposes instead of emitting wrong geometry. The UI
    renders this honestly (message + optional decomposition the user can act on).
    """

    reason_code: RefusalReason
    message: str = Field(..., description="Human-readable, honest, non-preachy")
    decomposition_suggestion: list[str] | None = Field(
        default=None,
        description="If the request is a composite of supported families, the sub-parts",
    )
    diagnostics: dict[str, str] = Field(
        default_factory=dict,
        description="Machine-readable context (verifier scores, missing family, etc.)",
    )
