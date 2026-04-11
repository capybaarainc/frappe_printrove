import frappe
from frappe.utils import get_url

def on_update(doc, method=None):
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
            api = settings.get_api()
            response = api.create_design(image_url, doc.item_name or doc.item_code)

            design_id = response.get("design", {}).get("id") if isinstance(response, dict) else None
            
            if design_id:
                frappe.flags.in_printrove_sync = True
                doc.db_set("printrove_id", str(design_id))
                frappe.flags.in_printrove_sync = False
        except Exception:
            frappe.log_error(message=frappe.get_traceback(), title="Printrove Design Sync Failed")
            # We don't throw here to avoid blocking item save, but log it
