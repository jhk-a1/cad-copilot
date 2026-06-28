# CAD-Copilot

An AI copilot for **Autodesk Fusion** that turns a natural-language description of an object into
**parametric, editable** CAD — and then tries to *prove* the result actually meets its requirements.

Describe an object → the model plans the **parts** → each part is built as a correct-by-construction
**feature program** (the "design genome") → a real geometry check + a **proof-of-fitness
certificate** verify it → the validated **Command IR** is executed in Fusion as a parametric feature
tree you can keep editing in plain English.

> **What makes this different from a generic text-to-CAD tool:** it is built around a
> **verification / "design-as-proof"** layer, not just generation. Every part carries an
> independently re-checkable certificate (does it meet its derived spec?), a functional gate (is it
> hollow when it must be, thick enough to manufacture?), and a bidirectional edit layer with
> persistent feature IDs so word-level edits don't break downstream references.

## Honest scope (please read before judging it)

This is a **research prototype**, not a finished product. Be clear-eyed about what it does:

- ✅ **Works well:** single parametric parts (brackets, plates, enclosures, vessels, flanges,
  spacers, adapters), user-dimensioned and verified; simple attachments (a handle on a body, a lid
  on a jar); the certification / functional / manufacturability gates; natural-language editing.
- ⚠️ **Does not work yet:** coherent **complex multi-part mechanisms** (engines, gearboxes,
  linkages). Geometry is computed outside the kernel and realized through an IR + mesh round-trip,
  which is robust for the cases above but not for richly-mated assemblies. See `docs/DECISIONS.md`.

If you are looking for a one-shot "type a sentence, get a working engine" generator, this is not
that, and the README will not pretend otherwise.

## Architecture

```
cad-copilot/
├── ai_server/              # FastAPI server (the "brain")
│   ├── models/             # API Contract — Pydantic schemas (source of truth)
│   ├── gateway/            # pluggable LLM gateway (mock by default; Anthropic/OpenAI/Google backends)
│   ├── routers/            # health / object-plan / sketch / codegen endpoints
│   └── services/
│       └── genome/         # the design-genome engine: closed grammar, hole solver, Kernel-CEGIS,
│                           #   geometry kernel, certification, DFM gate, texture field, editing
├── fusion_addin/           # Autodesk Fusion add-in (pure .py, Python 3.14)
│   ├── core/               # design-intent gate, safe executor, server client
│   └── ui/html/            # palette UI
├── eval/                   # offline evaluation harness
├── bench/                  # benchmark cases
└── tests/                  # contract (golden JSON) + unit + integration tests (~440)
```

The product runs **fully offline by default** — every model profile is a deterministic `mock`, so
the whole pipeline, eval, and test suite run with **no API key**. Adding a real model is opt-in
(see below).

## Quick start (offline, no key needed)

Requires Python 3.11+ (the Fusion target is 3.14).

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        # POSIX: source .venv/bin/activate
pip install -e ".[dev]"

uvicorn ai_server.main:app --reload       # http://localhost:8000/docs
pytest                                    # run the full test suite
```

## Going live on a real model (optional)

The repo never contains an API key. To use a real LLM:

```bash
cp ai_server/.env.example ai_server/.env
# edit ai_server/.env and set ANTHROPIC_API_KEY=...   (this file is gitignored — never commit it)
```

`ai_server/.env.example` documents the variables. Setting `MODELS_CONFIG_PATH=configs/models.anthropic.json`
switches the gateway from the offline mock to live Anthropic models. **Never commit `ai_server/.env`.**

## Load the add-in in Fusion

Fusion requires the add-in *folder name* to match the entry script (`CAD_Copilot.py`), so point
Fusion at a folder named `CAD_Copilot`. The simplest way is a junction:

```powershell
New-Item -ItemType Junction `
  -Path "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns\CAD_Copilot" `
  -Target "<repo>\cad-copilot\fusion_addin"
```

Then start the server (`uvicorn ai_server.main:app --port 8000`), and in Fusion:
**Utilities → ADD-INS → Scripts and Add-Ins** → select **CAD_Copilot** → **Run** → click the
**CAD Copilot** button (a Part/Hybrid design opens the palette).

## Project notes

`docs/` contains the development log, durable context, and the design-decision records (ADRs) that
explain the design-genome, certification, attachment, and editing layers — useful if you want to
understand *why* the architecture looks the way it does.

## License

MIT — see [LICENSE](LICENSE).
