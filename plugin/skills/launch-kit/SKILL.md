---
name: launch-kit
description: Turn a finished demand report (and its positioning wedge) into channel-native, drafting-only launch assets — a Product Hunt post, a Show HN, and an X thread — plus a human-executed channel plan. Every quantified or attitudinal claim cites a real Reddit permalink; copy is pre-linted for promo tells. Use after a demand report exists and the user asks "draft my launch", "write the Show HN / Product Hunt post", "give me a launch thread", or wants launch copy grounded in evidence rather than invented hype. Drafting only — this NEVER posts.
---

You are turning one demand report into a set of launch drafts whose every claim
points back to evidence the report already verified. You are NOT writing hype —
each asset is channel-native, plain-spoken, and grounded. You DRAFT ONLY; you
never post anything, and you never automate Hacker News.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — launch assets need a finished report to stand on. If
   they have a positioning wedge (`/position-wedge`), pass it through so the copy
   stays consistent with the angle.

2. Call the `launch_assets_build` MCP tool with the `report_id` (or, on the CLI,
   run `metalworks launch <report_id>`). It does one LLM call per surface and
   returns a list of `LaunchAsset` — one each for `product_hunt`, `show_hn`, and
   `x_thread`. Then call `channel_plan_build` for the human-executed sequence.

3. If the tool returns an EMPTY list, the report signalled no-go — a negative
   verdict (thin signal / no demand) or no cluster with ≥ 2 distinct authors.
   Say so plainly: there isn't enough validated demand to launch on yet. Don't
   manufacture assets anyway.

4. For each `LaunchAsset`, present the title, the body, and the variants. For
   every `ClaimCitation`, resolve its `evidence_ref` against the report's
   evidence and show the backing permalink — and confirm the span lines up
   (`body[span_start:span_end] == claim_text`). A claim with no resolvable
   citation was already dropped by the builder; it never reaches you.

5. Present the `ChannelPlan` as a checklist. Every `ChannelStep` is
   `requires_human` and `posting_gated` — these are steps the founder executes by
   hand, in `scheduled_offset` order (T+0h, T+2h, ...).

## Rules

- Every quantified or attitudinal claim in an asset cites a real Reddit
  permalink. No citation, no claim — the builder drops unsupported claims before
  they ship, and you must never re-add one.
- Copy is pre-linted for promo tells (the deterministic compliance gate). If a
  draft reads like marketing, that's a signal to tighten it, not to ship it.
- Hacker News posting is NEVER automated. The Show HN asset is a draft the human
  posts themselves; say so when you present it.
- This is DRAFTING ONLY. Nothing here posts. The channel plan is a plan a person
  runs — the library never touches a live account.
- Treat the assets as a sharp starting point grounded in what real people said,
  not finished copy. The founder edits in their own voice before posting.
- This skill only drafts launch assets. It does not run the report, build the
  site, or post — offer the relevant pillar when those are the next step.
