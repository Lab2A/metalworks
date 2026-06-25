"""Exa Research agentic discovery adapter (#156) — all offline.

A recorded Exa research response (synthesized answer prose + field-level
citations with verbatim excerpts) stands in for the live SDK. The load-bearing
assertions:

1. ``discover`` maps citations → ``DiscoveryFinding``s carrying the VERBATIM
   excerpt + its URL — cite-or-die.
2. The synthesized ``output.content`` answer text NEVER leaks into a finding.
3. ``config.resolve_discovery()`` picks the provider when ``EXA_API_KEY`` is set
   and the gate in ``web_research`` delegates to it (homegrown loop stays off).
4. Keyless / SDK-absent → not selected / ``MissingExtraError``; no crash.

A ``network``-marked live smoke exercises the real endpoint when a key is present.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from metalworks import config
from metalworks.errors import MissingExtraError, MissingKeyError

# The synthesized answer prose — this must NEVER appear in any finding.
_ANSWER_PROSE = (
    "In summary, most users prefer a focus supplement without an afternoon crash, "
    "and price sensitivity clusters around the $30 mark."
)

# Field-level citations: each is a verbatim excerpt + its source URL. These ARE
# what becomes findings.
_CITATIONS = [
    {
        "url": "https://forum.example/thread/1",
        "title": "What focus stack actually works?",
        "snippet": "Honestly I just want something that doesn't give me jitters at 4pm.",
        "author": "u/lifter",
    },
    {
        "url": "https://reddit.com/r/Supplements/comments/abc",
        "title": "Price check",
        "text": "Anything over thirty bucks a month and I'm out, full stop.",
    },
    # A duplicate URL → deduped to one finding.
    {
        "url": "https://forum.example/thread/1",
        "title": "dup",
        "snippet": "second excerpt, same url",
    },
    # No verbatim excerpt → dropped, never invented.
    {"url": "https://empty.example", "title": "no quote"},
]


class _FakeResearch:
    """Stub of ``exa.research`` — create + poll return a recorded result."""

    def __init__(self, result: Any) -> None:
        self._result = result
        self.instructions: str | None = None

    def create(self, *, instructions: str) -> Any:
        self.instructions = instructions
        return SimpleNamespace(research_id="res-123")

    def poll_until_finished(self, research_id: str, *, timeout_ms: int) -> Any:
        assert research_id == "res-123"
        return self._result


class _FakeExaClient:
    def __init__(self, *, citations: Any = None, content: str = _ANSWER_PROSE) -> None:
        output = SimpleNamespace(
            content=content,
            citations=_CITATIONS if citations is None else citations,
        )
        result = SimpleNamespace(status="completed", output=output)
        self.research = _FakeResearch(result)


def _provider(monkeypatch: pytest.MonkeyPatch, client: Any) -> Any:
    """Build an ExaResearchDiscovery whose SDK + key are stubbed to ``client``.

    Patches the lazily-imported ``exa_py`` module so the real constructor path
    runs (no private attribute reaching), with ``Exa(...)`` returning our fake.
    """
    from metalworks.research.discovery.exa import ExaResearchDiscovery

    fake_exa = ModuleType("exa_py")
    fake_exa.Exa = lambda **_kw: client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "exa_py", fake_exa)
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    return ExaResearchDiscovery(timeout_ms=1000)


# ── 1. Protocol shape ───────────────────────────────────────────────────────


def test_implements_discovery_provider_agentic(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.research.discovery import DiscoveryProvider

    prov = _provider(monkeypatch, _FakeExaClient())
    assert isinstance(prov, DiscoveryProvider)
    assert prov.agentic is True
    assert prov.provider_id == "exa_research"


# ── 2. Cite-or-die: citations → verbatim findings, NOT the answer prose ──────


def test_discover_maps_citations_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.research.discovery import DiscoveryBudget

    prov = _provider(monkeypatch, _FakeExaClient())
    found = prov.discover(
        question="what do gym-goers want in a focus supplement",
        directions=["pricing"],
        budget=DiscoveryBudget(max_findings=25, max_domains=12),
    )

    # Two distinct-URL cited excerpts with quotes survive (dup deduped, no-quote dropped).
    assert len(found) == 2
    quotes = {f.quote for f in found}
    assert "Honestly I just want something that doesn't give me jitters at 4pm." in quotes
    assert "Anything over thirty bucks a month and I'm out, full stop." in quotes

    by_url = {f.source_url: f for f in found}
    assert by_url["https://forum.example/thread/1"].extra["domain"] == "forum.example"
    assert by_url["https://reddit.com/r/Supplements/comments/abc"].extra["domain"] == "reddit.com"
    assert by_url["https://forum.example/thread/1"].author == "u/lifter"


def test_answer_prose_never_becomes_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cite-or-die line: the synthesized summary is dropped on the floor."""
    from metalworks.research.discovery import DiscoveryBudget

    prov = _provider(monkeypatch, _FakeExaClient())
    found = prov.discover(question="q", directions=[], budget=DiscoveryBudget(max_findings=25))
    for f in found:
        assert _ANSWER_PROSE not in f.quote
        assert f.quote != _ANSWER_PROSE
    # And the prose is not smuggled in verbatim anywhere.
    assert _ANSWER_PROSE not in {f.quote for f in found}


