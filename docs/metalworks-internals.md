# How metalworks works — the whole engine, in detail

> A complete internals reference for `Lab2A/metalworks`: what it is, the contract
> layer, the swappable-protocol architecture, the demand pipeline, the surfaces, and
> the startup-shapes catalog. Written 2026-06-17. Grounded in the real modules under
> `src/metalworks/`. Where a surface is not fully wired in this release it is marked
> **[planned]**.

---

## 0. What metalworks is, in one breath

Give it one sentence about a product idea. It reads **real Reddit conversations** (plus
optional web research), tells you whether people actually want it, and turns that into the
things you need to launch: positioning, the competitors to beat, a marketing site, a build
spec, and launch copy. **Every claim links back to a real comment you can click. Anything
it cannot back with a real quote, it drops.**

Two identity rules run through everything:

1. **Spec, don't vendor.** metalworks produces a runnable *spec* for *your own* coding
   agent (a Claude Code terminal) to build against. It is not a coding agent and does not
   host product backends.
2. **Nothing invented.** The honesty spine (exact-quote verification, distinct-author
   breadth, deterministic verdicts) is never bypassed. Evidence can always say no.

It ships as a Python library, a CLI, an MCP server, and a Claude Code plugin. MIT, pre-release
0.0.x — the stable surface is the `Metalworks` facade, the `metalworks.contract` models, and
the MCP tool contracts; everything else can change in any 0.x release.

---

## 1. The five-stage arc

```
   idea sentence
        │
        ▼
  ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌──────────┐   ┌──────────┐
  │ RESEARCH  │──▶│  DESIGN    │──▶│  BUILD    │──▶│  LAUNCH  │──▶│  GROWTH  │
  │ demand    │   │ position/  │   │ BuildSpec │   │ launch   │   │ content/ │
  │ report    │   │ landscape/ │   │ + shape   │   │ assets,  │   │ SEO,     │
  │ (cited)   │   │ surface/UX │   │ match     │   │ reply    │   │ engage   │
  └───────────┘   └───────────┘   └───────────┘   └──────────┘   └──────────┘
        │              │               │
        └── each stage emits one FROZEN, TYPED bundle; downstream resolves
            EvidenceRefs against the upstream report's evidence list.
```

Stage 1 (`Research`) is the only fully-built stage today; later pillars are exposed as
methods on the facade and as optional fields on the `Research` bundle that fill in as they
ship. The bundle (`contract/bundle.py`) is the durable stage-1 artifact: `demand` plus
optional `competitors`, `positioning`, `landscape`, `assessment`, `ideation`.

---

## 2. The contract layer — the stable public API

`metalworks.contract` is the single source of truth for every surface (library, CLI, MCP,
generated TypeScript). Pydantic models, content-addressed evidence ids, JSON-schema
snapshots diff-gated in CI.

### The demand report (`contract/research.py`)

`DemandReport` is the canonical output. Key parts:

- `ranked_clusters: list[InsightCluster]` — ranked consumer-insight themes. Each cluster:
  - `claim` — one-line synthesized insight
  - `demand_score` — weights **distinct-author breadth** above single-post virality
  - `distinct_author_count` — the honest base rate (separate from `mention_count`)
  - `signal: SignalStrength` (LOW / MEDIUM / HIGH) — the confidence chip
  - `quotes: list[ResolvedCitation]` — 2-3 verified quotes; **no-quote-no-theme**
- `ResolvedCitation` — the portable, verified quote: verbatim `text` (exact-matched to a
  real comment), `source_url` (the permalink), `author_hash` (salted, for distinct-author
  counting, never the raw username), `engagement`.
- Fork selectors: `segments` / `candidate_wedges` (options the engine *surfaces*, not
  collapses) with `default_*` / `active_*` accessors.
- `web_findings`, `price_finding`, `audience_profile`, `market_sizing`, `source_map`,
  `corpus_stats`, `cross_references`, `must_address_resolution`.
- `evidence` (computed property) — the flat, de-duplicated `EvidenceRecord` list every
  downstream `EvidenceRef` resolves against.

