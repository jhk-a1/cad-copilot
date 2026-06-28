# Model configuration (`models.json`)

The LLM Gateway maps **profiles** to `{provider, model, params}`. Switching a model is a
one-line edit here — no code change (M1-W2-BE-03 / plan §3.5).

## Profiles

| Profile | Used for | Pipeline stage |
|---|---|---|
| `INTENT` | object planning | 1 |
| `SKETCH` | per-part multi-view SketchSpec | 2 |
| `IR_CODEGEN` | Command IR generation | 4 |
| `SAMPLER` | cheap best-of-N candidate sampling | 4 |
| `VISION_JUDGE` | render-and-check verification | 4 |

## Default: offline mock

`models.json` defaults every profile to `provider: "mock"` so the whole pipeline and the eval
harness run **without any API key** (the mock returns schema-valid output). This stays the
default for tests/CI.

## Trial: Anthropic only, Claude Sonnet 4.6 (founder decision 2026-06-12)

The trial runs on **Anthropic alone**. **Claude Fable 5 is NOT used** (unavailable to the
founder). **Sonnet 4.6** is the default to keep cost low; the verifier keeps accuracy paramount
by escalating a rejected generation to **Opus 4.8** (never Fable) once the escalation ladder is
built (ADR-002). The ready-made config is [`models.anthropic.json`](models.anthropic.json) —
`SAMPLER` uses Haiku 4.5 (cheapest Claude) for high-volume best-of-N; everything else is Sonnet.

### Activate (when the Anthropic key is ready)

1. Put the key in `ai_server/.env`: `ANTHROPIC_API_KEY=sk-ant-...`
2. Point the gateway at the Anthropic config: `MODELS_CONFIG_PATH=configs/models.anthropic.json`
3. `pip install anthropic` (the backend imports it lazily).

That's it — no code change. Unsetting either var returns to the offline mock. The Anthropic
backend is wired but **UNTESTED LIVE** (built before keys); verify the request shape against the
`claude-api` reference on the first real call.

Verified model ids / pricing (June 2026): `claude-opus-4-8` ($5/$25), `claude-sonnet-4-6`
($3/$15), `claude-haiku-4-5` ($1/$5). (`claude-fable-5` $10/$50 — not used.)

The Week-8 bake-off (M2-W8-EVAL-03) revisits the production models by benchmark. **Sampler
escalation is the cost strategy** (ADR-002): draw best-of-N from `SAMPLER` (Haiku), escalate to
Sonnet then Opus only when no cheap candidate passes the verifier.
