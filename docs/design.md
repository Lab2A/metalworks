---
title: "Design & marketing site"
description: "Decide what to build — web, mobile, CLI? — and the screens you need, then get a marketing page whose every claim is a real, verbatim Reddit quote linked back to the thread it came from."
---

**Decide what to build and write the site — both straight from real demand.**

With a [demand report](/docs/demand-research) and your [positioning](/docs/positioning)
in hand, two more calls cover design: **surface + screens** (your *surface* is what you
build — a web app, mobile app, CLI, API… — and the screens it needs) and a **marketing
site** (a page whose every claim is a verbatim quote from a real user). Both read from
the same report, so nothing is made up.

## Surface & screens — what to build

```python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus supplement for developers")
positioning = mw.positioning(research)

surface = mw.surface(research, positioning)       # web? mobile? CLI? — and why
print(surface.chosen, "(runner-up:", surface.runner_up, ")")
for dim in surface.rubric:
    tag = "assumption" if dim.is_assumption else "backed by quotes"
    print(f"  {dim.name}: {dim.finding} [{tag}]")

ux = mw.ux(research, positioning, surface.chosen)  # the 3-5 screens you need
for s in ux.screens:
    flag = "validated" if s.validated else "HYPOTHESIS"
    star = "★" if s.serves_wedge else ""
    print(f"  {s.name}: {s.purpose} [{flag}] {star}")
```

From the command line:

```bash
metalworks research surface <report-id>
```

`mw.surface(...)` picks the right kind of product to build — `web`, `mobile`, `cli`,
`browser_extension`, and so on — with a runner-up and the trade-offs. It judges the
call on five fixed questions: where your users already are, how technical they are,
how often they'd use it, whether it needs realtime or hardware, and how you'd
distribute it. `mw.ux(...)` then sketches the 3-5 screens you need, each with a one-line
purpose and a single primary action.

### What you give it / what you get back

| Field | What it is |
| --- | --- |
| `surface.chosen` / `runner_up` | The recommended product type and the second choice. |
| `surface.rubric[].finding` | What the evidence says on each of the five questions. |
| `surface.rubric[].is_assumption` | `True` when no real quote backs that finding — a stated guess, labeled. |
| `surface.confidence` | How sure metalworks is, set from how many questions it could actually back with quotes. |
| `ux.screens[].validated` | `True` when at least one real voice asked for that screen; `False` means it's a hypothesis to test. |
| `ux.screens[].serves_wedge` | `True` when the screen directly delivers your *wedge* — your unique angle (the positioning you landed on). |

Each finding is checked against the real quotes in your report. Anything a quote
backs is labeled as such; anything it can't back is flagged as an assumption rather
than dressed up as a fact. Screens nobody asked for ship as honest hypotheses, never
silent requirements. This module deliberately stops at text and structure — it
recommends what to build and the screens, not the visual design.

### When the result is thin

This is the step with the least to stand on, so metalworks is deliberately strict:
when the signal is thin, it under-claims — marking more findings as honest assumptions
and dropping the whole recommendation to `partial=True` — rather than pinning a
confident "the users are here" on a loosely related comment.

## Marketing site — every claim is a real quote

```python
site = mw.site(research, positioning)             # marketing copy, every line a real quote
for sec in site.sections:
    print(sec.role, f"[{sec.provenance}]", "→", sec.copy[:60])

html = mw.render_site(site, research)             # a self-contained index.html
open("index.html", "w").write(html)
```

From the command line:

```bash
metalworks research site <report-id>
```

`mw.site(...)` drafts a small marketing page; `mw.render_site(...)` turns it into one
self-contained `index.html` you can open. The copy isn't AI prose — **every
claim-bearing line is a word-for-word quote from a real user**, and each one renders
with a footnote linking back to the Reddit thread it came from, so any visitor is one
click from the real comment.

### What you give it / what you get back

| Field | What it is |
| --- | --- |
| `site.sections[].role` | What the section does: `hero`, `feature`, `objection`, `pricing`, `social_proof`, or `cta`. |
| `site.sections[].copy` | The text. For a claimed section it contains a verbatim fragment of a real quote. |
| `site.sections[].provenance` | `verbatim` (a cited real quote) or `connective` (claim-free glue between sections). |

The hero is built on the need the most distinct people raised — the broadest demand,
not the loudest single post. metalworks may add short connective lines to bridge
sections, but those carry no claims at all: any glue line that sneaks in a number or a
superlative like "best" or "only" is dropped, so unsourced claims can't slip in.

### When the result is thin

metalworks drops anything it can't back with a real quote. If a line doesn't exactly
match a stored comment, that section is removed rather than shipped on the model's
word. If nothing matches at all, the site comes back empty with `partial=True` and a
caveat — never an invented section, never a crash.

## Next

You know what to build and you have a site. Now turn it into a build plan and launch:
→ [Build spec](/docs/build-spec) · [Launch assets](/docs/launch) ·
[the full walkthrough](/docs/walkthrough) · [why you can trust the output](/docs/how-it-works)
