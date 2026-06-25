"""Agentic discovery chassis (#155): protocol/registry, the homegrown loop,
the capability-ladder gate, and cite-or-die preservation.

Offline — a stub SearchProvider + FakeChatModel stand in for real providers.
The gate is the core deliverable: an agentic provider being configured means
the homegrown loop does NOT run (asserted via a spy), and with neither provider
the legacy single-pass path is byte-identical.
"""

from __future__ import annotations

import pytest

from metalworks import config
from metalworks.contract import ResearchBrief, SignalStrength, TargetSubreddit
from metalworks.llm import FakeChatModel
from metalworks.research.discovery import (
    DISCOVERY_PROVIDERS,
    DiscoveryBudget,
    DiscoveryFinding,
    DiscoveryProvider,
    HomegrownDiscovery,
    get_discovery,
    register_discovery,
)
from metalworks.research.web import web_research
from metalworks.search import SearchResult

# ── fixtures ────────────────────────────────────────────────────────────────


def _brief(**kw: object) -> ResearchBrief:
    base: dict[str, object] = dict(
        brief_id="b1",
        question="what do gym-goers want in a focus supplement",
        decision_context="d",
        success_criteria=["s"],
        must_address=["m"],
        target_subreddits=[TargetSubreddit(name="Supplements", rationale="core")],
        web_research_directions=["pricing", "competitors"],
        relevance_rubric="r",
    )
    base.update(kw)
    return ResearchBrief(**base)  # type: ignore[arg-type]


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions"):
        raise NotImplementedError

    def pull_subreddit(self, **_kw: object):
        raise NotImplementedError

    def fetch_submissions_by_ids(self, _ids: object, _months: object):
        raise NotImplementedError

    def close(self) -> None:
        return None


def _deps(chat: FakeChatModel, *, search: object = None, discovery: object = None):
    from metalworks.embeddings import FakeEmbedding
    from metalworks.research.deps import ResearchDeps
    from metalworks.stores import MemoryStores

    return ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
        search=search,  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )


class _StubSearch:
    """A single-shot SearchProvider that returns canned results per query.

    ``per_query`` maps a query (lower-cased) to its hits; an unknown query falls
    back to ``default``. Records every query in ``.queries`` for assertions.
    """

    protocol_version = "1.0"
    provider_id = "stub"

    def __init__(
        self,
        per_query: dict[str, list[SearchResult]] | None = None,
        *,
        default: list[SearchResult] | None = None,
    ) -> None:
        self._per_query = {k.lower(): v for k, v in (per_query or {}).items()}
        self._default = default or []
        self.queries: list[str] = []

    def search(
        self, *, query: str, max_results: int = 10, recency_days: int | None = None
    ) -> list[SearchResult]:
        self.queries.append(query)
        return self._per_query.get(query.lower(), self._default)


class _SpyAgentic:
    """An agentic DiscoveryProvider that records whether it was delegated to."""

    protocol_version = "1.0"
    provider_id = "spy-agentic"
    agentic = True

    def __init__(self, findings: list[DiscoveryFinding]) -> None:
        self._findings = findings
        self.called = False

    def discover(
        self, *, question: str, directions: list[str], budget: DiscoveryBudget
    ) -> list[DiscoveryFinding]:
        self.called = True
        return self._findings


def _result(url: str, title: str, snippet: str) -> SearchResult:
    return SearchResult(url=url, title=title, snippet=snippet)


# ── 1. Protocol / registry / resolve_discovery ──────────────────────────────


def test_protocol_registry_and_resolve() -> None:
    # HomegrownDiscovery satisfies the runtime-checkable Protocol and is the
    # non-agentic rung.
    loop = HomegrownDiscovery(search=_StubSearch(), chat=FakeChatModel())
    assert isinstance(loop, DiscoveryProvider)
    assert loop.agentic is False
    assert loop.provider_id == "homegrown"

    # Registry round-trips (idempotent re-register, construct via get_discovery).
    spy = _SpyAgentic([])
    register_discovery("spy", lambda: spy)
    register_discovery("spy", lambda: spy)  # idempotent
    assert "spy" in DISCOVERY_PROVIDERS
    assert get_discovery("spy") is spy
    try:
        get_discovery("nope")
    except KeyError as exc:
        assert "nope" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected KeyError for unknown provider")
    DISCOVERY_PROVIDERS.pop("spy", None)

    # No agentic adapter ships yet → resolve_discovery() is None (gate falls
    # through to the homegrown loop / single-pass).
    assert config.resolve_discovery() is None


