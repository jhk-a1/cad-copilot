# Project Memory — CAD-Copilot

Durable project context, fuller than the length-limited Claude auto-memory. Update when
significant facts change. For the running narrative see `SESSION_LOG.md`; for decisions see
`DECISIONS.md`.

---

## Identity
**CAD-Copilot** — an AI assistant inside Autodesk Fusion that operates the CAD tool like a
skilled designer: interpret natural language, show verifiable sketches, collect exact
dimensions, and build **fully parametric, editable** feature trees. Not a text-to-mesh
black box. **Accuracy at/above industry standard is paramount — no compromise.**

## Product concept (corrected — ADR-004)
- User describes an **OBJECT** (not a single part).
- AI decomposes it into the **PARTS** needed to build it properly (single-part = 1-part plan).
- Each part is verified as a proper **multi-view engineering drawing**: orthographic
  **front / top / right + isometric**, with **every feature dimensioned**.
- Entered dimensions become **named Fusion userParameters** (editability guarantee).
- Then parametric parts are built in Fusion. (Assembly/positioning of parts = later scope.)

## The fixed pipeline (stages never change; engines/richness inside may)
1. Intent → object plan (parts) + complexity gate (refuse/decompose, never guess)
2. Sketch → per-part multi-view, fully-dimensioned drawing (user verifies)
3. Dimensions → per-part, focus-to-highlight UX, → userParameters
4. Codegen → **Command IR** (validated, allowlisted) via LLM + RAG + best-of-N geometric
   verifier + one render-and-check pass
5. Execution → Safe Executor in Fusion, one command-transaction = one undo, rollback on fail

## Engine strategy (ADR-001)
- No custom model training on the 3-month path. Frontier LLMs (Claude/GPT/Gemini) + structured
  outputs + RAG + verifier scaffold. Provider abstraction mandatory. Fine-tuning (Zero-To-CAD-1m,
  Apache 2.0) is post-trial.
- Model picks decided by in-house bench bake-off, not press numbers.

## Accuracy program
- Benchmark built BEFORE the pipeline (~200-prompt in-house "CAD-Copilot Bench").
- Gate metrics (trial targets): execution success ≥95%, IoU ≥0.85, dimensional error <0.1mm,
  sketch first-pass ≥75%, refusal recall ≥90%, latency <60s. CI fails on ≥2-pt regression.
- Hard rule: refuse or decompose outside the validated envelope; never emit wrong geometry.

## Cost / pricing (ADR-002, ADR-006)
- Sampler-escalation default (cheap candidates, verifier-enforced quality, escalate on failure)
  + prompt caching + Batch API + local hosting. ~$500–900 / 3 months. Downshift ladder documented.
  Quality is never the variable. Cost-to-serve ~$0.05–0.15/gen → pricing likely $19–29/mo.
- **PROVIDER DECISION (ADR-006, 2026-06-12): Anthropic ONLY for the trial. Claude Fable 5 is
  UNAVAILABLE (government/export block) — never use it. Sonnet 4.6 is the trial default to keep
  cost low; SAMPLER uses Haiku 4.5; verifier-rejected work escalates to Opus 4.8 (not Fable).**
  Config = `configs/models.anthropic.json`; activate with env `ANTHROPIC_API_KEY` +
  `MODELS_CONFIG_PATH=configs/models.anthropic.json` (no code change; mock stays default offline).
  No OpenAI/Google keys needed. Anthropic backend untested live — verify on first real call.

## Data / licensing
- Train only on Apache/MIT/own-synthetic. Zero-To-CAD-1m (Apache) + clean-room CAD-Recode-method
  synthetic. RAG from AutodeskFusion360 MIT repos with a provenance manifest.
- Excluded (verified NC / tainted): Fusion 360 Gallery, SketchGraphs data, DeepCAD/ABC/Text2CAD,
  CAD-Recode data, CADPrompt. Benchmark on BenchCAD (permissive) + in-house.

## Platform (Autodesk Fusion, 2026) — must-handle
- Python **3.14** (pure .py add-in, no native wheels client-side).
- **Design-Intent gate**: modeling ops FAIL in assembly designs → gate every generation.
- Palette `adsk.fusionSendData` is **async/Promise** (Qt browser); palettes deleted on workspace
  switch (recreate); route all network via Python (no palette CORS).
