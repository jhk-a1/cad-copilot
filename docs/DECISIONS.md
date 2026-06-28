# Decisions & Discussion Log

This file records design decisions and discussions (ADR-style: one entry per decision,
with context + decision + consequences). Newest decisions are appended at the bottom.
Companion files: `SESSION_LOG.md` (detailed chronological work log) and
`PROJECT_MEMORY.md` (durable project facts).

---

## ADR-001 — Drop custom model training for the trial; use frontier LLMs + verification
**Date:** 2026-06-12 · **Status:** Accepted

**Context.** The Jan 2026 plan trained a custom Vitruvion-style sketch transformer and a
fine-tuned CodeLlama-13B. June 2026 deep research (primary sources) showed frontier LLMs
now beat fine-tuned CAD models on generalization (Text2CAD-Bench: GPT-5.2 IoU 0.59 vs
fine-tuned 0.02–0.08; CAD-Assistant: GPT-4o zero-shot beats Vitruvion 0.979 vs 0.706 F1).

**Decision.** No custom training on the 3-month path. Each pipeline stage uses a frontier
LLM with structured outputs + RAG + a best-of-N geometric verifier + one render-and-check
pass. Fine-tuning (on Apache-licensed Zero-To-CAD-1m) is deferred to post-trial.

**Consequences.** 3-month trial becomes feasible; accuracy enforced by the verifier, not by
model size; provider abstraction is mandatory (leaderboard churns fast).

---

## ADR-002 — Cost architecture: sampler escalation, quality never the variable
**Date:** 2026-06-12 · **Status:** Accepted

**Context.** Founder has limited funds. Accuracy is paramount and non-negotiable.

**Decision.** Best-of-N candidates are sampled from a cheap open-weight model; the geometric
verifier accepts only candidates passing the hard floors (execution, dimension echo, IoU)
regardless of which model produced them; escalate to a top model only if none pass. Prompt
caching + Batch API for benchmarks + local hosting until trial. Optimized budget ~$500–900
for 3 months; documented downshift ladder. **Gate metrics never move with budget** — if money
is short we slip the calendar or cut breadth, never accuracy.

**Consequences.** Cost-to-serve ~$0.05–0.15/generation; viable consumer pricing later.

---

## ADR-003 — Vision/moonshot: hybrid neuro-symbolic, NOT hyperdimensional-computing-as-store
**Date:** 2026-06-12 · **Status:** Accepted (long-horizon R&D, off the 3-month path)

**Context.** Founder proposed representing each CAD step as a hyperdimensional-computing
(HDC/VSA) vector, editing one and propagating via constraints, to fix CAD fragility. Research
(primary sources) found: (a) the instinct targets the real moat — the topological-naming
problem, 40 years unsolved; (b) HDC is the wrong *material* — approximate, lossy, can't hold
exact dimensions, edit-error accumulates (Frady 2018; Liu 2025); (c) the problem is a
*representation/reference* problem, not a constraint-propagation one (Bidarra 2005).

**Decision.** Pursue the corrected version as a parallel R&D track: **vectors propose**
(intent, similarity, dependency routing, reference re-identification) + **classical solver +
B-rep kernel guarantee** exact geometry and propagation + **references resolve to stable,
intent-defined anchors**. Documented in `../cad_copilot_vision_rnd_track.md`. The four-corner
whitespace (hybrid-gen / 3D-edit-propagate / stable-references / staged-verification) is
unoccupied by any competitor; our trial already owns the verification corner.

**Consequences.** Trial seeds the moat (edit-breakage dataset nobody else collects). Watch
Autodesk AI Lab (2D→3D) and Zoo.

---

## ADR-005 — Generality: capability = general IR + LLM + general verification, NOT the placeholder families
**Date:** 2026-06-12 · **Status:** Accepted

**Context.** The offline placeholder builds three families (box / cylinder / l_bracket) from
keyword templates. That could be mistaken for the product's ceiling. It is not — the founder
correctly insisted the product must handle "all things and shapes in Fusion 360."

**Decision.** The product's capability is the composition of three GENERAL layers, none tied to
those three families:
1. **General Command IR vocabulary** — sketch primitives (LINE, ARC, CIRCLE, RECTANGLE,
   CONSTRAINT) + features (EXTRUDE, REVOLVE, FILLET, CHAMFER, SHELL, HOLE). This expresses a
   broad space of Fusion parts. The three placeholder families are just deterministic IR templates
   over this vocabulary; the vocabulary is the real surface.
2. **LLM codegen** (M2-W5) emits this IR for ARBITRARY shapes from natural language — the
   generality engine. The keyword templates are the offline stand-in until credits land.
3. **General verification, two tiers:**
   - **Online (real product, Fusion present):** the Safe Executor builds the IR in Fusion, then
     reads the result body's REAL mass properties (volume, bounding box) from Fusion's API and
     checks them against `expected_geometry`. Fusion itself is the ground-truth kernel, so this
     verifies ANY shape — fillets, revolves, lofts, whatever — not just primitives.
   - **Offline (eval/CI, no Fusion):** the analytic mini-kernel (`services/geometry.py`) exactly
     measures the primitive families we can model. Limited by design; that's acceptable off-Fusion.

**The accuracy contract (ties to ADR-001/002):** build whatever the LLM emits, verify it against
Fusion's own geometry, and **refuse-or-decompose only what we cannot verify** — never silently
emit wrong geometry. Coverage grows by expanding the verified envelope, not by hardcoding shapes.

**Consequences.** To deliver generality the EXECUTOR must map the full IR vocabulary (not just
line/rect/circle/extrude) and the executor must run the in-Fusion mass-property check. Both are
implemented here (M1-W4). The analytic kernel stays primitive-only on purpose; OCP is still
deferred (ADR re: geometry kernel). Holes are made real cut geometry as the first proof that the
general feature path (sketch → feature → verify) works beyond solid primitives.

---

## ADR-004 — Input is an OBJECT decomposed into PARTS; sketches are multi-view + fully dimensioned
**Date:** 2026-06-12 · **Status:** Accepted — supersedes the single-"part" framing in the skeleton

**Context.** The Week-1 skeleton framed the input as "describe a part." That is wrong. A real
design request is for an **object**, which may consist of several parts (a mug = body + handle;
a phone stand = base + arm + cradle). A skilled designer decomposes the object, then draws each
part properly — **standard orthographic projection (front / top / side) plus isometric — and
dimensions every feature** before cutting any geometry.

**Decision.** The product concept (the five fixed pipeline stages are unchanged):
1. **Intent (Stage 1)** — user describes an **object**. The AI produces an *object plan*: the
   object decomposed into the list of **parts** required to build it properly, each part with
   its family, features, and likely operations. (Single-part objects are just a 1-part plan.)
2. **Sketch verification (Stage 2)** — for **each part**, generate a proper engineering-drawing
   preview: **orthographic views (front, top, right) + isometric**, with the geometry the part
   needs. Standard sketching procedure, not a single ad-hoc 2D view.
