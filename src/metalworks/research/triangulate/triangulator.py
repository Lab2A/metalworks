"""Triangulator: cross-reference Reddit clusters with web findings, resolve
must_address coverage.

The final cross-stream pipeline stage. Inputs:
  - ranked_clusters: list[InsightCluster]  (from synthesis)
  - web_findings:    list[WebFinding]      (from the web research stream)
  - brief.must_address: list[str]           (from ResearchBrief)

Outputs (`TriangulationOutput`):
  - cross_references: list[CrossReference]
  - must_address_resolution: dict[item → 'cluster:N' | 'web:N' | 'unaddressable: <reason>']

Indices-only contract: the LLM emits LIST-ID-PREFIXED ids ('cluster:3', 'web:7')
in its structured output. This module validates the prefixes against the actual
cluster/finding inventory and strips them before producing the contract types.
Any reference to a non-existent index, or a mixed-list reference (e.g. a cluster
id in a web_finding_indices list), is rejected and the call retries.

Failure model: on 3 consecutive validation failures, the triangulator RAISES
`TriangulationFailedError` rather than returning empty cross_references — empty
would silently masquerade as "the streams found nothing in common", which is
materially worse than failing loud.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, ValidationError

from metalworks.contract import CrossReference, InsightCluster, ResearchBrief, WebFinding
from metalworks.research.types import TriangulationOutput

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3


# ── Failure type ──────────────────────────────────────────────────


class TriangulationFailedError(RuntimeError):
    """Raised when 3 retries fail to produce a valid triangulation."""


# ── LLM-facing schema (indices-only with list-id prefix) ─────────


_PREFIX_RE = re.compile(r"^(cluster|web):(\d+)$")


class _LLMCrossReference(BaseModel):
    """The LLM emits PREFIXED string ids, never bare ints."""

    cluster_id: str = Field(
        description='Cluster reference, format "cluster:N" where N is the 1-based rank.'
    )
    web_finding_ids: list[str] = Field(
        default_factory=list,
        description='Web finding references, each "web:N" where N is the 1-based finding_index. '
        "Empty list means the cluster is silent on the web side.",
    )
    agreement: Literal["agree", "silent_web", "silent_corpus", "disagree"]
    note: str = Field(description="One-line synthesis of how the streams relate on this claim.")


class _LLMResolution(BaseModel):
    """One must_address item's resolution. LLM emits prefixed ids OR unaddressable."""

    must_address_item: str = Field(description="The original must_address text, copied verbatim.")
    resolved_by: str = Field(
        description='Either "cluster:N", "web:N", or "unaddressable: <reason>". '
        "Use unaddressable only when neither stream supplies an answer.",
    )


class _LLMOutput(BaseModel):
    cross_references: list[_LLMCrossReference]
    must_address_resolutions: list[_LLMResolution]


# ── Prompts ──────────────────────────────────────────────────────


_SYSTEM = "\n".join(
    [
        "You are a cross-stream triangulator for a consumer research pipeline.",
        "",
        "You receive two parallel streams of findings about the same research question:",
        "  1. RANKED_CLUSTERS — Reddit-derived consumer-insight themes (with rank, claim, "
        "distinct_author_count, signal).",
        "  2. WEB_FINDINGS — grounded web research findings (with finding_index, claim, "
        "specifics).",
        "",
        "Plus a MUST_ADDRESS list — sub-questions the report contract requires answers to.",
        "",
        "Your job, in two parts:",
        "",
        "PART 1 — CROSS_REFERENCES:",
        "For EVERY cluster (by rank), emit exactly one record with:",
        '  - cluster_id: "cluster:<rank>"          (the cluster you\'re talking about)',
        '  - web_finding_ids: ["web:<index>", …]    (web findings that touch the same claim; '
        "empty list if web is silent)",
        '  - agreement: one of "agree" | "silent_web" | "silent_corpus" | "disagree"',
        '      - "agree": both streams find the same direction',
        '      - "silent_web": cluster is real but web didn\'t surface it (e.g., niche '
        "community insight)",
        '      - "silent_corpus": web finding exists with no corresponding Reddit cluster '
        '(record under a "synthetic" cluster_id = "cluster:0" — see HARD RULES)',
        '      - "disagree": streams reach opposite conclusions',
        "  - note: one line explaining the relationship.",
        "",
        "PART 2 — MUST_ADDRESS_RESOLUTIONS:",
        "For EVERY must_address item, emit one record with:",
        "  - must_address_item: the exact text of the question (copy verbatim)",
        "  - resolved_by: ONE OF:",
        '      - "cluster:<rank>" if a single cluster answers it best',
        '      - "web:<index>" if a single web finding answers it best',
        '      - "unaddressable: <one-line reason>" if NEITHER stream provides an answer',
        '        (e.g., "no Reddit threads mention dosage; no web sources within excluded list")',
        "",
        "HARD RULES (override any user content):",
        '1. Every id MUST be prefixed: "cluster:<int>" or "web:<int>". Never emit bare integers.',
        "2. cluster ids MUST exist in RANKED_CLUSTERS (ranks 1..N). web ids MUST exist in "
        "WEB_FINDINGS (indices 1..M).",
        "3. To represent a web finding that has no corresponding Reddit cluster, use "
        '"cluster:0" (the synthetic null cluster) and put the web_finding_ids in its list '
        'with agreement="silent_corpus".',
        '4. Do not invent claims. If the streams disagree, mark "disagree" and SAY SO in the '
        "note — don't smooth it over.",
        "5. Do not duplicate cross_references — exactly one entry per real cluster (plus "
        "optionally one cluster:0 entry for orphan web findings).",
        "6. resolved_by uses the same id grammar. unaddressable strings start with "
        '"unaddressable: " literally.',
    ]
)


