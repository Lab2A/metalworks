"""Brief assembler — folds the planner's 8 answers into a ResearchBrief.

Ported from clique-research-api's ``brief_assembler.py``. The mapping from
answers to structured Brief fields is deterministic; the one LLM touch is the
subreddit picker, which APPENDS suggested communities to the user's D5
selection.

Port changes:

- Takes a :class:`BriefState` (defined in ``store.py``) instead of loose
  ``workspace_id`` / ``original_prompt`` / ``answers`` kwargs.
- Runs :func:`pick_target_subreddits` to append subs, rather than receiving a
  pre-computed ``suggested_subreddits`` list.

The answers dict has shape::

    {"D1": {"option_indices": [0], "custom_text": "", "selected_labels": [...]}, ...}

Each entry is the user's turn answer plus a denormalized ``selected_labels``
list; the assembler reads those and bakes them into ResearchBrief fields.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from metalworks.contract import (
    ResearchBrief,
    SignalStrength,
    TargetSubreddit,
    TriageThresholds,
)
from metalworks.research.planner.subreddit_picker import pick_target_subreddits

if TYPE_CHECKING:  # pragma: no cover - typing only
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.planner.store import BriefState


def _selected_labels(answer: dict[str, Any]) -> list[Any]:
    raw: Any = answer.get("selected_labels") or []
    return cast("list[Any]", raw) if isinstance(raw, list) else []


def _pick_text(answer: dict[str, Any] | None, default: str = "") -> str:
    """Return custom_text if present, else the first selected label."""
    a: dict[str, Any] = answer if answer is not None else cast("dict[str, Any]", {})
    custom = str(a.get("custom_text", "") or "").strip()
    if custom:
        return custom
    labels = _selected_labels(a)
    return str(labels[0]) if labels else default


def _pick_list(answer: dict[str, Any] | None) -> list[str]:
    """Return custom_text split on commas, or the selected labels."""
    a: dict[str, Any] = answer if answer is not None else cast("dict[str, Any]", {})
    custom = str(a.get("custom_text", "") or "").strip()
    if custom:
        parts = [s.strip() for s in custom.split(",") if s.strip()]
        return parts or [custom]
    return [str(x) for x in _selected_labels(a)]


def assemble_brief(deps: ResearchDeps, *, state: BriefState) -> ResearchBrief:
    """Produce a finalized ResearchBrief from the planner's accumulated answers.

    Maps D1-D7 answers to Brief fields, then runs the subreddit picker to append
    LLM-suggested communities to the user's D5 selection.
    """
    answers = state.answers
    d1 = answers.get("D1", {})
    d2 = answers.get("D2", {})
    d3 = answers.get("D3", {})
    d4 = answers.get("D4", {})
    d5 = answers.get("D5", {})
    d6 = answers.get("D6", {})
    d7 = answers.get("D7", {})
    d8 = answers.get("D8", {})

    question = _pick_text(d1, default=state.prompt)
    decision_context = _pick_text(d2, default="Validating a v0 before commitment")
    success_criteria = _pick_list(d3)
    must_address = _pick_list(d4)

    # D5: if the user typed subs, parse them; else start empty and let the
    # picker fill in. Either way the picker appends below.
    d5_custom = str((d5 or {}).get("custom_text", "") or "").strip()
    if d5_custom:
        names = [
            n.strip().lstrip("r/").lstrip("/")
            for n in d5_custom.replace("\n", ",").split(",")
            if n.strip()
        ]
        target_subreddits = [
            TargetSubreddit(name=n, rationale="User-specified at D5.") for n in names
        ]
    else:
        target_subreddits = [
            TargetSubreddit(name=str(label), rationale="Selected at D5.")
            for label in _selected_labels(d5)
        ]

    web_research_directions = _pick_list(d7)

    # D6: time window — extract digits from the label.
    d6_label = _pick_text(d6, default="12 months")
    try:
        time_window_months = int("".join(c for c in d6_label if c.isdigit()) or 12)
    except ValueError:
        time_window_months = 12

    # D8: output template + confidence threshold from the label.
    d8_label = _pick_text(d8, default="Full report at actionable confidence").lower()
    output_template: Any = "brief_only" if "brief" in d8_label else "full"
    if "investment" in d8_label:
        confidence_threshold = SignalStrength.HIGH
    elif "directional" in d8_label:
        confidence_threshold = SignalStrength.LOW
    else:
        confidence_threshold = SignalStrength.MEDIUM

    relevance_rubric = (
        f"For the question '{question}', relevance means: a thread or comment that directly "
        f"speaks to "
        f"{', '.join(must_address) if must_address else 'the question above'}; expresses a want, "
        f"complaint, comparison, or experience by a real person; carries enough specificity to be "
        f"usable as evidence."
    )

    brief = ResearchBrief(
        brief_id=state.brief_id or str(uuid.uuid4()),
        workspace_id=state.workspace_id,
        version=1,
        supersedes=None,
        question=question,
        decision_context=decision_context,
        success_criteria=success_criteria
        or [
            "Produces a clear yes / no / refine recommendation",
            "Cites at least 8 distinct authors per cluster",
        ],
        must_address=must_address
        or [
            "What's the most-asked feature?",
            "What price point does the audience accept?",
        ],
        target_subreddits=target_subreddits,
        web_research_directions=web_research_directions or ["Competitive landscape and pricing"],
        excluded_sources=[],
        time_window_months=time_window_months,
        relevance_rubric=relevance_rubric,
        triage_thresholds=TriageThresholds(),
        output_template=output_template,
        confidence_threshold=confidence_threshold,
        finalized_at=datetime.now(UTC),
    )

    # Append LLM-suggested subs (never mutates the user's listed set above).
    effective_subs = pick_target_subreddits(deps, brief=brief)
    return brief.model_copy(update={"target_subreddits": effective_subs})
