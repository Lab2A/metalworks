"""DuckDB-over-Parquet reader for Arctic Shift submission shards.

The submissions corpus reader (DuckDB over Parquet). The default source is
the Hugging Face ``open-index/arctic`` Parquet mirror, read directly over
httpfs:

    hf://datasets/open-index/arctic/data/submissions/<YYYY>/<MM>/*.parquet
    hf://datasets/open-index/arctic/data/comments/<YYYY>/<MM>/*.parquet

Each (year, month) directory holds ~80-100 shards; a multi-month pull
glob-matches all of them and pushes ``WHERE subreddit = ?`` into Parquet
predicate pushdown so DuckDB skips row groups that don't contain the target.

Port changes vs. the source:

- The Supabase Storage *mirror* source (the optional ``[supabase]`` perf tier)
  is dropped. Only the HF/local-Parquet path remains. TODO: a future
  ``ArcticMirrorReader`` can re-add the signed-URL perf tier behind
  ``metalworks[supabase]`` without touching this class.
- ``fetch_submissions_by_ids`` is now a PUBLIC method (the source's hydration
  reached into ``reader._con`` / ``reader._resolve_patterns``). Hydration calls
  the public method instead.
- ``data_root`` is overridable (constructor arg or the module-level
  ``data_root`` default) so tests can point at a LOCAL directory of
  ``.parquet`` files instead of ``hf://``.
- duckdb lives in the ``[arctic]`` extra and is imported lazily inside methods
  (never at module import time); absence raises ``MissingExtraError("arctic")``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from collections.abc import Iterator, Sequence
from typing import Any

from metalworks.errors import MissingExtraError
from metalworks.research.types import MonthRef

logger = logging.getLogger(__name__)

HF_DATASET = "open-index/arctic"
HF_DATA_ROOT = f"hf://datasets/{HF_DATASET}/data"

# Module-level default. A test (or a caller pointing at a local Parquet cache)
# can override this — or pass ``data_root=`` to the constructor — to read from
# a directory of ``.parquet`` files instead of Hugging Face.
data_root: str = HF_DATA_ROOT

# Chunk size for ``id IN (...)`` hydration reads. Keeps the SQL literal and the
# per-query memory bounded when the triage-relevant id set is large.
ID_CHUNK = 1000


def month_glob(content_type: str, m: MonthRef, *, root: str) -> str:
    """Glob pattern for one (content_type, year, month) under ``root``."""
    return f"{root}/{content_type}/{m.path_segment}/*.parquet"


def window_patterns(content_type: str, months: Sequence[MonthRef], *, root: str) -> list[str]:
    """One glob per month — HF's tree API can't brace-expand across path
    segments, so we materialize a pattern per month and let DuckDB union them.
    """
    if not months:
        raise ValueError("at least one month is required")
    return [month_glob(content_type, m, root=root) for m in months]


def _sql_array(patterns: Sequence[str]) -> str:
    """Render glob URLs as a DuckDB SQL string-array literal."""
    return "[" + ", ".join("'" + p.replace("'", "''") + "'" for p in patterns) + "]"


def _id_chunks(ids: Sequence[str], n: int) -> Iterator[list[str]]:
    """Yield ``n``-sized chunks of ids, dropping falsy entries."""
    cleaned = [i for i in ids if i]
    for i in range(0, len(cleaned), n):
        yield cleaned[i : i + n]


class ArcticReader:
    """DuckDB-backed reader for Arctic Shift submission shards.

    Implements the :class:`metalworks.research.deps.CorpusReader` protocol.
    duckdb is loaded lazily on first use; if the ``[arctic]`` extra is not
    installed, the first method that needs DuckDB raises
    :class:`~metalworks.errors.MissingExtraError`.
    """

    def __init__(
        self,
        *,
        memory_limit_gb: int = 4,
        hf_token: str | None = None,
        data_root: str | None = None,
        probe_sleep_s: float = 0.2,
    ) -> None:
        # Resolve the data root at construction so a per-instance override
        # beats the module-level default.
        self._data_root = data_root if data_root is not None else globals()["data_root"]
        self._memory_limit_gb = memory_limit_gb
        # Fall back to the standard HF env tokens so an opt-in HF run clears the
        # public-mirror 429 ceiling without the caller threading a token through.
        self._hf_token = (
            hf_token
            or os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGING_FACE_HUB_TOKEN")
            or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        )
        # Courtesy delay between HF probe requests in ``latest_available_month``.
        # Injectable/zeroable so tests don't sleep.
        self._probe_sleep_s = probe_sleep_s
        self._con: Any = None

    # ── Lazy connection ─────────────────────────────────────────────────

    def _duckdb(self) -> Any:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - exercised via MissingExtra test
            raise MissingExtraError("arctic", package="duckdb") from exc
        return duckdb

    def _is_remote(self) -> bool:
        """True when reading from a network root (HF) that needs httpfs."""
        return "://" in self._data_root and not self._data_root.startswith("file://")

    def _connection(self) -> Any:
        if self._con is not None:
            return self._con
        duckdb = self._duckdb()
        con: Any = duckdb.connect(":memory:")
        if self._is_remote():
            con.execute("INSTALL httpfs;")
            con.execute("LOAD httpfs;")
        con.execute(f"SET memory_limit = '{self._memory_limit_gb}GB';")
        con.execute("SET errors_as_json = true;")
        token = self._hf_token
        if self._is_remote() and token:
            try:
                con.execute("CREATE SECRET hf_token (TYPE huggingface, TOKEN ?);", [token])
                logger.info("ArcticReader: HF auth enabled via token")
            except Exception:
                logger.exception("ArcticReader: HF token secret failed; continuing unauthenticated")
        self._con = con
        return con

    def __enter__(self) -> ArcticReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._con is not None:
            with contextlib.suppress(Exception):
                self._con.close()
            self._con = None

    # ── Pattern resolution ──────────────────────────────────────────────

    def _resolve_patterns(self, content_type: str, months: Sequence[MonthRef]) -> list[str]:
        """Glob patterns DuckDB should read for these months."""
        return window_patterns(content_type, months, root=self._data_root)

    # ── Schema / availability ───────────────────────────────────────────

    def latest_available_month(self, content_type: str = "submissions") -> MonthRef:
        """Most recent month with at least one readable shard.

        Probes backward from the current month. A ~0.2s courtesy sleep between
        probes (configurable via ``probe_sleep_s``) keeps us under HF rate
        limits; set it to 0 in tests.
        """
        from datetime import UTC, datetime

        con = self._connection()
        now = datetime.now(UTC)
        y, m = now.year, now.month
        search_back = 12
        for _ in range(search_back):
            pattern = month_glob(content_type, MonthRef(y, m), root=self._data_root)
            try:
                con.execute(f"SELECT 1 FROM read_parquet('{pattern}') LIMIT 1").fetchone()
                return MonthRef(y, m)
            except Exception:
                pass
            m -= 1
            if m == 0:
                m = 12
                y -= 1
            if self._probe_sleep_s:
                time.sleep(self._probe_sleep_s)
        raise RuntimeError(
            f"No {content_type} shards found in the last {search_back} months from {now:%Y-%m-%d}"
        )

    # ── Pulls ───────────────────────────────────────────────────────────

    def pull_subreddit(
        self,
        *,
        subreddit: str,
        content_type: str,
        months: Sequence[MonthRef],
        select_cols: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield rows for one subreddit across ``months``, newest first.

        Streams via ``fetchmany`` so the full result is never materialized.
        """
        patterns = self._resolve_patterns(content_type, list(months))
        arr = _sql_array(patterns)
        cols = "*" if not select_cols else ", ".join(select_cols)
        limit_clause = f"LIMIT {int(limit)}" if limit else ""
        query = (
            f"SELECT {cols} FROM read_parquet({arr}, union_by_name=true) "
            f"WHERE subreddit = ? ORDER BY created_utc DESC {limit_clause}"
        )
        con = self._connection()
        cur: Any = con.execute(query, [subreddit])
        desc: list[Any] = list(cur.description or [])
        columns = [d[0] for d in desc]
        while True:
            batch: list[Any] = list(cur.fetchmany(1000))
            if not batch:
                break
            for row in batch:
                yield dict(zip(columns, row, strict=False))

    def fetch_submissions_by_ids(
        self, post_ids: Sequence[str], months: Sequence[MonthRef]
    ) -> Iterator[dict[str, Any]]:
        """Yield submission rows whose ``id`` is in ``post_ids``.

        PUBLIC hydration read — replaces the source's reach into
        ``reader._con`` / ``reader._resolve_patterns``. Builds the month-glob
        list and a parameterized ``id IN (...)`` query, chunking large id sets
        so neither the SQL literal nor the per-query memory blows up.
        """
        ids = [i for i in post_ids if i]
        if not ids:
            return
        if not months:
            raise ValueError("fetch_submissions_by_ids: months window required")
        patterns = self._resolve_patterns("submissions", list(months))
        arr = _sql_array(patterns)
        select = "id, subreddit, title, selftext, author, score, num_comments, url, created_utc"
        con = self._connection()
        for chunk in _id_chunks(ids, ID_CHUNK):
            placeholders = ", ".join("?" for _ in chunk)
            query = (
                f"SELECT {select} FROM read_parquet({arr}, union_by_name=true) "
                f"WHERE id IN ({placeholders})"
            )
            cur: Any = con.execute(query, list(chunk))
            desc: list[Any] = list(cur.description or [])
            columns = [d[0] for d in desc]
            rows: list[Any] = list(cur.fetchall())
            for row in rows:
                yield dict(zip(columns, row, strict=False))
