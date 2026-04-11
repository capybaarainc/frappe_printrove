import unittest
import frappe
from unittest.mock import patch, MagicMock
from frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings import (
    PrintroveAPI,
    sync_printrove_catalog,
)

class TestPrintroveSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Setup settings
        settings = frappe.get_doc("Printrove Settings")
        settings.enable_printrove = 1
        settings.client_id = "test@example.com"
        settings.client_secret = "test_password"
        settings.save(ignore_permissions=True)

        # Ensure Item Group 'All Item Groups' exists
        if not frappe.db.exists("Item Group", "All Item Groups"):
            frappe.get_doc(
                {"doctype": "Item Group", "item_group_name": "All Item Groups", "is_group": 1}
            ).insert(ignore_permissions=True)

        frappe.db.commit()

    @patch(
        "frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.requests.post"
    )
    def test_get_access_token(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "test_token"}
        mock_post.return_value = mock_response

        api = PrintroveAPI()
        self.assertEqual(api.token, "test_token")

    @patch(
        "frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.requests.post"
    )
    @patch(
        "frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.requests.request"
    )
    def test_get_categories(self, mock_request, mock_post):
        mock_post_response = MagicMock()
        mock_post_response.status_code = 200
        mock_post_response.json.return_value = {"access_token": "test_token"}
        mock_post.return_value = mock_post_response

        mock_request_response = MagicMock()
        mock_request_response.status_code = 200
        mock_request_response.json.return_value = {"data": [{"id": "1", "name": "T-Shirts"}]}
        mock_request.return_value = mock_request_response

        api = PrintroveAPI()
        categories = api.get_categories()

        self.assertIn("data", categories)
        self.assertEqual(categories["data"][0]["name"], "T-Shirts")

    @patch(
        "frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings.PrintroveAPI"
    )
    def test_sync_catalog(self, mock_api_class):
        mock_api = MagicMock()

        # Mock responses
        mock_api.get_categories.return_value = [{"id": "c1", "name": "T-Shirts"}]
        mock_api.get_category_products.return_value = [{"id": "p1", "name": "Classic T-Shirt", "price": 100}]
        # Mock variant fetch
        mock_api.get_product.return_value = []

        mock_api_class.return_value = mock_api

        # Run sync
        sync_printrove_catalog()

        # Check Item Group
        self.assertTrue(frappe.db.exists("Item Group", "T-Shirts"))

        # Check Item
        item_exists = frappe.db.exists("Item", "PR-p1")
        self.assertTrue(item_exists)

        if item_exists:
            item = frappe.get_doc("Item", "PR-p1")
            self.assertEqual(item.item_name, "Classic T-Shirt")
            self.assertEqual(item.printrove_id, "p1")
