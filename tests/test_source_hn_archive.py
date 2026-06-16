"""HackerNewsArchiveSource over a local Parquet fixture (offline, no network).

Builds a tiny HN month — three stories and a comment tree with a nested reply and
a dead comment — writes it to the archive's ``<root>/<YYYY>/<YYYY>-<MM>.parquet``
layout, points the reader at it via ``data_root``, and proves the keyword story
pull and the breadth-first comment walk.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from metalworks.research.sources import ItemSource, SourceWindow
from metalworks.research.sources.hn_archive import (
    HackerNewsArchiveReader,
    HackerNewsArchiveSource,
)
from metalworks.research.types import MonthRef

# Story 100 (keyboard) → comments 101, 102, dead-104; 101 → 103 (nested).
# Story 200 (chair)    → comment 201.  Story 300 (rust) → no keyword match, no kids.
_FIXTURE_SQL = """
CREATE TABLE items (
  id BIGINT, type TINYINT, "by" VARCHAR, time TIMESTAMP, text VARCHAR,
  url VARCHAR, score INTEGER, title VARCHAR, descendants INTEGER,
  parent BIGINT, kids BIGINT[], deleted TINYINT, dead TINYINT
);
INSERT INTO items VALUES
 (100,1,'alice',TIMESTAMP '2024-01-15 10:00','', 'https://kbd.example',120,
   'Show HN: a budget mechanical keyboard for programmers',3,NULL,[101,102,104],0,0),
 (200,1,'bob',  TIMESTAMP '2024-01-16 10:00','my back hurts','',50,
   'Ask HN: best ergonomic chair',1,NULL,[201],0,0),
 (300,1,'carol',TIMESTAMP '2024-01-17 10:00','rust 1.80 is out','',200,
   'Rust 1.80 released',0,NULL,[]::BIGINT[],0,0),
 (101,2,'dave', TIMESTAMP '2024-01-15 11:00','<p>I love the tactile switches</p>','',0,
   NULL,0,100,[103],0,0),
 (102,2,'eve',  TIMESTAMP '2024-01-15 11:30','too expensive for me','',0,
   NULL,0,100,[]::BIGINT[],0,0),
 (103,2,'frank',TIMESTAMP '2024-01-15 12:00','agreed, cherry browns are great','',0,
   NULL,0,101,[]::BIGINT[],0,0),
 (104,2,'mod',  TIMESTAMP '2024-01-15 12:30','[dead]','',0,
   NULL,0,100,[]::BIGINT[],0,1),
 (201,2,'grace',TIMESTAMP '2024-01-16 11:00','the herman miller is worth it','',0,
   NULL,0,200,[]::BIGINT[],0,0);
"""


@pytest.fixture
def archive_root(tmp_path: Path) -> str:
    duckdb = pytest.importorskip("duckdb")  # skips on the bare matrix (no duckdb)

    month_dir = tmp_path / "2024"
    month_dir.mkdir()
    con = duckdb.connect()
    con.execute(_FIXTURE_SQL)
    out = (month_dir / "2024-01.parquet").as_posix()
    con.execute(f"COPY items TO '{out}' (FORMAT PARQUET)")
    con.close()
    assert os.path.exists(out)
    return tmp_path.as_posix()


def _source(root: str) -> HackerNewsArchiveSource:
    reader = HackerNewsArchiveReader(data_root=root, probe_sleep_s=0.0)
    return HackerNewsArchiveSource(reader=reader)


_WINDOW = SourceWindow(months=(MonthRef(2024, 1),))


def test_satisfies_protocol(archive_root: str) -> None:
    assert isinstance(_source(archive_root), ItemSource)


def test_pull_keyword_filters_stories(archive_root: str) -> None:
    src = _source(archive_root)
    records = list(src.pull(query="mechanical keyboard", window=_WINDOW))
    ids = {r.id for r in records}
    assert ids == {"100"}  # only the keyboard story matches; chair + rust excluded
    rec = records[0]
    assert rec.source == "hackernews"
    assert rec.engagement == 120
    assert rec.url == "https://news.ycombinator.com/item?id=100"
    assert rec.author_hash and rec.author_hash.startswith("u_")
    assert rec.extra["num_comments"] == 3


def test_comment_tree_walks_nested_and_drops_dead(archive_root: str) -> None:
    src = _source(archive_root)
    # pull first so the source knows which months to read comments from
    list(src.pull(query="keyboard", window=_WINDOW))
    batches = src.comments_for(["100"])
    assert batches is not None
    comments = next(iter(batches))

    ids = {c.id for c in comments}
    # 101 + 102 (direct) + 103 (nested under 101); 104 is dead → dropped.
    assert ids == {"101", "102", "103"}
    assert all(c.parent_id == "100" for c in comments)  # flattened to the story
    assert all(c.source == "hackernews" for c in comments)
    by_id = {c.id: c for c in comments}
    assert by_id["101"].text == "I love the tactile switches"  # HTML stripped
    assert by_id["103"].text == "agreed, cherry browns are great"  # nested reply present


def test_two_stories_each_get_their_own_thread(archive_root: str) -> None:
    src = _source(archive_root)
    list(src.pull(query="keyboard chair", window=_WINDOW))  # matches 100 and 200
    batches = list(src.comments_for(["100", "200"]))
    assert {c.id for c in batches[0]} == {"101", "102", "103"}
    assert {c.id for c in batches[1]} == {"201"}
