"""Content provider for DecisionBriefs.

:func:`provide_content`
produces the next :class:`DecisionBrief` for a planner turn.

We ALWAYS call ``deps.chat.complete_structured``. A failure (model error, schema
validation, empty/truncated response) is a HARD error — :class:`PlannerError` —
not a silent canned substitute. An auto-selected canned default sends the whole
run off-topic (the classic failure was a supplement brief generated for an
auto-repair idea), so a planner that can't actually plan must say so loudly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from metalworks.errors import PlannerError
from metalworks.research.planner.decision_brief import DecisionBrief

if TYPE_CHECKING:  # pragma: no cover - typing only
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.planner.question_bank import QuestionSpec

logger = logging.getLogger(__name__)

# A DecisionBrief is small (2-4 options), but a reasoning model burns hidden
# thinking tokens before emitting the JSON; size the structured call generously
# so the planner doesn't truncate (the 1024 default left ~0 room for the JSON on
# DeepSeek-v4-flash / Gemini 3.x and silently failed every turn).
_PLANNER_MAX_TOKENS = 8192


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

    Calls ``deps.chat.complete_structured``. A failure is raised as
    :class:`PlannerError`, never swallowed into a canned brief: an auto-selected
    default decision silently steers the entire run off-topic.
    """
    try:
        return deps.chat.complete_structured(
            system=_SYSTEM_PROMPT,
            user=_build_user_prompt(question_spec, prompt, prior_answers),
            output_model=DecisionBrief,
            max_tokens=_PLANNER_MAX_TOKENS,
        )
    except Exception as exc:
        logger.warning("planner content failed for %s: %s", question_spec.decision_id, exc)
        raise PlannerError(question_spec.decision_id, str(exc)) from exc
