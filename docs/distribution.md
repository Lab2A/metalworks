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

## Channel-shaped assets

Once the strategy has selected your channels, one more call drafts the actual **copy** — one
`ChannelAsset` per channel, shaped to its surface. A launch asset isn't a flat string: a Product
Hunt post is a tagline + an authentic maker comment + gallery captions; a Show HN is a plain title
+ a technical first comment; an X launch is a numbered tweet thread; a LinkedIn post is a carousel.

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus tool for indie developers
/distribution-assets
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus tool for indie developers")

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
```

</CodeGroup>

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

## The data report — the on-brand flagship asset

One of those channels — `data_asset` — is something metalworks can uniquely generate: a
**corpus-derived data report**. It stacks every AI-citation driver at once — original research +
a ranking (the top AI-cited format) + verbatim quotes + permalinks — over a proprietary Reddit
corpus (the #1 AI-cited domain). The defensibility is the corpus others can't reproduce; the
credibility is the disclosed method.

One call projects a finished report's ranked clusters into a publishable `DataReportAsset`.

<CodeGroup>

```text Claude Code
/distribution-data-report
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus tool for indie developers")

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
```

</CodeGroup>

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

## Distribution → build requirements

Two distribution decisions are not marketing tactics bolted on after the fact — they are designed
INTO the product, so they have to be emitted as **build requirements** that feed
[the build spec](/docs/build-spec). Strategy runs *before* the build, so the build ships the loop
machinery and the conversion destination from day one rather than discovering they're missing
later. Notion's public-page SEO underperformed precisely because the build lacked SSR + a sitemap;
a watermark loop is worthless without a branded public viewer and badge-gating.

<CodeGroup>

```text Claude Code
/distribution-requirements
```

```python Python
strategy = mw.channel_strategy(research)
loops, conversion = mw.distribution_requirements(research)   # routes the strategy internally

for lr in loops:
    print(lr.loop_kind, "→", lr.build_requirements)          # e.g. watermark → public_share_urls, …
for cr in conversion:
    print(cr.destination, "—", cr.funnel_job)                # e.g. landing_page — convert the …

# feed them into the spec so it records what distribution decided
spec = mw.build_spec(research, distribution_requirements=(loops, conversion))
```

```bash CLI
metalworks distribution requirements <report-id>
```

</CodeGroup>

You get back two lists:

- **`loop_requirements`** — one `LoopRequirement` per selected `embedded_loop` channel. Its
  `loop_kind` (`watermark` / `ugc_seo` / `referral` / `free_tool` / `oss` / `single_player`) maps
  DETERMINISTICALLY to a fixed set of `build_requirements` (watermark ⇒ `public_share_urls` +
  `branded_viewer` + `badge_gating`; UGC-SEO ⇒ `ssr_public_pages` + `sitemap`; single-player ⇒
  `solo_aha_before_invite`), and its `rationale` traces to the channel's grounded `routing_signal`
  — never an invented feature. No embedded-loop channel selected → no loop requirements.
- **`conversion_surface_requirements`** — always one `ConversionSurfaceRequirement`. Channels
  create attention, and attention with no surface to catch it leaks out, so the build must include
  a **conversion destination**: its `destination`, its `funnel_job`, and the concrete
  `build_requirements` it must ship. This re-opens the marketing-site question from the right side
  — not cite-or-die marketing copy, but "the build must include a place to convert, here's its job
  per the funnel."

Pass the tuple to `build_spec(..., distribution_requirements=(loops, conversion))` and the
resulting `BuildSpec` records them on `loop_requirements` / `conversion_surface_requirements`. The
default (no tuple passed) leaves the spec unchanged.

## The distribution plan — pushes + streams

A distribution plan is not a flat list of channels with arbitrary `T+2h` spacing — that toy
even-spacing was an LLM-invented constant masquerading as a schedule. A plan is **pushes** (the
spike channels placed into concentrated launch moments) and **streams** (the compounding channels
run continuously). The split falls straight out of the channel's own `cadence` axis: `spike` →
push, `compounding` → stream — the same axis that made the old launch-vs-growth pillar split
unnecessary.

The timing of every push is **read from a deterministic playbook table**, sourced from the channel
playbooks in the research — so it is reproducible + citable, the opposite of an invented hour:

| Channel | Playbook timing |
| --- | --- |
| Product Hunt | Day 1, 12:01am PT (Tue/Wed) |
| Show HN / Launch HN | Day 3-4, Tue-Thu 8-10am PT |
| X / Twitter thread | Day 2, 9-11am PT (weekday) |
| LinkedIn post | Day 2, 8-10am local (Tue-Thu) |

The sequencer enforces the playbook's rules: at most **one all-day-attention channel per launch
day**, and **never Product Hunt and a big HN push on the same day** — if the report selected both,
they are staggered onto separate days. It frames the run as a campaign: a **pre-launch warming**
step before Day 1, the staggered **push week**, and a **30-day post step** after (where the early
channel tests resolve into a single channel to concentrate on — test→focus — and a winning push
becomes a repeatable one). Each spark-requiring channel carries its `spark_channel` (the
spark→flywheel edge: the push that ignites the amplifier).

<CodeGroup>

```text Claude Code
/distribution-plan
```

```python Python
dist = mw.distribution_plan(research)          # routes the strategy internally
for p in dist.pushes:
    print(p.timing, "—", p.channel_name, "→ sparks", p.spark_channel)
for s in dist.streams:
    print(s.channel_name, "—", s.cadence_note)
