import os
import time
import unittest

from fastapi.testclient import TestClient

from main import app
from database import get_connection
from tests.test_helpers import create_test_user, delete_test_user, run_db_cleanup


class SelfServiceAndManagerWorkbenchTests(unittest.TestCase):
    def test_employee_self_service_summary_tracks_hr_requests(self):
        employee = create_test_user(role="Сотрудник", name_prefix="Self Service Employee")
        client = TestClient(app)
        try:
            login = client.post("/api/login", json={"email": employee["email"], "password": employee["password"]})
            self.assertEqual(login.status_code, 200)

            leave = client.post("/api/users/self_service/leave_requests", json={
                "user_email": employee["email"],
                "leave_type": "vacation",
                "date_from": "12.05.2026",
                "date_to": "16.05.2026",
                "deputy_name": "",
                "status": "pending",
                "comment": "Плановый отпуск",
            })
            self.assertEqual(leave.status_code, 200)

            timesheet = client.post("/api/users/self_service/timesheets", json={
                "user_email": employee["email"],
                "entry_date": time.strftime("%d.%m.%Y"),
                "project_id": 0,
                "hours": 7.5,
                "work_mode": "remote",
                "status": "submitted",
                "comment": "Подготовка документов",
            })
            self.assertEqual(timesheet.status_code, 200)

            equipment = client.post("/api/users/self_service/equipment_requests", json={
                "user_email": employee["email"],
                "category": "hardware",
                "item_name": "Ноутбук",
                "qty": 1,
                "needed_by": "30.04.2026",
                "justification": "Для удаленной работы",
                "status": "pending",
                "comment": "Нужен новый ноутбук",
            })
            self.assertEqual(equipment.status_code, 200)

            substitution = client.post("/api/users/self_service/substitutions", json={
                "user_email": employee["email"],
                "substitute_name": "Коллега QA",
                "date_from": "12.05.2026",
                "date_to": "16.05.2026",
                "reason": "Подмена на период отсутствия",
                "status": "pending",
                "comment": "",
            })
            self.assertEqual(substitution.status_code, 200)

            trip = client.post("/api/users/self_service/business_trips", json={
                "user_email": employee["email"],
                "destination": "Казань",
                "date_from": "20.05.2026",
                "date_to": "22.05.2026",
                "purpose": "Встреча с подрядчиком",
                "transport_mode": "train",
                "estimated_cost": 18000,
                "status": "pending",
                "comment": "Командировка по проекту",
            })
            self.assertEqual(trip.status_code, 200)

            summary = client.get("/api/users/self_service/summary")
            self.assertEqual(summary.status_code, 200)
            payload = summary.json()
            self.assertGreaterEqual(int(payload["metrics"]["leave_pending"]), 1)
            self.assertGreaterEqual(float(payload["metrics"]["timesheet_hours_month"]), 7.5)
            self.assertGreaterEqual(int(payload["metrics"]["equipment_open"]), 1)
            self.assertGreaterEqual(int(payload["metrics"]["substitutions_active"]), 1)
            self.assertGreaterEqual(int(payload["metrics"]["business_trips_open"]), 1)
            self.assertTrue(any(item["item_name"] == "Ноутбук" for item in payload["equipment_requests"]))
            self.assertTrue(any(item["destination"] == "Казань" for item in payload["business_trips"]))
        finally:
            run_db_cleanup([
                ("DELETE FROM hr_business_trip_requests WHERE user_email=?", (employee["email"],)),
                ("DELETE FROM hr_substitution_requests WHERE user_email=?", (employee["email"],)),
                ("DELETE FROM hr_equipment_requests WHERE user_email=?", (employee["email"],)),
                ("DELETE FROM hr_timesheet_entries WHERE user_email=?", (employee["email"],)),
                ("DELETE FROM hr_leave_requests WHERE user_email=?", (employee["email"],)),
            ])
            delete_test_user(employee["email"])

    def test_manager_workbench_rolls_up_deal_context(self):
        manager_user = create_test_user(role="Менеджер", name_prefix="Workbench Manager")
        client = TestClient(app)
        created = {"client_id": 0, "project_id": 0, "purchase_id": 0, "sales_id": 0, "payment_id": 0, "document_id": 0, "quote_id": 0, "shipment_id": 0}
        project_name = f"Workbench Project {os.getpid()}"
        client_name = f"Workbench Client {os.getpid()}"
        try:
            login = client.post("/api/login", json={"email": manager_user["email"], "password": manager_user["password"]})
            self.assertEqual(login.status_code, 200)

            create_client_response = client.post("/api/clients", json={
                "name": client_name,
                "inn": f"77{os.getpid():08d}"[-10:],
                "contact": "workbench@example.com",
            })
            self.assertEqual(create_client_response.status_code, 200)

            create_project_response = client.post("/api/projects", json={
                "name": project_name,
                "contract": "WB-001",
                "client": client_name,
                "manager": manager_user["name"],
                "budget": 250000,
                "costs": 0,
                "team": [],
                "checklist": [],
                "allowed_roles": ["Менеджер", "Юрист", "Бухгалтерия"],
                "nomenclature": [],
                "archive_details": {},
            })
            self.assertEqual(create_project_response.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
            created["client_id"] = int(c.fetchone()[0])
            c.execute("SELECT id FROM projects WHERE name=? ORDER BY id DESC LIMIT 1", (project_name,))
            created["project_id"] = int(c.fetchone()[0])
            conn.close()

            purchase = client.post("/api/purchases", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "item_article": "WB-001",
                "item_name": "Поставка кабеля",
                "supplier": "ООО Поставщик WB",
                "supplier_id": 0,
                "qty": 4,
                "unit": "шт",
                "unit_price": 12000,
                "planned_unit_price": 11800,
                "status": "ordered",
                "expected_date": "29.04.2026",
                "planned_delivery_date": "29.04.2026",
                "received_date": "",
                "delivered_qty": 0,
                "request_status": "draft",
                "approval_status": "not_required",
                "schedule_status": "planned",
                "lead_time_days": 5,
                "comment": "Закупка для сделки",
            })
            self.assertEqual(purchase.status_code, 200)
            created["purchase_id"] = int(purchase.json()["id"])

            sales = client.post("/api/sales/documents", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "doc_type": "invoice",
                "doc_number": f"WB-INV-{os.getpid()}",
                "doc_date": "21.04.2026",
                "amount": 47000,
                "currency": "RUB",
                "status": "issued",
                "payment_status": "planned",
                "linked_payment_id": 0,
                "customer_order_no": "WB-PO-1",
                "shipment_status": "ready",
                "payment_due_date": "24.04.2026",
                "planned_ship_date": "23.04.2026",
                "shipped_at": "",
                "reserve_status": "none",
                "reserve_qty": 0,
                "price_list_id": 0,
                "discount_percent": 0,
                "discount_amount": 0,
                "comment": "Реализация по сделке",
                "recipient_email": "buyer@example.com",
                "sent_status": "draft",
                "sent_at": "",
                "delivered_at": "",
                "confirmed_at": "",
            })
            self.assertEqual(sales.status_code, 200)
            created["sales_id"] = int(sales.json()["id"])

            payment = client.post("/api/finance/payments", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "treasury_article_id": 0,
                "vat_rate_id": 0,
                "source_document_type": "sales_document",
                "source_document_id": created["sales_id"],
                "title": "Ожидаемая оплата WB",
                "kind": "incoming",
                "category": "payment",
                "amount": 47000,
                "currency": "RUB",
                "due_date": "20.04.2026",
                "paid_date": "",
                "status": "planned",
                "comment": "Дебиторка по сделке",
            })
            self.assertEqual(payment.status_code, 200)
            created["payment_id"] = int(payment.json()["id"])

            document = client.post("/api/documents", json={
                "type": "outgoing",
                "number": f"WB-DOC-{os.getpid()}",
                "d_date": "21.04.2026",
                "correspondent": client_name,
                "subject": "Коммерческий документ",
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
            self.assertEqual(document.status_code, 200)
            created["document_id"] = int(document.json()["id"])

            conn = get_connection()
            c = conn.cursor()
            now = int(time.time())
            c.execute(
                """
                INSERT INTO sales_quotes (project_id, client_id, contract_id, object_id, title, quote_number, stage, amount, currency, valid_until, responsible, probability, comment, created_by, created_at, updated_at)
                VALUES (?, ?, 0, 0, ?, ?, 'proposal', ?, 'RUB', '30.04.2026', ?, 80, ?, ?, ?, ?)
                """,
                (created["project_id"], created["client_id"], "WB Quote", f"WB-Q-{os.getpid()}", 52000, manager_user["name"], "КП для cockpit", manager_user["email"], now, now),
            )
            created["quote_id"] = int(c.lastrowid or 0)
            c.execute(
                """
                INSERT INTO sales_shipments (customer_order_id, sales_document_id, reservation_id, shipment_number, article, item_name, qty, warehouse, bin_code, batch_code, serial_no, planned_ship_date, shipped_at, status, carrier, tracking_no, comment, created_by, created_at, updated_at)
                VALUES (0, ?, 0, ?, 'WB-001', 'Поставка кабеля', 4, 'Основной склад', 'A-01', '', '', '23.04.2026', '', 'planned', 'WB Carrier', '', 'Ожидает отгрузки', ?, ?, ?)
                """,
                (created["sales_id"], f"WB-SHIP-{os.getpid()}", manager_user["email"], now, now),
            )
            created["shipment_id"] = int(c.lastrowid or 0)
            conn.commit()
            conn.close()

            cockpit = client.get("/api/manager/workbench")
            self.assertEqual(cockpit.status_code, 200)
            payload = cockpit.json()
            self.assertGreaterEqual(int(payload["metrics"]["active_deals"]), 1)
            self.assertGreaterEqual(int(payload["metrics"]["purchases_in_progress"]), 1)
            self.assertGreaterEqual(int(payload["metrics"]["shipments_pending"]), 1)
            self.assertGreaterEqual(float(payload["metrics"]["receivable_open"]), 47000)
            self.assertGreaterEqual(int(payload["metrics"]["documents_open"]), 1)
            self.assertTrue(any(int(item["project_id"]) == created["project_id"] for item in payload["focus_projects"]))
            self.assertTrue(any(item["project_name"] == project_name for item in payload["focus_projects"]))
        finally:
            run_db_cleanup([
                ("DELETE FROM sales_shipments WHERE id=?", (created["shipment_id"],)),
                ("DELETE FROM sales_quotes WHERE id=?", (created["quote_id"],)),
                ("DELETE FROM documents WHERE id=?", (created["document_id"],)),
                ("DELETE FROM finance_payments WHERE id=?", (created["payment_id"],)),
                ("DELETE FROM sales_documents_extended WHERE id=?", (created["sales_id"],)),
                ("DELETE FROM purchase_orders WHERE id=?", (created["purchase_id"],)),
                ("DELETE FROM projects WHERE id=?", (created["project_id"],)),
                ("DELETE FROM clients WHERE id=?", (created["client_id"],)),
            ])
            delete_test_user(manager_user["email"])
