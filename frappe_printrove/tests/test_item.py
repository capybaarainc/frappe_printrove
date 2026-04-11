import unittest
import frappe
from unittest.mock import patch, MagicMock
from frappe_printrove.utils.item import on_update

class TestItem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.exists("Item Group", "Print Files"):
            frappe.get_doc(
                {"doctype": "Item Group", "item_group_name": "Print Files", "is_group": 0}
            ).insert(ignore_permissions=True)
            
        if not frappe.db.exists("Item Group", "Products"):
            frappe.get_doc(
                {"doctype": "Item Group", "item_group_name": "Products", "is_group": 0}
            ).insert(ignore_permissions=True)

        if not frappe.db.exists("Item", "Test Print File"):
            item_dict = {
                "doctype": "Item",
                "item_code": "Test Print File",
                "item_name": "Test Print File",
                "item_group": "Print Files",
                "is_stock_item": 1,
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                if not frappe.db.exists("GST HSN Code", "999900"):
                    frappe.get_doc({"doctype": "GST HSN Code", "name": "999900", "description": "Default HSN"}).insert(ignore_permissions=True)
                item_dict["gst_hsn_code"] = "999900"
            doc = frappe.get_doc(item_dict)
            doc.insert(ignore_permissions=True)
            
        if not frappe.db.exists("Item", "Test Product Item"):
            item_dict = {
                "doctype": "Item",
                "item_code": "Test Product Item",
                "item_name": "Test Product Item",
                "item_group": "Products",
                "is_stock_item": 1,
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                item_dict["gst_hsn_code"] = "999900"
            doc = frappe.get_doc(item_dict)
            doc.insert(ignore_permissions=True)
            
        if not frappe.db.exists("Supplier", "Printrove Products Private Limited"):
            frappe.get_doc({
                "doctype": "Supplier",
                "supplier_name": "Printrove Products Private Limited",
                "supplier_group": "Distributor"
            }).insert(ignore_permissions=True)
            
        settings = frappe.get_doc("Printrove Settings")
        settings.enable_printrove = 1
        settings.supplier = "Printrove Products Private Limited"
        settings.save(ignore_permissions=True)

        frappe.db.commit()

    def test_on_update_drop_ship(self):
        item = frappe.get_doc("Item", "Test Product Item")
        # Ensure it has no delivered_by_supplier flag
        item.db_set("delivered_by_supplier", 0)
        
        # Link to Printrove Supplier
        if not any(s.supplier == "Printrove Products Private Limited" for s in item.supplier_items):
            item.append("supplier_items", {"supplier": "Printrove Products Private Limited"})
            item.save(ignore_permissions=True)
            
        on_update(item)
        item.reload()
        
        self.assertEqual(item.delivered_by_supplier, 1)

    def test_on_update(self):
        item = frappe.get_doc("Item", "Test Print File")
        item.image = "/files/test_image.png"
        item.printrove_id = None
        
        if not frappe.db.exists("File", {"file_url": item.image}):
            f_doc = frappe.get_doc({
                "doctype": "File",
                "file_url": item.image,
                "attached_to_doctype": "Item",
                "attached_to_name": item.name,
                "is_private": 0,
                "content": "test content"
            })
            f_doc.insert(ignore_permissions=True)

        with patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient") as MockAPI:
            mock_instance = MockAPI.return_value
            mock_instance.create_design.return_value = {"design": {"id": "123"}}
            
            on_update(item)
            item.reload()
            self.assertEqual(item.printrove_id, "123")
