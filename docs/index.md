---
title: "metalworks"
description: "Open-source, composable marketing research and Reddit engagement — a Python library, CLI, MCP server, and Claude Code plugin."
---

metalworks turns real Reddit conversations into demand reports, and gives you the
OAuth, search, and compliance primitives to act on them. It is MIT licensed and
built to be **embedded**: every layer is a swappable protocol, so you can build
your own product on top of it.

```python
from metalworks import Metalworks

# Zero keys, zero network — a real DemandReport from bundled data:
report = Metalworks.demo().research("Is there demand for a focus supplement?",
                                    subreddits=["Supplements"])
for cluster in report.ranked_clusters:
    print(cluster.signal, cluster.distinct_author_count, cluster.claim)
```

<Note>
Pre-release (0.0.1). The stable surface is the `Metalworks` facade,
`metalworks.contract` models, and the MCP tool contracts — breaking changes to
them go through a deprecation cycle. Everything else may change in any 0.x
release. Some surfaces are marked "planned for 0.1" where not yet wired.
</Note>

## Swap anything

metalworks is a **kit**, not a black box. Each capability is a small protocol with
a default implementation you can replace:

| Layer | Protocol | Ships with | Swap for |
| --- | --- | --- | --- |
| Chat model | `ChatModel` | Anthropic, OpenAI, Google, **any OpenAI-compatible endpoint** | OpenRouter, vLLM, LM Studio, your own |
| Embeddings | `EmbeddingProvider` | Google, OpenAI | any vector model |
| Web search | `SearchProvider` | Exa, Tavily | any search API |
| Reddit data | `CorpusReader` / `CommentSource` | Arctic Shift (HF + live API) | your own parquet, DB, or corpus |
| Storage | typed repos | in-memory, SQLite | Supabase, Postgres, anything |

No Arctic Shift? Bring your own `CorpusReader`. Don't want the research vertical?
Use just the Reddit client and the compliance gate. The point is to **sell the
shovel**: assemble exactly the product you want.

## What you can do

- **Demand reports** — a research brief becomes a clustered report whose quotes
  are exact-matched to real Reddit comments and whose web findings carry source
  URLs from grounding metadata, never model prose.
- **Reddit engagement** — search, subreddit intel, inbox, rate-limited OAuth and
  posting, and a deterministic compliance gate.
- **Discovery + reply generation** — find threads worth engaging and draft replies
  in your own voice, with the filter, generation, and compliance steps each a
  standalone building block.
- **Four form factors** — a Python library, a CLI, an MCP server, and a Claude
  Code plugin that share one typed contract. Non-Python? Drive it from the MCP
  server or the CLI.

## Common patterns

<CardGroup cols={2}>
  <Card title="A demand report" href="/docs/guide-demand-research">
    `Metalworks().research("...", subreddits=[...])` → a clustered DemandReport.
  </Card>
  <Card title="Find threads" href="/docs/guide-reddit-engagement">
    `mw.reddit.search("...")` and `mw.reddit.subreddit("...")` for live intel.
  </Card>
  <Card title="Draft + gate a reply" href="/docs/build-your-own">
    `mw.discovery.generate(post, persona=...)` then the compliance gate.
  </Card>
  <Card title="Build your own product" href="/docs/build-your-own">
    Compose the building blocks into your own discovery product.
  </Card>
</CardGroup>

## Where to start

<CardGroup cols={2}>
  <Card title="Quickstart" href="/docs/quickstart">
    The 4-line offline demo, then a real report with a provider key.
  </Card>
  <Card title="Core concepts" href="/docs/concepts">
    The object model: briefs, reports, clusters, posts, opportunities.
  </Card>
  <Card title="Building blocks" href="/docs/building-blocks">
    The swappable protocols and composable functions that make up the kit.
  </Card>
  <Card title="Model configuration" href="/docs/model-configuration">
    Provider/model refs, fast vs main, and any OpenAI-compatible endpoint.
  </Card>
</CardGroup>

## Usage policy

For authentic, disclosed engagement only. No fake personas, no invented account
backstories, no vote manipulation, no coordinated inauthentic behavior. See the
[usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).
