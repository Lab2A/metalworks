"""D3 — distribution → build requirements (embedded loops + conversion surface).

The build face of the Distribution pillar. Two distribution decisions are not
marketing tactics bolted on after the fact — they are designed INTO the product,
so they must be emitted as BUILD requirements that feed build-spec:

- **Embedded loops.** When :mod:`~metalworks.research.distribution.channels`
  selects an ``embedded_loop`` channel, the loop mechanic implies concrete things
  the build must ship: a watermark loop is worthless without public share-URLs +
  a branded viewer + badge-gating; a UGC-SEO loop underperforms (Notion's public
  pages did) without SSR public pages + a sitemap; a single-player loop needs the
  solo aha to land before any invite UI. :func:`loop_requirements` maps each
  selected loop channel's kind → its build requirements via a DETERMINISTIC table,
  grounded in that channel's ``routing_signal``.
- **The conversion surface.** Channels create attention; attention with no surface
  to catch it leaks out. So the build MUST include a conversion destination, and
  naming its funnel job is a distribution decision. :func:`conversion_surface_\
requirement` always emits one — this re-opens generate-site (#67) from the right
  side: "the build must include a conversion destination, here is its funnel job,"
  not cite-or-die marketing copy.

:func:`distribution_requirements` is the reusable core the four surfaces call. It
is PURE and deterministic — no LLM, no network — over the already-selected
channels; the grounding comes from the channels' own ``routing_signal``\\ s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from metalworks.contract import (
    ChannelSurfaceType,
    ConversionSurfaceRequirement,
    LoopRequirement,
)

if TYPE_CHECKING:
    from metalworks.contract import Channel

# The deterministic loop_kind → build_requirements table. Each entry is the
# concrete set of things the build must ship for that loop to actually work —
# the build face of a real, audience-derived loop decision.
LoopKind = Literal["watermark", "ugc_seo", "referral", "free_tool", "oss", "single_player"]

_LOOP_BUILD_REQUIREMENTS: dict[LoopKind, list[str]] = {
    "watermark": ["public_share_urls", "branded_viewer", "badge_gating"],
    "ugc_seo": ["ssr_public_pages", "sitemap", "canonical_urls"],
    "referral": ["referral_codes", "attribution_tracking", "reward_fulfillment"],
    "free_tool": ["standalone_free_tool", "soft_gated_upsell"],
    "oss": ["public_repo", "self_host_path", "upgrade_to_hosted_cta"],
    "single_player": ["solo_aha_before_invite", "deferred_invite_prompt"],
}

# Names of embedded-loop channels that select_channels emits, mapped to the loop
# kind their build requirements serve. select_channels currently emits the
# shareable-output watermark loop ('shareable_output_loop'); the rest of the
# vocabulary is supported so a hand-built or future channel routes deterministically.
_CHANNEL_NAME_TO_LOOP: dict[str, LoopKind] = {
    "shareable_output_loop": "watermark",
}


def _loop_kind_for_channel(channel: Channel) -> LoopKind:
    """Map an embedded-loop channel to its loop kind — deterministic, never invents.

    Prefers an explicit name match; else infers from the channel name / routing
    signal language (UGC/SEO, referral, free tool, OSS/open-source, single-player),
    and defaults to ``watermark`` (the shareable-output loop ``select_channels``
    emits). The mapping is a fixed table, not an LLM call.
    """
    name = channel.name.lower()
    if name in _CHANNEL_NAME_TO_LOOP:
        return _CHANNEL_NAME_TO_LOOP[name]
    haystack = f"{name} {channel.routing_signal.lower()}"
    if "single-player" in haystack or "single player" in haystack or "solo" in haystack:
        return "single_player"
    if "ugc" in haystack or "seo" in haystack or "public content" in haystack:
        return "ugc_seo"
    if "referral" in haystack or "invite" in haystack:
        return "referral"
    if "free tool" in haystack or "free_tool" in haystack:
        return "free_tool"
    if "oss" in haystack or "open-source" in haystack or "open source" in haystack:
        return "oss"
    return "watermark"


def loop_requirements(channels: list[Channel]) -> list[LoopRequirement]:
    """One :class:`LoopRequirement` per selected ``embedded_loop`` channel.

    DETERMINISTIC: each loop channel's kind maps to a fixed build-requirements set,
    and the ``rationale`` traces to that channel's grounded ``routing_signal`` so
    the requirement is the build face of a real, audience-derived loop decision —
    never an invented feature. Non-loop channels are ignored.
    """
    out: list[LoopRequirement] = []
    for ch in channels:
        if ch.surface_type != ChannelSurfaceType.EMBEDDED_LOOP:
            continue
        kind = _loop_kind_for_channel(ch)
        out.append(
            LoopRequirement(
                loop_kind=kind,
                build_requirements=list(_LOOP_BUILD_REQUIREMENTS[kind]),
                rationale=(
                    f"The '{ch.name}' embedded loop is selected because {ch.routing_signal}; "
                    f"the loop only works if the build ships these — it's a build-spec decision, "
                    f"not a post-hoc marketing tactic."
                ),
            )
        )
    return out


def conversion_surface_requirement(
    channels: list[Channel],
) -> ConversionSurfaceRequirement:
    """The conversion destination every channel points at — always emitted.

    Channels create attention; attention with no surface to catch it leaks out, so
    the build MUST include a conversion destination. Deterministic: the funnel-job
    framing adapts to whether the plan already carries a conversion-stage channel
    (then the destination CATCHES conversion-stage intent) or is all top-of-funnel
    (then it is the ONLY place the awareness pushes can convert — the leak to plug).
    Grounded in the channel plan, not invented marketing copy.
    """
    has_conversion = any(ch.funnel_stage == "conversion" for ch in channels)
    n = len(channels)
    if has_conversion:
        funnel_job = (
            "Catch the conversion-stage intent the channels drive and turn a visitor into a "
            "signup/trial — the single destination the funnel hands off to."
        )
        rationale = (
            f"The {n} selected channel(s) span into conversion; the build must ship the "
            "destination that intent lands on, or the conversion-stage channels have nowhere "
            "to convert."
        )
    else:
        funnel_job = (
            "Convert the awareness/consideration attention the channels create — the ONLY "
            "surface that turns a visitor into a signup, so the plan doesn't leak top-of-funnel."
        )
        rationale = (
            f"All {n} selected channel(s) are upstream of conversion; without a conversion "
            "destination in the build, the attention they create leaks out — this is the "
            "all-top-of-funnel leak, plugged on the build side."
        )
    return ConversionSurfaceRequirement(
        destination="landing_page",
        funnel_job=funnel_job,
        build_requirements=[
            "above_fold_value_prop",
            "single_primary_cta",
            "instrumented_signup",
        ],
        rationale=rationale,
    )


def distribution_requirements(
    channels: list[Channel],
) -> tuple[list[LoopRequirement], list[ConversionSurfaceRequirement]]:
    """The distribution→build requirements for a channel plan — the D3 face.

    Returns ``(loop_requirements, conversion_surface_requirements)``: one
    :class:`LoopRequirement` per selected ``embedded_loop`` channel (deterministic
    kind → build requirements, grounded in the channel's ``routing_signal``) and
    always one :class:`ConversionSurfaceRequirement` for the conversion destination
    the channels point at. PURE and deterministic — no LLM, no network. The
    conversion surface is wrapped in a list (always length 1) so build-spec can
    carry both as additive, defaulted list fields.
    """
    return loop_requirements(channels), [conversion_surface_requirement(channels)]
