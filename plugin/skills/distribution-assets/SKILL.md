---
name: distribution-assets
description: Turn a finished demand report (and its channel strategy) into channel-SHAPED, drafting-only launch assets — one per selected channel, shaped to its surface (Product Hunt = tagline + maker comment + gallery captions; Show HN = title + technical first comment; X = a numbered tweet thread; LinkedIn = a carousel). Demand/factual claims are grounded to real Reddit quotes (no-cite-no-claim); persuasive hooks, taglines and the per-channel offer/CTA are free craft. Platform invariants are enforced — never an "upvote us" ask, native-first (no link in the hook), founder-voiced. Use after a demand report exists and the user asks "draft my launch", "write the Product Hunt / Show HN post", "give me the launch thread", "what should the launch copy say", or wants channel-native launch copy grounded in evidence rather than a flat blob. DRAFTING ONLY — this NEVER posts.
---

## Preamble (run first)

Before any other tool, run the `preflight` MCP tool (or `metalworks preflight` on
the CLI). If it reports setup issues or that an update is available, surface that
to the user in one line and help them resolve it (install the missing extra/key,
or `pip install -U metalworks`) before continuing. Skip only if the user has
already passed preflight this session.

You are turning one demand report into channel-SHAPED launch assets — the actual
copy for each channel the strategy selected, drafted in the shape that channel
rewards. A Product Hunt post is a tagline + an authentic maker comment + gallery
captions; a Show HN is a plain title + a technical first comment; an X launch is
a numbered tweet thread; a LinkedIn post is a carousel. You are NOT writing one
flat blob and you are NOT forcing a Reddit quote behind every persuasive line.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — assets are drafted off a finished report and its
   channel strategy. If a positioning wedge exists, pass it; it sharpens the copy.

2. Call the `distribution_assets` MCP tool with the `report_id` (or, on the CLI,
   run `metalworks distribution assets <report_id>`). It routes the report into
   its channel strategy, then drafts one `ChannelAsset` per selected channel —
   one LLM call per channel — and returns the list.

3. Walk each asset honestly:
   - Lead with the **channel_name** + **surface_type** + **funnel_stage**.
   - Show the channel-shaped **parts** by role — the maker comment matters more
     than the tagline on PH; the technical first comment is the asset on Show HN.
   - Show the per-channel **offer** (the CTA / conversion ask).
   - Note how many **claim_citations** ground — these are the DEMAND claims that
     trace to a real quote; the persuasive hooks deliberately don't.

## Rules

- **Relaxed grounding, on purpose.** Only demand / factual claims (people want
  this, they resent the incumbent, a number, a sentiment) are grounded — each
  resolves to a real Reddit quote or it is DROPPED (no-cite-no-claim). Persuasive
  hooks, taglines and the offer/CTA are FREE craft — don't demand a citation
  behind a tagline. (Over-grounding the copy was the generate-site mistake; D4
  doesn't repeat it.)
- **Platform invariants are enforced, not optional.** Never an "upvote us" /
  "please upvote" ask — it is platform-fatal on PH and HN and reads as begging; a
  deterministic guard strips it. Native-first: the link goes in a reply / the
  comments, never the opening hook. Founder voice, first person — not brand-speak,
  no AI tells.
- **Channel-shaped, not flat.** The parts a channel gets are decided by its
  surface — don't reshape a Show HN into a Product Hunt post.
- This skill **only drafts**. It does not post, build the site, or run the plan —
  a human reviews and posts every asset. Offer the next distribution step once it
  ships.
