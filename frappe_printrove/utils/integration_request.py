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
            create_design(doc, api, payload)

        elif doc.request_description == "Create Product":
            create_product(doc, api, settings, payload)

        elif doc.request_description == "Create Order":
            create_order(doc, api, settings, payload)

        doc.db_set("status", "Completed")
        frappe.db.commit()

    except Exception as e:
        doc.db_set("status", "Failed")
        doc.db_set("error", str(e) + "\n\n" + frappe.get_traceback())
        frappe.db.commit()
        raise e

def create_design(doc, api, payload):
    import base64
    from frappe.core.doctype.file.utils import find_file_by_url
    
    file_url = payload.get("file_url")
    file_doc = find_file_by_url(file_url)
    
    if not file_doc:
        frappe.throw(f"File not found: {file_url}")
        
    file_content = file_doc.get_content()
    if isinstance(file_content, str):
        file_content = file_content.encode('utf-8')
    base64_file = base64.b64encode(file_content).decode('utf-8')
    
    import mimetypes
    content_type = mimetypes.guess_type(file_url)[0] or "image/png"
    data_uri = f"data:{content_type};base64,{base64_file}"

    response = api.create_design(data_uri, payload.get("name"))
    doc.db_set("output", json.dumps(response))
    design_id = response.get("design", {}).get("id") if isinstance(response, dict) else None
    
    if design_id:
        frappe.flags.in_printrove_sync = True
        item = frappe.get_doc("Item", doc.reference_docname)
        item.db_set("printrove_id", str(design_id))
        frappe.flags.in_printrove_sync = False
        
        # Retroactive hook for BOM
        boms = frappe.db.sql("""
            SELECT DISTINCT parent FROM `tabBOM Item`
            WHERE item_code = %s
            AND parent IN (
                SELECT name FROM `tabBOM` WHERE docstatus = 1 AND (printrove_id IS NULL OR printrove_id = '')
            )
        """, (item.name,), as_dict=True)
        
        from frappe_printrove.utils.bom import on_submit as bom_on_submit
        for bom_row in boms:
            bom_doc = frappe.get_doc("BOM", bom_row.parent)
            try:
                bom_on_submit(bom_doc)
            except Exception:
                pass # Prevent failure from breaking current process

def create_product(doc, api, settings, payload):
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

        # Retroactive hook for Sales Order
        sos = frappe.db.sql("""
            SELECT DISTINCT parent FROM `tabSales Order Item`
            WHERE item_code = %s
            AND parent IN (
                SELECT name FROM `tabSales Order` WHERE docstatus = 1
            )
        """, (item_doc.name,), as_dict=True)
        
        from frappe_printrove.utils.sales_order import on_submit as so_on_submit
        for so_row in sos:
            so_doc = frappe.get_doc("Sales Order", so_row.parent)
            try:
                so_on_submit(so_doc)
            except Exception:
                pass

def create_order(doc, api, settings, payload):
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
        return

    estimated_cost += float(shipping_cost)

    # Check Printrove Credit if configured
    credit_account = settings.printrove_credit_account
    if credit_account:
        available_credit = settings.get_available_credit(so.company)
        if estimated_cost > available_credit:
            raise Exception(f"Insufficient Printrove Credit. Estimated Cost: {estimated_cost}, Available: {available_credit}")

    response = api.create_order(payload)
    doc.db_set("output", json.dumps(response))
    
    pr_order_id = response.get("id") if isinstance(response, dict) else response
    order_cost = response.get("order_cost") if isinstance(response, dict) else 0

    # Update Draft PO
    draft_po_name = payload.get("_draft_po_name")
    if not draft_po_name:
        raise Exception("Draft PO name not found in payload")
        
    po = frappe.get_doc("Purchase Order", draft_po_name)
    
    total_item_qty = sum([item.qty for item in printrove_items])
    item_cost_pool = order_cost - shipping_cost if order_cost > shipping_cost else 0
    rate_per_item = item_cost_pool / total_item_qty if total_item_qty > 0 else 0

    # Update item rates based on actual cost
    if order_cost:
        po.ignore_pricing_rule = 1
        for row in po.items:
            row.margin_type = ""
            row.margin_rate_or_amount = 0.0
            row.price_list_rate = rate_per_item
            row.rate = rate_per_item
            row.amount = row.rate * row.qty

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

    po.save(ignore_permissions=True)
    po.save(ignore_permissions=True)
    po.submit()
