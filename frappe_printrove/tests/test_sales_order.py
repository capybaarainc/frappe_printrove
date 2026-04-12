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

        if not frappe.db.exists("Item", "NON-PR-ITEM"):
            item_dict2 = {
                "doctype": "Item",
                "item_code": "NON-PR-ITEM",
                "item_name": "Test Non-Printrove Product",
                "item_group": "All Item Groups",
                "is_stock_item": 1
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                item_dict2["gst_hsn_code"] = "999900"
            frappe.get_doc(item_dict2).insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Item", "NON-PR-ITEM", "printrove_id", None)

        if not frappe.db.exists("Item", "PR-STOCKED"):
            item_dict3 = {
                "doctype": "Item",
                "item_code": "PR-STOCKED",
                "item_name": "Test Stocked Product",
                "item_group": "All Item Groups",
                "is_stock_item": 1,
                "printrove_id": "9999"
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                item_dict3["gst_hsn_code"] = "999900"
            frappe.get_doc(item_dict3).insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Item", "PR-STOCKED", "printrove_id", "9999")

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

    @patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient")
    def test_on_submit(self, mock_api_class):
        settings = frappe.get_doc("Printrove Settings")
        settings.enable_printrove = 1
        settings.supplier = "Printrove"
        settings.shipping_account = "Freight and Forwarding Charges - _TC"
        settings.printrove_credit_account = None
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
            "delivered_by_supplier": 1,
            "supplier": "Printrove",
            "warehouse": "Test Warehouse - _TC"
        })
        so.append("items", {
            "item_code": "NON-PR-ITEM",
            "qty": 1,
            "rate": 300,
            "warehouse": "Test Warehouse - _TC"
        })
        # Add another Printrove item but do NOT set delivered_by_supplier to test that condition
        so.append("items", {
            "item_code": "PR-SUB-1",
            "qty": 5,
            "rate": 500,
            "delivered_by_supplier": 0,
            "warehouse": "Test Warehouse - _TC"
        })
        so.append("items", {
            "item_code": "PR-STOCKED",
            "qty": 3,
            "rate": 500,
            "delivered_by_supplier": 1,
            "supplier": "Printrove",
            "warehouse": "Test Warehouse - _TC"
        })
        so.insert(ignore_permissions=True, ignore_mandatory=True)
        so.docstatus = 1
        
        original_sql = frappe.db.sql
        def mock_sql(query, *args, **kwargs):
            if "select sum(actual_qty) from `tabBin` where item_code" in query:
                item_code = args[0] if args else None
                if isinstance(item_code, tuple):
                    item_code = item_code[0]
                if item_code == "PR-STOCKED":
                    return ((100,),)
                return ((0,),)
            return original_sql(query, *args, **kwargs)

        with patch.object(frappe.db, "sql", side_effect=mock_sql):
            on_submit(so)

            from frappe_printrove.utils.integration_request import process_order_request
            req = frappe.get_last_doc("Integration Request", filters={"reference_docname": so.name, "request_description": "Create Order"})
            if req:
                process_order_request(req.name)

        pos = frappe.get_all("Purchase Order Item", filters={"sales_order": so.name}, fields=["parent", "item_code", "qty", "rate"])
        
        # Should create a PO with exactly one item (the PR-SUB-1)
        reqs = frappe.get_all("Integration Request", filters={"reference_docname": so.name}, fields=["status", "error"], order_by="creation desc", limit=1)
        print(f"Reqs: {reqs}")
        self.assertTrue(len(pos) > 0)
        self.assertEqual(len(pos), 1)
        self.assertEqual(pos[0].item_code, "PR-SUB-1")
        
        # Check rates were updated via Printrove API Cost spreading
        # Mock returned 500 order_cost and 50 shipping_cost.
        # Item cost pool = 450. Qty = 2. Rate per item should be 225.
        self.assertEqual(pos[0].rate, 225.0)

        po = frappe.get_doc("Purchase Order", pos[0].parent)
        self.assertEqual(po.printrove_order_id, "EXT-ORDER-123")
        self.assertEqual(po.docstatus, 1)

    @patch("frappe_printrove.utils.sales_order.frappe.db.get_all")
    @patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient")
    def test_on_submit_insufficient_credit(self, mock_api_class, mock_get_all):
        settings = frappe.get_doc("Printrove Settings")
        settings.enable_printrove = 1
        settings.supplier = "Printrove"
        settings.shipping_account = None
        settings.printrove_credit_account = "Cash - _TC" # Some existing account
        settings.save(ignore_permissions=True)

        mock_api = MagicMock()
        mock_api.get_serviceability.return_value = {"options": [{"price": 50}]}
        mock_api_class.return_value = mock_api

        so = frappe.new_doc("Sales Order")
        so.company = "_Test Company"
        so.customer = "Test Customer"
        so.delivery_date = frappe.utils.add_days(frappe.utils.today(), 5)
        so.shipping_address_name = "Test Address-Billing"
        so.append("items", {
            "item_code": "PR-SUB-1",
            "qty": 200, # Large qty to trigger insufficient credit
            "rate": 500,
            "delivered_by_supplier": 1,
            "supplier": "Printrove",
            "warehouse": "Test Warehouse - _TC"
        })
        so.insert(ignore_permissions=True, ignore_mandatory=True)
        so.docstatus = 1
        
        # Give item high valuation rate
        frappe.db.set_value("Item", "PR-SUB-1", "valuation_rate", 1000)

        original_sql = frappe.db.sql
        def mock_sql(query, *args, **kwargs):
            if "select sum(actual_qty) from `tabBin` where item_code" in query:
                return ((0,),)
            if "SELECT SUM(debit) - SUM(credit)" in query:
                return ((50,),) # Low balance
            if "SELECT SUM(grand_total" in query:
                return ((0,),)
            return original_sql(query, *args, **kwargs)

        with patch.object(frappe.db, "sql", side_effect=mock_sql):
            on_submit(so)
            
            from frappe_printrove.utils.integration_request import process_order_request
            req = frappe.get_last_doc("Integration Request", filters={"reference_docname": so.name, "request_description": "Create Order"})
            if req:
                try:
                    process_order_request(req.name)
                except Exception:
                    pass
            
        pos = frappe.get_all("Purchase Order Item", filters={"sales_order": so.name}, fields=["parent"])
        self.assertEqual(len(pos), 1) # Draft PO should be created

        po = frappe.get_doc("Purchase Order", pos[0].parent)
        self.assertEqual(po.docstatus, 0) # Remains in draft mode

        # Check Integration Request
        reqs = frappe.get_all("Integration Request", filters={"reference_docname": so.name}, fields=["status", "error"], order_by="creation desc", limit=1)
        self.assertEqual(reqs[0].status, "Failed")
        self.assertIn("Insufficient Printrove Credit", reqs[0].error)

    @patch("frappe_printrove.utils.sales_order.frappe.db.get_all")
    @patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient")
    def test_on_submit_printrove_api_failure(self, mock_api_class, mock_get_all):
        import requests
        settings = frappe.get_doc("Printrove Settings")
        settings.enable_printrove = 1
        settings.supplier = "Printrove"
        settings.shipping_account = None
        settings.printrove_credit_account = None
        settings.save(ignore_permissions=True)

        # Mock an HTTP Error 422 from Printrove API
        mock_api = MagicMock()
        mock_api.get_serviceability.return_value = {"options": [{"price": 50}]}
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.text = '{"status":"failure","message":"It seems like you do not have sufficient credits to place this order"}'
        
        # In Python requests, an HTTPError usually has a response object
        http_err = requests.exceptions.HTTPError(response=mock_response)
        mock_api.create_order.side_effect = http_err
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
            "delivered_by_supplier": 1,
            "supplier": "Printrove",
            "warehouse": "Test Warehouse - _TC"
        })
        so.insert(ignore_permissions=True, ignore_mandatory=True)
        so.docstatus = 1
        
        original_sql = frappe.db.sql
        def mock_sql(query, *args, **kwargs):
            if "select sum(actual_qty) from `tabBin` where item_code" in query:
                return ((0,),)
            return original_sql(query, *args, **kwargs)

        with patch.object(frappe.db, "sql", side_effect=mock_sql):
            on_submit(so)
            
            from frappe_printrove.utils.integration_request import process_order_request
            req = frappe.get_last_doc("Integration Request", filters={"reference_docname": so.name, "request_description": "Create Order"})
            if req:
                try:
                    process_order_request(req.name)
                except Exception:
                    pass
            
        pos = frappe.get_all("Purchase Order Item", filters={"sales_order": so.name}, fields=["parent"])
        self.assertEqual(len(pos), 1) # Draft PO created

        po = frappe.get_doc("Purchase Order", pos[0].parent)
        self.assertEqual(po.docstatus, 0) # Remains in draft mode

        reqs = frappe.get_all("Integration Request", filters={"reference_docname": so.name}, fields=["status", "error"], order_by="creation desc", limit=1)
        self.assertEqual(reqs[0].status, "Failed")
        self.assertIn("HTTPError", reqs[0].error)
