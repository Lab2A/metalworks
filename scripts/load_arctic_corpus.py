#!/usr/bin/env python3
"""Build your own local Reddit corpus from the Arctic Shift mirror.

metalworks does *not* hinge on any one data source. The library reads
submissions through the small ``CorpusReader`` protocol — Arctic Shift is just
the default, swappable implementation (see ``docs/custom-corpus.md``). This
standalone script demotes Arctic to exactly that: a *sample loader* you run
yourself to materialize a local Parquet corpus, which you then point metalworks
at with ``ArcticReader(data_root=...)``.

What it does
------------
1.  Pull submissions for one or more subreddits across an N-month window from
    the Hugging Face ``open-index/arctic`` Parquet mirror, writing them into a
    local layout that :class:`metalworks.research.arctic.reader.ArcticReader`
    can read verbatim::

        <out>/submissions/<YYYY>/<MM>/<subreddit>.parquet

2.  (Optional, ``--comments``) Fetch the live comment tree for each pulled
    submission from the public Arctic Shift API and write it alongside::

        <out>/comments/<YYYY>/<MM>/<subreddit>.jsonl

Run it
------
::

    python scripts/load_arctic_corpus.py --subreddit Supplements --months 3 --out ./corpus

Then point metalworks at it::

    from metalworks import Metalworks
    from metalworks.research.arctic import ArcticReader

    mw = Metalworks(reader=ArcticReader(data_root="./corpus"))
    mw.research("a focus supplement without the jitters", subreddits=["Supplements"])

Dependencies
------------
Standard library + ``duckdb`` only (``pip install "metalworks[arctic]"``, or just
``pip install duckdb``). The optional ``--comments`` step uses ``urllib`` from the
stdlib — no extra install. This script imports nothing from metalworks at module
load time, so it works as a copy-paste reference even outside the package.

The DuckDB query, the ``hf://`` root, and the ``<root>/submissions/<YYYY>/<MM>``
glob layout below intentionally mirror ``ArcticReader`` so the two stay
read-compatible. We replicate the minimal query here (rather than importing the
reader to *pull*) so the script is fully self-contained; we only optionally
import the reader at the end to sanity-check that it can read what we wrote.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── Arctic Shift mirror constants (kept in sync with ArcticReader) ───────────

HF_DATASET = "open-index/arctic"
HF_DATA_ROOT = f"hf://datasets/{HF_DATASET}/data"

# Public Arctic Shift comment API. The HF mirror's comment tree is stale
# (stops ~2021-04), so current comments come from the live API instead.
ARCTIC_SHIFT_API = "https://arctic-shift.photon-reddit.com/api"

# Columns we materialize. Matches the shape ArcticReader / hydration expect.
SELECT_COLS = (
    "id",
    "subreddit",
    "title",
    "selftext",
    "author",
    "score",
    "num_comments",
    "url",
    "created_utc",
)

# Be polite to the comment API: ~1.5 req/s, like ArcticShiftApiClient.
COMMENT_MIN_INTERVAL_S = 1.0 / 1.5


class MonthRef:
    """An immutable year/month reference into the monthly-partitioned corpus.

    A tiny standalone copy of ``metalworks.research.types.MonthRef`` so this
    script has no import-time dependency on the package.
    """

    __slots__ = ("month", "year")

    def __init__(self, year: int, month: int) -> None:
        self.year = year
        self.month = month

    @property
    def path_segment(self) -> str:
        return f"{self.year:04d}/{self.month:02d}"

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def months_back(n: int, *, anchor: MonthRef) -> list[MonthRef]:
    """``n`` months ending at (and including) ``anchor``, oldest first."""
    out: list[MonthRef] = []
    y, m = anchor.year, anchor.month
    for _ in range(max(1, n)):
        out.append(MonthRef(y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


# ── DuckDB plumbing (mirrors ArcticReader's query) ──────────────────────────


def _require_duckdb() -> Any:
    try:
        import duckdb
    except ImportError:
        sys.exit(
            "error: duckdb is required.\n"
            '  Install it with:  pip install "metalworks[arctic]"\n'
            "  (or just:         pip install duckdb)"
        )
    return duckdb


def _connect(duckdb: Any, *, memory_limit_gb: int, hf_token: str | None) -> Any:
    """Open an in-memory DuckDB connection wired for httpfs/HF reads."""
    con = duckdb.connect(":memory:")
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")
    con.execute(f"SET memory_limit = '{memory_limit_gb}GB';")
    con.execute("SET errors_as_json = true;")
    if hf_token:
        try:
            con.execute("CREATE SECRET hf_token (TYPE huggingface, TOKEN ?);", [hf_token])
        except Exception as exc:
            print(f"  warn: HF token secret failed ({exc}); continuing unauthenticated")
    return con


def _month_glob(content_type: str, m: MonthRef, *, root: str) -> str:
    """Glob for one (content_type, year, month) under ``root``.

    Identical to ``ArcticReader``'s layout so the corpus we write here is
    read-compatible with the reader.
    """
    return f"{root}/{content_type}/{m.path_segment}/*.parquet"


def latest_available_month(con: Any, *, probe_sleep_s: float = 0.2) -> MonthRef:
    """Most recent month with at least one readable submissions shard on HF.

    Probes backward from the current month (up to 12 months). Mirrors
    ``ArcticReader.latest_available_month``.
    """
    now = datetime.now(UTC)
    y, m = now.year, now.month
    for _ in range(12):
        pattern = _month_glob("submissions", MonthRef(y, m), root=HF_DATA_ROOT)
        try:
            con.execute(f"SELECT 1 FROM read_parquet('{pattern}') LIMIT 1").fetchone()
            return MonthRef(y, m)
        except Exception:
            pass
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        if probe_sleep_s:
            time.sleep(probe_sleep_s)
    raise RuntimeError(f"No submissions shards found in the last 12 months from {now:%Y-%m-%d}")


def pull_month(
    con: Any,
    *,
    subreddit: str,
    month: MonthRef,
    out_root: Path,
    limit: int | None,
) -> int:
    """Pull one subreddit-month from HF into a local Parquet file.

    Pushes ``WHERE subreddit = ?`` into the Parquet scan (predicate pushdown)
    so DuckDB skips row groups that don't contain the target — the same trick
    ``ArcticReader.pull_subreddit`` relies on. Returns the row count written
    (0 if the month had no matching rows; no file is written in that case).
    """
    src_glob = _month_glob("submissions", month, root=HF_DATA_ROOT)
    cols = ", ".join(SELECT_COLS)
    limit_clause = f"LIMIT {int(limit)}" if limit else ""

    out_dir = out_root / "submissions" / f"{month.year:04d}" / f"{month.month:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    # One file per subreddit so multiple subreddits can share a month dir.
    out_file = out_dir / f"{_safe_name(subreddit)}.parquet"
    out_sql = str(out_file).replace("'", "''")

    # COPY (SELECT ...) TO ... streams straight to Parquet — never materializes
    # the full result in Python.
    copy_sql = (
        f"COPY (SELECT {cols} FROM read_parquet('{src_glob}', union_by_name=true) "
        f"WHERE subreddit = ? ORDER BY created_utc DESC {limit_clause}) "
        f"TO '{out_sql}' (FORMAT PARQUET)"
    )
    con.execute(copy_sql, [subreddit])

    count_row = con.execute(f"SELECT count(*) FROM read_parquet('{out_sql}')").fetchone()
    n = int(count_row[0]) if count_row else 0
    if n == 0:
        # Drop the empty file so the local glob stays clean.
        out_file.unlink(missing_ok=True)
    return n


def list_pulled_ids(out_root: Path, *, subreddit: str, month: MonthRef, con: Any) -> list[str]:
    """Read back the submission ids we just wrote for one subreddit-month."""
    out_file = (
        out_root
        / "submissions"
        / f"{month.year:04d}"
        / f"{month.month:02d}"
        / f"{_safe_name(subreddit)}.parquet"
    )
    if not out_file.exists():
        return []
    out_sql = str(out_file).replace("'", "''")
    rows = con.execute(f"SELECT id FROM read_parquet('{out_sql}')").fetchall()
    return [str(r[0]) for r in rows if r and r[0]]


# ── Comment fetching (stdlib urllib against the live Arctic Shift API) ───────


def _fetch_comment_tree(link_id: str, *, timeout_s: float) -> list[dict[str, Any]]:
    """Fetch + flatten the comment tree for one submission id.

    Walks Reddit's nested Listing shape into a flat list of comment dicts —
    the same flattening ``ArcticShiftApiClient.comments_tree`` does.
    """
    params = urllib.parse.urlencode({"link_id": link_id})
    url = f"{ARCTIC_SHIFT_API}/comments/tree?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "metalworks-sample-loader/0.1"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    wrapped = payload["data"] if isinstance(payload, dict) else payload
    out: list[dict[str, Any]] = []
    _flatten_listing(wrapped, out)
    return out


def _flatten_listing(nodes: Any, out: list[dict[str, Any]]) -> None:
    """Depth-first flatten of Reddit's nested ``t1``/``Listing`` tree."""
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("kind")
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        if kind == "t1":
            replies = data.pop("replies", None)
            out.append(data)
            if isinstance(replies, dict):
                child = replies.get("data", {})
                if isinstance(child, dict):
                    _flatten_listing(child.get("children", []), out)
        elif kind == "Listing":
            _flatten_listing(data.get("children", []), out)


