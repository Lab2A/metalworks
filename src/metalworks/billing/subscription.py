"""Subscription gating — the pure half of billing.

Given a stored :class:`~metalworks.contract.billing.Subscription`, decide whether
it grants access right now. The webhook mapper keeps ``status`` and
``current_period_end`` fresh; this logic only reads them, so it is unit-tested
against a fake store with no Stripe and no network.

This is what a downstream app (including a metalworks-specced product) imports to
enforce a paywall — no metalworks runtime required, just the contract model and
a :class:`~metalworks.billing.protocol.SubscriptionStore`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from metalworks.contract.billing import Subscription, SubscriptionStatus

if TYPE_CHECKING:
    from metalworks.billing.protocol import SubscriptionStore

_ACTIVE_STATUSES: frozenset[SubscriptionStatus] = frozenset({"active", "trialing"})


def is_active_status(status: SubscriptionStatus) -> bool:
    """Whether a status grants access. A trial counts; everything else does not."""
    return status in _ACTIVE_STATUSES


def is_subscription_active(record: Subscription | None, now: datetime | None = None) -> bool:
    """Authoritative "is this subscription currently good?" check.

    The status must be active/trialing AND the paid period must not have lapsed.
    A ``None`` record (no subscription) is never active. A record with no
    ``current_period_end`` is open-ended while its status is active.
    """
    if record is None:
        return False
    if not is_active_status(record.status):
        return False
    if record.current_period_end is None:
        return True
    now = now if now is not None else datetime.now(UTC)
    return now < _as_aware(record.current_period_end)


def require_active_subscription(
    user_id: str,
    product: str,
    store: SubscriptionStore,
    now: datetime | None = None,
) -> bool:
    """The access-guard entry point: does this owner hold an active subscription?

    Loads the row through the injected store and applies the rule above. The
    store call is the only I/O; pass a fake store to test the gate offline.
    """
    record = store.get_subscription(user_id, product)
    return is_subscription_active(record, now)


def _as_aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC so the comparison never raises.

    Pydantic parses an ISO ``...Z`` into an aware datetime, but a record built
    from a naive value would otherwise blow up the comparison against an aware
    ``now`` — assume UTC, the convention every Stripe timestamp follows.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
