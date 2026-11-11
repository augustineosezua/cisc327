from unittest.mock import patch


def test_low_stock_notification_success_stub(client, monkeypatch):
    # Stub: force the notification service to report success.
    monkeypatch.setattr(
        "app.routes.transactions.send_notification",
        lambda recipient, subject, message: True,
    )

    product_response = client.post("/products", json={
        "name": "Desk Lamp",
        "sku": "STUB-001",
        "unit_price": 20.0,
        "quantity_on_hand": 10,
        "reorder_level": 5,
    })
    assert product_response.status_code == 201
    product = product_response.get_json()

    # Removing 6 leaves 4, below the reorder level.
    response = client.post("/transactions", json={
        "product_id": product["id"],
        "type": "OUT",
        "quantity": 6,
    })

    assert response.status_code == 201
    assert response.headers["X-Notification-Status"] == "sent"

    transaction = response.get_json()
    assert transaction["product_id"] == product["id"]
    assert transaction["type"] == "OUT"
    assert transaction["quantity"] == 6

    updated_product = client.get(
        f"/products/{product['id']}"
    ).get_json()
    assert updated_product["quantity_on_hand"] == 4

    # Confirm the transaction was actually stored.
    transactions = client.get("/transactions").get_json()
    assert transactions == [transaction]


def test_low_stock_notification_success_mock_at_threshold(client):
    product_response = client.post("/products", json={
        "name": "Desk Lamp",
        "sku": "MOCK-001",
        "unit_price": 20.0,
        "quantity_on_hand": 10,
        "reorder_level": 5,
    })
    assert product_response.status_code == 201
    product = product_response.get_json()

    with patch(
        "app.routes.transactions.send_notification",
        return_value=True,
    ) as mock_send:
        # Removing 5 leaves exactly the reorder level.
        response = client.post("/transactions", json={
            "product_id": product["id"],
            "type": "OUT",
            "quantity": 5,
        })

        mock_send.assert_called_once_with(
            "inventory-staff@example.com",
            "Low stock alert",
            "Product Desk Lamp (SKU: MOCK-001) has "
            "5 units remaining. Reorder level: 5.",
        )

    assert response.status_code == 201
    assert response.headers["X-Notification-Status"] == "sent"

    transaction = response.get_json()
    assert transaction["product_id"] == product["id"]
    assert transaction["type"] == "OUT"
    assert transaction["quantity"] == 5

    updated_product = client.get(
        f"/products/{product['id']}"
    ).get_json()
    assert updated_product["quantity_on_hand"] == 5

    transactions = client.get("/transactions").get_json()
    assert transactions == [transaction]

def test_update_missing_supplier_returns_404(client):
    # Create an existing supplier to check that it stays unchanged.
    created = client.post("/suppliers", json={
        "name": "Existing Supplier",
        "contact_email": "supplier@example.com",
    })
    assert created.status_code == 201
    supplier = created.get_json()
    assert supplier["id"] != 999

    response = client.put("/suppliers/999", json={
        "name": "Changed Name",
        "contact_email": "changed@example.com",
    })

    assert response.status_code == 404
    assert response.get_json() == {"error": "Supplier not found"}

    # The failed update must not create or modify a supplier.
    suppliers = client.get("/suppliers").get_json()
    assert suppliers == [supplier]


def test_products_for_missing_supplier_returns_404(client):
    created = client.post("/products", json={
        "name": "Desk Lamp",
        "sku": "MISSING-SUPPLIER-001",
        "unit_price": 20.0,
        "quantity_on_hand": 10,
        "reorder_level": 5,
    })
    assert created.status_code == 201
    product = created.get_json()

    response = client.get("/suppliers/999/products")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Supplier not found"}

    # The request must leave products unchanged and create no supplier.
    assert client.get("/products").get_json() == [product]
    assert client.get("/suppliers").get_json() == []


def test_receive_missing_purchase_order_returns_404(client):
    created = client.post("/products", json={
        "name": "Desk Lamp",
        "sku": "MISSING-ORDER-001",
        "unit_price": 20.0,
        "quantity_on_hand": 10,
        "reorder_level": 5,
    })
    assert created.status_code == 201
    product = created.get_json()

    response = client.put("/purchase-orders/999/receive", json={
        "quantity_received": 5,
    })

    assert response.status_code == 404
    assert response.get_json() == {
        "error": "Purchase order not found"
    }

    # Receiving a nonexistent order must not change stock or create records.
    updated_product = client.get(
        f"/products/{product['id']}"
    ).get_json()
    assert updated_product == product
    assert client.get("/transactions").get_json() == []
    assert client.get("/purchase-orders").get_json() == []