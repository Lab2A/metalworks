# Changelog

All notable changes to metalworks are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it
reaches 1.0. Below 1.0, anything outside `metalworks.contract` and the MCP tool
contracts may change in any release.

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
