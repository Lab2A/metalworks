# metalworks

**Status: pre-release scaffold (0.0.1).** Nothing here is usable yet — the name is
registered and the foundations are being laid in public. Watch the repo.

metalworks is an open-source marketing library: demand research and Reddit
engagement primitives you can embed in your own tools or use directly from
Claude Code and other agents. Built by the team behind [Clique](https://clique.so),
extracted from the production pipeline that powers it.

What's coming (in order):

1. **Contract + protocols** — typed models for briefs and demand reports; small,
   versioned `ChatModel` / `SearchProvider` / `EmbeddingProvider` / repo protocols
   with adapters over official provider SDKs (`pip install metalworks[anthropic]`,
   `[openai]`, `[google]`). Zero provider deps in core.
2. **Research vertical** — conversational brief planner → Reddit corpus
   (historical archive + live API) → triage → clustered demand report with
   verified, permalinked quotes. Provenance is structural, not vibes.
3. **Reddit core** — OAuth, search, subreddit intel, inbox, posting with a
   deterministic compliance gate and built-in rate limiting.
4. **Surfaces** — CLI, MCP server (zero-key data tools + key-gated pipelines),
   and a Claude Code plugin (`/demand-report` with no API keys at all).

Usage policy: this library is for authentic, disclosed engagement. No coordinated
inauthentic behavior, no fake personas, no vote manipulation. The full policy
ships with the first release.

License: MIT.
