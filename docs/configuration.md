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

Metalworks(model="anthropic/claude-opus-4-6")
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
model = "claude-opus-4-6"
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
Metalworks(model="anthropic/claude-opus-4-6", fast_model="anthropic/claude-haiku-4-5")
```

If you set only `model`, the fast slot falls back to it. Resolve a pair directly
with `metalworks.config.resolve_models(model, fast_model)`.

## Check the resolution

```bash
metalworks doctor      # prints the resolved provider/model and which keys are set
```