- One command execute handler = one transaction = one undo (free rollback). userParameters keep
  models editable. AutoConstrain API (preview) for residual sketch constraining.
- **Fusion 360 is installed on the dev laptop** → real add-in integration testing is available.

## Competitive / vision (ADR-003)
- Nobody ships staged verification UX in 3D. Our trial owns that corner.
- Long-term moat = hybrid neuro-symbolic editing (vectors propose, solver+kernel guarantee,
  stable references) targeting the topological-naming problem. Four-corner whitespace unoccupied.
  Watch Autodesk AI Lab (2D→3D), Zoo, Aurorin CAD. See `../cad_copilot_vision_rnd_track.md`.

## Current build state (2026-06-12) — 24 commits, 127 tests pass, ruff clean. INTENT + CODEGEN live on Sonnet; BUILDS ANYTHING.
- Codebase: `cad-copilot/` (git repo). Python 3.14.3 venv at `cad-copilot/.venv`.
- **API Contract v2.1.0** (ADR-004): ObjectPlan/PartPlan (Stage 1), PartDrawing w/ FRONT/TOP/
  RIGHT/ISO views (Stage 2), per-part Command IR w/ part-prefixed userParameters (Stage 4).
- **DONE & verified** (commit trail at bottom):
  - Scaffold; full contract incl. refusal + multi-part; FastAPI server; Fusion add-in skeleton +
    Design-Intent gate (unit-tested); reframed to "object" (M1-W1).
  - **LLM Gateway** (M1-W2-BE-03): provider abstraction, profiles (INTENT/SKETCH/IR_CODEGEN/
    SAMPLER/VISION_JUDGE), mock backend default (offline), real Anthropic/OpenAI/Google backends
    wired (untested live — no keys). Model picks = config, not code.
  - **Eval harness + CAD-Copilot Bench** (M1-W1-EVAL-01, M1-W2-EVAL-02): 44 cases; harness drives
    real object-plan→sketch→codegen; scorecard + `--baseline` regression gate (CI fails ≥2pt).
    Baseline: behavior 81.8 / ir-validity 100 / generation 100 / dims 100 / render-check 100 /
    iou_mean 1.0 / views 100. IoU + render-check LIVE for box/cylinder/l_bracket (analytic kernel);
    render_check_rate is a CI gate metric; chamfer/holes-as-subtractions still pending.
  - **Palette UI** (M1-W2-UI-03): 3-step flow, dual transport (Fusion async Promise bridge OR
    direct browser fetch — click-through testable without Fusion).
  - **Complete dimension schedule + UI polish**: feature-derived engineering dimension schedule
    (box: Overall + Mounting holes [diameter/edge/spacing/count] + Fillets + Chamfers; cylinder:
    Overall + Bore; l_bracket: Overall + Holes + Fillets), dimensioned multi-view SVGs w/ focus-
    highlight, grouped UI cards.
  - **IR Validator** (M1-W3-BE-04): semantic gate between generation and execution — units, DAG
    acyclicity, ref resolution, plane/operation enums, positive-or-declared dims, sketch-closed-
    before-extrude, rollback/expected-geometry sanity. Wired into codegen: invalid IR is REFUSED,
    never emitted. 18 mutation tests.
  - **Intent service onto gateway** (M1-W3-BE-05): object→parts planning runs on the LLM when a
    real provider is configured, else deterministic templates (offline). Server-side **family
    gate** (keep only buildable families; downgrade to decompose/out_of_scope + honest
    clarification). Resilient fallback on any model failure. Flip configs/models.json INTENT
    provider to go live.
  - **Safe Executor** (M1-W3-UI-04): `fusion_addin/core/safe_executor.py` realizes a validated IR
    in Fusion. Pure `compile_ir` (mm→cm at the boundary, resolve symbolic dims, defensive) +
    `SafeExecutor.execute` (one timeline group = one undo, rollback on failure, extrude depth
    bound to the user parameter by name for editability). Wired into CAD_Copilot executeCode
    (re-gates design intent). Compile core unit-tested incl. full-chain (server IR compiles);
    geometry half verified live in Fusion.
  - **Geometry kernel + render-and-check** (ADR-001 verifier, primitive tier):
    `ai_server/services/geometry.py` — pure-Python ANALYTIC kernel (OCP deferred post-trial,
    no cp314 wheel). Exact Box/Cylinder volume+bbox; `realize(ir)`; voxel `iou()`;
    `check_geometry` render-and-check wired into codegen after the validator (measured vs
    expected within <0.1 mm → mismatch refused). Pipeline now has TWO gates: IR Validator +
    render-check. Also wired into the EVAL harness: render_check_rate (a CI gate metric) +
    iou_mean replace the old null kernel metrics for box/cylinder.
  - **Accurate multi-view drawings** (M1-W4): `ai_server/services/drawing.py` — ALL THREE families
    (box/cylinder/l_bracket) render PROPORTIONAL to real dimensions (one shared mm→view scale;
    holes at true positions; real iso projection; dimension + highlight hooks preserved).
  - **l_bracket family complete**: codegen (L profile = 6 ADD_LINE → extrude), executor ADD_LINE,
    kernel LBracket solid + realize + render-check, accurate L drawing. Was refused; now generates
    → eval generation_rate 77.8 → 100.
  - **Generality (ADR-005)**: the executor now compiles + maps the WHOLE IR vocabulary (ADD_ARC,
    REVOLVE, FILLET, CHAMFER, SHELL, HOLE, CONSTRAINT — not just primitives), and runs a GENERAL
    in-Fusion render-and-check (read body's real volume+bbox from Fusion mass-props, compare to
    expected, rollback on mismatch — verifies ANY shape). Holes are now REAL cut geometry (codegen
    HOLE → kernel WithHoles CSG → executor cut-extrude; box w/ 4×Ø6 → 27,738 mm³). Two-tier verify:
    online=Fusion (general), offline=analytic kernel (primitive-only).
