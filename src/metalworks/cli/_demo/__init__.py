"""Offline demo corpus for ``metalworks quickstart``.

A tiny, hand-authored set of submission rows is written to a local Parquet file
in a temp directory at runtime (via duckdb, the ``[arctic]`` extra), so the
quickstart runs with ZERO API keys and ZERO network: the corpus is local, and
the pipeline runs on :class:`~metalworks.llm.FakeChatModel` /
:class:`~metalworks.embeddings.FakeEmbedding`.

We generate the Parquet at runtime rather than committing a binary blob so the
package stays text-only and the data is human-readable here.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# A handful of realistic-looking submissions for a single subreddit. The corpus
# is written under the CURRENT year/month so the ArcticReader's
# ``latest_available_month`` probe (which walks back from today) finds it. One
# subreddit, one month so the directory layout matches the Arctic glob
# (``<root>/submissions/<YYYY>/<MM>/*.parquet``).
DEMO_SUBREDDIT = "Supplements"
_NOW = datetime.now(UTC)
DEMO_YEAR = _NOW.year
DEMO_MONTH = _NOW.month

_DEMO_ROWS: list[dict[str, Any]] = [
    {
        "id": "demo01",
        "title": "Looking for a focus supplement without the jitters",
        "selftext": "Coffee wrecks my stomach but I need to concentrate at work. "
        "Anything that actually helps without making me anxious?",
        "score": 142,
        "num_comments": 38,
    },
    {
        "id": "demo02",
        "title": "Best nootropic stack for studying that won't break the bank?",
        "selftext": "Student budget here. I keep seeing $60 bottles. Is there anything "
        "under $25 a month that's actually worth it?",
        "score": 96,
        "num_comments": 21,
    },
    {
        "id": "demo03",
        "title": "Magnesium glycinate finally fixed my sleep",
        "selftext": "After months of bad sleep, 400mg of magnesium glycinate before bed "
        "changed everything. Anyone else?",
        "score": 311,
        "num_comments": 74,
    },
    {
        "id": "demo04",
        "title": "Are focus gummies just candy with caffeine?",
        "selftext": "Every brand markets focus gummies to students. Is there real evidence "
        "or is it just sugar and marketing?",
        "score": 58,
        "num_comments": 15,
    },
    {
        "id": "demo05",
        "title": "What do you wish a supplement company would actually make?",
        "selftext": "If you could design the perfect daily focus product, what would be in "
        "it and what price would you pay?",
        "score": 203,
        "num_comments": 52,
    },
]


def write_demo_corpus(root: Path) -> Path:
    """Write the demo submissions Parquet under ``root`` and return ``root``.

    Layout: ``<root>/submissions/<YYYY>/<MM>/demo.parquet`` — exactly what
    :class:`~metalworks.research.arctic.reader.ArcticReader` globs for. Requires
    ``duckdb`` (the ``[arctic]`` extra); the caller guards for its absence.
    """
    import duckdb

    month_dir = root / "submissions" / f"{DEMO_YEAR:04d}" / f"{DEMO_MONTH:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    out = month_dir / "demo.parquet"

    base_ts = int(time.mktime((DEMO_YEAR, DEMO_MONTH, 15, 12, 0, 0, 0, 0, 0)))
    values: list[str] = []
    for i, row in enumerate(_DEMO_ROWS):
        title = str(row["title"]).replace("'", "''")
        selftext = str(row["selftext"]).replace("'", "''")
        url = f"https://reddit.com/r/{DEMO_SUBREDDIT}/comments/{row['id']}/"
        values.append(
            f"('{row['id']}', '{DEMO_SUBREDDIT}', '{title}', '{selftext}', "
            f"'demo_author_{i}', {int(row['score'])}, {int(row['num_comments'])}, "
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


from metalworks.cli._demo.scripted import (  # noqa: E402
    DemoChatModel,
    DemoComments,
    build_demo_chat,
)

__all__ = [
    "DEMO_MONTH",
    "DEMO_SUBREDDIT",
    "DEMO_YEAR",
    "DemoChatModel",
    "DemoComments",
    "build_demo_chat",
    "write_demo_corpus",
]
