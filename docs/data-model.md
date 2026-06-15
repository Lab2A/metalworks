---
title: "Data model"
description: "The objects metalworks gives you back: the source-neutral corpus records, the demand report and its ranked clusters, the verbatim quotes behind them, web findings, and the Reddit objects."
---

When you run research, this is what you get back — and what every later step reads from. Each
one is a Pydantic model in `metalworks.contract`, the part of the API you can depend on. There
aren't many, and they all connect through one report.

## The conversations behind a report

Every [source](/docs/sources) — Reddit, Hacker News, the web, your own — produces items in the
same two shapes, so the rest of metalworks doesn't care where a quote came from:

- **`CorpusRecord`** — one thing people are talking about (a Reddit post, an HN story, a web
  page): `id`, `source`, `url`, `title`, `text`, `author_hash`, `engagement`, `created_at`,
  plus an `extra` map for anything source-specific (subreddit, domain, rating…).
- **`CorpusComment`** — a comment under a record (a reply), the same fields plus a `parent_id`.

A quote in a report points back to the exact record or comment it came from, so you can always
trace a claim to the real conversation. See [your research data](/docs/corpus).

## The demand report and what's inside it

`mw.research(...)` returns a `Research` bundle; the report itself is on `.demand`. Everything
else you generate later reads from this one report.

- **`DemandReport`** — the output of demand research: a one-line `verdict` (go / no-go), the
  `ranked_clusters` (the real needs people voiced), web `web_findings`, audience and market
  sizing. If a best-effort stage degraded, `partial` is set with a plain-language `caveat`.
  `version`, `lineage_id`, and `parent_report_id` track a report's earlier versions when you
  [update it](/docs/corpus).
- **`InsightCluster`** — one ranked need. Carries a `claim` (the need, in plain words),
  `distinct_author_count` (how many different people raised it), `breadth_count` /
  `breadth_unit` (the same idea across sources — different people, or different sites for web
  pages), `mention_count`, a `signal` chip, a `demand_score` that ranks by how many people
  care over how viral one post was, and the `quotes` behind it.
- **`ResolvedCitation`** — a verbatim quote. Its `text` is the exact text of a real comment,
  and it carries `source_url` (open it and read it yourself), `source` / `source_name` (e.g.
  `reddit` / `r/Supplements`), and `engagement`. The quote text and link are stored right on it,
  so a report makes sense on its own — even handed to someone without your saved data. A
  cluster with zero verified quotes never ships: metalworks drops anything it can't back with a
  real quote.
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
