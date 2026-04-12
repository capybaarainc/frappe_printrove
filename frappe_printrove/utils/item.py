import frappe
from frappe.utils import get_url
from frappe_printrove.utils.integration_request import create

def on_update(doc, method=None):
    _set_delivered_by_supplier(doc)
    _queue_printrove_design_creation(doc)

def _set_delivered_by_supplier(doc):
    if getattr(doc, "item_group", "") == "Products" and getattr(doc, "delivered_by_supplier", 0) == 0:
        settings = frappe.get_single("Printrove Settings")
        if settings.supplier:
            for row in doc.get("supplier_items", []):
                if row.supplier == settings.supplier:
                    doc.db_set("delivered_by_supplier", 1)
                    break

def _queue_printrove_design_creation(doc):
    if getattr(doc, "item_group", "") != "Print Files" or doc.printrove_id:
        return

    if frappe.flags.in_printrove_sync:
        return

    if _is_request_queued(doc.name):
        return

    file_url = _get_item_image_url(doc)
    if not file_url:
        return

    settings = frappe.get_single("Printrove Settings")
    if not settings.enable_printrove:
        return

    payload = {
        "file_url": file_url,
        "name": doc.item_name or doc.item_code
    }
    
    try:
        create("Item", doc.name, "Create Design", payload)
    except Exception:
        frappe.log_error(message=frappe.get_traceback(), title="Printrove Design Sync Failed")

def _is_request_queued(docname):
    return frappe.db.exists("Integration Request", {
        "reference_doctype": "Item",
        "reference_docname": docname,
        "request_description": "Create Design",
        "status": ["in", ["Queued", "Processing"]]
    })

def _get_item_image_url(doc):
    attached_file = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Item",
            "attached_to_name": doc.name,
        },
        fields=["file_url"],
        order_by="creation desc",
        limit=1,
    )
    if attached_file:
        return attached_file[0].file_url
    return doc.image
