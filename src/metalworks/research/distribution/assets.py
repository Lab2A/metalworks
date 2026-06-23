"""D4 — channel-shaped distribution assets.

The drafting face of the Distribution pillar: turn the selected
:class:`~metalworks.contract.distribution.Channel`\\ s (from D2) into
channel-SHAPED, drafting-only :class:`~metalworks.contract.distribution.ChannelAsset`\\ s.
A launch asset for a real surface is not a flat string — a Product Hunt post is a
tagline + an authentic maker comment + gallery captions; a Show HN is a plain
title + a technical first comment; an X thread is N numbered tweets; a LinkedIn
post is carousel slides. Each channel's ``surface_type`` selects the shape
(:class:`~metalworks.contract.distribution.AssetPart` roles), and ONE
``complete_structured`` call drafts that channel's parts.

The grounding correction (the key D4 move): RELAXED, not removed. The library's
no-cite-no-claim gate still binds the *demand / factual* claims an asset makes —
that people want this, that they resent the incumbent — via the salvaged
``verbatim_match`` path, emitting a :class:`ClaimCitation` per claim that resolves
BOTH against a real report quote AND verbatim in the asset body; unresolved ones
are DROPPED. But the persuasive hooks, taglines and the per-channel ``offer``
(the CTA) are FREE — they are craft, not factual claims. Forcing a Reddit quote
behind every persuasive sentence was the generate-site (#67) category error;
D4 doesn't repeat it.

Platform invariants are enforced deterministically at assembly, never left to the
model: an "upvote us" / "please upvote" ask is stripped (Product Hunt + HN ban
it, and it reads as begging); the hook is native-first (no bare link in the
opening span); the voice is founder, not brand. The model is told all this, and a
:func:`_strip_upvote_ask` guard backstops it.

``build_channel_assets(deps, report, channels, positioning=None)`` is the
reusable core the four surfaces call. DRAFTING ONLY — nothing here posts.
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import (
    AssetPart,
    Channel,
    ChannelAsset,
    ChannelSurfaceType,
    ClaimCitation,
    DemandReport,
    EvidenceRef,
    ResolvedCitation,
)
from metalworks.errors import StructuredOutputError
from metalworks.research.grounding import verbatim_match

if TYPE_CHECKING:
    from metalworks.contract import PositioningBrief
    from metalworks.research.deps import ResearchDeps


# How many tweets / carousel slides / gallery captions to ask the model for.
_THREAD_LEN = 4
_CAROUSEL_LEN = 4
_GALLERY_CAPTIONS = 2

# An "upvote ask" is a platform-fatal tell on PH + HN and reads as begging
# everywhere — never ship one. Matches "upvote", "up-vote", "up vote".
_UPVOTE_RE = re.compile(r"\bup[\s-]?vote", re.IGNORECASE)
# A whole sentence/line that asks for upvotes — stripped wholesale from a body.
_UPVOTE_SENTENCE_RE = re.compile(r"[^.!?\n]*\bup[\s-]?vote[^.!?\n]*[.!?]?", re.IGNORECASE)


# ── Per-surface shape briefs ─────────────────────────────────────────────────


class _ShapeSpec(BaseModel):
    """The part roles to draft for one surface, in order, + how many of each."""

    roles: list[str]
    counts: dict[str, int] = Field(default_factory=dict[str, int])
    brief: str


# Each surface_type → its channel-native part shape + an operator-grounded brief.
_SHAPES: dict[ChannelSurfaceType, _ShapeSpec] = {
    ChannelSurfaceType.LAUNCH_PLATFORM: _ShapeSpec(
        roles=["tagline", "maker_comment", "gallery_caption"],
        counts={"gallery_caption": _GALLERY_CAPTIONS},
        brief=(
            "A Product Hunt-style launch: ONE punchy benefit-led tagline (no hype words), an "
            "AUTHENTIC first-person maker_comment (the maker comment out-converts a salesy one by "
            "+166% — tell the honest origin story, why you built it, what it does, in your own "
            "voice), and short gallery_caption lines for screenshots. Founder voice, not brand. "
            "Never ask for upvotes."
        ),
    ),
    ChannelSurfaceType.COMMUNITY: _ShapeSpec(
        roles=["title", "first_comment"],
        brief=(
            "A community (Reddit/forum) showcase: a plain, modest title and a story-led "
            "first_comment in the maker's own voice — what you built and why, NOT a link drop. "
            "Disclose you made it. No marketing voice, no upvote ask."
        ),
    ),
    ChannelSurfaceType.SOCIAL: _ShapeSpec(
        roles=["tweet"],
        counts={"tweet": _THREAD_LEN},
        brief=(
            "An X/Twitter launch thread: a strong first tweet HOOK (no link in the hook — the "
            "link goes in a reply), then follow-on tweets that build the story. Plain-spoken, no "
            "thread-bro filler, no 'a thread 🧵' cliché. Each tweet stands on its own."
        ),
    ),
    ChannelSurfaceType.EARNED_MEDIA: _ShapeSpec(
        roles=["title", "first_comment"],
        brief=(
            "A Show HN-style technical post: a plain 'Show HN:'-style title with NO superlatives, "
            "and a technical, no-marketing first_comment that respects a skeptical engineer "
            "audience — what it does, how it works, what's rough. Never ask for upvotes."
        ),
    ),
    ChannelSurfaceType.DATA_ASSET: _ShapeSpec(
        roles=["title", "body"],
        brief=(
            "A data-report / 'State of X' drop: a methodology-first title and a body that leads "
            "with the finding and the method. Credibility is the rigor, not hype."
        ),
    ),
}

# LinkedIn-style carousel — surfaces a B2B PLG / sales channel routes to. Keyed
# off the channel name (LinkedIn isn't its own surface_type) so it can override.
_CAROUSEL_SHAPE = _ShapeSpec(
    roles=["carousel_slide"],
    counts={"carousel_slide": _CAROUSEL_LEN},
    brief=(
        "A LinkedIn carousel: each carousel_slide is one tight, lessons-led card (a single idea "
        "per slide), founder voice, native-first — the link goes in the comments, never the first "
        "slide. No hype, no 'I'm humbled to announce'."
    ),
)

# The default shape for any surface_type without a bespoke one.
_DEFAULT_SHAPE = _ShapeSpec(
    roles=["title", "body"],
    brief=(
        "A plain channel post: a clear title and a benefit-led body in the maker's own voice. "
        "Native-first (no bare link in the opener), founder voice, no hype words."
    ),
)


def _shape_for(channel: Channel) -> _ShapeSpec:
    """Pick the channel-native part shape for a channel.

    LinkedIn routes to a carousel regardless of its surface_type; otherwise the
    surface_type selects the shape, falling back to title + body.
    """
    if "linkedin" in channel.name.lower():
        return _CAROUSEL_SHAPE
    return _SHAPES.get(channel.surface_type, _DEFAULT_SHAPE)


# ── LLM I/O shapes (private) ─────────────────────────────────────────────────


class _ClaimDraft(BaseModel):
    """One DEMAND/factual claim the LLM makes, with the quote it says supports it."""

    text: str = Field(
        description="The exact demand/factual claim sentence AS IT APPEARS verbatim in some part."
    )
    supporting_quote: str = Field(
        description="The verbatim Reddit quote that backs this claim. Copy it exactly."
    )


class _DraftedPart(BaseModel):
    """One channel-shaped span the LLM drafted."""

    role: str = Field(description="One of the requested roles for this surface.")
    text: str = Field(description="The copy for this span.")


class _AssetDraft(BaseModel):
    """The LLM-authored, channel-shaped draft for ONE channel.

    ``parts`` are the channel-native spans (e.g. PH: tagline + maker_comment +
    captions). ``offer`` is the per-channel CTA — persuasive, FREE (not grounded).
    ``claims`` lists ONLY the demand/factual claims that must ground; persuasive
    hooks and the offer are deliberately NOT claims.
    """

    parts: list[_DraftedPart] = Field(
        default_factory=list[_DraftedPart],
        description="The channel-shaped spans, in the requested roles.",
    )
    offer: str = Field(
        default="",
        description="The per-channel CTA / conversion ask. Persuasive and free — but NEVER an "
        "'upvote us' ask.",
    )
    claims: list[_ClaimDraft] = Field(
        default_factory=list[_ClaimDraft],
        description="ONLY the demand/factual claims (people want this / resent X), each with its "
        "verbatim supporting_quote. Persuasive hooks and the offer are NOT claims — omit them.",
    )


# ── Grounding helpers (relaxed: demand claims only) ──────────────────────────


def _all_quotes(report: DemandReport) -> list[ResolvedCitation]:
    """Every ResolvedCitation across all clusters (the verbatim corpus to ground on)."""
    return [q for c in report.ranked_clusters for q in c.quotes]


def _ground_claims(
    report: DemandReport, body: str, claims: list[_ClaimDraft]
) -> list[ClaimCitation]:
    """A ClaimCitation per demand claim that resolves BOTH ways; drop the rest.

    Mirrors the salvaged launch grounding: a claim survives only when (a) its
    supporting quote is a literal slice of a real report quote (``verbatim_match``)
    whose id is in ``report.evidence`` AND (b) its claim text is present verbatim
    in the concatenated ``body``. The span then satisfies
    ``body[start:end] == claim_text``. Only DEMAND/factual claims are passed here;
    persuasive hooks and the offer are never grounded.
    """
    quotes = _all_quotes(report)
    evidence_ids = {e.id for e in report.evidence}
    citations: list[ClaimCitation] = []
    for claim in claims:
        quote = verbatim_match(claim.supporting_quote, quotes)
        if quote is None or quote.id not in evidence_ids:
            continue  # no-cite-no-claim: support doesn't resolve to real evidence
        claim_text = claim.text.strip()
        start = body.find(claim_text)
        if not claim_text or start == -1:
            continue  # claim text not present verbatim in the body
        end = start + len(claim_text)
        citations.append(
            ClaimCitation(
                claim_text=claim_text,
                span_start=start,
                span_end=end,
                evidence_ref=EvidenceRef(evidence_id=quote.id, kind="quote"),
            )
        )
    return citations


# ── Platform-invariant guards (deterministic) ────────────────────────────────


def _strip_upvote_ask(text: str) -> str:
    """Strip any 'please upvote'/'upvote us' ask from a span. Deterministic guard.

    An upvote ask is platform-fatal on Product Hunt + Hacker News (both auto-detect
    and penalize vote solicitation) and reads as begging everywhere. The model is
    told never to write one; this backstops it. Removes the whole offending
    sentence/line, then collapses the whitespace it leaves behind.
    """
    if not _UPVOTE_RE.search(text):
        return text
    cleaned = _UPVOTE_SENTENCE_RE.sub("", text)
    # Collapse the gaps the removed sentence left, preserving paragraph breaks.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _clean_parts(drafted: list[_DraftedPart], allowed_roles: list[str]) -> list[AssetPart]:
    """Normalize the LLM's drafted spans into AssetParts under the platform invariants.

    Drops empty spans and ones whose role isn't in the surface's shape, strips any
    upvote ask from every span (and drops a span emptied by that strip), and
    preserves the model's ordering.
    """
    allowed = set(allowed_roles)
    parts: list[AssetPart] = []
    for d in drafted:
        role = d.role.strip()
        if role not in allowed:
            continue
        text = _strip_upvote_ask(d.text.strip())
        if not text:
            continue
        parts.append(AssetPart(role=role, text=text))
    return parts


# ── LLM pass (private) ───────────────────────────────────────────────────────


def _shape_instructions(shape: _ShapeSpec) -> str:
    """Human-readable 'draft these roles, this many of each' line for the prompt."""
    bits: list[str] = []
    for role in shape.roles:
        n = shape.counts.get(role, 1)
        bits.append(f"{n}x {role}" if n > 1 else role)
    return ", ".join(bits)


def _draft_channel(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None,
    channel: Channel,
    shape: _ShapeSpec,
) -> _AssetDraft:
    """One ``complete_structured`` call → the channel-shaped draft for one channel."""
    quotes = "\n".join(f'- "{q.text}"' for q in _all_quotes(report)[:8])
    claims_ctx = "\n".join(f"- {c.claim}" for c in report.ranked_clusters[:5])
    statement = positioning.positioning_statement if positioning is not None else ""
    pos_ctx = (
        f"\nPositioning statement to stay consistent with:\n{statement}\n" if statement else ""
    )

    system = (
        "You draft ONE channel-native distribution asset from ALREADY-VERIFIED demand evidence. "
        "You are DRAFTING ONLY — this is never posted automatically. Write in a plain FOUNDER "
        "voice (first person, not brand-speak), with NO hype words and NO AI tells (no "
        "'game-changer', 'revolutionary', 'I'm humbled to announce', 'in today's world', em-dash "
        "filler). Be NATIVE-FIRST: never put a bare link in the opening hook — a link belongs in "
        "a reply / the comments. NEVER ask anyone to upvote — it is platform-fatal and reads as "
        "begging.\n"
        "Grounding rule (READ CAREFULLY): only DEMAND / FACTUAL claims must be grounded — that "
        "people want this, that they resent an incumbent, any number or sentiment. For each such "
        "claim, write it verbatim in a part AND list it in `claims` with a `supporting_quote` "
        "copied EXACTLY from the evidence. Your persuasive HOOKS, taglines and the `offer` (CTA) "
        "are FREE craft — do NOT force a quote behind them and do NOT list them as claims. Do not "
        "invent demand the quotes don't support."
    )
    user = (
        f"Channel: {channel.name} (surface: {channel.surface_type}, funnel: {channel.funnel_stage})"
        f"\n{shape.brief}\n"
        f"Draft these parts, in order: {_shape_instructions(shape)}.\n{pos_ctx}\n"
        f"Top demand claims (already verified):\n{claims_ctx}\n\n"
        f"Verbatim quotes you may cite (copy supporting_quote from these EXACTLY):\n{quotes}\n\n"
        "Return `parts` (each with a `role` from the requested list and its `text`), an `offer` "
        "(the per-channel CTA — persuasive, free), and `claims` (ONLY demand/factual claims, each "
        "appearing verbatim in some part, each with a verbatim supporting_quote)."
    )
    return deps.chat.complete_structured(
        system=system,
        user=user,
        output_model=_AssetDraft,
        # A full asset (parts + offer + claims JSON) is large, and Gemini 3.x
        # burns ~1-2k hidden thinking tokens first — size generously or the JSON
        # truncates mid-string.
        max_tokens=4096,
        temperature=0.4,
    )


def _build_one_asset(
    deps: ResearchDeps,
    report: DemandReport,
    positioning: PositioningBrief | None,
    channel: Channel,
) -> ChannelAsset | None:
    """Draft + shape + ground one channel's asset.

    Returns ``None`` only when the model declines for this channel
    (:class:`StructuredOutputError`) — one channel failing to phrase never sinks
    the batch. Infra errors (auth/network/quota/timeout) propagate.
    """
    shape = _shape_for(channel)
    try:
        draft = _draft_channel(deps, report, positioning, channel, shape)
    except StructuredOutputError:
        return None
    parts = _clean_parts(draft.parts, shape.roles)
    if not parts:
        return None
    body = "\n\n".join(p.text for p in parts)
    offer = _strip_upvote_ask(draft.offer.strip())
    citations = _ground_claims(report, body, draft.claims)
    return ChannelAsset(
        channel_name=channel.name,
        surface_type=channel.surface_type,
        funnel_stage=channel.funnel_stage,
        body=body,
        parts=parts,
        offer=offer,
        claim_citations=citations,
    )


# ── Public entry ─────────────────────────────────────────────────────────────


def build_channel_assets(
    deps: ResearchDeps,
    report: DemandReport,
    channels: list[Channel],
    positioning: PositioningBrief | None = None,
) -> list[ChannelAsset]:
    """Draft channel-SHAPED, drafting-only assets for the selected channels.

    For each channel, one ``complete_structured`` call drafts the parts its
    ``surface_type`` calls for (Product Hunt = tagline + maker_comment + gallery
    captions; Show HN = title + first comment; X = N tweets; LinkedIn = carousel;
    default = title + body). Demand / factual claims are grounded against the
    report's verbatim quotes (no-cite-no-claim, unresolved dropped) while
    persuasive hooks and the per-channel ``offer`` are free; the platform
    invariants (no upvote ask, native-first, founder voice) are enforced
    deterministically. A channel whose draft fails or yields no usable parts is
    skipped, never fatal. DRAFTING ONLY — never posts.
    """
    assets: list[ChannelAsset] = []
    for channel in channels:
        asset = _build_one_asset(deps, report, positioning, channel)
        if asset is not None:
            # Best-effort compliance signal on the assembled body; never a blocker.
            with contextlib.suppress(Exception):
                from metalworks.reddit import heuristic_check

                heuristic_check(asset.body)
            assets.append(asset)
    return assets
