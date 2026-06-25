"""Parallel Task discovery adapter (#157): cite-or-die Basis mapping + the gate.

Offline by default — a recorded Parallel Task response drives an
``httpx.MockTransport`` so no socket is touched. The core assertions:

1. ``discover`` maps Basis ``citations[].excerpts`` → cite-or-die findings
   (verbatim quote + url), and NEVER ingests ``output.content`` (the synthesized
   prose). Asserted against a recorded response that contains a deliberately
   distinctive synthesized sentence we then prove is absent from every quote.
2. With the provider resolvable, the chassis gate delegates to it and the
   homegrown loop does NOT run (``[sources].discover`` off; search untouched).
3. Unconfigured (no ``PARALLEL_API_KEY``) → ``resolve_discovery()`` is ``None``,
   so the provider is not selected and nothing crashes.

A ``network``-marked live smoke runs a real Task only when a key is present.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

from metalworks import config
from metalworks.contract import ResearchBrief, TargetSubreddit
from metalworks.llm import FakeChatModel
from metalworks.research.discovery import DiscoveryBudget
from metalworks.research.discovery.parallel import ParallelTaskDiscovery
from metalworks.research.web import web_research
from metalworks.search import SearchResult

# ── A recorded Parallel Task result ─────────────────────────────────────────
#
# ``output.content`` is the SYNTHESIZED prose (the summary). The cite-or-die rule
# is that NONE of it leaks into a finding — only the Basis citation excerpts do.
_SYNTHESIZED_PROSE = "SYNTHESIZED_SUMMARY_THAT_MUST_NEVER_BECOME_A_QUOTE"

_RECORDED_RESULT: dict[str, Any] = {
    "run_id": "trun_recorded",
    "output": {
        "type": "task_run_result",
        "content": (
            f"{_SYNTHESIZED_PROSE}: gym-goers broadly prefer jitter-free focus "
            "supplements and are price-sensitive above $40."
        ),
        "basis": [
            {
                "field": "pain_points",
                "confidence": "high",
                "reasoning": "Multiple first-hand reports.",
                "citations": [
                    {
                        "url": "https://www.forum.example/thread/1",
                        "title": "Focus thread",
                        "excerpts": [
                            "Most people just want it to not give them jitters at 4pm.",
                            "The crash afterwards is the real dealbreaker for me.",
                        ],
                    },
                    {
                        "url": "https://blog.example/review",
                        "title": "A review",
                        "excerpts": ["I switched after the third bottle stopped working."],
                    },
                ],
            },
            {
                "field": "pricing",
                "confidence": "medium",
                "reasoning": "A couple of pricing mentions.",
                "citations": [
                    {
                        "url": "https://www.forum.example/thread/2",
                        "title": "Pricing thread",
                        "excerpts": ["Anything over $40 a month is a hard no for me."],
                    },
                ],
            },
        ],
    },
}


def _recorded_transport(captured: dict[str, Any] | None = None) -> httpx.MockTransport:
    """A MockTransport that answers create-run then get-result from the record."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["last"] = request
        if request.method == "POST" and request.url.path == "/v1/tasks/runs":
            return httpx.Response(200, json={"run_id": "trun_recorded", "status": "queued"})
        if request.method == "GET" and request.url.path.endswith("/result"):
            return httpx.Response(200, json=_RECORDED_RESULT)
        return httpx.Response(404, json={})  # pragma: no cover

    return httpx.MockTransport(handler)


def _make(
    *, transport: httpx.MockTransport, api_key: str = "test-key", processor: str = "lite"
) -> ParallelTaskDiscovery:
    """Construct the adapter, skipping when the ``parallel`` extra is absent.

    The extra gates construction (``MissingExtraError`` in ``__init__``), so the
    BARE matrix can't exercise the live mapping — but it CAN still import + register
    the module and verify the unconfigured-resolution path (see the extra-free tests
    at the bottom). This keeps the bare matrix green.
    """
    pytest.importorskip("parallel")
    client = httpx.Client(base_url="https://api.parallel.ai", transport=transport)
    return ParallelTaskDiscovery(api_key=api_key, processor=processor, client=client)


def _provider(
    *, captured: dict[str, Any] | None = None, processor: str = "lite"
) -> ParallelTaskDiscovery:
    return _make(transport=_recorded_transport(captured), processor=processor)


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
    protocol_version = "1.0"
    provider_id = "stub"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(
        self, *, query: str, max_results: int = 10, recency_days: int | None = None
    ) -> list[SearchResult]:
        self.queries.append(query)
        return [SearchResult(url="https://nope.com", title="Nope", snippet="should not run")]


# ── 1. Identity / protocol ──────────────────────────────────────────────────


def test_module_self_registers() -> None:
    # Extra-free: importing the adapter module registers a factory under its id
    # (a pure import side effect — no SDK / key needed). Runs on the bare matrix.
    from metalworks.research.discovery import DISCOVERY_PROVIDERS

    assert "parallel_task" in DISCOVERY_PROVIDERS


def test_provider_is_agentic() -> None:
    from metalworks.research.discovery import DiscoveryProvider

    provider = _provider()
    assert isinstance(provider, DiscoveryProvider)
    assert provider.agentic is True
    assert provider.provider_id == "parallel_task"


# ── 2. Cite-or-die: Basis excerpts only, NEVER the synthesized output ───────


