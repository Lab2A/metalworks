"""Web-research stream tests: grounded + external paths, pure parsers.

Offline — FakeChatModel's grounded queue and a stub SearchProvider stand in
for real providers.
"""

from __future__ import annotations

from metalworks.contract import ResearchBrief, SignalStrength, TargetSubreddit
from metalworks.llm import FakeChatModel, GroundedResult, GroundingChunk, GroundingSupport
from metalworks.research.web import (
    _ExternalFindings,
    _is_excluded,
    parse_numbered_findings,
    split_claim_specifics,
    web_research,
)
from metalworks.search import SearchResult


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


def _deps(chat: FakeChatModel, search: object = None):
    from metalworks.embeddings import FakeEmbedding
    from metalworks.research.deps import ResearchDeps
    from metalworks.stores import MemoryStores

    store = MemoryStores()
    return ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=store,
        reader=_NullReader(),
        search=search,  # type: ignore[arg-type]
    )


class _NullReader:
    def latest_available_month(self, content_type: str = "submissions"):
        raise NotImplementedError

    def pull_subreddit(self, **_kw: object):
        raise NotImplementedError

    def fetch_submissions_by_ids(self, _ids: object, _months: object):
        raise NotImplementedError

    def close(self) -> None:
        return None


class _StubSearch:
    protocol_version = "1.0"
    provider_id = "stub"

    def __init__(self, results: list[SearchResult]):
        self._results = results

    def search(self, *, query: str, max_results: int = 10, recency_days: int | None = None):
        return self._results


# ── Pure parsers ───────────────────────────────────────────────────────────


def test_split_claim_specifics_labeled_and_fallback() -> None:
    c, s = split_claim_specifics("CLAIM: focus blends are trending\nSPECIFICS: +40% YoY")
    assert c == "focus blends are trending"
    assert s == "+40% YoY"
    # Fallback: first line is claim, rest specifics.
    c2, s2 = split_claim_specifics("creatine is popular\nmentioned 30 times")
    assert c2 == "creatine is popular"
    assert s2 == "mentioned 30 times"


def test_parse_numbered_findings_spans() -> None:
    text = "1. CLAIM: a\n   SPECIFICS: x\n2. CLAIM: b\n   SPECIFICS: y\n"
    findings = parse_numbered_findings(text)
    assert [f.claim for f in findings] == ["a", "b"]
    # Spans are non-overlapping and ascending.
    assert findings[0].char_end <= findings[1].char_start + 1
    assert parse_numbered_findings("") == []
    assert parse_numbered_findings("no numbers here") == []


def test_is_excluded_domain_and_subdomain() -> None:
    assert _is_excluded("https://www.reddit.com/r/x", ["reddit.com"]) is True
    assert _is_excluded("https://sub.reddit.com/y", ["reddit.com"]) is True
    assert _is_excluded("https://example.com", ["reddit.com"]) is False
    assert _is_excluded("https://example.com/bad/path", ["example.com/bad"]) is True


# ── Internal grounded path ─────────────────────────────────────────────────


def test_grounded_path_maps_supports_to_citations() -> None:
    text = (
        "1. CLAIM: focus blends grew\n   SPECIFICS: +40% in 2025\n"
        "2. CLAIM: price band is $30\n   SPECIFICS: median\n"
    )
    f0_start = text.index("1.")
    f1_start = text.index("2.")
    chat = FakeChatModel(grounded=True)
    chat.grounded_results.append(
        GroundedResult(
            text=text,
            chunks=(
                GroundingChunk(
                    uri="https://nielsen.com/report", title="Nielsen", published_at="2025-06-01"
                ),
                GroundingChunk(uri="https://statista.com/x", title="Statista"),
            ),
            supports=(
                # finding 0 cited by chunks 0 and 1 → MEDIUM confidence
                GroundingSupport(start_char=f0_start, end_char=f1_start - 1, chunk_indices=(0, 1)),
                # finding 1 cited by chunk 1 only → LOW
                GroundingSupport(start_char=f1_start, end_char=len(text), chunk_indices=(1,)),
            ),
        )
    )
    findings = web_research(_deps(chat), brief=_brief())
    assert len(findings) == 2
    assert findings[0].claim == "focus blends grew"
    assert findings[0].source_url == "https://nielsen.com/report"  # primary = first usable
    assert findings[0].confidence == SignalStrength.MEDIUM
    assert findings[0].published_at is not None and findings[0].published_at.year == 2025
    assert findings[1].confidence == SignalStrength.LOW
    # Provenance: claim is from the LLM text, URL is from grounding metadata.
    assert findings[1].source_url == "https://statista.com/x"


def test_grounded_excluded_source_drops_finding() -> None:
    text = "1. CLAIM: only source is excluded\n   SPECIFICS: n/a\n"
    chat = FakeChatModel(grounded=True)
    chat.grounded_results.append(
        GroundedResult(
            text=text,
            chunks=(GroundingChunk(uri="https://reddit.com/r/x", title="Reddit"),),
            supports=(GroundingSupport(start_char=0, end_char=len(text), chunk_indices=(0,)),),
        )
    )
    findings = web_research(_deps(chat), brief=_brief(excluded_sources=["reddit.com"]))
    assert findings == []  # no usable non-excluded source → dropped, never synthesized


def test_grounded_zero_chunks_returns_empty() -> None:
    chat = FakeChatModel(grounded=True)
    chat.grounded_results.append(
        GroundedResult(text="1. CLAIM: x\n SPECIFICS: y", chunks=(), supports=())
    )
    assert web_research(_deps(chat), brief=_brief()) == []


# ── External search path ───────────────────────────────────────────────────


def test_external_search_path_cites_by_index() -> None:
    chat = FakeChatModel(grounded=False)  # no native grounding → external path
    chat.script(
        _ExternalFindings,
        _ExternalFindings.model_validate(
            {
                "findings": [
                    {"claim": "market is growing", "specifics": "+40%", "source_indices": [1, 2]},
                    {"claim": "fabricated cite", "specifics": "x", "source_indices": [99]},
                ]
            }
        ),
    )
    search = _StubSearch(
        [
            SearchResult(url="https://a.com", title="A", snippet="growth data"),
            SearchResult(url="https://b.com", title="B", snippet="more data"),
        ]
    )
    findings = web_research(_deps(chat, search), brief=_brief())
    # First finding cites valid sources 1 & 2 → MEDIUM; second cites only an
    # invalid index → dropped (no fabricated provenance).
    assert len(findings) == 1
    assert findings[0].claim == "market is growing"
    assert findings[0].source_url == "https://a.com"
    assert findings[0].confidence == SignalStrength.MEDIUM


def test_no_grounding_no_search_returns_empty() -> None:
    chat = FakeChatModel(grounded=False)
    assert web_research(_deps(chat, None), brief=_brief()) == []
