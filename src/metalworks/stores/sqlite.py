"""SQLite backend — the zero-infra persistent default.

Concurrency posture (from plan review): the research pipeline reads and
writes across a ThreadPoolExecutor, so this backend uses WAL mode plus a
process-wide serialized-writer policy (one RLock around every operation on a
single check_same_thread=False connection). busy_timeout is set as a second
line of defense against OTHER processes holding the file.

Each row stores the pydantic payload as JSON plus the columns queries
filter/sort on. IN-style queries chunk at 500 ids (SQLite's default
parameter ceiling is 999 on older builds; 500 leaves headroom).

The corpus is a source-neutral, durable store (Phase 1b): records/comments are
the generic :class:`CorpusRecord` / :class:`CorpusComment` spine, with the
source-specific tail in an ``extra`` JSON column. Reddit is mapped on at ingest
via the Reddit-named shims; new sources add their own mappers without a schema
change.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from metalworks.contract import (
    CorpusComment,
    CorpusRecord,
    DemandReport,
    InboxItem,
    Opportunity,
    RedditComment,
    RedditPost,
    ResearchBrief,
    RunSummary,
)
from metalworks.embeddings import IndexIdentity
from metalworks.errors import EmbeddingModelMismatch, StoreError
from metalworks.stores.corpus_mapping import (
    corpus_comments_from_reddit_comments,
    records_from_reddit_posts,
    reddit_comment_from_corpus_comment,
    reddit_post_from_record,
)
from metalworks.stores.repos import OpportunityStatus, StoredRedditAccount
from metalworks.stores.vectors import blob_to_vector, check_dims, cosine_topk, vector_to_blob

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

_ID_CHUNK = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS briefs (
    brief_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
    version INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_briefs_ws ON briefs(workspace_id);
CREATE TABLE IF NOT EXISTS runs (
    report_id TEXT PRIMARY KEY, brief_id TEXT,
    created_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_runs_brief ON runs(brief_id);
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
    url TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL,
    author_hash TEXT, engagement INTEGER NOT NULL, created_at TEXT,
    extra TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_records_source ON records(source);
CREATE TABLE IF NOT EXISTS corpus_comments (
    id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, source TEXT NOT NULL,
    url TEXT NOT NULL, text TEXT NOT NULL, author_hash TEXT NOT NULL,
    engagement INTEGER NOT NULL, created_at TEXT, extra TEXT NOT NULL,
    payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_corpus_comments_parent ON corpus_comments(parent_id);
CREATE TABLE IF NOT EXISTS accounts (
    username TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id TEXT PRIMARY KEY, post_url TEXT NOT NULL,
    status TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_opps_url ON opportunities(post_url);
CREATE INDEX IF NOT EXISTS idx_opps_status ON opportunities(status);
CREATE TABLE IF NOT EXISTS inbox (
    message_id TEXT PRIMARY KEY, read INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS embeddings (
    corpus_id TEXT PRIMARY KEY, vector BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS embedding_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1), model_id TEXT NOT NULL, dim INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS run_checkpoints (
    run_id TEXT NOT NULL, stage TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY (run_id, stage));
"""


def _chunks(ids: Sequence[str]) -> Iterator[Sequence[str]]:
    for i in range(0, len(ids), _ID_CHUNK):
        yield ids[i : i + _ID_CHUNK]


def _json(extra: dict[str, Any]) -> str:
    """Serialize the corpus ``extra`` tail for the denormalized column. The
    authoritative copy is the full ``payload`` JSON; this column is for queries."""
    return json.dumps(extra, default=str, sort_keys=True)


