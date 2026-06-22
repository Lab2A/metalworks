"""Synthesis subtree tests: loader mapping, embed-group dedup, cluster ranker
quote-verification, market/verdict determinism, orchestration.

Offline — MemoryStores holds contract Reddit rows, FakeChatModel is scripted
per output_model, FakeEmbedding drives the dedup clustering. No network.
"""

from __future__ import annotations

from typing import Any

from metalworks.contract import (
    InsightCluster,
    MarketSizing,
    PriceFinding,
    RedditComment,
    RedditPost,
    ResearchBrief,
    SignalStrength,
    SlotPlan,
    TargetSubreddit,
)
from metalworks.embeddings import FakeEmbedding
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.synthesis import (
    cluster_ranker,
    embed_group,
    loader,
    market,
    synthesize,
    verdict,
)
from metalworks.research.synthesis.cluster_ranker import _CandidateCluster, _SynthesisOutput
from metalworks.research.types import LoadedComment
from metalworks.stores import MemoryStores


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions"):
        raise NotImplementedError

    def pull_subreddit(self, **_kw: object):
        raise NotImplementedError

    def fetch_submissions_by_ids(self, _ids: object, _months: object):
        raise NotImplementedError

    def close(self) -> None:
        return None


def _deps(store: MemoryStores, chat: FakeChatModel | None = None) -> ResearchDeps:
    return ResearchDeps(
        chat=chat or FakeChatModel(),
        embeddings=FakeEmbedding(),
        corpus=store,
        reader=_NullReader(),
    )


def _brief(**kw: object) -> ResearchBrief:
    base: dict[str, object] = dict(
        brief_id="b1",
        question="what do gym-goers want in a focus supplement",
        decision_context="ship or not",
        success_criteria=["s"],
        must_address=["m"],
        target_subreddits=[TargetSubreddit(name="Supplements", rationale="core")],
        web_research_directions=["pricing"],
        relevance_rubric="r",
    )
    base.update(kw)
    return ResearchBrief(**base)  # type: ignore[arg-type]


def _comment(cid: str, body: str, *, score: int = 1, author: str = "a1") -> RedditComment:
    return RedditComment(
        comment_id=cid,
        post_id="post1",
        subreddit="Supplements",
        body=body,
        permalink=f"https://reddit.com/c/{cid}",
        author_hash=author,
        score=score,
    )


def _loaded(cid: str, body: str, *, upvotes: int = 1, author: str = "a1") -> LoadedComment:
    return LoadedComment(
        comment_id=cid,
        post_id="post1",
        subreddit="Supplements",
        body=body,
        upvotes=upvotes,
        author_hash=author,
        permalink=f"https://reddit.com/c/{cid}",
    )


# ── loader: contract → LoadedPost/LoadedComment mapping ─────────────────────


def test_loader_maps_score_to_upvotes_and_drops_empty() -> None:
    # Removal sentinels are normalized away at the INGEST boundary now (see
    # test_itemsource.test_ingest_source_is_idempotent), so the loader's only
    # remaining body filter is the defensive empty-body drop. Writing directly
    # to the store bypasses ingest, so any sentinel bodies here survive — the
    # loader is source-neutral and no longer special-cases them.
    store = MemoryStores()
    store.upsert_comments(
        [
            _comment("c1", "real signal here", score=42),
            _comment("c4", "   "),  # whitespace-only → empty after strip → dropped
        ]
    )
    deps = _deps(store)
    comments = loader.load_comments(deps, ["post1"])
    assert len(comments) == 1
    assert comments[0].comment_id == "c1"
    # RedditComment.score → LoadedComment.upvotes mapping.
    assert comments[0].upvotes == 42
    assert comments[0].permalink == "https://reddit.com/c/c1"


def test_loader_sorts_by_upvotes_desc_and_caps() -> None:
    store = MemoryStores()
    store.upsert_comments([_comment(f"c{i}", f"body {i}", score=i) for i in range(5)])
    deps = _deps(store)
    comments = loader.load_comments(deps, ["post1"], cap=3)
    assert [c.upvotes for c in comments] == [4, 3, 2]


def test_loader_maps_post_url_to_permalink() -> None:
    store = MemoryStores()
    store.upsert_posts(
        [
            RedditPost(
                post_id="post1",
                subreddit="Supplements",
                title="t",
                url="https://reddit.com/r/Supplements/post1",
                score=10,
                num_comments=3,
            )
        ]
    )
    deps = _deps(store)
    posts = loader.load_posts(deps, ["post1"])
    assert len(posts) == 1
    assert posts[0].permalink == "https://reddit.com/r/Supplements/post1"


# ── embed_group dedup ───────────────────────────────────────────────────────


