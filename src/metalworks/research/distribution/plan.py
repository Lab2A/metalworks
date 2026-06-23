"""D7 — DistributionPlan: pushes (sequenced moments) + streams (continuous).

The sequencing face of the Distribution pillar. It takes a finished demand report
+ its selected channels and lays them out as a distribution CAMPAIGN: the
``spike``-cadence channels become :class:`~metalworks.contract.distribution.Push`\\
es sequenced into concentrated launch moments, the ``compounding``-cadence
channels become :class:`~metalworks.contract.distribution.Stream`\\ s that run
continuously. Assembled into a
:class:`~metalworks.contract.distribution.DistributionPlan`.

This replaces the old toy plan — even-spacing pushes at ``T+{i*2}h`` (the
arbitrary-constant anti-pattern, an LLM-invented constant masquerading as a
schedule). Here the timing is READ from a DETERMINISTIC, module-level playbook
table (:data:`_PLAYBOOK_TIMING`) sourced from the channel playbooks in the
research — so every push's timing is reproducible + citable, the opposite of an
invented hour. The sequencer enforces the playbook's rules:

- at most ONE all-day-attention channel (Product Hunt, a big Show HN/Launch HN
  push) per launch day, and
- never Product Hunt and a big HN push on the SAME day — they are staggered across
  the campaign's days,

then frames the run as a campaign: pre-launch warming steps before Day 1, the
staggered push week, and a 30-day post step after. Each push is a channel *test*
(test→focus — early pushes prove a channel before you concentrate on the winner),
and a spark-requiring channel carries its ``spark_channel`` (the spark→flywheel
edge).

:func:`plan_distribution` is the reusable core the four surfaces call. It is PURE
and deterministic — no LLM, no network — over the already-selected channels.
``prior_results`` closes the loop (D8): pass the prior push's recorded
:class:`~metalworks.contract.distribution.ChannelResult`\\ s and the channels are
re-ranked (winners first) before sequencing, so the proven channels lead the next
push. The default (``prior_results=None``) path is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metalworks.contract import (
    ChannelSurfaceType,
    DistributionPlan,
    Push,
    Stream,
)

if TYPE_CHECKING:
    from metalworks.contract import Channel, ChannelResult, DemandReport


# ── The deterministic playbook timing table ──────────────────────────────────
#
# Channel name / surface type → the timing window the channel's playbook
# prescribes. Sourced from the per-platform launch playbooks in the research —
# reproducible + citable, the opposite of an LLM-invented hour. ``day`` is the
# campaign-relative launch day a moment lands on (1-based, within the staggered
# push week); ``window`` is the human-readable timing the playbook gives. Keyed by
# the concrete channel name first, then a surface-type fallback so a hand-built or
# future spike channel still sequences deterministically.

# (campaign day, timing window) for a known channel — the canonical playbook rows.
_PLAYBOOK_TIMING_BY_NAME: dict[str, tuple[int, str]] = {
    "product_hunt": (1, "Day 1, 12:01am PT (Tue/Wed)"),
    "show_hn": (3, "Day 3-4, Tue-Thu 8-10am PT"),
    "launch_hn": (3, "Day 3-4, Tue-Thu 8-10am PT"),
    "x_thread": (2, "Day 2, 9-11am PT (weekday)"),
    "twitter_thread": (2, "Day 2, 9-11am PT (weekday)"),
    "linkedin_post": (2, "Day 2, 8-10am local (Tue-Thu)"),
    "reddit_launch": (5, "Day 5, mid-morning local (after participating)"),
}

# Surface-type fallback for a spike channel whose name isn't a known playbook row.
_PLAYBOOK_TIMING_BY_SURFACE: dict[ChannelSurfaceType, tuple[int, str]] = {
    ChannelSurfaceType.LAUNCH_PLATFORM: (1, "Day 1, 12:01am PT (Tue/Wed)"),
    ChannelSurfaceType.SOCIAL: (2, "Day 2, 9-11am PT (weekday)"),
    ChannelSurfaceType.DATA_ASSET: (4, "Day 4, Tue-Thu morning (pitch alongside the launch)"),
    ChannelSurfaceType.EARNED_MEDIA: (4, "Day 4, Tue-Thu morning (pitch under embargo)"),
    ChannelSurfaceType.APP_STORE: (1, "Day 1, alongside the launch-day push"),
}

# The all-day-attention channels: a launch that eats a whole day of the founder's
# attention + the audience's. At most one of these per launch day, and never two
# of them on the same day (esp. Product Hunt + a big HN push). Keyed by surface
# type so any launch-platform spike counts.
_ALL_DAY_ATTENTION_SURFACES: frozenset[ChannelSurfaceType] = frozenset(
    {ChannelSurfaceType.LAUNCH_PLATFORM}
)

# The campaign frame: pre-launch warming steps before Day 1, a 30-day post step
# after. These are deterministic scaffolding, not channel pushes — they carry no
# playbook channel, so they use the report's launch frame as their surface anchor.
_PRELAUNCH_TIMING = "Pre-launch (Day -7 to -1)"
_POSTLAUNCH_TIMING = "Day 30 (post-launch)"


def _playbook_slot(channel: Channel) -> tuple[int, str]:
    """The (campaign day, timing window) the playbook prescribes for a spike channel.

    Reads the deterministic table — name match first, then surface-type fallback,
    then a last-resort generic spike slot. Never an invented hour.
    """
    name = channel.name.lower()
    if name in _PLAYBOOK_TIMING_BY_NAME:
        return _PLAYBOOK_TIMING_BY_NAME[name]
    if channel.surface_type in _PLAYBOOK_TIMING_BY_SURFACE:
        return _PLAYBOOK_TIMING_BY_SURFACE[channel.surface_type]
    return (2, "Day 2, weekday mid-morning local")


def _stagger_day(
    channel: Channel,
    preferred_day: int,
    used_attention_days: set[int],
) -> int:
    """Resolve the launch day for a spike channel, enforcing the playbook's rules.

    Non-attention channels keep their preferred day. An all-day-attention channel
    (a launch-platform push) must NOT share a day with another all-day-attention
    channel — so Product Hunt and a big HN push are pushed onto separate days. We
    walk forward from the preferred day to the first day no other attention channel
    already occupies, recording it so the next attention channel staggers again.
    """
    if channel.surface_type not in _ALL_DAY_ATTENTION_SURFACES:
        return preferred_day
    day = preferred_day
    while day in used_attention_days:
        day += 1
    used_attention_days.add(day)
    return day


def _prelaunch_pushes(report: DemandReport, has_spikes: bool) -> list[Push]:
    """Deterministic pre-launch WARMING steps, before any Day-1 push.

    Warming the audience is part of the campaign, not a channel — so it's emitted
    as scaffolding pushes that anchor the run. Only emitted when there is at least
    one real spike channel to warm toward (an all-streams plan has no launch week).
    """
    if not has_spikes:
        return []
    return [
        Push(
            channel_name="prelaunch_warming",
            surface_type=ChannelSurfaceType.COMMUNITY,
            timing=_PRELAUNCH_TIMING,
            action=(
                "Warm the audience before the push week: participate authentically where they "
                "already are, line up a small honest 'we're launching' list, and stage every "
                "asset so launch day is execution, not drafting. No 'please upvote' asks."
            ),
            rationale=(
                "A cold launch wastes the one push day; the playbook front-loads warming so the "
                "Day-1 spike lands on an audience that already knows you. This is a channel test "
                "of your warm list, not a guarantee."
            ),
        )
    ]


def _postlaunch_push(has_spikes: bool) -> list[Push]:
    """The deterministic 30-day post step — the campaign doesn't end on launch day."""
    if not has_spikes:
        return []
    return [
        Push(
            channel_name="day_30_review",
            surface_type=ChannelSurfaceType.COMMUNITY,
            timing=_POSTLAUNCH_TIMING,
            action=(
                "Review the push week against each channel's success_threshold, CONCENTRATE on "
                "the single channel that worked (test→focus), and treat a strong channel as a "
                "repeatable push — relaunch a major update on the winner rather than chasing "
                "every channel at once."
            ),
            rationale=(
                "Most products have ONE channel that drives nearly all growth; the 30-day step is "
                "where the early channel tests resolve into a focus, and a winning push becomes a "
                "repeatable one."
            ),
        )
    ]


