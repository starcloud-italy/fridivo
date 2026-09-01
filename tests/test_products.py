import pytest


def authenticated_headers(client, registration_payload):
    response = client.post("/api/v1/auth/register", json=registration_payload)
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/products/barcode/0801234567890",
        "/api/v1/products/0801234567890",
        "/api/v1/products/search?q=pasta",
    ),
)
def test_product_endpoints_require_authentication(client, path):
    assert client.get(path).status_code == 401


def test_barcode_lookup_preserves_leading_zeroes(client, registration_payload):
    response = client.get(
        "/api/v1/products/barcode/0801234567890",
        headers=authenticated_headers(client, registration_payload),
    )

    assert response.status_code == 200
    assert response.json() == {
        "barcode": "0801234567890",
        "name": "Pasta integrale",
        "brands": "Fridivo Test",
        "quantity": "500 g",
        "categories": "Pasta, Cereals",
        "image_url": "https://images.test/pasta.jpg",
        "nutriscore_grade": "a",
    }


def test_barcode_lookup_returns_404_for_unknown_product(client, registration_payload):
    response = client.get(
        "/api/v1/products/barcode/9999999999999",
        headers=authenticated_headers(client, registration_payload),
    )
    assert response.status_code == 404


@pytest.mark.parametrize("barcode", ("123", "1234567x90123", "123456789012345"))
def test_barcode_validation(client, registration_payload, barcode):
    response = client.get(
        f"/api/v1/products/barcode/{barcode}",
        headers=authenticated_headers(client, registration_payload),
    )
    assert response.status_code == 422


def test_product_detail(client, registration_payload):
    response = client.get(
        "/api/v1/products/4001234567890",
        headers=authenticated_headers(client, registration_payload),
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Dark chocolate"
    assert response.json()["barcode"] == "4001234567890"


def test_text_search_is_case_insensitive(client, registration_payload):
    response = client.get(
        "/api/v1/products/search",
        params={"q": "PASTA"},
        headers=authenticated_headers(client, registration_payload),
    )

    assert response.status_code == 200
    assert response.json()["limit"] == 20
    assert response.json()["offset"] == 0
    assert [item["name"] for item in response.json()["items"]] == [
        "Pasta integrale",
        "Salsa per pasta",
    ]


def test_text_search_pagination_and_literal_wildcards(client, registration_payload):
    headers = authenticated_headers(client, registration_payload)
    first_page = client.get(
        "/api/v1/products/search",
        params={"q": "pasta", "limit": 1, "offset": 0},
        headers=headers,
    )
    second_page = client.get(
        "/api/v1/products/search",
        params={"q": "pasta", "limit": 1, "offset": 1},
        headers=headers,
    )
    wildcard = client.get(
        "/api/v1/products/search", params={"q": "%%"}, headers=headers
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json()["items"][0]["barcode"] != second_page.json()["items"][0]["barcode"]
    assert wildcard.status_code == 200
    assert wildcard.json()["items"] == []


@pytest.mark.parametrize(
    "params",
    ({"q": "x"}, {"q": "   "}, {"q": "pasta", "limit": 101}, {"q": "pasta", "offset": -1}),
)
def test_search_input_validation(client, registration_payload, params):
    response = client.get(
        "/api/v1/products/search",
        params=params,
        headers=authenticated_headers(client, registration_payload),
    )
    assert response.status_code == 422

