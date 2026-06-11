---
title: "Reddit Engagement guide"
description: "Search, intel, the discovery loop, the compliance gate, and gated posting — plus the async job pattern for long runs."
---

The Reddit vertical is everything that touches Reddit directly: reading public
data (no keys), running the discovery loop, gating drafts through compliance, and
posting through OAuth. Each piece is usable on its own.

## Read public Reddit (zero keys)

```python
from metalworks import Metalworks
mw = Metalworks()

posts = mw.reddit.search("budget log aggregation", subreddit="sysadmin")
intel = mw.reddit.subreddit("sysadmin")        # description, subscribers, rules, top posts
rules = mw.reddit.rules("sysadmin")
comments = mw.reddit.comments(posts[0].url)
```

These need only the `[reddit]` extra — no API key, no OAuth. The Reddit client and
its rate limiter are shared across calls, so a loop of searches stays within
Reddit's limits.

## The discovery loop

`discovery.run` searches your queries, filters each candidate for relevance,
drafts a reply in the matching persona's voice, gates it through compliance, and
returns `Opportunity` objects. **Nothing is posted** — it produces gated drafts.

```python
from metalworks.contract import DiscoveryContext, Persona, PersonaSet

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
    print(o.post.url, "→", o.draft_reply[:120], "| pass:", o.compliance.pass_)
```

See [Build your own](/docs/build-your-own) to use the filter, generation, and
gate as separate building blocks.

## The compliance gate

The gate is a standalone, deterministic function — usable with no Reddit, no
posting, no LLM:

```python
from metalworks.reddit import heuristic_check

verdict = heuristic_check("This is a genuinely helpful, specific reply.")
verdict.pass_, verdict.violations, verdict.confidence
```

Below a confidence threshold, escalate to the LLM judge (`metalworks.discovery.llm_judge`).
The gate is the security boundary, not the prompt: the posting tools refuse on a
block verdict regardless of what a model asked for.

## Posting (gated + audited)

```python
result = mw.reddit.post(post_url, draft_text, username="my_account")
```

Posting requires `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` and a connected
account (`metalworks reddit auth login`). Every attempt — sent or blocked — is
appended to `~/.metalworks/post-log.jsonl`. A draft that fails the compliance
check is refused before it ever reaches Reddit.

> Authentic, disclosed engagement only. The [usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md)
> prohibits fake personas, invented backstories, and coordinated inauthentic
> behavior.

## Long runs: the async job pattern

A full research run takes minutes (comment hydration alone is rate-limited at
~1.5 req/s), so the MCP server exposes the pipeline as a **start → poll → result**
job instead of one blocking call:

```
research_start(brief)   → { run_id }
research_status(run_id) → { state: "running" | "done" | "error" }
research_result(run_id) → { report }
```

Discovery uses the same pattern. The Python `mw.research(...)` call is synchronous
and blocks; use the job tools when a host model's tool-call timeout is in play.
The CLI mirrors this with `metalworks research run` and `metalworks discovery run`.