def _push_for_channel(channel: Channel, timing: str) -> Push:
    """Build a :class:`Push` for one spike channel at its sequenced timing.

    Carries the spark→flywheel edge (``spark_channel``) when the channel ignites an
    amplifier, and frames the moment as a channel test (test→focus).
    """
    spark_clause = ""
    if channel.spark_channel:
        spark_clause = f" This push sparks the {channel.spark_channel} amplifier into motion."
    return Push(
        channel_name=channel.name,
        surface_type=channel.surface_type,
        timing=timing,
        spark_channel=channel.spark_channel,
        action=(
            channel.test
            or f"Fire the {channel.name} push at the playbook window; reply to everyone."
        ),
        rationale=(
            f"Sequenced from the playbook: {timing}. This is a channel TEST — "
            f"{channel.routing_signal}. Watch its success_threshold before concentrating here."
            + spark_clause
        ),
    )


def _stream_for_channel(channel: Channel) -> Stream:
    """Build a :class:`Stream` for one compounding channel — how it runs continuously."""
    spark_clause = ""
    if channel.spark_channel:
        spark_clause = (
            f" It's an amplifier — it doesn't start its own velocity; the {channel.spark_channel} "
            "push sparks it, then it compounds."
        )
    cadence_note = channel.test or (
        f"Run {channel.name} continuously rather than as a one-time moment; let it compound."
    )
    return Stream(
        channel_name=channel.name,
        surface_type=channel.surface_type,
        cadence_note=cadence_note,
        rationale=(
            f"A compounding channel: {channel.routing_signal}. It runs as a stream, not a push."
            + spark_clause
        ),
    )