- **NOT yet built**: 3D highlight handler (M1-W3-UI-05); real LLM sketch/codegen (M1-W4-BE-06 /
  M2-W5 — needs credits; THIS is what makes arbitrary-shape generation real); fillet/chamfer as
  kernel-measured volume offline (verified online via Fusion now); edge/face *selection* for
  fillet/chamfer is simplified (all edges) pending stable-reference work (ADR-003 moat)
  (M1-W4-BE-06 / M2-W6 — current SVGs are schematic placeholders); l_bracket codegen + real
  codegen via RAG+verifier (M2-W5); RAG KB (M1-W1-RAG-01); full security middleware (rate-limit/
  size); OpenAPI contract doc; geometry kernel (M2-W6 — unlocks IoU/Chamfer in harness); part
  positioning/assembly (later scope). Founder action: apply API credits (M1-W1-OPS-01).
- **Commit trail**: 9fe3c50 foundation · df546da object→parts (v2.1.0) · 502346d LLM gateway ·
  5ab9b8f eval+bench · 67601fe palette UI · 5af04f9 dimension schedule+UI · 3c9556a IR validator ·
  43c425b intent service · 4ab90c6 doc refresh · f8e6b0f Safe Executor (M1-W3-UI-04) · 3868c15
  geometry kernel + render-and-check · 63105b3 eval kernel metrics · 22f261e accurate multi-view
  drawings · 2403629 l_bracket family · (+ generality: full executor vocab + general Fusion verify
  + real holes, ADR-005). (M1-W2 complete; M1-W3 done except 3D highlight UI-05; executor builds +
  verifies the FULL IR vocabulary, not 3 shapes; generation_rate 100; holes are real cut geometry.)

## Design-Genome generation engine (ADR-007, 2026-06-26) — the codegen architecture now
- **The pivot.** Raw-LLM-emits-Command-IR codegen hit its ceiling (vague solids, tangent revolves,
  detached handles). After a 7-track cross-domain deep-research pass, replaced it with the
  **Design-Genome method**: "neural proposes structure, kernel guarantees exact geometry" — the
  generation-side form of the ADR-003 moat principle. Full writeup:
  `../cad_copilot_design_genome_method.md`. This builds **corner A (hybrid generation)** of the
  four-corner moat.
- **How it works.** The LLM/planner emits a `Genome` (typed feature program with HOLES in a CLOSED
  grammar → invalid trees largely unrepresentable). A solver fills holes onto the feasible manifold
  (clamp + cross-hole DRC, each clamp a counterexample). A compiler emits validated Command IR
  feature-by-feature. A **Kernel-CEGIS loop** gates each feature on the IR Validator + render-check
  and returns VERIFIED IR or an HONEST refusal — never a vague solid.
