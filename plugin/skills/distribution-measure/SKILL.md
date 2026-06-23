---
name: distribution-measure
description: Close the distribution loop for a finished demand report — emit, per selected channel, the success metric that defines what "worked" (e.g. attributed signups in 7d, installs + WAU, qualified replies + click-through, citation appearances) and the exact instrumentation to wire BEFORE the push (a UTM tag, an attributed-signup query, a citation check), all read DETERMINISTICALLY from a table keyed by the channel's surface type — never an invented KPI. This is the falsifiable disposition applied to distribution: name the metric and the instrument up front so the push is measurable, then the human records real results and feeds them back to re-rank the next push (the channels that performed rise, the dead ones fall). Use after a demand report (and ideally a distribution plan) exists and the user asks "how do I measure this", "what's the success metric for each channel", "how do I instrument the launch", "how do I know if a channel worked", "what do I track", or wants to close the loop rather than launch and hope. PLANNING ONLY — it defines what to measure; the human measures and records.
---

You are closing the distribution loop for one demand report. Everything else in
the Distribution pillar PLANS — channels, assets, the sequenced push/stream plan.
This is where it learns: you name, per channel, what "worked" means and exactly
how to track it, so the human can record a real result and the next push re-ranks
on evidence instead of vibes. metalworks can't watch live traffic, so in its lane
it defines the metric + the instrument — it does not measure for you.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — the metrics are derived from the report's channel
   strategy (D2), which needs a finished report to ground on. (Ideally they've
   also run `/distribution-plan` so they know which push each metric belongs to.)

2. Call the `distribution_measure` MCP tool with the `report_id` (or, on the CLI,
   run `metalworks distribution measure <report_id>`). It routes the report into
   its channel strategy, then returns one `ChannelMetric` per selected channel.

3. Present each `ChannelMetric` honestly:
   - `channel_name` + `surface_type` — which channel this is for.
   - `success_metric` — what "worked" means for this channel (e.g. a launch
     platform → top-N + attributed signups in 7d; a marketplace → installs + WAU;
     a community → qualified replies + click-through; answer-engine GEO → citation
     appearances).
   - `instrumentation` — the concrete thing to wire BEFORE the push: a UTM tag, an
     attributed-signup query, a citation check. Tell the user to set this up first;
     a push you can't attribute is launch theater.

4. Explain the loop. After the push, the human measures each metric and records a
   `ChannelResult` (`channel_name`, `metric`, `value`, `period` like "first 7d").
   Feeding those results back — as `prior_results` to the channel strategy and the
   distribution plan — re-ranks the channels so the ones that actually performed
   lead the next push and the dead ones fall. This is what makes a repeatable,
   long-running distribution motion real.

## Rules

- The metric + instrumentation are DETERMINISTIC — read from a fixed table keyed by
  surface type, not an LLM guess. Present what the tool returned; never invent or
  "improve" a KPI.
- Instrument BEFORE the push, not after. An un-attributable channel can't be
  re-ranked, so the loop never closes.
- Higher `value` is better — the re-rank sorts winners first. If a channel has no
  recorded result, it keeps its place but sits behind every measured channel
  (unproven, not promoted above a proven win; not dropped either).
- This skill PLANS what to measure; it never measures or posts. The human runs the
  push, records the numbers, and feeds them back.
- Hand the metrics to the user alongside the `/distribution-plan` so each push
  carries its success metric, then collect results to re-rank the next push.
