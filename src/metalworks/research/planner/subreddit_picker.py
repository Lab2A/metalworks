"""LLM-driven subreddit picker.

Runs an LLM-backed
picker that APPENDS new subreddits to the user's D5 selection. Design
constraints (preserved from the source):

- Append only — never remove subs the user explicitly listed at D5. The user's
  intent is authoritative; the picker fills the blind spot.
- Cap the total candidate list at ``max_total`` (default 8). Beyond that we burn
  pull/triage budget on long-tail subs.
- Does NOT mutate the brief — briefs are immutable. The picker's output is local
  to one run; ``brief.target_subreddits`` stays as the user finalized it.
- On any LLM failure, fall back silently to the user's original list.

Port change: uses ``deps.chat.complete_structured`` (no ``model=`` /
``posthog_distinct_id=``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import ResearchBrief, TargetSubreddit

if TYPE_CHECKING:  # pragma: no cover - typing only
    from metalworks.research.deps import ResearchDeps

logger = logging.getLogger(__name__)

DEFAULT_MAX_SUBREDDITS = 8


class _Suggestion(BaseModel):
    name: str = Field(description="Subreddit name without the 'r/' prefix.")
    rationale: str = Field(
        description="One-line reason this sub is on-topic for the brief's question."
    )


class _PickerOutput(BaseModel):
    suggestions: list[_Suggestion] = Field(
        default_factory=list["_Suggestion"],
        description="Ranked list of NEW subreddits beyond what the user already listed.",
    )


_SYSTEM_PROMPT = (
    "You are a Reddit research scout. The user has written a research brief and listed some "
    "subreddits to pull from. Your job: suggest 3-6 ADDITIONAL subreddits where the conversation "
    "about this specific question is active.\n"
    "\n"
    "Hard rules:\n"
    "1. NEVER remove or contradict the user's listed subs. Only add new ones.\n"
    "2. Prefer subs where the EXACT topic is discussed, not adjacent topics. If the brief is "
    "about a sleep supplement, r/Insomnia is on-topic; r/HealthAnxiety is adjacent at best.\n"
    "3. Do not suggest banned, quarantined, or NSFW subs (joke subs, satire subs).\n"
    "4. Do not include the 'r/' prefix — just the name (e.g. 'Nootropics').\n"
    "5. Each rationale should be one sentence, <= 25 words, explaining why this sub will have "
    "on-topic threads.\n"
    "6. If you genuinely cannot think of more relevant subs, return fewer rather than padding "
    "with weak picks."
)


def _build_user_prompt(brief: ResearchBrief) -> str:
    listed = (
        ", ".join(f"r/{s.name}" for s in brief.target_subreddits)
        if brief.target_subreddits
        else "(none)"
    )
    must = "\n".join(f"- {q}" for q in brief.must_address) or "(none specified)"
    return (
        f"RESEARCH QUESTION:\n{brief.question}\n\n"
        f"DECISION CONTEXT:\n{brief.decision_context}\n\n"
        f"MUST-ADDRESS SUB-QUESTIONS:\n{must}\n\n"
        f"USER ALREADY LISTED: {listed}\n\n"
        "Suggest 3-6 NEW subreddits that complement the listed ones."
    )


def pick_target_subreddits(
    deps: ResearchDeps,
    *,
    brief: ResearchBrief,
    max_total: int = DEFAULT_MAX_SUBREDDITS,
) -> list[TargetSubreddit]:
    """Return the effective subreddit list for this run.

    Starts with the user's listed subs (order preserved), appends LLM-suggested
    NEW subs deduped case-insensitively by name, capped at ``max_total``. On LLM
    failure, returns the user's list unchanged. Never mutates ``brief``.
    """
    user_subs = list(brief.target_subreddits or [])
    user_names_ci = {s.name.lower() for s in user_subs}

    if len(user_subs) >= max_total:
        logger.info(
            "subreddit_picker: user already listed %d subs (cap=%d); skipping picker",
            len(user_subs),
            max_total,
        )
        return user_subs[:max_total]

    try:
        out = deps.chat.complete_structured(
            system=_SYSTEM_PROMPT,
            user=_build_user_prompt(brief),
            output_model=_PickerOutput,
            max_tokens=4096,
            temperature=0.3,
        )
        suggestions = out.suggestions
    except Exception as exc:
        # Expected, handled degradation (e.g. a fake model in tests, or any model error):
        # fall back to the user's list. This is NOT an error path, so log it at debug
        # without a stack trace — a traceback on a clean happy path reads as "broken".
        logger.debug(
            "subreddit_picker: LLM call failed (%s); falling back to user list of %d subs",
            exc,
            len(user_subs),
        )
        return user_subs

    added: list[TargetSubreddit] = []
    seen_ci = set(user_names_ci)
    for s in suggestions:
        clean = (s.name or "").strip().lstrip("r/").lstrip("/")
        if not clean:
            continue
        key = clean.lower()
        if key in seen_ci:
            continue
        seen_ci.add(key)
        added.append(TargetSubreddit(name=clean, rationale=(s.rationale or "").strip()))
        if len(user_subs) + len(added) >= max_total:
            break

    final = user_subs + added
    if added:
        logger.info(
            "subreddit_picker: appended %d new subs (user=%d -> total=%d)",
            len(added),
            len(user_subs),
            len(final),
        )
    else:
        logger.info("subreddit_picker: no new subs added (user already covered the space)")
    return final
