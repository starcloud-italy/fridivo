from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.consumption import ConsumptionEvent, ConsumptionEventType
from app.models.household import Household, HouseholdMember, HouseholdPlan
from app.models.inventory import InventoryItem, StorageLocation
from app.models.shopping import ShoppingListItem


BASE_TIME = datetime(2030, 6, 15, 12, 0, tzinfo=timezone.utc)
CATALOG_BARCODES = (
    "0801234567890",
    "8001234567895",
    "8001234567896",
    "4001234567890",
    "9000000000101",
    "9000000000102",
    "9000000000103",
    "9000000000104",
)


def register(client, payload, *, email="suggestions@example.com"):
    response = client.post(
        "/api/v1/auth/register",
        json={**payload, "email": email, "household_name": email},
    )
    assert response.status_code == 201
    return response.json()


def auth(user):
    return {"Authorization": f"Bearer {user['access_token']}"}


def household_id(user, *, plus=False):
    with Session(engine) as db:
        household = db.scalar(
            select(Household)
            .join(HouseholdMember)
            .where(HouseholdMember.user_id == UUID(user["user"]["id"]))
        )
        assert household is not None
        if plus:
            household.plan = HouseholdPlan.PLUS
            db.commit()
        return household.id


def add_event(db, household, barcode, event_type, occurred_at, *, quantity=1):
    db.add(
        ConsumptionEvent(
            household_id=household,
            product_barcode=barcode,
            event_type=event_type,
            quantity=quantity,
            occurred_at=occurred_at,
        )
    )


def add_inventory(client, user, barcode, *, quantity=2):
    response = client.post(
        "/api/v1/inventory",
        headers=auth(user),
        json={
            "product_barcode": barcode,
            "quantity": quantity,
            "expiry_date": None,
            "storage_location": "pantry",
        },
    )
    assert response.status_code == 201
    return response.json()


def finish_inventory(client, user, item_id):
    response = client.post(
        "/api/v1/consumption-events",
        headers=auth(user),
        json={"inventory_item_id": item_id, "event_type": "FINISHED"},
    )
    assert response.status_code == 201
    return response.json()


def test_plus_finished_product_produces_enriched_suggestion(client, registration_payload):
    user = register(client, registration_payload)
    household_id(user, plus=True)
    item = add_inventory(client, user, CATALOG_BARCODES[0], quantity=3)
    finish_inventory(client, user, item["id"])

    response = client.get("/api/v1/shopping-list/suggestions", headers=auth(user))

    assert response.status_code == 200
    assert response.json() == [
        {
            "product_barcode": "0801234567890",
            "product_name": "Pasta integrale",
            "brands": "Fridivo Test",
            "product_quantity": "500 g",
            "image_url": "https://images.test/pasta.jpg",
            "last_finished_at": response.json()[0]["last_finished_at"],
        }
    ]


def test_free_household_cannot_access_suggestions(client, registration_payload):
    user = register(client, registration_payload)

    response = client.get("/api/v1/shopping-list/suggestions", headers=auth(user))

    assert response.status_code == 403
    assert response.json()["detail"] == "PLUS plan required"


