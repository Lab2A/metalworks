# Operating metalworks — agent reference

A concise operational reference so you can answer "how does metalworks behave?" and
recover from errors **without reading `src/`**. For depth, the full docs are at
<https://metalworks.lab2a.ai/docs> (configuration, sources, architecture). Run
`metalworks preflight` (or the `preflight` MCP tool) first — it reports your live
provider/model, the active reader, and any setup issues.

## Providers & models

Resolution precedence (highest first):
explicit `--model` / `model=` ref **>** `METALWORKS_MODEL` env **>** a config `model`
that is a routable ref **>** config `provider` (+ `model`) **>** first present API key
(Anthropic → OpenAI → Google) **>** Vertex (if `GOOGLE_GENAI_USE_VERTEXAI` is on) **>**
a lone `OPENROUTER_API_KEY` **>** the keyless **`claude-code`** floor (if
`metalworks[claude-code]` is installed and the `claude` CLI is present).

**Keyless on Claude Code (plugin users).** If you're in Claude Code with no API key,
install `metalworks[claude-code]` and run — with nothing else configured, the pipeline
falls back to the `claude-code` provider (your Claude Code login is the chat backend),
and web research runs keyless via Claude Code's `WebSearch`. Any explicit key/ref still
wins. Trade-off: it spawns the `claude` CLI per call (~5–7s each) — slower than a
configured key, but zero setup.

- A **ref** is `provider/id` or `provider:id`. An unknown vendor namespace routes to
  OpenRouter. So `deepseek/deepseek-v4-flash` → OpenRouter, `openai/gpt-5` → OpenAI
  native, `anthropic/claude-opus-4-8` → Anthropic.
- **To force a model on every surface (CLI + MCP + SDK) without editing config:** set
  `METALWORKS_MODEL=<provider/model>`. A config `model` that is itself a routable ref
  also works on its own (0.2.1+) — no separate `provider` needed.
- **OpenRouter does chat only (no embeddings).** Embeddings fall back to the keyless
  local fastembed model, which ships in the `research` extra — so an OpenRouter-only
  setup needs `metalworks[research]`.

### The Vertex gotcha (the #1 first-run failure)

`GOOGLE_GENAI_USE_VERTEXAI=true` (often **inherited from the launching shell**) makes
resolution prefer Google/Vertex for **chat and embeddings**. If the `google` extra
isn't installed, both fail (e.g. "defaulting to a Google model", `MissingExtraError`),
even when an OpenRouter key is set. Fix: set `METALWORKS_MODEL=<provider/model>` **and**
`GOOGLE_GENAI_USE_VERTEXAI=false`, or `pip install "metalworks[google]"`. `preflight`
flags this as an error.

## Sources & readers

- **Submissions and comments come from the live Arctic Shift API by default** — keyless,
  core `httpx`, current data, no extra. (0.2.1+ on every surface, including the MCP/plugin.)
- `ARCTIC_SHIFT_SOURCE` selects the reader: unset / `api` = live (default); `hf` (aliases
  `parquet`/`arctic`) = the Hugging Face Parquet mirror (`[arctic]` extra, reads `HF_TOKEN`;
  **anonymous pulls can 429**); `mirror` = a Supabase mirror (`[supabase]`).
- `preflight` reports the active reader (`active_reader`).

## Running the pipeline (async — do NOT blind-`sleep`)

`research_start(brief)` returns a `run_id` immediately; the run is **asynchronous**.

1. Poll `research_status(run_id)` until a terminal state. **Use the Monitor tool, or a
   bounded poll loop (~15–30s cadence with a sane cap) — never a blind/indefinite
   `sleep`.** Surface the current stage to the user as it progresses.
2. On `ready`: call `research_result(run_id)` to fetch the `DemandReport`.
3. On `failed`: read the error and act (see below) — don't silently retry forever.

## Common errors → fix

| Symptom | Cause | Fix |
|---|---|---|
| "defaulting to a Google model" / `MissingExtraError: google` | the Vertex gotcha | `METALWORKS_MODEL=<provider/model>` + `GOOGLE_GENAI_USE_VERTEXAI=false`, or install `[google]` |
| HTTP **429** on the post pull | you're on the `hf` reader (HF Parquet) | use the live default (unset `ARCTIC_SHIFT_SOURCE` or set `api`), or set `HF_TOKEN`, or tighten the month window |
| config `model` "still resolves Gemini" | pre-0.2.1, a config `model` needed a `provider` too | upgrade, set `provider` too, or use `METALWORKS_MODEL` |
| `missing_key` envelope from a tool | no LLM provider key resolved | set a provider key (or `METALWORKS_MODEL` + its key); **or, inside Claude Code, install `metalworks[claude-code]` to run keyless on your login**; embeddings can stay keyless via `[research]` |
