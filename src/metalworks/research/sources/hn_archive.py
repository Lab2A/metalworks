"""``HackerNewsArchiveSource`` — a bulk, offline :class:`ItemSource` over the HN archive.

Where :mod:`metalworks.research.sources.hackernews` talks to the live HN Algolia
search API, this connector reads the **Hugging Face ``open-index/hacker-news``
Parquet archive** with DuckDB-over-httpfs — the Hacker News analogue of
:class:`~metalworks.research.arctic.reader.ArcticReader`. The whole of HN (stories
*and* comments, 2006→present) lives in monthly Parquet files::

    hf://datasets/open-index/hacker-news/data/<YYYY>/<YYYY>-<MM>.parquet

One file per month, every item type in the same file. The columns we use::

    id uint32 · type int8 (1=story, 2=comment) · by string · time timestamp
    text string (HTML) · url string · score int32 · title string
    descendants int32 (thread size) · parent uint32 · kids list<uint32>
    deleted uint8 · dead uint8

Stories are filtered to a query by a keyword match on title/text (DuckDB pushes
the month partition; the keyword scan is the coarse candidate set the pipeline
then triages — same shape as Arctic pulling a whole subreddit). Comments are read
from the SAME archive, fully offline: each story's thread is walked breadth-first
down its ``kids`` (child-id) lists and flattened into :class:`CorpusComment`s
parented to the story.

``data_root`` is overridable (constructor arg / module default) so a local slice
materialized by ``scripts/load_hn_corpus.py`` is read with no ``hf://`` access —
the fast, offline path. DuckDB lives in the ``[arctic]`` extra (it is just
``duckdb``); absence raises :class:`~metalworks.errors.MissingExtraError`.

``query`` is a free-text search string; ``window.months`` drives which monthly
files are read (HN is month-partitioned, like Arctic).
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import logging
import re
import time as _time
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.errors import MissingExtraError
from metalworks.research.sources import SourceWindow, register_source
from metalworks.research.types import MonthRef

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = logging.getLogger(__name__)

HN_HF_DATASET = "open-index/hacker-news"
HN_HF_DATA_ROOT = f"hf://datasets/{HN_HF_DATASET}/data"

# Module-level default; override per-instance with ``data_root=`` or point this
# at a local directory of monthly ``.parquet`` files (the offline path).
data_root: str = HN_HF_DATA_ROOT

# HN item types in the archive's `type` column.
_TYPE_STORY = 1
_TYPE_COMMENT = 2

# Safety bounds on the comment-tree walk (a thread is finite, but cap the work so
# a pathological pull can't scan forever).
_MAX_COMMENT_ROUNDS = 25
_ID_CHUNK = 1000
_DEAD_TEXT = ("[flagged]", "[dead]", "[deleted]", "[removed]")


def _month_file(root: str, m: MonthRef) -> str:
    """Path to one monthly Parquet file: ``<root>/<YYYY>/<YYYY>-<MM>.parquet``."""
    return f"{root}/{m.year:04d}/{m.year:04d}-{m.month:02d}.parquet"


def _sql_array(paths: Sequence[str]) -> str:
    return "[" + ", ".join("'" + p.replace("'", "''") + "'" for p in paths) + "]"


def _tokens(query: str) -> list[str]:
    """Lowercase alphanumeric tokens of ``query`` for the keyword filter."""
    out: list[str] = []
    cur: list[str] = []
    for ch in query.lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    # Drop 1-char tokens — too noisy as a LIKE filter.
    return [t for t in out if len(t) > 1]


# ── boundary normalization (mirrors the live HN connector) ───────────────────
_TAG_RE = re.compile(r"<[^>]+>")
_PARA_RE = re.compile(r"\s*</?p\s*/?>\s*", re.IGNORECASE)
_MULTI_NL_RE = re.compile(r"\n{2,}")


def _hash_author(author: str | None, *, salt: str) -> str | None:
    """Stable, non-reversible author id; a missing author → tombstone (None)."""
    if not author:
        return None
    h = hashlib.sha256(f"{salt}:{author.lower()}".encode()).hexdigest()
    return f"u_{h[:16]}"


def _ts_to_dt(ts: Any) -> datetime | None:
    """The archive's ``time`` column is a DuckDB TIMESTAMP (→ datetime); accept
    epoch seconds / ISO strings too, for robustness."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _clean_html(text: str | None) -> str:
    """HN item text is HTML: convert ``<p>`` to newlines, strip other tags, unescape."""
    if not text:
        return ""
    text = _PARA_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _MULTI_NL_RE.sub("\n", text)
    return html.unescape(text).strip()


