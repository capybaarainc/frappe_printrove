# Copyright (c) 2024, Aquiveal and contributors
# For license information, please see license.txt

import frappe
import requests
import datetime
from frappe import _
from frappe.model.document import Document

class PrintroveSettings(Document):
    def validate(self):
        if self.enable_printrove:
            self.ensure_supplier()

    def ensure_supplier(self):
        if not self.supplier:
            supplier_name = "Printrove"
            if not frappe.db.exists("Supplier", supplier_name):
                supplier_group = (
                    frappe.db.get_single_value("Buying Settings", "supplier_group") or "Distributor"
                )
                if not frappe.db.exists("Supplier Group", supplier_group):
                    frappe.get_doc(
                        {"doctype": "Supplier Group", "supplier_group_name": supplier_group}
                    ).insert(ignore_permissions=True)

                supplier = frappe.get_doc(
                    {
                        "doctype": "Supplier",
                        "supplier_name": supplier_name,
                        "supplier_group": supplier_group,
                    }
                )
                supplier.insert(ignore_permissions=True)
            self.supplier = supplier_name

    @frappe.whitelist()
    def get_catalog(self):
        if not self.enable_printrove:
            frappe.throw(_("Please enable Printrove Integration first."))

        # Ensure supplier exists or create one
        self.ensure_supplier()
        self.save()

        # Enqueue or run directly
        frappe.enqueue(
            sync_printrove_catalog,
            queue="long",
            timeout=3000,
            now=frappe.flags.in_test,
        )

    def get_api(self):
        return PrintroveAPI(self)