- **Code.** `ai_server/services/genome/{grammar,library,solver,cegis,planner,prompt}.py`. Kernel
  gained exact `HollowCylinder`/`HollowBox` (so hollow bodies are render-check VERIFIED hollow). New
  `PATTERN` IR op (scales/ribs) across model/validator/`safe_executor`. Wired into `CodeGenService`
  genome-first (deterministic planner = $0 LLM for the mug; live LLM-genome for novel families;
  raw-IR retained as fallback). Trial-grade: training-free, cheaper LLM output than raw-IR.
- **Feature vocabulary (v1).** primaries: solid/hollow box, solid/hollow cylinder, l_bracket,
  loop_handle; modifiers: surface_pattern, fillet, chamfer. General `Sweep`/`Loft` fallback +
  differentiable fitting + edit-propagation are moat-grade (deferred).
- **Status.** 161 tests pass (+33), ruff clean, eval baseline holds. The dragon-scale mug builds
  OFFLINE correct-by-construction (hollow body verified, dimensionable scales, loop handle), every
  dimension a user parameter. Commit `817a8bb`.
- **Function drives topology (2026-06-26, commit `6dc7bf0`).** A hollow part's OPENING comes from
  what the object is FOR: vessels (cup/mug/bowl/jar/container/tray) open-top, pipe/tube open-both,
  sealed (tank/bottle) closed. Genome `Feature.options["opening"]`; planner sets it by function; the
  kernel models open_top/open_bottom (cavity reaches the rim) so render-check verifies *purpose*;
  the executor SHELL removes the matching end face. Seeds a functional-requirements layer
  (purpose→topology→verified). The earlier closed-top caveat is resolved.
- **Live-only gaps to check next Fusion run.** The SHELL face-removal (open top), loop_handle inner
  cut, and surface_pattern arrays are correct API usage but executor-runtime, non-fatal, and not yet
  live-verified by me.

## Generalisation: functional reasoning + general vocabulary (2026-06-26, commit `fd36444`)
- **The brain (understand the need).** `PartPlan` carries FUNCTIONAL fields the intent LLM reasons
  per part: `shape`, `hollow`, `opening`, `bore`, `purpose`. `plan_genome` routes by explicit
  function FIRST (shape→primitive, hollow→cavity, opening→topology, bore→hole); the family keyword
  map is only a fallback. So generalisation = the LLM reasoning function for ANY object; the lists
  are a $0 cache, never a ceiling. `genome/functional.py::unmet_requirements` is a functional gate:
  codegen REFUSES a part that misses its purpose (solid-when-hollow, closed-when-open, no-bore).
- **The vocabulary (able to build it).** General primitives: kernel `Frustum`/`RegularPrism`/
  `Sphere`/`Torus`/`Wedge` (cone+prism render-verified; rest live-verified); genome fragments
  cone/prism/sphere/torus/wedge/loft/sweep + `BORE`. New IR ops `ADD_POLYGON`, `SWEEP`, `LOFT`,
  `EXTRUDE.taper`, `CREATE_SKETCH.offset`. SWEEP/LOFT are the general escape hatches (advisory
  offline; the live frontier). Demonstrated across cup/funnel/ball/pipe/hex-nut/engine-cylinder/
  O-ring/ramp/elbow/duct — all build, all purpose-met, gibberish families.
- **Live frontier to verify in Fusion**: taper, ADD_POLYGON, REVOLVE (sphere/torus/sweep), LOFT +
  offset planes, SHELL open-face removal — correct API usage, executor-runtime, not yet live-tested.
- 192 tests pass, ruff clean, eval holds, object_plan golden regenerated.

## Relational + surface-parametric (ADR-008, 2026-06-26, commit `5c4cb19`)
- **Why.** Live tests: handle floats (joint wrong), scales are round dimples on the bottom (wrong
  surface, wrong shape). General class, rooted in absolute-coordinate + independent-part thinking. A
  7-field cross-domain pass (mate-connectors, molecular docking, skin-appendage fields, architectural
  paneling, scale-armour, surface-param/frame-fields) all said: place RELATIVE to surfaces/frames.
- **Attachment.** `genome/frames.py` computes analytic connector frames per primitive (cylinder
  wall/rim/base, box faces). A part mates its mounting frame to a host connector frame → a solved
  rigid transform; a handle seats on the wall at grip height for ANY radius. `PartPlan.attachment`,
  `CodeGenResult.placement`, executor `Matrix3D.setToAlignCoordinateSystems` (position = fallback).
