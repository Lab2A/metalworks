"""Question bank — the 8 ordered topics the planner walks through.

The D1-D8 planner question bank (pure data).
Each topic is a :class:`QuestionSpec`; the actual ELI10 / recommendation /
option content is produced by the content provider in ``llm_planner.py``.

Smart-skip is intentionally NOT implemented: every question is asked because
reports are slow and expensive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionSpec:
    """A single planner question definition. Static; content comes from the provider."""

    decision_id: str  # "D1"
    header_chip: str  # "D1 · The question"
    topic: str  # short title for logs/summaries
    multi_select: bool  # True for D3, D4, D7 (lists)
    stakes_hint: str  # seed for the stakes line
    eli10_hint: str  # seed for the ELI10
    recommendation_hint: str  # seed for the recommendation
    extracts_to: str  # key on the answers dict this question maps to


QUESTIONS: list[QuestionSpec] = [
    QuestionSpec(
        decision_id="D1",
        header_chip="D1 · The question",
        topic="The actual question",
        multi_select=False,
        stakes_hint=(
            "If we get the question wrong, the entire report answers a question you didn't have."
        ),
        eli10_hint=(
            "Your one-liner can mean different things to different people. We want to lock in the "
            "version of the question we're going to answer, before we spend hours and dollars "
            "researching."
        ),
        recommendation_hint="Pick the framing that matches the decision you're actually making.",
        extracts_to="question",
    ),
    QuestionSpec(
        decision_id="D2",
        header_chip="D2 · Decision context",
        topic="Decision context",
        multi_select=False,
        stakes_hint=(
            "If we don't know which decision this informs, we may produce a beautiful report that "
            "doesn't address what you'll actually do next."
        ),
        eli10_hint=(
            "Research is most useful when it serves a specific decision. Tell us what you'll do "
            "with the report so we can shape the output to that decision."
        ),
        recommendation_hint="Pick the decision shape closest to what you're really doing.",
        extracts_to="decision_context",
    ),
    QuestionSpec(
        decision_id="D3",
        header_chip="D3 · Success criteria",
        topic="Success criteria",
        multi_select=True,
        stakes_hint=(
            "If success isn't defined, we can't tell you (or us) whether the report did its job."
        ),
        eli10_hint=(
            "How will you know this report was worth running? Pick the criteria that, if met, "
            "would make you say 'this was useful.' These criteria shape what the report emphasizes."
        ),
        recommendation_hint=(
            "The criteria below are the most common; pick those that apply, add your own."
        ),
        extracts_to="success_criteria",
    ),
    QuestionSpec(
        decision_id="D4",
        header_chip="D4 · Must address",
        topic="Must-address sub-questions",
        multi_select=True,
        stakes_hint=(
            "If we don't list the sub-questions up front, the report may be excellent and still "
            "miss the specific thing you care about."
        ),
        eli10_hint=(
            "What specific sub-questions must the report answer? Each one becomes a line in the "
            "report's must-address index, either resolved with evidence or marked unaddressable "
            "with a reason."
        ),
        recommendation_hint=(
            "Start with what would frustrate you most if the report didn't address it."
        ),
        extracts_to="must_address",
    ),
    QuestionSpec(
        decision_id="D5",
        header_chip="D5 · Target communities",
        topic="Target subreddits",
        multi_select=True,
        stakes_hint=(
            "If we read the wrong subreddits, we'll get the wrong picture even from the same "
            "engine."
        ),
        eli10_hint=(
            "Which Reddit communities should the corpus pull cover? We've suggested the ones that "
            "look highest-intent for your question; you can add, remove, or replace."
        ),
        recommendation_hint=(
            "The suggested set covers the highest-signal communities for this question. Edit if "
            "you have domain knowledge we don't."
        ),
        extracts_to="target_subreddits",
    ),
    QuestionSpec(
        decision_id="D6",
        header_chip="D6 · Time window",
        topic="Time window",
        multi_select=False,
        stakes_hint=(
            "Too short a window misses seasonal patterns. Too long includes stale context that no "
            "longer reflects current preferences."
        ),
        eli10_hint=(
            "How far back should we read? Longer windows catch seasonal patterns; shorter windows "
            "stay close to today. Twelve months is the default and the right choice for most "
            "consumer-research questions."
        ),
        recommendation_hint=(
            "12 months. Captures a full seasonal cycle without drowning in stale content."
        ),
        extracts_to="time_window_months",
    ),
    QuestionSpec(
        decision_id="D7",
        header_chip="D7 · Web research",
        topic="Web research directions",
        multi_select=True,
        stakes_hint=(
            "The web stream runs in parallel to Reddit. If we point it nowhere, we lose the "
            "cross-stream verification that makes the verdict deterministic."
        ),
        eli10_hint=(
            "Beyond Reddit, what should the web research stream pursue? Each direction becomes a "
            "set of targeted queries; findings get cross-referenced against the Reddit clusters."
        ),
        recommendation_hint=(
            "Competitive landscape and pricing are usually the highest-leverage directions for "
            "consumer-research questions. Pick what applies."
        ),
        extracts_to="web_research_directions",
    ),
    QuestionSpec(
        decision_id="D8",
        header_chip="D8 · Output and confidence",
        topic="Output template and confidence threshold",
        multi_select=False,
        stakes_hint=(
            "Same data, different output and confidence levels. If we pick the wrong threshold, "
            "the report will either over-claim or under-deliver."
        ),
        eli10_hint=(
            "Two final choices: how complete should the report be (full vs brief-only), and how "
            "confident should the verdict be? Directional is fast and approximate; actionable is "
            "the standard for product decisions; investment-grade is for high-stakes capital "
            "allocation."
        ),
        recommendation_hint=(
            "Full report at actionable confidence is the right default for most consumer-research "
            "questions."
        ),
        extracts_to="output_settings",
    ),
]


def find_question(decision_id: str) -> QuestionSpec | None:
    """Look up a QuestionSpec by decision_id."""
    for q in QUESTIONS:
        if q.decision_id == decision_id:
            return q
    return None


def next_decision_id(current_decision_id: str | None) -> str | None:
    """The next decision_id in the sequence, or None when there's no more."""
    if current_decision_id is None:
        return QUESTIONS[0].decision_id
    for i, q in enumerate(QUESTIONS):
        if q.decision_id == current_decision_id and i + 1 < len(QUESTIONS):
            return QUESTIONS[i + 1].decision_id
    return None


def is_last_question(decision_id: str) -> bool:
    """True when this is the terminal question (answering it finalizes the brief)."""
    return decision_id == QUESTIONS[-1].decision_id
