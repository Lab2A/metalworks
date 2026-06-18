"""Subscription gating — the pure access rule, tested with a fake store.

Ports Clique's ``subscription.test.ts``: active/trialing grant access, an
expired period or a non-active status does not, a null record never does, and
``require_active_subscription`` reads the row through the injected store. Zero
network, zero Stripe.
"""

from __future__ import annotations

from datetime import UTC, datetime

from metalworks.billing import (
    is_active_status,
    is_subscription_active,
    require_active_subscription,
)
from metalworks.contract.billing import Subscription, SubscriptionStatus

NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def record(**over: object) -> Subscription:
    base: dict[str, object] = {
        "user_id": "user_1",
        "product": "taxlock",
        "status": "active",
        "stripe_customer_id": "cus_1",
        "stripe_subscription_id": "sub_1",
        "current_period_end": datetime(2026, 7, 1, tzinfo=UTC),
    }
    base.update(over)
    return Subscription.model_validate(base)


class FakeStore:
    """A one-row subscription store that records its reads/writes."""

    def __init__(self, rec: Subscription | None) -> None:
        self._rec = rec
        self.get_calls: list[tuple[str, str]] = []
        self.upserts: list[Subscription] = []

    def get_subscription(self, user_id: str, product: str) -> Subscription | None:
        self.get_calls.append((user_id, product))
        return self._rec

    def upsert_subscription(self, record: Subscription) -> None:
        self.upserts.append(record)


# ── is_active_status ──


def test_active_and_trialing_are_active() -> None:
    assert is_active_status("active") is True
    assert is_active_status("trialing") is True


def test_other_statuses_are_inactive() -> None:
    inactive: list[SubscriptionStatus] = [
        "canceled",
        "past_due",
        "unpaid",
        "incomplete",
        "incomplete_expired",
        "paused",
    ]
    for status in inactive:
        assert is_active_status(status) is False


# ── is_subscription_active ──


def test_active_within_period() -> None:
    assert is_subscription_active(record(), NOW) is True


def test_inactive_once_period_has_ended() -> None:
    expired = record(current_period_end=datetime(2026, 6, 9, 11, 0, 0, tzinfo=UTC))
    assert is_subscription_active(expired, NOW) is False


def test_inactive_when_canceled_even_with_future_period() -> None:
    assert is_subscription_active(record(status="canceled"), NOW) is False


def test_inactive_with_no_record() -> None:
    assert is_subscription_active(None, NOW) is False


def test_active_with_no_period_end() -> None:
    assert is_subscription_active(record(current_period_end=None), NOW) is True


def test_naive_period_end_is_treated_as_utc() -> None:
    # A record carrying a naive timestamp must not blow up the comparison.
    naive = record(current_period_end=datetime(2026, 7, 1))
    assert is_subscription_active(naive, NOW) is True


def test_now_defaults_to_wall_clock_when_omitted() -> None:
    # Period far in the future → active regardless of the real current time.
    future = record(current_period_end=datetime(2999, 1, 1, tzinfo=UTC))
    assert is_subscription_active(future) is True


# ── require_active_subscription ──


def test_require_true_for_active_subscription() -> None:
    store = FakeStore(record())
    assert require_active_subscription("user_1", "taxlock", store, NOW) is True
    assert store.get_calls == [("user_1", "taxlock")]


def test_require_false_when_no_row() -> None:
    store = FakeStore(None)
    assert require_active_subscription("user_1", "taxlock", store, NOW) is False


def test_require_false_when_canceled() -> None:
    store = FakeStore(record(status="canceled"))
    assert require_active_subscription("user_1", "taxlock", store, NOW) is False
