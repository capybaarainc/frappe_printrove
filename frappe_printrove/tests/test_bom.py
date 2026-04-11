import unittest
import frappe
from unittest.mock import patch, MagicMock
from frappe_printrove.utils.bom import on_submit

class TestBOM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        settings = frappe.get_doc("Printrove Settings")
        settings.enable_printrove = 1
        settings.client_id = "test@example.com"
        settings.client_secret = "test_password"
        settings.supplier = "Printrove Products Private Limited"
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        if not frappe.db.exists("Item Group", "Print Files"):
            frappe.get_doc(
                {"doctype": "Item Group", "item_group_name": "Print Files", "is_group": 0}
            ).insert(ignore_permissions=True)

        if not frappe.db.exists("Item", "PR-SUB-1"):
            item_dict1 = {
                "doctype": "Item",
                "item_code": "PR-SUB-1",
                "item_name": "Test Blank Product",
                "item_group": "All Item Groups",
                "is_stock_item": 1,
                "printrove_id": "101",
                "printrove_base_product_id": "100"
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                if not frappe.db.exists("GST HSN Code", "999900"):
                    frappe.get_doc({"doctype": "GST HSN Code", "name": "999900", "description": "Default HSN"}).insert(ignore_permissions=True)
                item_dict1["gst_hsn_code"] = "999900"
            frappe.get_doc(item_dict1).insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Item", "PR-SUB-1", "printrove_id", "101")
            frappe.db.set_value("Item", "PR-SUB-1", "printrove_base_product_id", "100")

        if not frappe.db.exists("Item", "Test Print File"):
            item_dict2 = {
                "doctype": "Item",
                "item_code": "Test Print File",
                "item_name": "Test Print File",
                "item_group": "Print Files",
                "is_stock_item": 1,
                "printrove_id": "123"
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                item_dict2["gst_hsn_code"] = "999900"
            frappe.get_doc(item_dict2).insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Item", "Test Print File", "printrove_id", "123")

        if not frappe.db.exists("Item", "Test Finished Product"):
            item_dict3 = {
                "doctype": "Item",
                "item_code": "Test Finished Product",
                "item_name": "Test Finished Product",
                "item_group": "All Item Groups",
                "is_stock_item": 1
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                item_dict3["gst_hsn_code"] = "999900"
            frappe.get_doc(item_dict3).insert(ignore_permissions=True)
        
        doc = frappe.get_doc("Item", "Test Finished Product")
        if not any(s.supplier == "Printrove Products Private Limited" for s in doc.supplier_items):
            doc.append("supplier_items", {"supplier": "Printrove Products Private Limited"})
            doc.save(ignore_permissions=True)
        frappe.db.commit()

    def test_on_submit(self):
        bom = frappe.new_doc("BOM")
        bom.item = "Test Finished Product"
        bom.qty = 1
        bom.custom_bom_code = "BOM-TEST-001"
        bom.append("items", {"item_code": "PR-SUB-1", "qty": 1})
        bom.append("items", {
            "item_code": "Test Print File",
            "qty": 1,
            "print_placement": "Front",
            "print_width": 10.0,
            "print_height": 12.0
        })
        bom.insert(ignore_permissions=True)
        
        with patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient") as MockAPI:
            mock_instance = MockAPI.return_value
            mock_instance.create_product.return_value = {"product": {"id": "prod_123", "variants": [{"id": "var_123"}]}}
            
            on_submit(bom)
            
            bom.reload()
            self.assertEqual(bom.printrove_id, "var_123")
            self.assertEqual(frappe.db.get_value("Item", "Test Finished Product", "printrove_id"), "var_123")
