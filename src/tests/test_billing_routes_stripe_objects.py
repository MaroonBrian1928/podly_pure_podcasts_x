"""Billing routes must read stripe-python SDK objects, which are not dicts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from stripe import StripeObject

from app.routes import billing_routes


def test_update_user_from_subscription_accepts_stripe_object(
    monkeypatch: Any,
) -> None:
    user = SimpleNamespace(id=7)
    query = MagicMock()
    query.filter_by.return_value.first.return_value = user
    monkeypatch.setattr(billing_routes, "User", SimpleNamespace(query=query))
    writer = MagicMock()
    monkeypatch.setattr(billing_routes, "writer_client", writer)

    sub = StripeObject.construct_from(
        {"id": "sub_1", "customer": "cus_1", "status": "active"}, "sk_test"
    )
    billing_routes._update_user_from_subscription(sub)

    query.filter_by.assert_called_once_with(stripe_customer_id="cus_1")
    writer.action.assert_called_once_with(
        "set_user_billing_by_customer_id",
        {
            "stripe_customer_id": "cus_1",
            "feed_allowance": 10,
            "feed_subscription_status": "active",
            "stripe_subscription_id": "sub_1",
        },
        wait=True,
    )
