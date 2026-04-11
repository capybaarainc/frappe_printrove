import frappe
from frappe import _
from frappe_printrove.utils.integration_request import create

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
    blank_variant_id = None
    designs = {}

    for item in doc.items:
        # Fetch Item details
        item_info = frappe.db.get_value("Item", item.item_code, ["printrove_id", "item_group", "variant_of"], as_dict=True)
        if not item_info or not item_info.printrove_id:
            continue

        if item_info.item_group == "Print Files":
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
        elif item_info.item_group == "Sub Assemblies":
            # The Sub Assembly is the variant item
            blank_variant_id = item_info.printrove_id
            
            # Fetch the printrove_id of the template item to use as the base product ID
            if item_info.variant_of:
                blank_product_id = frappe.db.get_value("Item", item_info.variant_of, "printrove_id")

    if blank_product_id and blank_variant_id and designs:
        try:
            payload = {
                "product_id": int(blank_product_id),
                "name": doc.item_name or doc.item,
                "variants": [{"product_id": int(blank_variant_id)}],
                "design": designs,
            }
            
            req = create("BOM", doc.name, "Create Product", payload)
            
            frappe.enqueue(
                "frappe_printrove.utils.integration_request.process",
                queue="long",
                integration_request_name=req.name,
                now=frappe.flags.in_test
            )
            
        except Exception:
            frappe.log_error(message=frappe.get_traceback(), title="Printrove BOM Sync Failed")
            frappe.throw(_("Failed to queue Product to Printrove. Check Error Log for details."))