3. **Dimensions (Stage 3)** — **every** feature dimensioned, per part, across the views, with
   the focus-to-highlight UX. Entered values become named userParameters.
4. **Codegen (Stage 4)** — Command IR per part (assembly/positioning of parts is later scope).
5. **Execution (Stage 5)** — parametric parts built in Fusion.

**How multi-view verification is generated:** the server-side geometry kernel (build123d/OCP,
planned M2-W6) realizes the part from its SketchSpec + dimensions and renders the orthographic +
iso views *before* anything commits to Fusion. This reuses the exact kernel we build for the
geometric verifier — multi-view verification and accuracy verification share one engine.

**Consequences / honest scope note.** This is richer and harder than single primitives:
- Object→parts decomposition is an LLM planning task (gate: refuse/decompose still applies to
  objects we can't yet build properly).
- Multi-view, fully-dimensioned drawing generation is essentially auto-drafting — non-trivial.
- The trial still validates on a *starting set* of objects/parts and grows by family-gate, but
  the **architecture, schemas, and UI are built for object→parts→multi-view from now on**, not
  retrofitted later.

**Implementation plan (next work block — "object→parts→multi-view contract rework"):**
- Contract: add `ObjectPlan` (object + parts[]) to Stage 1; make Stage 2 a per-part
  `PartDrawing` with `views[]` (FRONT/TOP/RIGHT/ISO) and per-view dimensioned geometry; Stage 3
  dimensions keyed by part.
- Services: object planner (decompose), per-part multi-view sketch builder, kernel-rendered
  views.
- UI: object input; per-part tabs; multi-view dimensioned preview with highlighting.
- Tests: object-plan golden fixtures; multi-view contract tests; refusal on un-buildable objects.

This ADR is the agreed direction; the schema/code rework follows in the next commits.

---

## ADR-006 — Trial runs on Anthropic only, Claude Sonnet 4.6 (no Fable 5)
**Date:** 2026-06-12 · **Status:** Accepted (refines ADR-002)

**Context.** Founder is acquiring API access. Decision: **Anthropic alone** for the trial.
**Claude Fable 5 is unavailable** to the founder (export/government restriction) — it must not be
used anywhere. Sonnet 4.6 is chosen to keep cost low for the initial trial.

**Decision.** All five gateway profiles use `provider: "anthropic"`. Model assignment:
INTENT / SKETCH / IR_CODEGEN / VISION_JUDGE → `claude-sonnet-4-6` ($3/$15); SAMPLER →
`claude-haiku-4-5` ($1/$5, cheapest for high-volume best-of-N). **Accuracy stays paramount
(ADR-002):** Sonnet is the cheap default, not a quality compromise — a verifier-rejected
generation escalates to `claude-opus-4-8` (the `_escalation_target`, NOT Fable) once the
escalation ladder is built. Config: `configs/models.anthropic.json`. Activation is keyless-safe:
`models.json` stays mock by default (tests/CI/offline); going live is two env vars
(`ANTHROPIC_API_KEY` + `MODELS_CONFIG_PATH=configs/models.anthropic.json`) — no code edit.
The Anthropic backend already routes Sonnet/Haiku/Opus correctly (Fable-only branches never fire);
it is UNTESTED LIVE and must be verified against the `claude-api` reference on the first real call.

**Consequences.** One vendor, one bill, simplest path to a real model. No OpenAI/Google/DeepSeek
keys needed for the trial. Estimated cost-to-serve drops vs a Fable/Opus default; revisit model
mix at the Week-8 bake-off (M2-W8-EVAL-03).

---

## ADR-007 — Generation engine: correct-by-construction Design Genome + Kernel-CEGIS (not raw-LLM-IR)
**Date:** 2026-06-26 · **Status:** Accepted (supersedes the raw-LLM-emits-Command-IR codegen path; refines ADR-001/005)

**Context.** Live testing exposed the ceiling of the raw-LLM-emits-Command-IR approach: the model
authors low-level geometry (sketch points, extrude/revolve) and is weak at precise spatial
reasoning, so it produces structurally-valid-but-geometrically-wrong "vague solids" (solid blob
instead of hollow mug; tangent revolve that fails and rolls back the whole body; detached handle;
missing scale rows). Prompt-tuning and post-hoc repair are whack-a-mole. A seven-track cross-domain
deep-research pass (program synthesis, generative biology, morphogenesis, robotics/control/EDA,
differentiable graphics, evolutionary/QD, + a text-to-CAD SOTA & novelty sweep) found that six
unrelated fields independently reject this "generate-then-check" architecture, and that no published
text-to-CAD system enforces validity *by construction* for 3D editable feature trees. Full writeup:
`../cad_copilot_design_genome_method.md`.

**Decision.** Codegen no longer asks the LLM to author raw geometry. The LLM emits a **genome** — a
typed feature-tree program with **holes** for dimensions and **intent-named anchors** for references,
in a **closed grammar where invalid trees are unrepresentable**. A deterministic pipeline then:
(1) **solves** the holes (user dims + defaults + inter-hole constraints); (2) **compiles** the genome
to the existing validated Command IR, one feature at a time; (3) runs a **Kernel-CEGIS loop** —
every feature is feasibility-gated by the IR Validator + render-and-check (and Fusion online), and a
rejection is a *counterexample* that re-fills holes or kicks structure revision, replacing blind
retry with monotone progress; refuses honestly if it cannot converge. The principle is the same one
ADR-003 names for editing ("neural proposes, symbolic guarantees; vectors for the fuzzy half,
solver+kernel for the exact half"), now applied to **generation**.

**Trial-grade vs moat-grade.** Trial-grade v1 (build now): grammar + compiler + hole-solver +
per-feature gate + CEGIS + a deterministic PartPlan→Genome planner (offline, no LLM spend) and the
live LLM-genome prompt. It is **training-free and cheaper than the raw-IR path** (smaller LLM output,
fewer retries; the grammar/solver/CEGIS loop is deterministic). Moat-grade (post-trial): differentiable
dimension-fitting + a contraction-proof geometry controller; the same attractor/anchor machinery becomes
the **editing** moat (corners B/C of ADR-003). This decision builds **corner A (hybrid generation)** of
the four-corner moat.

**Consequences.** Invalid geometry becomes structurally impossible (closed grammar + per-feature gate),
exact dimensions are manufactured by convergence rather than guessed, and corrections are provably
progressive. Generality is preserved via composition + general `Sweep`/`Loft` fallback fragments (a
vocabulary, not a fixed object list). The raw-IR path is retained as a fallback so nothing regresses.
New IR ops (`PATTERN`, `SWEEP`) are added across model/validator/kernel/executor/compiler as fragments
need them. Honest limits (recorded): the method guarantees *valid*, not *what you meant* — staged human
verification (corner D) stays essential; differentiable fitting and provable contraction are moat-grade,
softened to "monotone decrease within a trust region" at trial-grade.

---

## ADR-008 — Relational + surface-parametric representation: connector-frame attachment + surface-anchored features
**Date:** 2026-06-26 · **Status:** Accepted (extends ADR-007)

**Context.** Live tests showed a CLASS of recurring spatial-relational failures that made results
impractical even when each solid was valid: (1) a mug handle was placed at a GUESSED coordinate and
floated beside the body instead of attaching to the wall; (2) a scale pattern landed as round dimples
on the FLAT BOTTOM instead of wrapping the curved SIDE wall, oriented; (3) motifs were too primitive
(round, no scale shape). Root cause: the engine used ABSOLUTE coordinates + independent parts.

**Decision.** A seven-track cross-domain deep-research pass (mechanical mate-connectors, molecular
docking, skin-appendage patterning, architectural freeform paneling, scale-armour/phyllotaxis,
graphics surface-parameterisation/frame-fields, + a SOTA sweep) converged unanimously: **place things
RELATIVE to surfaces and frames, never at guessed XYZ.** Adopt a relational + surface-parametric layer:
- **Attachment = connector-frame mating.** Every primitive exposes named connector frames on its
  surfaces (`genome/frames.py`: cylinder wall/rim/base, box faces — analytic, closed-form). A part
  attaches by aligning its mounting frame to a host connector frame → a SOLVED rigid transform (a
  mate), so it seats on the host's surface for ANY size. `PartPlan.attachment {to,where,height_frac,
  angle}` (the intent LLM reasons it); `CodeGenResult.placement` carries the `{mount,target}` frames;
  the executor applies `Matrix3D.setToAlignCoordinateSystems` (position is the fallback).
- **Surface features = face-anchored, field-oriented, tiled.** A pattern is anchored to a host face's
  own parameterisation: a cylinder wall is already (θ,z), so scale motifs tile in rows×columns ON the
  wall (the YZ plane offset to the radius), each a scallop (real scale shape), wrapped by a circular
  pattern. (Full direction-field/imbrication is moat-grade; v1 uses the analytic wall frame.)

**Novelty.** The SOTA sweep found no system unifies (a) NL→generated mates, (b) field-oriented
feature placement on named faces, (c) field-conforming imbricated tiling, in one relational +
surface-parametric representation — each ingredient has isolated prior art in a *different* community
(CAD-assembly ML: AutoMate/JoinABLe/ArtiCAD; graphics: lapped textures/mesh-quilting/frame-fields;
text-to-CAD: single-solid command sequences). The unification is the whitespace.

**Consequences.** Parts attach where they belong (the floating handle is fixed, generally — any part
to any host). Features land on the correct surface, oriented, scale-shaped. The representation an LLM
targets becomes *relations over surfaces*, not coordinates — which it reasons about reliably. Honest
limits: analytic surfaces only (closed-form frames) — freeform faces need a mesh frame-field solver
(moat-grade); the Matrix3D mate, YZ-offset wall sketches, and join-extrude scales are correct API
usage but executor-runtime (live-verified next Fusion run); per-row imbrication offset deferred.

---

## ADR-009 — Close the loop: perception-driven spatial verification (perceive → compare → correct)
**Date:** 2026-06-27 · **Status:** Accepted (extends ADR-008)

**Context.** Across four rounds the same meta-failure recurred: the server-side math was correct
*offline* but the *live* Fusion result was wrong (scales burst into a floating radial star; the handle
dropped to the base). Root cause: the generate→build pipeline was **open-loop and blind** — nothing
ever perceived whether features sit ON a surface or parts actually CONTACT their host; the only check
was one body's volume/bbox, so spatial errors were invisible. Two diagnosed mechanisms: (a) no spatial
feedback, and (b) a FLAT motif placed tangent to a CURVED wall sticks out (the radial star).

**Decision.** A seven-field cross-domain deep-research pass — robotics **visual servoing**, physics
**contact mechanics**, neuroscience **predictive coding / active inference**, graphics **surface
scatter/decals**, **tailoring/draping**, **ergonomics/affordances**, + a text-to-CAD SOTA sweep —
converged: a generator must **perceive the result, measure the spatial RELATIONS against intent, and
correct**. Physics gives the exact predicate: a part is seated iff its gap to the host surface is ~0
(not floating) with no deep interpenetration — the "contact certificate". The SOTA sweep confirmed **no
text-to-CAD system verifies spatial relations** of generated geometry — open whitespace. Adopt:
- **Spatial comparator (`genome/verify.py`)** — measure relations on the analytic kernel: does an
  attached part SEAT on its host surface (gap≈0)? does each surface-feature seat lie ON the wall? It
  returns residuals + a certificate, so the engine *perceives* correctness (verifies INTENT).
- **Spatial certificate** surfaced in the build result ("seats on the host, gap 0.0 mm" / "WARNING
  floating") — the user is no longer blind.
- **Conforming surface features** — a feature is ENGRAVED into the wall (cut inward) so it conforms
  and cannot float as a tangent tab (the scatter/decal "seat→align→conform" contract; the scales fix).
- **Robust attachment** — handle-like parts DEFAULT-attach to the body even if the planner omitted it.
- **Live read-back (`safe_executor._readback`)** — the add-in measures where the part ACTUALLY landed
  in Fusion and reports the seat gap (verifies REALITY; catches executor errors the offline comparator
  can't), surfaced in the UI.

**Consequences.** The system finally has closed-loop perception: it sees whether the handle seats on
the wall and the scales sit on the surface. Honest boundary: the server-side comparator verifies the
*intent* is spatially right (catches floating-handle / off-wall-scale classes before shipping); the
live read-back verifies *reality*. Whitespace claim: a perceive-compare-correct loop whose controlled
error is *spatial-placement relations* (on-surface / contact / non-interpenetration / functional) over
generated B-rep — none of the surveyed systems do this. Moat-grade: full visual-servoing correction
(relation-Jacobian), affordance/ergonomic placement constraints, and freeform-face conformance.

---

## ADR-010 — Hybrid representation: B-rep structure + implicit/displacement fields + makeability gate
**Date:** 2026-06-27 · **Status:** Accepted (extends ADR-007/008/009)

**Context.** The recurring `NO_TARGET_BODY` scale failure (1 of 6 rows engraved; the rest died
unpredictably) was not a tuning bug — a seven-track cross-domain deep-research pass (implicit/FRep
modelling, additive-manufacturing texture, graphics displacement, mechanical constraint solving,
DFM/GD&T, robust geometric computation, + a text-to-CAD SOTA sweep) converged on a single root cause:
**B-rep feature operations are *partial functions*.** A boolean/cut/pattern must *find* a target and
re-knit topology, and on coincident/tangent/thin geometry (a cut on a curved wall) the kernel fails —
the canonical non-robustness problem (Shewchuk 1997; the topological-naming problem). The same fragility
will worsen as objects gain texture, lattices, internal channels, many parts, and manufacturing intent.

**Decision.** Adopt a **hybrid, per-feature representation** — the seam the SOTA sweep showed is
**unoccupied** (every text-to-CAD system is monolithic B-rep command sequences; industrial implicit CAD
is never NL-driven):
- **B-rep / Design-Genome** for editable, dimensioned structure (the strength we keep).
- **Implicit / displacement *fields*** for surface texture & complex geometry, where field ops
  (`min`/`max`/displacement) are *total* — they **cannot** fail. **Pillar A (shipped):** surface
  texture is a scalar height field `h(θ,z)` over the wall's own parameterisation, realised as ONE
  watertight **mesh skin** displaced along the normal (`genome/texture.py`), not N fragile cuts. A
  closed two-manifold is *always* valid (proven across 144 parameterisations), so it can never hit
  `NO_TARGET_BODY`; "200 scales" is one field, O(1) in robustness. New `CREATE_MESH_BODY` IR op
  (model/validator/executor); the executor imports the verified mesh as a Fusion mesh body (cosmetic →
  optional/non-fatal), leaving the parametric B-rep core untouched. (Cook displacement 1984; Reyes
  1987; Perlin 1985; Worley 1996; Pasko FRep 1995; Brunton displaced-SDF-for-AM 2021; slicer fuzzy skin.)
- **Robust execution (Pillar B, partial → roadmap):** the shipped non-fatal/`optional` mechanism is the
  first rung of a per-op fallback ladder; representation-routing of risky CSG to a total backend follows.
- **Makeability + mobility gates (Pillars C+D, shipped as `genome/dfm.py`):** extend "purpose must be
  met" to "must be **makeable** and must **fit/assemble**". (i) DFM predicates (min wall/feature,
  internal radius, draft) per process; (ii) **ISO-286 fits** computed from the standard IT formula
  (reproduces the textbook tables — H7/g6 Ø20 → 7..41 µm); (iii) **Grübler–Kutzbach mobility + loop
  counting** on a mate graph (a four-bar → M=1, 1 loop) that names over/under-constraint and the
  kinematic loops a tree-based placer silently breaks on. A makeability certificate is surfaced in the
  build result (advisory) like the spatial certificate.

**Consequences.** Surface texture moves from fragile-and-blind to robust-by-construction; the mug's
scales become a single verified mesh skin rather than a flaky cut array. The DFM/fit/mobility gates
pre-empt the failure classes complex objects will raise (unmoldable/unmachinable parts, parts that
won't fit, mechanisms that don't solve). Honest boundary: the **mesh-body realisation in Fusion**
(STL-import path) and the executor mesh import are the live frontier (founder verifies in Fusion); the
generation, watertight proof, ISO-286 fits, and mobility math are all offline-verified. Whitespace/moat:
the unification — per-feature representation choice (B-rep + implicit/displacement) under a robust
executor, a loop-closing assembly solver, and a makeability gate — is unclaimed in generative CAD.
Roadmap: implicit lattices/TPMS & internal channels as fields; the full fallback ladder; a constraint-
solved mate-network with simultaneous loop closure. Research doc: `../cad_copilot_robustness_research_2026-06.md`.

---

## ADR-011 — Certified CAD: design-as-proof (typed Specification + re-checkable proof-of-fitness)
**Date:** 2026-06-27 · **Status:** Accepted (first pillar of the breakthrough plan)

**Context.** The breakthrough research (`../cad_copilot_breakthrough_plan_2026-06.md`) found the
industry's universal ceiling: every text-to-CAD system — research (DeepCAD, Text2CAD, CAD-MLLM) and
commercial (Zoo, Spectral SGS-1, Autodesk Bernini) — generates geometry and *hopes*; none ships a
machine-checkable guarantee that the model meets the request. CAD-Copilot already owns the *verifier*
half (correct-by-construction genome + closed-loop spatial verification + DFM/fit/mobility gates),
so it is uniquely positioned to ship the thing nobody else can: a **certificate**.

**Decision.** Reframe the deliverable from a *model* to a **(specification, model, proof) triple**
(proof-carrying code — Necula 1997; CompCert). Two new modules, pure and offline:
- **`genome/spec.py` — the Specification (Pillar P0).** A typed `Requirement` is a self-contained
  predicate `(metric op target)` with kind/severity/tier/provenance. `derive_specification` composes
  the requirement set **generally from the part's functional intent + geometry + process** — not a
  per-object list: *hollow?* → cavity + capacity obligations; *opening?* → the opening its function
  needs; *bore?* → the through-hole; *attached?* → seats-on-host; any wall → process min-wall. The
  same rules certify a mug, a box, a bored engine cylinder, or an attached handle. `evidence()`
  measures the realized solid (volume, capacity≈ml, wall, opening, bore, seat-gap) — the witness.
- **`genome/certificate.py` — the proof-of-fitness certificate (Pillar P6).** `check(spec, evidence)`
  emits per-obligation verdicts (satisfied/violated/unverifiable) + margins + an overall fit result;
  the certificate is **self-contained** (it carries the spec AND the evidence). `recheck(cert)` is a
  tiny **independent re-verifier**: given only the certificate JSON, it recomputes every verdict and
  flags any claim that doesn't follow — catching a flipped verdict, a faked overall `ok`, a dropped
  obligation, or an obligation with no requirement. That is the moat: a customer re-verifies in
  seconds **without trusting the generator**.

Wired into `CodeGenService.generate` (every result carries `CodeGenResult.certificate`, summary in
the warnings), and surfaced in the add-in ("✓ certified fit (5/5)" / "✗ NOT certified: …"). It
subsumes and structures the previously ad-hoc functional/spatial/makeability checks.

**Consequences.** CAD-Copilot can now answer *"prove this part meets the request"* — certified
correctness, auditable engineering (the spec is a frozen contract the generator can't silently
weaken — `recheck` catches it), a path to liability-grade/regulated design. Honest boundary: the
offline certificate proves the *intent/design* is fit (geometry/function/manufacturing predicates,
tier="proved"; seating tier="tested"); physics obligations needing certified numerics are future
(tier="bounded"); the live read-back already certifies *reality*. Whitespace confirmed: no
generative-CAD system ships a re-checkable proof of fitness. Next pillars: pragmatic intent
understanding (frames feed more requirements into the spec), the qualitative-physics function gate,
typed compositional assembly, and bidirectional/incremental editing. 352 tests pass (+27), ruff clean.

---

## ADR-012 — Understanding layer: object frames infer the UNSAID, the certificate proves it
**Date:** 2026-06-27 · **Status:** Accepted (breakthrough Pillar P1; builds on ADR-011)

**Context.** The founder's deepest frustration: the system doesn't *understand* what a thing should be
(the dragon-scale motif reads as ripples; more fundamentally, "a coffee mug" leaves a dozen
requirements unstated that an expert just knows — stand without tipping, hold a useful volume,
food-safe wall, graspable handle). Every text-to-CAD system either hallucinates these or ignores
them. ADR-011 gave us a certificate, but it could only prove what was *explicitly stated*.

**Decision.** Add the **understanding layer** (`genome/understanding.py`) — Fillmore frame semantics
applied to CAD. An object class is a **frame** with typed REQUIREMENT TEMPLATES it implies, arranged
by **inheritance** (`object → container → vessel → drinkware`; `pipe`; `handle`). `resolve_frame`
maps a part to its most-specific frame by **keyword match + functional-field inference** (hollow +
open-both → pipe; hollow + drink purpose → drinkware) with a **generic fallback**, so EVERY object —
known or not — gets a principled expansion (general by construction, not a lookup table). `expand`
walks the inheritance chain and instantiates the implied requirements; `derive_specification` merges
them into the Specification (explicit intent wins on collision) and records an **assumption ledger**:
every requirement tagged `stated` (user declared) / `inferred` (frame implied — the unsaid) /
`derived` (from geometry/process), so the inference is auditable and overridable, never a black box.
Frame requirements are **advisory ("should")** — proven and surfaced but non-gating — while stated
intent stays **gating ("must")**; soft violations become `certificate.advisories` (e.g. a handle
whose grip is a little tight at 17 mm).

**Consequences.** "make me a coffee mug" now resolves to the *drinkware* frame and the certificate
**proves three requirements the user never stated** — stable base, useful capacity (≥150 ml),
food-safe wall — with the summary "certified fit … [drinkware]; proved 3 implied requirement(s)". The
system understands the need and *proves* it. This is the convergence of P1 (understanding) and P6
(certify): frames supply the implied obligations, the certificate discharges them, the ledger keeps
it honest. General: a pipe resolves by function with no keyword; an opaque part falls back to the
generic frame with no inferred noise. Honest boundary: the frame library is a curated seed (the
*mechanism* generalises; coverage grows with use), advisory inferences are heuristic, and ergonomic
predicates (stability ratio, grip clearance) are first-order proxies. Next: the qualitative-physics
function gate (does it actually *work*), typed compositional assembly, and bidirectional editing.
369 tests pass (+17), ruff clean. Plan: `../cad_copilot_breakthrough_plan_2026-06.md`.

---

## ADR-013 — Function gate: qualitative "does it WORK" (Function-Behaviour-Structure)
**Date:** 2026-06-27 · **Status:** Accepted (breakthrough Pillar P3; extends ADR-011/012)

**Context.** A model can be a valid solid and still be functionally dead (a cup you can't fill, a
faucet that won't flow). No text-to-CAD verifies this; the frontier "checks" by showing a vision
model a picture. The sound, 40-year-old answer is qualitative physics + Function-Behaviour-Structure
(de Kleer & Brown; Forbus QPT; Kuipers QSIM; Gero FBS; Stone & Wood Functional Basis).

**Decision.** `genome/function_model.py`: `infer_functions(part, genome)` derives the Functional-Basis
functions a part must perform from its purpose verbs AND its structure (hollow→contain; open-both/
bored→convey; attached→couple; purpose "support/fasten/move"→support/couple/actuate) — general, no
object table. `behavior_requirements` maps each function to a checkable *teleological* predicate the
certificate proves: **contain → the cavity is reachable to fill/empty** (`cavity_reachable`); **convey
→ a through-path exists** (`through_connected`); **support → it stands stably**; **couple → it has a
join**. Evidence (`spec.evidence`) gains `cavity_reachable / through_connected / has_coupling`,
computed analytically. Behaviour obligations are advisory ("should") — they catch "valid but doesn't
work" without over-gating; the hard functional gating stays in the stated-intent requirements.

**Consequences.** A sealed cup (hollow, no opening) now fails `behavior.contain` — the
functionally-dead case nobody else catches. A pipe proves it both contains and conveys. General over
any object (functions from purpose + structure). Mechanisms (actuate) are owned by the mobility/
assembly layer (dfm + ADR-014), not single parts. 380 tests pass (+6), ruff clean.

---

## ADR-014 — Compositional assembly: typed interfaces + system-level proof
**Date:** 2026-06-27 · **Status:** Accepted (breakthrough Pillar P5; uses ADR-011 + dfm mobility)

**Context.** Every text-to-CAD assembler places parts and *hopes* the whole is consistent — pairwise
mates, no system guarantee. Applied category theory (operads of wiring diagrams; (decorated) cospans;
functorial property propagation) gives the missing algebra: parts are boxes with TYPED PORTS;
composition is legal iff the port types match; the assembly is correct-by-construction at the SYSTEM
level.

**Decision.** `genome/assembly.py`: `ports_of(genome)` derives a part's typed interface ports from
its geometry (hollow cylinder → wall(`surface_round`) + rim; loop_handle → a `mount` plug; bracket →
`mount_face`; a bore → `bore` socket) — general, geometry-driven, not by name. `compatible(a,b)` is a
typed relation (mount↔surface, lid↔rim, shaft↔bore, face↔face). `build_assembly_spec(plan)` derives
typed connections from the plan's attachments, checks interface compatibility, runs a system-level
**Grübler–Kutzbach mobility** check (via `dfm.analyze_mechanism`) for connectivity + rigidity, and
emits an OBJECT-LEVEL Specification + evidence. `certify_assembly(plan)` returns a certificate
(reusing ADR-011 `check`), so the object certificate is **independently re-checkable**. New endpoint
`POST /api/codegen/assembly` (deterministic, no LLM) returns it.

**Consequences.** "the whole mug — body + handle — is a rigid, connected assembly whose interfaces
type-match" is now a *proof*, not a hope; a floating part breaks `assembly.connected`; an
unintended mechanism trips `assembly.rigid`. General over any multi-part object (mug+handle,
bracket+plate, shaft+bushing). The add-in can call the endpoint after building the parts. 387 tests
pass (+7, incl. the endpoint), ruff clean.

---

## ADR-015 — Open-ended understanding: formalise the unsaid into checkable requirements
**Date:** 2026-06-27 · **Status:** Accepted (breakthrough Pillar P1-full; extends ADR-012; touches P2)

**Context.** The deterministic frames (ADR-012) understand a *seed* of object classes. To generalise
to ANY object (the founder's non-negotiable), the planning model must reason about each object's
implied requirements — but a free-text "requirement" isn't checkable, and an open dict re-triggers
the Anthropic strict-schema 400 that once refused "coffee mug".

**Decision.** Autoformalization, scoped to what we can verify. A closed `RequirementSpec` model
(metric/op/target/description) is added to `PartPlan.requirements`; the intent prompt
(`REQUIREMENTS_PROMPT`) instructs the model to formalise the UNSAID as predicates in a CLOSED grammar
over an allow-listed **metric vocabulary** (the `spec.evidence` keys: capacity_mm3, wall_mm,
stability_ratio, is_hollow, opening, cavity_reachable, …). `genome/intent_expand.py` is the
**correct-by-construction filter**: `validate()` drops any proposal with an unknown metric, a bad
operator, a type-mismatched comparison, or an unparseable target — so a hallucinated requirement can
NEVER enter the certificate. Survivors become checkable `Requirement`s merged into the spec
(`derive_specification`) and proven by the certificate (ADR-011); the ledger marks them inferred. A
genuinely-ambiguous, design-critical choice becomes ONE high-value `clarifications_needed` question
instead of a guess.

**Consequences.** Understanding is now open-ended: for any object the model can express "a mug holds
≥250 ml, won't tip (stability_ratio ≥ 0.35), has a food-safe wall" and the certificate proves them —
no frame needed, yet still machine-checkable. The frames remain the free, deterministic floor. The
closed model keeps the structured-output schema strict-clean (guard test passes); the golden plan was
regenerated. 393 tests pass (+6), ruff clean. (Bridges P1 understanding and the P2 autoformalization
thesis — NL → typed, checkable obligations.)

---

## ADR-016 — Bidirectional, incremental editing: edit in words, references never break
**Date:** 2026-06-27 · **Status:** Accepted (breakthrough Pillar P7 — completes the breakthrough plan)

**Context.** A model's value is an EDITABLE design that carries intent; the industry's worst unsolved
pain is the topological-naming problem (edit upstream → downstream references break on regeneration).
Three never-connected fields fix it together: bidirectional transformations / LENSES (Foster et al.;
symmetric & edit lenses), self-adjusting / INCREMENTAL computation (Acar), and PERSISTENT topological
identity (Kripac).

**Decision.** `genome/edit.py`: the editable view is the parameters; a lens maps genome↔parameters
with the well-behaved laws (`parameters`/`with_parameters`, GetPut/PutGet/PutPut tested). An `Edit`
is a delta (set/scale/delta) on a hole or `*`; `apply_edit` returns a NEW genome with the SAME feature
ids (persistent identity) changing only the touched holes (incremental; `changed()` is the minimal
delta). `parse_edit` maps common NL edits ("make the wall thicker", "20% bigger", "set wall to 3") to
deltas — the deterministic floor; the LLM is the open-ended path. New endpoint `POST /api/codegen/edit`
returns the new dimensions, **keyed by the same user-parameter names** so nothing downstream breaks.

**Consequences.** Conversational editing is first-class and reference-safe: the test proves feature
ids AND the IR's `CREATE_USER_PARAMETER` names are unchanged across an edit — the topological-naming
problem solved at the parameter level, with edits propagating minimally. General over any genome part.
404 tests pass (+11). **This completes all seven breakthrough pillars** (P0/P6 certify, P1 understand,
P3 function, P5 assembly, P1-full open-ended, P7 edit) — Certified Functional CAD.

---

## Change Log (running)
- 2026-06-12: Reframed skeleton from "part" → "object" (palette text, README). Created
  `docs/` tracking files (SESSION_LOG, PROJECT_MEMORY, DECISIONS). Initial git commit of the
  verified Week-1 foundation.
- 2026-06-12: **Implemented ADR-004** — contract → v2.1.0. ObjectPlan/PartPlan (Stage 1),
  PartDrawing with FRONT/TOP/RIGHT/ISO views (Stage 2), per-part Command IR with part-prefixed
  userParameters (Stage 4). Multi-part demo working ("phone stand" → base + upright). 26 tests
  pass, ruff clean, live E2E verified. SVGs still schematic; LLM planner + l_bracket codegen +
  kernel-rendered accurate drawings pending.
- 2026-06-12: **Complete dimensioning (ADR-004 refinement)** — per founder, the dimension panel
  must surface EVERYTHING an engineer would dimension based on the part's features. Sketch service
  now derives a full schedule grouped by feature: Overall (L/W/H or Ø/H), Mounting holes (diameter,
  X/Y edge distance, X/Y spacing, count), Fillets, Chamfers, Bore. Views render as dimensioned
  drawings (dimension lines + labels). UI renders grouped collapsible schedule + cleaner tiles.
  46 tests pass, ruff clean, no eval regression. Still placeholder geometry; kernel-accurate
  drafting + codegen honoring holes/fillets land with the real engine (M1-W4/M2-W6).
- 2026-06-12: **IR Validator (M1-W3-BE-04)** — the semantic gate between generation and
  execution is in. `services/command_ir/validator.py` (IRValidator → ValidationReport of coded
  Issues). Checks: units=mm, unique ids, DAG acyclicity + dep ordering, entity-ref resolution +
  ordering, required refs per command type, valid plane/operation enums, positive-or-declared
  dimensions (symbolic dims must resolve to a CREATE_USER_PARAMETER), profile closed before
  extrude/revolve, expected_geometry sanity, rollback points real. Wired into the codegen path:
  invalid IR is REFUSED (VERIFIER_REJECTED), never emitted — per ADR-002 accuracy is
  non-negotiable. 18 mutation tests (one per failure mode) + 64 total pass, ruff clean, no eval
  regression (placeholder IRs pass clean → no false refusals).
- 2026-06-12: **Intent service onto the gateway (M1-W3-BE-05)** — first pipeline stage moved
  off the keyword placeholder onto a real model. `services/intent.py` (IntentService over the
  LLMGateway). Two paths, no keys required: provider=="mock" (default) → deterministic
  `placeholder.plan_object` templates (offline, what eval/palette use); any real provider →
  structured-output ObjectPlan from the model, then a server-side **family gate**. The gate is
  the accuracy guarantee on top of the model (refuse-or-decompose, ADR-002): only parts whose
  family we can build are kept; the rest are dropped and the plan is downgraded to decompose
  (some buildable) / out_of_scope (none) with an honest clarifying question. Every failure path
  (gateway error, schema-invalid candidate, empty result) falls back to the deterministic
  planner so the endpoint never 500s. Wired into /api/object/plan. 5 unit tests via scripted
  mock backend (offline fallback, model plan passthrough, gate→decompose, gate→out_of_scope,
  schema-invalid→fallback); 69 total pass, ruff clean, no eval regression. Flip configs/
  models.json INTENT provider to activate the live model. Pattern set for sketch/codegen
  migration (sketch kernel-rendered M1-W4-BE-06; codegen real M2-W5).
- 2026-06-12: **Safe Executor (M1-W3-UI-04)** — the add-in stage that realizes a validated IR
  in Fusion. `fusion_addin/core/safe_executor.py`, split like design_gate: a PURE `compile_ir`
  (IR dict → typed ops; single mm→cm conversion at the boundary; resolves symbolic dims;
  defensive — rejects non-mm units, empty IR, unresolved params, unsupported command types) +
  `SafeExecutor.execute` (lazy adsk; builds geometry, groups the whole build into ONE timeline
  group = one undo, rolls back all partial work on any failure). Editability: each
  CREATE_USER_PARAMETER becomes a real Fusion user parameter and the extrude depth is bound to
  it BY NAME (live expression). Wired into CAD_Copilot executeCode (re-gates design intent,
  returns real status). 9 unit tests on the compile core incl. the full-chain test (the IR the
  server emits + validator passes compiles cleanly to executor ops). 78 total pass, ruff clean,
  no eval regression. Fusion-runtime half verified live (founder has Fusion installed). 3D
  highlight of built geometry (M1-W3-UI-05) still acknowledged-only; drawing highlight is
  already client-side in the palette.
- 2026-06-12: **Geometry kernel = analytic, OCP deferred (refines ADR-001)** — the geometric
  verifier's primitive tier is a pure-Python ANALYTIC kernel (`services/geometry.py`), not
  build123d/OCP. Rationale: (a) box/cylinder/l_bracket are simple enough that analytic formulas
  give EXACT volume/bbox — exact beats the voxel approximation a kernel gives, and accuracy is
  paramount; (b) OCP has no real Python-3.14 wheel (only `cadquery-ocp-proxy`/`-novtk` shims) and
  pulls ~35 packages (scipy/scikit-learn/ipython) — disproportionate for the trial. OCP is
  deferred to post-trial, when booleans/fillets on arbitrary geometry are needed. `realize(ir)`
  returns None for families it can't build yet (never a false verdict). **Render-and-check**
  (`check_geometry`) is wired into codegen after the IR Validator: realize the IR, confirm
  measured volume/bbox match expected_geometry within the dimensional gate (<0.1 mm); a mismatch
  is REFUSED (VERIFIER_REJECTED). A `iou()` voxel primitive is included for eval shape-agreement
  scoring later. 9 kernel unit tests (incl. the verifier CATCHING a tampered expected_geometry) +
  88 total pass, ruff clean, no eval regression (all placeholder IRs verify clean).
- 2026-06-12: **Accurate multi-view drawings (M1-W4)** — replaced the schematic SVGs with
  PROPORTIONAL drafting. `services/drawing.py` projects box/cylinder to front/top/right + iso
  using one shared mm→view scale across the three ortho views (a 50 mm edge is the same length
  everywhere — engineering convention); holes are drawn at their true edge/spacing positions; the
  iso is a real isometric projection. So a 100×60×8 plate now draws a wide slab, a 30×30×80 bar a
  tall column. Dimension lines + `data-ref` highlight hooks preserved. `placeholder` box/cylinder
  drawing builders rewired to it (using the schedule's default values); l_bracket keeps its
  schematic outline until its kernel/codegen land. Analytic projection of the same primitives the
  geometry kernel measures (preview and verifier agree); OCP-rendered drafting deferred with the
  kernel. 7 proportionality unit tests + 95 total pass, ruff clean, no eval regression.
- 2026-06-12: **l_bracket family complete (codegen + executor + kernel + drawing)** — the third
  supported family is now end-to-end, not refused. Codegen builds the L as 6 `ADD_LINE` commands
  forming a closed profile → extrude (part-prefixed userParameters + expected_geometry). Executor
  gained `ADD_LINE` support. Kernel gained an exact `LBracket` solid (volume = thickness·(a+b−t)·
  depth) + `realize` (resolves leg/thickness params by suffix) so the render-check and eval IoU
  cover it. Drawing renders the true L outline (front), orthographic rectangles (top/right), an
  L-prism iso, and holes. Removed the now-dead schematic SVG helpers from placeholder (all view
  rendering lives in drawing.py via a `_VIEW_BUILDERS` map). Effect: eval generation_rate 77.8 →
  **100.0** (l_bracket bench cases now generate). 102 tests pass, ruff clean, baseline refreshed.
- 2026-06-26: **Design-Genome generation engine (ADR-007)** — pivoted codegen off raw-LLM-IR after a
  7-track cross-domain deep-research pass. New `ai_server/services/genome/` (grammar/library/solver/
  cegis/planner/prompt): the LLM/planner emits a typed feature genome with HOLES in a closed grammar;
  a solver fills holes onto the feasible manifold (DRC clamps as counterexamples); a compiler emits
  validated Command IR; a Kernel-CEGIS loop returns verified IR or an honest refusal. Kernel gained
  exact `HollowCylinder`/`HollowBox` (hollow bodies now render-check VERIFIED); new `PATTERN` IR op
  (scales/ribs) across model/validator/executor. Wired into CodeGenService genome-first (deterministic
  planner = $0 LLM; live LLM-genome for novel families; raw-IR fallback). The dragon-scale mug builds
  offline correct-by-construction. 161 tests pass (+33), ruff clean, eval baseline holds. Method doc:
  `../cad_copilot_design_genome_method.md`. Commit `817a8bb`.
- 2026-06-26: **Function drives topology** (commit `6dc7bf0`) — a hollow part's opening comes from
  what the object is FOR (cup→top, pipe→both, sealed→none): `Feature.options["opening"]`, kernel
  models open_top/open_bottom, executor SHELL removes the matching end face. The earlier closed-top
  caveat resolved. 165 tests.
- 2026-06-26: **Generalisation** (ADR-007 extension, commit `fd36444`) — answers "a keyword list is
  not generalisation." (a) Functional-intent layer: `PartPlan` carries `shape/hollow/opening/bore/
  purpose` the intent LLM reasons; `plan_genome` routes by explicit function first (keyword map only a
  fallback), so an engine cylinder → solid_cylinder+bore because it understands engines. (b)
  Functional-verification gate (`genome/functional.py`) refuses a part that misses its purpose. (c)
  General vocabulary: cone/prism/sphere/torus/wedge/loft/sweep primitives + BORE modifier; IR ops
  ADD_POLYGON/SWEEP/LOFT/EXTRUDE.taper/CREATE_SKETCH.offset (cone+prism render-verified, rest
  live-verified). Demonstrated across 10 diverse objects, all purpose-met, gibberish families. 192
  tests pass, ruff clean, eval holds, object_plan golden regenerated. SWEEP/LOFT/taper/offset-planes
  are the live frontier (executor-runtime, founder verifies in Fusion).
- 2026-06-26: **Relational + surface-parametric** (ADR-008, commit `5c4cb19`) — fixes the spatial
  failures (floating handle, scales-on-bottom) from a 7-field cross-domain pass that all said "place
  RELATIVE to surfaces/frames, not guessed XYZ." (a) Connector-frame attachment: `genome/frames.py`
  analytic frames; a part mates its mounting frame to a host connector → solved rigid transform
  (handle seats on the wall at grip height for any radius); `PartPlan.attachment`,
  `CodeGenResult.placement`, executor `Matrix3D.setToAlignCoordinateSystems`. (b) Surface features on
  the curved WALL: scale motifs (scallops) tiled in rows×columns on the wall plane, wrapped by a
  circular pattern — not dimples on the bottom. 195 tests pass (+8), ruff clean, eval holds. Live
  frontier: the mate transform, YZ-offset wall sketches, join-extrude scales (executor-runtime).
- 2026-06-27: **Strict-schema fix** (commit `7ff2a9e`) — `attachment` as an open dict made the plan
  structured-output schema illegal for Anthropic strict mode (400) → live intent fell back to keywords
  → "coffee mug" refused. Typed `Attachment` (closed model) + a contract guard test.
- 2026-06-27: **Closed-loop spatial verification** (ADR-009, commit `ad27b07`) — fixes the recurring
  open-loop/blind failure (floating scales, dropped handle) via a 7-field pass that converged on a
  spatial-relation error signal. `genome/verify.py` comparator (seat/float/on-surface), spatial
  certificate in the build result, scales ENGRAVED into the wall (new EXTRUDE `direction=negative`)
  so they conform, handle-like parts DEFAULT-attach, and a live read-back (`safe_executor._readback`)
  measures where the part actually landed in Fusion. SOTA whitespace: no text-to-CAD verifies spatial
  relations. 201 tests pass (+5), ruff clean, eval holds. Live frontier: read-back + engraved cut.
- 2026-06-27: **Seat correction works LIVE** (commit `7fc1fe8`) — the measurement-driven
  `_seat_correction` (measure where the part landed → translate to seat on the host target) fixed the
  handle live: read-back "seats on host, gap 0mm". The hard attachment problem is solved + general.
- 2026-06-27: **Scale-cut robustness** (commits `a6b5838`, `463a3e2`) — non-fatal optional cuts +
  participantBodies + inside-wall symmetric cut got 1/6 scale rows to engrave; the rest still fail
  `NO_TARGET_BODY`. Per-feature B-rep surface texturing on curved walls is fragile/un-debuggable blind.
- 2026-06-27: **Entering deep research** on a robust substrate (implicit/SDF/FRep hypothesis) for
  surface texture + the complex-object problems ahead. ADR + research doc to follow.
- 2026-06-27: **Texture = a MOTIF LIBRARY** (ADR-010 generalisation) — founder: "scales for any wall
  is still scale-specific; generalise to ANY pattern." The displacement-field→watertight-mesh substrate
  was already general; the motif was hardcoded. Now `texture.py` has 9 motifs (scales/knurl/studs/ribs/
  rings/grooves/hex/weave/bumps) as height fields over the wall's (u,v) chart + `MOTIFS`/`resolve_motif`
  mapping ANY intent word to a motif (default scales). `textured_wall_mesh(motif=…)`; planner carries
  the chosen motif on the SURFACE_PATTERN feature; every motif proven watertight + seamless. Any pattern
  on any round wall via one robust substrate. 422 tests (+18). Also fixed per-part understanding scoping
  (anchor each part to its own geometry — handle≠drinkware) + added the NL **edit UI** to the palette.
- 2026-06-27: **Bidirectional editing** (ADR-016) — edit in words, references never break.
  `genome/edit.py`: a lens (genome↔parameters, laws tested), `Edit` deltas, `parse_edit` for NL,
  persistent feature ids + IR parameter names across an edit (topological-naming problem solved at
  the parameter level), incremental recompute. New `POST /api/codegen/edit`. **Completes all 7
  breakthrough pillars.** 404 tests (+11).
- 2026-06-27: **Open-ended understanding** (ADR-015) — the LLM formalises the UNSAID into checkable
  requirements. Closed `RequirementSpec` on `PartPlan` + `REQUIREMENTS_PROMPT` over an allow-listed
  metric vocabulary; `genome/intent_expand.py` is the correct-by-construction filter (drops unprovable
  proposals), survivors merged into the spec + proven by the certificate. Removes the frame-seed
  ceiling (general for any object) while staying machine-checkable; strict-schema-clean. 393 tests (+6).
- 2026-06-27: **Compositional assembly** (ADR-014) — typed interfaces + system-level proof.
  `genome/assembly.py`: ports derived from geometry, `compatible()` typed relation, system-level
  Grübler–Kutzbach mobility (via dfm) → an object-level re-checkable certificate (interfaces match,
  connected, rigid). New `POST /api/codegen/assembly`. The whole mug is now a *proven* rigid
  assembly, not pairwise hope. 387 tests (+7).
- 2026-06-27: **Function gate** (ADR-013) — qualitative "does it WORK". `genome/function_model.py`
  infers Functional-Basis functions from purpose + structure (general) and proves the teleological
  chain (contain→reachable cavity, convey→through-path, support→stands, couple→join). Catches the
  functionally-dead case (a sealed cup you can't fill) nobody else does. 380 tests (+6).
- 2026-06-27: **Understanding layer** (ADR-012) — object FRAMES infer the unsaid; the certificate
  proves it. `genome/understanding.py`: inheritance hierarchy (object→container→vessel→drinkware;
  pipe; handle) of frames whose requirement-templates encode what a thing SHOULD be; `resolve_frame`
  by keyword + functional inference + generic fallback (general, not a list); `derive_specification`
  merges the implied requirements into the spec + an assumption ledger (stated/inferred/derived).
  Frame inferences are advisory ("should", non-gating) and surface as `certificate.advisories`. "make
  me a mug" → drinkware frame → proves stable-base + useful-capacity + food-safe-wall the user never
  stated ("certified fit [drinkware]; proved 3 implied requirement(s)"). 369 tests (+17), ruff clean.
- 2026-06-27: **Certified CAD / design-as-proof** (ADR-011) — first pillar of the breakthrough plan.
  The deliverable becomes a (spec, model, proof) triple. `genome/spec.py`: a typed Specification whose
  requirements are composed GENERALLY from functional intent + geometry + process (hollow→capacity,
  opening→its function, bore, attached→seated, wall→process min-wall). `genome/certificate.py`: a
  proof-of-fitness certificate (per-obligation verdicts + margins) that is self-contained and
  INDEPENDENTLY RE-CHECKABLE (`recheck` catches a flipped verdict / faked ok / dropped obligation —
  the proof-carrying moat: re-verify without trusting the generator). Wired into codegen
  (`CodeGenResult.certificate`) + add-in ("✓ certified fit (N/N)"). Subsumes the ad-hoc
  functional/spatial/makeability strings. The mug certifies fit and computes it holds ~370 ml. Live
  frontier: none (fully offline/deterministic) — restart server + reload add-in to see it. 352 tests
  pass (+27), ruff clean. Plan: `../cad_copilot_breakthrough_plan_2026-06.md`.
- 2026-06-27: **Mesh-skin live fix** (commit `f686303`) — the ADR-010 texture skin imported via the
  wrong API (`ImportManager.createMeshImportOptions` doesn't exist); replaced with the verified
  `MeshBodies.addByTriangleMeshData` (no file; coords in cm; BaseFeature host in parametric designs).
  Live run confirmed: clean mug + filleted handle + "applied 1 textured skin(s)". (The scale MOTIF
  still reads as ripples, not imbricated scales — a separate understanding/rendering problem deferred
  to the breakthrough's intent layer; the robustness substrate itself is proven.)
- 2026-06-27: **Hybrid representation** (ADR-010) — the seven-track research landed. Root cause of the
  scale failure: B-rep feature ops are *partial* (fail on tangent/thin geometry = `NO_TARGET_BODY`).
  Fix: per-feature representation choice. **Shipped:** (a) Pillar A `genome/texture.py` — surface
  texture as a displacement field → ONE watertight mesh skin (proven closed across 144 params; no
  boolean to miss), new `CREATE_MESH_BODY` IR op across model/validator/executor (STL-import mesh body,
  non-fatal), `_surface_pattern` rewired off the fragile cut+pattern path; (b) Pillars C+D `genome/
  dfm.py` — DFM predicates + ISO-286 fits (reproduce textbook tables: H7/g6 Ø20 → 7..41 µm) +
  Grübler–Kutzbach mobility/loop accountant (four-bar → M=1, 1 loop); makeability certificate surfaced
  in the build result. 325 tests pass (+24), ruff clean. Live frontier: the Fusion mesh-body import.
  Research doc `../cad_copilot_robustness_research_2026-06.md`.
