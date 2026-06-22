# Changelog

All notable changes to metalworks are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it
reaches 1.0. Below 1.0, anything outside `metalworks.contract` and the MCP tool
contracts may change in any release.

## [Unreleased]

### Added

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
