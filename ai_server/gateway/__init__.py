"""LLM Gateway — provider abstraction with structured outputs (M1-W2-BE-03)."""

from .base import LLMGateway, LLMResult, Message, Usage, estimate_cost
from .registry import build_gateway, load_profiles
from .schema_minimal import minimal_instance, sanitize_schema

__all__ = [
    "LLMGateway",
    "LLMResult",
    "Message",
    "Usage",
    "estimate_cost",
    "build_gateway",
    "load_profiles",
    "minimal_instance",
    "sanitize_schema",
]