def test_citations_keyed_by_field_are_flattened(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exa may return citations keyed by output field (a dict of lists)."""
    from metalworks.research.discovery import DiscoveryBudget

    keyed = {
        "valuation": [_CITATIONS[0]],
        "price": [_CITATIONS[1]],
    }
    prov = _provider(monkeypatch, _FakeExaClient(citations=keyed))
    found = prov.discover(question="q", directions=[], budget=DiscoveryBudget())
    assert {f.source_url for f in found} == {
        "https://forum.example/thread/1",
        "https://reddit.com/r/Supplements/comments/abc",
    }


def test_budget_caps_findings_and_domains(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.research.discovery import DiscoveryBudget

    prov = _provider(monkeypatch, _FakeExaClient())
    found = prov.discover(question="q", directions=[], budget=DiscoveryBudget(max_findings=1))
    assert len(found) == 1


def test_missing_output_degrades_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.research.discovery import DiscoveryBudget

    prov = _provider(monkeypatch, _FakeExaClient(citations=[]))
    assert prov.discover(question="q", directions=[], budget=DiscoveryBudget()) == []


# ── 3. resolve_discovery + the gate delegates to it ─────────────────────────


def test_resolve_discovery_picks_exa_when_keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    # Make the SDK importable + the Exa() constructor a no-op so resolve succeeds
    # without the real extra.
    fake_exa = ModuleType("exa_py")
    fake_exa.Exa = lambda **_kw: _FakeExaClient()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "exa_py", fake_exa)

    prov = config.resolve_discovery()
    assert prov is not None
    assert prov.agentic is True
    assert prov.provider_id == "exa_research"


def test_resolve_discovery_none_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    assert config.resolve_discovery() is None


def test_gate_delegates_to_exa_research(monkeypatch: pytest.MonkeyPatch) -> None:
    """With Exa Research resolvable, web_research delegates — homegrown loop OFF."""
    from metalworks.contract import ResearchBrief, TargetSubreddit
    from metalworks.embeddings import FakeEmbedding
    from metalworks.llm import FakeChatModel
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.web import web_research
    from metalworks.stores import MemoryStores

    class _NullReader:
        def latest_available_month(self, content_type: str = "submissions") -> object:
            raise NotImplementedError

        def pull_subreddit(self, **_kw: object) -> object:
            raise NotImplementedError

        def fetch_submissions_by_ids(self, _ids: object, _months: object) -> object:
            raise NotImplementedError

        def close(self) -> None:
            return None

    prov = _provider(monkeypatch, _FakeExaClient())
    brief = ResearchBrief(
        brief_id="b1",
        question="what do gym-goers want in a focus supplement",
        decision_context="d",
        success_criteria=["s"],
        must_address=["m"],
        target_subreddits=[TargetSubreddit(name="Supplements", rationale="core")],
        web_research_directions=["pricing"],
        relevance_rubric="r",
    )
    chat = FakeChatModel(grounded=False)
    deps = ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_NullReader(),
        search=None,
        discovery=prov,  # type: ignore[arg-type]
    )
    findings = web_research(deps, brief=brief)

    # Delegated: findings carry the verbatim Exa citation quotes, NOT the answer.
    assert findings
    specifics = {f.specifics for f in findings}
    assert "Honestly I just want something that doesn't give me jitters at 4pm." in specifics
    assert _ANSWER_PROSE not in specifics
    # No homegrown follow-up-query LLM call fired (loop stayed off).
    assert all(c["kind"] != "structured" for c in chat.calls)


# ── 4. extra / key guards ───────────────────────────────────────────────────


def test_missing_sdk_raises_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.research.discovery.exa import ExaResearchDiscovery

    monkeypatch.setitem(sys.modules, "exa_py", None)  # None → ImportError
    with pytest.raises(MissingExtraError) as excinfo:
        ExaResearchDiscovery()
    assert "pip install" in (excinfo.value.fix or "")


def test_missing_key_raises_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.research.discovery.exa import ExaResearchDiscovery

    fake_exa = ModuleType("exa_py")
    fake_exa.Exa = lambda **_kw: SimpleNamespace()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "exa_py", fake_exa)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with pytest.raises(MissingKeyError) as excinfo:
        ExaResearchDiscovery()
    assert "EXA_API_KEY" in (excinfo.value.fix or "")


# ── 5. live smoke (network) ─────────────────────────────────────────────────


@pytest.mark.network
def test_live_exa_research_smoke() -> None:  # pragma: no cover - network
    import os

    if not os.environ.get("EXA_API_KEY"):
        pytest.skip("EXA_API_KEY not set")
    from metalworks.research.discovery import DiscoveryBudget
    from metalworks.research.discovery.exa import ExaResearchDiscovery

    prov = ExaResearchDiscovery()
    found = prov.discover(
        question="what do people complain about in budget mechanical keyboards",
        directions=["switches", "build quality"],
        budget=DiscoveryBudget(max_findings=5, max_domains=5),
    )
    for f in found:
        assert f.quote and f.source_url
