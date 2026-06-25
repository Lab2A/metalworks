---
name: find-threads
description: Find live Reddit threads worth engaging for a product or topic. Use when the user wants to find conversations to join, monitor a subreddit for relevant discussion, or surface high-intent threads about their space. Needs no API key.
---

## Preamble (run first)

Before any other tool, run the `preflight` MCP tool (or `metalworks preflight` on
the CLI). If it reports setup issues or that an update is available, surface that
to the user in one line and help them resolve it (install the missing extra/key,
or `pip install -U metalworks`) before continuing. Skip only if the user has
already passed preflight this session.

You are finding Reddit threads worth a genuine, disclosed reply for the user's
product or topic.

## Steps

1. From the user's product or topic, generate 3-6 specific search queries that
   real people would write when they have the problem the product solves. Favor
   problem-phrased queries ("3pm energy crash without caffeine") over
   brand-phrased ones.

2. For each query, call `reddit_search_posts` (pass a subreddit when the user
   named one). Collect the results.

3. Filter for genuine intent. Keep threads where someone is asking for help,
   comparing options, or voicing a complaint the product addresses. Drop news,
   memes, and threads already saturated with replies.

4. Present a ranked list: for each kept thread, the subreddit, the title, the
   permalink, and one line on why it is a fit and what an honest reply would add.

## Rules

- This skill only finds threads. It does not draft or post. Offer to run
  `/draft-reply <url>` on any thread the user picks.
- Be honest about thin results. A short, real list beats a padded one.
- Never suggest replying to a thread where the only honest contribution would be
  a plug.
