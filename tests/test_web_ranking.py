"""Phase 4 — web (a commentless source) participates in synthesis + ranking.

4a: a record with no comment thread (a web page) enters synthesis as its own
unit, so a web-only corpus still produces demand clusters.
4b: breadth = distinct authors + distinct domains, so authorless web clusters
rank on domain breadth instead of scoring zero for having no author.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

import pytest

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceWindow

# Reuse the scripted-pipeline scaffolding (scripted chat + deps + brief).
from test_itemsource import _brief, _deps  # type: ignore[import-not-found]

_NOW = datetime(2026, 6, 1, tzinfo=UTC)

# Distinct text → distinct FakeEmbedding vectors (no dedup collapse). Each on its
# own domain, so domain-breadth is exercised.
_WEB = [
    ("w1", "founders want a stim-free focus aid that does not wreck sleep", "blog.acme.com"),
    ("w2", "afternoon crash help, anything that is not caffeine", "news.example.org"),
    ("w3", "stim free focus options, caffeine wrecks my sleep", "rdx.io"),
    ("w4", "l-theanine plus caffeine to concentrate at work", "wellness.co"),
    ("w5", "good budget nootropic stack under thirty a month", "forum.health.net"),
]


class WebFakeSource:
    """An authorless, commentless ItemSource (a web search connector shape)."""

    source_id = "web"
    yields_units = True  # records are self-representing synthesis units

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        for rid, text, domain in _WEB:
            yield CorpusRecord(
                id=rid,
                source="web",
                source_id=rid,
                url=f"https://{domain}/{rid}",
                title=text,
                text=text,
                author_hash="",  # web is authorless
                engagement=0,  # web has no native engagement
                created_at=_NOW,
                extra={"domain": domain},
            )

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        return None  # commentless

    def latest_window(self) -> SourceWindow:
        return SourceWindow(start=_NOW, end=_NOW)


def test_commentless_web_source_produces_clusters() -> None:
    """4a: web records (no comments) enter synthesis as units and form a cluster
    whose quotes resolve to the web source."""
    pytest.importorskip("rank_bm25")
    pytest.importorskip("numpy")
    from metalworks.research.pipeline import run_research
    from metalworks.stores import MemoryStores

    corpus = MemoryStores()
    report = run_research(_deps([WebFakeSource()], corpus), brief=_brief())

    # A cluster was synthesized purely from commentless web records.
    assert report.ranked_clusters, "web-only corpus must still produce clusters"
    cluster = report.ranked_clusters[0]
    assert cluster.quotes
    for q in cluster.quotes:
        assert q.source == "web"
        assert q.source_url.startswith("https://")  # the page link is the provenance
        assert q.author_hash == ""  # authorless

    # 4b: an authorless web cluster ranks on DOMAIN breadth, not author count.
    assert cluster.breadth_unit == "domains"
    assert cluster.breadth_count >= 2  # distinct domains among its members
    assert cluster.distinct_author_count == 0  # honestly zero authors
    assert cluster.demand_score > 0  # breadth keeps it off the floor

    # The web records persisted to the durable corpus (auto-ingest), comment-less.
    persisted = corpus.get_records([rid for rid, _, _ in _WEB])
    assert persisted and all(r.source == "web" for r in persisted)


def _unit(*, author_hash: str = "", source_url: str = "", body: str = "x") -> object:
    from metalworks.research.types import LoadedComment

    return LoadedComment(
        comment_id=f"{author_hash}{source_url}{body}",
        post_id="p",
        subreddit="",
        body=body,
        author_hash=author_hash,
        source_url=source_url,
    )


def test_cluster_breadth_authored_web_and_mixed() -> None:
    from metalworks.research.synthesis.cluster_ranker import cluster_breadth

    # Authored only (Reddit): breadth == distinct authors, unit "authors".
    authored = [_unit(author_hash="a1"), _unit(author_hash="a2"), _unit(author_hash="a1")]
    assert cluster_breadth(authored) == (2, 2, "authors")

    # Authorless web: breadth == distinct domains, unit "domains", 0 authors.
    web = [
        _unit(source_url="https://blog.acme.com/x"),
        _unit(source_url="https://www.acme.com/y"),  # www. stripped → same domain as none above
        _unit(source_url="https://news.example.org/z"),
    ]
    breadth, authors, unit = cluster_breadth(web)
    assert authors == 0
    assert unit == "domains"
    assert breadth == 3  # blog.acme.com, acme.com, news.example.org

    # Mixed: authors + domains, unit "voices".
    mixed = [_unit(author_hash="a1"), _unit(source_url="https://acme.com/x")]
    assert cluster_breadth(mixed) == (2, 1, "voices")
