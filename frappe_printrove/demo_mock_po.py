import frappe
from unittest.mock import patch, MagicMock
from frappe.utils import today, add_days

def execute():
    print("Setting up for Mock Sales Order creation...")

    if not frappe.db.exists("Customer", "Printrove Dummy Customer"):
        customer = frappe.new_doc("Customer")
        customer.customer_name = "Printrove Dummy Customer"
        customer.customer_type = "Individual"
        cg = frappe.db.get_list("Customer Group", pluck="name", limit=1)
        customer.customer_group = cg[0] if cg else "Commercial"
        terr = frappe.db.get_list("Territory", pluck="name", limit=1)
        customer.territory = terr[0] if terr else "All Territories"
        customer.insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.db.commit()

    if not frappe.db.exists("Address", {"address_title": "Mock Billing Address"}):
        frappe.get_doc({
            "doctype": "Address",
            "address_title": "Mock Billing Address",
            "address_line1": "123 Test St",
            "city": "Test City",
            "state": "Karnataka",
            "pincode": "560001",
            "country": "India",
            "address_type": "Billing",
            "links": [{"link_doctype": "Customer", "link_name": "Printrove Dummy Customer"}]
        }).insert(ignore_permissions=True)
        frappe.db.commit()

    addr = frappe.db.get_value("Address", {"address_title": "Mock Billing Address"}, "name")
    warehouse = frappe.db.get_value("Warehouse", {"company": "Capybaara"}, "name")
    
    settings = frappe.get_doc("Printrove Settings")
    freight_acct = frappe.db.get_value("Account", {"name": ["like", "%Freight%"], "company": "Capybaara"}, "name")
    if freight_acct:
        settings.shipping_account = freight_acct
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    print("Creating Sales Order...")
    so = frappe.new_doc("Sales Order")
    so.company = "Capybaara"
    so.customer = "Printrove Dummy Customer"
    so.delivery_date = add_days(today(), 5)
    so.shipping_address_name = addr
    
    so.append("items", {
        "item_code": "FG-TEST-TSHIRT-WHITE-S",
        "qty": 2,
        "rate": 799.0,
        "warehouse": warehouse
    })

    so.insert(ignore_permissions=True, ignore_mandatory=True)
    
    print(f"Sales Order created: {so.name}")
    print("Submitting Sales Order with mocked Printrove API response...")

    with patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient") as MockAPI:
        mock_instance = MockAPI.return_value
        
        mock_instance.get_serviceability.return_value = {"options": [{"price": 50}]}
        mock_instance.create_order.return_value = {"id": "MOCK-EXT-ORDER-999", "order_cost": 500.0}

        so.submit()
        frappe.db.commit()

    pos = frappe.get_all("Purchase Order Item", filters={"sales_order": so.name}, fields=["parent"])
    if pos:
        print(f"Successfully generated Purchase Order: {pos[0].parent}")
        po = frappe.get_doc("Purchase Order", pos[0].parent)
        print(f"Taxes and Charges:")
        for tax in po.taxes:
            print(f"- {tax.charge_type} {tax.account_head}: {tax.tax_amount}")
    else:
        print("Failed to generate Purchase Order.")
