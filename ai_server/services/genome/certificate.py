"""Proof-of-fitness certificate (ADR-011, breakthrough Pillar P6) - design-as-proof.

Every text-to-CAD system hands you geometry and asks you to trust it. This module makes the
deliverable a **certificate**: for each requirement in the Specification, an obligation verdict
(satisfied / violated / unverifiable) with the measured value and margin, plus an overall fitness
result. Because the certificate is self-contained - it carries the requirements AND the evidence it
was checked against - a third party can **re-verify it in seconds without trusting the generator**
(`recheck`). That is the proof-carrying-code property (Necula 1997; CompCert), applied to CAD: the
customer re-runs a tiny deterministic check rather than re-doing the design.

Pure and offline. The checker and the re-checker share `spec.evaluate`, so a certificate's claims
are reproducible; `recheck` recomputes every verdict from (requirements + evidence) and flags any
claim that doesn't follow - catching tampering or generator error.
"""

from __future__ import annotations

from dataclasses import dataclass

from .spec import Specification, evaluate

CERT_VERSION = "1.0"


@dataclass(frozen=True)
class Obligation:
    """A single checked requirement: its claimed verdict, the value measured, and the margin."""

    requirement_id: str
    kind: str
    description: str
    status: str            # "satisfied" | "violated" | "unverifiable"
    measured: object
    target: object
    op: str
    margin: float | None
    severity: str
    tier: str

    def to_dict(self) -> dict:
        return {"requirement_id": self.requirement_id, "kind": self.kind,
                "description": self.description, "status": self.status,
                "measured": self.measured, "target": self.target, "op": self.op,
                "margin": self.margin, "severity": self.severity, "tier": self.tier}


@dataclass(frozen=True)
class Certificate:
    """A self-contained proof of fitness: the spec, the evidence witness, and the verdicts."""

    part_id: str
    obligations: tuple[Obligation, ...]
    spec: Specification
    evidence: dict
    version: str = CERT_VERSION

    @property
    def violations(self) -> tuple[Obligation, ...]:
        return tuple(o for o in self.obligations if o.severity == "must" and o.status == "violated")

    @property
    def unverifiable(self) -> tuple[Obligation, ...]:
        return tuple(o for o in self.obligations
                     if o.severity == "must" and o.status == "unverifiable")

    @property
    def advisories(self) -> tuple[Obligation, ...]:
        """Soft ('should') obligations that are violated - usually frame-INFERRED expectations the
        part doesn't meet (e.g. a handle whose grip is a little tight). Informative, not gating."""
        return tuple(o for o in self.obligations if o.severity == "should" and o.status == "violated")

    @property
    def ok(self) -> bool:
        """Fit iff every MUST obligation is satisfied (no violations, nothing unverifiable)."""
        return not self.violations and not self.unverifiable

    def summary(self) -> str:
        musts = [o for o in self.obligations if o.severity == "must"]
        passed = sum(1 for o in musts if o.status == "satisfied")
        inferred = sum(1 for a in self.spec.assumptions if a.source == "inferred")
        ctx = f" [{self.spec.frame}]" if self.spec.frame and self.spec.frame != "object" else ""
        advice = ""
        if self.advisories:
            advice = "; advice: " + "; ".join(o.description for o in self.advisories)
        if self.ok:
            base = f"certified fit - {passed}/{len(musts)} obligations met{ctx}"
            if inferred:
                base += f"; proved {inferred} implied requirement(s)"
            return base + advice
        bits = []
        for o in self.violations:
            m = f" (by {abs(o.margin):.2f})" if isinstance(o.margin, (int, float)) else ""
            bits.append(f"{o.description}{m}")
        for o in self.unverifiable:
            bits.append(f"{o.description} [unverifiable]")
        return f"NOT certified{ctx} - {passed}/{len(musts)} met; fails: " + "; ".join(bits) + advice

    def to_dict(self) -> dict:
        return {"version": self.version, "part_id": self.part_id, "ok": self.ok,
                "summary": self.summary(), "spec": self.spec.to_dict(), "evidence": self.evidence,
                "obligations": [o.to_dict() for o in self.obligations]}


def check(spec: Specification, evidence: dict) -> Certificate:
    """Evaluate every requirement against the evidence and assemble the certificate."""
    obligations: list[Obligation] = []
    for r in spec.requirements:
        status, measured, margin = evaluate(r.metric, r.op, r.target, evidence)
        obligations.append(Obligation(
            requirement_id=r.id, kind=r.kind, description=r.description, status=status,
            measured=measured, target=r.target, op=r.op, margin=margin,
            severity=r.severity, tier=r.tier))
    return Certificate(part_id=spec.part_id, obligations=tuple(obligations),
                       spec=spec, evidence=evidence)


# --------------------------------------------------------------- the proof-carrying re-check


@dataclass(frozen=True)
class RecheckResult:
    """The verdict of independently re-verifying a certificate."""

    consistent: bool
    checked: int
    discrepancies: tuple[str, ...]

    def summary(self) -> str:
        if self.consistent:
            return f"certificate re-verified independently - {self.checked} obligations consistent"
        return ("certificate REJECTED - " + str(len(self.discrepancies))
                + " claim(s) do not follow from the evidence: " + "; ".join(self.discrepancies))


def recheck(certificate: dict) -> RecheckResult:
    """Independently re-verify a serialized certificate WITHOUT trusting its stated verdicts.

    The proof-carrying property: given only the certificate JSON (its requirements + evidence +
    claimed obligations), recompute each verdict from scratch and confirm the claims follow. Any
    mismatch - a flipped status, an `ok` that doesn't hold, an obligation for a missing requirement -
    is reported. This is what lets a customer trust the result in seconds without trusting us.
    """
    requirements = {r["id"]: r for r in certificate.get("spec", {}).get("requirements", [])}
    ev = certificate.get("evidence", {})
    claimed = certificate.get("obligations", [])
    discrepancies: list[str] = []
    checked = 0

    seen = set()
    for ob in claimed:
        rid = ob.get("requirement_id")
        seen.add(rid)
        req = requirements.get(rid)
        if req is None:
            discrepancies.append(f"{rid}: obligation has no matching requirement in the spec")
            continue
        status, _measured, _margin = evaluate(req["metric"], req["op"], req["target"], ev)
        checked += 1
        if status != ob.get("status"):
            discrepancies.append(
                f"{rid}: claims {ob.get('status')!r} but evidence gives {status!r}")
    # every requirement must have a corresponding obligation (no silently dropped checks)
    for rid in requirements:
        if rid not in seen:
            discrepancies.append(f"{rid}: requirement was not certified (no obligation)")

    # the overall ok claim must follow from the recomputed must-verdicts
    recomputed_ok = True
    for req in requirements.values():
        if req.get("severity", "must") != "must":
            continue
        status, _m, _mg = evaluate(req["metric"], req["op"], req["target"], ev)
        if status != "satisfied":
            recomputed_ok = False
            break
    if bool(certificate.get("ok")) != recomputed_ok:
        discrepancies.append(
            f"overall ok={certificate.get('ok')} but evidence implies ok={recomputed_ok}")

    return RecheckResult(consistent=not discrepancies, checked=checked,
                         discrepancies=tuple(discrepancies))


def certify(part, genome, solid, *, process: str = "fdm",
            seat_gap_mm: float | None = None) -> Certificate:
    """Convenience: derive the spec, gather evidence, and return the certificate in one call."""
    from .spec import derive_specification, evidence

    spec = derive_specification(part, genome, solid, process=process)
    ev = evidence(part, genome, solid, process=process, seat_gap_mm=seat_gap_mm)
    return check(spec, ev)