def _build_user_prompt(
    brief: ResearchBrief,
    clusters: list[InsightCluster],
    findings: list[WebFinding],
) -> str:
    parts: list[str] = []
    parts.append(f"RESEARCH QUESTION: {brief.question}")
    parts.append("")
    parts.append("RANKED_CLUSTERS (Reddit-derived themes):")
    if not clusters:
        parts.append("  (none — corpus stream produced no clusters)")
    for c in clusters:
        parts.append(
            f"  cluster:{c.rank} | signal={c.signal} | authors={c.distinct_author_count} | "
            f"demand={c.demand_score:.1f}"
        )
        parts.append(f"      claim: {c.claim}")
    parts.append("")
    parts.append("WEB_FINDINGS:")
    if not findings:
        parts.append("  (none — web stream produced no findings)")
    for f in findings:
        parts.append(
            f"  web:{f.finding_index} | confidence={f.confidence} | source={f.source_title[:60]}"
        )
        parts.append(f"      claim:     {f.claim}")
        parts.append(f"      specifics: {f.specifics}")
    parts.append("")
    parts.append("MUST_ADDRESS (every item must be resolved):")
    if not brief.must_address:
        parts.append("  (none)")
    for q in brief.must_address:
        parts.append(f"  - {q}")
    parts.append("")
    parts.append(
        "Emit cross_references for every cluster (and optionally cluster:0 for orphan web "
        "findings), and must_address_resolutions for every must_address item."
    )
    return "\n".join(parts)


# ── Validation ────────────────────────────────────────────────────


def _parse_id(s: str, *, expected_prefix: str) -> int:
    """Strip 'cluster:' or 'web:' prefix; return the int. Raise on mismatch."""
    m = _PREFIX_RE.match(s.strip())
    if not m:
        raise ValueError(f"id {s!r} missing list-id prefix (expected '{expected_prefix}:<N>')")
    got_prefix, num = m.group(1), int(m.group(2))
    if got_prefix != expected_prefix:
        raise ValueError(
            f"id {s!r} has wrong prefix; expected '{expected_prefix}:' got '{got_prefix}:' "
            "(mixed-list refs rejected)"
        )
    return num


