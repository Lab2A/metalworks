---
title: "Metalworks client"
description: "The high-level facade: construction, research, and the .reddit / .discovery namespaces."
---

`from metalworks import Metalworks` — the one-object front door. Everything below
is the easy path over the functions in [Building blocks](/docs/building-blocks);
drop down to those whenever you need more control.

## Construction

```python
Metalworks(
    *, chat=None, fast_chat=None, embeddings=None,
    store=None, reader=None, search=None, comments=None,
    model=None, fast_model=None,
)
```

Everything is optional and resolved lazily on first use. Pass a `model` /
`fast_model` ref (see [Model configuration](/docs/model-configuration)) to pick a
provider, or pass a fully-constructed object to swap that layer. `store` defaults
to in-memory; `reader` defaults to Arctic Shift. Constructing with no keys never
raises — a `MissingKeyError` only surfaces when a call actually needs a key.

### `Metalworks.demo()`

A fully offline facade: fake models + a small bundled corpus. Runs the whole
research pipeline with **zero keys and zero network**. Requires the `[arctic]`
extra.

```python
Metalworks.demo().research("Is there demand for a focus supplement?",
                           subreddits=["Supplements"])
```

## Research

| Method | Returns | Notes |
| --- | --- | --- |
| `.research(question, *, subreddits=None, time_window_months=None, per_sub_limit=None, max_findings=10)` | `DemandReport` | `question` is a string or a `ResearchBrief`. With no subreddits, the planner picks them. |
| `.plan(prompt)` | `ResearchBrief` | Walks the D1-D8 planner choosing recommended answers. |

## `.reddit`

Read/intel surfaces are zero-key; posting is gated and audited. The Reddit client
and its rate limiter are shared across calls on the instance.

| Method | Returns | Key? |
| --- | --- | --- |
| `.reddit.search(query, *, subreddit=None, limit=15)` | `list[RedditPost]` | no |
| `.reddit.subreddit(name)` | `SubredditIntel` | no |
| `.reddit.comments(post_url, *, limit=10)` | `list[RedditComment]` | no |
| `.reddit.rules(name)` | `list[str]` | no |
| `.reddit.inbox(*, access_token, limit=25)` | `list[InboxItem]` | OAuth |
| `.reddit.post(post_url, text, *, username)` | `PostResult` | OAuth + creds |

`.reddit.post` runs the compliance check first and **refuses on a block verdict**
(returning a failed `PostResult`); every attempt is appended to
`~/.metalworks/post-log.jsonl`.

## `.discovery`

| Method | Returns | Notes |
| --- | --- | --- |
| `.discovery.run(queries, *, subreddits=None, max_opportunities=30, context=None)` | `list[Opportunity]` | the full filter → generate → gate loop |
| `.discovery.filter(post, *, context=None)` | `FilterDecision \| None` | the filter building block |
| `.discovery.generate(post, *, persona=None, account_type="expert", context=None, subreddit_rules=None)` | `ReplyGenerationV2 \| None` | the reply building block |

## Stability

The `Metalworks` facade method signatures are part of the stable public surface
(alongside `metalworks.contract` and the MCP tools). Breaking changes go through a
`DeprecationWarning` at least one minor version ahead.
