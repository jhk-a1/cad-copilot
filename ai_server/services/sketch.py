"""Sketch / dimensioning stage (Stage 2).

Known families render exact, proportional engineering drawings (deterministic, in `placeholder`).
A novel (LLM-generated) part instead gets its PARAMETRIC structure from codegen: every dimension of
that structure becomes a dimension slot the user can set (the founder's accuracy model — the LLM
owns topology, the user owns every number). The generated IR is carried in `PartDrawing.base_ir`
so the codegen stage just substitutes the user's values, no second model call.
"""

from __future__ import annotations

from functools import lru_cache

from ..models import DrawingView, PartDrawing, Refusal, RefusalReason, ViewType
from . import drawing, placeholder
from .codegen import CodeGenService, get_codegen_service, template_suffices


class SketchService:
    def __init__(self, codegen: CodeGenService) -> None:
        self._codegen = codegen

    async def generate_drawing(self, plan, part_id: str) -> PartDrawing | Refusal:
        part = placeholder._find_part(plan, part_id)
        if part is None:
            return Refusal(reason_code=RefusalReason.OUT_OF_SCOPE,
                           message=f"No part '{part_id}' in this object plan.",
                           diagnostics={"part_id": part_id})

        if template_suffices(part):
            return placeholder.generate_part_drawing(plan, part_id)

        # Novel part: ask codegen for the parametric structure + its dimension slots.
        base_ir, slots = await self._codegen.generate_parametric(plan, part)
        if base_ir is None or not slots:
            # offline, or generation failed -> generic bounding-box drawing + generic schedule
            return placeholder.generate_part_drawing(plan, part_id)

        svgs = drawing.box_views({}, set(part.features))  # bounding-box preview; true shape is base_ir
        views = [
            DrawingView(view=ViewType.FRONT, svg=svgs["front"], dimension_refs=[s.id for s in slots]),
            DrawingView(view=ViewType.TOP, svg=svgs["top"]),
            DrawingView(view=ViewType.RIGHT, svg=svgs["right"]),
            DrawingView(view=ViewType.ISO, svg=svgs["iso"]),
        ]
        return PartDrawing(
            part_id=part.id, part_name=part.name, family=part.family, views=views,
            dimension_slots=slots, geometry_map={s.id: s.geometry_ref for s in slots},
            base_ir=base_ir,
        )


@lru_cache
def get_sketch_service() -> SketchService:
    return SketchService(get_codegen_service())
