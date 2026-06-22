---
title: "Positioning"
description: "Turn your demand report into your positioning — who it's for, why it's different, and roughly what to charge — built straight from the demand you found."
---

**Get your angle, built straight from the demand you found.**

Once you have a [demand report](/docs/demand-research), one call turns it into your
positioning: who it's for, why it's different, and roughly what to charge. It reads from the
report, so every line traces back to a real quote you can open.

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

## What you give it / what you get back

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

## When the result is thin

If every strong need in your report is already well-served by the market, there's no
real opening — and metalworks tells you so instead of manufacturing an angle. The
brief comes back with `pos.wedge = None`, `partial=True`, and a caveat suggesting you
either broaden the search or treat the market as commoditized. Same for price: if
your report didn't see enough price talk, `price_hypothesis` says so plainly rather
than guessing a number.

## Next

You have your angle. Now see who you're up against and decide what to build:
→ [Competitors](/docs/competitors) · [Build spec](/docs/build-spec) ·
[the full walkthrough](/docs/walkthrough) · [why you can trust the output](/docs/how-it-works)