class PrintroveAPI:
    def __init__(self, settings=None):
        self.settings = settings or frappe.get_single("Printrove Settings")
        if not self.settings.enable_printrove:
            frappe.throw(_("Printrove Integration is disabled in Settings."))

        self.base_url = self.settings.base_url.rstrip("/")
        self.client_id = self.settings.client_id
        self.client_secret = self.settings.get_password("client_secret", raise_exception=False)
        self.token = self.get_access_token()

    def get_access_token(self):
        cache_key = "printrove_access_token"
        cached_token = frappe.cache().get_value(cache_key)
        if cached_token:
            return cached_token

        url = f"{self.base_url}/api/external/token"
        payload = {"email": self.client_id, "password": self.client_secret}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            token = data.get("access_token")
            expires_at_str = data.get("expires_at")

            if token and expires_at_str:
                # Parse the ISO format string (e.g. 2027-04-11T12:23:37.000000Z)
                try:
                    expires_at = datetime.datetime.strptime(expires_at_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f")
                except ValueError:
                    # Fallback if there are no microseconds
                    expires_at = datetime.datetime.strptime(expires_at_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                
                now = datetime.datetime.utcnow()
                ttl = (expires_at - now).total_seconds()
                ttl_with_buffer = int(ttl - 300) # 5 minutes buffer

                if ttl_with_buffer > 0:
                    frappe.cache().set_value(cache_key, token, expires_in_sec=ttl_with_buffer)

            return token
        except Exception:
            frappe.log_error(message=frappe.get_traceback(), title="Printrove Authentication Failed")
            frappe.throw(_("Failed to authenticate with Printrove API. Check logs for details."))

    def _request(self, method, endpoint, params=None, json_data=None):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = requests.request(method, url, headers=headers, params=params, json=json_data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            frappe.log_error(
                message=f"Request: {method} {url}\nResponse: {response.text}\nError: {str(e)}",
                title="Printrove API Error",
            )
            frappe.throw(_("Printrove API Request Failed. Check Error Log for details."))
        except Exception:
            frappe.log_error(message=frappe.get_traceback(), title="Printrove API Error")
            frappe.throw(_("An error occurred while communicating with Printrove API."))

    def get_categories(self):
        return self._request("GET", "/api/external/categories")

    def get_category_products(self, category_id):
        return self._request("GET", f"/api/external/categories/{category_id}")

    def get_product(self, category_id, product_id):
        return self._request("GET", f"/api/external/categories/{category_id}/products/{product_id}")

    def create_design(self, image_url, name):
        payload = {"url": image_url, "name": name}
        return self._request("POST", "/api/external/designs/url", json_data=payload)

    def create_product(self, payload):
        return self._request("POST", "/api/external/products", json_data=payload)

    def create_order(self, payload):
        return self._request("POST", "/api/external/orders", json_data=payload)

    def get_serviceability(self, pincode, weight=None):
        params = {"pincode": pincode}
        if weight:
            params["weight"] = weight
        return self._request("GET", "/api/external/serviceability", params=params)

def sync_printrove_catalog():
    try:
        settings = frappe.get_single("Printrove Settings")
        api = settings.get_api()

        # 1. Fetch Categories
        categories = api.get_categories()

        # We assume the response might be a list directly, or under a key like 'data' or 'categories'
        category_list = (
            categories
            if isinstance(categories, list)
            else categories.get("data", categories.get("categories", []))
        )

        for category in category_list:
            category_id = str(category.get("id", ""))
            category_name = category.get("name")
            if not category_name:
                continue

            # 2. Create Item Category
            if not frappe.db.exists("Item Category", category_name):
                frappe.get_doc(
                    {
                        "doctype": "Item Category",
                        "item_category_name": category_name,
                        "parent_item_category": "All Item Categories",
                    }
                ).insert(ignore_permissions=True)

            # 3. Fetch Products for Category
            products = api.get_category_products(category_id)
            product_list = (
                products
                if isinstance(products, list)
                else products.get("data", products.get("products", []))
            )

            for product in product_list:
                product_id = str(product.get("id", ""))
                product_name = product.get("name")

                if not product_id or not product_name:
                    continue

                # Fetch Variants for Product
                try:
                    variants_data = api.get_product(category_id, product_id)
                    variant_list = (
                        variants_data
                        if isinstance(variants_data, list)
                        else variants_data.get("data", variants_data.get("variants", []))
                    )

                    if variant_list:
                        for variant in variant_list:
                            variant_id = str(variant.get("id", ""))
                            variant_name = variant.get("name", f"{product_name} - {variant_id}")
                            price = variant.get("price", 0.0)

                            _create_or_update_item(
                                item_code=f"PR-{variant_id}",
                                item_name=variant_name,
                                item_category=category_name,
                                printrove_id=variant_id,
                                valuation_rate=price,
                            )
                    else:
                        # No variants, create the product as item
                        _create_or_update_item(
                            item_code=f"PR-{product_id}",
                            item_name=product_name,
                            item_category=category_name,
                            printrove_id=product_id,
                            valuation_rate=product.get("price", 0.0),
                        )
                except Exception:
                    frappe.log_error(
                        message=frappe.get_traceback(),
                        title=f"Failed to fetch variants for product {product_id}",
                    )
                    continue

        frappe.db.commit()

    except Exception:
        frappe.db.rollback()
        frappe.log_error(message=frappe.get_traceback(), title="Printrove Catalog Sync Failed")

def _create_or_update_item(item_code, item_name, item_category, printrove_id, valuation_rate):
    if not frappe.db.exists("Item", item_code):
        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": item_code,
                "item_name": item_name,
                "item_group": "Products",  # Defaulting item_group as it is usually mandatory in ERPNext
                "item_category": item_category,
                "stock_uom": "Nos",
                "is_stock_item": 1,
                "is_sub_contracted_item": 0,
                "has_variants": 0,
                "standard_rate": valuation_rate,
                "valuation_rate": valuation_rate,
                "printrove_id": printrove_id,
            }
        )
        # Set default default_item_manufacturer if needed, or other flags
        item.insert(ignore_permissions=True)
    else:
        # Update existing
        item = frappe.get_doc("Item", item_code)
        updated = False
        if item.printrove_id != printrove_id:
            item.printrove_id = printrove_id
            updated = True
        if item.item_name != item_name:
            item.item_name = item_name
            updated = True
        if hasattr(item, "item_category") and item.item_category != item_category:
            item.item_category = item_category
            updated = True
        if updated:
            item.save(ignore_permissions=True)
