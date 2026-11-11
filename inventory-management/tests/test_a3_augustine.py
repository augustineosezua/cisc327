from unittest.mock import patch


def _create_product(client, sku="LAMP-001", quantity=10, reorder_level=5):
    response = client.post("/products", json={
        "name": "Desk Lamp",
        "sku": sku,
        "unit_price": 20.0,
        "quantity_on_hand": quantity,
        "reorder_level": reorder_level,
    })
    assert response.status_code == 201
    return response.get_json()


def _create_supplier(client, name="Lamp Supplier", email="lamps@example.com"):
    response = client.post("/suppliers", json={
        "name": name,
        "contact_email": email,
    })
    assert response.status_code == 201
    return response.get_json()


def _stock(client, product):
    return client.get(f"/products/{product['id']}").get_json()["quantity_on_hand"]


# Coverage-directed tests: web UI routes in app/routes/views.py

def test_delete_product_via_ui_removes_only_that_product(client):
    product = _create_product(client)
    other = _create_product(client, sku="CHAIR-002")

    response = client.post(f"/ui/products/{product['id']}/delete")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/ui/products")
    page = client.get("/ui/products").get_data(as_text=True)
    assert "LAMP-001" not in page
    assert "CHAIR-002" in page
    assert client.get(f"/products/{product['id']}").status_code == 404
    assert client.get("/products").get_json() == [other]


def test_delete_missing_product_via_ui_changes_nothing(client):
    product = _create_product(client)

    response = client.post("/ui/products/999/delete", follow_redirects=True)

    # Deleting an unknown id is ignored; the user lands back on the list.
    assert response.status_code == 200
    assert "LAMP-001" in response.get_data(as_text=True)
    assert client.get("/products").get_json() == [product]


def test_delete_supplier_via_ui_removes_only_that_supplier(client):
    supplier = _create_supplier(client)
    other = _create_supplier(client, name="Chair Supplier", email="chairs@example.com")

    response = client.post(f"/ui/suppliers/{supplier['id']}/delete")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/ui/suppliers")
    page = client.get("/ui/suppliers").get_data(as_text=True)
    assert "lamps@example.com" not in page
    assert "chairs@example.com" in page
    assert client.get(f"/suppliers/{supplier['id']}").status_code == 404
    assert client.get("/suppliers").get_json() == [other]


def test_delete_missing_supplier_via_ui_changes_nothing(client):
    supplier = _create_supplier(client)

    response = client.post("/ui/suppliers/999/delete", follow_redirects=True)

    assert response.status_code == 200
    assert "lamps@example.com" in response.get_data(as_text=True)
    assert client.get("/suppliers").get_json() == [supplier]


def test_ui_in_transaction_with_supplier_adds_stock(client):
    product = _create_product(client)
    supplier = _create_supplier(client)

    # Form fields arrive as strings, including the optional supplier id.
    response = client.post("/ui/transactions", data={
        "product_id": str(product["id"]),
        "type": "IN",
        "quantity": "7",
        "supplier_id": str(supplier["id"]),
    }, follow_redirects=True)

    assert response.status_code == 200
    assert _stock(client, product) == 17
    transactions = client.get("/transactions").get_json()
    assert len(transactions) == 1
    assert transactions[0]["product_id"] == product["id"]
    assert transactions[0]["supplier_id"] == supplier["id"]
    assert transactions[0]["type"] == "IN"
    assert transactions[0]["quantity"] == 7
    # The delivery is now linked to the supplier.
    supplier_products = client.get(f"/suppliers/{supplier['id']}/products").get_json()
    assert [p["id"] for p in supplier_products] == [product["id"]]


def test_ui_transaction_for_missing_product_records_nothing(client):
    product = _create_product(client)

    response = client.post("/ui/transactions", data={
        "product_id": "999",
        "type": "IN",
        "quantity": "7",
        "supplier_id": "",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert _stock(client, product) == 10
    assert client.get("/transactions").get_json() == []


# Notification tests: failure and non-trigger paths

def test_low_stock_notification_failure_stub(client, monkeypatch):
    # Stub: force the notification service to report a failure.
    monkeypatch.setattr(
        "app.routes.transactions.send_notification",
        lambda recipient, subject, message: False,
    )
    product = _create_product(client, quantity=10, reorder_level=5)

    # Removing 5 leaves exactly the reorder level, so an alert is attempted.
    response = client.post("/transactions", json={
        "product_id": product["id"],
        "type": "OUT",
        "quantity": 5,
    })

    # A failed notification must not block the stock movement.
    assert response.status_code == 201
    assert response.headers["X-Notification-Status"] == "failed"
    transaction = response.get_json()
    assert transaction["product_id"] == product["id"]
    assert transaction["type"] == "OUT"
    assert transaction["quantity"] == 5
    assert _stock(client, product) == 5
    assert client.get("/transactions").get_json() == [transaction]


def test_no_notification_when_stock_stays_above_reorder_level(client):
    product = _create_product(client, quantity=10, reorder_level=5)

    with patch("app.routes.transactions.send_notification") as mock_send:
        # Removing 4 leaves 6, one above the reorder level.
        response = client.post("/transactions", json={
            "product_id": product["id"],
            "type": "OUT",
            "quantity": 4,
        })

        mock_send.assert_not_called()

    assert response.status_code == 201
    assert response.headers["X-Notification-Status"] == "not_required"
    assert _stock(client, product) == 6
    assert client.get("/transactions").get_json() == [response.get_json()]


def test_no_notification_for_in_transaction_below_reorder_level(client):
    # Stock already starts below the reorder level.
    product = _create_product(client, quantity=2, reorder_level=5)

    with patch("app.routes.transactions.send_notification") as mock_send:
        # Restocking to 3 is still low, but only OUT movements trigger alerts.
        response = client.post("/transactions", json={
            "product_id": product["id"],
            "type": "IN",
            "quantity": 1,
        })

        mock_send.assert_not_called()

    assert response.status_code == 201
    assert response.headers["X-Notification-Status"] == "not_required"
    assert _stock(client, product) == 3
    assert client.get("/transactions").get_json() == [response.get_json()]


def test_no_notification_when_out_transaction_rejected(client):
    product = _create_product(client, quantity=5, reorder_level=5)

    with patch("app.routes.transactions.send_notification") as mock_send:
        # Removing more than is on hand is rejected before any alert.
        response = client.post("/transactions", json={
            "product_id": product["id"],
            "type": "OUT",
            "quantity": 6,
        })

        mock_send.assert_not_called()

    assert response.status_code == 400
    assert response.get_json() == {"error": "Insufficient stock"}
    assert "X-Notification-Status" not in response.headers
    assert _stock(client, product) == 5
    assert client.get("/transactions").get_json() == []
