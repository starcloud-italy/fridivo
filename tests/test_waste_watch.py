from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.consumption import ConsumptionEvent, ConsumptionEventType
from app.models.household import Household, HouseholdMember, HouseholdPlan
from app.models.inventory import InventoryItem, StorageLocation
from app.models.shopping import ShoppingListItem
from app.services.insights import _waste_watch_period


ROME = ZoneInfo("Europe/Rome")
PERIOD_END = datetime(2030, 4, 15, 12, 0, tzinfo=ROME)
PERIOD_START = PERIOD_END - timedelta(days=30)
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


def register(client, payload, *, email="waste-watch@example.com"):
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


def add_event(db, household, barcode, event_type, quantity, occurred_at):
    db.add(
        ConsumptionEvent(
            household_id=household,
            product_barcode=barcode,
            event_type=event_type,
            quantity=quantity,
            occurred_at=occurred_at,
        )
    )


def freeze_period(monkeypatch):
    monkeypatch.setattr(
        "app.services.insights._waste_watch_period",
        lambda _timezone, _now=None: (PERIOD_START, PERIOD_END),
    )


def test_waste_watch_period_uses_household_wall_clock_across_dst():
    start, end = _waste_watch_period("Europe/Rome", PERIOD_END)

    assert start == PERIOD_START
    assert end == PERIOD_END
    assert start.hour == end.hour == 12
    assert start.utcoffset() == timedelta(hours=1)
    assert end.utcoffset() == timedelta(hours=2)


def test_plus_two_discarded_events_produce_enriched_factual_pattern(
    client, registration_payload, monkeypatch
):
    freeze_period(monkeypatch)
    user = register(client, registration_payload)
    household = household_id(user, plus=True)
    with Session(engine) as db:
        add_event(
            db,
            household,
            CATALOG_BARCODES[0],
            ConsumptionEventType.DISCARDED,
            1,
            PERIOD_END - timedelta(days=4),
        )
        add_event(
            db,
            household,
            CATALOG_BARCODES[0],
            ConsumptionEventType.DISCARDED,
            3,
            PERIOD_END - timedelta(days=1),
        )
        db.commit()

    response = client.get("/api/v1/insights/waste-watch", headers=auth(user))

    assert response.status_code == 200
    item = response.json()[0]
    assert item == {
        "product_barcode": CATALOG_BARCODES[0],
        "product_name": "Pasta integrale",
        "brands": "Fridivo Test",
        "product_quantity": "500 g",
        "image_url": "https://images.test/pasta.jpg",
        "discarded_event_count": 2,
        "discarded_quantity": 4,
        "last_discarded_at": item["last_discarded_at"],
    }
    assert datetime.fromisoformat(item["last_discarded_at"]) == PERIOD_END - timedelta(days=1)


def test_single_large_discard_and_non_discard_events_do_not_reach_threshold(
    client, registration_payload, monkeypatch
):
    freeze_period(monkeypatch)
    user = register(client, registration_payload)
    household = household_id(user, plus=True)
    with Session(engine) as db:
        add_event(
            db,
            household,
            CATALOG_BARCODES[0],
            ConsumptionEventType.DISCARDED,
            5,
            PERIOD_END - timedelta(days=1),
        )
        add_event(
            db,
            household,
            CATALOG_BARCODES[0],
            ConsumptionEventType.CONSUMED,
            1,
            PERIOD_END - timedelta(hours=2),
        )
        add_event(
            db,
            household,
            CATALOG_BARCODES[0],
            ConsumptionEventType.FINISHED,
            1,
            PERIOD_END - timedelta(hours=1),
        )
        db.commit()

    response = client.get("/api/v1/insights/waste-watch", headers=auth(user))

    assert response.status_code == 200
    assert response.json() == []


