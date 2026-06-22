---
title: "MCP tools reference"
description: "Every registered metalworks MCP tool with its correct tier, purpose, and key parameters — the language-agnostic surface."
---

Run `metalworks mcp serve` (stdio is the keyless default) to expose metalworks as
MCP tools. Each tool is a thin async wrapper over a plain, unit-testable body; the
bodies own the error-envelope contract. The authoritative registered set is the
`_TOOL_WRAPPERS` tuple in `metalworks.mcp.server`, and each tool's docstring in
`metalworks.mcp.tools` begins with `TIER 1` or `TIER 2` — that prefix is the
source of truth for its tier.

**31 tools** are registered.

## The tier model

- **Tier 1 — zero-key.** Data and deterministic tools: Reddit search/intel
  (`[reddit]` extra, no API key), the Arctic corpus readers (`[arctic]` extra),
  local-store readers, the offline compliance check, and the two deterministic
  report projections (`channel_plan_build`, `content_plan_from_report`). No
  provider key needed.
- **Tier 2 — key-gated.** Anything that calls a model: planning, the
  report-derived tools, the research job pattern, reply drafting, discovery, and
  posting. These need a **chat provider key** (and some need an **embedding key**).
  A missing credential surfaces a `MissingKeyError` envelope naming the env var and
  extra — it does not crash.

## Tier 1 — zero-key

| Tool | Purpose | Key params |
| --- | --- | --- |
| `compliance_lint` | Deterministic, fully-offline compliance check on reply text; emits a `confirm_token` over the exact text on pass. | `text`, `subreddit_rules` |
| `reddit_search_posts` | Search public Reddit submissions (`[reddit]` extra, no key). | `query`, `subreddit`, `limit` (15) |
| `reddit_get_post_comments` | Top-level comments for a public post URL (`[reddit]`). | `url`, `limit` (10) |
| `reddit_subreddit_info` | Subreddit intel: description, rules, top titles (`[reddit]`). | `name` |
| `reddit_subreddit_rules` | A subreddit's posting rules (`[reddit]`). | `name` |
| `arctic_list_months` | Latest available month in the Arctic corpus (`[arctic]`). | `content_type` (`submissions`) |
| `arctic_pull_threads` | Pull submissions for one subreddit from the Arctic corpus. Scoped: `months` ≤ 3 (default 1), `limit` ≤ 1000 (default 200), so a Tier-1 caller can't trigger an unbounded read (`[arctic]`). | `subreddit`, `months`, `limit` |
| `corpus_stats` | Counts of persisted runs/reports in the local store (offline). | `store_path` |
| `research_list_runs` | List runs (including in-flight) from the local store. | `store_path`, `limit` (50) |
| `research_get_report` | Fetch a finished report from the local store by id. | `report_id`, `store_path` |
| `channel_plan_build` | Deterministic, human-executed launch channel plan for a stored report. Every step is `requires_human` + `posting_gated`; no LLM. | `report_id`, `store_path` |
| `content_plan_from_report` | Project a stored report into a deterministic content/SEO plan — pure, no LLM, no embeddings. | `report_id`, `store_path` |

## Tier 2 — key-gated

