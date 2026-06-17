"""Webhook mapping — Stripe event → access record, tested with no network.

Ports Clique's ``webhook.test.ts``: the four subscription/checkout events map to
an attributed record, ``deleted`` forces ``canceled``, an unrelated type or an
unattributable object returns ``None``, an expanded customer object resolves to
its id, and a missing period end stays ``None``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from metalworks.billing import subscription_event_to_record

# 1782000000 == 2026-05-31T... UTC; the exact instant the mapper must round-trip.
PERIOD_END_UNIX = 1782000000


def sub_event(event_type: str, **over: Any) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "id": "sub_1",
        "customer": "cus_1",
        "status": "active",
        "current_period_end": PERIOD_END_UNIX,
        "metadata": {"product": "taxlock", "user_id": "user_1"},
    }
    obj.update(over)
    return {"type": event_type, "data": {"object": obj}}


def test_updated_maps_to_active_record() -> None:
    rec = subscription_event_to_record(sub_event("customer.subscription.updated"))
    assert rec is not None
    assert rec.user_id == "user_1"
    assert rec.product == "taxlock"
    assert rec.status == "active"
    assert rec.stripe_customer_id == "cus_1"
    assert rec.stripe_subscription_id == "sub_1"
    assert rec.current_period_end == datetime.fromtimestamp(PERIOD_END_UNIX, tz=UTC)


def test_created_maps_the_same_way() -> None:
    rec = subscription_event_to_record(sub_event("customer.subscription.created"))
    assert rec is not None and rec.status == "active"


def test_deleted_forces_canceled() -> None:
    # Stripe may still report status:"active" on the deleted object; we cancel.
    rec = subscription_event_to_record(sub_event("customer.subscription.deleted"))
    assert rec is not None and rec.status == "canceled"


def test_past_due_passes_through() -> None:
    rec = subscription_event_to_record(
        sub_event("customer.subscription.updated", status="past_due")
    )
    assert rec is not None and rec.status == "past_due"


def test_checkout_session_completed_maps_to_active() -> None:
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_1",
                "customer": "cus_9",
                "subscription": "sub_9",
                "status": "complete",
                "metadata": {"product": "taxlock", "user_id": "user_9"},
            }
        },
    }
    rec = subscription_event_to_record(event)
    assert rec is not None
    assert rec.user_id == "user_9"
    assert rec.product == "taxlock"
    assert rec.status == "active"
    assert rec.stripe_customer_id == "cus_9"
    assert rec.stripe_subscription_id == "sub_9"


def test_expanded_customer_object_resolves_to_id() -> None:
    rec = subscription_event_to_record(
        sub_event("customer.subscription.updated", customer={"id": "cus_obj"})
    )
    assert rec is not None and rec.stripe_customer_id == "cus_obj"


def test_unrelated_event_returns_none() -> None:
    assert subscription_event_to_record(sub_event("invoice.paid")) is None


def test_unattributable_event_returns_none() -> None:
    rec = subscription_event_to_record(sub_event("customer.subscription.updated", metadata={}))
    assert rec is None


def test_missing_period_end_stays_none() -> None:
    rec = subscription_event_to_record(
        sub_event("customer.subscription.updated", current_period_end=None)
    )
    assert rec is not None and rec.current_period_end is None


def test_unknown_status_coerced_to_incomplete() -> None:
    rec = subscription_event_to_record(sub_event("customer.subscription.updated", status="bogus"))
    assert rec is not None and rec.status == "incomplete"


def test_malformed_event_returns_none() -> None:
    assert subscription_event_to_record({"type": "customer.subscription.updated"}) is None
