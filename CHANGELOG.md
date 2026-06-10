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
  and `SupabaseStores` behind `[supabase]` (paginates to exhaustion).
  `TokenCipher` for OAuth tokens at rest. Public conformance suite in
  `metalworks.testing`.
- **Research vertical** (`metalworks.research`): brief planner, Arctic Shift
  corpus reader (HF Parquet submissions + live API comments), hybrid triage,
  clustered synthesis with exact-matched quotes, web research (grounded +
  external), cross-stream triangulation, and `run_research` end to end.
- **Reddit core** (`metalworks.reddit`): rate limiter (token bucket honoring
  Reddit's headers), OAuth + posting on httpx with typed errors, search,
  metrics, inbox classification, subreddit intel, and a deterministic
  compliance gate.

### Notes

- A bare `import metalworks` pulls in no provider SDKs; CI asserts this.
- The fabricated-persona / account-backstory tooling from the source pipeline
  was deliberately not open-sourced. See `USAGE_POLICY.md`.
