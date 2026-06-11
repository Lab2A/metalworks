"""Tests for run_discovery — the filter → generate → gate pipeline (offline)."""

from __future__ import annotations

from metalworks.contract import (
    ComplianceVerdict,
    DiscoveryContext,
    Opportunity,
    Persona,
    PersonaSet,
    RedditPost,
)
from metalworks.discovery import DiscoveryDeps, run_discovery
from metalworks.llm import FakeChatModel
from metalworks.stores.memory import MemoryStores

# ── Fixtures / stubs ───────────────────────────────────────────────────────


class StubSearch:
    """Returns a fixed list of posts; never touches redditwarp."""

    def __init__(self, posts: list[RedditPost], *, rules: list[str] | None = None) -> None:
        self._posts = posts
        self._rules = rules or []
        self.queries: list[str] = []

    def search_posts(
        self,
        query: str,
        *,
        subreddit: str | None = None,
        limit: int = 15,
        sort: str = "relevance",
        time: str = "week",
    ) -> list[RedditPost]:
        self.queries.append(query)
        return list(self._posts)

    def get_subreddit_rules(self, name: str) -> list[str]:
        return list(self._rules)


def _post(post_id: str = "abc123", *, subreddit: str = "sysadmin") -> RedditPost:
    return RedditPost(
        post_id=post_id,
        subreddit=subreddit,
        title="What do you use for log aggregation on a budget?",
        selftext="Self-hosting a 12-node cluster, ELK is too heavy. What are the alternatives?",
        url=f"https://reddit.com/r/{subreddit}/comments/{post_id}/x/",
    )


def _keep() -> object:
    from metalworks.discovery import FilterDecision

    return FilterDecision(keep=True, account_type="expert", reason="relevant", confidence=0.9)


def _reject() -> object:
    from metalworks.discovery import FilterDecision

    return FilterDecision(keep=False, account_type="expert", reason="off-topic", confidence=0.9)


def _reply(text: str = "loki + grafana is the budget stack. lighter than elk by a mile.") -> object:
    from metalworks.discovery import ReplyGenerationV2

    return ReplyGenerationV2(
        reply_text=text,
        account_type="expert",
        short_description="budget log aggregation",
        voice_match_self_score=0.9,
        confidence=0.85,
        reasoning="adds a concrete named alternative",
    )


def _deps(
    *,
    search: StubSearch,
    stores: MemoryStores,
    chat: FakeChatModel,
    fast_chat: FakeChatModel | None = None,
    context: DiscoveryContext | None = None,
    on_query_result: object = None,
    query_performance: object = None,
) -> DiscoveryDeps:
    return DiscoveryDeps(
        chat=chat,
        search=search,  # type: ignore[arg-type]  # structural stub
        opportunities=stores,
        fast_chat=fast_chat,
        context=context or DiscoveryContext(),
        on_query_result=on_query_result,  # type: ignore[arg-type]
        query_performance=query_performance,  # type: ignore[arg-type]
    )


# ── Tests ──────────────────────────────────────────────────────────────────


def test_generate_then_gate_produces_opportunity_with_verdict() -> None:
    from metalworks.discovery import FilterDecision, ReplyGenerationV2

    chat = FakeChatModel()
    chat.script(FilterDecision, _keep())
    chat.script(ReplyGenerationV2, _reply())

    stores = MemoryStores()
    deps = _deps(search=StubSearch([_post()]), stores=stores, chat=chat)

    opps = run_discovery(deps, queries=["log aggregation"])

    assert len(opps) == 1
    opp = opps[0]
    assert isinstance(opp, Opportunity)
    assert opp.compliance is not None
    assert opp.compliance.pass_ is True
    assert opp.account_type == "expert"
    assert opp.draft_reply.startswith("loki")
    # Persisted.
    assert stores.opportunity_exists(_post().url)


def test_dedup_skips_seen_post_without_llm_calls() -> None:
    from metalworks.discovery import FilterDecision, ReplyGenerationV2

    stores = MemoryStores()
    # Pre-seed an opportunity for this post url.
    stores.save_opportunities(
        [
            Opportunity(
                opportunity_id="existing",
                post=_post(),
                draft_reply="already drafted",
            )
        ]
    )

    chat = FakeChatModel()
    chat.script(FilterDecision, _keep())
    chat.script(ReplyGenerationV2, _reply())

    deps = _deps(search=StubSearch([_post()]), stores=stores, chat=chat)
    opps = run_discovery(deps, queries=["log aggregation"])

    assert opps == []
    # No filter/generate LLM call was made for the seen url.
    assert chat.calls == []


