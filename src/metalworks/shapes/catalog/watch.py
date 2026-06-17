"""Watch base stack — keep an eye on something and notify when it changes.

The monitoring archetype: ingest a signal on a schedule (or via webhook), run it
through a rules engine, and fire a notification when a watched condition trips.
Consolidates the "alert me when X happens" demand — price moves, new listings,
downtime, anomalies, status changes — behind one reusable backend.
"""

from __future__ import annotations

from metalworks.contract.research import SignalStrength
from metalworks.contract.shape import BaseStack, MatchSignature, ProductShape
from metalworks.shapes import register_base_stack, register_shape

WATCH = BaseStack(
    id="watch",
    verb="watch",
    backend_capabilities=[
        "pollers / webhooks ingest",
        "rules engine",
        "notification channels (email/sms/slack)",
        "alert history",
    ],
    default_modules=[],
    scaffold_target="starter:watch-monitor",
)

PRICE_MONITOR = ProductShape(
    name="price-monitor",
    base_stack="watch",
    modules=[],
    domain_skin="Track a product's price and notify the watcher when it moves.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "alert me when the price changes",
            "track a price drop and notify me",
            "notify me when price goes down",
            "watch a price and ping me on change",
        ],
        surface="web",
        build_signals=["price", "alert", "track", "notify", "threshold"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

LISTING_MONITOR = ProductShape(
    name="listing-monitor",
    base_stack="watch",
    modules=[],
    domain_skin="Watch a search or feed and notify the watcher when a new listing appears.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "alert me when a new listing appears",
            "notify me of new listings",
            "watch a search for new listings",
            "ping me when an item is listed",
        ],
        surface="web",
        build_signals=["listing", "alert", "notify", "search", "new"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

UPTIME_MONITOR = ProductShape(
    name="uptime-monitor",
    base_stack="watch",
    modules=[],
    domain_skin="Poll a site or endpoint and notify the watcher when it goes down.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "alert me when my site goes down",
            "notify me when the website is down",
            "monitor uptime and ping me on an outage",
            "tell me when my server is offline",
        ],
        surface="web",
        build_signals=["uptime", "downtime", "alert", "ping", "outage"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

ANOMALY_DETECTOR = ProductShape(
    name="anomaly-detector",
    base_stack="watch",
    modules=[],
    domain_skin="Watch a metric stream and notify the watcher when a value looks abnormal.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "detect anomalies in my metrics",
            "alert me on unusual spikes",
            "notify me when numbers look abnormal",
            "flag outliers in the data",
        ],
        surface="web",
        build_signals=["anomaly", "spike", "metric", "threshold", "alert"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

STATUS_TRACKER = ProductShape(
    name="status-tracker",
    base_stack="watch",
    modules=[],
    domain_skin="Track a status and notify the watcher when it changes.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "track a status and ping me on change",
            "notify me when the status updates",
            "watch an order status and alert me",
            "tell me when the status changes",
        ],
        surface="web",
        build_signals=["status", "track", "update", "notify", "change"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

register_base_stack(WATCH)
register_shape(PRICE_MONITOR)
register_shape(LISTING_MONITOR)
register_shape(UPTIME_MONITOR)
register_shape(ANOMALY_DETECTOR)
register_shape(STATUS_TRACKER)
