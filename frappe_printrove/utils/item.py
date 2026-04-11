import frappe
from frappe.utils import get_url
from frappe_printrove.utils.integration_request import create, process

def on_update(doc, method=None):
    # Set delivered_by_supplier for Printrove Products
    if getattr(doc, "item_group", "") == "Products" and getattr(doc, "delivered_by_supplier", 0) == 0:
        settings = frappe.get_single("Printrove Settings")
        if settings.supplier:
            for row in doc.get("supplier_items", []):
                if row.supplier == settings.supplier:
                    doc.db_set("delivered_by_supplier", 1)
                    break

    # Print File Management
    if getattr(doc, "item_group", "") == "Print Files" and not doc.printrove_id:
        # Avoid recursive loop during save
        if frappe.flags.in_printrove_sync:
            return

        # Look for the latest attached image file
        attached_file = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Item",
                "attached_to_name": doc.name,
                "is_private": 0,  # Must be public for Printrove to access it
            },
            fields=["file_url", "name"],
            order_by="creation desc",
            limit=1,
        )

        if not attached_file:
            # Fallback to doc.image if set and public
            if doc.image and not doc.image.startswith("/private"):
                image_url = get_url(doc.image)
            else:
                return
        else:
            image_url = get_url(attached_file[0].file_url)

        try:
            settings = frappe.get_doc("Printrove Settings")
            if not settings.enable_printrove:
                return
                
            payload = {
                "image_url": image_url,
                "name": doc.item_name or doc.item_code
            }
            
            req = create("Item", doc.name, "Create Design", payload)
            
            frappe.enqueue(
                "frappe_printrove.utils.integration_request.process",
                queue="long",
                integration_request_name=req.name,
                now=frappe.flags.in_test
            )
        except Exception:
            frappe.log_error(message=frappe.get_traceback(), title="Printrove Design Sync Failed")