```

```bash CLI
metalworks distribution plan <report-id>
```

</CodeGroup>

It is **pure + deterministic** — no LLM, no network — over the already-selected channels. Every
push is `requires_human=True` and `posting_gated=True`: metalworks plans + drafts the sequence, a
human executes each moment. **DRAFTING + PLANNING ONLY — nothing here posts.**

## Closed-loop measurement — the loop that makes Distribution learn

Everything above PLANS; nothing learns. The loop closes here: **plan → (human executes) → record
results → re-rank the next push.** Distribution without "did it work + re-rank" is the theater the
research warned about — attribution murky, partnerships measured in logos. metalworks can't watch
live traffic, but in its lane it does the two things it *can* do deterministically: define the
metric + the instrumentation, and ingest the results to re-rank.

`mw.channel_metrics(research)` emits one `ChannelMetric` per selected channel — its `success_metric`
(what "worked" means) and its `instrumentation` (exactly how to track it), read from a fixed table
keyed by the channel's `surface_type` (never an invented KPI):

| Surface | Success metric | How to instrument |
| --- | --- | --- |
| launch platform | top-N + attributed signups in 7d | UTM-tag the launch link; count signups whose first touch carries it |
| marketplace | installs + WAU | the listing's install count + an in-product weekly-active event |
| community | qualified replies + click-through | count genuine "how do I try this" replies; UTM the link |
| answer-engine GEO | citation appearances | run the citability probes against the engines; count citations |
| embedded loop | signups per N shared outputs (K) | UTM + badge every shared output; divide signups by outputs |

This is the **falsifiable disposition** applied to distribution: name the metric and the instrument
*before* the push, so the outcome is measurable. After the push the human records a `ChannelResult`
(`channel_name`, `metric`, `value`, `period` like `"first 7d"`) for each channel.

Feeding those results back is what re-ranks the next push. `rerank_from_results(channels, results)`
is pure + deterministic: it sums each channel's recorded `value`s and re-orders the channels so the
ones that actually performed lead (and the dead ones fall) — measured channels first (by descending
score), unmeasured channels after, each group keeping its original order so the result is
reproducible. With no results it is a **no-op** (same channels, same order), so the default path is
unchanged. The re-rank is wired straight into selection + sequencing:
`select_channels(..., prior_results=...)` and `plan_distribution(..., prior_results=...)` apply it
when the prior push's results are passed.

<CodeGroup>

```text Claude Code
/distribution-measure
```

```python Python
metrics = mw.channel_metrics(research)         # routes the strategy internally
for m in metrics:
    print(m.channel_name, "→", m.success_metric)
    print("  instrument:", m.instrumentation)

# after the push, record what happened, then re-rank the next push:
from metalworks.contract import ChannelResult
from metalworks.research import build_channel_strategy, plan_distribution

results = [ChannelResult(channel_name="show_hn", metric="attributed signups in 7d",
                         value=42.0, period="first 7d")]
strategy = build_channel_strategy(mw.deps, report, prior_results=results)   # winners rise
plan = plan_distribution(report, strategy.channels, prior_results=results)
```

```bash CLI
metalworks distribution measure <report-id>
```

</CodeGroup>

The metric + instrumentation are deterministic; the human measures and records — metalworks never
watches traffic for you. **PLANNING ONLY — it defines what to measure; nothing here posts.**

## The participation/execution arm — the one channel metalworks can OPERATE

Everything above PLANS and DRAFTS. This is the one channel metalworks can actually **operate**, not
merely plan — and it is the moat the whole Distribution thesis rests on (*metalworks knows the real
threads*). The Reddit engagement capability (`metalworks.reddit`: OAuth, search, subreddit rules,
rate-limiting, inbox, the `heuristic_check` compliance gate, the voice stylebook) is **re-homed here
as Distribution's execution arm** for the community-native channel + the GEO participation stream.
The `reddit_*` tools keep working exactly as before — this re-homing adds a frame and a wiring, it
removes nothing.

The wiring: the GEO stream (above) produces **which** threads to engage — its
`participation_targets`, each a real `permalink` + a grounded `why` + a `suggested_angle`. The
execution arm engages one of them: `mw.distribution_engage(research, target)` drafts a **disclosed,
founder-voiced reply for that exact thread**, reusing the Reddit reply machinery and then running the
deterministic honesty gate (`heuristic_check`) over the result. The platform invariants — no "upvote"
ask, native-first, no AI tells — are the **single voice system** the channel-shaped launch assets
(above) also enforce: one stylebook (`metalworks.reddit.stylebook`), not two.

**Posting stays gated.** The returned `ParticipationReply` carries the draft, the compliance verdict,
and `requires_human` / `posting_gated` (both always true). metalworks drafts; a **human reviews and
posts** through the triple-gated path (`METALWORKS_ALLOW_POSTING=1` + a confirm-token over the exact
text + a re-run of the gate). DRAFTING ONLY — nothing here posts automatically.

<CodeGroup>

```text Claude Code
/distribution-engage
```

```python Python
geo = mw.geo(research)                       # D6 — which threads to engage
target = geo.participation_targets[0]        # a real thread, grounded `why`
reply = mw.distribution_engage(research, target)
print(reply.compliance.pass_, reply.community)
print(reply.draft)                           # disclosed, founder-voiced, gated
# a human posts it (gated) via `mw.reddit.post(...)` / the reddit_post_comment path
```

```bash CLI
metalworks distribution engage <report-id> \
  --permalink "https://reddit.com/r/SideProject/comments/.../x" \
  --why "what the audience is asking there" \
  --community r/SideProject --angle "answer first, then disclose"
```

</CodeGroup>

This is distinct from `/draft-reply` (the standalone `generate_reply` tool): that drafts a reply for
**any thread URL you paste**, report-free; the execution arm drafts for a **report-selected GEO
target**, grounded in the demand the report measured. They share the same honesty gate
(`heuristic_check`) and the same voice system by design — different entry points, one moat.
