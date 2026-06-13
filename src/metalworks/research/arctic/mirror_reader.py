"""Supabase Storage mirror reader — the ``metalworks[supabase]`` perf tier.

The HF ``open-index/arctic`` mirror (:class:`~metalworks.research.arctic.ArcticReader`)
is rate-limited and slow at scale: a multi-month single-sub pull globs ~400
shards/month over httpfs and ``latest_available_month`` probes month-by-month.
This reader instead reads a Supabase Storage bucket populated by an upstream
mirror job (the layout ``<content_type>/<YYYY>/<MM>/data_NNN.parquet`` + an
``arctic_shift_pulls`` table tracking complete months). It eliminates HF as a
runtime dependency: months come from the table, shards are listed and resolved
to signed URLs at query time, and DuckDB reads them over httpfs with the same
``WHERE subreddit = ?`` / ``id IN (...)`` predicate pushdown.

Implements the :class:`~metalworks.research.deps.CorpusReader` protocol, so it
drops into ``Metalworks(reader=...)`` or ``ResearchDeps(reader=...)`` wherever
``ArcticReader`` is used.

Config (constructor args win over env):

- ``SUPABASE_URL`` / ``SUPABASE_SERVICE_ROLE_KEY`` — the mirror's project.
- ``ARCTIC_SHIFT_MIRROR_BUCKET`` (default ``arctic-shift-mirror``).
- ``ARCTIC_SHIFT_SIGNED_URL_TTL`` seconds (default 3600).

Extras: ``duckdb`` (``[arctic]``) and ``supabase`` (``[supabase]``) are imported
lazily; the first method that needs a missing one raises
:class:`~metalworks.errors.MissingExtraError`.

Perf note: like the HF reader, ``pull_subreddit`` is newest-first
(``ORDER BY created_utc DESC``), which forces a full month scan before the
``LIMIT`` applies — at ~400 shards/month over signed URLs that is minutes, not
seconds. For repeated local runs, pre-stage the subset to a local Parquet and
point :class:`ArcticReader` at it via ``data_root``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from collections.abc import Iterator, Sequence
from functools import partial
from typing import Any

from metalworks.errors import MissingExtraError
from metalworks.research.types import MonthRef

logger = logging.getLogger(__name__)

DEFAULT_BUCKET = "arctic-shift-mirror"
DEFAULT_SIGNED_URL_TTL = 3600
_SIGN_BATCH = 500
_LIST_LIMIT = 100000
ID_CHUNK = 1000


def _sql_array(patterns: Sequence[str]) -> str:
    """Render a list of URLs/globs as a DuckDB SQL string-array literal."""
    return "[" + ", ".join("'" + p.replace("'", "''") + "'" for p in patterns) + "]"


def _id_chunks(ids: Sequence[str], n: int) -> Iterator[list[str]]:
    """Yield ``ids`` in chunks of ``n`` so neither the SQL literal nor the
    per-query memory blows up on a large id set."""
    for i in range(0, len(ids), n):
        yield list(ids[i : i + n])


def _retry(fn: Any, *, what: str, attempts: int = 3, base_delay: float = 2.0) -> Any:
    """Run ``fn`` with exponential backoff — Supabase list/sign calls are
    transient-network-prone at 12-month scale (one slow connection would
    otherwise strand the whole query)."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # retried below, re-raised after the last attempt
            last = exc
            if i + 1 == attempts:
                break
            wait = base_delay * (2**i)
            logger.warning(
                "ArcticMirrorReader: %s failed (%s); retry %d/%d in %.1fs",
                what,
                type(exc).__name__,
                i + 2,
                attempts,
                wait,
            )
            time.sleep(wait)
    assert last is not None
    raise last


