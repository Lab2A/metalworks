"""Pillar E — Marketing Website.

Turn a finished :class:`~metalworks.contract.research.DemandReport` into a small,
grounded marketing site (a :class:`~metalworks.contract.site.MarketingSite`) plus
a single self-contained ``index.html`` rendering.

The defensible-by-construction move mirrors Pillar B: copy SELECTION is
constrained and then re-verified deterministically. The builder takes the top 3
clusters by ``demand_score`` and makes exactly ONE constrained
``deps.chat.complete_structured`` call that, per cluster, (a) assigns a
``SiteSection`` role and (b) picks a VERBATIM fragment to quote out of that
cluster's quotes. The builder then re-runs EXACT-MATCH grounding: the picked
fragment must be a substring of some real ``QuoteCitation.text`` in that cluster.
If it is, the section ships ``provenance="verbatim"`` with a single
``EvidenceRef`` to that quote; if not (or if no quote backs it), the section is
DROPPED — no-quote-no-section. The hero is built on the cluster with the highest
``distinct_author_count`` (the broadest base rate, not the loudest post).

The LLM may also add CONNECTIVE copy (transitions). Connective sections ship
``provenance="connective"`` with NO refs and are forced claim-free: any line
carrying a number or a superlative is dropped, because glue must not smuggle in
an unsourced claim.

Best-effort: any LLM failure returns a partial empty ``MarketingSite``
(``partial=True`` + caveat), never a raise.

``build_marketing_site(deps, report, positioning=None)`` is the reusable core
behind the ``metalworks site`` CLI and the ``site_render`` MCP tool;
``render_site_html(site)`` turns the result into one ``index.html`` string with
footnoted permalinks for every verbatim section.
"""

from __future__ import annotations

import html
import re
import warnings
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import (
    DemandReport,
    EvidenceRecord,
    EvidenceRef,
    InsightCluster,
    QuoteCitation,
)
from metalworks.contract.site import MarketingSite, SiteSection

if TYPE_CHECKING:
    from metalworks.contract.positioning import PositioningBrief
    from metalworks.research.deps import ResearchDeps

# `_SectionPhrasing` / `_ConnectivePhrasing` (defined below) carry a deliberate
# `copy` field (the wire-contract name), which shadows the deprecated
# BaseModel.copy attribute; suppress pydantic's shadow warning narrowly rather
# than renaming. Set before those classes are defined, after the imports.
warnings.filterwarnings("ignore", message=r'Field name "copy".*', category=UserWarning)

_TOP_N = 3
_SITE_ROLES = ("hero", "feature", "objection", "pricing", "social_proof", "cta")

# A "claim" in connective glue = any digit (a number) or a superlative word.
# Connective copy must be claim-free, so a line carrying either is dropped.
_DIGIT_RE = re.compile(r"\d")
_SUPERLATIVE_RE = re.compile(
    r"\b(best|most|fastest|cheapest|#1|number one|guaranteed|proven|"
    r"largest|biggest|leading|only|always|never|all|every|"
    # Common -est superlatives (an exact list, not \w+est which false-positives
    # on honest/request/forest/interest).
    r"simplest|easiest|smartest|safest|strongest|greatest|finest|cleverest|"
    r"sharpest|sleekest|hardest|lightest)\b",
    re.IGNORECASE,
)

# A grounding fragment must be substantive — a 1-2 word substring like "users"
# is a real substring of a quote but does not grounded-support the surrounding
# claim. Require a minimum word count for the verbatim match to count.
_MIN_FRAGMENT_WORDS = 4


def _safe_href(url: str) -> str:
    """Allowlist URL schemes for an HTML href — http(s) or a local ``#`` anchor.

    ``EvidenceRecord.url`` is an unconstrained string (a web finding's source
    URL), and ``html.escape`` does NOT neutralize ``javascript:`` / ``data:``
    schemes — so a crafted URL would ship a clickable script in the rendered
    index.html. Anything that isn't http(s) or a ``#`` anchor collapses to ``#``.
    """
    u = (url or "").strip()
    if u.startswith(("http://", "https://", "#")):
        return u
    return "#"


