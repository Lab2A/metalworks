"""Typed repository protocols — the storage seam.

Design decision (from plan review, do not regress): the typed repos ARE the
protocol. There is no public generic doc-store — real production tables
are columnar, and a generic put/get cannot bind to them. Each backend
implements these protocols directly. The OSS core ships two zero-infra
backends (memory, sqlite); a hosted backend (e.g. Postgres for a SaaS
deployment) lives downstream and binds to pre-existing columnar schemas via
its own table_map + column codecs — the protocol seam is what makes that
downstream impl possible without changing the core.

Backends own their own query semantics:
- ID-chunk size for IN-style queries is per-backend (a PostgREST-backed impl
  caps ~200; SQLite's parameter ceiling differs).
- A hosted/PostgREST impl MUST paginate to exhaustion (PostgREST silently
  truncates at max-rows with HTTP 200).
- SQLite implementations MUST be safe under the pipeline's thread model
  (synthesis + web research run in a ThreadPoolExecutor).

One object may implement several (or all) of these protocols — structural
typing means `MemoryStores()` satisfies every repo parameter.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field

from metalworks.contract import (
    DemandReport,
    InboxItem,
    Opportunity,
    RedditComment,
    RedditPost,
    ResearchBrief,
    RunSummary,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from metalworks.embeddings import IndexIdentity

_M = TypeVar("_M", bound=BaseModel)

PROTOCOL_VERSION = "1.0"

OpportunityStatus = Literal["new", "approved", "cancelled", "posted"]


class StoredRedditAccount(BaseModel):
    """A connected Reddit account with encrypted-at-rest tokens.

    Token fields hold TokenCipher ciphertext, never plaintext. This model is
    storage-internal and deliberately not part of metalworks.contract (it
    never crosses the wire to UIs or MCP results).
    """

    username: str
    encrypted_access_token: str
    encrypted_refresh_token: str | None = Field(
        default=None,
        description="None when Reddit issued no refresh token (non-permanent grant). "
        "Empty strings are rejected at the OAuth layer, never stored.",
    )
    scopes: list[str] = Field(default_factory=list)
    token_expires_at: float | None = Field(
        default=None, description="Unix timestamp of access-token expiry."
    )
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Fitness facts (karma, age, verified) etc."
    )


@runtime_checkable
class BriefRepo(Protocol):
    """Persistence for immutable, versioned research briefs."""

    def save_brief(self, brief: ResearchBrief) -> None: ...

    def get_brief(self, brief_id: str) -> ResearchBrief | None: ...

    def list_briefs(
        self, *, workspace_id: str = "local", limit: int = 50
    ) -> list[ResearchBrief]: ...


@runtime_checkable
class RunRepo(Protocol):
    """Run lifecycle + finished report persistence."""

    def save_run(self, run: RunSummary) -> None:
        """Insert or update by report_id (status transitions overwrite)."""
        ...

    def get_run(self, report_id: str) -> RunSummary | None: ...

    def list_runs(self, *, brief_id: str | None = None, limit: int = 50) -> list[RunSummary]: ...

    def save_report(self, report: DemandReport) -> None: ...

    def get_report(self, report_id: str) -> DemandReport | None: ...


@runtime_checkable
class CorpusRepo(Protocol):
    """Post-triage corpus persistence (hydration writes, synthesis reads).

    Upserts are keyed on post_id / comment_id and must be idempotent — the
    hydration stage retries batches.
    """

    def upsert_posts(self, posts: Sequence[RedditPost]) -> None: ...

    def upsert_comments(self, comments: Sequence[RedditComment]) -> None: ...

    def get_posts(self, post_ids: Sequence[str]) -> list[RedditPost]: ...

    def get_comments_for_posts(self, post_ids: Sequence[str]) -> list[RedditComment]:
        """ALL comments for the given posts — backends paginate to exhaustion;
        silent truncation here corrupts every downstream count."""
        ...

    def upsert_embeddings(
        self, vectors: Mapping[str, Sequence[float]], *, identity: IndexIdentity
    ) -> None:
        """Idempotently store ``comment_id -> embedding vector``, tagged with the
        embedding model ``identity``. Upserting under a different identity than the
        stored one replaces the index — vectors from different models are
        geometrically incompatible and must not be mixed."""
        ...

    def search_embeddings(
        self, query: Sequence[float], *, k: int, identity: IndexIdentity
    ) -> list[tuple[str, float]]:
        """Brute-force cosine over the stored vectors → the ``k`` nearest
        ``(comment_id, score)`` pairs, score descending. Empty index → ``[]``.
        Raises :class:`~metalworks.errors.EmbeddingModelMismatch` when the stored
        index was built with a different model than ``identity``. Needs the
        ``[research]`` extra (numpy) for the cosine math."""
        ...


@runtime_checkable
class AccountRepo(Protocol):
    def save_account(self, account: StoredRedditAccount) -> None: ...

    def get_account(self, username: str) -> StoredRedditAccount | None: ...

    def list_accounts(self) -> list[StoredRedditAccount]: ...

    def delete_account(self, username: str) -> None: ...


@runtime_checkable
class OpportunityRepo(Protocol):
    def save_opportunities(self, opportunities: Sequence[Opportunity]) -> None: ...

    def opportunity_exists(self, post_url: str) -> bool:
        """Dedup gate: True if any opportunity references this thread. Without
        this check the discovery loop re-burns two LLM calls per seen post."""
        ...

    def list_opportunities(
        self, *, status: OpportunityStatus | None = None, limit: int = 100
    ) -> list[Opportunity]: ...

    def update_opportunity_status(self, opportunity_id: str, status: OpportunityStatus) -> None: ...


@runtime_checkable
class InboxRepo(Protocol):
    def upsert_inbox_items(self, items: Sequence[InboxItem]) -> None: ...

    def list_inbox_items(
        self, *, unread_only: bool = False, limit: int = 100
    ) -> list[InboxItem]: ...

    def mark_inbox_read(self, message_id: str) -> None: ...


class StoredArtifact(BaseModel):
    """A persisted Tier-2 pillar output + its provenance stamp.

    The artifact itself is any contract model (PositioningBrief, MarketingSite,
    ContentPlan, …) serialized into ``payload_json``. The stamp — ``report_id`` +
    ``generated_at`` — is what makes staleness detectable: when research re-runs
    and mints a new ``report_id``, a snapshot whose ``report_id`` no longer matches
    the project's latest run is flagged stale (per Decision §9.1). ``parse`` rebuilds
    the typed artifact.
    """

    project_id: str
    report_id: str
    stage: str = Field(description="Arc stage: 'design' | 'launch' | 'growth' | ….")
    kind: str = Field(description="Artifact kind, e.g. 'positioning' | 'site' | 'content_plan'.")
    generated_at: datetime
    payload_json: str = Field(description="The pillar artifact, serialized as JSON.")

    def parse(self, model: type[_M]) -> _M:
        """Rebuild the typed artifact from ``payload_json``."""
        return model.model_validate_json(self.payload_json)


@runtime_checkable
class ArtifactStore(Protocol):
    """Tier-2 derived-artifact persistence, keyed ``(project_id, report_id, stage,
    kind)``. One small protocol that lets every downstream stage persist without a
    shared container type — pillars stay pure functions.

    Persist-only-latest: ``get_latest`` returns the most recent artifact of a kind;
    history is the file/git layer, not this API. The default backend is a
    :class:`~metalworks.stores.FileStore` (markdown+json on disk); hosted backends
    bind to the same protocol downstream.
    """

    def save_artifact(
        self, project_id: str, report_id: str, stage: str, kind: str, obj: BaseModel
    ) -> StoredArtifact:
        """Persist ``obj`` as the latest artifact of ``kind`` (overwriting any prior
        latest) and return the stored envelope."""
        ...

    def get_latest(self, project_id: str, kind: str) -> StoredArtifact | None: ...

    def list_artifacts(self, project_id: str) -> list[StoredArtifact]: ...
