"""In-memory cache for Stripe subscription amounts to avoid redundant API calls."""

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("global_logger")

# Env flag that controls whether the admin cost dashboard does Stripe lookups
# at all. When unset/false, ``fetch_subscription_amount`` short-circuits
# before importing the stripe SDK — which avoids loading several MB of
# stripe/* modules into the long-lived process for deployments that don't
# track revenue. Default off; deployments that want the
# revenue-vs-cost view in the admin dashboard must opt in.
STRIPE_BILLING_ENABLED_ENV = "PODLY_STRIPE_BILLING_ENABLED"


def stripe_billing_enabled() -> bool:
    return os.environ.get(STRIPE_BILLING_ENABLED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_lock = threading.Lock()
# Cache stores tuples of (amount_cents, expiration_time)
_cache: dict[str, tuple[int | None, float]] = {}

CACHE_TTL_SECONDS = 3600  # 1 hour


def get_subscription_amount(subscription_id: str) -> int | None:
    with _lock:
        cached = _cache.get(subscription_id)
        if cached:
            amount, expires_at = cached
            if time.time() < expires_at:
                return amount
            else:
                del _cache[subscription_id]
        return None


def set_subscription_amount(subscription_id: str, amount_cents: int | None) -> None:
    with _lock:
        _cache[subscription_id] = (amount_cents, time.time() + CACHE_TTL_SECONDS)


def fetch_subscription_amount(subscription_id: str) -> int | None:
    """Fetch and cache the current subscription amount from Stripe.

    Returns the amount in cents, or None if unavailable. When
    ``PODLY_STRIPE_BILLING_ENABLED`` is unset/false, returns None without
    importing the stripe SDK or hitting the network.
    """
    if not stripe_billing_enabled():
        return None

    cached = get_subscription_amount(subscription_id)
    if cached is not None:
        return cached

    try:
        import stripe

        secret = os.getenv("STRIPE_SECRET_KEY")
        if not secret:
            return None

        # Passing api_key prevents mutating global stripe state
        sub: Any = stripe.Subscription.retrieve(subscription_id, api_key=secret)
        items = sub.get("items", {}).get("data", [])
        if items:
            amount_cents = items[0].get("price", {}).get("unit_amount")
            if isinstance(amount_cents, int):
                set_subscription_amount(subscription_id, amount_cents)
                return amount_cents
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "billing_cache: failed to fetch subscription %s: %s", subscription_id, exc
        )

    return None
