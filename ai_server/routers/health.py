"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..gateway.registry import build_gateway
from ..models import CONTRACT_VERSION, StrictModel

router = APIRouter(prefix="/health", tags=["Health"])


class HealthResponse(StrictModel):
    status: str
    version: str
    contract_version: str
    services: dict[str, str]


def _intent_backing() -> str:
    """Report what actually backs the INTENT stage (live model vs offline mock)."""
    try:
        prof = build_gateway().profiles.get("INTENT", {})
    except Exception:  # noqa: BLE001 - health must never fail on config issues
        return "unknown"
    if prof.get("provider", "mock") == "mock":
        return "mock (offline)"
    return f"{prof.get('provider')}:{prof.get('model')}"


@router.get("/", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        contract_version=CONTRACT_VERSION,
        services={
            "intent_parser": _intent_backing(),  # live model when configured, else mock
            "sketch_generator": "deterministic",
            "code_generator": "deterministic",
        },
    )


@router.get("/ready")
async def readiness_check() -> dict[str, bool]:
    return {"ready": True}
