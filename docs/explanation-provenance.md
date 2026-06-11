---
title: "Structural provenance"
description: "Why metalworks reports can't contain fabricated evidence — provenance enforced by construction, not by trust."
---

The research pipeline is built so that claims cannot be fabricated by
construction, not by trust. This is the core design principle, and it shapes the
whole architecture.

## The rule

A model is never the source of a fact. Models cluster, summarize, and phrase —
but every verifiable claim is backed by data the pipeline holds independently.

- **Cluster quotes** are exact-matched against stored Reddit comments. A quote
  that does not match a real, stored comment is dropped. A cluster with zero
  verified quotes is never shipped (`no-quote-no-theme`).
- **Web findings** carry their `source_url` from the grounding tool's citation
  metadata, never from model prose. Zero citations means the finding is dropped;
  URLs are never synthesized.
- **Counts** — distinct authors, mention counts, must-address resolution — are
  computed from set membership, never asserted by a model.

If you swap in your own `ChatModel`, this still holds: the verification happens in
the pipeline, around the model, not inside it.

## Internal vs external grounding

Web research follows a split. When the chat model supports native grounding
(Gemini's `google_search`, Anthropic's `web_search`), the adapter returns a
`GroundedResult` carrying chunks and character-offset supports, and the pipeline
maps findings to citations by span overlap. When it does not, the pipeline falls
back to an external `SearchProvider` (Exa, Tavily) plus a structured synthesis
call that cites results by index. Either way the provenance contract above holds.

## Why protocols, not a monolith

metalworks owns small, versioned protocols — `ChatModel`, `SearchProvider`,
`EmbeddingProvider`, and typed storage repos — with thin adapters over official
SDKs behind pip extras. Two reasons:

1. **Swappability is the product.** The durable value is the curated pipeline,
   prompts, and provenance discipline, not the API plumbing. Owning the protocols
   lets you replace any provider, data source, or store without forking.
2. **No hidden globals.** Every stage takes an injected deps object instead of
   reaching for module-level singletons, so the pipeline runs offline with fakes,
   in tests, and against any provider — and nothing raises at import time.

## What is deliberately excluded

Tooling that fabricates Reddit account histories to make accounts look aged and
credible is **not** part of metalworks and never will be. That is coordinated
inauthentic behavior and a Reddit ToS violation. The persona model carries a
`background` field that must be authentic; there is no path that invents one. See
the [usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).

## API stability

The stable surface is the `Metalworks` facade, `metalworks.contract` models, and
the MCP tool contracts. Everything else may change in any 0.x release. Breaking
changes to the stable surface go through a `DeprecationWarning` at least one minor
version ahead.