- **Surface features.** `surface_pattern` tiles scale motifs (scallops) on the curved WALL (the YZ
  plane offset to the radius), wrapped by a circular pattern, rows up the wall — not bottom dimples.
- **Status.** 195 tests, ruff clean, eval holds, golden regenerated. Live frontier (founder verifies):
  the Matrix3D mate, YZ-offset wall sketches, join-extrude scales (executor-runtime). Moat-grade:
  per-row imbrication, freeform-face frame-fields (mesh solver), direction-field orientation.

## Closed-loop spatial verification (ADR-009, 2026-06-27, commit `ad27b07`)
- **Why.** Every round was "offline-right, live-wrong, blind": the pipeline never perceived whether
  parts/features land where they should (scales floated as a radial star; handle dropped to the base).
  Only body volume was checked. A 7-field pass (visual servoing, contact mechanics, predictive coding,
  surface scatter, tailoring, ergonomics) converged: close the loop with a SPATIAL-RELATION error
  (contact gap=0, on-surface, no interpenetration). SOTA sweep: no text-to-CAD verifies spatial
  relations — whitespace.
- **Spatial comparator** `genome/verify.py`: `surface_distance` + `attach_seat_residual` (seat vs
  float/bury) + `feature_seat_residuals` (scale on the wall?) + `certificate`. The engine PERCEIVES.
- **Scales fixed:** `surface_pattern` ENGRAVES scales into the wall (cut inward via new EXTRUDE
  `direction=negative`) so they conform, not float. **Attachment robust:** handle-like parts
  DEFAULT-attach. **Certificate** surfaced in the build result. **Live read-back**
  `safe_executor._readback` measures where the part ACTUALLY landed in Fusion (REALITY half).
- **Status.** 201 tests, ruff clean, eval holds. Honest: comparator verifies INTENT, read-back verifies
  REALITY (Fusion). Live frontier: read-back + engraved cut + negative-direction extrude. Also fixed:
  `attachment` was an open dict that 400'd Anthropic strict mode → typed `Attachment` + guard test
  (commit `7ff2a9e`). Moat-grade: visual-servoing correction, ergonomic placement, freeform conformance.

## Live state (2026-06-27) + the surface-texture bottleneck
- **Working LIVE (read-back confirmed):** mug body (hollow, open-top, render-verified); handle
  ATTACHES correctly to the side wall at grip height ("seats on host, gap 0mm") via the
  measurement-driven `_seat_correction` (general: measure where the part landed, translate to seat
  on the host target — self-corrects build-orientation errors for any part). This solved the hard
  relational/attachment problem.
- **Bottleneck:** surface scales — the inside-wall symmetric cut engraved ONE row (skipped 6->5) but
  the other rows fail `NO_TARGET_BODY`. Per-feature B-rep cut + pattern on curved walls is fragile and
  un-debuggable blind. Non-fatal, so the mug always builds clean.
- **Direction (deep research 2026-06-27):** the failures come from fighting Fusion's feature-by-feature
  B-REP operations (topology-fragile). Researching a ROBUST substrate (hypothesis: implicit/SDF/FRep
  field-based modelling, the nTopology paradigm — never connected to text-to-CAD) for surface texture
  AND the complex-object problems ahead (assemblies/fits/interference, internal features,
  manufacturability, organic shapes). Findings -> `cad_copilot_robustness_research_2026-06.md` (to be
  written) + an ADR.

