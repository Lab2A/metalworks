# metalworks

Marketing research and Reddit engagement as a Python library: demand reports
from real Reddit conversations, plus the OAuth / search / compliance primitives
to act on them. MIT licensed, and built to be embedded — every layer (LLM,
search, embeddings, storage, data source) is a swappable protocol, so you can
assemble your own product on top of it.

> **Status: pre-release (0.0.1).** APIs are unstable below 1.0. The stable
> surface is the `metalworks.contract` Pydantic models and the MCP tool
> contracts. Everything else may change in any 0.x release. Some surfaces below
> are marked **planned for 0.1** where they are not wired yet, this README is
> honest about what runs today.

Read the [USAGE_POLICY](USAGE_POLICY.md) before you use the Reddit side. Short
version: authentic, disclosed engagement only. No fake personas, no vote
manipulation, no coordinated inauthentic behavior.

## 60-second quickstart (no API key)

The headline is the offline demo. It runs against committed Reddit sample data,
touches no network, and needs no keys.

```bash
pip install metalworks
metalworks quickstart    # planned for 0.1 — offline demo on bundled sample shards
```

`quickstart` builds a small demand report end to end with the in-memory store
and the bundled fake models, so you can see the shape of the output before you
decide to plug in your own provider.

### Then: a real demand report

For a real report you need one LLM provider extra and the matching API key. Pick
the provider whose key you already have:

```bash
pip install "metalworks[google,research]"
export GOOGLE_API_KEY=...     # or ANTHROPIC_API_KEY / OPENAI_API_KEY
```

```python
from metalworks.contract import ResearchBrief, TargetSubreddit
from metalworks.research import ResearchDeps, run_research
from metalworks.research.arctic.reader import ArcticReader
from metalworks.stores import MemoryStores
# from metalworks.llm.adapters.google import GoogleChatModel
# from metalworks.embeddings.adapters.google import GoogleEmbedding

brief = ResearchBrief(
    brief_id="demo-1",
    question="Is there demand for a focus supplement aimed at developers?",
    decision_context="Deciding whether to build a nootropic brand.",
    success_criteria=["Find the top unmet needs", "Gauge willingness to pay"],
    must_address=["What do people dislike about current options?"],
    target_subreddits=[TargetSubreddit(name="Nootropics", rationale="core community")],
    web_research_directions=[],
    relevance_rubric="Posts discussing focus, energy, or nootropic supplements.",
)

deps = ResearchDeps(
    chat=GoogleChatModel("gemini-2.5-pro"),         # bind the model you have a key for
    embeddings=GoogleEmbedding("gemini-embedding-001"),
    corpus=MemoryStores(),
    reader=ArcticReader(),                            # HF Parquet by default
)

report = run_research(deps, brief=brief)
print(report.partial, len(report.ranked_clusters))
```

Every quote in `report.ranked_clusters` is exact-matched to a stored Reddit
comment, and every web finding carries its source URL from the grounding tool's
citation metadata, not from model prose. See
[docs/explanation-open-core.md](docs/explanation-open-core.md) for why.

Notes on the real run:

- Submissions come from the Hugging Face `open-index/arctic` Parquet mirror by
  default. Comments come from the live Arctic Shift API (the bulk mirror's
  comment tree lags by years). Point `ArcticReader(data_root=...)` at a local
  directory of `.parquet` files to read offline.
- Unauthenticated Hugging Face access is rate-limited. Scope the first real pull
  to a 1 to 3 month window; set `HF_TOKEN` for longer windows.

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
| `supabase` | `supabase` | Supabase-backed repos (bind existing tables via `table_map`) |
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
  `SqliteStores` ship in core; `SupabaseStores` is behind `[supabase]`.

See [docs/reference-protocols.md](docs/reference-protocols.md) for signatures.

Two verticals sit on top of those protocols:

- **Research** (`metalworks.research`) — brief to Reddit corpus to triage to a
  clustered `DemandReport` with verified, permalinked quotes. Entry point:
  `run_research(deps, brief=...)`.
- **Reddit** (`metalworks.reddit`) — OAuth, search, subreddit intel, inbox,
  posting, in-library rate limiting, and a deterministic compliance gate
  (`heuristic_check`) that runs offline on reply and post text.

Four form factors share that contract:

1. **Library** — import and call (works today for the pieces above).
2. **CLI** — `metalworks ...` (the `version` and `doctor` commands exist;
   `research`, `reddit`, `arctic`, `discovery`, and `mcp serve` are **planned
   for 0.1**).
3. **MCP server** — zero-key data tools plus key-gated pipeline tools (**planned
   for 0.1**).
4. **Claude Code plugin** — `/demand-report` and friends, zero keys on the demo
   path (**planned for 0.1**).

## Testing your own adapters and backends

The conformance suites metalworks holds itself to ship as a public module:

```python
from metalworks.testing import FakeChatModel, FakeEmbedding, check_all_repos

def test_my_backend():
    check_all_repos(MyBackend())   # includes the >1000-row pagination case
```

See [docs/how-to-custom-chatmodel.md](docs/how-to-custom-chatmodel.md) and
[docs/how-to-supabase-store.md](docs/how-to-supabase-store.md).

## Docs

- [Tutorial: your first demand report](docs/tutorial-first-demand-report.md)
- [How-to: implement a custom ChatModel](docs/how-to-custom-chatmodel.md)
- [How-to: bind a Supabase store](docs/how-to-supabase-store.md)
- [Reference: protocols](docs/reference-protocols.md)
- [Explanation: open-core and structural provenance](docs/explanation-open-core.md)
- Agents: see [llms.txt](llms.txt) for a machine-readable index.

## Project

- License: [MIT](LICENSE).
- Usage policy: [USAGE_POLICY.md](USAGE_POLICY.md).
- Security: [SECURITY.md](SECURITY.md).
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md).
- Changes: [CHANGELOG.md](CHANGELOG.md).
- Org: [Lab2A](https://github.com/Lab2A).
