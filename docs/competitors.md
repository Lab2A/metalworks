---
title: "Competitors"
description: "Map everything that exists today from your demand report — direct/adjacent/status-quo rivals (each gap cited) plus real shipped products, each tagged with the demand clusters it competes for."
---

**Map what exists today — rivals + real products, each gap backed by a real complaint.**

With a [demand report](/docs/demand-research) in hand, one call maps the full supply side: the
products people use today, what each does well, the gap you can exploit, and — for the shipped
ones — their traction. Every gap traces back to an actual complaint someone posted, and every
competitor is **tagged with the demand clusters it competes for**, so you can see which of your
[wedges/segments](/docs/data-model) a rival actually threatens.

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus supplement for developers
/market-landscape
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus supplement for developers")

land = mw.landscape(research)
for rival in land.competitor_map.competitors:
    print(rival.kind, rival.name, "→ clusters", rival.addresses_clusters)
    for gap in rival.gaps:              # each gap is backed by a real complaint
        print("   misses:", gap.claim, f"[{gap.severity}]")
for product in land.existing_solutions:  # real shipped products, with traction
    print(product.name, product.traction, "→ clusters", product.addresses_clusters)
```

```bash CLI
metalworks research landscape <report-id>
```

</CodeGroup>

You get back a `Landscape`: the nested `competitor_map` (the real products people use today — each
with what it does well, a **gap you can exploit**, and the **clusters it addresses**) plus
`existing_solutions` (real shipped products from Product Hunt / the web, with traction, matched to
your demand clusters). It always includes the "do nothing" status-quo option, because the cost of
people sticking with their current habit is the real thing any new product has to beat.

> Competitor names come from **two grounded sources**: a live web search AND the corpus itself
> (tools people literally name in their complaints). A name you can't ground in either is dropped —
> no hallucinated rivals.

## What you get back

| Field | What it is |
| --- | --- |
| `land.competitor_map.competitors[].name` / `.kind` | The rival and its type: `direct`, `adjacent`, or `status_quo` (do nothing). |
| `…competitors[].addresses_clusters` | The demand-cluster ranks this rival competes for — which wedge/segment it threatens. |
| `…competitors[].strengths` | What that competitor does well. |
| `…competitors[].gaps[].claim` / `.severity` | A gap to exploit (what it misses); severity set from how many people complained, not a model's opinion. |
| `land.existing_solutions[]` | Real shipped products: `name`, `url`, `tagline`, `traction`, `addresses_clusters`. |

metalworks only lists rivals it can ground — a name with no web result and no corpus mention is
dropped — and only keeps a gap when a real complaint backs it: every gap links to one verbatim quote
or a grounded web source. A gap nobody voiced gets dropped.

## Per-fork saturation (advisory)

Because every competitor and product is cluster-tagged, [`assess`](/docs/validation-loop) can show
**how crowded each fork is on its own**: your indie-DX wedge might face Supabase/Neon while your
enterprise wedge faces RDS/Aurora. Each `ForkVerdict` carries its own `landscape_saturation`, so a
GO/NO-GO per fork shows whether *that* slice is open or crowded. (This per-fork saturation is
**advisory** today — the GO/NO-GO gate itself still uses the space-level number; the gate goes
per-fork in a follow-up once the attribution is proven stable.)

## When the result is thin

If metalworks can't confidently ground the named competitors, it still ships the "do nothing"
alternative (always grounded in your report's strongest pains) and the existing-solutions scan,
flagging the rest with `partial=True` and a caveat that the named set is unverified. You're never
handed a confident-looking map built on invented rivals. The existing-solutions scan needs a Product
Hunt token; without one, that half is empty and the competitor map still holds.

## Next

You know the landscape. Decide whether it's worth building with the
[validation loop](/docs/validation-loop), or move to what to build:
→ [Validation loop](/docs/validation-loop) · [Build spec](/docs/build-spec) ·
[why you can trust the output](/docs/how-it-works)
