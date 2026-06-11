---
title: "Protocols"
description: "The versioned ChatModel, SearchProvider, EmbeddingProvider, and storage-repo protocols metalworks owns."
---

The protocols metalworks owns. They are versioned as a unit
(`metalworks.PROTOCOLS_VERSION`); minor versions add keyword-only parameters
with defaults, major versions break. Adapters declare which version they
implement, and the conformance suites in `metalworks.testing` are the contract.

## ChatModel

```python
class ChatModel(Protocol):
    protocol_version: ClassVar[str]
    model_id: str
    capabilities: ChatCapabilities  # native_structured, tool_calls, native_grounding, thinking

    def complete_text(self, *, system: str, user: str, max_tokens: int = 1024,
                      temperature: float = 0.7, thinking_budget: int = 0,
                      timeout_s: float = 120.0) -> TextResult: ...

    def complete_structured(self, *, system: str, user: str, output_model: type[T],
                            max_tokens: int = 1024, temperature: float = 0.7,
                            thinking_budget: int = 0, timeout_s: float = 120.0) -> T: ...
```

`thinking_budget` is in tokens; adapters map it to their provider's mechanism.
Dispatch on `capabilities.native_grounding`, never `isinstance`.

## GroundedChatModel

```python
class GroundedChatModel(Protocol):
    def complete_grounded(self, *, system: str, user: str, max_tokens: int = 2048,
                          temperature: float = 0.7, timeout_s: float = 180.0) -> GroundedResult: ...
```

`GroundedResult` carries `text`, `chunks: tuple[GroundingChunk, ...]`, and
`supports: tuple[GroundingSupport, ...]`. Support spans are **character**
offsets into `text` (adapters convert provider byte offsets), so finding-to-
citation overlap bucketing is correct for non-ASCII output.

## SearchProvider

```python
class SearchProvider(Protocol):
    protocol_version: ClassVar[str]
    provider_id: str
    def search(self, *, query: str, max_results: int = 10,
               recency_days: int | None = None) -> list[SearchResult]: ...
```

External search (Exa, Tavily) is a separate interface from chat. Model-native
grounding lives on `GroundedChatModel`. The research web stream prefers internal
grounding and falls back to an external `SearchProvider` + structured synthesis.

## EmbeddingProvider

```python
class EmbeddingProvider(Protocol):
    protocol_version: ClassVar[str]
    model_id: str
    dim: int
    def embed(self, texts: Sequence[str], *,
              task: Literal["document", "query"] = "document") -> list[list[float]]: ...
```

Anything that persists vectors stores an `IndexIdentity` (model id + dim) and
hard-fails with `EmbeddingModelMismatch` on a mismatch. Vectors from different
models are geometrically incompatible; same-dimension swaps degrade retrieval
silently, so the guard is a hard error, not a warning.

## Storage repos

Typed repositories, not a generic document store (production tables are
columnar). One backend object implements as many as it supports.

```python
class CorpusRepo(Protocol):
    def upsert_posts(self, posts: Sequence[RedditPost]) -> None: ...
    def upsert_comments(self, comments: Sequence[RedditComment]) -> None: ...
    def get_posts(self, post_ids: Sequence[str]) -> list[RedditPost]: ...
    def get_comments_for_posts(self, post_ids: Sequence[str]) -> list[RedditComment]: ...
```

`BriefRepo`, `RunRepo`, `AccountRepo`, `OpportunityRepo`, and `InboxRepo` follow
the same shape. Backends shipped in core: `MemoryStores` and `SqliteStores`
(WAL, serialized writer). Hosted backends (Postgres/PostgREST) are a custom
store you implement downstream — see [how-to-custom-store](how-to-custom-store).
Verify any backend with `metalworks.testing.check_all_repos`.

## Errors

Every error carries an actionable `fix` and a machine-readable envelope used by
the MCP tools:

```python
err.envelope()  # {"error_code": ..., "message": ..., "fix": ..., "docs_url": ...}
```