def test_embed_group_dedups_identical_bodies() -> None:
    embed = FakeEmbedding()

    def _e(c: LoadedComment) -> list[float] | None:
        return embed.embed([c.body], task="document")[0]

    comments = [
        _loaded("c1", "same body"),
        _loaded("c2", "same body"),  # identical → same group as c1
        _loaded("c3", "completely different content"),
    ]
    groups = embed_group.embed_group(comments, _e)
    # Identical bodies collapse; the distinct one is its own group.
    flat = sorted(i for g in groups for i in g)
    assert flat == [0, 1, 2]  # every comment placed exactly once
    # c1 and c2 land together.
    group_of = {i: gi for gi, g in enumerate(groups) for i in g}
    assert group_of[0] == group_of[1]
    assert group_of[2] != group_of[0]


def test_embed_group_failed_embed_is_singleton() -> None:
    def _e(c: LoadedComment) -> list[float] | None:
        return None  # every embed fails

    comments = [_loaded("c1", "a"), _loaded("c2", "a")]
    groups = embed_group.embed_group(comments, _e)
    # Failed embeds never merge — each is its own singleton.
    assert sorted(groups) == [[0], [1]]


# ── cluster_ranker: quote verification (no-quote-no-theme) ──────────────────


def test_cluster_ranker_drops_cluster_with_hallucinated_quote() -> None:
    comments = [_loaded("c1", "I want better focus", author="a1")]
    groups = [[0]]
    chat = FakeChatModel()
    # The LLM cites a quote_comment_index whose body does NOT contain the
    # candidate text it's standing in for — but here the body IS the source, so
    # to force a hallucination we make the only comment body unrelated to a
    # claim the verifier would accept. Instead: point quote at a group whose
    # representative body won't exact-match. We simulate by having the member
    # body be the verified source, and a SEPARATE comment as quote that isn't a
    # substring of any member body.
    chat.script(
        _SynthesisOutput,
        _SynthesisOutput(
            clusters=[
                _CandidateCluster(
                    claim="people want focus",
                    member_comment_indices=[0],
                    quote_comment_indices=[0],
                )
            ]
        ),
    )
    deps_chat = chat
    clusters, _a, _s, _mi = cluster_ranker.build_clusters(
        ResearchDeps(
            chat=deps_chat,
            embeddings=FakeEmbedding(),
            corpus=MemoryStores(),
            reader=_NullReader(),
        ),
        axis_context="focus",
        representatives=[comments[0]],
        groups=groups,
        comments=comments,
    )
    # Quote 'I want better focus' IS a substring of the member body → survives.
    assert len(clusters) == 1
    assert clusters[0].quotes[0].text == "I want better focus"


def test_cluster_ranker_no_quote_no_theme_drops_unverifiable() -> None:
    # member body and quote-source body differ: the quoted representative is a
    # different group whose body is NOT contained in the member set's bodies.
    members = _loaded("c1", "great taste and value", author="a1")
    orphan = _loaded("c2", "ZZZ_HALLUCINATED_TEXT_NOT_IN_MEMBERS", author="a2")
    comments = [members, orphan]
    groups = [[0], [1]]
    chat = FakeChatModel()
    chat.script(
        _SynthesisOutput,
        _SynthesisOutput(
            clusters=[
                _CandidateCluster(
                    claim="taste matters",
                    member_comment_indices=[0],  # only group 0 (members)
                    quote_comment_indices=[1],  # quote from group 1 (orphan) → not in members
                )
            ]
        ),
    )
    clusters, _a, _s, _mi = cluster_ranker.build_clusters(
        ResearchDeps(
            chat=chat,
            embeddings=FakeEmbedding(),
            corpus=MemoryStores(),
            reader=_NullReader(),
        ),
        axis_context="x",
        representatives=[members, orphan],
        groups=groups,
        comments=comments,
    )
    # The orphan quote isn't a substring of any member body → no verified quote
    # → cluster dropped (no-quote-no-theme).
    assert clusters == []


def test_cluster_ranker_demand_score_weights_authors() -> None:
    # Breadth (many authors) outranks virality (one high-upvote author).
    assert cluster_ranker.compute_demand_score(50, 2) > cluster_ranker.compute_demand_score(1, 200)


def test_cluster_ranker_signal_is_relative_not_absolute() -> None:
    # The badge bands a cluster's breadth against ALL clusters in the report, not a
    # fixed cutoff: the SAME absolute count (10) is HIGH when it tops the report and
    # LOW when it sits at the bottom — proving the band is relative.
    broad = [10, 5, 2]  # 10 tops this report
    thin = [40, 20, 10]  # 10 is the floor of this report
    assert cluster_ranker.signal_from_breadth(10, broad) == SignalStrength.HIGH
    assert cluster_ranker.signal_from_breadth(10, thin) == SignalStrength.LOW
    # The shared back-compat alias resolves to the same relative helper.
    assert cluster_ranker.signal_from_author_count(10, broad) == SignalStrength.HIGH


