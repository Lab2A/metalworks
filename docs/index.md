---
title: "metalworks"
description: "Go from a startup idea to launch, grounded in what people actually want. Validate demand, get positioning, a design system, a build plan, and launch copy — every claim backed by a real quote you can open."
---

**metalworks turns a startup idea into a launch plan, grounded in real demand.**

Give it one sentence about what you want to build. It reads real conversations — Reddit,
Hacker News, the web, or your own data — to tell you whether people actually want it, then
turns that into the things you need to launch: your positioning, the competitors to beat, a
design system, a build plan for your coding agent, and launch copy. **Every claim links back
to a real quote you can click — nothing is invented.**

It's a Python library you install (also a CLI, an MCP server, and a Claude Code plugin).

## Your first report

Install metalworks with a provider SDK, and set **one** key — any provider works (embeddings
default to a local model, so there's no second key to set):

```bash
pip install "metalworks[research,openai]"     # or [research,google], [research,anthropic]
export OPENAI_API_KEY=...                      # or ANTHROPIC_API_KEY / GOOGLE_API_KEY
```

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus supplement for developers
```

```python Python
from metalworks import Metalworks

mw = Metalworks()                  # provider inferred from your env key
research = mw.research(
    "an affordable, jitter-free focus supplement for developers",
    subreddits=["Nootropics", "Supplements"],
)
report = research.demand           # .research() returns a report

print(report.demand_summary)       # how strong is the demand? a one-line summary
for cluster in report.ranked_clusters:
    print(cluster.distinct_author_count, "people:", cluster.claim)
    for quote in cluster.quotes:   # the real comments behind it — nothing invented
        print("  ", quote.source_url)
```

</CodeGroup>

That's a real report grounded in real conversations you can open — see the full
[Quickstart](/docs/quickstart).

## What you can do with it

Run demand research once, then turn that one report into whatever you need next. The work
falls into five stages — each step is a single call:

| Stage | What you get |
| --- | --- |
| **Research** | [Demand research](/docs/demand-research) — a read on how strong the demand is + the real needs people voiced, each backed by quotes. Run the full [validation loop](/docs/validation-loop) — frame an idea, weigh demand against what already exists, get a **GO / PIVOT / NO-GO** call — then your [positioning](/docs/positioning) (who it's for, why it's different) and the [competitors](/docs/competitors) to beat. |
| **Design** | [A design system](/docs/design-system) — an aesthetic direction and a SAFE/RISK choice per dimension, read from what rivals actually do. |
| **Build** | [A build spec](/docs/build-spec) — what to build (surface + screens), a feature plan mapped to real demand, and a project scaffold your coding agent executes. |
| **Launch** | [Launch assets](/docs/launch) — Product Hunt / Show HN / X drafts, each line backed by a quote (it never posts). |
| **Grow** | [Content & SEO](/docs/content-seo) — a plan that gets you cited by people and AI search — and [Reddit engagement](/docs/reddit-engagement): find threads to join and draft honest replies (you approve every post). |

New here? Walk one idea from start to finish in the [end-to-end walkthrough](/docs/walkthrough).

## Why it's not just another AI tool

Most "AI market research" makes up plausible-sounding answers. metalworks doesn't. It reads
real conversations across real sources, and **anything it can't back with an actual quote, it
drops.** When the demand isn't there, it tells you — instead of inventing an opportunity.
That's what makes the output safe to act on. See [why you can trust the output](/docs/how-it-works).

## Four ways to use it

The same engine, whichever fits your workflow:

- **Python library** — `from metalworks import Metalworks`. The full toolkit, embeddable. → [SDK reference](/docs/python-sdk)
- **CLI** — `metalworks research run --question "..."`, then `metalworks build init`, etc. → [CLI](/docs/cli)
- **MCP server** — `metalworks mcp serve`. Drive it from any MCP-aware agent or app. → [MCP tools](/docs/mcp-tools)
- **Claude Code plugin** — `/demand-report`, `/build-spec`, and more as slash commands. → [Claude Code plugin](/docs/claude-code)

The docs are split to match: **Documentation** (this section, the workflow end to end),
**Claude Code & plugins** (the slash commands), and the **SDK reference** (the Python API and
how to extend it).

## Install

```bash
pip install "metalworks[research]"     # the demand-research pipeline
```

Need only the data tools, or want to keep it lean? See [Installation](/docs/installation)
for the full options. metalworks is open source (MIT) on
[GitHub](https://github.com/Lab2A/metalworks).
