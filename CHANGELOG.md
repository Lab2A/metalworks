# Changelog

All notable changes to metalworks are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it
reaches 1.0. Below 1.0, anything outside `metalworks.contract` and the MCP tool
contracts may change in any release.

## [Unreleased]

## [0.3.1] - 2026-06-25

### Fixed
- **Reasoning-model hang at the triage stage.** A demand run on a reasoning model (e.g.
  `deepseek-v4-flash` via OpenRouter) could hang for 10+ minutes and then fail, because the
  OpenAI/compatible adapter made a single **non-streaming** call whose one timeout had to cover the
  model's entire hidden-reasoning phase *plus* the output — a model that thinks longer than the
  budget timed out mid-reasoning, before any output existed. Three changes fix it:
  - **Streamed the OpenAI/compatible path.** `complete_text` and the native `json_schema`
    `complete_structured` path now call `chat.completions.create(..., stream=True,
    stream_options={"include_usage": True})`, accumulate the delta chunks, and capture token usage
    from the final usage chunk (output and observability hook unchanged). The per-call timeout is now
    an `httpx.Timeout(connect=15, read=timeout_s, write=15, pool=15)` — a **read (gap-between-chunks)**
    budget, not a total — so a model that is slow to the first token or trickles tokens completes as
    long as no single gap exceeds the budget, while a genuinely stalled stream still fails cleanly.
  - **`max_retries=0` on the OpenAI and Anthropic clients.** The provider SDKs default to 2 internal
    retries and treat a timeout as retryable, silently stacking the budget up to 3× and re-running the
    hidden-reasoning phase from scratch. With them off, metalworks' `timeout_s` is the single honest
    budget and the shared `with_backoff` stays the sole retry (rate-limits only).
  - **Configurable, reasoning-safe default timeout.** New `config.llm_timeout_s()` resolver
    (`METALWORKS_LLM_TIMEOUT` env → `llm_timeout` config → **300s**, up from 120s). The chat adapter
    methods now default `timeout_s` to `None` and resolve this lazily, so the knob flows through every
    surface (CLI, MCP, SDK); grounding keeps a higher 300s floor.

  **Deferred (follow-up):** Anthropic and Google still use **non-streaming** calls — they received the
  higher configurable timeout (and Anthropic also `max_retries=0`), but were not converted to
  streaming in this release. The google-genai client does not cleanly expose a no-retry setting, so
  `max_retries=0` was not applied there. The reported bug is the OpenAI/OpenRouter path, which is now
  streamed.

## [0.3.0] - 2026-06-25

### Added
- **Research-job progress heartbeat.** A background `research_start` job now re-saves its
  `RunSummary` on every pipeline stage, so `research_status` reports fine-grained progress —
  `stage` (e.g. `analyzing`), `stage_index`/`stage_total` (for a `4/6` display), and `updated_at` —
  letting a poller tell a grinding run from a hung one. Four new defaulted `RunSummary` fields
  (`stage`, `stage_index`, `stage_total`, `updated_at`); old payloads still validate. The CLI gains
  `metalworks research status <run_id>` to surface them.
- **Resume a failed research run from its last checkpoint.** The pipeline now checkpoints each
  stage's output keyed by `run_id` (a new `CheckpointRepo` on both the memory + sqlite stores, with
  an explicit typed Pydantic serializer per stage — never pickle), so a failed run can re-run from
  the last incomplete stage instead of from zero — reusing the expensive Reddit pull, comment
  hydration, and synthesis. The non-determinism (subreddit / source pick) is captured in a `planning`
  checkpoint BEFORE the pull, so a resume reuses the exact same corpus plan. New `research_resume`
  primitive across all four surfaces: MCP tool (`research_resume`), CLI (`metalworks research resume
  <run_id>`), facade (`Metalworks.research_resume(run_id)`), and the `demand-report` skill (which now
  resumes a `failed` run before falling back). A fresh run with no checkpoint store is byte-for-byte
  unchanged — the checkpoint-or-compute wrapper is a transparent pass-through.

### Changed
- **Plugin docs + directive skill preambles.** Bundle a concise agent-facing
  `docs/operating-metalworks.md` (provider/model resolution + the Vertex gotcha, the readers/sources
  and `ARCTIC_SHIFT_SOURCE`, the async run loop, a common-errors table). All 22 skill preambles now
  carry a directive "STOP and read the reference before opening `src/`" plus a poll-with-Monitor /
  never-blind-`sleep` note — so an agent reads the docs instead of reverse-engineering the source.
  `metalworks init`'s `.env.example` documents `METALWORKS_MODEL`, the `GOOGLE_GENAI_USE_VERTEXAI`
  gotcha, and `ARCTIC_SHIFT_SOURCE`; `init` now points at `metalworks preflight`.

## [0.2.1] - 2026-06-25

### Fixed
- **The MCP research pipeline now uses the live Arctic Shift reader by default** (0.1.1's
  live-reader default never reached it). `mcp/tools.py` hardcoded `ArcticReader(probe_sleep_s=0.0)`
  (the HF Parquet mirror) at four sites — `_build_deps`, `research_plan_brief`, `arctic_list_months`,
  `arctic_pull_threads` — so MCP runs (the plugin surface) pulled posts from Hugging Face and **429'd**
  while `preflight` (which calls the resolver) reported `active_reader: arctic_shift_api`. All four now
  call `config.resolve_corpus_reader()`, so the live API is the default on the MCP surface too and
  `preflight` no longer disagrees with what the pipeline does.
- **A config `model` that is a routable ref now works on its own.** Setting
  `model = "deepseek/deepseek-v4-flash"` in `metalworks.toml` **without** also pinning `provider` was
  silently ignored for provider routing — resolution fell through to key-order/Vertex autodetection
  (so a machine with stray `GOOGLE_GENAI_USE_VERTEXAI` resolved Google instead). A config `model`
  carrying a vendor namespace (`deepseek/...`, `openai:...`) now routes on its own, before
  autodetection. A pinned `provider`+`model` is unchanged; a bare model id (no namespace) still can't
  self-route.

### Added
- **`preflight`/`doctor` now flag the Vertex-without-the-extra landmine** (error severity): when
  `GOOGLE_GENAI_USE_VERTEXAI` is on but `google.genai` isn't installed, chat→Vertex and embeddings
  (`resolve_embeddings` checks Vertex first) both fail on the missing SDK — even with an OpenRouter key
  set. The hint says to set `METALWORKS_MODEL` + `GOOGLE_GENAI_USE_VERTEXAI=false`, or
  `pip install "metalworks[google]"`. This is the exact first-run failure the preamble exists to catch.

## [0.2.0] - 2026-06-25

### Added
- **Proactive preflight + the skill preamble.** A new `preflight` primitive surfaces "is
  everything set up + is there an update" **before** the work runs, instead of failing midway.
  It is doctor's machine-readable twin (`PreflightReport`) and reports the active corpus reader
  (`arctic_shift_api` | `hf_parquet` | `supabase_mirror`), resolved chat/embedding models,
  installed extras, present keys, and actionable setup issues. Available on all four surfaces:
  `metalworks preflight` (with `--json`), `Metalworks.preflight()`, the `preflight` MCP tool
  (Tier 1, zero-key, offline-safe), and a shared **"## Preamble (run first)"** block added to all
  22 plugin skills so the agent runs preflight first. `PreflightReport` / `PreflightIssue` /
  `UpdateStatus` are new `metalworks.contract` models (additive — old payloads still validate).
- **PyPI update check.** A cached, offline-safe check (`metalworks._update_check`) compares the
  installed version against the latest on PyPI. Cached once-daily in `~/.metalworks/`, disable-able
  via the `update_check = false` config setting, snooze-able, and **silent on any failure** (`httpx`
  is lazy-imported inside the fetch only — `import metalworks` stays network-free). doctor and the
  banner show an "update available" line when one exists.
- **Proactive preflight banner.** Heavy research / build / distribution commands print a one-line
  stderr banner before doing work — **silent when healthy**, otherwise e.g.
  `metalworks: 2 setup issue(s) · update 0.1.1->0.2.0 available — run 'metalworks doctor'`. It is
  cached (the update-check cache + cheap local probes), session-once (a `~/.metalworks/` timestamp
  guard), gated by the `preflight_banner` config setting (default on), and **non-blocking** — it
  never changes an exit code or stops a command. The MCP stdio server prints the same one-line
  status to **stderr** at startup (stdout stays the clean protocol channel).

### Changed
- **`doctor` now renders from `preflight()`** — a single source of truth. The pure check helpers
  (extras / keys / resolved-models / renderer / corpus-reader / hints) moved into
  `metalworks.preflight`; both `doctor` and `preflight()` call the same code, so they can never
  drift. doctor keeps `--fix` and stays a pretty-printing superset, and now also reports the active
  corpus reader and an "update available" line.

## [0.1.1] - 2026-06-25

### Changed
- **Live Reddit submissions are now the DEFAULT corpus reader.** Submissions previously came
  from the Hugging Face `open-index/arctic` Parquet mirror (`ArcticReader`, `[arctic]` extra,
  DuckDB) — stale, slow, and prone to anonymous HTTP 429s on a first run. They now come from the
  **live Arctic Shift posts API** (`ArcticShiftReader`, `/posts/search` + `/posts/ids`) using only
  core `httpx` — no extra, current month included, no HF rate limits. Comments already came from
  the same live API. New `config.resolve_corpus_reader()` resolves the reader from
  `ARCTIC_SHIFT_SOURCE`: unset/`api` → live (default); `hf` (aliases `parquet`/`arctic`) → the HF
  Parquet mirror; `mirror` → the Supabase mirror (`ArcticMirrorReader`, `[supabase]`). The library
  facade and every CLI research/build/distribution command resolve through it, so a keyless,
  extra-less install pulls real submissions immediately. (`ArcticShiftApiClient` gains
  `search_submissions` / `submissions_by_ids`.)

### Added
- **`--model` / `-m` override on `research run` and `research ideate`, plus the `METALWORKS_MODEL`
  env var.** Pick a chat model per-invocation without editing config: `--model
  deepseek/deepseek-v4-flash` routes via OpenRouter (an unknown vendor namespace → OpenRouter),
  `--model openai/gpt-5` goes native. `METALWORKS_MODEL` applies the same override to **every**
  surface — CLI, MCP server, and the SDK — and beats config/key-order autodetection (so stray
  `VERTEX_*`/`GOOGLE_APPLICATION_CREDENTIALS` env no longer hijacks provider selection on a machine
  that also has an OpenRouter key).

### Fixed
- **`ArcticReader` now reads `HF_TOKEN` (or `HUGGING_FACE_HUB_TOKEN` / `HUGGINGFACE_HUB_TOKEN`)
  from the environment.** An opt-in HF run (`ARCTIC_SHIFT_SOURCE=hf`) previously 429'd against the
  public mirror because the CLI never threaded a token to the reader.
- **Provider-resolution failures now teach the escape hatch.** When no chat provider resolves, the
  CLI prints a tip to pass `--model PROVIDER/MODEL` (e.g. `deepseek/deepseek-v4-flash` with
  `OPENROUTER_API_KEY`) instead of only a bare key list.

## [0.1.0] - 2026-06-24

