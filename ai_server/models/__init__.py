"""API Contract v2.1.0 — the source of truth for all CAD-Copilot communication.

The Fusion add-in, the FastAPI server, and the eval harness all build against these
schemas. Changes require a contract version bump (semver). v2.1.0 (ADR-004): input is an
OBJECT decomposed into PARTS; each part verified via a multi-view, fully-dimensioned drawing.
"""

from .codegen import (
    CodeGenRequest,
    CodeGenResponse,
    CodeGenResult,
    ExecutionStep,
)
from .command_ir import (
    IR_VERSION,
    CommandIR,
    ExpectedGeometry,
    IRCommand,
    IRCommandType,
)
from .common import (
    CONTRACT_VERSION,
    ComplexityClass,
    Refusal,
    RefusalReason,
    StrictModel,
    Unit,
)
from .errors import (
    ERROR_REGISTRY,
    ErrorDetail,
    ErrorResponse,
    ErrorType,
    make_error,
)
from .object_plan import (
    Clarification,
    ObjectPlan,
    ObjectRequest,
    PartPlan,
    PlanContext,
    RequirementSpec,
)
from .sketch import (
    ConstraintIntent,
    ConstraintIntentType,
    DimensionSlot,
    DrawingView,
    PartDrawing,
    PartDrawingRequest,
    Primitive,
    PrimitiveType,
    ViewType,
)

__all__ = [
    "CONTRACT_VERSION",
    "IR_VERSION",
    # common
    "ComplexityClass",
    "Refusal",
    "RefusalReason",
    "StrictModel",
    "Unit",
    # object plan (Stage 1)
    "Clarification",
    "RequirementSpec",
    "ObjectPlan",
    "ObjectRequest",
    "PartPlan",
    "PlanContext",
    # part drawing (Stage 2)
    "ConstraintIntent",
    "ConstraintIntentType",
    "DimensionSlot",
    "DrawingView",
    "PartDrawing",
    "PartDrawingRequest",
    "Primitive",
    "PrimitiveType",
    "ViewType",
    # command IR (Stage 4)
    "CommandIR",
    "ExpectedGeometry",
    "IRCommand",
    "IRCommandType",
    # codegen (Stage 4)
    "CodeGenRequest",
    "CodeGenResponse",
    "CodeGenResult",
    "ExecutionStep",
    # errors
    "ERROR_REGISTRY",
    "ErrorDetail",
    "ErrorResponse",
    "ErrorType",
    "make_error",
]
