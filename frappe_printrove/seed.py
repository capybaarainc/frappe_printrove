import frappe
import json
import os

ATTRIBUTES_TO_EXTRACT = ["color", "size"]

ALLOWED_PRODUCTS = [
    "Half Sleeve Round Neck T-Shirt",
    "Polo T-shirts",
    "Oversized Tshirts",
    "Shorts",
    "Joggers",
    "Toddler Half Sleeve Round Neck T-Shirt",
    "Kids Half Sleeve Round Neck T-Shirt",
    "Mugs",
    "Mouse Pads",
    "Posters",
    "Tote Bags"
]

SIZE_MAPPING = {
    "S": "Small",
    "M": "Medium",
    "L": "Large",
    "XL": "Extra Large",
    "XS": "Extra Small",
    "2XL": "Extra Extra Large",
    "3XL": "Triple Extra Large",
    "4XL": "Quadruple Extra Large",
    "5XL": "Five Extra Large"
}

EXISTING_COLOR_ABBR = {
    "Yellow": "YLW", "Royal Blue": "RYB", "Red": "RED", "Mustard Yellow": "MTY",
    "Light Pink": "LGP", "Butter Yellow": "BTY", "Purple": "PUR", "Iris Lavender": "ILA", 
    "Ivory": "IVO", "Liril Green": "LLG", "Coffee Brown": "CFB",
    "Charcoal Grey": "CCG", "Silver Frost": "SVF", "Surf Blue": "SFB",
    "Chocolate Brown": "CCB", "Almond": "ALM", "Smoke Blue": "SMB", "Burgundy": "BUR",
    "Orange": "ORG", "Olive Green": "OLG", "Sky Blue": "SKB", "Pastel Dusty": "PTD",
    "Melange Grey": "MLG", "Golden Yellow": "GDY", "Cyan": "CYN", "Navy Blue": "NAV",
    "Magenta": "MGT", "Grey": "GRY", "Maroon": "MAR", "Black": "BLK", "White": "WHI",
    "Lavender": "LAV", "Beige": "BEI", "Bottle Green": "BTG"
}

EXISTING_SIZE_ABBR = {
    "Extra Small": "XS", "Extra Extra Large": "2XL", "Triple Extra Large": "3XL",
    "Medium": "M", "Five Extra Large": "5XL", "Quadruple Extra Large": "4XL",
    "Large": "L", "Extra Large": "XL", "Small": "S"
}

TEMPLATE_STATIC_ATTRIBUTES = {
    "Half Sleeve Round Neck T-Shirt": {"Fit": "Regular Fit, Boxy", "Neckline": "Crew Neck", "Sleeve": "Half Sleeves, Hemmed Cuff", "Hemline": "Straight", "Material": "Cotton, GSM 180"},
    "Polo T-shirts": {"Fit": "Regular Fit", "Neckline": "Polo", "Sleeve": "Half Sleeves, Hemmed Cuff", "Hemline": "Straight", "Material": "Cotton, GSM 240"},
    "Oversized Tshirts": {"Fit": "Oversized Fit", "Neckline": "Crew Neck", "Sleeve": "Half Sleeves, Hemmed Cuff", "Hemline": "Straight", "Material": "Cotton, GSM 220"},
    "Shorts": {"Fit": "Regular Fit", "Hemline": "Elastic Cuffs"},
    "Joggers": {"Fit": "Regular Fit", "Hemline": "Elastic Cuffs"},
    "Kids Half Sleeve Round Neck T-Shirt": {"Neckline": "Round Neck", "Sleeve": "Half Sleeves", "Fit": "Regular Fit", "Material": "Cotton, GSM 180"},
    "Toddler Half Sleeve Round Neck T-Shirt": {"Neckline": "Round Neck", "Sleeve": "Half Sleeves", "Fit": "Regular Fit", "Material": "Cotton, GSM 180"}
}

def is_product_allowed(prod_name):
    return prod_name in ALLOWED_PRODUCTS

