---
title: "Launch assets"
description: "Draft channel-native launch copy — Product Hunt, Show HN, an X thread — every claim backed by a real quote. Plus a human-run channel plan. metalworks drafts; you post."
---

Turn your demand report into launch copy you can post. `launch` drafts one asset per channel —
Product Hunt, Show HN, an X thread — each in that channel's voice, with every claim backed by a
real quote. `channel_plan` gives you a step-by-step checklist to run by hand.

**Drafting only. metalworks never posts.** `launch(...)` returns drafts; `channel_plan(...)`
returns a checklist you execute yourself. Nothing here touches a network.

```python
from metalworks import Metalworks
mw = Metalworks()
research = mw.research("an affordable, jitter-free focus supplement for developers")
positioning = mw.positioning(research)

assets = mw.launch(research, positioning)   # list[LaunchAsset] — [] on a no-go report
for asset in assets:
    print(asset.surface, "—", asset.title)
    print(asset.body)
    for v in asset.variants:                # alternate hooks you can pick from
        print("  variant:", v)

plan = mw.channel_plan(research)            # a checklist you run by hand
for step in plan.steps:
    print(step.scheduled_offset, step.surface, "—", step.action)
```

From the CLI (`report-id` comes from `metalworks research list`):

```bash
metalworks research launch <report-id>
```

## What you give it / what you get back

**You give it:** a finished `Research` bundle (the report lives on `.demand`). Positioning is
optional — pass it to keep the copy consistent with your
[positioning statement](/docs/positioning).

**You get back:** a `list[LaunchAsset]`, one per channel. Each asset carries a `title` (the hook),
a channel-native `body`, alternate `variants`, and `claim_citations` — the claims it could back.

Launch copy is the easiest place to over-claim, so every factual, quantified, or attitudinal
claim is backed by a real quote. The model writes the body and lists each claim with the verbatim
Reddit quote it says supports it; metalworks keeps a claim only when both the supporting quote
resolves to a real quote in the report **and** the claim text appears verbatim in the body.
**Anything it can't back is dropped** — never softened, never guessed.

```python
asset = assets[0]
for c in asset.claim_citations:
    quote = asset.body[c.span_start:c.span_end]   # == c.claim_text
    print(quote, "→ backed by", c.evidence_ref.evidence_id)
```

> The char offsets are Python code-point offsets. A non-Python consumer (JS counts UTF-16 code
> units) should treat `claim_text` as authoritative and re-find it rather than slicing by offset
> when the body contains emoji.

## The channel plan

`mw.channel_plan(research)` returns a `ChannelPlan`: a fully deterministic sequence, no model
involved. One step per channel, each marked `requires_human` and `posting_gated` — the library
plans, you post.

**Show HN is never automated.** Its step says to post it manually and answer replies yourself —
the HN audience expects a human, and the plan encodes that. Holding a `LaunchAsset` or a
`ChannelPlan` never posts anything.

## When the result is thin

`launch(...)` **refuses — returns `[]`** — when the report says don't launch: a negative demand
verdict (thin signal / no demand), or no demand cluster with at least 2 distinct people behind
it. It won't manufacture a launch for an idea the report couldn't validate.

A strong-demand report with a thin *price* signal is still launch-worthy — the refusal reads only
the demand-strength part of the verdict, so a "not enough price signal" caveat is never mistaken
for a no-go. If a single channel's model call fails, that channel is skipped; the rest still
draft.

This is honest, disclosed work only. metalworks won't write fake reviews, invent personas, or
post on your behalf — see the
[usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).

---

Next: a [content & SEO plan](/docs/content-seo) from the same report, or the authentic
[Reddit engagement](/docs/reddit-engagement) loop. Or read
[why you can trust the output](/docs/how-it-works) — the rule that drops any claim it can't back.
