import unittest
import frappe
from unittest.mock import patch, MagicMock
from frappe_printrove.frappe_printrove.doctype.printrove_settings.printrove_settings import (
    PrintroveAPI
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

