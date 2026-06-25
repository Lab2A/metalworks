"""LLM cluster synthesis + deterministic InsightCluster assembly.

The LLM sees one representative per near-duplicate group, returns candidate
clusters as INDICES (structural-provenance: never quote text). This module:

  1. asks the LLM to label/merge the deduped representatives into themes (with
     3x retry — fails LOUD on validation failure, never empty-success),
  2. expands each candidate's member indices back to ALL original comments in
     those groups,
  3. builds a verified InsightCluster (deterministic counts + signal +
     demand_score) and runs the exact-match quote gate as defense-in-depth.

Demographic-match weighting is dropped — synthesis takes no `target_demographic`
string; ranking is straight demand_score.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from metalworks.contract import InsightCluster, ResolvedCitation, SignalStrength
from metalworks.research.synthesis.demand import relative_band
from metalworks.research.synthesis.signals import aggregate_signals, score_signals
from metalworks.research.types import LoadedComment

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps

# ── tuning knobs (module-level so an eval can sweep) ─────────────────────────
AUTHOR_WEIGHT = 10.0
MAX_QUOTES_PER_CLUSTER = 3

# Synthesis budget. The LLM output is a list whose size scales with how many
# deduped representatives we pass in. Keep this high — a long
# member_comment_indices list plus hidden "thinking" tokens will silently
# truncate (finish_reason=length, empty content) at lower ceilings.
SYNTHESIS_MAX_TOKENS = 65536
SYNTHESIS_TEMPERATURE = 0.4

LLM_RETRIES = 3  # fail loud after 3 retries, never empty-success.


# ── LLM I/O (the model sees numbered comments, returns indices) ──────────────
class _CandidateCluster(BaseModel):
    claim: str = Field(
        description="One-line insight: what these consumers want/feel/struggle with."
    )
    member_comment_indices: list[int] = Field(
        description="Indices (from the numbered list) of ALL comments expressing this theme."
    )
    quote_comment_indices: list[int] = Field(
        description="2-3 of the members whose verbatim text best illustrates the claim."
    )


class _SynthesisOutput(BaseModel):
    clusters: list[_CandidateCluster] = Field(
        description="Distinct consumer-insight themes. Merge near-identical themes; "
        "omit one-off noise."
    )


# ── pure helpers ─────────────────────────────────────────────────────────────
def signal_from_breadth(breadth: int, population: list[int]) -> SignalStrength:
    """Confidence chip for a cluster — its breadth banded RELATIVE to this report's
    clusters (``population`` = the breadth counts of every cluster in the report),
    via the shared :func:`~metalworks.research.synthesis.demand.relative_band`.

    HIGH means top-third *of this report*, not an absolute author cutoff — so the
    badge tracks the same "demand is relative" thesis the demand verdict uses, and
    a 12-author cluster can be HIGH in a thin report yet LOW in a broad one.
    ``population`` must include ``breadth``. For an all-authored cluster breadth ==
    distinct authors, so the Reddit chip stays a distinct-author band.
    """
    return relative_band(breadth, population)


# Back-compat alias — breadth == author count for all-authored clusters.
signal_from_author_count = signal_from_breadth


def compute_demand_score(breadth: int, signals: Mapping[str, float] | float) -> float:
    """Rank by breadth of voices, not virality (50x2 outranks 1x200).

    ``breadth`` is the source-neutral count of distinct independent voices —
    distinct authors for authored sources, distinct domains for authorless web,
    summed for mixed clusters — so every source ranks on the same axis.

    ``signals`` is the cluster's aggregated source-declared signal vector (e.g.
    ``{"upvotes": 312}``); each known kind contributes via its registered
    ``SignalSpec`` (unknown kinds are context-only). As of 0.2a that includes the
    ``is_magnitude`` kinds (``search_volume``/``installs``/…), so a theme carrying
    high volume sorts above an equal-breadth theme without it — but ONLY here, in
    the sort key. The verdict band (``demand.strength``) never receives this vector.

    A bare number is accepted as the legacy ``{"upvotes": n}`` engagement total —
    so the back-compat invariant holds: a Reddit-only cluster's ``{"upvotes": sum}``
    yields ``log1p(sum)``, exactly the pre-signals ``log1p(total_engagement)``, and
    a Reddit-only run (no magnitude kinds present) orders byte-identically.
    """
    vec: Mapping[str, float] = (
        {"upvotes": float(signals)} if isinstance(signals, int | float) else signals
    )
    return breadth * AUTHOR_WEIGHT + score_signals(vec)


def _domain(url: str) -> str:
    """Registrable-ish domain of a URL for breadth counting (netloc, no www.)."""
    netloc = urlsplit(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def cluster_breadth(members: list[LoadedComment]) -> tuple[int, int, str]:
    """Distinct independent voices behind a cluster, source-aware.

    A "voice" is an author when the record has one (Reddit/HN/reviews) or a
    distinct domain when it doesn't (authorless web). Returns
    ``(breadth, distinct_authors, unit)`` where ``breadth`` = distinct authors +
    distinct domains and ``unit`` is ``"authors"`` (all authored), ``"domains"``
    (all authorless web), or ``"voices"`` (mixed). Authored-only clusters get
    ``breadth == distinct_authors`` and ``unit == "authors"`` — the Reddit path
    is unchanged.
    """
    authors = {m.author_hash for m in members if m.author_hash}
    domains = {_domain(m.source_url) for m in members if not m.author_hash}
    domains.discard("")
    breadth = len(authors) + len(domains)
    if authors and domains:
        unit = "voices"
    elif domains:
        unit = "domains"
    else:
        unit = "authors"
    return breadth, len(authors), unit


def source_mix(members: list[LoadedComment]) -> dict[str, int]:
    """Source composition of a cluster: source_id → count of members from it.

    Computed over ALL members (not the 2-3 surfaced quotes) so it reflects the
    cluster's true composition. Keys are sorted for a deterministic, stable
    payload. A Reddit-only cluster yields ``{"reddit": N}``. Pure disclosure —
    this never feeds ``demand_score`` or the verdict band (see #164 step 1).
    """
    mix: dict[str, int] = {}
    for m in members:
        mix[m.source] = mix.get(m.source, 0) + 1
    return {k: mix[k] for k in sorted(mix)}


def _format_numbered_comment(i: int, c: LoadedComment) -> str:
    """Render one numbered comment for the synthesis prompt, source-neutrally.

    Reads the generic display fields (`source_label`, `engagement`,
    `engagement_unit`, `text`) so nothing Reddit-specific (`r/...`, `upvotes`)
    leaks when the source isn't Reddit. For the Reddit path these are populated
    by the loader to `r/<sub>` / score / "upvotes", so the rendered line is
    unchanged.
    """
    label = c.source_label or (f"r/{c.subreddit}" if c.subreddit else "")
    return f"[{i}] ({label}, {c.engagement} {c.engagement_unit}) {c.text or c.body}"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _verify_quote(candidate: str, sources: list[str]) -> bool:
    nc = _normalize(candidate)
    if not nc:
        return False
    return any(nc in _normalize(b) for b in sources)


# ── synthesis (the LLM call) ─────────────────────────────────────────────────
def _default_synthesize(
    deps: ResearchDeps,
    axis_context: str,
    representatives: list[LoadedComment],
) -> _SynthesisOutput:
    """Real LLM call. Numbered comments in, indices+claims out.

    Wrapped in LLM_RETRIES retries — a model can return finish_reason=length
    with empty content if its thinking budget eats the response window. After
    the retries we RAISE — synthesis never silently returns empty
    ranked_clusters and pretends that's success.
    """
    numbered = "\n".join(_format_numbered_comment(i, c) for i, c in enumerate(representatives))
    system = (
        "You are a consumer-research analyst. Given real user conversations, group them into "
        "distinct consumer-insight themes. For each theme: a one-line claim, the indices of ALL "
        "comments expressing it (member_comment_indices), and 2-3 of those indices whose verbatim "
        "text best illustrates it (quote_comment_indices). Merge near-identical themes. Omit "
        "one-off noise. NEVER invent a comment index that isn't in the list. Reference comments "
        "only by their [index]."
    )
    user = f"Research goal: {axis_context}\n\nComments:\n{numbered}"

    last_err: Exception | None = None
    for attempt in range(LLM_RETRIES):
        try:
            return deps.chat.complete_structured(
                system=system,
                user=user,
                output_model=_SynthesisOutput,
                max_tokens=SYNTHESIS_MAX_TOKENS,
                temperature=SYNTHESIS_TEMPERATURE,
            )
        except Exception as e:  # surfaced after retries; backoff then re-raise
            last_err = e
            # Exponential-ish backoff so a transient throttle gets a chance.
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"Synthesis LLM failed after {LLM_RETRIES} attempts: {last_err}")


# ── cluster build ────────────────────────────────────────────────────────────
def _build_cluster(
    rank: int,
    candidate: _CandidateCluster,
    groups: list[list[int]],
    comments: list[LoadedComment],
) -> tuple[InsightCluster, set[str], list[str], list[int]] | None:
    """Turn one LLM candidate into a verified InsightCluster.

    Returns (cluster, author_hash_set, subreddits, member_comment_indices) on
    success — the trailing tuple feeds segmentation (per-cluster authors +
    subreddits) and the source_map (member indices into `comments`).

    Returns None when no quote survives the exact-match gate (no-quote-no-theme).
    """
    member_groups = [g for g in candidate.member_comment_indices if 0 <= g < len(groups)]
    if not member_groups:
        return None
    # Expand each cited GROUP back to all its original comments — otherwise dedup
    # would silently undercount distinct authors (the base-rate honesty the
    # contract depends on).
    member_comment_indices = sorted({j for g in member_groups for j in groups[g]})
    members = [comments[j] for j in member_comment_indices]

    quote_groups = [g for g in candidate.quote_comment_indices if 0 <= g < len(groups)]
    quote_groups = (quote_groups or member_groups)[:MAX_QUOTES_PER_CLUSTER]
    quote_members = [comments[groups[g][0]] for g in quote_groups]

    member_bodies = [m.body for m in members]
    quotes: list[ResolvedCitation] = []
    for m in quote_members:
        if not _verify_quote(m.body, member_bodies):
            continue
        # Materialize the source-neutral, portable ResolvedCitation directly
        # from the LoadedComment we already hold (no corpus round-trip — the
        # comment is loaded during synthesis). For the Reddit path source_label
        # is "r/<sub>" and source_url is the permalink, so the serialized
        # citation carries the same text + url as before under generic names.
        label = m.source_label or (
            m.subreddit if m.subreddit.startswith("r/") else f"r/{m.subreddit}"
        )
        link = m.source_url or m.permalink or m.post_url
        quotes.append(
            ResolvedCitation(
                record_id=m.comment_id,
                source=m.source,
                source_name=label,
                source_url=link,
                text=m.body,
                author_hash=m.author_hash,
                engagement=m.engagement or m.upvotes,
                signals=dict(m.signals),
            )
        )
        if len(quotes) >= MAX_QUOTES_PER_CLUSTER:
            break
    if not quotes:  # no-quote-no-theme
        return None

    distinct_authors = {m.author_hash for m in members if m.author_hash}
    breadth, distinct_count, breadth_unit = cluster_breadth(members)
    # Aggregate the source-declared signal vector across members, then score it
    # spec-weighted. For a Reddit-only cluster this is {"upvotes": sum} →
    # log1p(sum), identical to the old sum(m.upvotes) path (the back-compat
    # invariant); a review/search cluster carries its own kinds.
    demand_signals = aggregate_signals(members)
    cluster = InsightCluster(
        rank=rank,
        claim=candidate.claim,
        demand_score=compute_demand_score(breadth, demand_signals),
        distinct_author_count=distinct_count,
        breadth_count=breadth,
        breadth_unit=breadth_unit,
        mention_count=len(members),
        demand_signals=demand_signals,
        # Provisional — re-banded relative to ALL clusters' breadths in build_clusters
        # once the full report population is known (the badge is relative, not absolute).
        signal=SignalStrength.LOW,
        quotes=quotes,
        # Source composition over ALL members (disclosure only; never scored).
        source_mix=source_mix(members),
    )
    return cluster, distinct_authors, [m.subreddit for m in members], member_comment_indices


def build_clusters(
    deps: ResearchDeps,
    *,
    axis_context: str,
    representatives: list[LoadedComment],
    groups: list[list[int]],
    comments: list[LoadedComment],
) -> tuple[list[InsightCluster], list[set[str]], list[list[str]], list[list[int]]]:
    """Run synthesis + build verified InsightClusters.

    Returns (clusters, per_cluster_authors, per_cluster_subreddits,
    per_cluster_member_indices), aligned by index. Clusters are 1-ranked by
    demand_score (desc) and renumbered.
    """
    if not representatives:
        return [], [], [], []
    synthesis = _default_synthesize(deps, axis_context, representatives)

    built: list[tuple[InsightCluster, set[str], list[str], list[int]]] = []
    for candidate in synthesis.clusters:
        result = _build_cluster(rank=0, candidate=candidate, groups=groups, comments=comments)
        if result is not None:
            built.append(result)

    built.sort(key=lambda it: it[0].demand_score, reverse=True)
    # Badge is RELATIVE: band each cluster's breadth against the distribution of ALL
    # clusters in THIS report (top third → HIGH), not a fixed absolute cutoff.
    population = [c.breadth_count for (c, *_rest) in built]
    clusters: list[InsightCluster] = []
    authors: list[set[str]] = []
    subs: list[list[str]] = []
    member_indices: list[list[int]] = []
    for i, (c, a, s, mi) in enumerate(built, start=1):
        c.rank = i
        c.signal = signal_from_breadth(c.breadth_count, population)
        clusters.append(c)
        authors.append(a)
        subs.append(s)
        member_indices.append(mi)
    return clusters, authors, subs, member_indices
