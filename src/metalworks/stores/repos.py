"""Typed repository protocols — the storage seam.

Design decision (from plan review, do not regress): the typed repos ARE the
protocol. There is no public generic doc-store — Clique's production tables
are columnar, and a generic put/get cannot bind to them. Each backend
(memory, sqlite, supabase) implements these protocols directly; the Supabase
backend additionally takes a table_map + column codecs so it can bind to
pre-existing schemas at migration time.

Backends own their own query semantics:
- ID-chunk size for IN-style queries is per-backend (PostgREST ~200,
  SQLite parameter ceiling differs).
- Supabase implementations MUST paginate to exhaustion (PostgREST silently
  truncates at max-rows with HTTP 200).
- SQLite implementations MUST be safe under the pipeline's thread model
  (synthesis + web research run in a ThreadPoolExecutor).

One object may implement several (or all) of these protocols — structural
typing means `MemoryStores()` satisfies every repo parameter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

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
    from collections.abc import Sequence

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
