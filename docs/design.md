---
title: "Surface & screens"
description: "Decide what to build — web, mobile, CLI? — and the screens you need, with every recommendation traced to a real customer voice rather than taste."
---

**Decide what to build, straight from real demand.**

With a [demand report](/docs/demand-research) and your [positioning](/docs/positioning) in
hand, one step decides what kind of product to build — a web app, mobile app, CLI, API… — and
sketches the screens you need. Every call traces back to the real quotes in your report, so
nothing is made up.

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus supplement for developers
/surface-and-ux
```

```python Python
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

```bash CLI
metalworks research surface <report-id>
```

</CodeGroup>

`mw.surface(...)` picks the right kind of product to build — `web`, `mobile`, `cli`,
`browser_extension`, and so on — with a runner-up and the trade-offs. It judges the
call on five fixed questions: where your users already are, how technical they are,
how often they'd use it, whether it needs realtime or hardware, and how you'd
distribute it. `mw.ux(...)` then sketches the 3-5 screens you need, each with a one-line
purpose and a single primary action.

## What you give it / what you get back

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

## When the result is thin

This is the step with the least to stand on, so metalworks is deliberately strict:
when the signal is thin, it under-claims — marking more findings as honest assumptions
and dropping the whole recommendation to `partial=True` — rather than pinning a
confident "the users are here" on a loosely related comment.

## Next

You know what to build. Now write the site, then turn it into a build plan:
→ [Marketing site](/docs/marketing-site) · [Build spec](/docs/build-spec) ·
[the full walkthrough](/docs/walkthrough) · [why you can trust the output](/docs/how-it-works)
