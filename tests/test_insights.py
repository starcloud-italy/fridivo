from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.consumption import ConsumptionEvent, ConsumptionEventType
from app.models.household import HouseholdMember


def register(client, payload, *, email="insights@example.com"):
    response = client.post(
        "/api/v1/auth/register",
        json={**payload, "email": email, "household_name": email},
    )
    assert response.status_code == 201
    return response.json()


def auth(user):
    return {"Authorization": f"Bearer {user['access_token']}"}


def household_id(user) -> UUID:
    with SessionLocal() as db:
        return db.scalar(
            select(HouseholdMember.household_id).where(
                HouseholdMember.user_id == UUID(user["user"]["id"])
            )
        )


def add_event(household, barcode, event_type, quantity, occurred_at):
    with SessionLocal() as db:
        db.add(
            ConsumptionEvent(
                household_id=household,
                product_barcode=barcode,
                event_type=ConsumptionEventType(event_type),
                quantity=quantity,
                occurred_at=occurred_at,
            )
        )
        db.commit()


def test_consumption_insights_require_authentication(client):
    assert client.get("/api/v1/insights/consumption").status_code == 401


def test_empty_insights_handle_zero_denominator(client, registration_payload):
    user = register(client, registration_payload)

    response = client.get("/api/v1/insights/consumption", headers=auth(user))

    assert response.status_code == 200
    data = response.json()
    assert data["period"]["days"] == 30
    assert data["summary"] == {
        "consumed_quantity": 0,
        "discarded_quantity": 0,
        "consumed_event_count": 0,
        "finished_event_count": 0,
        "discarded_event_count": 0,
        "distinct_products": 0,
        "waste_ratio": None,
    }
    assert data["most_consumed"] == []
    assert data["most_discarded"] == []
    assert data["products"] == []


def test_insights_aggregate_window_enrichment_rankings_and_do_not_mutate(
    client, registration_payload
):
    user = register(client, registration_payload)
    other = register(client, registration_payload, email="other-insights@example.com")
    current = datetime.now(timezone.utc) - timedelta(minutes=1)
    household = household_id(user)
    other_household = household_id(other)

    # Pasta: used 5 (CONSUMED + FINISHED), discarded 2; latest is DISCARDED.
    add_event(household, "0801234567890", "CONSUMED", 2, current - timedelta(days=3))
    add_event(household, "0801234567890", "FINISHED", 3, current - timedelta(days=2))
    add_event(household, "0801234567890", "DISCARDED", 2, current - timedelta(days=1))
    # Sauce ties on used quantity; barcode provides deterministic secondary ordering.
    add_event(household, "8001234567895", "CONSUMED", 5, current - timedelta(hours=4))
    # Water has no waste and must not appear in most_discarded.
    add_event(household, "8001234567896", "FINISHED", 1, current - timedelta(hours=3))
    # Old and foreign-household events must be excluded.
    add_event(household, "4001234567890", "DISCARDED", 99, current - timedelta(days=31))
    add_event(other_household, "4001234567890", "DISCARDED", 50, current)

    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(ConsumptionEvent))

    response = client.get("/api/v1/insights/consumption", headers=auth(user))

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == {
        "consumed_quantity": 11,
        "discarded_quantity": 2,
        "consumed_event_count": 2,
        "finished_event_count": 2,
        "discarded_event_count": 1,
        "distinct_products": 3,
        "waste_ratio": 2 / 13,
    }
    assert [item["barcode"] for item in data["most_consumed"]] == [
        "0801234567890",
        "8001234567895",
        "8001234567896",
    ]
    assert [item["barcode"] for item in data["most_discarded"]] == ["0801234567890"]

    pasta = next(item for item in data["products"] if item["barcode"] == "0801234567890")
    last_event_at = pasta.pop("last_event_at")
    assert pasta == {
        "barcode": "0801234567890",
        "product_name": "Pasta integrale",
        "brands": "Fridivo Test",
        "image_url": "https://images.test/pasta.jpg",
        "consumed_quantity": 5,
        "discarded_quantity": 2,
        "consumed_event_count": 1,
        "finished_event_count": 1,
        "discarded_event_count": 1,
        "last_event": "DISCARDED",
        "waste_ratio": 2 / 7,
    }
    assert datetime.fromisoformat(last_event_at) == current - timedelta(days=1)

    with SessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(ConsumptionEvent))
    assert after == before


def test_product_with_only_discarded_events_has_full_waste_ratio(
    client, registration_payload
):
    user = register(client, registration_payload)
    add_event(
        household_id(user),
        "4001234567890",
        "DISCARDED",
        4,
        datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    data = client.get("/api/v1/insights/consumption", headers=auth(user)).json()

    assert data["summary"]["waste_ratio"] == 1.0
    assert data["products"][0]["waste_ratio"] == 1.0
    assert data["most_consumed"] == []
