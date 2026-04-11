import frappe
from frappe import _
from frappe_printrove.utils.integration_request import create

def on_submit(doc, method=None):
    # Sales Order to Purchase Order Generation
    settings = frappe.get_single("Printrove Settings")
    if not settings.enable_printrove or not settings.supplier:
        return

    printrove_items = []
    total_weight = 0

    for item in doc.items:
        if not item.delivered_by_supplier:
            continue

        p_id = frappe.db.get_value("Item", item.item_code, "printrove_id")
        if p_id:
            # Only create PO if there is zero or negative stock across all warehouses
            actual_qty = frappe.db.sql("select sum(actual_qty) from `tabBin` where item_code=%s", item.item_code)[0][0] or 0
            if actual_qty <= 0:
                printrove_items.append(item)
                # Fetch weight if set
                weight = frappe.db.get_value("Item", item.item_code, "weight_per_unit") or 0.2
                total_weight += weight * item.qty

    if not printrove_items:
        return

    try:
        shipping_address = None
        if doc.shipping_address_name:
            shipping_address = frappe.get_doc("Address", doc.shipping_address_name)

        # Push Order to Printrove
        order_products = []
        for item in printrove_items:
            p_id = frappe.db.get_value("Item", item.item_code, "printrove_id")
            try:
                variant_id = int(p_id) if p_id else None
            except (ValueError, TypeError):
                variant_id = p_id  # Keep as is if not int

            order_products.append({"variant_id": variant_id, "quantity": int(item.qty), "is_plain": False})

        order_payload = {
            "reference_number": doc.name,
            "retail_price": doc.total,
            "customer": {
                "name": doc.customer_name,
                "email": doc.contact_email or "no-email@example.com",
                "number": (
                    shipping_address.phone
                    if shipping_address and shipping_address.phone
                    else 9999999999
                ),
                "address1": (shipping_address.address_line1 if shipping_address and shipping_address.address_line1 else "No Address")[:50],
                "city": shipping_address.city if shipping_address else "Unknown",
                "state": shipping_address.state if shipping_address else "Unknown",
                "pincode": int(shipping_address.pincode) if shipping_address and shipping_address.pincode and shipping_address.pincode.isdigit() else 000000,
                "country": shipping_address.country if shipping_address else "India",
            },
            "order_products": order_products,
            "cod": False,
            "_total_weight": total_weight  # Custom key for integration worker
        }
        
        if shipping_address and shipping_address.address_line2:
            order_payload["customer"]["address2"] = shipping_address.address_line2[:50]

        req = create("Sales Order", doc.name, "Create Order", order_payload)
        
        frappe.enqueue(
            "frappe_printrove.utils.integration_request.process",
            queue="long",
            integration_request_name=req.name,
            now=frappe.flags.in_test
        )

        frappe.msgprint(_("Printrove fulfillment has been queued. A Purchase Order will be generated shortly."))

    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="Printrove PO Generation Failed")
        frappe.msgprint("Failed to queue Purchase Order for Printrove. Check Error Log.")

