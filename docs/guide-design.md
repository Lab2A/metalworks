---
title: "Design guide"
description: "From grounded demand to a product shape and a marketing site whose every claim is a real Reddit quote — Pillar C and Pillar E."
---

The design pillars answer the next question after *is there demand?* — namely,
*what do we build, and how do we sell it?* **Surface + UX** (Pillar C) recommends
the product shape and sketches its screens; the **marketing site** (Pillar E)
drafts a page whose every claim-bearing line is a verbatim Reddit quote. Both
build on the [demand report](/docs/guide-demand-research) and the
[positioning](/docs/guide-positioning-landscape) wedge, and both keep the same
provenance discipline: see [structural provenance](/docs/explanation-provenance)
and [the arc](/docs/the-arc).

## Surface & UX — the product shape

`mw.surface(research, pos)` recommends the surface to build against a **fixed
five-dimension rubric**; `mw.ux(...)` sketches a screen skeleton for it.

```python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("Is there demand for a focus supplement aimed at developers?")
pos = mw.positioning(research)

surf = mw.surface(research, pos)        # -> SurfaceRecommendation
print(surf.chosen, "(runner-up:", surf.runner_up, ")")
for dim in surf.rubric:
    tag = "assumption" if dim.is_assumption else "grounded"
    print(f"  {dim.name}: {dim.finding} [{tag}]")

ux = mw.ux(research, pos, surf.chosen)  # -> UxSkeleton
for s in ux.screens:
    flag = "validated" if s.validated else "HYPOTHESIS"
    print(f"  {s.name}: {s.purpose} [{flag}]", "★" if s.serves_wedge else "")
```

From the CLI:

```bash
metalworks research surface <report-id>
```

### The fixed rubric, grounded per dimension

The surface is judged on five **service-defined** dimensions — the model never
invents them:

- `where_are_the_users`
- `technical_sophistication`
- `usage_frequency`
- `realtime_or_hardware`
- `distribution`

One LLM call phrases each dimension's finding plus the chosen surface, a
runner-up, and the trade-offs. The service then **grounds each dimension** by
cosine-matching its finding to the report's real evidence (cluster quotes / web
findings). A dimension that matches nothing is marked `is_assumption=True` — an
explicit, stated guess. `confidence` is service-assigned from how many dimensions
are actually grounded, and thin grounding drops the whole recommendation to
`partial=True`: a labelled hypothesis, not a finding.

This is the **highest grounding-risk pillar**, so the matching threshold is
deliberately strict — metalworks under-claims (more honest assumptions) rather
than over-attributing a "no signal" finding to a loosely related quote.

### The UX skeleton — unbacked screens ship `validated=False`

`mw.ux(...)` sketches a 3–5 screen skeleton (name, one-line purpose, single
primary action) for the chosen surface. Each screen's purpose is grounded the same
way. A screen with backing voice carries its `evidence_refs` and ships
`validated=True`; a screen with **no** backing voice ships `validated=False` — an
explicit hypothesis to test, never a silently asserted requirement. `serves_wedge`
flags the screens that directly deliver the positioning wedge.

Aesthetics, deliberately, do **not** ground: visual craft is convention, not
evidence, so this module ships text and structure only — no pixels.

### What surface & UX contain

| Field | Grounding rule |
| --- | --- |
| `surf.chosen` / `runner_up` / `rationale` | LLM-phrased pick; the decision is driven by the grounded rubric. |
| `surf.rubric[].finding` | LLM-phrased per fixed dimension. |
| `surf.rubric[].is_assumption` | `True` when no evidence cosine-matches the finding. |
| `surf.confidence` | Service-assigned from grounded-dimension count — never LLM-claimed. |
| `surf.trade_offs[]` | Cited where evidence supports them. |
| `ux.screens[].validated` | `True` iff at least one real voice backs the screen; else a flagged hypothesis. |
| `ux.screens[].serves_wedge` | `True` when the screen directly delivers the wedge. |
| `partial` / `caveat` | Set on thin grounding or any unvalidated screen. |

## Marketing site — every claim is a real quote

`mw.site(research, pos)` drafts a small `MarketingSite`; `mw.render_site(...)`
turns it into a single self-contained `index.html`.

```python
site = mw.site(research, pos)           # -> MarketingSite
for sec in site.sections:
    print(sec.role, f"[{sec.provenance}]", "→", sec.copy[:60])

html = mw.render_site(site, research)   # -> index.html string
open("index.html", "w").write(html)
```

From the CLI:

```bash
metalworks research site <report-id>
```

### How copy is grounded — no-quote-no-section

The builder takes the top 3 clusters by `demand_score` and makes exactly **one**
constrained LLM call that, per cluster, (a) assigns a section role and (b) picks a
**verbatim fragment** to quote from that cluster's quotes. The builder then
**re-runs exact-match grounding**: the picked fragment must be a real substring
(and at least four words) of a stored `QuoteCitation.text` in that cluster.

- Match → the section ships `provenance="verbatim"` with a single `EvidenceRef` to
  that quote.
- No match → the section is **dropped**. This is **no-quote-no-section** — the
  same spine the demand report and positioning brief use. A claim is never shipped
  on a model's word.

The **hero** is built on the cluster with the highest `distinct_author_count` —
the broadest base rate, not the loudest single post.

### Connective copy ships claim-free

The LLM may add **connective** copy (transitions between verbatim sections). These
ship `provenance="connective"` with **no refs**, and are forced claim-free: any
line carrying a number or a superlative (`best`, `most`, `only`, `proven`, …) is
dropped. Glue must not smuggle in an unsourced claim.

If no fragment matches a verified quote, the site comes back empty with
`partial=True` and a caveat — never an invented section, never a crash.

### The rendered `index.html`

`mw.render_site(site, research)` renders each verbatim section's copy followed by a
footnote linking the quote's **permalink** (resolved through the report's
`evidence`), so every claim on the page is one click from the real Reddit comment.
Connective sections render with no footnote. URL schemes are allowlisted to
http(s) / local anchors, so a crafted source URL can't ship a clickable script.

### What the site contains

| Field | Grounding rule |
| --- | --- |
| `sections[].role` | `hero`/`feature`/`objection`/`pricing`/`social_proof`/`cta`. |
| `sections[].copy` (verbatim) | Contains a fragment exact-matching a real quote; else dropped. |
| `sections[].evidence_refs` | One quote `EvidenceRef` for verbatim sections; empty for connective. |
| `sections[].provenance` | `verbatim` (cited) or `connective` (claim-free glue). |
| `partial` / `caveat` | Set when synthesis is unavailable or nothing grounds. |

## How both tie to the evidence chain

Surface, UX, and the site all FK to one report and resolve every `EvidenceRef`
against **that** report's `evidence`. The rubric grounds against real quotes, each
screen is either backed or honestly flagged, and every claim-bearing line on the
marketing page is a verbatim comment one footnote away from its permalink. Nothing
here is a new source of truth — it's the same evidence, carried one step closer to
something you can build and ship. See [structural provenance](/docs/explanation-provenance)
for the enforcement and [the arc](/docs/the-arc) for the full pillar chain.