class SqliteStores:
    """Satisfies all six repo protocols. One file, one connection, WAL."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._lock = threading.RLock()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._con = sqlite3.connect(self._path, check_same_thread=False)
        except (OSError, sqlite3.Error) as exc:
            raise StoreError(
                f"Cannot open SQLite store at {self._path}: {exc}",
                fix="Check the directory exists and is writable, or pass a different path.",
            ) from exc
        with self._lock:
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA busy_timeout=5000")
            self._con.executescript(_SCHEMA)
            self._con.commit()

    def close(self) -> None:
        with self._lock:
            self._con.close()

    # ── BriefRepo ──

    def save_brief(self, brief: ResearchBrief) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO briefs (brief_id, workspace_id, version, payload) "
                "VALUES (?, ?, ?, ?)",
                (brief.brief_id, brief.workspace_id, brief.version, brief.model_dump_json()),
            )
            self._con.commit()

    def get_brief(self, brief_id: str) -> ResearchBrief | None:
        with self._lock:
            row = self._con.execute(
                "SELECT payload FROM briefs WHERE brief_id = ?", (brief_id,)
            ).fetchone()
        return ResearchBrief.model_validate_json(row[0]) if row else None

    def list_briefs(self, *, workspace_id: str = "local", limit: int = 50) -> list[ResearchBrief]:
        with self._lock:
            rows = self._con.execute(
                "SELECT payload FROM briefs WHERE workspace_id = ? "
                "ORDER BY version DESC, brief_id DESC LIMIT ?",
                (workspace_id, limit),
            ).fetchall()
        return [ResearchBrief.model_validate_json(r[0]) for r in rows]

    # ── RunRepo ──

    def save_run(self, run: RunSummary) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO runs (report_id, brief_id, created_at, payload) "
                "VALUES (?, ?, ?, ?)",
                (run.report_id, run.brief_id, run.created_at.isoformat(), run.model_dump_json()),
            )
            self._con.commit()

    def get_run(self, report_id: str) -> RunSummary | None:
        with self._lock:
            row = self._con.execute(
                "SELECT payload FROM runs WHERE report_id = ?", (report_id,)
            ).fetchone()
        return RunSummary.model_validate_json(row[0]) if row else None

    def list_runs(self, *, brief_id: str | None = None, limit: int = 50) -> list[RunSummary]:
        with self._lock:
            if brief_id is None:
                rows = self._con.execute(
                    "SELECT payload FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = self._con.execute(
                    "SELECT payload FROM runs WHERE brief_id = ? ORDER BY created_at DESC LIMIT ?",
                    (brief_id, limit),
                ).fetchall()
        return [RunSummary.model_validate_json(r[0]) for r in rows]

    def save_report(self, report: DemandReport) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO reports (report_id, payload) VALUES (?, ?)",
                (report.report_id, report.model_dump_json()),
            )
            self._con.commit()

    def get_report(self, report_id: str) -> DemandReport | None:
        with self._lock:
            row = self._con.execute(
                "SELECT payload FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        return DemandReport.model_validate_json(row[0]) if row else None

    # ── CheckpointRepo ──

    def save_checkpoint(self, run_id: str, stage: str, payload: str) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO run_checkpoints (run_id, stage, payload) VALUES (?, ?, ?)",
                (run_id, stage, payload),
            )
            self._con.commit()

    def get_checkpoint(self, run_id: str, stage: str) -> str | None:
        with self._lock:
            row = self._con.execute(
                "SELECT payload FROM run_checkpoints WHERE run_id = ? AND stage = ?",
                (run_id, stage),
            ).fetchone()
        return row[0] if row else None

    def clear_checkpoints(self, run_id: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM run_checkpoints WHERE run_id = ?", (run_id,))
            self._con.commit()

    # ── CorpusRepo: generic record/comment surface (authoritative) ──

    def upsert_records(self, records: Sequence[CorpusRecord]) -> None:
        with self._lock:
            self._con.executemany(
                "INSERT OR REPLACE INTO records "
                "(id, source, source_id, url, title, text, author_hash, engagement, "
                "created_at, extra, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        r.id,
                        r.source,
                        r.source_id,
                        r.url,
                        r.title,
                        r.text,
                        r.author_hash,
                        r.engagement,
                        r.created_at.isoformat() if r.created_at else None,
                        _json(r.extra),
                        r.model_dump_json(),
                    )
                    for r in records
                ],
            )
            self._con.commit()

    def upsert_corpus_comments(self, comments: Sequence[CorpusComment]) -> None:
        with self._lock:
            self._con.executemany(
                "INSERT OR REPLACE INTO corpus_comments "
                "(id, parent_id, source, url, text, author_hash, engagement, "
                "created_at, extra, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.id,
                        c.parent_id,
                        c.source,
                        c.url,
                        c.text,
                        c.author_hash,
                        c.engagement,
                        c.created_at.isoformat() if c.created_at else None,
                        _json(c.extra),
                        c.model_dump_json(),
                    )
                    for c in comments
                ],
            )
            self._con.commit()

    def get_records(self, record_ids: Sequence[str]) -> list[CorpusRecord]:
        out: list[CorpusRecord] = []
        with self._lock:
            for chunk in _chunks(record_ids):
                marks = ",".join("?" * len(chunk))
                rows = self._con.execute(
                    f"SELECT payload FROM records WHERE id IN ({marks})",
                    tuple(chunk),
                ).fetchall()
                out.extend(CorpusRecord.model_validate_json(r[0]) for r in rows)
        return out

    def get_comments_for_records(self, record_ids: Sequence[str]) -> list[CorpusComment]:
        out: list[CorpusComment] = []
        with self._lock:
            for chunk in _chunks(record_ids):
                marks = ",".join("?" * len(chunk))
                rows = self._con.execute(
                    f"SELECT payload FROM corpus_comments WHERE parent_id IN ({marks})",
                    tuple(chunk),
                ).fetchall()
                out.extend(CorpusComment.model_validate_json(r[0]) for r in rows)
        return out

    # ── CorpusRepo: Reddit-named shims (map onto the generic surface) ──

    def upsert_posts(self, posts: Sequence[RedditPost]) -> None:
        self.upsert_records(records_from_reddit_posts(posts))

    def upsert_comments(self, comments: Sequence[RedditComment]) -> None:
        self.upsert_corpus_comments(corpus_comments_from_reddit_comments(comments))

    def get_posts(self, post_ids: Sequence[str]) -> list[RedditPost]:
        return [reddit_post_from_record(r) for r in self.get_records(post_ids)]

    def get_comments_for_posts(self, post_ids: Sequence[str]) -> list[RedditComment]:
        return [
            reddit_comment_from_corpus_comment(c) for c in self.get_comments_for_records(post_ids)
        ]

    def upsert_embeddings(
        self, vectors: Mapping[str, Sequence[float]], *, identity: IndexIdentity
    ) -> None:
        check_dims(vectors, identity.dim)
        with self._lock:
            row = self._con.execute(
                "SELECT model_id, dim FROM embedding_meta WHERE id = 1"
            ).fetchone()
            changed = row is not None and (
                row[0] != identity.embedding_model_id or row[1] != identity.dim
            )
            if changed:
                # Model changed: vectors from different models don't mix — rebuild.
                self._con.execute("DELETE FROM embeddings")
                self._con.execute("DELETE FROM embedding_meta")
                row = None
            if row is None:
                self._con.execute(
                    "INSERT INTO embedding_meta (id, model_id, dim) VALUES (1, ?, ?)",
                    (identity.embedding_model_id, identity.dim),
                )
            self._con.executemany(
                "INSERT INTO embeddings (corpus_id, vector) VALUES (?, ?) "
                "ON CONFLICT(corpus_id) DO UPDATE SET vector = excluded.vector",
                [(corpus_id, vector_to_blob(vec)) for corpus_id, vec in vectors.items()],
            )
            self._con.commit()

    def search_embeddings(
        self, query: Sequence[float], *, k: int, identity: IndexIdentity
    ) -> list[tuple[str, float]]:
        with self._lock:
            meta = self._con.execute(
                "SELECT model_id, dim FROM embedding_meta WHERE id = 1"
            ).fetchone()
            if meta is None:
                return []
            if meta[0] != identity.embedding_model_id or meta[1] != identity.dim:
                raise EmbeddingModelMismatch(
                    index_model=f"{meta[0]} (dim={meta[1]})",
                    current_model=f"{identity.embedding_model_id} (dim={identity.dim})",
                )
            rows = self._con.execute("SELECT corpus_id, vector FROM embeddings").fetchall()
        vectors = {corpus_id: blob_to_vector(blob) for corpus_id, blob in rows}
        return cosine_topk(query, vectors, k)

    def get_embeddings(
        self, ids: Sequence[str], *, identity: IndexIdentity
    ) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        with self._lock:
            meta = self._con.execute(
                "SELECT model_id, dim FROM embedding_meta WHERE id = 1"
            ).fetchone()
            if meta is None or meta[0] != identity.embedding_model_id or meta[1] != identity.dim:
                return {}  # no index, or built with a different model → all misses
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                rows = self._con.execute(
                    f"SELECT corpus_id, vector FROM embeddings WHERE corpus_id IN ({marks})",
                    tuple(chunk),
                ).fetchall()
                out.update({corpus_id: blob_to_vector(blob) for corpus_id, blob in rows})
        return out

    # ── AccountRepo ──

    def save_account(self, account: StoredRedditAccount) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO accounts (username, payload) VALUES (?, ?)",
                (account.username, account.model_dump_json()),
            )
            self._con.commit()

    def get_account(self, username: str) -> StoredRedditAccount | None:
        with self._lock:
            row = self._con.execute(
                "SELECT payload FROM accounts WHERE username = ?", (username,)
            ).fetchone()
        return StoredRedditAccount.model_validate_json(row[0]) if row else None

    def list_accounts(self) -> list[StoredRedditAccount]:
        with self._lock:
            rows = self._con.execute("SELECT payload FROM accounts").fetchall()
        return [StoredRedditAccount.model_validate_json(r[0]) for r in rows]

    def delete_account(self, username: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM accounts WHERE username = ?", (username,))
            self._con.commit()

    # ── OpportunityRepo ──

    def save_opportunities(self, opportunities: Sequence[Opportunity]) -> None:
        with self._lock:
            self._con.executemany(
                "INSERT OR REPLACE INTO opportunities "
                "(opportunity_id, post_url, status, payload) VALUES (?, ?, ?, ?)",
                [
                    (o.opportunity_id, o.post.url, o.status, o.model_dump_json())
                    for o in opportunities
                ],
            )
            self._con.commit()

    def opportunity_exists(self, post_url: str) -> bool:
        with self._lock:
            row = self._con.execute(
                "SELECT 1 FROM opportunities WHERE post_url = ? LIMIT 1", (post_url,)
            ).fetchone()
        return row is not None

    def list_opportunities(
        self, *, status: OpportunityStatus | None = None, limit: int = 100
    ) -> list[Opportunity]:
        with self._lock:
            if status is None:
                rows = self._con.execute(
                    "SELECT payload FROM opportunities LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = self._con.execute(
                    "SELECT payload FROM opportunities WHERE status = ? LIMIT ?",
                    (status, limit),
                ).fetchall()
        return [Opportunity.model_validate_json(r[0]) for r in rows]

    def update_opportunity_status(self, opportunity_id: str, status: OpportunityStatus) -> None:
        with self._lock:
            row = self._con.execute(
                "SELECT payload FROM opportunities WHERE opportunity_id = ?",
                (opportunity_id,),
            ).fetchone()
            if row is None:
                return
            opp = Opportunity.model_validate_json(row[0]).model_copy(update={"status": status})
            self._con.execute(
                "UPDATE opportunities SET status = ?, payload = ? WHERE opportunity_id = ?",
                (status, opp.model_dump_json(), opportunity_id),
            )
            self._con.commit()

    # ── InboxRepo ──

    def upsert_inbox_items(self, items: Sequence[InboxItem]) -> None:
        with self._lock:
            self._con.executemany(
                "INSERT OR REPLACE INTO inbox (message_id, read, payload) VALUES (?, ?, ?)",
                [(i.message_id, int(i.read), i.model_dump_json()) for i in items],
            )
            self._con.commit()

    def list_inbox_items(self, *, unread_only: bool = False, limit: int = 100) -> list[InboxItem]:
        with self._lock:
            if unread_only:
                rows = self._con.execute(
                    "SELECT payload FROM inbox WHERE read = 0 LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = self._con.execute("SELECT payload FROM inbox LIMIT ?", (limit,)).fetchall()
        return [InboxItem.model_validate_json(r[0]) for r in rows]

    def mark_inbox_read(self, message_id: str) -> None:
        with self._lock:
            row = self._con.execute(
                "SELECT payload FROM inbox WHERE message_id = ?", (message_id,)
            ).fetchone()
            if row is None:
                return
            item = InboxItem.model_validate_json(row[0]).model_copy(update={"read": True})
            self._con.execute(
                "UPDATE inbox SET read = 1, payload = ? WHERE message_id = ?",
                (item.model_dump_json(), message_id),
            )
            self._con.commit()
