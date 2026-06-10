"""Supabase/PostgREST backend (extra: [supabase]).

Iron rule encoded here: PostgREST silently truncates result sets at its
max-rows setting (default 1000) with HTTP 200 — every read in this backend
paginates with .range() until exhaustion. The conformance suite's
>1000-rows case exists to catch any regression of this.

Schema: metalworks-native tables (payload jsonb + the columns queries filter
on); `SCHEMA_SQL` below bootstraps them. `table_map` renames logical →
physical tables so hosted deployments can place them anywhere. Binding to
PRE-EXISTING columnar schemas (the Clique migration) is done by subclassing
per-repo methods with column codecs — that lands with the migration, not
here.

IN-style filters chunk at 200 ids (PostgREST URL-length constraint).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from metalworks.contract import (
    DemandReport,
    InboxItem,
    Opportunity,
    RedditComment,
    RedditPost,
    ResearchBrief,
    RunSummary,
)
from metalworks.errors import MissingExtraError, StoreError
from metalworks.stores.repos import OpportunityStatus, StoredRedditAccount

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_ID_CHUNK = 200
_PAGE = 1000

DEFAULT_TABLES = {
    "briefs": "metalworks_briefs",
    "runs": "metalworks_runs",
    "reports": "metalworks_reports",
    "posts": "metalworks_posts",
    "comments": "metalworks_comments",
    "accounts": "metalworks_accounts",
    "opportunities": "metalworks_opportunities",
    "inbox": "metalworks_inbox",
}

SCHEMA_SQL = """
create table if not exists metalworks_briefs (
  brief_id text primary key, workspace_id text not null,
  version integer not null, payload jsonb not null);
create index if not exists idx_mw_briefs_ws on metalworks_briefs(workspace_id);
create table if not exists metalworks_runs (
  report_id text primary key, brief_id text,
  created_at timestamptz not null, payload jsonb not null);
create index if not exists idx_mw_runs_brief on metalworks_runs(brief_id);
create table if not exists metalworks_reports (
  report_id text primary key, payload jsonb not null);
create table if not exists metalworks_posts (
  post_id text primary key, payload jsonb not null);
create table if not exists metalworks_comments (
  comment_id text primary key, post_id text not null, payload jsonb not null);
create index if not exists idx_mw_comments_post on metalworks_comments(post_id);
create table if not exists metalworks_accounts (
  username text primary key, payload jsonb not null);
create table if not exists metalworks_opportunities (
  opportunity_id text primary key, post_url text not null,
  status text not null, payload jsonb not null);
create index if not exists idx_mw_opps_url on metalworks_opportunities(post_url);
create table if not exists metalworks_inbox (
  message_id text primary key, read boolean not null default false, payload jsonb not null);
