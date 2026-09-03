from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.consumption import ConsumptionEvent
from app.models.inventory import InventoryItem
from app.models.shopping import ShoppingListItem


def register(client, payload, *, email="shopping@example.com"):
    response = client.post(
        "/api/v1/auth/register",
        json={**payload, "email": email, "household_name": email},
    )
    assert response.status_code == 201
    return response.json()


def auth(user):
    return {"Authorization": f"Bearer {user['access_token']}"}


def create_item(client, headers, **overrides):
    payload = {"name": "Latte", **overrides}
    return client.post("/api/v1/shopping-list", json=payload, headers=headers)


def test_shopping_list_requires_authentication(client):
    assert client.get("/api/v1/shopping-list").status_code == 401
    assert client.post("/api/v1/shopping-list", json={"name": "Pane"}).status_code == 401


def test_create_and_list_support_free_name_and_optional_fields(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)

    name_only = create_item(client, headers, name="  Pane   integrale  ")
    detailed = create_item(
        client,
        headers,
        name="Acqua naturale",
        quantity=3,
        note="Confezioni piccole",
        product_barcode="8001234567896",
    )

    assert name_only.status_code == 201
    assert name_only.json()["name"] == "Pane integrale"
    assert name_only.json()["quantity"] is None
    assert name_only.json()["note"] is None
    assert name_only.json()["product_barcode"] is None
    assert detailed.status_code == 201
    assert detailed.json()["quantity"] == 3
    assert detailed.json()["note"] == "Confezioni piccole"
    assert detailed.json()["product_barcode"] == "8001234567896"

    listed = client.get("/api/v1/shopping-list", headers=headers).json()
    assert [item["name"] for item in listed] == ["Acqua naturale", "Pane integrale"]
    assert all(item["is_completed"] is False for item in listed)


def test_name_is_required_and_quantity_must_be_positive(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)

    assert client.post("/api/v1/shopping-list", json={}, headers=headers).status_code == 422
    assert create_item(client, headers, name="   ").status_code == 422
    assert create_item(client, headers, quantity=0).status_code == 422


def test_update_complete_restore_and_delete(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers).json()

    updated = client.patch(
        f"/api/v1/shopping-list/{item['id']}",
        json={"name": "Latte intero", "quantity": 2, "note": "Senza lattosio"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Latte intero"
    assert updated.json()["quantity"] == 2
    assert updated.json()["note"] == "Senza lattosio"

    completed = client.patch(
        f"/api/v1/shopping-list/{item['id']}/status",
        json={"is_completed": True},
        headers=headers,
    )
    assert completed.status_code == 200
    assert completed.json()["is_completed"] is True
    assert completed.json()["completed_at"] is not None

    restored = client.patch(
        f"/api/v1/shopping-list/{item['id']}/status",
        json={"is_completed": False},
        headers=headers,
    )
    assert restored.status_code == 200
    assert restored.json()["is_completed"] is False
    assert restored.json()["completed_at"] is None

    assert client.delete(f"/api/v1/shopping-list/{item['id']}", headers=headers).status_code == 204
    assert client.get("/api/v1/shopping-list", headers=headers).json() == []


def test_items_are_isolated_by_household(client, registration_payload):
    owner = register(client, registration_payload, email="shopping-owner@example.com")
    stranger = register(client, registration_payload, email="shopping-stranger@example.com")
    item = create_item(client, auth(owner)).json()

    assert client.get("/api/v1/shopping-list", headers=auth(stranger)).json() == []
    assert client.patch(
        f"/api/v1/shopping-list/{item['id']}",
        json={"name": "Altro"},
        headers=auth(stranger),
    ).status_code == 404
    assert client.patch(
        f"/api/v1/shopping-list/{item['id']}/status",
        json={"is_completed": True},
        headers=auth(stranger),
    ).status_code == 404
    assert client.delete(
        f"/api/v1/shopping-list/{item['id']}", headers=auth(stranger)
    ).status_code == 404


def test_active_duplicates_are_merged_by_name_or_barcode(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)

    assert create_item(client, headers, name="  Mele ").status_code == 201
    merged_name = create_item(client, headers, name="mele", note="Rosse")
    assert merged_name.status_code == 200
    assert merged_name.json()["quantity"] == 2
    assert merged_name.json()["note"] == "Rosse"

    assert create_item(
        client, headers, name="Acqua", product_barcode="8001234567896", quantity=2
    ).status_code == 201
    merged_barcode = create_item(
        client, headers, name="Nome catalogo differente", product_barcode="8001234567896"
    )
    assert merged_barcode.status_code == 200
    assert merged_barcode.json()["name"] == "Acqua"
    assert merged_barcode.json()["quantity"] == 3

    completed = client.patch(
        f"/api/v1/shopping-list/{merged_name.json()['id']}/status",
        json={"is_completed": True},
        headers=headers,
    )
    assert completed.status_code == 200
    assert create_item(client, headers, name="MELE").status_code == 201
    assert len(client.get("/api/v1/shopping-list", headers=headers).json()) == 3


def test_shopping_actions_do_not_change_inventory_events_or_insights(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    inventory = client.post(
        "/api/v1/inventory",
        json={
            "product_barcode": "0801234567890",
            "quantity": 2,
            "expiry_date": None,
            "storage_location": "pantry",
        },
        headers=headers,
    )
    assert inventory.status_code == 201
    before_insights = client.get("/api/v1/insights/consumption", headers=headers).json()
    item = create_item(client, headers, name="Pasta", product_barcode="0801234567890").json()

    assert client.patch(
        f"/api/v1/shopping-list/{item['id']}/status",
        json={"is_completed": True},
        headers=headers,
    ).status_code == 200
    assert client.delete(f"/api/v1/shopping-list/{item['id']}", headers=headers).status_code == 204

    assert client.get("/api/v1/inventory", headers=headers).json()[0]["quantity"] == 2
    assert client.get("/api/v1/consumption-events", headers=headers).json() == []
    assert client.get("/api/v1/insights/consumption", headers=headers).json()["summary"] == before_insights["summary"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(InventoryItem)) == 1
        assert db.scalar(select(func.count()).select_from(ConsumptionEvent)) == 0
        assert db.scalar(select(func.count()).select_from(ShoppingListItem)) == 0
