import frappe
import json

def create(reference_doctype, reference_docname, request_type, payload):
    doc = frappe.new_doc("Integration Request")
    doc.integration_request_service = "Printrove"
    doc.is_remote_request = 1
    doc.request_description = request_type
    doc.reference_doctype = reference_doctype
    doc.reference_docname = reference_docname
    doc.data = json.dumps(payload)
    doc.status = "Queued"
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc

def process(integration_request_name):
    frappe.db.commit() # ensure latest state
    doc = frappe.get_doc("Integration Request", integration_request_name)
    if doc.status == "Completed":
        return

    try:
        settings = frappe.get_doc("Printrove Settings")
        api = settings.get_api()
        payload = json.loads(doc.data)

        if doc.request_description == "Create Design":
            response = api.create_design(payload.get("image_url"), payload.get("name"))
            doc.db_set("output", json.dumps(response))
            design_id = response.get("design", {}).get("id") if isinstance(response, dict) else None
            
            if design_id:
                frappe.flags.in_printrove_sync = True
                item = frappe.get_doc("Item", doc.reference_docname)
                item.db_set("printrove_id", str(design_id))
                frappe.flags.in_printrove_sync = False

        elif doc.request_description == "Create Product":
            response = api.create_product(payload)
            doc.db_set("output", json.dumps(response))
            
            product_data = response.get("product", {}) if isinstance(response, dict) else {}
            variants = product_data.get("variants", [])
            new_product_id = variants[0].get("id") if variants else product_data.get("id")

            if new_product_id:
                # Update BOM
                bom = frappe.get_doc("BOM", doc.reference_docname)
                bom.db_set("printrove_id", str(new_product_id))
                
                # Update Finished Good Item
                item_doc = frappe.get_doc("Item", bom.item)
                item_doc.db_set("printrove_id", str(new_product_id))
                item_doc.db_set("delivered_by_supplier", 1)
                
                supplier_item_exists = False
                for row in item_doc.supplier_items:
                    if row.supplier == settings.supplier:
                        supplier_item_exists = True
                        row.db_set("supplier_part_no", str(new_product_id))
                        break
                
                if not supplier_item_exists:
                    item_doc.append("supplier_items", {
                        "supplier": settings.supplier,
                        "supplier_part_no": str(new_product_id)
                    })
                    item_doc.save(ignore_permissions=True)

        elif doc.request_description == "Create Order":
            # Fetch shipping cost dynamically here
            so = frappe.get_doc("Sales Order", doc.reference_docname)
            shipping_cost = 0
            
            shipping_address = None
            if so.shipping_address_name:
                shipping_address = frappe.get_doc("Address", so.shipping_address_name)

            if shipping_address and shipping_address.pincode:
                try:
                    total_weight = payload.pop("_total_weight", 0) # Read and remove
                    serviceability = api.get_serviceability(shipping_address.pincode, total_weight)
                    options = serviceability.get("options", [])
                    if options:
                        cheapest = min(options, key=lambda x: x.get("price", 0))
                        shipping_cost = cheapest.get("price", 0)
                except Exception:
                    frappe.log_error(message=frappe.get_traceback(), title="Printrove Serviceability Check Failed")

            # Now execute the main order creation payload
            # Reconstruct printrove items and calculate estimated cost
            printrove_items = []
            estimated_cost = 0
            for item in so.items:
                if not item.delivered_by_supplier:
                    continue
                p_id = frappe.db.get_value("Item", item.item_code, "printrove_id")
                if p_id:
                    actual_qty = frappe.db.sql("select sum(actual_qty) from `tabBin` where item_code=%s", item.item_code)[0][0] or 0
                    if actual_qty <= 0:
                        printrove_items.append(item)
                        # Estimate Cost using standard buying rate or valuation
                        rate = frappe.db.get_value("Item", item.item_code, "valuation_rate") or frappe.db.get_value("Item", item.item_code, "standard_rate") or 0
                        estimated_cost += float(rate) * item.qty

            if not printrove_items:
                doc.db_set("status", "Completed")
                frappe.db.commit()
                return

            estimated_cost += float(shipping_cost)

            # Check Printrove Credit if configured
            credit_account = settings.printrove_credit_account
            if credit_account:
                available_credit = settings.get_available_credit(so.company)
                if estimated_cost > available_credit:
                    doc.db_set("status", "Failed")
                    doc.db_set("error", f"Insufficient Printrove Credit. Estimated Cost: {estimated_cost}, Available: {available_credit}")
                    frappe.db.commit()
                    return

            response = api.create_order(payload)
            doc.db_set("output", json.dumps(response))
            
            pr_order_id = response.get("id") if isinstance(response, dict) else response
            order_cost = response.get("order_cost") if isinstance(response, dict) else 0

            # Create PO
            po = frappe.new_doc("Purchase Order")
            po.company = so.company
            po.supplier = settings.supplier
            po.schedule_date = so.delivery_date
            
            total_item_qty = sum([item.qty for item in printrove_items])
            item_cost_pool = order_cost - shipping_cost if order_cost > shipping_cost else 0
            rate_per_item = item_cost_pool / total_item_qty if total_item_qty > 0 else 0

            for item in printrove_items:
                po.append(
                    "items",
                    {
                        "item_code": item.item_code,
                        "qty": item.qty,
                        "rate": rate_per_item if order_cost else item.rate,
                        "schedule_date": so.delivery_date,
                        "warehouse": item.warehouse or frappe.get_cached_value("Company", so.company, "default_warehouse"),
                        "sales_order": so.name,
                        "sales_order_item": item.name,
                    },
                )

            if shipping_cost > 0:
                shipping_account = settings.shipping_account
                if not shipping_account:
                    expense_accounts = frappe.db.get_all("Account", filters={"account_type": ["in", ["Expense Account", "Chargeable"]], "company": so.company}, limit=1)
                    if not expense_accounts:
                        expense_accounts = frappe.db.get_all("Account", filters={"name": ["like", "%Freight%"], "company": so.company}, limit=1)
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

        doc.db_set("status", "Completed")
        frappe.db.commit()

    except Exception as e:
        doc.db_set("status", "Failed")
        doc.db_set("error", str(e) + "\n\n" + frappe.get_traceback())
        frappe.db.commit()
        raise e
