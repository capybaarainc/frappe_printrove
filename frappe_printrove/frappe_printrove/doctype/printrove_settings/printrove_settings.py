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
            # supplier look up by gst number
            supplier_name = "Printrove Products Private Limited"
            
            if frappe.db.has_column("Supplier", "gstin"):
                supplier_match = frappe.db.get_value("Supplier", {"gstin": "33AAICP8487B1Z9"}, "name")
                if supplier_match:
                    supplier_name = supplier_match
                    self.supplier = supplier_name
                    return
            
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
                if frappe.db.has_column("Supplier", "gstin"):
                    supplier.gstin = "33AAICP8487B1Z9"
                
                supplier.insert(ignore_permissions=True)
            self.supplier = supplier_name

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

    def _request(self, method, endpoint, params=None, json_data=None, retries=5):
        import time
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        for attempt in range(retries):
            try:
                response = requests.request(method, url, headers=headers, params=params, json=json_data)
                
                # Check for rate limit
                if response.status_code == 429:
                    wait_time = 2 ** attempt
                    frappe.logger().warning(f"Printrove Rate Limit Hit. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                    
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as e:
                # If it's not a 429 or we ran out of retries, throw error
                frappe.log_error(
                    message=f"Request: {method} {url}\nResponse: {response.text}\nError: {str(e)}",
                    title="Printrove API Error",
                )
                frappe.throw(_("Printrove API Request Failed. Check Error Log for details."))
            except Exception:
                frappe.log_error(message=frappe.get_traceback(), title="Printrove API Error")
                frappe.throw(_("An error occurred while communicating with Printrove API."))
        
        frappe.throw(_("Printrove API Rate Limit Exceeded after retries."))

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