# ── 2. The gate ─────────────────────────────────────────────────────────────


def test_gate_agentic_delegates_and_loop_does_not_run() -> None:
    spy = _SpyAgentic(
        [DiscoveryFinding(quote="agentic verbatim quote", source_url="https://x.com", title="X")]
    )
    # A SearchProvider is ALSO present; the agentic provider must win and the
    # homegrown loop must NOT touch search.
    search = _StubSearch(default=[_result("https://nope.com", "Nope", "should not be searched")])
    chat = FakeChatModel(grounded=False)
    findings = web_research(_deps(chat, search=search, discovery=spy), brief=_brief())

    assert spy.called is True  # delegated
    assert search.queries == []  # homegrown loop never ran → no search calls
    assert all(c["kind"] != "structured" for c in chat.calls)  # no follow-up LLM
    assert len(findings) == 1
    assert findings[0].specifics == "agentic verbatim quote"  # cite-or-die quote
    assert findings[0].source_url == "https://x.com"


def test_gate_homegrown_runs_with_search_when_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.research.discovery import _FollowupQueries

    # Opt in to the homegrown loop (``[sources].discover = true``).
    monkeypatch.setattr(config, "discovery_loop_enabled", lambda: True)
    search = _StubSearch(
        default=[_result("https://a.com", "A", "real snippet about focus supplements")]
    )
    chat = FakeChatModel(grounded=False)
    chat.script(_FollowupQueries, _FollowupQueries(queries=[]))  # no further digging
    findings = web_research(_deps(chat, search=search), brief=_brief())
    assert search.queries  # homegrown loop ran (searched at least once)
    assert len(findings) == 1
    assert findings[0].specifics == "real snippet about focus supplements"


def test_gate_search_without_optin_is_single_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    # DEFAULT: a SearchProvider is configured but the loop is NOT opted in
    # (``discover`` unset) → rung 3 single-pass _external_search, NOT the loop.
    # The loop's signature move — a ``_FollowupQueries`` LLM call — must NOT fire
    # (single-pass still makes a structured findings call, just never a follow-up).
    from metalworks.research.discovery import _FollowupQueries

    monkeypatch.setattr(config, "discovery_loop_enabled", lambda: False)
    search = _StubSearch(
        default=[_result("https://a.com", "A", "real snippet about focus supplements")]
    )
    chat = FakeChatModel(grounded=False)
    web_research(_deps(chat, search=search), brief=_brief())
    assert search.queries  # single-pass still searches the SearchProvider
    # The loop's signature LLM call (follow-up queries) must NOT fire — proves we
    # took rung 3 (single-pass), not rung 2 (the opt-in loop). Single-pass may make
    # its own structured findings call, but never a _FollowupQueries one.
    assert not any(c.get("output_model") is _FollowupQueries for c in chat.calls)


def test_gate_neither_provider_is_byte_identical_single_pass() -> None:
    # Neither an agentic provider NOR a SearchProvider → rung 3 = legacy
    # _external_search, which with no search provider returns []. Pinned.
    chat = FakeChatModel(grounded=False)
    assert web_research(_deps(chat, search=None, discovery=None), brief=_brief()) == []


# ── 3. Homegrown loop: multi-round, follow-ups, dedup, budget ───────────────


def test_homegrown_iterates_two_rounds_with_followups() -> None:
    from metalworks.research.discovery import _FollowupQueries

    search = _StubSearch(
        per_query={
            "what do gym-goers want in a focus supplement": [
                _result("https://r1a.com", "R1A", "round one finding a"),
            ],
            "pricing": [_result("https://r1b.com", "R1B", "round one pricing")],
            "competitors": [_result("https://r1c.com", "R1C", "round one competitors")],
            # round-2 follow-up queries proposed by the LLM:
            "niche forum deep dive": [_result("https://r2a.com", "R2A", "round two deep finding")],
        }
    )
    chat = FakeChatModel(grounded=False)
    chat.script(_FollowupQueries, _FollowupQueries(queries=["niche forum deep dive"]))

    loop = HomegrownDiscovery(search=search, chat=chat)
    found = loop.discover(
        question="what do gym-goers want in a focus supplement",
        directions=["pricing", "competitors"],
        budget=DiscoveryBudget(max_rounds=2, max_findings=25, max_domains=12),
    )
    urls = {f.source_url for f in found}
    assert "https://r2a.com" in urls  # the second round actually ran
    assert len(found) == 4
    # The follow-up query the LLM proposed was actually searched.
    assert "niche forum deep dive" in search.queries
    # Every finding carries a verbatim quote (cite-or-die), never empty.
    assert all(f.quote for f in found)


