"""Functional-verification gate (ADR-007) — does the built part actually serve its purpose?

The Kernel-CEGIS loop guarantees the geometry is VALID. This gate goes further: it checks the
realized genome against the part's stated FUNCTIONAL REQUIREMENTS (an LVS-style intent-vs-model
check). A cup that came out solid, or closed when it should open at the top, or missing its bore, is
a *functional* failure even if the solid is geometrically fine — and the founder's rule is that the
purpose must be met, not merely that the shape is valid. Unmet requirements are surfaced loudly (and
can gate the build), so "it understands the need" is enforced, not hoped.
"""

from __future__ import annotations

from .grammar import FeatureType, Genome

_HOLLOW = {FeatureType.HOLLOW_CYLINDER, FeatureType.HOLLOW_BOX}


def unmet_requirements(part, genome: Genome) -> list[str]:
    """Return the functional requirements the genome does NOT satisfy ([] = purpose met)."""
    types = [f.type for f in genome.features]
    hollow_built = any(t in _HOLLOW for t in types)
    bore_built = FeatureType.BORE in types
    primary = genome.primary
    opening = (primary.options.get("opening") if primary else "") or ""

    unmet: list[str] = []
    if bool(getattr(part, "hollow", False)) and not (hollow_built or bore_built):
        unmet.append("part must be HOLLOW (it needs an internal cavity) but was built solid")

    want_open = (getattr(part, "opening", "") or "").strip().lower()
    if hollow_built and want_open and opening != want_open:
        unmet.append(f"opening must be {want_open!r} (its function) but is {opening!r}")

    if bool(getattr(part, "bore", False)) and not (bore_built or opening == "both"):
        unmet.append("part must have a central BORE (through-hole) but none was built")
    return unmet