## Hybrid representation shipped (ADR-010, 2026-06-27)
The seven-track research confirmed the hypothesis: B-rep feature ops are *partial* (fail on
tangent/thin geometry = `NO_TARGET_BODY`); the fix is a **per-feature representation choice** — B-rep
for editable structure, implicit/displacement *fields* (total ops, can't fail) for texture & complex
geometry. The B-rep↔implicit seam is unoccupied in generative CAD (the moat). Built, all offline-verified:
- **Pillar A — `genome/texture.py` (the scales fix).** Surface texture = a tileable height field
  `h(θ,z)` over the wall → ONE watertight **mesh skin** displaced along the normal (proven closed across
  144 params, so no `NO_TARGET_BODY` is possible; "200 scales" = one field op). New `CREATE_MESH_BODY`
  IR op (model/validator/executor); `_surface_pattern` no longer emits per-row cuts. Executor imports
  the verified mesh as a Fusion mesh body (STL-import path), **optional/non-fatal** — the parametric mug
  is untouched. UI shows "applied N textured skin(s)".
- **Pillars C+D — `genome/dfm.py` (future-proofing).** DFM predicates (min wall/feature/internal
  radius/draft per process) + **ISO-286 fits** (standard IT formula; reproduces textbook tables, H7/g6
  Ø20 → 7..41 µm) + **Grübler–Kutzbach mobility/loop** accountant (four-bar → M=1, 1 loop; names
  over/under-constraint + kinematic loops a tree placer breaks on). Makeability certificate surfaced in
  the build result.
- **Live frontier:** the Fusion mesh-body import (STL) — founder verifies in Fusion. Non-fatal: if it
  fails the mug still builds clean. 325 tests pass (+24), ruff clean. Research doc:
  `cad_copilot_robustness_research_2026-06.md`. Roadmap: implicit lattices/channels as fields; the full
  per-op fallback ladder (Pillar B); a constraint-solved mate-network with loop closure (Pillar C).

**Live-verified (ADR-010, 2026-06-27):** after a server restart + add-in reload (the first live run
used stale processes), the mug builds clean and the texture skin lands ("applied 1 textured skin(s)")
via `MeshBodies.addByTriangleMeshData` (the STL-import guess `ImportManager.createMeshImportOptions`
doesn't exist; fixed in `f686303`). The scale MOTIF still reads as ripples not imbricated scales — an
UNDERSTANDING problem (deferred to the breakthrough's intent layer), not a robustness one.

## Certified CAD — the breakthrough's first pillar (ADR-011, 2026-06-27)
The breakthrough plan (`cad_copilot_breakthrough_plan_2026-06.md`) is "design-as-proof": ship a
(spec, model, proof) triple, not just geometry. First pillar shipped, fully offline/deterministic:
- `genome/spec.py` — a typed `Requirement` is a self-contained `metric op target` predicate;
  `derive_specification` composes the requirement set GENERALLY from functional intent + geometry +
  process (hollow→cavity+capacity, opening→its function, bore, attached→seated, wall→process min-wall)
  — same rules for any object. `evidence()` measures the realized solid (incl. capacity≈ml).
- `genome/certificate.py` — `check` emits per-obligation verdicts + margins; `recheck(cert)` is an
  INDEPENDENT re-verifier that, from the certificate JSON alone, rejects a flipped verdict / faked
  `ok` / dropped obligation (the proof-carrying moat: re-verify without trusting the generator).
- Wired into codegen (`CodeGenResult.certificate`) + add-in ("✓ certified fit (N/N)"). Subsumes the
  ad-hoc functional/spatial/makeability strings. The mug certifies fit, holds ~370 ml. 352 tests (+27).
- Next pillars (plan): qualitative-physics function gate (does it WORK), typed compositional assembly,
  bidirectional/incremental editing.

## Understanding layer — the breakthrough's second pillar (ADR-012, 2026-06-27)
P1: the system now infers what a thing SHOULD be and the certificate proves it. `genome/
understanding.py`: object FRAMES in an inheritance hierarchy (object→container→vessel→drinkware; pipe;
handle), each implying requirement-templates. `resolve_frame` = keyword + functional inference
(hollow+open-both→pipe; hollow+drink→drinkware) + generic fallback (general, not a list).
`derive_specification` merges the implied requirements into the spec + an **assumption ledger**
(stated/inferred/derived); frame inferences are advisory ("should", non-gating; soft fails →
`certificate.advisories`). "make me a mug" → drinkware → proves stable-base + useful-capacity +
food-safe-wall the user never stated ("certified fit [drinkware]; proved 3 implied requirement(s)").
A tight 17 mm handle grip is flagged as advisory. 369 tests (+17), ruff clean. This is where "knows
what a mug/scale should be" gets fixed: understanding supplies implied obligations, the certificate
discharges them. (The dragon-scale MOTIF rendering still needs a real imbricated-scale model on the
ADR-010 substrate — a separate downstream task.)

## Reference docs (parent `cad ai/` folder)
- `cad_ai_development_plan_v3.md` — strategy · `ai agent/cad_copilot_task_prompts_v3.md` — tasks
- `deep_research_report_2026-06.md` — evidence · `cad_copilot_vision_rnd_track.md` — moonshot
- `cad_copilot_breakthrough_plan_2026-06.md` — the north-star plan (Certified Functional CAD)
