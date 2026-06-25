"""Agentic web-discovery — the iterate-and-dig tier ABOVE single-shot search.

The capability ladder (the architecture decision this package implements):

```
DiscoveryProvider (agentic):  Exa Research / Parallel Task → DELEGATE (loop OFF)
   else → HomegrownDiscovery (this module's iterate-and-dig loop)
      else → web.py's single-pass _external_search  (unchanged fallback)
```

Today web research is single-pass: ``web_research`` fans out
``queries = [brief_question, *directions]`` once over ``SearchProvider.search``
and stops. Phase 4 makes discovery **agentic** — iterate-and-dig — so the long
tail (niche forums, blogs, Quora, blocked review sites' underlying pages) gets
reached without a per-venue connector. This package adds the abstraction
(``DiscoveryProvider``), the homegrown loop (``HomegrownDiscovery``), and the
registry; the keyed agentic adapters (Exa Research P4.1, Parallel Task P4.2)
are follow-on issues that simply register an ``agentic=True`` provider, which
trips the gate in :mod:`metalworks.research.web`.

Two non-negotiables this package preserves:

- **Cite-or-die.** A :class:`DiscoveryFinding` is the cite-or-die unit: it
  carries the underlying *verbatim* ``quote`` + ``source_url`` (+ ``author``
  when present), NEVER a synthesized summary. Findings map onto the existing
  corpus spine (``CorpusRecord`` / ``WebFinding``) with the QUOTE, so the
  deterministic scorer runs on real quotes. This is the line that separates
  metalworks from "summary-on-top-of-evidence."

- **Determinism.** :class:`HomegrownDiscovery`'s "what to search next" is an LLM
  call. This is **discovery / corpus-construction, NOT the verdict** — the same
  class as :func:`metalworks.research.planner.subreddit_picker.pick_target_subreddits`,
  so it is allowed under "decisions are deterministic, the LLM writes only
  prose / proposes only queries." The verdict still scores deterministically
  downstream on the grounded quotes the loop returns. The budget (rounds /
  findings / domains) is a pure, deterministic stop condition; the LLM only
  *proposes* follow-up queries — it never decides when to stop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Callable

    from metalworks.llm import ChatModel
    from metalworks.search import SearchProvider, SearchResult

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "1.0"


# ── The cite-or-die unit ────────────────────────────────────────────────────


@dataclass(frozen=True)
class DiscoveryFinding:
    """One grounded discovery hit — the cite-or-die unit.

    ``quote`` is a *verbatim* fragment of the underlying source (the search
    result's snippet/highlight, or an agentic provider's extracted excerpt),
    NEVER a synthesized summary. ``source_url`` is where it came from. Together
    they map onto the corpus spine so the deterministic scorer runs on a real
    quote, not on model prose.
    """

    quote: str
    source_url: str
    title: str
    author: str | None = None
    extra: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class DiscoveryBudget:
    """Deterministic stop condition for the iterate-and-dig loop.

    The loop stops when ANY ceiling is reached (or a round adds nothing new).
    This is a pure budget — the LLM never decides when to stop; it only proposes
    the next round's queries.
    """

    max_rounds: int = 3
    max_findings: int = 25
    max_domains: int = 12


# ── The provider abstraction ────────────────────────────────────────────────


@runtime_checkable
class DiscoveryProvider(Protocol):
    """A web-discovery tier above single-shot search.

    ``agentic`` is the gate signal: an ``agentic=True`` provider does its own
    iterate-and-dig (Exa Research, Parallel Task), so metalworks' homegrown loop
    does NOT run — :mod:`metalworks.research.web` delegates the whole thing to
    ``discover``. :class:`HomegrownDiscovery` reports ``agentic=False``: it is
    metalworks' *own* loop over a plain ``SearchProvider``, the rung used only
    when no agentic provider is configured.
    """

    protocol_version: ClassVar[str]
    provider_id: str
    agentic: bool

    def discover(
        self,
        *,
        question: str,
        directions: list[str],
        budget: DiscoveryBudget,
    ) -> list[DiscoveryFinding]: ...


# ── Registry (mirrors research.sources.register_source) ─────────────────────

DISCOVERY_PROVIDERS: dict[str, Callable[..., DiscoveryProvider]] = {}


def register_discovery(provider_id: str, factory: Callable[..., DiscoveryProvider]) -> None:
    """Register ``factory`` under ``provider_id`` (idempotent on re-import).

    Re-registering the same id overwrites — module re-imports under pytest must
    not raise, and a downstream override of a built-in is intentional. Mirrors
    :func:`metalworks.research.sources.register_source`.
    """
    DISCOVERY_PROVIDERS[provider_id] = factory


def get_discovery(provider_id: str, **kwargs: object) -> DiscoveryProvider:
    """Construct the registered discovery provider for ``provider_id``.

    Unknown ids raise ``KeyError`` naming what is registered.
    """
    try:
        factory = DISCOVERY_PROVIDERS[provider_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown discovery provider {provider_id!r}; registered: {sorted(DISCOVERY_PROVIDERS)}"
        ) from exc
    return factory(**kwargs)


# ── Homegrown iterate-and-dig loop ──────────────────────────────────────────


class _FollowupQueries(BaseModel):
    """The LLM's proposed next-round queries (discovery, not verdict)."""

    queries: list[str] = Field(
        default_factory=list[str],
        description="New search queries to dig deeper, beyond what already surfaced.",
    )