def test_only_finished_candidates_survive_household_inventory_and_shopping_filters(
    client, registration_payload
):
    user = register(client, registration_payload)
    other = register(client, registration_payload, email="other-suggestions@example.com")
    household = household_id(user, plus=True)
    other_household = household_id(other, plus=True)

    with Session(engine) as db:
        add_event(db, household, CATALOG_BARCODES[0], ConsumptionEventType.CONSUMED, BASE_TIME)
        add_event(db, household, CATALOG_BARCODES[1], ConsumptionEventType.DISCARDED, BASE_TIME)
        add_event(db, household, CATALOG_BARCODES[2], ConsumptionEventType.FINISHED, BASE_TIME)
        add_event(db, household, CATALOG_BARCODES[3], ConsumptionEventType.FINISHED, BASE_TIME)
        add_event(db, household, CATALOG_BARCODES[4], ConsumptionEventType.FINISHED, BASE_TIME)
        add_event(
            db,
            household,
            CATALOG_BARCODES[5],
            ConsumptionEventType.FINISHED,
            BASE_TIME,
        )
        add_event(
            db,
            other_household,
            CATALOG_BARCODES[6],
            ConsumptionEventType.FINISHED,
            BASE_TIME + timedelta(days=1),
        )
        add_event(db, household, "9999999999999", ConsumptionEventType.FINISHED, BASE_TIME)
        db.add(
            InventoryItem(
                household_id=household,
                product_barcode=CATALOG_BARCODES[2],
                quantity=1,
                expiry_date=None,
                storage_location=StorageLocation.PANTRY,
            )
        )
        db.add_all(
            (
                ShoppingListItem(
                    household_id=household,
                    product_barcode=CATALOG_BARCODES[3],
                    name="Dark chocolate",
                    is_completed=False,
                ),
                ShoppingListItem(
                    household_id=household,
                    product_barcode=CATALOG_BARCODES[4],
                    name="Rankingyogurt",
                    is_completed=True,
                    completed_at=BASE_TIME + timedelta(hours=1),
                ),
                ShoppingListItem(
                    household_id=household,
                    product_barcode=CATALOG_BARCODES[5],
                    name="Rankingyogurt bianco",
                    is_completed=True,
                    completed_at=BASE_TIME - timedelta(hours=1),
                ),
            )
        )
        db.commit()

    response = client.get("/api/v1/shopping-list/suggestions", headers=auth(user))

    assert response.status_code == 200
    assert [item["product_barcode"] for item in response.json()] == [CATALOG_BARCODES[5]]


def test_repeated_finished_events_are_deduplicated_ordered_and_limited(
    client, registration_payload
):
    user = register(client, registration_payload)
    household = household_id(user, plus=True)
    with Session(engine) as db:
        for index, barcode in enumerate(CATALOG_BARCODES[:6]):
            add_event(
                db,
                household,
                barcode,
                ConsumptionEventType.FINISHED,
                BASE_TIME + timedelta(minutes=index),
            )
        add_event(
            db,
            household,
            CATALOG_BARCODES[0],
            ConsumptionEventType.FINISHED,
            BASE_TIME + timedelta(minutes=10),
        )
        db.commit()

    response = client.get("/api/v1/shopping-list/suggestions", headers=auth(user))

    assert response.status_code == 200
    assert [item["product_barcode"] for item in response.json()] == [
        CATALOG_BARCODES[0],
        CATALOG_BARCODES[5],
        CATALOG_BARCODES[4],
        CATALOG_BARCODES[3],
        CATALOG_BARCODES[2],
    ]


def test_suggestion_read_is_read_only_and_explicit_shopping_add_removes_it(
    client, registration_payload
):
    user = register(client, registration_payload)
    household_id(user, plus=True)
    item = add_inventory(client, user, CATALOG_BARCODES[0], quantity=2)
    finish_inventory(client, user, item["id"])

    with Session(engine) as db:
        before = (
            db.scalar(select(func.count()).select_from(ConsumptionEvent)),
            db.scalar(select(func.count()).select_from(InventoryItem)),
            db.scalar(select(func.count()).select_from(ShoppingListItem)),
        )

    suggestion = client.get(
        "/api/v1/shopping-list/suggestions", headers=auth(user)
    ).json()[0]

    with Session(engine) as db:
        after_read = (
            db.scalar(select(func.count()).select_from(ConsumptionEvent)),
            db.scalar(select(func.count()).select_from(InventoryItem)),
            db.scalar(select(func.count()).select_from(ShoppingListItem)),
        )
    assert after_read == before

    added = client.post(
        "/api/v1/shopping-list",
        headers=auth(user),
        json={
            "product_barcode": suggestion["product_barcode"],
            "name": suggestion["product_name"],
        },
    )
    assert added.status_code == 201
    assert added.json()["is_completed"] is False
    assert client.get("/api/v1/shopping-list", headers=auth(user)).json()[0][
        "product_barcode"
    ] == suggestion["product_barcode"]
    assert client.get(
        "/api/v1/shopping-list/suggestions", headers=auth(user)
    ).json() == []


def test_suggestions_require_authentication(client):
    assert client.get("/api/v1/shopping-list/suggestions").status_code == 401
