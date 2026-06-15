"""Pillar F — Launch.

Turn a finished :class:`~metalworks.contract.research.DemandReport` (plus its
:class:`~metalworks.contract.positioning.PositioningBrief`) into a set of
channel-native, drafting-only launch assets — one per surface — and a
deterministic :class:`~metalworks.contract.launch.ChannelPlan`.

The honesty move: launch copy is the easiest place to over-claim, so every
factual / quantified / attitudinal claim an asset makes is GROUNDED. The LLM
returns a body plus a list of claims, each paired with the verbatim quote that
supports it. The builder then, for each claim:

1. finds the claim's supporting quote in the report (exact substring match
   against some ``ResolvedCitation.text``) → an :class:`EvidenceRef` (quote id);
2. locates the claim text inside the asset body (``body.find``) → char span;
3. emits a :class:`~metalworks.contract.launch.ClaimCitation` only when BOTH
   resolve. A claim whose support doesn't resolve against ``report.evidence``,
   or whose text isn't in the body, is DROPPED (no-cite-no-claim).

The builder REFUSES (returns ``[]``) when the report signals no-go: a negative
``verdict`` (thin signal / no demand), or no cluster with ``≥ 2`` distinct
authors. Each asset body is run through the deterministic ``heuristic_check``
compliance gate best-effort — a drafting-time signal only, never a blocker.

``plan_channels(report, surfaces)`` is fully deterministic: one
``requires_human`` + ``posting_gated`` :class:`ChannelStep` per surface. Show HN
in particular is never automated.

DRAFTING ONLY — this module never posts. ``build_launch_assets`` /
``plan_channels`` are the reusable cores behind the ``metalworks launch`` CLI and
the ``launch_assets_build`` / ``channel_plan_build`` MCP tools.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import DemandReport, EvidenceRef, ResolvedCitation
from metalworks.contract.launch import (
    ChannelPlan,
    ChannelStep,
    ClaimCitation,
    LaunchAsset,
)
from metalworks.reddit import heuristic_check

if TYPE_CHECKING:
    from metalworks.contract.positioning import PositioningBrief
    from metalworks.research.deps import ResearchDeps

# The launch surfaces this pillar drafts, in execution order.
DEFAULT_SURFACES: tuple[str, ...] = ("product_hunt", "show_hn", "x_thread")

# Verdict substrings that mean "don't launch" — a no-go signal from the report.
_NEGATIVE_VERDICT = ("thin signal", "no demand", "insufficient", "not enough", "no-go", "no go")

# Minimum distinct authors on at least one cluster for a launch to be defensible.
_MIN_DISTINCT_AUTHORS = 2

# A supporting quote fragment must be substantive — a 1-2 word substring is a
# real slice of a quote but doesn't ground the claim (no-cite-no-claim).
_MIN_SUPPORT_WORDS = 4

# Human-friendly framing per surface, fed to the LLM and to the channel plan.
_SURFACE_BRIEF: dict[str, str] = {
    "product_hunt": (
        "A Product Hunt launch post: a punchy tagline + a short maker comment. "
        "Concrete, benefit-led, no hype words."
    ),
    "show_hn": (
        "A Show HN post: a plain 'Show HN: <thing>' title + a technical, "
        "no-marketing first comment that respects the HN audience."
    ),
    "x_thread": (
        "An X/Twitter launch thread: a strong first-tweet hook + a few short "
        "follow-on lines. Plain-spoken, no thread-bro filler."
    ),
}

_SURFACE_ACTION: dict[str, str] = {
    "product_hunt": "Review and submit the Product Hunt draft, then engage in comments.",
    "show_hn": "Manually post the Show HN draft (NEVER automated) and answer replies yourself.",
    "x_thread": "Review and post the X launch thread from your own account.",
}


# ── LLM I/O shapes (private) ─────────────────────────────────────────────────


class _ClaimDraft(BaseModel):
    """One claim the LLM wants to make, with the quote it says supports it."""

    text: str = Field(
        description="The exact claim sentence/phrase AS IT APPEARS in the body verbatim."
    )
    supporting_quote: str = Field(
        description="The verbatim Reddit quote that backs this claim. Copy it exactly."
    )


class _AssetPhrasing(BaseModel):
    """The LLM-authored launch draft for one surface."""

    title: str = Field(description="The headline / title / first-tweet hook for this surface.")
    body: str = Field(description="The channel-native body copy.")
    variants: list[str] = Field(
        default_factory=list[str], description="1-3 alternate hooks/headlines."
    )
    claims: list[_ClaimDraft] = Field(
        default_factory=list[_ClaimDraft],
        description="Each factual/quantified/attitudinal claim, with its supporting quote.",
    )


# ── Refusal gate ─────────────────────────────────────────────────────────────


def _is_no_go(report: DemandReport) -> bool:
    """True when the report says don't launch (negative verdict or thin evidence).

    Only the DEMAND-strength segment of the verdict is judged — the leading part
    before the first ``;``. The verdict appends market/price caveats (e.g.
    ``"not enough price signal to recommend a price"``) whose wording collides
    with the negative-demand phrases; a strong-demand report with thin PRICE
    signal is still launch-worthy, so those caveats must not be read as no-go.
    """
    verdict = (report.verdict or "").lower()
    demand_segment = verdict.split(";", 1)[0]
    if demand_segment and any(signal in demand_segment for signal in _NEGATIVE_VERDICT):
        return True
    return not any(c.distinct_author_count >= _MIN_DISTINCT_AUTHORS for c in report.ranked_clusters)


# ── Grounding helpers ────────────────────────────────────────────────────────


def _all_quotes(report: DemandReport) -> list[ResolvedCitation]:
    """Every ResolvedCitation across all clusters (the verbatim corpus to ground on)."""
    return [q for c in report.ranked_clusters for q in c.quotes]


def _supporting_quote(report: DemandReport, supporting_quote: str) -> ResolvedCitation | None:
    """The report quote whose text contains the LLM's supporting_quote, or None.

    Exact-substring match (the verbatim gate): the LLM's claimed support must be
    a literal slice of a real, verified quote — not a paraphrase.
    """
    needle = supporting_quote.strip()
    # A 1-2 word substring ("users") is a real slice of a quote but doesn't
    # ground the surrounding claim — require a substantive fragment.
    if not needle or len(needle.split()) < _MIN_SUPPORT_WORDS:
        return None
    for q in _all_quotes(report):
        if needle in q.text:
            return q
    return None


def _ground_claims(
    report: DemandReport, body: str, claims: list[_ClaimDraft]
) -> list[ClaimCitation]:
    """Build a ClaimCitation per claim that resolves BOTH ways; drop the rest.

    A claim survives only when (a) its supporting quote resolves to a real
    ResolvedCitation in the report AND (b) its claim text is found verbatim in the
    asset body. The resulting span satisfies ``body[start:end] == claim_text``,
    and the ``EvidenceRef`` resolves against ``report.evidence`` by quote id.
    """
    evidence_ids = {e.id for e in report.evidence}
    citations: list[ClaimCitation] = []
    for claim in claims:
        quote = _supporting_quote(report, claim.supporting_quote)
        if quote is None or quote.id not in evidence_ids:
            continue  # no-cite-no-claim: support doesn't resolve
        claim_text = claim.text.strip()
        start = body.find(claim_text)
        if not claim_text or start == -1:
            continue  # claim text not present verbatim in the body
        end = start + len(claim_text)
        citations.append(
            ClaimCitation(
                claim_text=claim_text,
                span_start=start,
                span_end=end,
                evidence_ref=EvidenceRef(evidence_id=quote.id, kind="quote"),
            )
        )
    return citations


# ── LLM pass (private) ───────────────────────────────────────────────────────


def _phrase_asset(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None,
    surface: str,
) -> _AssetPhrasing:
    quotes = "\n".join(f'- "{q.text}"' for q in _all_quotes(report)[:8])
    claims_ctx = "\n".join(f"- {c.claim}" for c in report.ranked_clusters[:5])
    statement = positioning.positioning_statement if positioning is not None else ""
    pos_ctx = (
        f"\nPositioning statement to stay consistent with:\n{statement}\n" if statement else ""
    )
    surface_brief = _SURFACE_BRIEF.get(surface, f"A launch post for the '{surface}' channel.")

    system = (
        "You draft ONE channel-native launch asset from ALREADY-VERIFIED demand evidence. "
        "You are DRAFTING ONLY — this is never posted automatically. Write in a plain, "
        "human voice with NO hype words and NO AI tells (no 'game-changer', 'revolutionary', "
        "'great question', 'in today's world', em-dash filler). Every factual, quantified, or "
        "attitudinal claim you make MUST be backed by a verbatim quote from the evidence below: "
        "put the claim sentence in the body EXACTLY as you list it in `claims`, and copy its "
        "`supporting_quote` verbatim from the provided quotes. Do not invent numbers or sentiment "
        "the quotes don't support."
    )
    user = (
        f"Surface: {surface}\n{surface_brief}\n{pos_ctx}\n"
        f"Top demand claims (already verified):\n{claims_ctx}\n\n"
        f"Verbatim quotes you may cite (copy supporting_quote from these EXACTLY):\n{quotes}\n\n"
        "Write the asset: title (the hook), body (channel-native copy), variants (1-3 alternate "
        "hooks), and claims (each with `text` appearing verbatim in the body and a verbatim "
        "`supporting_quote`)."
    )
    return deps.chat.complete_structured(
        system=system,
        user=user,
        output_model=_AssetPhrasing,
        # A full asset (body + variants + claims JSON) is large, and Gemini 3.x
        # spends ~1-2k hidden thinking tokens first — too small a cap truncates
        # the JSON mid-string. Size generously.
        max_tokens=4096,
        temperature=0.4,
    )


def _build_one_asset(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None,
    surface: str,
) -> LaunchAsset | None:
    """Draft + ground one surface's asset. Returns None on LLM failure (skip)."""
    try:
        phrasing = _phrase_asset(deps, report, positioning, surface)
    except Exception:  # best-effort per surface — one failure never sinks the batch
        return None
    body = phrasing.body
    citations = _ground_claims(report, body, phrasing.claims)
    # Drafting-only compliance signal — run the gate but never block on it.
    with contextlib.suppress(Exception):
        heuristic_check(body)
    return LaunchAsset(
        surface=surface,
        title=phrasing.title.strip(),
        body=body,
        variants=[v.strip() for v in phrasing.variants if v.strip()],
        claim_citations=citations,
    )


