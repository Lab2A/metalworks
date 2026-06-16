---
title: "Demand research"
description: "Give metalworks one sentence about your idea. It reads real conversations — Reddit, Hacker News, the web — and tells you whether people actually want it: a go/no-go verdict plus the real needs people voiced, each backed by a quote you can click."
---

**Find out whether people actually want your idea — backed by real conversations, not a guess.**

Give metalworks one sentence about what you want to build. It reads real
conversations across your [sources](/docs/sources) — Reddit, Hacker News, the web,
your own data — and hands back a go/no-go verdict plus the specific needs people
voiced, each one backed by a real quote you can open and read. This is the report
every other step runs on, so do it first.

## Run it

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus supplement for developers
```

```python Python
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
        print("   ", q.source_url, "→", q.text[:80])
```

```bash CLI
metalworks research run --question "an affordable, jitter-free focus supplement for developers"
```

</CodeGroup>

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
| `report.ranked_clusters` | The real needs people voiced, ranked by how many different people raised each — not by how viral one post was. Each cluster has a `claim`, a `distinct_author_count`, and its `quotes`. |
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

### Read from more sources

metalworks reads Reddit by default, and can also read Hacker News, the web, or your
own data. Name the sources you want for a run:

```bash
metalworks research run --question "..." --source reddit --source hackernews
```

See [Sources](/docs/sources) to choose what to read from, or [use your own
data](/docs/custom-corpus) to load conversations you already have.

### Update a report later

Each run saves what it read, so your [research data](/docs/corpus) builds up over
time. Collect more, then update the report to see what changed:

```bash
metalworks corpus add --source hackernews -q "..."
metalworks research refresh <report-id>     # an updated report + what changed
```

## When the result is thin

metalworks tells you when there isn't a real opening instead of inventing one. If
the demand is weak or a part of the run degraded — say it couldn't reach the web —
the report comes back with `partial=True` and a plain-English `caveat` saying what
happened. The later steps stay honest about it too, rather than building a launch
plan on signal that isn't there.

## Next

You have the report. Now turn it into the things you need to launch:
→ [Positioning](/docs/positioning) · [Competitors](/docs/competitors) ·
[Surface & screens](/docs/design) · [Marketing site](/docs/marketing-site) ·
[the full walkthrough](/docs/walkthrough)
