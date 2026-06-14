---
title: "Reddit engagement"
description: "Find Reddit threads worth joining and draft honest, disclosed replies that pass a compliance check. You approve every post — it never auto-posts."
---

Find live Reddit threads where your product genuinely helps, and draft a reply in a real
persona's voice that passes a compliance check before you ever see it. **You approve every post —
nothing is posted automatically.**

```python
from metalworks import Metalworks
from metalworks.contract import DiscoveryContext, Persona, PersonaSet

mw = Metalworks()

context = DiscoveryContext(
    voice_guidelines=["Be specific. Name real tools. No marketing voice."],
    personas=PersonaSet(personas={
        "expert": Persona(voice_rubric="terse senior engineer", background="ran ops for 8 years"),
    }),
)

opps = mw.discovery.run(
    queries=["log aggregation on a budget", "elk alternatives"],
    subreddits=["sysadmin", "devops"],
    context=context,
)
for o in opps:
    print(o.post.url, "→", o.draft_reply[:120], "| passed compliance:", o.compliance.pass_)
```

`discovery.run` searches your queries, filters each candidate for relevance, drafts a reply in the
matching persona's voice, runs it through a compliance check, and returns `Opportunity` objects.
**Nothing is posted** — you get gated drafts to review.

## What you give it / what you get back

**You give it:** your search queries, the subreddits to search, and a `DiscoveryContext` — your
voice guidelines and the personas replies should be written in.

**You get back:** a list of `Opportunity` objects, each with the live post, a drafted reply, and
the compliance verdict (`pass_`, `violations`, `confidence`). You read every one and decide what,
if anything, to post.

## Read public Reddit (zero keys)

The Reddit reader needs only the `[reddit]` extra — no API key, no OAuth:

```python
posts    = mw.reddit.search("budget log aggregation", subreddit="sysadmin")
intel    = mw.reddit.subreddit("sysadmin")     # description, subscribers, rules, top posts
rules    = mw.reddit.rules("sysadmin")
comments = mw.reddit.comments(posts[0].url)
```

The Reddit client and its rate limiter are shared across calls, so a loop of searches stays
within Reddit's limits.

## The compliance check

The check is a standalone, deterministic function — usable with no Reddit, no posting, no model:

```python
from metalworks.reddit import heuristic_check

verdict = heuristic_check("This is a genuinely helpful, specific reply.")
verdict.pass_, verdict.violations, verdict.confidence
```

Below a confidence threshold, it escalates to an LLM judge
(`metalworks.discovery.llm_judge`). The check is the security boundary, not a suggestion: the
posting tools refuse on a block verdict regardless of what a model asked for.

## Posting (you approve, every time)

```python
result = mw.reddit.post(post_url, draft_text, username="my_account")
```

Posting requires `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` and a connected account
(`metalworks reddit auth login`). Every attempt — sent or blocked — is appended to
`~/.metalworks/post-log.jsonl`. A draft that fails the compliance check is refused before it ever
reaches Reddit.

> Authentic, disclosed engagement only. The
> [usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md) prohibits fake
> personas, invented backstories, and coordinated inauthentic behavior.

## When the run is long

A full discovery run can take minutes (comment hydration is rate-limited at ~1.5 req/s), so for
agent and MCP use it runs as a **start → poll → result** job instead of one blocking call:

```
discovery_start(...)   → { run_id }
discovery_status(run_id) → { state: "running" | "done" | "error" }
discovery_result(run_id) → { opportunities }
```

The Python `mw.discovery.run(...)` call is synchronous and blocks; use the job tools when a host
model's tool-call timeout is in play. The CLI mirrors this with `metalworks discovery run`.

To wire the filter, generation, and gate together as your own building blocks, see
[Build your own agents](/docs/ai-agents).

---

Next: draft your [launch assets](/docs/launch) or a [content & SEO plan](/docs/content-seo) from
the same report. Or read [why you can trust the output](/docs/how-it-works).
