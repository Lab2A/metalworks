"""Ideation contract — the front of the validate loop.

``ideate`` has two entry points, both producing :class:`IdeaSketch`es:

- **idea-first** ("validate my idea"): one sketch carrying the sharpened
  hypothesis plus a ``ResearchBrief`` ready to run demand on. ``evidence`` is
  empty — it's a hypothesis, not yet grounded.
- **evidence-first** ("show me real pain, I'll pick"): an :class:`IdeationResult`
  of several sketches surfaced from an existing report's forks (its candidate
  wedges or top clusters), each grounded by an ``EvidenceRef`` — no guessing.

The sketch is the hand-off into demand + landscape + assess; nothing here decides
anything, it only frames the idea to test next.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from metalworks.contract.evidence import EvidenceRef
from metalworks.contract.research import ResearchBrief


def _sketch_id(*parts: str) -> str:
    """Content-addressed sketch id (``idea:<hash>``), mirroring the research id scheme."""
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"idea:{digest}"


class IdeaSketch(BaseModel):
    """One framed idea to test — a hypothesis plus where it came from.

    ``provenance`` records the entry point. For ``idea-first`` the ``brief`` is
    set (run demand on it) and ``evidence`` is empty; for ``evidence-first`` the
    ``evidence`` points at the report fork it was surfaced from and ``brief`` is
    ``None`` (the report already exists).
    """

    idea: str = Field(description="The idea in the user's / cluster's own words.")
    hypothesis: str = Field(description="The sharpened wedge/segment hypothesis, one sentence.")
    pain: str = Field(default="", description="The specific pain this addresses.")
    target_segment_hint: str = Field(default="", description="Who it's for, if discernible.")
    provenance: Literal["idea-first", "evidence-first"] = Field(
        description="Which entry point produced this sketch."
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef],
        description="Backing forks (evidence-first); empty for an idea-first hypothesis.",
    )
    brief: ResearchBrief | None = Field(
        default=None, description="The brief to run demand on (idea-first); None evidence-first."
    )
    partial: bool = Field(default=False)
    caveat: str | None = Field(default=None)

    @computed_field
    @property
    def sketch_id(self) -> str:
        """Stable content-addressed id (``idea:<hash of idea|provenance>``)."""
        return _sketch_id(self.idea, self.provenance)


class IdeationResult(BaseModel):
    """The evidence-first surface: several grounded sketches to pick from.

    Surfaced from an existing report's forks (candidate wedges, else top
    clusters). ``partial`` is true when the report had no forks to surface.
    """

    report_id: str | None = Field(default=None, description="The report these were surfaced from.")
    sketches: list[IdeaSketch] = Field(default_factory=list[IdeaSketch])
    partial: bool = Field(default=False)
    caveat: str | None = Field(default=None)
