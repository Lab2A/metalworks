---
name: distribution-strategy
description: Turn a finished demand report into a channel strategy — route the report's real named entities + signals into the structured channel space as test→focus channel experiments (community-native, marketplace/wedge, embedded loop, data asset, a launch-platform spark), each carrying a cheap test + a success threshold and a routing_signal that traces to a real corpus entity. Use after a demand report exists and the user asks "what channels should I use", "how do I distribute this", "how do I launch this", "where do I find my users", or wants a grounded distribution plan rather than generic "post to Product Hunt" advice. NOT a ranked portfolio — a set of experiments to test and then concentrate on the winner.
---

## Preamble (run first)

Before any other tool, run the `preflight` MCP tool (or `metalworks preflight` on
the CLI). If it reports setup issues or that an update is available, surface that
to the user in one line and help them resolve it (install the missing extra/key,
or `pip install -U metalworks`) before continuing. Skip only if the user has
already passed preflight this session.

You are turning one demand report into a channel strategy — the entity→channel
routing that decides WHERE this product gets distributed, grounded in the real
communities, platforms and signals the audience already named. You are NOT
guessing a generic launch checklist; every channel traces to evidence the report
already verified, and the output is a set of **experiments**, not a portfolio.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — distribution strategy needs a finished report to
   route on. If a positioning wedge exists, it sharpens the product-type call.

2. Call the `distribution_strategy` MCP tool with the `report_id` (or, on the
   CLI, run `metalworks distribution strategy <report_id>`). It does one LLM
   classification call + deterministic routing and returns a `ChannelStrategy`.

3. Read the strategy honestly:
   - Lead with the **product_type** + the one-line **icp_summary** (who this is
     for, in their words).
   - Walk each **channel** as an experiment: its `surface_type` + `funnel_stage`,
     the **routing_signal** (the real entity/signal that selected it), the cheap
     **test**, and the **success_threshold** (the bar to concentrate here).
   - Flag every channel where `requires_spark` is true — name its `spark_channel`
     (marketplaces and loops don't start their own velocity; they need a push to
     ignite).
   - Surface the `worth_it_note` and `caveat` per channel — the honest read, not
     hype (e.g. "Product Hunt drives awareness, not conversions").

4. Close with the two cross-channel reads:
   - **focusing_rule** — most products have ONE channel that works. Tell the user
     to test these cheaply and concentrate on the single winner, not run all of
     them.
   - **funnel_note** — if it flags an all-top-of-funnel **LEAK**, say so plainly:
     attention with no conversion surface to catch it leaks out.

## Rules

- Channels are **derived from the corpus**, never a hardcoded launch list. Every
  `routing_signal` traces to a real named entity/signal (a subreddit the audience
  lives in, a platform in their workflow, a hated incumbent). If the report named
  no communities, the community channel won't appear — don't invent one.
- This is **test→focus, not a portfolio**. Present the channels as experiments to
  validate cheaply; the goal is to find the one channel worth concentrating on.
- Marketplaces, embedded loops and data assets **amplify** existing demand — they
  never create it. Pair them with their spark and report any K-factor honestly.
- This skill only plans the strategy. It does not draft assets, build the site,
  or post anything — offer the next distribution step once it ships.
