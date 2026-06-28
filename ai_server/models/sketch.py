"""Per-part multi-view drawing contract (POST /api/sketch/generate) — Stage 2, v2.1.0.

Each part is verified the way an engineer draws it: standard orthographic views
(front / top / right) plus an isometric, with every feature dimensioned. The LLM emits
primitives + constraint intents + dimension slots with SYMBOLIC parameters; a deterministic
2D solver / geometry kernel computes coordinates and renders the views. The model never
places final coordinates directly (AIDL finding).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .command_ir import CommandIR
from .common import StrictModel, Unit
from .object_plan import ObjectPlan


class ViewType(StrEnum):
    FRONT = "front"
    TOP = "top"
    RIGHT = "right"
    ISO = "iso"


class PrimitiveType(StrEnum):
    LINE = "line"
    CIRCLE = "circle"
    ARC = "arc"
    RECTANGLE = "rectangle"
    POLYGON = "polygon"


class ConstraintIntentType(StrEnum):
    COINCIDENT = "coincident"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    PARALLEL = "parallel"
    PERPENDICULAR = "perpendicular"
    TANGENT = "tangent"
    EQUAL = "equal"
    CONCENTRIC = "concentric"
    SYMMETRIC = "symmetric"


class Primitive(StrictModel):
    """A primitive with SYMBOLIC parameters (e.g. width -> 'length' slot id)."""

    id: str
    type: PrimitiveType
    params: dict[str, str] = Field(
        default_factory=dict, description="Symbolic param -> dimension-slot id or literal"
    )


class ConstraintIntent(StrictModel):
    type: ConstraintIntentType
    refs: list[str] = Field(..., description="Primitive ids (and optional sub-refs) involved")


class DimensionSlot(StrictModel):
    id: str
    label: str
    default_value: float
    unit: Unit = Unit.MM
    min_value: float | None = None
    max_value: float | None = None
    geometry_ref: str = Field(..., description="SVG/primitive ref to highlight on focus")
    group: str = Field(default="General", description="UI grouping (Body, Handle, ...)")


class DrawingView(StrictModel):
    """One orthographic or isometric view of a part."""

    view: ViewType
    svg: str = Field(..., description="Rendered view with data-ref attributes")
    primitives: list[Primitive] = Field(default_factory=list)
    dimension_refs: list[str] = Field(
        default_factory=list, description="Dimension-slot ids annotated in this view"
    )


class PartDrawing(StrictModel):
    """The multi-view, fully-dimensioned drawing of one part (the unit the user verifies)."""

    part_id: str
    part_name: str
    family: str
    views: list[DrawingView]
    dimension_slots: list[DimensionSlot]
    geometry_map: dict[str, str] = Field(
        default_factory=dict, description="dimension id -> geometry ref"
    )
    base_ir: CommandIR | None = Field(
        default=None,
        description="For LLM-generated (novel) parts: the parametric IR whose user parameters ARE "
        "the dimension slots. Carried to codegen, which substitutes the user's values. None for "
        "template families (those regenerate deterministically from the dimensions).",
    )


class PartDrawingRequest(StrictModel):
    object_plan: ObjectPlan
    part_id: str = Field(..., description="Which part of the object to draw")
    user_feedback: str | None = Field(
        default=None, description="e.g. 'make the base wider' — drives regeneration"
    )
