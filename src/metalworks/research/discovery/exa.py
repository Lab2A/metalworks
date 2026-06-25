"""Exa Research agentic ``DiscoveryProvider`` (``metalworks[exa]``, exa-py SDK).

The first agentic discovery adapter (P4.1). Exa's **Research** endpoint runs its
own iterate-and-dig loop (parallel search agents that "search again until highest
quality") and returns **field-level citations** — verbatim excerpts paired with
their source URL. This adapter consumes ONLY those cited excerpts → one
:class:`DiscoveryFinding` per excerpt (``quote`` = the verbatim highlight/excerpt,
``source_url`` = the citation URL).

Cite-or-die — the load-bearing line of this adapter: it **never ingests Exa's
synthesized answer/summary prose** (``output.content``). Only the citations'
verbatim excerpts become findings, so the deterministic scorer downstream runs on
real quotes, never model prose. ``test_discovery_exa.py`` asserts this against a
recorded response (the answer text must NOT leak into any finding).

``agentic`` is ``True``: when configured, the capability-ladder gate in
:mod:`metalworks.research.web` delegates the whole discovery to this provider and
metalworks' homegrown loop does NOT run. The SDK is lazy-imported behind the
``exa`` extra so ``import metalworks`` stays free on a bare install.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import TYPE_CHECKING, Any, ClassVar, cast
from urllib.parse import urlsplit

from metalworks.errors import MissingExtraError, MissingKeyError
from metalworks.research.discovery import (
    PROTOCOL_VERSION,
    DiscoveryBudget,
    DiscoveryFinding,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Cap how long we ask Exa's research loop to run before giving up. Discovery is
# best-effort: the gate returns [] on any failure, so a ceiling keeps a stuck
# research task from blocking the pillar.
_DEFAULT_TIMEOUT_MS = 180_000


def _domain_of(url: str) -> str:
    """The host without a leading ``www.`` (the ``extra={"domain": ...}`` value)."""
    host = urlsplit((url or "").strip()).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def _instructions(question: str, directions: list[str]) -> str:
    """The research instructions handed to Exa's loop (NOT a verdict prompt).

    Frames the research question + the brief's directions. Exa decides what to
    search and re-search; we only consume its citations. Kept plain so the
    long-tail (forums, community threads) is fair game for Exa's neural search.
    """
    lines = [question.strip()]
    extra = [d.strip() for d in directions if d.strip()]
    if extra:
        lines.append("Also investigate: " + "; ".join(extra) + ".")
    lines.append(
        "Surface real first-hand discussion and primary sources, including niche "
        "forums and community threads."
    )
    return "\n".join(lines)


class ExaResearchDiscovery:
    """Agentic ``DiscoveryProvider`` over Exa's Research/Deep endpoint.

    ``discover`` submits a research task, waits for it, then maps each
    **field-level citation** (verbatim excerpt + URL) to a
    :class:`DiscoveryFinding`. The synthesized answer prose is dropped on the
    floor (cite-or-die). The deterministic budget caps how many findings /
    distinct domains we keep — Exa runs its own loop, so ``max_rounds`` is
    advisory and not enforced client-side.
    """

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "exa_research"
    agentic: bool = True

    def __init__(
        self, *, api_key: str | None = None, timeout_ms: int = _DEFAULT_TIMEOUT_MS
    ) -> None:
        try:
            exa_py = importlib.import_module("exa_py")
        except ImportError as exc:
            raise MissingExtraError("exa", package="exa-py") from exc
        key = api_key or os.environ.get("EXA_API_KEY")
        if not key:
            raise MissingKeyError("EXA_API_KEY", provider="Exa")
        self._client: Any = exa_py.Exa(api_key=key)
        self._timeout_ms = timeout_ms

    def discover(
        self,
        *,
        question: str,
        directions: list[str],
        budget: DiscoveryBudget,
    ) -> list[DiscoveryFinding]:
        task = self._run_research(_instructions(question, directions))
        if task is None:
            return []
        return self._findings_from_citations(task, budget)

    # ── internals ──

    def _run_research(self, instructions: str) -> Any | None:
        """Submit a research task and wait for it; ``None`` on any failure.

        Exa's SDK exposes ``research.create`` + ``research.poll_until_finished``;
        older builds expose ``research.create_task`` + ``poll_task``. We probe
        both so the adapter survives minor SDK drift. Best-effort: discovery
        degrades to [] rather than raising into the pillar.
        """
        research: Any = getattr(self._client, "research", None)
        if research is None:
            logger.debug("ExaResearchDiscovery: SDK exposes no .research surface")
            return None
        try:
            create = getattr(research, "create", None) or getattr(research, "create_task", None)
            if create is None:
                return None
            task = create(instructions=instructions)
            research_id: Any = _attr(task, "research_id", "id", "researchId")
            poll = getattr(research, "poll_until_finished", None) or getattr(
                research, "poll_task", None
            )
            if poll is not None and research_id is not None:
                return poll(research_id, timeout_ms=self._timeout_ms)
            return task
        except Exception as exc:  # network / timeout / SDK shape — degrade to []
            logger.debug("ExaResearchDiscovery: research task failed (%s)", exc)
            return None

    def _findings_from_citations(
        self, task: Any, budget: DiscoveryBudget
    ) -> list[DiscoveryFinding]:
        """Map Exa's field-level citations → findings (NEVER the answer prose).

        ``output.content`` (the synthesized answer) is deliberately untouched.
        Only ``output.citations`` — verbatim excerpts + their URLs — become
        findings, deduped by URL and capped by the deterministic budget.
        """
        findings: list[DiscoveryFinding] = []
        seen_urls: set[str] = set()
        seen_domains: set[str] = set()
        for cite in self._iter_citations(task):
            if len(findings) >= budget.max_findings:
                break
            url = _attr(cite, "url", "source_url", "link")
            quote = _attr(cite, "snippet", "text", "excerpt", "extract", "content")
            if not url or not quote:
                # No verbatim excerpt to anchor on, or no URL → drop, never invent.
                continue
            if url in seen_urls:
                continue
            domain = _domain_of(url)
            if domain and domain not in seen_domains and len(seen_domains) >= budget.max_domains:
                continue
            seen_urls.add(url)
            if domain:
                seen_domains.add(domain)
            findings.append(
                DiscoveryFinding(
                    quote=quote.strip(),
                    source_url=url,
                    title=(_attr(cite, "title") or "").strip(),
                    author=(_attr(cite, "author") or None),
                    extra={"domain": domain} if domain else {},
                )
            )
        return findings

    def _iter_citations(self, task: Any) -> Iterable[Any]:
        """Yield every citation object across the research output.

        Exa returns citations either flat (``output.citations`` is a list) or
        keyed by output field (a dict of ``field -> [citation, ...]``). We also
        accept ``data.citations`` / a top-level ``.citations`` so the adapter
        survives the SDK's response-shape variants. We NEVER read
        ``output.content`` (the synthesized answer) — that is the cite-or-die
        line.
        """
        output = _attr(task, "output", "data") or task
        raw = _attr(output, "citations") or _attr(task, "citations")
        if raw is None:
            return
        groups: list[Any]
        if isinstance(raw, dict):
            # Keyed by output field → flatten every field's citation list.
            groups = list(raw.values())  # type: ignore[arg-type]
        elif isinstance(raw, list):
            groups = list(raw)  # type: ignore[arg-type]
        else:
            groups = [raw]
        for group in groups:
            if isinstance(group, list):
                yield from group  # type: ignore[misc]
            else:
                yield group


def _attr(obj: Any, *names: str) -> Any:
    """First present attribute / dict key among ``names`` (None if none/empty).

    Exa's SDK objects are pydantic-ish (attributes) but raw responses may be
    plain dicts; this reads either. Empty strings count as absent so a blank
    field falls through to the next candidate name.
    """
    for name in names:
        if isinstance(obj, dict):
            value: Any = cast("dict[str, Any]", obj).get(name)
        else:
            value = getattr(obj, name, None)
        if value:
            return value
    return None


__all__ = ["ExaResearchDiscovery"]
