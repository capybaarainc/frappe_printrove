import unittest
import frappe
from unittest.mock import patch, MagicMock
from frappe_printrove.utils.sales_order import on_submit

class TestSalesOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.exists("Company", "_Test Company"):
            frappe.get_doc({
                "doctype": "Company",
                "company_name": "_Test Company",
                "abbr": "_TC",
                "default_currency": "USD",
                "country": "India"
            }).insert(ignore_permissions=True, ignore_mandatory=True)

        if not frappe.db.exists("Item", "PR-SUB-1"):
            frappe.get_doc({
                "doctype": "Item",
                "item_code": "PR-SUB-1",
                "item_name": "Test Blank Product",
                "item_group": "All Item Groups",
                "is_stock_item": 1,
                "printrove_id": "12345"
            }).insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Item", "PR-SUB-1", "printrove_id", "12345")

        if not frappe.db.exists("Supplier", "Printrove"):
            frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": "Printrove",
                "supplier_group": "Distributor"
            }).insert(ignore_permissions=True)
            
        if not frappe.db.exists("Customer Group", "Test Retail"):
            frappe.get_doc({"doctype": "Customer Group", "customer_group_name": "Test Retail", "is_group": 0}).insert(ignore_permissions=True)

        if not frappe.db.exists("Customer", "Test Customer"):
            frappe.get_doc({
                "doctype": "Customer",
                "customer_name": "Test Customer",
                "customer_type": "Individual",
                "customer_group": "Test Retail",
                "territory": "All Territories"
            }).insert(ignore_permissions=True, ignore_mandatory=True)

        if not frappe.db.exists("Address", "Test Address-Billing"):
            frappe.get_doc({
                "doctype": "Address",
                "address_title": "Test Address",
                "address_line1": "123 Test St",
                "city": "Test City",
                "state": "Karnataka",
                "gst_state": "Karnataka",
                "pincode": "560001",
                "country": "India",
                "address_type": "Billing",
                "links": [{"link_doctype": "Customer", "link_name": "Test Customer"}]
            }).insert(ignore_permissions=True)

        if not frappe.db.exists("Warehouse", "Test Warehouse - _TC"):
            frappe.get_doc({
                "doctype": "Warehouse",
                "warehouse_name": "Test Warehouse",
                "company": "_Test Company"
            }).insert(ignore_permissions=True, ignore_mandatory=True)

        frappe.db.commit()

    @patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveAPI")
    def test_on_submit(self, mock_api_class):
        settings = frappe.get_doc("Printrove Settings")
        settings.enable_printrove = 1
        settings.supplier = "Printrove"
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        mock_api = MagicMock()
        mock_api.get_serviceability.return_value = {"options": [{"price": 50}]}
        mock_api.create_order.return_value = {"id": "EXT-ORDER-123", "order_cost": 500}
        mock_api_class.return_value = mock_api

        so = frappe.new_doc("Sales Order")
        so.company = "_Test Company"
        so.customer = "Test Customer"
        so.delivery_date = frappe.utils.add_days(frappe.utils.today(), 5)
        so.shipping_address_name = "Test Address-Billing"
        so.append("items", {
            "item_code": "PR-SUB-1",
            "qty": 2,
            "rate": 500,
            "warehouse": "Test Warehouse - _TC"
        })
        so.insert(ignore_permissions=True, ignore_mandatory=True)
        so.docstatus = 1
        
        on_submit(so)

        pos = frappe.get_all("Purchase Order Item", filters={"sales_order": so.name}, fields=["parent"])
        self.assertTrue(len(pos) > 0)
        po = frappe.get_doc("Purchase Order", pos[0].parent)
        self.assertEqual(po.printrove_order_id, "EXT-ORDER-123")
