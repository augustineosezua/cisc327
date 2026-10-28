import pytest


def _get_json(client, path, **kwargs):
    response = client.get(path, **kwargs)
    assert response.status_code == 200
    return response.get_json()


def _assert_error(response, status):
    assert response.status_code == status
    assert response.is_json
    assert response.get_json()["error"]


def _create(client, path, **data):
    response = client.post(path, json=data)
    assert response.status_code == 201
    result = response.get_json()
    assert {key: result[key] for key in data} == data
    return result


def _product(client, **changes):
    data = dict(name="Desk Lamp", sku="LAMP-001", unit_price=24.50,
                quantity_on_hand=10, reorder_level=2)
    return _create(client, "/products", **(data | changes))


# Home page

def test_home_page_links_to_all_sections(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Inventory Management System" in html
    for section in ("Products", "Suppliers", "Transactions"):
        path = f"/ui/{section.lower()}"
        assert f'href="{path}"' in html
        assert section in html
        destination = client.get(path)
        assert destination.status_code == 200
        assert f"<h1>{section}</h1>" in destination.get_data(as_text=True)


# Products

def test_list_products_returns_all_created(client):
    first = _product(client)
    second = _product(client, name="Chair", sku="CHAIR-002", unit_price=80.0)
    products = _get_json(client, "/products")
    assert sorted(products, key=lambda item: item["id"]) == [first, second]


def test_create_product_persists_all_fields(client):
    product = _product(client, quantity_on_hand=25, reorder_level=5)
    assert _get_json(client, f"/products/{product['id']}") == product


def test_create_product_via_ui_form(client):
    data = dict(name="Form Lamp", sku="FORM-001", unit_price=12.75, quantity_on_hand=8)
    response = client.post("/ui/products", data=data, follow_redirects=True)
    assert response.status_code == 200
    assert "Form Lamp" in response.get_data(as_text=True)
    products = _get_json(client, "/products")
    assert len(products) == 1
    assert products[0] == dict(id=products[0]["id"], reorder_level=0, **data)


def test_create_product_missing_sku_rejected(client, monkeypatch):
    existing = _product(client)
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)
    response = client.post("/products", json={
        "name": "No SKU", "unit_price": 5.0, "quantity_on_hand": 1,
    })
    _assert_error(response, 400)
    assert _get_json(client, "/products") == [existing]


@pytest.mark.parametrize("quantity", [-1, "many"], ids=["negative", "text"])
def test_create_product_invalid_quantity_rejected(client, quantity):
    existing = _product(client)
    response = client.post("/products", json={
        "name": "Invalid", "sku": "BAD-001", "quantity_on_hand": quantity,
    })
    _assert_error(response, 400)
    assert _get_json(client, "/products") == [existing]


def test_duplicate_sku_rejected(client):
    existing = _product(client)
    response = client.post("/products", json={
        "name": "Different Lamp", "sku": existing["sku"], "quantity_on_hand": 3,
    })
    assert response.status_code in (400, 409)
    assert response.get_json()["error"]
    assert _get_json(client, "/products") == [existing]
    assert _get_json(client, f"/products/{existing['id']}") == existing


def test_get_nonexistent_product_returns_404(client):
    existing = _product(client)
    _assert_error(client.get("/products/9999"), 404)
    assert _get_json(client, "/products") == [existing]


def test_update_product_changes_only_given_fields(client):
    product = _product(client)
    expected = {**product, "name": "Renamed Lamp"}
    response = client.put(f"/products/{product['id']}", json={"name": expected["name"]})
    assert response.status_code == 200
    assert response.get_json() == expected
    assert _get_json(client, f"/products/{product['id']}") == expected


def test_update_nonexistent_product_returns_404(client):
    existing = _product(client)
    _assert_error(client.put("/products/9999", json={"name": "Ghost"}), 404)
    assert _get_json(client, "/products") == [existing]


def test_delete_product_removes_it(client):
    product = _product(client)
    other = _product(client, name="Chair", sku="CHAIR-002")
    response = client.delete(f"/products/{product['id']}")
    assert response.status_code == 204
    _assert_error(client.get(f"/products/{product['id']}"), 404)
    assert _get_json(client, "/products") == [other]


def test_delete_product_twice_returns_404(client):
    product = _product(client)
    url = f"/products/{product['id']}"
    assert client.delete(url).status_code == 204
    _assert_error(client.delete(url), 404)
    assert _get_json(client, "/products") == []
