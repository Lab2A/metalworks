---
title: "From idea to company"
description: "The full 7-pillar arc — research to launch — as one continuous flow on a single grounded evidence chain."
---

Most "idea to startup" tools generate breadth: a positioning line, a competitor
list, a landing page, a launch tweet — each a fresh hallucination, none answerable
to the others. metalworks runs the same breadth, but every claim-bearing output of
every pillar resolves to a real Reddit quote (or a cited web finding) by reference.
One report, one evidence chain, seven pillars hanging off it. The breadth isn't
slop because nothing in it is invented.

This page walks the whole arc as one cohesive sequence. Each pillar has its own
guide for depth; here it's the through-line.

## The arc

Everything starts with one `research()` call. It returns a `Research` bundle whose
`.demand` is a `DemandReport` — the go/no-go and the grounded evidence. The seven
pillars are functions *on that report*. They never re-research; they read the same
evidence and ground their own outputs against it.

```
                       mw.research(question, subreddits=[...])
                                      │
                                      ▼
                           ┌──────────────────────┐
                           │   Research (DemandReport)   │  ← the go/no-go + report.evidence
                           └──────────┬───────────┘
                                      │  every pillar below grounds against report.evidence
        ┌───────────┬───────────┬─────┴─────┬───────────┬───────────┐
        ▼           ▼           ▼           ▼           ▼           ▼
   Positioning  Landscape    Design       Site        Build       Launch ─▶ Growth
      (B)          (A)        (C)          (E)         (D)          (F)        (G)
   wedge+price  cited gaps  surface+UX  cited site  cite-or-die  drafts+   content/SEO
                                                     harness     channels   + Reddit loop
```

