import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def create_integrations_tab():
    doctypes = ["BOM Item", "Item Attribute", "Item Attribute Value", "BOM", "Item Category", "Item", "Purchase Order"]

    for doctype in doctypes:
        if not frappe.db.exists("DocType", doctype):
            continue

        create_custom_field(
            doctype,
            {
                "fieldname": "integrations_tab",
                "label": "Integrations",
                "fieldtype": "Tab Break",
                "insert_after": "", 
                "is_system_generated": 1 
            },
            ignore_validate=True
        )
