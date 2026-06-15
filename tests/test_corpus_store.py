"""Source-neutral corpus store round-trips (Phase 1b).

The corpus store holds the generic `CorpusRecord` / `CorpusComment` spine, not
anything Reddit-specific. These tests prove a NON-Reddit source (Hacker News)
round-trips through both zero-infra backends — including a comment-less record
(a link-only story with no quotes) and embeddings keyed by an arbitrary corpus
`record_id` (a record OR a comment id).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.embeddings import IndexIdentity
from metalworks.stores import CorpusRepo, MemoryStores, SqliteStores

_NOW = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def corpus(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[CorpusRepo]:
    if request.param == "memory":
        yield MemoryStores()
    else:
        backend = SqliteStores(tmp_path / "corpus.db")
        yield backend
        backend.close()


def _hn_story(i: int, *, with_text: bool = True) -> CorpusRecord:
    return CorpusRecord(
        id=f"hn-story-{i}",
        source="hackernews",
        source_id=str(40000 + i),
        url=f"https://news.ycombinator.com/item?id={40000 + i}",
        title=f"Show HN: a thing #{i}",
        text="we built this over a weekend" if with_text else "",
        author_hash="hn_author_x",
        engagement=120 + i,
        created_at=_NOW,
        extra={"site": "example.com", "comment_count": 3},
    )


def _hn_comment(i: int, parent_id: str) -> CorpusComment:
    return CorpusComment(
        id=f"hn-cmt-{i}",
        parent_id=parent_id,
        source="hackernews",
        url=f"https://news.ycombinator.com/item?id={50000 + i}",
        text=f"switched off the tool after the pricing change ({i})",
        author_hash=f"hn_commenter_{i % 3}",
        engagement=40 + i,
        created_at=_NOW,
        extra={"parent_native": parent_id},
    )


def test_non_reddit_record_round_trips(corpus: CorpusRepo) -> None:
    story = _hn_story(1)
    corpus.upsert_records([story])
    # Idempotent re-upsert must not duplicate.
    corpus.upsert_records([story])

    got = corpus.get_records(["hn-story-1", "hn-missing"])
    assert len(got) == 1
    rec = got[0]
    assert rec.source == "hackernews"
    assert rec.id == "hn-story-1"
    assert rec.url == "https://news.ycombinator.com/item?id=40001"
    assert rec.engagement == 121
    assert rec.created_at == _NOW
    assert rec.extra["site"] == "example.com"


def test_commentless_record_round_trips(corpus: CorpusRepo) -> None:
    """A link-only record with no comments must store + read back cleanly, and
    `get_comments_for_records` returns nothing for it."""
    story = _hn_story(2, with_text=False)
    corpus.upsert_records([story])

    got = corpus.get_records(["hn-story-2"])
    assert len(got) == 1
    assert got[0].text == ""
    assert corpus.get_comments_for_records(["hn-story-2"]) == []


def test_comments_for_records(corpus: CorpusRepo) -> None:
    story = _hn_story(3)
    comments = [_hn_comment(i, story.id) for i in range(5)]
    corpus.upsert_records([story])
    corpus.upsert_corpus_comments(comments)
    # Idempotent re-upsert.
    corpus.upsert_corpus_comments(comments[:2])

    got = corpus.get_comments_for_records(["hn-story-3"])
    assert len(got) == 5
    assert {c.id for c in got} == {f"hn-cmt-{i}" for i in range(5)}
    one = next(c for c in got if c.id == "hn-cmt-0")
    assert one.source == "hackernews"
    assert one.parent_id == "hn-story-3"
    assert one.extra["parent_native"] == "hn-story-3"


def test_embeddings_keyed_by_record_id(corpus: CorpusRepo) -> None:
    """Embeddings are keyed by an arbitrary corpus id — a record id OR a comment
    id — not specifically a comment id."""
    identity = IndexIdentity(embedding_model_id="hn-embed", dim=4)
    # Mix a record id and a comment id in the same index.
    corpus.upsert_embeddings(
        {
            "hn-story-7": [1.0, 0.0, 0.0, 0.0],
            "hn-cmt-7": [0.0, 1.0, 0.0, 0.0],
        },
        identity=identity,
    )

    fetched = corpus.get_embeddings(["hn-story-7", "hn-cmt-7", "absent"], identity=identity)
    assert set(fetched) == {"hn-story-7", "hn-cmt-7"}
    assert fetched["hn-story-7"][0] == 1.0

    wrong = IndexIdentity(embedding_model_id="other", dim=4)
    assert corpus.get_embeddings(["hn-story-7"], identity=wrong) == {}


def test_memory_and_sqlite_equivalent(tmp_path: Path) -> None:
    def script(s: CorpusRepo) -> tuple[int, int, str]:
        s.upsert_records([_hn_story(i) for i in range(3)])
        s.upsert_corpus_comments([_hn_comment(i, f"hn-story-{i % 3}") for i in range(9)])
        recs = s.get_records(["hn-story-0", "hn-story-1", "hn-story-2"])
        cmts = s.get_comments_for_records(["hn-story-0", "hn-story-1", "hn-story-2"])
        return (len(recs), len(cmts), recs[0].source if recs else "")

    sqlite_backend = SqliteStores(tmp_path / "eq.db")
    try:
        assert script(MemoryStores()) == script(sqlite_backend)
    finally:
        sqlite_backend.close()
