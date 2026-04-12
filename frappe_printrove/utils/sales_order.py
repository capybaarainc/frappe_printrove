import frappe
from frappe import _
from frappe_printrove.utils.integration_request import create

def on_submit(doc, method=None):
    # Sales Order to Purchase Order Generation
    settings = frappe.get_single("Printrove Settings")
    if not settings.enable_printrove or not settings.supplier:
        return

    printrove_items = []
    items_needing_po = []
    total_weight = 0

    for item in doc.items:
        if not item.delivered_by_supplier:
            continue

        actual_qty = frappe.db.sql("select sum(actual_qty) from `tabBin` where item_code=%s", item.item_code)[0][0] or 0
        if actual_qty <= 0:
            printrove_items.append(item)
            
            # Check if this specific Sales Order Item has already been added to a Purchase Order
            already_ordered = frappe.db.exists("Purchase Order Item", {
                "sales_order": doc.name,
                "sales_order_item": item.name,
                "docstatus": ["!=", 2]
            })
            if not already_ordered:
                items_needing_po.append(item)
                
            weight = frappe.db.get_value("Item", item.item_code, "weight_per_unit") or 0.2
            total_weight += weight * item.qty

    if not printrove_items:
        return

    draft_po_name = None

    # Create Draft PO for any items that need it
    if items_needing_po:
        po = frappe.new_doc("Purchase Order")
        po.company = doc.company
        po.supplier = settings.supplier
        po.schedule_date = doc.delivery_date
        
        for item in items_needing_po:
            # use valuation_rate for draft PO cost
            rate = frappe.db.get_value("Item", item.item_code, "valuation_rate") or frappe.db.get_value("Item", item.item_code, "standard_rate") or 0
            po.append(
                "items",
                {
                    "item_code": item.item_code,
                    "qty": item.qty,
                    "rate": float(rate),
                    "schedule_date": doc.delivery_date,
                    "warehouse": item.warehouse or frappe.get_cached_value("Company", doc.company, "default_warehouse"),
                    "sales_order": doc.name,
                    "sales_order_item": item.name,
                },
            )
            
        po.insert(ignore_permissions=True)
        draft_po_name = po.name
        frappe.msgprint(_("Draft Purchase Order {0} created for Printrove items.").format(po.name))

    # Determine if ALL printrove items are ready to be sent to Printrove
    all_ready = True
    order_products = []
    for item in printrove_items:
        p_id = frappe.db.get_value("Item", item.item_code, "printrove_id")
        if not p_id:
            all_ready = False
            break
            
        try:
            variant_id = int(p_id) if p_id else None
        except (ValueError, TypeError):
            variant_id = p_id

        order_products.append({"variant_id": variant_id, "quantity": int(item.qty), "is_plain": False})

    if not all_ready:
        if items_needing_po:
            frappe.msgprint(_("Sync to Printrove is pending until all items have Printrove IDs."))
        return

    # Check if we already synced this Sales Order successfully or queued it
    existing_req = frappe.db.exists("Integration Request", {
        "reference_doctype": "Sales Order",
        "reference_docname": doc.name,
        "request_description": "Create Order",
        "status": ["in", ["Queued", "Processing", "Completed"]]
    })
    
    if existing_req:
        return

    # If we didn't just create a Draft PO, we need to find the existing one to update it
    if not draft_po_name:
        # Find the Draft PO that contains these items
        po_item = frappe.db.get_value("Purchase Order Item", {"sales_order": doc.name, "docstatus": 0}, "parent")
        if po_item:
            draft_po_name = po_item
        else:
            # If there's no Draft PO (maybe it was submitted manually?), we can't update costs
            # We'll just skip or log an error. Let's just return.
            return

    try:
        shipping_address = None
        if doc.shipping_address_name:
            shipping_address = frappe.get_doc("Address", doc.shipping_address_name)

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
            "_total_weight": total_weight,
            "_draft_po_name": draft_po_name
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

        frappe.msgprint(_("Printrove fulfillment has been queued. The Purchase Order will be updated shortly."))

    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="Printrove PO Generation Failed")
        frappe.msgprint("Failed to queue Purchase Order for Printrove. Check Error Log.")


