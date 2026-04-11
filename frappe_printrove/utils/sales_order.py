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
        }
        
        if shipping_address and shipping_address.address_line2:
            order_payload["customer"]["address2"] = shipping_address.address_line2[:50]

        try:
            pr_order = api.create_order(order_payload)
            pr_order_id = pr_order.get("id") if isinstance(pr_order, dict) else pr_order
            order_cost = pr_order.get("order_cost") if isinstance(pr_order, dict) else 0

        except Exception as e:
            # Check if it's a 422 with order_cost (insufficient credits)
            # We can still extract order_cost if possible, but API wrapper throws error on 422
            frappe.log_error(message=frappe.get_traceback(), title="Printrove API Order Push Failed")
            frappe.msgprint("Failed to push Order to Printrove. Check Error Log.")
            return

        # Create PO
        po = frappe.new_doc("Purchase Order")
        po.company = doc.company
        po.supplier = settings.supplier
        po.schedule_date = doc.delivery_date
        
        total_item_qty = sum([item.qty for item in printrove_items])
        
        # If Printrove returned order_cost, distribute it across items. 
        # Subtract shipping_cost from order_cost to get item cost.
        item_cost_pool = order_cost - shipping_cost if order_cost > shipping_cost else 0
        rate_per_item = item_cost_pool / total_item_qty if total_item_qty > 0 else 0

        for item in printrove_items:
            po.append(
                "items",
                {
                    "item_code": item.item_code,
                    "qty": item.qty,
                    "rate": rate_per_item if order_cost else item.rate,  # Use calculated rate or fallback to Sales Order rate
                    "schedule_date": doc.delivery_date,
                    "warehouse": item.warehouse or frappe.get_cached_value("Company", doc.company, "default_warehouse"),
                    "sales_order": doc.name,
                    "sales_order_item": item.name,
                },
            )

        if shipping_cost > 0:
            shipping_account = frappe.db.get_single_value("Printrove Settings", "shipping_account")
            # Ensure the shipping account belongs to the PO's company
            if shipping_account:
                acct_company = frappe.db.get_value("Account", shipping_account, "company")
                if acct_company != doc.company:
                    shipping_account = None

            if not shipping_account:
                # Fallback to standard expense account if possible
                expense_accounts = frappe.db.get_all("Account", filters={"account_type": ["in", ["Expense Account", "Chargeable"]], "company": doc.company}, limit=1)
                if not expense_accounts:
                    expense_accounts = frappe.db.get_all("Account", filters={"name": ["like", "%Freight%"], "company": doc.company}, limit=1)
                shipping_account = expense_accounts[0].name if expense_accounts else None

            if shipping_account:
                po.append(
                    "taxes",
                    {
                        "charge_type": "Actual",
                        "account_head": shipping_account,
                        "tax_amount": shipping_cost,
                        "description": "Shipping and Delivery Expenses",
                        "add_deduct_tax": "Add"
                    }
                )

        if pr_order_id:
            po.printrove_order_id = str(pr_order_id)

        po.insert(ignore_permissions=True)
        po.submit()

        frappe.msgprint(
            f"Automatically created Purchase Order <a href='/app/purchase-order/{po.name}'>{po.name}</a> for Printrove items."
        )

    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="Printrove PO Generation Failed")
        frappe.msgprint("Failed to auto-generate Purchase Order for Printrove. Check Error Log.")

