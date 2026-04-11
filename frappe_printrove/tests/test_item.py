import unittest
import frappe
from unittest.mock import patch, MagicMock
from frappe_printrove.utils.item import on_update

class TestItem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.exists("Item", "Test Print File"):
            doc = frappe.get_doc({
                "doctype": "Item",
                "item_code": "Test Print File",
                "item_name": "Test Print File",
                "item_group": "All Item Groups",
                "is_stock_item": 1,
                "is_print_file": 1,
            })
            doc.insert(ignore_permissions=True)
        frappe.db.commit()

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

        with patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveAPI") as MockAPI:
            mock_instance = MockAPI.return_value
            mock_instance.create_design.return_value = {"id": "123"}
            
            on_update(item)
            self.assertEqual(item.printrove_id, "123")
