"""Object planning endpoint (Stage 1). Decomposes an object into parts (M1-W3-BE-05).

Runs on the LLM gateway when a real provider is configured; falls back to deterministic
templates under the default mock provider so the pipeline works offline.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..models import ObjectPlan, ObjectRequest
from ..services.intent import get_intent_service

router = APIRouter(prefix="/api/object", tags=["Object Plan"])


@router.post("/plan", response_model=ObjectPlan)
async def plan_object(request: ObjectRequest) -> ObjectPlan:
    return await get_intent_service().plan(request.text)
