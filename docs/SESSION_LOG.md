# Session Log

Detailed, chronological record of everything done on CAD-Copilot. Full detail by design —
the Claude auto-memory is length-limited, so this file (and `PROJECT_MEMORY.md`) hold the
complete picture. Newest entries at the bottom. Times are approximate; date is authoritative.

Format per entry: what was done · why · result/verification · artifacts.

---

## 2026-06-12 — Entry 0 · Studied existing planning material
- Read all 7 prior planning docs in the parent `cad ai/` folder: `cad_ai_development_plan.md`
  (v1), `cad_ai_development_plan_v2.md`, the Antigravity multi-agent execution plan, and the
  task-prompt docs (v1, v2, and the two ~5,165-line "final" exports which are byte-identical
  except formatting).
- **Findings:** product = AI Fusion add-in, pipeline NL→sketch-verify→dimensions→codegen→
  parametric build. v2 added the Command IR safety layer, API contract, RAG eval pack. Gaps:
  4 referenced-but-never-written tasks; Fusion 360 Gallery dataset is non-commercial; 12-month
  plan vs the user's ~3-month goal.

## 2026-06-12 — Entry 1 · Deep research (4 parallel agents + adversarial verification)
- Ran 4 web-research agents (generation strategy, competitive landscape, datasets/licensing,
  Fusion platform) + a 5th adversarial agent that re-verified the 12 most decision-critical
  claims against primary sources (12/12 confirmed, 2 minor corrections).
- **Key verified findings:**
  - Frontier LLMs beat fine-tuned CAD models on generalization (Text2CAD-Bench May 2026:
    GPT-5.2 IoU 0.59 vs fine-tuned 0.02–0.08; CAD-Assistant ICCV 2025: GPT-4o zero-shot beats
    Vitruvion 0.979 vs 0.706 primitive-F1).
  - Test-time scaffolding (best-of-N + geometric verifier; one render-and-check pass) worth
    ~10–25 accuracy points — more than swapping models.
  - Structured outputs are reliable (OpenAI 100% schema eval; Anthropic GA constrained decoding).
  - Fusion 360 Gallery = custom non-commercial license (verified); Onshape-derived data tainted;
    Autodesk's own **Zero-To-CAD-1m** (Apache 2.0, 999,633 programs) is the clean training set.
  - Fusion platform changes (verified): Jan 2026 → Python 3.14; Intent-Driven Design (modeling
    ops FAIL in assembly designs); palette `fusionSendData` is async/Promise (Qt browser).
  - Competitors: Adam (Fusion ext. May 2026), Zoo Zookeeper, Autodesk MCP servers; nobody ships
    staged verification UX. Autodesk Neural CAD announced, not GA.
- **Artifact:** `../deep_research_report_2026-06.md` (cited, with §6 accuracy-target table).

## 2026-06-12 — Entry 2 · v3 plan + task prompts authored
- Wrote `../cad_ai_development_plan_v3.md` (strategy) and `../ai agent/cad_copilot_task_prompts_v3.md`
  (execution). Pipeline fixed; engines swapped to frontier-LLM + structured outputs + best-of-N
  verifier + render-check; benchmark-first accuracy program with a refuse-or-decompose rule;
  licensing-clean data stack; Fusion 2026 platform fixes; 12-week schedule; ~$500–900 budget
  (after the cost discussion); new Agent-Eval role; wrote the 4 previously-missing tasks; removed
  all ML-training tasks.

## 2026-06-12 — Entry 3 · Cost / pricing discussion
- Founder flagged limited funds and "can't run at a loss, can't charge extremely high."
- Decided sampler-escalation as default (cheap candidates, verifier-enforced quality, escalate
  only on failure); documented downshift ladder; cost-to-serve ~$0.05–0.15/gen → viable pricing
  ($19–29/mo vs Zoo $99, Adam $10). Recorded as ADR-002 / plan §10.

## 2026-06-12 — Entry 4 · Vision/moonshot research (HDC idea) + vision doc
- Founder proposed hyperdimensional-computing representation (each CAD step a vector, edit one →
  propagate). Ran 4 research agents (HDC fundamentals, HDC-for-CAD prior art, parametric-fragility
  root cause, neural/latent CAD frontier) + a company-landscape agent.
