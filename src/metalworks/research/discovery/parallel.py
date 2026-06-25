"""Parallel (parallel.ai) **Task API** agentic discovery adapter (``metalworks[parallel]``).

This is the second agentic :class:`~metalworks.research.discovery.DiscoveryProvider`
(P4.2). Parallel's Task API is a managed deep-research engine — multi-minute, depth
tiered — that returns the **Basis** framework: per-output-field **citations** (each
with a source ``url``, a ``title``, and verbatim ``excerpts``) plus per-field
``reasoning`` and ``confidence``. That makes it the most verifiable of the agentic
providers, and it is the only thing this adapter ingests.

**Cite-or-die — what we map, and what we DON'T.**
``discover`` runs a Task and consumes ONLY the Basis citations + excerpts. Each cited
excerpt becomes one :class:`~metalworks.research.discovery.DiscoveryFinding` whose
``quote`` is the excerpt *verbatim*, ``source_url`` the citation url, ``title`` the
citation title, and ``extra={"confidence": ..., "domain": ...}``. We **never** ingest
``output.content`` — Parallel's synthesized task-output prose — because that is a
summary, not a grounded quote. The deterministic scorer downstream re-scores on the
real excerpts; ``extra["confidence"]`` is carried for provenance only and does NOT
feed the verdict band.

**Budget → depth tier.** A :class:`~metalworks.research.discovery.DiscoveryBudget`
maps to a Parallel *processor* tier. We default to the cheapest deep-research tier,
**``lite``** (≈ $5 / 1k task runs at the time of writing — the cost-aware default;
deeper ``base``/``core``/``pro``/``ultra`` tiers cross-reference more sources and cost
1-3 orders of magnitude more, and are intentionally out of scope here). The budget's
``max_findings`` caps how many cited excerpts we keep; ``max_domains`` caps distinct
hosts; rounds do not apply (Parallel runs its own internal loop).

**Integration approach — httpx against the REST endpoints**, not the SDK call surface.
Mirrors :mod:`metalworks.search.adapters.parallel`: the ``parallel-web`` SDK namespace
is still beta and has shifted between releases, so we pin to the stable, documented REST
contract (``POST /v1/tasks/runs`` then ``GET /v1/tasks/runs/{id}/result``) over
``httpx`` (already a core dependency). We still lazy-import the ``parallel`` package in
``__init__`` purely to gate the ``parallel`` extra (raising
:class:`~metalworks.errors.MissingExtraError` when absent), so the install story matches
Exa/Tavily exactly and the bare matrix stays green.

REST reference (verified 2026-06): ``POST https://api.parallel.ai/v1/tasks/runs`` then
``GET https://api.parallel.ai/v1/tasks/runs/{run_id}/result``, header ``x-api-key``.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import TYPE_CHECKING, Any, ClassVar, cast
from urllib.parse import urlsplit

import httpx

from metalworks.errors import MissingExtraError, MissingKeyError
from metalworks.research.discovery import (
    PROTOCOL_VERSION,
    DiscoveryFinding,
    register_discovery,
)

if TYPE_CHECKING:
    from metalworks.research.discovery import DiscoveryBudget

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.parallel.ai"
_RUNS_PATH = "/v1/tasks/runs"
# Cheapest deep-research tier (cost-aware default; see module docstring).
_DEFAULT_PROCESSOR = "lite"
# A single multi-minute Task run plus result poll. Generous, but Parallel's
# Task API is intentionally slow (it is the iterate-and-dig that replaces our loop).
_TIMEOUT_S = 600.0


def _domain_of(url: str) -> str:
    """The host without a leading ``www.`` — the unit ``max_domains`` counts."""
    host = urlsplit((url or "").strip()).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


class ParallelTaskDiscovery:
    """Agentic ``DiscoveryProvider`` over Parallel's Task API (Basis citations).

    ``agentic`` is ``True``: when this is configured the chassis gate in
    :mod:`metalworks.research.web` delegates the whole discovery to ``discover``
    and metalworks' homegrown iterate-and-dig loop does NOT run. ``discover`` maps
    each Basis **citation excerpt** to a cite-or-die :class:`DiscoveryFinding`
    (verbatim quote + url), never Parallel's synthesized task output.
    """

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "parallel_task"
    agentic: bool = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        processor: str = _DEFAULT_PROCESSOR,
        client: httpx.Client | None = None,
    ) -> None:
        # Gate the `parallel` extra. We call the REST endpoint over httpx (see
        # module docstring), but the import keeps the MissingExtraError contract
        # identical to the SDK-backed adapters and the bare matrix green.
        try:
            importlib.import_module("parallel")
        except ImportError as exc:
            raise MissingExtraError("parallel", package="parallel-web") from exc
        key = api_key or os.environ.get("PARALLEL_API_KEY")
        if not key:
            raise MissingKeyError("PARALLEL_API_KEY", provider="Parallel")
        self._api_key: str = key
        self._processor = processor
        # An injected client lets tests drive a stub/recorded transport offline;
        # in production we make a fresh client per call (no shared mutable state).
        self._client = client

    def discover(
        self,
        *,
        question: str,
        directions: list[str],
        budget: DiscoveryBudget,
    ) -> list[DiscoveryFinding]:
        """Run a Task and map its Basis citation excerpts → cite-or-die findings.

        Consumes ONLY ``output.basis[].citations[].excerpts`` (verbatim quotes),
        never ``output.content`` (the synthesized prose). ``budget.max_findings``
        caps kept excerpts; ``budget.max_domains`` caps distinct hosts.
        """
        objective = self._objective(question, directions)
        payload = self._run_task(objective)
        return self._findings_from_basis(payload, budget)

    # ── internals ──

    @staticmethod
    def _objective(question: str, directions: list[str]) -> str:
        """The Task ``input`` — the research goal plus the brief's directions."""
        dirs = [d.strip() for d in directions if d and d.strip()]
        if not dirs:
            return question
        joined = "; ".join(dirs)
        return f"{question}\n\nAlso investigate these angles: {joined}."

    def _run_task(self, objective: str) -> dict[str, Any]:
        """Create a Task run, then fetch its result. Returns the raw result JSON.

        Uses the injected client when present (tests), else a fresh one. Any
        transport/HTTP error propagates — the chassis gate wraps ``discover`` in a
        try/except and degrades to no findings, so a Parallel outage never crashes
        a run.
        """
        headers = {
            "x-api-key": self._api_key,
            "content-type": "application/json",
        }
        body = {"input": objective, "processor": self._processor}
        if self._client is not None:
            return self._execute(self._client, headers, body)
        with httpx.Client(base_url=_BASE_URL, timeout=_TIMEOUT_S) as client:
            return self._execute(client, headers, body)

    @staticmethod
    def _execute(
        client: httpx.Client, headers: dict[str, str], body: dict[str, Any]
    ) -> dict[str, Any]:
        create = client.post(_RUNS_PATH, json=body, headers=headers)
        create.raise_for_status()
        run: dict[str, Any] = cast("dict[str, Any]", create.json() or {})
        run_id = str(run.get("run_id") or run.get("id") or "")
        if not run_id:
            return {}
        result = client.get(f"{_RUNS_PATH}/{run_id}/result", headers=headers)
        result.raise_for_status()
        return cast("dict[str, Any]", result.json() or {})

    def _findings_from_basis(
        self, payload: dict[str, Any], budget: DiscoveryBudget
    ) -> list[DiscoveryFinding]:
        """Map ``output.basis[].citations[].excerpts`` → cite-or-die findings.

        One finding per cited excerpt (verbatim quote + citation url). The
        synthesized ``output.content`` is intentionally ignored. Dedupes by
        (url, quote); honours ``max_findings`` / ``max_domains`` deterministically.
        """
        output = payload.get("output")
        if not isinstance(output, dict):
            return []
        output_dict = cast("dict[str, Any]", output)
        basis = output_dict.get("basis")
        if not isinstance(basis, list):
            return []
        basis_list = cast("list[Any]", basis)

        findings: list[DiscoveryFinding] = []
        seen: set[tuple[str, str]] = set()
        seen_domains: set[str] = set()

        for field in basis_list:
            if not isinstance(field, dict):
                continue
            field_dict = cast("dict[str, Any]", field)
            confidence = str(field_dict.get("confidence") or "").strip()
            citations = field_dict.get("citations")
            citation_list: list[Any] = (
                cast("list[Any]", citations) if isinstance(citations, list) else []
            )
            for citation in citation_list:
                if not isinstance(citation, dict):
                    continue
                citation_dict = cast("dict[str, Any]", citation)
                url = str(citation_dict.get("url") or "").strip()
                title = str(citation_dict.get("title") or "").strip()
                if not url:
                    continue
                domain = _domain_of(url)
                # A new distinct domain past the ceiling is dropped; excerpts on a
                # domain we already count are still admitted (more evidence).
                new_domain = bool(domain) and domain not in seen_domains
                if new_domain and len(seen_domains) >= budget.max_domains:
                    continue
                excerpts = citation_dict.get("excerpts")
                excerpt_list: list[Any] = (
                    cast("list[Any]", excerpts) if isinstance(excerpts, list) else []
                )
                for raw in excerpt_list:
                    quote = str(raw or "").strip()
                    if not quote or (url, quote) in seen:
                        continue
                    seen.add((url, quote))
                    if domain:
                        seen_domains.add(domain)
                    extra: dict[str, str] = {}
                    if confidence:
                        extra["confidence"] = confidence
                    if domain:
                        extra["domain"] = domain
                    findings.append(
                        DiscoveryFinding(
                            quote=quote,  # VERBATIM excerpt, never output.content
                            source_url=url,
                            title=title,
                            author=None,
                            extra=extra,
                        )
                    )
                    if len(findings) >= budget.max_findings:
                        return findings
        return findings


def _build() -> ParallelTaskDiscovery:
    """Registry factory — constructs from the ambient ``PARALLEL_API_KEY``."""
    return ParallelTaskDiscovery()


register_discovery("parallel_task", _build)


__all__ = ["ParallelTaskDiscovery"]
