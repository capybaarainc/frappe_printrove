import frappe
import json
import base64
import mimetypes
from frappe.core.doctype.file.utils import find_file_by_url

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

def process():
    """
    Message Relay pattern: process all queued requests by routing to specific functions.
    """
    queued_requests = frappe.get_all(
        "Integration Request",
        filters={
            "integration_request_service": "Printrove",
            "status": "Queued"
        },
        fields=["name", "request_description"],
        limit=50
    )

    for req in queued_requests:
        try:
            if req.request_description == "Create Design":
                process_design_request(req.name)
            elif req.request_description == "Create Product":
                process_product_request(req.name)
            elif req.request_description == "Create Order":
                process_order_request(req.name)
        except Exception:
            pass

def _set_request_status(doc, status, error=None):
    doc.db_set("status", status)
    if error:
        doc.db_set("error", error)
    frappe.db.commit()

def process_design_request(integration_request_name):
    frappe.db.commit()
    doc = frappe.get_doc("Integration Request", integration_request_name)
    if doc.status == "Completed":
        return

    try:
        settings = frappe.get_doc("Printrove Settings")
        api = settings.get_api()
        payload = json.loads(doc.data)

        create_design(doc, api, payload)

        _set_request_status(doc, "Completed")
    except Exception as e:
        _set_request_status(doc, "Failed", str(e) + "\n\n" + frappe.get_traceback())
        raise e

def process_product_request(integration_request_name):
    frappe.db.commit()
    doc = frappe.get_doc("Integration Request", integration_request_name)
    if doc.status == "Completed":
        return

    try:
        settings = frappe.get_doc("Printrove Settings")
        api = settings.get_api()
        payload = json.loads(doc.data)

        create_product(doc, api, settings, payload)

        _set_request_status(doc, "Completed")
    except Exception as e:
        _set_request_status(doc, "Failed", str(e) + "\n\n" + frappe.get_traceback())
        raise e

def process_order_request(integration_request_name):
    frappe.db.commit()
    doc = frappe.get_doc("Integration Request", integration_request_name)
    if doc.status == "Completed":
        return

    try:
        settings = frappe.get_doc("Printrove Settings")
        api = settings.get_api()
        payload = json.loads(doc.data)

        create_order(doc, api, settings, payload)

        _set_request_status(doc, "Completed")
    except Exception as e:
        _set_request_status(doc, "Failed", str(e) + "\n\n" + frappe.get_traceback())
        raise e

def create_design(doc, api, payload):
    file_url = payload.get("file_url")
    data_uri = _get_base64_data_uri(file_url)

    response = api.create_design(data_uri, payload.get("name"))
    doc.db_set("output", json.dumps(response))
    
    design_id = _extract_id_from_response(response, "design")
    if design_id:
        _update_item_printrove_id(doc.reference_docname, design_id)
        _trigger_retroactive_bom_sync(doc.reference_docname)

def _get_base64_data_uri(file_url):
    file_doc = find_file_by_url(file_url)
    if not file_doc:
        frappe.throw(f"File not found: {file_url}")
        
    file_content = file_doc.get_content()
    if isinstance(file_content, str):
        file_content = file_content.encode('utf-8')
        
    base64_file = base64.b64encode(file_content).decode('utf-8')
    content_type = mimetypes.guess_type(file_url)[0] or "image/png"
    return f"data:{content_type};base64,{base64_file}"

def _update_item_printrove_id(item_name, design_id):
    frappe.flags.in_printrove_sync = True
    item = frappe.get_doc("Item", item_name)
    item.db_set("printrove_id", str(design_id))
    frappe.flags.in_printrove_sync = False

def _trigger_retroactive_bom_sync(item_name):
    boms = frappe.db.sql("""
        SELECT DISTINCT parent FROM `tabBOM Item`
        WHERE item_code = %s
        AND parent IN (
            SELECT name FROM `tabBOM` WHERE docstatus = 1 AND (printrove_id IS NULL OR printrove_id = '')
        )
    """, (item_name,), as_dict=True)
    
    from frappe_printrove.utils.bom import on_submit as bom_on_submit
    for bom_row in boms:
        try:
            bom_doc = frappe.get_doc("BOM", bom_row.parent)
            bom_on_submit(bom_doc)
        except Exception:
            pass

def _extract_id_from_response(response, key):
    if isinstance(response, dict):
        return response.get(key, {}).get("id") if key else response.get("id")
    return None

def create_product(doc, api, settings, payload):
    response = api.create_product(payload)
    doc.db_set("output", json.dumps(response))
    
    product_data = response.get("product", {}) if isinstance(response, dict) else {}
    variants = product_data.get("variants", [])
    new_product_id = variants[0].get("id") if variants else product_data.get("id")

    if new_product_id:
        bom = frappe.get_doc("BOM", doc.reference_docname)
        bom.db_set("printrove_id", str(new_product_id))
        
        _update_finished_good_item(bom.item, new_product_id, settings.supplier)
        _trigger_retroactive_sales_order_sync(bom.item)

