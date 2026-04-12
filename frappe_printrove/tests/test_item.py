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
        item.save(ignore_permissions=True)
        frappe.db.delete("Integration Request", {"reference_doctype": "Item", "reference_docname": item.name})
        
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

        with patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.get_access_token") as mock_token, \
             patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.create_design") as mock_create_design:
            
            mock_token.return_value = "mocked_token"
            mock_create_design.return_value = {"design": {"id": "123"}}
            
            on_update(item)
            
            # Since the request is enqueued, we need to process it synchronously for the test
            from frappe_printrove.utils.integration_request import process
            req = frappe.get_last_doc("Integration Request", filters={"reference_docname": item.name, "request_description": "Create Design"})
            process(req.name)
            
            item.reload()
            self.assertEqual(item.printrove_id, "123")

    def test_file_after_insert(self):
        # Delete existing item if any
        if frappe.db.exists("Item", "Late Upload File Item"):
            frappe.delete_doc("Item", "Late Upload File Item")
            
        # Create a blank print file with NO image initially
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": "Late Upload File Item",
            "item_name": "Late Upload File Item",
            "item_group": "Print Files",
            "is_stock_item": 1
        })
        if frappe.db.has_column("Item", "gst_hsn_code"):
            item.gst_hsn_code = "999900"
        item.insert(ignore_permissions=True)

        # Clear any requests
        frappe.db.delete("Integration Request", {"reference_doctype": "Item", "reference_docname": item.name})
        
        # Now attach a file. The `File` after_insert hook should trigger `item.save()`, 
        # which triggers `on_update` -> pushes to Printrove
        with patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.get_access_token") as mock_token, \
             patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.create_design") as mock_create_design:
            
            mock_token.return_value = "mocked_token"
            mock_create_design.return_value = {"design": {"id": "999"}}
            
            f_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": "late_design.png",
                "attached_to_doctype": "Item",
                "attached_to_name": item.name,
                "is_private": 1,
                "content": "some image data here"
            })
            f_doc.insert(ignore_permissions=True)
            
            from frappe_printrove.utils.integration_request import process
            req = frappe.get_last_doc("Integration Request", filters={"reference_docname": item.name, "request_description": "Create Design"})
            process(req.name)
            
            # Verify the item now has the printrove_id set!
            item.reload()
            self.assertEqual(item.printrove_id, "999")
