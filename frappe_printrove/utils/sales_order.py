import frappe
from frappe import _

def on_submit(doc, method=None):
    # Sales Order to Purchase Order Generation
    settings = frappe.get_single("Printrove Settings")
    if not settings.enable_printrove or not settings.supplier:
        return

    printrove_items = []
    total_weight = 0

    for item in doc.items:
        p_id = frappe.db.get_value("Item", item.item_code, "printrove_id")
        if p_id:
            printrove_items.append(item)
            # Fetch weight if set
            weight = frappe.db.get_value("Item", item.item_code, "weight_per_unit") or 0.2
            total_weight += weight * item.qty

    if not printrove_items:
        return

    try:
        api = settings.get_api()

        # Calculate Serviceability / Shipping Cost
        shipping_cost = 0
        shipping_address = None
        if doc.shipping_address_name:
            shipping_address = frappe.get_doc("Address", doc.shipping_address_name)

        if shipping_address and shipping_address.pincode:
            try:
                serviceability = api.get_serviceability(shipping_address.pincode, total_weight)
                options = serviceability.get("options", [])
                if options:
                    # Find cheapest
                    cheapest = min(options, key=lambda x: x.get("price", 0))
                    shipping_cost = cheapest.get("price", 0)
            except Exception:
                frappe.log_error(message=frappe.get_traceback(), title="Printrove Serviceability Check Failed")

        # Create PO
        po = frappe.new_doc("Purchase Order")
        po.company = doc.company
        po.supplier = settings.supplier
        po.schedule_date = doc.delivery_date

        for item in printrove_items:
            po.append(
                "items",
                {
                    "item_code": item.item_code,
                    "qty": item.qty,
                    "rate": item.rate,  # Or standard buying rate
                    "schedule_date": doc.delivery_date,
                    "warehouse": item.warehouse or frappe.get_cached_value("Company", doc.company, "default_warehouse"),
                    "sales_order": doc.name,
                    "sales_order_item": item.name,
                },
            )

        if shipping_cost > 0:
            shipping_item = frappe.db.get_single_value("Printrove Settings", "shipping_item") or "Printrove Shipping"
            if frappe.db.exists("Item", shipping_item):
                po.append(
                    "items",
                    {
                        "item_code": shipping_item,
                        "qty": 1,
                        "rate": shipping_cost,
                        "schedule_date": doc.delivery_date,
                        "warehouse": frappe.get_cached_value("Company", doc.company, "default_warehouse"),
                    },
                )

        po.insert(ignore_permissions=True)
        po.submit()

        # Push Order to Printrove
        try:
            order_products = []
            for item in printrove_items:
                p_id = frappe.db.get_value("Item", item.item_code, "printrove_id")
                try:
                    product_id = int(p_id) if p_id else None
                except (ValueError, TypeError):
                    product_id = p_id  # Keep as is if not int

                order_products.append({"product_id": product_id, "quantity": int(item.qty), "is_plain": False})

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
                    "address1": shipping_address.address_line1 if shipping_address else "",
                    "address2": shipping_address.address_line2 if shipping_address else "",
                    "city": shipping_address.city if shipping_address else "",
                    "state": shipping_address.state if shipping_address else "",
                    "pincode": shipping_address.pincode if shipping_address else "",
                    "country": shipping_address.country if shipping_address else "India",
                },
                "order_products": order_products,
                "cod": False,
            }

            pr_order = api.create_order(order_payload)
            pr_order_id = pr_order.get("id") if isinstance(pr_order, dict) else pr_order

            if pr_order_id:
                frappe.db.set_value("Purchase Order", po.name, "inter_company_order_reference", str(pr_order_id))

            frappe.msgprint(
                f"Automatically created Purchase Order <a href='/app/purchase-order/{po.name}'>{po.name}</a> for Printrove items."
            )
        except Exception:
            frappe.log_error(message=frappe.get_traceback(), title="Printrove API Order Push Failed")
            frappe.msgprint("Failed to push Order to Printrove. Check Error Log.")

    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="Printrove PO Generation Failed")
        frappe.msgprint("Failed to auto-generate Purchase Order for Printrove. Check Error Log.")
