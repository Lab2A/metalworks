"""Design contract — the visual-design pillar output for one report.

The visual counterpart to positioning: positioning grounds the *words* (a wedge
from real demand quotes); a :class:`DesignSystem` grounds the *look*. But design
is taste, so grounding here is DIRECTIONAL, never cited per-decision — the
competitor landscape INFORMS the bet ("rivals skew serif → lean serif, or break
to sans"); it does not cite it. There are deliberately NO ``evidence_refs`` on a
design choice.

Two honesty signals instead:

- every :class:`DesignChoice` is labelled **SAFE** (category baseline a user
  expects) or **RISK** (a deliberate departure, where the brand gets its face);
- the whole system records its :data:`GroundingTier` — whether it was produced
  from a real competitor teardown (a renderer), web text, or only the model's own
  design knowledge — so a consumer is never misled about how grounded the look is.

The model authors the system under one of a few curated taste presets (recorded in
``taste``); metalworks records WHICH tier produced it and never pretends taste is
evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# How grounded the system actually is. Surfaced everywhere a consumer reads it
# (the result, `doctor`, the `/design` skill) so the tier is never hidden.
GroundingTier = Literal["renderer", "web", "model_knowledge"]

# The dimensions of a design system — service-defined, never invented by the model.
DesignDimension = Literal[
    "aesthetic",
    "decoration",
    "layout",
    "color",
    "typography",
    "spacing",
    "motion",
]

# SAFE = category baseline users expect; RISK = a deliberate departure.
DesignStance = Literal["safe", "risk"]


class LandscapeSignal(BaseModel):
    """A DIRECTIONAL read of the competitive landscape that informs the system.

    Not a cited claim — a pattern observed across rivals plus the move it implies
    ("all five skew rounded-blue SaaS → differentiate into editorial monochrome").
    """

    observation: str = Field(description="The pattern across competitors (directional, not cited).")
    implication: str = Field(description="The design move it suggests — lean in, or break.")
    competitors: list[str] = Field(
        default_factory=list[str], description="Competitor names this signal reads from."
    )


class DesignChoice(BaseModel):
    """One dimension's decision, labelled SAFE (baseline) or RISK (departure)."""

    dimension: DesignDimension = Field(description="The fixed design dimension.")
    decision: str = Field(
        description="The choice, concretely (e.g. 'Fraunces display + Geist body; ink #1A1A1A')."
    )
    stance: DesignStance = Field(
        description="safe = category baseline; risk = a deliberate departure with a payoff."
    )
    rationale: str = Field(
        description="Why, one line. For a RISK: what it gains and what it costs."
    )


class DesignSystem(BaseModel):
    """The grounded-but-directional design system for one report (the `/design` output).

    FKs to one report via ``report_id``. ``grounding_tier`` records how the
    landscape was actually read (renderer teardown > web text > model knowledge),
    so the look's groundedness is never overstated. Choices carry a SAFE/RISK
    stance; ``landscape_signals`` are directional reads, not per-decision evidence.
    """

    report_id: str
    brand_name: str = Field(description="The brand the system was designed for.")
    memorable_thing: str = Field(
        description="The one thing someone should remember on first contact — the north star."
    )
    grounding_tier: GroundingTier = Field(
        description="How grounded: a real competitor teardown, web text, or model knowledge."
    )
    aesthetic: str = Field(
        description="The aesthetic direction in one line (e.g. 'editorial monochrome, dark-first')."
    )
    taste: str = Field(
        default="editorial",
        description="The taste preset the system was authored under (e.g. 'editorial', "
        "'brutalist', 'warm-minimal', 'technical') — drives the director voice + preview chrome.",
    )
    choices: list[DesignChoice] = Field(
        default_factory=list[DesignChoice],
        description="One per design dimension, each SAFE/RISK-labelled.",
    )
    landscape_signals: list[LandscapeSignal] = Field(
        default_factory=list[LandscapeSignal],
        description="Directional reads of the competition that informed the system (not cited).",
    )
    design_md: str = Field(
        default="", description="The rendered DESIGN.md — the per-project source of truth."
    )
    generated_at: datetime
    partial: bool = Field(default=False)
    caveat: str | None = Field(default=None)


# ── Design review — the audit of a RENDERED page against the system ────────────

ReviewSeverity = Literal["fail", "warn", "ok"]
ReviewCategory = Literal["fonts", "headings", "palette", "system_match", "slop"]


class StyleFinding(BaseModel):
    """One deterministic finding from auditing a rendered page's computed styles."""

    severity: ReviewSeverity = Field(description="fail (hard) / warn (soft) / ok (positive note).")
    category: ReviewCategory
    detail: str = Field(description="What was observed and why it's flagged, one line.")


class DesignReview(BaseModel):
    """A computed-style audit of a RENDERED page — what's actually on screen.

    Deterministic: the findings are pure functions of the page's computed styles
    (fonts, heading scale, colors) plus, when supplied, the brand's
    :class:`DesignSystem`. The model writes nothing here. Requires a script-capable
    renderer (Playwright) — a screenshot-only backend can't read computed styles.
    """

    url: str = Field(description="The page that was audited.")
    fonts: list[str] = Field(
        default_factory=list[str], description="Distinct font families actually rendered."
    )
    headings: list[str] = Field(
        default_factory=list[str], description="Rendered h1/h2/h3 font sizes, in document order."
    )
    ink: str = Field(default="", description="The rendered body text color.")
    background: str = Field(default="", description="The rendered body background color.")
    findings: list[StyleFinding] = Field(default_factory=list[StyleFinding])
    score: int = Field(default=10, ge=0, le=10, description="10 minus penalties for findings.")
    passed: bool = Field(default=True, description="True when there are no fail-severity findings.")
    against_system: bool = Field(
        default=False, description="Whether it was graded against a DesignSystem (not just rules)."
    )
    generated_at: datetime
    partial: bool = Field(default=False)
    caveat: str | None = Field(default=None)