def test_filter_reject_drops_post() -> None:
    from metalworks.discovery import FilterDecision, ReplyGenerationV2

    chat = FakeChatModel()
    chat.script(FilterDecision, _reject())
    chat.script(ReplyGenerationV2, _reply())

    deps = _deps(search=StubSearch([_post()]), stores=MemoryStores(), chat=chat)
    opps = run_discovery(deps, queries=["q"])

    assert opps == []
    # Filter was called; generate was not.
    kinds = [c.get("output_model") for c in chat.calls]
    assert FilterDecision in kinds
    assert ReplyGenerationV2 not in kinds


def test_heuristic_fail_blocks_opportunity() -> None:
    from metalworks.discovery import FilterDecision, ReplyGenerationV2

    chat = FakeChatModel()
    chat.script(FilterDecision, _keep())
    # Em-dash is a deterministic high-confidence heuristic failure.
    chat.script(
        ReplyGenerationV2, _reply("this reply has an em-dash — which the gate rejects hard")
    )

    deps = _deps(search=StubSearch([_post()]), stores=MemoryStores(), chat=chat)
    opps = run_discovery(deps, queries=["q"])

    assert opps == []
    # Judge was NOT consulted (heuristic was confident).
    assert ComplianceVerdict not in [c.get("output_model") for c in chat.calls]


def test_low_confidence_heuristic_escalates_to_llm_judge() -> None:
    from metalworks.discovery import FilterDecision, ReplyGenerationV2

    # A reply with a CTA verb ("try it") drives heuristic confidence to 0.6
    # (< 0.7) — a pass, but uncertain → must escalate to the judge. Kept >30
    # chars and free of AI-tells/em-dashes so the only signal is the CTA.
    borderline = "honestly you should try it for a week and see how the latency looks"
    chat = FakeChatModel()
    fast = FakeChatModel(model_id="fake/fast")
    # filter + judge both run on the fast (filter) model; generate on chat.
    fast.script(FilterDecision, _keep())
    chat.script(ReplyGenerationV2, _reply(borderline))
    fast.script(
        ComplianceVerdict,
        ComplianceVerdict.model_validate({"pass": True, "violations": [], "confidence": 0.8}),
    )

    deps = _deps(search=StubSearch([_post()]), stores=MemoryStores(), chat=chat, fast_chat=fast)
    opps = run_discovery(deps, queries=["q"])

    assert len(opps) == 1
    # The judge output_model was requested on the fast model.
    assert ComplianceVerdict in [c.get("output_model") for c in fast.calls]


def test_pro_to_flash_degradation_retry() -> None:
    from metalworks.discovery import FilterDecision, ReplyGenerationV2

    class BrokenGenerate(FakeChatModel):
        """Raises on the generate call (ReplyGenerationV2), passes filter through."""

        def complete_structured(self, *, output_model, **kwargs):  # type: ignore[no-untyped-def, override]
            if output_model is ReplyGenerationV2:
                raise RuntimeError("pro model truncated mid-string")
            return super().complete_structured(output_model=output_model, **kwargs)

    chat = BrokenGenerate()
    chat.script(FilterDecision, _keep())
    fast = FakeChatModel(model_id="fake/fast")
    # filter falls back to chat when fast_chat is set? No — filter uses fast_chat.
    fast.script(FilterDecision, _keep())
    fast.script(ReplyGenerationV2, _reply())

    deps = _deps(search=StubSearch([_post()]), stores=MemoryStores(), chat=chat, fast_chat=fast)
    opps = run_discovery(deps, queries=["q"])

    # Generate failed on pro (chat), succeeded on flash (fast_chat).
    assert len(opps) == 1
    assert opps[0].draft_reply.startswith("loki")


def test_max_opportunities_cap() -> None:
    from metalworks.discovery import FilterDecision, ReplyGenerationV2

    posts = [_post(post_id=f"p{i}") for i in range(5)]
    chat = FakeChatModel()
    # Single scripted instance is returned every call.
    chat.script(FilterDecision, _keep())
    chat.script(ReplyGenerationV2, _reply())

    deps = _deps(search=StubSearch(posts), stores=MemoryStores(), chat=chat)
    opps = run_discovery(deps, queries=["q"], max_opportunities=2)

    assert len(opps) == 2