def get_abbreviation(attr_name, val):
    val_str = str(val).strip()
    if attr_name == "Size":
        if val_str in EXISTING_SIZE_ABBR:
            return EXISTING_SIZE_ABBR[val_str]
        return val_str
    if attr_name == "Colour":
        if val_str in EXISTING_COLOR_ABBR:
            return EXISTING_COLOR_ABBR[val_str]
        words = val_str.split()
        if len(words) > 1:
            return "".join(w[0].upper() for w in words)[:3]
        else:
            cons = "".join(c for c in val_str.upper() if c not in "AEIOU")
            if len(cons) >= 3:
                return cons[:3]
            return val_str[:3].upper()
    return val_str[:3].upper()

def ensure_item_attribute(attr_name, attr_values):
    if not frappe.db.exists("Item Attribute", attr_name):
        doc = frappe.new_doc("Item Attribute")
        doc.attribute_name = attr_name
        doc.numeric_values = 0
        doc.insert(ignore_permissions=True)
    
    doc = frappe.get_doc("Item Attribute", attr_name)
    existing_vals = {row.attribute_value.lower(): row.abbr for row in doc.item_attribute_values if row.attribute_value}
    existing_abbrs = {row.abbr.lower() for row in doc.item_attribute_values if row.abbr}
    
    changed = False
    for val in sorted(list(attr_values)):
        if not val:
            continue
        if val.lower() not in existing_vals:
            abbr = get_abbreviation(attr_name, val)
            
            # Ensure abbreviation is unique case-insensitively
            original_abbr = abbr
            counter = 1
            while abbr.lower() in existing_abbrs:
                abbr = f"{original_abbr[:2]}{counter}"
                counter += 1
                
            doc.append("item_attribute_values", {
                "attribute_value": val,
                "abbr": abbr
            })
            existing_abbrs.add(abbr.lower())
            existing_vals[val.lower()] = abbr
            changed = True
            
    if changed:
        doc.save(ignore_permissions=True)

def ensure_supplier_item(doc, supplier, part_no):
    changed = False
    found = False
    for row in doc.supplier_items:
        if row.supplier == supplier:
            found = True
            if row.supplier_part_no != part_no:
                row.supplier_part_no = part_no
                changed = True
            break
            
    if not found:
        doc.append("supplier_items", {
            "supplier": supplier,
            "supplier_part_no": part_no
        })
        changed = True
    return changed

