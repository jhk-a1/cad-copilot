"""Typed error schema + error-code registry (Contract v2.0.0).

Errors (HTTP >= 400) are distinct from refusals (HTTP 200). A refusal is the product
working correctly (declining out-of-scope work); an error is something going wrong.

Error code registry:
  E1xxx  Validation errors      (E1001 missing field, E1002 invalid type, E1003 out of range)
  E2xxx  Constraint conflicts   (E2001 geometry conflict, E2002 dimension conflict)
  E3xxx  Execution failures      (E3001 sketch failed, E3002 extrude failed, E3003 rollback)
  E4xxx  Timeout errors          (E4001 request timeout, E4002 operation timeout)
  E5xxx  Internal errors         (E5001 service unavailable, E5002 unexpected state)
  E9xxx  Rate limiting           (E9001 too many requests)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .common import StrictModel


class ErrorType(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONSTRAINT_CONFLICT = "CONSTRAINT_CONFLICT"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"


class ErrorDetail(StrictModel):
    type: ErrorType
    message: str
    code: str = Field(..., pattern=r"^E[0-9]{4}$")
    details: dict[str, str] = Field(default_factory=dict)
    recoverable: bool = False
    retry_after: int | None = Field(default=None, description="Seconds to wait (rate limits)")


class ErrorResponse(StrictModel):
    error: ErrorDetail


# Convenience registry — machine code -> (type, default message, recoverable)
ERROR_REGISTRY: dict[str, tuple[ErrorType, str, bool]] = {
    "E1001": (ErrorType.VALIDATION_ERROR, "Missing required field", False),
    "E1002": (ErrorType.VALIDATION_ERROR, "Invalid field type", False),
    "E1003": (ErrorType.VALIDATION_ERROR, "Value out of range", False),
    "E2001": (ErrorType.CONSTRAINT_CONFLICT, "Geometry constraint conflict", False),
    "E2002": (ErrorType.CONSTRAINT_CONFLICT, "Dimension conflict", False),
    "E3001": (ErrorType.EXECUTION_FAILURE, "Sketch creation failed", True),
    "E3002": (ErrorType.EXECUTION_FAILURE, "Extrude failed", True),
    "E3003": (ErrorType.EXECUTION_FAILURE, "Rollback triggered", True),
    "E4001": (ErrorType.TIMEOUT_ERROR, "Request timed out", True),
    "E4002": (ErrorType.TIMEOUT_ERROR, "Operation timed out", True),
    "E5001": (ErrorType.INTERNAL_ERROR, "Service unavailable", True),
    "E5002": (ErrorType.INTERNAL_ERROR, "Unexpected state", False),
    "E9001": (ErrorType.RATE_LIMIT_ERROR, "Too many requests", True),
}


def make_error(code: str, message: str | None = None, **details: str) -> ErrorResponse:
    etype, default_msg, recoverable = ERROR_REGISTRY[code]
    return ErrorResponse(
        error=ErrorDetail(
            type=etype,
            message=message or default_msg,
            code=code,
            details=details,
            recoverable=recoverable,
        )
    )