### Changed
- **Sources — sources-by-idea as the default (#167).** The ultra-wide corpus was invisible on the
  first run (reddit-only default; the selector was opt-in). Two changes make the brief pick its
  sources by default. **(1) A CUT in the selection path.** `planner.select_sources` (the default
  path) was append-only — the LLM ranked the reachable set but never dropped, so a pick returned ALL
  reachable sources reordered (9 keyless sources every run, including clearly-irrelevant ats/wordpress
  for an espresso brief). It now **cuts**: the model SELECTS the few sources worth pulling for the
  brief (typically 2–5), an omitted source is *respected as not-relevant* (no re-append), the
  non-removable `reddit` floor is always kept, and the pick is capped at 6 (`SELECT_CAP`). The
  append-only `planner.pick_sources` full rank is unchanged for callers that want the whole reachable
  corpus prioritized. **(2) `[sources].select` default flips ON** (`config.source_selector_enabled`):
  a run with no explicit `[sources].enabled` / `--source` selects by idea. **Precedence unchanged** —
  explicit override > selector > `reddit` floor; an explicit source list still wins. **Blast-radius
  guard:** when there is no chat model, or the selection call fails / returns nothing usable, the cut
  degrades to the `reddit` floor (just `reddit`), NOT the all-reachable set — so an offline /
  model-less run is deterministic reddit-only, exactly the old default. No contract change (the
  surfaced `SourceSelection` shape is unchanged); the verdict band is untouched (selection is
  discovery/corpus-construction, like subreddit picking — the verdict still scores deterministically).
  A `network`-marked selector-quality eval over representative briefs (espresso→reddit/forums, dev
  tool→reddit+stackexchange, wordpress-plugin→wordpress) asserts relevant-in / irrelevant-cut.

### Added
- **Sources — source-mix disclosure on clusters (#164 step 1).** Going ultra-wide let a cluster fuse
  quotes from many source types (Reddit + a job posting + a review + an RFP); cite-or-die proves each
  quote is real, not that the cluster is *coherent*. New **additive** contract field
  `InsightCluster.source_mix: dict[str, int]` — source_id → count of the cluster's **members** from
  that source, computed in `cluster_ranker._build_cluster` over **all** members (not just the 2-3
  surfaced quotes), so it reflects true composition. A Reddit-only cluster is `{"reddit": N}`. A
  derived `@computed_field cross_source: bool` flags a theme as suspiciously cross-source when it
  draws from ≥ 2 sources **and** no single source supplies ≥ 60% (`CROSS_SOURCE_DOMINANCE`) of the
  members. Deterministic (pure computation from `member.source`, no LLM). **Disclosure only** — it
  never feeds `demand_score` or the verdict band (which stay breadth-only; guarded by test). Surfaced
  lightly in the run-summary markdown (`runs.py`) as a `_sources: …_` line with a ⚠ on cross-source
  clusters. Defaulted/empty so old payloads validate; TS + JSON-Schema regenerated. Steps 2
  (coherence verify-pass) and 3 (same-source-purity weighting) remain out of scope.
- **Sources P4.2 — Parallel Task discovery adapter (#157).** New
  `metalworks.research.discovery.parallel.ParallelTaskDiscovery` — the second **agentic**
  `DiscoveryProvider` (`agentic=True`, `provider_id="parallel_task"`), over Parallel's
  [Task API](https://docs.parallel.ai) managed deep-research engine. `discover` runs a Task
  (`POST /v1/tasks/runs` → `GET /v1/tasks/runs/{id}/result` over `httpx`, mirroring the single-shot
  `search.adapters.parallel` REST shape) and consumes **only the Basis citations + excerpts** — each
  cited `output.basis[].citations[].excerpts[]` entry maps to one cite-or-die `DiscoveryFinding`
  (`quote` = the excerpt **verbatim**, `source_url` = citation url, `title`, `extra={"confidence",
  "domain"}`). Parallel's synthesized `output.content` prose is **never** ingested — cite-or-die,
  asserted against a recorded response. The `DiscoveryBudget` maps to a Parallel **processor** tier,
  defaulting to the cheapest deep-research tier **`lite`** (≈ $5 / 1k task runs; deeper tiers out of
  scope); `max_findings`/`max_domains` cap kept excerpts / distinct hosts deterministically.
  `extra["confidence"]` is carried for provenance only and does **not** feed the verdict band. Auth
  `PARALLEL_API_KEY`; SDK lazy-imported behind the `parallel` extra (bare matrix stays green).
  `config.resolve_discovery()` returns it when `PARALLEL_API_KEY` is set — tripping the chassis gate
  so the homegrown loop is OFF and `web_research` delegates to it. Offline tests
  (`tests/test_discovery_parallel.py`, `httpx.MockTransport` over a recorded Basis response) plus a
  `network`-marked live smoke. Internal-only (no `contract` change, no TS regen).
- **Sources P4.1 — Exa Research discovery adapter (#156).** New
  `metalworks.research.discovery.exa.ExaResearchDiscovery` — the first **agentic** `DiscoveryProvider`
  (`agentic=True`, `provider_id="exa_research"`) over Exa's **Research/Deep** endpoint. `discover`
  submits a research task, waits for Exa's own iterate-and-dig loop, and maps each **field-level
  citation** (verbatim Highlights/excerpt + its source URL) to a `DiscoveryFinding`
  (`quote`=excerpt verbatim, `source_url`=citation URL, `title`, `extra={"domain": ...}`), deduped by
  URL and capped by the deterministic `DiscoveryBudget`. **Cite-or-die:** Exa's synthesized
  answer/summary prose (`output.content`) is **never** ingested — only the cited excerpts become
  findings, so the deterministic scorer downstream runs on real quotes. Auth `EXA_API_KEY`; the
  exa-py SDK is lazy-imported behind the `exa` extra (`import metalworks` stays free; the bare matrix
  is green without the extra). `config.resolve_discovery()` now returns it when `EXA_API_KEY` is set,
  which trips the capability-ladder gate in `web_research` (homegrown loop stays OFF; metalworks
  delegates discovery to Exa). Keyless/unconfigured → not selected, no crash. Internal-only types (no
  `contract` change, no TS regen). Offline + `network`-marked tests in `tests/test_discovery_exa.py`.
- **Sources P4.0 — agentic discovery chassis (#155).** New
  `metalworks.research.discovery` package: a `DiscoveryProvider` Protocol (`provider_id`, `agentic`,
  `discover(*, question, directions, budget)`), the cite-or-die unit `DiscoveryFinding` (verbatim
  `quote` + `source_url` + `title` + optional `author`/`extra`), a `DiscoveryBudget`
  (`max_rounds`/`max_findings`/`max_domains`), a registry (`register_discovery` / `get_discovery`),
  and `HomegrownDiscovery` — metalworks' own **iterate-and-dig loop** over the existing single-shot
  `SearchProvider.search`. Round 1 searches the brief's queries (`[question, *directions]`); each
  subsequent round an LLM **proposes** follow-up queries from what surfaced (deduped vs run queries),
  with new hits deduped by URL, stopping on the deterministic budget or a no-new-findings round. The
  follow-up-query LLM call is discovery/corpus-construction, **not** the verdict (same allowance as
  `pick_target_subreddits`); the budget is a pure stop condition — the LLM only proposes queries.
  `config.resolve_discovery()` mirrors `resolve_search` (returns `None` until the keyed agentic
  adapters — Exa Research P4.1, Parallel Task P4.2 — land). **The capability-ladder gate** is wired
  into `web_research`: if an **agentic** `DiscoveryProvider` is configured → delegate to its
  `discover` (homegrown loop OFF); else if a `SearchProvider` exists → run `HomegrownDiscovery`; else
  → today's single-pass `_external_search`, **byte-identical**. All three rungs map findings onto the
  same corpus spine (`WebFinding`) with the verbatim quote as the anchor — never a synthesized
  summary (cite-or-die preserved). `ResearchDeps` gains an injectable `discovery` seam. Internal-only
  types (no `contract` change, no TS regen). Offline tests in `tests/test_research_discovery.py`.
- **Sources P3 — GitHub Issues connector (#149).** New
  `metalworks.research.sources.github.GitHubItemSource` — a Phase-3 grounding singleton, a
  keyless-with-optional-token `ItemSource` over the GitHub REST API. GitHub Issues capture a demand
  modality nothing else reaches: **feature requests and bug reports filed against shipping products**
  ("plugin X doesn't support SSO", 340 👍) from the developers and buyers of dev tooling. `pull` runs
  the brief's terms through `GET /search/issues` (`advanced_search=true`, scoped `type:issue` over a
  `created:<start>..<end>` window) and maps each issue to a `CorpusRecord` (title, body, `html_url`,
  author login pseudonymized); `comments_for` fetches each issue's
  `/repos/{owner}/{repo}/issues/{n}/comments` thread → `CorpusComment` (body + per-comment permalink +
  author), addressing recovered from the search hit's `repository_url` + `number`. A **new
  `reactions` signal kind** is registered `is_magnitude=True` in
  `metalworks.research.synthesis.signals` (the 👍/`+1` count = absolute endorsement volume; it lifts
  ranking, never the verdict band). Because GitHub has a real comment layer it is **not**
  `yields_units`, so per the rule-5 sweep the grounding lane also declares the non-magnitude
  `engagement` (the issue's comment count) — each record emits
  `{"reactions": <+1 count>, "engagement": <comment count>}` and `signals=("reactions", "engagement")`.
  Auth mirrors Stack Exchange's optional-key pattern: `auth="key"`, `access="open"` (keyless works at
  60/hr), `env=("GITHUB_TOKEN",)`; the token is sent as an `Authorization: Bearer` header **only when
  present** (keyless leaks no token — asserted). `targeting="keyword"`. Registered via the single
  `BUILTIN_SOURCE_MODULES` map (#139); `docs/sources.md` regenerated. New `tests/test_source_github.py`
  (offline stub-client unit tests for search→issue→record, comments→quotes, ghost-author tombstone,
  empty-comment drop, `reactions` registered + ranking lift, keyless-leaks-no-token, query/window
  shape, `check_item_source` conformance, registry resolution, plus a `network`-marked live smoke).
  GraphQL Discussions and per-repo deep crawl left out of scope per the issue.
- **Sources P3 — WordPress plugin reviews connector (#150).** New
  `metalworks.research.sources.wordpress.WordPressSource` — a keyless `ItemSource` over the
  WordPress.org plugin directory, a Phase-3 grounding singleton (the review/marketplace shape). The
  WordPress.org directory is the one marketplace that is fully open AND carries both quotable reviews
  and a deployment magnitude: it reaches site admins / agencies / freelancers (the SMB long-tail B2B
  layer Reddit/HN underweight). A review maps like a comment — the plugin is the record, each review
  is the quote-bearing sub-item. `pull` runs the brief's terms as the `request[search]` plugin search
  (`https://api.wordpress.org/plugins/info/1.2/?action=query_plugins`) and maps each plugin to a
  `CorpusRecord` (name, short description, plugin page url), emitting `{"installs": active_installs}`
  — the deployment magnitude — on the plugin record (OMITTED, never `0.0`, when absent). `comments_for`
  fetches each plugin's public reviews feed (`wordpress.org/support/plugin/<slug>/reviews/feed/`, RSS)
  and maps each review to a `CorpusComment` (verbatim review text + per-review permalink + reviewer
  handle pseudonymized), emitting `{"rating": stars}` per review — the registered polarity-capable
  kind (carried/ranked, not yet band-affecting). Both `installs` (magnitude) and `rating` (polarity)
  are already registered in `synthesis.signals` (no new `register_signal`); the verdict band is
  untouched. Auth is keyless: `auth="none"`, `access="open"`; `targeting="keyword"` (the brief's terms
  drive the search), picked by the `keyword` target picker. Registered via the single
  `BUILTIN_SOURCE_MODULES` map (#139); `docs/sources.md` regenerated. New `tests/test_source_wordpress.py`
  (offline stub-client unit tests for search→plugin→installs, reviews→quotes→rating, empty-review drop,
  blank-author collapse, installs lifts ranking, `check_item_source` conformance, registry resolution,
  plus a `network`-marked live smoke); added to the 0.5 conformance sweep.
- **Sources P3 — SAM.gov procurement connector (#148).** New
  `metalworks.research.sources.samgov.SamGovItemSource` — the marquee Phase-3 grounding singleton, a
  `yields_units` `ItemSource` over the SAM.gov Opportunities API
  (`https://api.sam.gov/opportunities/v2/search`). Public procurement is the one B2B layer nothing
  else reaches: government buyers post explicit unmet needs **with a dollar value and a deadline
  attached, named** (the contracting agency). `pull` runs the brief's terms as the `title` keyword
  search over the posted-date window (`postedFrom`/`postedTo`, `MM/dd/yyyy`, one-year cap) and maps
  each notice to a self-representing `CorpusRecord` (title + solicitation summary; `uiLink`
  permalink; contracting agency `fullParentPathName` as the "author"); `yields_units=True` so the
  ranker measures breadth by distinct agency/domain, and `comments_for` returns `None`. A notice
  carrying an award attaches `{"rfp_budget": <amount>}` — the literal willingness-to-pay magnitude,
  already registered `is_magnitude=True` (no new `register_signal`) — and **OMITS** it (never `0.0`)
  when absent. Auth is a free, registered key (`SAM_GOV_API_KEY`): `auth="key"`, `access="free_key"`,
  passed when present; the selector's access gate skips it cleanly when unset. As a `yields_units`
  grounding source it is rule-5 exempt (its only signal is the magnitude `rfp_budget`). Registered
  via the single `BUILTIN_SOURCE_MODULES` map (#139); `docs/sources.md` regenerated. New
  `tests/test_source_samgov.py` (offline stub-client unit tests for search→notice→unit, agency as
  author, `rfp_budget` attached / omitted-not-zero, keyword+window+key request shape, unkeyed-skip,
  `check_item_source` conformance, registry resolution, plus a `network`-marked live smoke).
  USAspending award-$ overlay left as a docstring TODO (a lane-② `MagnitudeProvider`, not part of the
  grounding deliverable); EU TED is a fast-follow on this shape.
- **Sources P2 — Wikipedia pageviews magnitude provider (#144).** New
  `metalworks.research.sources.magnitude_wikipedia.WikipediaPageviewsProvider` — a keyless lane-②
  magnitude provider over the Wikimedia REST pageviews API
  (`wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/<title>/monthly/<start>/<end>`).
  Where npm/PyPI give *dev-demand* volume, Wikipedia pageviews give a **broad, domain-neutral
  interest-magnitude** denominator — how many people look something up. Each entity is treated
  directly as an English-Wikipedia article title (spaces → underscores, URL-encoded); `measure`
  sums the window's monthly views → `{entity: {"pageviews": <total>}}`. An entity with no article
  (404) is OMITTED — omission is unknown, never `0.0`. The descriptive `User-Agent` Wikimedia
  requires is set on the owned client. `provider_id="wikipedia"`, `signals=("pageviews",)`,
  `auth="none"`; registered via `register_magnitude` + the `get_magnitude_provider._BUILTIN_MODULES`
  lazy map. The `pageviews` signal kind was already `is_magnitude=True` (no new `register_signal`).
  Title disambiguation / fuzzy search and non-en wikis are out of scope (kept deterministic).
- **Sources P2 — PyPI downloads magnitude provider (#143).** New
  `metalworks.research.sources.magnitude_pypi.PyPIDownloadsProvider` — the second worked **free**
  lane-② magnitude provider after npm. `measure` maps each entity that looks like a PyPI package
  name to its last-month download count via the keyless pypistats.org `recent` endpoint
  (`GET pypistats.org/api/packages/<pkg>/recent`, normalizing to the PEP 503 form), emitting the
  `downloads` kind already registered `is_magnitude=True` — no new `register_signal`. A package
  pypistats has no data for (404 / null `last_month`) is **omitted** (unknown, never `0.0` — the
  #122 contract); non-package handles (free text, path/URL shapes) are skipped outright. Registers
  at module scope via `register_magnitude("pypi", …)` with a `MagnitudeSpec(provider_id="pypi",
  signals=("downloads",), auth="none")`, and adds `"pypi"` to `get_magnitude_provider`'s lazy
  `_BUILTIN_MODULES` map. Magnitude providers are not connectors, so the #139 source module-lists
  and the source catalog (`docs/sources.md`) are untouched. New `tests/test_source_magnitude_pypi.py`
  (offline stub-client unit tests for measure → downloads, 404 omission, non-package skipping +
  name normalization, `check_magnitude_provider` conformance, registry resolution, plus a
  `network`-marked live smoke). The homegrown loop is **opt-in** (`[sources].discover = true`, mirroring the #123 selector): with it unset a configured single-shot SearchProvider keeps driving the legacy single-pass path — no extra LLM rounds, default cost unchanged; an agentic provider always delegates regardless.

- **Consolidated built-in connector registration into one list (#139).** A new source was
  registered in four scattered places (`get_source` lazy map, the selector's spec-import, the
  catalog generator, the CLI's own discovery) — miss one (the CLI's was the easy miss) and
  `sources list` silently omitted it. All four now derive from a single `BUILTIN_SOURCE_MODULES`
  map in `research.sources` via `builtin_connector_modules()` / `builtin_source_ids()`; a guard
  test fails CI if a built-in id half-registers. No behavior change (catalog byte-identical).

- **Sources P1 — ATS connector (Greenhouse/Lever/Ashby) (#136).** New
  `metalworks.research.sources.ats.ATSItemSource` — one keyless `ItemSource` over the three public
  ATS job boards (Greenhouse `boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true`, Lever
  `api.lever.co/v0/postings/<slug>?mode=json`, Ashby `api.ashbyhq.com/posting-api/job-board/<slug>`),
  parameterized by `provider` + a company `slug`. Public ATS boards are a B2B **pain & spend proxy**
  nothing else in the corpus reaches: a company hiring for a tool/skill states the explicit need in
  the job description. `pull` fetches a board, filters its postings to the brief's terms, and maps
  each to a self-representing `CorpusRecord` (title = role, text = JD, url = posting permalink,
  company = the "author"). The JD IS the synthesis unit, so this is a `yields_units` **grounding**
  source (`comments_for` returns `None`): it ranks by distinct company/domain breadth, like the web
  lane, and declares **no per-record signal** (`signals=()`) — a JD has no upvote/view analogue, and
  the demand magnitude here is posting frequency, a deferred cluster-level overlay we never
  fabricate per-item. There is no "list all companies" endpoint, so the `slug` target picker
  (`planner/source_picker.py`) reads a **curated** slug registry seeded as DATA
  (`ats.CURATED_SLUGS`) and lets a brief name companies; full slug-discovery is a later concern
  (stated in the module docstring). Auth is keyless (`auth="none"`, `access="open"`). Registered in
  `SOURCE_SPECS`, the lazy `get_source` map, the CLI/catalog connector lists, and `_BUILTIN_IDS`;
  `docs/sources.md` regenerated. The 0.5 conformance sweep's rule 5 (a grounding lane must declare a
  non-magnitude signal) now exempts `yields_units` sources for the same reason it exempts the web
  lane — they rank by domain breadth, not a signal vector — so an empty `signals` is legal. New
  `tests/test_source_ats.py` (offline stub-client unit tests for each provider's board→postings→units
  mapping, term/window filtering, `yields_units` + domain breadth, conformance + registry, plus a
  `network`-marked live Greenhouse smoke).
- **Sources P1 — Discourse connector (#135).** The highest *venues-per-build* Phase-1 connector: one
  adapter over the public Discourse JSON API unlocks the long tail of branded community forums (every
  `community.X.com`, `meta.*`, vendor/dev/vertical board) that all run the same software and expose the
  same keyless API. New `metalworks.research.sources.discourse.DiscourseSource` — an `ItemSource`
  parameterized by `instance` (the forum host, default `meta.discourse.org`): `pull` queries
  `/search.json` (windowed in-query with Discourse's `after:`/`before:` date operators) → topics →
  `CorpusRecord` (title + search blurb); `comments_for` reads `/t/<id>.json`'s `post_stream` → each post
  → `CorpusComment` (cooked HTML → text, a per-post permalink `/t/<slug>/<id>/<post_number>`, a
  pseudonymized `username`). Signals `{"upvotes": like_count}` (social, the Discourse "like") plus
  `{"views": topic_views}` (magnitude) — both kinds already registered, so no new `register_signal`.
  Auth is keyless (`auth="none"`, `access="open"`); a login-gated host that answers 403/redirect is
  **skipped gracefully** (the pull yields nothing rather than crashing the run). The shared `instance`
  target picker (`planner/source_picker.py`) gains a `discourse_instances` seed — a curated list of
  well-known public forums (non-removable `meta.discourse.org` default) plus brief-named hosts,
  normalized and append-only — until web-lane host discovery lands (Phase 4). Registered in
  `SOURCE_SPECS`, the lazy `get_source` map, the CLI/catalog connector lists, the planner spec modules,
  `native_kind`, and `_BUILTIN_IDS`; `docs/sources.md` regenerated. New `tests/test_source_discourse.py`
  (offline stub-client unit tests for the topic/post mapping, the 403 gated-host skip, instance
  normalization, the `views` magnitude lifting the ranking score, plus a `network`-marked live smoke),
  and the source is wired into the 0.5 conformance sweep with an offline stub-client fixture.
- **Sources P1 — Stack Exchange connector (#134).** The first connector on the Phase-0 chassis (and
  its end-to-end validation: scaffold → `instance` picker → generated catalog). New
  `metalworks.research.sources.stackexchange.StackExchangeSource` — a keyless `ItemSource` over the
  Stack Exchange API 2.3 (`/search/advanced` for questions → `CorpusRecord`, `/questions/{ids}/answers`
  for answers → `CorpusComment`), paged with a `withbody` filter that carries the body, `score`, and
  `view_count`. It spans 170+ B2B/role sites (Server Fault, DBA, Security, Salesforce, …) over one API
  — the `instance` target is the SE `site` (default `stackoverflow`). It emits
  `{"votes": score, "views": view_count}`, adding a real **magnitude** signal (`views`) Reddit upvotes
  can't express ("47k views, no accepted answer" = quantified unmet demand) — both kinds already
  registered, so no new `register_signal`. Auth is keyless (`auth="none"`, `access="open"`); an
  optional `STACKEXCHANGE_KEY` is passed through when set to raise the quota but is never required.
  Content is CC BY-SA, so the connector is framed as **evidence retrieval / quoting under CC BY-SA**
  (attribution = question permalink + pseudonymized author profile), NOT corpus ingestion for model
  training. The `instance` target picker (`planner/source_picker.py`) is fleshed out for SE — append-
  only over a non-removable `stackoverflow` default, LLM-ranking role/topic sites, degrading to the
  default on any failure. Registered in `SOURCE_SPECS`, the lazy `get_source` map, the CLI/catalog
  connector lists, and `_BUILTIN_IDS`; `docs/sources.md` regenerated. New
  `tests/test_source_stackexchange.py` (offline stub-client unit tests for the record/answer mapping,
  the `views` magnitude lifting the ranking score, plus a `network`-marked live smoke), and the source
  is wired into the 0.5 conformance sweep with an offline stub-client fixture.
- **Sources 0.5 — lane conformance sweep (#124).** The last Phase-0 chassis piece: a parametrized
  conformance sweep over `SOURCE_SPECS` + `MAGNITUDE_SPECS` that turns the single-fake source check
  into the registry-level backstop keeping lane discipline honest as the source count grows.
  `metalworks.testing` gains `check_lane_conformance` (plus per-rule helpers) asserting, across every
  registered source + magnitude provider: (1) every `grounding` id is constructible via `get_source`
  with offline fixture deps and yields ≥1 quotable record (text + url + pseudonymizable author, or
  `yields_units` + domain breadth); (2) no `magnitude` lane id appears in `SOURCES`; (3) no
  `access=="blocked"` id appears in `SOURCES` or `MAGNITUDE_PROVIDERS`; (4) every kind in a spec's
  `signals` is registered in `SIGNAL_SPECS` (catches the silent magnitude-drop); (5) a `grounding`
  lane declares ≥1 non-`is_magnitude` signal; (6) the default/empty stub spec fails (spec effectively
  required); (7) every non-`none` `targeting` has a registered target picker — plus a keys-env-only
  declaration guard (env entries are UPPER_SNAKE names, never literal secrets). New
  `tests/test_conformance_sweep.py` runs the sweep on the real shipped registries (all offline — stub
  clients / fake readers, no network) plus one NEGATIVE fixture per rule. The sweep runs under pytest,
  which IS the CI gate, so no `ci.yml` change is needed. No connector / selector / provider behavior
  changed — this only adds the guardrail (the shipped sources/providers already pass).
- **Sources 0.7 — DX: scaffold + spec-driven `sources list` + generated catalog (#125).** Adding a
  source is now a fill-in-the-bodies job, not a 7-step edit across 6 files, and the catalog stays
  honest because it's generated from each source's `SourceSpec`. New `metalworks sources scaffold
  <id> --lane <lane> --auth <auth>` emits a connector module (a real `ItemSource` carrying a filled
  `SourceSpec` + a `register_signal` block, only `pull` / `comments_for` left to write) and a
  conformance test, then **prints** (never auto-edits) the `pyproject.toml` extra snippet and the
  `docs/sources.md` row. `metalworks sources list` now reads `SOURCE_SPECS` directly — rendering
  lane / auth / access / env / relevance-hint plus a computed `reachable` column (is the env var
  set?) — with `--lane` and `--needs-key` filters; the hardcoded `_SOURCE_REACH` dict is retired.
  `metalworks doctor` gains a Sources / key-status section. `docs/sources.md` is now generated by
  `scripts/gen_sources_md.py` (mirroring `gen_ts_types.py`); `gen_sources_md.py --check` is a CI
  drift gate. `research/sources/template.py` now carries a `SPEC = SourceSpec(...)` + a commented
  `register_signal` example, and CONTRIBUTING.md gains an "Adding a source connector" section with a
  worked Discourse example. No `pipeline.py` / contract changes — additive DX only.
- **Generalized source selector + per-target pickers (sources 0.4).** Source selection was
  config-only; this generalizes it into a **brief-aware selector** that picks which of the N
  registered sources to trust per run — with a non-removable floor so it can never silently choose
  zero sources. `research/planner/source_picker.py` adds `pick_sources(deps, brief)` (a deterministic
  access/auth gate on each `SourceSpec`'s `access`/`auth`/`env` — reachable iff keyless or its key is
  set — then an **append-only** LLM relevance rank on `relevance_hint`) and `select_sources(...)`
  (the full `SourceSelection`: the ranked pick, the sources skipped for missing keys with their
  `MissingKeyError`-shaped env var/fix, and a `floor_applied` caveat). A `register_target_picker`
  registry makes the existing subreddit picker the `subreddit` entry and adds `keyword` / `instance`
  / `slug` stubs (their content registries are out of scope). `ResearchDeps.effective_sources()`
  becomes brief-aware: precedence is **explicit `[sources].enabled` / `--source` override > selector
  (opt-in) > the `reddit` default**. **The selector is opt-in** via `[sources].select = true`
  (`config.source_selector_enabled()`) — default behavior is unchanged until a brief→expected-sources
  eval set lands. Two new additive contract models — `SourceSelection` + `SkippedSource` — surface
  the pick on `DemandReport.source_selection`, and the pipeline logs a pre-flight
  `Selected: …; Skipped (no key): X — set ENV` line. **Floor (hard rule):** a brief matching only
  paid sources with no keys falls back to `reddit` with a distinct caveat, never an empty corpus.

- **Reddit engagement re-homed as Distribution's participation/execution arm (D9).** The Reddit
  engagement module (`metalworks.reddit`: OAuth, search, subreddit rules, rate-limiting, inbox, the
  `heuristic_check` compliance gate, the voice stylebook) + `generate_reply` is the **one channel
  metalworks can OPERATE rather than merely plan** — the moat the Distribution thesis rests on. It is
  re-homed under Distribution as the execution arm for the community-native + GEO participation
  stream; the existing `reddit_*` tools keep working unchanged. A new **participation-reply
  primitive** wires D6's targets to the engagement machinery: `participation_reply(deps, report,
  target)` (in `research/distribution/engage.py`) takes one D6 `ParticipationTarget` (a real thread:
  its `permalink` + `why` + `suggested_angle`) and drafts a **disclosed, founder-voiced reply for
  that exact thread**, reusing the discovery reply seam and then running the shared deterministic
  honesty gate (`heuristic_check`) over the result. One new contract model, `ParticipationReply`
  (`community`, `permalink`, `draft`, `compliance`, and `requires_human` / `posting_gated` — both
  always true). Available on all four surfaces: `mw.distribution_engage(research, target)`,
  `metalworks distribution engage <report-id> --permalink … --why …`, the `distribution_engage` MCP
  tool (tool count **34 → 35**), and the `distribution-engage` skill. **Voice consolidated:** the
  no-"upvote" platform invariant (`UPVOTE_REGEX` / `strip_upvote_ask`) now lives in
  `metalworks.reddit.stylebook` alongside the AI-tell denylist, so the channel-shaped launch assets
  (D4) and the participation arm share ONE voice system — D4's `assets.py` imports the guard rather
  than re-defining it. **Redundancy audit:** the standalone reply flow (`/draft-reply`,
  `generate_reply`) is the report-free entry (draft for any pasted URL) and the participation arm is
  the report-grounded entry (draft for a GEO-selected target); they share the same honesty gate and
  voice system by design — complementary entries, no genuine duplication removed; `heuristic_check`
  stays the shared gate the rest of the system leans on. **POSTING STAYS GATED** — drafting only; a
  human posts via the triple-gated `reddit_post_comment` path.

- **Closed-loop measurement (D8) — per-channel metric + instrumentation, ingest results, re-rank.**
  Everything in the Distribution pillar so far PLANS; nothing learns. D8 closes the loop: plan →
  (human executes) → record `ChannelResult`s → re-rank the next push. metalworks can't watch live
  traffic, so in its lane it defines the metric + what to instrument and ingests results to re-rank
  — its falsifiable disposition applied to distribution. Two new contract models: `ChannelMetric`
  (`channel_name`, `surface_type`, `success_metric`, `instrumentation`) and `ChannelResult`
  (`channel_name`, `metric`, `value`, `period`). A new `research/distribution/measure.py`:
  `channel_metrics(channels)` is DETERMINISTIC — one metric per channel with its success metric +
  instrumentation read from a table keyed by `surface_type` (launch platform → top-N + attributed
  signups, UTM; marketplace → installs + WAU; community → qualified replies + click-through;
  answer-engine GEO → citation appearances; …) — and `rerank_from_results(channels, results)` is
  pure + deterministic: it sums each channel's recorded `value`s and re-orders so the channels that
  actually performed lead (measured first by descending score, unmeasured after, each group keeping
  its original order); with no results it is a no-op. `prior_results` is now **meaningful**:
  `select_channels(..., prior_results=...)` and `plan_distribution(..., prior_results=...)` apply
  the re-rank when the prior push's results are passed, and the `prior_results=None` path is
  byte-for-byte unchanged. Available on all four surfaces: `mw.channel_metrics(...)`, `metalworks
  distribution measure <report-id>`, the `distribution_measure` MCP tool (tool count 33 → 34), and
  the `distribution-measure` skill. PLANNING ONLY — it defines what to measure; the human measures,
  records, and feeds the results back to re-rank.

- **Distribution plan (D7) — pushes (sequenced moments) + streams (continuous), deterministically
  sequenced.** A new `distribution plan` surface replaces the old toy even-spacing plan (`T+{i*2}h`
  — an LLM-invented constant masquerading as a schedule). A distribution plan is now **pushes** (the
  `spike`-cadence channels placed into concentrated launch moments) + **streams** (the
  `compounding`-cadence channels run continuously) — the split falls straight out of the channel's
  own `cadence` axis. `plan_distribution(report, channels, prior_results=None)` is PURE +
  DETERMINISTIC (no LLM, no network): each push's `timing` is READ from a module-level **playbook
  table** sourced from the research (Product Hunt → "Day 1, 12:01am PT (Tue/Wed)"; Show HN → "Day
  3-4, Tue-Thu 8-10am PT"; an X thread → its window) — reproducible + citable, never an invented
  hour. The sequencer enforces the playbook's rules: at most **one all-day-attention channel per
  launch day**, and **never Product Hunt and a big HN push on the same day** (they stagger onto
  separate days); it opens with a **pre-launch warming** step, runs the staggered **push week**, and
  closes with a **30-day post step** (where the early channel TESTS resolve into a single channel to
  concentrate on — test→focus — and a winning push becomes a repeatable one). Each spark-requiring
  channel carries its `spark_channel` (the spark→flywheel edge). `prior_results` is accepted for the
  D8 re-rank (threaded through, unused now). Available on all four surfaces:
  `mw.distribution_plan(...)`, `metalworks distribution plan <report-id>`, the `distribution_plan`
  MCP tool (tool count 32 → 33), and the `distribution-plan` skill. DRAFTING + PLANNING ONLY —
  every push is `requires_human=True` + `posting_gated=True`; nothing posts. Additive contract: the
  new `Push`, `Stream`, and `DistributionPlan` models. (#105)

- **Distribution → build requirements (D3) — embedded loops + the conversion surface feed
  build-spec.** Two distribution decisions are designed INTO the product, not bolted on as
  marketing tactics, so they are now emitted as BUILD requirements that feed the build spec.
  `distribution_requirements(channels)` is DETERMINISTIC: for each selected `embedded_loop`
  channel it emits a `LoopRequirement` mapping the loop kind → a fixed set of build requirements
  (watermark ⇒ `public_share_urls` + `branded_viewer` + `badge_gating`; UGC-SEO ⇒
  `ssr_public_pages` + `sitemap`; single-player ⇒ `solo_aha_before_invite`), grounded in the
  channel's `routing_signal`; and it ALWAYS emits a `ConversionSurfaceRequirement` for the
  conversion destination the channels point at (its funnel job + what it must ship) — channels
  create attention, and attention with no surface to catch it leaks out, so the build must include
  a place to convert. This re-opens generate-site (#67) from the right side: not cite-or-die
  marketing copy, but "the build must include a conversion destination." `build_spec_from_report`
  gains an additive `distribution_requirements=None` parameter; when supplied, the `BuildSpec`
  records them on the new additive `loop_requirements` / `conversion_surface_requirements` fields.
  Default `None` → byte-for-byte unchanged behavior. Available on all four surfaces:
  `mw.distribution_requirements(...)`, `metalworks distribution requirements <report-id>`, the
  `distribution_requirements` MCP tool (tool count 31 → 32), and the `distribution-requirements`
  skill. Deterministic — no invented features. Additive contract: the new `LoopRequirement` and
  `ConversionSurfaceRequirement` models. (#101)

- **Distribution GEO / LLM-citability stream (D6) — participation targets, citability probes,
  answer-first briefs.** A new `distribution geo` surface turns a finished demand report into the
  GEO ("get cited by AI") stream. Reddit is the #1 AI-cited domain and most AI citations are Q&A
  threads, so the play is to participate in the threads the audience is *already* asking in and to
  publish answer-first content. **Participation targets** are pulled DETERMINISTICALLY from the
  report's real permalinks + communities (a target's `permalink` is a verbatim `source_url` from a
  verified quote — never invented) with a `why` grounded in the cluster claim. **Citability probes**
  are derived deterministically from the cluster claims (the real questions the audience asks), not
  templated keyword fluff. **Answer briefs** are LLM-authored answer-first prose, but cite-or-die is
  CORRECT here — the answer is a factual claim, so each brief's `evidence_refs` resolve against
  `report.evidence` and its `stat_anchors` carry the cluster's real distinct-author / mention
  counts; a brief whose evidence doesn't resolve is DROPPED. Available on all four surfaces:
  `mw.geo(...)`, `metalworks distribution geo <report-id>`, the `distribution_geo` MCP tool (tool
  count 30 → 31), and the `distribution-geo` skill. Drafting only — nothing posts. Additive
  contract: the new `ParticipationTarget`, `CitabilityProbe`, `AnswerBrief`, and `GeoPlan` models.
  (#104)
- **Data-as-marketing data report (D5) — the on-brand flagship asset.** A new `distribution
  data-report` surface projects a finished demand report into a corpus-derived `DataReportAsset`
  — a publishable ranking (a `complaint_index`, a `feature_ranking`, or a `state_of` report) over
  a proprietary Reddit corpus. It stacks every AI-citation driver at once: original research + a
  ranking + verbatim quotes + permalinks. The ranking is DETERMINISTIC — the items ARE the
  report's own `ranked_clusters`, in their own order, each `DataReportItem` carrying that
  cluster's REAL `distinct_author_count` / `mention_count`, the real `source_url` permalinks of
  its verified quotes, and one verbatim quote — never re-scored, never invented. The LLM writes
  only the report `title` and each row's framing `label`, grounded in the cluster's claim, and
  falls back to the claim verbatim on failure. `methodology` discloses the honest base (N threads
  analyzed, distinct-author counting, the corpus date range) — the survey-fabrication base rate is
  the trap, so rigor IS the credibility. Available on all four surfaces: `mw.data_asset(...)`,
  `metalworks distribution data-report <report-id> --kind complaint_index`, the
  `distribution_data_report` MCP tool (tool count 29 → 30), and the `distribution-data-report`
  skill. Additive contract: the new `DataReportAsset` + `DataReportItem` models. (#103)
- **Channel-shaped distribution assets (D4) — relaxed grounding, platform invariants, offer/CTA.**
  A new `distribution assets` surface drafts channel-SHAPED, drafting-only launch copy off a
  finished report and its channel strategy: one `ChannelAsset` per selected channel, broken into
  channel-native `AssetPart`s by the channel's surface (Product Hunt = tagline + authentic maker
  comment + gallery captions; Show HN = plain title + technical first comment; X = a numbered tweet
  thread; LinkedIn = a carousel; default = title + body). The old flat `LaunchAsset.body: str` is
  gone — a thread isn't a string. Grounding is **relaxed** on purpose: only DEMAND/factual claims
  are held to no-cite-no-claim (each resolves to a real Reddit quote via `verbatim_match` and emits
  a `ClaimCitation`, unresolved ones dropped), while persuasive hooks, taglines and the per-channel
  `offer` (the CTA) are FREE craft — over-grounding the copy was a category error. Platform
  invariants are enforced deterministically: never an "upvote us" ask (a guard strips it),
  native-first (no link in the hook), founder-voiced. Available on all four surfaces:
  `mw.channel_assets(...)`, `metalworks distribution assets <report-id>`, the `distribution_assets`
  MCP tool (tool count 28 → 29), and the `distribution-assets` skill. Additive contract: the new
  `AssetPart` + `ChannelAsset` models. (#102)

- **Distribution channel strategy (D2) — entity→channel routing, test→focus.** A new
  `distribution strategy` surface routes a finished demand report's *real named entities +
  signals* into the structured channel space and emits a small set of **channel experiments**
  (not a ranked portfolio). The communities/permalinks that ground a community channel are pulled
  DETERMINISTICALLY from the report's verified quotes — the LLM only classifies the product/ICP
  archetype, writes the one-line ICP, and surfaces platforms/media the audience explicitly named;
  it never invents grounding. Every `Channel` sets all five placement axes, carries a cheap `test`
  + a `success_threshold` (test→focus: most products have ONE channel that works — test cheaply,
  concentrate on the winner), pairs amplifiers (marketplaces/loops) with the spark that ignites
  them, and traces its `routing_signal` to a real corpus entity (the no-fabrication rule). The
  assembled `ChannelStrategy` carries a `focusing_rule` + a `funnel_note` that flags an
  all-top-of-funnel plan as a conversion leak. Available on all four surfaces:
  `mw.channel_strategy(...)`, `metalworks distribution strategy <report-id>`, the
  `distribution_strategy` MCP tool (tool count 27 → 28), and the `distribution-strategy` skill.
  Additive contract: the new `ChannelStrategy` model. (#100)

- **Evidence-gating observability + a recall backstop.** The cosine/percentile thresholds that
  decide which evidence reaches synthesis are now visible and measured, not blind. The previously
  un-surfaced cutoffs are config fields with documented defaults: the embed-group near-dup cosine
  (`0.92`) and the synthesis comment cap (`2000`) move onto the new additive
  `SynthesisThresholds` on `ResearchBrief`, and the landscape gap→complaint / product→cluster match
  floors are surfaced as `LandscapeMatchPolicy` — and tightened from `0.55`/`0.45` to `0.62`/`0.55`
  so a coincidental, topically-adjacent complaint no longer attaches as a competitor gap. A run now
  emits a **false-reject-rate estimate**: the triage step samples N threads from the auto-rejected
  band, runs them back through the same LLM classifier, and surfaces the fraction it would have kept
  on the `corpus_shape` contract (`ExplorationReport.false_reject_rate` / `_sample_size`), plus the
  embed-group **merge rate** (`dedup_merge_rate`) so breadth-collapse is visible. Finally
  `TriageThresholds.cosine_ceiling` ships a non-None default (`0.50`) — the recall safety valve —
  so a high-cosine thread mis-ranked into the reject band is rescued to the middle bucket instead of
  being silently auto-rejected on percentile alone. All additive + defaulted; behavior is unchanged
  except the two raised landscape floors and the now-on safety valve. (#82)

- **Taste presets for the design pillar.** The single global `TASTE` director is now a small,
  curated set of opinionated presets — `editorial` (the default, byte-for-byte the old voice, so
  output is unchanged), `brutalist`, `warm-minimal`, and `technical`. Pick one with a `taste`
  param threaded through all four surfaces (`Metalworks.design(... , taste=)`, `metalworks design
  --taste`, the `design_from_report` / `logo_generate` MCP tools, and the `/design` skill); the
  chosen preset is recorded on the new additive `DesignSystem.taste` field. The preview and logo
  picker now derive their chrome (palette + fonts) from the chosen preset instead of one hardcoded
  dark/cream theme — and no longer render in a convergence-trap face (the logo picker stops leading
  with `Inter`, which the design system's own review rejects). The same report under two presets
  yields a visibly different system. (Subsumes the font half of the preview/picker cleanup.)

- **Grounded build order in the build spec.** `BuildSpec.features` now come back ordered by the
  demand strength of the cluster behind each (the new `FeatureSpec.source_cluster_rank`, 1 =
  strongest), and the cap keeps the highest-demand features. `features[0]` is the spine — the
  feature to build first — and `SPEC.md` renders a numbered "build in this order" list with the
  spine flagged. The sequence is a deterministic read of real demand; no new LLM call. (This is the
  kept residue of the build-blueprint exploration: a grounded build order earns its keep where a
  reusable archetype catalog did not.)

- **Page-rendering infrastructure (`metalworks.render`).** A new `PageRenderer` protocol — a
  screenshot plus computed-style extraction over a real page — with an owned-Chromium **Playwright**
  adapter (the new `metalworks[browser]` extra), a hosted **Firecrawl** adapter (screenshot-only,
  reuses `[firecrawl]`), and a `FakeRenderer` for offline tests. Resolved via
  `config.resolve_renderer()` (Playwright → Firecrawl → none) and surfaced in `doctor`. It is
  infrastructure like `SearchProvider`/`EmbeddingProvider` — the first consumer is the upcoming
  design pillar, and it is reusable for landscape / deploy checks. Bare `import metalworks` still
  imports no browser. The protocol exposes no caller-supplied JavaScript by design.
- **`metalworks browser install [--with-deps]`** — downloads Chromium for the browser renderer (the
  post-install step for `[browser]`); `--with-deps` also installs the Linux system libraries Chromium
  needs to launch.
- **`metalworks render <url> -o shot.png`** — a debug command to verify the renderer is working.
- `doctor` now reports the `browser` extra and the active **renderer tier** (Playwright / Firecrawl /
  none) without launching Chromium, plus `BrowserNotInstalledError` / `BrowserLaunchError` /
  `StyleAuditUnsupported` with copy-pasteable fixes.
- **Visual-design pillar (`/design`).** Turn a finished report into a grounded-but-directional
  `DesignSystem` — an aesthetic direction, a SAFE/RISK choice per design dimension, directional
  landscape signals, and a `DESIGN.md` source of truth + a preview page. It reads the competition at
  the richest tier available — a real browser teardown of competitor sites (Playwright screenshots +
  computed styles) > web text > the model's own knowledge — and records the `grounding_tier` so the
  look is never overstated. Grounding is **directional, not cited** (the landscape informs the bet, it
  doesn't cite it); the honesty signal is the SAFE/RISK stance + the tier. On all four surfaces:
  `mw.design()`, `metalworks design`, the `design_from_report` MCP tool, and the `/design` skill.
- **Logo (`/logo`) — the mark submodule of the design pillar.** Diverse, company-grade SVG logo
  options, one per design angle (symbol / logotype / negative-space / reference / expressive), each
  drawn **under the brand's `DesignSystem`** (its aesthetic, typography, color) rather than an invented
  house style. Options are offered, never auto-selected; an angle that returns no valid SVG — or an
  **unsafe** one (a `<script>` / event handler / `<foreignObject>` in model-authored markup) — is
  dropped, never inlined. `LogoOption` / `LogoSet` contracts; on all four surfaces: `mw.logo()`,
  `metalworks research logo`, the `logo_generate` MCP tool, and the `/logo` skill.
- **The marketing site can now look like the brand.** `render_site_html` takes an optional
  `DesignSystem` and inlines a brand stylesheet derived from it (fonts, accent, light/dark mode);
  `mw.render_site(site, research, design=…)`, `metalworks research site --styled`, and the
  `site_render` MCP tool's `styled=true` build the design and apply it. **Strictly additive** — with no
  design system the site renders exactly the unstyled structural HTML as before.
- **Design review (`/design-review`) — the audit half of the design pillar.** A **deterministic**
  computed-style audit of a *rendered* page: it opens the URL in a real browser, reads the actual
  fonts / heading scale / colors, and flags hard-rule violations (too many fonts, an AI-default
  convergence-trap body face, a non-monotonic heading scale) plus — with a report — whether the page
  matches that report's design system. The model writes nothing; every `StyleFinding` is a pure
  function of the page. `DesignReview` / `StyleFinding` contracts; on all four surfaces:
  `mw.design_review()`, `metalworks research design-review`, the `design_review` MCP tool, and the
  `/design-review` skill. Needs a script-capable browser renderer (Playwright).

### Docs
- **Refreshed corpus/sources docs for the 3-lane source model + connector build guides.** The
  conceptual docs described the old Reddit/HN single-source world; they now reflect the
  ultra-wide-sources surface. New page `docs/build-sources.md` ("Build a source") is the
  canonical how-to for all three lanes, each with a copy-paste worked example mirroring a shipped
  source — a **grounding** connector (`ItemSource` + `SourceSpec` + the single
  `BUILTIN_SOURCE_MODULES` registration (#139) + `register_signal` + the `yields_units` / rule-5
  rule + `metalworks sources scaffold`; ref `stackexchange.py`), a **magnitude** provider
  (`MagnitudeProvider` + `register_magnitude`, omission=unknown-never-0, never-creates-a-cluster;
  ref `magnitude.py` / npm), and an agentic **discovery** provider (`DiscoveryProvider`,
  cite-or-die when delegating, the capability-ladder gate; ref `discovery/exa.py`). `docs/corpus.md`
  is now the corpus-purpose overview (the 3 lanes, buyer-layer breadth, cite-or-die, the advisory
  demand-volume signal) instead of just "where the .db lives". `docs/architecture.md` and
  `docs/how-it-works.md` show the source pipeline (selector → pull per lane → cluster → magnitude
  overlay → deterministic score) and the deterministic-scorer / **advisory-magnitude,
  breadth-only-verdict** split. `docs/custom-corpus.md`, `docs/extending.md`,
  `docs/metalworks-internals.md`, `docs/load-reddit-corpus.md`, `docs/load-hn-corpus.md` updated;
  the stale `sources#add-your-own-source` cross-references now point at the build guide.
  `CONTRIBUTING.md` "Adding a source connector" gains the #139 single-registration step and a
  pointer to the magnitude/discovery guides. The generated `docs/sources.md` (via
  `scripts/gen_sources_md.py` static prose) leads with the lane model and links the build guide;
  `docs.json` nav adds the new page. Docs-only — no `src/` behavior change.

### Changed

- **`DemandReport.pinned_axis` / `optimized_axis` are now optional (`str | None`, default `None`).**
  They were required `str` but never computed — the pipeline filled them with sentinel strings
  (`"(slot_plan-driven)"`, `"(no corpus)"`) that read like data. No code consumed them; the pipeline
  now leaves them `None` (honestly "not computed") instead of shipping a placeholder.
- **Renamed `DemandReport.verdict` → `demand_summary`.** The field is a demand-strength *summary*
  ("Strong demand — 130 distinct voices; ~130 reachable on Reddit"), not the authoritative
  go/no-go — that remains `assess`'s `Decision` (GO / PIVOT / NO_GO). Because the summary carries no
  saturation/competitive context it can read more bullish than the actual call, and the shared name
  invited readers to treat it as the verdict; the rename keeps the two distinct. No logic change —
  `derive_verdict` is a pure formatter and owns no thresholds. **Contract break (below 1.0):** the
  field is renamed on `DemandReport` (and in the generated `ts/contract.ts` + schema); the launch
  refusal gate, run-markdown renderer, and SDK docs read the new name. The `assess` `Decision` /
  `ForkVerdict` are untouched.

- **The build spec now owns the surface decision and the screen skeleton.** `build_spec_from_report`
  gains `surface: SurfaceKind | "auto" = "auto"`: with `"auto"` (the new default) the *same*
  feature-mapping LLM call also returns the chosen surface + a one-line rationale (no extra call —
  it already has the query, wedge, and pains in scope); a pinned surface (e.g. `"cli"`) is honored
  and skips the pick. Screens are then sketched **after** the features exist, so each maps to real
  `feature_id`s (the old standalone skeleton was generated blind to the features it was meant to
  serve); shell screens (auth/settings) are flagged `scaffolding`, not demand hypotheses. **Contract
  (additive):** `BuildSpec` grows `surface_rationale: str | None` and `screens: list[Screen]`, and
  `Screen` grows `feature_ids` + `scaffolding`; old payloads still validate. `SPEC.md` renders a
  `## Screens` section and the surface rationale next to the grounded build order; `metalworks build
  init` / the `build_spec` MCP tool default to `--surface auto`.

### Removed

- **Dropped `MarketSizing.addressable_market` (a `reddit_floor × 100` assumption printed as a number).**
  The 100× reach multiplier ("posters are ~1% of the population") was an editable assumption whose
  honesty lived only in a docstring the user never saw, so the report effectively printed a fabricated
  TAM next to real counts. `MarketSizing` now ships only what's honest: `reddit_floor` (a real distinct-
  author count) and `penetration` (already-labeled scenario bands). `synthesis/market.py` drops
  `DEFAULT_REACH_MULTIPLIER`, the `reach_multiplier` param, and the multiply (keeps `DEFAULT_PENETRATION`);
  `derive_verdict` no longer appends the "~N addressable" clause (keeps "~N reachable on Reddit").
  **Contract break (below 1.0):** the field is removed from `MarketSizing` and the generated
  `ts/contract.ts` + schema.

- **Retired `/generate-site` (the grounded marketing-site generator).** It optimized provenance, not
  conversion — forcing the hero to be a raw forum quote, stripping every number and superlative from
  the copy, and shipping no `<h1>`/nav/CTA/pricing — so its likely output was an empty `partial`
  page nobody ships. Its honest use (a quote wall) is already covered by the demand report +
  `/content-plan`. Removed across all four surfaces: the `mw.site()` / `mw.render_site()` facade
  methods, the `metalworks research site` CLI command, the `site_render` MCP tool, and the
  `/generate-site` skill, plus the core `research/site.py`. **Contract:** the `MarketingSite` and
  `SiteSection` models are removed from `metalworks.contract` (and from the generated `ts/contract.ts`).
  `DesignSystem` and `/design-review` are unaffected; `/content-plan` (the separate content pillar) stays.
- **Retired the standalone `/surface-and-ux` pillar (folded into `/build-spec`).** Its outputs were
  orphaned — nothing downstream read them, and the UX skeleton was generated blind to the chosen
  features. The surface decision and the (now feature-grounded) screens are owned by the build spec
  (see **Changed**). Removed across all four surfaces + the registry: the `mw.surface()` / `mw.ux()`
  facade methods, the `metalworks research surface` CLI command, the `surface_recommend` and
  `ux_skeleton_build` MCP tools (+ their `_TOOL_WRAPPERS` registration), and the `/surface-and-ux`
  skill, plus the core `research/surface.py`. **Contract:** the now-unproduced `SurfaceRecommendation`,
  `UxSkeleton`, `RubricDimension`, and `TradeOff` models are removed from `metalworks.contract` (and
  from the generated `ts/contract.ts`); `Screen` and `SurfaceKind` are kept (the build spec uses them).
  The `docs/design` "Surface & screens" page is folded into `docs/build-spec`.
- **Retired the standalone Launch + Content/SEO pillars (replaced by Distribution).** The Launch
  pillar (channel-native launch assets + a human-executed channel plan) and the Content/SEO pillar
  (a deterministic per-cluster content plan) are subsumed by the Distribution pillar's grounded
  channel strategy, channel-shaped assets, the corpus-derived data report, the GEO / LLM-citability
  stream, and the pushes-and-streams plan. Removed across all four surfaces (parallel to the
  `/generate-site` + `/surface-and-ux` retirements above): the `launch_assets_build` /
  `channel_plan_build` / `content_plan_from_report` MCP tools (+ their `_TOOL_WRAPPERS`
  registration), the `mw.launch()` / `mw.channel_plan()` / `mw.content_plan()` facade methods, the
  `metalworks research launch` / `metalworks research content-plan` CLI commands, and the
  `/launch-kit` + `/content-plan` skills, plus the core `research/marketing.py`. **Contract:** the
  now-unproduced `LaunchAsset`, `ChannelPlan`, `ContentPlan`, and `MarketingSite` models are removed
  from `metalworks.contract` (and from the generated `ts/contract.ts`); the live Distribution models
  (`ChannelStrategy` / `Channel`, `ChannelAsset` / `AssetPart`, `DataReportAsset` / `DataReportItem`,
  `GeoPlan` and friends, `DistributionPlan` / `Push` / `Stream`, `ChannelMetric` / `ChannelResult`,
  `LoopRequirement` / `ConversionSurfaceRequirement`, `ParticipationReply`) replace them. The
  `/docs/launch` + `/docs/content-seo` pages redirect to `/docs/distribution`.

### Fixed

- **`[sources].enabled` now actually feeds the pipeline.** The config-driven multi-source system was
  fully built but never plugged in: `_Resolver.sources()` hardcoded a single Reddit/Arctic connector
  and never called `config.resolve_sources()`, so `metalworks sources enable hackernews_archive`
  (and the `[sources].enabled` it writes) had **zero** effect on what demand research ingested — every
  non-Arctic source (`hackernews_archive`, `hackernews`, `web`) was dead for the `Metalworks(...)`
  facade path. `client.sources()` now delegates to `resolve_sources(reader=…, comments=…)`, so the
  default (no `[sources]` config) stays byte-for-byte one Reddit/Arctic source, while enabling another
  source genuinely **adds** it. Also hardened the `hackernews_archive` factory: `resolve_sources`
  passes the Reddit reader/comments to every factory, and HN's `__init__` would silently swallow a
  foreign reader (no `TypeError`, so the `_build_source` fallback never fired) — it now drops any
  non-`HackerNewsArchiveReader` reader and the `comments` kwarg, so HN always reads its **own**
  archive (the live `hackernews`, `web`, and `producthunt` factories already raised `TypeError` on
  those kwargs and needed no change).
- **Distribution post-ship review fixes (Show HN shape, enriched-entity grounding, surfaced
  compliance).** Three Distribution defects found in review: (1) **Show HN drew the Product Hunt
  shape.** D2 creates the `show_hn` channel as a `launch_platform`, but `assets._shape_for` keyed the
  Product-Hunt shape (tagline + maker_comment + gallery) to `LAUNCH_PLATFORM` and the Show-HN shape
  (title + technical first_comment, no superlatives) to `EARNED_MEDIA` — which no channel emits — so
  HN drafted as a PH launch and the HN shape was unreachable. `show_hn` is now special-cased **by
  name** (exactly as `linkedin` already is) to draw the technical title + first_comment shape; its
  `surface_type` is unchanged. (2) **Enriched entities weren't corpus-verified.** The LLM
  enrichment pass (`channels._enrich_entities`) returned `named_platforms` / `named_media` /
  `hated_incumbent` / `benchmark_hunger` with no check that they appear in the corpus, while the
  contract + module docstrings claimed `routing_signal` "always traces to a real corpus entity /
  never invents." A new `_verify_enrichment` now drops any platform / media / incumbent absent from
  the corpus text (a normalized substring check, `grounding.appears_in_corpus` — the named-entity
  cousin of `verbatim_match`), and `benchmark_hunger` survives only with a real benchmark cue in the
  corpus — so an un-verified entity can no longer become a channel or populate a `routing_signal`.
  The deterministic community grounding is unchanged. (3) **A computed compliance verdict was
  discarded.** `build_channel_assets` ran `heuristic_check(asset.body)` under `contextlib.suppress`
  and threw the result away; `ChannelAsset` now carries an additive `compliance: ComplianceVerdict |
  None` field (default `None`, the same signal D9's `ParticipationReply.compliance` carries),
  populated from that check. `ts/contract.ts` regenerated. Plus two docstring corrections (the
  funnel-note `else` branch and `plan.plan_distribution`'s rerank note, which overstated that rerank
  reorders spike pushes — spikes are always re-sorted by `(playbook_day, name)`).

## [0.0.5] - 2026-06-18

The CLI gets a real front door. Still pre-1.0; anything outside `metalworks.contract` and the MCP
tool contracts may change.

### Added

- **Top-level interactive menu.** Running bare `metalworks` now opens a menu — validate an idea,
  configure models, configure data sources, view/edit config, run diagnostics (`doctor`), onboard
  (`setup`), or browse past runs — all reachable with **no project and no idea**. `metalworks start`
  keeps the direct idea flow.
- **`models` / `sources` / `config` open their own interactive menu** when run with no sub-command
  (set a model, toggle a source, set a config value); their flag-based subcommands still work for
  scripting.

### Changed

- Bare `metalworks` no longer jumps straight into the idea wizard, so configuration is no longer
  gated behind making a project and entering an idea.

### Docs

- New **Architecture** page (the contract-first / four-surface / no-cite-no-claim philosophy), a
  README "Develop" section, an expanded `CONTRIBUTING.md` (surface parity + contract-registry
  lockstep + release mechanics), and a `/pr-ready` Claude Code skill for contributors.

## [0.0.4] - 2026-06-17

Sharper decisions and a friendlier front door. The verdict stops collapsing the
report's forks, the CLI gets a guided session, and the competitive landscape becomes
one segment-aware surface. Still pre-1.0; anything outside `metalworks.contract` and the
MCP tool contracts may change — including the removed competitor-map surface below.

### Added

- **Per-fork verdicts.** `assess()` now scores each candidate wedge AND segment and
  synthesizes the three-lane top-line; `Assessment.fork_verdicts` carries the
  un-collapsed answer ("GO on the sleep wedge, NO-GO on the broad market"), each with
  its own demand band and a `confidence` (distance from a band edge). New `ForkVerdict`
  contract.
- **Relative, self-calibrating demand.** Demand strength is now a fork's prevalence
  (its share of the pulled crowd) and its standing among the report's other forks, not a
  hardcoded author-count cutoff — so the bands self-calibrate to each run. `GapAnalysis`
  gains `demand_prevalence` / `demand_percentile` / `confidence` / `reference`.
- **Guided CLI session.** Bare `metalworks` (or `metalworks start`) walks one idea end to
  end — setup → idea → demand → landscape → assess with the GO/PIVOT/NO-GO call in your
  hands each round — then offers positioning / site / scaffold after a GO.
- **Corpus-mined competitors + cluster tags.** `landscape()` now discovers rivals from a
  live web search AND the corpus (products people name in their complaints), and tags each
  `Competitor` with the demand clusters it competes for (`addresses_clusters`). Each
  `ForkVerdict` carries an **advisory** per-fork `landscape_saturation` (which wedge the
  supply competes for — shown, not yet gated).

### Changed

- **Report ids are optional everywhere.** Every report-grounded command (`landscape`,
  `assess`, `position`, `surface`, `site`, `launch`, `content-plan`, `refresh`,
  `versions`, `build init`) takes an id/prefix or defaults to your latest run — no more
  copy/pasting UUIDs. `research --help` groups the verbs into Core / Pillars / History.
- **`research validate` is interactive by default** (you make each GO/PIVOT/NO-GO call;
  `--auto` for headless), and both it and the guided session persist their final report.
- `derive_verdict` is a pure formatter — the demand-strength bands live in one place
  (`synthesis.demand`), so `report.verdict` and the assess decision can't disagree.

### Removed

- **The lean competitor-map surface.** `Metalworks.competitors()`, the
  `metalworks research competitor-map` CLI command, the MCP `competitor_map_from_report`
  tool, and the `/competitor-map` skill are gone — folded into `landscape()` (which still
  exposes the map as a nested `competitor_map`). Use `landscape()` /
  `metalworks research landscape` / `landscape_from_report` / `/market-landscape`.

## [0.0.3] - 2026-06-16

Research becomes a **validation loop**: ideate → demand + landscape → assess
(GO / PIVOT / NO-GO) → loop. Every new primitive is exposed on all four surfaces
(Python facade, CLI, MCP server, Claude Code plugin) and follows the no-cite-no-claim
rule. Pre-1.0; anything outside `metalworks.contract` may still change.

### Added

- **Decision-bearing forks.** `DemandReport` now surfaces the choices it used to
  collapse: `segments` (decision-bearing `SegmentChoice`, with an `overlap` guard so
  near-identical audiences aren't offered as a real choice) and `candidate_wedges`
  (`CandidateWedge` — the narrowest things someone would pay for), plus `None`-safe
  `default_*` / `active_*` selectors.
- **`landscape()`** — the full "what exists today": wraps the `CompetitorMap` and adds
  an empirical existing-solutions scan (real shipped products from Product Hunt + web,
  matched to demand clusters). CLI `research landscape`, MCP `landscape_from_report`,
  skill `/market-landscape`.
- **`assess()` → `Assessment`** — the **GO / PIVOT / NO-GO** verdict, a *deterministic*
  gap over demand × landscape (the model only writes the rationale). PIVOT carries a real
  `pivot_target` fork; a partial landscape never yields a hard GO. CLI `research assess`,
  MCP `assess_from_report`, skill `/go-no-go`.
- **`ideate()`** — idea-first (sharpen a raw idea into a hypothesis + a brief) and
  evidence-first (surface a report's forks as grounded sketches). CLI `research ideate`
  (+ `--from-report`), MCP `ideate_from_idea` / `ideate_from_report`, skill `/ideate`.
- **`validate()`** — the loop orchestrator. Pulls the corpus **once** and reuses it for
  in-corpus pivots; a fresh pull happens only when a pivot leaves the corpus. CLI
  `research validate`, MCP `validate_from_idea`, skill `/validate`. MCP tools: 26 → **31**.
- New "Validation loop" docs page + reference updates (CLI, SDK, MCP, data-model).

### Fixed

- **Vertex web grounding** now fires reliably — competitor enumeration mandates a web
  search instead of answering from memory (verified on Vertex `gemini-3.1-pro-preview`).
- **`DemandReport.source`** is derived from the sources actually read (e.g. `hackernews`,
  `mixed`) instead of always reporting `reddit_arctic_shift`.

## [0.0.2] - 2026-06-15

Multi-source corpus-as-core, live versioned reports, and keyless-by-default
providers. Pre-1.0, so anything outside `metalworks.contract` may still change.

### Added

- **Corpus-as-core.** A durable, multi-source corpus is now the core. Sources are
  `ItemSource` connectors that ingest source-neutral `CorpusRecord` /
  `CorpusComment` into one shared store: Reddit, Hacker News (keyless), web
  search, and bring-your-own (copy the template, `register_source`). CLI:
  `metalworks corpus add/sync/stats`, `metalworks sources list/enable/disable`,
  and a `--source` flag on `research run`; a `[sources]` config table.
- **Live, versioned reports.** A report is a refreshable view over the corpus:
  `metalworks research refresh <id>` re-synthesizes against the now-larger corpus
  and pins a new version in the same lineage, with a `ReportDiff` of what moved;
  `research versions` / `research diff` and `Metalworks.refresh()`. Prior versions
  stay frozen (citations are materialized inline).
- **Web as a flat peer source.** `WebItemSource`; comment-less records enter
  synthesis as their own units (`yields_units`); ranking uses a source-neutral
  **breadth** (distinct authors + distinct domains) so authored, web, and mixed
  clusters rank comparably (`InsightCluster.breadth_count` / `breadth_unit`).
- **First-class providers.** Local keyless embeddings (`fastembed` bge-small) as
  the default floor — any chat-only key (Anthropic included) works end to end;
  OpenAI bundled as a universal client; `metalworks models` / `doctor` / `setup`;
  opt-in chat fallback chains.

### Changed

- **Source-neutral citations (breaking, pre-1.0).** `QuoteCitation` →
  `ResolvedCitation`: `permalink` → `source_url`, `subreddit` → `source` /
  `source_name`, `upvotes` → `engagement`, plus `record_id` and a thin live-view
  `CitationRef`. The materialized `ResolvedCitation` is what serializes to disk
  and over MCP, so reports stay readable detached from the corpus.

### Removed

- The fake-data, no-API-key demo — metalworks is for grounded output; the demo
  has no place.

## [Unreleased]

Pre-release foundations. Nothing here is stable yet.

### Added

- **Contract** (`metalworks.contract`): Pydantic models for the research and
  Reddit surfaces (`DemandReport`, `ResearchBrief`, `Opportunity`,
  `RedditPost`, `RedditComment`, `SubredditIntel`, `InboxItem`,
  `ComplianceVerdict`, `DiscoveryContext`, ...), plus a TypeScript-type +
  JSON-schema generator with diff-gated snapshots.
- **Protocols + adapters**: own versioned `ChatModel` / `GroundedChatModel` /
  `SearchProvider` / `EmbeddingProvider` protocols with a structured-output
  ladder, plus thin adapters over official SDKs behind extras
  (`anthropic`, `openai`, `google`, `exa`, `tavily`). Google grounding converts
  provider byte offsets to character offsets so non-ASCII provenance stays
  correct.
- **Stores**: typed repos (`CorpusRepo`, `BriefRepo`, `RunRepo`, `AccountRepo`,
  `OpportunityRepo`, `InboxRepo`) with `MemoryStores` + `SqliteStores` in core
  (hosted backends live downstream via the same protocols). `CorpusRepo` carries
  a local vector memory — embeddings as float64 blobs + brute-force numpy cosine,
  no new core dependency. New `ArtifactStore` protocol + files-first `FileStore`
  for Tier-2 pillar artifacts. `TokenCipher` for OAuth tokens at rest. Public
  conformance suite in `metalworks.testing`.
- **Research vertical** (`metalworks.research`): brief planner, Arctic Shift
  corpus reader (HF Parquet submissions + live API comments), hybrid triage,
  clustered synthesis with exact-matched quotes, web research (grounded +
  external), cross-stream triangulation, and `run_research` end to end.
- **Reddit core** (`metalworks.reddit`): rate limiter (token bucket honoring
  Reddit's headers), OAuth + posting on httpx with typed errors, search,
  metrics, inbox classification, subreddit intel, and a deterministic
  compliance gate.
- **Project layer** (`.metalworks/`): a project is a directory like `.git`.
  `metalworks init` creates it with a `project.json` manifest, a gitignored
  `corpus.db` (corpus + embeddings), committed `runs/<id>/research.{md,json}`,
  and an `artifacts/` tree. A casual `Metalworks().research(...)` with no project
  present leaves zero footprint. Non-secret config lives in
  `.metalworks/config.toml` (a legacy cwd `metalworks.toml` is still read).
- **Evidence chain**: content-addressed stable ids on `QuoteCitation` /
  `WebFinding` / `PriceEvidence`, a `metalworks.contract.evidence` module
  (`EvidenceRef` / `EvidenceRecord`), and a `DemandReport.evidence` accessor —
  the spine downstream pillars resolve grounded claims against.
- **Embedding reuse**: the research pipeline persists corpus embeddings and
  reuses them across runs (keyed on the embedding model identity), so a re-run on
  the same corpus re-embeds only the query.
- **Front door**: `Metalworks().research(question, subreddits=...)` returns a
  frozen `Research` bundle, and the CLI gains `metalworks research run
  --question "..."` (no `brief.json` round-trip for the common case).
- **Vertex AI**: the Google chat + embedding adapters authenticate via Vertex
  (Application Default Credentials) when `GOOGLE_GENAI_USE_VERTEXAI=true`
  (`VERTEX_PROJECT_ID`/`GOOGLE_CLOUD_PROJECT` + `VERTEX_LOCATION`), not just an
  API key — `build_genai_client` in `metalworks._genai_client`; provider
  resolution routes to Google under Vertex even with no `GOOGLE_API_KEY`.
- **Marketing site (Pillar E)**: `build_marketing_site(deps, report, positioning=None)
  -> MarketingSite` + `render_site_html(site, report)` (`metalworks.research.site`).
  Top 3 clusters by demand_score; one constrained LLM call assigns each a
  SiteSection role and picks a VERBATIM fragment; the builder re-runs exact-match
  against the cluster's real `QuoteCitation.text` and DROPS any section that
  isn't a verbatim substring (no-quote-no-section). Connective copy ships
  `provenance="connective"` with no refs and is gated claim-free. Hero = the
  highest-distinct-author cluster. `render_site_html` emits one self-contained
  `index.html` with a permalink footnote (+ `data-evidence`) per verbatim
  section. New contract `metalworks.contract.site` (`MarketingSite` /
  `SiteSection`). CLI `metalworks research site`, MCP Tier-2 `site_render`, skill
  `generate-site`.
- **Launch (Pillar F)**: `build_launch_assets(deps, report, positioning) ->
  list[LaunchAsset]` + `plan_channels(report) -> ChannelPlan`
  (`metalworks.research.launch`). Refuses (returns []) on a no-go report
  (negative verdict or no cluster ≥2 distinct authors). One LLM call per surface
  (Product Hunt / Show HN / X thread) → title + body + variants + claims; each
  claim is grounded to a real quote and carries a `ClaimCitation` with char-offset
  spans into the body (`body[span_start:span_end] == claim_text`) — unresolvable
  claims are dropped. Bodies run through the compliance gate best-effort.
  Drafting-only: `plan_channels` marks every `ChannelStep` `requires_human` +
  `posting_gated`; the library never posts. New contract
  `metalworks.contract.launch` (`LaunchAsset` / `ClaimCitation` / `ChannelPlan` /
  `ChannelStep`). CLI `metalworks research launch`, MCP Tier-2 `launch_assets_build`
  + Tier-1 `channel_plan_build`, skill `launch-kit`.
- **Content/SEO (Pillar G)**: `content_plan_from_report(report) -> ContentPlan`
  (`metalworks.research.marketing`) — PURE deterministic, zero-key, no LLM. One
  `ContentPage` per cluster (normalized target_phrase, heuristic page_kind,
  real-count `stat_anchors`, FAQ from `ResearchBrief.must_address` verbatim) plus
  a `CitationStrategy` whose `reddit_targets` are real quote permalinks.
  `render_content_markdown` + `render_faq_jsonld` (a mechanical FAQPage stub).
  Makes no ranking promises; never invents a keyword or quote. New contract
  `metalworks.contract.marketing` (`ContentPlan` / `ContentPage` / `FaqItem` /
  `CitationStrategy`). CLI `metalworks research content-plan`, MCP **Tier-1**
  (zero-key) `content_plan_from_report`, skill `content-plan`.
- **Build (Pillar D)**: `build_spec_from_report(deps, report, positioning=None,
  surface="web", *, stack="empty") -> BuildSpec` + `scaffold(spec, report, dest,
  *, base) -> list[Path]` (`metalworks.build`). One LLM call maps demand clusters
  to candidate features; grounding is DETERMINISTIC — each feature is attached to
  its `source_cluster_rank`'s verbatim quotes and DROPPED if that cluster is
  invalid or quote-less (no-cite-no-feature), so the model cannot smuggle in an
  un-grounded feature. Personas derive from the report's audience segments;
  pricing tiers copy through from the report's price evidence (never recomputed).
  An infra error (404/auth) propagates rather than being relabelled a thin-demand
  `partial`. `scaffold` writes a deterministic build harness for the user's OWN
  coding agent — `CLAUDE.md` (cite-or-die Rule 0), `docs/SPEC.md`, a frozen
  `docs/EVIDENCE.md` quote+permalink table, a build-pack of skills
  (`scaffold-startup` / `spec-from-report` / `cite-or-die`), a `cite_or_die.py`
  PostToolUse lint, and `.mcp.json` — but writes NO product code (`--base` is a
  stack hint, not vendored boilerplate). New contract `metalworks.contract.build`
  (`BuildSpec` / `FeatureSpec` / `BuildPersona` / `PricingTier`). CLI `metalworks
  build init`, MCP **Tier-2** `build_spec`, skill `build-spec`.
- **Surface + UX (Pillar C, Design stage)**: `decide_surface(deps, report,
  positioning) -> SurfaceRecommendation` + `build_ux_skeleton(deps, report,
  positioning, surface) -> UxSkeleton` (`metalworks.research.surface`). A FIXED
  five-dimension rubric (where-are-the-users, technical sophistication, usage
  frequency, realtime/hardware, distribution) drives the surface pick; one LLM
  call phrases each dimension's finding + the chosen surface, and the service
  GROUNDS each by cosine-matching to the report's real evidence — a dimension
  with no match is marked `is_assumption`, and `confidence` is service-assigned
  from grounded coverage. UX screens with no backing voice ship `validated=False`
  (an explicit hypothesis). Text + structure only (no pixels); the `DesignBrief`
  handoff is explicitly ungrounded. New contract `metalworks.contract.surface`
  (`SurfaceRecommendation` / `UxSkeleton` / `RubricDimension` / `Screen` /
  `TradeOff` / `DesignBrief`); `Research.competitors` and `.positioning` are both
  real fields now. Surfaced via `metalworks surface <report_id>` CLI, the
  synchronous `surface_recommend` + `ux_skeleton_build` MCP tools, and the
  `surface-and-ux` skill.
- **Landscape (Pillar A)**: `run_competitor_map(deps, report) -> CompetitorMap`
  (`metalworks.research.landscape`) maps the competitive set — direct, adjacent,
  and the mandatory status-quo "do nothing" alternative — with an exploitable,
  EVIDENCED gap per competitor. Four deterministic stages: grounded enumeration
  (names with zero grounding chunks dropped; degrades to an ungrounded structured
  call marked `partial`); per-competitor strength/gap harvest; cosine
  complaint-matching of each gap against the report's real evidence (cluster
  quotes first, then web findings); assemble, dropping any gap with no resolvable
  evidence (no-quote-no-gap). `severity` is service-assigned from the matched
  complaint's distinct-author breadth, never LLM. The status-quo alternative is
  built deterministically from the top clusters (always verbatim-grounded). New
  contract `metalworks.contract.landscape` (`CompetitorMap` / `Competitor` /
  `GapClaim` / `StrengthClaim`), every gap an `EvidenceRef`; `Research.competitors`
  is now a real optional field. Surfaced via the `metalworks competitor-map
  <report_id>` CLI, the synchronous `competitor_map_from_report` MCP tool, and the
  `competitor-map` skill.
- **Positioning (Pillar B)**: `build_positioning_brief(deps, report) -> PositioningBrief`
  (`metalworks.research.synthesis.positioning`) turns a demand report into a
  grounded Dunford wedge + price hypothesis. Wedge SELECTION is deterministic —
  it stands on an `InsightCluster` the web stream is `silent_web`/`disagree` on at
  ≥ MEDIUM signal (a pain competitors miss), ranked by `demand_score`; no white
  space → an honest null brief. Exactly one LLM call phrases the three free-text
  slots (constrained to the Dunford template) and a second pass verifies each
  clause is entailed by its cited quotes (marks the brief `partial` if not). The
  price band is copied through from `PriceFinding`, never recomputed. New
  contract `metalworks.contract.positioning` (`PositioningBrief` / `WedgeClaim` /
  `PriceHypothesis`), every slot an `EvidenceRef`; `Research.positioning` is now a
  real optional field. Surfaced via the `metalworks position <report_id>` CLI,
  the synchronous `positioning_from_report` MCP tool, and the `position-wedge` skill.
- **Supabase mirror reader**: `ArcticMirrorReader` (`metalworks[supabase]`) reads
  the Arctic submission corpus from a Supabase Storage bucket — months from the
  `arctic_shift_pulls` table, shards listed and signed at query time, DuckDB
  reading the signed URLs with `WHERE subreddit`/`id IN` pushdown. A faster
  alternative to the HF mirror that removes HF as a runtime dependency;
  implements `CorpusReader` and is selected at runtime with
  `ARCTIC_SHIFT_SOURCE=mirror`.

### Changed

- `Metalworks.research()` now returns a `Research` bundle instead of a bare
  `DemandReport`; the report is on `.demand` and the grounded evidence on
  `.evidence`. This stabilizes the stage-1 front-door shape before the 0.1.0 tag.
- Renamed the low-level discovery export `generate_reply` → `draft_reply` (the
  MCP tool name is unchanged).
- Cut `SupabaseStores` from the OSS core; hosted store backends bind to the
  same repo protocols downstream. The `[supabase]` extra now scopes the Arctic
  mirror reader (above) instead of the dropped stores.
- The Google adapters respect Vertex's request ceilings: embeddings are batched
  at 100 instances/request (Vertex caps at 250) and chat clamps
  `max_output_tokens` to 65536, so large triage/synthesis calls no longer 400.
- Tightened package public surfaces: demoted internal plumbing out of the
  `reddit` / `research` / `discovery` package `__all__`s (still importable from
  their submodules).

### Notes

- A bare `import metalworks` pulls in no provider SDKs; CI asserts this.
- The fabricated-persona / account-backstory tooling from the source pipeline
  was deliberately not open-sourced. See `USAGE_POLICY.md`.
