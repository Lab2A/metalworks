"""Structured web-research stream → list[WebFinding].

Dual path (Inspect-AI internal/external split):

- **Internal grounding** when the chat model supports it
  (`capabilities.native_grounding`): one `complete_grounded` call. The adapter
  has already parsed Gemini/Anthropic grounding metadata into a `GroundedResult`
  with char-offset supports, so this module only maps findings → citations by
  character-span overlap. (In the source this parsing lived here and mixed
  UTF-8 byte offsets with char offsets; the adapter now converts to char
  offsets, so the overlap bucketing is correct for non-ASCII output.)
- **External search** when there's no native grounding but a `SearchProvider`
  is configured: search per research direction, then a structured LLM call
  that cites results by index.

Structural-provenance contract (NON-NEGOTIABLE, preserved from source):
- The LLM produces ONLY `claim`, `specifics`, and the ordering/citation
  indices. `source_url` / `source_title` / `published_at` come from grounding
  or search metadata, never from LLM-emitted text.
- `confidence` is service-assigned from the count of distinct supporting
  sources. Zero citations → the finding is dropped. URLs are never synthesized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from metalworks.contract import SignalStrength, WebFinding
from metalworks.errors import GroundingUnavailable

if TYPE_CHECKING:
    from metalworks.contract import ResearchBrief
    from metalworks.llm.protocol import (
        GroundedChatModel,
        GroundedResult,
        GroundingChunk,
        GroundingSupport,
    )
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.discovery import DiscoveryFinding
    from metalworks.search import SearchResult

# Confidence thresholds: count of distinct supporting sources for a finding.
_CONF_MEDIUM_MIN = 2
_CONF_HIGH_MIN = 3

# Generous max_tokens — reasoning models burn hidden thinking tokens before
# emitting visible text; too small a cap yields empty responses.
_MAX_TOKENS = 4096
_TEMPERATURE = 0.3

_SYSTEM_PROMPT = (
    "You are a web researcher contributing to a structured market-research "
    "report. Your output is parsed by a downstream service that pairs each of "
    "your findings with citation metadata from the search tool. Findings "
    "without grounding are discarded.\n\n"
    "OUTPUT FORMAT (strict): a numbered list. One finding per number. Each "
    "finding is exactly two lines:\n"
    "  N. CLAIM: <one-line factual claim>\n"
    "     SPECIFICS: <the anchoring number, date, name, or short quote>\n\n"
    "Hard rules:\n"
    "(1) CLAIM is one factual sentence. No hedging, no preamble.\n"
    "(2) SPECIFICS contains the concrete anchor: a number, percentage, date, "
    "study name, brand name, or short verbatim quote.\n"
    "(3) Findings must be NEW information, not platitudes. Prefer the last 24 "
    "months unless the question is explicitly historical.\n"
    "(4) Do NOT emit URLs, source titles, or citation markers in your text. "
    "The system attaches sources from the tool.\n"
    "(5) Do NOT emit a confidence field. The service assigns confidence.\n"
    "(6) No preamble, no closing remarks, no markdown headers.\n"
    "(7) No em-dashes. Use commas or periods."
)


# ── Numbered-list parsing (pure, ported) ───────────────────────────────────

# Match "1.", "2)", "1:" etc. starting a line.
_NUMBERED_RE = re.compile(r"^\s*(\d+)\s*[.\):\-]\s*", re.MULTILINE)


@dataclass(frozen=True)
class _ParsedFinding:
    claim: str
    specifics: str
    char_start: int
    char_end: int


def parse_numbered_findings(text: str) -> list[_ParsedFinding]:
    """Parse the LLM's numbered list into findings with char spans.

    char_start/char_end are char offsets into `text` — the same space the
    adapter reports support spans in (it converts provider byte offsets to
    char offsets), so overlap bucketing is correct for non-ASCII output.
    """
    if not text:
        return []
    matches = list(_NUMBERED_RE.finditer(text))
    if not matches:
        return []
    out: list[_ParsedFinding] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        claim, specifics = split_claim_specifics(text[m.end() : end].strip())
        if not claim:
            continue
        out.append(_ParsedFinding(claim=claim, specifics=specifics, char_start=start, char_end=end))
    return out


def split_claim_specifics(block: str) -> tuple[str, str]:
    """Pull CLAIM / SPECIFICS from a finding block; tolerant of formats."""
    if not block:
        return "", ""
    claim = ""
    specifics = ""
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    for ln in lines:
        m_c = re.match(r"^\*?\*?CLAIM\*?\*?\s*[:\-]\s*(.+)$", ln, re.IGNORECASE)
        m_s = re.match(r"^\*?\*?SPECIFICS?\*?\*?\s*[:\-]\s*(.+)$", ln, re.IGNORECASE)
        if m_c and not claim:
            claim = m_c.group(1).strip()
        elif m_s and not specifics:
            specifics = m_s.group(1).strip()
    if not claim and lines:
        claim = lines[0]
        if len(lines) > 1:
            specifics = " ".join(lines[1:])
    return claim.strip(" *_`"), specifics.strip(" *_`")


def _build_user_prompt(
    deps_brief_question: str, directions: list[str], excluded: list[str], max_findings: int
) -> str:
    directions_block = "\n".join(f"- {d}" for d in directions) if directions else "(none specified)"
    excluded_block = "\n".join(f"- {e}" for e in excluded) if excluded else "(none)"
    return (
        f"PRIMARY QUESTION: {deps_brief_question}\n\n"
        f"ADDITIONAL ANGLES TO COVER:\n{directions_block}\n\n"
        f"EXCLUDED SOURCES (do not cite these domains or URLs):\n{excluded_block}\n\n"
        f"Produce up to {max_findings} findings. Cover the primary question "
        "first, then pursue each additional angle. Every finding must be "
        "grounded in a source. Format exactly as specified in the system prompt."
    )


# ── Excluded-source filtering (pure, ported) ───────────────────────────────


def _domain_of(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    try:
        host = urlparse(s).netloc
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _is_excluded(uri: str, excluded: list[str]) -> bool:
    if not uri or not excluded:
        return False
    target = _domain_of(uri)
    if not target:
        return False
    for raw in excluded:
        ex = _domain_of(raw) or raw.strip().lower()
        if not ex:
            continue
        if target == ex or target.endswith("." + ex):
            return True
        if "/" in raw and raw.strip().lower() in uri.lower():
            return True
    return False


def _confidence_for(n_sources: int) -> SignalStrength:
    if n_sources >= _CONF_HIGH_MIN:
        return SignalStrength.HIGH
    if n_sources >= _CONF_MEDIUM_MIN:
        return SignalStrength.MEDIUM
    return SignalStrength.LOW


def _parse_published(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = raw.strip().rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


# ── Internal grounded path ─────────────────────────────────────────────────


def _chunks_for_finding(
    start: int, end: int, supports: tuple[GroundingSupport, ...], n_chunks: int
) -> list[int]:
    """Chunk indices whose support spans overlap this finding's char span.

    De-duplicated, order-preserving. Both the finding span and the support
    spans are char offsets into the same response text.
    """
    out: list[int] = []
    seen: set[int] = set()
    for sup in supports:
        if sup.end_char < start or sup.start_char >= end:
            continue
        for idx in sup.chunk_indices:
            if 0 <= idx < n_chunks and idx not in seen:
                seen.add(idx)
                out.append(idx)
    return out


def _findings_from_grounded(
    result: GroundedResult, *, excluded: list[str], max_findings: int
) -> list[WebFinding]:
    text = result.text.strip()
    if not text or not result.chunks:
        return []
    parsed = parse_numbered_findings(text)
    if not parsed:
        return []

    findings: list[WebFinding] = []
    finding_idx = 0
    for p in parsed[:max_findings]:
        chunk_idxs = _chunks_for_finding(
            p.char_start, p.char_end, result.supports, len(result.chunks)
        )
        usable: list[GroundingChunk] = []
        for ci in chunk_idxs:
            ch = result.chunks[ci]
            if not ch.uri or _is_excluded(ch.uri, excluded):
                continue
            usable.append(ch)
        if not usable:
            continue
        primary = usable[0]
        finding_idx += 1
        findings.append(
            WebFinding(
                finding_index=finding_idx,
                claim=p.claim,
                specifics=p.specifics,
                source_url=primary.uri,
                source_title=primary.title or primary.uri,
                published_at=_parse_published(primary.published_at),
                confidence=_confidence_for(len(usable)),
            )
        )
    return findings


# ── External search path ───────────────────────────────────────────────────


class _ExternalFinding(BaseModel):
    claim: str = Field(description="One-line factual claim.")
    specifics: str = Field(description="The anchoring number, date, name, or quote.")
    source_indices: list[int] = Field(
        description="1-based indices into the numbered SOURCES list that support this claim."
    )


class _ExternalFindings(BaseModel):
    findings: list[_ExternalFinding] = Field(default_factory=list[_ExternalFinding])


def _external_search(
    deps: ResearchDeps,
    *,
    brief_question: str,
    directions: list[str],
    excluded: list[str],
    max_findings: int,
) -> list[WebFinding]:
    if deps.search is None:
        return []
    queries = [brief_question, *directions][: max(1, max_findings)]
    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    for q in queries:
        try:
            hits = deps.search.search(query=q, max_results=5)
        except Exception:
            continue
        for hit in hits:
            if hit.url and hit.url not in seen_urls and not _is_excluded(hit.url, excluded):
                seen_urls.add(hit.url)
                results.append(hit)
    if not results:
        return []

    numbered = "\n".join(
        f"{i + 1}. {r.title}\n   {r.url}\n   {r.snippet[:300]}" for i, r in enumerate(results)
    )
    user = (
        f"PRIMARY QUESTION: {brief_question}\n\n"
        f"ADDITIONAL ANGLES:\n" + ("\n".join(f"- {d}" for d in directions) or "(none)") + "\n\n"
        f"SOURCES (cite these by number):\n{numbered}\n\n"
        f"Produce up to {max_findings} findings, each citing the source index/indices "
        "that support it. Use ONLY the sources above."
    )
    try:
        out = deps.chat.complete_structured(
            system=_SYSTEM_PROMPT,
            user=user,
            output_model=_ExternalFindings,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
        )
    except Exception:
        return []

    findings: list[WebFinding] = []
    finding_idx = 0
    for f in out.findings[:max_findings]:
        valid = [i for i in f.source_indices if 1 <= i <= len(results)]
        if not valid:
            continue
        primary = results[valid[0] - 1]
        finding_idx += 1
        findings.append(
            WebFinding(
                finding_index=finding_idx,
                claim=f.claim,
                specifics=f.specifics,
                source_url=primary.url,
                source_title=primary.title or primary.url,
                published_at=_parse_published(primary.published_at),
                confidence=_confidence_for(len(valid)),
            )
        )
    return findings


# ── Discovery ladder (the capability-ladder gate) ──────────────────────────
#
# A discovery tier ABOVE single-shot search. The rule (verified by spy tests):
#
#   1. an AGENTIC DiscoveryProvider is configured → DELEGATE to its iterate-and-
#      dig loop; metalworks' homegrown loop does NOT run.
#   2. else a SearchProvider exists → run HomegrownDiscovery (our own loop over
#      single-shot search).
#   3. else → today's single-pass _external_search, BYTE-IDENTICAL (the pinned
#      fallback when neither a discovery provider nor a search provider exists).
#
# All three rungs map findings onto the SAME corpus spine (verbatim quote +
# source_url), so cite-or-die is preserved no matter which rung runs.


def _findings_from_discovery(
    discovery_findings: list[DiscoveryFinding], *, excluded: list[str], max_findings: int
) -> list[WebFinding]:
    """Map cite-or-die :class:`DiscoveryFinding`s onto :class:`WebFinding`s.

    The finding's *verbatim* ``quote`` becomes ``specifics`` (the anchoring
    quote) and its ``title`` the ``claim`` — never a synthesized summary, and
    ``source_url`` / ``source_title`` come from the finding metadata, not from
    LLM text. Excluded domains are dropped. Confidence is LOW: a single
    discovery hit is one source (the deterministic verdict re-scores downstream).
    """
    findings: list[WebFinding] = []
    finding_idx = 0
    for f in discovery_findings:
        url = (f.source_url or "").strip()
        quote = (f.quote or "").strip()
        if not url or not quote or _is_excluded(url, excluded):
            continue
        finding_idx += 1
        findings.append(
            WebFinding(
                finding_index=finding_idx,
                claim=(f.title or url).strip(),
                specifics=quote,  # verbatim quote, never a summary (cite-or-die)
                source_url=url,
                source_title=(f.title or url).strip(),
                published_at=None,
                confidence=_confidence_for(1),
            )
        )
        if finding_idx >= max_findings:
            break
    return findings


def _discover(
    deps: ResearchDeps,
    *,
    brief_question: str,
    directions: list[str],
    excluded: list[str],
    max_findings: int,
) -> list[WebFinding]:
    """The capability-ladder gate. See the module-level note above.

    Rung 1 (agentic provider): delegate to ``deps.discovery.discover`` — the
    homegrown loop is NOT constructed. Rung 2 (search only): run
    ``HomegrownDiscovery``. Rung 3 (neither): fall through to ``_external_search``
    unchanged — this is the byte-identical legacy path, pinned by tests.
    """
    from metalworks.research.discovery import DiscoveryBudget, HomegrownDiscovery

    budget = DiscoveryBudget(max_findings=max(1, max_findings))

    # Rung 1 — an AGENTIC provider configured wins: delegate, loop stays OFF.
    if deps.discovery is not None and deps.discovery.agentic:
        try:
            found = deps.discovery.discover(
                question=brief_question, directions=directions, budget=budget
            )
        except Exception:
            return []
        return _findings_from_discovery(found, excluded=excluded, max_findings=max_findings)

    # Rung 2 — a SearchProvider exists AND the homegrown loop is opted in
    # (``[sources].discover = true``): run our own iterate-and-dig loop. The opt-in
    # gate (mirrors the #123 selector) keeps the more-expensive, LLM-driven loop from
    # silently replacing single-pass for existing search users — default stays rung 3.
    from metalworks import config

    if deps.search is not None and config.discovery_loop_enabled():
        loop = HomegrownDiscovery(search=deps.search, chat=deps.chat)
        try:
            found = loop.discover(question=brief_question, directions=directions, budget=budget)
        except Exception:
            return []
        return _findings_from_discovery(found, excluded=excluded, max_findings=max_findings)

    # Rung 3 — agentic off and (loop off OR not opted in): today's single-pass path,
    # byte-identical. This is the DEFAULT for a configured single-shot SearchProvider.
    return _external_search(
        deps,
        brief_question=brief_question,
        directions=directions,
        excluded=excluded,
        max_findings=max_findings,
    )


# ── Public entry ───────────────────────────────────────────────────────────


def web_research(
    deps: ResearchDeps, *, brief: ResearchBrief, max_findings: int = 10
) -> list[WebFinding]:
    """Run the web stream. Best-effort: returns [] on any failure or when no
    grounding/search path is available (the pipeline degrades gracefully)."""
    if max_findings <= 0:
        return []
    directions = list(brief.web_research_directions or [])
    excluded = list(brief.excluded_sources or [])

    if deps.chat.capabilities.native_grounding:
        user = _build_user_prompt(brief.question, directions, excluded, max_findings)
        # Capability gate guarantees this model satisfies GroundedChatModel.
        grounded = cast("GroundedChatModel", deps.chat)
        try:
            result = grounded.complete_grounded(
                system=_SYSTEM_PROMPT, user=user, max_tokens=_MAX_TOKENS, temperature=_TEMPERATURE
            )
        except GroundingUnavailable:
            return _discover(
                deps,
                brief_question=brief.question,
                directions=directions,
                excluded=excluded,
                max_findings=max_findings,
            )
        except Exception:
            return []
        return _findings_from_grounded(result, excluded=excluded, max_findings=max_findings)

    return _discover(
        deps,
        brief_question=brief.question,
        directions=directions,
        excluded=excluded,
        max_findings=max_findings,
    )


__all__ = ["web_research"]
