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