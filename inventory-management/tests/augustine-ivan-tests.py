from datetime import date

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


def _assert_stock(client, product, quantity):
    assert _get_json(client, f"/products/{product['id']}/stock-level") == {
        "product_id": product["id"], "quantity_on_hand": quantity,
    }
    assert _get_json(client, f"/products/{product['id']}") == {
        **product, "quantity_on_hand": quantity,
    }


def _transaction(client, product, kind, quantity, supplier=None):
    return _create(client, "/transactions", product_id=product["id"],
                   type=kind, quantity=quantity,
                   supplier_id=supplier["id"] if supplier else None)


def _supplier(client, **changes):
    data = dict(name="Lamp Supplier", contact_email="lamps@example.com")
    return _create(client, "/suppliers", **(data | changes))


def _purchase_order(client, product, supplier, quantity=20):
    return _create(client, "/purchase-orders", product_id=product["id"],
                   supplier_id=supplier["id"], quantity_ordered=quantity)


def _assert_receipt_transaction(client, order, quantity):
    history = _get_json(client, "/transactions")
    expected = dict(product_id=order["product_id"], supplier_id=order["supplier_id"],
                    type="IN", quantity=quantity)
    assert len(history) == 1
    assert {key: history[0][key] for key in expected} == expected
    return history


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


# Stock level and low stock

def test_stock_level_matches_product_quantity(client):
    product = _product(client, quantity_on_hand=25)
    _assert_stock(client, product, 25)


def test_stock_level_nonexistent_product_404(client):
    product = _product(client)
    _assert_error(client.get("/products/9999/stock-level"), 404)
    _assert_stock(client, product, 10)


def test_low_stock_includes_product_at_threshold(client):
    at_threshold = _product(client, quantity_on_hand=5, reorder_level=5)
    below = _product(client, sku="LOW-002", quantity_on_hand=4, reorder_level=5)
    flagged = _get_json(client, "/products/low-stock")
    assert sorted(flagged, key=lambda item: item["id"]) == [at_threshold, below]


def test_low_stock_excludes_product_above_threshold(client):
    above = _product(client, quantity_on_hand=6, reorder_level=5)
    low = _product(client, sku="LOW-002", quantity_on_hand=1, reorder_level=5)
    assert _get_json(client, "/products/low-stock") == [low]
    _assert_stock(client, above, 6)


def test_low_stock_updates_after_removal(client):
    product = _product(client, quantity_on_hand=7, reorder_level=5)
    assert _get_json(client, "/products/low-stock") == []
    transaction = _transaction(client, product, "OUT", 2)
    assert _get_json(client, "/products/low-stock") == [
        {**product, "quantity_on_hand": 5},
    ]
    _assert_stock(client, product, 5)
    assert _get_json(client, "/transactions") == [transaction]


# Stock movements

def test_stock_increases_after_in_transaction(client):
    product = _product(client)
    other = _product(client, sku="OTHER-002")
    transaction = _transaction(client, product, "IN", 7)
    _assert_stock(client, product, 17)
    _assert_stock(client, other, 10)
    assert _get_json(client, "/transactions") == [transaction]


def test_stock_decreases_after_out_transaction(client):
    product = _product(client)
    other = _product(client, sku="OTHER-002")
    first = _transaction(client, product, "OUT", 4)
    _assert_stock(client, product, 6)
    second = _transaction(client, product, "OUT", 6)
    _assert_stock(client, product, 0)
    _assert_stock(client, other, 10)
    assert _get_json(client, "/transactions") == [first, second]


def test_stock_cannot_go_negative(client):
    product = _product(client)
    accepted = _transaction(client, product, "OUT", 4)
    _assert_stock(client, product, 6)
    response = client.post("/transactions", json={
        "product_id": product["id"], "type": "OUT", "quantity": 7,
    })
    _assert_error(response, 400)
    _assert_stock(client, product, 6)
    assert _get_json(client, "/transactions") == [accepted]


