import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import stripe
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.billing import StripeWebhookEvent
from app.models.household import Household, HouseholdPlan
from app.services.billing import plan_for_subscription_status


WEBHOOK_SECRET = "whsec_test_fixture_only"


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_entitled_statuses_grant_plus(status):
    assert plan_for_subscription_status(status, HouseholdPlan.FREE) is HouseholdPlan.PLUS


@pytest.mark.parametrize(
    "status", ["canceled", "unpaid", "incomplete", "incomplete_expired", "paused"]
)
def test_nonvalid_statuses_revoke_plus(status):
    assert plan_for_subscription_status(status, HouseholdPlan.PLUS) is HouseholdPlan.FREE


def test_past_due_and_unknown_statuses_preserve_current_entitlement():
    assert (
        plan_for_subscription_status("past_due", HouseholdPlan.PLUS)
        is HouseholdPlan.PLUS
    )
    assert (
        plan_for_subscription_status("future_stripe_status", HouseholdPlan.FREE)
        is HouseholdPlan.FREE
    )


def register(client, payload):
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    return response.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def current_household(client, token):
    response = client.get("/api/v1/households/current", headers=auth(token))
    assert response.status_code == 200
    return response.json()


def signed_request(client, event, *, secret=WEBHOOK_SECRET, signature=None):
    payload = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time())
    if signature is None:
        signed_payload = f"{timestamp}.".encode() + payload
        digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        signature = f"t={timestamp},v1={digest}"
    return client.post(
        "/api/v1/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )


def configure_webhook(monkeypatch, subscription, calls=None):
    calls = calls if calls is not None else []

    class Subscriptions:
        def retrieve(self, subscription_id):
            calls.append(subscription_id)
            return subscription(subscription_id) if callable(subscription) else subscription

    fake_client = SimpleNamespace(v1=SimpleNamespace(subscriptions=Subscriptions()))
    monkeypatch.setattr(settings, "stripe_webhook_secret", SecretStr(WEBHOOK_SECRET))
    monkeypatch.setattr(settings, "stripe_secret_key", SecretStr("sk_test_fixture_only"))
    monkeypatch.setattr("app.services.billing._stripe_client", lambda key: fake_client)
    return calls


def subscription_object(
    household_id,
    *,
    status="active",
    customer_id="cus_household",
    subscription_id="sub_household",
    cancel_at_period_end=False,
    period_end=1_900_000_000,
):
    return {
        "id": subscription_id,
        "customer": customer_id,
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "metadata": {"household_id": str(household_id)},
        "items": {"data": [{"current_period_end": period_end}]},
    }


def checkout_event(household_id, *, event_id="evt_checkout"):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test",
                "mode": "subscription",
                "customer": "cus_household",
                "subscription": "sub_household",
                "client_reference_id": str(household_id),
                "metadata": {"household_id": str(household_id)},
            }
        },
    }


def subscription_event(event_type, subscription, *, event_id):
    return {"id": event_id, "type": event_type, "data": {"object": subscription}}


def invoice_event(event_type, subscription_id, *, event_id):
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": "in_test",
                "parent": {
                    "type": "subscription_details",
                    "subscription_details": {"subscription": subscription_id},
                },
            }
        },
    }


def test_webhook_without_signature_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", SecretStr(WEBHOOK_SECRET))
    response = client.post("/api/v1/billing/webhook", content=b"{}")
    assert response.status_code == 400


def test_webhook_with_invalid_signature_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", SecretStr(WEBHOOK_SECRET))
    response = signed_request(
        client,
        {"id": "evt_invalid", "type": "test", "data": {"object": {}}},
        signature=f"t={int(time.time())},v1=invalid",
    )
    assert response.status_code == 400


