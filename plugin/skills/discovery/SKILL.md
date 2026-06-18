---
name: discovery
description: Find live Reddit threads worth replying to and draft a gated reply for each, in one batch over several queries. Use when the user wants to discover engagement opportunities across topics at once ("find threads I could reply to", "where can I help and mention my product", "scan Reddit for opportunities") rather than work one known thread. Drafting only — it never posts. Posting any draft is a separate, explicitly-confirmed step.
---

You are running discovery: searching Reddit across the user's queries, finding
threads where a genuine reply would help, drafting one reply per thread, and
gating each draft through the compliance check. This is the batch version of
`/find-threads` + `/draft-reply`. It produces drafts only and never posts.

## Steps

1. Get the queries. Ask what the user is looking for — the topics, problems, or
   product space to search. Each becomes a search query; you can pass several.
   Optionally restrict to specific subreddits and set a voice for the drafts.

2. Call the `discovery_run` MCP tool with the `queries` (and optional
   `subreddits`, `max_opportunities`, `voice`). On the CLI this is
   `metalworks discovery run -q "<query>" [-q ...] [--subreddit r] [--voice ...]`.
   It searches, filters for real intent, drafts a reply per thread, and runs each
   draft through `compliance_lint`.

3. Present the opportunities. For each, show the subreddit, the thread URL and
   title, the drafted reply, and the compliance verdict (pass or needs-review).
   Group or sort so the strongest, clean-passing opportunities are easy to see.
   Be honest about the weak ones.

4. Stop there. Discovery never posts. If the user wants to act on a draft, that is
   a separate, deliberate step: refine it if needed (re-run it through the
   compliance gate after any edit, the same as `/draft-reply`), then post only on
   their explicit instruction via `reddit_post_comment` (which also requires
   `METALWORKS_ALLOW_POSTING=1`, a connected account, and a matching confirm token).

## Rules

- Drafting only. Never post from discovery; surface drafts and let the user choose.
- Authentic engagement only. Drop a thread if the only honest reply would be a plug.
- Never edit a draft after its compliance pass without re-linting — the confirm
  token is bound to the exact text.
- Discovery is for finding opportunities across many threads at once. For one known
  thread, use `/draft-reply`; for just finding threads without drafting, use
  `/find-threads`.
