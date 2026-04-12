import unittest
import frappe
from unittest.mock import patch, MagicMock

class TestUtils(unittest.TestCase):
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
        
        if not frappe.db.exists("Item Group", "Print Files"):
            frappe.get_doc({"doctype": "Item Group", "item_group_name": "Print Files", "is_group": 0}).insert(ignore_permissions=True)
        if not frappe.db.exists("Item Group", "Sub Assemblies"):
            frappe.get_doc({"doctype": "Item Group", "item_group_name": "Sub Assemblies", "is_group": 0}).insert(ignore_permissions=True)
            
        if not frappe.db.exists("Item Attribute", "Test Size"):
            frappe.get_doc({"doctype": "Item Attribute", "attribute_name": "Test Size", "item_attribute_values": [{"attribute_value": "M", "abbr": "M"}]}).insert(ignore_permissions=True)

        if not frappe.db.exists("Item", "PR-SUB-DOMINO-TMPL"):
            template_dict = {
                "doctype": "Item",
                "item_code": "PR-SUB-DOMINO-TMPL",
                "item_name": "PR-SUB-DOMINO-TMPL",
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
            try:
                doc = frappe.get_doc(template_dict)
                doc.flags.ignore_mandatory = True
                doc.insert(ignore_permissions=True, set_name="PR-SUB-DOMINO-TMPL")
            except frappe.DuplicateEntryError:
                pass
        else:
            frappe.db.set_value("Item", "PR-SUB-DOMINO-TMPL", "printrove_id", "100")

        if not frappe.db.exists("Item", "PR-SUB-DOMINO-VAR"):
            item_dict1 = {
                "doctype": "Item",
                "item_code": "PR-SUB-DOMINO-VAR",
                "item_name": "PR-SUB-DOMINO-VAR",
                "item_group": "Sub Assemblies",
                "is_stock_item": 1,
                "variant_of": "PR-SUB-DOMINO-TMPL",
                "printrove_id": "101",
                "attributes": [{"attribute": "Test Size", "attribute_value": "M"}]
            }
            if frappe.db.has_column("Item", "gst_hsn_code"):
                item_dict1["gst_hsn_code"] = "999900"
            try:
                doc = frappe.get_doc(item_dict1)
                doc.flags.ignore_mandatory = True
                doc.insert(ignore_permissions=True, set_name="PR-SUB-DOMINO-VAR")
            except frappe.DuplicateEntryError:
                pass
        else:
            frappe.db.set_value("Item", "PR-SUB-DOMINO-VAR", "printrove_id", "101")
            
        if not frappe.db.exists("Customer", "Test Customer Retro"):
            frappe.get_doc({"doctype": "Customer", "customer_name": "Test Customer Retro"}).insert(ignore_permissions=True)

    def test_utils(self):
        import uuid
        uid = str(uuid.uuid4())[:8]
        
        pf_item = f"Retro PF {uid}"
        fg_item = f"Retro FG {uid}"
        
        # 1. Create Finished Good (without printrove_id)
        fg_doc = frappe.get_doc({
            "doctype": "Item",
            "item_code": fg_item,
            "item_name": fg_item,
            "item_group": "Products",
            "is_stock_item": 1,
            "delivered_by_supplier": 1,
            "supplier_items": [{"supplier": "Printrove Products Private Limited"}]
        })
        if frappe.db.has_column("Item", "gst_hsn_code"):
            fg_doc.gst_hsn_code = "999900"
        fg_doc.insert(ignore_permissions=True)
        
        # 2. Create Sales Order
        so = frappe.new_doc("Sales Order")
        so.customer = "Test Customer Retro"
        so.delivery_date = frappe.utils.add_days(frappe.utils.today(), 10)
        so.append("items", {
            "item_code": fg_item,
            "qty": 1,
            "rate": 1000,
            "delivered_by_supplier": 1,
            "supplier": "Printrove Products Private Limited"
        })
        so.insert(ignore_permissions=True)
        so.submit()
        
        # A Draft PO should be created, but NO Integration Request for "Create Order" yet.
        po_exists = frappe.db.exists("Purchase Order Item", {"sales_order": so.name})
        self.assertTrue(po_exists, "Draft PO should be created immediately")
        
        req_exists = frappe.db.exists("Integration Request", {"reference_docname": so.name, "request_description": "Create Order"})
        self.assertFalse(req_exists, "Create Order should NOT be queued yet")
        
        # 3. Create Print File (without image, so no printrove_id)
        pf_doc = frappe.get_doc({
            "doctype": "Item",
            "item_code": pf_item,
            "item_name": pf_item,
            "item_group": "Print Files",
            "is_stock_item": 1
        })
        if frappe.db.has_column("Item", "gst_hsn_code"):
            pf_doc.gst_hsn_code = "999900"
        pf_doc.insert(ignore_permissions=True)
        
        # 4. Create BOM
        bom = frappe.new_doc("BOM")
        bom.item = fg_item
        bom.qty = 1
        bom.custom_bom_code = f"BOM-DOMINO-{uid}"
        bom.append("items", {"item_code": "PR-SUB-DOMINO-VAR", "qty": 1})
        bom.append("items", {
            "item_code": pf_item,
            "qty": 1,
            "print_placement": "Front",
            "print_width": 10.0,
            "print_height": 12.0
        })
        bom.insert(ignore_permissions=True)
        bom.submit()
        
        req_bom_exists = frappe.db.exists("Integration Request", {"reference_docname": bom.name, "request_description": "Create Product"})
        self.assertFalse(req_bom_exists, "Create Product should NOT be queued yet")
        
        # 5. NOW attach the file to Print File to trigger the retro effect!
        with patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.get_access_token") as mock_token, \
             patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.create_design") as mock_create_design, \
             patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.create_product") as mock_create_product, \
             patch("frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveClient.create_order") as mock_create_order, \
             patch("frappe.core.doctype.file.utils.find_file_by_url") as mock_find_file:
             
            mock_token.return_value = "mock_token"
            
            mock_file = MagicMock()
            mock_file.get_content.return_value = b"fake"
            mock_find_file.return_value = mock_file
            
            mock_create_design.return_value = {"design": {"id": "123456"}}
            mock_create_product.return_value = {"product": {"id": "123457", "variants": [{"id": "123458"}]}}
            mock_create_order.return_value = {"id": "123459", "order_cost": 500}
            
            # This triggers File after_insert -> Item on_update -> queue "Create Design" -> retro sync BOM -> queue "Create Product" -> retro sync SO -> queue "Create Order"
            # Since frappe.flags.in_test=True, enqueued functions run synchronously inline!
            f_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": f"retro_design_{uid}.png",
                "attached_to_doctype": "Item",
                "attached_to_name": pf_item,
                "is_private": 1,
                "content": "retro content"
            })
            f_doc.insert(ignore_permissions=True)
            
            from frappe_printrove.utils.integration_request import process
            req_design = frappe.get_last_doc("Integration Request", filters={"reference_docname": pf_item, "request_description": "Create Design"})
            if req_design.status != "Completed":
                process(req_design.name)
                
            # Verify the item now has the printrove_id set!
            pf_doc.reload()
            print("PF PRINTROVE ID:", pf_doc.printrove_id)
            
            req_product = None
            try:
                req_product = frappe.get_last_doc("Integration Request", filters={"reference_docname": bom.name, "request_description": "Create Product"})
            except frappe.DoesNotExistError:
                pass
            print("PRODUCT REQ STATUS:", req_product.status if req_product else "NOT FOUND")
            if req_product and req_product.status != "Completed":
                process(req_product.name)
                
            req_order = None
            try:
                req_order = frappe.get_last_doc("Integration Request", filters={"reference_docname": so.name, "request_description": "Create Order"})
            except frappe.DoesNotExistError:
                pass
            print("ORDER REQ STATUS:", req_order.status if req_order else "NOT FOUND")
            if req_order and req_order.status != "Completed":
                process(req_order.name)
            self.assertEqual(pf_doc.printrove_id, "123456")
            
            bom.reload()
            self.assertEqual(bom.printrove_id, "123458")
            
            fg_doc.reload()
            self.assertEqual(fg_doc.printrove_id, "123458")
            
            # Verify SO queued "Create Order"
            req_so = frappe.get_last_doc("Integration Request", filters={"reference_docname": so.name, "request_description": "Create Order"})
            self.assertEqual(req_so.status, "Completed")
            
            # Verify PO was updated and submitted
            po_name = frappe.db.get_value("Purchase Order Item", {"sales_order": so.name}, "parent")
            po = frappe.get_doc("Purchase Order", po_name)
            self.assertEqual(po.docstatus, 1) # Submitted!
            self.assertEqual(po.printrove_order_id, "123459")