def fetch_comments(
    out_root: Path,
    *,
    subreddit: str,
    month: MonthRef,
    ids: list[str],
    timeout_s: float,
) -> int:
    """Fetch comments for ``ids`` and append them to a per-month JSONL file.

    Returns the number of comment rows written. Failures on a single link are
    logged and skipped (the pull still succeeds).
    """
    if not ids:
        return 0
    out_dir = out_root / "comments" / f"{month.year:04d}" / f"{month.month:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{_safe_name(subreddit)}.jsonl"

    written = 0
    last_request_at = 0.0
    with out_file.open("w", encoding="utf-8") as fh:
        for i, link_id in enumerate(ids, start=1):
            wait = COMMENT_MIN_INTERVAL_S - (time.monotonic() - last_request_at)
            if wait > 0:
                time.sleep(wait)
            last_request_at = time.monotonic()
            try:
                tree = _fetch_comment_tree(link_id, timeout_s=timeout_s)
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
                print(f"    skip comments for {link_id}: {type(exc).__name__}: {exc}")
                continue
            for comment in tree:
                fh.write(json.dumps(comment) + "\n")
                written += 1
            if i % 25 == 0:
                print(f"    …comments for {i}/{len(ids)} submissions")
    if written == 0:
        out_file.unlink(missing_ok=True)
    return written


