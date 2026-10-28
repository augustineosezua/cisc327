# Inventory Management System (IMS)

A small Flask REST API for tracking products, suppliers, and stock transactions.
Data is stored **in memory** (plain Python objects, no database) and is reset
every time the app restarts — this project is meant to run before you've
covered databases.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

The API runs at `http://127.0.0.1:5000`.

## Web UI

Open `http://127.0.0.1:5000/` in a browser for a basic HTML front end (plain
forms and tables, no JavaScript) to add/delete products and suppliers, and
record stock transactions:

| Page | Path |
|---|---|
| Home | `/` |
| Products | `/ui/products` |
| Suppliers | `/ui/suppliers` |
| Transactions | `/ui/transactions` |

This UI is separate from the JSON API below — it's there so you can see the
app working without a REST client, and calls the same in-memory store.

## Entities

- **Product**: `id, name, sku, unit_price, quantity_on_hand`
- **Supplier**: `id, name, contact_email`
- **Transaction**: `id, product_id, supplier_id, type (IN/OUT), quantity, transaction_date`
- **PurchaseOrder**: `id, supplier_id, product_id, quantity_ordered, status,
  created_date, received_date, quantity_received, quantity_difference, clerk_id`

## JSON API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/products` | List all products |
| GET | `/products?sku=HAM-01` | Search by exact, case-sensitive SKU |
| GET | `/products?name=hammer` | Search by case-insensitive partial name |
| POST | `/products` | Create a product |
| GET | `/products/<id>` | Get one product |
| PUT | `/products/<id>` | Update a product |
| DELETE | `/products/<id>` | Delete a product |
| GET | `/products/<id>/stock-level` | Current quantity on hand |
| GET | `/suppliers` | List all suppliers |
| POST | `/suppliers` | Create a supplier |
| GET | `/suppliers/<id>` | Get one supplier |
| PUT | `/suppliers/<id>` | Update a supplier |
| DELETE | `/suppliers/<id>` | Delete a supplier |
| POST | `/transactions` | Record a stock movement (`product_id`, `type`: IN/OUT, `quantity`, optional `supplier_id`) |
| GET | `/transactions?product_id=&supplier_id=` | Look up transactions |
| POST | `/purchase-orders` | Create a pending order (`supplier_id`, `product_id`, `quantity_ordered`) |
| GET | `/purchase-orders` | List purchase orders, including receipt details |
| GET | `/purchase-orders/<id>` | Get a purchase order and its receipt details |
| PUT | `/purchase-orders/<id>/receive` | Receive actual units (`quantity_received`, optional `clerk_id`) and update stock |

## Product search (R3, R11)

Search results include the full product data, including `quantity_on_hand`.
For example, `?name=hammer` matches both `Claw Hammer` and `HAMMER Drill`.
SKU matching is exact: `?sku=HAM-01` does not match `HAM-010` or `ham-01`.
When both filters are supplied, a product must match both. No matches returns
`[]`; omitting the filters returns all products.

## Receiving a purchase order (R3, R4, R9)

Send a JSON body to `PUT /purchase-orders/<id>/receive`:

```json
{"quantity_received": 40, "clerk_id": "C7"}
```

For an order of 50 units, this adds **40** units to the product's existing stock
and records one IN transaction for 40. The response and subsequent PO GETs
retain `quantity_ordered: 50` and store `quantity_received: 40`,
`quantity_difference: 10`, `clerk_id: "C7"`, the receipt date (`YYYY-MM-DD`),
and `status: "received"`.

`quantity_difference` is ordered minus received: positive means a short
delivery, zero means a full delivery, and negative means extra units arrived.
Receipt fields are `null` while an order is pending. `clerk_id` is recorded when
supplied and otherwise remains `null`.

The received quantity must be a positive JSON integer. A missing quantity,
zero, negative number, fraction, boolean, or text value returns HTTP 400.
A missing or invalid JSON object also returns 400. An unknown order or an
order whose product was deleted returns 404. Rejection leaves the order,
inventory, and transaction history unchanged.

Each PO can be received once, including a short delivery. A repeated receive
returns 400 without adding stock or another transaction. Receiving without
a body is no longer supported; callers must provide `quantity_received`.

## Tests

```bash
python -m pytest -v
```

The tests in `tests/augustine-ivan-tests.py` cover search, receipt discrepancies,
stock updates, repeated receipts, and invalid quantities. `pytest.ini` includes
this filename in normal test discovery.
