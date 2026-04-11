import frappe

def after_insert(doc, method=None):
    if getattr(doc, "attached_to_doctype", None) == "Item" and getattr(doc, "attached_to_name", None):
        item = frappe.get_doc("Item", doc.attached_to_name)
        if getattr(item, "item_group", "") == "Print Files" and not getattr(item, "printrove_id", None):
            # Trigger the item's on_update to push the design
            item.save(ignore_permissions=True)