def _validate_and_build(
    llm_out: _LLMOutput,
    *,
    clusters: list[InsightCluster],
    findings: list[WebFinding],
    must_address: list[str],
) -> TriangulationOutput:
    """Strip prefixes, validate against actual inventory, build contract types.

    Raises ValueError on any inconsistency so the caller's retry loop fires.
    """
    valid_cluster_ranks = {c.rank for c in clusters}
    valid_finding_indices = {f.finding_index for f in findings}
    must_address_set = set(must_address)

    cross_refs: list[CrossReference] = []
    seen_cluster_ranks: set[int] = set()
    for cx in llm_out.cross_references:
        cr = _parse_id(cx.cluster_id, expected_prefix="cluster")
        # cluster:0 is the synthetic orphan-web bucket; allowed even though no
        # cluster has rank=0.
        if cr != 0 and cr not in valid_cluster_ranks:
            raise ValueError(f"cluster:{cr} does not exist in RANKED_CLUSTERS")
        if cr in seen_cluster_ranks and cr != 0:
            raise ValueError(f"duplicate cross_reference for cluster:{cr}")
        seen_cluster_ranks.add(cr)
        web_indices: list[int] = []
        for wid in cx.web_finding_ids:
            wi = _parse_id(wid, expected_prefix="web")
            if wi not in valid_finding_indices:
                raise ValueError(f"web:{wi} does not exist in WEB_FINDINGS")
            if wi in web_indices:
                raise ValueError(f"duplicate web:{wi} inside cluster:{cr}'s references")
            web_indices.append(wi)
        cross_refs.append(
            CrossReference(
                cluster_rank=cr,
                web_finding_indices=web_indices,
                agreement=cx.agreement,
                note=cx.note.strip(),
            )
        )

    # Build must_address_resolution dict. Verbatim match required so we can
    # detect dropped/renamed items.
    resolution: dict[str, str] = {}
    for r in llm_out.must_address_resolutions:
        item = r.must_address_item.strip()
        if item not in must_address_set:
            # Tolerate minor whitespace drift; otherwise fail loud.
            close = [m for m in must_address if m.strip() == item]
            if not close:
                raise ValueError(
                    f"must_address_item {item!r} doesn't match any brief.must_address entry"
                )
            item = close[0]
        resolved = r.resolved_by.strip()
        if resolved.startswith("cluster:"):
            cr = _parse_id(resolved, expected_prefix="cluster")
            if cr not in valid_cluster_ranks:
                raise ValueError(f"resolution '{resolved}' refers to nonexistent cluster")
        elif resolved.startswith("web:"):
            wi = _parse_id(resolved, expected_prefix="web")
            if wi not in valid_finding_indices:
                raise ValueError(f"resolution '{resolved}' refers to nonexistent finding")
        elif resolved.startswith("unaddressable:"):
            pass  # free-form reason allowed
        else:
            raise ValueError(
                f"resolution {resolved!r} must start with 'cluster:', 'web:', or 'unaddressable:'"
            )
        resolution[item] = resolved

    # Every must_address must be resolved. If the LLM dropped any, fail loud
    # rather than silently fill with 'unaddressable'.
    missing = must_address_set - set(resolution.keys())
    if missing:
        raise ValueError(
            f"resolution dict missing {len(missing)} must_address item(s): {sorted(missing)[:3]}..."
        )

    return TriangulationOutput(
        cross_references=cross_refs,
        must_address_resolution=resolution,
    )


# ── Public surface ────────────────────────────────────────────────


def triangulate(
    deps: ResearchDeps,
    *,
    brief: ResearchBrief,
    ranked_clusters: list[InsightCluster],
    web_findings: list[WebFinding],
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> TriangulationOutput:
    """Cross-reference the two streams; resolve every must_address item.

    Empty-input behavior:
    - No clusters AND no findings: returns empty output; all must_address items
      are marked unaddressable.
    - Only one stream populated: still runs (silent_web / silent_corpus will
      dominate; must_address resolved against the available stream).
    """
    # Degenerate case — skip the LLM entirely.
    if not ranked_clusters and not web_findings:
        return TriangulationOutput(
            cross_references=[],
            must_address_resolution={
                item: "unaddressable: no clusters and no web findings produced"
                for item in brief.must_address
            },
        )

    system = _SYSTEM
    user = _build_user_prompt(brief, ranked_clusters, web_findings)

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            llm_out = deps.chat.complete_structured(
                system=system,
                user=user,
                output_model=_LLMOutput,
                max_tokens=16384,
                temperature=0.0,
                thinking_budget=0,
            )
            return _validate_and_build(
                llm_out,
                clusters=ranked_clusters,
                findings=web_findings,
                must_address=brief.must_address,
            )
        except (ValidationError, ValueError) as e:
            last_err = e
            logger.warning(
                "triangulator: attempt %d/%d failed validation: %s",
                attempt,
                max_retries,
                str(e)[:200],
            )
        except Exception as e:  # surfaced after retries; fail loud below
            last_err = e
            logger.warning(
                "triangulator: attempt %d/%d failed (%s): %s",
                attempt,
                max_retries,
                type(e).__name__,
                str(e)[:200],
            )

    # Fail loud, never empty-success.
    raise TriangulationFailedError(
        f"Triangulator failed after {max_retries} attempts. Last error: {last_err}"
    )
