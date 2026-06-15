---
title: "CLI reference"
description: "Every metalworks CLI command — by sub-app, with invocations, flags, and which need provider keys."
---

The `metalworks` console script is CLI-first by design: `metalworks --help` and
`metalworks version` work on a bare install with no extras. Everything heavier
(provider SDKs, duckdb, redditwarp, the MCP server) is lazy-imported inside the
command that needs it.

Secrets come from the **environment only** — never the config file. The chat
provider is auto-resolved by which key is present (`ANTHROPIC_API_KEY` >
`OPENAI_API_KEY` > `GOOGLE_API_KEY`/`GEMINI_API_KEY`). Commands that call a model
are flagged **(chat key)** below; the rest are **zero-key**.

## Top-level commands

| Command | Description | Keys |
| --- | --- | --- |
| `metalworks version` | Print the installed metalworks version. | zero-key |
| `metalworks doctor` | Report installed extras, configured keys, the **resolved chat + embedding models**, the store path, connected Reddit accounts, and actionable hints. | zero-key |
| `metalworks init` | Create a `.metalworks/` project in the cwd (like `git init`) — a `project.json` manifest, a `config.toml`, a gitignored `corpus.db`, and a `.env.example`. Idempotent. | zero-key |

**`metalworks init`** option: `--idea TEXT` — one line on what you're building (seeds the project slug).

## models

Inspect and set the chat/fast/embedding models.

| Command | Description | Keys |
| --- | --- | --- |
| `metalworks models list` | Resolved chat / fast / embedding models + a provider × key × extra reachability matrix. | zero-key |
| `metalworks models set <ref>` | Set the default chat model (writes `model` to the cwd `metalworks.toml`). | zero-key |
| `metalworks models set-fast <ref>` | Set the fast/triage model (`fast_model`). | zero-key |
| `metalworks models warm` | Pre-download the local embedding model so the first run isn't blocked on it. | zero-key |

## research

Plan and run demand-research reports, then derive everything else from them. The
report-grounded commands (`position`, `competitor-map`, `surface`, `site`, `launch`,
`content-plan`) all take a **report id** from a prior `research run` (or
`research list`).

| Command | Description | Keys |
| --- | --- | --- |
| `metalworks research plan PROMPT` | Walk the D1-D8 planner over a prompt and write a `brief.json` (recommended option auto-selected, non-interactive). | chat key |
| `metalworks research run` | Run the research pipeline from a `--question` (no brief needed) or a `--brief` file. Stores the report. | chat key |
| `metalworks research list` | List stored research runs — the report ids the report-grounded commands take. | zero-key |
| `metalworks research refresh REPORT_ID` | Re-run a stored report against your latest [research data](/docs/corpus) → an updated report saved as a new version, plus what changed. | chat key |
| `metalworks research versions REPORT_ID` | List a report's versions, oldest → newest. | zero-key |
| `metalworks research diff REPORT_A REPORT_B` | Show the diff between two stored report versions. | chat key |
| `metalworks research position REPORT_ID` | Derive grounded positioning from a stored report (one LLM call). | chat key |
| `metalworks research competitor-map REPORT_ID` | Map the competitive landscape for a stored report — grounded names, cited gaps. | chat key |
| `metalworks research surface REPORT_ID` | Recommend a product surface + UX skeleton for a stored report (grounded). | chat key |
| `metalworks research site REPORT_ID` | Build a grounded marketing site (verbatim, cited copy) from a stored report. | chat key |
| `metalworks research launch REPORT_ID` | Draft grounded, channel-native launch assets + a human-run channel plan. **Never posts.** | chat key |
| `metalworks research content-plan REPORT_ID` | Project a stored report into a deterministic content/SEO plan. **No LLM.** | zero-key |

Options:

- `research plan` — `--out, -o PATH` (default `brief.json`).
- `research run` — `--question, -q TEXT` *or* `--brief PATH` (pass exactly one); `--subreddit TEXT` (repeatable, else auto); `--source TEXT` (repeatable — which [sources](/docs/sources) to ingest from; else configured/Reddit); `--months INT` (corpus window, default 12); `--out, -o PATH` to write the report JSON.
- `research list` — `--limit INT` (max runs to show, default 20).
- `research refresh` — `REPORT_ID` argument (any version of the report; updates from the latest one); `--out, -o PATH` to write the new report JSON.
- `research diff` — `REPORT_A REPORT_B` arguments (earlier, later).
- `research position` / `competitor-map` / `surface` / `launch` / `content-plan` — `REPORT_ID` argument; `--out, -o PATH` to write the artifact JSON.
- `research site` — `REPORT_ID` argument; `--out, -o PATH` for the rendered `index.html`; `--json PATH` for the `MarketingSite` JSON.

## corpus

Grow and inspect your [saved research data](/docs/corpus) — what research reads
from. A `research run` saves what it reads automatically, but you can also add to
it directly to build up evidence over time and across sources.