| Tool | Purpose | Key params |
| --- | --- | --- |
| `research_plan_brief` | Walk the D1-D8 planner with default answers → an assembled `ResearchBrief` (chat key). | `prompt`, `store_path` |
| `positioning_from_report` | Derive grounded positioning from a stored report — one LLM call, synchronous (chat key). | `report_id`, `store_path` |
| `landscape_from_report` | The full "what exists today" — direct/adjacent/status-quo rivals (each gap cited, each tagged with the clusters it competes for) **plus** an empirical existing-solutions scan, synchronous (chat + embedding keys). | `report_id`, `store_path` |
| `ideate_from_idea` | Idea-first: sharpen a raw idea into a testable hypothesis + a brief (chat key). | `idea`, `store_path` |
| `ideate_from_report` | Evidence-first: surface a stored report's forks as grounded idea sketches (chat key). | `report_id`, `store_path` |
| `assess_from_report` | The **GO / PIVOT / NO-GO** verdict — runs the landscape, then the deterministic demand × landscape gap, synchronous (chat + embedding keys). | `report_id`, `store_path` |
| `validate_from_idea` | Run the validation loop headlessly (`--auto`) from a raw idea — ideate → demand → landscape → assess, looping on PIVOT. **Synchronous and slow** (runs a demand pull); the interactive loop lives in the `validate` skill. | `idea`, `max_iterations` (3), `store_path` |
| `surface_recommend` | Recommend a product surface — grounded rubric + trade-offs, synchronous (chat + embedding keys). | `report_id`, `store_path` |
| `ux_skeleton_build` | Build a UX skeleton for a stored report on the given surface, synchronous (chat + embeddings). | `report_id`, `surface`, `store_path` |
| `site_render` | Build a grounded marketing site + a self-contained `index.html`; `styled=true` also builds the design system and styles it like the brand (chat + embeddings). | `report_id`, `store_path`, `styled` |
| `design_from_report` | Author a grounded-but-directional design system (+ preview HTML) — SAFE/RISK choices read from a real competitor teardown where available; records the `grounding_tier` (chat key). | `report_id`, `name`, `store_path` |
| `logo_generate` | Generate diverse logo options (+ a self-contained picker) drawn under the design system; the model authors each SVG, an unsafe/empty one is dropped (chat key). | `report_id`, `name`, `store_path` |
| `design_review` | Deterministically audit a rendered page's computed styles (fonts, heading scale, colors) against design hard-rules and (with a report) its design system. Needs a script-capable browser renderer. | `url`, `report_id`, `store_path` |
| `launch_assets_build` | Draft grounded, channel-native launch assets — one LLM call per surface; `[]` on a no-go report. Drafting only (chat key). | `report_id`, `store_path` |
| `build_spec` | Derive an evidence-grounded `BuildSpec` — each feature maps to a real demand cluster with quotes; un-grounded features dropped. Returns the spec; does **not** write files (that is the `metalworks build init` CLI) (chat + embedding keys). | `report_id`, `surface` (`web`), `stack` (`empty`), `store_path` |
| `research_start` | Start the pipeline as a background job and return a `run_id` immediately (chat + embedding keys). | `brief`, `months`, `store_path` |
| `research_status` | Status of a background research job. | `run_id`, `store_path` |
| `research_result` | The finished report for a completed job, or a status payload while running. | `run_id`, `store_path` |
| `generate_reply` | Draft a Reddit reply for a thread + run the compliance gate; emits a `confirm_token` on pass (chat key). | `thread_url`, `voice` |
| `discovery_run` | Run discovery over queries → gated draft opportunities. **Never posts** (chat key, `[reddit]`). | `queries`, `subreddits`, `max_opportunities` (10), `voice` |
| `reddit_post_comment` | **Security boundary** — post a reply to a public thread (see below). | `url`, `text`, `confirm_token`, `username` |

<Note>
The report-derived tools (`positioning_from_report`,
`landscape_from_report`, `assess_from_report`, `ideate_from_report`, `surface_recommend`,
`ux_skeleton_build`, `site_render`, `launch_assets_build`, `build_spec`) are **synchronous** —
run them after a stored report exists. `validate_from_idea` is the exception: like the pipeline
it runs a demand pull (minutes), so call it sparingly or prefer the interactive `validate` skill.
</Note>

## The async job pattern

Research takes minutes, so it never runs inline. Call `research_start` to get a
`run_id` immediately, then poll `research_status` (run state) and `research_result`
(the finished report, or a status payload while it's still running).

## The error-envelope contract

Every tool body returns either its success payload or an **error envelope**. The
`guard` decorator turns any raised exception — typed or not — into that envelope,
so a host model never sees a raw traceback:

```json
{ "error": { "error_code": "...", "message": "...", "fix": "...", "docs_url": "..." } }
```

Relay the `fix` string verbatim. Tier-2 bodies that need a credential surface a
`MissingKeyError` envelope naming the env var and extra.

## The posting security gate

`reddit_post_comment` is the security boundary and is **triple-gated**:

1. `METALWORKS_ALLOW_POSTING=1` must be set (operator opt-in) — there is no override.
2. The `confirm_token` must be the one a prior `compliance_lint` (or
   `generate_reply`) pass emitted over this **exact** text — proof the text cleared
   the deterministic gate unchanged. Tokens are per-process HMAC and do not survive
   a server restart.
3. The compliance gate is re-run server-side and must still pass (defense in depth).

It also needs the `[reddit]` extra plus `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`
and a connected account (`metalworks reddit auth login`). A model cannot post
without a passing compliance check on the identical text and an explicit operator
opt-in.
