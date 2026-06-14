---
title: "Python SDK"
description: "The Metalworks facade: how to construct it, run demand research, and call every capability from positioning to launch — plus the .reddit and .discovery namespaces."
---

`from metalworks import Metalworks` — the one object you construct. It's the easy path over
the functions in [Extending metalworks](/docs/extending); drop down to those whenever you
need more control.

## Construction

```python
Metalworks(
    *, chat=None, fast_chat=None, embeddings=None,
    store=None, reader=None, search=None, comments=None,
    model=None, fast_model=None,
)
```

Everything is optional and resolved lazily on first use. Pass a `model` / `fast_model` ref
(see [Configuration](/docs/configuration)) to pick a provider, or pass a fully-constructed
object to swap that layer. `store` defaults to in-memory; `reader` defaults to Arctic Shift.
Constructing with no keys never raises — a `MissingKeyError` only surfaces when a call
actually needs a key.

### `Metalworks.demo()`

A fully offline facade: fake models + a small bundled corpus. Runs the whole research
pipeline with **zero keys and zero network**. Requires the `[arctic]` extra.

```python
Metalworks.demo().research("Is there demand for a focus supplement?",
                           subreddits=["Supplements"])
```

## Research

| Method | Returns | Notes |
| --- | --- | --- |
| `.research(question, *, subreddits=None, time_window_months=None, per_sub_limit=None, max_findings=10)` | `Research` | `question` is a string or a `ResearchBrief`. The `DemandReport` is on `.demand`. With no subreddits, the planner picks them. |
| `.plan(prompt)` | `ResearchBrief` | Walks the D1-D8 planner choosing recommended answers. |

## Everything you generate from a report

Each method takes the `Research` bundle (or a bare `DemandReport`) and threads the resolved
`ResearchDeps` for you — no hand-built deps, no private internals. See the
[walkthrough](/docs/walkthrough) for the flow end to end, and the per-capability guides for
detail.

| Method | Returns | What it does |
| --- | --- | --- |
| `.deps` (property) | `ResearchDeps` | The resolved deps — the escape hatch to call the raw functions. |
| `.positioning(research)` | `PositioningBrief` | Your angle: who it's for + a price hypothesis. |
| `.competitors(research)` | `CompetitorMap` | Direct / adjacent / status-quo rivals, with cited gaps. |
| `.surface(research, positioning)` | `SurfaceRecommendation` | A grounded surface pick (web, mobile, CLI…) + rubric. |
| `.ux(research, positioning, surface)` | `UxSkeleton` | A 3-5 screen skeleton (`surface` is a `SurfaceKind`). |
| `.site(research, positioning=None)` | `MarketingSite` | A marketing site with verbatim, cited copy. |
| `.render_site(site, research=None)` | `str` | A self-contained `index.html`. |
| `.build_spec(research, positioning=None, surface="web", *, stack="empty")` | `BuildSpec` | A grounded build spec. |
| `.scaffold(spec, research, dest, *, base="empty")` | `list[Path]` | Writes the scaffold with the real quotes behind every feature. |
| `.launch(research, positioning=None)` | `list[LaunchAsset]` | Cited drafts (`[]` on a no-go). Never posts. |
| `.channel_plan(research, surfaces=None)` | `ChannelPlan` | A deterministic, human-gated launch plan. |
| `.content_plan(research)` | `ContentPlan` | A deterministic, zero-key content/SEO plan. |

## `.reddit`

Read and intel surfaces are zero-key; posting is gated and audited. The Reddit client and
its rate limiter are shared across calls on the instance.

| Method | Returns | Key? |
| --- | --- | --- |
| `.reddit.search(query, *, subreddit=None, limit=15)` | `list[RedditPost]` | no |
| `.reddit.subreddit(name)` | `SubredditIntel` | no |
| `.reddit.comments(post_url, *, limit=10)` | `list[RedditComment]` | no |
| `.reddit.rules(name)` | `list[str]` | no |
| `.reddit.inbox(*, access_token, limit=25)` | `list[InboxItem]` | OAuth |
| `.reddit.post(post_url, text, *, username)` | `PostResult` | OAuth + creds |

`.reddit.post` runs the compliance check first and **refuses on a block verdict** (returning
a failed `PostResult`); every attempt is appended to `~/.metalworks/post-log.jsonl`.

## `.discovery`

| Method | Returns | Notes |
| --- | --- | --- |
| `.discovery.run(queries, *, subreddits=None, max_opportunities=30, context=None)` | `list[Opportunity]` | the full filter → generate → gate loop |
| `.discovery.filter(post, *, context=None)` | `FilterDecision \| None` | the filter building block |
| `.discovery.generate(post, *, persona=None, account_type="expert", context=None, subreddit_rules=None)` | `ReplyGenerationV2 \| None` | the reply building block |

## Stability

The `Metalworks` facade method signatures are part of the stable public surface (alongside
`metalworks.contract` and the MCP tools). Breaking changes go through a `DeprecationWarning`
at least one minor version ahead.
</content>
