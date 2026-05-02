import frappe
from frappe import _
from frappe_printrove.utils.integration_request import create

def on_submit(doc, method=None):
    settings = frappe.get_single("Printrove Settings")
    if not settings.enable_printrove or not settings.supplier:
        return

    if not _is_printrove_item(doc.item, settings.supplier):
        return

    blank_product_id, blank_variant_id, designs = _extract_printrove_details(doc)

    if blank_product_id and blank_variant_id and designs:
        payload = {
            "product_id": int(blank_product_id),
            "name": doc.item_name or doc.item,
            "variants": [{"product_id": int(blank_variant_id)}],
            "design": designs,
        }
        try:
            create("BOM", doc.name, "Create Product", payload)
        except Exception:
            frappe.log_error(message=frappe.get_traceback(), title="Printrove BOM Sync Failed")
            frappe.throw(_("Failed to queue Product to Printrove. Check Error Log for details."))

def _is_printrove_item(item_code, supplier):
    return frappe.db.exists("Item Supplier", {"parent": item_code, "supplier": supplier})

def _extract_printrove_details(doc):
    blank_product_id = None
    blank_variant_id = None
    designs = {}

    for item in doc.items:
        item_info = frappe.db.get_value("Item", item.item_code, ["printrove_id", "item_group", "variant_of"], as_dict=True)
        if not item_info or not item_info.printrove_id:
            continue

        if item_info.item_group == "Print Files":
            placement = (item.get("print_placement") or "Front").lower()
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
            blank_variant_id = item_info.printrove_id
            if item_info.variant_of:
                blank_product_id = frappe.db.get_value("Item", item_info.variant_of, "printrove_id")

    return blank_product_id, blank_variant_id, designs
