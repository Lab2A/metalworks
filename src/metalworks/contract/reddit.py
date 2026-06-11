"""Reddit-side data contract: posts, comments, subreddit intel, inbox,
opportunities, compliance verdicts, and the discovery-context seam.

Compliance models formalize the deterministic gate's output; the entity
models formalize the dict shapes that flow through the discovery/inbox
services.

`DiscoveryContext` (incl. `PersonaSet`) is a PUBLIC contract: it is the seam
a caller (for example, a memory system) renders its knowledge into. Personas
carry a `background` field that MUST be authentic; fabricated
personas/backstories are prohibited by the usage policy, and tooling that
fabricates them is deliberately not part of metalworks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ──────────────────────────────────────────────────────────────────────────
# Compliance gate output (ported from the deterministic judge)
# ──────────────────────────────────────────────────────────────────────────


class ComplianceVerdict(BaseModel):
    """Verdict from the compliance gate (deterministic heuristic or LLM judge)."""

    model_config = ConfigDict(populate_by_name=True)

    pass_: bool = Field(alias="pass", description="True if the reply is OK to post.")
    violations: list[str] = Field(
        default_factory=list, description="Specific issues — empty when pass=True."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the verdict.")


class LintViolation(BaseModel):
    """Structured lint output for post drafts.

    Free-form strings would rot into stringly-typed UI within a quarter;
    this enum-backed shape forces every new rule to declare its severity
    and code up front.
    """

    code: str = Field(
        description="Stable identifier for the rule that fired (e.g., 'title_too_short')."
    )
    severity: Literal["error", "warn"] = Field(
        description="error blocks submit; warn surfaces but allows it."
    )
    message: str = Field(description="Human-readable explanation suitable for inline UI.")
    span: tuple[int, int] | None = Field(
        default=None,
        description="Optional [start,end] char offsets in the offending field.",
    )
    field: Literal["title", "body", "flair", "draft"] = Field(
        default="draft", description="Which field the violation applies to."
    )


class PostLintVerdict(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pass_: bool = Field(alias="pass", description="True when no `error`-severity violations fired.")
    violations: list[LintViolation] = Field(default_factory=list[LintViolation])


# ──────────────────────────────────────────────────────────────────────────
# Reddit entities
# ──────────────────────────────────────────────────────────────────────────


class RedditPost(BaseModel):
    """A Reddit submission as surfaced by search or the historical corpus."""

    post_id: str = Field(description="Reddit base36 id without the 't3_' prefix.")
    subreddit: str = Field(description="Subreddit name without 'r/' prefix.")
    title: str
    selftext: str = Field(default="", description="Body text; empty for link posts.")
    url: str = Field(description="Full permalink to the post.")
    author: str | None = Field(
        default=None,
        description="Username when sourced live; None when the source pseudonymizes.",
    )
    score: int = 0
    num_comments: int = 0
    created_utc: datetime | None = None
    flair: str | None = None


class RedditComment(BaseModel):
    """A Reddit comment, from the live API or the historical corpus."""

    comment_id: str = Field(description="Reddit base36 id without the 't1_' prefix.")
    post_id: str = Field(description="Parent submission id.")
    subreddit: str
    body: str
    permalink: str
    author_hash: str = Field(
        description="Salted pseudonymous author id — pseudonymization, not anonymization."
    )
    score: int = 0
    created_utc: datetime | None = None
    parent_id: str | None = Field(
        default=None, description="Parent comment id for nested replies; None for top-level."
    )


class SubredditIntel(BaseModel):
    """Community context: what a brand needs to know before participating."""

    name: str = Field(description="Subreddit name without 'r/' prefix.")
    title: str | None = None
    description: str | None = None
    subscribers: int | None = None
    rules: list[str] = Field(default_factory=list)
    top_post_titles: list[str] = Field(
        default_factory=list, description="Recent top posts, for tone calibration."
    )
    fetched_at: datetime | None = None


class InboxItem(BaseModel):
    """One classified item from a Reddit account's inbox."""

    message_id: str
    kind: Literal["comment_reply", "post_reply", "dm", "mention", "mod"] = Field(
        description="Classification from the inbox poller."
    )
    author: str | None = None
    subject: str | None = None
    body: str
    permalink: str | None = None
    created_utc: datetime | None = None
    read: bool = False


class Opportunity(BaseModel):
    """A discovered thread worth engaging, with its generated draft reply.

    The discovery pipeline emits these; nothing is ever posted from an
    Opportunity without an explicit, gated, audited posting action.
    """

    opportunity_id: str
    post: RedditPost
    draft_reply: str = Field(description="Generated draft — a starting point, not a send.")
    account_type: str | None = Field(
        default=None, description="Which persona the draft was written for."
    )
    relevance_reason: str | None = Field(
        default=None, description="Why the filter kept this thread."
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    risks: list[str] = Field(default_factory=list)
    compliance: ComplianceVerdict | None = None
    status: Literal["new", "approved", "cancelled", "posted"] = "new"
    discovered_at: datetime | None = None


# ──────────────────────────────────────────────────────────────────────────
# Discovery context — the public seam callers render knowledge into
# ──────────────────────────────────────────────────────────────────────────


class Persona(BaseModel):
    """Voice profile for one account type used in reply generation.

    `background` MUST be authentic — a true description of who is posting
    (e.g. "founder of a sleep-tech startup, former RN"). Fabricated personas
    and invented account histories are prohibited by the usage policy.
    """

    example_posts: list[str] = Field(
        default_factory=list, description="Real writing samples that define the voice."
    )
    voice_rubric: str | None = Field(
        default=None, description="Distilled description of the voice (tone, quirks, register)."
    )
    background: str | None = Field(
        default=None,
        description="AUTHENTIC background of the human/brand behind the account. "
        "Never fabricated. See USAGE_POLICY.",
    )


class PersonaSet(BaseModel):
    """Personas keyed by account_type (e.g. 'founder', 'team', 'brand')."""

    personas: dict[str, Persona] = Field(default_factory=dict)

    def get(self, account_type: str) -> Persona:
        return self.personas.get(account_type, Persona())


class DiscoveryContext(BaseModel):
    """Everything a caller wants the discovery loop to know.

    This is the contract a memory system (or a human-maintained config file)
    renders into. Plain lists by design: the discovery loop has no opinion
    about where this knowledge comes from.
    """

    voice_guidelines: list[str] = Field(default_factory=list)
    winning_examples: list[str] = Field(
        default_factory=list, description="Replies that performed well — style anchors."
    )
    pinned_notes: list[str] = Field(
        default_factory=list, description="Standing instructions from the caller."
    )
    avoid: list[str] = Field(
        default_factory=list, description="Topics, claims, or phrasings to never use."
    )
    personas: PersonaSet = Field(default_factory=PersonaSet)
