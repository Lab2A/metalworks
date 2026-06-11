"""plan_brief — walk the D1-D8 question bank picking the recommended answer.

Shared by the MCP ``research_plan_brief`` tool and the ``Metalworks.plan()``
facade method so the auto-planner walk lives in exactly one place.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from metalworks.research.planner.brief_assembler import assemble_brief
from metalworks.research.planner.llm_planner import provide_content
from metalworks.research.planner.question_bank import QUESTIONS
from metalworks.research.planner.store import BriefState

if TYPE_CHECKING:
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
