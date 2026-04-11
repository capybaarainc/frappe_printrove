// Copyright (c) 2024, Aquiveal and contributors
// For license information, please see license.txt

frappe.ui.form.on("Printrove Settings", {
	refresh(frm) {
		if (frm.doc.enable_printrove) {
			frm.add_custom_button(__("Sync Catalog"), function () {
				frappe.call({
					method: "get_catalog",
					doc: frm.doc,
					freeze: true,
					freeze_message: __("Queuing sync..."),
					callback: function (r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __("Catalog synchronization queued."),
								indicator: "green",
							});
						}
					},
				});
			});
		}
	},
});
