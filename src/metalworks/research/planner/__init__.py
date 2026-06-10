"""Conversational planner subtree: 8 ordered questions -> ResearchBrief.

The planner walks the user through D1-D8 (:data:`QUESTIONS`), producing a
:class:`DecisionBrief` per turn via :func:`provide_content`. Once answered,
:func:`assemble_brief` folds the answers into a :class:`ResearchBrief`, running
:func:`pick_target_subreddits` to append LLM-suggested communities.

Brief-state persistence is out of scope for M2 — see ``store.py``. Only the
:class:`BriefState` dataclass (used by the assembler) and an in-memory holder
for tests survive here.
"""

from metalworks.research.planner.brief_assembler import assemble_brief
from metalworks.research.planner.decision_brief import DecisionBrief, Option
from metalworks.research.planner.llm_planner import provide_content
from metalworks.research.planner.question_bank import QUESTIONS, QuestionSpec
from metalworks.research.planner.store import BriefState, InMemoryBriefStates
from metalworks.research.planner.subreddit_picker import pick_target_subreddits

__all__ = [
    "QUESTIONS",
    "BriefState",
    "DecisionBrief",
    "InMemoryBriefStates",
    "Option",
    "QuestionSpec",
    "assemble_brief",
    "pick_target_subreddits",
    "provide_content",
]