@pytest.mark.parametrize("tx_type", ["IN", "OUT"])
@pytest.mark.parametrize("quantity", [0, -5], ids=["zero", "negative"])
def test_transaction_zero_or_negative_quantity_rejected(client, tx_type, quantity):
    product = _product(client)
    response = client.post("/transactions", json={
        "product_id": product["id"], "type": tx_type, "quantity": quantity,
    })
    _assert_error(response, 400)
    _assert_stock(client, product, 10)
    assert _get_json(client, "/transactions") == []


def test_transaction_invalid_type_rejected(client):
    product = _product(client)
    response = client.post("/transactions", json={
        "product_id": product["id"], "type": "SIDEWAYS", "quantity": 3,
    })
    _assert_error(response, 400)
    _assert_stock(client, product, 10)
    assert _get_json(client, "/transactions") == []


def test_transaction_nonexistent_product_404(client):
    product = _product(client)
    response = client.post("/transactions", json={
        "product_id": 9999, "type": "IN", "quantity": 3,
    })
    _assert_error(response, 404)
    _assert_stock(client, product, 10)
    assert _get_json(client, "/transactions") == []


def test_record_transaction_via_ui_form(client):
    product = _product(client)
    data = dict(product_id=product["id"], type="OUT", quantity=3, supplier_id="")
    response = client.post("/ui/transactions", data=data, follow_redirects=True)
    assert response.status_code == 200
    _assert_stock(client, product, 7)
    history = _get_json(client, "/transactions")
    assert len(history) == 1
    assert {key: history[0][key] for key in data} == data | {"supplier_id": None}


# Suppliers

def test_list_suppliers_returns_all_created(client):
    first = _supplier(client)
    second = _supplier(client, name="Chair Supplier", contact_email="chairs@example.com")
    suppliers = _get_json(client, "/suppliers")
    assert sorted(suppliers, key=lambda item: item["id"]) == [first, second]


def test_get_nonexistent_supplier_returns_404(client):
    existing = _supplier(client)
    _assert_error(client.get("/suppliers/9999"), 404)
    assert _get_json(client, "/suppliers") == [existing]


def test_create_supplier_persists_fields(client):
    supplier = _supplier(client)
    assert _get_json(client, f"/suppliers/{supplier['id']}") == supplier


def test_create_supplier_via_ui_form(client):
    payload = {"name": "Form Supplier", "contact_email": "form@example.com"}
    response = client.post("/ui/suppliers", data=payload, follow_redirects=True)
    assert response.status_code == 200
    assert "Form Supplier" in response.get_data(as_text=True)
    suppliers = _get_json(client, "/suppliers")
    assert len(suppliers) == 1
    supplier = suppliers[0]
    assert supplier == {"id": supplier["id"], **payload}
    assert _get_json(client, f"/suppliers/{supplier['id']}") == supplier


def test_create_supplier_missing_email_rejected(client, monkeypatch):
    existing = _supplier(client)
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)
    response = client.post("/suppliers", json={"name": "Missing Email"})
    _assert_error(response, 400)
    assert _get_json(client, "/suppliers") == [existing]


def test_update_supplier_changes_only_given_fields(client):
    supplier = _supplier(client)
    expected = {**supplier, "name": "Renamed Supplier"}
    response = client.put(f"/suppliers/{supplier['id']}", json={"name": expected["name"]})
    assert response.status_code == 200
    assert response.get_json() == expected
    assert _get_json(client, f"/suppliers/{supplier['id']}") == expected


def test_delete_supplier_removes_it(client):
    supplier = _supplier(client)
    other = _supplier(client, name="Other Supplier", contact_email="other@example.com")
    response = client.delete(f"/suppliers/{supplier['id']}")
    assert response.status_code == 204
    _assert_error(client.get(f"/suppliers/{supplier['id']}"), 404)
    assert _get_json(client, "/suppliers") == [other]


def test_delete_nonexistent_supplier_returns_404(client):
    existing = _supplier(client)
    _assert_error(client.delete("/suppliers/9999"), 404)
    assert _get_json(client, "/suppliers") == [existing]