# ── Public entry ─────────────────────────────────────────────────────────────


def build_launch_assets(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None = None,
) -> list[LaunchAsset]:
    """Draft grounded, channel-native launch assets from a finished report.

    REFUSES (returns ``[]``) when the report signals no-go: a negative
    ``verdict`` (thin signal / no demand) or no cluster with ``≥ 2`` distinct
    authors. Otherwise drafts one asset per surface in :data:`DEFAULT_SURFACES`
    via a single ``complete_structured`` call each, grounds every claim against
    the report's verbatim quotes (no-cite-no-claim), and runs each body through
    the deterministic compliance gate best-effort. A surface whose LLM call fails
    is skipped, never fatal. DRAFTING ONLY — never posts.
    """
    if _is_no_go(report):
        return []
    assets: list[LaunchAsset] = []
    for surface in DEFAULT_SURFACES:
        asset = _build_one_asset(deps, report, positioning, surface)
        if asset is not None:
            assets.append(asset)
    return assets


def plan_channels(report: DemandReport, surfaces: list[str] | None = None) -> ChannelPlan:
    """Build a deterministic, human-executed launch sequence for a report.

    One :class:`ChannelStep` per surface, each ``requires_human`` and
    ``posting_gated`` by construction (the library plans; a person posts). Show
    HN is never automated. No LLM call — fully deterministic.
    """
    chosen = surfaces if surfaces is not None else list(DEFAULT_SURFACES)
    steps = [
        ChannelStep(
            surface=surface,
            action=_SURFACE_ACTION.get(surface, f"Review and post the {surface} draft yourself."),
            scheduled_offset=f"T+{i * 2}h",
            requires_human=True,
            posting_gated=True,
        )
        for i, surface in enumerate(chosen)
    ]
    return ChannelPlan(report_id=report.report_id, steps=steps)
