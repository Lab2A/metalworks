---
title: "Build a startup: end to end"
description: "Walk one real idea from a single sentence to a launch plan — demand research, positioning, design, a build spec, and launch copy, in order, with one report behind all of it."
---

This is the whole thing in one page: take an idea, find out if people want it, and turn it
into everything you need to launch. Each step is one slash command in Claude Code — or one
Python call. They all read from the **one demand report** you produce first, so every
recommendation traces back to a real quote you can open.

Install the [Claude Code plugin](/docs/claude-code), or `pip install "metalworks[research]"`
and set one provider key (see [Installation](/docs/installation)). Then walk the five steps
below.

## 1. Is there demand?

Start with one sentence about your idea. metalworks reads real conversations — Reddit, Hacker
News, the web, or [your own data](/docs/sources) — and gives you a go/no-go plus the actual
needs people voiced.

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus supplement for developers
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research(
    "an affordable, jitter-free focus supplement for developers",
    subreddits=["Nootropics", "Supplements"],   # omit to let it pick
)
report = research.demand

print(report.verdict)                 # e.g. "Strong demand — 312 distinct voices..."
for c in report.ranked_clusters:
    print(c.distinct_author_count, "people:", c.claim)
```

</CodeGroup>

If the demand is thin, it says so here — and the later steps stay honest about it instead of
inventing an opportunity. Everything below runs on this `report`.
→ [Demand research](/docs/demand-research)

## 2. Find your angle and your competitors

<CodeGroup>

```text Claude Code
/position-wedge
/market-landscape
```

```python Python
positioning = mw.positioning(research)
print(positioning.positioning_statement)   # who it's for, and why it's different

land = mw.landscape(research)
for rival in land.competitor_map.competitors:
    for gap in rival.gaps:                  # an opening, backed by a real complaint
        print(rival.name, "misses:", gap.claim)
```

</CodeGroup>

Your positioning is built from the unmet needs in the report; each competitor gap is a real
complaint someone posted. → [Positioning](/docs/positioning) · [Competitors](/docs/competitors)

## 3. Decide what to build, and write the site

<CodeGroup>

```text Claude Code
/surface-and-ux
/generate-site
```

```python Python
surface = mw.surface(research, positioning)      # web? mobile? CLI? — and why
ux = mw.ux(research, positioning, surface.chosen)  # the 3-5 screens you need

site = mw.site(research, positioning)            # marketing copy, every line a real quote
html = mw.render_site(site, research)            # a self-contained index.html
open("index.html", "w").write(html)
```

</CodeGroup>

The marketing copy isn't AI prose — each section is a verbatim quote from a real user, with
a link back to the thread. → [Surface & screens](/docs/design) · [Marketing site](/docs/marketing-site)

## 4. Turn it into a build plan

metalworks writes the **spec**, not the product. It maps the demand to a feature list and
scaffolds a project your own coding agent (Claude Code, Cursor, etc.) then builds.

<CodeGroup>

```text Claude Code
/build-spec
```

```python Python
spec = mw.build_spec(research, positioning, surface.chosen)
for feature in spec.features:
    print(feature.title, "—", feature.rationale)   # each tied to real demand

mw.scaffold(spec, research, "./my-startup")        # writes the build harness
```

</CodeGroup>

The scaffold includes a frozen list of the real quotes behind every feature, so whatever
your agent builds stays true to what people actually asked for. → [Build spec](/docs/build-spec)

## 5. Launch and grow

<CodeGroup>

```text Claude Code
/launch-kit
/content-plan
```

```python Python
assets = mw.launch(research, positioning)   # Product Hunt / Show HN / X drafts (never posts)
plan = mw.channel_plan(research)            # a step-by-step launch checklist you run

content = mw.content_plan(research)         # an SEO/content plan, one page per real need
```

</CodeGroup>

Launch copy is drafting-only — metalworks never posts anything. Each claim in a draft is
backed by a quote; the content plan lists the real threads to cite so people and AI search
engines find you. → [Launch assets](/docs/launch) · [Content & SEO](/docs/content-seo)

## That's the loop

One idea → one grounded report → positioning, design, a build plan, launch copy. Because it
all reads from the same report, **every recommendation links back to a real quote you can
open and read for yourself.** That's the difference between this and a tool that just makes
things up — see [why you can trust the output](/docs/how-it-works).

Run `metalworks init` first and metalworks **remembers** all of this — each run is saved under
`.metalworks/` and later steps chain off its `report_id` instead of re-running research. See
[Projects & memory](/docs/projects).

New to the plugin? See the [Claude Code plugin](/docs/claude-code) for installing it and
what each command does. Driving it from your own app or agent? The same flow runs through the
[CLI](/docs/cli) and [MCP tools](/docs/mcp-tools).
