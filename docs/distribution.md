---
title: "Distribution"
description: "Route your demand report's real communities and signals into channel experiments — test→focus, not a generic launch checklist."
---

**Where this product gets distributed, built from the demand you found.**

Once you have a [demand report](/docs/demand-research), one call turns it into a **channel
strategy**: it reads the real entities your audience named — the subreddits they live in, the
platforms in their workflow, the incumbent they resent — and routes them into the structured
channel space as a small set of **channel experiments**. Not "post to Product Hunt"; a set of
cheap tests, each grounded in something the report actually found.

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus tool for indie developers
/distribution-strategy
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus tool for indie developers")

strategy = mw.channel_strategy(research)        # optionally pass a positioning brief
print(strategy.product_type, "—", strategy.icp_summary)
for ch in strategy.channels:
    print(ch.name, ch.funnel_stage, "→", ch.routing_signal)
    print("  test:", ch.test)
    print("  pass when:", ch.success_threshold)
print(strategy.focusing_rule)
print(strategy.funnel_note)
```

```bash CLI
metalworks distribution strategy <report-id>
```

</CodeGroup>

## What you get back

A `ChannelStrategy` with:

- **`product_type` + `icp_summary`** — the classified ICP archetype (a dev tool routes
  differently than a consumer app) and a one-line ICP grounded in the report.
- **`channels`** — the selected channel **experiments**. Each `Channel` is placed in the
  structured space (`surface_type`, plus the `motion` / `cadence` / `discovery` / `role` /
  `funnel_stage` axes) and carries:
  - a **`routing_signal`** that traces to a real entity in the corpus — a community channel is
    selected because the audience *named that subreddit*, never from a hardcoded list;
  - a cheap **`test`** and a **`success_threshold`** — the test→focus discipline;
  - `requires_spark` + `spark_channel` on amplifiers — marketplaces and embedded loops don't
    start their own velocity, so they're paired with the launch push that ignites them;
  - an honest `worth_it_note` and `caveat` (e.g. "Product Hunt drives awareness, not
    conversions").
- **`focusing_rule`** — most products have ONE channel that drives nearly all growth. Test these
  cheaply, then concentrate on the single winner. This is a set of experiments, not a portfolio.
- **`funnel_note`** — coverage across the funnel. An all-top-of-funnel plan is flagged as a
  conversion **leak**: attention with nothing to catch it leaks out.

## The honesty contract

Channels are **derived from the report**, not invented. The communities and permalinks that
ground a community channel are pulled deterministically from your report's verified quotes — the
model only classifies the product type, writes the ICP line, and surfaces platforms/media the
audience explicitly named. Nothing it can't ground survives.

Treat the strategy as a set of **hypotheses to test**, sharp because they start from what real
people said — not a guaranteed playbook. metalworks plans and drafts distribution; a human runs it.

<<<<<<< HEAD
## The data report — the on-brand flagship asset

One of those channels — `data_asset` — is something metalworks can uniquely generate: a
**corpus-derived data report**. It stacks every AI-citation driver at once — original research +
a ranking (the top AI-cited format) + verbatim quotes + permalinks — over a proprietary Reddit
corpus (the #1 AI-cited domain). The defensibility is the corpus others can't reproduce; the
credibility is the disclosed method.

One call projects a finished report's ranked clusters into a publishable `DataReportAsset`.
=======
## Channel-shaped assets

Once the strategy has selected your channels, one more call drafts the actual **copy** — one
`ChannelAsset` per channel, shaped to its surface. A launch asset isn't a flat string: a Product
Hunt post is a tagline + an authentic maker comment + gallery captions; a Show HN is a plain title
+ a technical first comment; an X launch is a numbered tweet thread; a LinkedIn post is a carousel.
>>>>>>> origin/main

<CodeGroup>

```text Claude Code
<<<<<<< HEAD
/distribution-data-report
=======
/demand-report an affordable, jitter-free focus tool for indie developers
/distribution-assets
>>>>>>> origin/main
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus tool for indie developers")

<<<<<<< HEAD
report = mw.data_asset(research, kind="complaint_index")   # or "feature_ranking" | "state_of"
print(report.title)
for item in report.items:
    print(item.rank, item.label, f"({item.distinct_authors} authors, {item.mentions} mentions)")
    print("  ", item.quote)
    print("  ", item.permalinks)
print(report.methodology)
```

```bash CLI
metalworks distribution data-report <report-id> --kind complaint_index
=======
assets = mw.channel_assets(research)        # optionally pass a positioning brief
for a in assets:
    print(a.channel_name, a.surface_type, a.funnel_stage)
    for part in a.parts:
        print(" ", part.role, "—", part.text)
    print("  offer:", a.offer)
    print("  grounded demand claims:", len(a.claim_citations))
```

```bash CLI
metalworks distribution assets <report-id>
>>>>>>> origin/main
```

</CodeGroup>

<<<<<<< HEAD
### What you get back

A `DataReportAsset` with a `title`, a `kind` (`complaint_index` = pain points, `feature_ranking`
= requested features, `state_of` = the overall state), a `methodology` line, and the ranked
`items`. Each `DataReportItem` carries:

- **`rank`**, **`distinct_authors`**, and **`mentions`** — copied straight from the source
  cluster (`rank` / `distinct_author_count` / `mention_count`). Never re-scored, never invented.
- **`permalinks`** — the real `source_url`s of that cluster's verified quotes.
- **`quote`** — one verbatim supporting quote, exact text.
- **`label`** — the only authored prose in the row, an LLM-written headline grounded in the
  cluster's claim.

### Why the rigor is the point

The survey-fabrication base rate is the trap: a data report with invented numbers or a hidden
method reads like marketing and destroys its own credibility. So the ranking here is
**deterministic** — the items *are* the report's own clusters, with their own counts — and the
`methodology` discloses the honest base out loud: the thread count, the distinct-author counting
method, and the corpus date range. Every number is reproducible from the cited permalinks. The
LLM only writes the title and the per-row labels; it never touches a count, a link, or a quote.

Data reports take ~3 months to a first citation — methodology rigor is what earns it. metalworks
generates the asset; a human decides where to publish it.
=======
Each `ChannelAsset` carries:

- **`parts`** — the channel-shaped spans, each an `AssetPart` with a `role` (`tagline` |
  `maker_comment` | `gallery_caption` | `title` | `first_comment` | `tweet` | `carousel_slide` | …)
  and its `text`. `body` is the concatenated copy for back-compat.
- **`offer`** — the per-channel CTA / conversion ask.
- **`claim_citations`** — the grounded **demand** claims.

### Relaxed grounding (and why)

Grounding here is **relaxed** versus the rest of metalworks — on purpose. Only **demand / factual**
claims (people want this, they resent the incumbent, a number, a sentiment) are held to
no-cite-no-claim: each resolves to a real Reddit quote or it is **dropped**. The persuasive
**hooks, taglines and the offer/CTA are free** — they're craft, not factual claims. Forcing a quote
behind every persuasive sentence was a category error; channel-shaped assets don't repeat it.

### Platform invariants (enforced, not optional)

- **Never an "upvote us" ask** — it's platform-fatal on Product Hunt and Hacker News and reads as
  begging. A deterministic guard strips any upvote ask from every span.
- **Native-first** — the link goes in a reply / the comments, never the opening hook.
- **Founder-voiced** — first person, not brand-speak; no AI tells.

**DRAFTING ONLY** — channel assets are never posted. A human reviews and posts every one.
>>>>>>> origin/main
