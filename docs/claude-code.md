---
title: "Claude Code plugin"
description: "Run the whole metalworks workflow inside Claude Code as slash commands — validate an idea, get positioning, scaffold a build, plan distribution and draft Reddit replies — backed by an MCP server with 35 tools and a hard posting gate."
---

The metalworks plugin brings the full workflow into Claude Code. Ask
`/demand-report can I sell a focus supplement to developers?` and you get the same grounded
report the library produces — every claim linked to a real quote you can open — right in your chat,
then keep going (`/position-wedge`, `/build-spec`, `/distribution-strategy`) from there.

Under the hood it's an [MCP server](/docs/mcp-tools): each slash command is a skill that calls
one or more of its 35 tools. The commands chain through a stored demand report, exactly like the
[CLI](/docs/cli) — see [Projects & memory](/docs/projects) for how that state persists.

## Install

```
/plugin marketplace add Lab2A/metalworks
/plugin install metalworks@lab2a
```

You need [uv](https://docs.astral.sh/uv/) on your PATH. The plugin runs the metalworks MCP
server via `uvx`, which installs it into an isolated environment on first launch:

```
uvx --from "metalworks[mcp,arctic,reddit]" metalworks mcp serve --transport stdio
```

A `SessionStart` hook **pre-warms** that environment (it runs `metalworks version` quietly when
your session opens), so the first real command doesn't pay the one-time install delay.

## Keys: what works with none, what needs one

The data tools run with **no API key**. The research and synthesis tools use whatever provider
key is in your environment (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` — first
present wins) — or, with `metalworks[claude-code]` installed and no key set, they run **keyless on
your Claude Code login** (the session you're already in). The embeddings a few tools need likewise
default to a keyless local model. So inside Claude Code, the whole pipeline can run with zero keys.

The tools fall into four tiers by what they need: **zero-key** data tools (Reddit + corpus
reads, compliance lint, the corpus-derived data report), **chat-key** synthesis tools (demand
research, positioning, distribution assets, discovery), **chat + embeddings** tools (competitor
map, build spec — which now folds in surface + screens), and the **gated** posting tool (a Reddit reply,
behind an env opt-in). The [MCP tools reference](/docs/mcp-tools) is the canonical list — every
tool, its tier, and its key requirement, in one table.

## The commands

Each command runs one step of the [end-to-end workflow](/docs/walkthrough). Start with
`/demand-report`; the rest take the report it produces (by `report_id`) and build on it.

### Research

- **`/demand-report <idea>`** — is there real demand? Runs the full pipeline (`research_plan_brief` → `research_start` → poll `research_status` → `research_result`) on your provider key — or **keyless on your Claude Code login** when `metalworks[claude-code]` is installed and no key is set. Returns a go/no-go plus ranked demand clusters with distinct-author counts and verbatim, permalinked quotes. Research only — never posts.
- **`/position-wedge`** — turns the report into a Dunford wedge (competitive alternative, unique attribute, value, beachhead, category) + a price band. Calls `positioning_from_report`. Every slot resolves to a real quote; if nothing defensible survives, it says so rather than inventing one.

### Validation loop

Frame an idea, weigh demand against what already exists, get an honest build/don't-build call. See the [validation loop](/docs/validation-loop).

- **`/ideate <idea>`** — sharpen a raw idea into a testable hypothesis + a brief to run demand on (idea-first), or surface a report's under-served forks as grounded sketches to pick from (evidence-first). Calls `ideate_from_idea` / `ideate_from_report`.
- **`/market-landscape`** — the full "what exists today": the competitor map **plus** an empirical scan of real shipped products, each matched to a demand cluster. Calls `landscape_from_report`.
- **`/go-no-go`** — the **GO / PIVOT / NO-GO** verdict, a deterministic gap over demand × landscape, delivered office-hours-style; PIVOT names an under-served fork to aim at, and you make the final call. Calls `assess_from_report`.
- **`/validate <idea>`** — runs the whole loop interactively, with you deciding at each gate; loops back on PIVOT toward the under-served fork until GO, NO-GO, or exhausted.

### Design

- **`/design`** — a grounded-but-directional design system: an aesthetic direction + a SAFE/RISK choice per dimension (`design_from_report`), read from a real browser teardown of competitor sites where available. Records its `grounding_tier` (renderer / web / model_knowledge) so the look is never overstated; writes a `DESIGN.md`. Authors a system, not pixels.
- **`/logo`** — the mark submodule: diverse, company-grade SVG logo options (`logo_generate`), one per design angle, drawn under the brand's design system. Offered, never auto-selected; an unsafe or empty SVG is dropped, never inlined.
- **`/design-review`** — a deterministic audit of a *rendered* page's actual computed styles (fonts, heading scale, colors) against design hard-rules + the design system (`design_review`). The model writes nothing; needs the browser renderer.

### Build

- **`/build-spec`** — a feature spec mapped to real demand (`build_spec`), the surface to build it on (auto-picked with a one-line rationale, or pinned) and a feature-grounded screen skeleton, then a scaffolded repo: `CLAUDE.md` with a cite-or-die rule, `docs/SPEC.md`, a frozen `docs/EVIDENCE.md` quote table, a `PostToolUse` lint hook, and `.mcp.json` wiring back to metalworks. metalworks specs and scaffolds; your agent builds. Ungrounded features are dropped before scaffolding.

### Distribution

Plan where this product gets distributed and draft the channel-native assets — all grounded in the report, all drafting-only. See [Distribution](/docs/distribution) and [GEO / LLM-citability](/docs/distribution-geo).

- **`/distribution-strategy`** — route the report's real named entities + signals into **test→focus** channel experiments (`distribution_strategy`); every channel's `routing_signal` traces to a real corpus entity. Not a ranked portfolio — a set of experiments to test, then concentrate on the winner.
- **`/distribution-requirements`** — the distribution → build requirements (`distribution_requirements`): the embedded loops + the conversion surface distribution designs INTO the product, emitted as concrete build requirements. Feed it to `/build-spec`.
- **`/distribution-assets`** — channel-SHAPED, drafting-only assets per channel (`distribution_assets`): Product Hunt tagline + maker comment, Show HN title + first comment, an X thread, a LinkedIn carousel. Demand claims are grounded; hooks are free. **It never posts.**
- **`/distribution-data-report`** — a corpus-derived **data report** (`distribution_data_report`): a deterministic ranking of the report's clusters (complaint index / feature ranking / State of X) carrying REAL counts, real permalinks, and a verbatim quote per row. Zero-key; the numbers are copied, never invented.
- **`/distribution-geo`** — the GEO / LLM-citability stream (`distribution_geo`): participation targets (real threads from the report's permalinks), citability probes, and answer-first answer briefs. **Drafting only.**
- **`/distribution-engage`** — the participation/execution arm (`distribution_engage`): draft a disclosed, founder-voiced reply for one GEO participation target, run the compliance gate, hand it to you to post. **Posting is human-gated.**
- **`/distribution-plan`** — sequence the channels into a campaign (`distribution_plan`): **pushes** (spike channels at deterministic playbook timings) + **streams** (compounding channels run continuously), pre-launch warming → push week → 30-day post step. **Planning only.**
- **`/distribution-measure`** — close the loop (`distribution_measure`): the per-channel success metric + the instrumentation to wire BEFORE the push, read deterministically by surface type, then re-rank the next push on real results. **Planning only.**

### Grow

- **`/find-threads <product>`** — live Reddit threads worth a genuine reply (`reddit_search_posts`), ranked by honest fit. Discovery only — it doesn't draft or post.
- **`/draft-reply <thread>`** — reads the thread and rules (`reddit_get_post_comments`, `reddit_subreddit_rules`), drafts a reply in your voice (`generate_reply`), and runs it through the compliance gate (`compliance_lint`) until it passes. It stops there. Posting happens only on your explicit instruction, and only if the gate is satisfied.
- **`/subreddit-intel <r/name>`** — a practical brief on a community (rules that bite, tone, what gets removed) before you participate (`reddit_subreddit_info`). Reconnaissance only.
- **`/discovery <queries>`** — the batch of find-threads + draft-reply: searches Reddit across several queries, drafts one reply per worthwhile thread, and gates each through the compliance check (`discovery_run`). Drafts only — it never posts.

## The posting gate

Nothing in the plugin posts to Reddit on its own. The one tool that can, `reddit_post_comment`,
is the security boundary, and it is **triple-gated**:

1. **Operator opt-in.** It refuses unless `METALWORKS_ALLOW_POSTING=1` is set in the server's
   environment. Disabled by default.
2. **A confirm token.** The reply text must carry a token issued by the deterministic
   compliance check (`compliance_lint` / `generate_reply`) over that *exact* text — edit the
   draft after it passed, and the token no longer matches.
3. **A re-check.** It re-runs the compliance gate at post time and refuses if it fails.

It also needs `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` and a connected account. Every
attempt is logged.

### What the compliance gate checks

The gate (`compliance_lint`) is deterministic, offline, and zero-key. It flags AI-tells
("great question", "hope this helps", em-dashes), over-promotion (your product named repeatedly),
length out of bounds, and naked CTAs ("sign up", "check out") — returning a pass/fail verdict
with a confidence score. Drafts that read like marketing get tightened, not shipped.

## Personas, honestly

Reply drafting can take a **persona** — a voice defined by real writing samples and an
**authentic** background. Fabricated personas, invented backstories, and coordinated
inauthentic behavior are prohibited by the
[usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md); the default
persona is empty, so fabrication is never accidental.

## Same engine, your choice of surface

The plugin, the [Python SDK](/docs/python-sdk), the [CLI](/docs/cli), and the
[MCP server](/docs/mcp-tools) all run the same engine and produce the same results — pick
whichever fits how you work. Driving metalworks from your own agent instead of the plugin? See
[using with AI agents](/docs/ai-agents).
