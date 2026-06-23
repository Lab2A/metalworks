"""D6 — GEO / LLM-citability: participation targets, citability probes, answer briefs.

The GEO ("get cited by AI") stream of the Distribution pillar. GEO is a
compounding *stream*, not a separate pillar — Reddit is the #1 AI-cited domain
and the majority of AI citations are Q&A threads, so the fastest path to being
the cited answer is to participate in the threads the audience is already asking
in and to publish answer-first content for the questions they ask. This module
turns a finished :class:`~metalworks.contract.research.DemandReport` into three
grounded outputs:

- :func:`participation_targets` — DETERMINISTIC. The real threads/communities to
  engage, pulled from the report's verified permalinks + the cluster claims that
  say what that audience is asking. Never an invented thread.
- :func:`citability_probes` — DETERMINISTIC. The real conversational queries to
  test whether you're cited, derived from the cluster claims (the questions the
  audience actually asks), not templated keyword fluff.
- :func:`answer_briefs` — the LLM writes answer-first prose, but the answer is a
  factual claim, so cite-or-die is CORRECT here: each answer carries
  ``evidence_refs`` that resolve against ``report.evidence`` and ``stat_anchors``
  with the cluster's real counts. An answer whose evidence doesn't resolve is
  DROPPED (no-cite-no-claim).

DRAFTING ONLY — this names where to show up and what to say; it never posts.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import (
    AnswerBrief,
    CitabilityProbe,
    DemandReport,
    EvidenceRef,
    GeoPlan,
    ParticipationTarget,
)

if TYPE_CHECKING:
    from metalworks.contract import InsightCluster
    from metalworks.research.deps import ResearchDeps


# A subreddit reference inside a permalink or an "r/Name" label (mirrors channels.py).
_SUBREDDIT_RE = re.compile(r"\br/([A-Za-z0-9][A-Za-z0-9_]{1,50})\b")


# How many participation targets / probes / briefs to emit at most — keep the
# output a sharp shortlist, not an exhaustive dump.
_MAX_TARGETS = 8
_MAX_PROBES = 8
_MAX_BRIEFS = 6


# ── participation targets (deterministic) ────────────────────────────────────


def participation_targets(report: DemandReport) -> list[ParticipationTarget]:
    """The real threads/communities to engage — DETERMINISTIC from the report.

    Every target's ``permalink`` is a verbatim ``source_url`` from a verified
    quote and its ``community`` is a real subreddit the audience named; ``why``
    paraphrases the cluster claim that quote backs (what the audience is asking
    there). Never invents a thread — if a quote carries no resolvable permalink,
    it is skipped. Deduped by permalink, ranked by the cluster's demand order.
    """
    targets: list[ParticipationTarget] = []
    seen: set[str] = set()
    for cluster in report.ranked_clusters:
        for q in cluster.quotes:
            permalink = q.source_url.strip()
            if not permalink or permalink in seen:
                continue
            community = _community_for_quote(q.source_name, permalink)
            if not community:
                continue
            seen.add(permalink)
            targets.append(
                ParticipationTarget(
                    community=community,
                    permalink=permalink,
                    why=f"This audience is asking about: {cluster.claim}",
                    suggested_angle=(
                        "Answer the question directly and helpfully first; disclose your "
                        "affiliation, never drop a bare link — earn the citation by being "
                        "the most useful reply in the thread."
                    ),
                )
            )
            if len(targets) >= _MAX_TARGETS:
                return targets
    return targets


def _community_for_quote(source_name: str, permalink: str) -> str:
    """Best real community label for a quote — its source_name, else from the permalink.

    Both sources are REAL report fields (a resolved 'r/Name' label and the verbatim
    permalink); the community is never invented. Returns '' when neither names a
    subreddit, and the caller skips that quote.
    """
    name = source_name.strip()
    if name.lower().startswith("r/"):
        return name
    m = _SUBREDDIT_RE.search(permalink)
    if m:
        return f"r/{m.group(1)}"
    return name  # may be '' — caller skips empties


# ── citability probes (deterministic) ────────────────────────────────────────


def citability_probes(report: DemandReport) -> list[CitabilityProbe]:
    """Conversational queries to test whether you're cited — from the cluster claims.

    Each probe's ``prompt`` is a real question phrased the way someone would ask an
    answer engine, derived from a cluster claim (the demand the audience actually
    expressed); ``target_phrase`` is that claim, so a probe always traces back to
    real demand. Deterministic — no LLM, no templated keyword fluff.
    """
    probes: list[CitabilityProbe] = []
    for cluster in report.ranked_clusters[:_MAX_PROBES]:
        claim = cluster.claim.strip()
        if not claim:
            continue
        probes.append(CitabilityProbe(prompt=_claim_to_query(claim), target_phrase=claim))
    return probes


def _claim_to_query(claim: str) -> str:
    """Phrase a cluster claim as a question someone would ask an answer engine."""
    text = claim.rstrip(".!?").strip()
    lowered = text.lower()
    if lowered.startswith(("how ", "what ", "why ", "when ", "where ", "which ", "who ", "is ")):
        return text + "?"
    return f"What do people recommend when {text[0].lower() + text[1:]}?"


# ── answer briefs (LLM, grounded — cite-or-die) ──────────────────────────────


class _AnswerDraft(BaseModel):
    """The LLM's answer-first prose for one cluster question (the only authoring)."""

    answer: str = Field(
        description="Answer-first, factual prose answering the question, grounded ONLY in the "
        "supplied quotes. Lead with the answer. Do not invent facts the quotes don't support."
    )


