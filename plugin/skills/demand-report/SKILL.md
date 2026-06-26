---
name: demand-report
description: Produce a demand report for a product idea from real conversations across the web (Reddit, Hacker News, forums, and more). Use when the user wants to validate an idea, gauge demand, find unmet needs, or understand what consumers say about a category. Works with an LLM key (the full clustered pipeline), keyless on your Claude Code login (install metalworks[claude-code] — full pipeline, no key), or fully zero-setup (sampled corpus + synthesis here).
---

## Preamble (run first)

Before any other tool, run the `preflight` MCP tool (or `metalworks preflight` on
the CLI). If it reports setup issues or that an update is available, surface that
to the user in one line and help them resolve it (install the missing extra/key,
or `pip install -U metalworks`) before continuing. Skip only if the user has
already passed preflight this session.

**No provider key? You're in Claude Code — run keyless.** If preflight shows no chat
key but `claude-code` as the resolved provider, the **full** clustered pipeline runs
keyless on the user's Claude Code login (web research included). If `metalworks[claude-code]`
isn't installed, offer `pip install "metalworks[claude-code]"` as the no-key path before
falling back to the sampled here-synthesis route. It's slower (~5–7s/LLM call) but needs no key.

**Read the reference; never reverse-engineer the source.** The moment you need to know how
metalworks behaves — provider/model resolution, which source/reader runs, config precedence,
an error you hit, or the async run loop — **STOP and read `docs/operating-metalworks.md`
(bundled with this plugin) before opening any file under `src/`.** It is the source of truth;
do not derive behavior from source. (Full docs: https://metalworks.lab2a.ai/docs.) For a
long-running run, poll status with the Monitor tool or a bounded loop — never a blind `sleep`.

You are running the metalworks demand-report flow. The goal is a report grounded
in real conversations across the web, never in your own assumptions.

## Step 1: Frame the question

Ask the user (or infer from their message) the research question, the decision
it informs, and 1-3 candidate subreddits. Keep it to a short exchange. If they
gave enough already, skip ahead.

## Step 2: Pick the path

Check whether the full pipeline is available by calling `research_plan_brief`
with the user's idea.

- If it returns a brief (an LLM key is configured): run the real pipeline.
  Call `research_start` with that brief — it returns a `run_id` and runs
  **asynchronously**. Watch it with the **Monitor tool**, or poll
  `research_status(run_id)` on a **bounded loop (~15–30s cadence, never a blind or
  indefinite `sleep`)**, until it reaches a terminal state. `research_status` reports
  fine-grained progress — read `stage`, `stage_index`/`stage_total`, and `updated_at`
  (e.g. "stage 4/6: analyzing · updated 3s ago") so you can tell the run is grinding,
  not hung, and surface that to the user. On `ready`, call `research_result` to fetch
  the `DemandReport` (on `failed`, see the resume step below). Present the ranked
  clusters with their distinct-author counts and quoted permalinks, the verdict, and
  any web findings. Every quote is exact-matched to a real comment; do not paraphrase
  them as if they were your own.

  If `research_status` reports `failed`, do NOT restart from scratch — call
  `research_resume(run_id)` first. The pipeline checkpoints each stage, so a
  resume re-runs only from the last incomplete stage (it reuses the expensive
  Reddit pull, comment hydration, and synthesis already done) and keeps the same
  report id. Then resume polling `research_status`. Only fall back to the
  zero-key path below if a resume also fails or no brief was stored.

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
