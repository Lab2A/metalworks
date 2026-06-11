"""Planner brief-in-progress state.

Brief-state persistence, intentionally minimal.

Port change / scope decision: the source's ``InMemoryStore`` and
``SupabaseStore`` (full CRUD + workspace-scoped Supabase persistence) are
DROPPED. Brief-state persistence is OUT OF SCOPE for M2 — the real persistence
will bind to ``BriefRepo`` later. What survives here:

- :class:`BriefState` — the small dataclass the brief assembler reads from and
  writes the finalized brief back onto.
- :class:`InMemoryBriefStates` — a thin dict-backed holder used by tests and
  throwaway runs. NOT a workspace-scoped store; no Supabase, no migrations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover - typing only
    from metalworks.contract import ResearchBrief


@dataclass
class BriefState:
    """In-memory representation of a brief-in-progress.

    ``answers`` maps decision_id ("D1".."D8") to the user's denormalized turn
    answer (``{"option_indices": [...], "custom_text": "...",
    "selected_labels": [...]}``) — the shape the brief assembler reads.
    """

    brief_id: str
    workspace_id: str = "local"
    prompt: str = ""
    answers: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    current_decision_id: str | None = None
    status: Literal["planning", "finalized"] = "planning"
    finalized_brief: ResearchBrief | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finalized_at: datetime | None = None


class InMemoryBriefStates:
    """Dict-backed holder for :class:`BriefState`, for tests and local runs.

    Deliberately minimal: this is NOT the workspace-scoped persistence layer.
    Real persistence binds to ``BriefRepo`` in a later milestone.
    """

    def __init__(self) -> None:
        self._states: dict[str, BriefState] = {}

    def create(self, *, prompt: str, workspace_id: str = "local") -> BriefState:
        state = BriefState(
            brief_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            prompt=prompt,
        )
        self._states[state.brief_id] = state
        return state

    def get(self, brief_id: str) -> BriefState | None:
        return self._states.get(brief_id)

    def save(self, state: BriefState) -> None:
        self._states[state.brief_id] = state

    def list(self) -> list[BriefState]:
        return sorted(self._states.values(), key=lambda s: s.created_at, reverse=True)
