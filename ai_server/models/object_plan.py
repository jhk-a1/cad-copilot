"""Object planning contract (POST /api/object/plan) — Stage 1, v2.1.0 (ADR-004).

The user describes an OBJECT. The planner decomposes it into the PARTS needed to build it
properly (a single-part object is just a one-part plan). The complexity gate still applies at
the object level: refuse or decompose, never guess an object we can't build properly.
"""

from __future__ import annotations

from pydantic import Field

from .common import ComplexityClass, StrictModel


class PlanContext(StrictModel):
    """Optional context carried across clarification turns."""

    clarification_answers: dict[str, str] = Field(default_factory=dict)
    session_id: str | None = None


class ObjectRequest(StrictModel):
    text: str = Field(..., max_length=1000, description="Natural-language OBJECT description")
    context: PlanContext | None = None


class Clarification(StrictModel):
    """A question the planner asks instead of guessing."""

    question: str
    options: list[str] = Field(default_factory=list)


class Attachment(StrictModel):
    """How a part attaches to another (ADR-008) — a CLOSED schema (an open dict breaks Anthropic
    strict structured output). The engine solves the mate so the part seats on the host's surface."""

    to: str = Field(..., description="Host part id this attaches to, e.g. 'body'")
    where: str = Field(default="side", description="Host surface: side|wall|top|rim|bottom|front|...")
    height_frac: float = Field(default=0.5, description="0..1 up the host wall (for a side mate)")
    angle: float = Field(default=0.0, description="Angle around the host axis, degrees")


class RequirementSpec(StrictModel):
    """A typed, checkable requirement the model FORMALISES from intent (ADR-015).

    The open-ended understanding: the LLM reasons about the requirements an expert assumes for THIS
    object and expresses each as a predicate in a CLOSED grammar — ``<metric> <op> <target>`` over an
    allow-listed metric vocabulary — so every requirement it emits is machine-checkable by the
    certificate (correct-by-construction; invalid ones are dropped). A closed model (not an open dict)
    keeps the structured-output schema Anthropic-strict-clean.
    """

    metric: str = Field(..., description="One allow-listed metric, e.g. 'capacity_mm3', 'wall_mm', "
                        "'is_hollow', 'opening', 'stability_ratio', 'cavity_reachable'.")
    op: str = Field(..., description="Comparison: >, >=, <, <=, ==, != (== or != for bool/enum).")
    target: str = Field(..., description="The bound as text: a number ('150000'), a bool ('true'), "
                        "or an enum value ('top'). Parsed against the metric's type.")
    description: str = Field(default="", description="Plain-English statement of the requirement.")


class PartPlan(StrictModel):
    """One constituent part the object needs."""

    id: str = Field(..., description="Stable part id, e.g. 'body', 'handle', 'base'")
    name: str = Field(..., description="Human label shown in the UI")
    family: str = Field(..., description="Validated family: box | cylinder | l_bracket | ...")
    object_type: str = Field(..., description="prismatic | cylindrical | bracket | ...")
    features: list[str] = Field(default_factory=list)
    operations_likely: list[str] = Field(default_factory=list)
    count: int = Field(default=1, ge=1, description="How many of this part the object needs")
    position: list[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0],
        description="[x, y, z] in mm: where this part sits in the object frame, so parts assemble "
        "(the main/body part at [0,0,0]; others offset to their real location).",
    )
    # --- FUNCTIONAL REQUIREMENTS (the generalization: the model REASONS each part's function, so it
    #     knows an engine block is hollow with bores because it understands engines — not a keyword)
    shape: str = Field(
        default="",
        description="Primitive that best realizes this part: box | cylinder | prism | cone | sphere "
        "| torus | wedge | loft | sweep | l_bracket | handle. Empty => infer from family.",
    )
    hollow: bool = Field(default=False, description="Does the part need a cavity / internal space?")
    opening: str = Field(
        default="",
        description="If hollow, where it OPENS by function: top (cup/bowl) | both (pipe/tube) | "
        "bottom | none (sealed). Empty => inferred.",
    )
    bore: bool = Field(default=False, description="Needs a central axial through-hole (a bore)?")
    pattern: str = Field(
        default="",
        description="Surface texture for this part: a named motif (scales | knurl | studs | ribs | "
        "rings | grooves | hex | weave | bumps) OR — for ANY custom pattern — a height-field "
        "expression h(u,v) in [0,1], e.g. '0.5+0.5*sin(u*tau*10)' or "
        "'pow(1-frac(v*rows),3)' (downward spikes). u,v in [0,1] over the wall; cols,rows tile it. "
        "Allowed: sin cos tan sqrt abs floor frac tri saw noise hash min max pow clamp smoothstep "
        "step mix sign + - * / % **, and pi/tau. Empty = no texture.",
    )
    purpose: str = Field(default="", description="One line: what this part is for / must do.")
    requirements: list[RequirementSpec] = Field(
        default_factory=list,
        description="Implied engineering requirements an expert assumes for this part (the UNSAID), "
        "each a checkable predicate. The certificate (ADR-011) proves them; the assumption ledger "
        "marks them inferred. Leave empty to rely on the deterministic frames.",
    )
    attachment: Attachment | None = Field(
        default=None,
        description="How this part ATTACHES to another instead of a guessed position (ADR-008). The "
        "engine solves the mate so the part seats on the host's surface. A handle on a mug body: "
        "{to:'body', where:'side', height_frac:0.5}. Null for a free-standing part.",
    )


class ObjectPlan(StrictModel):
    object_name: str = Field(..., description="What the user is building, e.g. 'phone stand'")
    summary: str = Field(..., description="One line describing the object")
    parts: list[PartPlan] = Field(default_factory=list)
    complexity_class: ComplexityClass
    clarifications_needed: list[Clarification] = Field(default_factory=list)
    assembly_notes: str | None = Field(
        default=None, description="How parts relate (positioning/joints are later scope)"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