def plan_distribution(
    report: DemandReport,
    channels: list[Channel],
    prior_results: list[ChannelResult] | None = None,
) -> DistributionPlan:
    """Sequence a report's channels into pushes + streams — the D7 face.

    DETERMINISTIC — no LLM, no network. Splits the channels by their ``cadence``
    axis: ``spike`` channels become :class:`~metalworks.contract.distribution.Push`\\
    es sequenced from the :data:`_PLAYBOOK_TIMING_BY_NAME` /
    :data:`_PLAYBOOK_TIMING_BY_SURFACE` playbook tables (reproducible timings, never
    invented), ``compounding`` channels become
    :class:`~metalworks.contract.distribution.Stream`\\ s that run continuously. The
    sequencer enforces the playbook's staggering rules — at most one all-day-attention
    channel per launch day, never Product Hunt + a big HN push the same day — opens
    with pre-launch warming and closes with a 30-day post step, and threads each
    spark-requiring channel's ``spark_channel`` through (the spark→flywheel edge).

    ``prior_results`` closes the loop (D8): when the prior push's recorded
    :class:`~metalworks.contract.distribution.ChannelResult`\\ s are passed, the
    channels are re-ranked (winners first, via
    :func:`~metalworks.research.distribution.measure.rerank_from_results`) BEFORE the
    cadence split, so the proven channels lead the next push's STREAMS — the
    streams preserve that order. The spike pushes do NOT inherit it: they are always
    re-sorted by ``(playbook_day, name)`` so the launch week stays deterministically
    sequenced regardless of results. The default (``prior_results=None``) path is
    unchanged.
    """
    if prior_results:
        from metalworks.research.distribution.measure import rerank_from_results

        channels = rerank_from_results(channels, prior_results)

    spike_channels = [c for c in channels if c.cadence == "spike"]
    compounding_channels = [c for c in channels if c.cadence == "compounding"]
    has_spikes = bool(spike_channels)

    # Resolve each spike channel's launch day from the playbook, staggering the
    # all-day-attention channels so no two share a day (esp. not PH + a big HN push).
    used_attention_days: set[int] = set()
    sequenced: list[tuple[int, str, Channel]] = []
    for channel in spike_channels:
        preferred_day, window = _playbook_slot(channel)
        day = _stagger_day(channel, preferred_day, used_attention_days)
        # If the channel was staggered off its preferred day, reflect the new day
        # in its timing string so the moment reads truthfully.
        if day != preferred_day and window.startswith("Day "):
            window = f"Day {day} (staggered off Day {preferred_day} — one all-day push per day)"
        sequenced.append((day, window, channel))

    # Order the push week by day, then by channel name for a stable, reproducible plan.
    sequenced.sort(key=lambda row: (row[0], row[2].name))

    pushes: list[Push] = []
    pushes.extend(_prelaunch_pushes(report, has_spikes))
    pushes.extend(_push_for_channel(channel, window) for _day, window, channel in sequenced)
    pushes.extend(_postlaunch_push(has_spikes))

    streams = [_stream_for_channel(c) for c in compounding_channels]

    return DistributionPlan(report_id=report.report_id, pushes=pushes, streams=streams)
