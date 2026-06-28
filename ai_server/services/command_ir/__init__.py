"""Command IR services — the validated safety layer (M1-W3-BE-04)."""

from __future__ import annotations

from .validator import IRValidator, Issue, ValidationReport

__all__ = ["IRValidator", "Issue", "ValidationReport"]
