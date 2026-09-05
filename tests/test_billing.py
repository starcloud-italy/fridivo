from types import SimpleNamespace

import stripe
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.household import Household, HouseholdPlan


CHECKOUT_URL = "https://checkout.stripe.test/session/checkout-test"


def register(client, payload):
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    return response.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def configure_checkout(monkeypatch, captured, *, raises=None):
    class Sessions:
        def create(self, params):
            captured["params"] = params
            if raises is not None:
                raise raises
            return SimpleNamespace(url=CHECKOUT_URL)

    fake_client = SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions()))
    )
    monkeypatch.setattr(settings, "stripe_secret_key", SecretStr("sk_test_fixture_only"))
    monkeypatch.setattr(settings, "stripe_plus_monthly_price_id", "price_from_server")
    monkeypatch.setattr("app.services.billing._stripe_client", lambda key: fake_client)


def test_checkout_requires_authentication(client):
    assert client.post("/api/v1/billing/checkout").status_code == 401


def test_free_household_creates_subscription_checkout_from_server_values(
    client, registration_payload, monkeypatch
):
    registered = register(client, registration_payload)
    current = client.get(
        "/api/v1/households/current", headers=auth(registered["access_token"])
    ).json()
    captured = {}
    configure_checkout(monkeypatch, captured)

    response = client.post(
        "/api/v1/billing/checkout",
        headers=auth(registered["access_token"]),
        json={
            "price_id": "price_attacker",
            "amount": 1,
            "currency": "USD",
            "plan": "PLUS",
            "household_id": "attacker-household",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"url": CHECKOUT_URL}
    params = captured["params"]
    assert params["mode"] == "subscription"
    assert params["line_items"] == [{"price": "price_from_server", "quantity": 1}]
    assert params["metadata"] == {"household_id": current["id"]}
    assert params["subscription_data"] == {
        "metadata": {"household_id": current["id"]}
    }
    assert params["client_reference_id"] == current["id"]
    assert params["customer_email"] == registration_payload["email"]
    assert params["success_url"] == "http://testserver/?checkout=success"
    assert params["cancel_url"] == "http://testserver/?checkout=cancel"
    assert not {"amount", "currency", "plan", "household_id"}.intersection(params)

    with Session(engine) as db:
        household = db.scalar(select(Household))
        assert household is not None
        assert household.plan is HouseholdPlan.FREE


def test_plus_household_cannot_create_checkout(client, registration_payload, monkeypatch):
    registered = register(client, registration_payload)
    with Session(engine) as db:
        household = db.scalar(select(Household))
        assert household is not None
        household.plan = HouseholdPlan.PLUS
        db.commit()

    captured = {}
    configure_checkout(monkeypatch, captured)
    response = client.post(
        "/api/v1/billing/checkout", headers=auth(registered["access_token"])
    )

    assert response.status_code == 409
    assert "params" not in captured


def test_missing_stripe_configuration_is_safe(client, registration_payload, monkeypatch):
    registered = register(client, registration_payload)
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    monkeypatch.setattr(settings, "stripe_plus_monthly_price_id", None)

    response = client.post(
        "/api/v1/billing/checkout", headers=auth(registered["access_token"])
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Billing is temporarily unavailable"}


def test_missing_stripe_price_is_safe(client, registration_payload, monkeypatch):
    registered = register(client, registration_payload)
    monkeypatch.setattr(settings, "stripe_secret_key", SecretStr("sk_test_fixture_only"))
    monkeypatch.setattr(settings, "stripe_plus_monthly_price_id", "")

    response = client.post(
        "/api/v1/billing/checkout", headers=auth(registered["access_token"])
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Billing is temporarily unavailable"}


def test_stripe_error_is_mapped_without_provider_detail(
    client, registration_payload, monkeypatch
):
    registered = register(client, registration_payload)
    captured = {}
    configure_checkout(
        monkeypatch,
        captured,
        raises=stripe.APIConnectionError("provider-sensitive-detail"),
    )

    response = client.post(
        "/api/v1/billing/checkout", headers=auth(registered["access_token"])
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Billing is temporarily unavailable"}
    assert "provider-sensitive-detail" not in response.text


def test_checkout_reuses_persisted_stripe_customer(
    client, registration_payload, monkeypatch
):
    registered = register(client, registration_payload)
    with Session(engine) as db:
        household = db.scalar(select(Household))
        assert household is not None
        household.stripe_customer_id = "cus_existing"
        db.commit()
    captured = {}
    configure_checkout(monkeypatch, captured)

    response = client.post(
        "/api/v1/billing/checkout", headers=auth(registered["access_token"])
    )

    assert response.status_code == 200
    assert captured["params"]["customer"] == "cus_existing"
    assert "customer_email" not in captured["params"]
