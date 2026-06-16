---
title: "Competitors"
description: "Map the competitors you have to beat from your demand report — each with what it does well and a real, cited gap you can exploit."
---

**Map the rivals to beat — each gap backed by a real complaint.**

With a [demand report](/docs/demand-research) in hand, one call maps the products people use
today: what each does well, and the gap you can exploit. Every gap is backed by an actual
complaint someone posted, so the whole map traces back to real quotes you can open.

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus supplement for developers
/competitor-map
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus supplement for developers")

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

## What you give it / what you get back

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

## When the result is thin

If metalworks can't confidently ground the list of named competitors, it still ships
the "do nothing" alternative (always grounded in your report's strongest pains) and
flags the rest with `partial=True` and a caveat telling you the named set is unverified.
You're never handed a confident-looking map built on invented rivals.

## The fuller picture: landscape

The competitor map is the lean "who are the rivals." For the full **"what exists today"** —
the competitor map **plus** an empirical scan of real shipped products (Product Hunt launches and
web), each matched to a demand cluster with its traction — use `landscape()` instead. That's the
supply side the [validation loop](/docs/validation-loop) weighs against demand to reach a
GO / PIVOT / NO-GO call.

## Next

You know the landscape. Decide whether it's worth building with the
[validation loop](/docs/validation-loop), or move to what to build:
→ [Validation loop](/docs/validation-loop) · [Surface & screens](/docs/design) ·
[Marketing site](/docs/marketing-site) · [why you can trust the output](/docs/how-it-works)
