"""Audience inference for the demand report.

Two pieces:

1. **Subreddit → audience descriptor static map**. Hand-curated map of
   age/identity-coded communities → short descriptor (interest-only subs are
   deliberately absent so they fall through to the honest "unverified" note).
   This is the cheap, deterministic floor — no LLM, no network.

2. **Structured AudienceProfile synthesis**. One LLM pass that reorganizes the
   static descriptors of the corpus's source subreddits into the four
   AudienceProfile buckets (age_range / income_band / geography /
   buying_behavior). Each attribute carries its own confidence + evidence.
   Returns None when no source community is demographically coded — better
   honest-empty than fabricated. Best-effort: never raises.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from metalworks.contract import AudienceAttribute, AudienceProfile, SignalStrength

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps


# ── 1. static map (hand-curated, age/identity-coded only) ────────────────────
SUBREDDIT_AUDIENCE: dict[str, str] = {
    # age-coded
    "teenagers": "teens (Gen Z)",
    "genz": "Gen Z",
    "zoomer": "Gen Z",
    "college": "college students (Gen Z / younger millennial)",
    "youngadults": "young adults",
    "genx": "Gen X",
    "millennials": "millennials",
    "boomersbeing": "boomers",
    # identity-coded
    "askwomen": "women",
    "twoxchromosomes": "women",
    "askmen": "men",
    "askgaybros": "gay men",
    "actuallesbians": "queer women",
    # life-stage-coded
    "parenting": "parents",
    "newparents": "new parents",
    "beyondthebump": "new parents",
    "students": "students",
}

_MEDIUM_SHARE = 0.5


def _norm_sub(s: str) -> str:
    return (s or "").lower().lstrip("r/").strip()


def describe_audience(subreddits: list[str]) -> tuple[str | None, str]:
    """(attribution_method, confidence_note) for a cluster's source subs.

    method = 'subreddit-proxy' when at least one source is demographically
    coded, else None — and the note carries the honest disclaimer.
    """
    norm = [_norm_sub(s) for s in subreddits if s]
    if not norm:
        return None, "No source subreddits — audience cannot be inferred."

    coded = [SUBREDDIT_AUDIENCE[s] for s in norm if s in SUBREDDIT_AUDIENCE]
    total = len(norm)
    if not coded:
        sample = ", ".join(f"r/{s}" for s in dict.fromkeys(norm[:3]))
        return (
            None,
            f"Audience unverified: sources are interest-based communities ({sample}). "
            "Reddit exposes no age/identity signal — treat any demographic claim as unconfirmed.",
        )

    top_desc, _ = Counter(coded).most_common(1)[0]
    share = len(coded) / total
    strength = "Moderate" if share >= _MEDIUM_SHARE else "Weak"
    return (
        "subreddit-proxy",
        f"{strength} signal: audience skews {top_desc} "
        f"({len(coded)} of {total} source communities are demographically coded). "
        "Inferred from subreddit, not self-reported — directional, not a verified sample.",
    )


# ── 2. structured AudienceProfile synthesis ──────────────────────────────────
_CAVEAT = (
    "Demographics inferred from the audience skew of the source communities, not "
    "self-reported; treat as directional, not a survey."
)

_CONF_RANK = {SignalStrength.LOW: 1, SignalStrength.MEDIUM: 2, SignalStrength.HIGH: 3}
_RANK_TO_CONF = {1: SignalStrength.LOW, 2: SignalStrength.MEDIUM, 3: SignalStrength.HIGH}
_FROM_LITERAL = {
    "low": SignalStrength.LOW,
    "medium": SignalStrength.MEDIUM,
    "high": SignalStrength.HIGH,
}


class _AttrEstimate(BaseModel):
    estimate: str | None = Field(
        default=None,
        description="The estimate, e.g. '25-34' or '$50k-$80k'. Null if no signal.",
    )
    confidence: Literal["high", "medium", "low"] = Field(default="low")


class _AudienceSynthesis(BaseModel):
    age_range: _AttrEstimate = Field(default_factory=_AttrEstimate)
    income_band: _AttrEstimate = Field(default_factory=_AttrEstimate)
    geography: _AttrEstimate = Field(default_factory=_AttrEstimate)
    buying_behavior: _AttrEstimate = Field(default_factory=_AttrEstimate)


def build_audience_profile(
    deps: ResearchDeps,
    coded_descriptors: list[tuple[str, str]],
) -> AudienceProfile | None:
    """Synthesize one structured AudienceProfile from per-subreddit descriptors.

    Args:
        coded_descriptors: List of (subreddit_name, descriptor) for the
            subreddits in the corpus that have a static-map descriptor.
            Subreddits without a coded audience MUST be omitted — passing them
            in just fabricates demographic certainty.

    Returns None when no descriptors are coded, or the synthesis yields no
    supported attribute. The report-level caveat covers that case honestly.
    """
    if not coded_descriptors:
        return None
    try:
        raw = _default_synthesize(deps, coded_descriptors)
    except Exception:  # best-effort; never fail the report on audience synth
        return None

    # Ceiling: the static-map descriptors are 'high' confidence per the
    # SUBREDDIT_AUDIENCE contract. A synthesis is never more certain than its
    # strongest source — and static-map is the only source we read here, so the
    # ceiling is HIGH. Future inferred sources should lower this.
    ceiling = _CONF_RANK[SignalStrength.HIGH]
    srcs = ", ".join(f"r/{s}" for s, _ in coded_descriptors[:4])
    evidence_base = f"Inferred from the audience skew of {srcs} (subreddit proxy, directional)."

    def attr(e: _AttrEstimate) -> AudienceAttribute | None:
        if not e.estimate or not e.estimate.strip():
            return None
        conf = _FROM_LITERAL.get(e.confidence.lower(), SignalStrength.LOW)
        clamped = _RANK_TO_CONF[min(_CONF_RANK[conf], ceiling)]
        return AudienceAttribute(
            estimate=e.estimate.strip(), confidence=clamped, evidence=evidence_base
        )

    profile = AudienceProfile(
        age_range=attr(raw.age_range),
        income_band=attr(raw.income_band),
        geography=attr(raw.geography),
        buying_behavior=attr(raw.buying_behavior),
        caveat=_CAVEAT,
    )
    if not any(
        (profile.age_range, profile.income_band, profile.geography, profile.buying_behavior)
    ):
        return None
    return profile


def _default_synthesize(
    deps: ResearchDeps,
    coded_descriptors: list[tuple[str, str]],
) -> _AudienceSynthesis:
    descriptors = "\n".join(f"- r/{s}: {d}" for s, d in coded_descriptors[:12])
    system = (
        "You reorganize already-grounded subreddit audience descriptors into four buckets: "
        "age_range, income_band, geography, buying_behavior. Introduce NO demographic the "
        "descriptors don't support — leave a bucket's estimate null when there's no signal for it. "
        "Per bucket, set confidence to 'high' only when multiple communities agree, 'medium' for a "
        "single clear signal, 'low' otherwise. You are summarizing evidence, not guessing."
    )
    user = (
        "Source community audience reads:\n"
        f"{descriptors}\n\n"
        "Reorganize these into the four demographic buckets. Leave any unsupported bucket null."
    )
    return deps.chat.complete_structured(
        system=system,
        user=user,
        output_model=_AudienceSynthesis,
        max_tokens=2048,
        temperature=0.2,
    )


def coded_subreddits(subreddit_counts: list[tuple[str, int]]) -> list[tuple[str, str]]:
    """Filter a corpus's (sub, count) list to just the demographically-coded
    ones, preserving the input order (caller passes most-frequent-first). Each
    is paired with its static-map descriptor."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for sub, _ in subreddit_counts:
        norm = _norm_sub(sub)
        if norm in SUBREDDIT_AUDIENCE and norm not in seen:
            seen.add(norm)
            out.append((norm, SUBREDDIT_AUDIENCE[norm]))
    return out
