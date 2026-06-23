"""D8 — closed-loop measurement: per-channel metric + instrumentation, re-rank.

The learning face of the Distribution pillar. Everything else in the pillar
PLANS; nothing learns. D8 closes the loop: plan → (human executes) → record
:class:`~metalworks.contract.distribution.ChannelResult`\\ s → re-rank the next
push. metalworks can't watch live traffic, so in its lane it does the two things
it *can* do deterministically:

- :func:`channel_metrics` — name, per channel, what "worked" means
  (``success_metric``) and exactly how to track it (``instrumentation``), keyed by
  the channel's ``surface_type`` from a fixed table. This is the falsifiable
  disposition applied to distribution: declare the metric + the instrument BEFORE
  the push so the outcome is measurable, not vibes.
- :func:`rerank_from_results` — ingest the recorded results and re-order the
  channels so the ones that actually performed rise (and the dead ones fall) for
  the next push. Pure + deterministic — no LLM, no network.

:func:`rerank_from_results` is what makes ``select_channels(prior_results=...)``
(D2) and ``plan_distribution(prior_results=...)`` (D7) meaningful — pass the prior
push's results and the selection / sequencing biases toward the winners.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metalworks.contract import (
    ChannelMetric,
    ChannelResult,
    ChannelSurfaceType,
)

if TYPE_CHECKING:
    from metalworks.contract import Channel


# ── The deterministic metric + instrumentation table ─────────────────────────
#
# surface_type → (success_metric, instrumentation). What "worked" means and how
# to track it, per kind of surface. Reproducible + citable, never an LLM guess —
# the same disposition as the playbook timing table in plan.py. Keyed by surface
# type so any channel (named or hand-built) gets an honest metric.

_METRIC_BY_SURFACE: dict[ChannelSurfaceType, tuple[str, str]] = {
    ChannelSurfaceType.LAUNCH_PLATFORM: (
        "top-N placement + attributed signups in the first 7d",
        "Tag the launch link with a UTM (utm_source=producthunt / hn); count signups whose first "
        "touch carries that UTM, and record the day's rank.",
    ),
    ChannelSurfaceType.MARKETPLACE: (
        "installs + WAU (weekly active users) from the listing",
        "Read the marketplace's install count for the listing; instrument an in-product event to "
        "count weekly-active installs attributed to that source.",
    ),
    ChannelSurfaceType.COMMUNITY: (
        "qualified replies + click-through to the product",
        "Count genuine 'how do I try this' replies on the post; tag the link with a UTM "
        "(utm_source=reddit/<sub>) and count click-throughs + attributed signups.",
    ),
    ChannelSurfaceType.ANSWER_ENGINE_GEO: (
        "citation appearances in answer-engine responses",
        "Run the citability probes against the answer engines and count how many cite your "
        "content; track the count over time.",
    ),
    ChannelSurfaceType.EMBEDDED_LOOP: (
        "new signups per N shared outputs (the loop's K-factor)",
        "Tag every shared/public output with a UTM and badge link; count signups attributed to "
        "shares and divide by outputs shared to report K honestly.",
    ),
    ChannelSurfaceType.WEDGE_INTEGRATION: (
        "attributed trials from the 'alternative to X' intent",
        "Tag the comparison/alternative page with a UTM and count trials whose first touch is that "
        "page; watch ranking/citation for the branded-alternative query.",
    ),
    ChannelSurfaceType.BORROWED_AUDIENCE: (
        "attributed signups from the borrowed audience",
        "Give the partner/newsletter a unique UTM or discount code; count signups carrying it.",
    ),
    ChannelSurfaceType.DATA_ASSET: (
        "earned citations / backlinks to the data report",
        "Track inbound links + named mentions of the report (a backlink monitor); count UTM'd "
        "click-throughs from outlets that cite it.",
    ),
    ChannelSurfaceType.EARNED_MEDIA: (
        "earned placements + referral traffic",
        "Count secured placements; tag each outlet's link with a UTM and count referral signups.",
    ),
    ChannelSurfaceType.SOCIAL: (
        "engaged click-through + attributed signups",
        "Tag the post's link with a UTM (utm_source=x/linkedin); count click-throughs + signups, "
        "not vanity likes.",
    ),
    ChannelSurfaceType.SEARCH: (
        "organic impressions → clicks → attributed signups",
        "Read Search Console impressions/clicks for the target query; tag landing pages and count "
        "attributed signups.",
    ),
    ChannelSurfaceType.APP_STORE: (
        "store impressions → installs (conversion rate)",
        "Read the app store's impressions + install conversion for the listing; instrument "
        "first-open → signup.",
    ),
    ChannelSurfaceType.PAID: (
        "CAC and attributed conversions (metalworks does not operate this)",
        "Tag every ad with a UTM and a campaign id; count attributed conversions and divide spend "
        "to get CAC. (metalworks names this channel; it does not run it.)",
    ),
    ChannelSurfaceType.SALES: (
        "qualified meetings → closed deals (metalworks does not operate this)",
        "Track the pipeline in a CRM; attribute meetings + closed deals to the source. (metalworks "
        "names this channel; it does not run it.)",
    ),
}

# A last-resort honest default for any surface not in the table (defensive — the
# table currently covers every ChannelSurfaceType member).
_DEFAULT_METRIC: tuple[str, str] = (
    "attributed signups in the first 7d",
    "Tag this channel's link with a UTM and count signups whose first touch carries it.",
)


def channel_metrics(channels: list[Channel]) -> list[ChannelMetric]:
    """Per-channel success metric + instrumentation guidance — the D8 metric face.

    DETERMINISTIC: one :class:`~metalworks.contract.distribution.ChannelMetric` per
    channel, with the ``success_metric`` (what "worked" means) and
    ``instrumentation`` (how to track it — a UTM tag, an attributed-signup query, a
    citation check, …) read from a fixed table keyed by the channel's
    ``surface_type``. No LLM, no network. This is what the human wires BEFORE the
    push so the outcome is measurable — and so the recorded
    :class:`~metalworks.contract.distribution.ChannelResult`\\ s can feed
    :func:`rerank_from_results` for the next push.
    """
    metrics: list[ChannelMetric] = []
    for channel in channels:
        success_metric, instrumentation = _METRIC_BY_SURFACE.get(
            channel.surface_type, _DEFAULT_METRIC
        )
        metrics.append(
            ChannelMetric(
                channel_name=channel.name,
                surface_type=channel.surface_type,
                success_metric=success_metric,
                instrumentation=instrumentation,
            )
        )
    return metrics


def rerank_from_results(
    channels: list[Channel],
    results: list[ChannelResult],
) -> list[Channel]:
    """Re-order channels by their recorded results — winners rise, dead ones fall.

    Ingests the :class:`~metalworks.contract.distribution.ChannelResult`\\ s from
    the prior push and returns the channels re-ordered so the ones that actually
    performed lead the next push. PURE + DETERMINISTIC — no LLM, no network, no
    mutation of the inputs:

    - A channel's score is the SUM of its results' ``value``\\ s (a channel can be
      measured on more than one metric), matched by ``channel_name``.
    - Channels WITH results sort first, by descending score; ties (and channels
      with equal score) keep their original relative order (a stable sort), so the
      ordering is reproducible.
    - Channels with NO recorded result keep their original relative order and sit
      *after* every measured channel — unproven, not promoted above a proven win,
      but not dropped either (the next push may still test them).

    When ``results`` is empty this returns the channels unchanged (same objects,
    same order) — the no-evidence path is a no-op, which is what keeps
    ``select_channels()`` / ``plan_distribution()`` byte-for-byte identical when no
    prior results are passed.
    """
    if not results:
        return list(channels)

    # Sum recorded values per channel name (a channel may carry several metrics).
    scores: dict[str, float] = {}
    for r in results:
        scores[r.channel_name] = scores.get(r.channel_name, 0.0) + r.value

    # Stable, deterministic ordering: measured channels first (by descending
    # score), then the unmeasured ones — each group preserving original order.
    # Python's sort is stable, so equal keys keep input order; we key on
    # (has_result desc, score desc) via a negated-score tuple.
    measured = [c for c in channels if c.name in scores]
    unmeasured = [c for c in channels if c.name not in scores]
    measured.sort(key=lambda c: -scores[c.name])
    return measured + unmeasured
