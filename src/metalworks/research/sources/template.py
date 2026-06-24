"""Bring-your-own-corpus template — copy this file to add a new source.

metalworks researches over a *source-neutral* corpus. To point it at YOUR data
(an internal forum, a reviews export, a Discord archive, a CRM, a CSV …) you only
need to implement one small protocol: :class:`~metalworks.research.sources.ItemSource`.
Copy this file, rename the class, fill in the three methods, and pass an instance
to the pipeline:

    from metalworks import Metalworks
    from my_package.my_source import MyCorpusSource

    mw = Metalworks(sources=[MyCorpusSource()])

That is the whole integration surface. The pipeline pulls candidate records from
your source, triages them for relevance, fetches comments only for the relevant
subset, and synthesizes — it never learns where the data came from.

Verify your connector against the published contract before you ship it:

    from metalworks.testing import check_item_source

    def test_my_source_conforms():
        check_item_source(MyCorpusSource())

Two non-negotiable contract rules (the conformance check enforces both):

* **Stable ids.** A record's ``id`` must be the SAME string every time you pull
  the same underlying item. The corpus upserts by ``id``; an unstable id (a
  random uuid, a row number that shifts) duplicates rows on every run.
* **Idempotent pull.** Pulling the same ``query`` / ``window`` twice must yield
  the same set of ids. (Order and transient engagement counts may differ; the
  id set may not.)

This module is import-safe and does NOT touch the network — it is a skeleton.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class MyCorpusSource:
    """A template :class:`ItemSource`. Rename it, then fill in the three methods.

    ``source_id`` is the short, stable tag that lands on every record/comment as
    ``source=...`` (e.g. ``"reddit"``, ``"hackernews"``). Pick something lowercase
    and durable — it is part of your corpus's identity and shows up in reports.
    """

    source_id = "mysource"

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """Yield the candidate top-level items for ``query`` over ``window``.

        Map each of YOUR items onto a :class:`CorpusRecord`. The fields:

        * ``id`` — corpus-wide identity. MUST be stable across pulls (see module
          docstring). Usually your native item id, optionally prefixed.
        * ``source`` — set this to ``self.source_id``.
        * ``source_id`` — the native id within your source (so you can recover the
          origin item later). Often the same string as ``id``.
        * ``url`` — a resolvable link to the item. This is the provenance link the
          report cites; make it open the real item.
        * ``title`` — headline / subject. Empty string if your items have none.
        * ``text`` — the body. For a link-only item, fall back to the link itself
          (so it is never empty). Strip any markup to plain text here.
        * ``author_hash`` — a SALTED, non-reversible author id, or ``None`` when
          the author is unknown/removed. Never store the raw username. Hash at THIS
          boundary so nothing downstream sees source-specific identities:

              import hashlib
              h = hashlib.sha256(f"{salt}:{username.lower()}".encode()).hexdigest()
              author_hash = f"u_{h[:16]}"

        * ``engagement`` — your source's native popularity signal as an int
          (upvotes, points, likes, helpful-count). Used for ranking; 0 if you have
          none.
        * ``created_at`` — a timezone-aware ``datetime`` (UTC), or ``None``.
        * ``extra`` — a free-form dict for source-specific fields that do not earn
          a spine column (a star rating, a board name, a product SKU).

        ``query`` is whatever YOUR source searches on (a keyword, a category, a
        board id — your choice). ``window`` carries a ``[start, end]`` datetime
        span (and, for partitioned sources, ``months``) — filter by whichever you
        understand. ``limit`` is a dev guard (``None`` in production); honor it by
        stopping early. This is the CANDIDATE set — pull broadly; the pipeline
        triages for relevance before any expensive comment fetch.

        Replace the stub below with your real fetch + mapping.
        """
        _ = (query, window, limit)
        # Example shape (delete this; it is illustrative, not a real fetch):
        #
        #   for item in my_api.search(query, since=window.start, until=window.end):
        #       yield CorpusRecord(
        #           id=item.id,
        #           source=self.source_id,
        #           source_id=item.id,
        #           url=item.permalink,
        #           title=item.subject,
        #           text=item.body or item.permalink,
        #           author_hash=_hash(item.author),
        #           engagement=item.likes,
        #           created_at=item.created_at,
        #           extra={"board": item.board},
        #       )
        return iter(())

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """Yield one comment batch per record id, IN INPUT ORDER.

        For each id in ``record_ids``, yield a (possibly empty) list of
        :class:`CorpusComment`. The comment fields mirror :class:`CorpusRecord`,
        with two that matter most:

        * ``parent_id`` — the ``id`` of the :class:`CorpusRecord` this comment
          belongs to. Use the incoming record id; this is what links a quote back
          to its thread.
        * ``url`` — must resolve to the quote IN CONTEXT (the comment permalink),
          because the report cites comments as evidence.

        Also set ``id`` (stable, comment-native), ``source`` (= ``self.source_id``),
        ``text`` (plain text, markup stripped), ``author_hash`` (salted, ``""`` if
        unknown), ``engagement`` (0 if comments have no score), and ``created_at``.

        **Normalize removed/dead content HERE.** If your source has tombstones
        (``[deleted]``, ``null`` text, a flagged marker), DROP those comments —
        do not emit empty ones. The pipeline's quote layer assumes every comment
        carries real, quotable text.

        Return ``None`` (not an empty iterator) ONLY if your source has NO comment
        layer at all — then the run is recorded as comment-less rather than failed.
        A source WITH comments yields a list per id (empty when a record has none).

        Replace the stub below with your real comment fetch.
        """
        _ = record_ids
        # Sources WITH comments: yield one (possibly empty) list per record id:
        #
        #   for rid in record_ids:
        #       yield [
        #           CorpusComment(
        #               id=c.id, parent_id=rid, source=self.source_id,
        #               url=c.permalink, text=strip(c.body),
        #               author_hash=_hash(c.author), engagement=c.score,
        #               created_at=c.created_at,
        #           )
        #           for c in my_api.comments(rid)
        #           if not c.is_deleted  # drop tombstones; don't emit empties
        #       ]
        #
        # Sources WITHOUT a comment layer: `return None` instead of the loop.
        empty: list[CorpusComment] = []
        return (empty for _ in record_ids)

    def latest_window(self) -> SourceWindow:
        """Return the most recent :class:`SourceWindow` your source can serve.

        This is your source's anchor — the window the pipeline falls back to when
        the caller does not specify one. For a live API, an end-bounded window at
        "now" is typical. For a partitioned dataset, return the latest available
        partition in ``months``. ``start``/``end`` are timezone-aware datetimes.
        """
        return SourceWindow(end=datetime.now(tz=UTC))


# ── declare what this source IS ───────────────────────────────────────────────
# Every source carries a SourceSpec so the selector, the catalog (`sources list`
# / docs/sources.md), and the conformance guardrail can read its lane / auth /
# signal facts without constructing it. Fill these in to match YOUR source:
#
# * lane       — "grounding" (discrete pain-bearing items) or "web" (context).
# * signals    — the named demand-signal kinds you emit (e.g. ("upvotes",)); each
#                must be registered in metalworks.research.synthesis.signals.
# * targeting  — the selector knob you vary on: "none" / "keyword" / "subreddit" /
#                "instance" / "slug".
# * auth/env   — "none" (env empty) or "key"/"oauth"/"paid" (env names the var(s)).
# * access     — "open" / "free_key" / "paid" / "blocked".
SPEC = SourceSpec(
    source_id="mysource",
    lane="grounding",
    signals=("upvotes",),
    targeting="keyword",
    auth="none",
    env=(),
    access="open",
    relevance_hint="one line on what this source is best at surfacing",
)


# Register on import so a bare ``import`` of your module wires the source up.
# Pass ``spec=SPEC`` so the metadata layer is populated too:
#
#     from metalworks.research.sources import register_source
#     register_source("mysource", lambda **_: MyCorpusSource(), spec=SPEC)
#
# If your source emits a signal kind the registry doesn't know yet, declare its
# semantics so the deterministic scorer can weight it (mirrors register_source):
#
#     from metalworks.research.synthesis.signals import SignalSpec, register_signal
#     register_signal(SignalSpec(kind="helpfulness", weight=1.0, transform="log"))


__all__ = ["SPEC", "MyCorpusSource"]