_FOLLOWUP_SYSTEM_PROMPT = (
    "You are a web-research scout running an iterate-and-dig loop. Given the "
    "research question and a sample of what the last search round surfaced, "
    "propose 2-5 NEW search queries that would reach evidence the current "
    "results miss — niche forums, specific products, contrarian takes, "
    "underlying primary sources.\n\n"
    "Hard rules:\n"
    "1. Propose queries only. Do NOT summarize, conclude, or answer the question.\n"
    "2. Each query is a short search string, not a sentence or a URL.\n"
    "3. Prefer queries that broaden DOMAIN coverage, not re-runs of what was "
    "already searched.\n"
    "4. If the surfaced results already cover the space well, return fewer "
    "queries (or none) rather than padding with weak ones."
)


def _domain_of(url: str) -> str:
    """The host without a leading ``www.`` — the unit ``max_domains`` counts."""
    host = urlsplit((url or "").strip()).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


class HomegrownDiscovery:
    """metalworks' own iterate-and-dig loop over a single-shot ``SearchProvider``.

    Round 1 searches the brief's queries (``[question, *directions]``). Each
    subsequent round, the LLM proposes follow-up queries from what surfaced
    (deduped against already-run queries); those are searched and new-by-URL
    hits are kept. The loop stops when the budget is hit (rounds / findings /
    distinct domains) OR a round adds no new findings.

    ``agentic`` is ``False``: this is the homegrown rung, used only when no
    agentic :class:`DiscoveryProvider` is configured. The follow-up-query LLM
    call is discovery (corpus construction), NOT the verdict — same allowance as
    :func:`pick_target_subreddits`. The budget is a pure deterministic stop; the
    LLM only proposes queries. Each hit becomes a :class:`DiscoveryFinding`
    carrying the result's verbatim snippet as the quote (cite-or-die), never a
    summary.
    """

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "homegrown"
    agentic: bool = False

    # How many results to request per query, and how many surfaced titles to
    # show the LLM when it proposes the next round (kept small + deterministic).
    _PER_QUERY = 5
    _SAMPLE_FOR_LLM = 8

    def __init__(self, *, search: SearchProvider, chat: ChatModel) -> None:
        self._search = search
        self._chat = chat

    def discover(
        self,
        *,
        question: str,
        directions: list[str],
        budget: DiscoveryBudget,
    ) -> list[DiscoveryFinding]:
        findings: list[DiscoveryFinding] = []
        seen_urls: set[str] = set()
        seen_domains: set[str] = set()
        run_queries: set[str] = set()

        queries = [question, *directions]
        rounds = max(1, budget.max_rounds)

        for round_idx in range(rounds):
            new_this_round = 0
            for query in queries:
                key = query.strip().lower()
                if not key or key in run_queries:
                    continue
                run_queries.add(key)
                for hit in self._search_one(query):
                    if self._full(findings, seen_domains, budget):
                        break
                    added = self._consume(hit, findings, seen_urls, seen_domains, budget)
                    new_this_round += int(added)
                if self._full(findings, seen_domains, budget):
                    break

            if self._full(findings, seen_domains, budget):
                break
            # Stop when a round adds nothing new — no point asking the LLM to dig
            # into a space we have already exhausted.
            if new_this_round == 0 and round_idx > 0:
                break
            if round_idx + 1 >= rounds:
                break
            queries = self._propose_followups(question, findings, run_queries)
            if not queries:
                break

        return findings

    # ── internals ──

    def _search_one(self, query: str) -> list[SearchResult]:
        try:
            return self._search.search(query=query, max_results=self._PER_QUERY)
        except Exception as exc:  # provider hiccup → skip this query, keep digging
            logger.debug("HomegrownDiscovery: search(%r) failed (%s); skipping", query, exc)
            return []

    def _consume(
        self,
        hit: SearchResult,
        findings: list[DiscoveryFinding],
        seen_urls: set[str],
        seen_domains: set[str],
        budget: DiscoveryBudget,
    ) -> bool:
        """Map one search hit → a DiscoveryFinding if it is new by URL.

        Returns True when a finding was added. The quote is the result's
        verbatim snippet — never a summary (cite-or-die).
        """
        url = (hit.url or "").strip()
        snippet = (hit.snippet or "").strip()
        if not url or not snippet or url in seen_urls:
            return False
        domain = _domain_of(url)
        # A new distinct domain past the ceiling is dropped, but a hit on a
        # domain we already count is still admitted (more evidence, same breadth).
        if domain and domain not in seen_domains and len(seen_domains) >= budget.max_domains:
            return False
        seen_urls.add(url)
        if domain:
            seen_domains.add(domain)
        findings.append(
            DiscoveryFinding(
                quote=snippet,
                source_url=url,
                title=(hit.title or "").strip(),
                author=None,
                extra={"domain": domain} if domain else {},
            )
        )
        return True

    @staticmethod
    def _full(
        findings: list[DiscoveryFinding], seen_domains: set[str], budget: DiscoveryBudget
    ) -> bool:
        return len(findings) >= budget.max_findings or len(seen_domains) >= budget.max_domains

    def _propose_followups(
        self,
        question: str,
        findings: list[DiscoveryFinding],
        run_queries: set[str],
    ) -> list[str]:
        """Ask the LLM for the next round's queries (discovery, not verdict).

        Deduped against already-run queries. On any LLM failure the loop simply
        stops digging (returns ``[]``) — a degraded path, not an error.
        """
        if not findings:
            return []
        sample = "\n".join(
            f"- {f.title or f.source_url} ({_domain_of(f.source_url)})"
            for f in findings[: self._SAMPLE_FOR_LLM]
        )
        user = (
            f"RESEARCH QUESTION: {question}\n\n"
            f"WHAT THE LAST ROUNDS SURFACED:\n{sample}\n\n"
            "Propose 2-5 NEW search queries to dig into evidence these miss."
        )
        try:
            out = self._chat.complete_structured(
                system=_FOLLOWUP_SYSTEM_PROMPT,
                user=user,
                output_model=_FollowupQueries,
                max_tokens=1024,
                temperature=0.3,
            )
        except Exception as exc:
            logger.debug("HomegrownDiscovery: follow-up LLM failed (%s); stopping loop", exc)
            return []
        out_queries: list[str] = []
        for raw in out.queries:
            q = (raw or "").strip()
            if q and q.lower() not in run_queries:
                out_queries.append(q)
        return out_queries


__all__ = [
    "DISCOVERY_PROVIDERS",
    "PROTOCOL_VERSION",
    "DiscoveryBudget",
    "DiscoveryFinding",
    "DiscoveryProvider",
    "HomegrownDiscovery",
    "get_discovery",
    "register_discovery",
]