def run():
    frappe.logger().info("Starting Printrove Catalog Seed (Upsert)")
    
    data_path = os.path.join(frappe.get_app_path("frappe_printrove"), "fixtures", "resources.json")
    if not os.path.exists(data_path):
        frappe.logger().error(f"Catalog data not found at {data_path}")
        return

    with open(data_path, "r") as f:
        catalog = json.load(f)

    # 1. Gather all attributes
    attributes = {}
    templates_data = []

    for category in catalog:
        cat_name = category.get("name")
        for product in category.get("products", []):
            prod_name = product.get("name")
            if not is_product_allowed(prod_name):
                continue
                
            prod_id = product.get("id")
            product_variants = product.get("variants", [])
            
            filtered_variants = []
            for variant in product_variants:
                if "Framed" in str(variant.get("size", "")):
                    continue
                filtered_variants.append(variant)
                
            if not filtered_variants:
                continue
                
            template_attrs = set()
            for variant in filtered_variants:
                for attr_key in ATTRIBUTES_TO_EXTRACT:
                    val = variant.get(attr_key)
                    if val:
                        attr_name = attr_key.replace("_", " ").title()
                        if attr_name == "Color":
                            attr_name = "Colour"
                        if attr_name == "Size" and val in SIZE_MAPPING:
                            val = SIZE_MAPPING[val]
                            
                        template_attrs.add(attr_name)
                        if attr_name not in attributes:
                            attributes[attr_name] = set()
                        attributes[attr_name].add(str(val))
                        
            static_attrs = TEMPLATE_STATIC_ATTRIBUTES.get(prod_name, {})
            for static_attr_name, static_attr_val in static_attrs.items():
                template_attrs.add(static_attr_name)
                if static_attr_name not in attributes:
                    attributes[static_attr_name] = set()
                attributes[static_attr_name].add(str(static_attr_val))
                
            templates_data.append({
                "template_name": prod_name,
                "template_id": prod_id,
                "item_group": "Sub Assemblies",
                "attributes": list(template_attrs),
                "variants": filtered_variants
            })

    # 2. Ensure Attributes exist
    for attr_name, attr_values in attributes.items():
        ensure_item_attribute(attr_name, attr_values)
        
    frappe.db.commit()

    # 3. Upsert Templates and Variants
    from erpnext.controllers.item_variant import create_variant
    
    for t_data in templates_data:
        template_name = t_data["template_name"]
        has_variant_attr = bool(t_data["attributes"])
        
        # If the item doesn't have variants, its printrove ID should be the single variant's ID
        # Otherwise, the template gets the parent ID, and variants get their own IDs
        main_printrove_id = str(t_data["template_id"])
        if not has_variant_attr and len(t_data["variants"]) > 0:
            main_printrove_id = str(t_data["variants"][0].get("id"))
            
        if not frappe.db.exists("Item Group", t_data["item_group"]):
            frappe.get_doc({
                "doctype": "Item Group",
                "item_group_name": t_data["item_group"],
                "parent_item_group": "All Item Groups",
                "is_group": 0
            }).insert(ignore_permissions=True)
                
        # Check if template/item exists
        existing_item = frappe.db.get_value("Item", {"item_name": template_name}, "name")
        
        if not existing_item:
            # Create template/item
            doc = frappe.new_doc("Item")
            doc.item_name = template_name
            doc.item_code = template_name
            doc.item_group = t_data["item_group"]
            
            if t_data["attributes"]:
                doc.has_variants = 1
            else:
                doc.has_variants = 0
                
            doc.is_stock_item = 1
            doc.stock_uom = "Nos"
            doc.delivered_by_supplier = 1
            doc.printrove_id = main_printrove_id
            doc.printrove_base_product_id = str(t_data["template_id"])
            
            if doc.meta.has_field("gst_hsn_code"):
                doc.gst_hsn_code = "61091000"
            
            if has_variant_attr:
                for attr in t_data["attributes"]:
                    include_in_code = 1 if attr in ["Size", "Colour"] else 0
                    doc.append("attributes", {
                        "attribute": attr,
                        "include_in_item_code": include_in_code
                    })
            else:
                # Set price and weight if there's no variant
                if len(t_data["variants"]) > 0:
                    first_var = t_data["variants"][0]
                    doc.valuation_rate = first_var.get("base_price", 0)
                    if first_var.get("weight"):
                        doc.weight_per_unit = first_var.get("weight") / 1000.0
                        doc.weight_uom = "Kg"
                        
            ensure_supplier_item(doc, "Printrove Products Private Limited", main_printrove_id)
                    
            doc.insert(ignore_permissions=True)
            existing_item = doc.name
            frappe.logger().info(f"Created Item/Template: {existing_item}")
        else:
            # Upsert template/item
            doc = frappe.get_doc("Item", existing_item)
            changed = False
            
            if doc.item_group != t_data["item_group"]:
                doc.item_group = t_data["item_group"]
                changed = True

            if not doc.delivered_by_supplier:
                doc.delivered_by_supplier = 1
                changed = True

            if doc.printrove_id != main_printrove_id:
                doc.printrove_id = main_printrove_id
                changed = True

            if doc.get("printrove_base_product_id") != str(t_data["template_id"]):
                doc.printrove_base_product_id = str(t_data["template_id"])
                changed = True

            if has_variant_attr and not doc.has_variants:
                doc.has_variants = 1
                changed = True
                
            if has_variant_attr:
                existing_attrs = {row.attribute: row for row in doc.attributes}
                for attr in t_data["attributes"]:
                    include_in_code = 1 if attr in ["Size", "Colour"] else 0
                    if attr not in existing_attrs:
                        doc.append("attributes", {
                            "attribute": attr,
                            "include_in_item_code": include_in_code
                        })
                        changed = True
                    else:
                        row = existing_attrs[attr]
                        if getattr(row, "include_in_item_code", None) != include_in_code:
                            row.include_in_item_code = include_in_code
                            changed = True
            else:
                if len(t_data["variants"]) > 0:
                    first_var = t_data["variants"][0]
                    val_rate = first_var.get("base_price", 0)
                    if doc.valuation_rate != val_rate:
                        doc.valuation_rate = val_rate
                        changed = True
                        
                    if first_var.get("weight"):
                        weight = first_var.get("weight") / 1000.0
                        if doc.weight_per_unit != weight:
                            doc.weight_per_unit = weight
                            doc.weight_uom = "Kg"
                            changed = True
                            
            if ensure_supplier_item(doc, "Printrove Products Private Limited", main_printrove_id):
                changed = True
                
            if changed:
                doc.save(ignore_permissions=True)
                frappe.logger().info(f"Updated Item/Template: {existing_item}")
                
        frappe.db.commit()

        # If it doesn't have variants, we don't process child variants
        if not has_variant_attr:
            continue

        # Upsert Variants
        for variant in t_data["variants"]:
            var_id = variant.get("id")
            
            variant_attributes = {}
            attr_values_list = []
            
            for attr_key in ATTRIBUTES_TO_EXTRACT:
                val = variant.get(attr_key)
                if val:
                    attr_name = attr_key.replace("_", " ").title()
                    if attr_name == "Color":
                        attr_name = "Colour"
                    if attr_name == "Size" and val in SIZE_MAPPING:
                        val = SIZE_MAPPING[val]
                        
                    variant_attributes[attr_name] = val
                    attr_values_list.append(str(val))
            
            static_attrs = TEMPLATE_STATIC_ATTRIBUTES.get(template_name, {})
            for static_attr_name, static_attr_val in static_attrs.items():
                variant_attributes[static_attr_name] = static_attr_val
                    
            variant_item_name = template_name
            if attr_values_list:
                variant_item_name += " - " + " - ".join(attr_values_list)
            
            existing_variant = frappe.db.get_value("Item", {"printrove_id": str(var_id)}, "name")
            
            if not existing_variant:
                try:
                    var_doc = create_variant(existing_item, variant_attributes)
                    var_doc.item_name = variant_item_name
                    var_doc.printrove_id = str(var_id)
                    var_doc.delivered_by_supplier = 1
                    var_doc.valuation_rate = variant.get("base_price", 0)
                    if variant.get("weight"):
                        var_doc.weight_per_unit = variant.get("weight") / 1000.0
                        var_doc.weight_uom = "Kg"
                        
                    ensure_supplier_item(var_doc, "Printrove Products Private Limited", str(var_id))
                            
                    var_doc.insert(ignore_permissions=True)
                    frappe.db.commit()
                except Exception as e:
                    frappe.logger().error(f"Failed to create variant {var_id}: {e}")
                    frappe.db.rollback()
            else:
                try:
                    var_doc = frappe.get_doc("Item", existing_variant)
                    changed = False
                    
                    if var_doc.item_name != variant_item_name:
                        var_doc.item_name = variant_item_name
                        changed = True

                    if not var_doc.delivered_by_supplier:
                        var_doc.delivered_by_supplier = 1
                        changed = True

                    if var_doc.printrove_id != str(var_id):
                        var_doc.printrove_id = str(var_id)
                        changed = True
                        
                    val_rate = variant.get("base_price", 0)
                    if var_doc.valuation_rate != val_rate:
                        var_doc.valuation_rate = val_rate
                        changed = True
                        
                    if variant.get("weight"):
                        weight = variant.get("weight") / 1000.0
                        if var_doc.weight_per_unit != weight:
                            var_doc.weight_per_unit = weight
                            var_doc.weight_uom = "Kg"
                            changed = True
                            
                    if ensure_supplier_item(var_doc, "Printrove Products Private Limited", str(var_id)):
                        changed = True
                        
                    existing_var_attrs = {}
                    for row in var_doc.attributes:
                        existing_var_attrs[row.attribute] = row

                    for attr_name, attr_val in variant_attributes.items():
                        if attr_name not in existing_var_attrs:
                            var_doc.append("attributes", {
                                "attribute": attr_name,
                                "attribute_value": attr_val
                            })
                            changed = True
                        elif existing_var_attrs[attr_name].attribute_value != attr_val:
                            existing_var_attrs[attr_name].attribute_value = attr_val
                            changed = True

                    if changed:
                        var_doc.save(ignore_permissions=True)
                        frappe.db.commit()
                except Exception as e:
                    frappe.logger().error(f"Failed to update variant {var_id}: {e}")
                    frappe.db.rollback()
                    
    frappe.logger().info("Finished Printrove Catalog Seed")