Pillars A–G are independent reads of the same report — run only the ones you need,
in any order. The only hard dependency is that a pillar consuming positioning
(Design's surface pick, the Site, the Build spec) wants the `PositioningBrief`
first.

## The end-to-end walk

One report, then the pillars. This is the whole company-in-a-file sequence.

```python
from metalworks import Metalworks

mw = Metalworks(model="...")            # or Metalworks.demo() — fully offline, zero keys

# Research — the only stage that touches Reddit + the web. Returns the go/no-go.
research = mw.research(
    "Is there demand for a focus supplement aimed at developers?",
    subreddits=["Nootropics", "Supplements"],
)
report = research.demand                # the DemandReport every pillar reads
print(report.verdict)                   # the synthesized go / no-go
```

If `report.verdict` is a no-go, stop — the downstream pillars are honest about it
(Launch refuses outright on a negative verdict). On a go, fan out. **Positioning
(B)** picks a wedge competitors miss and copies the price band through from the
report's evidence — it never invents a number:

```python
pos = mw.positioning(research)          # PositioningBrief — the Dunford wedge + price hypothesis
print(pos.positioning_statement)        # each free-text slot carries EvidenceRefs back to quotes
```

**Landscape (A)** maps the competitive set — direct, adjacent, and the mandatory
"do nothing" status quo — with one *evidenced* gap per rival:

```python
comp = mw.competitors(research)         # CompetitorMap — each GapClaim grounded to a real complaint
for c in comp.competitors:
    for g in c.gaps:                    # severity is set from distinct-author breadth, never the LLM
        print(c.name, "→", g.claim)
```

**Design (C)** decides the surface against a fixed five-dimension rubric, then
sketches a UX skeleton for it. `surf.chosen` is the picked `SurfaceKind`:

```python
surf = mw.surface(research, pos)        # SurfaceRecommendation — .chosen is a SurfaceKind, e.g. "web"
ux   = mw.ux(research, pos, surf.chosen) # UxSkeleton — screens with no backing voice ship validated=False
```

**Site (E)** writes a marketing site whose every claim-bearing section is a
*verbatim* fragment of a real quote (any section that isn't an exact substring is
dropped), and renders it to a self-contained `index.html`:

```python
site = mw.site(research, pos)           # MarketingSite — verbatim, cited copy only
html = mw.render_site(site, research)   # one self-contained index.html string, permalink footnotes baked in
```

**Build (D)** maps demand clusters to candidate features — each feature attached to
its source cluster's verbatim quotes and dropped if that cluster is invalid
(no-cite-no-feature) — then scaffolds a cite-or-die build harness:

```python
spec  = mw.build_spec(research, pos, surf.chosen)  # BuildSpec — every FeatureSpec grounded to quotes
paths = mw.scaffold(spec, research, "./build")     # writes CLAUDE.md, SPEC.md, a frozen EVIDENCE.md, the lint
```

**Launch (F)** drafts channel-native assets (Product Hunt / Show HN / X), each
claim grounded to a real quote with character-offset spans into the body, and a
human-run channel plan — it **never posts**:

```python
assets = mw.launch(research, pos)       # list[LaunchAsset] — drafting only, every claim cited
plan   = mw.channel_plan(research)      # ChannelPlan — every step requires_human + posting_gated
```

**Growth (G)** is the deterministic finish: a zero-key content/SEO plan, one page
per cluster, FAQs lifted verbatim from the brief's must-address questions, and a
citation strategy whose Reddit targets are real quote permalinks:

```python
content = mw.content_plan(research)     # ContentPlan — PURE deterministic, no LLM, no key
```

That's research → positioning → landscape → design → site → build → launch →
growth as one flow, off one report. Want to compose the raw functions instead of
the facade? `mw.deps` hands you the resolved `ResearchDeps` — the same chat /
embeddings / corpus the pillars thread through — so you can call
`build_positioning_brief`, `run_competitor_map`, and the rest directly.

## The evidence chain is the moat

Breadth is cheap. *Answerable* breadth is the thing. Every pillar above produces
claim-bearing fields, and not one of them is allowed to assert a claim it can't
trace. The mechanism is uniform: a downstream field carries `EvidenceRef`s, each
`EvidenceRef` resolves by id against `report.evidence` (a flat list of
`EvidenceRecord`s), and each record carries the real permalink. A field with zero
resolvable refs is dropped at assembly. This is `no-cite-no-claim` — the
generalization of the research pipeline's `no-quote-no-theme` rule, run through all
seven pillars.

Follow one claim the whole way down. A `LaunchAsset` makes a claim; a `BuildSpec`
attaches a feature; either one points at the same evidence:

```python
asset = assets[0]
claim = asset.claim_citations[0]        # a ClaimCitation on the launch draft

# 1. the downstream claim points upstream by id, not by free text
ref = claim.evidence_ref                # EvidenceRef(evidence_id="…", kind="quote")

# 2. resolve it against the report's flat evidence list
record = next(r for r in report.evidence if r.id == ref.evidence_id)  # an EvidenceRecord

# 3. the record carries the real Reddit permalink and the verbatim text
print(record.provenance)                # "verbatim" — an exact-matched corpus quote
print(record.url)                       # https://reddit.com/r/.../comment/...  ← a real human said this
print(record.text)                      # the exact comment the launch claim stands on
```

```
LaunchAsset.claim ─┐
BuildSpec.feature ─┤── EvidenceRef.evidence_id ──▶ report.evidence[id] ──▶ EvidenceRecord
SiteSection ───────┤                                                         ├─ provenance: verbatim
PositioningBrief ──┘                                                         ├─ url: real permalink
                                                                             └─ text: the exact quote
```

`provenance` is the honesty label: `verbatim` (an exact-matched corpus quote,
highest trust), `grounded-web` (a paraphrase over a real cited URL), `derived`
(computed or structural, no single source). A model phrases and clusters; it is
never the *source* of a fact. That's why you can ship the whole arc — a positioning
deck, a landing page, a launch thread — and defend every line of it back to a
permalink. The shovel, not the gold: metalworks doesn't decide your company is
good, it makes sure every claim it surfaces is one a real person actually made.

## Go deeper

Each pillar has its own guide. Start with research, then take any branch.

<CardGroup cols={2}>
  <Card title="Demand Research" href="/docs/guide-demand-research">
    The one stage that touches Reddit + the web — `mw.research(...)` → a `Research` bundle (report on `.demand`).
  </Card>
  <Card title="Positioning + Landscape" href="/docs/guide-positioning-landscape">
    Pillars B and A — the grounded Dunford wedge, the price band, the cited competitive gaps.
  </Card>
  <Card title="Design" href="/docs/guide-design">
    Pillar C — the five-dimension surface rubric and the grounded UX skeleton.
  </Card>
  <Card title="Build" href="/docs/guide-build">
    Pillar D — the `BuildSpec` and the cite-or-die scaffold for your own coding agent.
  </Card>
  <Card title="Launch + Growth" href="/docs/guide-launch-growth">
    Pillars F and G — channel-native cited drafts, the human-gated plan, the deterministic content/SEO loop.
  </Card>
  <Card title="Structural provenance" href="/docs/explanation-provenance">
    Why none of this can contain fabricated evidence — enforced by construction, not trust.
  </Card>
</CardGroup>

<Note>
**Build emits a spec and a scaffold for *your* coding agent — it is not a code
generator.** `mw.scaffold(...)` writes a `CLAUDE.md` (cite-or-die Rule 0), a
`SPEC.md`, a frozen `EVIDENCE.md` quote+permalink table, a build-pack of skills,
and a `cite_or_die.py` lint hook — but writes **no product code**. Your agent
builds the product against that harness, with every feature already tied to a real
quote. metalworks hands the agent the ground truth; it doesn't write the app.
</Note>
