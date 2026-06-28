"""Kernel-CEGIS — the convergent, feasibility-gated compile loop (ADR-007).

This is the engine that replaces "retry until lucky" with "refine until proven". Given a genome:

  1. CLOSURE gate — `validate_genome` (the grammar): an ill-formed tree can't proceed.
  2. SOLVE + DRC gate — fill holes and clamp them onto the feasible manifold (`solver.solve`);
     every clamp is a *counterexample* recorded in the result.
  3. COMPILE — `library.build_ir` turns the solved genome into Command IR + the exact kernel solid.
  4. VERIFY gate — the IR Validator (well-formed build program) + render-and-check (the realized
     geometry matches the genome's intended solid). A structural failure is a counterexample: the
     loop drops the offending trailing modifier and retries (CEGIS backtrack); if the body itself
     can't pass, it refuses honestly rather than emit wrong geometry (ADR-002).

For correct-by-construction fragments steps 3–4 pass first time; the value of the loop is that it is
*guaranteed* to return either a verified IR or an honest refusal — never a vague solid.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...models import CommandIR
from ..command_ir import IRValidator
from ..geometry import GeometryCheck, check_geometry
from .grammar import FEATURE_SPECS, Genome, validate_genome
from .library import build_ir
from .solver import solve

_VALIDATOR = IRValidator()
_MAX_ITERS = 4


@dataclass
class CegisResult:
    ok: bool
    ir: CommandIR | None = None
    counterexamples: list[str] = field(default_factory=list)  # what the loop repaired/learned
    refusal: str | None = None
    render_check: GeometryCheck | None = None


def synthesize(genome: Genome, holes: dict[str, float] | None = None) -> CegisResult:
    """Run the loop. `holes` are user dimension values keyed by hole name (prefix stripped)."""
    notes: list[str] = []

    closure = validate_genome(genome)
    if closure:
        return CegisResult(False, refusal="genome is not well-formed: " + "; ".join(closure),
                           counterexamples=notes)

    work = genome
    for _ in range(_MAX_ITERS):
        solved, repairs = solve(work, holes or {})
        notes.extend(repairs)

        ir, _solid = build_ir(solved)
        report = _VALIDATOR.validate(ir)
        if report.valid:
            check = check_geometry(ir)
            if check.realized and not check.ok:
                # the kernel disagrees with the genome's own solid — a real counterexample.
                note = f"render-check mismatch: {check.message}"
                notes.append(note)
                dropped = _drop_last_modifier(work)
                if dropped is not None:
                    work = dropped
                    continue
                return CegisResult(False, refusal=note, counterexamples=notes, render_check=check)
            return CegisResult(True, ir=ir, counterexamples=notes, render_check=check)

        # structural counterexample: drop the trailing modifier and retry; refuse if none left.
        notes.append(f"IR rejected: {report.summary()}")
        dropped = _drop_last_modifier(work)
        if dropped is None:
            return CegisResult(False, refusal="could not synthesize a valid build: " + report.summary(),
                               counterexamples=notes)
        work = dropped

    return CegisResult(False, refusal="did not converge within the iteration budget",
                       counterexamples=notes)


def _drop_last_modifier(genome: Genome) -> Genome | None:
    """CEGIS backtrack: remove the last (trailing) modifier feature. None if only the primary is left."""
    for i in range(len(genome.features) - 1, -1, -1):
        if not FEATURE_SPECS[genome.features[i].type].primary:
            feats = genome.features[:i] + genome.features[i + 1:]
            return genome.model_copy(update={"features": feats})
    return None
