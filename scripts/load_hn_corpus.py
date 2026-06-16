#!/usr/bin/env python3
"""Build your own local Hacker News corpus from the open-index HF archive.

metalworks reads Hacker News two ways: live (the keyless Algolia connector,
``--source hackernews``) and *bulk* — the Hugging Face ``open-index/hacker-news``
Parquet archive (``--source hackernews_archive``), the HN analogue of the Arctic
Shift Reddit mirror. This standalone script materializes a local slice of that
archive so research runs read it fast and fully offline, with no ``hf://`` access.

What it does
------------
Downloads the monthly Parquet files for an N-month window straight into the layout
:class:`metalworks.research.sources.hn_archive.HackerNewsArchiveReader` reads
verbatim::

    <out>/<YYYY>/<YYYY>-<MM>.parquet

Each file holds *everything* for that month — stories AND their comments — so the
reader's keyword story pull and offline comment-tree walk both work against the
local copy with no further fetching.

Run it
------
::

    python scripts/load_hn_corpus.py --months 1 --out ./hn-corpus

Then point metalworks at it::

    from metalworks import Metalworks
    from metalworks.research.sources.hn_archive import (
        HackerNewsArchiveReader, HackerNewsArchiveSource)

    src = HackerNewsArchiveSource(reader=HackerNewsArchiveReader(data_root="./hn-corpus"))
    mw = Metalworks(sources=[src])
    mw.research("a budget mechanical keyboard for programmers")

Heads up: there is no topic partition in HN, so a month is one file covering the
*whole* site — recent months are hundreds of MB. Start with ``--months 1``.

Dependencies
------------
Standard library only (``urllib``) — the download is a raw file copy, no DuckDB
needed. Reading the result later needs ``duckdb`` (``pip install "metalworks[arctic]"``).
This script imports nothing from metalworks at module load (only an optional
reader import at the end to sanity-check the result), so it works as a copy-paste
reference too.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# ── HF archive constants (kept in sync with HackerNewsArchiveReader) ─────────

HF_DATASET = "open-index/hacker-news"
# Raw-file download endpoint (the ``hf://`` path the reader uses, as plain HTTPS).
HF_RESOLVE = f"https://huggingface.co/datasets/{HF_DATASET}/resolve/main/data"
_CHUNK = 1 << 20  # 1 MiB streaming chunks


class MonthRef:
    """A tiny standalone year/month ref (no import-time dependency on metalworks)."""

    __slots__ = ("month", "year")

    def __init__(self, year: int, month: int) -> None:
        self.year = year
        self.month = month

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
            m, y = 12, y - 1
    return list(reversed(out))


def _month_url(m: MonthRef) -> str:
    return f"{HF_RESOLVE}/{m.year:04d}/{m.year:04d}-{m.month:02d}.parquet"


def _request(
    url: str, *, token: str | None, range_header: str | None = None
) -> urllib.request.Request:
    headers = {"User-Agent": "metalworks-hn-loader/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if range_header:
        headers["Range"] = range_header
    return urllib.request.Request(url, headers=headers)


def month_exists(m: MonthRef, *, token: str | None) -> bool:
    """Cheap existence probe — fetch the first byte (follows HF's CDN redirect)."""
    req = _request(_month_url(m), token=token, range_header="bytes=0-0")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status in (200, 206)
    except (urllib.error.HTTPError, urllib.error.URLError):
        return False


def latest_available_month(*, token: str | None) -> MonthRef:
    """Most recent month whose Parquet file exists (probes back up to 18 months)."""
    now = datetime.now(UTC)
    y, m = now.year, now.month
    for _ in range(18):
        ref = MonthRef(y, m)
        if month_exists(ref, token=token):
            return ref
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    raise RuntimeError(f"No HN archive months found in the last 18 from {now:%Y-%m-%d}")


def download_month(m: MonthRef, *, out_root: Path, token: str, force: bool) -> int:
    """Stream one monthly Parquet file to ``<out>/<YYYY>/<YYYY>-<MM>.parquet``.

    Returns bytes written (0 if skipped because it already exists and ``force``
    is false, or the month is missing upstream).
    """
    out_dir = out_root / f"{m.year:04d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{m.year:04d}-{m.month:02d}.parquet"
    if out_file.exists() and not force:
        print(f"  {m}: exists, skipping (use --force to re-download)")
        return 0
    req = _request(_month_url(m), token=token or None)
    tmp = out_file.with_suffix(".parquet.part")
    written = 0
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as fh:
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
                print(f"\r  {m}: {written / 1e6:,.1f} MB", end="", flush=True)
        tmp.replace(out_file)
        print(f"\r  {m}: {written / 1e6:,.1f} MB  ✓")
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        tmp.unlink(missing_ok=True)
        print(f"\r  {m}: error — {type(exc).__name__}: {exc}")
        return 0
    return written


def _verify_readable(out_root: Path) -> str:
    """Best-effort: confirm the HN archive reader can read what we wrote."""
    try:
        from metalworks.research.sources.hn_archive import HackerNewsArchiveReader
    except Exception:
        return "skipped (metalworks not importable here)"
    try:
        reader = HackerNewsArchiveReader(data_root=str(out_root), probe_sleep_s=0.0)
        month = reader.latest_available_month()
        reader.close()
        return f"ok — reader sees latest local month {month}"
    except Exception as exc:
        return f"warning — reader could not read it: {type(exc).__name__}: {exc}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="load_hn_corpus.py",
        description=(
            "Download a local Hacker News corpus from the open-index/hacker-news HF "
            "archive, laid out for metalworks' HackerNewsArchiveReader(data_root=...)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "example:\n"
            "  python scripts/load_hn_corpus.py --months 1 --out ./hn-corpus\n\n"
            "then in Python:\n"
            "  from metalworks import Metalworks\n"
            "  from metalworks.research.sources.hn_archive import (\n"
            "      HackerNewsArchiveReader, HackerNewsArchiveSource)\n"
            "  r = HackerNewsArchiveReader(data_root='./hn-corpus')\n"
            "  Metalworks(sources=[HackerNewsArchiveSource(reader=r)]).research('...')"
        ),
    )
    parser.add_argument(
        "--months",
        "-m",
        type=int,
        default=1,
        help="how many months back to download, ending at the latest available (default: 1)",
    )
    parser.add_argument(
        "--out",
        "-o",
        type=Path,
        default=Path("./hn-corpus"),
        help="output corpus root (default: ./hn-corpus)",
    )
    parser.add_argument(
        "--hf-token",
        default="",
        metavar="TOKEN",
        help="Hugging Face token for authenticated reads (optional)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download months that already exist locally",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    if args.months < 1:
        print("error: --months must be >= 1.", file=sys.stderr)
        return 2
    out_root = args.out.expanduser().resolve()
    token = args.hf_token or None

    print(f"Resolving latest available month on {HF_DATASET} …")
    try:
        anchor = latest_available_month(token=token)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    window = months_back(args.months, anchor=anchor)
    print(f"  window: {window[0]} … {window[-1]}  ({len(window)} month(s))")
    print(f"  output: {out_root}")
    print("  note: each month is one file for the whole site — recent months are large.\n")

    total = 0
    for m in window:
        total += download_month(m, out_root=out_root, token=args.hf_token, force=args.force)

    print("\nDone.")
    print(f"  bytes downloaded: {total / 1e6:,.1f} MB")
    print(f"  corpus root:      {out_root}")
    print(f"  reader check:     {_verify_readable(out_root)}")
    print("\nPoint metalworks at it:")
    print("  from metalworks.research.sources.hn_archive import HackerNewsArchiveReader")
    print(f"  reader = HackerNewsArchiveReader(data_root={str(out_root)!r})")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
