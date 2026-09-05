from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.household import Household, HouseholdMember, HouseholdPlan
from app.models.inventory import InventoryItem


FIXED_TODAY = date(2030, 6, 15)


def register(client, payload, *, email="consume-first@example.com"):
    response = client.post(
        "/api/v1/auth/register",
        json={**payload, "email": email, "household_name": email},
    )
    assert response.status_code == 201
    return response.json()


def auth(user):
    return {"Authorization": f"Bearer {user['access_token']}"}


def set_plus(user) -> None:
    with Session(engine) as db:
        household = db.scalar(
            select(Household)
            .join(HouseholdMember)
            .where(HouseholdMember.user_id == UUID(user["user"]["id"]))
        )
        assert household is not None
        household.plan = HouseholdPlan.PLUS
        db.commit()


def add_item(client, user, barcode, expiry_date, *, quantity=2, location="fridge"):
    response = client.post(
        "/api/v1/inventory",
        headers=auth(user),
        json={
            "product_barcode": barcode,
            "quantity": quantity,
            "expiry_date": expiry_date.isoformat() if expiry_date else None,
            "storage_location": location,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_free_household_cannot_access_consume_first(client, registration_payload):
    user = register(client, registration_payload)
    item = add_item(client, user, "0801234567890", FIXED_TODAY)

    response = client.get("/api/v1/inventory/consume-first", headers=auth(user))

    assert response.status_code == 403
    assert response.json()["detail"] == "PLUS plan required"
    inventory = client.get("/api/v1/inventory", headers=auth(user)).json()
    assert [existing["id"] for existing in inventory] == [item["id"]]


def test_plus_ranking_is_bounded_enriched_isolated_and_read_only(
    client, registration_payload, monkeypatch
):
    monkeypatch.setattr(
        "app.services.inventory._today_for_household", lambda _timezone: FIXED_TODAY
    )
    owner = register(client, registration_payload)
    stranger = register(client, registration_payload, email="other-household@example.com")
    set_plus(owner)

    dated_items = [
        ("0801234567890", FIXED_TODAY - timedelta(days=2)),
        ("8001234567895", FIXED_TODAY),
        ("8001234567896", FIXED_TODAY + timedelta(days=1)),
        ("4001234567890", FIXED_TODAY + timedelta(days=3)),
        ("9000000000101", FIXED_TODAY + timedelta(days=8)),
        ("9000000000102", FIXED_TODAY + timedelta(days=20)),
    ]
    created = [add_item(client, owner, barcode, expiry) for barcode, expiry in dated_items]
    undated = add_item(client, owner, "9000000000103", None)
    add_item(client, stranger, "9000000000104", FIXED_TODAY - timedelta(days=30))

    with Session(engine) as db:
        before = {
            str(item.id): (item.quantity, item.expiry_date, item.storage_location.value)
            for item in db.scalars(select(InventoryItem))
        }

    response = client.get("/api/v1/inventory/consume-first", headers=auth(owner))

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 5
    assert [item["product_barcode"] for item in items] == [
        barcode for barcode, _expiry in dated_items[:5]
    ]
    assert [item["expiry_status"] for item in items] == [
        "EXPIRED",
        "TODAY",
        "TOMORROW",
        "FUTURE",
        "FUTURE",
    ]
    assert [item["days_until_expiry"] for item in items] == [-2, 0, 1, 3, 8]
    assert undated["id"] not in {item["id"] for item in items}
    assert created[5]["id"] not in {item["id"] for item in items}
    assert items[0]["product_name"] == "Pasta integrale"
    assert items[0]["brands"] == "Fridivo Test"
    assert items[0]["product_quantity"] == "500 g"
    assert items[0]["image_url"] == "https://images.test/pasta.jpg"
    assert all(item["household_id"] == created[0]["household_id"] for item in items)

    with Session(engine) as db:
        after = {
            str(item.id): (item.quantity, item.expiry_date, item.storage_location.value)
            for item in db.scalars(select(InventoryItem))
        }
    assert after == before


def test_equal_expiry_dates_use_barcode_as_deterministic_tie_break(
    client, registration_payload, monkeypatch
):
    monkeypatch.setattr(
        "app.services.inventory._today_for_household", lambda _timezone: FIXED_TODAY
    )
    user = register(client, registration_payload)
    set_plus(user)
    same_date = FIXED_TODAY + timedelta(days=4)
    add_item(client, user, "9000000000103", same_date)
    add_item(client, user, "4001234567890", same_date)

    response = client.get("/api/v1/inventory/consume-first", headers=auth(user))

    assert response.status_code == 200
    assert [item["product_barcode"] for item in response.json()] == [
        "4001234567890",
        "9000000000103",
    ]


def test_consume_first_requires_authentication(client):
    assert client.get("/api/v1/inventory/consume-first").status_code == 401
