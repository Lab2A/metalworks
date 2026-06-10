---
name: subreddit-intel
description: Write a community brief for a subreddit before participating in it. Use when the user wants to understand a subreddit's norms, rules, tone, and what gets removed before they post or reply there. Needs no API key.
---

You are writing a short, practical brief on a subreddit so the user can
participate without getting removed or downvoted.

## Steps

1. Call `reddit_subreddit_info` and `reddit_subreddit_rules` on the subreddit.
2. Optionally call `corpus_stats` to gauge how much historical discussion exists.
3. Read the description, rules, and recent top titles, then write the brief.

## The brief

Keep it tight and actionable:

- **What it is**: one line on the community and its size.
- **Rules that bite**: the specific rules most likely to get a post or reply
  removed (self-promotion limits, required flair, link policy, account-age or
  karma gates). Quote the rule text where it matters.
- **Tone**: how people actually write here, from the top titles. Formal or
  casual, first-person or not, what openers land.
- **What gets removed**: the failure modes a newcomer would hit.
- **How to show up**: one or two concrete suggestions for an honest, welcome
  first contribution.

## Rules

- Ground every claim in what the tools returned. If the rules are sparse or the
  sub is private, say so rather than guessing.
- This is reconnaissance. It does not post anything.