### The evidence spine (`contract/evidence.py`)

`EvidenceRef` (`evidence_id` + `kind` in {quote, web, price, cluster} + optional
`cluster_rank`) is how every downstream pillar points at upstream evidence by id, never by
free text. The **no-cite-no-claim** gate: a claim-bearing field with zero resolvable refs is
dropped at assembly.

### Downstream pillar contracts

| Contract | File | What it carries |
|---|---|---|
| `PositioningBrief` | `positioning.py` | Dunford wedge (competitive alt → unique attribute → value → beachhead → category) + price hypothesis; `wedge` is `None` when there's no real white space |
| `Landscape` / `CompetitorMap` | `landscape.py` | competitors (direct/adjacent/status-quo), gaps, existing solutions |
| `SurfaceRecommendation` | `surface.py` | `chosen: SurfaceKind` ∈ {sdk, web, mobile, cli, browser_extension, api, desktop} + UX skeleton |
| `BuildSpec` | `build.py` | `features` (each evidence-backed, cite-or-die), `personas`, `pricing_tiers`, `stack` hint |
| `Assessment` / `Decision` | `assess.py` | GO / PIVOT / NO_GO — **deterministic** from demand × landscape; LLM only writes the rationale |
| `MarketingSite` | `contract/site.py` (rendered by `research/site.py`) | verbatim-cited site sections + `render_site_html` |
| `ContentPlan` | `marketing.py` | deterministic SEO/content plan, one page per cluster |

The deterministic verdict is the heart of the honesty model: `assess()` computes the gap
(demand strength vs landscape saturation); a `partial` landscape can never yield a hard GO.

---

## 3. The swappable-protocol architecture

Every layer is a `runtime_checkable` Protocol with thin adapters and a deterministic fake.
Bare `import metalworks` pulls **zero** provider SDKs; each adapter lazy-imports its SDK and
raises `MissingExtraError` with the exact `pip install` to run.

```
        Metalworks facade  /  CLI  /  MCP  /  plugin
                         │
   ┌─────────┬───────────┼────────────┬───────────┬──────────────┐
   ▼         ▼           ▼            ▼           ▼              ▼
ChatModel  Embedding   Search     ItemSource   Stores       (shapes)
 (llm/)    Provider    Provider   + Corpus     (memory,     ShapeMatcher
           (embeddings)(search/)   Reader       sqlite,      (shapes/)
                                  (research/    file)
   anthropic fastembed exa        sources/)
   openai    openai    tavily     arctic
   google    google    parallel   hackernews
   (+fallback)         firecrawl  producthunt, web
```

| Protocol | Module | Methods | Adapters |
|---|---|---|---|
| `ChatModel` / `GroundedChatModel` | `llm/protocol.py` | `complete_text`, `complete_structured`, `complete_grounded` | anthropic, openai, google (+ `FallbackChatModel`, `FakeChatModel`) |
| `EmbeddingProvider` | `embeddings/` | `embed(texts, task)` + `IndexIdentity` guard | fastembed (local), openai, google (+ `FakeEmbedding`) |
| `SearchProvider` | `search/` | `search(query, max_results, recency_days)` | exa, tavily, parallel, firecrawl |
| `ItemSource` / `CorpusReader` / `CommentSource` | `research/sources/`, `research/deps.py` | `pull`, `comments_for`, `latest_window` | arctic (Reddit), hackernews, producthunt, web |
| repos (`BriefRepo`, `RunRepo`, `CorpusRepo`, `AccountRepo`, `OpportunityRepo`, `InboxRepo`, `ArtifactStore`) | `stores/` | typed per-repo methods | memory, sqlite, filestore |

Two registry patterns recur: the **`SOURCES` registry** (`research/sources/__init__.py`,
self-registering on import, lazy builtin loading) and now the **shapes catalog** (§7), which
copies it. `metalworks.testing` ships conformance suites (`check_all_repos`,
`check_item_source`) so anyone writing a custom adapter can verify it.

