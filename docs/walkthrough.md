---
title: "Build a startup: end to end"
description: "Walk one real idea from a single sentence to a launch plan — demand research, positioning, design, a build spec, and launch copy, in order, with one report behind all of it."
---

This is the whole thing in one page: take an idea, find out if people want it, and turn it
into everything you need to launch. Each step is one call. They all read from the **one
demand report** you produce first, so every recommendation traces back to a real Reddit
comment.

Set a provider key first (see [Installation](/docs/installation)), then:

```python
from metalworks import Metalworks

mw = Metalworks()
```

## 1. Is there demand?

Start with one sentence about your idea. metalworks reads real Reddit threads and gives you
a go/no-go plus the actual needs people voiced.

```python
research = mw.research(
    "an affordable, jitter-free focus supplement for developers",
    subreddits=["Nootropics", "Supplements"],   # omit to let it pick
)
report = research.demand

print(report.verdict)                 # e.g. "Strong demand — 312 distinct voices..."
for c in report.ranked_clusters:
    print(c.distinct_author_count, "people:", c.claim)
```

If the demand is thin, it says so here — and the later steps stay honest about it instead of
inventing an opportunity. Everything below runs on this `report`. → [Demand research](/docs/demand-research)

## 2. Find your angle and your competitors

```python
positioning = mw.positioning(research)
print(positioning.positioning_statement)   # who it's for, and why it's different

competitors = mw.competitors(research)
for rival in competitors.competitors:
    for gap in rival.gaps:                  # an opening, backed by a real complaint
        print(rival.name, "misses:", gap.claim)
```

Your positioning is built from the unmet needs in the report; each competitor gap is a real
complaint someone posted. → [Positioning & competitors](/docs/positioning)

## 3. Decide what to build, and write the site

```python
surface = mw.surface(research, positioning)      # web? mobile? CLI? — and why
ux = mw.ux(research, positioning, surface.chosen)  # the 3-5 screens you need

site = mw.site(research, positioning)            # marketing copy, every line a real quote
html = mw.render_site(site, research)            # a self-contained index.html
open("index.html", "w").write(html)
```

The marketing copy isn't AI prose — each section is a verbatim quote from a real user, with
a link back to the thread. → [Design & marketing site](/docs/design)

## 4. Turn it into a build plan

metalworks writes the **spec**, not the product. It maps the demand to a feature list and
scaffolds a project your own coding agent (Claude Code, Cursor, etc.) then builds.

```python
spec = mw.build_spec(research, positioning, surface.chosen)
for feature in spec.features:
    print(feature.title, "—", feature.rationale)   # each tied to real demand

mw.scaffold(spec, research, "./my-startup")        # writes the build harness
```

The scaffold includes a frozen list of the real quotes behind every feature, so whatever
your agent builds stays true to what people actually asked for. → [Build spec](/docs/build-spec)

## 5. Launch and grow

```python
assets = mw.launch(research, positioning)   # Product Hunt / Show HN / X drafts (never posts)
plan = mw.channel_plan(research)            # a step-by-step launch checklist you run

content = mw.content_plan(research)         # an SEO/content plan, one page per real need
```

Launch copy is drafting-only — metalworks never posts anything. Each claim in a draft is
backed by a quote; the content plan lists the real threads to cite so people and AI search
engines find you. → [Launch assets](/docs/launch) · [Content & SEO](/docs/content-seo)

## That's the loop

One idea → one grounded report → positioning, design, a build plan, launch copy. Because it
all reads from the same report, **every recommendation links back to a real comment you can
open and read for yourself.** That's the difference between this and a tool that just makes
things up — see [why you can trust the output](/docs/how-it-works).

Run `metalworks init` first and metalworks **remembers** all of this — each run is saved under
`.metalworks/` and later steps chain off its `report_id` instead of re-running research. See
[Projects & memory](/docs/projects).

Prefer the command line or an agent? The exact same flow is available in the
[CLI](/docs/cli), the [MCP tools](/docs/mcp-tools), and the
[Claude Code plugin](/docs/claude-code).
