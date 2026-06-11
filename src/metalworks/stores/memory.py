"""In-memory backend implementing every repo protocol. Zero infra, zero deps.

The default for tests and throwaway runs; also the reference semantics the
conformance suite holds every other backend to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metalworks.contract import (
    DemandReport,
    InboxItem,
    Opportunity,
    RedditComment,
    RedditPost,
    ResearchBrief,
    RunSummary,
)
from metalworks.embeddings import IndexIdentity
from metalworks.errors import EmbeddingModelMismatch
from metalworks.stores.repos import OpportunityStatus, StoredRedditAccount
from metalworks.stores.vectors import check_dims, cosine_topk

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class MemoryStores:
    """Satisfies BriefRepo, RunRepo, CorpusRepo, AccountRepo, OpportunityRepo,
    InboxRepo via structural typing."""

    def __init__(self) -> None:
        self._briefs: dict[str, ResearchBrief] = {}
        self._runs: dict[str, RunSummary] = {}
        self._reports: dict[str, DemandReport] = {}
        self._posts: dict[str, RedditPost] = {}
        self._comments: dict[str, RedditComment] = {}
        self._accounts: dict[str, StoredRedditAccount] = {}
        self._opportunities: dict[str, Opportunity] = {}
        self._inbox: dict[str, InboxItem] = {}
        self._embeddings: dict[str, list[float]] = {}
        self._embedding_identity: IndexIdentity | None = None

    # ── BriefRepo ──

    def save_brief(self, brief: ResearchBrief) -> None:
        self._briefs[brief.brief_id] = brief.model_copy(deep=True)

    def get_brief(self, brief_id: str) -> ResearchBrief | None:
        found = self._briefs.get(brief_id)
        return found.model_copy(deep=True) if found else None

    def list_briefs(self, *, workspace_id: str = "local", limit: int = 50) -> list[ResearchBrief]:
        out = [
            b.model_copy(deep=True) for b in self._briefs.values() if b.workspace_id == workspace_id
        ]
        out.sort(key=lambda b: (b.version, b.brief_id), reverse=True)
        return out[:limit]

    # ── RunRepo ──

    def save_run(self, run: RunSummary) -> None:
        self._runs[run.report_id] = run.model_copy(deep=True)

    def get_run(self, report_id: str) -> RunSummary | None:
        found = self._runs.get(report_id)
        return found.model_copy(deep=True) if found else None

    def list_runs(self, *, brief_id: str | None = None, limit: int = 50) -> list[RunSummary]:
        runs = [
            r.model_copy(deep=True)
            for r in self._runs.values()
            if brief_id is None or r.brief_id == brief_id
        ]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    def save_report(self, report: DemandReport) -> None:
        self._reports[report.report_id] = report.model_copy(deep=True)

    def get_report(self, report_id: str) -> DemandReport | None:
        found = self._reports.get(report_id)
        return found.model_copy(deep=True) if found else None

    # ── CorpusRepo ──

    def upsert_posts(self, posts: Sequence[RedditPost]) -> None:
        for post in posts:
            self._posts[post.post_id] = post.model_copy(deep=True)

    def upsert_comments(self, comments: Sequence[RedditComment]) -> None:
        for comment in comments:
            self._comments[comment.comment_id] = comment.model_copy(deep=True)

    def get_posts(self, post_ids: Sequence[str]) -> list[RedditPost]:
        wanted = set(post_ids)
        return [p.model_copy(deep=True) for pid, p in self._posts.items() if pid in wanted]

    def get_comments_for_posts(self, post_ids: Sequence[str]) -> list[RedditComment]:
        wanted = set(post_ids)
        return [c.model_copy(deep=True) for c in self._comments.values() if c.post_id in wanted]

    def upsert_embeddings(
        self, vectors: Mapping[str, Sequence[float]], *, identity: IndexIdentity
    ) -> None:
        check_dims(vectors, identity.dim)
        if self._embedding_identity != identity:
            self._embeddings.clear()  # model changed → rebuild the index
            self._embedding_identity = identity
        for corpus_id, vector in vectors.items():
            self._embeddings[corpus_id] = list(vector)

    def search_embeddings(
        self, query: Sequence[float], *, k: int, identity: IndexIdentity
    ) -> list[tuple[str, float]]:
        if self._embedding_identity is None:
            return []
        if self._embedding_identity != identity:
            raise EmbeddingModelMismatch(
                index_model=f"{self._embedding_identity.embedding_model_id} "
                f"(dim={self._embedding_identity.dim})",
                current_model=f"{identity.embedding_model_id} (dim={identity.dim})",
            )
        return cosine_topk(query, self._embeddings, k)

    def get_embeddings(
        self, ids: Sequence[str], *, identity: IndexIdentity
    ) -> dict[str, list[float]]:
        if self._embedding_identity != identity:
            return {}  # index built with a different model → all misses
        return {cid: list(self._embeddings[cid]) for cid in ids if cid in self._embeddings}

    # ── AccountRepo ──

    def save_account(self, account: StoredRedditAccount) -> None:
        self._accounts[account.username] = account.model_copy(deep=True)

    def get_account(self, username: str) -> StoredRedditAccount | None:
        found = self._accounts.get(username)
        return found.model_copy(deep=True) if found else None

    def list_accounts(self) -> list[StoredRedditAccount]:
        return [a.model_copy(deep=True) for a in self._accounts.values()]

    def delete_account(self, username: str) -> None:
        self._accounts.pop(username, None)

    # ── OpportunityRepo ──

    def save_opportunities(self, opportunities: Sequence[Opportunity]) -> None:
        for opp in opportunities:
            self._opportunities[opp.opportunity_id] = opp.model_copy(deep=True)

    def opportunity_exists(self, post_url: str) -> bool:
        return any(o.post.url == post_url for o in self._opportunities.values())

    def list_opportunities(
        self, *, status: OpportunityStatus | None = None, limit: int = 100
    ) -> list[Opportunity]:
        out = [
            o.model_copy(deep=True)
            for o in self._opportunities.values()
            if status is None or o.status == status
        ]
        return out[:limit]

    def update_opportunity_status(self, opportunity_id: str, status: OpportunityStatus) -> None:
        opp = self._opportunities.get(opportunity_id)
        if opp is not None:
            self._opportunities[opportunity_id] = opp.model_copy(update={"status": status})

    # ── InboxRepo ──

    def upsert_inbox_items(self, items: Sequence[InboxItem]) -> None:
        for item in items:
            self._inbox[item.message_id] = item.model_copy(deep=True)

    def list_inbox_items(self, *, unread_only: bool = False, limit: int = 100) -> list[InboxItem]:
        out = [
            i.model_copy(deep=True) for i in self._inbox.values() if not unread_only or not i.read
        ]
        return out[:limit]

    def mark_inbox_read(self, message_id: str) -> None:
        item = self._inbox.get(message_id)
        if item is not None:
            self._inbox[message_id] = item.model_copy(update={"read": True})