class HackerNewsArchiveReader:
    """DuckDB-backed reader for the ``open-index/hacker-news`` Parquet archive.

    DuckDB is imported lazily; without the ``[arctic]`` extra (which provides
    ``duckdb``) the first read raises :class:`MissingExtraError`. A single in-memory
    connection is reused across reads and closed by :meth:`close` / the context
    manager. Mirrors :class:`~metalworks.research.arctic.reader.ArcticReader`'s
    connection scaffolding.
    """

    def __init__(
        self,
        *,
        memory_limit_gb: int = 4,
        hf_token: str | None = None,
        data_root: str | None = None,
        probe_sleep_s: float = 0.2,
    ) -> None:
        self._data_root = data_root if data_root is not None else globals()["data_root"]
        self._memory_limit_gb = memory_limit_gb
        self._hf_token = hf_token
        self._probe_sleep_s = probe_sleep_s
        self._con: Any = None

    def _duckdb(self) -> Any:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - exercised via MissingExtra test
            raise MissingExtraError("arctic", package="duckdb") from exc
        return duckdb

    def _is_remote(self) -> bool:
        return "://" in self._data_root and not self._data_root.startswith("file://")

    def _connection(self) -> Any:
        if self._con is not None:
            return self._con
        duckdb = self._duckdb()
        con: Any = duckdb.connect(":memory:")
        if self._is_remote():
            con.execute("INSTALL httpfs;")
            con.execute("LOAD httpfs;")
            if self._hf_token:
                with contextlib.suppress(Exception):
                    con.execute(
                        "CREATE SECRET hf_token (TYPE huggingface, TOKEN ?);", [self._hf_token]
                    )
        con.execute(f"SET memory_limit = '{self._memory_limit_gb}GB';")
        con.execute("SET errors_as_json = true;")
        self._con = con
        return con

    def __enter__(self) -> HackerNewsArchiveReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._con is not None:
            with contextlib.suppress(Exception):
                self._con.close()
            self._con = None

    # ── availability ─────────────────────────────────────────────────────────

    def latest_available_month(self) -> MonthRef:
        """Most recent month with a readable Parquet file (probes back 18 months)."""
        con = self._connection()
        now = datetime.now(UTC)
        y, m = now.year, now.month
        for _ in range(18):
            path = _month_file(self._data_root, MonthRef(y, m))
            try:
                con.execute(f"SELECT 1 FROM read_parquet('{path}') LIMIT 1").fetchone()
                return MonthRef(y, m)
            except Exception:
                pass
            m -= 1
            if m == 0:
                m, y = 12, y - 1
            if self._probe_sleep_s:
                _time.sleep(self._probe_sleep_s)
        raise RuntimeError(f"No HN archive shards found in the last 18 months from {now:%Y-%m-%d}")

    # ── reads ──────────────────────────────────────────────────────────────────

    def _existing_month_files(self, months: Sequence[MonthRef]) -> list[str]:
        """Month paths that actually read (skip empty/missing months so a glob over
        a sparse local slice doesn't error on an absent file)."""
        con = self._connection()
        out: list[str] = []
        for m in months:
            path = _month_file(self._data_root, m)
            try:
                con.execute(f"SELECT 1 FROM read_parquet('{path}') LIMIT 1").fetchone()
                out.append(path)
            except Exception:
                continue
        return out

    def pull_stories(
        self, *, query: str, months: Sequence[MonthRef], limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield story rows matching ``query`` across ``months``, highest-score first."""
        files = self._existing_month_files(months)
        if not files:
            return
        arr = _sql_array(files)
        toks = _tokens(query)
        where = [f"type = {_TYPE_STORY}", "coalesce(deleted, 0) = 0", "coalesce(dead, 0) = 0"]
        params: list[Any] = []
        if toks:
            ors: list[str] = []
            for t in toks:
                ors.append("lower(coalesce(title, '')) LIKE ?")
                ors.append("lower(coalesce(text, '')) LIKE ?")
                params.extend([f"%{t}%", f"%{t}%"])
            where.append("(" + " OR ".join(ors) + ")")
        cols = 'id, "by", time, text, url, score, title, descendants'
        limit_clause = f"LIMIT {int(limit)}" if limit else ""
        sql = (
            f"SELECT {cols} FROM read_parquet({arr}, union_by_name=true) "
            f"WHERE {' AND '.join(where)} ORDER BY score DESC NULLS LAST {limit_clause}"
        )
        con = self._connection()
        cur: Any = con.execute(sql, params)
        desc: list[Any] = list(cur.description or [])
        columns: list[str] = [str(d[0]) for d in desc]
        while True:
            batch: list[Any] = list(cur.fetchmany(1000))
            if not batch:
                break
            for row in batch:
                yield dict(zip(columns, row, strict=False))

    def comment_threads(
        self, story_ids: Sequence[str], months: Sequence[MonthRef]
    ) -> dict[str, list[dict[str, Any]]]:
        """Walk each story's comment tree (breadth-first over ``kids``) within
        ``months``; return ``{story_id: [comment rows]}``.

        Reads are batched per BFS level (``id IN (...)``), so a thread costs one
        scan per depth level, not per comment. ``kids`` of a dead/deleted node are
        still walked, so a live reply under a removed parent survives.
        """
        files = self._existing_month_files(months)
        roots = [s for s in story_ids if s]
        result: dict[str, list[dict[str, Any]]] = {s: [] for s in roots}
        if not files or not roots:
            return result
        arr = _sql_array(files)
        con: Any = self._connection()

        # Seed the frontier from each story's direct kids.
        root_of: dict[int, str] = {}
        frontier: deque[int] = deque()

        def _seed(ids: Sequence[str]) -> None:
            numeric = [int(s) for s in ids if str(s).isdigit()]
            for chunk in _chunked(numeric, _ID_CHUNK):
                ph = ", ".join("?" for _ in chunk)
                sql = (
                    f"SELECT id, kids FROM read_parquet({arr}, union_by_name=true) "
                    f"WHERE id IN ({ph})"
                )
                rows: list[Any] = list(con.execute(sql, list(chunk)).fetchall())
                for row in rows:
                    sid = str(row[0])
                    kids: list[Any] = list(row[1] or [])
                    for kid in kids:
                        ki = int(kid)
                        if ki not in root_of:
                            root_of[ki] = sid
                            frontier.append(ki)

        _seed(roots)

        rounds = 0
        seen: set[int] = set()
        while frontier and rounds < _MAX_COMMENT_ROUNDS:
            rounds += 1
            level = [cid for cid in frontier if cid not in seen]
            frontier.clear()
            seen.update(level)
            for chunk in _chunked(level, _ID_CHUNK):
                ph = ", ".join("?" for _ in chunk)
                sql = (
                    'SELECT id, "by", time, text, parent, kids, type, dead, deleted '
                    f"FROM read_parquet({arr}, union_by_name=true) WHERE id IN ({ph})"
                )
                cur: Any = con.execute(sql, list(chunk))
                desc: list[Any] = list(cur.description or [])
                columns: list[str] = [str(d[0]) for d in desc]
                for raw in list(cur.fetchall()):
                    row: dict[str, Any] = dict(zip(columns, raw, strict=False))
                    root = root_of.get(int(row["id"]))
                    if root is None:
                        continue
                    if int(row.get("type") or _TYPE_COMMENT) == _TYPE_COMMENT:
                        result[root].append(row)
                    child_ids: list[Any] = list(row.get("kids") or [])
                    for kid in child_ids:
                        ki = int(kid)
                        if ki not in root_of:
                            root_of[ki] = root
                            frontier.append(ki)
        return result


def _chunked(items: Sequence[int], n: int) -> Iterator[list[int]]:
    for i in range(0, len(items), n):
        yield list(items[i : i + n])


class HackerNewsArchiveSource:
    """:class:`ItemSource` over the offline ``open-index/hacker-news`` Parquet archive."""

    source_id = "hackernews_archive"

    def __init__(
        self,
        *,
        reader: HackerNewsArchiveReader | None = None,
        author_salt: str = "metalworks-local",
        **reader_kwargs: Any,
    ) -> None:
        self._reader = reader if reader is not None else HackerNewsArchiveReader(**reader_kwargs)
        self._salt = author_salt
        # The window the last pull used — comments_for reads the same months
        # (the pipeline always pulls before fetching comments on one instance).
        self._window_months: tuple[MonthRef, ...] = ()

    # ── pull (stories → CorpusRecord) ──────────────────────────────────────────

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        months = list(window.months) or list(self.latest_window().months)
        self._window_months = tuple(months)
        for row in self._reader.pull_stories(query=query, months=months, limit=limit):
            rec = self._record_from_row(row)
            if rec is not None:
                yield rec

    def _record_from_row(self, row: dict[str, Any]) -> CorpusRecord | None:
        rid = row.get("id")
        if rid is None:
            return None
        rid = str(rid)
        text = _clean_html(row.get("text")) or str(row.get("url") or "")
        score = int(row.get("score") or 0)
        return CorpusRecord(
            id=rid,
            source="hackernews",
            source_id=rid,
            url=f"https://news.ycombinator.com/item?id={rid}",
            title=str(row.get("title") or ""),
            text=text,
            author_hash=_hash_author(row.get("by"), salt=self._salt),
            engagement=score,
            created_at=_ts_to_dt(row.get("time")),
            extra={
                "num_comments": int(row.get("descendants") or 0),
                "points": score,
                "objectID": rid,
            },
        )

    # ── comments (offline tree → CorpusComment) ────────────────────────────────

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """One comment batch per story id, walked from the same archive (offline)."""
        return self._iter_comments(record_ids)

    def _iter_comments(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]]:
        ids = [r for r in record_ids if r]
        months = list(self._window_months) or list(self.latest_window().months)
        threads = self._reader.comment_threads(ids, months)
        for rid in record_ids:
            rows = threads.get(rid, [])
            batch: list[CorpusComment] = []
            for row in rows:
                c = self._comment_from_row(row, parent_record=rid)
                if c is not None:
                    batch.append(c)
            yield batch

    def _comment_from_row(self, row: dict[str, Any], *, parent_record: str) -> CorpusComment | None:
        if int(row.get("dead") or 0) or int(row.get("deleted") or 0):
            return None
        cid = row.get("id")
        if cid is None:
            return None
        cid = str(cid)
        text = _clean_html(row.get("text"))
        if not text or text in _DEAD_TEXT:
            return None
        return CorpusComment(
            id=cid,
            parent_id=parent_record,
            source="hackernews",
            url=f"https://news.ycombinator.com/item?id={cid}",
            text=text,
            author_hash=_hash_author(row.get("by"), salt=self._salt) or "",
            engagement=0,
            created_at=_ts_to_dt(row.get("time")),
            extra={"objectID": cid, "parent_id_native": row.get("parent")},
        )

    # ── window ─────────────────────────────────────────────────────────────────

    def latest_window(self) -> SourceWindow:
        anchor = self._reader.latest_available_month()
        return SourceWindow(months=(anchor,))


def _factory(**kwargs: Any) -> HackerNewsArchiveSource:
    return HackerNewsArchiveSource(**kwargs)


# Self-register on import (append-friendly registry; mirrors arctic.py / hackernews.py).
register_source("hackernews_archive", _factory)
register_source("hn_archive", _factory)


__all__ = ["HackerNewsArchiveReader", "HackerNewsArchiveSource"]
