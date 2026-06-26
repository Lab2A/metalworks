# metalworks

**Go from a startup idea to launch, grounded in real demand.**

Give metalworks one sentence about what you want to build. It reads real
conversations across the web — Reddit, Hacker News, forums, Q&A, or your own
data — to tell you whether people actually want it, then turns that into the
things you need to launch: your positioning, the competitors to beat, a design
system, a build plan for your coding agent, and launch copy. **Every claim links
back to a real quote you can click — nothing is invented.**

A Python library (also a CLI, an MCP server, and a Claude Code plugin). MIT
licensed and built to be embedded — every layer (LLM, search, embeddings,
storage, data source) is a swappable protocol.

> **Status: pre-release (0.4.0).** APIs are unstable below 1.0. The stable
> surface is the `Metalworks` facade, the `metalworks.contract` Pydantic models,
> and the MCP tool contracts — everything else may change in any 0.x release.
> Everything described in this README runs today.

Read the [USAGE_POLICY](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md) before you use the Reddit side. Short
version: authentic, disclosed engagement only. No fake personas, no vote
manipulation, no coordinated inauthentic behavior.

## Quickstart

Install metalworks with a provider SDK and set **one** key — any provider works:

```bash
pip install "metalworks[openai,research]"   # or [google,research], [anthropic,research]
export OPENAI_API_KEY=...                    # or ANTHROPIC_API_KEY / GOOGLE_API_KEY / OPENROUTER_API_KEY
```

Or **run keyless on your Claude Code login** — no provider key at all:

```bash
pip install "metalworks[claude-code,research]"   # bundles the `claude` CLI; no env var to set
```

With `[claude-code]` installed and no key configured, the chat model **and** web search fall back to
your Claude Code session (the keyless "floor"). It's the no-setup path for local/individual use — it
spawns the `claude` CLI per call (~5–7s each), so a configured key is faster for big runs, and any
explicit key/ref still wins.

Embeddings need no separate key either: with a Google or OpenAI key metalworks uses theirs, otherwise
it falls back to a small local model (`fastembed`, bundled with `[research]`, downloaded once).
So one chat key — Anthropic, OpenRouter, anything — *or zero keys via Claude Code* — gets you a full run.
`metalworks models warm` pre-downloads the local model.

