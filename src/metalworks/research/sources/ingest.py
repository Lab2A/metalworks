"""``corpus.ingest`` — the source→corpus write path.

:func:`ingest_source` is the single primitive that turns an :class:`ItemSource`
into durable corpus state: pull records → ``corpus.upsert_records`` → pull their
comments → ``corpus.upsert_corpus_comments``. It is idempotent (upserts are
keyed on id, so re-ingesting the same window produces no duplicates) and it is
the boundary where Reddit's ``[deleted]`` / ``[removed]`` sentinels are
normalized to tombstones — that special-case used to live in the shared synthesis
loader; it belongs at the source boundary so the loader stays source-neutral.

The pipeline uses the finer-grained helpers (:func:`ingest_records` /
:func:`ingest_comments_for`) to keep its triage-then-hydrate efficiency: it
ingests the candidate records, triages them, then fetches comments ONLY for the
relevant subset. The all-in-one :func:`ingest_source` is the convenience path
(and the one the FakeSource test drives).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metalworks.contract import CorpusComment, CorpusRecord

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from metalworks.research.sources import ItemSource, SourceWindow
    from metalworks.stores.repos import CorpusRepo

# Reddit's content-removal sentinels. Normalized away at the ingest boundary so
# the source-neutral spine never carries them downstream.
_SENTINELS = ("[deleted]", "[removed]")


@dataclass
class IngestResult:
    """Outcome of an ingest pass — how many records/comments landed."""

    records: int = 0
    comments: int = 0
    has_comments: bool = True

    def __str__(self) -> str:
        tail = "" if self.has_comments else " (source has no comments)"
        return f"ingest: {self.records} records, {self.comments} comments{tail}"


def _normalize_record(r: CorpusRecord) -> CorpusRecord:
    """Tombstone a record whose author is a Reddit removal sentinel."""
    if r.author_hash in _SENTINELS:
        return r.model_copy(update={"author_hash": None})
    return r


def _normalize_comment(c: CorpusComment) -> CorpusComment | None:
    """Tombstone / drop a comment carrying a removal sentinel.

    A ``[deleted]`` / ``[removed]`` *body* carries no quotable signal, so the
    comment is dropped here (the loader used to do this inline). A sentinel
    *author* on an otherwise-real comment is normalized to an empty author_hash.
    """
    body = (c.text or "").strip()
    if not body or body in _SENTINELS:
        return None
    if c.author_hash in _SENTINELS:
        return c.model_copy(update={"author_hash": ""})
    return c


def ingest_records(corpus: CorpusRepo, records: Iterable[CorpusRecord]) -> int:
    """Normalize + upsert ``records``; return the count written."""
    normalized = [_normalize_record(r) for r in records if r.id]
    if normalized:
        corpus.upsert_records(normalized)
    return len(normalized)


def ingest_comments_for(
    corpus: CorpusRepo, source: ItemSource, record_ids: Sequence[str]
) -> tuple[int, bool]:
    """Pull comments for ``record_ids`` from ``source`` and upsert them.

    Returns ``(written, has_comments)``. ``has_comments`` is ``False`` when the
    source has no comment layer (``comments_for`` returned ``None``).
    """
    ids = [rid for rid in record_ids if rid]
    if not ids:
        return 0, True
    batches = source.comments_for(ids)
    if batches is None:
        return 0, False
    written = 0
    for batch in batches:
        normalized: list[CorpusComment] = []
        for c in batch:
            nc = _normalize_comment(c)
            if nc is not None:
                normalized.append(nc)
        if normalized:
            corpus.upsert_corpus_comments(normalized)
            written += len(normalized)
    return written, True


def ingest_source(
    corpus: CorpusRepo,
    source: ItemSource,
    *,
    query: str,
    window: SourceWindow,
    limit: int | None = None,
) -> IngestResult:
    """Pull a source's items for ``query``/``window`` into the durable corpus.

    The all-in-one write path: every pulled record is upserted, then comments
    are fetched for every pulled record. Idempotent — re-running over the same
    window upserts by id, so no duplicates. The pipeline uses the finer helpers
    above to fetch comments for only the triage-relevant subset; this convenience
    form is for callers (and tests) that want a one-shot ingest.
    """
    record_ids: list[str] = []
    n_records = 0
    pending: list[CorpusRecord] = []
    for r in source.pull(query=query, window=window, limit=limit):
        nr = _normalize_record(r)
        if not nr.id:
            continue
        pending.append(nr)
        record_ids.append(nr.id)
        if len(pending) >= 500:
            corpus.upsert_records(pending)
            n_records += len(pending)
            pending = []
    if pending:
        corpus.upsert_records(pending)
        n_records += len(pending)

    n_comments, has_comments = ingest_comments_for(corpus, source, record_ids)
    return IngestResult(records=n_records, comments=n_comments, has_comments=has_comments)


__all__ = [
    "IngestResult",
    "ingest_comments_for",
    "ingest_records",
    "ingest_source",
]
