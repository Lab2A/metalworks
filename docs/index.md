---
title: "metalworks"
description: "Go from a startup idea to launch, grounded in what people actually want. Validate demand, get positioning, a marketing site, a build plan, and launch copy — every claim backed by a real Reddit quote."
---

**metalworks turns a startup idea into a launch plan, grounded in real demand.**

Give it one sentence about what you want to build. It reads real Reddit conversations to
tell you whether people actually want it, then turns that into the things you need to
launch: your positioning, the competitors to beat, a marketing site, a build plan for your
coding agent, and launch copy. **Every claim links back to a real comment you can click —
nothing is invented.**

It's a Python library you install (also a CLI, an MCP server, and a Claude Code plugin).

## See it in 60 seconds

No API key, no setup — run the bundled offline demo:

```bash
pip install "metalworks[research]"
```

```python
from metalworks import Metalworks

research = Metalworks.demo().research(
    "an affordable, jitter-free focus supplement for developers",
    subreddits=["Nootropics", "Supplements"],
)
report = research.demand           # .research() returns a report

print(report.verdict)              # is there real demand? a one-line go / no-go
for cluster in report.ranked_clusters:
    print(cluster.distinct_author_count, "people:", cluster.claim)
```

Then add a provider key (Anthropic, OpenAI, or Google) and point it at your own idea to
get a real report. See [Quickstart](/docs/quickstart).

## What you can do with it

Run demand research once, then turn that one report into whatever you need next. Each is a
single call:

| Capability | What you get |
| --- | --- |
| [Demand research](/docs/demand-research) | A go/no-go verdict + the real needs people voiced, each backed by quotes |
| [Positioning & competitors](/docs/positioning) | Your angle (who it's for, why it's different) + the rivals to beat |
| [Design & marketing site](/docs/design) | What to build (surface + screens) + a marketing site with cited copy |
| [Build spec](/docs/build-spec) | A build plan + a project scaffold your coding agent executes |
| [Launch assets](/docs/launch) | Product Hunt / Show HN / X drafts, each line backed by a quote (never posts) |
| [Content & SEO](/docs/content-seo) | A content plan that gets you cited by people and AI search |
| [Reddit engagement](/docs/reddit-engagement) | Find threads to join + draft honest replies (you approve every post) |

New here? Walk one idea from start to finish in the [end-to-end walkthrough](/docs/walkthrough).

## Why it's not just another AI tool

Most "AI market research" makes up plausible-sounding answers. metalworks doesn't. It reads
real Reddit threads, and **anything it can't back with an actual quote, it drops.** When the
demand isn't there, it tells you — instead of inventing an opportunity. That's what makes the
output safe to act on. See [why you can trust the output](/docs/how-it-works).

## Four ways to use it

The same engine, whichever fits your workflow:

- **Python library** — `from metalworks import Metalworks`. The full toolkit, embeddable.
- **CLI** — `metalworks research run --question "..."`, then `metalworks build init`, etc.
- **MCP server** — `metalworks mcp serve`. Drive it from any MCP-aware agent or app.
- **Claude Code plugin** — `/demand-report`, `/build-spec`, and more as slash commands.

## Install

```bash
pip install "metalworks[research]"     # the demand-research pipeline
```

Need only the data tools, or want to keep it lean? See [Installation](/docs/installation)
for the full options. metalworks is open source (MIT) on
[GitHub](https://github.com/Lab2A/metalworks).
