import os
import unittest

from fastapi.testclient import TestClient

from main import app
from database import get_connection
from tests.test_helpers import create_test_user, delete_test_user


class EmployeeWorkflowSmokeTests(unittest.TestCase):
    def test_employee_workflow_smoke(self):
        users = {
            "manager": create_test_user(role="Менеджер", name_prefix="Workflow Manager"),
            "accounting": create_test_user(role="Бухгалтерия", name_prefix="Workflow Accounting"),
            "warehouse": create_test_user(role="Склад", name_prefix="Workflow Warehouse"),
            "production": create_test_user(role="Производство и ОТК", name_prefix="Workflow Production"),
            "legal": create_test_user(role="Юрист", name_prefix="Workflow Legal"),
            "employee": create_test_user(role="Сотрудник", name_prefix="Workflow Employee"),
        }
        clients = {key: TestClient(app) for key in users}
        created = {
            "client_id": 0,
            "project_id": 0,
            "document_id": 0,
            "task_id": 0,
            "approval_id": 0,
            "payment_id": 0,
            "purchase_id": 0,
            "sales_id": 0,
            "production_id": 0,
        }
        client_name = f"QA Workflow Client {os.getpid()}"
        project_name = f"QA Workflow Project {os.getpid()}"
        document_number = f"WF-DOC-{os.getpid()}"
        approval_title = f"WF Approval {os.getpid()}"
        task_title = f"WF Task {os.getpid()}"
        try:
            for key, user in users.items():
                login = clients[key].post("/api/login", json={"email": user["email"], "password": user["password"]})
                self.assertEqual(login.status_code, 200, msg=f"login failed for {key}")

            create_client = clients["manager"].post("/api/clients", json={
                "name": client_name,
                "inn": f"77{os.getpid():08d}"[-10:],
                "contact": "workflow@example.com",
            })
            self.assertEqual(create_client.status_code, 200)

            create_project = clients["manager"].post("/api/projects", json={
                "name": project_name,
                "contract": "WF-001",
                "client": client_name,
                "manager": users["manager"]["name"],
                "budget": 120000,
                "costs": 0,
                "team": [users["employee"]["name"]],
                "checklist": [],
                "allowed_roles": ["Юрист", "Склад", "Производство и ОТК", "Бухгалтерия"],
                "nomenclature": [],
                "archive_details": {},
            })
            self.assertEqual(create_project.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
            created["client_id"] = int(c.fetchone()[0])
            c.execute("SELECT id FROM projects WHERE name=? ORDER BY id DESC LIMIT 1", (project_name,))
            created["project_id"] = int(c.fetchone()[0])
            conn.close()

            create_document = clients["manager"].post("/api/documents", json={
                "type": "incoming",
                "number": document_number,
                "d_date": "18.04.2026",
                "correspondent": "ООО Workflow",
                "subject": "Проверка входящего документа",
                "status": "registered",
                "project_id": created["project_id"],
                "contract_id": 0,
                "object_id": 0,
                "parent_id": 0,
                "priority": "normal",
                "resolution": "",
                "resolution_author": "",
                "resolution_deadline": "",
                "resolution_assignee": "",
                "resolution_task_id": 0,
            })
            self.assertEqual(create_document.status_code, 200)
            created["document_id"] = int(create_document.json()["id"])

            create_task = clients["employee"].post("/api/tasks", json={
                "title": task_title,
                "description": "Сотрудник создал рабочее поручение",
                "author": users["employee"]["name"],
                "executor": users["employee"]["name"],
                "deadline": "21.04.2026",
                "recurrence": "none",
                "priority": "normal",
                "project_id": created["project_id"],
            })
            self.assertEqual(create_task.status_code, 200)
            tasks = clients["employee"].get("/api/tasks")
            self.assertEqual(tasks.status_code, 200)
            task_row = next(item for item in tasks.json() if item["title"] == task_title)
            created["task_id"] = int(task_row["id"])

            create_approval = clients["manager"].post("/api/approvals", json={
                "title": approval_title,
                "item_link": f"/projects/{created['project_id']}",
                "route": [users["legal"]["name"]],
                "author": users["manager"]["name"],
            })
            self.assertEqual(create_approval.status_code, 200)

            legal_approvals = clients["legal"].get("/api/approvals")
            self.assertEqual(legal_approvals.status_code, 200)
            approval_row = next(item for item in legal_approvals.json() if item["title"] == approval_title)
            created["approval_id"] = int(approval_row["id"])
            self.assertIn(users["legal"]["name"], approval_row["route"][0])

            create_payment = clients["accounting"].post("/api/finance/payments", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "treasury_article_id": 0,
                "vat_rate_id": 0,
                "source_document_type": "",
                "source_document_id": 0,
                "title": "WF Payment",
                "kind": "incoming",
                "category": "payment",
                "amount": 55000,
                "currency": "RUB",
                "due_date": "22.04.2026",
                "paid_date": "",
                "status": "planned",
                "comment": "Smoke payment",
            })
            self.assertEqual(create_payment.status_code, 200)
            created["payment_id"] = int(create_payment.json()["id"])

            create_purchase = clients["warehouse"].post("/api/purchases", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "item_article": "WF-ITEM-001",
                "item_name": "Позиция склада",
                "supplier": "Workflow Supplier",
                "supplier_id": 0,
                "qty": 5,
                "unit": "шт",
                "unit_price": 3200,
                "planned_unit_price": 3000,
                "status": "planned",
                "expected_date": "24.04.2026",
                "planned_delivery_date": "24.04.2026",
                "received_date": "",
                "delivered_qty": 0,
                "request_status": "draft",
                "approval_status": "not_required",
                "schedule_status": "planned",
                "lead_time_days": 4,
                "comment": "Smoke purchase",
            })
            self.assertEqual(create_purchase.status_code, 200)
            created["purchase_id"] = int(create_purchase.json()["id"])

            create_sales = clients["manager"].post("/api/sales/documents", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "doc_type": "invoice",
                "doc_number": f"WF-INV-{os.getpid()}",
                "doc_date": "18.04.2026",
                "amount": 78000,
                "currency": "RUB",
                "status": "issued",
                "payment_status": "planned",
                "linked_payment_id": 0,
                "customer_order_no": "WF-PO-001",
                "shipment_status": "ready",
                "payment_due_date": "25.04.2026",
                "planned_ship_date": "22.04.2026",
                "shipped_at": "",
                "reserve_status": "none",
                "reserve_qty": 0,
                "price_list_id": 0,
                "discount_percent": 0,
                "discount_amount": 0,
                "comment": "Smoke sales",
                "recipient_email": "buyer@example.com",
                "sent_status": "draft",
                "sent_at": "",
                "delivered_at": "",
                "confirmed_at": "",
            })
            self.assertEqual(create_sales.status_code, 200)
            created["sales_id"] = int(create_sales.json()["id"])

            create_production = clients["production"].post("/api/production/orders", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "order_name": "WF Production Order",
                "stage": "queue",
                "priority": "high",
                "planned_start": "19.04.2026",
                "planned_finish": "26.04.2026",
                "actual_finish": "",
                "progress": 0,
                "responsible": users["production"]["name"],
                "route_name": "",
                "planned_qty": 10,
                "produced_qty": 0,
                "scrap_qty": 0,
                "planned_cost": 42000,
                "actual_cost": 0,
                "labor_hours_plan": 16,
                "labor_hours_fact": 0,
                "comment": "Smoke production",
            })
            self.assertEqual(create_production.status_code, 200)
            created["production_id"] = int(create_production.json()["id"])

            dossier = clients["employee"].get(f"/api/clients/{created['client_id']}/dossier")
            self.assertEqual(dossier.status_code, 200)
            dossier_json = dossier.json()
            self.assertEqual(int(dossier_json["client"]["id"]), created["client_id"])

            forbidden_payment = clients["employee"].post("/api/finance/payments", json={
                "title": "Employee should not create payment",
                "kind": "incoming",
                "category": "payment",
                "amount": 1000,
                "currency": "RUB",
                "status": "planned",
                "due_date": "22.04.2026",
                "project_id": created["project_id"],
                "client_id": created["client_id"],
            })
            self.assertEqual(forbidden_payment.status_code, 200)
            self.assertEqual(forbidden_payment.json()["error"], "forbidden")
        finally:
            conn = get_connection()
            c = conn.cursor()
            if created["production_id"]:
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='production_order' AND entity_id=?", (created["production_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='production_order' AND entity_id=?", (created["production_id"],))
                c.execute("DELETE FROM production_orders WHERE id=?", (created["production_id"],))
            if created["sales_id"]:
                c.execute("DELETE FROM accounting_entries WHERE source_type='sales_document' AND source_id=?", (created["sales_id"],))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='sales_document' AND entity_id=?", (created["sales_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='sales_document' AND entity_id=?", (created["sales_id"],))
                c.execute("DELETE FROM finance_payments WHERE source_document_type='sales_document' AND source_document_id=?", (created["sales_id"],))
                c.execute("DELETE FROM sales_documents_extended WHERE id=?", (created["sales_id"],))
            if created["purchase_id"]:
                c.execute("DELETE FROM accounting_entries WHERE source_type='purchase_order' AND source_id=?", (created["purchase_id"],))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='purchase_order' AND entity_id=?", (created["purchase_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='purchase_order' AND entity_id=?", (created["purchase_id"],))
                c.execute("DELETE FROM finance_payments WHERE source_document_type='purchase_order' AND source_document_id=?", (created["purchase_id"],))
                c.execute("DELETE FROM purchase_orders WHERE id=?", (created["purchase_id"],))
            if created["payment_id"]:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (created["payment_id"],))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (created["payment_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (created["payment_id"],))
                c.execute("DELETE FROM finance_payments WHERE id=?", (created["payment_id"],))
            if created["approval_id"]:
                c.execute("DELETE FROM notifications WHERE entity_type='approval' AND entity_id=?", (str(created["approval_id"]),))
                c.execute("DELETE FROM approvals WHERE id=?", (created["approval_id"],))
            if created["task_id"]:
                c.execute("DELETE FROM notifications WHERE entity_type='task' AND entity_id=?", (str(created["task_id"]),))
                c.execute("DELETE FROM tasks WHERE id=?", (created["task_id"],))
            if created["document_id"]:
                c.execute("DELETE FROM notifications WHERE entity_type='document' AND entity_id=?", (str(created["document_id"]),))
                c.execute("DELETE FROM documents WHERE id=?", (created["document_id"],))
            if created["project_id"]:
                c.execute("DELETE FROM projects WHERE id=?", (created["project_id"],))
            if created["client_id"]:
                c.execute("DELETE FROM contacts WHERE client_id=?", (created["client_id"],))
                c.execute("DELETE FROM clients WHERE id=?", (created["client_id"],))
            conn.commit()
            conn.close()
            for user in users.values():
                delete_test_user(user["email"])


if __name__ == "__main__":
    unittest.main()
