---
title: "Positioning & landscape guide"
description: "From a grounded demand report to a defensible Dunford wedge and the real competitive set — Pillar B and Pillar A, end to end."
---

Once the [demand research](/docs/guide-demand-research) vertical has run, you hold
a `DemandReport` whose every quote is exact-matched to a real comment. Two pillars
build directly on that evidence spine: **Positioning** (Pillar B) turns the demand
into a defensible wedge, and **Landscape** (Pillar A) maps the real competitive
set. Both follow the same discipline as the report itself — a model phrases, but
never sources, a fact. See [the arc](/docs/the-arc) for how every pillar chains
off the report, and [structural provenance](/docs/explanation-provenance) for why
that chain can't fabricate evidence.

## Positioning — a grounded Dunford wedge

`mw.positioning(research)` derives a `PositioningBrief`: an April-Dunford wedge
(competitive alternative → unique attribute → value → beachhead → market category)
plus a price hypothesis. The defensible move is that wedge **selection is
deterministic, not LLM creativity**.

```python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("Is there demand for a focus supplement aimed at developers?")

pos = mw.positioning(research)          # -> PositioningBrief
print(pos.positioning_statement)
if pos.wedge:
    print(pos.wedge.unique_attribute, "→", pos.wedge.value)
if pos.price_hypothesis:
    print(pos.price_hypothesis.framing)
```

From the CLI:

```bash
metalworks research position <report-id>
```

### How the wedge is selected

A wedge can only stand on an `InsightCluster` that the web research stream is
`silent_web` or `disagree` on — a real pain competitors miss — at **≥ MEDIUM**
signal, ranked by `demand_score`. The pipeline picks that cluster
deterministically. Then exactly **one** LLM call phrases the three free-text slots
(`unique_attribute`, `value`, `market_category`), constrained to fill this exact
sentence:

> For *\<beachhead\>* who currently rely on *\<competitive_alternative\>*, this is
> the *\<market_category\>* that *\<unique_attribute\>* — so they *\<value\>*.

A second cheap pass verifies each authored clause is **entailed** by the cited
quotes — the no-cite-no-claim rule generalized to free text. If a clause isn't
supported, the brief ships `partial=True` and the `caveat` names the unverified
slot. The `beachhead` is deterministic (the top segment, or the audience profile);
the `competitive_alternative` is drawn from the cluster's real web findings.

### The honest null

When no cluster qualifies — every strong demand cluster is echoed by the web, so
there's no white space — there is no wedge to invent. The brief comes back with
`wedge=None`, `partial=True`, and a caveat telling you to re-run with broader web
research or treat the market as commoditized. metalworks will not manufacture an
angle that the evidence doesn't support.

### The price hypothesis

`pos.price_hypothesis` is **copied through** from the report's `PriceFinding` —
never recomputed here. When the report didn't see enough price talk,
`insufficient_signal=True` and there's no band, only an honest framing line. Price
is a finding upstream; positioning just carries it forward.

### What the brief contains

| Field | Grounding rule |
| --- | --- |
| `wedge.competitive_alternative` | Drawn from the cluster's real `WebFinding`s. |
| `wedge.unique_attribute` / `value` / `market_category` | LLM-phrased, entailment-verified against cited quotes; failure → `partial`. |
| `wedge.beachhead` | Deterministic from `segments` / `audience_profile`. |
| `wedge.source_cluster_rank` | The 1-based `silent_web`/`disagree` cluster the wedge stands on. |
| `wedge.evidence` | Refs (cluster quotes + web findings) resolvable against the report. |
| `price_hypothesis` | Copied from the report's `PriceFinding`; `insufficient_signal` mirrors the source. |
| `partial` / `caveat` | Set on an absent wedge or an unverified clause. |

The brief is a **hypothesis**, not a finding — but every slot it carries traces
back to upstream evidence by id, the same `EvidenceRef` spine the report uses.

## Landscape — the real competitive set

`mw.competitors(research)` builds a `CompetitorMap`: direct competitors, adjacent
alternatives, and the mandatory April-Dunford **status-quo "do nothing"**
alternative — each with what it does well and an exploitable, evidenced gap.

```python
comp = mw.competitors(research)         # -> CompetitorMap

for c in comp.competitors:
    print(c.kind, c.name)
    for g in c.gaps:                    # each gap carries one cited complaint
        print("   gap:", g.claim, f"[{g.severity}]")
```

From the CLI:

```bash
metalworks research competitor-map <report-id>
```

### How it's built — and why a gap can't be invented

The map assembles in four deterministic stages:

1. **Enumerate.** One *grounded* chat call lists the real products people use
   today. Any name with zero grounding chunks is dropped — no hallucinated rivals.
   If the model can't ground at all, the map degrades to a plain call and ships
   `partial=True` with a caveat that the named set is unverified.
2. **Harvest.** One structured call per competitor produces strengths and gap
   *claims* (text only). The LLM never assigns severity and never invents
   citations.
3. **Complaint match.** Each gap claim is embedded and cosine-matched against the
   report's **real** evidence — cluster quotes first, then web findings. A match
   attaches the resolvable `EvidenceRef`; severity is **service-assigned** from
   the matched complaint's distinct-author breadth (or web confidence).
4. **Assemble.** Any gap with no matched evidence is **dropped** — this is
   **no-quote-no-gap**. A competitor keeps only the gaps a real complaint backs.

### The status quo is always present

The cost of doing nothing is the default any new product must beat, so the
status-quo "do nothing" alternative is mandatory and grounded verbatim from the
report's strongest pains. It ships even when the named-competitor enumeration
degrades.

### What the map contains

| Field | Grounding rule |
| --- | --- |
| `competitors[].name` / `kind` | Grounded enumeration; ungrounded names dropped (or whole set flagged `partial`). |
| `competitors[].strengths` | LLM-phrased claims; evidence optional (often web-sourced). |
| `competitors[].gaps[].claim` | Kept only when a real complaint cosine-matches it (no-quote-no-gap). |
| `competitors[].gaps[].severity` | Service-assigned from complaint breadth / web confidence — never LLM. |
| `competitors[].gaps[].evidence` | Exactly one resolvable `EvidenceRef` (verbatim quote or grounded web). |
| `partial` / `caveat` | Set when enumeration ran ungrounded or a stage degraded. |

Named-competitor gaps are honestly asymmetric: cluster-matched gaps inherit
verbatim quotes (high trust), while web-matched gaps are `grounded-web` (medium).
The provenance label lives on the resolved evidence, not on a model's say-so.

## How both tie to the evidence chain

Positioning and landscape both FK to exactly one report and resolve every
`EvidenceRef` against **that** report's `evidence` list. Nothing here adds a new
source of truth — the wedge stands on a white-space cluster, each gap stands on a
matched complaint, and the price band is the report's own. That's the whole point:
every downstream claim is traceable to a real, stored Reddit comment. Read
[structural provenance](/docs/explanation-provenance) for the architecture that
enforces it, and [the arc](/docs/the-arc) for the full pillar chain.
