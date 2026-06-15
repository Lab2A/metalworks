"""A small local Reddit corpus for offline pipeline tests.

Writes a handful of hand-authored submission rows to a local Parquet file (via
duckdb), laid out exactly how :class:`~metalworks.research.arctic.reader.ArcticReader`
globs for them — ``<root>/submissions/<YYYY>/<MM>/*.parquet`` under the current
month. A test fixture only; not shipped in the package.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SAMPLE_SUBREDDIT = "Supplements"
_NOW = datetime.now(UTC)
_YEAR = _NOW.year
_MONTH = _NOW.month

_ROWS: list[dict[str, Any]] = [
    {
        "id": "row01",
        "title": "Looking for a focus supplement without the jitters",
        "selftext": "Coffee wrecks my stomach but I need to concentrate at work. "
        "Anything that actually helps without making me anxious?",
        "score": 142,
        "num_comments": 38,
    },
    {
        "id": "row02",
        "title": "Best nootropic stack for studying that won't break the bank?",
        "selftext": "Student budget here. I keep seeing $60 bottles. Is there anything "
        "under $25 a month that's actually worth it?",
        "score": 96,
        "num_comments": 21,
    },
    {
        "id": "row03",
        "title": "Magnesium glycinate finally fixed my sleep",
        "selftext": "After months of bad sleep, 400mg of magnesium glycinate before bed "
        "changed everything. Anyone else?",
        "score": 311,
        "num_comments": 74,
    },
    {
        "id": "row04",
        "title": "Are focus gummies just candy with caffeine?",
        "selftext": "Every brand markets focus gummies to students. Is there real evidence "
        "or is it just sugar and marketing?",
        "score": 58,
        "num_comments": 15,
    },
    {
        "id": "row05",
        "title": "What do you wish a supplement company would actually make?",
        "selftext": "If you could design the perfect daily focus product, what would be in "
        "it and what price would you pay?",
        "score": 203,
        "num_comments": 52,
    },
]


def write_sample_corpus(root: Path) -> Path:
    """Write the sample submissions Parquet under ``root`` and return ``root``.

    Layout: ``<root>/submissions/<YYYY>/<MM>/sample.parquet``. Requires duckdb
    (the ``[arctic]`` extra); callers guard for its absence with ``importorskip``.
    """
    import duckdb

    month_dir = root / "submissions" / f"{_YEAR:04d}" / f"{_MONTH:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    out = month_dir / "sample.parquet"

    base_ts = int(time.mktime((_YEAR, _MONTH, 15, 12, 0, 0, 0, 0, 0)))
    values: list[str] = []
    for i, row in enumerate(_ROWS):
        title = str(row["title"]).replace("'", "''")
        selftext = str(row["selftext"]).replace("'", "''")
        url = f"https://reddit.com/r/{SAMPLE_SUBREDDIT}/comments/{row['id']}/"
        values.append(
            f"('{row['id']}', '{SAMPLE_SUBREDDIT}', '{title}', '{selftext}', "
            f"'sample_author_{i}', {int(row['score'])}, {int(row['num_comments'])}, "
            f"'{url}', {base_ts + i})"
        )

    con = duckdb.connect(":memory:")
    try:
        con.execute(
            "CREATE TABLE submissions ("
            "id VARCHAR, subreddit VARCHAR, title VARCHAR, selftext VARCHAR, "
            "author VARCHAR, score BIGINT, num_comments BIGINT, url VARCHAR, "
            "created_utc BIGINT)"
        )
        con.execute("INSERT INTO submissions VALUES " + ", ".join(values))
        out_sql = str(out).replace("'", "''")
        con.execute(f"COPY submissions TO '{out_sql}' (FORMAT PARQUET)")
    finally:
        con.close()
    return root
