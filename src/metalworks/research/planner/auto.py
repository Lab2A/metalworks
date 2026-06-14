"""Auto-brief builders — turn a prompt or question into a ``ResearchBrief``.

``plan_brief`` walks the full D1-D8 question bank (LLM-heavy); ``brief_from_question``
is the lightweight one-liner path. Both live here so the brief-building shared by
the MCP tools, the ``Metalworks`` facade, and the CLI sits in exactly one place.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from metalworks.research.planner.brief_assembler import assemble_brief
from metalworks.research.planner.llm_planner import provide_content
from metalworks.research.planner.question_bank import QUESTIONS
from metalworks.research.planner.store import BriefState
from metalworks.research.planner.subreddit_picker import pick_target_subreddits

if TYPE_CHECKING:
    from collections.abc import Sequence

    from metalworks.contract import ResearchBrief
    from metalworks.research.deps import ResearchDeps


def plan_brief(deps: ResearchDeps, prompt: str) -> ResearchBrief:
    """Walk the D1-D8 planner choosing the recommended option at each decision.

    Returns an assembled :class:`~metalworks.contract.ResearchBrief` for
    ``prompt`` (the planner runs LLM calls, so ``deps`` needs a chat model,
    embeddings, a corpus, and a reader). This is the non-interactive path; an
    interactive caller can present each ``provide_content`` result instead.
    """
    state = BriefState(brief_id=str(uuid.uuid4()), prompt=prompt)
    for spec in QUESTIONS:
        brief = provide_content(
            deps, question_spec=spec, prompt=prompt, prior_answers=dict(state.answers)
        )
        recommended = next(
            (i for i, o in enumerate(brief.options) if o.is_recommended),
            0 if brief.options else -1,
        )
        labels = [brief.options[recommended].label] if recommended >= 0 else []
        state.answers[spec.decision_id] = {
            "option_indices": [recommended] if recommended >= 0 else [],
            "custom_text": "",
            "selected_labels": labels,
        }
    return assemble_brief(deps, state=state)


def brief_from_question(
    deps: ResearchDeps,
    question: str,
    *,
    subreddits: Sequence[str] | None = None,
    time_window_months: int = 12,
) -> ResearchBrief:
    """A minimal ``ResearchBrief`` straight from a ``question`` — the quick path
    behind ``Metalworks.research(question)`` and the CLI ``research run --question``.

    When ``subreddits`` is omitted, the planner picks the communities to cover
    (:func:`pick_target_subreddits`); otherwise the caller's list is used verbatim.
    For the full D1-D8 interview, use :func:`plan_brief` instead.
    """
    from metalworks.contract import ResearchBrief, TargetSubreddit

    targets = [TargetSubreddit(name=s, rationale="caller-specified") for s in (subreddits or [])]
    brief = ResearchBrief(
        brief_id=str(uuid.uuid4()),
        question=question,
        decision_context="Assess the Reddit demand signal behind this question.",
        success_criteria=["Surface the top unmet needs and the demand signal."],
        must_address=[],
        target_subreddits=targets,
        web_research_directions=[],
        relevance_rubric=f"Posts and comments relevant to: {question}",
        time_window_months=time_window_months,
    )
    if not targets:
        brief = brief.model_copy(
            update={"target_subreddits": pick_target_subreddits(deps, brief=brief)}
        )
    return brief
