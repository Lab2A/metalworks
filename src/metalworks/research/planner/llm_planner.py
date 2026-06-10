"""Content provider for DecisionBriefs.

Ported from clique-research-api's ``llm_planner.py``. :func:`provide_content`
produces the next :class:`DecisionBrief` for a planner turn.

Port change: the source's ``PLANNER_MODE`` env switch (stub vs vertex) is
dropped. We ALWAYS call ``deps.chat.complete_structured``; on any failure
(model error, schema validation, empty response) we fall back to a small
built-in canned brief so a planner turn never hard-fails. The canned options
are kept verbatim from the source's stub set so the fallback is usable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from metalworks.research.planner.decision_brief import DecisionBrief, Option

if TYPE_CHECKING:  # pragma: no cover - typing only
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.planner.question_bank import QuestionSpec

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "You are the conversational planner for a consumer-research engine, building a Research Brief "
    "one question at a time. Produce a DecisionBrief in the gstack format. Honor: 2-4 options, "
    ">=2 pros (>=40 chars) and >=1 con (>=40 chars) per option, exactly one option marked "
    "recommended, ELI10 >=80 chars, an explicit recommendation line with reason, an honest stakes "
    "line."
)


def _build_user_prompt(spec: QuestionSpec, prompt: str, prior_answers: dict[str, object]) -> str:
    return (
        f"Research prompt: {prompt}\n"
        f"Prior answers so far: {prior_answers}\n"
        f"Current question topic ({spec.decision_id}): {spec.topic}\n"
        f"Stakes hint: {spec.stakes_hint}\n"
        f"ELI10 hint: {spec.eli10_hint}\n"
        f"Recommendation hint: {spec.recommendation_hint}\n"
        f"multi_select: {spec.multi_select}\n"
        f"Header chip MUST be exactly: {spec.header_chip}"
    )


def provide_content(
    deps: ResearchDeps,
    *,
    question_spec: QuestionSpec,
    prompt: str,
    prior_answers: dict[str, object],
) -> DecisionBrief:
    """Produce the DecisionBrief for one planner turn.

    Always tries ``deps.chat.complete_structured`` first; on any failure, falls
    back to a built-in canned brief so the turn never hard-fails.
    """
    try:
        return deps.chat.complete_structured(
            system=_SYSTEM_PROMPT,
            user=_build_user_prompt(question_spec, prompt, prior_answers),
            output_model=DecisionBrief,
        )
    except Exception:
        logger.exception(
            "planner content failed for %s; falling back to canned brief",
            question_spec.decision_id,
        )
        return _fallback_brief(question_spec)


def _fallback_brief(spec: QuestionSpec) -> DecisionBrief:
    """A minimal, always-valid DecisionBrief from the canned option bank."""
    options = _FALLBACK_OPTIONS.get(spec.decision_id) or _GENERIC_OPTIONS
    return DecisionBrief(
        decision_id=spec.decision_id,
        header=spec.header_chip,
        eli10=spec.eli10_hint,
        stakes="Stakes if we pick wrong: " + spec.stakes_hint,
        recommendation="Recommendation: " + spec.recommendation_hint,
        options=options,
        multi_select=spec.multi_select,
        custom_text_allowed=True,
    )


# A topic-agnostic last resort so even an unknown decision_id yields a valid
# brief (and the fallback never raises on a missing key).
_GENERIC_OPTIONS: list[Option] = [
    Option(
        label="Go with the recommendation",
        pros=[
            "The recommended framing is the safe default for the overwhelming majority of cases",
            "Keeps the planning conversation moving without burning a turn on a custom answer",
        ],
        cons=[
            "May not capture a nuance specific to your situation that custom text would surface",
        ],
        net="Best when the recommendation already matches what you're trying to do.",
        is_recommended=True,
    ),
    Option(
        label="Answer in your own words",
        pros=[
            "Lets you state exactly what you mean instead of picking the closest preset option",
            "The custom-text path is always available and is the truth tap for this question",
        ],
        cons=[
            "Takes a little longer and asks you to articulate the answer precisely yourself",
        ],
        net="Best when none of the presets quite fit what you actually need.",
    ),
]


# Canned per-question options, kept verbatim from the source stub set. These are
# the fallback when ``deps.chat.complete_structured`` fails for a known topic.
_FALLBACK_OPTIONS: dict[str, list[Option]] = {
    "D1": [
        Option(
            label="Validate demand for a specific product",
            pros=[
                "Sharpest framing when you have a v0 in mind and need a go / no-go before building "
                "further",
                "Maps cleanly onto Reddit's audience-language signal — wants and complaints "
                "translate directly",
            ],
            cons=[
                "Misses adjacent product opportunities the audience may want more than your "
                "specific v0",
            ],
            net="Best when you already know what you want to build and need a sanity check.",
            is_recommended=True,
        ),
        Option(
            label="Characterize the audience for a category",
            pros=[
                "Useful when the category is set but the specific product is still flexible enough "
                "to shape",
                "Surfaces sub-segments and language that inform both product and positioning",
            ],
            cons=[
                "Tends to read as broad rather than decisive when you need a yes / no answer",
            ],
            net="Best when you're early enough that audience shape can still steer the product.",
        ),
        Option(
            label="Map competitors and pricing",
            pros=[
                "Best framing when the product is well-defined and the open question is where it "
                "sits",
                "Cross-stream synthesis is at its strongest here — Reddit voice plus pricing intel",
            ],
            cons=[
                "Doesn't directly answer 'is anyone asking for this' if the category itself is new",
            ],
            net="Best when product-market fit isn't the question, but positioning is.",
        ),
    ],
    "D2": [
        Option(
            label="Should we build this v0 at all",
            pros=[
                "Highest-leverage framing — the report will explicitly produce a recommended go / "
                "no-go",
                "Forces the verdict to be defensible against the cross-stream evidence",
            ],
            cons=[
                "If you've already decided to build, this framing wastes the report's persuasive "
                "power",
            ],
            net="Best when you're genuinely undecided and need the evidence to push you one way.",
            is_recommended=True,
        ),
        Option(
            label="Refine positioning for an already-committed v0",
            pros=[
                "Shapes the report toward language, segment fit, and the specific positioning "
                "angle",
                "Includes the must-address index for positioning sub-questions you can act on",
            ],
            cons=[
                "Less useful if the team hasn't agreed on the v0 itself yet — risks polishing the "
                "wrong thing",
            ],
            net="Best when the team is aligned on what to build and the question is how to talk "
            "about it.",
        ),
        Option(
            label="Inform a fundraising or hiring pitch",
            pros=[
                "Tunes the verdict and corpus stats toward defensible numbers a stakeholder would "
                "scrutinize",
                "Surfaces the deck-quality charts and citations the pitch will need to land",
            ],
            cons=[
                "Higher confidence threshold means smaller findings get filtered out and slower "
                "turnaround",
            ],
            net="Best when the report needs to survive an investor or executive review.",
        ),
    ],
    "D3": [
        Option(
            label="Surfaces what consumers actually say in their own words",
            pros=[
                "Produces direct quotes you can put in a deck, ad, or product brief, with "
                "citations that hold up",
                "Reddit-side strength of the engine; the cross-stream synthesis adds the why "
                "behind the what",
            ],
            cons=[
                "If the audience is silent on Reddit, this criterion will read as thin even on a "
                "good run",
            ],
            net="Strongest criterion when the report needs to be persuasive to a non-technical "
            "audience.",
            is_recommended=True,
        ),
        Option(
            label="Names specific competitors and how they're discussed",
            pros=[
                "Anchors the verdict to a competitive landscape the reader can verify by reading "
                "themselves",
                "Combines the web stream's pricing intel with the Reddit stream's qualitative "
                "reception",
            ],
            cons=[
                "Pulls effort away from audience-voice if the competitor list is long or "
                "fragmented",
            ],
            net="Strongest when the open question is positioning rather than demand.",
        ),
        Option(
            label="Produces a recommended go / no-go with confidence band",
            pros=[
                "Single-line decision support, the highest-leverage output for an executive reader",
                "Forces every other finding to support or qualify the recommendation — no orphaned "
                "data",
            ],
            cons=[
                "Compresses the report's nuance; some readers want the evidence map, not the "
                "verdict",
            ],
            net="Strongest when the report is feeding a yes / no decision.",
        ),
        Option(
            label="Estimates market size and willingness-to-pay",
            pros=[
                "Bottom-up Reddit floor plus addressable-market modeling, with the assumptions "
                "exposed",
                "Most useful criterion when the report is part of a fundraising or "
                "capital-allocation pitch",
            ],
            cons=[
                "Sizing always carries assumptions; the model exposes them, but readers can argue "
                "with them",
            ],
            net="Strongest when the dollar number matters as much as the audience signal.",
        ),
    ],
    "D4": [
        Option(
            label="What price point will the audience accept",
            pros=[
                "Cross-stream verification of pricing through both willingness-to-pay signals and "
                "competitor data",
                "Always one of the most-asked must-address items in consumer-research reports",
            ],
            cons=[
                "WTP signals are noisier than other corpus stats; confidence band may be wide on "
                "first run",
            ],
            net="Useful default unless price is already locked.",
            is_recommended=True,
        ),
        Option(
            label="Which segment is the highest-conviction buyer",
            pros=[
                "Segment ranking is built into the engine and produces a clear top-1 with evidence",
                "Surfaces sub-audiences that may differ meaningfully from the headline target "
                "demographic",
            ],
            cons=[
                "Only useful if you have flexibility on who to target with launch messaging or "
                "paid acquisition",
            ],
            net="Useful when you need to focus a small launch budget on one segment.",
        ),
        Option(
            label="What specific features are most-asked",
            pros=[
                "Maps directly to a roadmap-priority list ranked by distinct-author breadth, not "
                "vote count",
                "Each finding cites the real comment so engineers can read the original ask in "
                "context",
            ],
            cons=[
                "Returns less signal when the product space is mature and feature wishlists are "
                "already saturated",
            ],
            net="Useful for shaping the v1 backlog when v0 is already decided.",
        ),
    ],
    "D5": [
        Option(
            label="Top consumer-supplement subreddits (r/Supplements, r/Nootropics)",
            pros=[
                "Highest signal-to-noise for supplement-buyer audiences and willingness-to-pay "
                "discussions",
                "Combined population of distinct authors per year is more than enough for a "
                "confident verdict",
            ],
            cons=[
                "Skews male-skewing and west-coast; cross-check with the audience profile in the "
                "report",
            ],
            net="Default for most supplement-related consumer-research questions.",
            is_recommended=True,
        ),
        Option(
            label="Add demographic-specific subreddits (r/GenZ, r/Fitness)",
            pros=[
                "Broadens the audience signal and catches segments that don't show up in core "
                "supplement subs",
                "Useful when the question is about positioning to a specific demographic rather "
                "than category",
            ],
            cons=[
                "Adds noise; raises the post-triage relevant rate but lowers it for the wider raw "
                "pull",
            ],
            net="Add when the question explicitly targets a demographic outside the "
            "supplement-core audience.",
        ),
        Option(
            label="Pick custom subreddits (advanced)",
            pros=[
                "Use when you have domain knowledge about communities the planner missed or "
                "weighted wrong",
                "Lets you exclude communities where your category is taboo or off-topic",
            ],
            cons=[
                "Wrong picks here cost a full run; mistake costs are real because reports aren't "
                "free",
            ],
            net="Use when you know your category better than the planner does.",
        ),
    ],
    "D6": [
        Option(
            label="12 months",
            pros=[
                "Captures a full seasonal cycle — winter / summer / back-to-school / holiday — "
                "without staleness",
                "Standard window the engine is calibrated for; the eval fixtures all run at this "
                "width",
            ],
            cons=[
                "Misses long-term trend changes that span 2+ years",
            ],
            net="The right default for ~95% of consumer-research questions.",
            is_recommended=True,
        ),
        Option(
            label="24 months",
            pros=[
                "Year-over-year comparison surfaces growth, decay, or genuine seasonality vs "
                "episodic chatter",
                "Better signal when the question is explicitly about trend direction rather than "
                "current state",
            ],
            cons=[
                "Doubles the pull size and increases compile cost noticeably; longer wall-clock "
                "per report",
            ],
            net="Pick when the question is about trends, not snapshots.",
        ),
        Option(
            label="6 months",
            pros=[
                "Faster pull and lower compile cost; useful for fast-iteration scenarios",
                "Tighter recency bias for categories where last quarter's voice dominates the "
                "current one",
            ],
            cons=[
                "May miss the seasonal pattern entirely, especially for categories with clear "
                "winter / summer behavior",
            ],
            net="Pick when recency matters more than seasonal coverage.",
        ),
    ],
    "D7": [
        Option(
            label="Competitive landscape and pricing",
            pros=[
                "Cross-stream verification is strongest here — Reddit voice plus structured price "
                "data on competitors",
                "Drives the most-cited section of the report when the question involves "
                "positioning",
            ],
            cons=[
                "Adds time to the web stream; pricing-page parsing is the slowest of the "
                "structured-finding modes",
            ],
            net="The single highest-leverage web direction for most consumer-research questions.",
            is_recommended=True,
        ),
        Option(
            label="SEO and search-intent for the category",
            pros=[
                "Surfaces what the broader internet (not just Reddit) is asking about the category "
                "right now",
                "Useful counterweight when Reddit's coverage skews to enthusiasts and you need "
                "mainstream signal",
            ],
            cons=[
                "Search data is noisier and less attributable than Reddit comments; "
                "lower-confidence findings",
            ],
            net="Add when Reddit alone risks looking like an enthusiast bubble.",
        ),
        Option(
            label="Regulatory and category news",
            pros=[
                "Catches category-level events that shape demand independently of individual "
                "product preferences",
                "Required when the category has active regulatory motion — FDA, FTC, state-level "
                "rule changes",
            ],
            cons=[
                "Most categories don't have meaningful regulatory motion; can come back light",
            ],
            net="Add when the category has clear regulatory exposure.",
        ),
    ],
    "D8": [
        Option(
            label="Full report at actionable confidence",
            pros=[
                "Default and right for the overwhelming majority of consumer-research questions",
                "Verdict is supported by enough evidence to act on, without inflating findings "
                "beyond what's there",
            ],
            cons=[
                "Slower than brief-only at the same confidence; investment-grade requires more "
                "compute still",
            ],
            net="The right default.",
            is_recommended=True,
        ),
        Option(
            label="Brief-only at actionable confidence",
            pros=[
                "Fastest output for when the team only needs the verdict, top clusters, and "
                "one-line takeaways",
                "Cuts compile time and cost noticeably when the full breakdown isn't needed for "
                "this decision",
            ],
            cons=[
                "Loses the depth that makes a report convincing to a skeptical reader",
            ],
            net="Pick when the report's job is to inform one decision quickly, not to persuade.",
        ),
        Option(
            label="Full report at investment-grade confidence",
            pros=[
                "Tighter confidence bands and more aggressive corpus expansion; the "
                "highest-confidence verdict",
                "Right when the report has to survive an investor or executive review",
            ],
            cons=[
                "Materially slower and more expensive — roughly 2x cost and wall-clock per run vs "
                "actionable",
            ],
            net="Pick when capital allocation depends on the verdict.",
        ),
    ],
}