def test_supplier_products_lists_received_products(client):
    supplier = _supplier(client)
    other_supplier = _supplier(client, name="Other", contact_email="other@example.com")
    delivered = _product(client)
    other_delivery = _product(client, sku="OTHER-002")
    out_only = _product(client, sku="OUT-003")
    _transaction(client, delivered, "IN", 3, supplier)
    _transaction(client, delivered, "IN", 2, supplier)
    _transaction(client, other_delivery, "IN", 4, other_supplier)
    _transaction(client, out_only, "OUT", 1, supplier)
    assert _get_json(client, f"/suppliers/{supplier['id']}/products") == [
        {**delivered, "quantity_on_hand": 15},
    ]


def test_supplier_products_empty_when_no_deliveries(client):
    supplier = _supplier(client)
    other = _supplier(client, name="Other", contact_email="other@example.com")
    product = _product(client)
    _transaction(client, product, "IN", 3, other)
    assert _get_json(client, f"/suppliers/{supplier['id']}/products") == []
    assert _get_json(client, f"/suppliers/{supplier['id']}") == supplier


# Transaction lookup

def test_filter_transactions_by_supplier(client):
    supplier = _supplier(client)
    other = _supplier(client, name="Other", contact_email="other@example.com")
    product = _product(client)
    first = _transaction(client, product, "IN", 3, supplier)
    unrelated = _transaction(client, product, "IN", 4, other)
    second = _transaction(client, product, "IN", 2, supplier)
    results = _get_json(client, "/transactions", query_string={"supplier_id": supplier["id"]})
    assert results == [first, second]
    assert _get_json(client, "/transactions") == [first, unrelated, second]


def test_filter_transactions_by_product(client):
    product = _product(client)
    other_product = _product(client, sku="OTHER-002")
    first_supplier = _supplier(client)
    second_supplier = _supplier(client, name="Other", contact_email="other@example.com")
    # Cross IDs to catch filtering on supplier_id instead of product_id.
    assert product["id"] != second_supplier["id"]
    assert product["id"] == first_supplier["id"]
    first = _transaction(client, product, "IN", 3, second_supplier)
    unrelated = _transaction(client, other_product, "IN", 4, first_supplier)
    second = _transaction(client, product, "OUT", 2)
    results = _get_json(client, "/transactions", query_string={"product_id": product["id"]})
    assert results == [first, second]
    assert _get_json(client, "/transactions") == [first, unrelated, second]


# Purchase orders

def test_create_purchase_order_is_pending(client):
    product = _product(client)
    supplier = _supplier(client)
    order = _purchase_order(client, product, supplier)
    assert order["status"] == "pending"
    assert order["received_date"] is None
    assert order["quantity_received"] is None
    assert order["quantity_difference"] is None
    assert order["clerk_id"] is None
    assert order["created_date"]
    assert _get_json(client, f"/purchase-orders/{order['id']}") == order
    assert _get_json(client, "/purchase-orders") == [order]
    _assert_stock(client, product, 10)
    assert _get_json(client, "/transactions") == []


@pytest.mark.parametrize("missing_field", ["supplier_id", "product_id"])
def test_create_po_nonexistent_supplier_or_product_404(client, missing_field):
    product = _product(client)
    supplier = _supplier(client)
    payload = {
        "product_id": product["id"], "supplier_id": supplier["id"],
        "quantity_ordered": 20,
    }
    payload[missing_field] = 9999
    _assert_error(client.post("/purchase-orders", json=payload), 404)
    assert _get_json(client, "/purchase-orders") == []
    assert _get_json(client, "/transactions") == []
    _assert_stock(client, product, 10)
    assert _get_json(client, f"/suppliers/{supplier['id']}") == supplier


def test_list_purchase_orders_returns_all(client):
    product = _product(client)
    other = _product(client, sku="OTHER-002")
    supplier = _supplier(client)
    first = _purchase_order(client, product, supplier, quantity=20)
    second = _purchase_order(client, other, supplier, quantity=7)
    orders = _get_json(client, "/purchase-orders")
    assert sorted(orders, key=lambda item: item["id"]) == [first, second]


