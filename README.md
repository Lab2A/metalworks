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

> **Status: pre-release (0.0.1).** APIs are unstable below 1.0. The stable
> surface is the `Metalworks` facade, the `metalworks.contract` Pydantic models,
> and the MCP tool contracts. Everything else may change in any 0.x release. Some
> surfaces below are marked **planned for 0.1** where they are not wired yet;
> this README is honest about what runs today.

Read the [USAGE_POLICY](USAGE_POLICY.md) before you use the Reddit side. Short
version: authentic, disclosed engagement only. No fake personas, no vote
manipulation, no coordinated inauthentic behavior.

## Quickstart (no API key)

The headline is the offline demo: fake models on a bundled Reddit corpus, no
keys, no network.

```bash
pip install "metalworks[research]"
```

```python
from metalworks import Metalworks

research = Metalworks.demo().research("Is there demand for a focus supplement?",
                                     subreddits=["Supplements"])
report = research.demand   # .research() returns a Research bundle; the report is on .demand
print(report.verdict)
for cluster in report.ranked_clusters:
    print(cluster.signal, cluster.distinct_author_count, cluster.claim)
```

### Then: a real demand report

Set one provider key — the provider is inferred from whichever key is present:

```bash
pip install "metalworks[google,research]"
export GOOGLE_API_KEY=...     # or ANTHROPIC_API_KEY / OPENAI_API_KEY
```

Prefer Vertex AI over an API key? Set `GOOGLE_GENAI_USE_VERTEXAI=true` plus
`VERTEX_PROJECT_ID` and `VERTEX_LOCATION` and the Google adapters authenticate
via Application Default Credentials. See
[docs/configuration.md](docs/configuration.md).

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
[why you can trust the output](docs/how-it-works.md).

The `Metalworks` facade is the easy path over `run_research` / `run_discovery`
and the protocols — drop down to those whenever you want more control. Submissions
come from the Hugging Face `open-index/arctic` Parquet mirror; comments from the
live Arctic Shift API. Set `HF_TOKEN` for windows beyond a few months. To read
the submission corpus from a Supabase Storage bucket instead (no HF runtime
dependency), install `metalworks[supabase]` and set `ARCTIC_SHIFT_SOURCE=mirror`,
or [bring your own corpus](docs/custom-corpus.md) to skip Arctic Shift.

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
  [docs/custom-store.md](docs/custom-store.md).

See [docs/protocols.md](docs/protocols.md) for signatures.

Two verticals sit on top of those protocols:

- **Research** (`metalworks.research`) — turns an idea into a clustered
  `DemandReport` of real, permalinked Reddit quotes. Entry point:
  `run_research(deps, brief=...)`. Seven functions build on a finished report,
  each linking its output back to that report's real quotes: positioning
  (`build_positioning_brief`), competitors (`run_competitor_map`), surface + UX
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
   commands (`metalworks research position|competitor-map|surface|site|launch|content-plan`,
   `metalworks build init`),
   `metalworks quickstart`, `metalworks doctor`, `metalworks mcp serve`.
3. **MCP server** — zero-key data tools plus key-gated pipeline tools, over stdio
   or SSE.
4. **Claude Code plugin** — `/demand-report` and friends, zero keys on the demo
   path (`/plugin marketplace add Lab2A/metalworks`).

## Testing your own adapters and backends

The conformance suites metalworks holds itself to ship as a public module:

```python
from metalworks.testing import FakeChatModel, FakeEmbedding, check_all_repos

def test_my_backend():
    check_all_repos(MyBackend())   # includes the >1000-row pagination case
```

See [docs/custom-chatmodel.md](docs/custom-chatmodel.md) and
[docs/custom-store.md](docs/custom-store.md).

## Docs

Full docs: **[metalworks.lab2a.ai](https://metalworks.lab2a.ai)**

- [Installation](docs/installation.md) · [Quickstart](docs/quickstart.md) · [Build a startup, end to end](docs/walkthrough.md)
- Capabilities: [demand research](docs/demand-research.md) · [positioning & competitors](docs/positioning.md) · [design & site](docs/design.md) · [build spec](docs/build-spec.md) · [launch](docs/launch.md) · [content & SEO](docs/content-seo.md) · [Reddit engagement](docs/reddit-engagement.md)
- [Why you can trust the output](docs/how-it-works.md) · [Data model](docs/data-model.md)
- Reference: [Python SDK](docs/python-sdk.md) · [CLI](docs/cli.md) · [MCP tools](docs/mcp-tools.md) · [Configuration](docs/configuration.md) · [Using with AI agents](docs/ai-agents.md)
- Extending: [overview](docs/extending.md) · [protocols](docs/protocols.md) · [custom model/corpus/store](docs/custom-chatmodel.md)

## Project

- License: [MIT](LICENSE).
- Usage policy: [USAGE_POLICY.md](USAGE_POLICY.md).
- Security: [SECURITY.md](SECURITY.md).
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md).
- Changes: [CHANGELOG.md](CHANGELOG.md).
- Org: [Lab2A](https://github.com/Lab2A).
