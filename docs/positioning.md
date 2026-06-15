---
title: "Positioning & competitors"
description: "Turn your demand report into your positioning — who it's for, why it's different, and what to charge — plus the competitors you have to beat, each with a real, cited gap you can exploit."
---

**Get your angle and your competitive map, both built straight from the demand you found.**

Once you have a [demand report](/docs/demand-research), two calls turn it into the
things you need before you build: **positioning** (who it's for, why it's different,
roughly what to charge) and a **competitor map** (the rivals to beat, each with a
real gap you can exploit). Both read from the same report, so every line traces
back to a real quote you can open.

## Positioning — your angle

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus supplement for developers
/position-wedge
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus supplement for developers")

pos = mw.positioning(research)
print(pos.positioning_statement)        # who it's for, and why it's different
if pos.wedge:
    print(pos.wedge.unique_attribute, "→", pos.wedge.value)
if pos.price_hypothesis:
    print(pos.price_hypothesis.framing)
```

```bash CLI
metalworks research position <report-id>
```

</CodeGroup>

You get back a positioning statement built around one **unmet need your competitors
miss** — metalworks finds the strongest need in your report that the wider market
isn't already serving, and frames your product around exactly that. (The frame
follows April Dunford's positioning method.) The result reads like:

```
For developers who currently rely on caffeine-heavy pre-workouts, this is the
focus supplement that won't spike-and-crash them by mid-afternoon — so they stay
sharp through a full workday.
```

### What you give it / what you get back

You give it the `research` bundle. You get back a `PositioningBrief`:

| Field | What it is |
| --- | --- |
| `pos.positioning_statement` | The full one-sentence positioning: who it's for and why it's different. |
| `pos.wedge` | The pieces of that angle — `unique_attribute` (what you do differently), `value` (why it matters), `beachhead` (the narrow first audience to win), `competitive_alternative` (what they use today). |
| `pos.price_hypothesis` | A read on what to charge, carried over from the price talk in your report. |

metalworks picks the need to build around from your data, not from thin air — it's
the strongest pain in your report that the market isn't already answering. The model
only phrases the sentence; it can't choose a different need or invent one. Each
phrase is then checked against the real quotes behind it, and anything it can't back
gets flagged.

### When the result is thin

If every strong need in your report is already well-served by the market, there's no
real opening — and metalworks tells you so instead of manufacturing an angle. The
brief comes back with `pos.wedge = None`, `partial=True`, and a caveat suggesting you
either broaden the search or treat the market as commoditized. Same for price: if
your report didn't see enough price talk, `price_hypothesis` says so plainly rather
than guessing a number.

## Competitors — the rivals to beat

<CodeGroup>

```text Claude Code
# uses the report you already made
/competitor-map
```

```python Python
comp = mw.competitors(research)

for rival in comp.competitors:
    print(rival.kind, rival.name)       # direct, adjacent, or "do nothing"
    for gap in rival.gaps:              # each gap is backed by a real complaint
        print("   misses:", gap.claim, f"[{gap.severity}]")
```

```bash CLI
metalworks research competitor-map <report-id>
```

</CodeGroup>

You get back a `CompetitorMap`: the real products people use today, each with what it
does well and a **gap you can exploit** — and that gap is always backed by an actual
complaint someone posted. It also always includes the "do nothing" option, because
the cost of people sticking with their current habit is the real thing any new product
has to beat.

### What you give it / what you get back

| Field | What it is |
| --- | --- |
| `comp.competitors[].name` / `.kind` | The rival and its type: `direct`, `adjacent`, or `status_quo` (do nothing). |
| `comp.competitors[].strengths` | What that competitor does well. |
| `comp.competitors[].gaps[].claim` | A gap you can exploit — phrased as what the rival misses. |
| `comp.competitors[].gaps[].severity` | How big the gap is, set from how many people complained about it (not a model's opinion). |

metalworks only lists rivals it can actually find evidence for — if a name can't be
grounded in a real source, it's dropped, so you won't get hallucinated competitors.
And it only keeps a gap when a real complaint backs it up: every gap links to one
verbatim quote or a grounded web source. A gap nobody actually voiced gets dropped.

### When the result is thin

If metalworks can't confidently ground the list of named competitors, it still ships
the "do nothing" alternative (always grounded in your report's strongest pains) and
flags the rest with `partial=True` and a caveat telling you the named set is unverified.
You're never handed a confident-looking map built on invented rivals.

## Next

You know your angle and your competitors. Now decide what to build and write the site:
→ [Design & marketing site](/docs/design) · [the full walkthrough](/docs/walkthrough) ·
[why you can trust the output](/docs/how-it-works)
