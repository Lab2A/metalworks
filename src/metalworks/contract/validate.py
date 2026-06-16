"""Validation-loop contract — the discovery loop's result + decision log.

Named ``validate`` (NOT ``discover``) on purpose: ``metalworks discovery`` already
ships and means Reddit reply-opportunity discovery, a different subsystem.

``validate`` runs the loop — ideate → demand → landscape → assess — and either
exits on GO, terminates on NO-GO, or loops on PIVOT toward the under-served fork,
accumulating a :class:`DecisionLogEntry` per round so a killed fork is never
re-proposed. ``outcome`` records why it stopped.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from metalworks.contract.assess import Assessment, Decision


class DecisionLogEntry(BaseModel):
    """One round of the loop — the idea tried, the verdict, and what it ruled out."""

    iteration: int = Field(description="1-based round number.")
    idea: str = Field(description="The idea this round tested.")
    decision: Decision = Field(description="The verdict for this round.")
    ruled_out: list[str] = Field(
        default_factory=list[str],
        description="Forks/ideas this round eliminated — the anti-repeat memory.",
    )
    why: str = Field(default="", description="One-line reasoning for the verdict.")


class ValidationResult(BaseModel):
    """The outcome of a validate loop.

    ``outcome``: ``go`` (a round passed), ``no_go`` (a round was killed), or
    ``exhausted`` (the loop circled without a new fork, or hit the iteration cap).
    ``final_assessment`` is the last round's verdict.
    """

    outcome: Literal["go", "no_go", "exhausted"] = Field(description="Why the loop stopped.")
    final_assessment: Assessment | None = Field(
        default=None, description="The last round's GO/PIVOT/NO-GO verdict."
    )
    decision_log: list[DecisionLogEntry] = Field(
        default_factory=list[DecisionLogEntry], description="One entry per round."
    )
    iterations: int = Field(default=0, description="Rounds run.")