def test_missing_webhook_secret_is_controlled(client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", None)
    response = signed_request(
        client, {"id": "evt_missing_secret", "type": "test", "data": {"object": {}}}
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Billing is temporarily unavailable"}


def test_checkout_completed_links_household_and_uses_active_subscription_state(
    client, registration_payload, monkeypatch
):
    registered = register(client, registration_payload)
    household_id = current_household(client, registered["access_token"])["id"]
    period_end = 1_900_000_000
    subscription = subscription_object(household_id, period_end=period_end)
    calls = configure_webhook(monkeypatch, subscription)

    response = signed_request(client, checkout_event(household_id))

    assert response.status_code == 200
    assert response.json() == {"received": True, "duplicate": False}
    assert calls == ["sub_household"]
    with Session(engine) as db:
        household = db.get(Household, uuid.UUID(household_id))
        assert household is not None
        assert household.stripe_customer_id == "cus_household"
        assert household.stripe_subscription_id == "sub_household"
        assert household.subscription_status == "active"
        assert household.subscription_current_period_end == datetime.fromtimestamp(
            period_end, tz=timezone.utc
        )
        assert household.subscription_cancel_at_period_end is False
        assert household.plan is HouseholdPlan.PLUS


def test_trialing_subscription_grants_plus(client, registration_payload, monkeypatch):
    registered = register(client, registration_payload)
    household_id = current_household(client, registered["access_token"])["id"]
    subscription = subscription_object(household_id, status="trialing")
    configure_webhook(monkeypatch, subscription)

    response = signed_request(
        client,
        subscription_event(
            "customer.subscription.created", subscription, event_id="evt_trialing"
        ),
    )

    assert response.status_code == 200
    with Session(engine) as db:
        assert db.get(Household, uuid.UUID(household_id)).plan is HouseholdPlan.PLUS


def test_scheduled_cancellation_stays_plus(client, registration_payload, monkeypatch):
    registered = register(client, registration_payload)
    household_id = current_household(client, registered["access_token"])["id"]
    subscription = subscription_object(
        household_id, status="active", cancel_at_period_end=True
    )
    configure_webhook(monkeypatch, subscription)

    response = signed_request(
        client,
        subscription_event(
            "customer.subscription.updated", subscription, event_id="evt_cancel_scheduled"
        ),
    )

    assert response.status_code == 200
    with Session(engine) as db:
        household = db.get(Household, uuid.UUID(household_id))
        assert household.plan is HouseholdPlan.PLUS
        assert household.subscription_cancel_at_period_end is True


def test_deleted_subscription_revokes_plus(client, registration_payload, monkeypatch):
    registered = register(client, registration_payload)
    household_id = current_household(client, registered["access_token"])["id"]
    deleted = subscription_object(household_id, status="canceled")
    configure_webhook(monkeypatch, deleted)
    with Session(engine) as db:
        household = db.get(Household, uuid.UUID(household_id))
        household.stripe_customer_id = "cus_household"
        household.stripe_subscription_id = "sub_household"
        household.subscription_status = "active"
        household.plan = HouseholdPlan.PLUS
        db.commit()

    response = signed_request(
        client,
        subscription_event(
            "customer.subscription.deleted", deleted, event_id="evt_deleted"
        ),
    )

    assert response.status_code == 200
    with Session(engine) as db:
        household = db.get(Household, uuid.UUID(household_id))
        assert household.plan is HouseholdPlan.FREE
        assert household.subscription_status == "canceled"
        assert household.stripe_subscription_id == "sub_household"


def test_invoice_paid_resynchronizes_and_keeps_plus(
    client, registration_payload, monkeypatch
):
    registered = register(client, registration_payload)
    household_id = current_household(client, registered["access_token"])["id"]
    renewed_end = 1_910_000_000
    subscription = subscription_object(household_id, period_end=renewed_end)
    configure_webhook(monkeypatch, subscription)
    with Session(engine) as db:
        household = db.get(Household, uuid.UUID(household_id))
        household.stripe_customer_id = "cus_household"
        household.stripe_subscription_id = "sub_household"
        household.plan = HouseholdPlan.PLUS
        db.commit()

    response = signed_request(
        client,
        invoice_event("invoice.paid", "sub_household", event_id="evt_invoice_paid"),
    )

    assert response.status_code == 200
    with Session(engine) as db:
        household = db.get(Household, uuid.UUID(household_id))
        assert household.plan is HouseholdPlan.PLUS
        assert household.subscription_current_period_end == datetime.fromtimestamp(
            renewed_end, tz=timezone.utc
        )


def test_payment_failed_past_due_does_not_revoke_plus(
    client, registration_payload, monkeypatch
):
    registered = register(client, registration_payload)
    household_id = current_household(client, registered["access_token"])["id"]
    subscription = subscription_object(household_id, status="past_due")
    configure_webhook(monkeypatch, subscription)
    with Session(engine) as db:
        household = db.get(Household, uuid.UUID(household_id))
        household.stripe_customer_id = "cus_household"
        household.stripe_subscription_id = "sub_household"
        household.subscription_status = "active"
        household.plan = HouseholdPlan.PLUS
        db.commit()

    response = signed_request(
        client,
        invoice_event(
            "invoice.payment_failed", "sub_household", event_id="evt_payment_failed"
        ),
    )

    assert response.status_code == 200
    with Session(engine) as db:
        household = db.get(Household, uuid.UUID(household_id))
        assert household.plan is HouseholdPlan.PLUS
        assert household.subscription_status == "past_due"


def test_duplicate_event_is_acknowledged_without_reapplying(
    client, registration_payload, monkeypatch
):
    registered = register(client, registration_payload)
    household_id = current_household(client, registered["access_token"])["id"]
    calls = configure_webhook(monkeypatch, subscription_object(household_id))
    event = checkout_event(household_id, event_id="evt_duplicate")

    first = signed_request(client, event)
    second = signed_request(client, event)

    assert first.status_code == second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert calls == ["sub_household"]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(StripeWebhookEvent)) == 1


def test_nonexistent_household_is_rejected_without_recording_event(client, monkeypatch):
    household_id = uuid.uuid4()
    configure_webhook(monkeypatch, subscription_object(household_id))

    response = signed_request(client, checkout_event(household_id, event_id="evt_unknown"))

    assert response.status_code == 409
    with Session(engine) as db:
        assert db.get(StripeWebhookEvent, "evt_unknown") is None


@pytest.mark.parametrize(
    ("conflicting_field", "conflicting_value"),
    [
        ("stripe_customer_id", "cus_household"),
        ("stripe_subscription_id", "sub_household"),
    ],
)
def test_stripe_identity_cannot_be_reassigned_between_households(
    client,
    registration_payload,
    monkeypatch,
    conflicting_field,
    conflicting_value,
):
    first = register(client, registration_payload)
    first_id = current_household(client, first["access_token"])["id"]
    second_payload = {
        **registration_payload,
        "email": "second-billing@example.com",
        "household_name": "Second household",
    }
    second = register(client, second_payload)
    second_id = current_household(client, second["access_token"])["id"]
    with Session(engine) as db:
        second_household = db.get(Household, uuid.UUID(second_id))
        setattr(second_household, conflicting_field, conflicting_value)
        db.commit()
    configure_webhook(monkeypatch, subscription_object(first_id))

    response = signed_request(client, checkout_event(first_id, event_id="evt_conflict"))

    assert response.status_code == 409
    with Session(engine) as db:
        first_household = db.get(Household, uuid.UUID(first_id))
        assert first_household.stripe_customer_id is None
        assert first_household.plan is HouseholdPlan.FREE


def test_provider_error_is_sanitized_and_event_remains_retryable(
    client, registration_payload, monkeypatch
):
    registered = register(client, registration_payload)
    household_id = current_household(client, registered["access_token"])["id"]

    def unavailable(_subscription_id):
        raise stripe.APIConnectionError("provider-sensitive-detail")

    configure_webhook(monkeypatch, unavailable)
    event = checkout_event(household_id, event_id="evt_provider_error")

    response = signed_request(client, event)

    assert response.status_code == 502
    assert response.json() == {"detail": "Billing is temporarily unavailable"}
    assert "provider-sensitive-detail" not in response.text
    with Session(engine) as db:
        assert db.get(StripeWebhookEvent, "evt_provider_error") is None


def test_out_of_order_update_uses_current_stripe_state(
    client, registration_payload, monkeypatch
):
    registered = register(client, registration_payload)
    household_id = current_household(client, registered["access_token"])["id"]
    stale_payload = subscription_object(household_id, status="canceled")
    current_subscription = subscription_object(household_id, status="active")
    configure_webhook(monkeypatch, current_subscription)
    with Session(engine) as db:
        household = db.get(Household, uuid.UUID(household_id))
        household.stripe_customer_id = "cus_household"
        household.stripe_subscription_id = "sub_household"
        household.subscription_status = "canceled"
        household.plan = HouseholdPlan.FREE
        db.commit()

    response = signed_request(
        client,
        subscription_event(
            "customer.subscription.updated", stale_payload, event_id="evt_out_of_order"
        ),
    )

    assert response.status_code == 200
    with Session(engine) as db:
        household = db.get(Household, uuid.UUID(household_id))
        assert household.subscription_status == "active"
        assert household.plan is HouseholdPlan.PLUS


def test_success_redirect_alone_does_not_change_plan(client, registration_payload):
    registered = register(client, registration_payload)
    response = client.get("/?checkout=success")
    assert response.status_code == 200
    assert current_household(client, registered["access_token"])["plan"] == "FREE"
