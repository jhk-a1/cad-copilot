"""Unit tests for the Design-Intent gate (M1-W1-UI-01).

The gate has no adsk dependency, so it is testable without Fusion. We load it by file
path to avoid clashing with the ai_server package namespace.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_GATE_PATH = (
    Path(__file__).resolve().parents[2] / "fusion_addin" / "core" / "design_gate.py"
)
_spec = importlib.util.spec_from_file_location("design_gate", _GATE_PATH)
design_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(design_gate)

pytestmark = pytest.mark.unit


class _Intent:
    def __init__(self, name: str) -> None:
        self.name = name


class _Design:
    def __init__(self, intent) -> None:
        self.designIntent = intent


def test_assembly_design_is_blocked() -> None:
    result = design_gate.evaluate(_Design(_Intent("AssemblyDesignType")))
    assert result.allowed is False
    assert result.kind == design_gate.DesignKind.ASSEMBLY
    assert "Assembly" in result.message


def test_part_design_allowed() -> None:
    result = design_gate.evaluate(_Design(_Intent("PartDesignType")))
    assert result.allowed is True
    assert result.kind == design_gate.DesignKind.PART
    assert result.message == ""


def test_hybrid_design_allowed() -> None:
    result = design_gate.evaluate(_Design(_Intent("HybridDesignType")))
    assert result.allowed is True
    assert result.kind == design_gate.DesignKind.HYBRID


def test_missing_design_intent_allowed_with_warning() -> None:
    """Older Fusion builds without designIntent must not be hard-blocked."""
    result = design_gate.evaluate(_Design(None))
    assert result.allowed is True
    assert result.kind == design_gate.DesignKind.UNKNOWN
    assert result.message  # warns, but proceeds


def test_broken_design_object_does_not_raise() -> None:
    class Boom:
        @property
        def designIntent(self):
            raise RuntimeError("api mismatch")

    result = design_gate.evaluate(Boom())
    assert result.kind == design_gate.DesignKind.UNKNOWN
    assert result.allowed is True