def test_get_nonexistent_po_returns_404(client):
    product = _product(client)
    supplier = _supplier(client)
    order = _purchase_order(client, product, supplier)
    _assert_error(client.get("/purchase-orders/9999"), 404)
    assert _get_json(client, "/purchase-orders") == [order]


@pytest.mark.parametrize("quantity", [20, 25], ids=["full", "extra"])
def test_receive_purchase_order_updates_stock(client, quantity):
    product = _product(client)
    order = _purchase_order(client, product, _supplier(client))
    url = f"/purchase-orders/{order['id']}"
    response = client.put(f"{url}/receive", json={"quantity_received": quantity, "clerk_id": "C7"})
    assert response.status_code == 200
    received = response.get_json()
    assert received["status"] == "received"
    assert received["received_date"]
    assert received["quantity_received"] == quantity
    assert received["quantity_difference"] == 20 - quantity
    assert received["clerk_id"] == "C7"
    assert _get_json(client, url) == received
    _assert_receipt_transaction(client, order, quantity)
    _assert_stock(client, product, 10 + quantity)


def test_receive_purchase_order_twice_rejected(client):
    product = _product(client)
    order = _purchase_order(client, product, _supplier(client))
    url = f"/purchase-orders/{order['id']}"
    first = client.put(f"{url}/receive", json={"quantity_received": 20, "clerk_id": "C7"})
    assert first.status_code == 200
    history = _assert_receipt_transaction(client, order, 20)
    stock = _get_json(client, f"/products/{product['id']}")["quantity_on_hand"]
    repeat = client.put(f"{url}/receive", json={"quantity_received": 5, "clerk_id": "C8"})
    _assert_error(repeat, 400)
    assert _get_json(client, url) == first.get_json()
    assert _get_json(client, "/transactions") == history
    _assert_stock(client, product, stock)


def test_receive_partial_purchase_order(client):
    product = _product(client)
    order = _purchase_order(client, product, _supplier(client), quantity=50)
    url = f"/purchase-orders/{order['id']}"
    response = client.put(f"{url}/receive", json={"quantity_received": 40, "clerk_id": "C7"})
    assert response.status_code == 200
    received = response.get_json()
    assert received == order | {
        "status": "received", "quantity_received": 40, "quantity_difference": 10,
        "received_date": date.today().isoformat(), "clerk_id": "C7",
    }
    assert _get_json(client, url) == received
    assert _get_json(client, "/purchase-orders") == [received]
    _assert_stock(client, product, 50)
    _assert_receipt_transaction(client, order, 40)


@pytest.mark.parametrize("payload", [
    {}, {"quantity_received": 0}, {"quantity_received": -5},
    {"quantity_received": None}, {"quantity_received": "40"},
    {"quantity_received": 1.5}, {"quantity_received": True}, [], None,
], ids=["missing", "zero", "negative", "null", "text", "fraction", "boolean", "list", "no-body"])
def test_receive_invalid_quantity_preserves_state(client, payload):
    product = _product(client)
    order = _purchase_order(client, product, _supplier(client))
    url = f"/purchase-orders/{order['id']}"
    _assert_error(client.put(f"{url}/receive", json=payload), 400)
    assert _get_json(client, url) == order
    _assert_stock(client, product, 10)
    assert _get_json(client, "/transactions") == []


def test_receive_order_with_deleted_product_preserves_state(client):
    product = _product(client)
    order = _purchase_order(client, product, _supplier(client))
    assert client.delete(f"/products/{product['id']}").status_code == 204
    url = f"/purchase-orders/{order['id']}"
    response = client.put(f"{url}/receive", json={"quantity_received": 20, "clerk_id": "C7"})
    _assert_error(response, 404)
    assert _get_json(client, url) == order
    assert _get_json(client, "/transactions") == []
