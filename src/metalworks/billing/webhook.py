"""Webhook mapping — Stripe event → access record.

Pure mapping from a Stripe webhook event to a
:class:`~metalworks.contract.billing.Subscription` (or ``None`` when the event is
not subscription-relevant or cannot be attributed to a user). Signature
verification and the DB write are thin I/O the downstream route owns; this is the
tested core, so the "active vs canceled" rule has no network in its tests.

Attribution rides on the metadata the Stripe adapter stamps when it creates the
product/checkout (``{"product": ..., "user_id": ...}``) — see
:mod:`metalworks.billing.adapters.stripe`. An event whose object carries no
resolvable ``user_id`` + ``product`` is dropped (returns ``None``), exactly as
Clique drops an unattributable event.

The event is taken as a plain mapping (``stripe.Event`` is dict-like, and a
downstream route can pass ``event.to_dict()``), so this module imports no SDK and
stays in the bare-install, offline-tested core.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast, get_args

from metalworks.contract.billing import Subscription, SubscriptionStatus

_KNOWN_STATUSES: frozenset[str] = frozenset(get_args(SubscriptionStatus))

_SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)


def subscription_event_to_record(event: Mapping[str, Any]) -> Subscription | None:
    """Map a Stripe webhook event to a :class:`Subscription`, or ``None``.

    Handles the four events the paywall depends on:

    * ``customer.subscription.{created,updated,deleted}`` — the subscription's
      status flows through, except ``deleted``, which is forced to ``canceled``
      even when Stripe still reports ``status:"active"`` on the deleted object.
    * ``checkout.session.completed`` — grants access immediately as ``active``; a
      later ``customer.subscription.updated`` fills in ``current_period_end``.

    Any other event type, or one that cannot be attributed to a user/product via
    metadata, returns ``None``.
    """
    event_type = str(event.get("type", ""))
    obj = _object(event)

    if event_type in _SUBSCRIPTION_EVENTS:
        who = _attribution(obj)
        if who is None:
            return None
        user_id, product = who
        status: SubscriptionStatus = (
            "canceled"
            if event_type == "customer.subscription.deleted"
            else _status(obj.get("status"))
        )
        return Subscription(
            user_id=user_id,
            product=product,
            status=status,
            stripe_customer_id=_customer_id(obj.get("customer")),
            stripe_subscription_id=obj.get("id") if isinstance(obj.get("id"), str) else None,
            current_period_end=_period_end(obj.get("current_period_end")),
        )

    if event_type == "checkout.session.completed":
        who = _attribution(obj)
        if who is None:
            return None
        user_id, product = who
        sub_id = obj.get("subscription")
        return Subscription(
            user_id=user_id,
            product=product,
            status="active",
            stripe_customer_id=_customer_id(obj.get("customer")),
            stripe_subscription_id=sub_id if isinstance(sub_id, str) else None,
            current_period_end=_period_end(obj.get("current_period_end")),
        )

    return None


def _object(event: Mapping[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    if isinstance(data, Mapping):
        obj = cast("Mapping[str, Any]", data).get("object")
        if isinstance(obj, Mapping):
            return dict(cast("Mapping[str, Any]", obj))
    return {}


def _attribution(obj: Mapping[str, Any]) -> tuple[str, str] | None:
    """Pull ``(user_id, product)`` from the object's stamped metadata, or ``None``."""
    meta = obj.get("metadata")
    if not isinstance(meta, Mapping):
        return None
    meta = cast("Mapping[str, Any]", meta)
    user_id = meta.get("user_id")
    product = meta.get("product")
    if isinstance(user_id, str) and user_id and isinstance(product, str) and product:
        return user_id, product
    return None


def _customer_id(value: Any) -> str | None:
    """Stripe sends ``customer`` as an id string, or an expanded object with ``id``."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        cid = cast("Mapping[str, Any]", value).get("id")
        return cid if isinstance(cid, str) else None
    return None


def _period_end(value: Any) -> datetime | None:
    """``current_period_end`` is Stripe unix seconds; ``None``/absent stays ``None``."""
    if isinstance(value, bool):  # bool is an int subclass — never a timestamp
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    return None


def _status(value: Any) -> SubscriptionStatus:
    """Coerce a raw status to the typed set, defaulting unknowns to ``incomplete``."""
    if isinstance(value, str) and value in _KNOWN_STATUSES:
        return cast("SubscriptionStatus", value)
    return "incomplete"