Prefer Vertex AI over an API key? Set `GOOGLE_GENAI_USE_VERTEXAI=true` plus
`VERTEX_PROJECT_ID` and `VERTEX_LOCATION` and the Google adapters authenticate
via Application Default Credentials. See
[docs/configuration.md](https://metalworks.lab2a.ai/docs/configuration).

```python
from metalworks import Metalworks

mw = Metalworks()             # provider inferred; or Metalworks(model="anthropic/claude-opus-4-8")
research = mw.research("Is there demand for a focus supplement aimed at developers?",
                       subreddits=["Nootropics", "Supplements"])
report = research.demand
```

Every quote in `report.ranked_clusters` is the exact text of a real Reddit
comment, and every web finding carries its real source URL — never model prose.
Anything metalworks can't back with a real quote, it drops. See
[why you can trust the output](https://metalworks.lab2a.ai/docs/how-it-works).

The `Metalworks` facade is the easy path over `run_research` / `run_discovery`
and the protocols — drop down to those whenever you want more control. Submissions
and comments both come from the **live Arctic Shift API** by default — current data,
keyless, on core `httpx`. Opt into a bulk/offline tier with `ARCTIC_SHIFT_SOURCE`: `hf`
reads the Hugging Face `open-index/arctic` Parquet mirror (`metalworks[arctic]`, reads
`HF_TOKEN` to lift the public rate limit), `mirror` reads a Supabase Storage bucket
(`metalworks[supabase]`). Or [bring your own corpus](https://metalworks.lab2a.ai/docs/custom-corpus)
to skip Arctic Shift entirely.

## Extras

Core stays lean (pydantic, httpx, typer, rich). Everything that pulls a provider
SDK or a heavy dependency lives behind an extra, so you install only what
matches the keys you have. Adapters lazy-import their SDK and raise
`MissingExtraError` with the exact `pip install` command when it is absent.

```bash
pip install "metalworks[google]"
pip install "metalworks[research,reddit]"
pip install "metalworks[all]"
```

| Extra | Pulls in | For |
| --- | --- | --- |
| `anthropic` | `anthropic` | Claude `ChatModel` adapter |
| `openai` | `openai` | OpenAI `ChatModel` + embedding adapters |
| `google` | `google-genai` | Gemini `ChatModel` (native grounding) + embeddings |
| `claude-code` | `claude-agent-sdk` | **Run keyless on your Claude Code login** (bundled `claude` CLI) — the chat *and* web-search floors when no provider key is set |
| `litellm` | `litellm` | Optional long-tail provider routing |
| `reddit` | `redditwarp`, `cryptography` | Reddit search, OAuth, posting, token encryption |
| `arctic` | `duckdb` | Read Arctic Shift Parquet shards (submissions corpus) |
| `research` | `arctic` + `rank-bm25` | The full demand-report pipeline |
| `supabase` | `arctic` + `supabase` | `ArcticMirrorReader` — Arctic corpus from a Supabase Storage bucket (`ARCTIC_SHIFT_SOURCE=mirror`) |
| `exa` | `exa-py` | Exa `SearchProvider` adapter |
| `tavily` | `tavily-python` | Tavily `SearchProvider` adapter |
| `parallel` | `parallel-web` | Parallel `SearchProvider` / agentic discovery |
| `firecrawl` | `firecrawl-py` | Firecrawl search + hosted page rendering |
| `browser` | `playwright` | Owned headless Chromium `PageRenderer` (competitor teardowns, design review). **Post-install step:** `metalworks browser install`. On a server, `FIRECRAWL_API_KEY` renders without a local browser. |
| `mcp` | `mcp[cli]` | MCP server surface |
| `all` | everything above | Kitchen sink |
| `dev` | pytest, ruff, pyright, respx | Contributors |

A bare `import metalworks` pulls in no provider modules; CI asserts this.

## Architecture

metalworks owns small, versioned **protocols** and ships thin **adapters** over
official provider SDKs. It does not route every provider through LiteLLM by
default. The protocols are the seam your code and the pipeline speak through:

- `ChatModel` — `complete_text` / `complete_structured`, model bound at adapter
  construction. `GroundedChatModel` adds model-native web grounding with full
  provenance (chunks plus character-offset supports).
- `SearchProvider` — external web search (Exa, Tavily, Parallel, Firecrawl), or keyless via Claude Code.
- `EmbeddingProvider` — embeddings with a hard index-identity guard.
- The typed repos (`CorpusRepo`, `BriefRepo`, `RunRepo`, `AccountRepo`,
  `OpportunityRepo`, `InboxRepo`) are the storage protocol. `MemoryStores` and
  `SqliteStores` ship in core; hosted backends (Postgres/PostgREST) are a custom
  store you implement downstream — see
  [docs/custom-store.md](https://metalworks.lab2a.ai/docs/custom-store).

See [docs/protocols.md](https://metalworks.lab2a.ai/docs/protocols) for signatures.

Two verticals sit on top of those protocols:

- **Research** (`metalworks.research`) — turns an idea into a clustered
  `DemandReport` of real, permalinked Reddit quotes. Entry point:
  `run_research(deps, brief=...)`. Several functions build on a finished report,
  each linking its output back to that report's real quotes: positioning
  (`build_positioning_brief`), the landscape (`run_landscape`), distribution
  (`build_channel_strategy` / `build_channel_assets` / `build_data_asset` /
  `build_geo_plan` / `plan_distribution`), and a build plan + scaffold
  (`build_spec_from_report` / `scaffold`) — which also picks the surface and
  sketches feature-grounded screens.
- **Reddit** (`metalworks.reddit`) — OAuth, search, subreddit intel, inbox,
  posting, in-library rate limiting, and a deterministic compliance gate
  (`heuristic_check`) that runs offline on reply and post text.

Four form factors share that contract:

1. **Library** — `from metalworks import Metalworks`, or the functions and
   protocols underneath.
2. **CLI** — `metalworks research|reddit|arctic|discovery run`, the report
   commands (`metalworks research position|landscape`,
   `metalworks distribution strategy|assets|data-report|geo|requirements|plan|measure|engage`,
   `metalworks build init`),
   `metalworks doctor`, `metalworks mcp serve`.
3. **MCP server** — zero-key data tools plus key-gated pipeline tools, over stdio
   or SSE.
4. **Claude Code plugin** — `/demand-report` and friends
   (`/plugin marketplace add Lab2A/metalworks`).

## Testing your own adapters and backends

The conformance suites metalworks holds itself to ship as a public module:

```python
from metalworks.testing import FakeChatModel, FakeEmbedding, check_all_repos

def test_my_backend():
    check_all_repos(MyBackend())   # includes the >1000-row pagination case
```

See [docs/custom-chatmodel.md](https://metalworks.lab2a.ai/docs/custom-chatmodel) and
[docs/custom-store.md](https://metalworks.lab2a.ai/docs/custom-store).

## Docs

Full docs: **[metalworks.lab2a.ai](https://metalworks.lab2a.ai)**

- [Installation](https://metalworks.lab2a.ai/docs/installation) · [Quickstart](https://metalworks.lab2a.ai/docs/quickstart) · [Build a startup, end to end](https://metalworks.lab2a.ai/docs/walkthrough)
- Capabilities: [demand research](https://metalworks.lab2a.ai/docs/demand-research) · [positioning & competitors](https://metalworks.lab2a.ai/docs/positioning) · [design system](https://metalworks.lab2a.ai/docs/design-system) · [build spec](https://metalworks.lab2a.ai/docs/build-spec) · [distribution](https://metalworks.lab2a.ai/docs/distribution) · [GEO / LLM-citability](https://metalworks.lab2a.ai/docs/distribution-geo) · [Reddit engagement](https://metalworks.lab2a.ai/docs/reddit-engagement)
- [Why you can trust the output](https://metalworks.lab2a.ai/docs/how-it-works) · [Data model](https://metalworks.lab2a.ai/docs/data-model)
- Reference: [Python SDK](https://metalworks.lab2a.ai/docs/python-sdk) · [CLI](https://metalworks.lab2a.ai/docs/cli) · [MCP tools](https://metalworks.lab2a.ai/docs/mcp-tools) · [Configuration](https://metalworks.lab2a.ai/docs/configuration) · [Using with AI agents](https://metalworks.lab2a.ai/docs/ai-agents)
- Extending: [overview](https://metalworks.lab2a.ai/docs/extending) · [protocols](https://metalworks.lab2a.ai/docs/protocols) · [custom model/corpus/store](https://metalworks.lab2a.ai/docs/custom-chatmodel)

## Contributing & development

Collaborators welcome. metalworks is **contract-first**: one set of Pydantic models
(`metalworks.contract`) is the stable spine, and every surface speaks it — so a capability lands on
the **Python facade, the CLI, the MCP server, and the Claude Code plugin together**, never just one.
The [architecture page](https://metalworks.lab2a.ai/docs/architecture) is the mental model;
[CONTRIBUTING.md](https://github.com/Lab2A/metalworks/blob/main/CONTRIBUTING.md) is the operational
guide.

```bash
git clone https://github.com/Lab2A/metalworks && cd metalworks
uv venv && uv pip install -e ".[all,dev]"
# the gate — everything must pass before a PR:
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q
```

Where things live:

| Path | What |
| --- | --- |
| `src/metalworks/contract/` | the Pydantic models every surface speaks — the stable spine |
| `src/metalworks/research/`, `reddit/` | the two cores: demand research + Reddit engagement |
| `src/metalworks/client.py` | the `Metalworks` facade — **surface 1** |
| `src/metalworks/cli/` | the `metalworks` CLI — **surface 2** |
| `src/metalworks/mcp/` | the MCP tool bodies + server — **surface 3** |
| `plugin/skills/` | the Claude Code plugin skills — **surface 4** |
| `scripts/gen_ts_types.py` | regenerates `ts/contract.ts` + JSON schema snapshots from the contract |
| `tests/` | offline by default (`pytest-socket`; fakes for the LLM / embeddings / stores) |

**The golden rule:** a change to a primitive moves all four surfaces, the contract registry
(`gen_ts_types` + `contract/__init__`), and the docs — together. Run **`/pr-ready`** (the Claude Code
skill in `.claude/skills/`) before opening a PR: it runs the gate, the contract-drift check CI
*doesn't*, and walks the parity / docs / CHANGELOG checklist.

## Project

- License: [MIT](https://github.com/Lab2A/metalworks/blob/main/LICENSE).
- Usage policy: [USAGE_POLICY.md](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).
- Security: [SECURITY.md](https://github.com/Lab2A/metalworks/blob/main/SECURITY.md).
- Contributing: [CONTRIBUTING.md](https://github.com/Lab2A/metalworks/blob/main/CONTRIBUTING.md).
- Changes: [CHANGELOG.md](https://github.com/Lab2A/metalworks/blob/main/CHANGELOG.md).
- Org: [Lab2A](https://github.com/Lab2A).
