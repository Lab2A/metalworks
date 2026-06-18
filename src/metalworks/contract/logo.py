"""Logo contract — the brand logo options offered for one report.

Unlike copy, a logo is *authored*, not grounded against quotes: the model draws
the SVG directly under a fixed house design system. Geometry is the one artifact
metalworks lets the LLM draw, because a logo is a designed object, not a claim.
The honesty signal is the usual ``partial`` / ``caveat`` pair (an angle that
returned no valid SVG is dropped, never faked).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LogoOption(BaseModel):
    """One logo option: a self-contained SVG plus how it was arrived at."""

    angle: str = Field(description="The design angle that produced it, e.g. 'logotype'.")
    concept: str = Field(description="One line: the idea behind the mark.")
    svg: str = Field(description="A self-contained SVG lockup (mark + wordmark).")


class LogoSet(BaseModel):
    """The options offered for one brand, for a human to choose from."""

    report_id: str = Field(description="The DemandReport this set was generated for.")
    brand_name: str = Field(description="The wordmark name the logos were drawn for.")
    options: list[LogoOption] = Field(
        default_factory=list[LogoOption], description="Diverse options, one per design angle."
    )
    partial: bool = Field(
        default=False, description="True when fewer options than requested were produced."
    )
    caveat: str | None = Field(
        default=None, description="Why the set is partial / which angles were dropped."
    )
