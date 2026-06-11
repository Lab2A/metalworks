---
title: "Core concepts"
description: "The object model: the ~14 nouns you touch across the research and Reddit verticals."
---

metalworks has two verticals and a small, holdable set of objects. Every noun is
a Pydantic model in `metalworks.contract` — the stable surface you can depend on.

## Demand research

The research vertical turns a question into a grounded report.

- **`ResearchBrief`** — what you want to learn: the question, the subreddits to
  cover, success criteria, and a relevance rubric. The input. Build one by hand,
  let `Metalworks().plan(prompt)` walk the planner, or just pass a question
  string to `.research()`.
- **`DemandReport`** — the output: `ranked_clusters`, web `findings`, audience and
  market sizing, a `verdict`, and a `partial` / `caveat` pair set when a
  best-effort stage degraded.
- **`InsightCluster`** — one ranked theme, scored by `demand_score` (which weights
  *distinct-author breadth* above single-post virality). Carries a `claim`,
  `distinct_author_count`, `mention_count`, a `signal` chip, and its `quotes`.
- **`QuoteCitation`** — a real Reddit quote whose `text` exact-matches a stored
  comment. A cluster with zero verified quotes is never shipped
  (`no-quote-no-theme`).
- **`WebFinding`** — a web claim whose `source_url` comes from the grounding
  tool's citation metadata, never from model prose.

```
ResearchBrief ──▶ run_research ──▶ DemandReport
                                    ├─ ranked_clusters: [InsightCluster ─▶ quotes: [QuoteCitation]]
                                    ├─ findings:        [WebFinding]
                                    └─ verdict / audience / sizing
```

## Reddit engagement

The Reddit vertical searches, reads, and (carefully) acts.

- **`RedditPost` / `RedditComment`** — the corpus primitives (title, body, score,
  permalink, salted `author_hash`).
- **`SubredditIntel`** — community metadata: description, subscribers, rules, top
  posts.
- **`Opportunity`** — a discovered thread + a drafted reply + its compliance
  verdict. The discovery loop emits these; nothing is ever posted from one without
  an explicit, gated action.
- **`ComplianceVerdict`** — the deterministic gate's output: `pass_`, `violations`,
  `confidence`. Below a confidence threshold the caller escalates to the LLM judge.
- **`DiscoveryContext`** — the public seam you inject your knowledge through:
  `voice_guidelines`, `winning_examples`, `pinned_notes`, `avoid`, and `personas`.
- **`Persona` / `PersonaSet`** — voice profiles keyed by account type. The
  `background` field MUST be authentic; fabricated backstories are prohibited.

```
queries ──▶ run_discovery ──▶ [Opportunity]
                               ├─ post:        RedditPost
                               ├─ draft_reply: str (in your Persona's voice)
                               └─ compliance:  ComplianceVerdict
```

## How they connect

Both verticals consume the same swappable protocols — `ChatModel`,
`EmbeddingProvider`, `SearchProvider`, `CorpusReader`, and the typed storage
repos. See [Building blocks](/docs/building-blocks) for the protocols, and the
[Protocols reference](/docs/reference-protocols) for their exact shapes.