def answer_briefs(deps: ResearchDeps, report: DemandReport) -> list[AnswerBrief]:
    """Answer-first briefs — the LLM writes grounded prose, evidence MUST resolve.

    For each top cluster, the LLM writes an answer-first paragraph grounded in that
    cluster's verified quotes. The brief carries ``evidence_refs`` (the quote ids)
    that resolve against ``report.evidence`` and ``stat_anchors`` with the
    cluster's REAL ``distinct_authors`` / ``mentions``. A brief whose evidence
    doesn't resolve against ``report.evidence`` is DROPPED (no-cite-no-claim) — the
    answer is a factual claim, so cite-or-die is correct.
    """
    resolvable: set[str] = {rec.id for rec in report.evidence}
    briefs: list[AnswerBrief] = []
    for cluster in report.ranked_clusters[:_MAX_BRIEFS]:
        brief = _brief_for_cluster(deps, cluster, resolvable)
        if brief is not None:
            briefs.append(brief)
    return briefs


def _brief_for_cluster(
    deps: ResearchDeps, cluster: InsightCluster, resolvable: set[str]
) -> AnswerBrief | None:
    """Draft one grounded brief; drop it if no evidence resolves."""
    refs = [
        EvidenceRef(evidence_id=q.id, kind="quote") for q in cluster.quotes if q.id in resolvable
    ]
    if not refs:
        return None  # no resolvable evidence → drop (no-cite-no-claim)

    quote_block = "\n".join(f'- "{q.text}"' for q in cluster.quotes if q.id in resolvable)
    question = cluster.claim.strip()
    system = (
        "You write ONE answer-first paragraph for an LLM-citability brief. Lead with the "
        "factual answer in the first sentence, then support it. Ground EVERY statement in the "
        "supplied verbatim consumer quotes — do not invent facts, statistics, or product names "
        "the quotes do not support. Plain, factual, no marketing fluff."
    )
    user = (
        f"Question the audience is asking: {question}\n\n"
        f"Verbatim consumer quotes (your only evidence):\n{quote_block}\n\n"
        "Write the answer-first paragraph."
    )
    try:
        draft = deps.chat.complete_structured(
            system=system,
            user=user,
            output_model=_AnswerDraft,
            max_tokens=512,
            temperature=0.2,
        )
        answer = draft.answer.strip()
    except Exception:
        answer = ""
    if not answer:
        # The LLM gave us nothing usable — fall back to the grounded claim itself
        # rather than dropping a real, evidenced question.
        answer = cluster.claim.strip()

    return AnswerBrief(
        question=question,
        answer=answer,
        evidence_refs=refs,
        stat_anchors={
            "distinct_authors": cluster.distinct_author_count,
            "mentions": cluster.mention_count,
        },
    )


# ── orchestrator (the GeoPlan the four surfaces emit) ────────────────────────


def build_geo_plan(deps: ResearchDeps, report: DemandReport) -> GeoPlan:
    """Assemble the three GEO streams into a :class:`GeoPlan` — the D6 face.

    The reusable core the four surfaces call: deterministic participation targets
    + citability probes, and the LLM-authored-but-grounded answer briefs.
    """
    return GeoPlan(
        report_id=report.report_id,
        participation_targets=participation_targets(report),
        citability_probes=citability_probes(report),
        answer_briefs=answer_briefs(deps, report),
    )