"""


def _chunks(ids: Sequence[str]) -> Iterator[Sequence[str]]:
    for i in range(0, len(ids), _ID_CHUNK):
        yield ids[i : i + _ID_CHUNK]


class SupabaseStores:
    """Satisfies all six repo protocols against a Supabase project.

    Pass an existing supabase-py client, or url+key to construct one.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        url: str | None = None,
        key: str | None = None,
        table_map: dict[str, str] | None = None,
    ):
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise MissingExtraError("supabase") from exc
            if not url or not key:
                raise StoreError(
                    "SupabaseStores needs either a client or url+key.",
                    fix="Pass client=, or url= + key= (service-role key for server-side use).",
                )
            client = create_client(url, key)
        self._c: Any = client
        self._t = {**DEFAULT_TABLES, **(table_map or {})}

    # ── helpers ──

    def _select_all(
        self,
        table: str,
        *,
        eq: tuple[str, object] | None = None,
        in_filter: tuple[str, Sequence[str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate to exhaustion. A fresh query is built each page because
        PostgREST builders are single-use. Filters are passed as data (not a
        callable) so the whole path stays statically typed despite the
        duck-typed client."""
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            query: Any = self._c.table(self._t[table]).select("payload")
            if eq is not None:
                query = query.eq(eq[0], eq[1])
            if in_filter is not None:
                query = query.in_(in_filter[0], list(in_filter[1]))
            resp: Any = query.range(offset, offset + _PAGE - 1).execute()
            rows = cast("list[dict[str, Any]]", resp.data or [])
            out.extend(rows)
            if len(rows) < _PAGE:
                return out
            offset += _PAGE

    @staticmethod
    def _rows(resp: Any) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", resp.data or [])

    @staticmethod
    def _payload(row: dict[str, Any]) -> str:
        payload = row["payload"]
        return payload if isinstance(payload, str) else json.dumps(payload)

    def _upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
        if rows:
            self._c.table(self._t[table]).upsert(rows, on_conflict=on_conflict).execute()

    # ── BriefRepo ──

    def save_brief(self, brief: ResearchBrief) -> None:
        self._upsert(
            "briefs",
            [
                {
                    "brief_id": brief.brief_id,
                    "workspace_id": brief.workspace_id,
                    "version": brief.version,
                    "payload": json.loads(brief.model_dump_json()),
                }
            ],
            "brief_id",
        )

    def get_brief(self, brief_id: str) -> ResearchBrief | None:
        rows = self._select_all("briefs", eq=("brief_id", brief_id))
        return ResearchBrief.model_validate_json(self._payload(rows[0])) if rows else None

    def list_briefs(self, *, workspace_id: str = "local", limit: int = 50) -> list[ResearchBrief]:
        resp = (
            self._c.table(self._t["briefs"])
            .select("payload")
            .eq("workspace_id", workspace_id)
            .order("version", desc=True)
            .order("brief_id", desc=True)
            .limit(limit)
            .execute()
        )
        return [ResearchBrief.model_validate_json(self._payload(r)) for r in self._rows(resp)]

    # ── RunRepo ──

    def save_run(self, run: RunSummary) -> None:
        self._upsert(
            "runs",
            [
                {
                    "report_id": run.report_id,
                    "brief_id": run.brief_id,
                    "created_at": run.created_at.isoformat(),
                    "payload": json.loads(run.model_dump_json()),
                }
            ],
            "report_id",
        )

    def get_run(self, report_id: str) -> RunSummary | None:
        rows = self._select_all("runs", eq=("report_id", report_id))
        return RunSummary.model_validate_json(self._payload(rows[0])) if rows else None

    def list_runs(self, *, brief_id: str | None = None, limit: int = 50) -> list[RunSummary]:
        query = self._c.table(self._t["runs"]).select("payload")
        if brief_id is not None:
            query = query.eq("brief_id", brief_id)
        resp = query.order("created_at", desc=True).limit(limit).execute()
        return [RunSummary.model_validate_json(self._payload(r)) for r in self._rows(resp)]

    def save_report(self, report: DemandReport) -> None:
        self._upsert(
            "reports",
            [{"report_id": report.report_id, "payload": json.loads(report.model_dump_json())}],
            "report_id",
        )

    def get_report(self, report_id: str) -> DemandReport | None:
        rows = self._select_all("reports", eq=("report_id", report_id))
        return DemandReport.model_validate_json(self._payload(rows[0])) if rows else None

    # ── CorpusRepo ──

    def upsert_posts(self, posts: Sequence[RedditPost]) -> None:
        self._upsert(
            "posts",
            [{"post_id": p.post_id, "payload": json.loads(p.model_dump_json())} for p in posts],
            "post_id",
        )

    def upsert_comments(self, comments: Sequence[RedditComment]) -> None:
        self._upsert(
            "comments",
            [
                {
                    "comment_id": c.comment_id,
                    "post_id": c.post_id,
                    "payload": json.loads(c.model_dump_json()),
                }
                for c in comments
            ],
            "comment_id",
        )

    def get_posts(self, post_ids: Sequence[str]) -> list[RedditPost]:
        out: list[RedditPost] = []
        for chunk in _chunks(post_ids):
            ids = list(chunk)
            rows = self._select_all("posts", in_filter=("post_id", ids))
            out.extend(RedditPost.model_validate_json(self._payload(r)) for r in rows)
        return out

    def get_comments_for_posts(self, post_ids: Sequence[str]) -> list[RedditComment]:
        out: list[RedditComment] = []
        for chunk in _chunks(post_ids):
            ids = list(chunk)
            rows = self._select_all("comments", in_filter=("post_id", ids))
            out.extend(RedditComment.model_validate_json(self._payload(r)) for r in rows)
        return out

    # ── AccountRepo ──

    def save_account(self, account: StoredRedditAccount) -> None:
        self._upsert(
            "accounts",
            [{"username": account.username, "payload": json.loads(account.model_dump_json())}],
            "username",
        )

    def get_account(self, username: str) -> StoredRedditAccount | None:
        rows = self._select_all("accounts", eq=("username", username))
        return StoredRedditAccount.model_validate_json(self._payload(rows[0])) if rows else None

    def list_accounts(self) -> list[StoredRedditAccount]:
        rows = self._select_all("accounts")
        return [StoredRedditAccount.model_validate_json(self._payload(r)) for r in rows]

    def delete_account(self, username: str) -> None:
        self._c.table(self._t["accounts"]).delete().eq("username", username).execute()

    # ── OpportunityRepo ──

    def save_opportunities(self, opportunities: Sequence[Opportunity]) -> None:
        self._upsert(
            "opportunities",
            [
                {
                    "opportunity_id": o.opportunity_id,
                    "post_url": o.post.url,
                    "status": o.status,
                    "payload": json.loads(o.model_dump_json()),
                }
                for o in opportunities
            ],
            "opportunity_id",
        )

    def opportunity_exists(self, post_url: str) -> bool:
        resp = (
            self._c.table(self._t["opportunities"])
            .select("opportunity_id")
            .eq("post_url", post_url)
            .limit(1)
            .execute()
        )
        return bool(resp.data)

    def list_opportunities(
        self, *, status: OpportunityStatus | None = None, limit: int = 100
    ) -> list[Opportunity]:
        query = self._c.table(self._t["opportunities"]).select("payload")
        if status is not None:
            query = query.eq("status", status)
        resp = query.limit(limit).execute()
        return [Opportunity.model_validate_json(self._payload(r)) for r in self._rows(resp)]

    def update_opportunity_status(self, opportunity_id: str, status: OpportunityStatus) -> None:
        rows = self._select_all("opportunities", eq=("opportunity_id", opportunity_id))
        if not rows:
            return
        opp = Opportunity.model_validate_json(self._payload(rows[0])).model_copy(
            update={"status": status}
        )
        self._c.table(self._t["opportunities"]).update(
            {"status": status, "payload": json.loads(opp.model_dump_json())}
        ).eq("opportunity_id", opportunity_id).execute()

    # ── InboxRepo ──

    def upsert_inbox_items(self, items: Sequence[InboxItem]) -> None:
        self._upsert(
            "inbox",
            [
                {
                    "message_id": i.message_id,
                    "read": i.read,
                    "payload": json.loads(i.model_dump_json()),
                }
                for i in items
            ],
            "message_id",
        )

    def list_inbox_items(self, *, unread_only: bool = False, limit: int = 100) -> list[InboxItem]:
        query = self._c.table(self._t["inbox"]).select("payload")
        if unread_only:
            query = query.eq("read", False)
        resp = query.limit(limit).execute()
        return [InboxItem.model_validate_json(self._payload(r)) for r in self._rows(resp)]

    def mark_inbox_read(self, message_id: str) -> None:
        rows = self._select_all("inbox", eq=("message_id", message_id))
        if not rows:
            return
        item = InboxItem.model_validate_json(self._payload(rows[0])).model_copy(
            update={"read": True}
        )
        self._c.table(self._t["inbox"]).update(
            {"read": True, "payload": json.loads(item.model_dump_json())}
        ).eq("message_id", message_id).execute()
