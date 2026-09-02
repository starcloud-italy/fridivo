from uuid import uuid4

import pytest
from sqlalchemy.orm import Session


def register(client, payload, *, email=None):
    body = {**payload}
    if email:
        body["email"] = email
        body["household_name"] = email
    response = client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 201
    return response.json()


def auth(user):
    return {"Authorization": f"Bearer {user['access_token']}"}


def create_item(client, headers, *, quantity=4, barcode="0801234567890"):
    response = client.post(
        "/api/v1/inventory",
        json={
            "product_barcode": barcode,
            "quantity": quantity,
            "expiry_date": None,
            "storage_location": "pantry",
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def create_event(client, headers, item_id, event_type, quantity=None):
    payload = {"inventory_item_id": item_id, "event_type": event_type}
    if quantity is not None:
        payload["quantity"] = quantity
    return client.post("/api/v1/consumption-events", json=payload, headers=headers)


def test_consumption_endpoints_require_authentication(client):
    assert client.get("/api/v1/consumption-events").status_code == 401
    response = client.post(
        "/api/v1/consumption-events",
        json={"inventory_item_id": str(uuid4()), "event_type": "FINISHED"},
    )
    assert response.status_code == 401


def test_consumed_event_decrements_inventory(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers, quantity=4)

    response = create_event(client, headers, item["id"], "CONSUMED", 1)

    assert response.status_code == 201
    assert response.json()["event_type"] == "CONSUMED"
    assert response.json()["quantity"] == 1
    assert response.json()["product_barcode"] == item["product_barcode"]
    assert response.json()["product_name"] == "Pasta integrale"
    assert client.get("/api/v1/inventory", headers=headers).json()[0]["quantity"] == 3


def test_discarded_event_decrements_and_can_remove_inventory(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers, quantity=2)

    first = create_event(client, headers, item["id"], "DISCARDED", 1)
    second = create_event(client, headers, item["id"], "DISCARDED", 1)

    assert first.status_code == 201
    assert second.status_code == 201
    assert client.get("/api/v1/inventory", headers=headers).json() == []
    assert len(client.get("/api/v1/consumption-events", headers=headers).json()) == 2


def test_finished_records_all_remaining_quantity_and_removes_item(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers, quantity=3)

    response = create_event(client, headers, item["id"], "FINISHED")

    assert response.status_code == 201
    assert response.json()["quantity"] == 3
    assert client.get("/api/v1/inventory", headers=headers).json() == []
    assert client.get("/api/v1/consumption-events", headers=headers).json()[0]["event_type"] == "FINISHED"


@pytest.mark.parametrize("quantity", (0, -1))
def test_consumed_and_discarded_quantities_must_be_positive(client, registration_payload, quantity):
    user = register(client, registration_payload)
    item = create_item(client, auth(user))
    response = create_event(client, auth(user), item["id"], "CONSUMED", quantity)
    assert response.status_code == 422


def test_cannot_consume_more_than_available_and_no_event_is_created(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers, quantity=2)

    response = create_event(client, headers, item["id"], "CONSUMED", 3)

    assert response.status_code == 409
    assert client.get("/api/v1/inventory", headers=headers).json()[0]["quantity"] == 2
    assert client.get("/api/v1/consumption-events", headers=headers).json() == []


def test_finished_rejects_an_explicit_quantity(client, registration_payload):
    user = register(client, registration_payload)
    item = create_item(client, auth(user))
    assert create_event(client, auth(user), item["id"], "FINISHED", 1).status_code == 422


def test_events_are_isolated_by_household(client, registration_payload):
    owner = register(client, registration_payload, email="event-owner@example.com")
    stranger = register(client, registration_payload, email="event-stranger@example.com")
    item = create_item(client, auth(owner))

    assert create_event(client, auth(stranger), item["id"], "FINISHED").status_code == 404
    assert client.get("/api/v1/consumption-events", headers=auth(stranger)).json() == []
    assert client.get("/api/v1/inventory", headers=auth(owner)).json()[0]["quantity"] == 4


def test_history_is_newest_first_and_survives_inventory_removal(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    first_item = create_item(client, headers, quantity=2)
    create_event(client, headers, first_item["id"], "CONSUMED", 1)
    create_event(client, headers, first_item["id"], "FINISHED")

    history = client.get("/api/v1/consumption-events", headers=headers).json()

    assert [event["event_type"] for event in history] == ["FINISHED", "CONSUMED"]
    assert all(event["product_name"] == "Pasta integrale" for event in history)
    assert client.get("/api/v1/inventory", headers=headers).json() == []


def test_manual_inventory_delete_does_not_create_consumption_event(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers)

    assert client.delete(f"/api/v1/inventory/{item['id']}", headers=headers).status_code == 204
    assert client.get("/api/v1/consumption-events", headers=headers).json() == []


def test_event_and_inventory_update_roll_back_together_on_commit_failure(
    client, registration_payload, monkeypatch
):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers, quantity=4)

    def fail_commit(_session):
        raise RuntimeError("forced commit failure")

    with monkeypatch.context() as context:
        context.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="forced commit failure"):
            create_event(client, headers, item["id"], "CONSUMED", 1)

    assert client.get("/api/v1/inventory", headers=headers).json()[0]["quantity"] == 4
    assert client.get("/api/v1/consumption-events", headers=headers).json() == []
