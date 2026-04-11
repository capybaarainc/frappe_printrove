import frappe
def execute():
    logs = frappe.get_all('Error Log', fields=['method', 'error'], order_by='creation desc', limit=1)
    for log in logs:
        print('--- LOG ---')
        print(log.method)
        print(log.error)
