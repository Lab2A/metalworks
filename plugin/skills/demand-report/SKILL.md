---
name: demand-report
description: Produce a demand report for a product idea from real Reddit conversations. Use when the user wants to validate an idea, gauge demand, find unmet needs, or understand what consumers say about a category. Works with no API keys (sampled corpus + synthesis here) or with an LLM key (the full clustered pipeline).
---

## Preamble (run first)

Before any other tool, run the `preflight` MCP tool (or `metalworks preflight` on
the CLI). If it reports setup issues or that an update is available, surface that
to the user in one line and help them resolve it (install the missing extra/key,
or `pip install -U metalworks`) before continuing. Skip only if the user has
already passed preflight this session.

You are running the metalworks demand-report flow. The goal is a report grounded
in real Reddit conversations, never in your own assumptions.

## Step 1: Frame the question

Ask the user (or infer from their message) the research question, the decision
it informs, and 1-3 candidate subreddits. Keep it to a short exchange. If they
gave enough already, skip ahead.

## Step 2: Pick the path

Check whether the full pipeline is available by calling `research_plan_brief`
with the user's idea.

- If it returns a brief (an LLM key is configured): run the real pipeline.
  Call `research_start` with that brief, then poll `research_status` every few
  seconds until it is ready, then `research_result` to fetch the `DemandReport`.
  Present the ranked clusters with their distinct-author counts and quoted
  permalinks, the verdict, and any web findings. Every quote is exact-matched
  to a real comment; do not paraphrase them as if they were your own.

- If it returns a `missing_key` envelope (no LLM key): run the zero-key path.
  For each candidate subreddit, call `arctic_pull_threads` (scope it to 1 month)
  and `corpus_stats`. Read the pulled threads yourself and synthesize a
  lightweight report in the DemandReport shape: 3-6 demand themes, each with the
  number of distinct authors you saw expressing it and 1-2 verbatim quotes with
  their permalinks. State plainly that this is a sampled, host-synthesized
  report and that adding an LLM key unlocks the full clustered pipeline.

## Rules

- Quotes are verbatim and carry a permalink. Never invent a quote or a URL.
- Report distinct-author breadth, not raw upvotes, as the demand signal.
- If a subreddit returns no relevant threads, say so. Do not pad.
- This is research. It never posts anything to Reddit.
