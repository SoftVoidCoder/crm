import unittest
import os
import json
import io
import time

from fastapi.testclient import TestClient

from main import app
from database import DB_NAME, get_connection
from routers.users import _totp_code
from tests.test_helpers import (
    allocate_test_project_id,
    create_test_user,
    delete_test_user,
    run_db_cleanup,
)


class HealthSessionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Менеджер")

    def tearDown(self):
        delete_test_user(self.user["email"])

    def test_health_endpoints(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

        deep = self.client.get("/api/health/deep")
        self.assertEqual(deep.status_code, 200)
        self.assertIn("checks", deep.json())

    def test_login_creates_server_session(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)
        self.assertIn("korda_session_id", login.cookies)

        session = self.client.get("/api/session")
        self.assertEqual(session.status_code, 200)
        self.assertEqual(session.json()["email"], self.user["email"])

    def test_register_creates_pending_user(self):
        email = f"qa-register-flow-{os.getpid()}-{self.user['email'].split('@')[0]}@example.com"
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM auth_attempts WHERE action='register_ip'")
        conn.commit()
        conn.close()
        res = self.client.post(
            "/api/register",
            json={"name": "QA Register", "email": email, "password": "Strongpass1"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT status FROM users WHERE email=?", (email,))
        row = c.fetchone()
        c.execute("DELETE FROM auth_attempts WHERE action='register_ip'")
        c.execute("DELETE FROM users WHERE email=?", (email,))
        conn.commit()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "pending")

    def test_director_backup_create_and_restore(self):
        director = create_test_user(role="Директор", name_prefix="Backup Director")
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            create_res = self.client.post("/api/system/backup")
            self.assertEqual(create_res.status_code, 200)
            self.assertEqual(create_res.json()["status"], "success")
            filename = create_res.json()["filename"]

            backups = self.client.get("/api/system/backups?limit=5")
            self.assertEqual(backups.status_code, 200)
            self.assertTrue(any(item["filename"] == filename for item in backups.json()))

            with open(DB_NAME, "rb") as current_db:
                restore_res = self.client.post(
                    "/api/system/restore",
                    files={"upload": ("restore_test.db", current_db, "application/octet-stream")},
                )
            self.assertEqual(restore_res.status_code, 200)
            self.assertEqual(restore_res.json()["status"], "success")
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT file_path FROM system_backups WHERE actor_email=?", (director["email"],))
            for (file_path,) in c.fetchall():
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
            c.execute("DELETE FROM system_backups WHERE actor_email=?", (director["email"],))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_bank_and_telephony_auto_linking(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        client_name = f"QA AutoLink Client {os.getpid()}"
        contact_phone = "+7 (999) 111-22-33"
        project_id = 0
        client_id = 0
        payment_id = 0
        telephony_account_id = 0
        telephony_call_id = 0
        bank_line_id = 0
        try:
            client_create = self.client.post("/api/clients", json={"name": client_name, "inn": "7707654321", "contact": "autolink@example.com"})
            self.assertEqual(client_create.status_code, 200)

            project_create = self.client.post("/api/projects", json={
                "name": "QA AutoLink Project",
                "contract": "QA-AL-001",
                "client": client_name,
                "manager": self.user["name"],
                "budget": 0,
                "costs": 0,
                "team": [],
                "checklist": [],
                "allowed_roles": [],
                "nomenclature": [],
                "archive_details": {},
            })
            self.assertEqual(project_create.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
            client_id = int(c.fetchone()[0])
            c.execute("SELECT id FROM projects WHERE name=? ORDER BY id DESC LIMIT 1", ("QA AutoLink Project",))
            project_id = int(c.fetchone()[0])
            conn.close()

            contact_create = self.client.post("/api/contacts", json={
                "client_id": client_id,
                "name": "QA Contact",
                "phone": contact_phone,
                "email": "contact@example.com",
                "position": "Снабжение",
            })
            self.assertEqual(contact_create.status_code, 200)

            telephony_account = self.client.post("/api/telephony/accounts", json={
                "provider_name": "Mango",
                "line_name": "AutoLink line",
                "external_line_id": "AUTO-LINE",
                "is_active": 1,
            })
            self.assertEqual(telephony_account.status_code, 200)
            telephony_account_id = int(telephony_account.json()["id"])

            telephony_call = self.client.post("/api/telephony/calls", json={
                "account_id": telephony_account_id,
                "phone_number": "8 999 111 22 33",
                "direction": "inbound",
                "status": "answered",
                "duration_sec": 32,
                "summary": "Автопривязка по контакту",
            })
            self.assertEqual(telephony_call.status_code, 200)
            telephony_call_id = int(telephony_call.json()["id"])

            calls = self.client.get("/api/telephony/calls")
            self.assertEqual(calls.status_code, 200)
            linked_call = next(item for item in calls.json() if int(item["id"]) == telephony_call_id)
            self.assertEqual(int(linked_call["client_id"]), client_id)
            self.assertEqual(int(linked_call["project_id"]), project_id)
            self.assertEqual(linked_call["contact_name"], "QA Contact")

            system_events = self.client.get("/api/system/events?limit=80&entity_type=telephony_call")
            self.assertEqual(system_events.status_code, 200)
            self.assertTrue(any(item.get("stream_type") == "domain_event" and item.get("entity_id") == str(telephony_call_id) for item in system_events.json()))

            payment_create = self.client.post("/api/finance/payments", json={
                "project_id": project_id,
                "client_id": client_id,
                "title": "QA AutoLink Payment",
                "kind": "incoming",
                "category": "payment",
                "amount": 7777,
                "currency": "RUB",
                "due_date": "13.04.2026",
                "paid_date": "",
                "status": "planned",
                "comment": "Автосопоставление банка",
            })
            self.assertEqual(payment_create.status_code, 200)
            payment_id = int(payment_create.json()["id"])

            bank_import = self.client.post("/api/banking/statements/import", json={
                "bank_account_id": 0,
                "lines": [{
                    "line_date": "13.04.2026",
                    "amount": 7777,
                    "direction": "incoming",
                    "counterparty": client_name,
                    "purpose": "Оплата по договору",
                    "client_id": 0,
                    "payment_id": 0,
                    "external_line_id": f"AUTO-BANK-{os.getpid()}",
                    "comment": "Автосопоставление",
                }],
            })
            self.assertEqual(bank_import.status_code, 200)
            self.assertEqual(bank_import.json()["created"], 1)
            bank_line_id = int(bank_import.json()["ids"][0])

            bank_lines = self.client.get("/api/banking/statements")
            self.assertEqual(bank_lines.status_code, 200)
            matched_line = next(item for item in bank_lines.json() if int(item["id"]) == bank_line_id)
            self.assertEqual(int(matched_line["client_id"]), client_id)
            self.assertEqual(int(matched_line["linked_payment_id"]), payment_id)
            self.assertEqual(matched_line["status"], "reconciled")
        finally:
            conn = get_connection()
            c = conn.cursor()
            if bank_line_id:
                c.execute("DELETE FROM audit_log WHERE entity_type='bank_statement_line' AND entity_id=?", (str(bank_line_id),))
                c.execute("DELETE FROM bank_statement_lines WHERE id=?", (bank_line_id,))
            if payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
                c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?)", (payment_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
            if telephony_call_id:
                c.execute("DELETE FROM notifications WHERE entity_type='telephony_call' AND entity_id=?", (str(telephony_call_id),))
                c.execute("DELETE FROM audit_log WHERE entity_type='telephony_call' AND entity_id=?", (str(telephony_call_id),))
                c.execute("DELETE FROM telephony_calls WHERE id=?", (telephony_call_id,))
            if telephony_account_id:
                c.execute("DELETE FROM audit_log WHERE entity_type='telephony_account' AND entity_id=?", (str(telephony_account_id),))
                c.execute("DELETE FROM telephony_accounts WHERE id=?", (telephony_account_id,))
            if client_id:
                c.execute("DELETE FROM contacts WHERE client_id=?", (client_id,))
                c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            if project_id:
                c.execute("DELETE FROM projects WHERE id=?", (project_id,))
            conn.commit()
            conn.close()

    def test_communications_roundtrip_after_service_refactor(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        meeting_id = 0
        chat_id = 0
        task_id = 0
        try:
            meeting_create = self.client.post("/api/meetings", json={
                "title": "QA Совещание",
                "m_date": "14.04.2026",
                "m_time": "10:30",
                "participants": [self.user["name"]],
                "agenda": ["Проверка service-layer"],
            })
            self.assertEqual(meeting_create.status_code, 200)

            meetings = self.client.get("/api/meetings")
            self.assertEqual(meetings.status_code, 200)
            meeting = next(item for item in meetings.json() if item["title"] == "QA Совещание")
            meeting_id = int(meeting["id"])
            self.assertEqual(meeting["participants"], [self.user["name"]])

            meeting_update = self.client.put(f"/api/meetings/{meeting_id}", json={
                "title": "QA Совещание обновлено",
                "m_date": "14.04.2026",
                "m_time": "11:00",
                "participants": [self.user["name"]],
                "agenda": ["Проверка update"],
                "decisions": {"owner": self.user["name"]},
                "status": "done",
            })
            self.assertEqual(meeting_update.status_code, 200)

            chat_create = self.client.post("/api/chats", json={
                "name": "QA Chat",
                "creator": self.user["name"],
                "participants": [self.user["name"]],
            })
            self.assertEqual(chat_create.status_code, 200)

            chats = self.client.get("/api/chats")
            self.assertEqual(chats.status_code, 200)
            chat = next(item for item in chats.json() if item["name"] == "QA Chat")
            chat_id = int(chat["id"])

            message_create = self.client.post(f"/api/chats/{chat_id}/messages", json={
                "user": self.user["name"],
                "role": self.user["role"],
                "text": "Service refactor smoke",
            })
            self.assertEqual(message_create.status_code, 200)

            messages = self.client.get(f"/api/chats/{chat_id}/messages")
            self.assertEqual(messages.status_code, 200)
            self.assertTrue(any(item["text"] == "Service refactor smoke" for item in messages.json()))

            task_create = self.client.post("/api/tasks", json={
                "title": "QA Task",
                "description": "Проверка задач после выноса сервиса",
                "author": self.user["name"],
                "executor": self.user["name"],
                "deadline": "20.04.2026",
                "recurrence": "none",
                "priority": "normal",
                "project_id": 0,
            })
            self.assertEqual(task_create.status_code, 200)

            tasks = self.client.get("/api/tasks")
            self.assertEqual(tasks.status_code, 200)
            task = next(item for item in tasks.json() if item["title"] == "QA Task")
            task_id = int(task["id"])
            self.assertEqual(task["executor"], self.user["name"])

            task_update = self.client.put(f"/api/tasks/{task_id}", json={
                "status": "done",
                "executor": self.user["name"],
                "history": [{"at": "14.04.2026 11:00", "status": "done"}],
            })
            self.assertEqual(task_update.status_code, 200)

            tasks_after = self.client.get("/api/tasks")
            self.assertEqual(tasks_after.status_code, 200)
            updated_task = next(item for item in tasks_after.json() if int(item["id"]) == task_id)
            self.assertEqual(updated_task["status"], "done")
            self.assertEqual(updated_task["history"][0]["status"], "done")
        finally:
            conn = get_connection()
            c = conn.cursor()
            if task_id:
                c.execute("DELETE FROM notifications WHERE entity_type='task' AND title='Новое поручение'")
                c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            if chat_id:
                c.execute("DELETE FROM global_messages WHERE chat_id=?", (chat_id,))
                c.execute("DELETE FROM global_chats WHERE id=?", (chat_id,))
            if meeting_id:
                c.execute("DELETE FROM meetings WHERE id=?", (meeting_id,))
            conn.commit()
            conn.close()

    def test_finance_module_and_client_dossier(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        client_name = "QA Finance Client"
        client_create = self.client.post("/api/clients", json={"name": client_name, "inn": "7701234567", "contact": "qa@example.com"})
        self.assertEqual(client_create.status_code, 200)

        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM purchase_orders WHERE project_id=?", (991001,))
        c.execute("DELETE FROM sales_documents_extended WHERE project_id=?", (991001,))
        c.execute("DELETE FROM production_orders WHERE project_id=?", (991001,))
        c.execute("DELETE FROM stock_reservations WHERE project_id=?", (991001,))
        c.execute("DELETE FROM projects WHERE id=?", (991001,))
        c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
        client_id = c.fetchone()[0]
        c.execute(
            "INSERT INTO contacts (client_id, name, phone, email, position) VALUES (?, ?, ?, ?, ?)",
            (client_id, "QA Contact", "+79990000000", "contact@example.com", "Менеджер клиента"),
        )
        c.execute(
            """
            INSERT INTO projects (
                id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                subtasks, time_logs, allowed_roles, nomenclature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                991001,
                "QA Finance Project",
                "2026-КРД-QA",
                client_name,
                self.user["name"],
                "active",
                35,
                "{}",
                "{}",
                "{}",
                150000,
                90000,
                "[]",
                "[]",
                "[]",
                "[]",
                "[]",
                "{}",
                "{}",
                "{}",
                "{}",
                "[]",
                "[]",
                "[]",
            ),
        )
        conn.commit()
        conn.close()

        payment_create = self.client.post(
            "/api/finance/payments",
            json={
                "project_id": 991001,
                "client_id": client_id,
                "title": "Аванс по договору",
                "kind": "incoming",
                "category": "advance",
                "amount": 50000,
                "currency": "RUB",
                "due_date": "20.04.2026",
                "paid_date": "",
                "status": "issued",
                "comment": "Проверка finance-модуля",
            },
        )
        self.assertEqual(payment_create.status_code, 200)
        self.assertEqual(payment_create.json()["status"], "success")
        payment_id = payment_create.json()["id"]

        summary = self.client.get("/api/finance/summary")
        self.assertEqual(summary.status_code, 200)
        self.assertGreaterEqual(summary.json()["metrics"]["incoming_open"], 50000)

        dossier = self.client.get(f"/api/clients/{client_id}/dossier")
        self.assertEqual(dossier.status_code, 200)
        dossier_payload = dossier.json()
        self.assertEqual(dossier_payload["client"]["name"], client_name)
        self.assertTrue(any(item["title"] == "Аванс по договору" for item in dossier_payload["finance"]))
        self.assertTrue(any(item["name"] == "QA Finance Project" for item in dossier_payload["projects"]))

        director = create_test_user(role="Директор", name_prefix="Finance Director")
        try:
            director_login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(director_login.status_code, 200)

            delete_payment = self.client.delete(f"/api/finance/payments/{payment_id}")
            self.assertEqual(delete_payment.status_code, 200)
            self.assertEqual(delete_payment.json()["status"], "success")

            payments_after_delete = self.client.get(f"/api/finance/payments?client_id={client_id}")
            self.assertEqual(payments_after_delete.status_code, 200)
            self.assertFalse(any(item["id"] == payment_id for item in payments_after_delete.json()))
        finally:
            delete_test_user(director["email"])

        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM finance_payments WHERE client_id=?", (client_id,))
        c.execute("DELETE FROM contacts WHERE client_id=?", (client_id,))
        c.execute("DELETE FROM projects WHERE id=?", (991001,))
        c.execute("DELETE FROM clients WHERE id=?", (client_id,))
        conn.commit()
        conn.close()

    def test_client_dossier_includes_commercial_and_integration_context(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        client_name = f"QA Dossier Client {os.getpid()}"
        quote_id = 0
        price_list_id = 0
        terms_id = 0
        bank_account_id = 0
        bank_line_id = 0
        telephony_account_id = 0
        telephony_call_id = 0
        project_id = 0
        client_id = 0
        try:
            client_create = self.client.post("/api/clients", json={"name": client_name, "inn": "7707654321", "contact": "dossier@example.com"})
            self.assertEqual(client_create.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
            client_id = int(c.fetchone()[0])
            c.execute(
                """
                INSERT INTO contacts (client_id, name, phone, email, position)
                VALUES (?, ?, ?, ?, ?)
                """,
                (client_id, "QA Dossier Contact", "+79992223344", "dossier-contact@example.com", "Коммерческий отдел"),
            )
            c.execute(
                """
                INSERT INTO projects (
                    name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                    budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                    subtasks, time_logs, allowed_roles, nomenclature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "QA Dossier Project",
                    "QA-DOSSIER-001",
                    client_name,
                    self.user["name"],
                    "active",
                    55,
                    "{}",
                    "{}",
                    "{}",
                    250000,
                    110000,
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "{}",
                    "{}",
                    "{}",
                    "{}",
                    "[]",
                    "[]",
                    "[]",
                ),
            )
            project_id = int(c.lastrowid)
            conn.commit()
            conn.close()

            quote_create = self.client.post("/api/sales/quotes", json={
                "project_id": project_id,
                "client_id": client_id,
                "title": "QA Commercial Offer",
                "quote_number": f"QUO-{os.getpid()}",
                "stage": "proposal",
                "amount": 88000,
                "currency": "RUB",
                "valid_until": "20.04.2026",
                "responsible": self.user["name"],
                "probability": 65,
                "comment": "Для проверки dossier",
            })
            self.assertEqual(quote_create.status_code, 200)
            quote_id = int(quote_create.json()["id"])

            price_list_create = self.client.post("/api/sales/price_lists", json={
                "name": "QA Dossier Price",
                "currency": "RUB",
                "valid_from": "13.04.2026",
                "valid_to": "30.04.2026",
                "item_article": "QA-DOSSIER-ART",
                "item_name": "QA Position",
                "unit": "шт",
                "base_price": 15000,
                "min_price": 12000,
                "status": "active",
                "comment": "Прайс для dossier",
            })
            self.assertEqual(price_list_create.status_code, 200)
            price_list_id = int(price_list_create.json()["id"])

            terms_create = self.client.post("/api/sales/client_terms", json={
                "client_id": client_id,
                "price_list_id": price_list_id,
                "discount_percent": 7.5,
                "discount_amount": 0,
                "payment_delay_days": 14,
                "credit_limit": 300000,
                "shipment_priority": "high",
                "status": "active",
                "comment": "Условия клиента",
            })
            self.assertEqual(terms_create.status_code, 200)
            terms_id = int(terms_create.json()["id"])

            conn = get_connection()
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO bank_accounts (name, bank_name, account_number, bik, currency, legal_entity_id, is_active, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'), strftime('%s','now'))
                """,
                ("QA Dossier Bank", "Test Bank", f"40702810{os.getpid()}", "044525225", "RUB", 0, 1, self.user["email"]),
            )
            bank_account_id = int(c.lastrowid)
            conn.commit()
            conn.close()

            bank_import = self.client.post("/api/banking/statements/import", json={
                "bank_account_id": bank_account_id,
                "lines": [{
                    "line_date": "13.04.2026",
                    "amount": 88000,
                    "direction": "incoming",
                    "counterparty": client_name,
                    "purpose": "Оплата по КП",
                    "client_id": client_id,
                    "payment_id": 0,
                    "external_line_id": f"DOSSIER-BANK-{os.getpid()}",
                    "comment": "Банковская строка dossier",
                }],
            })
            self.assertEqual(bank_import.status_code, 200)
            bank_line_id = int(bank_import.json()["ids"][0])

            telephony_account = self.client.post("/api/telephony/accounts", json={
                "provider_name": "Mango",
                "line_name": "QA Dossier Line",
                "external_line_id": f"DOSSIER-LINE-{os.getpid()}",
                "is_active": 1,
            })
            self.assertEqual(telephony_account.status_code, 200)
            telephony_account_id = int(telephony_account.json()["id"])

            telephony_call = self.client.post("/api/telephony/calls", json={
                "account_id": telephony_account_id,
                "client_id": client_id,
                "project_id": project_id,
                "contact_name": "QA Dossier Contact",
                "phone_number": "+79992223344",
                "direction": "outbound",
                "status": "answered",
                "duration_sec": 95,
                "call_at": "13.04.2026 14:30",
                "summary": "Уточнение коммерческих условий",
                "recording_url": "",
            })
            self.assertEqual(telephony_call.status_code, 200)
            telephony_call_id = int(telephony_call.json()["id"])

            dossier = self.client.get(f"/api/clients/{client_id}/dossier")
            self.assertEqual(dossier.status_code, 200)
            payload = dossier.json()
            self.assertTrue(any(item["title"] == "QA Commercial Offer" for item in payload["sales_quotes"]))
            self.assertTrue(any(int(item["client_id"]) == client_id for item in payload["client_terms"]))
            self.assertTrue(any(item["counterparty"] == client_name for item in payload["bank_lines"]))
            self.assertTrue(any(int(item["id"]) == telephony_call_id for item in payload["telephony_calls"]))
            self.assertGreaterEqual(payload["metrics"]["quotes_total"], 88000)
            self.assertGreaterEqual(payload["metrics"]["bank_turnover"], 88000)
            self.assertGreaterEqual(payload["metrics"]["calls_total"], 1)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if telephony_call_id:
                c.execute("DELETE FROM notifications WHERE entity_type='telephony_call' AND entity_id=?", (str(telephony_call_id),))
                c.execute("DELETE FROM audit_log WHERE entity_type='telephony_call' AND entity_id=?", (str(telephony_call_id),))
                c.execute("DELETE FROM telephony_calls WHERE id=?", (telephony_call_id,))
            if telephony_account_id:
                c.execute("DELETE FROM audit_log WHERE entity_type='telephony_account' AND entity_id=?", (str(telephony_account_id),))
                c.execute("DELETE FROM telephony_accounts WHERE id=?", (telephony_account_id,))
            if bank_line_id:
                c.execute("DELETE FROM audit_log WHERE entity_type='bank_statement_line' AND entity_id=?", (str(bank_line_id),))
                c.execute("DELETE FROM bank_statement_lines WHERE id=?", (bank_line_id,))
            if bank_account_id:
                c.execute("DELETE FROM audit_log WHERE entity_type='bank_account' AND entity_id=?", (str(bank_account_id),))
                c.execute("DELETE FROM bank_accounts WHERE id=?", (bank_account_id,))
            if terms_id:
                c.execute("DELETE FROM client_sales_terms WHERE id=?", (terms_id,))
            if price_list_id:
                c.execute("DELETE FROM price_lists WHERE id=?", (price_list_id,))
            if quote_id:
                c.execute("DELETE FROM sales_quotes WHERE id=?", (quote_id,))
            if project_id:
                c.execute("DELETE FROM projects WHERE id=?", (project_id,))
            if client_id:
                c.execute("DELETE FROM contacts WHERE client_id=?", (client_id,))
                c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            conn.commit()
            conn.close()

    def test_project_1c_invoice_endpoint_adds_file(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        project_id = allocate_test_project_id()
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO projects (
                id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                subtasks, time_logs, allowed_roles, nomenclature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                "QA 1C Project",
                "2026-КРД-1C",
                "QA Invoice Client",
                self.user["name"],
                "active",
                10,
                "{}",
                "{}",
                "{}",
                123456,
                10000,
                "[]",
                "[]",
                "[]",
                "[]",
                "[]",
                "{}",
                "{}",
                "{}",
                "{}",
                "[]",
                "[]",
                "[]",
            ),
        )
        conn.commit()
        conn.close()

        created_file_path = ""
        try:
            response = self.client.post(f"/api/projects/{project_id}/1c_invoice")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "success")

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT files, logs FROM projects WHERE id=?", (project_id,))
            row = c.fetchone()
            conn.close()

            self.assertIsNotNone(row)
            files = json.loads(row[0] or "[]")
            logs = json.loads(row[1] or "[]")
            self.assertTrue(any(item.get("doc_type") == "Счет на оплату" for item in files))
            self.assertTrue(any("1С" in (item.get("action") or "") for item in logs))

            invoice_file = next(item for item in files if item.get("doc_type") == "Счет на оплату")
            invoice_url = invoice_file.get("url") or ""
            created_file_path = os.path.join(os.path.dirname(DB_NAME), invoice_url.replace("/uploads/", "uploads/", 1).lstrip("/"))
            self.assertTrue(created_file_path)
            self.assertTrue(os.path.exists(created_file_path))
        finally:
            if created_file_path and os.path.exists(created_file_path):
                try:
                    os.remove(created_file_path)
                except OSError:
                    pass
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM projects WHERE id=?", (project_id,))
            conn.commit()
            conn.close()

    def test_document_resolution_creates_notification_and_task_for_assignee(self):
        assignee = create_test_user(role="Менеджер", name_prefix="Resolution Assignee")
        try:
            login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
            self.assertEqual(login.status_code, 200)

            create_doc = self.client.post(
                "/api/documents",
                json={
                    "type": "incoming",
                    "number": "RES-001",
                    "d_date": "12.04.2026",
                    "correspondent": "ООО Тест",
                    "subject": "Проверка резолюции",
                    "status": "registered",
                    "project_id": 0,
                    "parent_id": 0,
                    "priority": "normal",
                },
            )
            self.assertEqual(create_doc.status_code, 200)
            self.assertEqual(create_doc.json()["status"], "success")

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM documents WHERE number=?", ("RES-001",))
            doc_id = c.fetchone()[0]
            conn.close()

            update_doc = self.client.put(
                f"/api/documents/{doc_id}",
                json={
                    "type": "incoming",
                    "number": "RES-001",
                    "d_date": "12.04.2026",
                    "correspondent": "ООО Тест",
                    "subject": "Проверка резолюции",
                    "status": "registered",
                    "project_id": 0,
                    "parent_id": 0,
                    "priority": "normal",
                    "resolution": "Подготовить ответ и согласовать позицию.",
                    "resolution_author": self.user["name"],
                    "resolution_deadline": "15.04.2026",
                    "resolution_assignee": assignee["name"],
                },
            )
            self.assertEqual(update_doc.status_code, 200)
            self.assertEqual(update_doc.json()["status"], "success")
            resolution_task_id = int(update_doc.json()["resolution_task_id"])
            self.assertGreater(resolution_task_id, 0)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT resolution_task_id FROM documents WHERE id=?", (doc_id,))
            doc_row = c.fetchone()
            self.assertIsNotNone(doc_row)
            self.assertEqual(int(doc_row[0]), resolution_task_id)
            c.execute("SELECT title, executor, deadline, status FROM tasks WHERE id=?", (resolution_task_id,))
            task_row = c.fetchone()
            self.assertIsNotNone(task_row)
            self.assertIn("Резолюция по документу", task_row[0])
            self.assertIn(assignee["name"], task_row[1])
            self.assertEqual(task_row[2], "15.04.2026")
            self.assertEqual(task_row[3], "active")
            c.execute(
                "SELECT title, user_name, entity_id FROM notifications WHERE user_name=? AND entity_type='document' ORDER BY id DESC LIMIT 1",
                (assignee["name"],),
            )
            row = c.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "Новая резолюция по документу")
            self.assertEqual(row[1], assignee["name"])
            self.assertEqual(str(row[2]), str(doc_id))
            c.execute(
                "SELECT title, entity_id FROM notifications WHERE user_name=? AND entity_type='task' ORDER BY id DESC LIMIT 1",
                (assignee["name"],),
            )
            task_notification = c.fetchone()
            self.assertIsNotNone(task_notification)
            self.assertIn("поручение", task_notification[0].lower())
            self.assertEqual(str(task_notification[1]), str(resolution_task_id))
            c.execute("DELETE FROM notifications WHERE entity_type='document' AND entity_id=?", (str(doc_id),))
            c.execute("DELETE FROM notifications WHERE entity_type='task' AND entity_id=?", (str(resolution_task_id),))
            c.execute("DELETE FROM tasks WHERE id=?", (resolution_task_id,))
            c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            conn.commit()
            conn.close()
        finally:
            delete_test_user(assignee["email"])

    def test_epl_stage_sequence_and_summary_work(self):
        director = create_test_user(role="Директор", name_prefix="EPL Director")
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            driver_res = self.client.post(
                "/api/epl/drivers",
                json={
                    "full_name": "QA Водитель",
                    "personnel_number": "QA-DRV-100",
                    "license_number": "77 77 123456",
                    "license_category": "B, C",
                    "phone": "+79990000001",
                    "medical_valid_to": "30.04.2026",
                    "signature_profile": "УНЭП",
                    "status": "active",
                    "comment": "QA",
                },
            )
            self.assertEqual(driver_res.status_code, 200)
            driver_id = int(driver_res.json()["id"])

            vehicle_res = self.client.post(
                "/api/epl/vehicles",
                json={
                    "registration_no": "QA001AA123",
                    "garage_number": "QA-G-1",
                    "brand": "GAZ",
                    "model": "Next",
                    "odometer": 12000,
                    "carrying_capacity": 3.5,
                    "diagnostic_valid_to": "25.04.2026",
                    "insurance_valid_to": "30.05.2026",
                    "status": "active",
                    "comment": "QA",
                },
            )
            self.assertEqual(vehicle_res.status_code, 200)
            vehicle_id = int(vehicle_res.json()["id"])

            waybill_res = self.client.post(
                "/api/epl/waybills",
                json={
                    "issue_date": "12.04.2026",
                    "shift_date": "12.04.2026",
                    "waybill_type": "truck",
                    "driver_id": driver_id,
                    "vehicle_id": vehicle_id,
                    "route_text": "Краснодар -> Склад QA",
                    "departure_point": "Краснодар",
                    "destination_point": "Склад QA",
                    "dispatcher_name": director["name"],
                    "medical_name": "Мед QA",
                    "mechanic_name": "Механик QA",
                    "planned_departure": "12.04.2026 08:00",
                    "odometer_out": 12000,
                    "integration_status": "draft",
                },
            )
            self.assertEqual(waybill_res.status_code, 200)
            waybill_id = int(waybill_res.json()["id"])

            invalid_return = self.client.post(
                f"/api/epl/waybills/{waybill_id}/actions",
                json={
                    "stage": "dispatcher_return",
                    "signer_name": director["name"],
                    "signed_at": "12.04.2026 19:00",
                    "status_value": "returned",
                    "comment": "Нельзя раньше выезда",
                },
            )
            self.assertEqual(invalid_return.status_code, 400)
            self.assertEqual(invalid_return.json().get("error"), "validation_error")
            self.assertIn("выезд", str(invalid_return.json().get("message", "")).lower())

            for stage, signer, status_value, signed_at in [
                ("medical_pretrip", "Мед QA", "passed", "12.04.2026 07:30"),
                ("mechanic_pretrip", "Механик QA", "passed", "12.04.2026 07:40"),
                ("dispatcher_departure", director["name"], "departed", "12.04.2026 08:05"),
                ("dispatcher_return", director["name"], "returned", "12.04.2026 18:55"),
                ("medical_posttrip", "Мед QA", "passed", "12.04.2026 19:05"),
                ("mechanic_posttrip", "Механик QA", "passed", "12.04.2026 19:12"),
            ]:
                res = self.client.post(
                    f"/api/epl/waybills/{waybill_id}/actions",
                    json={
                        "stage": stage,
                        "signer_name": signer,
                        "signed_at": signed_at,
                        "status_value": status_value,
                        "comment": f"QA {stage}",
                    },
                )
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["status"], "success")

            ready_res = self.client.post(
                f"/api/epl/waybills/{waybill_id}/actions",
                json={
                    "stage": "integration",
                    "integration_status": "ready",
                    "signer_name": director["name"],
                    "signed_at": "12.04.2026 19:20",
                    "comment": "Готово к выгрузке",
                },
            )
            self.assertEqual(ready_res.status_code, 200)
            self.assertEqual(ready_res.json()["status"], "success")

            summary_res = self.client.get("/api/epl/summary")
            self.assertEqual(summary_res.status_code, 200)
            payload = summary_res.json()
            self.assertIn("recent", payload)
            self.assertIn("alerts", payload)
            self.assertTrue(any(int(item["id"]) == waybill_id for item in payload["recent"]))

            detail_res = self.client.get(f"/api/epl/waybills/{waybill_id}")
            self.assertEqual(detail_res.status_code, 200)
            detail = detail_res.json()
            self.assertEqual(detail["waybill"]["integration_status"], "ready")
            self.assertEqual(detail["waybill"]["status"], "closed")
            self.assertEqual(detail["waybill"]["readiness_percent"], 100)
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM epl_signatures WHERE signer_name IN (?, ?, ?)", (director["name"], "Мед QA", "Механик QA"))
            c.execute("DELETE FROM epl_waybills WHERE route_text=?", ("Краснодар -> Склад QA",))
            c.execute("DELETE FROM epl_drivers WHERE personnel_number=?", ("QA-DRV-100",))
            c.execute("DELETE FROM epl_vehicles WHERE registration_no=?", ("QA001AA123",))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_ops_modules_link_to_project(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        client_name = "QA Ops Client"
        self.client.post("/api/clients", json={"name": client_name, "inn": "7707654321", "contact": "ops@example.com"})
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM purchase_orders WHERE project_id=?", (991002,))
        c.execute("DELETE FROM sales_documents_extended WHERE project_id=?", (991002,))
        c.execute("DELETE FROM production_orders WHERE project_id=?", (991002,))
        c.execute("DELETE FROM stock_reservations WHERE project_id=?", (991002,))
        c.execute("DELETE FROM projects WHERE id=?", (991002,))
        c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
        client_id = c.fetchone()[0]
        c.execute(
            """
            INSERT INTO projects (
                id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                subtasks, time_logs, allowed_roles, nomenclature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                991002,
                "QA Ops Project",
                "2026-КРД-OPS",
                client_name,
                self.user["name"],
                "active",
                15,
                "{}",
                "{}",
                "{}",
                50000,
                30000,
                "[]",
                "[]",
                "[]",
                "[]",
                "[]",
                "{}",
                "{}",
                "{}",
                "{}",
                "[]",
                "[]",
                "[]",
            ),
        )
        conn.commit()
        conn.close()

        purchase = self.client.post("/api/purchases", json={
            "project_id": 991002, "client_id": client_id, "item_article": "OPS-001", "item_name": "Термочехол",
            "supplier": "Тестовый поставщик", "qty": 3, "unit": "шт", "unit_price": 4000, "status": "ordered",
            "expected_date": "22.04.2026", "received_date": "", "comment": "Тест закупки"
        })
        self.assertEqual(purchase.status_code, 200)

        sales = self.client.post("/api/sales/documents", json={
            "project_id": 991002, "client_id": client_id, "doc_type": "invoice", "doc_number": "INV-OPS-01",
            "doc_date": "11.04.2026", "amount": 50000, "currency": "RUB", "status": "issued",
            "payment_status": "planned", "linked_payment_id": 0, "comment": "Тест счета"
        })
        self.assertEqual(sales.status_code, 200)

        production = self.client.post("/api/production/orders", json={
            "project_id": 991002, "client_id": client_id, "order_name": "Производство термочехлов",
            "stage": "in_work", "priority": "high", "planned_start": "12.04.2026", "planned_finish": "20.04.2026",
            "actual_finish": "", "progress": 45, "responsible": "Мастер смены", "comment": "Тест производства"
        })
        self.assertEqual(production.status_code, 200)

        reservation = self.client.post("/api/stock/reservations", json={
            "project_id": 991002, "nomenclature_article": "OPS-001", "nomenclature_name": "Термочехол",
            "qty": 2, "status": "reserved", "comment": "Тест резерва"
        })
        self.assertEqual(reservation.status_code, 200)

        project_ops = self.client.get("/api/projects/991002/ops")
        self.assertEqual(project_ops.status_code, 200)
        payload = project_ops.json()
        self.assertTrue(payload["purchases"])
        self.assertTrue(payload["sales"])
        self.assertTrue(payload["production"])
        self.assertTrue(payload["reservations"])

        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM purchase_orders WHERE project_id=?", (991002,))
        c.execute("DELETE FROM sales_documents_extended WHERE project_id=?", (991002,))
        c.execute("DELETE FROM production_orders WHERE project_id=?", (991002,))
        c.execute("DELETE FROM stock_reservations WHERE project_id=?", (991002,))
        c.execute("DELETE FROM projects WHERE id=?", (991002,))
        c.execute("DELETE FROM clients WHERE id=?", (client_id,))
        conn.commit()
        conn.close()

    def test_enterprise_modules_and_executive_summary(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        client_name = "QA Enterprise Client"
        self.client.post("/api/clients", json={"name": client_name, "inn": "7701112233", "contact": "enterprise@example.com"})

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM clients WHERE name=? ORDER BY id DESC LIMIT 1", (client_name,))
        client_id = c.fetchone()[0]
        try:
            c.execute("DELETE FROM expense_requests WHERE project_id=?", (991003,))
            c.execute("DELETE FROM internal_requests WHERE project_id=?", (991003,))
            c.execute("DELETE FROM resource_allocations WHERE project_id=?", (991003,))
            c.execute("DELETE FROM service_cases WHERE project_id=?", (991003,))
            c.execute("DELETE FROM project_budget_lines WHERE project_id=?", (991003,))
            c.execute("DELETE FROM projects WHERE id=?", (991003,))
            conn.commit()
            c.execute(
                """
                INSERT INTO projects (
                    id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                    budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                    subtasks, time_logs, allowed_roles, nomenclature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    991003,
                    "QA Enterprise Project",
                    "2026-КРД-ENT",
                    client_name,
                    self.user["name"],
                    "active",
                    45,
                    "{}",
                    "{}",
                    "{}",
                    200000,
                    120000,
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "{}",
                    "{}",
                    "{}",
                    "{}",
                    "[]",
                    "[]",
                    "[]",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        expense = self.client.post("/api/expenses/requests", json={
            "project_id": 991003, "client_id": client_id, "title": "Оплата поставщику ткани",
            "request_type": "payment", "amount": 65000, "currency": "RUB", "approver_role": "Директор",
            "approver_name": "Илья Осипов", "due_date": "25.04.2026", "linked_payment_id": 0, "status": "pending",
            "comment": "Тест согласования"
        })
        self.assertEqual(expense.status_code, 200)

        internal_request = self.client.post("/api/internal_requests", json={
            "project_id": 991003, "title": "Подготовить допсоглашение", "request_type": "legal",
            "target_role": "Юрист", "assignee_name": "QA Lawyer", "priority": "high",
            "status": "new", "deadline": "18.04.2026", "comment": "Тест внутренней заявки"
        })
        self.assertEqual(internal_request.status_code, 200)

        resource = self.client.post("/api/resources/allocations", json={
            "project_id": 991003, "department": "Конструкторское бюро", "resource_name": "QA Engineer",
            "role_name": "Инженер", "load_percent": 90, "date_from": "12.04.2026", "date_to": "25.04.2026",
            "status": "overloaded", "comment": "Тест загрузки"
        })
        self.assertEqual(resource.status_code, 200)

        service = self.client.post("/api/service/cases", json={
            "project_id": 991003, "client_id": client_id, "case_number": "SRV-001",
            "title": "Гарантийная замена", "case_type": "warranty", "status": "open",
            "priority": "high", "defect": "Нарушена изоляция", "warranty_until": "01.12.2026",
            "sla_deadline": "16.04.2026", "responsible": "QA Service", "resolution": ""
        })
        self.assertEqual(service.status_code, 200)

        budget = self.client.post("/api/budget/lines", json={
            "project_id": 991003, "line_type": "materials", "category": "Материалы",
            "plan_amount": 80000, "fact_amount": 72000, "comment": "Тест бюджета"
        })
        self.assertEqual(budget.status_code, 200)

        ops = self.client.get("/api/projects/991003/ops")
        self.assertEqual(ops.status_code, 200)
        payload = ops.json()
        self.assertTrue(payload["expenses"])
        self.assertTrue(payload["requests"])
        self.assertTrue(payload["resources"])
        self.assertTrue(payload["service"])
        self.assertGreaterEqual(payload["budget"]["contract_total"], 200000)

        dossier = self.client.get(f"/api/clients/{client_id}/dossier")
        self.assertEqual(dossier.status_code, 200)
        self.assertTrue(dossier.json()["service_cases"])

        director = create_test_user(role="Директор", name_prefix="Exec Director")
        try:
            director_client = TestClient(app)
            login_director = director_client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login_director.status_code, 200)
            executive = director_client.get("/api/executive/summary")
            self.assertEqual(executive.status_code, 200)
            executive_payload = executive.json()
            self.assertIn("metrics", executive_payload)
            self.assertTrue(isinstance(executive_payload["risk_projects"], list))
        finally:
            delete_test_user(director["email"])

        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM expense_requests WHERE project_id=?", (991003,))
        c.execute("DELETE FROM internal_requests WHERE project_id=?", (991003,))
        c.execute("DELETE FROM resource_allocations WHERE project_id=?", (991003,))
        c.execute("DELETE FROM service_cases WHERE project_id=?", (991003,))
        c.execute("DELETE FROM project_budget_lines WHERE project_id=?", (991003,))
        c.execute("DELETE FROM projects WHERE id=?", (991003,))
        c.execute("DELETE FROM clients WHERE id=?", (client_id,))
        conn.commit()
        conn.close()

    def test_spec_versions_stock_balances_and_sales_delivery_flow(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        client_name = "QA Warehouse Client"
        self.client.post("/api/clients", json={"name": client_name, "inn": "7709988776", "contact": "warehouse@example.com"})

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
        client_id = c.fetchone()[0]
        try:
            c.execute("DELETE FROM stock_movements WHERE article=?", ("QA-STOCK-001",))
            c.execute("DELETE FROM inventory_balances WHERE article=?", ("QA-STOCK-001",))
            c.execute("DELETE FROM specification_versions WHERE project_id=?", (991004,))
            c.execute("DELETE FROM sales_documents_extended WHERE project_id=?", (991004,))
            c.execute("DELETE FROM resource_allocations WHERE project_id=?", (991004,))
            c.execute("DELETE FROM nomenclature WHERE article=?", ("QA-STOCK-001",))
            c.execute("DELETE FROM projects WHERE id=?", (991004,))
            conn.commit()

            c.execute(
                """
                INSERT INTO projects (
                    id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                    budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                    subtasks, time_logs, allowed_roles, nomenclature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    991004,
                    "QA Stock Project",
                    "2026-КРД-STOCK",
                    client_name,
                    self.user["name"],
                    "active",
                    10,
                    "{}",
                    "{}",
                    "{}",
                    100000,
                    25000,
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "{}",
                    "{}",
                    "{}",
                    "{}",
                    "[]",
                    "[]",
                    '[{"name":"Термочехол QA","article":"QA-STOCK-001","qty":2,"price":1500,"unit":"шт"}]',
                ),
            )
            c.execute(
                "INSERT INTO nomenclature (name, article, unit, price, stock, currency) VALUES (?, ?, ?, ?, ?, ?)",
                ("Термочехол QA", "QA-STOCK-001", "шт", 1500, 0, "RUB"),
            )
            conn.commit()
        finally:
            conn.close()

        try:
            version = self.client.post(
                "/api/projects/991004/spec_versions",
                json={
                    "label": "Стартовая версия",
                    "comment": "Тест спецификации",
                    "items": [{"name": "Термочехол QA", "article": "QA-STOCK-001", "qty": 2, "price": 1500, "unit": "шт"}],
                },
            )
            self.assertEqual(version.status_code, 200)
            self.assertEqual(version.json()["status"], "success")

            versions = self.client.get("/api/projects/991004/spec_versions")
            self.assertEqual(versions.status_code, 200)
            self.assertTrue(any(item["label"] == "Стартовая версия" for item in versions.json()))

            move_in = self.client.post(
                "/api/nomenclature/QA-STOCK-001/movement_detailed",
                json={
                    "qty": 5,
                    "type": "add",
                    "from_warehouse": "Поставка",
                    "from_bin": "IN-01",
                    "to_warehouse": "Основной склад",
                    "to_bin": "A-01",
                    "comment": "Тест прихода",
                },
            )
            self.assertEqual(move_in.status_code, 200)
            self.assertEqual(move_in.json()["status"], "success")

            move_transfer = self.client.post(
                "/api/nomenclature/QA-STOCK-001/movement_detailed",
                json={
                    "qty": 2,
                    "type": "transfer",
                    "from_warehouse": "Основной склад",
                    "from_bin": "A-01",
                    "to_warehouse": "Монтаж",
                    "to_bin": "M-03",
                    "comment": "Тест перемещения",
                },
            )
            self.assertEqual(move_transfer.status_code, 200)
            self.assertEqual(move_transfer.json()["status"], "success")

            balances = self.client.get("/api/stock/balances?article=QA-STOCK-001")
            self.assertEqual(balances.status_code, 200)
            balances_payload = balances.json()
            self.assertTrue(any(item["warehouse"] == "Основной склад" for item in balances_payload))
            self.assertTrue(any(item["warehouse"] == "Монтаж" for item in balances_payload))

            sales = self.client.post("/api/sales/documents", json={
                "project_id": 991004,
                "client_id": client_id,
                "doc_type": "invoice",
                "doc_number": "INV-QA-DELIVERY",
                "doc_date": "11.04.2026",
                "amount": 100000,
                "currency": "RUB",
                "status": "issued",
                "payment_status": "planned",
                "linked_payment_id": 0,
                "recipient_email": "client@example.com",
                "sent_status": "delivered",
                "sent_at": "11.04.2026 10:00",
                "delivered_at": "11.04.2026 10:05",
                "confirmed_at": "",
                "comment": "Тест отправки клиенту",
            })
            self.assertEqual(sales.status_code, 200)

            resource = self.client.post("/api/resources/allocations", json={
                "project_id": 991004,
                "department": "Производство и ОТК",
                "resource_name": "Монтажник QA",
                "role_name": "Старший монтажник",
                "crew_name": "Бригада Север",
                "crew_type": "installation",
                "load_percent": 70,
                "date_from": "12.04.2026",
                "date_to": "18.04.2026",
                "location": "Газпром Объект-1",
                "status": "confirmed",
                "comment": "Выезд на объект",
            })
            self.assertEqual(resource.status_code, 200)

            sales_rows = self.client.get("/api/sales/documents?project_id=991004")
            self.assertEqual(sales_rows.status_code, 200)
            self.assertTrue(any(item["sent_status"] == "delivered" and item["recipient_email"] == "client@example.com" for item in sales_rows.json()))

            resource_rows = self.client.get("/api/resources/allocations?project_id=991004")
            self.assertEqual(resource_rows.status_code, 200)
            self.assertTrue(any(item["crew_name"] == "Бригада Север" and item["location"] == "Газпром Объект-1" for item in resource_rows.json()))
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM stock_movements WHERE article=?", ("QA-STOCK-001",))
            c.execute("DELETE FROM inventory_balances WHERE article=?", ("QA-STOCK-001",))
            c.execute("DELETE FROM specification_versions WHERE project_id=?", (991004,))
            c.execute("DELETE FROM sales_documents_extended WHERE project_id=?", (991004,))
            c.execute("DELETE FROM resource_allocations WHERE project_id=?", (991004,))
            c.execute("DELETE FROM nomenclature WHERE article=?", ("QA-STOCK-001",))
            c.execute("DELETE FROM projects WHERE id=?", (991004,))
            c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            conn.commit()
            conn.close()

    def test_stock_lot_reservation_and_fulfillment_flow(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        article = "QA-LOT-001"
        create_nom = self.client.post("/api/nomenclature", json={
            "name": "Кабель в партии",
            "article": article,
            "unit": "м",
            "price": 150,
            "stock": 0,
            "currency": "RUB",
        })
        self.assertEqual(create_nom.status_code, 200)
        self.assertEqual(create_nom.json()["status"], "success")

        try:
            move_in = self.client.post(
                f"/api/nomenclature/{article}/movement_detailed",
                json={
                    "qty": 5,
                    "type": "add",
                    "from_warehouse": "Поставка",
                    "from_bin": "IN-02",
                    "to_warehouse": "Основной склад",
                    "to_bin": "B-04",
                    "batch_code": "LOT-QA-APR",
                    "serial_no": "",
                    "comment": "Приход партии для резерва",
                },
            )
            self.assertEqual(move_in.status_code, 200)
            self.assertEqual(move_in.json()["status"], "success")

            reserve = self.client.post(
                "/api/stock/reservations",
                json={
                    "project_id": 0,
                    "nomenclature_article": article,
                    "nomenclature_name": "Кабель в партии",
                    "qty": 2,
                    "status": "reserved",
                    "comment": "Резерв под проект",
                    "warehouse": "Основной склад",
                    "bin_code": "B-04",
                    "batch_code": "LOT-QA-APR",
                    "serial_no": "",
                },
            )
            self.assertEqual(reserve.status_code, 200)
            self.assertEqual(reserve.json()["status"], "success")
            self.assertEqual(reserve.json()["reservation_status"], "reserved")
            reservation_id = reserve.json()["id"]

            fulfill = self.client.post(
                f"/api/stock/reservations/{reservation_id}/fulfill",
                json={
                    "qty": 2,
                    "warehouse": "Основной склад",
                    "bin_code": "B-04",
                    "batch_code": "LOT-QA-APR",
                    "serial_no": "",
                    "comment": "Выдача в проект",
                },
            )
            self.assertEqual(fulfill.status_code, 200)
            self.assertEqual(fulfill.json()["status"], "success")
            self.assertEqual(fulfill.json()["reservation_status"], "fulfilled")

            lots = self.client.get(f"/api/stock/lots?article={article}")
            self.assertEqual(lots.status_code, 200)
            self.assertTrue(any(item["batch_code"] == "LOT-QA-APR" and float(item["qty"]) == 3 for item in lots.json()))

            balances = self.client.get(f"/api/stock/balances?article={article}")
            self.assertEqual(balances.status_code, 200)
            self.assertTrue(any(item["warehouse"] == "Основной склад" and item["bin_code"] == "B-04" and float(item["qty"]) == 3 for item in balances.json()))

            movements = self.client.get(f"/api/stock/movements?article={article}")
            self.assertEqual(movements.status_code, 200)
            self.assertTrue(any(item["batch_code"] == "LOT-QA-APR" and item["movement_type"] == "add" for item in movements.json()))
            self.assertTrue(any(item["batch_code"] == "LOT-QA-APR" and item["movement_type"] == "remove" and int(item["reservation_id"] or 0) == reservation_id for item in movements.json()))

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT stock FROM nomenclature WHERE article=?", (article,))
            self.assertEqual(float(c.fetchone()[0]), 3.0)
            c.execute("SELECT status, fulfilled_qty, warehouse, bin_code, batch_code FROM stock_reservations WHERE id=?", (reservation_id,))
            reservation_row = c.fetchone()
            self.assertIsNotNone(reservation_row)
            self.assertEqual(reservation_row[0], "fulfilled")
            self.assertEqual(float(reservation_row[1]), 2.0)
            self.assertEqual(reservation_row[2], "Основной склад")
            self.assertEqual(reservation_row[3], "B-04")
            self.assertEqual(reservation_row[4], "LOT-QA-APR")
            conn.close()
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM stock_reservations WHERE nomenclature_article=?", (article,))
            c.execute("DELETE FROM stock_movements WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_balances WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_lots WHERE article=?", (article,))
            c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
            conn.commit()
            conn.close()

    def test_erp_process_flow_links_entities_and_exports_snapshot(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        client_name = "QA ERP Client"
        duplicate_name = "QA ERP Client"
        self.client.post("/api/clients", json={"name": client_name, "inn": "7712345600", "contact": "erp@example.com"})
        self.client.post("/api/clients", json={"name": duplicate_name, "inn": "7712345600", "contact": "erp-dup@example.com"})

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM clients WHERE name=? ORDER BY id ASC", (client_name,))
        client_ids = [row[0] for row in c.fetchall()]
        client_id = client_ids[0]
        c.execute("DELETE FROM erp_entity_links WHERE process_id IN (SELECT id FROM erp_process_runs WHERE project_id=991006)")
        c.execute("DELETE FROM erp_process_runs WHERE project_id=?", (991006,))
        c.execute("DELETE FROM finance_payments WHERE project_id IN (?, ?)", (991006, 777888))
        c.execute("DELETE FROM purchase_orders WHERE project_id=?", (991006,))
        c.execute("DELETE FROM approvals WHERE item_link=?", ("/erp/process/qa-991006",))
        c.execute("DELETE FROM internal_requests WHERE project_id=?", (991006,))
        c.execute("DELETE FROM projects WHERE id=?", (991006,))
        c.execute(
            """
            INSERT INTO projects (
                id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                subtasks, time_logs, allowed_roles, nomenclature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                991006,
                "QA ERP Project",
                "2026-КРД-ERP",
                client_name,
                self.user["name"],
                "active",
                20,
                "{}",
                "{}",
                "{}",
                42000,
                12000,
                "[]",
                "[]",
                "[]",
                "[]",
                "[]",
                "{}",
                "{}",
                "{}",
                "{}",
                "[]",
                "[]",
                "[]",
            ),
        )
        c.execute(
            """
            INSERT INTO finance_payments (
                project_id, client_id, title, kind, category, amount, currency, due_date,
                paid_date, status, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (777888, 0, "Orphan QA Payment", "incoming", "erp", 1000, "RUB", "20.04.2026", "", "planned", "orphan", self.user["email"], 0, 0),
        )
        conn.commit()
        conn.close()

        try:
            started = self.client.post(
                "/api/erp/processes/start",
                json={
                    "project_id": 991006,
                    "client_id": client_id,
                    "title": "ERP маршрут поставки",
                    "request_type": "purchase",
                    "scenario": ["request", "approval", "purchase", "payment"],
                    "due_date": "25.04.2026",
                    "amount": 42000,
                    "assignee_name": self.user["name"],
                    "approver_name": self.user["name"],
                    "item_article": "ERP-001",
                    "item_name": "Тестовый комплект",
                    "qty": 3,
                    "supplier": "QA Supplier",
                    "comment": "Тест сквозного ERP-процесса",
                },
            )
            self.assertEqual(started.status_code, 200)
            self.assertEqual(started.json()["status"], "success")
            process_id = started.json()["id"]
            self.assertIn("autoroute", started.json())
            self.assertTrue(started.json()["autoroute"])

            director = create_test_user(role="Директор", name_prefix="ERP Director")
            try:
                director_client = TestClient(app)
                director_login = director_client.post("/api/login", json={"email": director["email"], "password": director["password"]})
                self.assertEqual(director_login.status_code, 200)
                done = director_client.post(f"/api/erp/processes/{process_id}/advance", json={"target_stage": "done"})
                self.assertEqual(done.status_code, 200)
                self.assertEqual(done.json()["status"], "success")
            finally:
                delete_test_user(director["email"])

            summary = self.client.get("/api/erp/summary")
            self.assertEqual(summary.status_code, 200)
            self.assertGreaterEqual(summary.json()["metrics"]["processes_total"], 1)

            quality = self.client.get("/api/erp/data_quality")
            self.assertEqual(quality.status_code, 200)
            quality_payload = quality.json()
            self.assertGreaterEqual(quality_payload["orphans"]["finance_missing_project"], 1)
            self.assertTrue(quality_payload["clients_duplicates"] or quality_payload["clients_duplicate_inn"])

            rows = self.client.get("/api/erp/processes?project_id=991006")
            self.assertEqual(rows.status_code, 200)
            self.assertTrue(any(item["id"] == process_id for item in rows.json()))

            detail = self.client.get(f"/api/erp/processes/{process_id}")
            self.assertEqual(detail.status_code, 200)
            detail_payload = detail.json()
            self.assertTrue(detail_payload["links"])
            self.assertTrue(detail_payload["audit"])

            export = self.client.get("/api/erp/export")
            self.assertEqual(export.status_code, 200)
            export_payload = export.json()
            self.assertIn("summary", export_payload)
            self.assertTrue(any(item["id"] == process_id for item in export_payload["processes"]))

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT request_id, approval_id, purchase_id, payment_id FROM erp_process_runs WHERE id=?", (process_id,))
            run_row = c.fetchone()
            self.assertIsNotNone(run_row)
            self.assertGreater(int(run_row[0]), 0)
            self.assertGreater(int(run_row[1]), 0)
            self.assertGreater(int(run_row[2]), 0)
            self.assertGreater(int(run_row[3]), 0)
            c.execute("SELECT COUNT(*) FROM erp_entity_links WHERE process_id=?", (process_id,))
            self.assertGreaterEqual(c.fetchone()[0], 3)
            conn.close()
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM erp_entity_links WHERE process_id IN (SELECT id FROM erp_process_runs WHERE project_id=991006)")
            c.execute("DELETE FROM erp_process_runs WHERE project_id=?", (991006,))
            c.execute("DELETE FROM finance_payments WHERE project_id IN (?, ?)", (991006, 777888))
            c.execute("DELETE FROM purchase_orders WHERE project_id=?", (991006,))
            c.execute("DELETE FROM approvals WHERE title=?", ("Согласование: ERP маршрут поставки",))
            c.execute("DELETE FROM internal_requests WHERE project_id=?", (991006,))
            c.execute("DELETE FROM projects WHERE id=?", (991006,))
            c.execute("DELETE FROM clients WHERE name=?", (client_name,))
            conn.commit()
            conn.close()

    def test_import_and_merge_master_data(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        client_csv = io.BytesIO("name,inn,contact\nООО Альфа,7701000001,alpha@example.com\nООО Альфа,7701000001,new@example.com\nООО Бета,7701000002,beta@example.com\n".encode("utf-8"))
        clients_import = self.client.post("/api/clients/import", files={"upload": ("clients.csv", client_csv, "text/csv")})
        self.assertEqual(clients_import.status_code, 200)
        self.assertEqual(clients_import.json()["status"], "success")
        self.assertGreaterEqual(clients_import.json()["created"], 2)

        nomenclature_json = io.BytesIO(json.dumps([
            {"name": "Кабель силовой", "article": "CAB-001", "unit": "м", "price": 120, "stock": 10, "currency": "RUB"},
            {"name": "Кабель силовой дубль", "article": "CAB-001-DUP", "unit": "м", "price": 125, "stock": 4, "currency": "RUB"},
        ], ensure_ascii=False).encode("utf-8"))
        nsi_import = self.client.post("/api/nomenclature/import", files={"upload": ("nomenclature.json", nomenclature_json, "application/json")})
        self.assertEqual(nsi_import.status_code, 200)
        self.assertEqual(nsi_import.json()["status"], "success")

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM clients WHERE name='ООО Альфа' ORDER BY id ASC")
        alpha_ids = [row[0] for row in c.fetchall()]
        if len(alpha_ids) < 2:
            c.execute("INSERT INTO clients (name, inn, contact) VALUES (?, ?, ?)", ("ООО Альфа", "7701000001", "dup@example.com"))
            conn.commit()
            c.execute("SELECT id FROM clients WHERE name='ООО Альфа' ORDER BY id ASC")
            alpha_ids = [row[0] for row in c.fetchall()]
        master_client_id, duplicate_client_id = alpha_ids[0], alpha_ids[-1]
        c.execute("INSERT INTO contacts (client_id, name, phone, email, position) VALUES (?, ?, ?, ?, ?)", (duplicate_client_id, "QA Duplicate", "", "dup@example.com", "Контакт"))
        c.execute("INSERT INTO finance_payments (project_id, client_id, title, kind, category, amount, currency, due_date, paid_date, status, comment, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (0, duplicate_client_id, "Платеж дубля", "incoming", "erp", 1000, "RUB", "", "", "planned", "", self.user["email"], 0, 0))
        c.execute("INSERT INTO nomenclature (name, article, unit, price, stock, currency) VALUES (?, ?, ?, ?, ?, ?)", ("Кабель силовой", "CAB-001", "м", 120, 10, "RUB"))
        c.execute("INSERT OR IGNORE INTO nomenclature (name, article, unit, price, stock, currency) VALUES (?, ?, ?, ?, ?, ?)", ("Кабель силовой дубль", "CAB-001-DUP", "м", 125, 4, "RUB"))
        c.execute("INSERT INTO stock_reservations (project_id, nomenclature_article, nomenclature_name, qty, status, comment, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (0, "CAB-001-DUP", "Кабель силовой дубль", 2, "reserved", "", self.user["email"], 0))
        conn.commit()
        conn.close()

        try:
            director = create_test_user(role="Директор", name_prefix="Merge Director")
            try:
                director_client = TestClient(app)
                director_login = director_client.post("/api/login", json={"email": director["email"], "password": director["password"]})
                self.assertEqual(director_login.status_code, 200)

                merged_clients = director_client.post("/api/clients/merge", json={"master_id": master_client_id, "duplicate_ids": [duplicate_client_id]})
                self.assertEqual(merged_clients.status_code, 200)
                self.assertEqual(merged_clients.json()["status"], "success")

                merged_nsi = director_client.post("/api/nomenclature/merge", json={"master_article": "CAB-001", "duplicate_articles": ["CAB-001-DUP"]})
                self.assertEqual(merged_nsi.status_code, 200)
                self.assertEqual(merged_nsi.json()["status"], "success")
            finally:
                delete_test_user(director["email"])

            quality = self.client.get("/api/erp/data_quality")
            self.assertEqual(quality.status_code, 200)
            payload = quality.json()
            self.assertIn("clients_duplicates", payload)
            self.assertIn("nomenclature_duplicates", payload)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM clients WHERE id=?", (duplicate_client_id,))
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT COUNT(*) FROM contacts WHERE client_id=?", (master_client_id,))
            self.assertGreaterEqual(c.fetchone()[0], 1)
            c.execute("SELECT COUNT(*) FROM finance_payments WHERE client_id=?", (master_client_id,))
            self.assertGreaterEqual(c.fetchone()[0], 1)
            c.execute("SELECT COUNT(*) FROM nomenclature WHERE article='CAB-001-DUP'")
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT stock FROM nomenclature WHERE article='CAB-001'")
            self.assertGreaterEqual(float(c.fetchone()[0]), 14)
            c.execute("SELECT COUNT(*) FROM stock_reservations WHERE nomenclature_article='CAB-001'")
            self.assertGreaterEqual(c.fetchone()[0], 1)
            conn.close()
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM stock_reservations WHERE nomenclature_article IN (?, ?)", ("CAB-001", "CAB-001-DUP"))
            c.execute("DELETE FROM finance_payments WHERE title='Платеж дубля'")
            c.execute("DELETE FROM contacts WHERE email='dup@example.com'")
            c.execute("DELETE FROM nomenclature WHERE article IN (?, ?)", ("CAB-001", "CAB-001-DUP"))
            c.execute("DELETE FROM clients WHERE name IN (?, ?)", ("ООО Альфа", "ООО Бета"))
            conn.commit()
            conn.close()

    def test_finance_erp_controls_create_entries_sync_sign_and_close_period(self):
        director = create_test_user(role="Директор", name_prefix="ERP Finance Director")
        director_client = TestClient(app)
        try:
            login = director_client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            master_data = director_client.get("/api/finance/master_data")
            self.assertEqual(master_data.status_code, 200)
            master_payload = master_data.json()
            legal_entity_id = int(master_payload["defaults"]["legal_entity_id"])
            business_unit_id = int(master_payload["defaults"]["business_unit_id"])
            vat_rate_id = int(master_payload["defaults"]["vat_rate_id"])
            outgoing_article = next(item for item in master_payload["treasury_articles"] if item["flow_kind"] == "outgoing")

            client_name = "QA ERP Finance Client"
            project_id = allocate_test_project_id()
            period_key = "2099-12"

            director_client.post("/api/clients", json={"name": client_name, "inn": "7701555000", "contact": "erp-fin@example.com"})
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
            client_id = int(c.fetchone()[0])
            c.execute(
                """
                INSERT INTO projects (
                    id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                    budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                    subtasks, time_logs, allowed_roles, nomenclature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    "QA ERP Finance Project",
                    "QA-ERP-2099",
                    client_name,
                    director["name"],
                    "active",
                    5,
                    "{}",
                    "{}",
                    "{}",
                    100000,
                    0,
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "{}",
                    "{}",
                    "{}",
                    "{}",
                    "[]",
                    "[]",
                    "[]",
                ),
            )
            conn.commit()
            conn.close()

            limit_res = director_client.post(
                "/api/finance/treasury_limits",
                json={
                    "period_key": period_key,
                    "legal_entity_id": legal_entity_id,
                    "business_unit_id": business_unit_id,
                    "treasury_article_id": outgoing_article["id"],
                    "amount_limit": 15000,
                    "status": "active",
                },
            )
            self.assertEqual(limit_res.status_code, 200)
            self.assertEqual(limit_res.json()["status"], "success")

            payment_res = director_client.post(
                "/api/finance/payments",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "legal_entity_id": legal_entity_id,
                    "business_unit_id": business_unit_id,
                    "treasury_article_id": outgoing_article["id"],
                    "vat_rate_id": vat_rate_id,
                    "source_document_type": "manual",
                    "source_document_id": 0,
                    "title": "ERP тестовая выплата",
                    "kind": "outgoing",
                    "category": "expense",
                    "amount": 12000,
                    "currency": "RUB",
                    "due_date": "15.12.2099",
                    "paid_date": "16.12.2099",
                    "status": "paid",
                    "comment": "Проверка ERP-финконтура",
                },
            )
            self.assertEqual(payment_res.status_code, 200)
            self.assertEqual(payment_res.json()["status"], "success")
            payment_id = int(payment_res.json()["id"])

            journal = director_client.get("/api/finance/journal")
            self.assertEqual(journal.status_code, 200)
            self.assertTrue(any(item["source_id"] == payment_id and item["source_type"] == "finance_payment" for item in journal.json()))

            queue_before = director_client.get("/api/finance/sync_queue")
            self.assertEqual(queue_before.status_code, 200)
            self.assertTrue(any(item["entity_type"] == "finance_payment" and int(item["entity_id"]) == payment_id for item in queue_before.json()))

            process_res = director_client.post("/api/finance/sync_queue/process?limit=10")
            self.assertEqual(process_res.status_code, 200)
            self.assertEqual(process_res.json()["status"], "success")
            self.assertGreaterEqual(process_res.json()["success"], 1)

            sign_res = director_client.post(
                "/api/finance/edo_signatures",
                json={
                    "entity_type": "finance_payment",
                    "entity_id": payment_id,
                    "signer_name": director["name"],
                    "signer_role": "Директор",
                    "certificate_thumbprint": "QA-THUMBPRINT-2099",
                    "signature_provider": "1С-ЭДО",
                    "signature_status": "signed",
                    "signed_at": "16.12.2099",
                    "comment": "Тестовая подпись",
                },
            )
            self.assertEqual(sign_res.status_code, 200)
            self.assertEqual(sign_res.json()["status"], "success")

            act_res = director_client.post(
                "/api/finance/reconciliation_acts",
                json={
                    "client_id": client_id,
                    "contract_id": 0,
                    "period_key": period_key,
                    "act_number": "QA-ACT-2099",
                    "amount_receivable": 0,
                    "amount_payable": 12000,
                    "details": {"note": "Автотест"},
                    "status": "draft",
                },
            )
            self.assertEqual(act_res.status_code, 200)
            self.assertEqual(act_res.json()["status"], "success")

            close_res = director_client.post(
                "/api/finance/periods/close",
                json={"period_key": period_key, "comment": "Закрыто автотестом"},
            )
            self.assertEqual(close_res.status_code, 200)
            self.assertEqual(close_res.json()["status"], "success")

            erp_summary = director_client.get("/api/finance/erp_summary")
            self.assertEqual(erp_summary.status_code, 200)
            self.assertGreaterEqual(erp_summary.json()["metrics"]["edo_signed"], 1)

            periods = director_client.get("/api/finance/periods")
            self.assertEqual(periods.status_code, 200)
            self.assertTrue(any(item["period_key"] == period_key and item["status"] == "closed" for item in periods.json()))
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM audit_log WHERE entity_type IN ('finance_payment', 'treasury_limit', 'reconciliation_act', 'accounting_period', 'integration_sync_queue') AND (entity_id=? OR entity_id=? OR entity_id=?)", (str(project_id if 'project_id' in locals() else 0), str(client_id if 'client_id' in locals() else 0), str(payment_id if 'payment_id' in locals() else 0)))
            if 'payment_id' in locals():
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM edo_signature_registry WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
            c.execute("DELETE FROM reconciliation_acts WHERE act_number='QA-ACT-2099'")
            c.execute("DELETE FROM treasury_limits WHERE period_key='2099-12'")
            c.execute("DELETE FROM accounting_periods WHERE period_key='2099-12'")
            c.execute("DELETE FROM contract_master WHERE project_id=?", (project_id if 'project_id' in locals() else 0,))
            c.execute("DELETE FROM business_objects WHERE client_id IN (SELECT id FROM clients WHERE name=?)", ("QA ERP Finance Client",))
            c.execute("DELETE FROM projects WHERE id=?", (project_id if 'project_id' in locals() else 0,))
            c.execute("DELETE FROM clients WHERE name=?", ("QA ERP Finance Client",))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_finance_master_data_crud_and_archive(self):
        director = create_test_user(role="Директор", name_prefix="ERP Master Director")
        director_client = TestClient(app)
        legal_id = 0
        unit_id = 0
        article_id = 0
        vat_id = 0
        try:
            login = director_client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            legal_res = director_client.post(
                "/api/finance/master_data/legal_entities",
                json={
                    "name": "ООО Тестовое Юрлицо",
                    "short_name": "Тест ЮЛ",
                    "inn": "7701999000",
                    "kpp": "770101001",
                    "ogrn": "1234567890123",
                    "vat_mode": "osno",
                    "default_currency": "RUB",
                    "is_active": 1,
                },
            )
            self.assertEqual(legal_res.status_code, 200)
            legal_id = int(legal_res.json()["id"])

            unit_res = director_client.post(
                "/api/finance/master_data/business_units",
                json={
                    "legal_entity_id": legal_id,
                    "name": "Проектный офис QA",
                    "code": "QA-OFFICE",
                    "manager_name": "Тестовый руководитель",
                    "is_active": 1,
                },
            )
            self.assertEqual(unit_res.status_code, 200)
            unit_id = int(unit_res.json()["id"])

            article_res = director_client.post(
                "/api/finance/master_data/treasury_articles",
                json={
                    "name": "QA Поступления",
                    "code": "QA-IN",
                    "flow_kind": "incoming",
                    "category": "qa",
                    "is_active": 1,
                },
            )
            self.assertEqual(article_res.status_code, 200)
            article_id = int(article_res.json()["id"])

            vat_res = director_client.post(
                "/api/finance/master_data/vat_rates",
                json={
                    "name": "QA НДС 7%",
                    "rate": 7,
                    "is_default": 1,
                    "is_active": 1,
                },
            )
            self.assertEqual(vat_res.status_code, 200)
            vat_id = int(vat_res.json()["id"])

            update_res = director_client.put(
                f"/api/finance/master_data/business_units/{unit_id}",
                json={
                    "legal_entity_id": legal_id,
                    "name": "Проектный офис QA+",
                    "code": "QA-OFFICE-2",
                    "manager_name": "Тестовый руководитель 2",
                    "is_active": 1,
                },
            )
            self.assertEqual(update_res.status_code, 200)
            self.assertEqual(update_res.json()["status"], "success")

            archive_res = director_client.delete(f"/api/finance/master_data/treasury_articles/{article_id}")
            self.assertEqual(archive_res.status_code, 200)
            self.assertEqual(archive_res.json()["status"], "success")

            master_data = director_client.get("/api/finance/master_data")
            self.assertEqual(master_data.status_code, 200)
            payload = master_data.json()
            self.assertTrue(any(item["id"] == legal_id for item in payload["legal_entities"]))
            self.assertTrue(any(item["id"] == unit_id and item["name"] == "Проектный офис QA+" for item in payload["business_units"]))
            self.assertFalse(any(item["id"] == article_id for item in payload["treasury_articles"]))
            self.assertTrue(any(item["id"] == vat_id and int(item["is_default"]) == 1 for item in payload["vat_rates"]))
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM business_units WHERE code IN (?, ?)", ("QA-OFFICE", "QA-OFFICE-2"))
            c.execute("DELETE FROM treasury_articles WHERE code=?", ("QA-IN",))
            c.execute("DELETE FROM vat_rates WHERE name=?", ("QA НДС 7%",))
            c.execute("DELETE FROM legal_entities WHERE inn=?", ("7701999000",))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_source_documents_auto_sync_finance_payments(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        client_name = "QA Source Truth Client"
        client_id = 0
        project_id = allocate_test_project_id()
        purchase_id = 0
        sales_id = 0
        expense_id = 0
        purchase_payment_id = 0
        sales_payment_id = 0
        expense_payment_id = 0

        self.client.post("/api/clients", json={"name": client_name, "inn": "7701777000", "contact": "truth@example.com"})
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
        client_id = int(c.fetchone()[0])
        c.execute(
            """
            INSERT INTO projects (
                id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                subtasks, time_logs, allowed_roles, nomenclature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                "QA Source Truth Project",
                "QA-SOT-120",
                client_name,
                self.user["name"],
                "active",
                10,
                "{}",
                "{}",
                "{}",
                250000,
                0,
                "[]",
                "[]",
                "[]",
                "[]",
                "[]",
                "{}",
                "{}",
                "{}",
                "{}",
                "[]",
                "[]",
                "[]",
            ),
        )
        conn.commit()
        conn.close()

        try:
            purchase_res = self.client.post(
                "/api/purchases",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "item_article": "QA-RAW-01",
                    "item_name": "Тестовый материал",
                    "supplier": "ООО Поставщик QA",
                    "qty": 5,
                    "unit": "шт",
                    "unit_price": 1200,
                    "status": "ordered",
                    "expected_date": "20.12.2099",
                    "received_date": "",
                    "comment": "Автосвязь с финансами",
                },
            )
            self.assertEqual(purchase_res.status_code, 200)
            purchase_id = int(purchase_res.json()["id"])
            purchase_payment_id = int(purchase_res.json()["linked_payment_id"])

            sales_res = self.client.post(
                "/api/sales/documents",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "doc_type": "invoice",
                    "doc_number": "QA-SALE-120",
                    "doc_date": "21.12.2099",
                    "amount": 18500,
                    "currency": "RUB",
                    "status": "issued",
                    "payment_status": "issued",
                    "comment": "Автосвязь реализации",
                },
            )
            self.assertEqual(sales_res.status_code, 200)
            sales_id = int(sales_res.json()["id"])
            sales_payment_id = int(sales_res.json()["linked_payment_id"])

            expense_res = self.client.post(
                "/api/expenses/requests",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "title": "QA Заявка на расход",
                    "request_type": "expense",
                    "amount": 7300,
                    "currency": "RUB",
                    "approver_role": "Директор",
                    "approver_name": "",
                    "due_date": "22.12.2099",
                    "status": "approved",
                    "comment": "Автосвязь расхода",
                },
            )
            self.assertEqual(expense_res.status_code, 200)
            expense_id = int(expense_res.json()["id"])
            expense_payment_id = int(expense_res.json()["linked_payment_id"])

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT kind, status, source_document_type, source_document_id FROM finance_payments WHERE id=?", (purchase_payment_id,))
            purchase_payment = c.fetchone()
            c.execute("SELECT kind, status, source_document_type, source_document_id FROM finance_payments WHERE id=?", (sales_payment_id,))
            sales_payment = c.fetchone()
            c.execute("SELECT kind, status, source_document_type, source_document_id FROM finance_payments WHERE id=?", (expense_payment_id,))
            expense_payment = c.fetchone()
            conn.close()

            self.assertEqual(purchase_payment[0], "outgoing")
            self.assertEqual(purchase_payment[1], "issued")
            self.assertEqual(purchase_payment[2], "purchase_order")
            self.assertEqual(int(purchase_payment[3]), purchase_id)

            self.assertEqual(sales_payment[0], "incoming")
            self.assertEqual(sales_payment[1], "issued")
            self.assertEqual(sales_payment[2], "sales_document")
            self.assertEqual(int(sales_payment[3]), sales_id)

            self.assertEqual(expense_payment[0], "outgoing")
            self.assertEqual(expense_payment[1], "issued")
            self.assertEqual(expense_payment[2], "expense_request")
            self.assertEqual(int(expense_payment[3]), expense_id)

            reject_res = self.client.put(
                f"/api/expenses/requests/{expense_id}",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "title": "QA Заявка на расход",
                    "request_type": "expense",
                    "amount": 7300,
                    "currency": "RUB",
                    "approver_role": "Директор",
                    "approver_name": "",
                    "due_date": "22.12.2099",
                    "linked_payment_id": expense_payment_id,
                    "status": "rejected",
                    "comment": "Отклонено",
                },
            )
            self.assertEqual(reject_res.status_code, 200)
            self.assertEqual(reject_res.json()["linked_payment_id"], 0)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM finance_payments WHERE source_document_type='expense_request' AND source_document_id=?", (expense_id,))
            self.assertEqual(c.fetchone()[0], 0)
            conn.close()
        finally:
            conn = get_connection()
            c = conn.cursor()
            if expense_payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (expense_payment_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (expense_payment_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (expense_payment_id,))
                c.execute("DELETE FROM edo_signature_registry WHERE entity_type='finance_payment' AND entity_id=?", (expense_payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (expense_payment_id,))
            if sales_payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (sales_payment_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (sales_payment_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (sales_payment_id,))
                c.execute("DELETE FROM edo_signature_registry WHERE entity_type='finance_payment' AND entity_id=?", (sales_payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (sales_payment_id,))
            if purchase_payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (purchase_payment_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (purchase_payment_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (purchase_payment_id,))
                c.execute("DELETE FROM edo_signature_registry WHERE entity_type='finance_payment' AND entity_id=?", (purchase_payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (purchase_payment_id,))
            if expense_id:
                c.execute("DELETE FROM expense_requests WHERE id=?", (expense_id,))
            if sales_id:
                c.execute("DELETE FROM sales_documents_extended WHERE id=?", (sales_id,))
            if purchase_id:
                c.execute("DELETE FROM purchase_orders WHERE id=?", (purchase_id,))
            c.execute("DELETE FROM contract_master WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM business_objects WHERE client_id=?", (client_id,))
            c.execute("DELETE FROM projects WHERE id=?", (project_id,))
            c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            conn.commit()
            conn.close()

    def test_finance_inbound_sync_conflicts_and_analytics(self):
        director = create_test_user(role="Директор", name_prefix="Inbound Sync Director")
        director_client = TestClient(app)
        payment_id = 0
        project_id = allocate_test_project_id()
        client_id = 0
        try:
            login = director_client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            master_data = director_client.get("/api/finance/master_data").json()
            incoming_article = next(item for item in master_data["treasury_articles"] if item["flow_kind"] == "incoming")

            director_client.post("/api/clients", json={"name": "QA Inbound Sync Client", "inn": "7701888000", "contact": "inbound@example.com"})
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", ("QA Inbound Sync Client",))
            client_id = int(c.fetchone()[0])
            c.execute(
                """
                INSERT INTO projects (
                    id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                    budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                    subtasks, time_logs, allowed_roles, nomenclature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id, "QA Inbound Sync Project", "QA-INBOUND-130", "QA Inbound Sync Client", director["name"],
                    "active", 15, "{}", "{}", "{}", 500000, 0, "[]", "[]", "[]", "[]", "[]", "{}", "{}", "{}",
                    "{}", "[]", "[]", "[]",
                ),
            )
            conn.commit()
            conn.close()

            payment_res = director_client.post(
                "/api/finance/payments",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "legal_entity_id": int(master_data["defaults"]["legal_entity_id"]),
                    "business_unit_id": int(master_data["defaults"]["business_unit_id"]),
                    "treasury_article_id": int(incoming_article["id"]),
                    "vat_rate_id": int(master_data["defaults"]["vat_rate_id"]),
                    "title": "QA Inbound payment",
                    "kind": "incoming",
                    "category": "invoice",
                    "amount": 15000,
                    "currency": "RUB",
                    "due_date": "17.12.2099",
                    "paid_date": "",
                    "status": "issued",
                    "comment": "Ждём ответ из 1С",
                    "source_document_type": "manual",
                    "source_document_id": 0,
                },
            )
            self.assertEqual(payment_res.status_code, 200)
            payment_id = int(payment_res.json()["id"])

            preview_res = director_client.post(
                "/api/finance/sync_queue/inbound/preview",
                json={
                    "items": [
                        {
                            "идентификатор записи": payment_id,
                            "внешний идентификатор": "1C-QA-130",
                            "статус": "оплачено",
                            "дата оплаты": "18.12.2099",
                            "сумма": "15 000",
                            "валюта": "RUB",
                        }
                    ],
                    "source_system": "1C",
                    "actor_note": "Предпросмотр входящего обмена",
                },
            )
            self.assertEqual(preview_res.status_code, 200)
            self.assertEqual(preview_res.json()["status"], "success")
            self.assertEqual(preview_res.json()["errors"], 0)
            self.assertEqual(preview_res.json()["ready"], 1)
            self.assertEqual(preview_res.json()["rows"][0]["normalized"]["status"], "paid")

            inbound_res = director_client.post(
                "/api/finance/sync_queue/inbound",
                json={
                    "items": [
                        {"entity_id": payment_id, "external_id": "1C-QA-130", "status": "paid", "paid_date": "18.12.2099", "amount": 15000, "currency": "RUB"},
                        {"entity_id": payment_id, "external_id": "1C-QA-130-BAD", "status": "paid", "paid_date": "18.12.2099", "amount": 19999, "currency": "RUB"},
                    ],
                    "source_system": "1C",
                    "actor_note": "Автотест входящего обмена",
                },
            )
            self.assertEqual(inbound_res.status_code, 200)
            self.assertEqual(inbound_res.json()["status"], "success")
            self.assertGreaterEqual(inbound_res.json()["applied"], 1)
            self.assertGreaterEqual(inbound_res.json()["conflicts"], 1)

            payments = director_client.get("/api/finance/payments")
            self.assertEqual(payments.status_code, 200)
            applied_payment = next(item for item in payments.json() if int(item["id"]) == payment_id)
            self.assertEqual(applied_payment["status"], "paid")
            self.assertEqual(applied_payment["external_sync_id"], "1C-QA-130")

            conflicts = director_client.get("/api/finance/sync_conflicts")
            self.assertEqual(conflicts.status_code, 200)
            self.assertTrue(any(item["external_id"] == "1C-QA-130-BAD" for item in conflicts.json()))

            analytics = director_client.get(f"/api/finance/analytics?project_id={project_id}")
            self.assertEqual(analytics.status_code, 200)
            analytics_payload = analytics.json()
            self.assertGreaterEqual(float(analytics_payload["metrics"]["dds_in_fact"]), 15000)
            self.assertTrue(any(item["project_id"] == project_id for item in analytics_payload["top_projects"]))
        finally:
            conn = get_connection()
            c = conn.cursor()
            if payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM edo_signature_registry WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
            c.execute("DELETE FROM contract_master WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM business_objects WHERE client_id=?", (client_id,))
            c.execute("DELETE FROM projects WHERE id=?", (project_id,))
            c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_production_operations_rollup_and_costing(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        client_name = "QA Production Ops Client"
        project_id = allocate_test_project_id()
        client_id = 0
        order_id = 0
        operation_ids = []

        self.client.post("/api/clients", json={"name": client_name, "inn": "7701999131", "contact": "prod@example.com"})
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
        client_id = int(c.fetchone()[0])
        c.execute(
            """
            INSERT INTO projects (
                id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                subtasks, time_logs, allowed_roles, nomenclature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, "QA Production Ops Project", "QA-PROD-131", client_name, self.user["name"],
                "active", 20, "{}", "{}", "{}", 350000, 0, "[]", "[]", "[]", "[]", "[]", "{}", "{}", "{}",
                "{}", "[]", "[]", "[]",
            ),
        )
        conn.commit()
        conn.close()

        try:
            order_res = self.client.post(
                "/api/production/orders",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "order_name": "QA Production Order",
                    "responsible": self.user["name"],
                    "route_name": "Сборка -> ОТК",
                    "stage": "queue",
                    "priority": "high",
                    "planned_start": "10.12.2099",
                    "planned_finish": "20.12.2099",
                    "planned_qty": 10,
                    "planned_cost": 50000,
                    "labor_hours_plan": 24,
                    "progress": 0,
                    "comment": "Тест операций производства",
                },
            )
            self.assertEqual(order_res.status_code, 200)
            order_id = int(order_res.json()["id"])

            op1 = self.client.post(
                "/api/production/operations",
                json={
                    "order_id": order_id,
                    "sequence_no": 1,
                    "operation_name": "Сборка",
                    "work_center": "Цех 1",
                    "status": "done",
                    "planned_hours": 8,
                    "actual_hours": 9,
                    "planned_qty": 10,
                    "completed_qty": 10,
                    "scrap_qty": 1,
                    "labor_rate": 1000,
                    "material_cost": 12000,
                    "overhead_cost": 3000,
                    "started_at": "10.12.2099",
                    "finished_at": "11.12.2099",
                    "note": "Первый этап",
                },
            )
            self.assertEqual(op1.status_code, 200)
            operation_ids.append(int(op1.json()["id"]))

            op2 = self.client.post(
                "/api/production/operations",
                json={
                    "order_id": order_id,
                    "sequence_no": 2,
                    "operation_name": "ОТК",
                    "work_center": "ОТК",
                    "status": "done",
                    "planned_hours": 4,
                    "actual_hours": 5,
                    "planned_qty": 10,
                    "completed_qty": 10,
                    "scrap_qty": 0,
                    "labor_rate": 800,
                    "material_cost": 0,
                    "overhead_cost": 1500,
                    "started_at": "12.12.2099",
                    "finished_at": "12.12.2099",
                    "note": "Контроль качества",
                },
            )
            self.assertEqual(op2.status_code, 200)
            operation_ids.append(int(op2.json()["id"]))

            orders = self.client.get("/api/production/orders")
            self.assertEqual(orders.status_code, 200)
            order = next(item for item in orders.json() if int(item["id"]) == order_id)
            self.assertEqual(int(order["operations_count"]), 2)
            self.assertEqual(int(order["progress"]), 100)
            self.assertEqual(order["stage"], "done")
            self.assertGreaterEqual(float(order["actual_cost_total"]), 25500)
            self.assertGreaterEqual(float(order["labor_hours_total"]), 14)
            self.assertGreaterEqual(float(order["produced_qty_total"]), 10)

            ops = self.client.get(f"/api/production/operations?order_id={order_id}")
            self.assertEqual(ops.status_code, 200)
            self.assertEqual(len(ops.json()), 2)
            self.assertTrue(all(float(item["actual_cost"]) >= 0 for item in ops.json()))

            summary = self.client.get("/api/production/summary")
            self.assertEqual(summary.status_code, 200)
            self.assertGreaterEqual(int(summary.json()["metrics"]["operations_total"]), 2)
            self.assertGreaterEqual(float(summary.json()["metrics"]["actual_cost_total"]), 25500)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if operation_ids:
                c.execute(f"DELETE FROM production_operations WHERE id IN ({','.join('?' for _ in operation_ids)})", tuple(operation_ids))
            if order_id:
                c.execute("DELETE FROM production_orders WHERE id=?", (order_id,))
            c.execute("DELETE FROM contract_master WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM business_objects WHERE client_id=?", (client_id,))
            c.execute("DELETE FROM projects WHERE id=?", (project_id,))
            c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            conn.commit()
            conn.close()

    def test_delete_lifecycle_for_ops_and_enterprise_modules(self):
        director = create_test_user(role="Директор", name_prefix="Lifecycle Director")
        project_id = allocate_test_project_id()
        client_id = 0
        process_id = 0
        request_id = 0
        purchase_id = 0
        purchase_payment_id = 0
        sales_id = 0
        sales_payment_id = 0
        expense_id = 0
        expense_payment_id = 0
        production_id = 0
        resource_id = 0
        service_id = 0
        budget_id = 0
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            client_name = "QA Lifecycle Client"
            client_create = self.client.post("/api/clients", json={"name": client_name, "inn": "7705554433", "contact": "life@example.com"})
            self.assertEqual(client_create.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=? ORDER BY id DESC LIMIT 1", (client_name,))
            client_id = int(c.fetchone()[0])
            c.execute(
                """
                INSERT INTO projects (
                    id, name, contract, client, manager, status, progress, checkedState, comments, deadlines,
                    budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles,
                    subtasks, time_logs, allowed_roles, nomenclature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    "QA Lifecycle Project",
                    "2026-КРД-LIFE",
                    client_name,
                    director["name"],
                    "active",
                    20,
                    "{}",
                    "{}",
                    "{}",
                    150000,
                    50000,
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "{}",
                    "{}",
                    "{}",
                    "{}",
                    "[]",
                    "[]",
                    "[]",
                ),
            )
            conn.commit()
            conn.close()

            purchase = self.client.post("/api/purchases", json={
                "project_id": project_id, "client_id": client_id, "item_article": "LIFE-001", "item_name": "Позиция закупки",
                "supplier": "ООО Жизненный цикл", "qty": 2, "unit": "шт", "unit_price": 3500, "status": "ordered",
                "expected_date": "30.12.2099", "received_date": "", "comment": "Удаление закупки"
            })
            self.assertEqual(purchase.status_code, 200)
            purchase_id = int(purchase.json()["id"])
            purchase_payment_id = int(purchase.json()["linked_payment_id"])

            sales = self.client.post("/api/sales/documents", json={
                "project_id": project_id, "client_id": client_id, "doc_type": "invoice", "doc_number": "LIFE-SALE-01",
                "doc_date": "12.04.2026", "amount": 28000, "currency": "RUB", "status": "issued",
                "payment_status": "issued", "linked_payment_id": 0, "comment": "Удаление реализации"
            })
            self.assertEqual(sales.status_code, 200)
            sales_id = int(sales.json()["id"])
            sales_payment_id = int(sales.json()["linked_payment_id"])

            production = self.client.post("/api/production/orders", json={
                "project_id": project_id, "client_id": client_id, "order_name": "Заказ на производство",
                "stage": "queue", "priority": "normal", "planned_start": "13.04.2026", "planned_finish": "20.04.2026",
                "actual_finish": "", "progress": 10, "responsible": "QA Master", "comment": "Удаление производства"
            })
            self.assertEqual(production.status_code, 200)
            production_id = int(production.json()["id"])

            expense = self.client.post("/api/expenses/requests", json={
                "project_id": project_id, "client_id": client_id, "title": "Затраты по проекту",
                "request_type": "expense", "amount": 9700, "currency": "RUB", "approver_role": "Директор",
                "approver_name": director["name"], "due_date": "25.04.2026", "linked_payment_id": 0, "status": "approved",
                "comment": "Удаление затрат"
            })
            self.assertEqual(expense.status_code, 200)
            expense_id = int(expense.json()["id"])
            expense_payment_id = int(expense.json()["linked_payment_id"])

            resource = self.client.post("/api/resources/allocations", json={
                "project_id": project_id, "department": "Конструкторское бюро", "resource_name": "QA Resource",
                "role_name": "Инженер", "load_percent": 65, "date_from": "12.04.2026", "date_to": "19.04.2026",
                "status": "planned", "comment": "Удаление ресурса"
            })
            self.assertEqual(resource.status_code, 200)
            resource_id = int(resource.json()["id"])

            service = self.client.post("/api/service/cases", json={
                "project_id": project_id, "client_id": client_id, "case_number": "LIFE-SRV-01",
                "title": "Сервисный кейс", "case_type": "maintenance", "status": "open",
                "priority": "normal", "defect": "Проверка", "warranty_until": "", "sla_deadline": "21.04.2026",
                "responsible": "QA Service", "resolution": ""
            })
            self.assertEqual(service.status_code, 200)
            service_id = int(service.json()["id"])

            budget = self.client.post("/api/budget/lines", json={
                "project_id": project_id, "line_type": "cost", "category": "Прочие расходы",
                "plan_amount": 15000, "fact_amount": 5000, "comment": "Удаление бюджета"
            })
            self.assertEqual(budget.status_code, 200)
            budget_id = int(budget.json()["id"])

            started = self.client.post(
                "/api/erp/processes/start",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "title": "ERP для удаления заявки",
                    "request_type": "purchase",
                    "scenario": ["request", "approval"],
                    "due_date": "30.04.2026",
                    "amount": 10000,
                    "assignee_name": director["name"],
                    "approver_name": director["name"],
                    "item_article": "LIFE-ERP-01",
                    "item_name": "ERP позиция",
                    "qty": 1,
                    "supplier": "ERP Supplier",
                    "comment": "Проверка detach",
                },
            )
            self.assertEqual(started.status_code, 200)
            self.assertEqual(started.json()["status"], "success")
            process_id = int(started.json()["id"])

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT request_id FROM erp_process_runs WHERE id=?", (process_id,))
            request_id = int(c.fetchone()[0])
            conn.close()
            self.assertGreater(request_id, 0)

            self.assertEqual(self.client.delete(f"/api/purchases/{purchase_id}").status_code, 200)
            self.assertEqual(self.client.delete(f"/api/sales/documents/{sales_id}").status_code, 200)
            self.assertEqual(self.client.delete(f"/api/production/orders/{production_id}").status_code, 200)
            self.assertEqual(self.client.delete(f"/api/expenses/requests/{expense_id}").status_code, 200)
            self.assertEqual(self.client.delete(f"/api/resources/allocations/{resource_id}").status_code, 200)
            self.assertEqual(self.client.delete(f"/api/service/cases/{service_id}").status_code, 200)
            self.assertEqual(self.client.delete(f"/api/budget/lines/{budget_id}").status_code, 200)
            self.assertEqual(self.client.delete(f"/api/internal_requests/{request_id}").status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM purchase_orders WHERE id=?", (purchase_id,))
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT COUNT(*) FROM sales_documents_extended WHERE id=?", (sales_id,))
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT COUNT(*) FROM production_orders WHERE id=?", (production_id,))
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT COUNT(*) FROM expense_requests WHERE id=?", (expense_id,))
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT COUNT(*) FROM resource_allocations WHERE id=?", (resource_id,))
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT COUNT(*) FROM service_cases WHERE id=?", (service_id,))
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT COUNT(*) FROM project_budget_lines WHERE id=?", (budget_id,))
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT COUNT(*) FROM internal_requests WHERE id=?", (request_id,))
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT COUNT(*) FROM finance_payments WHERE id IN (?, ?, ?)", (purchase_payment_id, sales_payment_id, expense_payment_id))
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT request_id FROM erp_process_runs WHERE id=?", (process_id,))
            self.assertEqual(int(c.fetchone()[0]), 0)
            conn.close()
        finally:
            statements = []
            if process_id:
                statements.append(("DELETE FROM erp_entity_links WHERE process_id=?", (process_id,)))
                statements.append(("DELETE FROM erp_process_runs WHERE id=?", (process_id,)))
            statements.extend(
                [
                    ("DELETE FROM project_budget_lines WHERE project_id=?", (project_id,)),
                    ("DELETE FROM service_cases WHERE project_id=?", (project_id,)),
                    ("DELETE FROM resource_allocations WHERE project_id=?", (project_id,)),
                    ("DELETE FROM expense_requests WHERE project_id=?", (project_id,)),
                    ("DELETE FROM production_orders WHERE project_id=?", (project_id,)),
                    ("DELETE FROM sales_documents_extended WHERE project_id=?", (project_id,)),
                    ("DELETE FROM purchase_orders WHERE project_id=?", (project_id,)),
                    ("DELETE FROM internal_requests WHERE project_id=?", (project_id,)),
                    (
                        "DELETE FROM notifications WHERE entity_id IN (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(purchase_id),
                            str(sales_id),
                            str(expense_id),
                            str(resource_id),
                            str(service_id),
                            str(budget_id),
                            str(request_id),
                            str(process_id),
                        ),
                    ),
                    (
                        "DELETE FROM accounting_entries WHERE source_id IN (?, ?, ?)",
                        (purchase_payment_id, sales_payment_id, expense_payment_id),
                    ),
                    (
                        "DELETE FROM integration_sync_log WHERE entity_id IN (?, ?, ?)",
                        (str(purchase_payment_id), str(sales_payment_id), str(expense_payment_id)),
                    ),
                    (
                        "DELETE FROM integration_sync_queue WHERE entity_id IN (?, ?, ?)",
                        (str(purchase_payment_id), str(sales_payment_id), str(expense_payment_id)),
                    ),
                    (
                        "DELETE FROM edo_signature_registry WHERE entity_id IN (?, ?, ?)",
                        (purchase_payment_id, sales_payment_id, expense_payment_id),
                    ),
                    (
                        "DELETE FROM finance_payments WHERE id IN (?, ?, ?)",
                        (purchase_payment_id, sales_payment_id, expense_payment_id),
                    ),
                    ("DELETE FROM projects WHERE id=?", (project_id,)),
                ]
            )
            if client_id:
                statements.append(("DELETE FROM clients WHERE id=?", (client_id,)))
            run_db_cleanup(statements)
            delete_test_user(director["email"])

    def test_global_1c_sync_for_supply_sales_production_and_nsi(self):
        director = create_test_user(role="Директор", name_prefix="Sync Director")
        client_name = "QA Sync Client"
        sync_suffix = str(int(time.time() * 1000))
        warehouse_code = f"QA-SYNC-WH-{sync_suffix}"
        warehouse_name = "QA Sync Warehouse"
        group_code = f"QA-SYNC-GRP-{sync_suffix}"
        group_name = "QA Sync Group"
        article_code = f"QA-SYNC-ITEM-{sync_suffix}"
        item_name = f"QA Sync Item {sync_suffix}"
        sales_doc_number = f"SYNC-{sync_suffix}"
        purchase_id = 0
        sales_id = 0
        production_id = 0
        reservation_id = 0
        nomenclature_id = 0
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            self.assertEqual(self.client.post("/api/clients", json={"name": client_name, "inn": "7711223344", "contact": "sync@example.com"}).status_code, 200)
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=? ORDER BY id DESC LIMIT 1", (client_name,))
            client_id = int(c.fetchone()[0])
            conn.close()

            self.assertEqual(self.client.post("/api/nsi/master_data/warehouses", json={"name": warehouse_name, "code": warehouse_code}).status_code, 200)
            self.assertEqual(self.client.post("/api/nsi/master_data/groups", json={"name": group_name, "code": group_code}).status_code, 200)
            created_nomenclature = self.client.post("/api/nomenclature", json={
                "name": item_name,
                "article": article_code,
                "unit": "шт",
                "price": 1200,
                "stock": 0,
                "currency": "RUB",
                "group_name": group_name,
                "default_warehouse": warehouse_name,
            })
            self.assertEqual(created_nomenclature.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM nomenclature WHERE article=?", (article_code,))
            nomenclature_id = int(c.fetchone()[0])
            conn.close()

            purchase = self.client.post("/api/purchases", json={
                "project_id": 0, "client_id": client_id, "item_article": article_code, "item_name": item_name,
                "supplier": "ООО Sync", "qty": 3, "unit": "шт", "unit_price": 1500, "status": "ordered",
                "expected_date": "30.04.2026", "received_date": "", "comment": "Queue purchase"
            })
            self.assertEqual(purchase.status_code, 200)
            purchase_id = int(purchase.json()["id"])

            sales = self.client.post("/api/sales/documents", json={
                "project_id": 0, "client_id": client_id, "doc_type": "invoice", "doc_number": sales_doc_number,
                "doc_date": "12.04.2026", "amount": 5400, "currency": "RUB", "status": "issued",
                "payment_status": "issued", "linked_payment_id": 0, "comment": "Queue sales"
            })
            self.assertEqual(sales.status_code, 200)
            sales_id = int(sales.json()["id"])

            production = self.client.post("/api/production/orders", json={
                "project_id": 0, "client_id": client_id, "order_name": "QA Sync Production",
                "stage": "queue", "priority": "normal", "planned_start": "13.04.2026", "planned_finish": "20.04.2026",
                "actual_finish": "", "progress": 15, "responsible": "QA Master", "comment": "Queue production"
            })
            self.assertEqual(production.status_code, 200)
            production_id = int(production.json()["id"])

            reservation = self.client.post("/api/stock/reservations", json={
                "project_id": 0, "nomenclature_article": article_code, "nomenclature_name": item_name,
                "qty": 2, "status": "reserved", "comment": "Queue reservation"
            })
            self.assertEqual(reservation.status_code, 200)
            reservation_id = int(reservation.json()["id"])

            processed = self.client.post("/api/integration/1c/process?limit=25")
            self.assertEqual(processed.status_code, 200)
            self.assertEqual(processed.json()["status"], "success")
            self.assertGreaterEqual(processed.json()["success"], 4)

            inbound = self.client.post("/api/integration/1c/inbound", json={
                "source_system": "1C",
                "actor_note": "batch inbound",
                "items": [
                    {"entity_type": "purchase_order", "entity_id": purchase_id, "external_id": "1C-PUR-EXT-1", "status": "received", "comment": "Получено из 1С"},
                    {"entity_type": "sales_document", "entity_id": sales_id, "external_id": "1C-SAL-EXT-1", "status": "signed", "payload": {"payment_status": "paid"}},
                    {"entity_type": "production_order", "entity_id": production_id, "external_id": "1C-PRD-EXT-1", "status": "done", "payload": {"stage": "done"}},
                    {"entity_type": "stock_reservation", "entity_id": reservation_id, "external_id": "1C-RES-EXT-1", "status": "fulfilled"},
                    {"entity_type": "nomenclature", "entity_id": nomenclature_id, "external_id": "1C-NSI-EXT-1", "payload": {"price": 1750, "group_name": "QA Sync Group", "default_warehouse": "QA Sync Warehouse", "unit": "шт"}},
                ],
            })
            self.assertEqual(inbound.status_code, 200)
            self.assertEqual(inbound.json()["status"], "success")
            self.assertEqual(inbound.json()["conflicts"], 0)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT status, exchange_state, external_sync_id FROM purchase_orders WHERE id=?", (purchase_id,))
            purchase_state = c.fetchone()
            self.assertEqual(purchase_state[0], "received")
            self.assertEqual(purchase_state[1], "synced")
            self.assertEqual(purchase_state[2], "1C-PUR-EXT-1")
            c.execute("SELECT status, payment_status, exchange_state FROM sales_documents_extended WHERE id=?", (sales_id,))
            sales_state = c.fetchone()
            self.assertEqual(sales_state[0], "signed")
            self.assertEqual(sales_state[1], "paid")
            self.assertEqual(sales_state[2], "synced")
            c.execute("SELECT stage, exchange_state FROM production_orders WHERE id=?", (production_id,))
            production_state = c.fetchone()
            self.assertEqual(production_state[0], "done")
            self.assertEqual(production_state[1], "synced")
            c.execute("SELECT status, exchange_state FROM stock_reservations WHERE id=?", (reservation_id,))
            reservation_state = c.fetchone()
            self.assertEqual(reservation_state[0], "fulfilled")
            self.assertEqual(reservation_state[1], "synced")
            c.execute("SELECT price, default_warehouse, exchange_state FROM nomenclature WHERE id=?", (nomenclature_id,))
            nsi_state = c.fetchone()
            self.assertEqual(float(nsi_state[0]), 1750.0)
            self.assertEqual(nsi_state[1], warehouse_name)
            self.assertEqual(nsi_state[2], "synced")
            conn.close()
        finally:
            statements = []
            if purchase_id:
                statements.extend([
                    ("DELETE FROM integration_sync_log WHERE entity_type='purchase_order' AND entity_id=?", (purchase_id,)),
                    ("DELETE FROM integration_sync_queue WHERE entity_type='purchase_order' AND entity_id=?", (purchase_id,)),
                    ("DELETE FROM purchase_orders WHERE id=?", (purchase_id,)),
                ])
            if sales_id:
                statements.extend([
                    ("DELETE FROM integration_sync_log WHERE entity_type='sales_document' AND entity_id=?", (sales_id,)),
                    ("DELETE FROM integration_sync_queue WHERE entity_type='sales_document' AND entity_id=?", (sales_id,)),
                    ("DELETE FROM sales_documents_extended WHERE id=?", (sales_id,)),
                ])
            if production_id:
                statements.extend([
                    ("DELETE FROM integration_sync_log WHERE entity_type='production_order' AND entity_id=?", (production_id,)),
                    ("DELETE FROM integration_sync_queue WHERE entity_type='production_order' AND entity_id=?", (production_id,)),
                    ("DELETE FROM production_operations WHERE order_id=?", (production_id,)),
                    ("DELETE FROM production_orders WHERE id=?", (production_id,)),
                ])
            if reservation_id:
                statements.extend([
                    ("DELETE FROM integration_sync_log WHERE entity_type='stock_reservation' AND entity_id=?", (reservation_id,)),
                    ("DELETE FROM integration_sync_queue WHERE entity_type='stock_reservation' AND entity_id=?", (reservation_id,)),
                    ("DELETE FROM stock_reservations WHERE id=?", (reservation_id,)),
                ])
            if nomenclature_id:
                statements.extend([
                    ("DELETE FROM integration_sync_log WHERE entity_type='nomenclature' AND entity_id=?", (nomenclature_id,)),
                    ("DELETE FROM integration_sync_queue WHERE entity_type='nomenclature' AND entity_id=?", (nomenclature_id,)),
                    ("DELETE FROM stock_movements WHERE article=?", (article_code,)),
                    ("DELETE FROM inventory_documents WHERE article=?", (article_code,)),
                    ("DELETE FROM inventory_balances WHERE article=?", (article_code,)),
                    ("DELETE FROM inventory_lots WHERE article=?", (article_code,)),
                    ("DELETE FROM nomenclature WHERE id=?", (nomenclature_id,)),
                ])
            statements.extend([
                ("DELETE FROM nomenclature_groups WHERE code=?", (group_code,)),
                ("DELETE FROM warehouse_master WHERE code=?", (warehouse_code,)),
                ("DELETE FROM clients WHERE name=?", (client_name,)),
            ])
            run_db_cleanup(statements)
            delete_test_user(director["email"])

    def test_nsi_master_directories_and_sync_controls(self):
        director = create_test_user(role="Директор", name_prefix="NSI Director")
        position_id = 0
        employee_id = 0
        storage_cell_id = 0
        characteristic_id = 0
        frc_id = 0
        operation_type_id = 0
        bank_account_id = 0
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            payload = self.client.get("/api/nsi/master_data").json()
            warehouse_id = int(payload["defaults"]["warehouse_id"])
            legal_entity_id = int(payload["defaults"]["legal_entity_id"])
            business_unit_id = int(payload["defaults"]["business_unit_id"])

            position = self.client.post("/api/nsi/master_data/positions", json={
                "name": "QA NSI Position",
                "code": "QA-NSI-POS",
                "department_name": "QA Department",
            })
            self.assertEqual(position.status_code, 200)
            position_id = int(position.json()["id"])

            employee = self.client.post("/api/nsi/master_data/employees", json={
                "name": "QA NSI Employee",
                "personnel_number": "QA-EMP-001",
                "email": "qa-nsi-employee@example.com",
                "phone": "+79990001122",
                "legal_entity_id": legal_entity_id,
                "business_unit_id": business_unit_id,
                "position_id": position_id,
            })
            self.assertEqual(employee.status_code, 200)
            employee_id = int(employee.json()["id"])

            characteristic = self.client.post("/api/nsi/master_data/characteristics", json={
                "name": "QA NSI Characteristic",
                "code": "QA-NSI-CHAR",
                "characteristic_type": "size",
            })
            self.assertEqual(characteristic.status_code, 200)
            characteristic_id = int(characteristic.json()["id"])

            storage_cell = self.client.post("/api/nsi/master_data/storage_cells", json={
                "name": "QA NSI Cell",
                "code": "QA-NSI-CELL",
                "warehouse_id": warehouse_id,
                "zone_name": "QA-ZONE",
            })
            self.assertEqual(storage_cell.status_code, 200)
            storage_cell_id = int(storage_cell.json()["id"])

            frc = self.client.post("/api/nsi/master_data/financial_responsibility_centers", json={
                "name": "QA NSI FRC",
                "code": "QA-NSI-FRC",
                "legal_entity_id": legal_entity_id,
                "business_unit_id": business_unit_id,
                "manager_name": director["name"],
            })
            self.assertEqual(frc.status_code, 200)
            frc_id = int(frc.json()["id"])

            operation_type = self.client.post("/api/nsi/master_data/operation_types", json={
                "name": "QA NSI Operation",
                "code": "QA-NSI-OP",
                "module_name": "warehouse",
                "flow_kind": "internal",
            })
            self.assertEqual(operation_type.status_code, 200)
            operation_type_id = int(operation_type.json()["id"])

            bank_account = self.client.post("/api/nsi/master_data/bank_accounts", json={
                "name": "QA NSI Bank",
                "code": "QA-NSI-BANK",
                "bank_name": "QA Bank",
                "account_number": "40702810900000000001",
                "bik": "044525225",
                "currency": "RUB",
                "legal_entity_id": legal_entity_id,
            })
            self.assertEqual(bank_account.status_code, 200)
            bank_account_id = int(bank_account.json()["id"])

            payload = self.client.get("/api/nsi/master_data").json()
            self.assertTrue(any(item["id"] == position_id for item in payload["positions"]))
            self.assertTrue(any(item["id"] == employee_id for item in payload["employees"]))
            self.assertTrue(any(item["id"] == characteristic_id for item in payload["characteristics"]))
            self.assertTrue(any(item["id"] == storage_cell_id for item in payload["storage_cells"]))
            self.assertTrue(any(item["id"] == frc_id for item in payload["financial_responsibility_centers"]))
            self.assertTrue(any(item["id"] == operation_type_id for item in payload["operation_types"]))
            self.assertTrue(any(item["id"] == bank_account_id for item in payload["bank_accounts"]))

            sync_position = self.client.post(f"/api/nsi/master_data/positions/{position_id}/sync")
            self.assertEqual(sync_position.status_code, 200)
            self.assertEqual(sync_position.json()["status"], "success")
            self.assertGreater(int(sync_position.json()["queue_id"]), 0)

            conn = get_connection()
            c = conn.cursor()
            now = int(time.time())
            c.execute(
                """
                INSERT INTO integration_sync_queue
                (system_name, entity_type, entity_id, mapping_key, payload, state, external_id, last_error, created_by, created_at, updated_at)
                VALUES ('1C', ?, ?, ?, ?, 'failed', '', 'QA mismatch', ?, ?, ?)
                """,
                (
                    "bank_accounts",
                    bank_account_id,
                    f"bank_accounts:{bank_account_id}",
                    "{}",
                    director["email"],
                    now,
                    now,
                ),
            )
            c.execute("UPDATE bank_accounts SET exchange_state='queued', external_sync_id='' WHERE id=?", (bank_account_id,))
            conn.commit()
            conn.close()

            retry_failed = self.client.post("/api/nsi/master_data/bank_accounts/sync_failed")
            self.assertEqual(retry_failed.status_code, 200)
            self.assertEqual(retry_failed.json()["status"], "success")
            self.assertGreaterEqual(int(retry_failed.json()["queued"]), 1)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if bank_account_id:
                c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='bank_accounts' AND entity_id=?)", (bank_account_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='bank_accounts' AND entity_id=?", (bank_account_id,))
            if position_id:
                c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='positions' AND entity_id=?)", (position_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='positions' AND entity_id=?", (position_id,))
            c.execute("DELETE FROM bank_accounts WHERE id=?", (bank_account_id,))
            c.execute("DELETE FROM financial_responsibility_centers WHERE id=?", (frc_id,))
            c.execute("DELETE FROM operation_types WHERE id=?", (operation_type_id,))
            c.execute("DELETE FROM storage_cells WHERE id=?", (storage_cell_id,))
            c.execute("DELETE FROM nomenclature_characteristics WHERE id=?", (characteristic_id,))
            c.execute("DELETE FROM employee_master WHERE id=?", (employee_id,))
            c.execute("DELETE FROM position_master WHERE id=?", (position_id,))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_inventory_documents_posting_flow(self):
        director = create_test_user(role="Директор", name_prefix="Stock Docs Director")
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(self.client.post("/api/nomenclature", json={
                "name": "QA Inventory Item",
                "article": "QA-INV-ITEM",
                "unit": "шт",
                "price": 100,
                "stock": 0,
                "currency": "RUB",
                "group_name": "Материалы",
                "default_warehouse": "Основной склад",
            }).status_code, 200)

            receipt = self.client.post("/api/stock/documents", json={
                "doc_type": "receipt_adjustment",
                "article": "QA-INV-ITEM",
                "qty": 10,
                "warehouse": "Основной склад",
                "bin_code": "A-01",
                "reason": "Стартовый приход",
            })
            self.assertEqual(receipt.status_code, 200)
            self.assertEqual(receipt.json()["status"], "success")

            transfer = self.client.post("/api/stock/documents", json={
                "doc_type": "transfer",
                "article": "QA-INV-ITEM",
                "qty": 4,
                "warehouse": "Основной склад",
                "bin_code": "A-01",
                "target_warehouse": "Монтаж",
                "target_bin": "M-01",
                "reason": "Передача в монтаж",
            })
            self.assertEqual(transfer.status_code, 200)

            inventory = self.client.post("/api/stock/documents", json={
                "doc_type": "inventory",
                "article": "QA-INV-ITEM",
                "warehouse": "Монтаж",
                "bin_code": "M-01",
                "counted_qty": 3,
                "reason": "Инвентаризация монтажа",
            })
            self.assertEqual(inventory.status_code, 200)

            documents = self.client.get("/api/stock/documents?limit=20")
            self.assertEqual(documents.status_code, 200)
            doc_rows = documents.json()
            self.assertGreaterEqual(len([row for row in doc_rows if row["article"] == "QA-INV-ITEM"]), 3)

            balances = self.client.get("/api/stock/balances?article=QA-INV-ITEM")
            self.assertEqual(balances.status_code, 200)
            grouped = {(row["warehouse"], row["bin_code"]): float(row["qty"]) for row in balances.json()}
            self.assertAlmostEqual(grouped.get(("Основной склад", "A-01"), 0.0), 6.0)
            self.assertAlmostEqual(grouped.get(("Монтаж", "M-01"), 0.0), 3.0)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT stock FROM nomenclature WHERE article='QA-INV-ITEM'")
            self.assertAlmostEqual(float(c.fetchone()[0]), 9.0)
            conn.close()
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM integration_sync_log WHERE entity_type='nomenclature' AND entity_id IN (SELECT id FROM nomenclature WHERE article='QA-INV-ITEM')")
            c.execute("DELETE FROM integration_sync_queue WHERE entity_type='nomenclature' AND entity_id IN (SELECT id FROM nomenclature WHERE article='QA-INV-ITEM')")
            c.execute("DELETE FROM stock_movements WHERE article='QA-INV-ITEM'")
            c.execute("DELETE FROM inventory_documents WHERE article='QA-INV-ITEM'")
            c.execute("DELETE FROM inventory_balances WHERE article='QA-INV-ITEM'")
            c.execute("DELETE FROM inventory_lots WHERE article='QA-INV-ITEM'")
            c.execute("DELETE FROM nomenclature WHERE article='QA-INV-ITEM'")
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_production_bom_routes_and_executive_snapshot(self):
        director = create_test_user(role="Директор", name_prefix="Prod ERP Director")
        order_id = 0
        bom_id = 0
        route_id = 0
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            self.assertEqual(self.client.post("/api/nomenclature", json={
                "name": "QA BOM Item",
                "article": "QA-BOM-ITEM",
                "unit": "шт",
                "price": 250,
                "stock": 0,
                "currency": "RUB",
                "group_name": "Материалы",
                "default_warehouse": "Основной склад",
            }).status_code, 200)

            created_order = self.client.post("/api/production/orders", json={
                "project_id": 0, "client_id": 0, "order_name": "QA Production ERP",
                "stage": "queue", "priority": "high", "planned_start": "13.04.2026", "planned_finish": "15.04.2026",
                "actual_finish": "", "progress": 0, "responsible": "QA Chief", "route_name": "Шкафы", "planned_qty": 10,
                "produced_qty": 0, "scrap_qty": 0, "planned_cost": 0, "actual_cost": 0, "labor_hours_plan": 0, "labor_hours_fact": 0, "comment": ""
            })
            self.assertEqual(created_order.status_code, 200)
            order_id = int(created_order.json()["id"])

            created_bom = self.client.post("/api/production/bom", json={
                "order_id": order_id,
                "article": "QA-BOM-ITEM",
                "item_name": "QA BOM Item",
                "unit": "шт",
                "qty_per_unit": 2,
                "planned_qty": 20,
                "actual_qty": 18,
                "unit_cost": 250,
                "warehouse": "Основной склад",
                "bin_code": "A-01",
                "note": "Материал заказа",
            })
            self.assertEqual(created_bom.status_code, 200)
            bom_id = int(created_bom.json()["id"])

            created_route = self.client.post("/api/production/routes", json={
                "order_id": order_id,
                "sequence_no": 1,
                "operation_name": "Лазерная резка",
                "work_center": "Цех раскроя",
                "planned_hours": 6,
                "planned_qty": 10,
                "labor_rate": 700,
                "note": "Старт маршрута",
            })
            self.assertEqual(created_route.status_code, 200)
            route_id = int(created_route.json()["id"])

            applied = self.client.post(f"/api/production/orders/{order_id}/apply_route")
            self.assertEqual(applied.status_code, 200)
            self.assertEqual(applied.json()["status"], "success")
            self.assertEqual(applied.json()["created"], 1)

            bom_rows = self.client.get(f"/api/production/bom?order_id={order_id}")
            self.assertEqual(bom_rows.status_code, 200)
            self.assertEqual(len(bom_rows.json()), 1)
            self.assertAlmostEqual(float(bom_rows.json()[0]["planned_cost"]), 5000.0)

            route_rows = self.client.get(f"/api/production/routes?order_id={order_id}")
            self.assertEqual(route_rows.status_code, 200)
            self.assertEqual(len(route_rows.json()), 1)

            operations = self.client.get(f"/api/production/operations?order_id={order_id}")
            self.assertEqual(operations.status_code, 200)
            self.assertEqual(len(operations.json()), 1)

            summary = self.client.get("/api/production/summary")
            self.assertEqual(summary.status_code, 200)
            self.assertGreaterEqual(summary.json()["metrics"]["bom_items_total"], 1)
            self.assertGreaterEqual(summary.json()["metrics"]["route_templates_total"], 1)

            discrepancy = self.client.post("/api/stock/documents", json={
                "doc_type": "inventory",
                "article": "QA-BOM-ITEM",
                "warehouse": "Основной склад",
                "bin_code": "A-01",
                "counted_qty": 2,
                "reason": "Контрольный пересчёт",
            })
            self.assertEqual(discrepancy.status_code, 200)

            executive = self.client.get("/api/executive/summary")
            self.assertEqual(executive.status_code, 200)
            payload = executive.json()
            self.assertIn("production_bottlenecks", payload)
            self.assertIn("inventory_discrepancies", payload)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if route_id:
                c.execute("DELETE FROM production_route_templates WHERE id=?", (route_id,))
            if bom_id:
                c.execute("DELETE FROM production_bom_items WHERE id=?", (bom_id,))
            if order_id:
                c.execute("DELETE FROM production_operations WHERE order_id=?", (order_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='production_order' AND entity_id=?", (order_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='production_order' AND entity_id=?", (order_id,))
                c.execute("DELETE FROM production_orders WHERE id=?", (order_id,))
            c.execute("DELETE FROM inventory_documents WHERE article='QA-BOM-ITEM'")
            c.execute("DELETE FROM stock_movements WHERE article='QA-BOM-ITEM'")
            c.execute("DELETE FROM inventory_balances WHERE article='QA-BOM-ITEM'")
            c.execute("DELETE FROM inventory_lots WHERE article='QA-BOM-ITEM'")
            c.execute("DELETE FROM nomenclature WHERE article='QA-BOM-ITEM'")
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_production_deep_summary_exposes_wip_shift_norm_fact_and_change_log(self):
        director = create_test_user(role="Директор", name_prefix="Prod Deep Director")
        order_id = 0
        route_id = 0
        shift_id = 0
        job_id = 0
        material_norm_id = 0
        labor_norm_id = 0
        operation_id = 0
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            created_order = self.client.post("/api/production/orders", json={
                "project_id": 0,
                "client_id": 0,
                "order_name": "QA Deep Flow",
                "stage": "in_work",
                "priority": "critical",
                "planned_start": "14.04.2026",
                "planned_finish": "16.04.2026",
                "actual_finish": "",
                "progress": 35,
                "responsible": "QA Shift Lead",
                "route_name": "Цех раскроя",
                "planned_qty": 12,
                "produced_qty": 4,
                "scrap_qty": 1,
                "planned_cost": 12000,
                "actual_cost": 13600,
                "labor_hours_plan": 10,
                "labor_hours_fact": 6,
                "comment": "Контроль WIP",
            })
            self.assertEqual(created_order.status_code, 200)
            order_id = int(created_order.json()["id"])

            created_route = self.client.post("/api/production/routes", json={
                "order_id": order_id,
                "sequence_no": 1,
                "operation_name": "Резка профиля",
                "work_center": "Цех раскроя",
                "planned_hours": 4,
                "planned_qty": 12,
                "labor_rate": 650,
                "note": "Старт маршрута",
            })
            self.assertEqual(created_route.status_code, 200)
            route_id = int(created_route.json()["id"])

            applied = self.client.post(f"/api/production/orders/{order_id}/apply_route")
            self.assertEqual(applied.status_code, 200)
            self.assertEqual(applied.json()["created"], 1)

            operations = self.client.get(f"/api/production/operations?order_id={order_id}")
            self.assertEqual(operations.status_code, 200)
            self.assertTrue(operations.json())
            operation_id = int(operations.json()[0]["id"])

            updated_operation = self.client.put(f"/api/production/operations/{operation_id}", json={
                "order_id": order_id,
                "sequence_no": 1,
                "operation_name": "Резка профиля",
                "work_center": "Цех раскроя",
                "status": "in_progress",
                "planned_hours": 4,
                "actual_hours": 5.5,
                "planned_qty": 12,
                "completed_qty": 5,
                "scrap_qty": 1,
                "labor_rate": 650,
                "material_cost": 1800,
                "overhead_cost": 420,
                "started_at": "14.04.2026 08:00",
                "finished_at": "",
                "note": "Идёт первая смена",
            })
            self.assertEqual(updated_operation.status_code, 200)

            created_shift = self.client.post("/api/production/shifts/deep", json={
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "shift_date": "14.04.2026",
                "shift_name": "Смена А",
                "work_center": "Цех раскроя",
                "capacity_hours": 8,
                "team_name": "Бригада 1",
                "supervisor_name": "QA Shift Lead",
                "status": "active",
                "comment": "Рабочая смена",
            })
            self.assertEqual(created_shift.status_code, 200)
            shift_id = int(created_shift.json()["id"])

            created_job = self.client.post("/api/production/jobs/deep", json={
                "order_id": order_id,
                "shift_id": shift_id,
                "operation_id": operation_id,
                "title": "Резка первой партии",
                "work_center": "Цех раскроя",
                "executor_name": "QA Operator",
                "planned_qty": 12,
                "completed_qty": 5,
                "status": "in_progress",
                "started_at": "14.04.2026 08:00",
                "finished_at": "",
                "comment": "В работе",
            })
            self.assertEqual(created_job.status_code, 200)
            job_id = int(created_job.json()["id"])

            created_material_norm = self.client.post("/api/production/material_norms/deep", json={
                "order_id": order_id,
                "article": "QA-MAT-001",
                "item_name": "Профиль",
                "unit": "шт",
                "norm_qty": 24,
                "scrap_rate": 0.05,
                "substitute_article": "",
                "comment": "Норма профиля",
            })
            self.assertEqual(created_material_norm.status_code, 200)
            material_norm_id = int(created_material_norm.json()["id"])

            created_labor_norm = self.client.post("/api/production/labor_norms/deep", json={
                "order_id": order_id,
                "operation_name": "Резка профиля",
                "work_center": "Цех раскроя",
                "norm_hours": 4,
                "rate_per_hour": 650,
                "team_size": 2,
                "comment": "Норма трудозатрат",
            })
            self.assertEqual(created_labor_norm.status_code, 200)
            labor_norm_id = int(created_labor_norm.json()["id"])

            deep = self.client.get("/api/production/deep_summary")
            self.assertEqual(deep.status_code, 200)
            payload = deep.json()
            self.assertIn("wip_board", payload)
            self.assertIn("shift_board", payload)
            self.assertIn("order_timelines", payload)
            self.assertIn("norm_fact_board", payload)
            self.assertIn("change_log", payload)
            self.assertTrue(any(int(item["order_id"]) == order_id for item in payload["wip_board"]["in_work"]))
            self.assertTrue(any(item["work_center"] == "Цех раскроя" for item in payload["shift_board"]))
            self.assertTrue(any(int(item["order_id"]) == order_id for item in payload["order_timelines"]))
            self.assertTrue(any(int(item["order_id"]) == order_id for item in payload["norm_fact_board"]))
            self.assertTrue(any(item["entity_type"] in {"production_order", "production_operation", "production_job"} for item in payload["change_log"]))
        finally:
            conn = get_connection()
            c = conn.cursor()
            if job_id:
                c.execute("DELETE FROM production_jobs WHERE id=?", (job_id,))
            if shift_id:
                c.execute("DELETE FROM production_shifts WHERE id=?", (shift_id,))
            if material_norm_id:
                c.execute("DELETE FROM production_material_norms WHERE id=?", (material_norm_id,))
            if labor_norm_id:
                c.execute("DELETE FROM production_labor_norms WHERE id=?", (labor_norm_id,))
            if route_id:
                c.execute("DELETE FROM production_route_templates WHERE id=?", (route_id,))
            if operation_id:
                c.execute("DELETE FROM production_operations WHERE id=?", (operation_id,))
            if order_id:
                c.execute("DELETE FROM production_orders WHERE id=?", (order_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='production_order' AND entity_id=?", (order_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='production_order' AND entity_id=?", (order_id,))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_finance_scope_sessions_and_field_change_audit(self):
        director = create_test_user(role="Директор", name_prefix="Security Director")
        manager = create_test_user(role="Менеджер", name_prefix="Scoped Manager")
        director_client = TestClient(app)
        manager_client = TestClient(app)
        new_legal_entity_id = 0
        new_business_unit_id = 0
        payment_allowed_id = 0
        payment_blocked_id = 0
        try:
            login_director = director_client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login_director.status_code, 200)

            master_data = director_client.get("/api/finance/master_data")
            self.assertEqual(master_data.status_code, 200)
            payload = master_data.json()
            default_legal = int(payload["legal_entities"][0]["id"])
            default_bu = int(payload["business_units"][0]["id"])

            created_le = director_client.post("/api/finance/master_data/legal_entities", json={
                "name": "QA Scoped LE",
                "short_name": "QAScope",
                "inn": "7700000001",
                "kpp": "770001001",
                "ogrn": "1247700000001",
                "vat_mode": "osno",
                "default_currency": "RUB",
                "is_active": 1,
            })
            self.assertEqual(created_le.status_code, 200)
            new_legal_entity_id = int(created_le.json()["id"])

            created_bu = director_client.post("/api/finance/master_data/business_units", json={
                "legal_entity_id": new_legal_entity_id,
                "name": "QA Scoped BU",
                "code": "QA-BU",
                "manager_name": director["name"],
                "is_active": 1,
            })
            self.assertEqual(created_bu.status_code, 200)
            new_business_unit_id = int(created_bu.json()["id"])

            created_allowed = director_client.post("/api/finance/payments", json={
                "title": "QA Scope Allowed",
                "kind": "incoming",
                "category": "payment",
                "amount": 11111,
                "currency": "RUB",
                "status": "planned",
                "due_date": "15.04.2026",
                "legal_entity_id": new_legal_entity_id,
                "business_unit_id": new_business_unit_id,
            })
            self.assertEqual(created_allowed.status_code, 200)
            payment_allowed_id = int(created_allowed.json()["id"])

            created_blocked = director_client.post("/api/finance/payments", json={
                "title": "QA Scope Blocked",
                "kind": "incoming",
                "category": "payment",
                "amount": 22222,
                "currency": "RUB",
                "status": "planned",
                "due_date": "15.04.2026",
                "legal_entity_id": default_legal,
                "business_unit_id": default_bu,
            })
            self.assertEqual(created_blocked.status_code, 200)
            payment_blocked_id = int(created_blocked.json()["id"])

            updated_scope = director_client.put("/api/users/access_scope", json={
                "email": manager["email"],
                "allowed_legal_entities": [new_legal_entity_id],
                "allowed_business_units": [new_business_unit_id],
                "two_factor_enabled": 1,
            })
            self.assertEqual(updated_scope.status_code, 200)
            self.assertEqual(updated_scope.json()["status"], "success")

            director_sessions = director_client.get("/api/users/sessions?limit=80")
            self.assertEqual(director_sessions.status_code, 200)
            self.assertTrue(any(item["user_email"] == director["email"] for item in director_sessions.json()))

            login_manager = manager_client.post("/api/login", json={"email": manager["email"], "password": manager["password"]})
            self.assertEqual(login_manager.status_code, 200)

            manager_permissions = manager_client.get("/api/permissions")
            self.assertEqual(manager_permissions.status_code, 200)
            self.assertIn(new_legal_entity_id, manager_permissions.json()["scope"]["legal_entities"])
            self.assertEqual(manager_permissions.json()["two_factor_enabled"], 1)

            manager_payments = manager_client.get("/api/finance/payments")
            self.assertEqual(manager_payments.status_code, 200)
            manager_titles = {item["title"] for item in manager_payments.json()}
            self.assertIn("QA Scope Allowed", manager_titles)
            self.assertNotIn("QA Scope Blocked", manager_titles)

            manager_summary = manager_client.get("/api/finance/summary")
            self.assertEqual(manager_summary.status_code, 200)
            self.assertAlmostEqual(float(manager_summary.json()["metrics"]["incoming_open"]), 11111.0)

            field_changes = director_client.get("/api/audit/field_changes?entity_type=user&entity_id=" + manager["email"])
            self.assertEqual(field_changes.status_code, 200)
            self.assertTrue(any(item["field_name"] == "allowed_legal_entities" for item in field_changes.json()))

            refreshed_sessions = director_client.get("/api/users/sessions?limit=80")
            self.assertEqual(refreshed_sessions.status_code, 200)
            manager_session = next(item for item in refreshed_sessions.json() if item["user_email"] == manager["email"])

            revoke_res = director_client.post("/api/users/sessions/revoke", json={
                "session_id": manager_session["session_id"],
                "user_email": manager["email"],
            })
            self.assertEqual(revoke_res.status_code, 200)
            self.assertEqual(revoke_res.json()["status"], "success")

            manager_session_after = manager_client.get("/api/session")
            self.assertEqual(manager_session_after.status_code, 200)
            self.assertEqual(manager_session_after.json()["error"], "unauthorized")
        finally:
            conn = get_connection()
            c = conn.cursor()
            if payment_allowed_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_allowed_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (payment_allowed_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_allowed_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_allowed_id,))
            if payment_blocked_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_blocked_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (payment_blocked_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_blocked_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_blocked_id,))
            if new_business_unit_id:
                c.execute("DELETE FROM business_units WHERE id=?", (new_business_unit_id,))
            if new_legal_entity_id:
                c.execute("DELETE FROM legal_entities WHERE id=?", (new_legal_entity_id,))
            c.execute("DELETE FROM field_change_log WHERE entity_type='user' AND entity_id=?", (manager["email"],))
            conn.commit()
            conn.close()
            delete_test_user(manager["email"])
            delete_test_user(director["email"])

    def test_form_policy_endpoint_returns_centralized_payload(self):
        manager = create_test_user(role="Менеджер", name_prefix="Policy Manager")
        client = TestClient(app)
        rule_id = 0
        try:
            login_res = client.post("/api/login", json={"email": manager["email"], "password": manager["password"]})
            self.assertEqual(login_res.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            now = int(time.time())
            c.execute(
                """
                INSERT INTO field_access_rules (
                    role_name, module_name, entity_type, field_name, can_view, can_edit, allowed_statuses,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                ("Менеджер", "sales", "sales_document", "status", 1, 1, json.dumps(["draft", "issued"], ensure_ascii=False), now, now),
            )
            rule_id = int(c.lastrowid)
            conn.commit()
            conn.close()

            payload = client.get("/api/permissions/forms/sales/sales_document")
            self.assertEqual(payload.status_code, 200)
            data = payload.json()
            self.assertEqual(data["module"], "sales")
            self.assertEqual(data["entity_type"], "sales_document")
            self.assertIn("status", data["fields"])
            self.assertEqual(data["restricted_status_fields"]["status"], ["draft", "issued"])
            self.assertIn("Разрешённые статусы", data["messages"]["status"])
        finally:
            conn = get_connection()
            c = conn.cursor()
            if rule_id:
                c.execute("DELETE FROM field_access_rules WHERE id=?", (rule_id,))
            conn.commit()
            conn.close()
            delete_test_user(manager["email"])

    def test_2fa_operations_center_and_security_endpoints(self):
        director = create_test_user(role="Директор", name_prefix="Ops Director")
        bank_account_id = 0
        statement_line_id = 0
        telephony_account_id = 0
        telephony_call_id = 0
        report_id = 0
        lock_session = ""
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            setup = self.client.get("/api/users/2fa/setup")
            self.assertEqual(setup.status_code, 200)
            secret = setup.json()["secret"]
            otp_code = _totp_code(secret)

            enable = self.client.post("/api/users/2fa/enable", json={"otp_code": otp_code})
            self.assertEqual(enable.status_code, 200)
            self.assertEqual(enable.json()["status"], "success")

            second_client = TestClient(app)
            login_without_otp = second_client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login_without_otp.status_code, 200)
            self.assertTrue(login_without_otp.json()["two_factor_required"])

            login_with_otp = second_client.post("/api/login", json={
                "email": director["email"],
                "password": director["password"],
                "otp_code": _totp_code(secret),
            })
            self.assertEqual(login_with_otp.status_code, 200)
            self.assertEqual(login_with_otp.json()["email"], director["email"])

            rule_create = self.client.post("/api/users/field_rules", json={
                "role": "Бухгалтерия",
                "module": "finance",
                "entity_type": "finance_payment",
                "field_name": "amount",
                "can_view": 1,
                "can_edit": 0,
                "allowed_statuses": ["planned", "issued"],
                "is_active": 1,
            })
            self.assertEqual(rule_create.status_code, 200)
            rule_id = int(rule_create.json()["id"])

            rules = self.client.get("/api/users/field_rules?role=Бухгалтерия")
            self.assertEqual(rules.status_code, 200)
            self.assertTrue(any(int(item["id"]) == rule_id for item in rules.json()))

            bank = self.client.post("/api/banking/accounts", json={
                "name": "QA Operations Account",
                "bank_name": "QA Bank",
                "account_number": "40702810000000000001",
                "bik": "044525225",
                "currency": "RUB",
                "legal_entity_id": 0,
                "is_active": 1,
            })
            self.assertEqual(bank.status_code, 200)
            bank_account_id = int(bank.json()["id"])

            imported = self.client.post("/api/banking/statements/import", json={
                "bank_account_id": bank_account_id,
                "lines": [{
                    "line_date": "13.04.2026",
                    "amount": 12345,
                    "direction": "incoming",
                    "counterparty": "QA Counterparty",
                    "purpose": "Ops test import",
                    "client_id": 0,
                    "payment_id": 0,
                    "external_line_id": "QA-LINE-001",
                    "comment": "Imported by test",
                }],
            })
            self.assertEqual(imported.status_code, 200)
            self.assertEqual(imported.json()["created"], 1)
            statement_line_id = int(imported.json()["ids"][0])

            telephony_account = self.client.post("/api/telephony/accounts", json={
                "provider_name": "Mango",
                "line_name": "Sales desk",
                "external_line_id": "QA-LINE",
                "is_active": 1,
            })
            self.assertEqual(telephony_account.status_code, 200)
            telephony_account_id = int(telephony_account.json()["id"])

            telephony_call = self.client.post("/api/telephony/calls", json={
                "account_id": telephony_account_id,
                "contact_name": "QA Caller",
                "phone_number": "+79990001122",
                "direction": "inbound",
                "status": "missed",
                "duration_sec": 0,
                "summary": "Нужно перезвонить",
            })
            self.assertEqual(telephony_call.status_code, 200)
            telephony_call_id = int(telephony_call.json()["id"])

            report = self.client.post("/api/analytics/reports", json={
                "report_type": "operations_monitoring",
                "title": "QA Ops Report",
                "filters": {},
                "layout": {},
                "scope": "private",
            })
            self.assertEqual(report.status_code, 200)
            report_id = int(report.json()["id"])

            report_run = self.client.post(f"/api/analytics/reports/{report_id}/run")
            self.assertEqual(report_run.status_code, 200)
            self.assertEqual(report_run.json()["status"], "success")

            lock = self.client.post("/api/locks/acquire", json={
                "entity_type": "finance_payment",
                "entity_id": "qa-ops-lock",
                "force": 0,
            })
            self.assertEqual(lock.status_code, 200)
            self.assertEqual(lock.json()["status"], "success")
            lock_session = lock.json().get("session_id", "")

            locks = self.client.get("/api/locks")
            self.assertEqual(locks.status_code, 200)
            self.assertTrue(any(item["entity_id"] == "qa-ops-lock" for item in locks.json()))

            reconciliation = self.client.post("/api/integration/1c/reconciliation/run")
            self.assertEqual(reconciliation.status_code, 200)
            self.assertEqual(reconciliation.json()["status"], "success")

            monitoring = self.client.get("/api/operations/monitoring")
            self.assertEqual(monitoring.status_code, 200)
            payload = monitoring.json()
            self.assertIn("integration", payload)
            self.assertIn("locks", payload)
            self.assertIn("bank_unreconciled", payload)
            self.assertIn("missed_calls", payload)
            self.assertIn("reliability", payload)
            self.assertTrue(any(item["id"] == statement_line_id for item in payload["bank_unreconciled"]))
            self.assertTrue(any(item["id"] == telephony_call_id for item in payload["missed_calls"]))

            released = self.client.post("/api/locks/release", json={
                "entity_type": "finance_payment",
                "entity_id": "qa-ops-lock",
                "force": 1,
            })
            self.assertEqual(released.status_code, 200)
            self.assertEqual(released.json()["status"], "success")

            delete_rule = self.client.delete(f"/api/users/field_rules/{rule_id}")
            self.assertEqual(delete_rule.status_code, 200)

            disable = self.client.post("/api/users/2fa/disable", json={"otp_code": _totp_code(secret)})
            self.assertEqual(disable.status_code, 200)
            self.assertEqual(disable.json()["status"], "success")
        finally:
            conn = get_connection()
            c = conn.cursor()
            if lock_session:
                c.execute("DELETE FROM entity_edit_locks WHERE session_id=?", (lock_session,))
            c.execute("DELETE FROM entity_edit_locks WHERE entity_type='finance_payment' AND entity_id='qa-ops-lock'")
            if report_id:
                c.execute("DELETE FROM saved_reports WHERE id=?", (report_id,))
            if telephony_call_id:
                c.execute("DELETE FROM notifications WHERE entity_type='telephony_call' AND entity_id=?", (str(telephony_call_id),))
                c.execute("DELETE FROM audit_log WHERE entity_type='telephony_call' AND entity_id=?", (str(telephony_call_id),))
                c.execute("DELETE FROM telephony_calls WHERE id=?", (telephony_call_id,))
            if telephony_account_id:
                c.execute("DELETE FROM audit_log WHERE entity_type='telephony_account' AND entity_id=?", (str(telephony_account_id),))
                c.execute("DELETE FROM telephony_accounts WHERE id=?", (telephony_account_id,))
            if statement_line_id:
                c.execute("DELETE FROM audit_log WHERE entity_type='bank_statement_line' AND entity_id=?", (str(statement_line_id),))
                c.execute("DELETE FROM bank_statement_lines WHERE id=?", (statement_line_id,))
            if bank_account_id:
                c.execute("DELETE FROM audit_log WHERE entity_type='bank_account' AND entity_id=?", (str(bank_account_id),))
                c.execute("DELETE FROM bank_accounts WHERE id=?", (bank_account_id,))
            c.execute("DELETE FROM integration_reconciliation_runs WHERE created_by=?", (director["email"],))
            c.execute("DELETE FROM field_access_rules WHERE created_by=?", (director["email"],))
            c.execute("UPDATE users SET two_factor_enabled=0, two_factor_secret='' WHERE email=?", (director["email"],))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_security_guard_and_form_policy_matrix(self):
        director = create_test_user(role="Директор", name_prefix="Security Director")
        manager = create_test_user(role="Менеджер", name_prefix="Security Manager")
        try:
            login_director = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login_director.status_code, 200)

            field_rule = self.client.post("/api/users/field_rules", json={
                "role": "Менеджер",
                "module": "accounting",
                "entity_type": "epl_waybill",
                "field_name": "status",
                "can_view": 1,
                "can_edit": 1,
                "allowed_statuses": ["draft", "ready"],
                "is_active": 1,
            })
            self.assertEqual(field_rule.status_code, 200)

            action_policy = self.client.post("/api/security/action_policies", json={
                "role_name": "Менеджер",
                "module_name": "sales",
                "entity_type": "sales_document",
                "action_name": "delete",
                "status_name": "",
                "allow_execute": 0,
                "require_2fa": 0,
                "require_reason": 0,
                "is_active": 1,
            })
            self.assertEqual(action_policy.status_code, 200)

            danger_rule = self.client.post("/api/security/danger_rules", json={
                "module_name": "supply",
                "entity_type": "purchase_order",
                "action_name": "delete",
                "risk_level": "high",
                "require_2fa": 0,
                "require_reason": 1,
                "blocked_roles": [],
                "is_active": 1,
                "comment": "Need reason",
            })
            self.assertEqual(danger_rule.status_code, 200)

            manager_client = TestClient(app)
            login_manager = manager_client.post("/api/login", json={"email": manager["email"], "password": manager["password"]})
            self.assertEqual(login_manager.status_code, 200)

            form_payload = manager_client.get("/api/permissions/forms/accounting/epl_waybill")
            self.assertEqual(form_payload.status_code, 200)
            form_json = form_payload.json()
            self.assertIn("status", form_json["restricted_status_fields"])
            self.assertIn("status", form_json["status_fields"])
            self.assertEqual(form_json["restricted_status_fields"]["status"], ["draft", "ready"])

            blocked_delete = manager_client.post("/api/security/guard/check", json={
                "module_name": "sales",
                "entity_type": "sales_document",
                "action_name": "delete",
            })
            self.assertEqual(blocked_delete.status_code, 200)
            self.assertEqual(blocked_delete.json()["error"], "policy_blocked")

            reason_required = manager_client.post("/api/security/guard/check", json={
                "module_name": "supply",
                "entity_type": "purchase_order",
                "action_name": "delete",
            })
            self.assertEqual(reason_required.status_code, 200)
            self.assertEqual(reason_required.json()["error"], "reason_required")

            allowed_with_reason = manager_client.post("/api/security/guard/check", json={
                "module_name": "supply",
                "entity_type": "purchase_order",
                "action_name": "delete",
                "reason": "Удаление ошибочного дубля",
            })
            self.assertEqual(allowed_with_reason.status_code, 200)
            self.assertEqual(allowed_with_reason.json()["status"], "allow")

            security_summary = self.client.get("/api/security/plus_summary")
            self.assertEqual(security_summary.status_code, 200)
            summary_json = security_summary.json()
            self.assertGreaterEqual(int(summary_json["metrics"]["field_rules_total"]), 1)
            self.assertGreaterEqual(int(summary_json["metrics"]["matrix_rows_total"]), 1)
            self.assertTrue(any(
                item["role_name"] == "Менеджер" and item["module_name"] == "accounting" and int(item["status_rules_total"] or 0) >= 1
                for item in summary_json["policy_matrix"]
            ))
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM security_action_policies WHERE created_by=?", (director["email"],))
            c.execute("DELETE FROM security_danger_rules WHERE created_by=?", (director["email"],))
            c.execute("DELETE FROM field_access_rules WHERE created_by=?", (director["email"],))
            conn.commit()
            conn.close()
            delete_test_user(manager["email"])
            delete_test_user(director["email"])

    def test_deep_analytics_and_reliability_reports(self):
        director = create_test_user(role="Директор", name_prefix="Analytics Director")
        analytics_report_id = 0
        reliability_report_id = 0
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            analytics = self.client.get("/api/analytics/deep")
            self.assertEqual(analytics.status_code, 200)
            analytics_payload = analytics.json()
            self.assertIn("by_client", analytics_payload)
            self.assertIn("by_product", analytics_payload)
            self.assertIn("inventory_turnover", analytics_payload)
            self.assertIn("sla_summary", analytics_payload)
            self.assertIn("budget_plan_fact", analytics_payload)
            self.assertIn("production_plan_fact", analytics_payload)
            self.assertIn("purchase_plan_fact", analytics_payload)

            reliability = self.client.get("/api/system/reliability")
            self.assertEqual(reliability.status_code, 200)
            reliability_payload = reliability.json()
            self.assertIn("module_health", reliability_payload)
            self.assertIn("integrity_issues", reliability_payload)
            self.assertIn("recovery", reliability_payload)

            analytics_report = self.client.post("/api/analytics/reports", json={
                "report_type": "analytics_deep",
                "title": "QA Deep Analytics",
                "filters": {},
                "layout": {},
                "scope": "private",
            })
            self.assertEqual(analytics_report.status_code, 200)
            analytics_report_id = int(analytics_report.json()["id"])

            reliability_report = self.client.post("/api/analytics/reports", json={
                "report_type": "reliability_dashboard",
                "title": "QA Reliability",
                "filters": {},
                "layout": {},
                "scope": "private",
            })
            self.assertEqual(reliability_report.status_code, 200)
            reliability_report_id = int(reliability_report.json()["id"])

            analytics_run = self.client.post(f"/api/analytics/reports/{analytics_report_id}/run")
            self.assertEqual(analytics_run.status_code, 200)
            self.assertEqual(analytics_run.json()["status"], "success")
            self.assertIn("by_client", analytics_run.json()["payload"])

            reliability_run = self.client.post(f"/api/analytics/reports/{reliability_report_id}/run")
            self.assertEqual(reliability_run.status_code, 200)
            self.assertEqual(reliability_run.json()["status"], "success")
            self.assertIn("module_health", reliability_run.json()["payload"])

            delete_reliability = self.client.delete(f"/api/analytics/reports/{reliability_report_id}")
            self.assertEqual(delete_reliability.status_code, 200)
            self.assertEqual(delete_reliability.json()["status"], "success")
            reliability_report_id = 0

            reports_after_delete = self.client.get("/api/analytics/reports")
            self.assertEqual(reports_after_delete.status_code, 200)
            self.assertFalse(any(int(item["id"]) == int(delete_reliability.json()["id"]) for item in reports_after_delete.json()))
        finally:
            conn = get_connection()
            c = conn.cursor()
            if analytics_report_id:
                c.execute("DELETE FROM saved_reports WHERE id=?", (analytics_report_id,))
            if reliability_report_id:
                c.execute("DELETE FROM saved_reports WHERE id=?", (reliability_report_id,))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_system_runtime_and_recovery_workflow(self):
        director = create_test_user(role="Директор", name_prefix="Runtime Director")
        stale_entity_id = f"runtime-lock-{int(time.time())}"
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO entity_edit_locks (entity_type, entity_id, actor_email, actor_name, session_id, locked_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("finance_payment", stale_entity_id, director["email"], director["name"], "stale-session", int(time.time()) - 7200),
            )
            conn.commit()
            conn.close()

            runtime = self.client.get("/api/system/runtime")
            self.assertEqual(runtime.status_code, 200)
            runtime_payload = runtime.json()
            self.assertIn("database", runtime_payload)
            self.assertIn("background_jobs", runtime_payload)
            self.assertIn("recovery_runs", runtime_payload)
            self.assertIn("lock_policies", runtime_payload)

            recovery = self.client.post(
                "/api/system/recovery/run",
                json={"action_name": "release_stale_locks", "older_than_minutes": 15, "stale_only": 1},
            )
            self.assertEqual(recovery.status_code, 200)
            recovery_payload = recovery.json()
            self.assertEqual(recovery_payload["status"], "success")
            self.assertGreaterEqual(int(recovery_payload.get("affected", 0)), 1)

            runtime_after = self.client.get("/api/system/runtime")
            self.assertEqual(runtime_after.status_code, 200)
            self.assertTrue(any(item["action_name"] == "release_stale_locks" for item in runtime_after.json().get("recovery_runs", [])))

            events = self.client.get("/api/system/events?limit=20")
            self.assertEqual(events.status_code, 200)
            self.assertTrue(isinstance(events.json(), list))

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM entity_edit_locks WHERE entity_id=?", (stale_entity_id,))
            remaining = c.fetchone()[0]
            conn.close()
            self.assertEqual(remaining, 0)
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM entity_edit_locks WHERE entity_id=?", (stale_entity_id,))
            c.execute("DELETE FROM recovery_workflow_runs WHERE actor_email=?", (director["email"],))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_analytics_dashboard_hub_and_drilldown(self):
        director = create_test_user(role="Директор", name_prefix="BI Director")
        client_id = 0
        payment_id = 0
        dashboard_report_id = 0
        drill_report_id = 0
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            client_name = f"QA BI Client {os.getpid()}"
            created_client = self.client.post("/api/clients", json={"name": client_name, "inn": "7711999000", "contact": "bi@example.com"})
            self.assertEqual(created_client.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
            client_id = int(c.fetchone()[0])
            conn.close()

            payment = self.client.post("/api/finance/payments", json={
                "project_id": 0,
                "client_id": client_id,
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "treasury_article_id": 0,
                "vat_rate_id": 0,
                "source_document_type": "",
                "source_document_id": 0,
                "title": "QA BI Incoming",
                "kind": "incoming",
                "category": "payment",
                "amount": 125000,
                "currency": "RUB",
                "due_date": "15.04.2026",
                "paid_date": "",
                "status": "planned",
                "comment": "BI drilldown source",
            })
            self.assertEqual(payment.status_code, 200)
            payment_id = int(payment.json()["id"])

            dashboard_report = self.client.post("/api/analytics/reports", json={
                "report_type": "dashboard_hub",
                "title": "BI · Dashboard Hub",
                "filters": {},
                "layout": {"target_role": "Директор", "dashboard_kind": "dashboard", "tags": ["bi", "executive"]},
                "scope": "shared",
            })
            self.assertEqual(dashboard_report.status_code, 200)
            dashboard_report_id = int(dashboard_report.json()["id"])

            drill_report = self.client.post("/api/analytics/reports", json={
                "report_type": "analytics_drilldown",
                "title": "BI · Client Drill",
                "filters": {"dimension": "client", "value": client_name, "value_id": client_id, "limit": 20},
                "layout": {"target_role": "Менеджер", "dashboard_kind": "cockpit", "tags": ["client"]},
                "scope": "private",
            })
            self.assertEqual(drill_report.status_code, 200)
            drill_report_id = int(drill_report.json()["id"])

            dashboards = self.client.get("/api/analytics/dashboards")
            self.assertEqual(dashboards.status_code, 200)
            dashboards_json = dashboards.json()
            self.assertIn("role_dashboards", dashboards_json)
            self.assertIn("saved_views", dashboards_json)
            self.assertGreaterEqual(int(dashboards_json["metrics"]["role_dashboards_total"]), 1)
            self.assertTrue(any(item["title"] == "BI · Dashboard Hub" for item in dashboards_json["saved_views"]["shared"]))

            drilldown = self.client.get(f"/api/analytics/drilldown?dimension=client&value={client_name}&value_id={client_id}&limit=20")
            self.assertEqual(drilldown.status_code, 200)
            drill_json = drilldown.json()
            self.assertEqual(drill_json["dimension"], "client")
            self.assertGreaterEqual(int(drill_json["summary"]["rows_total"]), 1)
            self.assertTrue(any(item["entity_type"] == "finance_payment" for item in drill_json["rows"]))

            run_dashboard = self.client.post(f"/api/analytics/reports/{dashboard_report_id}/run")
            self.assertEqual(run_dashboard.status_code, 200)
            self.assertIn("role_dashboards", run_dashboard.json()["payload"])

            run_drill = self.client.post(f"/api/analytics/reports/{drill_report_id}/run")
            self.assertEqual(run_drill.status_code, 200)
            self.assertEqual(run_drill.json()["payload"]["dimension"], "client")
            self.assertGreaterEqual(len(run_drill.json()["payload"]["rows"]), 1)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if dashboard_report_id:
                c.execute("DELETE FROM saved_reports WHERE id=?", (dashboard_report_id,))
            if drill_report_id:
                c.execute("DELETE FROM saved_reports WHERE id=?", (drill_report_id,))
            if payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
                c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?)", (payment_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
            if client_id:
                c.execute("DELETE FROM contacts WHERE client_id=?", (client_id,))
                c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_docflow_plus_summary_includes_timeline_and_templates(self):
        director = create_test_user(role="Директор", name_prefix="Docflow Director")
        template_id = 0
        document_id = 0
        version_id = 0
        print_form_id = 0
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            created = self.client.post("/api/documents", json={
                "type": "incoming",
                "number": "QA-DOCFLOW-001",
                "d_date": "13.04.2026",
                "correspondent": "QA Sender",
                "subject": "Проверка docflow timeline",
                "status": "registered",
                "project_id": 0,
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
            self.assertEqual(created.status_code, 200)
            document_id = int(created.json()["id"])

            template = self.client.post("/api/docflow/templates", json={
                "title": "QA Шаблон письма",
                "doc_type": "incoming",
                "template_kind": "catalog",
                "version_label": "v1",
                "body_text": "Текст по шаблону",
                "variables": ["number", "subject"],
                "status": "active",
                "comment": "Шаблон для smoke-теста",
            })
            self.assertEqual(template.status_code, 200)
            template_id = int(template.json()["id"])

            version = self.client.post("/api/docflow/versions", json={
                "document_id": document_id,
                "version_label": "QA-v1",
                "version_status": "draft",
                "payload": {"subject": "Проверка docflow timeline"},
                "file_url": "",
                "comment": "Создано тестом",
            })
            self.assertEqual(version.status_code, 200)
            version_id = int(version.json()["id"])

            print_form = self.client.post("/api/docflow/print_forms", json={
                "document_id": document_id,
                "template_id": template_id,
                "format_type": "pdf",
                "form_name": "QA Print Form",
                "file_url": "",
                "status": "generated",
                "comment": "Сгенерировано тестом",
            })
            self.assertEqual(print_form.status_code, 200)
            print_form_id = int(print_form.json()["id"])

            summary = self.client.get("/api/docflow/plus_summary")
            self.assertEqual(summary.status_code, 200)
            payload = summary.json()
            self.assertIn("timeline", payload)
            self.assertIn("type_breakdown", payload)
            self.assertIn("template_catalog", payload)
            self.assertIn("template_families", payload)
            self.assertIn("strict_type_breakdown", payload)
            self.assertIn("print_coverage", payload)
            self.assertTrue(any(item["title"] == "QA Шаблон письма" for item in payload["templates"]))
            self.assertGreaterEqual(int(payload["type_breakdown"].get("incoming", 0)), 1)
            self.assertTrue(any(int(item.get("document_id") or 0) == document_id for item in payload["timeline"]))
            self.assertTrue(any(item.get("kind") == "version" and int(item.get("document_id") or 0) == document_id for item in payload["timeline"]))
            self.assertTrue(any(item.get("kind") == "print_form" and int(item.get("document_id") or 0) == document_id for item in payload["timeline"]))
            self.assertTrue(any(item.get("doc_type") == "incoming" for item in payload["template_catalog"]))

            version_diff = self.client.get(f"/api/docflow/versions/{version_id}/diff")
            self.assertEqual(version_diff.status_code, 200)
            diff_payload = version_diff.json()
            self.assertEqual(int(diff_payload["document_id"]), document_id)
            self.assertGreaterEqual(int(diff_payload["change_count"]), 1)

            timeline = self.client.get(f"/api/docflow/documents/{document_id}/timeline")
            self.assertEqual(timeline.status_code, 200)
            timeline_payload = timeline.json()
            self.assertEqual(int(timeline_payload["document_id"]), document_id)
            self.assertTrue(any(item.get("kind") == "version" for item in timeline_payload["timeline"]))

            print_set = self.client.post(f"/api/docflow/documents/{document_id}/generate_print_set")
            self.assertEqual(print_set.status_code, 200)
            print_set_payload = print_set.json()
            self.assertGreaterEqual(int(print_set_payload["count"]), 1)
            generated_ids = [int(item["id"]) for item in print_set_payload.get("items", [])]
        finally:
            conn = get_connection()
            c = conn.cursor()
            for generated_id in locals().get("generated_ids", []):
                c.execute("DELETE FROM document_print_forms WHERE id=?", (generated_id,))
            if print_form_id:
                c.execute("DELETE FROM document_print_forms WHERE id=?", (print_form_id,))
            if version_id:
                c.execute("DELETE FROM document_versions WHERE id=?", (version_id,))
            if template_id:
                c.execute("DELETE FROM document_templates WHERE id=?", (template_id,))
            if document_id:
                c.execute("DELETE FROM documents WHERE id=?", (document_id,))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_integration_plus_supports_mapping_inbound_connector_sync_and_auto_resolve(self):
        director = create_test_user(role="Директор", name_prefix="Integration Plus Director")
        client_id = 0
        project_id = 0
        payment_id = 0
        bank_account_id = 0
        bank_order_id = 0
        telephony_account_id = 0
        telephony_call_id = 0
        connector_ids = []
        inbound_id = 0
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            bootstrap = self.client.post("/api/integration/mappings/bootstrap/purchase_order")
            self.assertEqual(bootstrap.status_code, 200)
            self.assertEqual(bootstrap.json()["status"], "success")

            client_name = f"QA Integration Client {os.getpid()}"
            created_client = self.client.post("/api/clients", json={"name": client_name, "inn": "7701888999", "contact": "integration@example.com"})
            self.assertEqual(created_client.status_code, 200)

            created_project = self.client.post("/api/projects", json={
                "name": "QA Integration Project",
                "contract": "QA-INT-001",
                "client": client_name,
                "manager": director["name"],
                "budget": 0,
                "costs": 0,
                "team": [],
                "checklist": [],
                "allowed_roles": [],
                "nomenclature": [],
                "archive_details": {},
            })
            self.assertEqual(created_project.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
            client_id = int(c.fetchone()[0])
            c.execute("SELECT id FROM projects WHERE name=? ORDER BY id DESC LIMIT 1", ("QA Integration Project",))
            project_id = int(c.fetchone()[0])
            conn.close()

            contact_create = self.client.post("/api/contacts", json={
                "client_id": client_id,
                "name": "QA Integration Contact",
                "phone": "+7 (999) 222-33-44",
                "email": "integration-contact@example.com",
                "position": "Sales",
            })
            self.assertEqual(contact_create.status_code, 200)

            payment_create = self.client.post("/api/finance/payments", json={
                "project_id": project_id,
                "client_id": client_id,
                "title": "QA Integration Payment",
                "kind": "incoming",
                "category": "payment",
                "amount": 5500,
                "currency": "RUB",
                "due_date": "15.04.2026",
                "paid_date": "",
                "status": "issued",
                "comment": "integration plus",
            })
            self.assertEqual(payment_create.status_code, 200)
            payment_id = int(payment_create.json()["id"])

            bank_account = self.client.post("/api/banking/accounts", json={
                "name": "QA Integration Bank",
                "bank_name": "Mock Bank",
                "account_number": "40702810900000000001",
                "bik": "044525225",
                "currency": "RUB",
                "legal_entity_id": 0,
                "is_active": 1,
            })
            self.assertEqual(bank_account.status_code, 200)
            bank_account_id = int(bank_account.json()["id"])

            bank_order = self.client.post("/api/banking/payment_orders", json={
                "payment_id": payment_id,
                "bank_account_id": bank_account_id,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "order_date": "15.04.2026",
                "amount": 5500,
                "currency": "RUB",
                "counterparty": client_name,
                "purpose": "QA Integration Export",
                "status": "approved",
                "comment": "connector sync test",
            })
            self.assertEqual(bank_order.status_code, 200)
            bank_order_id = int(bank_order.json()["id"])

            telephony_account = self.client.post("/api/telephony/accounts", json={
                "provider_name": "Mango",
                "line_name": "QA Integration Line",
                "external_line_id": "INT-LINE-01",
                "is_active": 1,
            })
            self.assertEqual(telephony_account.status_code, 200)
            telephony_account_id = int(telephony_account.json()["id"])

            telephony_call = self.client.post("/api/telephony/calls", json={
                "account_id": telephony_account_id,
                "phone_number": "+7 (999) 222-33-44",
                "direction": "inbound",
                "status": "answered",
                "duration_sec": 28,
                "summary": "Auto-link integration connector",
            })
            self.assertEqual(telephony_call.status_code, 200)
            telephony_call_id = int(telephony_call.json()["id"])

            for connector_type, provider in [("bank", "Mock Bank API"), ("telephony", "Mango"), ("bi", "Metabase"), ("1c", "1C Gateway")]:
                connector = self.client.post("/api/integration/connectors", json={
                    "connector_type": connector_type,
                    "provider_name": provider,
                    "status": "active",
                    "settings": {},
                    "scope": {},
                })
                self.assertEqual(connector.status_code, 200)
                connector_ids.append(int(connector.json()["id"]))

            inbound = self.client.post("/api/integration/inbound_updates", json={
                "entity_type": "finance_payment",
                "entity_id": payment_id,
                "external_id": f"1C-FIN-{payment_id}",
                "payload": {"status": "paid", "amount": 5500, "currency": "RUB", "paid_date": "15.04.2026", "comment": "inbound preview"},
                "apply_mode": "preview",
                "comment": "preview first",
            })
            self.assertEqual(inbound.status_code, 200)
            inbound_id = int(inbound.json()["id"])
            self.assertEqual(inbound.json()["apply_status"], "preview")

            inbound_preview = self.client.get(f"/api/integration/inbound_updates/{inbound_id}/preview")
            self.assertEqual(inbound_preview.status_code, 200)
            self.assertTrue(inbound_preview.json()["matched"])
            self.assertGreaterEqual(len(inbound_preview.json()["changes"]), 1)

            applied = self.client.post(f"/api/integration/inbound_updates/{inbound_id}/apply")
            self.assertEqual(applied.status_code, 200)
            self.assertEqual(applied.json()["apply_status"], "applied")

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT status FROM finance_payments WHERE id=?", (payment_id,))
            self.assertEqual(c.fetchone()[0], "paid")
            c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?)", (payment_id,))
            c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
            c.execute("UPDATE finance_payments SET exchange_state='issued', external_sync_id='' WHERE id=?", (payment_id,))
            conn.commit()
            conn.close()

            auto_resolve = self.client.post("/api/integration/reconciliation/auto_resolve")
            self.assertEqual(auto_resolve.status_code, 200)
            self.assertEqual(auto_resolve.json()["status"], "success")

            bank_sync = self.client.post(f"/api/integration/connectors/{connector_ids[0]}/sync")
            self.assertEqual(bank_sync.status_code, 200)
            self.assertEqual(bank_sync.json()["status"], "success")
            self.assertGreaterEqual(int(bank_sync.json()["exported_orders"]), 1)

            telephony_sync = self.client.post(f"/api/integration/connectors/{connector_ids[1]}/sync")
            self.assertEqual(telephony_sync.status_code, 200)
            self.assertEqual(telephony_sync.json()["status"], "success")

            bi_sync = self.client.post(f"/api/integration/connectors/{connector_ids[2]}/sync")
            self.assertEqual(bi_sync.status_code, 200)
            self.assertEqual(bi_sync.json()["status"], "success")

            onec_sync = self.client.post(f"/api/integration/connectors/{connector_ids[3]}/sync")
            self.assertEqual(onec_sync.status_code, 200)
            self.assertEqual(onec_sync.json()["status"], "success")

            calls = self.client.get("/api/telephony/calls")
            self.assertEqual(calls.status_code, 200)
            linked_call = next(item for item in calls.json() if int(item["id"]) == telephony_call_id)
            self.assertEqual(int(linked_call["client_id"]), client_id)
            self.assertEqual(int(linked_call["project_id"]), project_id)

            plus = self.client.get("/api/integration/plus_summary")
            self.assertEqual(plus.status_code, 200)
            plus_payload = plus.json()
            self.assertIn("mapping_matrix", plus_payload)
            self.assertIn("operator_recovery_board", plus_payload)
            self.assertIn("bank_exchange_board", plus_payload)
            self.assertIn("telephony_board", plus_payload)
            self.assertIn("bi_vitrines", plus_payload)
            self.assertTrue(any(item["entity_type"] == "purchase_order" for item in plus_payload["mapping_matrix"]))
        finally:
            conn = get_connection()
            c = conn.cursor()
            if telephony_call_id:
                c.execute("DELETE FROM notifications WHERE entity_type='telephony_call' AND entity_id=?", (str(telephony_call_id),))
                c.execute("DELETE FROM audit_log WHERE entity_type='telephony_call' AND entity_id=?", (str(telephony_call_id),))
                c.execute("DELETE FROM telephony_calls WHERE id=?", (telephony_call_id,))
            if telephony_account_id:
                c.execute("DELETE FROM audit_log WHERE entity_type='telephony_account' AND entity_id=?", (str(telephony_account_id),))
                c.execute("DELETE FROM telephony_accounts WHERE id=?", (telephony_account_id,))
            if bank_order_id:
                c.execute("DELETE FROM bank_payment_orders WHERE id=?", (bank_order_id,))
            if bank_account_id:
                c.execute("DELETE FROM audit_log WHERE entity_type='bank_account' AND entity_id=?", (str(bank_account_id),))
                c.execute("DELETE FROM bank_accounts WHERE id=?", (bank_account_id,))
            if payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
                c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?)", (payment_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
            if inbound_id:
                c.execute("DELETE FROM integration_inbound_updates WHERE id=?", (inbound_id,))
            for connector_id in connector_ids:
                c.execute("DELETE FROM audit_log WHERE entity_type='integration_connector' AND entity_id=?", (str(connector_id),))
                c.execute("DELETE FROM integration_connectors WHERE id=?", (connector_id,))
            c.execute("DELETE FROM saved_reports WHERE owner_email=? AND title LIKE 'BI · %'", (director["email"],))
            c.execute("DELETE FROM bank_exchange_batches WHERE created_by=?", (director["email"],))
            c.execute("DELETE FROM integration_reconciliation_runs WHERE created_by=?", (director["email"],))
            c.execute("DELETE FROM integration_field_mappings WHERE created_by=? AND entity_type='purchase_order'", (director["email"],))
            if client_id:
                c.execute("DELETE FROM contacts WHERE client_id=?", (client_id,))
                c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            if project_id:
                c.execute("DELETE FROM projects WHERE id=?", (project_id,))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_sales_document_supports_price_list_terms_and_shipping_fields(self):
        manager = create_test_user(role="Менеджер", name_prefix="Sales Fields Manager")
        client_id = 0
        price_list_id = 0
        terms_id = 0
        sales_id = 0
        try:
            login = self.client.post("/api/login", json={"email": manager["email"], "password": manager["password"]})
            self.assertEqual(login.status_code, 200)

            client_name = f"QA Sales Terms Client {os.getpid()}"
            created_client = self.client.post("/api/clients", json={"name": client_name, "inn": "7701999000", "contact": "sales-terms@example.com"})
            self.assertEqual(created_client.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
            client_id = int(c.fetchone()[0])
            conn.close()

            price_list = self.client.post("/api/sales/price_lists", json={
                "name": "QA Sales Terms Price",
                "currency": "RUB",
                "valid_from": "13.04.2026",
                "valid_to": "30.04.2026",
                "item_article": "QA-SALES-001",
                "item_name": "QA Sales Item",
                "unit": "шт",
                "base_price": 100000,
                "min_price": 90000,
                "status": "active",
                "comment": "",
            })
            self.assertEqual(price_list.status_code, 200)
            price_list_id = int(price_list.json()["id"])

            terms = self.client.post("/api/sales/client_terms", json={
                "client_id": client_id,
                "price_list_id": price_list_id,
                "discount_percent": 10,
                "discount_amount": 5000,
                "payment_delay_days": 14,
                "credit_limit": 250000,
                "shipment_priority": "high",
                "status": "active",
                "comment": "",
            })
            self.assertEqual(terms.status_code, 200)
            terms_id = int(terms.json()["id"])

            created_sales = self.client.post("/api/sales/documents", json={
                "project_id": 0,
                "client_id": client_id,
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "doc_type": "invoice",
                "doc_number": f"INV-QA-{os.getpid()}",
                "doc_date": "13.04.2026",
                "amount": 95000,
                "currency": "RUB",
                "status": "issued",
                "payment_status": "planned",
                "linked_payment_id": 0,
                "customer_order_no": "PO-QA-001",
                "shipment_status": "ready",
                "payment_due_date": "27.04.2026",
                "planned_ship_date": "20.04.2026",
                "shipped_at": "",
                "reserve_status": "reserved",
                "reserve_qty": 3,
                "price_list_id": price_list_id,
                "discount_percent": 10,
                "discount_amount": 5000,
                "comment": "Коммерческие условия сохранены",
                "recipient_email": "buyer@example.com",
                "sent_status": "sent",
                "sent_at": "13.04.2026",
                "delivered_at": "",
                "confirmed_at": "",
            })
            self.assertEqual(created_sales.status_code, 200)
            sales_id = int(created_sales.json()["id"])

            sales_rows = self.client.get("/api/sales/documents")
            self.assertEqual(sales_rows.status_code, 200)
            row = next(item for item in sales_rows.json() if int(item["id"]) == sales_id)
            self.assertEqual(int(row["price_list_id"]), price_list_id)
            self.assertEqual(float(row["discount_percent"]), 10)
            self.assertEqual(float(row["discount_amount"]), 5000)
            self.assertEqual(row["customer_order_no"], "PO-QA-001")
            self.assertEqual(row["shipment_status"], "ready")
            self.assertEqual(row["payment_due_date"], "27.04.2026")
            self.assertEqual(row["planned_ship_date"], "20.04.2026")
            self.assertEqual(row["reserve_status"], "reserved")
            self.assertEqual(float(row["reserve_qty"]), 3)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if sales_id:
                c.execute("SELECT id FROM finance_payments WHERE source_document_type='sales_document' AND source_document_id=?", (sales_id,))
                payment_ids = [int(row[0]) for row in c.fetchall()]
                if payment_ids:
                    c.executemany("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", [(payment_id,) for payment_id in payment_ids])
                    c.executemany("DELETE FROM finance_payments WHERE id=?", [(payment_id,) for payment_id in payment_ids])
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='sales_document' AND entity_id=?", (sales_id,))
                c.execute("DELETE FROM sales_documents_extended WHERE id=?", (sales_id,))
            if terms_id:
                c.execute("DELETE FROM client_sales_terms WHERE id=?", (terms_id,))
            if price_list_id:
                c.execute("DELETE FROM price_lists WHERE id=?", (price_list_id,))
            if client_id:
                c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            conn.commit()
            conn.close()

    def test_documents_1c_import_preview_and_apply(self):
        director = create_test_user(role="Директор", name_prefix="Documents 1C Import Director")
        director_client = TestClient(app)
        external_id = f"1C-DOC-QA-{int(time.time() * 1000)}"
        doc_id = 0
        try:
            login = director_client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            payload = {
                "source_system": "1C",
                "actor_note": "Автотест переноса документов",
                "items": [
                    {
                        "тип": "входящий",
                        "номер": "QA-1C-DOC-001",
                        "дата": "23.04.2026",
                        "контрагент": "ООО Документы 1С",
                        "тема": "Договор поставки из 1С",
                        "статус": "зарегистрирован",
                        "внешний идентификатор": external_id,
                    }
                ],
            }
            preview = director_client.post("/api/documents/1c/import/preview", json=payload)
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.json()["status"], "success")
            self.assertEqual(preview.json()["errors"], 0)
            self.assertEqual(preview.json()["ready"], 1)

            applied = director_client.post("/api/documents/1c/import", json=payload)
            self.assertEqual(applied.status_code, 200)
            self.assertEqual(applied.json()["status"], "success")
            self.assertEqual(applied.json()["created"], 1)
            doc_id = int(applied.json()["results"][0]["entity_id"])

            documents = director_client.get("/api/documents")
            self.assertEqual(documents.status_code, 200)
            imported = next(item for item in documents.json() if int(item["id"]) == doc_id)
            self.assertEqual(imported["number"], "QA-1C-DOC-001")
            self.assertEqual(imported["external_sync_id"], external_id)
            self.assertEqual(imported["exchange_state"], "synced")
        finally:
            conn = get_connection()
            c = conn.cursor()
            if doc_id:
                c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            c.execute("DELETE FROM integration_external_objects WHERE entity_type='document' AND external_id=?", (external_id,))
            c.execute("DELETE FROM integration_sync_log WHERE entity_type='document' AND external_id=?", (external_id,))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])

    def test_sales_and_supply_extended_summary_exposes_mature_commercial_metrics(self):
        actor = create_test_user(role="Директор", name_prefix="Ops Mature")
        article = f"QA-MATURE-{os.getpid()}"
        client_id = 0
        supplier_id = 0
        quote_id = 0
        plan_id = 0
        price_list_ids = []
        terms_id = 0
        sales_id = 0
        purchase_plan_id = 0
        purchase_id = 0
        schedule_id = 0
        supplier_return_id = 0
        discrepancy_id = 0
        try:
            login = self.client.post("/api/login", json={"email": actor["email"], "password": actor["password"]})
            self.assertEqual(login.status_code, 200)

            client_name = f"QA Mature Client {os.getpid()}"
            supplier_name = f"QA Mature Supplier {os.getpid()}"
            created_client = self.client.post("/api/clients", json={"name": client_name, "inn": f"77{os.getpid():08d}"[-10:], "contact": "mature@example.com"})
            self.assertEqual(created_client.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
            client_id = int(c.fetchone()[0])
            conn.close()

            supplier = self.client.post("/api/suppliers", json={
                "supplier_name": supplier_name,
                "inn": "7701888777",
                "category": "Металл",
                "rating": 4.5,
                "lead_time_days": 12,
                "reliability_percent": 88,
                "payment_terms": "30/70",
                "comment": "Тестовый зрелый поставщик",
            })
            self.assertEqual(supplier.status_code, 200)
            supplier_id = int(supplier.json()["id"])

            quote = self.client.post("/api/sales/quotes", json={
                "client_id": client_id,
                "title": "QA Mature Quote",
                "stage": "negotiation",
                "amount": 125000,
                "valid_until": "20.04.2026",
                "responsible": actor["name"],
                "probability": 65,
                "comment": "КП для проверки pipeline",
            })
            self.assertEqual(quote.status_code, 200)
            quote_id = int(quote.json()["id"])

            for valid_to in ("20.04.2026", "30.04.2026"):
                created = self.client.post("/api/sales/price_lists", json={
                    "name": "QA Mature Price",
                "currency": "RUB",
                "valid_from": "10.04.2026",
                "valid_to": valid_to,
                "item_article": article,
                "item_name": "QA Mature Item",
                    "unit": "шт",
                    "base_price": 125000 if valid_to == "20.04.2026" else 128000,
                    "min_price": 110000,
                    "status": "active",
                    "comment": "Версионный прайс",
                })
                self.assertEqual(created.status_code, 200)
                price_list_ids.append(int(created.json()["id"]))

            terms = self.client.post("/api/sales/client_terms", json={
                "client_id": client_id,
                "price_list_id": price_list_ids[-1],
                "discount_percent": 8,
                "discount_amount": 4000,
                "payment_delay_days": 10,
                "credit_limit": 350000,
                "shipment_priority": "priority",
                "status": "active",
                "comment": "Тестовые условия",
            })
            self.assertEqual(terms.status_code, 200)
            terms_id = int(terms.json()["id"])

            sales_plan = self.client.post("/api/sales/plans", json={
                "period_key": "2026-04",
                "manager_name": actor["name"],
                "client_id": client_id,
                "target_amount": 150000,
                "target_docs": 2,
                "status": "active",
                "comment": "План для summary",
            })
            self.assertEqual(sales_plan.status_code, 200)
            plan_id = int(sales_plan.json()["id"])

            sales_doc = self.client.post("/api/sales/documents", json={
                "project_id": 0,
                "client_id": client_id,
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "doc_type": "invoice",
                "doc_number": f"INV-MATURE-{os.getpid()}",
                "doc_date": "01.04.2026",
                "amount": 121000,
                "currency": "RUB",
                "status": "issued",
                "payment_status": "planned",
                "linked_payment_id": 0,
                "customer_order_no": "PO-MATURE-1",
                "shipment_status": "ready",
                "payment_due_date": "05.04.2026",
                "planned_ship_date": "06.04.2026",
                "shipped_at": "",
                "reserve_status": "reserved",
                "reserve_qty": 2,
                "price_list_id": price_list_ids[-1],
                "discount_percent": 8,
                "discount_amount": 4000,
                "comment": "Документ для overdue и SLA",
                "recipient_email": "buyer@example.com",
                "sent_status": "sent",
                "sent_at": "01.04.2026",
                "delivered_at": "",
                "confirmed_at": "",
            })
            self.assertEqual(sales_doc.status_code, 200)
            sales_id = int(sales_doc.json()["id"])

            purchase_plan = self.client.post("/api/purchase/plans", json={
                "period_key": "2026-04",
                "supplier_id": supplier_id,
                "project_id": 0,
                "item_article": article,
                "item_name": "QA Mature Item",
                "qty_plan": 10,
                "unit": "шт",
                "target_unit_price": 10000,
                "target_amount": 100000,
                "status": "active",
                "comment": "План для summary",
            })
            self.assertEqual(purchase_plan.status_code, 200)
            purchase_plan_id = int(purchase_plan.json()["id"])

            purchase = self.client.post("/api/purchases", json={
                "project_id": 0,
                "client_id": client_id,
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "item_article": article,
                "item_name": "QA Mature Item",
                "supplier": supplier_name,
                "supplier_id": supplier_id,
                "qty": 10,
                "unit": "шт",
                "unit_price": 11200,
                "planned_unit_price": 10000,
                "status": "ordered",
                "expected_date": "07.04.2026",
                "planned_delivery_date": "07.04.2026",
                "received_date": "",
                "delivered_qty": 0,
                "schedule_status": "planned",
                "lead_time_days": 12,
                "comment": "Закупка для отклонений",
            })
            self.assertEqual(purchase.status_code, 200)
            purchase_id = int(purchase.json()["id"])

            create_nom = self.client.post("/api/nomenclature", json={
                "name": "QA Mature Item",
                "article": article,
                "unit": "шт",
                "price": 11200,
                "stock": 0,
                "currency": "RUB",
            })
            self.assertEqual(create_nom.status_code, 200)

            move_in = self.client.post(
                f"/api/nomenclature/{article}/movement_detailed",
                json={
                    "qty": 5,
                    "type": "add",
                    "from_warehouse": "Поставка",
                    "from_bin": "IN-01",
                    "to_warehouse": "Основной склад",
                    "to_bin": "A-01",
                    "batch_code": "MATURE-LOT",
                    "serial_no": "",
                    "comment": "Приход под возврат поставщику",
                },
            )
            self.assertEqual(move_in.status_code, 200)
            self.assertEqual(move_in.json()["status"], "success")

            schedule = self.client.post("/api/purchase/delivery_schedules", json={
                "purchase_id": purchase_id,
                "supplier_id": supplier_id,
                "scheduled_date": "08.04.2026",
                "planned_qty": 10,
                "delivered_qty": 4,
                "status": "partial",
                "transport_no": "TRK-001",
                "comment": "Частичная поставка",
            })
            self.assertEqual(schedule.status_code, 200)
            schedule_id = int(schedule.json()["id"])

            supplier_return = self.client.post("/api/purchase/returns", json={
                "purchase_id": purchase_id,
                "supplier_id": supplier_id,
                "article": article,
                "item_name": "QA Mature Item",
                "qty": 1,
                "amount": 11200,
                "currency": "RUB",
                "warehouse": "Основной склад",
                "bin_code": "A-01",
                "status": "approved",
                "reason": "Брак поставки",
                "comment": "Возврат поставщику",
            })
            self.assertEqual(supplier_return.status_code, 200)
            supplier_return_id = int(supplier_return.json()["id"])

            discrepancy = self.client.post("/api/purchase/discrepancy_acts", json={
                "purchase_id": purchase_id,
                "supplier_id": supplier_id,
                "article": article,
                "item_name": "QA Mature Item",
                "planned_qty": 10,
                "actual_qty": 4,
                "planned_unit_price": 10000,
                "actual_unit_price": 11200,
                "status": "open",
                "reason": "Недопоставка и цена выше плана",
                "comment": "Тестовый акт",
            })
            self.assertEqual(discrepancy.status_code, 200)
            discrepancy_id = int(discrepancy.json()["id"])

            sales_summary = self.client.get("/api/sales/extended_summary")
            self.assertEqual(sales_summary.status_code, 200)
            sales_payload = sales_summary.json()
            self.assertIn("client_health", sales_payload)
            self.assertIn("price_lifecycle", sales_payload)
            self.assertIn("pipeline", sales_payload)
            self.assertGreaterEqual(int(sales_payload["metrics"]["quotes_active"]), 1)
            self.assertGreaterEqual(int(sales_payload["metrics"]["customer_risk_clients"]), 1)
            self.assertTrue(any(item["stage"] == "negotiation" for item in sales_payload["pipeline"]))

            supply_summary = self.client.get("/api/supply/extended_summary")
            self.assertEqual(supply_summary.status_code, 200)
            supply_payload = supply_summary.json()
            self.assertIn("supplier_health", supply_payload)
            self.assertIn("schedule_alerts", supply_payload)
            self.assertIn("plan_fact", supply_payload)
            self.assertGreaterEqual(int(supply_payload["metrics"]["late_deliveries"]), 1)
            self.assertGreaterEqual(int(supply_payload["metrics"]["underdelivery_cases"]), 1)

            price_lists = self.client.get("/api/sales/price_lists")
            self.assertEqual(price_lists.status_code, 200)
            mature_price_rows = [item for item in price_lists.json() if item.get("name") == "QA Mature Price"]
            self.assertTrue(mature_price_rows)
            self.assertTrue(all("version_no" in item and "lifecycle_state" in item for item in mature_price_rows))

            suppliers = self.client.get("/api/suppliers")
            self.assertEqual(suppliers.status_code, 200)
            supplier_row = next(item for item in suppliers.json() if int(item["id"]) == supplier_id)
            self.assertIn("health_score", supplier_row)
            self.assertIn("late_deliveries", supplier_row)

            schedules = self.client.get("/api/purchase/delivery_schedules")
            self.assertEqual(schedules.status_code, 200)
            schedule_row = next(item for item in schedules.json() if int(item["id"]) == schedule_id)
            self.assertIn("remaining_qty", schedule_row)
            self.assertIn("late_days", schedule_row)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if discrepancy_id:
                c.execute("DELETE FROM supplier_discrepancy_acts WHERE id=?", (discrepancy_id,))
            if supplier_return_id:
                c.execute("DELETE FROM supplier_returns WHERE id=?", (supplier_return_id,))
            if schedule_id:
                c.execute("DELETE FROM supplier_delivery_schedules WHERE id=?", (schedule_id,))
            if purchase_id:
                c.execute("SELECT id FROM finance_payments WHERE source_document_type='purchase_order' AND source_document_id=?", (purchase_id,))
                payment_ids = [int(row[0]) for row in c.fetchall()]
                if payment_ids:
                    c.executemany("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", [(payment_id,) for payment_id in payment_ids])
                    c.executemany("DELETE FROM finance_payments WHERE id=?", [(payment_id,) for payment_id in payment_ids])
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='purchase_order' AND entity_id=?", (purchase_id,))
                c.execute("DELETE FROM purchase_orders WHERE id=?", (purchase_id,))
            if purchase_plan_id:
                c.execute("DELETE FROM purchase_plans WHERE id=?", (purchase_plan_id,))
            if sales_id:
                c.execute("SELECT id FROM finance_payments WHERE source_document_type='sales_document' AND source_document_id=?", (sales_id,))
                payment_ids = [int(row[0]) for row in c.fetchall()]
                if payment_ids:
                    c.executemany("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", [(payment_id,) for payment_id in payment_ids])
                    c.executemany("DELETE FROM finance_payments WHERE id=?", [(payment_id,) for payment_id in payment_ids])
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='sales_document' AND entity_id=?", (sales_id,))
                c.execute("DELETE FROM sales_documents_extended WHERE id=?", (sales_id,))
            if terms_id:
                c.execute("DELETE FROM client_sales_terms WHERE id=?", (terms_id,))
            if price_list_ids:
                c.executemany("DELETE FROM price_lists WHERE id=?", [(row_id,) for row_id in price_list_ids])
            if plan_id:
                c.execute("DELETE FROM sales_plans WHERE id=?", (plan_id,))
            if quote_id:
                c.execute("DELETE FROM sales_quotes WHERE id=?", (quote_id,))
            if supplier_id:
                c.execute("DELETE FROM supplier_registry WHERE id=?", (supplier_id,))
            c.execute("DELETE FROM stock_movements WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_balances WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_lots WHERE article=?", (article,))
            c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
            if client_id:
                c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            conn.commit()
            conn.close()
            delete_test_user(actor["email"])

    def test_stock_journal_bulk_actions_and_print_forms_cover_warehouse_flow(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        source_article = "QA-WH-001"
        target_article = "QA-WH-002"
        inventory_act_id = 0
        quality_id = 0
        regrading_id = 0
        linked_document_id = 0
        try:
            for article, name in ((source_article, "Складской тестовый товар"), (target_article, "Товар назначения")):
                response = self.client.post("/api/nomenclature", json={
                    "name": name,
                    "article": article,
                    "unit": "шт",
                    "price": 1200,
                    "stock": 0,
                    "currency": "RUB",
                })
                self.assertEqual(response.status_code, 200)

            move_in = self.client.post(
                f"/api/nomenclature/{source_article}/movement_detailed",
                json={
                    "qty": 5,
                    "type": "add",
                    "from_warehouse": "Поставка",
                    "from_bin": "IN-05",
                    "to_warehouse": "Основной склад",
                    "to_bin": "A-05",
                    "batch_code": "QA-STOCK-WH",
                    "serial_no": "",
                    "comment": "Приход для складского контура",
                },
            )
            self.assertEqual(move_in.status_code, 200)
            self.assertEqual(move_in.json()["status"], "success")

            inventory_act = self.client.post("/api/stock/inventory_acts", json={
                "warehouse": "Основной склад",
                "bin_code": "A-05",
                "article": source_article,
                "item_name": "Складской тестовый товар",
                "expected_qty": 5,
                "counted_qty": 4,
                "batch_code": "QA-STOCK-WH",
                "serial_no": "",
                "status": "posted",
                "comment": "Инвентаризация с расхождением",
            })
            self.assertEqual(inventory_act.status_code, 200)
            inventory_act_payload = inventory_act.json()
            self.assertEqual(inventory_act_payload["status"], "success")
            inventory_act_id = int(inventory_act_payload["id"])
            linked_document_id = int(inventory_act_payload["linked_document_id"])

            quality = self.client.post("/api/stock/quality_reports", json={
                "warehouse": "Основной склад",
                "bin_code": "A-05",
                "article": source_article,
                "item_name": "Складской тестовый товар",
                "qty": 1,
                "quality_status": "hold",
                "defect_kind": "Повреждена упаковка",
                "decision": "inspect",
                "status": "open",
                "comment": "Кейс качества",
            })
            self.assertEqual(quality.status_code, 200)
            quality_id = int(quality.json()["id"])

            regrading = self.client.post("/api/stock/regrading", json={
                "warehouse": "Основной склад",
                "bin_code": "A-05",
                "from_article": source_article,
                "from_name": "Складской тестовый товар",
                "to_article": target_article,
                "to_name": "Товар назначения",
                "qty": 1,
                "status": "posted",
                "reason": "Пересортица после приёмки",
                "comment": "Ручная пересортица",
            })
            self.assertEqual(regrading.status_code, 200)
            regrading_id = int(regrading.json()["id"])

            summary = self.client.get("/api/stock/extended_summary")
            self.assertEqual(summary.status_code, 200)
            summary_payload = summary.json()
            self.assertGreaterEqual(int(summary_payload["metrics"]["journal_entries"]), 3)
            self.assertGreaterEqual(int(summary_payload["metrics"]["discrepancy_cases"]), 1)
            self.assertTrue(summary_payload["discrepancy_reasons"])
            self.assertTrue(summary_payload["quality_statuses"])

            journal = self.client.get("/api/stock/journal?limit=50")
            self.assertEqual(journal.status_code, 200)
            journal_rows = journal.json()
            self.assertTrue(any(item["entity_type"] == "inventory_act" for item in journal_rows))
            self.assertTrue(any(item["entity_type"] == "quality_report" for item in journal_rows))
            self.assertTrue(any(item["entity_type"] == "regrading_doc" for item in journal_rows))

            print_doc = self.client.get(f"/api/stock/documents/{linked_document_id}/print")
            self.assertEqual(print_doc.status_code, 200)
            self.assertEqual(print_doc.json()["status"], "success")

            print_act = self.client.get(f"/api/stock/inventory_acts/{inventory_act_id}/print")
            self.assertEqual(print_act.status_code, 200)
            self.assertEqual(print_act.json()["status"], "success")

            print_quality = self.client.get(f"/api/stock/quality_reports/{quality_id}/print")
            self.assertEqual(print_quality.status_code, 200)
            self.assertEqual(print_quality.json()["status"], "success")

            bulk_close = self.client.post("/api/stock/bulk_action", json={
                "entity_type": "quality_report",
                "action": "close",
                "ids": [quality_id],
            })
            self.assertEqual(bulk_close.status_code, 200)
            self.assertEqual(bulk_close.json()["status"], "success")

            quality_rows = self.client.get("/api/stock/quality_reports")
            self.assertEqual(quality_rows.status_code, 200)
            quality_row = next(item for item in quality_rows.json() if int(item["id"]) == quality_id)
            self.assertEqual(quality_row["status"], "closed")

            bulk_print = self.client.post("/api/stock/bulk_action", json={
                "entity_type": "regrading_doc",
                "action": "print",
                "ids": [regrading_id],
            })
            self.assertEqual(bulk_print.status_code, 200)
            self.assertEqual(int(bulk_print.json()["count"]), 1)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if quality_id:
                c.execute("DELETE FROM warehouse_quality_reports WHERE id=?", (quality_id,))
            if regrading_id:
                c.execute("DELETE FROM inventory_regrading_docs WHERE id=?", (regrading_id,))
            if inventory_act_id:
                c.execute("DELETE FROM inventory_acts WHERE id=?", (inventory_act_id,))
            if linked_document_id:
                c.execute("DELETE FROM inventory_documents WHERE id=?", (linked_document_id,))
            c.execute("DELETE FROM stock_movements WHERE article IN (?, ?)", (source_article, target_article))
            c.execute("DELETE FROM inventory_balances WHERE article IN (?, ?)", (source_article, target_article))
            c.execute("DELETE FROM inventory_lots WHERE article IN (?, ?)", (source_article, target_article))
            c.execute("DELETE FROM nomenclature WHERE article IN (?, ?)", (source_article, target_article))
            conn.commit()
            conn.close()

    def test_finance_accounting_deep_supports_treasury_routes_and_bank_exchange(self):
        director = create_test_user(role="Директор", name_prefix="Accounting Deep Director")
        director_client = TestClient(app)
        route_id = 0
        payment_id = 0
        bank_account_id = 0
        payment_order_id = 0
        export_batch_id = 0
        import_batch_id = 0
        try:
            login = director_client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            master_payload = director_client.get("/api/finance/master_data").json()
            legal_entity_id = int(master_payload["defaults"]["legal_entity_id"])
            business_unit_id = int(master_payload["defaults"]["business_unit_id"])
            outgoing_article = next(item for item in master_payload["treasury_articles"] if item["flow_kind"] == "outgoing")
            vat_rate_id = int(master_payload["defaults"]["vat_rate_id"])

            route_res = director_client.post("/api/finance/treasury_routes", json={
                "route_name": "QA Treasury Route",
                "legal_entity_id": legal_entity_id,
                "business_unit_id": business_unit_id,
                "min_amount": 1000,
                "max_amount": 500000,
                "currency": "RUB",
                "stages": [{"step": 1, "role": "Бухгалтер"}, {"step": 2, "role": "Финдиректор"}, {"step": 3, "role": "Директор"}],
                "is_active": 1,
            })
            self.assertEqual(route_res.status_code, 200)
            route_id = int(route_res.json()["id"])

            payment_res = director_client.post("/api/finance/payments", json={
                "title": "QA Bank Outgoing",
                "kind": "outgoing",
                "category": "payment",
                "amount": 125000,
                "currency": "RUB",
                "status": "planned",
                "due_date": "20.04.2026",
                "legal_entity_id": legal_entity_id,
                "business_unit_id": business_unit_id,
                "treasury_article_id": int(outgoing_article["id"]),
                "vat_rate_id": vat_rate_id,
                "comment": "Платеж для bank exchange",
            })
            self.assertEqual(payment_res.status_code, 200)
            payment_id = int(payment_res.json()["id"])

            bank_account_res = director_client.post("/api/banking/accounts", json={
                "name": "QA Bank Account",
                "bank_name": "QA Bank",
                "account_number": "40702810900000000001",
                "bik": "044525225",
                "currency": "RUB",
                "legal_entity_id": legal_entity_id,
                "is_active": 1,
            })
            self.assertEqual(bank_account_res.status_code, 200)
            bank_account_id = int(bank_account_res.json()["id"])

            order_res = director_client.post("/api/banking/payment_orders", json={
                "payment_id": payment_id,
                "bank_account_id": bank_account_id,
                "legal_entity_id": legal_entity_id,
                "business_unit_id": business_unit_id,
                "order_date": "15.04.2026",
                "amount": 125000,
                "currency": "RUB",
                "counterparty": "QA Supplier",
                "purpose": "Оплата по QA банку",
                "status": "draft",
            })
            self.assertEqual(order_res.status_code, 200)
            payment_order_id = int(order_res.json()["id"])

            export_res = director_client.post("/api/banking/exchange_batches/export", json={
                "provider_name": "bank_api",
                "batch_type": "payment_exchange",
                "bank_account_id": bank_account_id,
                "payment_order_ids": [payment_order_id],
            })
            self.assertEqual(export_res.status_code, 200)
            export_batch_id = int(export_res.json()["id"])

            import_res = director_client.post("/api/banking/exchange_batches/import_result", json={
                "provider_name": "bank_api",
                "batch_type": "payment_exchange",
                "bank_account_id": bank_account_id,
                "result_items": [{
                    "payment_order_id": payment_order_id,
                    "status": "executed",
                    "external_payment_id": "BANK-QA-001",
                    "executed_at": "16.04.2026",
                }],
            })
            self.assertEqual(import_res.status_code, 200)
            import_batch_id = int(import_res.json()["id"])

            finance_deep = director_client.get("/api/finance/deep_summary")
            self.assertEqual(finance_deep.status_code, 200)
            finance_payload = finance_deep.json()
            self.assertTrue(any(int(item["id"]) == route_id for item in finance_payload["treasury_routes"]))
            self.assertTrue(any(int(item["payment_id"]) == payment_id for item in finance_payload["bank_payment_orders"]))
            self.assertTrue(any(int(item["id"]) == export_batch_id for item in finance_payload["exchange_batches"]))
            self.assertIn("factor_variance", finance_payload)

            accounting_deep = director_client.get("/api/accounting/deep_summary")
            self.assertEqual(accounting_deep.status_code, 200)
            accounting_payload = accounting_deep.json()
            self.assertTrue(accounting_payload["posting_templates"])
            self.assertTrue(accounting_payload["balance_sheet_lines"])
            self.assertIn("vat_by_rate", accounting_payload)
            self.assertTrue(any(int(item["id"]) == payment_order_id for item in accounting_payload["bank_payment_orders"]))
            self.assertTrue(any(int(item["id"]) == import_batch_id for item in accounting_payload["exchange_batches"]))

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT status, paid_date FROM finance_payments WHERE id=?", (payment_id,))
            payment_row = c.fetchone()
            self.assertEqual(payment_row[0], "paid")
            self.assertEqual(payment_row[1], "16.04.2026")
            conn.close()
        finally:
            conn = get_connection()
            c = conn.cursor()
            if import_batch_id:
                c.execute("DELETE FROM bank_exchange_batches WHERE id=?", (import_batch_id,))
            if export_batch_id:
                c.execute("DELETE FROM bank_exchange_batches WHERE id=?", (export_batch_id,))
            if payment_order_id:
                c.execute("DELETE FROM bank_payment_orders WHERE id=?", (payment_order_id,))
            if bank_account_id:
                c.execute("DELETE FROM bank_accounts WHERE id=?", (bank_account_id,))
            if payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
            if route_id:
                c.execute("DELETE FROM treasury_approval_routes WHERE id=?", (route_id,))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])


if __name__ == "__main__":
    unittest.main()
