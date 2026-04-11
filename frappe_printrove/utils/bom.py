import frappe
from frappe import _

def on_submit(doc, method=None):
    # BOM Publishing Logic
    settings = frappe.get_single("Printrove Settings")
    if not settings.enable_printrove or not settings.supplier:
        return

    # Check if the finished good item has Printrove as a supplier
    is_printrove_item = frappe.db.exists("Item Supplier", {"parent": doc.item, "supplier": settings.supplier})
    if not is_printrove_item:
        return

    blank_product_id = None
    designs = {}

    for item in doc.items:
        # Fetch Item details
        item_info = frappe.db.get_value("Item", item.item_code, ["printrove_id", "is_print_file"], as_dict=True)
        if not item_info or not item_info.printrove_id:
            continue

        if item_info.is_print_file:
            placement = (item.get("print_placement") or "Front").lower()
            # Map placements to Printrove expected keys if needed, but 'front', 'back' are standard
            designs[placement] = {
                "id": int(item_info.printrove_id),
                "dimensions": {
                    "width": int((item.get("print_width") or 0) * 300),
                    "height": int((item.get("print_height") or 0) * 300),
                    "top": int((item.get("print_top") or 0) * 300),
                    "left": int((item.get("print_left") or 0) * 300),
                },
            }
        else:
            # Assume any other item with printrove_id is the blank product
            blank_product_id = item_info.printrove_id

    if blank_product_id and designs:
        try:
            api = settings.get_api()
            payload = {
                "product_id": int(blank_product_id),
                "name": doc.item_name or doc.item,
                "design": designs,
            }
            response = api.create_product(payload)
            # Response handling based on API docs: usually returns the created product info
            new_product_id = response.get("id") if isinstance(response, dict) else response

            if new_product_id:
                frappe.db.set_value("BOM", doc.name, "printrove_id", str(new_product_id))
                # Also assign to the finished good item
                frappe.db.set_value("Item", doc.item, "printrove_id", str(new_product_id))
        except Exception:
            frappe.log_error(message=frappe.get_traceback(), title="Printrove BOM Sync Failed")
            frappe.throw(_("Failed to publish Product to Printrove. Check Error Log for details."))
