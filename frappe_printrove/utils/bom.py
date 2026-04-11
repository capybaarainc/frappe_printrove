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
    blank_variant_id = None
    designs = {}

    for item in doc.items:
        # Fetch Item details
        item_info = frappe.db.get_value("Item", item.item_code, ["printrove_id", "printrove_base_product_id", "item_group"], as_dict=True)
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
        else:
            # Assume any other item with printrove_id is the blank product (variant)
            blank_product_id = item_info.printrove_base_product_id
            blank_variant_id = item_info.printrove_id

    if blank_product_id and blank_variant_id and designs:
        try:
            api = settings.get_api()
            payload = {
                "product_id": int(blank_product_id),
                "name": doc.item_name or doc.item,
                "variants": [{"product_id": int(blank_variant_id)}],
                "design": designs,
            }
            response = api.create_product(payload)
            # Response handling based on API docs: usually returns the created product info
            product_data = response.get("product", {}) if isinstance(response, dict) else {}
            variants = product_data.get("variants", [])
            new_product_id = variants[0].get("id") if variants else product_data.get("id")

            if new_product_id:
                frappe.db.set_value("BOM", doc.name, "printrove_id", str(new_product_id))
                # Also assign to the finished good item
                item_doc = frappe.get_doc("Item", doc.item)
                item_doc.printrove_id = str(new_product_id)
                item_doc.delivered_by_supplier = 1
                
                # Add/Update Supplier Part Number
                supplier_item_exists = False
                for row in item_doc.supplier_items:
                    if row.supplier == settings.supplier:
                        supplier_item_exists = True
                        row.supplier_part_no = str(new_product_id)
                        break
                
                if not supplier_item_exists:
                    item_doc.append("supplier_items", {
                        "supplier": settings.supplier,
                        "supplier_part_no": str(new_product_id)
                    })
                    
                item_doc.save(ignore_permissions=True)
        except Exception:
            frappe.log_error(message=frappe.get_traceback(), title="Printrove BOM Sync Failed")
            frappe.throw(_("Failed to publish Product to Printrove. Check Error Log for details."))
