---
title: "Model configuration"
description: "Pick a provider and model, set a fast model, or point at any OpenAI-compatible endpoint — OpenRouter, vLLM, LM Studio, your own."
---

metalworks talks to LLMs through the `ChatModel` protocol. You rarely construct
adapters by hand — you name a model and metalworks resolves it.

## Model refs

A model ref is `provider:model-id` or `provider/model` (the slash form matches
the convention used by OpenRouter, LiteLLM, and most agent runtimes):

```python
from metalworks import Metalworks

Metalworks(model="anthropic/claude-opus-4-8")
Metalworks(model="openai:gpt-5")
Metalworks(model="google/gemini-3-pro")
```

| Ref | Routes to | Needs |
| --- | --- | --- |
| `anthropic/<id>` | native Anthropic SDK | `ANTHROPIC_API_KEY` |
| `openai/<id>` | native OpenAI SDK | `OPENAI_API_KEY` |
| `google/<id>` (or `gemini/<id>`) | native Google SDK | `GOOGLE_API_KEY` / `GEMINI_API_KEY`, or Vertex AI (below) |
| `openrouter/<vendor/model>` | OpenRouter | `OPENROUTER_API_KEY` |
| `openai-compatible/<id>` | your `OPENAI_BASE_URL` endpoint | `OPENAI_API_KEY` + `OPENAI_BASE_URL` |
| `meta-llama/llama-3-70b` (any unknown vendor) | OpenRouter (the whole ref is the id) | `OPENROUTER_API_KEY` |

A bare known-provider slash like `anthropic/claude-opus` always routes to the
native SDK — it never silently lands on OpenRouter.

## No ref? Inferred from your keys

With no `model`, the provider is taken from the first key present, in order:
Anthropic, OpenAI, Google. So `Metalworks()` with only `OPENAI_API_KEY` set uses
OpenAI. If none of those is set, a lone `OPENROUTER_API_KEY` is the recognized
single-key fallback — `Metalworks()` then talks to OpenRouter's OpenAI-compatible
endpoint (so one key reaches many models). A native key always wins over it. You
can also pin a default in `~/.config/metalworks/metalworks.toml`:

```toml
provider = "anthropic"
model = "claude-opus-4-8"
```

Precedence: explicit `model=` ref > config file > first present key.

## Google via Vertex AI

The Google chat and embedding adapters can authenticate through Vertex AI
(Application Default Credentials, e.g. a service account) instead of an API key.
Set `GOOGLE_GENAI_USE_VERTEXAI=true` and provide a project and location:

```bash
export GOOGLE_GENAI_USE_VERTEXAI=true
export VERTEX_PROJECT_ID=...        # or GOOGLE_CLOUD_PROJECT
export VERTEX_LOCATION=us-central1  # or GOOGLE_CLOUD_LOCATION (default us-central1)
# credentials: GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json, or ambient gcloud ADC
```

With Vertex mode on, provider inference routes to Google even when no
`GOOGLE_API_KEY` is set. The project is required (`VERTEX_PROJECT_ID` or
`GOOGLE_CLOUD_PROJECT`); the location defaults to `us-central1`.

## Any OpenAI-compatible endpoint

This is the "bring your own model" path. Any server that speaks the OpenAI
chat-completions API — OpenRouter, vLLM, LM Studio, Together, Groq, a local
runtime — works with no new adapter:

```python
from metalworks.llm.adapters.openai import OpenAIChatModel

local = OpenAIChatModel(
    model_id="llama-3.1-70b",
    base_url="http://localhost:1234/v1",   # your endpoint
    api_key_env="LOCAL_LLM_KEY",           # the env var holding its key
    native_structured=False,               # use the schema-in-prompt ladder
)
Metalworks(chat=local).research("...", subreddits=["..."])
```

`native_structured=False` routes structured calls straight to the schema-in-prompt
ladder tier, which is the safe default for endpoints whose JSON-schema support
varies. Leave it `True` if your endpoint enforces `response_format` reliably.

## Fast vs main model

The research and discovery pipelines use a cheap "fast" model for triage and
filtering and a capable model for synthesis and generation. Set both:

```python
Metalworks(model="anthropic/claude-opus-4-8", fast_model="anthropic/claude-haiku-4-5")
```

If you set only `model`, the fast slot falls back to it. Resolve a pair directly
with `metalworks.config.resolve_models(model, fast_model)`.

## Embeddings

The pipeline embeds Reddit comments to cluster demand. You don't configure this
separately — it resolves from your environment, and **never requires its own key**:

| Present | Embeddings used |
| --- | --- |
| `GOOGLE_API_KEY` / Vertex | Google embeddings |
| else `OPENAI_API_KEY` | OpenAI embeddings |
| neither | **local model** — `fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim), no key |

So a chat-only provider (Anthropic, OpenRouter, a local LLM) just works: embeddings fall back
to the local model, downloaded once to the Hugging Face cache, then fully offline. A Google
or OpenAI key is used automatically when present (higher quality, no download).

```bash
metalworks models warm          # pre-download the local model before your first run
```

Override explicitly by injecting a provider:

```python
from metalworks.embeddings.adapters.openai import OpenAIEmbedding
Metalworks(embeddings=OpenAIEmbedding())     # force a specific embedding backend
```

<Note>
Embedding vectors from different models live in incompatible spaces. metalworks stamps each
cached index with an identity and refuses to mix them — switching embedding backend on an
existing `.metalworks/` project triggers a clear `EmbeddingModelMismatch` rather than silently
degrading retrieval. Re-run research to rebuild the index under the new model.
</Note>

## Sources

Which connectors a research run pulls from is resolved by a fixed precedence —
**explicit override > brief-aware selector > the `reddit` floor** — so an explicit
choice always wins:

| Layer | How you set it | Wins when |
| --- | --- | --- |
| **Explicit override** | CLI `--source reddit --source hackernews`, or `[sources].enabled` in config | Always — the operator chose the connectors, so neither the selector nor the floor second-guesses it |
| **Selector (default ON)** | nothing configured, or `[sources].select = true` | No override given. The selector **cuts** to the few *reachable* sources relevant to the brief and pulls those (plus the reddit floor) |
| **Floor** | `[sources].select = false`, or no chat model / a failed selection | No usable selection — the run uses `reddit` (the Arctic connector) |

```toml
# .metalworks/config.toml
[sources]
enabled = ["reddit", "hackernews"]   # explicit override — exactly these, in order
default = "reddit"                    # the floor the selector falls back to
select  = false                       # opt OUT of the brief-aware selector (default: true)
```

The **selector is ON by default** (sources-by-idea, #167): with `select` unset and
no explicit override, a run **picks its sources by the idea**. It applies a
deterministic **access gate** — a source is only pickable if it needs no key or its
key is set — then an LLM **cut** over what's reachable: the model selects the few
sources worth pulling for this brief (typically 2–5), an omitted source is dropped
(not re-appended), the non-removable `reddit` floor is always kept, and the pick is
capped at 6. So a consumer brief pulls community/forum sources and cuts the dev/B2B
and CMS/ATS ones; a developer-tool brief elevates Stack Exchange / GitHub. Set
`select = false` to opt back out to the configured `[sources].enabled` / `reddit`
default. A source the cut wants but can't reach (no key) is reported in a pre-flight
line naming the env var to set, e.g.
`Skipped (no key): producthunt — Set the PRODUCT_HUNT_TOKEN environment variable.`

The selector has a **non-removable floor** and a **blast-radius guard**: when the
cut yields nothing — a brief that matched only paid sources with no keys set, OR
there is no chat model / the selection call fails — the run falls back to `reddit`
(or `[sources].default`) with a distinct caveat, never the all-reachable set and
never an empty corpus. (This guard keeps an offline / model-less run deterministic
reddit-only.) The pick, the skipped sources, and any floor caveat are surfaced on
the report's `source_selection` field.

## Check the resolution

```bash
metalworks doctor        # resolved chat + embedding models, keys found, actionable hints
metalworks models list   # the same, plus a provider × key × extra reachability matrix
```
