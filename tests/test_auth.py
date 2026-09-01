from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.household import Household, HouseholdMember, HouseholdRole
from app.models.user import User


def register(client, payload):
    return client.post("/api/v1/auth/register", json=payload)


def test_register_normalizes_email_and_returns_token(client, registration_payload):
    registration_payload["email"] = "  Mario.Rossi@Example.COM  "
    response = register(client, registration_payload)

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "mario.rossi@example.com"
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "password_hash" not in body["user"]


def test_duplicate_email_is_rejected_after_normalization(client, registration_payload):
    assert register(client, registration_payload).status_code == 201
    registration_payload["email"] = "  MARIO@EXAMPLE.COM "

    response = register(client, registration_payload)

    assert response.status_code == 409
    with Session(engine) as db:
        assert len(db.scalars(select(User)).all()) == 1
        assert len(db.scalars(select(Household)).all()) == 1


def test_password_is_argon2_hashed(client, registration_payload):
    assert register(client, registration_payload).status_code == 201

    with Session(engine) as db:
        user = db.scalar(select(User))
        assert user is not None
        assert user.password_hash != registration_payload["password"]
        assert user.password_hash.startswith("$argon2")


def test_registration_atomically_creates_household_owner(client, registration_payload):
    response = register(client, registration_payload)
    user_id = response.json()["user"]["id"]

    with Session(engine) as db:
        household = db.scalar(select(Household))
        membership = db.scalar(select(HouseholdMember))
        assert household is not None
        assert household.name == "Casa Rossi"
        assert household.country_code == "IT"
        assert household.default_language_code == "it"
        assert household.currency_code == "EUR"
        assert household.timezone == "Europe/Rome"
        assert membership is not None
        assert str(membership.user_id) == user_id
        assert membership.household_id == household.id
        assert membership.role is HouseholdRole.OWNER


def test_valid_and_invalid_login(client, registration_payload):
    assert register(client, registration_payload).status_code == 201

    valid = client.post(
        "/api/v1/auth/login",
        json={"email": "MARIO@EXAMPLE.COM", "password": registration_payload["password"]},
    )
    invalid_password = client.post(
        "/api/v1/auth/login",
        json={"email": registration_payload["email"], "password": "totally-wrong"},
    )
    unknown_user = client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@example.com", "password": "totally-wrong"},
    )

    assert valid.status_code == 200
    assert valid.json()["access_token"]
    assert invalid_password.status_code == 401
    assert unknown_user.status_code == 401


def test_me_requires_valid_bearer_and_returns_current_user(client, registration_payload):
    registered = register(client, registration_payload).json()
    token = registered["access_token"]

    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer invalid-token"}
    ).status_code == 401

    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == registered["user"]["id"]
    assert response.json()["email"] == registration_payload["email"]