Provider auto-resolution (`config.py`): ambient env keys → adapter instances. Precedence is
explicit arg > env var > config file. Config files hold only non-secrets; all keys come from
env.

---

## 4. The demand pipeline, step by step

```
question + subreddits
      │
      ▼
[1] plan brief        brief_from_question (D1-D8) + pick_target_subreddits   (LLM)
      │
      ▼
[2] pull corpus       ArcticReader: HF open-index/arctic Parquet via DuckDB (submissions)
      │
      ▼
[3] triage            embed + 3-bucket (accept / classify / reject) by cosine+BM25 hybrid
      │
      ▼
[4] hydrate           ArcticShiftApiClient: live comment trees for the relevant subset
      │
      ├───────────────┐
      ▼               ▼
[5] synthesize     [5'] web research (parallel)   GroundedChatModel or SearchProvider
   cluster + rank      structured WebFindings
      │               │
      └──────┬────────┘
             ▼
[6] triangulate    cross-stream agreement (agree / silent_web / silent_corpus / disagree)
             │      + QUOTE VERIFICATION: every quote exact-matched to a stored comment,
             │      or it is dropped
             ▼
        DemandReport  (ranked_clusters, each cited; partial+caveat on graceful failure)
```

Orchestration lives in `research/pipeline.py` (`run_research`); dependencies are injected via
`ResearchDeps` (chat, fast_chat, embeddings, corpus, reader, search, comments, sources). Web
research is best-effort (a failure yields a `partial` report with a caveat); synthesis is
required. `run_discovery` (`discovery/service.py`) is the sibling loop for Reddit *engagement*
opportunities (filter → draft → gate), distinct from wedge validation.

**Corpus sources.** Submissions come from the Hugging Face `open-index/arctic` Parquet mirror
(read with DuckDB; `HF_TOKEN` for long windows) or a Supabase Storage mirror
(`ARCTIC_SHIFT_SOURCE=mirror`). Comments come from the live Arctic Shift API. Additional
sources (Hacker News, Product Hunt, web) plug in through `ItemSource`.

---

## 5. Surfaces

- **Library facade** (`client.py`, `Metalworks`): `.research()`, `.positioning()`,
  `.landscape()`, `.assess()`, `.surface()`, `.ux()`, `.site()`, `.render_site()`,
  `.build_spec()`, `.scaffold()`, `.launch()`, `.content_plan()`, plus `.reddit` and
  `.discovery` namespaces and a `.deps` escape hatch. `.research()` returns the `Research`
  bundle; sub-pillars are pure functions over it.
- **CLI** (`cli/`): `metalworks` with sub-apps `research`, `reddit`, `arctic`, `config`,
  `models`, `sources`, `corpus`, `mcp serve`, plus a top-level interactive menu and
  `doctor`. Lazy-imports providers so the CLI starts free of heavy deps.
- **MCP server** (`mcp/`): tiered tools — Tier 1 zero-key (compliance lint, Reddit search,
  Arctic pulls, subreddit intel), Tier 2 key-gated (research + all pillar builders, ideate,
  assess, validate, discovery), Tier 3 gated + confirmed (Reddit posting requires a
  compliance pass + HMAC token + `METALWORKS_ALLOW_POSTING=1`).
- **Claude Code plugin** (`plugin/`): `/demand-report`, `/thread-discovery`, `/reply-draft`
  over the MCP tools.

**Reddit engagement** (`reddit/`) is its own subsystem: OAuth + encrypted tokens, public
search, subreddit intel, inbox, and gated posting. The compliance gate is deterministic
(`heuristic_check`) with an escalating LLM judge for uncertain cases — authentic, disclosed
engagement only.

---

## 6. The honesty + safety model (why you can trust the output)

- **Quote verification:** every `ResolvedCitation.text` is exact-matched to a stored comment;
  unmatched quotes are dropped. A report that reaches the contract is guaranteed real.
- **Breadth over virality:** ranking weights distinct authors, so 50 people each saying it
  once outranks 1 person saying it 200 times.
- **Honest nulls:** no white-space wedge → `positioning.wedge is None`; thin demand → NO_GO;
  grounding unavailable → `partial` + caveat, never a fabricated GO.