| Command | Description | Keys |
| --- | --- | --- |
| `metalworks corpus add --source <id> -q "..."` | Pull a source's items for a query into the corpus (idempotent — re-adding upserts by id). | depends on source |
| `metalworks corpus sync` | Re-pull the latest window for the enabled sources. | depends on source |
| `metalworks corpus stats` | Records + comments in the corpus, broken down by source. | zero-key |

Options: `corpus add` — `--source TEXT` (the source id, e.g. `reddit` / `hackernews` / `web`); `-q, --query TEXT`; `--limit INT`.

## sources

List and toggle the [data sources](/docs/sources) research ingests from.

| Command | Description | Keys |
| --- | --- | --- |
| `metalworks sources list` | Registered sources + whether each is enabled and reachable. | zero-key |
| `metalworks sources enable <id>` | Enable a source (writes the `[sources]` config table). | zero-key |
| `metalworks sources disable <id>` | Disable a source. | zero-key |

## build

Scaffold an evidence-grounded build harness from a report (see the
[Build spec](/docs/build-spec)).

| Command | Description | Keys |
| --- | --- | --- |
| `metalworks build init REPORT` | Turn a stored report into a build plan and scaffold a project for your coding agent (no product code). | chat key |

`REPORT` is a stored report id (from `research list`) **or** a path to a
`report.json`. Options:

- `--dest, -d PATH` — directory to scaffold into (default `./build`).
- `--surface TEXT` — target surface: `web` | `mobile` | `cli` | `api` | `sdk` | `browser_extension` | `desktop` (default `web`).
- `--base TEXT` — stack hint recorded in the spec, e.g. `next-shipfast` (default `empty`).

## reddit

Search Reddit, fetch intel, and post (gated). The `[reddit]` extra is required;
search and intel need **no API key**, only posting needs OAuth credentials.

| Command | Description | Keys |
| --- | --- | --- |
| `metalworks reddit search QUERY` | Search public Reddit submissions. | zero-key (`[reddit]`) |
| `metalworks reddit subreddit info NAME` | Subreddit intel: description, subscribers, top titles, rules. | zero-key (`[reddit]`) |
| `metalworks reddit subreddit rules NAME` | List a subreddit's posting rules. | zero-key (`[reddit]`) |
| `metalworks reddit auth login` | Start the Reddit OAuth loopback flow and store the connected account. | Reddit OAuth |
| `metalworks reddit post URL --text ...` | Reply to a thread. Runs the deterministic compliance gate **first**; refuses on fail. Dry-run by default. | Reddit OAuth |

Options:

- `reddit search` — `--subreddit TEXT` (restrict to r/X); `--limit INT` (default 15).
- `reddit auth login` — requires `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` in the env; you paste the `code` from the redirect URL.
- `reddit post` — `URL` argument; `--text TEXT` (the reply, required); `--username TEXT` (which connected account); `--yes` (actually send — default is a dry-run that prints the verdict and stops).

## discovery

Find and draft Reddit reply opportunities (drafts only; never posts).

| Command | Description | Keys |
| --- | --- | --- |
| `metalworks discovery run --query ...` | Search Reddit, draft replies, and gate each through the compliance check. **Produces drafts only.** | chat key (`[reddit]`) |

Post a chosen draft yourself with `metalworks reddit post <url> --text ...`.

## arctic

Read the Arctic Shift historical corpus. **Zero-key** — needs the `[arctic]` extra (duckdb).

| Command | Description | Keys |
| --- | --- | --- |
| `metalworks arctic months` | Print the latest available submissions month in the Arctic corpus. | zero-key (`[arctic]`) |
| `metalworks arctic pull SUBREDDIT` | Pull submissions for a subreddit from the corpus → table or JSONL. | zero-key (`[arctic]`) |

Options for `arctic pull`: `--months INT` (how many months back, default 1); `--out, -o PATH` (write rows as JSONL; otherwise prints a table preview).

## config

Read and write non-secret config (cwd over the user config dir). **Zero-key.**
Secret keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, provider/search/Reddit keys,
`METALWORKS_FERNET_KEY`, `METALWORKS_MCP_TOKEN`) are refused — they must come from
the environment.

| Command | Description |
| --- | --- |
| `metalworks config list` | Print the merged non-secret config. |
| `metalworks config get KEY` | Print one config value (file only). |
| `metalworks config set KEY VALUE` | Set one non-secret value in the cwd config. Refuses secret keys. |

## mcp

Run the metalworks MCP server (see the [MCP tools reference](/docs/mcp-tools)).

| Command | Description |
| --- | --- |
| `metalworks mcp serve` | Launch the MCP server. |

Options: `--transport TEXT` (`stdio` default — keyless; or `sse`); `--port INT`
(SSE port); `--host TEXT` (SSE bind host); `--token TEXT` (bearer token). The
`sse` transport is network-exposed and **refuses to start without a bearer token**
(`--token` or `METALWORKS_MCP_TOKEN`); `stdio` is the keyless default.
