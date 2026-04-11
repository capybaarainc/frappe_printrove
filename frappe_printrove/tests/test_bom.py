import unittest
import frappe
from unittest.mock import patch, MagicMock
from frappe_printrove.utils.bom import on_submit

class TestBOM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.exists("Item", "PR-SUB-1"):
            frappe.get_doc({
                "doctype": "Item",
                "item_code": "PR-SUB-1",
                "item_name": "Test Blank Product",
                "item_group": "All Item Groups",
                "is_stock_item": 1,
                "printrove_id": "101"
            }).insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Item", "PR-SUB-1", "printrove_id", "101")

        if not frappe.db.exists("Item", "Test Print File"):
            frappe.get_doc({
                "doctype": "Item",
                "item_code": "Test Print File",
                "item_name": "Test Print File",
                "item_group": "All Item Groups",
                "is_stock_item": 1,
                "is_print_file": 1,
                "printrove_id": "123"
            }).insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Item", "Test Print File", "printrove_id", "123")

        if not frappe.db.exists("Item", "Test Finished Product"):
            doc = frappe.get_doc({
                "doctype": "Item",
                "item_code": "Test Finished Product",
                "item_name": "Test Finished Product",
                "item_group": "All Item Groups",
                "is_stock_item": 1
            })
            doc.insert(ignore_permissions=True)
        
        doc = frappe.get_doc("Item", "Test Finished Product")
        if not any(s.supplier == "Printrove" for s in doc.supplier_items):
            doc.append("supplier_items", {"supplier": "Printrove"})
            doc.save(ignore_permissions=True)
        frappe.db.commit()

    def test_on_submit(self):
        bom = frappe.new_doc("BOM")
        bom.item = "Test Finished Product"
        bom.qty = 1
        bom.append("items", {"item_code": "PR-SUB-1", "qty": 1})
        bom.append("items", {
            "item_code": "Test Print File",
            "qty": 1,
            "print_placement": "Front",
            "print_width": 10.0,
            "print_height": 12.0
        })
        bom.insert(ignore_permissions=True)
        
        with patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveAPI") as MockAPI:
            mock_instance = MockAPI.return_value
            mock_instance.create_product.return_value = {"id": "prod_123"}
            
            on_submit(bom)
            
            bom.reload()
            self.assertEqual(bom.printrove_id, "prod_123")
            self.assertEqual(frappe.db.get_value("Item", "Test Finished Product", "printrove_id"), "prod_123")