def _update_finished_good_item(item_code, new_product_id, supplier):
    item_doc = frappe.get_doc("Item", item_code)
    item_doc.db_set("printrove_id", str(new_product_id))
    item_doc.db_set("delivered_by_supplier", 1)
    
    supplier_item_exists = False
    for row in item_doc.supplier_items:
        if row.supplier == supplier:
            supplier_item_exists = True
            row.db_set("supplier_part_no", str(new_product_id))
            break
    
    if not supplier_item_exists:
        item_doc.append("supplier_items", {
            "supplier": supplier,
            "supplier_part_no": str(new_product_id)
        })
        item_doc.save(ignore_permissions=True)

def _trigger_retroactive_sales_order_sync(item_code):
    sos = frappe.db.sql("""
        SELECT DISTINCT parent FROM `tabSales Order Item`
        WHERE item_code = %s
        AND parent IN (
            SELECT name FROM `tabSales Order` WHERE docstatus = 1
        )
    """, (item_code,), as_dict=True)
    
    from frappe_printrove.utils.sales_order import on_submit as so_on_submit
    for so_row in sos:
        try:
            so_doc = frappe.get_doc("Sales Order", so_row.parent)
            so_on_submit(so_doc)
        except Exception:
            pass

def create_order(doc, api, settings, payload):
    so = frappe.get_doc("Sales Order", doc.reference_docname)
    total_weight = payload.pop("_total_weight", 0)
    draft_po_name = payload.pop("_draft_po_name", None)
    
    if not draft_po_name:
        raise Exception("Draft PO name not found in payload")

    shipping_cost = _calculate_shipping_cost(api, so, total_weight)
    printrove_items, items_cost = _calculate_printrove_items_cost(so)

    if not printrove_items:
        return

    estimated_cost = items_cost + float(shipping_cost)
    _validate_credit_limit(settings, so.company, estimated_cost)

    response = api.create_order(payload)
    doc.db_set("output", json.dumps(response))
    
    pr_order_id = _extract_id_from_response(response, None) or response
    order_cost = response.get("order_cost") if isinstance(response, dict) else 0

    _update_draft_purchase_order(draft_po_name, printrove_items, order_cost, shipping_cost, settings, so.company, pr_order_id)

def _calculate_shipping_cost(api, so, total_weight):
    if not so.shipping_address_name:
        return 0

    shipping_address = frappe.get_doc("Address", so.shipping_address_name)
    if not shipping_address.pincode:
        return 0

    try:
        serviceability = api.get_serviceability(shipping_address.pincode, total_weight)
        options = serviceability.get("options", [])
        if options:
            cheapest = min(options, key=lambda x: x.get("price", 0))
            return cheapest.get("price", 0)
    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="Printrove Serviceability Check Failed")
    
    return 0

def _calculate_printrove_items_cost(so):
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
                rate = frappe.db.get_value("Item", item.item_code, "valuation_rate") or frappe.db.get_value("Item", item.item_code, "standard_rate") or 0
                estimated_cost += float(rate) * item.qty

    return printrove_items, estimated_cost

def _validate_credit_limit(settings, company, estimated_cost):
    credit_account = settings.printrove_credit_account
    if credit_account:
        available_credit = settings.get_available_credit(company)
        if estimated_cost > available_credit:
            raise Exception(f"Insufficient Printrove Credit. Estimated Cost: {estimated_cost}, Available: {available_credit}")

def _update_draft_purchase_order(draft_po_name, printrove_items, order_cost, shipping_cost, settings, company, pr_order_id):
    po = frappe.get_doc("Purchase Order", draft_po_name)
    
    total_item_qty = sum([item.qty for item in printrove_items])
    item_cost_pool = order_cost - shipping_cost if order_cost > shipping_cost else 0
    rate_per_item = item_cost_pool / total_item_qty if total_item_qty > 0 else 0

    if order_cost:
        po.ignore_pricing_rule = 1
        for row in po.items:
            row.margin_type = ""
            row.margin_rate_or_amount = 0.0
            row.price_list_rate = rate_per_item
            row.rate = rate_per_item
            row.amount = row.rate * row.qty

    if shipping_cost > 0:
        shipping_account = _get_shipping_account(settings, company)
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
    po.submit()

def _get_shipping_account(settings, company):
    if settings.shipping_account:
        return settings.shipping_account
        
    expense_accounts = frappe.db.get_all("Account", filters={"account_type": ["in", ["Expense Account", "Chargeable"]], "company": company}, limit=1)
    if not expense_accounts:
        expense_accounts = frappe.db.get_all("Account", filters={"name": ["like", "%Freight%"], "company": company}, limit=1)
        
    return expense_accounts[0].name if expense_accounts else None