# ── Helpers ─────────────────────────────────────────────────────────────────


def _safe_name(name: str) -> str:
    """Filesystem-safe filename stem for a subreddit."""
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in name) or "subreddit"


def _verify_readable(out_root: Path) -> str:
    """Best-effort: confirm ArcticReader can read what we wrote.

    Imports the public reader only if metalworks is installed. Returns a short
    status string for the summary; never raises.
    """
    try:
        from metalworks.research.arctic import ArcticReader
    except Exception:
        return "skipped (metalworks not importable here)"
    try:
        reader = ArcticReader(data_root=str(out_root))
        month = reader.latest_available_month("submissions")
        reader.close()
        return f"ok — ArcticReader sees latest month {month}"
    except Exception as exc:
        return f"warning — ArcticReader could not read it: {type(exc).__name__}: {exc}"


# ── CLI ─────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="load_arctic_corpus.py",
        description=(
            "Build a local Reddit corpus from the Arctic Shift HF Parquet mirror, "
            "laid out for metalworks' ArcticReader(data_root=...)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "example:\n"
            "  python scripts/load_arctic_corpus.py "
            "--subreddit Supplements --months 3 --out ./corpus\n\n"
            "then in Python:\n"
            "  from metalworks import Metalworks\n"
            "  from metalworks.research.arctic import ArcticReader\n"
            "  mw = Metalworks(reader=ArcticReader(data_root='./corpus'))"
        ),
    )
    parser.add_argument(
        "--subreddit",
        "-s",
        action="append",
        dest="subreddits",
        metavar="NAME",
        help="subreddit to pull (repeatable, e.g. -s Supplements -s Nootropics)",
    )
    parser.add_argument(
        "--months",
        "-m",
        type=int,
        default=1,
        help="how many months back to pull, ending at the latest available month (default: 1)",
    )
    parser.add_argument(
        "--out",
        "-o",
        type=Path,
        default=Path("./corpus"),
        help="output corpus root (default: ./corpus)",
    )
    parser.add_argument(
        "--comments",
        action="store_true",
        help="also fetch live comment trees for pulled submissions (Arctic Shift API)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max submissions per subreddit-month (default: no limit)",
    )
    parser.add_argument(
        "--hf-token",
        default=None,
        metavar="TOKEN",
        help="Hugging Face token for authenticated mirror reads (optional)",
    )
    parser.add_argument(
        "--memory-limit-gb",
        type=int,
        default=4,
        help="DuckDB memory limit in GB (default: 4)",
    )
    parser.add_argument(
        "--comment-timeout-s",
        type=float,
        default=30.0,
        help="per-request timeout for comment fetches in seconds (default: 30)",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    subreddits = [s for s in (args.subreddits or []) if s.strip()]
    if not subreddits:
        print("error: at least one --subreddit is required (repeatable).", file=sys.stderr)
        return 2
    if args.months < 1:
        print("error: --months must be >= 1.", file=sys.stderr)
        return 2

    out_root = args.out.expanduser().resolve()
    duckdb = _require_duckdb()
    con = _connect(duckdb, memory_limit_gb=args.memory_limit_gb, hf_token=args.hf_token)

    print(f"Resolving latest available month on {HF_DATASET} …")
    try:
        anchor = latest_available_month(con)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    window = months_back(args.months, anchor=anchor)
    print(f"  window: {window[0]} … {window[-1]}  ({len(window)} month(s))")
    print(f"  output: {out_root}")

    total_subs = 0
    total_comments = 0
    for subreddit in subreddits:
        print(f"\nr/{subreddit}")
        for month in window:
            try:
                n = pull_month(
                    con,
                    subreddit=subreddit,
                    month=month,
                    out_root=out_root,
                    limit=args.limit,
                )
            except Exception as exc:
                print(f"  {month}: error — {type(exc).__name__}: {exc}")
                continue
            total_subs += n
            print(f"  {month}: {n} submission(s)")
            if args.comments and n:
                ids = list_pulled_ids(out_root, subreddit=subreddit, month=month, con=con)
                written = fetch_comments(
                    out_root,
                    subreddit=subreddit,
                    month=month,
                    ids=ids,
                    timeout_s=args.comment_timeout_s,
                )
                total_comments += written
                print(f"  {month}: {written} comment(s)")

    con.close()

    print("\nDone.")
    print(f"  submissions written: {total_subs}")
    if args.comments:
        print(f"  comments written:    {total_comments}")
    print(f"  corpus root:         {out_root}")
    print(f"  reader check:        {_verify_readable(out_root)}")
    print("\nPoint metalworks at it:")
    print("  from metalworks.research.arctic import ArcticReader")
    print(f"  reader = ArcticReader(data_root={str(out_root)!r})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
