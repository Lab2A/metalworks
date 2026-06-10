---
title: "Your first demand report"
description: "From the zero-key offline demo to a real, grounded demand report."
---

This walks from the zero-key demo to a real demand report.

## 1. The offline demo (no keys, no network)

```bash
pip install metalworks
metalworks quickstart   # planned for 0.1
```

`quickstart` runs the full research pipeline against bundled Reddit sample
shards using the in-memory store and the bundled fake models. It prints a small
`DemandReport` so you can see the output shape before plugging in a provider.

## 2. A real report

You need one LLM provider extra and the matching API key.

```bash
pip install "metalworks[google,research]"
export GOOGLE_API_KEY=...
```

```python
from metalworks.contract import ResearchBrief, TargetSubreddit
from metalworks.research import ResearchDeps, run_research
from metalworks.research.arctic.reader import ArcticReader
from metalworks.stores import MemoryStores
from metalworks.llm.adapters.google import GoogleChatModel
from metalworks.embeddings.adapters.google import GoogleEmbedding

brief = ResearchBrief(
    brief_id="demo-1",
    question="Is there demand for a focus supplement aimed at developers?",
    decision_context="Deciding whether to build a nootropic brand.",
    success_criteria=["Find the top unmet needs", "Gauge willingness to pay"],
    must_address=["What do people dislike about current options?"],
    target_subreddits=[TargetSubreddit(name="Nootropics", rationale="core community")],
    web_research_directions=[],
    relevance_rubric="Posts discussing focus, energy, or nootropic supplements.",
)

deps = ResearchDeps(
    chat=GoogleChatModel("gemini-2.5-pro"),
    embeddings=GoogleEmbedding("gemini-embedding-001"),
    corpus=MemoryStores(),
    reader=ArcticReader(),  # HF Parquet submissions + live Arctic Shift comments
)

report = run_research(deps, brief=brief)
for cluster in report.ranked_clusters:
    print(cluster.signal, cluster.distinct_author_count, cluster.claim)
    for quote in cluster.quotes:
        print("  ", quote.permalink, "->", quote.text[:80])
```

## What you get

- `report.ranked_clusters`: themes ranked by distinct-author breadth, each with
  verified quotes whose `text` exact-matches a stored Reddit comment.
- `report.web_findings`: findings whose `source_url` comes from the grounding
  tool's citation metadata, not from model prose.
- `report.partial` / `report.caveat`: set when a best-effort stage degraded.

## Notes

- Submissions come from the Hugging Face `open-index/arctic` Parquet mirror;
  comments come from the live Arctic Shift API. Set `HF_TOKEN` for windows
  longer than a few months. Point `ArcticReader(data_root="/path")` at local
  `.parquet` files to run fully offline.
- For persistence across runs, swap `MemoryStores()` for
  `SqliteStores("~/.metalworks/store.db")`.