def test_window_boundaries_and_household_isolation_are_applied(
    client, registration_payload, monkeypatch
):
    freeze_period(monkeypatch)
    user = register(client, registration_payload)
    other = register(client, registration_payload, email="other-waste-watch@example.com")
    household = household_id(user, plus=True)
    other_household = household_id(other, plus=True)
    with Session(engine) as db:
        add_event(
            db,
            household,
            CATALOG_BARCODES[1],
            ConsumptionEventType.DISCARDED,
            2,
            PERIOD_START - timedelta(microseconds=1),
        )
        add_event(
            db,
            household,
            CATALOG_BARCODES[1],
            ConsumptionEventType.DISCARDED,
            1,
            PERIOD_START,
        )
        add_event(
            db,
            household,
            CATALOG_BARCODES[1],
            ConsumptionEventType.DISCARDED,
            3,
            PERIOD_END,
        )
        add_event(
            db,
            other_household,
            CATALOG_BARCODES[1],
            ConsumptionEventType.DISCARDED,
            20,
            PERIOD_END - timedelta(hours=2),
        )
        add_event(
            db,
            other_household,
            CATALOG_BARCODES[1],
            ConsumptionEventType.DISCARDED,
            20,
            PERIOD_END - timedelta(hours=1),
        )
        db.commit()

    item = client.get("/api/v1/insights/waste-watch", headers=auth(user)).json()[0]

    assert item["discarded_event_count"] == 2
    assert item["discarded_quantity"] == 4
    assert datetime.fromisoformat(item["last_discarded_at"]) == PERIOD_END


def test_ranking_uses_event_count_quantity_recency_then_limit(
    client, registration_payload, monkeypatch
):
    freeze_period(monkeypatch)
    user = register(client, registration_payload)
    household = household_id(user, plus=True)
    patterns = (
        (CATALOG_BARCODES[0], 4, 1, PERIOD_END - timedelta(days=4)),
        (CATALOG_BARCODES[1], 3, 3, PERIOD_END - timedelta(days=3)),
        (CATALOG_BARCODES[2], 3, 2, PERIOD_END - timedelta(days=1)),
        (CATALOG_BARCODES[3], 3, 2, PERIOD_END - timedelta(days=2)),
        (CATALOG_BARCODES[4], 2, 10, PERIOD_END - timedelta(hours=1)),
        (CATALOG_BARCODES[5], 2, 7, PERIOD_END),
    )
    with Session(engine) as db:
        for barcode, event_count, quantity, latest in patterns:
            for index in range(event_count):
                add_event(
                    db,
                    household,
                    barcode,
                    ConsumptionEventType.DISCARDED,
                    quantity,
                    latest - timedelta(minutes=index),
                )
        db.commit()

    response = client.get("/api/v1/insights/waste-watch", headers=auth(user))

    assert response.status_code == 200
    assert [item["product_barcode"] for item in response.json()] == [
        CATALOG_BARCODES[0],
        CATALOG_BARCODES[1],
        CATALOG_BARCODES[2],
        CATALOG_BARCODES[3],
        CATALOG_BARCODES[4],
    ]


def test_free_forbidden_unresolved_omitted_and_read_is_non_mutating(
    client, registration_payload, monkeypatch
):
    freeze_period(monkeypatch)
    free_user = register(client, registration_payload)
    forbidden = client.get("/api/v1/insights/waste-watch", headers=auth(free_user))
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "PLUS plan required"

    household = household_id(free_user, plus=True)
    with Session(engine) as db:
        add_event(
            db,
            household,
            "9999999999999",
            ConsumptionEventType.DISCARDED,
            1,
            PERIOD_END - timedelta(days=2),
        )
        add_event(
            db,
            household,
            "9999999999999",
            ConsumptionEventType.DISCARDED,
            1,
            PERIOD_END - timedelta(days=1),
        )
        db.add(
            InventoryItem(
                household_id=household,
                product_barcode=CATALOG_BARCODES[0],
                quantity=1,
                storage_location=StorageLocation.PANTRY,
            )
        )
        db.add(ShoppingListItem(household_id=household, name="Pane"))
        db.commit()
        before = (
            db.scalar(select(func.count()).select_from(ConsumptionEvent)),
            db.scalar(select(func.count()).select_from(InventoryItem)),
            db.scalar(select(func.count()).select_from(ShoppingListItem)),
        )

    response = client.get("/api/v1/insights/waste-watch", headers=auth(free_user))

    assert response.status_code == 200
    assert response.json() == []
    with Session(engine) as db:
        after = (
            db.scalar(select(func.count()).select_from(ConsumptionEvent)),
            db.scalar(select(func.count()).select_from(InventoryItem)),
            db.scalar(select(func.count()).select_from(ShoppingListItem)),
        )
    assert after == before


def test_waste_watch_requires_authentication(client):
    assert client.get("/api/v1/insights/waste-watch").status_code == 401
