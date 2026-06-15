---
title: "Data model"
description: "The objects metalworks gives you back: the source-neutral corpus records, the demand report and its ranked clusters, the verbatim quotes behind them, web findings, and the Reddit objects."
---

These are the objects metalworks gives you back. Every one is a Pydantic model in
`metalworks.contract` — the stable surface you can depend on. There aren't many, and they
all connect through one report, which resolves back to the source-neutral records in the
[corpus](/docs/corpus).

## The corpus spine

Every source — Reddit, Hacker News, the web, your own — maps its items onto one shape, so
the report layer never has to care where a quote came from:

- **`CorpusRecord`** — a top-level item: `id`, `source`, `source_id`, `url`, `title`, `text`,
  `author_hash`, `engagement`, `created_at`, and an open `extra` map for source-specific
  fields (subreddit, domain, rating…).
- **`CorpusComment`** — a quote-bearing sub-item of a record (a reply or thread comment),
  the same spine plus a `parent_id`.

Citations resolve against these by id, so the chain runs from a line on your landing page
back to the real record. See [the corpus](/docs/corpus) and [sources](/docs/sources).

## The demand report and what's inside it

`mw.research(...)` returns a `Research` bundle; the report itself is on `.demand`. Everything
else you generate later reads from this one report.

- **`DemandReport`** — the output of demand research: a one-line `verdict` (go / no-go), the
  `ranked_clusters` (the real needs people voiced), web `web_findings`, audience and market
  sizing. If a best-effort stage degraded, `partial` is set with a plain-language `caveat`.
  A report is a versioned view over the corpus: `lineage_id`, `version`, and
  `parent_report_id` link it to its earlier versions when you [refresh](/docs/corpus) it.
- **`InsightCluster`** — one ranked need. Carries a `claim` (the need, in plain words),
  `distinct_author_count` (distinct authors, authored sources only), `breadth_count` /
  `breadth_unit` (the source-neutral count — distinct authors plus distinct domains for
  authorless web; `"authors"`, `"domains"`, or `"voices"`), `mention_count`, a `signal` chip,
  a `demand_score` that weights **breadth** over how viral a single post was, and the
  `quotes` behind it.
- **`ResolvedCitation`** — a verbatim quote, source-neutral and self-contained. Its `text` is
  the exact text of a real stored record, and it carries `source_url` (open it and read it
  yourself), `source` / `source_name` (e.g. `reddit` / `r/Supplements`), `engagement`, and the
  `record_id` it resolves to in the corpus. This is the *materialized, portable* form that
  serializes to disk and over MCP, so a report stays readable detached from the corpus;
  `CitationRef` is the thin live-view pointer used internally. A cluster with zero verified
  quotes never ships — metalworks drops anything it can't back with a real quote.
- **`WebFinding`** — a fact pulled from the web. Its `source_url` comes from the search
  tool's citation data, never from model prose. No source, no finding.
- **`ReportDiff`** — what changed between two versions of a report: count deltas (threads,
  distinct voices, clusters, source distribution) plus themes added / faded / shifted. You
  get one back from `mw.refresh(...)` or `metalworks research diff`. See [the corpus](/docs/corpus).

```
ResearchBrief ──▶ run_research ──▶ DemandReport
                                    ├─ ranked_clusters: [InsightCluster ─▶ quotes: [ResolvedCitation]]
                                    ├─ web_findings:    [WebFinding]
                                    └─ verdict / audience / sizing
```

The input is a **`ResearchBrief`** — the question, the subreddits to cover, success criteria,
and a relevance rubric. You rarely build one by hand: pass a question string straight to
`.research()`, or let `Metalworks().plan(prompt)` assemble one for you.

## Everything points back to the report

Positioning, the marketing site, the build spec, and launch copy are all derived objects.
Each one is generated from the report and links its claims back to the same quotes:

- **`PositioningBrief`** — your angle: who it's for and why it's different, built from the
  unmet needs in the report.
- **`CompetitorMap`** — the rivals to beat, each `gap` tied to a real complaint someone
  posted.
- **`SurfaceRecommendation` / `UxSkeleton`** — what to build (web, mobile, CLI…) and the
  3-5 screens you need.
- **`MarketingSite`** — marketing copy where each section is a verbatim quote with a link
  back to the thread, not AI prose.
- **`BuildSpec`** — a feature list where every feature maps to a real need; anything that
  can't be tied to a quote is dropped.
- **`LaunchAsset` / `ChannelPlan` / `ContentPlan`** — launch drafts and a human-run plan,
  each line backed by a quote. metalworks never posts.

So whatever you generate, the chain runs from a real comment all the way to the line on your
landing page — see [why you can trust the output](/docs/how-it-works).

## Reddit objects

The Reddit tools search, read, and (carefully) draft replies.

- **`RedditPost` / `RedditComment`** — what a thread looks like: title, body, score,
  permalink, and a salted `author_hash` (never a raw username).
- **`SubredditIntel`** — community metadata: description, subscribers, rules, top posts.
- **`Opportunity`** — a thread metalworks found, plus a drafted reply and its compliance
  result. Nothing is ever posted from one without your explicit, per-action approval.
- **`ComplianceVerdict`** — the result of the offline gate over a draft: `pass_`,
  `violations`, `confidence`.
- **`DiscoveryContext`** — where you inject your own knowledge: `voice_guidelines`,
  `winning_examples`, `pinned_notes`, `avoid`, and `personas`.
- **`Persona` / `PersonaSet`** — voice profiles keyed by account type. The `background`
  field must be authentic; fabricated backstories are not allowed.

```
queries ──▶ run_discovery ──▶ [Opportunity]
                               ├─ post:        RedditPost
                               ├─ draft_reply: str (in your Persona's voice)
                               └─ compliance:  ComplianceVerdict
```

## How they connect

Both sets of objects run on the same swappable protocols — `ChatModel`, `EmbeddingProvider`,
`SearchProvider`, `CorpusReader`, and the typed storage repos. See [Extending
metalworks](/docs/extending) for the protocols, and the [Protocols
reference](/docs/protocols) for their exact shapes.
