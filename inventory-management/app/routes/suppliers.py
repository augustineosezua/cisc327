from flask import Blueprint, jsonify, request

from app import store
from app.models.supplier import Supplier

suppliers_bp = Blueprint("suppliers", __name__, url_prefix="/suppliers")


@suppliers_bp.route("", methods=["GET"])
def list_suppliers():
    return jsonify([s.to_dict() for s in store.suppliers.values()])


@suppliers_bp.route("", methods=["POST"])
def create_supplier():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data.get("name") or not data.get("contact_email"):
        return jsonify({"error": "name and contact_email are required"}), 400
    supplier_id = store.next_id("supplier")
    supplier = Supplier(id=supplier_id, name=data["name"], contact_email=data["contact_email"])
    store.suppliers[supplier_id] = supplier
    return jsonify(supplier.to_dict()), 201


@suppliers_bp.route("/<int:supplier_id>", methods=["GET"])
def get_supplier(supplier_id):
    supplier = store.suppliers.get(supplier_id)
    if supplier is None:
        return jsonify({"error": "Supplier not found"}), 404
    return jsonify(supplier.to_dict())


@suppliers_bp.route("/<int:supplier_id>", methods=["PUT"])
def update_supplier(supplier_id):
    supplier = store.suppliers.get(supplier_id)
    if supplier is None:
        return jsonify({"error": "Supplier not found"}), 404
    data = request.get_json()
    supplier.name = data.get("name", supplier.name)
    supplier.contact_email = data.get("contact_email", supplier.contact_email)
    return jsonify(supplier.to_dict())


@suppliers_bp.route("/<int:supplier_id>", methods=["DELETE"])
def delete_supplier(supplier_id):
    supplier = store.suppliers.pop(supplier_id, None)
    if supplier is None:
        return jsonify({"error": "Supplier not found"}), 404
    return "", 204


@suppliers_bp.route("/<int:supplier_id>/products", methods=["GET"])
def supplier_products(supplier_id):
    """Return all products that have been received (IN transactions) from this supplier."""
    supplier = store.suppliers.get(supplier_id)
    if supplier is None:
        return jsonify({"error": "Supplier not found"}), 404

    product_ids = {
        t.product_id
        for t in store.transactions.values()
        if t.supplier_id == supplier_id and t.type == "IN"
    }
    products = [
        store.products[pid].to_dict()
        for pid in product_ids
        if pid in store.products
    ]
    return jsonify(products)
