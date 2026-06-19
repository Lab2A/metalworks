# metalworks

**Go from a startup idea to launch, grounded in real demand.**

Give metalworks one sentence about what you want to build. It reads real Reddit
conversations to tell you whether people actually want it, then turns that into
the things you need to launch: your positioning, the competitors to beat, a
marketing site, a build plan for your coding agent, and launch copy. **Every claim
links back to a real comment you can click — nothing is invented.**

A Python library (also a CLI, an MCP server, and a Claude Code plugin). MIT
licensed and built to be embedded — every layer (LLM, search, embeddings,
storage, data source) is a swappable protocol.

> **Status: pre-release (0.0.4).** APIs are unstable below 1.0. The stable
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

Embeddings need no separate key: with a Google or OpenAI key metalworks uses theirs, otherwise
it falls back to a small local model (`fastembed`, bundled with `[research]`, downloaded once).
So a single chat key — Anthropic, OpenRouter, anything — gets you a full run.
`metalworks models warm` pre-downloads the local model.

Prefer Vertex AI over an API key? Set `GOOGLE_GENAI_USE_VERTEXAI=true` plus
`VERTEX_PROJECT_ID` and `VERTEX_LOCATION` and the Google adapters authenticate
via Application Default Credentials. See
[docs/configuration.md](https://metalworks.lab2a.ai/docs/configuration).

```python
from metalworks import Metalworks

mw = Metalworks()             # provider inferred; or Metalworks(model="anthropic/claude-opus-4-6")
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
come from the Hugging Face `open-index/arctic` Parquet mirror; comments from the
live Arctic Shift API. Set `HF_TOKEN` for windows beyond a few months. To read
the submission corpus from a Supabase Storage bucket instead (no HF runtime
dependency), install `metalworks[supabase]` and set `ARCTIC_SHIFT_SOURCE=mirror`,
or [bring your own corpus](https://metalworks.lab2a.ai/docs/custom-corpus) to skip Arctic Shift.

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
| `litellm` | `litellm` | Optional long-tail provider routing |
| `reddit` | `redditwarp`, `cryptography` | Reddit search, OAuth, posting, token encryption |
| `arctic` | `duckdb` | Read Arctic Shift Parquet shards (submissions corpus) |
| `research` | `arctic` + `rank-bm25` | The full demand-report pipeline |
| `supabase` | `arctic` + `supabase` | `ArcticMirrorReader` — Arctic corpus from a Supabase Storage bucket (`ARCTIC_SHIFT_SOURCE=mirror`) |
| `exa` | `exa-py` | Exa `SearchProvider` adapter |
| `tavily` | `tavily-python` | Tavily `SearchProvider` adapter |
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
- `SearchProvider` — external web search (Exa, Tavily).
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
  `run_research(deps, brief=...)`. Seven functions build on a finished report,
  each linking its output back to that report's real quotes: positioning
  (`build_positioning_brief`), the landscape (`run_landscape`), surface + UX
  (`decide_surface` / `build_ux_skeleton`), marketing site
  (`build_marketing_site`), launch assets (`build_launch_assets` /
  `plan_channels`), a content/SEO plan (`content_plan_from_report`), and a build
  plan + scaffold (`build_spec_from_report` / `scaffold`).
- **Reddit** (`metalworks.reddit`) — OAuth, search, subreddit intel, inbox,
  posting, in-library rate limiting, and a deterministic compliance gate
  (`heuristic_check`) that runs offline on reply and post text.

Four form factors share that contract:

1. **Library** — `from metalworks import Metalworks`, or the functions and
   protocols underneath.
2. **CLI** — `metalworks research|reddit|arctic|discovery run`, the report
   commands (`metalworks research position|landscape|surface|site|launch|content-plan`,
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
- Capabilities: [demand research](https://metalworks.lab2a.ai/docs/demand-research) · [positioning & competitors](https://metalworks.lab2a.ai/docs/positioning) · [design & site](https://metalworks.lab2a.ai/docs/design) · [build spec](https://metalworks.lab2a.ai/docs/build-spec) · [launch](https://metalworks.lab2a.ai/docs/launch) · [content & SEO](https://metalworks.lab2a.ai/docs/content-seo) · [Reddit engagement](https://metalworks.lab2a.ai/docs/reddit-engagement)
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
