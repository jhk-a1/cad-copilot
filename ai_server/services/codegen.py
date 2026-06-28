"""Code generation service — build ANY part, dimensioned by the user (M2-W5 brought forward).

The accuracy model (per the founder's insight): the LLM is responsible only for the STRUCTURE
(topology) of a part; EVERY dimension is a named user parameter, surfaced in the dimensioning
panel, and the USER sets the numbers. So a novel shape is as accurate as a template — the user
dimensions every edge/face/feature. The LLM never owns the final sizes.

Flow for a novel part:
  1. `generate_parametric(plan, part)` — the LLM emits a fully-parametric IR (every dimension a
     CREATE_USER_PARAMETER). We derive the dimension slots from those parameters and carry the IR
     forward (PartDrawing.base_ir).
  2. The user edits the values in the dimensioning panel.
  3. `generate(..., base_ir=...)` substitutes the user's values into the carried IR, re-validates,
     and returns it — no second model call.

Known families (box/cylinder/l_bracket) skip all of this: exact, free, deterministic templates.
The IR Validator is the hard safety gate throughout; nothing that fails it is ever emitted.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import ValidationError

from ..gateway import LLMGateway, Message, build_gateway
from ..models import (
    CodeGenResponse,
    CodeGenResult,
    CommandIR,
    DimensionSlot,
    ExecutionStep,
    IRCommandType,
)
from . import placeholder
from .command_ir import IRValidator
from .genome import SYSTEM_PROMPT as _GENOME_SYSTEM
from .genome import Genome, parse_genome, plan_genome, synthesize, unmet_requirements
from .genome import user_prompt as _genome_user_prompt
from .geometry import check_geometry

_log = logging.getLogger("cad_copilot")

IR_CODEGEN_PROFILE = "IR_CODEGEN"
_TEMPLATE_FAMILIES = {"box", "cylinder", "l_bracket"}
# features a deterministic template can actually honor; anything else routes to the LLM
_TEMPLATE_FEATURES = {"holes", "filleted_edges", "chamfered_edges"}
_MAX_ATTEMPTS = 3
_VALIDATOR = IRValidator()


def template_suffices(part) -> bool:
    """A template fits only a simple part: a template family with no features beyond the few the
    template honors. A 'cylinder' that is hollow/embossed/tapered is NOT a template cylinder — it
    goes to the LLM so those features are actually built (not silently dropped)."""
    return (part.family in _TEMPLATE_FAMILIES
            and all(f in _TEMPLATE_FEATURES for f in part.features))

_SYSTEM_PROMPT = (
    "You are the geometry stage of CAD-Copilot. Generate a Command IR — a JSON build program that "
    "constructs ONE part as a parametric solid in Autodesk Fusion. Units are millimetres.\n\n"
    "Output ONLY this JSON object:\n"
    '{"version":"2.1.0","units":"mm","commands":[...],"rollback_points":[ids],'
    '"expected_geometry":{"bbox_mm":[dx,dy,dz],"volume_mm3":number,"key_dims":{}}}\n\n'
    'Each command: {"id":int,"type":TYPE,"params":{...},"depends_on":[ids],"produces":ref|null}.\n'
    "Allowed TYPE and required params:\n"
    "  CREATE_USER_PARAMETER {name, value(number), unit:'mm'}            (declare a named dimension)\n"
    "  CREATE_SKETCH {plane:'XY'|'XZ'|'YZ'}  produces 'sketch_<n>'\n"
    "  ADD_LINE {sketch_ref, start:[x,y], end:[x,y]}\n"
    "  ADD_ARC {sketch_ref, start:[x,y], mid:[x,y], end:[x,y]}\n"
    "  ADD_CIRCLE {sketch_ref, center:[x,y], diameter}\n"
    "  ADD_RECTANGLE {sketch_ref, corner1:[x,y], width, height}\n"
    "  CLOSE_SKETCH {sketch_ref}\n"
    "  EXTRUDE {profile_ref, distance, operation:'new_body'|'join'|'cut'|'intersect'} produces 'body_<n>'\n"
    "  REVOLVE {profile_ref, angle, axis:'x'|'y'|'z', operation} produces 'body_<n>'\n"
    "  FILLET {body_ref, radius}   CHAMFER {body_ref, distance}   SHELL {body_ref, thickness}\n"
    "  HOLE {body_ref, positions:[[x,y],...], diameter, through:true}\n\n"
    "RULES (the IR is validated; broken IR is rejected):\n"
    "  - ids start at 0, unique, and every depends_on / *_ref points to an EARLIER command.\n"
    "  - A closed loop of ADD_LINE/ADD_ARC forms a profile: the LAST sketch-geometry command of the "
    "loop sets produces:'profile_<n>'. ADD_RECTANGLE/ADD_CIRCLE each produce their own profile.\n"
    "  - CLOSE_SKETCH the sketch BEFORE the EXTRUDE/REVOLVE that consumes its profile.\n"
    "  - EVERY dimension MUST be a CREATE_USER_PARAMETER with a clear name (prefix it with the part "
    "id) and a sensible default in mm — and referenced BY NAME wherever a size/distance/radius/"
    "diameter is used. Do NOT hard-code dimension numbers in geometry; the USER will set these "
    "parameters. (Sketch point coordinates may be literals, but every length/size is a parameter.)\n"
    "  - ROBUSTNESS (avoid Fusion build errors): PREFER EXTRUDE (then SHELL to hollow) over REVOLVE. "
    "For a hollow round part (mug/cup/pipe/vase): EXTRUDE a circle to a solid, then SHELL it to "
    "hollow — do NOT revolve a thin C/L profile. Use REVOLVE only when the profile is clearly OFFSET "
    "from the axis and NEVER touches or is tangent to it. Every profile must be a simple, closed, "
    "non-self-intersecting loop that does not cross its own extrude/revolve axis.\n"
    "  - Build the real shape — approximate curves with arcs/short segments. Keep numbers to <=2 "
    "decimals. Make expected_geometry roughly match the defaults.\n"
    "Return ONLY the JSON. No prose, no markdown."
)


# --------------------------------------------------------- IR <-> dimension-slot helpers

def _humanize(name: str, part_id: str) -> str:
    s = name[len(part_id) + 1:] if name.startswith(part_id + "_") else name
    return s.replace("_", " ").strip().capitalize() or name


def dimension_slots_from_ir(ir: CommandIR, part_id: str) -> list[DimensionSlot]:
    """Turn the IR's user parameters INTO the dimension slots the user edits (the founder's model:
    every parameter of the generated structure is dimensionable)."""
    slots: list[DimensionSlot] = []
    for c in ir.commands:
        if c.type is IRCommandType.CREATE_USER_PARAMETER:
            name, value = c.params.get("name"), c.params.get("value")
            if isinstance(name, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
                slots.append(DimensionSlot(
                    id=name, label=_humanize(name, part_id), default_value=float(value),
                    min_value=0.01, max_value=100000, geometry_ref="ref_" + name, group="Dimensions"))
    return slots


def apply_dimensions(ir: CommandIR, dimensions: dict[str, float]) -> CommandIR:
    """Substitute the user's values into the IR's matching user parameters (exact, no model call)."""
    out = []
    for c in ir.commands:
        if c.type is IRCommandType.CREATE_USER_PARAMETER and c.params.get("name") in dimensions:
            params = dict(c.params)
            params["value"] = float(dimensions[c.params["name"]])
            out.append(c.model_copy(update={"params": params}))
        else:
            out.append(c)
    return ir.model_copy(update={"commands": out})


class CodeGenService:
    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    def _provider(self) -> str:
        return self._gateway.profiles.get(IR_CODEGEN_PROFILE, {}).get("provider", "mock")

    def has_live_model(self) -> bool:
        return self._provider() != "mock"

    # --- used by the sketch stage: produce the parametric structure + its dimension slots --------
    async def generate_parametric(self, plan, part) -> tuple[CommandIR | None, list[DimensionSlot]]:
        # Design-Genome path (ADR-007): deterministic planner first (free), LLM-genome if live.
        genome = await self._genome_for(plan, part)
        if genome is not None:
            result = synthesize(genome)
            if result.ok and result.ir is not None:
                return result.ir, dimension_slots_from_ir(result.ir, part.id)
        # legacy raw-IR LLM fallback (truly novel families the genome can't express yet)
        if not self.has_live_model():
            return None, []
        ir = await self._generate_ir(plan, part, {})
        if ir is None:
            return None, []
        return ir, dimension_slots_from_ir(ir, part.id)

    # --- used by the codegen stage ---------------------------------------------------------------
    async def generate(self, plan, part_id, dimensions, base_ir=None) -> CodeGenResponse:
        resp = await self._generate_impl(plan, part_id, dimensions, base_ir)
        # ATTACHMENT (ADR-008): seat the part on its host's surface via a solved mate transform,
        # instead of a guessed coordinate. Attached to any successful result, regardless of how its
        # geometry was built.
        if resp.result is not None:
            part = placeholder._find_part(plan, part_id)
            placement = _solve_attachment(plan, part) if part is not None else None
            if placement is not None:
                resp.result.placement = placement
            # closed-loop perception (ADR-009): measure whether the part actually seats on its host
            cert = _spatial_certificate(plan, part, placement) if part is not None else None
            if cert is not None:
                resp.result.warnings.append(cert)
            # makeability gate (ADR-010 Pillar D): flag a part the chosen process cannot make
            dfm = _makeability_certificate(part) if part is not None else None
            if dfm is not None:
                resp.result.warnings.append(dfm)
            # proof-of-fitness certificate (ADR-011): does the part PROVABLY meet its spec? Attach a
            # self-contained, independently re-checkable certificate (design-as-proof).
            cert = _fitness_certificate(plan, part, dimensions, placement) if part is not None else None
            if cert is not None:
                resp.result.certificate = cert
                resp.result.warnings.append("certificate: " + str(cert.get("summary", "")))
        return resp

    async def _generate_impl(self, plan, part_id, dimensions, base_ir=None) -> CodeGenResponse:
        part = placeholder._find_part(plan, part_id)
        if part is None:
            return placeholder._refuse(f"No part '{part_id}' in this object plan.", part_id=part_id)

        if template_suffices(part):
            return placeholder.generate_part_code(plan, part_id, dimensions)

        # Design-Genome path: re-derive the (deterministic) genome and SOLVE it with the user's
        # dimensions — this recomputes expected_geometry so render-check is a real verification, and
        # costs no LLM call. The Kernel-CEGIS loop returns verified IR or an honest refusal.
        genome = plan_genome(part)
        if genome is not None:
            result = synthesize(genome, _holes_from_dimensions(part.id, dimensions))
            if result.ok and result.ir is not None:
                unmet = unmet_requirements(part, genome)
                if unmet:  # purpose must be met, not just valid geometry (ADR-007 functional gate)
                    return placeholder._refuse(
                        f"I could build '{part.name}' but it would not serve its purpose: "
                        + "; ".join(unmet) + ". Refusing rather than ship a part that misses the need.",
                        family=part.family)
                return _finalize_genome(part.id, result)

        # novel / feature-rich part: substitute the user's values into the IR carried from sketch time
        if base_ir is not None:
            final = apply_dimensions(_as_ir(base_ir), dimensions)
            report = _VALIDATOR.validate(final)
            if report.valid:
                return _finalize(part.id, final)
            _log.warning("carried base_ir invalid after dimensioning: %s", report.summary())

        if not self.has_live_model():
            return placeholder._refuse(
                f"Building a '{part.family}' part needs the live model (the server is offline/mock).",
                family=part.family)

        ir = await self._generate_ir(plan, part, dimensions)
        if ir is None:
            return placeholder._refuse(
                f"I couldn't produce a safe build for '{part.name}' after {_MAX_ATTEMPTS} attempts.",
                family=part.family)
        return _finalize(part.id, ir)

    async def _genome_for(self, plan, part) -> Genome | None:
        """A genome for this part: the deterministic planner (free), else the live LLM-genome path."""
        genome = plan_genome(part)
        if genome is not None:
            return genome
        if self.has_live_model():
            return await self._genome_llm(plan, part)
        return None

    async def _genome_llm(self, plan, part) -> Genome | None:
        messages = [
            Message("system", _GENOME_SYSTEM),
            Message("user", _genome_user_prompt(plan.object_name, plan.summary, part)),
        ]
        try:
            result = await self._gateway.generate_structured(
                messages, Genome.model_json_schema(), profile=IR_CODEGEN_PROFILE, n=1)
        except Exception:
            _log.exception("genome gateway call failed")
            return None
        if not result.candidates:
            return None
        return parse_genome(result.candidates[0], part.id)

    async def _generate_ir(self, plan, part, dimensions) -> CommandIR | None:
        """The validator-feedback retry loop. Returns a structurally-valid IR or None."""
        messages = [
            Message("system", _SYSTEM_PROMPT),
            Message("user", _user_prompt(plan.object_name, plan.summary, part, dimensions)),
        ]
        schema = CommandIR.model_json_schema()
        for _ in range(_MAX_ATTEMPTS):
            try:
                result = await self._gateway.generate_structured(
                    messages, schema, profile=IR_CODEGEN_PROFILE, n=1)
            except Exception:
                _log.exception("codegen gateway call failed")
                return None
            if not result.candidates:
                messages.append(Message("user", "No valid JSON was produced. Return ONLY the JSON IR."))
                continue
            try:
                ir = CommandIR.model_validate(result.candidates[0])
            except ValidationError as exc:
                messages.append(Message("user",
                    f"The JSON did not fit the schema: {str(exc)[:300]}. Return ONLY corrected JSON."))
                continue
            report = _VALIDATOR.validate(ir)
            if report.valid:
                return ir
            messages.append(Message("user",
                f"The IR failed validation: {report.summary()}. Fix ALL of these and return ONLY "
                "corrected JSON."))
        return None


def _as_ir(base_ir) -> CommandIR:
    return base_ir if isinstance(base_ir, CommandIR) else CommandIR.model_validate(base_ir)


def _user_prompt(object_name: str, summary: str, part, dimensions: dict[str, float]) -> str:
    dims = ", ".join(f"{k}={v}" for k, v in dimensions.items()) or "(choose sensible defaults in mm)"
    feats = ", ".join(part.features) or "none"
    return (
        f"Object: {object_name} — {summary}\n"
        f"Build this PART: id={part.id}, name={part.name!r}, family={part.family!r}, "
        f"object_type={part.object_type!r}, features=[{feats}].\n"
        f"User dimensions (mm): {dims}.\n"
        f"Prefix every CREATE_USER_PARAMETER name with '{part.id}_'."
    )


def _finalize(part_id: str, ir: CommandIR) -> CodeGenResponse:
    """Build the response for an IR that PASSED the validator. Render-check is ADVISORY for LLM IR."""
    check = check_geometry(ir)
    if not check.realized:
        warnings = ["novel geometry - dimension every parameter and verify the 3D result"]
    elif check.ok:
        warnings = [f"render-check ok: {check.message}"]
    else:
        warnings = [f"render-check advisory (LLM geometry estimate): {check.message}"]
    return CodeGenResponse(result=CodeGenResult(
        part_id=part_id, command_ir=ir,
        code=f"# Parametric IR for part '{part_id}' (not executed). Fusion units = cm.\n",
        operations=["sketch", "extrude"], warnings=warnings,
        execution_order=[
            ExecutionStep(step=1, operation="create_sketch", entity_ref="sketch_0"),
            ExecutionStep(step=2, operation="add_profile", entity_ref="profile_0"),
            ExecutionStep(step=3, operation="extrude", entity_ref="body_0"),
        ],
    ))


# primary feature types that attach to a body and should DEFAULT to a mate if the plan forgot one
_ATTACHING_PRIMARIES = {"loop_handle"}


def _main_body(plan, part):
    """The host a dependent part attaches to: a sibling at the origin, else the first sibling."""
    others = [p for p in plan.parts if p.id != part.id]
    for p in others:
        pos = getattr(p, "position", None)
        if not pos or not any(pos):  # a part at [0,0,0] is the body
            return p
    return others[0] if others else None


def _world_offset(plan, part, _seen=None) -> tuple[float, float, float]:
    """Where `part`'s LOCAL origin actually sits in WORLD space, by composing the attachment chain.

    THE multi-part-assembly fix: every mate is solved against its host AT THE ORIGIN (host-local
    frames). That is correct for a part attached straight to the body (the body is at [0,0,0] — a mug
    handle works). But a host that is ITSELF attached has moved, so a CHAIN of attachments
    (engine: crankcase <- cylinder barrel <- head; box-cutter: handle <- slider) floats unless we
    accumulate each host's world position. Walk to the root (a position-placed part), summing each
    host's connector origin. Translation-only — exact for the common coaxial / stacked case (the
    bases sit centred on the host's top/side face); host-local rotations are left untouched.
    """
    _seen = set() if _seen is None else _seen
    if part is None or part.id in _seen:
        return (0.0, 0.0, 0.0)
    _seen.add(part.id)
    spec = _attach_spec(plan, part)
    if not spec:  # the root body: it sits at its own position
        pos = getattr(part, "position", None) or [0.0, 0.0, 0.0]
        return (float(pos[0]), float(pos[1]), float(pos[2])) if len(pos) >= 3 else (0.0, 0.0, 0.0)
    host = placeholder._find_part(plan, str(spec["to"]))
    host_solid = _host_solid(plan, spec)
    if host is None or host_solid is None:
        return (0.0, 0.0, 0.0)
    from .genome.frames import host_connector
    try:
        target = host_connector(host_solid, str(spec.get("where", "side")),
                                float(spec.get("height_frac", 0.5) or 0.5),
                                float(spec.get("angle", 0.0) or 0.0))
    except Exception:  # noqa: BLE001 - composition must never break codegen
        return (0.0, 0.0, 0.0)
    ho = _world_offset(plan, host, _seen)
    return (target.origin[0] + ho[0], target.origin[1] + ho[1], target.origin[2] + ho[2])


def _attach_spec(plan, part) -> dict | None:
    """The attachment spec for a part: the plan's explicit one, or a DEFAULT for handle-like parts
    so a handle still seats on the body even when the planner emitted no attachment (the live bug
    where the handle dropped to the base)."""
    spec = getattr(part, "attachment", None)
    spec = spec.model_dump() if hasattr(spec, "model_dump") else spec
    if isinstance(spec, dict) and spec.get("to"):
        return spec
    pg = plan_genome(part)
    if pg is not None and pg.primary is not None and pg.primary.type.value in _ATTACHING_PRIMARIES:
        host = _main_body(plan, part)
        if host is not None:
            return {"to": host.id, "where": "side", "height_frac": 0.5}
    return None


def _host_solid(plan, spec):
    host = placeholder._find_part(plan, str(spec["to"])) if spec else None
    if host is None:
        return None
    hg = plan_genome(host)
    if hg is None:
        return None
    from .genome.library import build_ir
    from .genome.solver import solve as solve_holes
    hs, _ = solve_holes(hg, {})
    _, solid = build_ir(hs)
    return solid


def _solve_attachment(plan, part) -> dict | None:
    """Solve a part's mate transform onto its host's surface (ADR-008), or None to use position."""
    spec = _attach_spec(plan, part)
    host_solid = _host_solid(plan, spec)
    part_g = plan_genome(part)
    if host_solid is None or part_g is None or part_g.primary is None:
        return None
    from .genome.frames import solve_placement
    from .genome.library import resolved
    try:
        placement = solve_placement(host_solid, part_g.primary.type.value, resolved(part_g.primary), spec)
    except Exception:  # noqa: BLE001 - never break codegen over placement; fall back to position
        return None
    out = placement.as_dict()
    # ASSEMBLY COMPOSITION: the mate frames above are host-LOCAL (host at origin). If the host is
    # itself attached (a chain), carry its world position so the part stacks where the host ACTUALLY
    # sits instead of floating back to the origin. Host-at-origin (direct-to-body) keeps offset 0.
    host = placeholder._find_part(plan, str(spec["to"])) if spec else None
    if host is not None:
        ho = _world_offset(plan, host)
        if any(abs(v) > 1e-9 for v in ho):
            out["world_offset"] = [round(v, 4) for v in ho]
    return out


def _spatial_certificate(plan, part, placement) -> str | None:
    """Perceive whether the part actually seats on its host (ADR-009 closed-loop comparator) and
    return a human-readable certificate for the build result — so the user is not flying blind."""
    spec = _attach_spec(plan, part)
    host_solid = _host_solid(plan, spec) if spec else None
    if host_solid is None:
        return None
    from .genome.verify import attach_seat_residual
    r = attach_seat_residual(host_solid, placement, getattr(part, "position", None), part.id)
    return ("spatial OK - " + r.message) if r.ok else ("spatial WARNING - " + r.message)


def _makeability_certificate(part) -> str | None:
    """Makeability gate (ADR-010 Pillar D): does the chosen process allow this part's wall?

    Surfaces only when there's something to say — a hollow vessel whose wall is too thin (or a
    process warning). Returns None for a clean, makeable part (no noise) and for parts where no wall
    can be derived. Advisory (WARNING level), never blocks; the process defaults to FDM.
    """
    try:
        genome = plan_genome(part)
        if genome is None or not genome.features:
            return None
        from .genome.dfm import manufacturability_certificate
        from .genome.library import resolved

        wall = resolved(genome.features[0]).get("wall")
        if wall is None:
            return None
        process = getattr(part, "process", None) or "fdm"
        cert = manufacturability_certificate(process=process, wall_mm=float(wall))
        if cert.ok and not cert.warnings:
            return None
        return cert.summary()
    except Exception:  # noqa: BLE001 - the makeability gate must never break codegen
        return None


def _fitness_certificate(plan, part, dimensions, placement) -> dict | None:
    """Proof-of-fitness certificate (ADR-011): derive the part's Specification, gather evidence from
    the realized kernel solid, and return a self-contained, re-checkable certificate. General over
    any part (the requirements are composed from functional intent + geometry + process). Never
    breaks codegen — returns None on any issue."""
    try:
        genome = plan_genome(part)
        if genome is None or not genome.features:
            return None
        from .genome.certificate import certify
        from .genome.library import build_ir
        from .genome.solver import solve as solve_holes

        solved, _ = solve_holes(genome, _holes_from_dimensions(part.id, dimensions))
        _, solid = build_ir(solved)
        # spatial evidence: measure how far an attached part sits from its host surface (gap ~ 0)
        seat_gap = None
        spec = _attach_spec(plan, part)
        host_solid = _host_solid(plan, spec) if spec else None
        if host_solid is not None:
            from .genome.verify import attach_seat_residual

            r = attach_seat_residual(host_solid, placement, getattr(part, "position", None), part.id)
            seat_gap = r.value_mm
        process = getattr(part, "process", None) or "fdm"
        return certify(part, solved, solid, process=process, seat_gap_mm=seat_gap).to_dict()
    except Exception:  # noqa: BLE001 - the certificate must never break codegen
        return None


def _holes_from_dimensions(part_id: str, dimensions: dict[str, float] | None) -> dict[str, float]:
    """User dimension ids are the IR parameter names (f'{part_id}_{hole}'); strip the prefix back to
    the genome hole names the solver expects."""
    prefix = part_id + "_"
    out: dict[str, float] = {}
    for k, v in (dimensions or {}).items():
        hole = k[len(prefix):] if k.startswith(prefix) else k
        try:
            out[hole] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _finalize_genome(part_id: str, result) -> CodeGenResponse:
    """Build the response for a Design-Genome IR that the Kernel-CEGIS loop verified (ADR-007)."""
    ir = result.ir
    check = result.render_check
    warnings: list[str] = []
    if check is None or not check.realized:
        warnings.append("novel geometry — dimension every parameter and verify the 3D result")
    elif check.ok:
        warnings.append(f"render-check ok (geometry verified): {check.message}")
    else:
        warnings.append(f"render-check advisory: {check.message}")
    if result.counterexamples:
        warnings.append("design-rule auto-repair: " + "; ".join(result.counterexamples[:6]))
    return CodeGenResponse(result=CodeGenResult(
        part_id=part_id, command_ir=ir,
        code=f"# Design-Genome IR for part '{part_id}' (ADR-007, correct-by-construction). "
             "Fusion units = cm.\n",
        operations=["genome", "sketch", "extrude"], warnings=warnings,
        execution_order=[
            ExecutionStep(step=1, operation="create_sketch", entity_ref="sketch_0"),
            ExecutionStep(step=2, operation="add_profile", entity_ref="profile_0"),
            ExecutionStep(step=3, operation="extrude", entity_ref="body_0"),
        ],
    ))


@lru_cache
def get_codegen_service() -> CodeGenService:
    return CodeGenService(build_gateway())