def test_persona_selected_by_account_type() -> None:
    from metalworks.discovery import FilterDecision, ReplyGenerationV2

    founder_decision = FilterDecision(
        keep=True, account_type="founder", reason="tool debate", confidence=0.9
    )
    chat = FakeChatModel()
    chat.script(FilterDecision, founder_decision)
    chat.script(ReplyGenerationV2, _reply())

    context = DiscoveryContext(
        personas=PersonaSet(
            personas={
                "founder": Persona(
                    example_posts=["FOUNDER_VOICE_MARKER lowercase only"],
                    background="founder of a log startup",
                ),
                "expert": Persona(example_posts=["EXPERT_VOICE_MARKER"]),
            }
        )
    )
    deps = _deps(search=StubSearch([_post()]), stores=MemoryStores(), chat=chat, context=context)
    run_discovery(deps, queries=["q"])

    # The generate call's user prompt carried the founder persona's voice sample.
    gen_call = next(c for c in chat.calls if c.get("output_model") is ReplyGenerationV2)
    user = gen_call["user"]
    assert isinstance(user, str)
    assert "FOUNDER_VOICE_MARKER" in user
    assert "EXPERT_VOICE_MARKER" not in user


def test_on_query_result_called_with_counts() -> None:
    from metalworks.discovery import FilterDecision, ReplyGenerationV2

    calls: list[tuple[str, int, int]] = []

    def record(query: str, found: int, kept: int) -> None:
        calls.append((query, found, kept))

    # Two posts; one kept (filter reject on the second via a FIFO list).
    posts = [_post(post_id="keep1"), _post(post_id="drop2")]
    chat = FakeChatModel()
    chat.script(FilterDecision, [_keep(), _reject()])
    chat.script(ReplyGenerationV2, _reply())

    deps = _deps(
        search=StubSearch(posts),
        stores=MemoryStores(),
        chat=chat,
        on_query_result=record,
    )
    run_discovery(deps, queries=["q"])

    assert calls == [("q", 2, 1)]


def test_query_performance_orders_queries() -> None:
    from metalworks.discovery import FilterDecision, ReplyGenerationV2

    chat = FakeChatModel()
    chat.script(FilterDecision, _reject())  # reject everything; we only check ordering
    chat.script(ReplyGenerationV2, _reply())

    search = StubSearch([_post()])
    # "high" scores above "low" → must be searched first.
    perf = {"low": 0.1, "high": 0.9}

    deps = _deps(
        search=search,
        stores=MemoryStores(),
        chat=chat,
        query_performance=lambda q: perf[q],
    )
    run_discovery(deps, queries=["low", "high"])

    assert search.queries == ["high", "low"]


# ── Standalone seam tests (WS3: filter_post / generate_reply are public) ─────


def test_filter_post_standalone_building_block() -> None:
    from metalworks.discovery import FilterDecision, filter_post

    chat = FakeChatModel()
    chat.script(FilterDecision, _keep())
    decision = filter_post(chat, _post(), DiscoveryContext())
    assert decision is not None
    assert decision.keep is True


def test_filter_post_reports_errors_via_callback() -> None:
    from metalworks.discovery import filter_post

    class _BoomChat(FakeChatModel):
        def complete_structured(self, **kwargs: object) -> object:  # type: ignore[override]
            raise RuntimeError("boom")

    errors: list[str] = []
    decision = filter_post(_BoomChat(), _post(), DiscoveryContext(), on_error=errors.append)
    assert decision is None
    assert errors and errors[0].startswith("filter-error:")


def test_generate_reply_standalone_building_block() -> None:
    from metalworks.discovery import ReplyGenerationV2, generate_reply

    chat = FakeChatModel()
    chat.script(ReplyGenerationV2, _reply())
    reply = generate_reply(chat, _post(), Persona(), "expert", DiscoveryContext())
    assert reply is not None
    assert reply.reply_text.strip()


def test_generate_reply_retries_on_fast_chat_when_capable_returns_empty() -> None:
    from metalworks.discovery import ReplyGenerationV2, generate_reply

    capable = FakeChatModel()
    capable.script(ReplyGenerationV2, _reply(text="   "))  # empty → triggers pro→flash retry
    fast = FakeChatModel()
    fast.script(ReplyGenerationV2, _reply(text="recovered budget log aggregation reply text"))

    events: list[str] = []
    reply = generate_reply(
        capable,
        _post(),
        Persona(),
        "expert",
        DiscoveryContext(),
        fast_chat=fast,
        on_event=events.append,
    )
    assert reply is not None
    assert reply.reply_text == "recovered budget log aggregation reply text"
    assert any(e.startswith("generate-retry:") for e in events)
