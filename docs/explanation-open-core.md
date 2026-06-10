# Explanation: open-core, and what stays in Clique

metalworks is the open-source core of [Clique](https://clique.so)'s production
pipeline. Clique runs on metalworks. This document explains the boundary and the
principles behind it.

## Why open-core

Two reasons. First, distribution: the easiest way to get a tool in front of the
developers and agent-builders who would use it is to make the core free and
embeddable. Second, it is a forcing function for clean architecture: extracting
the pipeline behind versioned protocols, with no Supabase or auth singletons,
makes it better software than it was as an internal monolith.

## What is in metalworks

The pieces that are generally useful and carry no tenant-specific logic:

- The data contract and the LLM / search / embedding / storage protocols.
- The research vertical: brief to corpus to triage to clustered demand report.
- The Reddit core: OAuth, search, metrics, inbox, subreddit intel, rate
  limiting, posting, and the deterministic compliance gate.
- The discovery loop: filter to generate to gate.

## What stays in Clique

Deliberately not open-sourced:

- **Account-backstory generation.** The source had tooling that fabricated
  Reddit account histories to make accounts look aged and credible. That is
  coordinated inauthentic behavior and a Reddit ToS violation. It was excluded
  on purpose. The persona model here carries a `background` field that must be
  authentic; there is no path that invents one. See `USAGE_POLICY.md`.
- **The memory system.** Clique's episodic / structured / procedural memory is
  product surface. metalworks exposes a plain `DiscoveryContext` seam (voice
  guidelines, winning examples, pinned notes, personas) that a memory system
  renders into; the memory itself stays in Clique.
- **Multi-tenant auth, billing, plan caps, and spend caps.** Tenant fields
  default to `"local"` so a library user never thinks about tenants.

## Structural provenance

The research pipeline is built so that claims cannot be fabricated by
construction, not by trust:

- Cluster quotes are exact-matched against stored Reddit comments. A quote that
  does not match a real comment is dropped (`no-quote-no-theme`).
- Web findings carry their `source_url` from the grounding tool's citation
  metadata, never from model prose. Zero citations means the finding is dropped;
  URLs are never synthesized.
- Counts (distinct authors, mention counts, must-address resolution) are
  computed from membership, never asserted by a model.

## Internal vs external grounding

Web research follows the Inspect-AI split. When the chat model supports native
grounding (Gemini's `google_search`, Anthropic's `web_search`), the adapter
returns a `GroundedResult` with character-offset supports and the pipeline maps
findings to citations by span overlap. When it does not, the pipeline falls back
to an external `SearchProvider` (Exa, Tavily) plus a structured synthesis call
that cites results by index. Either way, the provenance contract above holds.

## API stability

Below 1.0, the stable surface is `metalworks.contract` and the MCP tool
contracts. Everything else may change in any 0.x release. This lets the four
form factors ship before the internal APIs are frozen.