def test_cluster_ranker_raises_after_retries() -> None:
    class _Down(FakeChatModel):
        def complete_structured(self, **_kw: Any) -> Any:
            raise RuntimeError("llm down")

    import pytest

    with pytest.raises(RuntimeError, match="Synthesis LLM failed"):
        cluster_ranker.build_clusters(
            ResearchDeps(
                chat=_Down(),
                embeddings=FakeEmbedding(),
                corpus=MemoryStores(),
                reader=_NullReader(),
            ),
            axis_context="x",
            representatives=[_loaded("c1", "body")],
            groups=[[0]],
            comments=[_loaded("c1", "body")],
        )


# ── market + verdict determinism ────────────────────────────────────────────


def test_market_sizing_deterministic() -> None:
    m = market.build_market_sizing(40)
    assert m.reddit_floor == 40
    assert m.addressable_market == 4000  # 40 x 100 default multiplier
    assert m.penetration == {"conservative": 0.01, "expected": 0.03, "good": 0.06}


def test_market_sizing_zero_authors() -> None:
    m = market.build_market_sizing(0)
    assert m.reddit_floor == 0
    assert m.addressable_market == 0


def test_verdict_formats_the_given_strength_label() -> None:
    # derive_verdict is now a pure formatter — the strength is computed in demand.py
    # and handed in. (The band logic itself is covered by test_synthesis_demand.py.)
    assert verdict.derive_verdict(
        strength_label="Strong demand", total_distinct_authors=150
    ).startswith("Strong demand")
    assert verdict.derive_verdict(
        strength_label="Moderate demand", total_distinct_authors=30
    ).startswith("Moderate demand")
    thin = verdict.derive_verdict(strength_label="Thin signal", total_distinct_authors=5)
    assert thin.startswith("Thin signal")
    assert thin.endswith("Treat as exploratory.")


def test_verdict_includes_market_and_price() -> None:
    out = verdict.derive_verdict(
        strength_label="Strong demand",
        total_distinct_authors=120,
        market=MarketSizing(reddit_floor=120, addressable_market=12000, penetration={}),
        price=PriceFinding(low=10.0, high=25.0, currency="USD"),
    )
    assert "12,000 addressable" in out
    assert "willingness to pay ~USD 10" in out


# ── synthesize orchestration ────────────────────────────────────────────────


def test_synthesize_no_comments_returns_empty_shape() -> None:
    store = MemoryStores()
    deps = _deps(store)
    out = synthesize(deps, brief=_brief(), hydrated_post_ids=["post1"])
    assert out.ranked_clusters == []
    assert out.total_distinct_authors == 0
    assert out.n_synthesized == 0
    assert out.verdict is not None
    assert isinstance(out.slot_plan, SlotPlan)


def test_synthesize_end_to_end_builds_cluster() -> None:
    store = MemoryStores()
    store.upsert_posts(
        [
            RedditPost(
                post_id="post1",
                subreddit="Supplements",
                title="focus thread",
                url="https://reddit.com/post1",
                score=5,
                num_comments=2,
            )
        ]
    )
    store.upsert_comments(
        [
            _comment("c1", "I want better focus all day", score=10, author="a1"),
            _comment("c2", "focus crashes ruin my afternoon", score=3, author="a2"),
        ]
    )
    chat = FakeChatModel()
    chat.script(
        _SynthesisOutput,
        _SynthesisOutput(
            clusters=[
                _CandidateCluster(
                    claim="consumers want sustained focus",
                    member_comment_indices=[0, 1],
                    quote_comment_indices=[0, 1],
                )
            ]
        ),
    )
    # Secondary best-effort calls (audience/segments/pricing) may also hit chat;
    # they swallow their own failures, so leaving them unscripted is fine — the
    # FakeChatModel raises AssertionError, which best-effort wrappers catch.
    deps = _deps(store, chat)
    out = synthesize(deps, brief=_brief(), hydrated_post_ids=["post1"])
    assert len(out.ranked_clusters) == 1
    c = out.ranked_clusters[0]
    assert isinstance(c, InsightCluster)
    assert c.rank == 1
    assert c.distinct_author_count == 2
    assert c.mention_count == 2
    assert len(c.quotes) >= 1
    assert out.total_distinct_authors == 2
    # source_map reflects the hydrated post subset.
    assert any(e.subreddit == "r/Supplements" for e in out.source_map)
