import unittest
import frappe
import json
from unittest.mock import patch, MagicMock
from frappe_printrove.utils.integration_request import create_design, create_product, create_order

class TestIntegrationRequestFunctions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.flags.in_test = True
        
        settings = frappe.get_doc("Printrove Settings")
        settings.enable_printrove = 1
        settings.client_id = "test@example.com"
        settings.client_secret = "test_password"
        settings.supplier = "Printrove Products Private Limited"
        settings.save(ignore_permissions=True)

    @patch("frappe.core.doctype.file.utils.find_file_by_url")
    def test_create_design(self, mock_find_file):
        mock_api = MagicMock()
        mock_api.create_design.return_value = {"design": {"id": "design_123"}}
        
        mock_file = MagicMock()
        mock_file.get_content.return_value = b"fake_image_content"
        mock_find_file.return_value = mock_file
        
        # Setup Item
        item_code = "Test Design Item"
        if not frappe.db.exists("Item", item_code):
            item_dict = {
                "doctype": "Item",
                "item_code": item_code,
                "item_name": item_code,
                "item_group": "Print Files",
                "is_stock_item": 1
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                if not frappe.db.exists("GST HSN Code", "999900"):
                    frappe.get_doc({"doctype": "GST HSN Code", "name": "999900", "description": "Default HSN"}).insert(ignore_permissions=True)
                item_dict["gst_hsn_code"] = "999900"
            frappe.get_doc(item_dict).insert(ignore_permissions=True)
            
        doc = MagicMock()
        doc.reference_docname = item_code
        payload = {"file_url": "/private/files/test.png", "name": "Test Design"}
        
        create_design(doc, mock_api, payload)
        
        mock_api.create_design.assert_called_once()
        
        # Verify the item got updated
        item = frappe.get_doc("Item", item_code)
        self.assertEqual(item.printrove_id, "design_123")

    def test_create_product(self):
        mock_api = MagicMock()
        mock_api.create_product.return_value = {"product": {"id": "product_123", "variants": [{"id": "variant_123"}]}}
        
        settings = frappe.get_doc("Printrove Settings")
        
        # Setup FG Item
        item_code = "Test FG Item"
        if not frappe.db.exists("Item", item_code):
            item_dict2 = {
                "doctype": "Item",
                "item_code": item_code,
                "item_name": item_code,
                "item_group": "Products",
                "is_stock_item": 1
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                item_dict2["gst_hsn_code"] = "999900"
            frappe.get_doc(item_dict2).insert(ignore_permissions=True)
            
        # Setup BOM
        bom_name = "BOM-Test FG Item-001"
        if not frappe.db.exists("BOM", bom_name):
            frappe.get_doc({
                "doctype": "BOM",
                "name": bom_name,
                "item": item_code,
                "qty": 1,
                "custom_bom_code": "BOM-TEST-FG-001",
                "items": [{"item_code": "Test Design Item", "qty": 1}]
            }).insert(ignore_permissions=True)
            
        doc = MagicMock()
        doc.reference_docname = bom_name
        payload = {"dummy": "payload"}
        
        create_product(doc, mock_api, settings, payload)
        
        mock_api.create_product.assert_called_once_with(payload)
        
        # Verify BOM and Item updated
        bom = frappe.get_doc("BOM", bom_name)
        self.assertEqual(bom.printrove_id, "variant_123")
        
        item = frappe.get_doc("Item", item_code)
        self.assertEqual(item.printrove_id, "variant_123")
        self.assertEqual(item.delivered_by_supplier, 1)

    @patch("frappe.get_doc")
    @patch("frappe.db.get_value")
    @patch("frappe.db.get_all")
    @patch("frappe.db.sql")
    def test_create_order(self, mock_sql, mock_get_all, mock_get_value, mock_get_doc):
        mock_api = MagicMock()
        mock_api.get_serviceability.return_value = {"options": [{"price": 50}]}
        mock_api.create_order.return_value = {"id": "order_123", "order_cost": 250}
        
        settings = frappe.get_doc("Printrove Settings")
        settings.shipping_account = None
        settings.printrove_credit_account = None
        
        # Mock SO
        mock_so = MagicMock()
        mock_so.name = "SO-TEST-001"
        mock_so.shipping_address_name = "Test Address"
        mock_so.customer_name = "Test Cust"
        mock_so.contact_email = "test@example.com"
        mock_so.company = "Test Co"
        
        # Mock SO Item
        mock_item = MagicMock()
        mock_item.item_code = "Test Order Item"
        mock_item.qty = 2
        mock_item.delivered_by_supplier = 1
        mock_so.items = [mock_item]
        
        # Mock Address
        mock_addr = MagicMock()
        mock_addr.name = "Test Address"
        mock_addr.pincode = "400001"
        mock_addr.phone = "9999999999"
        mock_addr.address_line1 = "Test Line"
        mock_addr.city = "Test City"
        mock_addr.state = "Maharashtra"
        mock_addr.country = "India"
        
        # Mock Draft PO
        mock_po = MagicMock()
        mock_po.name = "PO-TEST-001"
        mock_po.items = [MagicMock()]
        
        original_get_doc = frappe.get_doc
        def _mock_get_doc(doctype, name=None, *args, **kwargs):
            if doctype == "Printrove Settings":
                return settings
            if doctype == "Sales Order" and name == mock_so.name:
                return mock_so
            if doctype == "Address" and name == mock_addr.name:
                return mock_addr
            if doctype == "Purchase Order" and name == mock_po.name:
                return mock_po
            return original_get_doc(doctype, name, *args, **kwargs)
            
        mock_get_doc.side_effect = _mock_get_doc
        
        def _mock_get_value(doctype, *args, **kwargs):
            fieldname = kwargs.get("fieldname") or (args[1] if len(args) > 1 else None)
            if doctype == "Item" and fieldname == "printrove_id":
                return "variant_123"
            if doctype == "Item" and fieldname == "valuation_rate":
                return 100
            return None
            
        mock_get_value.side_effect = _mock_get_value
        
        # mock account get_all
        def _mock_get_all(doctype, *args, **kwargs):
            if doctype == "Account":
                account_mock = MagicMock()
                account_mock.name = "Shipping Account"
                return [account_mock]
            return []
        
        mock_get_all.side_effect = _mock_get_all
        
        mock_sql.return_value = [[0]] # For actual_qty
            
        doc = MagicMock()
        doc.reference_docname = mock_so.name
        
        payload = {"_draft_po_name": "PO-TEST-001", "_total_weight": 0.5, "dummy": "order_payload"}
        
        create_order(doc, mock_api, settings, payload)
        
        mock_api.create_order.assert_called_once()
        
        # Check if PO was updated correctly
        mock_po.save.assert_called()
        mock_po.submit.assert_called()
        self.assertEqual(mock_po.printrove_order_id, "order_123")
        self.assertEqual(mock_po.items[0].rate, 100) # (250 - 50) / 2 = 100