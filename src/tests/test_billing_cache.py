"""Tests for the Stripe-billing flag short-circuit in app.billing_cache.

The whole point of ``PODLY_STRIPE_BILLING_ENABLED`` is to skip importing the
stripe SDK into the long-lived Flask/writer processes for deployments that
don't track revenue. These tests assert the flag actually prevents the
import and the cost-dashboard Stripe enrichment is a no-op."""

from __future__ import annotations

import sys
from typing import Any

from app import billing_cache


def test_fetch_subscription_amount_short_circuits_when_flag_off(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("PODLY_STRIPE_BILLING_ENABLED", raising=False)
    # Simulate "stripe not yet imported" to prove the call never imports it.
    monkeypatch.delitem(sys.modules, "stripe", raising=False)

    result = billing_cache.fetch_subscription_amount("sub_test")

    assert result is None
    assert "stripe" not in sys.modules


def test_fetch_subscription_amount_attempts_lookup_when_flag_on(
    monkeypatch: Any,
) -> None:
    """When the flag is on but no STRIPE_SECRET_KEY is set, the function
    enters the lookup branch and returns None after importing stripe and
    finding no secret. The test only asserts the short-circuit is gone —
    we don't want to make a real network call."""
    monkeypatch.setenv("PODLY_STRIPE_BILLING_ENABLED", "true")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    assert billing_cache.stripe_billing_enabled() is True
    assert billing_cache.fetch_subscription_amount("sub_test") is None


def test_enrich_rust_users_with_stripe_is_noop_when_flag_off(
    monkeypatch: Any,
) -> None:
    """The Rust-path enrichment helper must not call into billing_cache (and
    thus must not import stripe) when the flag is off."""
    monkeypatch.delenv("PODLY_STRIPE_BILLING_ENABLED", raising=False)

    from app.routes.cost_routes import _enrich_rust_users_with_stripe

    called: list[str] = []

    def _explode(_sub_id: str) -> int | None:
        called.append(_sub_id)
        raise AssertionError("Stripe lookup must not run when the flag is off")

    monkeypatch.setattr(billing_cache, "fetch_subscription_amount", _explode)

    users = [
        {"id": 1, "stripe_subscription_id": "sub_x", "subscription_amount_cents": None}
    ]
    _enrich_rust_users_with_stripe(users)

    assert called == []
    assert users[0]["subscription_amount_cents"] is None