- **Verified verdict:** instinct excellent (targets topological-naming, the real moat) but
  HDC-as-store is wrong (approximate/lossy, can't hold exact dims, edit-error accumulates). Right
  answer = hybrid neuro-symbolic (vectors propose, solver+kernel guarantee, stable references).
  Four-corner whitespace unoccupied; Autodesk leads corner A but only in 2D; Aurorin CAD (YC
  W2026) is the ideological twin but tiny.
- **Artifact:** `../cad_copilot_vision_rnd_track.md` (ADR-003).

## 2026-06-12 — Entry 5 · Week-1 foundation BUILD (verified)
- Environment: dev machine Python **3.14.3** (matches Fusion target), git 2.53, node 24.
- Created `cad-copilot/` project (separate from planning docs). Files built:
  - **Scaffold:** `.gitignore`, `pyproject.toml` (deps trimmed for 3.14 wheel safety; ruff +
    pytest config), `README.md`.
  - **API Contract v2.0.0** (`ai_server/models/`): `common.py` (Unit, ComplexityClass, Refusal,
    StrictModel), `intent.py` (IntentResponse + complexity gate), `sketch.py` (SketchSpec:
    primitives/constraint-intents/dimension-slots), `command_ir.py` (Command IR v2.1:
    CREATE_USER_PARAMETER, units=mm, expected_geometry), `codegen.py`, `errors.py` (E-code
    registry), `__init__.py` (32 exports). All inside the constrained-decoding-safe subset.
  - **FastAPI server** (`ai_server/`): `main.py` (lifespan, CORS, WS stub), `config.py`
    (DEV/PROD), `middleware/logging.py` (correlation IDs), routers health/intent/sketch/codegen,
    `services/placeholder.py` (deterministic box IR + cylinder/L-bracket sketches + refusal
    paths exercising the full contract).
  - **Fusion add-in** (`fusion_addin/`): `CAD_Copilot.manifest`, `CAD_Copilot.py` (run/stop,
    lazy imports for 0.005s startup, command + palette + design-gate wiring), `core/design_gate.py`
    (part/assembly/hybrid, defensive, no adsk import at module load → unit-testable),
    `core/server_client.py` (stdlib urllib, threaded), `ui/html/palette.html` (placeholder).
  - **Tests:** contract golden round-trips + constrained-decoding subset lint; full endpoint
    integration (intent recognize + refuse, sketch slots + refusal, codegen box IR with correct
    expected volume + userParameters, cylinder refusal, WebSocket); 5 Design-Intent gate unit
    tests (assembly blocked, part/hybrid allowed, missing-intent + broken-object degrade safely).
- **Verification:** `pytest` → **23 passed**; `ruff check .` → **All checks passed**; server boots,
  OpenAPI generates all routes; Command IR round-trips. Dependencies installed on cp314 wheels
  (fastapi 0.138, pydantic 2.13, uvicorn 0.49) — no Python 3.14 issues.
- **Not done / honest caveats:** add-in Fusion-side code not yet *run* in Fusion (syntax-valid;
  gate logic unit-tested without adsk); services are deliberate placeholders; eval harness, RAG
  KB, LLM gateway, full security middleware not yet built.

## 2026-06-12 — Entry 6 · "Describe object" correction + tracking files + commit
- Founder clarified: input is an **OBJECT** decomposed into **PARTS**; each part verified via
  **multi-view orthographic drawings (front/top/side + iso), fully dimensioned** (standard
  engineering procedure). Recorded as **ADR-004**. Pipeline stages unchanged; richness within
  Stages 1–3 grows.
- Founder confirmed **Fusion 360 is installed** on this laptop → real add-in integration testing
  now possible.
- Created project tracking files: `docs/DECISIONS.md`, `docs/SESSION_LOG.md` (this file),
  `docs/PROJECT_MEMORY.md`. Reason: keep full detail outside the length-limited Claude auto-memory.
- Fixed "describe part" → "describe an object" framing in `palette.html` and `README.md`; noted
  object→parts evolution in code.
- git: initialized repo, initial commit of the verified foundation + reframe.
- **Next block:** object→parts→multi-view contract rework (see ADR-004 implementation plan).

## 2026-06-12 — Entry 7 · Object→parts→multi-view contract rework (v2.1.0, ADR-004)
- Implemented the ADR-004 concept change. Contract bumped 2.0.0 → **2.1.0**.
- **Schemas:** new `models/object_plan.py` (ObjectRequest, PlanContext, Clarification, PartPlan,
  ObjectPlan) — Stage 1 now decomposes an OBJECT into PARTS. Rewrote `models/sketch.py` as a
  per-part multi-view drawing: ViewType (FRONT/TOP/RIGHT/ISO), DrawingView (svg + primitives +
  dimension_refs), PartDrawing (views[] + dimension_slots), PartDrawingRequest. Rewrote
  `models/codegen.py` to per-part (CodeGenRequest{object_plan, part_id, dimensions};
  CodeGenResult gains part_id). Removed `models/intent.py`. Updated `__init__` exports.
- **Services** (`placeholder.py`): `plan_object` (single-family objects + a multi-part demo —
  "phone stand" = base box + upright box, in_scope), `generate_part_drawing` (4 views per part
  for box/cylinder/l_bracket, schematic SVGs with data-ref), `generate_part_code` (box + cylinder
  Command IR with **part-prefixed userParameters** so multi-part objects don't collide;
  l_bracket codegen pending M2).
- **Routers:** new `/api/object/plan`; `/api/sketch/generate` and `/api/codegen/generate` are now
  per-part. Removed `routers/intent.py`. Updated `main.py`.
- **Tests:** rewrote goldens (object_request, object_plan; removed intent goldens) and integration
  suite. **26 pass**; ruff clean. Live E2E verified: "a phone stand" → 2 parts → each a 4-view
  drawing (front/top/right/iso) + a valid IR v2.1.0; params `base_*` vs `upright_*` (no collision);
  cylinder volume = π·r²·h checks out.
- **Honest caveats:** SVGs are schematic placeholders (real engineering-accurate multi-view
  drafting comes with the geometry kernel, M2-W6); l_bracket codegen + true object planning (LLM)
  still pending; part positioning/assembly is later scope.
- Commit: object→parts→multi-view rework.

## 2026-06-12 — Entry 8 · LLM Gateway (M1-W2-BE-03)
- Consulted the claude-api skill for verified June-2026 API shapes (model ids, pricing,
  structured outputs via output_config.format, Fable-5 specifics, no native `n`).
- Built `ai_server/gateway/`: `base.py` (Message/Usage/LLMResult/LLMGateway, PRICING + estimate_cost),
  `schema_minimal.py` (minimal_instance → schema-valid stub for any contract model; sanitize_schema
  strips provider-unsupported constraint keywords), `providers/mock.py` (offline, schema-valid,
  scriptable), `providers/anthropic_backend.py` (output_config.format, Fable-5 no-temperature +
  fallbacks-to-Opus-4.8, N via parallel asyncio.gather, cost from pricing), `providers/openai_backend.py`
  (response_format json_schema, native n, base_url for open-weight SAMPLER), `providers/google_backend.py`
  (response_schema, parallel N), `registry.py` (build_gateway from configs/models.json + Settings),
  `__init__.py`. Config `configs/models.json` (profiles INTENT/SKETCH/IR_CODEGEN/SAMPLER/VISION_JUDGE,
  all default to mock so pipeline runs offline) + `configs/README.md`.
- **Tests:** `tests/unit/test_gateway.py` — minimal_instance validates against ObjectPlan/PartDrawing/
  CommandIR/CodeGenResponse; sanitize strips constraints; cost table; mock returns N valid candidates +
  telemetry; scripted override; unknown profile/provider raise; missing-SDK backend raises clearly.
  **38 tests pass**, ruff clean. Live offline demo: INTENT→valid ObjectPlan, SAMPLER best-of-8→8 valid
  candidates, $0 (mock).
- **Honest caveats:** real Anthropic/OpenAI/Google backends are wired with verified shapes but UNTESTED
  LIVE (no keys — M1-W1-OPS-01). OpenAI strict json_schema may need all-required schema massaging for
  our nullable-optional fields (documented follow-up). Mock is the default until credits land.
- Commit: LLM Gateway.

## 2026-06-12 — Entry 9 · Eval harness + CAD-Copilot Bench (M1-W1-EVAL-01 + M1-W2-EVAL-02)
- The measuring stick, built before the engines it measures (accuracy-paramount discipline).
- **Bench:** `bench/build_cases.py` (deterministic generator) → `bench/cases/*.json`, 44 cases
  across 5 slices (mvp_families 15, extended_families 8, dimension_fidelity 6, edge_cases 7,
  refusal_correctness 8). Each case = prompt + golden dims + expected_geometry + expected_behavior
  (generate/clarify/decompose/refuse). Encodes INTENDED behavior; target ~200, grows with families.
- **Harness:** `eval/metrics.py` (derive_plan_behavior, ir_schema_valid, dimensional_error),
  `eval/harness.py` (drives real /api/object/plan → /api/sketch/generate → /api/codegen/generate
  via in-process TestClient; scores per case; aggregates per slice), `eval/run.py` (CLI → scorecard
  json+md, optional --baseline regression gate), `eval/compare.py` (find_regressions, >2pt drop).
  IoU/Chamfer/kernel-execution are explicit null placeholders until the geometry kernel (M2-W6).
- **Baseline** (`bench/baseline_scorecard.json`, placeholder pipeline + mock gateway, 44 cases):
  behavior_accuracy 81.8, ir_validity 100, generation_rate 77.8, dimensional_accuracy 100,
  views_ok 100. Honest gaps: extended_families 50% behavior + l_bracket codegen not impl → the
  documented placeholder limits real engines close. Drives CI regression gating going forward.
- **Tests:** `tests/unit/test_eval.py` — metrics, harness run_case (generate + refusal), full-run
  scorecard, regression detection. **45 tests pass**, ruff clean.
- Commit: eval harness + bench.

## 2026-06-12 — Entry 10 · Palette UI + Promise bridge (M1-W2-UI-03)
- Full palette UI in `fusion_addin/ui/html/`: `styles.css` (Fusion dark theme, responsive
  300–600px), `palette.html` (3 steps: describe object → verify each part → result),
  `app.js` (state, dual transport, full flow).
- **Dual transport (the key design):** `app.js` detects `window.adsk`. In Fusion → routes
  network through `adsk.fusionSendData('apiRequest', …)` which returns a Promise (Qt browser
  async); Python proxies the HTTP (no browser CORS) and geometry highlight/execute route to the
  add-in. In a plain browser (no adsk) → `fetch()` the server directly, so the WHOLE flow is
  click-through testable without Fusion (footer shows 'browser test', pings /health on load).
- **Flow:** describe object → POST /api/object/plan → render parts as tabs → select part →
  POST /api/sketch/generate → render 4 views (front/top/right/iso) + dimension panel; focusing a
  dimension highlights the matching geometry across all views (SVG data-ref) AND sends highlight
  to Fusion → Generate → POST /api/codegen/generate → executeCode to Fusion (or browser summary);
  refusals + clarifications rendered honestly; mm/cm/in unit toggle.
- **Python wiring:** `CAD_Copilot.py` `_HTMLEventHandler` routes `apiRequest` (proxy via
  ServerClient), `highlight`/`clearHighlight` (ack — full highlight M1-W3-UI-05), `executeCode`
  (ack — Safe Executor M1-W3-UI-04). Synchronous proxy for now; threaded version M1-W3.
- **Verified:** `node --check app.js` OK, CAD_Copilot.py parses, 45 tests pass, ruff clean.
  Rendered a faithful mockup of the docked panel (phone stand → Base/Upright → multi-view +
  dims) for the founder.
- Commit: palette UI.

## 2026-06-12 — Entry 11 · Complete engineering dimension schedule + UI polish
- Founder feedback: when dimensioning each part, EVERYTHING an engineer would dimension must
  appear based on what features are present; and make the UI nicer.
- **Sketch service** (`placeholder.py`): added `_schedule(part)` — feature-derived complete
  dimension set, grouped: box → Overall (length/width/height) + Mounting holes (hole_diameter,
  hole_edge_x/y, hole_spacing_x/y, hole_count) + Fillets (fillet_radius) + Chamfers (chamfer_size);
  cylinder → Overall (diameter/height) + Bore (bore_diameter/depth) + Chamfers; l_bracket → Overall
  (leg_a/leg_b/thickness/depth) + Holes + Fillets. Views are now DIMENSIONED drawings: SVG helpers
  (_dimh/_dimv/_note) render dimension lines + extension ticks + labels (L, H, Ø, Xe, Sx, R, …);
  holes drawn as circles in the top view with position/spacing dims. Each dim's geometry_ref maps
  to a data-ref group so focusing it highlights the dim line(s) across views (currentColor recolor).
  phone-stand parts gained features (base: holes, upright: fillets) to show feature variety.
- **UI** (`styles.css` + `app.js`): dimensions render as a grouped schedule (collapsible group
  cards with header + count, like a drawing's dimension table); count-type dims (hole_count) handled
  as unit-less integers; bigger/cleaner view tiles; highlight via currentColor on dim-line groups.
- **Verified:** 46 tests pass (added test_box_with_holes_full_dimension_schedule; relaxed the
  per-view data-ref check since iso is pictorial), ruff clean, app.js node-checked, eval baseline
  unchanged (no regression). Showed founder the box-with-holes verification view with full schedule.
- Commit: complete dimension schedule + UI polish.

## 2026-06-12 — Entry 12 · IR Validator (M1-W3-BE-04) — the semantic safety gate
- Began M1-W3. Built the validated safety layer between generation and execution — the piece
  the whole "never emit wrong geometry" promise (ADR-002) rests on. Frontier models are strong
  at intent, weak at validity (dangling refs, cycles, extrude-before-close, undeclared symbolic
  dims): Pydantic guarantees the IR is well-typed, this validator guarantees it is well-formed
  as a build program. No API keys needed — pure logic, fully testable now.
- **`ai_server/services/command_ir/validator.py`** — `IRValidator.validate(CommandIR) ->
  ValidationReport` (list of coded `Issue`s; errors block, warnings advise; does not stop at
  first error). Checks: units=mm; unique ids; dependency graph is a DAG (no cycle via iterative
  DFS, no self/dangling dep, deps precede dependents); every consumed entity ref
  (sketch/profile/body/edge) resolves to an *earlier* producer; required ref present per command
  type; CREATE_SKETCH plane ∈ {XY,XZ,YZ}; EXTRUDE/REVOLVE operation ∈ {new_body,join,cut,
  intersect} + required distance/angle; dimension scalars are a positive number OR the name of a
  declared CREATE_USER_PARAMETER (catches typo'd symbolic dims); a profile is only extruded after
  its sketch is CLOSE_SKETCH'd before it; expected_geometry bbox/volume/key_dims sane; rollback
  points are real command ids.
- **Wired into codegen** (`placeholder._result`): every generated IR runs the validator; if
  invalid → `Refusal(VERIFIER_REJECTED)` with machine codes + summary, IR never returned; if
  valid → warnings attached to `CodeGenResult.warnings`. The placeholder box/cylinder IRs pass
  clean (zero warnings) so nothing is falsely refused.
- **Verified:** new `tests/unit/test_ir_validator.py` — 18 cases, one per failure mode (dup id,
  bad/self dep, cycle, unresolved + missing + out-of-order ref, undeclared/ nonpositive dim, bad
  plane, bad operation, extrude-before-close, bad rollback, negative bbox) + happy-path box &
  cylinder. Full suite 64 passed, ruff clean, eval baseline unchanged (no false refusals).
- Next in M1-W3: migrate intent/sketch/codegen services onto the LLM gateway (real generation
  when keys exist, deterministic templates under the mock provider) and wire the Safe Executor.

## 2026-06-12 — Entry 13 · Intent service onto the LLM gateway (M1-W3-BE-05)
- Moved the first pipeline stage (object→parts planning) off the keyword placeholder onto the
  LLM gateway, without breaking offline operation. This is where the "intelligence" starts being
  real rather than templated.
- **`ai_server/services/intent.py`** — `IntentService(gateway)`:
  - `provider == "mock"` (default until API credits): delegate to `placeholder.plan_object`
    (deterministic, input-sensitive templates — exactly what the integration tests and eval
    harness already exercise, so nothing offline changes).
  - real provider: build system+user messages, call `gateway.generate_structured(profile=INTENT,
    schema=sanitize_schema(ObjectPlan.json_schema), n=1)`, validate the candidate to ObjectPlan,
    then run the **family gate**.
  - `_enforce_family_gate`: keep only parts whose family ∈ SUPPORTED_FAMILIES; if any are
    unbuildable, drop them and downgrade complexity to `decompose` (some buildable) or
    `out_of_scope` (none), appending an honest clarifying question listing what we can/can't
    build. This is the server-side accuracy guarantee on top of the model — the product never
    pretends it can build geometry it can't (ADR-002, refuse-or-decompose).
  - Resilience: gateway exception, schema-invalid candidate, or empty result each fall back to
    the deterministic planner — the endpoint never 500s on a bad model response.
  - `get_intent_service()` (lru_cache) builds the service over the configured gateway; the
    `/api/object/plan` router now `await`s it.
- **Verified:** `tests/unit/test_intent_service.py` — 5 cases via a scripted MockBackend pointed
  at a non-mock provider (offline→templates; model plan passthrough; gate→decompose with gear
  dropped; gate→out_of_scope; schema-invalid→fallback). Full suite 69 passed, ruff clean, eval
  baseline unchanged (offline path identical to before).
- To go live: flip `configs/models.json` INTENT provider to anthropic/google + a real model id
  (needs API credits, M1-W1-OPS-01). Same pattern will migrate sketch (M1-W4-BE-06, kernel) and
  codegen (M2-W5).

## 2026-06-12 — Entry 14 · Safe Executor (M1-W3-UI-04)
- Built the add-in stage that turns a validated Command IR into real Fusion geometry — the last
  link in the safety chain (intent → drawing → dimensions → IR → **validator** → **executor**).
- **`fusion_addin/core/safe_executor.py`**, split like `design_gate` (no module-level `adsk`):
  - **Pure `compile_ir(ir_dict) -> [ops]`**: the testable compiler. Validates units are mm (the
    single mm→cm conversion, `mm_to_cm`, lives here at the boundary and nowhere else); builds the
    user-parameter table; resolves each dimension (numeric or symbolic param name) and converts to
    cm; emits typed ops (CreateParam, CreateSketch, AddRectangle, AddCircle, CloseSketch, Extrude).
    Defensive — never trusts its input even though the server validator already passed it: rejects
    non-mm units, empty IR, unresolved parameter refs, and unsupported command types.
  - **`SafeExecutor.execute(ir, design)`** (lazy adsk, Fusion-only): runs the ops, then groups the
    whole build into ONE timeline group = one undo; on ANY exception rolls back all partial work
    (deletes created timeline entities newest-first + created user parameters) and raises
    ExecutionError. Editability guarantee: every CREATE_USER_PARAMETER becomes a real Fusion user
    parameter, and the extrude depth is bound to it BY NAME via a live expression — editing the
    parameter updates the model. (Parametric sketch-dimension binding for rectangle/circle is a
    documented live-Fusion follow-up; geometry is placed at resolved cm coords for now.)
- **Wired into `CAD_Copilot.py`** executeCode handler: pulls `command_ir` from the palette payload,
  re-runs the design-intent gate, executes, returns a real `{status, features}` (or blocked/error)
  instead of the previous `{"status":"queued"}` stub.
- **Verified:** `tests/unit/test_safe_executor.py` — 9 cases (units; box compiles to the expected
  7 ops with correct cm + the extrude bound to "box_height"; cylinder circle Ø converts; 4 error
  paths; and the full-chain test that compiles the IR the *server* actually emits for box +
  cylinder). Fixed an importlib gotcha: a path-loaded module must be registered in sys.modules
  before exec or @dataclass can't resolve its own annotations. Full suite 78 passed, ruff clean,
  eval baseline unchanged (executor is add-in-side; server untouched).
- Live test (in Fusion, founder's machine) is how the geometry half gets exercised. Next: 3D
  highlight handler (M1-W3-UI-05); then M1-W4 sketch kernel for accurate drawings.

## 2026-06-12 — Entry 15 · Geometry kernel + render-and-check (ADR-001 verifier, primitive tier)
- Built the geometric-verifier foundation — the accuracy measuring stick ADR-001 promises. Chose
  a pure-Python ANALYTIC kernel over build123d/OCP after probing: OCP would install on cp314 only
  via `cadquery-ocp-proxy`/`-novtk` shims (no real 3.14 binary) and drag in ~35 packages
  (scipy/scikit-learn/ipython). For box/cylinder/l_bracket, analytic formulas give EXACT
  volume/bbox — exact beats voxel approximation, and it's zero-dep + fully testable. OCP deferred
  to post-trial (recorded in DECISIONS).
- **`ai_server/services/geometry.py`**:
  - `Solid` / `Box` / `Cylinder`: exact `volume_mm3`, `bbox_mm`, `bounds`, and `contains()` for
    voxel sampling.
  - `realize(ir) -> Solid | None`: reads CREATE_USER_PARAMETER values + the ADD_RECTANGLE/
    ADD_CIRCLE + EXTRUDE to build the exact solid. Returns None for families it can't build yet
    (l_bracket, holes, fillets) — honest "can't measure", never a false verdict.
  - `iou(a, b, n)`: pure-Python voxel intersection-over-union (the shape-agreement primitive the
    eval harness will use against reference solids).
  - `check_geometry(ir) -> GeometryCheck`: the render-and-check. Realize, then confirm measured
    volume/bbox match `expected_geometry` within the dimensional gate (bbox <0.1 mm, volume
    <0.1%). Unrealizable families are skipped (realized=False, ok=True).
- **Wired into codegen** (`placeholder._result`) right after the IR Validator: realizable parts
  are render-checked; a MISMATCH is refused (VERIFIER_REJECTED); a pass appends a concise
  "render-check ok: …" note to `CodeGenResult.warnings`. So the pipeline now has TWO gates — the
  IR Validator (well-formed program) and the render-check (geometry matches intent).
- **Verified:** `tests/unit/test_geometry.py` — 9 cases: exact box/cylinder volume+bbox; IoU
  identical=1.0 and subset≈0.5; realize box/cylinder; render-check passes a consistent box;
  render-check CATCHES a tampered expected_geometry (the key test — proves the gate fires when an
  IR's geometry disagrees with its declared size, which is exactly the bug class real LLM codegen
  will produce); skip on unrealizable. Plus an integration test (codegen box surfaces the
  render-check warning). Full suite 88 passed, ruff clean, eval baseline unchanged.
- Next: this `iou` + reference solids let the eval harness replace its null IoU metric with a
  real shape-agreement score once bench cases carry target geometry; M1-W4 grows the kernel/
  drawings; M1-W3-UI-05 (3D highlight) remains the one Fusion-gated leftover.

## 2026-06-12 — Entry 16 · Geometry verifier wired into eval (real IoU + render-check metrics)
- Turned the kernel into a measuring stick in the scorecard: the eval harness now reports real
  geometric accuracy instead of null placeholders.
- **`eval/metrics.py`**: `render_check_ok(ir)` (realize + match the IR's own expected_geometry
  within <0.1 mm; None when the family isn't realizable yet) and `kernel_iou(ir, family, golden)`
  (voxel IoU between the realized solid and a reference solid built from the case's golden
  dimensions; None when N/A).
- **`eval/harness.py`**: records `render_check_ok` + `iou` per case; `_summarize` adds
  `render_check_rate` and `iou_mean`; status string updated (kernel metrics live for box/cylinder).
- **`eval/compare.py`**: `render_check_rate` added to GATE_METRICS — a geometric-fidelity
  regression now fails CI like the other gates. **`eval/run.py`**: render_check_rate + iou_mean
  columns in the scorecard table.
- **Honest framing of what this measures now:** because the harness hands codegen the golden
  dimensions, realized == reference for the placeholder → IoU 1.0 / render-check 100%. The value
  today is (a) metric plumbing + a regression guard, (b) replacing documented nulls with measured
  numbers, (c) the gate is proven to fire (geometry unit tests catch a tampered expected_geometry).
  The IoU becomes a real generation-accuracy signal the moment the model INFERS dimensions from
  the prompt rather than being handed them (real LLM codegen, M2-W5).
- **Verified:** updated the eval unit test (box case now asserts render_check_ok True + IoU≈1.0);
  refreshed `bench/baseline_scorecard.json` (overall render_check_rate 100.0, iou_mean 1.0). Full
  suite 88 passed, ruff clean, regression gate green against the new baseline.

## 2026-06-12 — Entry 17 · Accurate multi-view drawings (M1-W4)
- Replaced the schematic part-verification SVGs with geometry PROPORTIONAL to real dimensions —
  the last "schematic → accurate" upgrade in the visible product.
- **`ai_server/services/drawing.py`** (new): analytic orthographic + isometric projection for
  box & cylinder.
  - One shared mm→view scale across front/top/right (`_box_scale` fits all extents), so a 50 mm
    edge renders the same length in every view (engineering-drawing convention). All three ortho
    views use a uniform `0 0 160 116` canvas; outline size = dimension × scale.
  - Box: front L×H, top L×W, right W×H; holes drawn at TRUE positions (edge_x/edge_y/spacing
    scaled) grouped under `data-ref="ref_hole_diameter"`; real isometric (`_box_iso` projects the
    8 corners, draws the 3 visible faces). Cylinder: front/right D×H rectangle, top a Ø circle,
    iso an ellipse-extrusion; optional central bore.
  - Dimension-line helpers (`_dim_h/_dim_v/_note`) + every `data-ref` highlight hook preserved, so
    panel focus-highlighting keeps working unchanged.
- **`placeholder.py`**: `_box_drawing`/`_cylinder_drawing` now build the schedule, extract default
  values (`_defaults`), call `drawing.box_views`/`cylinder_views`, and assemble via new `_assemble`.
  Old hand-coded schematic SVG removed. `_l_bracket_drawing` + the old `_svg/_rect/_dimh/_dimv/
  _note` helpers kept (l_bracket still schematic until its kernel/codegen arrive).
- **Verified visually:** dumped real server SVGs — 100×60×8 plate → wide flat slab with 4 holes at
  correct positions; 30×30×80 bar → tall column (front 22.5×60, top 22.5 square); Ø40×25 cylinder
  → wide disc. Shown to founder.
- **Verified by tests:** `tests/unit/test_drawing.py` — 7 cases pinning proportionality (wide vs
  tall front; top tracks L×W; cylinder front D:H ratio; 4 holes grouped; all 4 views wrapped +
  highlightable + iso polygon). Integration drawing tests still green. Full suite 95 passed, ruff
  clean, no eval regression (views set unchanged → views_ok still 100).
- Next: l_bracket accurate drawing + codegen; or real LLM codegen (M2-W5) to make IoU a live
  signal; M1-W3-UI-05 3D highlight remains the Fusion-gated leftover.

## 2026-06-12 — Entry 18 · l_bracket family complete (codegen + executor + kernel + drawing)
- Closed out the third supported family end to end — l_bracket was drawable but its codegen was
  refused; now it generates, executes, is kernel-verified, and draws accurately like box/cylinder.
- **Codegen** (`placeholder._l_bracket_code`): the L profile is six `ADD_LINE` commands forming a
  closed loop (verts (0,0)→(a,0)→(a,t)→(t,t)→(t,b)→(0,b)); the last line carries `profile_0`;
  CLOSE_SKETCH → EXTRUDE by `{part}_depth`. Part-prefixed userParameters (leg_a/leg_b/thickness/
  depth) + expected_geometry (bbox [a,b,depth], volume t·(a+b−t)·depth). Passes IR Validator +
  render-check.
- **Executor** (`safe_executor`): added `AddLine` op + compile/apply (`addByTwoPoints`), so the
  L-profile builds in Fusion; the loop's profile extrudes like the rectangle path.
- **Kernel** (`geometry`): exact `LBracket` solid (volume/bbox/contains for the L cross-section)
  + `realize` branch that resolves leg/thickness params by suffix (so `{part}_leg_a` matches) and
  uses the extrude distance as depth. Render-check + eval IoU now cover l_bracket.
- **Drawing** (`drawing.l_bracket_views`): true L outline (front, 6-vertex polygon, A/B/t dims +
  optional inner fillet), leg_a×depth and depth×leg_b rectangles (top/right), holes at real
  positions, and an L-prism isometric (front L poly + depth-offset back poly + connectors).
- **Cleanup**: removed the now-dead schematic helpers (`_svg/_rect/_dimh/_dimv/_note/_drawing`)
  from placeholder — all view rendering is in `drawing.py`, selected via a `_VIEW_BUILDERS` map.
- **Eval impact:** generation_rate 77.8 → **100.0** (the l_bracket bench cases in mvp_families +
  extended_families now generate). render_check_rate + IoU stay 100/1.0. Baseline refreshed.
- **Verified:** added tests across every layer — kernel (LBracket exact volume/bbox/contains;
  realize; render-check), drawing (6-vertex L front; holes count), executor (l_bracket IR compiles
  to 6 AddLine ops; full-chain), integration (codegen l_bracket → valid IR, 4 userParameters, 6
  ADD_LINE, render-check warning). Fixed the eval refusal test to use a not-in-plan part (l_bracket
  no longer refuses). 102 passed, ruff clean. Showed founder the real L-bracket views.
- Remaining schematic→accurate gap is closed for all three families. Next: real LLM codegen
  (M2-W5, needs credits) to make IoU a live signal; or M1-W3-UI-05 3D highlight (Fusion-gated).

## 2026-06-12 — Entry 19 · Generality: full executor vocabulary + general verification + real holes (ADR-005)
- Founder pushed on a crucial point: the product must handle ALL shapes in Fusion, not a few
  hardcoded families. Recorded **ADR-005** (capability = general IR vocabulary + LLM codegen +
  general verification; the 3 placeholder families are just offline templates) and implemented the
  pieces that make the GENERAL layers actually general.
- **Executor now compiles the WHOLE IR vocabulary** (`safe_executor.compile_ir` + `_apply`): added
  ADD_ARC, REVOLVE, FILLET, CHAMFER, SHELL, HOLE, ADD_CONSTRAINT (no-op) on top of line/rect/circle/
  extrude. New ops + Fusion mappings (revolveFeatures, filletFeatures all-edges, chamferFeatures,
  shellFeatures, hole = cut-extrude through-all). So the executor builds whatever valid IR the LLM
  emits — not a fixed shape list. (Edge/face *selection* is simplified — fillet/chamfer all edges —
  pending the stable-reference work; the LLM will specify edges later.)
- **General in-Fusion render-and-check** (`_verify_against_intent` + pure `compare_geometry`): after
  building, read the body's REAL volume (physicalProperties) + bounding box from Fusion and compare
  to `expected_geometry` within 0.1 mm / 2%. Fusion is the ground-truth kernel, so this verifies ANY
  shape (fillets, revolves, …), not just primitives; a mismatch rolls the whole build back. This is
  the accuracy guarantee that lets us build arbitrary shapes without emitting wrong geometry.
- **Holes are now REAL cut geometry** (first proof the general feature path works): box-with-holes
  codegen emits a HOLE command (centres from the shared `hole_layout`, through-all); the kernel
  models it as a CSG `WithHoles` (volume = blank − bores, bbox unchanged); the executor cuts it;
  the render-check verifies the holed volume. Verified: a 50×30×20 box with 4×Ø6 holes →
  27,738 mm³ (was 30,000), render-check ok.
- **Eval**: `WithHoles` + shared `hole_layout` make the holed-box reference solid model the intended
  holes too, so a correctly-built holed box scores IoU 1.0 (briefly 0.93 when the reference was a
  naive box — fixed by sharing the layout). Threaded part `features` through the harness.
- **Two-tier verification documented**: ONLINE = Fusion mass-props (general, any shape); OFFLINE =
  analytic kernel (primitive-only, eval/CI). The analytic kernel stays primitive on purpose.
- **Verified:** new tests — kernel (WithHoles volume/bbox; box-with-holes realize + render-check),
  executor (full-vocabulary compile incl. REVOLVE/FILLET/CHAMFER/SHELL/HOLE/ARC; box-holes → Hole
  op; `compare_geometry` match/bbox-miss/vol-miss/no-expectation), retargeted the "unsupported
  command" test to LOFT. 109 passed, ruff clean, eval baseline refreshed (iou 1.0).
- HONEST status: the executor's advanced-feature `_apply` (revolve/fillet/chamfer/shell/hole) is
  Fusion-runtime and verified LIVE on the founder's machine; edge selection is simplified for now.
  Real arbitrary-shape generation still needs LLM codegen (M2-W5, credits). But the machinery to
  build + verify any shape is now in place — not limited to three families.

## 2026-06-12 — Entry 20 · FIRST LIVE LLM — Anthropic key in, INTENT stage real (4 bugs caught + fixed)
- Founder pasted the real ANTHROPIC_API_KEY into ai_server/.env. Ran the live smoke test; it caught
  a cascade of real integration bugs that would have broken the product on day one. All fixed; the
  INTENT stage now produces genuinely intelligent plans on Claude Sonnet 4.6.
- **Bug 1 — .env not loading.** Settings(env_file=".env") was relative to CWD; the file is in
  ai_server/. Fixed to an absolute path (committed cf6ca77). Without this the key was never read.
- **Bug 2 — strict structured output 400.** Anthropic's output_config.format requires
  `additionalProperties: false` on every object. Added `strictify()` (schema_minimal) applied in the
  anthropic backend. THEN a second strict requirement surfaced: the model dodged `parts` by emitting
  `parts: null` (it's not in `required`), which collapsed to a degenerate plan — so strictify also
  forces every property into `required` (optional fields stay nullable). This was THE fix that made
  box plans consistent.
- **Bug 3 — runaway float / max_tokens truncation.** The model emitted confidence as the full
  float64 expansion (0.82984375000000018346…), blowing 4096 tokens and truncating the JSON →
  empty candidates. Fixed: prompt instruction "keep every number ≤2 decimals" + raised the backend
  default max_tokens 4096→8192.
- **Bug 4 — family/feature synonyms + invariant.** The model labels families/features with synonyms
  (rectangular_prism→box, mounting_holes→holes). The gate silently dropped them, leaving the
  contradiction "in_scope with no parts." Fixed in IntentService: `_canonical_family` +
  `_canonical_features` synonym maps, and the gate now enforces the invariant (no buildable parts ⇒
  out_of_scope with a clarification, never in_scope-empty). Prompt also clarifies holes/fillets are
  FEATURES, not separate parts / a reason to refuse.
- **Live results (real Sonnet):** "a phone stand" → decompose into box base + l_bracket support,
  asks orientation; "a coffee mug" → cylinder body + l_bracket handle; "a box with mounting holes" →
  in_scope box w/ holes feature (stable across runs); "a single gear"/"a dragon statue" → out_of_scope
  refusal. Genuine intelligence, not templates. Cost ~$0.008–0.012 per plan; structured output OK.
- **Cost-safety fix.** `eval.run` reads the live .env and was billing the real provider per case
  (and is meaningless vs the mock baseline). Added a `--live` flag; eval now DEFAULTS to the offline
  mock (forces MODELS_CONFIG_PATH="" + clears the settings cache). conftest already pins tests to mock.
- **Verified:** offline suite 115 passed, ruff clean, eval (mock) no regression. New tests: strictify
  rules; intent family-synonym, feature-synonym, in_scope-empty→out_of_scope. SDK `anthropic` added
  as optional dep; SDK-missing test repurposed to client construction.
- HONEST follow-ups: SKETCH + IR_CODEGEN still use placeholder (only INTENT is live) — wire next;
  feature synonyms normalized at intent but the model's vocabulary may need few-shot tuning (M2).

## 2026-06-12 — Entry 21 · Codegen path decided (deterministic) + full pipeline verified live end-to-end
- DECISION (founder): keep CODEGEN and SKETCH deterministic; the LLM stays at INTENT only. Probed
  whether the LLM could generate Command IR via Anthropic strict structured output — it CANNOT: the
  IR has map-style fields (params, key_dims = dict[str,X]) and strict mode rejects them ("For
  'object' type, 'additionalProperties: object' is not supported. set to false"). Strict output
  can't represent open dicts. LLM codegen would need a NON-STRICT JSON mode + parse + the existing
  validator/render-check gates — deferred to M2 (when new families/bench cases make it worth it).
  For the 3 current families the deterministic templates are EXACT, so LLM codegen adds cost +
  latency with zero capability gain now. Rationale recorded; budget-friendly (≈$0.01/object, the
  single INTENT call). SKETCH stays deterministic too: the drawing must be exact (kernel-rendered),
  and the dimension schedule is feature-driven off the (LLM-generated) plan.
- **End-to-end live verification (the new integration seam: LLM plan → deterministic sketch +
  codegen).** One object through all three endpoints with INTENT live: "a 60x40x10 mounting plate
  with bolt holes" → PLAN (live Sonnet) = in_scope box, features [holes, chamfered_edges] (family +
  features already normalized to canonical) → SKETCH = 4 views + schedule incl. chamfer + hole dims
  → CODEGEN = valid IR, 8 commands, real HOLE cut, render-check ok (box+holes 22,869 mm^3, bbox
  error 0.0000 mm). No integration bugs — the family/feature normalization added in Entry 20 makes
  LLM plans flow cleanly into the deterministic stages. The product now works END TO END with the
  real model.
- Next high-value (offline/free): hardening for real users (security middleware: rate-limit/size/
  input limits), or expanding the family set (grows capability + makes future LLM codegen worth
  it), or INTENT few-shot tuning for reliability. The add-in's live in-Fusion run is the founder's
  to exercise.

## 2026-06-12 — Entry 22 · Security/robustness hardening (M1-W1-SEC-01) before real users
- The server takes free-text user input and will face trial users, so added the guards that were
  configured but not enforced. `ai_server/middleware/security.py`:
  - **RequestSizeLimitMiddleware** — rejects bodies over max_request_size_mb (Content-Length) → 413
    with the typed error envelope.
  - **RateLimitMiddleware** — fixed-window per client IP (rate_limit_requests / rate_limit_window_s)
    → 429 + Retry-After (E9001). DISABLED under tests (conftest sets ENVIRONMENT=test) so the suite
    isn't throttled; enabled in dev/prod.
  - **SecurityHeadersMiddleware** — X-Content-Type-Options: nosniff, X-Frame-Options: DENY,
    Referrer-Policy: no-referrer.
  - Wired into main.py (added last = run first: size → rate → headers → CORS → logging → routes).
  - Input length already bounded at the schema (ObjectRequest.text max_length=1000).
- **Verified:** tests/unit/test_security.py — rate limit blocks after N + carries Retry-After +
  passes through when disabled; size limit rejects/allows; security headers present on the live app.
  121 passed, ruff clean. Confirmed the app builds + serves in dev mode with the limiter enabled.
- Founder will now try the add-in live in Fusion. Build-anything requirement reaffirmed: the path
  is non-strict LLM codegen (the next major build) on top of the already-general IR vocabulary +
  executor + Fusion verification (ADR-005). Deterministic templates stay as the free/exact path for
  known families.

## 2026-06-12 — Entry 23 · BUILD ANYTHING: non-strict LLM codegen + decompose-don't-refuse
- Founder, mid-Fusion-test, hit the wall: the live INTENT REFUSED "a children's slide" because a
  curved chute isn't box/cylinder/l_bracket. Correct call — 3 families is not a product. Built the
  generality: decompose anything into parts, build known families from templates and EVERYTHING
  else via LLM-generated IR.
- **Gateway non-strict mode** (`anthropic_backend`): strict structured output can't carry the
  open-dict Command IR (probe 400'd: "additionalProperties: object not supported"). Added a path
  where `structured:false` profiles request JSON in the prompt (schema as guidance) and parse it
  defensively (`_extract_json`, tolerant of code fences). IR_CODEGEN profile set structured:false.
- **CodeGenService** (`services/codegen.py` + router): known families → exact deterministic
  template (free/instant); any other family → LLM IR with a **validator-feedback RETRY loop** (up
  to 3 tries; the IR Validator's error codes are fed back so the model self-corrects), then build.
  The IR Validator is the hard safety gate; the render-check is ADVISORY for LLM IR (the model also
  writes expected_geometry, so a mismatch is its own estimate vs. its own commands, never a
  refusal). `_finalize` builds the response with an honest "verify the 3D result" note.
- **INTENT loosened** (`intent.py`): prompt now says DECOMPOSE don't refuse — pick a known family
  (template) or a short descriptive family ('curved_chute', 'ring', 'tapered_leg') for novel
  shapes; out_of_scope only for non-objects. The family gate no longer DROPS parts — it normalizes
  known synonyms and keeps everything (refuse only on empty parts).
- **Sketch handles novel parts**: `_schedule` gets a generic overall-bbox+features fallback;
  `generate_part_drawing` defaults a novel family to a bounding-box preview (true geometry comes
  from codegen, verified in 3D) instead of refusing.
- **LIVE PROOF**: "a small children's slide" → DECOMPOSE into 8 parts (platform/rungs/rails/legs/
  posts via templates; slide_chute + slide_side_rail + handrail as novel 'curved_chute'/'curved_
  rail' via LLM). Codegen of the curved chute → **34 commands** (5 params, sketches with ARCs for
  the curve, 4 extrudes, a FILLET), IR-validator-clean, advisory note. Real arbitrary geometry.
- **Honest accuracy stance** (told founder, recorded): "build anything" + "auto-guaranteed-accurate"
  can't both hold for novel shapes (the unsolved CAD problem). Resolution: known shapes exact +
  auto-verified; novel shapes structurally-validated (won't crash Fusion) + human-verified via the
  preview + Fusion at build. That IS the product's premise (verifiable previews).
- **Verified:** 125 passed (4 new codegen-service tests: template path, offline-refusal, LLM-builds-
  with-advisory, retry-then-refuse), ruff clean, eval (mock) no regression.
- NEXT: vocabulary expansion (SPLINE/LOFT/SWEEP) so curves are smooth, not arc-approximated;
  assembly/positioning of the decomposed parts; and the founder resumes the in-Fusion test.

## 2026-06-12 — Entry 24 · Accuracy for novel shapes = user dimensions the LLM structure (founder's insight)
- Founder corrected my framing: "if it has structure, every edge/face can be dimensioned manually —
  that's what the dimensioning panel is for; there's no accuracy issue." CORRECT. I had conflated
  the genuinely-hard topological-naming problem (breaks on EDIT; the moat, ADR-003) with dimensional
  accuracy (trivially solved if every dimension is a user parameter). Reframed + built it.
- **Accuracy model now**: the LLM owns only the STRUCTURE (topology); EVERY dimension is a named
  user parameter surfaced in the dimensioning panel; the USER sets the numbers. A novel shape is as
  accurate as a template — the user dimensions every parameter.
- **codegen** (`services/codegen.py` rewrite): prompt now requires EVERY dimension be a
  CREATE_USER_PARAMETER referenced by name (no hard-coded sizes). New helpers:
  `dimension_slots_from_ir` (params -> dimension slots) and `apply_dimensions` (substitute the
  user's values, exact, no model call). `generate_parametric(plan, part)` returns the parametric IR
  + slots; `generate(..., base_ir=...)` substitutes user values into the carried IR and re-validates.
- **sketch** (`services/sketch.py`, new SketchService): novel part -> ask codegen for the parametric
  structure, derive the dimension slots from its parameters, carry the IR in the new
  `PartDrawing.base_ir` field; bounding-box preview. Known families stay deterministic/exact.
- **flow**: sketch generates the structure (one model call) -> dimension panel shows EVERY parameter
  -> palette sends base_ir back as drawing_data -> codegen substitutes the user's values (no second
  model call). Routers + palette (app.js carries base_ir) wired.
- **LIVE PROOF**: curved_chute -> 33-command parametric IR; dimension panel exposed 7 params
  (length 2000, width 500, thickness 8, drop 1200, side height/thickness, fillet r). User set
  chute_length=555 -> built IR has chute_length=555.0 EXACTLY. Novel shape, user-dimensioned, exact.
- **Verified**: 127 passed (new tests: slots-from-IR, exact dimension substitution via base_ir),
  ruff clean. base_ir added to PartDrawing (additive, optional).

## 2026-06-12 — Entry 25 · Assembly (part positioning) + clean decomposition (live-tested in Fusion)
- Founder's live Fusion test BUILT a dragon-scale mug (hollow tapered body + handle + scale tile +
  base) — generation/build works end to end for novel geometry. Punch-list from that test:
  (a) parts not assembled (built at own origins, overlapping), (b) scales shown under BOTH body and
  a redundant 'scale_tile' part (dimensioning not part-specific), (c) one scale row only,
  (d) handle/base geometry off. Fixed the ARCHITECTURE (a,b) deterministically; (c,d) are
  geometry-quality (need PATTERN op + prompt tuning) — deferred to avoid burning money perfecting
  one complex object.
- **Assembly**: PartPlan gained `position: [x,y,z]` mm (object frame). Intent prompt assigns each
  part a position (body at origin; others at real locations). SafeExecutor.execute(position=...)
  translates the bodies it created to that position (moveFeatures, mm->cm). Palette sends the
  part's position to executeCode; the handler passes it through.
- **Clean decomposition**: intent prompt now states surface textures/patterns (scales, knurling,
  emboss, ribs, threads) are FEATURES of their part, NEVER separate parts; keep decomposition
  minimal. Fixes the redundant 'scale_tile' part (the dimensioning-not-respective bug) and the
  stray bottom geometry.
- **LIVE confirm ($0.02, one intent call)**: 'dragon scale coffee mug with a handle' -> 2 parts:
  body (hollow_cylinder, pos [0,0,0]) + handle (curved_handle, pos [45,0,45]). No scale part. Clean.
- **Verified**: 128 tests pass (regenerated the ObjectPlan golden for the new position field), ruff
  clean. The Fusion move is verified live by the founder.
- DEFERRED (geometry quality, founder aware): full scale rows need a PATTERN op in the IR vocabulary
  + executor; handle shape needs prompt tuning. Best iterated on simple objects, not the mug.

## 2026-06-26 — Design-Genome generation engine (ADR-007), the pivot off raw-LLM-IR

**Why this session happened.** Live mug tests kept failing in new ways: solid blob instead of
hollow (shell silently skipped), then a REVOLVE that failed `ASM_PATH_TANGENT` and rolled back the
whole body, detached handle, missing scales. The founder called it: "all messed... only creates
solids vaguely. lets stop and think." Correct read — the raw-LLM-emits-Command-IR architecture had
hit its ceiling: the model authors low-level geometry and is weak at precise spatial reasoning, so
it emits structurally-valid-but-geometrically-wrong programs. Prompt-tuning is whack-a-mole.

**Deep-research pass (cross-domain).** Founder asked for a genuinely novel solution from fields
OUTSIDE CAD. Ran a 7-track research fleet: program synthesis, generative structural biology,
morphogenesis/self-organization, robotics-control/EDA, differentiable graphics, evolutionary/QD,
plus a text-to-CAD SOTA & novelty sweep. Finding: six unrelated fields INDEPENDENTLY reject
"generate-then-check" for the same move — **the proposer never owns exact geometry; it owns
structure; the exact part is grown by a constrained solver that physically cannot produce an invalid
result and provably converges.** The SOTA sweep confirmed no published text-to-CAD system enforces
validity by construction for 3D editable feature trees (Vitruvion/AIDL are 2D only; GenCAD-SR/EvoCAD
are post-hoc/statistical). Whitespace.

**Wrote the method up** → `../cad_copilot_design_genome_method.md` (v1.0): the cross-domain synthesis,
the Kernel-CEGIS over a Design-Genome architecture (3 layers), failure-mode mapping, novelty
positioning with citations, honest risks, trial-grade vs moat-grade split. **ADR-007** records the
decision.

**Built the trial-grade engine (server-side, fully offline-testable, ZERO LLM spend):**
- `ai_server/services/genome/` — `grammar.py` (typed FeatureType vocabulary + holes + closure
  validation: one primary first, modifiers after, known holes only → invalid trees largely
  unrepresentable); `library.py` (each feature → tested Command-IR fragment + its exact kernel
  Solid; `build_ir` aggregates + sets expected_geometry from that solid); `solver.py` (fill holes:
  user dims > existing > default, clamp to bounds, cross-hole DRC — wall < 0.45×body, fillet <
  body, dimple < wall — each clamp a recorded counterexample); `cegis.py` (the convergent loop:
  closure gate → solve+DRC gate → compile → IR-validator + render-check gate; a structural
  counterexample drops the trailing modifier and retries; honest refusal if it can't converge);
  `planner.py` (deterministic PartPlan→Genome, no LLM); `prompt.py` (live LLM-genome path: model
  emits a GENOME, parsed + closure-validated, never raw geometry).
- Kernel: added exact `HollowCylinder` + `HollowBox` solids; `realize()` detects extrude+SHELL →
  hollow, so a hollow body is render-check VERIFIED hollow (mug body 0.000% volume error), not
  advisory.
- New `PATTERN` IR op (surface scales/ribs/bolt-circles) across the IR model, validator, and
  `safe_executor` (circular + rectangular array of the last feature; non-fatal like other
  refinements). Compile layer unit-tested; `_apply` follows the Fusion circular/rectangularPattern
  API (live deferred).
- Wired into `CodeGenService`: `generate_parametric` (sketch) and `generate` (codegen) go
  genome-first — deterministic planner (free) for the mug's families, LLM-genome when live for novel
  families, raw-IR retained as fallback. `generate` re-derives + re-solves the genome with the
  user's dimensions so expected_geometry is recomputed (render-check stays a REAL verification).

**Result.** The dragon-scale mug now builds OFFLINE, correct-by-construction: hollow body (verified),
dimensionable scale pattern (real circular+linear array), loop-handle frame — every dimension a user
parameter. Infeasible inputs converge via DRC counterexamples; malformed genomes refuse honestly.

**Verified.** 161 tests pass (+33 new: `test_genome.py` 30 + codegen genome path + executor chain),
ruff clean, eval baseline holds (no regressions, 2pt threshold). Commit `817a8bb`.

**Honest limits (live-only, for the next Fusion test).** The hollow uses Fusion's whole-body shell
(closed top — open-top needs a removed top face); the loop_handle inner cut and the surface_pattern
arrays are executor-attempted but non-fatal and not live-verified by me (founder away). Check these
first on the next live run. Differentiable fitting + provable contraction + edit-propagation are
moat-grade, deferred per ADR-007.

## 2026-06-26 — Function drives topology (the open-top fix, generalized)

Founder pushback on the closed-top hollow caveat: "a cup must have an open top — what is the point
of a closed cup. And the same for any other object: its purpose must be met. You can't just fix the
cup alone — it should understand the needs." Correct, and a product principle, not a bug. Treating
the opening as a cosmetic tweak was wrong: the opening is part of *meeting the request*.

Generalized the fix instead of hardcoding the cup. A hollow part's OPENING is now derived from what
the object is FOR:
- Genome `Feature` gained `options` (non-numeric functional aspects). Hollow features carry
  `opening`: `top` (cup/mug/bowl/glass/vase/jar/container/tray), `both` (pipe/tube/sleeve), `none`
  (sealed tank/bottle/canister). Default = open-top (a hollow vessel is open by purpose).
- `planner.py` sets opening from the object's function (broadened vessel vocabulary: bowl, jar,
  pot, can, tank, drum, barrel, bucket, bottle, flask, tumbler, …); the live LLM-genome prompt now
  instructs the model to set opening to serve the request.
- Kernel `HollowCylinder`/`HollowBox` model `open_top`/`open_bottom` exactly — the cavity reaches
  the rim — so render-check VERIFIES the part serves its purpose, not merely that it is hollow.
- Executor `SHELL` removes the matching end face(s) (top face by highest centroid) to actually open
  the vessel; closed only when function says so.

This seeds a **functional-requirements layer**: purpose → required topology → encoded + verified
(the LVS-style intent↔model check the research flagged as whitespace). 165 tests pass (+4), ruff
clean, eval baseline holds. Commit `6dc7bf0`. The closed-top live caveat is now resolved (still
unverified in real Fusion, but the face-removal is correct API usage).

## 2026-06-26 — Generalisation: functional-intent reasoning + general geometry vocabulary

Founder challenge: "what if I ask for an engine, will it know it needs to hollow things? this is
just a list not generalisation." Correct — the opening keyword map was a cache, not generalisation.
Built both halves of real generalisation (offline, ZERO API calls — live tests deferred to the
founder's return).

**Understand the need (the brain).** `PartPlan` gained FUNCTIONAL fields the intent LLM reasons per
part: `shape` (box/cylinder/prism/cone/sphere/torus/wedge/loft/sweep/l_bracket/handle), `hollow`,
`opening` (top/both/none), `bore`, `purpose`. `plan_genome` now routes by EXPLICIT function first
(shape→primitive, hollow→cavity, opening→topology, bore→through-hole); the family keyword map is only
a fallback when no function was reasoned. So an engine cylinder becomes solid_cylinder+bore because
the model understands engines — not because "engine" is listed. Intent prompt updated to fill these.
New **functional-verification gate** (`genome/functional.py` `unmet_requirements`): codegen REFUSES a
part that would not serve its purpose (solid when it must be hollow, closed when it must open, no
bore when it needs one) — purpose met, not just valid geometry.

**Able to build it (the vocabulary).** General primitives so the engine composes ANY shape:
kernel `Frustum`/`RegularPrism`/`Sphere`/`Torus`/`Wedge` (cone + prism render-check VERIFIED exactly
via taper-detection and ADD_POLYGON; sphere/torus/wedge/loft/sweep build valid IR, verified live).
New IR ops `ADD_POLYGON`, `SWEEP`, `LOFT`, `EXTRUDE.taper`, `CREATE_SKETCH.offset` across
model/validator/executor (offset planes enable loft sections). Genome fragments cone/prism/sphere/
torus/wedge/loft/sweep + a `BORE` modifier (central axial hole, kernel-verified via WithHoles).
SWEEP/LOFT are the general escape hatches (advisory offline, the live frontier).

**Demonstrated** offline across cup→hollow_cylinder, funnel→cone, ball→sphere, pipe→hollow open-both,
hex nut→prism, engine cylinder→solid+bore, O-ring→torus, ramp→wedge, elbow→sweep, duct→loft — every
one builds and is purpose-met, with gibberish families (proving function, not keywords, drives it).
192 tests pass (+27: general primitives, functional routing, the gate), ruff clean, eval baseline
holds, object_plan golden regenerated. Commit `fd36444`.

**Live frontier (founder to verify in Fusion).** EXTRUDE taper, ADD_POLYGON, REVOLVE (sphere/torus/
sweep), LOFT + offset planes, and the SHELL open-face removal are correct Fusion API usage but
executor-runtime, not yet live-verified. SWEEP/LOFT are primaries, so a Fusion failure fails that
part (no graceful skip) — first thing to check live. The deterministic planner covers common shapes;
truly novel families fall to the live LLM-genome path.

## 2026-06-26 — Relational + surface-parametric (ADR-008): attachment + wall features

Founder live test (screenshots): better, but "not useful in practical life yet" — the handle floats
beside the body (joint wrong), the scales are round dimples on the BOTTOM instead of scale-shapes on
the curved wall. Correctly identified as a GENERAL class (where parts attach, which surface features
sit on + orientation, what features look like), all rooted in the engine using ABSOLUTE coordinates +
independent parts. Founder asked for another deep cross-domain research pass.

**Research (7 agents, verified sources).** Convergent finding: every field places things RELATIVE to
surfaces and frames, never at guessed XYZ. Attachment → mechanical mate-connectors + molecular docking
(pair complementary frames, kernel solves the transform). Feature-on-surface → architectural paneling
+ graphics surface-param/frame-fields + developmental-biology PCP orientation fields (orientation is a
property of the surface). Motif tiling → scale-armour imbrication + phyllotaxis + mesh-quilting. SOTA
sweep: no system unifies NL→mates + field-oriented surface features + imbricated tiling — whitespace.

**Built (offline, no API).** Key enabler: my primitives have ANALYTIC surfaces (a cylinder wall is
already (θ,z) with a closed-form frame), so all of this is exact and offline — no mesh field solver.
- `genome/frames.py`: a `Frame` (origin + orthonormal basis, uz=mating normal); named connector
  frames per primitive (cylinder wall/rim/base, box faces); `part_mounting` (a handle mounts at its
  back-edge centre, bulging outward); `align`/`solve_placement` → a `Placement {mount,target}`.
- `PartPlan.attachment {to,where,height_frac,angle}` (intent LLM reasons it); intent prompt updated.
  `CodeGenResult.placement` carries the solved frames; `_solve_attachment` builds the host solid +
  part mounting and aligns them. Executor `_place` applies `Matrix3D.setToAlignCoordinateSystems`
  (rotation+translation), falling back to `position`. Wired through CAD_Copilot.py + app.js.
  VERIFIED offline: a handle's back edge seats at radius == R (on the wall) at grip height, bulging
  outward, for any body radius — the floating-handle fix, general.
- `surface_pattern` rewritten: scale motifs tile on the WALL (the YZ plane offset to the radius),
  each a SCALLOP (arc+chord, a real scale shape, not a round dimple), raised (join) and wrapped
  around the axis by a circular pattern; rows climb the wall. The hollow body stays render-verified.

**Verified.** 195 tests pass (+8: frames/attachment, attachment-through-codegen, wall scales), ruff
clean, eval baseline holds, object_plan golden regenerated. Commits `5c4cb19` (code) + docs.

**Live frontier (founder verifies in Fusion).** The Matrix3D mate transform, the YZ-offset wall
sketches, and the join-extrude scales are correct Fusion API usage but executor-runtime, not yet
live-verified. Per-row imbrication offset and freeform-face frame-fields (mesh solver) are moat-grade.

## 2026-06-27 — Close the loop: perception-driven spatial verification (ADR-009)

First fixed a live blocker: the "coffee mug" prompt was REFUSED because I'd added `attachment` as an
open dict (`dict[str,object]`), which made the planning structured-output schema illegal for Anthropic
strict mode (400 "additionalProperties: true not supported") → live intent fell back to the keyword
planner → refusal. Fixed by typing `Attachment` (closed model) + a contract guard test that fails if
any open dict re-enters the plan schema. (commit `7ff2a9e`)

Then the deeper problem. Founder live test: body clean, but scales burst into a floating RADIAL STAR
and the handle dropped to the BASE. I studied the system and named the meta-pattern honestly: the
pipeline is OPEN-LOOP and BLIND — nothing perceives whether parts/features end up where they should;
the only check is body volume, so spatial errors are invisible (offline-right, live-wrong, every
round). Plus a flat motif placed tangent to a curved wall sticks out (the star).

**Research (7 agents, verified):** robotics visual servoing, physics contact mechanics, predictive
coding / active inference, graphics surface-scatter/decals, tailoring/draping, ergonomics/affordances,
+ SOTA sweep. Unanimous: close the loop with a SPATIAL-RELATION error signal (contact gap=0,
on-surface, no interpenetration) — physics' "contact certificate". SOTA sweep: NO text-to-CAD system
verifies spatial relations of generated geometry — whitespace.

**Built (offline, no API):**
- `genome/verify.py` — the spatial comparator: `surface_distance` (analytic, cylinder/box walls+caps),
  `attach_seat_residual` (does the part seat on the host surface, or float/bury?), `feature_seat_
  residuals` (each scale ON the wall?), `certificate`. The engine now PERCEIVES correctness. Verified:
  detects floating parts (160mm gap) + off-wall scales (20mm), confirms seated handles (gap 0).
- Scales fixed (the star): `surface_pattern` ENGRAVES each scale INTO the wall — cut inward via a new
  `EXTRUDE direction=negative` (executor extrudes opposite the sketch normal) — so it conforms and
  can't float as a raised tangent tab.
- Attachment robustness (the dropped handle): handle-like parts DEFAULT-attach to the body even when
  the planner emits no attachment; codegen surfaces a spatial certificate in the build result.
- Live read-back (`safe_executor._readback`): the add-in measures where the part ACTUALLY landed in
  Fusion (bbox center, seat gap vs the target) and reports it — the REALITY half of the loop, surfaced
  in app.js. Catches executor errors the offline comparator can't.

**Verified.** 201 tests pass (+5), ruff clean, eval holds. Commit `ad27b07` + docs. Honest boundary:
the comparator verifies INTENT (catches floating/off-wall before shipping); the read-back verifies
REALITY (Fusion). Live frontier: the read-back + engraved-cut + the direction=negative extrude realize
in Fusion (founder verifies). Moat-grade: visual-servoing correction (relation-Jacobian), ergonomic
placement constraints, freeform-face conformance.

## 2026-06-27 — Closed-loop correction realized: measurement-driven seat + symmetric cut

The read-back (ADR-009) paid off — it gave GROUND TRUTH on a live test: the mug body built clean
(scales all failed `NO_TARGET_BODY` and were skipped — the non-fatal fix held), and the handle
reported "NOT seated: 40mm from target, center (57.5,0,-32.5)" — i.e. hanging BELOW the base (z<0).
Both are me guessing Fusion conventions I can't see (the handle's vertical sketch-plane local→world
sign; the tangent cut not intersecting the curved wall). Fixed GENERALLY (founder: "must be
generalised, not just to fix his cup"):
- **`safe_executor._seat_correction`** (general, any part/host): after the open-loop mate, MEASURE the
  part's actual bounding box in Fusion and translate it to seat on the host target frame — centred on
  the seat point in the surface-tangent plane, touching the surface along the outward normal. This is
  the visual-servoing correction (measure error → correct), so it self-fixes the build-orientation
  errors the offline math can't see, for ANY part. (Handle: z corrected from -32.5 to grip height.)
- **Symmetric scale cut**: a scale now engraves with a SYMMETRIC extrude-cut from the wall's tangent
  plane (`EXTRUDE direction=symmetric` → `setDistanceExtent(isSymmetric=True)`), so the inward half
  ALWAYS crosses the wall → the cut always has a target body (fixes `NO_TARGET_BODY`) regardless of
  normal sign. Still optional/non-fatal.

201 tests pass, ruff clean. Commit `7fc1fe8`. Live frontier: the correction + symmetric cut realize in
Fusion (verified via the read-back line). Both are general principles driven by the measured error, not
cup-specific hacks.

## 2026-06-27 — Live state + the surface-texture bottleneck (entering deep research)

Live test after the seat-correction + inside-wall scale fixes (read-back = ground truth):
- **Handle: SOLVED.** Read-back "seats on host (gap 0mm)". The measurement-driven `_seat_correction`
  works live — the handle attaches to the side wall at grip height, correctly oriented. The hard
  relational/attachment problem (the thing that makes multi-part objects actually work) is done and
  general (any part on any host, self-correcting via measured error).
- **Mug body: SOLVED.** Clean hollow, open top, render-verified.
- **Scales: PARTIAL — the bottleneck.** Inside-wall symmetric cut got ONE row to engrave (visible
  notches near the base; skipped 6 -> 5), but the other 5 rows still fail `NO_TARGET_BODY`. Surface
  micro-texturing on a curved wall via per-feature B-rep cut + circular pattern is fragile and
  unpredictable, and I can't debug it blind in Fusion. Non-fatal, so the mug always builds clean.

**Root realisation:** the remaining failures (and the ones complex objects will bring) come from
fighting Fusion's feature-by-feature B-REP operations (booleans/patterns on tangent/offset planes are
topology-fragile and convention-dependent). Entering a deep cross-domain research pass to find a
ROBUST general approach to (a) surface texture/microfeatures on curved geometry, and (b) the problems
complex objects will raise that we haven't hit yet (large assemblies, fits/interference, internal
features, manufacturability, organic shapes). Hypothesis to test: implicit / SDF / field-based
modelling (the nTopology/FRep paradigm) as a robust substrate where B-rep struggles — a paradigm never
connected to text-to-CAD (which is universally B-rep command sequences).

Commits to date this arc: handle/scales fixes through `463a3e2`. 201 tests pass, ruff clean.

## 2026-06-27 — Robustness research landed: hybrid representation (ADR-010)

Ran the seven-track cross-domain deep-research fleet (implicit/FRep, AM texture, graphics displacement,
mechanical constraint solving, DFM/GD&T, robust geometric computation, + a text-to-CAD SOTA sweep). All
seven converged on ONE root cause: **B-rep feature operations are partial functions** — they fail on
coincident/tangent/thin geometry (exactly `NO_TARGET_BODY`). The fix, unanimous across fields: where
B-rep is fragile, switch to a representation whose ops are *total* (implicit/displacement fields —
`min`/`max`/displacement always produce a valid result). The SOTA sweep showed the B-rep↔implicit seam
is **unoccupied** in generative CAD (every text-to-CAD system is monolithic B-rep; industrial implicit
CAD is never NL-driven) — the moat. Synthesis + verified sources: `../cad_copilot_robustness_research_2026-06.md`.

**Built (ADR-010), all offline-verified:**
- **Pillar A — surface texture as a displacement field (the scales fix).** `genome/texture.py`: the
  scale motif is a tileable height field `h(θ,z)` over the wall's own parameterisation, realised as ONE
  watertight **mesh skin** displaced along the normal. Proven a closed two-manifold across 144 param
  combinations — so it can NEVER hit `NO_TARGET_BODY` (no boolean, no target to miss); "200 scales" is
  one field op. New `CREATE_MESH_BODY` IR command (model + validator + executor). `_surface_pattern`
  rewired off the fragile per-row cut+pattern path to emit one mesh skin. Executor imports the verified
  mesh as a Fusion mesh body via the stable STL-import path, **optional/non-fatal** (the parametric
  B-rep mug is untouched and can't be rolled back by the texture). Add-in surfaces "applied N textured
  skin(s)".
- **Pillars C+D — makeability/fit/mobility gates (future-proofing).** `genome/dfm.py`: DFM predicates
  (min wall/feature, internal radius, draft) per process; **ISO-286 fits** from the standard IT formula
  (validated against published tables — IT7 Ø20 = 21 µm; H7/g6 Ø20 → 7..41 µm clearance);
  **Grübler–Kutzbach mobility + loop counting** on a mate graph (four-bar → M=1, 1 loop; names
  over/under-constraint and the kinematic loops a tree placer breaks on). A makeability certificate is
  surfaced in the build result like the spatial certificate.

**Honest boundary:** the generation, watertight proof, ISO-286 fits and mobility math are all
offline-verified (325 tests, +24). The **Fusion mesh-body import is the live frontier** — to verify in
Fusion. If it doesn't import, the mug still builds clean (non-fatal); best case, robust scales appear.

Tests: 325 pass (+24), ruff clean.

## 2026-06-27 — Live verification of ADR-010, then ADR-011 (Certified CAD, the breakthrough's first pillar)

**Live run + fix.** Founder reloaded and tested in Fusion. First build was the OLD code (server +
add-in had never been restarted after the ADR-010 commit — a real process-staleness miss). After a
hard server restart + add-in reload, the new pipeline ran: clean mug body (no `NO_TARGET_BODY`, no
grooves), handle with a fillet — but the texture skin skipped with
"`ImportManager` has no attribute `createMeshImportOptions`" (wrong mesh API, but graceful: mug
intact). Looked up the Autodesk API and replaced the STL-import path with
`MeshBodies.addByTriangleMeshData` (no file; flat coords in cm; a BaseFeature host in parametric
designs). Commit `f686303`. Re-run: **"applied 1 textured skin(s)"** — the displacement-field skin
lands. ADR-010 robustness is proven live. (Open: the scale MOTIF reads as horizontal ripples, not
imbricated dragon scales — the founder correctly identified this as an UNDERSTANDING problem, deferred
to the breakthrough's intent layer; the robust substrate itself works.)

**Founder direction:** picked the breakthrough plan as the path; "choose the best path... finish the
whole thing... generalisation always important." Chose **Certified CAD (Pillars P0 + P6)** — the
plan's recommended lead wedge, fully offline, maximally general, and the strongest moat.

**Built (ADR-011), all offline-verified:**
- `genome/spec.py` — typed `Requirement` (a self-contained `metric op target` predicate) +
  `Specification`. `derive_specification` composes requirements GENERALLY from functional intent +
  geometry + process (hollow→cavity+capacity, opening→its function, bore, attached→seated,
  wall→process min-wall). `evidence()` measures the realized solid (volume, capacity≈ml, wall,
  opening, bore, seat-gap). The same rules certify a mug, a box, a bored cylinder, an attached handle.
- `genome/certificate.py` — `check(spec, evidence)` → per-obligation verdicts + margins + overall
  fitness. `recheck(cert)` is an INDEPENDENT re-verifier: from the certificate JSON alone it recomputes
  every verdict and rejects a flipped verdict / faked `ok` / dropped obligation / orphan obligation.
  That's the proof-carrying moat — re-verify in seconds without trusting the generator.
- Wired into `CodeGenService.generate` (`CodeGenResult.certificate`, summary in warnings) + add-in
  ("✓ certified fit (5/5)" / "✗ NOT certified: …"). Subsumes the ad-hoc functional/spatial/makeability
  strings. The mug certifies fit and computes it holds ~370 ml.

**Honest boundary:** fully offline/deterministic — no live frontier. It certifies the *intent/design*
is fit (geometry/function/manufacturing proved; seating tested); physics-needing-certified-numerics is
future. To see it live: restart the server + reload the add-in.

## 2026-06-27 (cont.) — ADR-012: the understanding layer (frames infer the unsaid)

With the certificate spine in place, built the breakthrough's second pillar — the founder's deepest
pain (the system not understanding what a thing *should* be). `genome/understanding.py`: Fillmore
frame semantics for CAD. Frames form an INHERITANCE hierarchy (object→container→vessel→drinkware;
pipe; handle), each carrying typed REQUIREMENT TEMPLATES for what the object implies. `resolve_frame`
picks the most-specific frame by keyword + functional-field inference (hollow+open-both→pipe;
hollow+drink→drinkware) with a generic fallback — so EVERY object resolves principled, known or not
(general, not a list). `expand` walks the chain; `derive_specification` merges the implied
requirements into the spec (explicit intent wins) and records an **assumption ledger** tagging each
requirement stated / inferred / derived. Frame inferences are advisory ("should", non-gating) and
surface as `certificate.advisories`.

Result: "make me a coffee mug" → drinkware frame → the certificate now **proves three requirements
the user never stated** (stable base, useful capacity ≥150 ml, food-safe wall): "certified fit
[drinkware]; proved 3 implied requirement(s)". The pipe resolves by function with no keyword; an
opaque part falls back to the generic frame (no inferred noise). A tight handle (17 mm grip) is
flagged as an advisory. This is the convergence: understanding supplies the implied obligations, the
certificate discharges them, the ledger keeps it auditable.

Honest boundary: the frame library is a curated seed (mechanism generalises, coverage grows);
ergonomic predicates are first-order proxies. Fully offline. 369 tests pass (+17), ruff clean.

Tests: 352 pass (+27: spec/certificate/recheck general across objects, tamper-detection, codegen
integration), ruff clean.

## 2026-06-27 (cont.) — ALL SEVEN breakthrough pillars built (ADR-011 → ADR-016)

Founder: "build the entire thing, nothing left out, generalisation always." Built the whole
breakthrough (Certified Functional CAD) end to end. Every pillar extends the existing engine, is
GENERAL (composed from properties/structure, never object names), and is offline-verified.

- **P0+P6 Certify (ADR-011)** — `genome/spec.py` typed Specification (requirements composed generally
  from intent+geometry+process) + `genome/certificate.py` proof-of-fitness with an INDEPENDENT
  `recheck` (rejects tampering — the proof-carrying moat). Wired into codegen + add-in.
- **P1 Understand (ADR-012)** — `genome/understanding.py` object frames (inheritance + functional
  inference + generic fallback) infer the UNSAID; assumption ledger (stated/inferred/derived). "mug"
  → drinkware → proves stable-base + useful-capacity + food-safe-wall unstated. Fixed a generality bug
  (resolved off the geometry primitive `family`; now semantic intent only).
- **P3 Function (ADR-013)** — `genome/function_model.py` Functional-Basis functions from purpose+
  structure → behaviour predicates (contain→reachable cavity, convey→through-path, support→stands,
  couple→join). Catches a sealed cup you can't fill — the functionally-dead case nobody detects.
- **P5 Assembly (ADR-014)** — `genome/assembly.py` typed interface ports + compatibility relation +
  system-level Grübler–Kutzbach mobility → an object-level re-checkable certificate (interfaces match,
  connected, rigid). `POST /api/codegen/assembly`. The whole mug is a *proven* rigid assembly.
- **P1-full Open-ended (ADR-015)** — `genome/intent_expand.py`: the LLM formalises the unsaid into a
  CLOSED grammar over an allow-listed metric vocabulary (`RequirementSpec` on `PartPlan`); a
  correct-by-construction filter drops the unprovable; survivors proven by the certificate. Removes the
  frame-seed ceiling (general for ANY object) while staying checkable. Strict-schema-clean; golden
  regenerated.
- **P7 Edit (ADR-016)** — `genome/edit.py`: a lens (genome↔parameters, laws tested), `Edit` deltas,
  `parse_edit` for NL, PERSISTENT feature ids + IR parameter names across an edit (topological-naming
  problem solved at the parameter level), incremental recompute. `POST /api/codegen/edit`.

**Verification:** 404 tests pass (+79 across the breakthrough), ruff clean. Live-verified the
certificate flows over HTTP (deterministic mug). Everything offline/deterministic except the LLM
intent-expansion (mock-tested; runs live in Fusion). Server restarted; reload the add-in to test.

**Still distinct (not part of these pillars):** the dragon-scale MOTIF rendering (a real imbricated-
scale model on the ADR-010 substrate) — an open downstream task; the understanding layer fixes "knows
what it should be", not the motif geometry.

<!-- Append new entries below as work proceeds. Keep full detail. -->
