import os
import time
import unittest
from time import perf_counter

from fastapi.testclient import TestClient

from main import app
from database import get_connection
from tests.test_helpers import create_test_user, delete_test_user


class HandoverReadinessTests(unittest.TestCase):
    def test_critical_chains_and_heavy_endpoints(self):
        suffix = f"{os.getpid()}_{int(time.time())}"
        article = f"WF-HO-{suffix}"
        users = {
            "director": create_test_user(role="Директор", name_prefix="Handover Director"),
            "manager": create_test_user(role="Менеджер", name_prefix="Handover Manager"),
            "accounting": create_test_user(role="Бухгалтерия", name_prefix="Handover Accounting"),
            "warehouse": create_test_user(role="Склад", name_prefix="Handover Warehouse"),
            "production": create_test_user(role="Производство и ОТК", name_prefix="Handover Production"),
            "legal": create_test_user(role="Юрист", name_prefix="Handover Legal"),
            "employee": create_test_user(role="Сотрудник", name_prefix="Handover Employee"),
        }
        clients = {key: TestClient(app) for key in users}
        created = {
            "client_id": 0,
            "project_id": 0,
            "document_id": 0,
            "document_task_id": 0,
            "payment_id": 0,
            "purchase_id": 0,
            "purchase_linked_payment_id": 0,
            "reservation_id": 0,
            "sales_id": 0,
            "sales_linked_payment_id": 0,
            "production_id": 0,
            "template_id": 0,
            "print_form_ids": [],
        }
        client_name = f"HO Client {suffix}"
        project_name = f"HO Project {suffix}"
        document_number = f"HO-DOC-{suffix}"
        sales_number = f"HO-SALES-{suffix}"
        timings = {}
        try:
            for key, user in users.items():
                login = clients[key].post("/api/login", json={"email": user["email"], "password": user["password"]})
                self.assertEqual(login.status_code, 200, msg=f"login failed for {key}")

            session = clients["manager"].get("/api/session")
            self.assertEqual(session.status_code, 200)
            session_json = session.json()
            self.assertEqual(session_json["status"], "approved")
            self.assertEqual(session_json["role"], "Менеджер")

            create_client = clients["manager"].post("/api/clients", json={
                "name": client_name,
                "inn": f"77{int(time.time()):08d}"[-10:],
                "contact": "handover@example.com",
            })
            self.assertEqual(create_client.status_code, 200)

            create_project = clients["manager"].post("/api/projects", json={
                "name": project_name,
                "contract": "HO-001",
                "client": client_name,
                "manager": users["manager"]["name"],
                "budget": 250000,
                "costs": 0,
                "team": [users["employee"]["name"], users["production"]["name"]],
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
                "correspondent": client_name,
                "subject": "Документ handover smoke",
                "status": "registered",
                "project_id": created["project_id"],
                "contract_id": 0,
                "object_id": 0,
                "parent_id": 0,
                "priority": "normal",
                "resolution": "Подготовить ответ клиенту",
                "resolution_author": users["manager"]["name"],
                "resolution_deadline": "21.04.2026",
                "resolution_assignee": users["employee"]["name"],
                "resolution_task_id": 0,
            })
            self.assertEqual(create_document.status_code, 200)
            create_document_json = create_document.json()
            created["document_id"] = int(create_document_json["id"])
            created["document_task_id"] = int(create_document_json["resolution_task_id"])
            self.assertGreater(created["document_task_id"], 0)

            employee_tasks = clients["employee"].get("/api/tasks")
            self.assertEqual(employee_tasks.status_code, 200)
            self.assertTrue(any(int(item["id"]) == created["document_task_id"] for item in employee_tasks.json()))

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
                "title": "HO Payment",
                "kind": "incoming",
                "category": "payment",
                "amount": 64000,
                "currency": "RUB",
                "due_date": "23.04.2026",
                "paid_date": "",
                "status": "planned",
                "comment": "handover payment",
            })
            self.assertEqual(create_payment.status_code, 200)
            created["payment_id"] = int(create_payment.json()["id"])

            project_payments = clients["accounting"].get(f"/api/finance/payments?project_id={created['project_id']}")
            self.assertEqual(project_payments.status_code, 200)
            self.assertTrue(any(int(item["id"]) == created["payment_id"] for item in project_payments.json()))

            create_nomenclature = clients["director"].post("/api/nomenclature", json={
                "name": "Handover Кабель",
                "article": article,
                "unit": "шт",
                "price": 1500,
                "stock": 0,
                "currency": "RUB",
                "group_name": "Demo",
                "default_warehouse": "Главный склад",
            })
            self.assertEqual(create_nomenclature.status_code, 200)

            create_purchase = clients["warehouse"].post("/api/purchases", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "item_article": article,
                "item_name": "Handover Кабель",
                "supplier": "ООО Снабжение HO",
                "supplier_id": 0,
                "qty": 8,
                "unit": "шт",
                "unit_price": 1500,
                "planned_unit_price": 1450,
                "status": "received",
                "expected_date": "20.04.2026",
                "planned_delivery_date": "20.04.2026",
                "received_date": "20.04.2026",
                "delivered_qty": 8,
                "request_status": "approved",
                "approval_status": "approved",
                "schedule_status": "received",
                "lead_time_days": 2,
                "comment": "handover purchase",
            })
            self.assertEqual(create_purchase.status_code, 200)
            purchase_json = create_purchase.json()
            created["purchase_id"] = int(purchase_json["id"])
            created["purchase_linked_payment_id"] = int(purchase_json["linked_payment_id"])
            self.assertGreater(created["purchase_linked_payment_id"], 0)

            stock_add = clients["director"].post(f"/api/nomenclature/{article}/movement_detailed", json={
                "type": "add",
                "qty": 8,
                "from_warehouse": "",
                "from_bin": "",
                "to_warehouse": "Главный склад",
                "to_bin": "A-01",
                "batch_code": "",
                "serial_no": "",
                "comment": "handover stock add",
            })
            self.assertEqual(stock_add.status_code, 200)

            create_reservation = clients["warehouse"].post("/api/stock/reservations", json={
                "project_id": created["project_id"],
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "nomenclature_article": article,
                "nomenclature_name": "Handover Кабель",
                "qty": 3,
                "warehouse": "Главный склад",
                "bin_code": "A-01",
                "batch_code": "",
                "serial_no": "",
                "comment": "handover reserve",
            })
            self.assertEqual(create_reservation.status_code, 200)
            created["reservation_id"] = int(create_reservation.json()["id"])

            fulfill_reservation = clients["warehouse"].post(f"/api/stock/reservations/{created['reservation_id']}/fulfill", json={
                "qty": 3,
                "warehouse": "Главный склад",
                "bin_code": "A-01",
                "batch_code": "",
                "serial_no": "",
                "comment": "handover fulfill",
            })
            self.assertEqual(fulfill_reservation.status_code, 200)
            self.assertEqual(fulfill_reservation.json()["reservation_status"], "fulfilled")

            create_sales = clients["manager"].post("/api/sales/documents", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "doc_type": "invoice",
                "doc_number": sales_number,
                "doc_date": "18.04.2026",
                "amount": 92000,
                "currency": "RUB",
                "status": "issued",
                "payment_status": "planned",
                "linked_payment_id": 0,
                "customer_order_no": "HO-PO-001",
                "shipment_status": "ready",
                "payment_due_date": "25.04.2026",
                "planned_ship_date": "21.04.2026",
                "shipped_at": "",
                "reserve_status": "none",
                "reserve_qty": 0,
                "price_list_id": 0,
                "discount_percent": 0,
                "discount_amount": 0,
                "comment": "handover sales",
                "recipient_email": "buyer@example.com",
                "sent_status": "draft",
                "sent_at": "",
                "delivered_at": "",
                "confirmed_at": "",
            })
            self.assertEqual(create_sales.status_code, 200)
            sales_json = create_sales.json()
            created["sales_id"] = int(sales_json["id"])
            created["sales_linked_payment_id"] = int(sales_json["linked_payment_id"])
            self.assertGreater(created["sales_linked_payment_id"], 0)

            create_production = clients["production"].post("/api/production/orders", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "order_name": "HO Production",
                "stage": "queue",
                "priority": "high",
                "planned_start": "19.04.2026",
                "planned_finish": "24.04.2026",
                "actual_finish": "",
                "progress": 0,
                "responsible": users["production"]["name"],
                "route_name": "Основной",
                "planned_qty": 3,
                "produced_qty": 0,
                "scrap_qty": 0,
                "planned_cost": 30000,
                "actual_cost": 0,
                "labor_hours_plan": 12,
                "labor_hours_fact": 0,
                "comment": "handover production",
            })
            self.assertEqual(create_production.status_code, 200)
            created["production_id"] = int(create_production.json()["id"])

            seed_demo = clients["director"].post("/api/demo/full-seed?force=1")
            self.assertEqual(seed_demo.status_code, 200)
            self.assertEqual(seed_demo.json()["status"], "success")

            create_template = clients["director"].post("/api/documents/templates/deep", json={
                "title": f"HO Template {suffix}",
                "doc_type": "incoming",
                "template_kind": "editable",
                "version_label": "v1",
                "body_text": "Шаблон для handover smoke",
                "variables": [],
                "status": "active",
                "comment": "handover template",
            })
            self.assertEqual(create_template.status_code, 200)
            created["template_id"] = int(create_template.json()["id"])

            print_set = clients["director"].post(f"/api/docflow/documents/{created['document_id']}/generate_print_set")
            self.assertEqual(print_set.status_code, 200)
            print_set_json = print_set.json()
            self.assertEqual(print_set_json["status"], "success")
            self.assertGreaterEqual(int(print_set_json["count"]), 1)
            created["print_form_ids"] = [int(item["id"]) for item in print_set_json.get("items", [])]

            executive = clients["director"].get("/api/executive/summary")
            self.assertEqual(executive.status_code, 200)
            executive_json = executive.json()
            self.assertIn("metrics", executive_json)

            drilldown = clients["director"].get(f"/api/analytics/drilldown?dimension=client&value_id={created['client_id']}")
            self.assertEqual(drilldown.status_code, 200)
            drilldown_json = drilldown.json()
            self.assertIn("summary", drilldown_json)
            self.assertGreaterEqual(int(drilldown_json["summary"].get("rows_total", 0)), 1)

            export_snapshot = clients["director"].get("/api/erp/export")
            self.assertEqual(export_snapshot.status_code, 200)
            export_json = export_snapshot.json()
            self.assertIn("summary", export_json)
            self.assertIn("processes", export_json)

            performance_cases = {
                "main_projects": clients["director"],
                "documents": clients["director"],
                "clients": clients["director"],
                "executive": clients["director"],
                "stock_ops": clients["director"],
                "production": clients["director"],
                "big_tables_finance": clients["director"],
            }
            performance_urls = {
                "main_projects": f"/api/projects?user_name={users['director']['name']}&user_role=Директор&is_head=0",
                "documents": "/api/documents",
                "clients": "/api/clients",
                "executive": "/api/executive/summary",
                "stock_ops": "/api/stock/movements",
                "production": "/api/production/orders",
                "big_tables_finance": "/api/finance/payments",
            }
            for key, client in performance_cases.items():
                started = perf_counter()
                response = client.get(performance_urls[key])
                timings[key] = round(perf_counter() - started, 3)
                self.assertEqual(response.status_code, 200, msg=f"{key} endpoint failed")
                self.assertLess(timings[key], 3.5, msg=f"{key} is too slow: {timings[key]}s")
        finally:
            conn = get_connection()
            c = conn.cursor()
            if created["print_form_ids"]:
                placeholders = ", ".join(["?"] * len(created["print_form_ids"]))
                c.execute(f"DELETE FROM document_print_forms WHERE id IN ({placeholders})", tuple(created["print_form_ids"]))
            if created["template_id"]:
                c.execute("DELETE FROM document_templates WHERE id=?", (created["template_id"],))
            if created["production_id"]:
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='production_order' AND entity_id=?", (created["production_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='production_order' AND entity_id=?", (created["production_id"],))
                c.execute("DELETE FROM production_orders WHERE id=?", (created["production_id"],))
            if created["sales_linked_payment_id"]:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (created["sales_linked_payment_id"],))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (created["sales_linked_payment_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (created["sales_linked_payment_id"],))
                c.execute("DELETE FROM finance_payments WHERE id=?", (created["sales_linked_payment_id"],))
            if created["sales_id"]:
                c.execute("DELETE FROM accounting_entries WHERE source_type='sales_document' AND source_id=?", (created["sales_id"],))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='sales_document' AND entity_id=?", (created["sales_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='sales_document' AND entity_id=?", (created["sales_id"],))
                c.execute("DELETE FROM finance_payments WHERE source_document_type='sales_document' AND source_document_id=?", (created["sales_id"],))
                c.execute("DELETE FROM sales_documents_extended WHERE id=?", (created["sales_id"],))
            if created["reservation_id"]:
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='stock_reservation' AND entity_id=?", (created["reservation_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='stock_reservation' AND entity_id=?", (created["reservation_id"],))
                c.execute("DELETE FROM stock_movements WHERE reservation_id=?", (created["reservation_id"],))
                c.execute("DELETE FROM stock_reservations WHERE id=?", (created["reservation_id"],))
            c.execute("DELETE FROM stock_movements WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_lots WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_balances WHERE article=?", (article,))
            c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
            if created["purchase_linked_payment_id"]:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (created["purchase_linked_payment_id"],))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (created["purchase_linked_payment_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (created["purchase_linked_payment_id"],))
                c.execute("DELETE FROM finance_payments WHERE id=?", (created["purchase_linked_payment_id"],))
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
            if created["document_task_id"]:
                c.execute("DELETE FROM notifications WHERE entity_type='task' AND entity_id=?", (str(created["document_task_id"]),))
                c.execute("DELETE FROM tasks WHERE id=?", (created["document_task_id"],))
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