def test_discover_maps_basis_excerpts_verbatim() -> None:
    provider = _provider()
    found = provider.discover(
        question="what do gym-goers want in a focus supplement",
        directions=["pricing"],
        budget=DiscoveryBudget(max_findings=25, max_domains=12),
    )
    # One finding per cited excerpt across both basis fields (2 + 1 + 1 = 4).
    assert len(found) == 4
    quotes = {f.quote for f in found}
    assert "Most people just want it to not give them jitters at 4pm." in quotes
    assert "Anything over $40 a month is a hard no for me." in quotes

    # CITE-OR-DIE: the synthesized output.content NEVER becomes a quote.
    assert all(_SYNTHESIZED_PROSE not in f.quote for f in found)

    # Each finding carries url + title + provenance extras (confidence + domain).
    by_url = {f.source_url: f for f in found}
    pricing = by_url["https://www.forum.example/thread/2"]
    assert pricing.title == "Pricing thread"
    assert pricing.extra["confidence"] == "medium"
    assert pricing.extra["domain"] == "forum.example"  # www. stripped
    pain = by_url["https://www.forum.example/thread/1"]
    assert pain.extra["confidence"] == "high"


def test_request_uses_default_lite_processor() -> None:
    import json

    captured_post: dict[str, Any] = {}

    def post_handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path == "/v1/tasks/runs":
            captured_post["body"] = req.read()
            return httpx.Response(200, json={"run_id": "x"})
        return httpx.Response(200, json=_RECORDED_RESULT)

    provider = _make(transport=httpx.MockTransport(post_handler), api_key="k")
    provider.discover(question="q", directions=["pricing"], budget=DiscoveryBudget())
    body = json.loads(captured_post["body"])
    # The create-run POST carried the cheapest default tier and the objective.
    assert body["processor"] == "lite"
    assert "q" in body["input"]
    assert "pricing" in body["input"]


def test_budget_caps_findings_and_domains() -> None:
    provider = _provider()
    # max_findings=1 → stop after the first cited excerpt.
    one = provider.discover(question="q", directions=[], budget=DiscoveryBudget(max_findings=1))
    assert len(one) == 1
    # max_domains=1 → only the first distinct host's excerpts survive
    # (forum.example has 3 excerpts across two threads; blog.example is dropped).
    capped = provider.discover(
        question="q", directions=[], budget=DiscoveryBudget(max_findings=25, max_domains=1)
    )
    assert {f.extra["domain"] for f in capped} == {"forum.example"}


@pytest.mark.parametrize(
    "result",
    [
        {},  # empty result
        {"output": {"content": "x"}},  # synthesized prose but no basis
        {"output": {"basis": ["junk", 3]}},  # malformed basis entries
        {"output": {"basis": [{"citations": [{"excerpts": ["q"]}]}]}},  # citation w/o url
    ],
)
def test_empty_or_malformed_basis_yields_nothing(result: dict[str, Any]) -> None:
    # Defensive parsing: a degenerate Parallel result → no findings, no crash.
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json={"run_id": "x"})
        return httpx.Response(200, json=result)

    provider = _make(transport=httpx.MockTransport(handler), api_key="k")
    assert provider.discover(question="q", directions=[], budget=DiscoveryBudget()) == []


# ── 3. The gate: configured → delegate, homegrown loop OFF ──────────────────


def test_gate_delegates_to_parallel_and_loop_does_not_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The provider is resolvable; a SearchProvider is ALSO present. The agentic
    # provider must win, and the homegrown loop must never touch search.
    provider = _provider()
    monkeypatch.setattr(config, "resolve_discovery", lambda: provider)
    # Even with the loop opted in, the agentic provider takes precedence.
    monkeypatch.setattr(config, "discovery_loop_enabled", lambda: True)

    search = _StubSearch()
    chat = FakeChatModel(grounded=False)
    deps = _deps(chat, search=search, discovery=config.resolve_discovery())
    findings = web_research(deps, brief=_brief())

    assert search.queries == []  # homegrown loop never ran
    assert all(c["kind"] != "structured" for c in chat.calls)  # no follow-up LLM
    assert findings  # delegated to Parallel and produced grounded findings
    specifics = {f.specifics for f in findings}
    assert "Most people just want it to not give them jitters at 4pm." in specifics
    assert all(_SYNTHESIZED_PROSE not in s for s in specifics)


# ── 4. Resolution: configured ↔ key, unconfigured → None ────────────────────


def test_resolve_discovery_unkeyed_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Extra-free, runs on the bare matrix: unconfigured → not selected, no crash.
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    assert config.resolve_discovery() is None


def test_resolve_discovery_keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("parallel")
    # Configured → the Parallel Task provider (lazy import behind the extra),
    # tripping the chassis gate.
    monkeypatch.setenv("PARALLEL_API_KEY", "test-key")
    resolved = config.resolve_discovery()
    assert resolved is not None
    assert resolved.provider_id == "parallel_task"
    assert resolved.agentic is True


def test_resolve_discovery_keyed_without_extra_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # The key is present but the `parallel` extra is NOT importable → config
    # swallows MissingExtraError and returns None (never crashes a run). Simulated
    # by blocking the import so this holds on BOTH matrices.
    import sys

    monkeypatch.setenv("PARALLEL_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "parallel", None)  # None entry → ImportError
    assert config.resolve_discovery() is None


# ── 5. Live smoke (network) ─────────────────────────────────────────────────


@pytest.mark.network
def test_live_parallel_task_smoke() -> None:  # pragma: no cover - network
    if not os.environ.get("PARALLEL_API_KEY"):
        pytest.skip("PARALLEL_API_KEY not set")
    provider = ParallelTaskDiscovery()
    found = provider.discover(
        question="What do people complain about with focus supplements?",
        directions=["jitters", "price"],
        budget=DiscoveryBudget(max_findings=5, max_domains=5),
    )
    # Cite-or-die holds against a real response: every finding is a real quote+url.
    assert all(f.quote and f.source_url for f in found)
