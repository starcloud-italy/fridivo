from uuid import uuid4

import pytest


def register(client, payload, *, email=None):
    body = {**payload}
    if email is not None:
        body["email"] = email
        body["household_name"] = email
    response = client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 201
    return response.json()


def auth(user):
    return {"Authorization": f"Bearer {user['access_token']}"}


def item_payload(**overrides):
    return {
        "product_barcode": "0801234567890",
        "quantity": 2,
        "expiry_date": "2026-12-31",
        "storage_location": "pantry",
        **overrides,
    }


def create_item(client, headers, **overrides):
    response = client.post("/api/v1/inventory", json=item_payload(**overrides), headers=headers)
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("post", "/api/v1/inventory"),
        ("get", "/api/v1/inventory"),
        ("patch", f"/api/v1/inventory/{uuid4()}"),
        ("delete", f"/api/v1/inventory/{uuid4()}"),
    ),
)
def test_inventory_endpoints_require_authentication(client, method, path):
    kwargs = {"json": item_payload()} if method in {"post", "patch"} else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_add_valid_product(client, registration_payload):
    user = register(client, registration_payload)
    response = client.post(
        "/api/v1/inventory", json=item_payload(), headers=auth(user)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["household_id"]
    assert body["product_barcode"] == "0801234567890"
    assert body["quantity"] == 2
    assert body["expiry_date"] == "2026-12-31"
    assert body["storage_location"] == "pantry"
    assert body["product_name"] == "Pasta integrale"
    assert body["brands"] == "Fridivo Test"
    assert body["product_quantity"] == "500 g"
    assert body["image_url"] == "https://images.test/pasta.jpg"


def test_unknown_barcode_is_rejected(client, registration_payload):
    user = register(client, registration_payload)
    response = client.post(
        "/api/v1/inventory",
        json=item_payload(product_barcode="9999999999999"),
        headers=auth(user),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


@pytest.mark.parametrize("quantity", (0, -1, -100))
def test_quantity_must_be_positive(client, registration_payload, quantity):
    user = register(client, registration_payload)
    response = client.post(
        "/api/v1/inventory", json=item_payload(quantity=quantity), headers=auth(user)
    )
    assert response.status_code == 422


def test_expiry_date_is_optional(client, registration_payload):
    user = register(client, registration_payload)
    payload = item_payload()
    payload.pop("expiry_date")
    response = client.post("/api/v1/inventory", json=payload, headers=auth(user))
    assert response.status_code == 201
    assert response.json()["expiry_date"] is None


@pytest.mark.parametrize("location", ("fridge", "freezer", "pantry", "other"))
def test_valid_storage_locations(client, registration_payload, location):
    user = register(client, registration_payload)
    response = client.post(
        "/api/v1/inventory",
        json=item_payload(storage_location=location),
        headers=auth(user),
    )
    assert response.status_code == 201
    assert response.json()["storage_location"] == location


def test_invalid_storage_location(client, registration_payload):
    user = register(client, registration_payload)
    response = client.post(
        "/api/v1/inventory",
        json=item_payload(storage_location="garage"),
        headers=auth(user),
    )
    assert response.status_code == 422


def test_list_inventory_includes_product_information(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    create_item(client, headers)
    create_item(
        client,
        headers,
        product_barcode="8001234567896",
        quantity=4,
        expiry_date=None,
        storage_location="fridge",
    )

    response = client.get("/api/v1/inventory", headers=headers)

    assert response.status_code == 200
    assert len(response.json()) == 2
    products = {item["product_barcode"]: item for item in response.json()}
    assert products["0801234567890"]["product_name"] == "Pasta integrale"
    assert products["0801234567890"]["product_quantity"] == "500 g"
    assert products["8001234567896"]["product_name"] == "Acqua naturale"
    assert products["8001234567896"]["quantity"] == 4


def test_update_quantity(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers)

    response = client.patch(
        f"/api/v1/inventory/{item['id']}", json={"quantity": 7}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["quantity"] == 7


def test_update_and_clear_expiry_date(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers)

    updated = client.patch(
        f"/api/v1/inventory/{item['id']}",
        json={"expiry_date": "2027-01-15"},
        headers=headers,
    )
    cleared = client.patch(
        f"/api/v1/inventory/{item['id']}", json={"expiry_date": None}, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["expiry_date"] == "2027-01-15"
    assert cleared.status_code == 200
    assert cleared.json()["expiry_date"] is None


def test_update_storage_location(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers)

    response = client.patch(
        f"/api/v1/inventory/{item['id']}",
        json={"storage_location": "freezer"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["storage_location"] == "freezer"


def test_delete_inventory_item(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    item = create_item(client, headers)

    deleted = client.delete(f"/api/v1/inventory/{item['id']}", headers=headers)
    remaining = client.get("/api/v1/inventory", headers=headers)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert remaining.json() == []


@pytest.mark.parametrize("method", ("patch", "delete"))
def test_missing_inventory_item(client, registration_payload, method):
    user = register(client, registration_payload)
    kwargs = {"json": {"quantity": 2}} if method == "patch" else {}
    response = getattr(client, method)(
        f"/api/v1/inventory/{uuid4()}", headers=auth(user), **kwargs
    )
    assert response.status_code == 404


def test_duplicate_product_does_not_create_multiple_lots(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    create_item(client, headers)
    response = client.post(
        "/api/v1/inventory", json=item_payload(quantity=3), headers=headers
    )
    assert response.status_code == 409
    assert len(client.get("/api/v1/inventory", headers=headers).json()) == 1


def test_scanner_style_addition_increments_an_existing_inventory_item(client, registration_payload):
    user = register(client, registration_payload)
    headers = auth(user)
    existing = create_item(client, headers, quantity=2)

    scanned_quantity = 3
    response = client.patch(
        f"/api/v1/inventory/{existing['id']}",
        json={
            "quantity": existing["quantity"] + scanned_quantity,
            "storage_location": "pantry",
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["quantity"] == 5
    items = client.get("/api/v1/inventory", headers=headers).json()
    assert len(items) == 1
    assert items[0]["product_barcode"] == existing["product_barcode"]


def test_inventory_is_isolated_between_households(client, registration_payload):
    owner = register(client, registration_payload, email="owner@example.com")
    stranger = register(client, registration_payload, email="stranger@example.com")
    item = create_item(client, auth(owner))

    assert client.get("/api/v1/inventory", headers=auth(stranger)).json() == []
    patch = client.patch(
        f"/api/v1/inventory/{item['id']}",
        json={"quantity": 99},
        headers=auth(stranger),
    )
    delete = client.delete(f"/api/v1/inventory/{item['id']}", headers=auth(stranger))
    assert patch.status_code == 404
    assert delete.status_code == 404
    assert client.get("/api/v1/inventory", headers=auth(owner)).json()[0]["quantity"] == 2
