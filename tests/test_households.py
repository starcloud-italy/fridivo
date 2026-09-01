from sqlalchemy import text

from app.db.session import engine


def register(client, payload):
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    return response.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_current_household_returns_owner_membership(client, registration_payload):
    registered = register(client, registration_payload)

    response = client.get(
        "/api/v1/households/current", headers=auth(registered["access_token"])
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Casa Rossi"
    assert response.json()["role"] == "owner"
    assert response.json()["currency_code"] == "EUR"
    assert response.json()["timezone"] == "Europe/Rome"


def test_current_household_requires_authentication(client):
    assert client.get("/api/v1/households/current").status_code == 401


def test_households_are_isolated_between_users(client, registration_payload):
    first = register(client, registration_payload)
    second_payload = {
        **registration_payload,
        "email": "anna@example.de",
        "first_name": "Anna",
        "household_name": "Zuhause Anna",
        "language_code": "de",
        "country_code": "DE",
        "currency_code": "EUR",
        "timezone": "Europe/Berlin",
    }
    second = register(client, second_payload)

    first_household = client.get(
        "/api/v1/households/current", headers=auth(first["access_token"])
    ).json()
    second_household = client.get(
        "/api/v1/households/current", headers=auth(second["access_token"])
    ).json()

    assert first_household["id"] != second_household["id"]
    assert first_household["name"] == "Casa Rossi"
    assert second_household["name"] == "Zuhause Anna"
    assert second_household["country_code"] == "DE"
    assert second_household["default_language_code"] == "de"
    assert second_household["timezone"] == "Europe/Berlin"


def test_migration_preserves_existing_products_table():
    with engine.connect() as connection:
        marker = connection.scalar(text("SELECT marker FROM products WHERE id = -1"))
    assert marker == "must-survive"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

