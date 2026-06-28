"""Command IR v2.1 — the validated safety layer between generation and execution.

The model emits this structured, allowlisted IR under constrained decoding (never raw
Python that gets exec'd). The IR Validator (M1-W3-BE-04) checks it; the Safe Executor
(M1-W3-UI-04) realizes it inside one Fusion command transaction (one undo).

UNITS: the IR is always in millimetres. The executor converts to Fusion-internal
centimetres at the API boundary (single tested conversion helper).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .common import StrictModel

IR_VERSION = "2.1.0"


class IRCommandType(StrEnum):
    """Allowlist. The executor maps ONLY these; anything else is rejected by the validator."""

    # Parameters
    CREATE_USER_PARAMETER = "CREATE_USER_PARAMETER"  # named, editable dimension
    # Sketch
    CREATE_SKETCH = "CREATE_SKETCH"
    ADD_LINE = "ADD_LINE"
    ADD_CIRCLE = "ADD_CIRCLE"
    ADD_RECTANGLE = "ADD_RECTANGLE"
    ADD_ARC = "ADD_ARC"
    ADD_POLYGON = "ADD_POLYGON"  # regular n-gon (hex/oct posts, nut blanks, faceted columns)
    ADD_CONSTRAINT = "ADD_CONSTRAINT"
    CLOSE_SKETCH = "CLOSE_SKETCH"
    # Features
    EXTRUDE = "EXTRUDE"          # supports an optional `taper` (deg) -> cones / draft
    REVOLVE = "REVOLVE"
    SWEEP = "SWEEP"              # a profile along a path (pipes, frames, hooks) — general
    LOFT = "LOFT"               # blend between cross-sections (bottles, ducts) — general
    FILLET = "FILLET"
    CHAMFER = "CHAMFER"
    SHELL = "SHELL"
    HOLE = "HOLE"
    PATTERN = "PATTERN"  # rectangular/circular array of a feature (surface scales, ribs, bolt circles)
    # Implicit / displacement substrate (ADR-010): surface texture as a watertight mesh skin computed
    # from a height field. A closed mesh is *always* valid, so this never fails like a per-feature cut.
    CREATE_MESH_BODY = "CREATE_MESH_BODY"


class IRCommand(StrictModel):
    id: int = Field(..., ge=0)
    type: IRCommandType
    params: dict[str, object] = Field(
        default_factory=dict, description="Type-specific parameters (validated per type)"
    )
    depends_on: list[int] = Field(
        default_factory=list, description="Command ids this depends on (forms a DAG)"
    )
    produces: str | None = Field(
        default=None, description="Entity ref produced, e.g. 'sketch_0', 'profile_0', 'body_0'"
    )


class ExpectedGeometry(StrictModel):
    """Server-computed expectation used to CHECK the model — not produced by the LLM.

    The geometric verifier (M2-W6-BE-09) compares the realized solid against this.
    """

    bbox_mm: list[float] = Field(..., description="[dx, dy, dz] bounding-box extents in mm")
    volume_mm3: float | None = None
    key_dims: dict[str, float] = Field(
        default_factory=dict, description="param name -> value the model must honor (mm)"
    )


class CommandIR(StrictModel):
    version: str = Field(default=IR_VERSION)
    units: str = Field(default="mm", description="IR is always mm; executor converts to cm")
    commands: list[IRCommand]
    rollback_points: list[int] = Field(
        default_factory=list, description="Command ids at safe rollback boundaries"
    )
    expected_geometry: ExpectedGeometry | None = None