class ArcticMirrorReader:
    """CorpusReader over the Supabase ``arctic-shift-mirror`` bucket.

    Pass a pre-built ``client`` (anything exposing the Supabase ``table`` /
    ``storage`` API) to inject a stub in tests; otherwise one is built lazily
    from the environment.
    """

    def __init__(
        self,
        *,
        bucket: str | None = None,
        signed_url_ttl: int | None = None,
        memory_limit_gb: int = 4,
        client: Any = None,
    ) -> None:
        self._bucket = bucket or os.environ.get("ARCTIC_SHIFT_MIRROR_BUCKET") or DEFAULT_BUCKET
        self._ttl = (
            signed_url_ttl
            if signed_url_ttl is not None
            else int(os.environ.get("ARCTIC_SHIFT_SIGNED_URL_TTL") or DEFAULT_SIGNED_URL_TTL)
        )
        self._memory_limit_gb = memory_limit_gb
        self._client = client
        self._con: Any = None

    # ── Lazy deps ───────────────────────────────────────────────────────

    def _connection(self) -> Any:
        if self._con is not None:
            return self._con
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - exercised via MissingExtra test
            raise MissingExtraError("arctic", package="duckdb") from exc
        con: Any = duckdb.connect(":memory:")
        con.execute("INSTALL httpfs;")
        con.execute("LOAD httpfs;")
        con.execute(f"SET memory_limit = '{self._memory_limit_gb}GB';")
        con.execute("SET errors_as_json = true;")
        # Signed-URL reads at scale touch thousands of objects; the httpfs
        # defaults (30s/3 retries) intermittently strand a query on one slow
        # object. Loosen them.
        con.execute("SET http_timeout = 120000;")
        con.execute("SET http_retries = 5;")
        con.execute("SET http_retry_wait_ms = 500;")
        con.execute("SET http_retry_backoff = 2.0;")
        self._con = con
        return con

    def _supabase(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from supabase import create_client
        except ImportError as exc:  # pragma: no cover - exercised via MissingExtra test
            raise MissingExtraError("supabase", package="supabase") from exc
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError(
                "ArcticMirrorReader needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY"
            )
        self._client = create_client(url, key)
        return self._client

    def __enter__(self) -> ArcticMirrorReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._con is not None:
            with contextlib.suppress(Exception):
                self._con.close()
            self._con = None

    # ── Source resolution ───────────────────────────────────────────────

    def latest_available_month(self, content_type: str = "submissions") -> MonthRef:
        """Newest ``complete`` month for ``content_type`` from ``arctic_shift_pulls``."""
        sb: Any = self._supabase()
        resp: Any = (
            sb.table("arctic_shift_pulls")
            .select("year,month")
            .eq("content_type", content_type)
            .eq("status", "complete")
            .order("year", desc=True)
            .order("month", desc=True)
            .limit(1)
            .execute()
        )
        rows: list[Any] = list(getattr(resp, "data", None) or [])
        if not rows:
            raise RuntimeError(
                f"ArcticMirrorReader: no complete {content_type} months in arctic_shift_pulls"
            )
        top = rows[0]
        return MonthRef(int(top["year"]), int(top["month"]))

    def _list_shards(self, sb: Any, prefix: str) -> Any:
        return sb.storage.from_(self._bucket).list(prefix, {"limit": _LIST_LIMIT})

    def _sign(self, sb: Any, chunk: list[str]) -> Any:
        return sb.storage.from_(self._bucket).create_signed_urls(chunk, self._ttl)

    def _resolve_patterns(self, content_type: str, months: Sequence[MonthRef]) -> list[str]:
        """List shards under each month's prefix and batch-sign them to URLs."""
        sb: Any = self._supabase()
        paths: list[str] = []
        for m in months:
            prefix = f"{content_type}/{m.year}/{m.month:02d}"
            # partial binds prefix by value (no loop-var closure); _retry calls it now.
            entries: list[Any] = list(
                _retry(partial(self._list_shards, sb, prefix), what=f"list({prefix})") or []
            )
            paths.extend(
                sorted(
                    f"{prefix}/{e['name']}"
                    for e in entries
                    if str(e.get("name", "")).endswith(".parquet")
                )
            )
        if not paths:
            raise RuntimeError(
                f"ArcticMirrorReader: no shards in bucket={self._bucket} for "
                f"months={[str(m) for m in months]}"
            )
        urls: list[str] = []
        for i in range(0, len(paths), _SIGN_BATCH):
            chunk: list[str] = paths[i : i + _SIGN_BATCH]
            batch: list[Any] = list(
                _retry(partial(self._sign, sb, chunk), what=f"sign({len(chunk)})") or []
            )
            urls.extend(str(item["signedURL"]) for item in batch)
        return urls

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
        """Yield rows for one subreddit across ``months``, newest first."""
        patterns = self._resolve_patterns(content_type, list(months))
        arr = _sql_array(patterns)
        cols = "*" if not select_cols else ", ".join(select_cols)
        limit_clause = f"LIMIT {int(limit)}" if limit else ""
        query = (
            f"SELECT {cols} FROM read_parquet({arr}, union_by_name=true) "
            f"WHERE subreddit = ? ORDER BY created_utc DESC {limit_clause}"
        )
        cur: Any = self._connection().execute(query, [subreddit])
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
        """Yield submission rows whose ``id`` is in ``post_ids`` (chunked)."""
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
            for row in list(cur.fetchall()):
                yield dict(zip(columns, row, strict=False))
