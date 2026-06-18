# metalworks plugin for Claude Code

Reddit demand research and engagement, inside Claude Code. The plugin bundles
the metalworks MCP server and sixteen skills across four groups: validate an
idea, engage on Reddit, build on a finished demand report, and take it live.

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

**Validate an idea** — the loop from a raw idea to an honest build/don't-build
call:

- **/demand-report `<idea>`** — a demand report from real Reddit conversations.
  Runs with no API key (sampled corpus + synthesis) or the full clustered
  pipeline when an LLM key is set.
- **/ideate** — frame an idea worth testing: sharpen a raw pitch into one
  testable hypothesis, or surface an existing report's forks as grounded wedges
  to pick from. Frames the idea; it doesn't decide.
- **/market-landscape** — the full "what exists today": direct, adjacent, and
  status-quo rivals (each gap backed by a cited complaint, each tagged with the
  clusters it competes for) plus a scan of real shipped products with traction.
- **/go-no-go** — an honest GO / PIVOT / NO-GO verdict for a finished report: the
  gap between real demand and what people can already do. Computed from the
  evidence, argued with quotes; the human makes the final call.
- **/validate `<idea>`** — run the whole loop end to end (ideate → demand →
  landscape → assess → loop), human-gated at each step, until a GO or out of road.

**Engage on Reddit** — find and join real conversations:

- **/find-threads `<product>`** — find live threads worth a genuine reply.
- **/draft-reply `<thread-url>`** — draft an authentic reply and run it through
  the compliance gate. Drafting is free; posting requires explicit confirmation.
- **/subreddit-intel `<r/name>`** — a community brief before you participate.

**Build on a finished report** — every claim traces back to a real Reddit quote
by permalink:

- **/position-wedge** — a grounded Dunford positioning wedge + price hypothesis.
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

**Take it live** — report → live → paid, with the irreversible step human-gated:

- **/deploy-site** — deploy the report's grounded marketing site to Vercel and
  get a live URL. Preview by default; production needs explicit confirmation.
- **/billing** — turn the report's cited pricing tiers into a real Stripe product,
  price, and payment link. Test mode by default; live charges are double-gated.

## Keys (optional)

The data tools (search, subreddit intel, corpus pulls, compliance lint) need no
keys. The pipeline tools read a provider key from your environment:

- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY` for the report and
  reply pipelines (first present wins).
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` and `METALWORKS_ALLOW_POSTING=1`
  for the posting path. Posting always runs the compliance gate first and
  always requires your explicit confirmation.
- `VERCEL_TOKEN` for `/deploy-site`, and `METALWORKS_ALLOW_DEPLOY=1` to allow a
  production promote. `STRIPE_SECRET_KEY` (with the `[stripe]` extra) for
  `/billing`, and `METALWORKS_ALLOW_BILLING=1` to allow live charges. Both
  default to the safe side — a preview URL, a test-mode product — and never go
  irreversible without your explicit confirmation. No secret is ever printed.

## Usage policy

Authentic, disclosed engagement only. No fake personas, no coordinated
inauthentic behavior, no vote manipulation. See
[USAGE_POLICY](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).

## Versioning

Pre-release. The `.mcp.json` installs the latest metalworks from PyPI
(`metalworks[mcp,arctic,reddit]`), so `uvx` always resolves the newest published
release. A future stable line may switch to a version pin
(`metalworks[mcp,arctic,reddit]==X.Y.Z`) bumped in lockstep with the package.