def test_homegrown_dedups_by_url() -> None:
    from metalworks.research.discovery import _FollowupQueries

    dup = _result("https://same.com", "Same", "same snippet")
    search = _StubSearch(
        per_query={
            "q": [dup],
            "pricing": [dup],  # same URL surfaced again → deduped
            "followup": [dup],  # and again in round 2 → still deduped
        }
    )
    chat = FakeChatModel(grounded=False)
    chat.script(_FollowupQueries, _FollowupQueries(queries=["followup"]))
    loop = HomegrownDiscovery(search=search, chat=chat)
    found = loop.discover(
        question="q",
        directions=["pricing"],
        budget=DiscoveryBudget(max_rounds=2),
    )
    assert len(found) == 1  # one URL, one finding


def test_homegrown_stops_on_budget_and_no_new_findings() -> None:
    from metalworks.research.discovery import _FollowupQueries

    # max_findings=2 stops mid-round-1 even though more hits exist.
    search = _StubSearch(
        default=[
            _result("https://a.com", "A", "a"),
            _result("https://b.com", "B", "b"),
            _result("https://c.com", "C", "c"),
        ]
    )
    chat = FakeChatModel(grounded=False)
    chat.script(_FollowupQueries, _FollowupQueries(queries=["more"]))
    loop = HomegrownDiscovery(search=search, chat=chat)
    found = loop.discover(
        question="q",
        directions=[],
        budget=DiscoveryBudget(max_rounds=5, max_findings=2),
    )
    assert len(found) == 2  # budget stop
    # No follow-up LLM call: budget hit in round 1.
    assert all(c["kind"] != "structured" for c in chat.calls)


def test_homegrown_stops_when_round_adds_nothing() -> None:
    from metalworks.research.discovery import _FollowupQueries

    # Round 1 finds one hit; the follow-up query returns the SAME url (no new),
    # so the loop stops rather than spinning.
    hit = _result("https://only.com", "Only", "only snippet")
    search = _StubSearch(per_query={"q": [hit], "followup": [hit]})
    chat = FakeChatModel(grounded=False)
    chat.script(
        _FollowupQueries,
        [_FollowupQueries(queries=["followup"]), _FollowupQueries(queries=["again"])],
    )
    loop = HomegrownDiscovery(search=search, chat=chat)
    found = loop.discover(question="q", directions=[], budget=DiscoveryBudget(max_rounds=5))
    assert len(found) == 1
    # The loop stopped after round 2 added nothing — it did NOT ask for a 3rd
    # round of follow-ups (only one follow-up call consumed).
    structured_calls = [c for c in chat.calls if c["kind"] == "structured"]
    assert len(structured_calls) == 1


# ── 4. Cite-or-die: finding → quote+url, not a summary ──────────────────────


def test_cite_or_die_quote_not_summary() -> None:
    from metalworks.research.web import _findings_from_discovery

    verbatim = "Most people just want it to not give them jitters at 4pm."
    found = [
        DiscoveryFinding(quote=verbatim, source_url="https://forum.example/thread", title="Thread")
    ]
    web_findings = _findings_from_discovery(found, excluded=[], max_findings=10)
    assert len(web_findings) == 1
    wf = web_findings[0]
    # The verbatim quote is preserved as the anchor; the URL comes from the
    # finding metadata — NOT a synthesized summary.
    assert wf.specifics == verbatim
    assert wf.source_url == "https://forum.example/thread"
    assert wf.confidence == SignalStrength.LOW

    # A finding with no quote or an excluded domain is dropped, never invented.
    assert (
        _findings_from_discovery(
            [DiscoveryFinding(quote="", source_url="https://x.com", title="X")],
            excluded=[],
            max_findings=10,
        )
        == []
    )
    assert _findings_from_discovery(found, excluded=["forum.example"], max_findings=10) == []
