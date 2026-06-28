"""Design-Intent gate — MANDATORY platform fix (Autodesk Fusion, Jan 2026).

The Jan 2026 "Intent-Driven Design" update introduced part / assembly / hybrid design
types. In an ASSEMBLY design, "creating features and other modeling operations are not
supported and will fail if attempted" (Fusion API docs). In a PART design, creating a
new component fails. CAD-Copilot generates parts, so every generation MUST gate on the
active design's intent before touching geometry.

This module has NO hard dependency on adsk at import time (so it can be unit-tested and
so older Fusion builds without `designIntent` degrade gracefully).
"""

from __future__ import annotations

from enum import StrEnum


class DesignKind(StrEnum):
    PART = "part"
    ASSEMBLY = "assembly"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class GateResult:
    """Whether generation may proceed, and a user-facing message if not."""

    def __init__(self, allowed: bool, kind: DesignKind, message: str = "") -> None:
        self.allowed = allowed
        self.kind = kind
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"GateResult(allowed={self.allowed}, kind={self.kind}, message={self.message!r})"


# Outcomes by design kind. Hybrid and part allow modeling; assembly does not.
_MESSAGES = {
    DesignKind.ASSEMBLY: (
        "CAD-Copilot generates parts. This is an Assembly design, where modeling "
        "operations aren't supported. Open or create a Part or Hybrid design (or "
        "activate a component) and try again."
    ),
    DesignKind.UNKNOWN: (
        "CAD-Copilot couldn't determine the design type. Proceeding cautiously; if "
        "generation fails, switch to a Part or Hybrid design."
    ),
}


def classify_design_intent(design) -> DesignKind:
    """Read the active design's intent defensively.

    `design` is an adsk.fusion.Design. Older builds may lack `designIntent`; treat any
    failure as UNKNOWN rather than crashing (the add-in must never hard-fail here).
    """
    try:
        raw = getattr(design, "designIntent", None)
        if raw is None:
            return DesignKind.UNKNOWN
        name = str(getattr(raw, "name", raw)).lower()
        if "assembl" in name:
            return DesignKind.ASSEMBLY
        if "hybrid" in name:
            return DesignKind.HYBRID
        if "part" in name:
            return DesignKind.PART
        return DesignKind.UNKNOWN
    except Exception:
        return DesignKind.UNKNOWN


def evaluate(design) -> GateResult:
    """Decide whether a generation command may run against this design."""
    kind = classify_design_intent(design)
    if kind == DesignKind.ASSEMBLY:
        return GateResult(False, kind, _MESSAGES[DesignKind.ASSEMBLY])
    if kind == DesignKind.UNKNOWN:
        # Allow but warn — we don't block users on builds without designIntent.
        return GateResult(True, kind, _MESSAGES[DesignKind.UNKNOWN])
    return GateResult(True, kind, "")