- **Embedding-identity guard:** vectors carry `IndexIdentity`; a model/dim mismatch is a hard
  error, never a silent degrade.
- **Posting/charging/prod are gated:** deterministic compliance + confirm token + opt-in env
  flag, the same pattern reused by the deploy/billing capability (§8).

---

## 7. The startup-shapes catalog (new)

The newest layer turns "build a product from the demand" from bespoke into **reusable**. A
*shape* is a reference architecture for a class of product, in two layers.

### The model

```
LAYER 1 — 6 BASE STACKS (the reusable backend a CC terminal builds from)
  store · match · synthesize · automate · generate · watch
        (dominant verb: store / match a market / synthesize intelligence /
         automate across systems / generate artifacts / watch and alert)

LAYER 2 — ~5 COMPOSABLE MODULES
  payments · feed · threads · progress · paywall

= ~25 NAMED PRODUCT SHAPES (base + modules + a thin domain skin)
  e.g. submission-portal (store), goods-marketplace (match),
       demand-intelligence (synthesize — this is Clique), price-monitor (watch),
       invoicing (store+payments), community (match+feed)
```

The point: you build **6 backends + 5 snap-ons**, and the catalog *feels* like ~25
recognizable products. Each base ships with a `scaffold_target` pointer — a stable string a
Claude Code terminal resolves to a starter and builds against. metalworks carries only the
pointer (spec, don't vendor).

### The contract (`contract/shape.py`)

- `Module` — `id: ModuleId`, `adds`, `requires`
- `BaseStack` — `id: BaseStackId`, `verb`, `backend_capabilities`, `default_modules`,
  `scaffold_target`
- `ProductShape` — `name`, `base_stack`, `modules`, `domain_skin`, `match_signature`
- `MatchSignature` — the structured predicate scored against a report: `cluster_keywords`
  (vs `InsightCluster.claim`), `surface` (vs `SurfaceRecommendation`), `build_signals`
  (vs `BuildSpec.features[].title`), `min_signal` (the breadth floor)
- `ShapeMatch` — `shape`, resolved `base_stack`, `score` (0-1), `rationale`,
  `evidence_refs` (cluster refs, so a match is itself cited)

### The catalog (`shapes/catalog/`)

An auto-discovered package: each base owns `catalog/<base>.py` that self-registers its
`BaseStack` + `ProductShape`s on import; `catalog/__init__.py` imports every submodule via
`pkgutil`, so new shapes drop in without editing a shared list. (`shapes/__init__.py` holds
the `BASE_STACKS` / `SHAPES` registries + `register_*` / `get_*`.)

### The matcher (`shapes/matcher.py`)

```
research.assessment.decision ?
  NO_GO  -> []                      (the corpus vetoed every shape)
  PIVOT  -> score only the pivot fork's clusters
  None   -> score all clusters (demand-only, reduced confidence)
  GO     -> score all clusters
      │
      ▼  for each registered ProductShape:
  gate clusters by MatchSignature.min_signal (breadth floor)
  relevance = max sim(signature.cluster_keywords, cluster.claim)
              + surface-match bonus + build-signal bonus
  drop below min_score
      │
      ▼
  ranked list[ShapeMatch], each cited to the clusters that drove it
```

`ShapeMatcher.match(research, *, surface=None, build_spec=None, min_score=0.5)` is **pure,
read-only over the report, and verdict-reactive** (it reads `Assessment.decision` but never
mutates the report or touches the gates). Scoring is **embedding-similarity** when an
`EmbeddingProvider` is supplied (reuses the engine's embedding infra), with a deterministic
**keyword-coverage fallback** otherwise — so it runs on a bare install and is fully
offline-testable.

### How a product gets built from a shape

```
DemandReport ──▶ assess() ──▶ ShapeMatcher.match() ──▶ top ShapeMatch
                                                          │
              .base_stack.scaffold_target + .shape.modules │
                                                          ▼
                                   a Claude Code terminal builds + runs the product
```

This is the whole "stop building from scratch" win, and it stays honest: a NO_GO report
yields no match, so a shape can be falsified by the evidence.

---

## 8. End-to-end: idea → live, paid product

```
"is there demand for X?"
   │  research            DemandReport (cited)
   ▼
 assess()                 GO / PIVOT / NO_GO        ── NO_GO ─▶ stop
   │ GO
   ▼
 match_shapes()           top ProductShape + BaseStack
   │
   ▼
 CC terminal builds       real backend from scaffold_target + the BuildSpec
   │
   ▼
 deploy + bill            metalworks deploy (Vercel) + metalworks billing (Stripe)   [in PR]
   │                      pure subscription-gate + webhook mapper, test-mode by default
   ▼
 launch reply             a disclosed, non-salesy Reddit reply to the originating thread
```

Two in-flight additions extend the engine (separate branches, not yet merged to `main`):

- **deploy + billing** (`Lab2A/metalworks` PR #51): `metalworks deploy` (render the marketing
  site → Vercel) and `metalworks billing create` (cited `pricing_tiers` → Stripe product +
  payment link). New `DeployProvider` / `BillingProvider` protocols mirroring the llm/search
  adapters; pure subscription-gate + webhook mapper a downstream app imports; irreversible
  steps gated like Reddit posting.
- **startup shapes** (`feat/startup-shapes`, §7): the 6-base catalog + matcher.

---

## 9. The Clique relationship

`Clique-Labs/metalworks` is a separate, private Next.js **factory** that builds and hosts
micro-SaaS products. It consumes this OSS engine as its demand brain (a pip dependency; the
adapter maps the OSS arc → its `WedgeSpec`). The engine specs; the factory (and any Claude
Code terminal) builds. Clique itself is the reference implementation of the `synthesize`
base stack (external-data ingestion → LLM synthesis → cited evidence → dashboard).

---

## 10. Packaging, distribution, testing

- **Install:** `pip install "metalworks[<provider>,research]"` + one env key. Extras pull
  provider SDKs / DuckDB / redditwarp / supabase / mcp behind `[...]`; core stays lean
  (pydantic, httpx, typer, rich).
- **Distribution:** PyPI, the `metalworks` CLI, the MCP server, the Claude Code plugin.
- **Quality bars:** pyright strict on `src/`, ruff, pytest run offline by default
  (`--disable-socket`; network tests gated behind `-m network`). `metalworks.testing` ships
  conformance suites for custom adapters/backends.
- **Honesty in tests:** the demand pipeline's guarantees (exact-quote match, breadth
  weighting, deterministic verdict) are CI-tested, not aspirational.

---

## Appendix — module map

```
src/metalworks/
  client.py            Metalworks facade + lazy dependency resolver
  config.py            provider auto-resolution, non-secret config
  errors.py            MetalworksError, MissingExtraError, MissingKeyError, ...
  contract/            the stable Pydantic API (research, positioning, landscape,
                       surface, build, assess, site, marketing, bundle, evidence, shape, ...)
  research/            pipeline.py, deps.py, planner/, exploration/, synthesis/,
                       triangulate/, sources/ (arctic, hackernews, producthunt, web), site.py
  discovery/           run_discovery (engagement opportunities)
  reddit/              oauth, search, subreddit intel, inbox, compliance, posting
  llm/                 ChatModel protocol + adapters (anthropic/openai/google) + fallback + fake
  embeddings/          EmbeddingProvider + adapters + FakeEmbedding + IndexIdentity guard
  search/              SearchProvider + adapters (exa/tavily/parallel/firecrawl)
  stores/              repo protocols + memory/sqlite/file backends + token crypto
  shapes/              startup-shape catalog: contract via contract/shape.py, registry
                       (__init__), catalog/<base>.py (auto-discovered), matcher.py
  build/               BuildSpec assembly + scaffold harness
  cli/                 the metalworks CLI
  mcp/                 FastMCP server + tiered tools + jobs
  testing/             conformance suites + fakes
  project.py           .metalworks/ project detection + run persistence
```
