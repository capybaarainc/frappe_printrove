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

        if not frappe.db.exists("Item Group", "Sub Assemblies"):
            frappe.get_doc(
                {"doctype": "Item Group", "item_group_name": "Sub Assemblies", "is_group": 0}
            ).insert(ignore_permissions=True)

        if not frappe.db.exists("Item Attribute", "Test Size"):
            frappe.get_doc({
                "doctype": "Item Attribute",
                "attribute_name": "Test Size",
                "item_attribute_values": [{"attribute_value": "M", "abbr": "M"}]
            }).insert(ignore_permissions=True)

        template_name = "PR-SUB-TEMPLATE"
        if not frappe.db.exists("Item", template_name):
            template_dict = {
                "doctype": "Item",
                "item_code": template_name,
                "item_name": "Test Template Product",
                "item_group": "Sub Assemblies",
                "is_stock_item": 0,
                "has_variants": 1,
                "attributes": [{"attribute": "Test Size"}],
                "printrove_id": "100"
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                if not frappe.db.exists("GST HSN Code", "999900"):
                    frappe.get_doc({"doctype": "GST HSN Code", "name": "999900", "description": "Default HSN"}).insert(ignore_permissions=True)
                template_dict["gst_hsn_code"] = "999900"
            # temporarily bypass naming series if any
            frappe.db.set_value("Print Settings", "Print Settings", "item_naming_by", "Item Code") 
            try:
                doc = frappe.get_doc(template_dict)
                doc.flags.ignore_mandatory = True
                doc.flags.ignore_validate = True
                doc.insert(ignore_permissions=True, set_name=template_name)
            except frappe.DuplicateEntryError:
                pass
        else:
            frappe.db.set_value("Item", template_name, "printrove_id", "100")

        variant_name = "PR-SUB-1"
        if not frappe.db.exists("Item", variant_name):
            item_dict1 = {
                "doctype": "Item",
                "item_code": variant_name,
                "item_name": "Test Blank Product",
                "item_group": "Sub Assemblies",
                "is_stock_item": 1,
                "variant_of": template_name,
                "printrove_id": "101",
                "attributes": [{"attribute": "Test Size", "attribute_value": "M"}]
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                item_dict1["gst_hsn_code"] = "999900"
            try:
                doc = frappe.get_doc(item_dict1)
                doc.flags.ignore_mandatory = True
                doc.flags.ignore_validate = True
                doc.insert(ignore_permissions=True, set_name=variant_name)
            except frappe.DuplicateEntryError:
                pass
        else:
            frappe.db.set_value("Item", variant_name, "printrove_id", "101")
            frappe.db.set_value("Item", variant_name, "item_group", "Sub Assemblies")
            frappe.db.set_value("Item", variant_name, "variant_of", template_name)

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
            
            from frappe_printrove.utils.integration_request import process_product_request
            req = frappe.get_last_doc("Integration Request", filters={"reference_docname": bom.name, "request_description": "Create Product"})
            if req:
                process_product_request(req.name)
            
            bom.reload()
            self.assertEqual(bom.printrove_id, "var_123")
            self.assertEqual(frappe.db.get_value("Item", "Test Finished Product", "printrove_id"), "var_123")

    def test_asynchronous_bom_product_sync(self):
        import uuid
        uid = str(uuid.uuid4())[:8]
        
        retro_item_name = f"Retro Print File {uid}"
        bom_fg_name = f"Test Finished Product 2 {uid}"
        
        # Create a print file WITHOUT a printrove_id
        item_dict_retro = {
            "doctype": "Item",
            "item_code": retro_item_name,
            "item_name": retro_item_name,
            "item_group": "Print Files",
            "is_stock_item": 1
        }
        if frappe.db.has_column("Item", "gst_hsn_code"):
            item_dict_retro["gst_hsn_code"] = "999900"
        frappe.get_doc(item_dict_retro).insert(ignore_permissions=True)
        
        # Create BOM with it
        bom = frappe.new_doc("BOM")
        bom.item = bom_fg_name
        if not frappe.db.exists("Item", bom_fg_name):
            fg2 = frappe.get_doc({"doctype": "Item", "item_code": bom_fg_name, "item_group": "All Item Groups", "is_stock_item": 1})
            if frappe.db.has_column("Item", "gst_hsn_code"):
                fg2.gst_hsn_code = "999900"
            fg2.append("supplier_items", {"supplier": "Printrove Products Private Limited"})
            fg2.insert()
            
        bom.qty = 1
        bom.custom_bom_code = f"BOM-RETRO-{uid}"
        bom.append("items", {"item_code": "PR-SUB-1", "qty": 1})
        bom.append("items", {
            "item_code": retro_item_name,
            "qty": 1,
            "print_placement": "Front",
            "print_width": 10.0,
            "print_height": 12.0
        })
        bom.insert(ignore_permissions=True)
        bom.submit() # Submit it, it should NOT sync yet

        self.assertFalse(bom.printrove_id)
        
        # Now simulate "Create Design" finishing for the Retro Print File
        from frappe_printrove.utils.integration_request import create, process_design_request
        
        req = create("Item", retro_item_name, "Create Design", {"file_url": "/fake.png"})
        
        # We need to mock find_file_by_url so it returns a fake file doc
        with patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.get_access_token") as mock_token, \
             patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.create_design") as mock_create_design, \
             patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.create_product") as mock_create_product, \
             patch("frappe.core.doctype.file.utils.find_file_by_url") as mock_find_file:
             
            mock_token.return_value = "mock_token"
            mock_file = MagicMock()
            mock_file.get_content.return_value = b"fake"
            mock_find_file.return_value = mock_file
            
            mock_create_design.return_value = {"design": {"id": "12345678"}}
            mock_create_product.return_value = {"product": {"id": "87654321", "variants": [{"id": "11223344"}]}}
            
            process_design_request(req.name)
            
            bom.reload()
            self.assertEqual(bom.printrove_id, "11223344")
