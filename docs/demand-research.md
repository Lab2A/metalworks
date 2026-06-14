---
title: "Demand research"
description: "Give metalworks one sentence about your idea. It reads real Reddit threads and tells you whether people actually want it — a go/no-go verdict plus the real needs people voiced, each backed by a quote you can click."
---

**Find out whether people actually want your idea — backed by real conversations, not a guess.**

Give metalworks one sentence about what you want to build. It reads real Reddit
threads and hands back a go/no-go verdict plus the specific needs people voiced,
each one backed by a real comment you can open and read. This is the report every
other step runs on, so do it first.

## Run it

```python
from metalworks import Metalworks

mw = Metalworks()                       # picks up your provider key from the env
research = mw.research(
    "an affordable, jitter-free focus supplement for developers",
    subreddits=["Nootropics", "Supplements"],   # omit to let it pick
)
report = research.demand                # .research() returns a bundle; the report is .demand

print(report.verdict)                   # is there real demand? a one-line go / no-go
for c in report.ranked_clusters:
    print(c.distinct_author_count, "people:", c.claim)
    for q in c.quotes:                  # the real comments behind the claim
        print("   ", q.permalink, "→", q.text[:80])
```

From the command line:

```bash
metalworks research run --question "an affordable, jitter-free focus supplement for developers"
```

A run prints something like:

```
Strong demand — 312 distinct voices across 9 themes.
  187 people: jitter and crashes from caffeine-based focus products
   https://reddit.com/r/Nootropics/comments/... → "every pre-workout style focus thing wrecks me by 2pm..."
   94 people: hard to find something that isn't priced like a luxury subscription
```

## What you give it / what you get back

You give it **one sentence** and, optionally, a list of subreddits. You get back a
report on `research.demand`:

| Field | What it is |
| --- | --- |
| `report.verdict` | A one-line go / no-go summary. |
| `report.ranked_clusters` | The real needs people voiced, ranked by how many distinct people raised each. Each cluster has a `claim`, a `distinct_author_count`, and its `quotes`. |
| `report.web_findings` | Supporting facts pulled from the web, each carrying its real source URL. |
| `report.partial`, `report.caveat` | Set when part of the run came up short (see below). |

Every quote is the exact text of a real stored comment, matched — not paraphrased.
Every count is the result of counting distinct authors, not a model's estimate. If
a finding can't be tied to a real quote or a real source URL, metalworks drops it
rather than shipping it. That's why a "go" here is one you can defend line by line —
see [why you can trust the output](/docs/how-it-works).

## Want a richer brief first?

`mw.research(question)` works from one sentence. If you'd rather refine the question,
set success criteria, and let metalworks suggest subreddits before it runs, plan first:

```python
brief = mw.plan("Should I build a focus-supplement brand for developers?")
report = mw.research(brief).demand      # hand the brief straight back
```

## Scope what it reads

```python
mw.research(
    "...",
    subreddits=["Nootropics"],
    time_window_months=6,   # how far back to read (default 12)
    per_sub_limit=500,      # cap submissions pulled per subreddit
    max_findings=20,        # cap web findings
)
```

By default metalworks reads from public Reddit archives. To point it at your own
data instead, see [bring your own corpus](/docs/configuration).

## When the result is thin

metalworks tells you when there isn't a real opening instead of inventing one. If
the demand is weak or a part of the run degraded — say it couldn't reach the web —
the report comes back with `partial=True` and a plain-English `caveat` saying what
happened. The later steps stay honest about it too, rather than building a launch
plan on signal that isn't there.

## Next

You have the report. Now turn it into the things you need to launch:
→ [Positioning & competitors](/docs/positioning) · [Design & marketing site](/docs/design) ·
[the full walkthrough](/docs/walkthrough) · [why you can trust it](/docs/how-it-works)