# ── LLM I/O shapes (private) ─────────────────────────────────────────────────


class _SectionPhrasing(BaseModel):
    """One LLM-proposed section for a single cluster.

    ``cluster_rank`` ties the proposal back to its source cluster so the builder
    can re-run exact-match grounding against THAT cluster's quotes. ``fragment``
    is the verbatim span the LLM claims to be quoting — the builder verifies it
    is a real substring before shipping anything.
    """

    cluster_rank: int = Field(description="1-based InsightCluster.rank this section is built on.")
    role: str = Field(description="Section job: hero/feature/objection/pricing/social_proof/cta.")
    copy: str = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        description="The section copy. MUST contain the verbatim fragment, word for word."
    )
    fragment: str = Field(
        description="A VERBATIM span copied character-for-character from one of the cluster's "
        "quotes — the load-bearing claim. Do not paraphrase."
    )


class _ConnectivePhrasing(BaseModel):
    """One claim-free transition the LLM may add between verbatim sections."""

    role: str = Field(description="Connective role, e.g. 'cta' or 'feature' glue.")
    copy: str = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        description="Claim-free transition copy: NO numbers, NO superlatives. Pure glue."
    )


class _SitePhrasing(BaseModel):
    """The ONE constrained LLM output for the whole site.

    ``sections`` are the per-cluster verbatim proposals (one per top cluster, in
    the builder's order); ``connective`` are optional claim-free transitions.
    """

    sections: list[_SectionPhrasing] = Field(
        default_factory=list[_SectionPhrasing],
        description="One proposed section per top cluster, each quoting a verbatim fragment.",
    )
    connective: list[_ConnectivePhrasing] = Field(
        default_factory=list[_ConnectivePhrasing],
        description="Optional claim-free transitions between sections.",
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _top_clusters(report: DemandReport) -> list[InsightCluster]:
    """Top clusters by demand_score that actually carry quotes (no-quote-no-section)."""
    with_quotes = [c for c in report.ranked_clusters if c.quotes]
    ranked = sorted(with_quotes, key=lambda c: c.demand_score, reverse=True)
    return ranked[:_TOP_N]


def _hero_rank(clusters: list[InsightCluster]) -> int | None:
    """The rank of the highest-distinct_author_count cluster (the hero's base)."""
    if not clusters:
        return None
    hero = max(clusters, key=lambda c: c.distinct_author_count)
    return hero.rank


def _matching_quote(cluster: InsightCluster, fragment: str) -> QuoteCitation | None:
    """The cluster quote whose text contains ``fragment`` verbatim, or None.

    Exact-match grounding: the LLM-picked fragment must be a real substring of a
    stored quote (which is itself already exact-matched to a Reddit comment). A
    blank or whitespace-only fragment never matches.
    """
    needle = fragment.strip()
    # A blank or too-short fragment never grounds — a 1-2 word substring is real
    # but doesn't support the surrounding copy (no-cite-no-claim, honestly).
    if not needle or len(needle.split()) < _MIN_FRAGMENT_WORDS:
        return None
    for q in cluster.quotes:
        if needle in q.text:
            return q
    return None


def _is_claim_free(text: str) -> bool:
    """True when connective copy carries no number and no superlative."""
    return not _DIGIT_RE.search(text) and not _SUPERLATIVE_RE.search(text)


def _normalize_role(role: str, *, fallback: str = "feature") -> str:
    r = role.strip().lower().replace(" ", "_").replace("-", "_")
    return r if r in _SITE_ROLES else fallback


def _build_sections(
    report: DemandReport,
    clusters: list[InsightCluster],
    phrasing: _SitePhrasing,
) -> list[SiteSection]:
    """Re-run exact-match grounding + claim-free gating over the LLM proposals.

    A verbatim proposal survives only when its fragment exact-matches a quote in
    its named cluster; it then carries one quote ``EvidenceRef``. The hero
    (highest-distinct_author_count cluster) is ordered first. Connective glue
    survives only when claim-free, and carries no refs.
    """
    by_rank = {c.rank: c for c in clusters}
    hero_rank = _hero_rank(clusters)

    verbatim: list[tuple[int, SiteSection]] = []
    for proposal in phrasing.sections:
        cluster = by_rank.get(proposal.cluster_rank)
        if cluster is None:
            continue  # proposal points at a cluster outside the top set — drop it.
        quote = _matching_quote(cluster, proposal.fragment)
        if quote is None:
            continue  # no-quote-no-section: unbacked fragment is dropped.
        role = "hero" if cluster.rank == hero_rank else _normalize_role(proposal.role)
        section = SiteSection(
            role=role,
            copy=proposal.copy.strip(),
            evidence_refs=[EvidenceRef(evidence_id=quote.id, kind="quote")],
            provenance="verbatim",
        )
        is_hero = cluster.rank == hero_rank
        verbatim.append((0 if is_hero else 1, section))

    # Hero first, then the rest in proposal order (stable sort preserves it).
    verbatim.sort(key=lambda t: t[0])
    sections: list[SiteSection] = [s for _, s in verbatim]

    for glue in phrasing.connective:
        copy = glue.copy.strip()
        if not copy or not _is_claim_free(copy):
            continue  # connective copy must be claim-free — drop claim-bearing glue.
        sections.append(
            SiteSection(
                role=_normalize_role(glue.role, fallback="cta"),
                copy=copy,
                evidence_refs=[],
                provenance="connective",
            )
        )
    return sections


# ── LLM pass (private) ───────────────────────────────────────────────────────


def _phrase_site(
    deps: ResearchDeps,
    clusters: list[InsightCluster],
    positioning: PositioningBrief | None,
) -> _SitePhrasing:
    blocks: list[str] = []
    for c in clusters:
        quotes = "\n".join(f'  - "{q.text}"' for q in c.quotes[:3])
        blocks.append(
            f"Cluster rank {c.rank} ({c.distinct_author_count} distinct authors): {c.claim}\n"
            f"Verbatim quotes you may pull a fragment from:\n{quotes}"
        )
    cluster_ctx = "\n\n".join(blocks)
    angle = ""
    if positioning is not None and positioning.wedge is not None:
        angle = (
            "\n\nPositioning angle to honor (do not invent beyond it):\n"
            f"{positioning.positioning_statement}"
        )
    system = (
        "You draft a small marketing site from ALREADY-VERIFIED Reddit demand evidence. For each "
        "cluster you are given, propose ONE section: pick a role "
        "(hero/feature/objection/pricing/social_proof/cta) and write short copy whose load-bearing "
        "line is a VERBATIM fragment copied character-for-character from one of that cluster's "
        "quotes. Put that exact fragment in BOTH the `fragment` field and inside `copy`. Never "
        "paraphrase the fragment — it is re-checked against the real quote and the section is "
        "dropped if it doesn't match. You MAY add a few `connective` transitions, but connective "
        "copy must be claim-free: no numbers and no superlatives (best/most/fastest/only/etc.)."
    )
    user = (
        f"Top demand clusters (most-supported first):\n\n{cluster_ctx}{angle}\n\n"
        "Return one section per cluster (set cluster_rank to that cluster's rank), each quoting a "
        "verbatim fragment, plus optional claim-free connective glue."
    )
    return deps.chat.complete_structured(
        system=system,
        user=user,
        output_model=_SitePhrasing,
        max_tokens=2048,
        temperature=0.4,
    )


# ── Public entry ─────────────────────────────────────────────────────────────


def build_marketing_site(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None = None,
) -> MarketingSite:
    """Build a grounded :class:`MarketingSite` from a finished report.

    Takes the top 3 clusters by ``demand_score``, makes one constrained LLM call
    to assign roles + pick verbatim fragments, then re-runs exact-match grounding
    so only sections whose fragment is a real quote substring ship (each with a
    resolvable quote ref). The hero is built on the highest-distinct_author_count
    cluster. Connective copy ships claim-free with no refs. On any LLM failure,
    returns an honest partial empty site — never raises.
    """
    site_id = f"site-{report.report_id}"
    clusters = _top_clusters(report)
    if not clusters:
        return MarketingSite(
            site_id=site_id,
            report_id=report.report_id,
            sections=[],
            partial=True,
            caveat="No quote-backed demand clusters to build a site on (no-quote-no-section).",
        )

    try:
        phrasing = _phrase_site(deps, clusters, positioning)
    except Exception as exc:  # phrasing failed — honest partial, not a crash
        return MarketingSite(
            site_id=site_id,
            report_id=report.report_id,
            sections=[],
            partial=True,
            caveat=f"Site synthesis unavailable ({type(exc).__name__}); no sections built.",
        )

    sections = _build_sections(report, clusters, phrasing)
    if not sections:
        return MarketingSite(
            site_id=site_id,
            report_id=report.report_id,
            sections=[],
            partial=True,
            caveat="No section's fragment matched a verified quote (no-quote-no-section).",
        )
    return MarketingSite(
        site_id=site_id,
        report_id=report.report_id,
        sections=sections,
    )


# ── Rendering ────────────────────────────────────────────────────────────────


def _evidence_by_id(report_evidence: list[EvidenceRecord]) -> dict[str, EvidenceRecord]:
    return {e.id: e for e in report_evidence}


def render_site_html(site: MarketingSite, report: DemandReport | None = None) -> str:
    """Render ``site`` as one self-contained ``index.html`` string.

    Each verbatim section's copy is followed by a superscript footnote linking
    the quote's permalink (carrying a ``data-evidence`` attribute with the
    evidence id); connective sections render with no footnote. When ``report`` is
    supplied, footnote permalinks resolve through its ``evidence``; otherwise the
    footnote falls back to the bare evidence id.
    """
    lookup = _evidence_by_id(report.evidence) if report is not None else {}

    body: list[str] = []
    footnotes: list[str] = []
    note_n = 0
    for section in site.sections:
        role = html.escape(section.role)
        copy = html.escape(section.copy)
        if section.provenance == "verbatim" and section.evidence_refs:
            ref = section.evidence_refs[0]
            eid = ref.evidence_id
            note_n += 1
            record = lookup.get(eid)
            raw_url = record.url if record is not None and record.url else f"#evidence-{eid}"
            permalink = _safe_href(raw_url)
            sup = (
                f'<sup class="fn"><a href="{html.escape(permalink)}" '
                f'data-evidence="{html.escape(eid)}">[{note_n}]</a></sup>'
            )
            body.append(
                f'  <section class="section section--{role}" data-provenance="verbatim">\n'
                f"    <p>{copy}{sup}</p>\n"
                f"  </section>"
            )
            footnotes.append(
                f'    <li id="fn-{note_n}" data-evidence="{html.escape(eid)}">'
                f'<a href="{html.escape(permalink)}">{html.escape(permalink)}</a></li>'
            )
        else:
            body.append(
                f'  <section class="section section--{role}" data-provenance="connective">\n'
                f"    <p>{copy}</p>\n"
                f"  </section>"
            )

    footnotes_block = ""
    if footnotes:
        footnotes_block = (
            '  <footer class="footnotes">\n    <ol>\n'
            + "\n".join(footnotes)
            + "\n    </ol>\n  </footer>"
        )

    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        f"  <title>{html.escape(site.site_id)}</title>",
        "</head>",
        "<body>",
        "  <main>",
        *body,
        "  </main>",
    ]
    if footnotes_block:
        parts.append(footnotes_block)
    parts += ["</body>", "</html>", ""]
    return "\n".join(parts)
