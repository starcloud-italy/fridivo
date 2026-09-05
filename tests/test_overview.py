from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.consumption import ConsumptionEvent, ConsumptionEventType
from app.models.household import Household, HouseholdMember, HouseholdPlan
from app.models.inventory import InventoryItem, StorageLocation
from app.models.shopping import ShoppingListItem
from app.services.insights import _insight_period


ROME = ZoneInfo("Europe/Rome")
PERIOD_END = datetime(2030, 4, 15, 12, 0, tzinfo=ROME)
PERIOD_START = PERIOD_END - timedelta(days=30)
BARCODES = tuple(f"7000000000{index:03d}" for index in range(17))


def register(client, payload, *, email="overview@example.com"):
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


def seed_catalog():
    with engine.begin() as connection:
        for index, barcode in enumerate(BARCODES):
            connection.execute(
                text(
                    "INSERT INTO products (id, code, product_name, brands, quantity, marker) "
                    "VALUES (:id, :barcode, :name, 'Overview Test', '1 unit', 'overview-fixture') "
                    "ON CONFLICT (code) DO UPDATE SET product_name = EXCLUDED.product_name"
                ),
                {
                    "id": 1000 + index,
                    "barcode": barcode,
                    "name": f"Overview product {index}",
                },
            )


@pytest.fixture
def fixed_period(monkeypatch):
    monkeypatch.setattr(
        "app.services.insights._insight_period",
        lambda _timezone, _now=None: (PERIOD_START, PERIOD_END),
    )


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


def test_overview_period_preserves_household_wall_clock_across_dst():
    start, end = _insight_period("Europe/Rome", PERIOD_END)

    assert start == PERIOD_START
    assert end == PERIOD_END
    assert start.hour == end.hour == 12
    assert start.utcoffset() == timedelta(hours=1)
    assert end.utcoffset() == timedelta(hours=2)


def test_plus_overview_reuses_metrics_and_returns_total_signal_counts(
    client, registration_payload, fixed_period
):
    seed_catalog()
    user = register(client, registration_payload)
    other = register(client, registration_payload, email="other-overview@example.com")
    household = household_id(user, plus=True)
    other_household = household_id(other, plus=True)

    with Session(engine) as db:
        # Six repeated-waste products: the overview must count all six, not Module 9's five cards.
        for barcode in BARCODES[:6]:
            add_event(db, household, barcode, ConsumptionEventType.DISCARDED, 1, PERIOD_END - timedelta(days=2))
            add_event(db, household, barcode, ConsumptionEventType.DISCARDED, 1, PERIOD_END - timedelta(days=1))
        # Used means CONSUMED + FINISHED, exactly as in the existing Insights summary.
        add_event(db, household, BARCODES[0], ConsumptionEventType.CONSUMED, 3, PERIOD_END - timedelta(hours=3))
        add_event(db, household, BARCODES[0], ConsumptionEventType.FINISHED, 2, PERIOD_END - timedelta(hours=2))
        # Six all-history Module 8 candidates, deliberately outside the 30-day metric window.
        for barcode in BARCODES[6:12]:
            add_event(db, household, barcode, ConsumptionEventType.FINISHED, 1, PERIOD_START - timedelta(days=1))
        # Six current Module 7 candidates; the first also blocks its FINISHED from repurchase.
        for index, barcode in enumerate((BARCODES[0], *BARCODES[12:17])):
            db.add(
                InventoryItem(
                    household_id=household,
                    product_barcode=barcode,
                    quantity=1,
                    expiry_date=date(2030, 4, 16 + index),
                    storage_location=StorageLocation.PANTRY,
                )
            )
        # Out-of-window and foreign data cannot alter the 30-day metrics.
        add_event(db, household, BARCODES[1], ConsumptionEventType.DISCARDED, 100, PERIOD_START - timedelta(microseconds=1))
        add_event(db, other_household, BARCODES[1], ConsumptionEventType.DISCARDED, 100, PERIOD_END)
        db.commit()

        before = (
            db.scalar(select(func.count()).select_from(ConsumptionEvent)),
            db.scalar(select(func.count()).select_from(InventoryItem)),
            db.scalar(select(func.count()).select_from(ShoppingListItem)),
        )

    response = client.get("/api/v1/insights/overview", headers=auth(user))

    assert response.status_code == 200
    overview = response.json()
    assert overview == {
        "period": {
            "days": 30,
            "start": PERIOD_START.isoformat(),
            "end": PERIOD_END.isoformat(),
        },
        "used_quantity": 5,
        "discarded_quantity": 12,
        "waste_ratio": 12 / 17,
        "repeated_waste_product_count": 6,
        "repurchase_candidate_count": 6,
        "expiry_attention_product_count": 6,
    }
    factual_summary = client.get(
        "/api/v1/insights/consumption", headers=auth(user)
    ).json()["summary"]
    assert overview["used_quantity"] == factual_summary["consumed_quantity"]
    assert overview["discarded_quantity"] == factual_summary["discarded_quantity"]
    assert overview["waste_ratio"] == factual_summary["waste_ratio"]
    assert len(client.get("/api/v1/insights/waste-watch", headers=auth(user)).json()) == 5
    assert len(client.get("/api/v1/shopping-list/suggestions", headers=auth(user)).json()) == 5
    assert len(client.get("/api/v1/inventory/consume-first", headers=auth(user)).json()) == 5

    with Session(engine) as db:
        after = (
            db.scalar(select(func.count()).select_from(ConsumptionEvent)),
            db.scalar(select(func.count()).select_from(InventoryItem)),
            db.scalar(select(func.count()).select_from(ShoppingListItem)),
        )
    assert after == before


def test_empty_plus_overview_is_factual_and_has_null_ratio(
    client, registration_payload, fixed_period
):
    user = register(client, registration_payload)
    household_id(user, plus=True)

    response = client.get("/api/v1/insights/overview", headers=auth(user))

    assert response.status_code == 200
    data = response.json()
    assert data["used_quantity"] == 0
    assert data["discarded_quantity"] == 0
    assert data["waste_ratio"] is None
    assert data["repeated_waste_product_count"] == 0
    assert data["repurchase_candidate_count"] == 0
    assert data["expiry_attention_product_count"] == 0


def test_overview_is_plus_only_and_requires_authentication(client, registration_payload):
    user = register(client, registration_payload)

    forbidden = client.get("/api/v1/insights/overview", headers=auth(user))

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "PLUS plan required"
    assert client.get("/api/v1/insights/overview").status_code == 401
