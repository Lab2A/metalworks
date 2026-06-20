# metalworks plugin for Claude Code

Reddit demand research and engagement, inside Claude Code. The plugin bundles
the metalworks MCP server and twelve skills: the five engagement skills below,
plus seven grounded pillars that build on a finished demand report.

## Install

```
/plugin marketplace add Lab2A/metalworks
/plugin install metalworks@lab2a
```

## Requirements

- **uv** on your PATH. The MCP server runs via `uvx`, which installs metalworks
  on first launch into an isolated environment. Install uv with:

  ```
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

  If you see "MCP server failed to connect" right after install, uv is almost
  always the cause. Install it and restart Claude Code.

- **First launch is slow.** `uvx` resolves and installs metalworks (duckdb is a
  large wheel) the first time, which can take a minute or two. A SessionStart
  hook warms the cache, and the install is cached under the plugin's data
  directory after that. If the first launch times out, bump `MCP_TIMEOUT` in
  your environment and retry.

## Skills

- **/demand-report `<idea>`** — a demand report from real Reddit conversations.
  Runs with no API key (sampled corpus + synthesis) or the full clustered
  pipeline when an LLM key is set.
- **/find-threads `<product>`** — find live threads worth a genuine reply.
- **/draft-reply `<thread-url>`** — draft an authentic reply and run it through
  the compliance gate. Drafting is free; posting requires explicit confirmation.
- **/subreddit-intel `<r/name>`** — a community brief before you participate.
- **/discovery `<queries>`** — batch find-threads + draft-reply across several
  queries: drafts a gated reply per worthwhile thread. Never posts.

Pillars run on a finished demand report and trace every claim back to a real
Reddit quote by permalink:

- **/position-wedge** — a grounded Dunford positioning wedge + price hypothesis.
- **/market-landscape** — the full "what exists today": direct, adjacent, and
  status-quo rivals (each gap backed by a cited complaint, each tagged with the
  clusters it competes for) plus a scan of real shipped products with traction.
- **/surface-and-ux** — what surface to build (sdk / web / mobile / cli / ...) and
  a 3-5 screen UX skeleton, each decision traced to a customer voice.
- **/generate-site** — a small marketing site whose every claim-bearing line is a
  verbatim Reddit quote, footnoted to its permalink.
- **/launch-kit** — drafting-only Product Hunt / Show HN / X-thread assets plus a
  human-executed channel plan. Never posts.
- **/content-plan** — a deterministic, zero-key content/SEO plan: one page per
  demand cluster with real stat anchors and the actual permalinks to cite.
- **/build-spec** — an evidence-grounded build harness for a coding agent: core
  features each mapped to a real demand cluster, plus a scaffolded repo with a
  cite-or-die rule and a frozen quote table. metalworks specs it; you build it.

## Keys (optional)

The data tools (search, subreddit intel, corpus pulls, compliance lint) need no
keys. The pipeline tools read a provider key from your environment:

- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY` for the report and
  reply pipelines (first present wins).
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` and `METALWORKS_ALLOW_POSTING=1`
  for the posting path. Posting always runs the compliance gate first and
  always requires your explicit confirmation.

## Usage policy

Authentic, disclosed engagement only. No fake personas, no coordinated
inauthentic behavior, no vote manipulation. See
[USAGE_POLICY](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).

## Versioning

Pre-release. The `.mcp.json` installs the latest metalworks from PyPI
(`metalworks[mcp,arctic,reddit]`), so `uvx` always resolves the newest published
release. A future stable line may switch to a version pin
(`metalworks[mcp,arctic,reddit]==X.Y.Z`) bumped in lockstep with the package.
