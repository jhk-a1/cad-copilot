"""Per-part drawing endpoint (Stage 2). Returns a multi-view PartDrawing or a Refusal."""

from __future__ import annotations

from fastapi import APIRouter

from ..models import PartDrawing, PartDrawingRequest, Refusal
from ..services.sketch import get_sketch_service

router = APIRouter(prefix="/api/sketch", tags=["Sketch"])


@router.post("/generate", response_model=PartDrawing | Refusal)
async def generate_drawing(request: PartDrawingRequest) -> PartDrawing | Refusal:
    return await get_sketch_service().generate_drawing(request.object_plan, request.part_id)
