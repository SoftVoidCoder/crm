import os
import time
import unittest

from fastapi.testclient import TestClient

from main import app
from database import get_connection
from tests.test_helpers import create_test_user, delete_test_user, run_db_cleanup


class WorkbenchUXTests(unittest.TestCase):
    def test_server_form_draft_roundtrip(self):
        director = create_test_user(role="Директор", name_prefix="Workbench Draft Director")
        client = TestClient(app)
        suffix = f"{os.getpid()}_{int(time.time() * 1000)}"
        draft_key = f"qa_finance_payment_{suffix}"
        try:
            login = client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            save = client.post("/api/workbench/form_drafts", json={
                "draft_key": draft_key,
                "entity_type": "finance_payment",
                "title": "Черновик оплаты QA",
                "source_view": "finance",
                "payload": {
                    "values": {
                        "financeTitle": "QA оплата",
                        "financeAmount": "12500",
                        "financeDueDate": "22.04.2026",
                    }
                },
            })
            self.assertEqual(save.status_code, 200)
            self.assertEqual(save.json()["status"], "success")
            self.assertEqual(save.json()["draft"]["draft_key"], draft_key)

            loaded = client.get(f"/api/workbench/form_drafts/{draft_key}")
            self.assertEqual(loaded.status_code, 200)
            self.assertEqual(loaded.json()["draft"]["payload"]["values"]["financeAmount"], "12500")

            listed = client.get("/api/workbench/form_drafts")
            self.assertEqual(listed.status_code, 200)
            self.assertTrue(any(item["draft_key"] == draft_key for item in listed.json()["drafts"]))

            deleted = client.delete(f"/api/workbench/form_drafts/{draft_key}")
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(deleted.json()["status"], "success")

            missing = client.get(f"/api/workbench/form_drafts/{draft_key}")
            self.assertEqual(missing.status_code, 200)
            self.assertEqual(missing.json()["error"], "form_draft_not_found")
        finally:
            run_db_cleanup([("DELETE FROM user_form_drafts WHERE draft_key=? OR user_email=?", (draft_key, director["email"]))])
            delete_test_user(director["email"])

    def test_workbench_bulk_actions_and_watch_digest(self):
        director = create_test_user(role="Директор", name_prefix="Workbench Bulk Director")
        client = TestClient(app)
        suffix = f"bulk_{os.getpid()}_{int(time.time() * 1000)}"
        sales_id = 0
        try:
            login = client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)
            conn = get_connection()
            try:
                conn.execute(
                    "INSERT INTO sales_documents_extended (doc_type, doc_number, amount, status, comment) VALUES ('invoice', ?, 1500, 'draft', ?)",
                    (suffix, suffix),
                )
                conn.commit()
                sales_id = int(conn.execute("SELECT id FROM sales_documents_extended WHERE doc_number=?", (suffix,)).fetchone()[0])
            finally:
                conn.close()

            status_res = client.post("/api/workbench/bulk_actions", json={
                "entity_type": "sales_document",
                "action": "update_status",
                "ids": [sales_id],
                "status": "issued",
            })
            self.assertEqual(status_res.status_code, 200)
            self.assertEqual(status_res.json()["count"], 1)

            export_res = client.post("/api/workbench/bulk_actions", json={
                "entity_type": "sales_document",
                "action": "export",
                "ids": [sales_id],
            })
            self.assertEqual(export_res.status_code, 200)
            self.assertEqual(export_res.json()["items"][0]["status"], "issued")

            watch_res = client.post("/api/workbench/watches", json={
                "entity_type": "sales_document",
                "entity_id": str(sales_id),
                "title": "Bulk invoice",
                "condition_key": "status_changed",
                "digest_mode": "daily",
                "event_types": ["status_changed"],
            })
            self.assertEqual(watch_res.status_code, 200)
            self.assertEqual(watch_res.json()["watch"]["digest_mode"], "daily")

            digest = client.get("/api/workbench/watch_digest")
            self.assertEqual(digest.status_code, 200)
            self.assertTrue(any(item["entity_type"] == "sales_document" for item in digest.json()["watches"]))

            delete_res = client.post("/api/workbench/bulk_actions", json={
                "entity_type": "sales_document",
                "action": "delete",
                "ids": [sales_id],
            })
            self.assertEqual(delete_res.status_code, 200)
            self.assertEqual(delete_res.json()["count"], 1)
            sales_id = 0
        finally:
            cleanup = [
                ("DELETE FROM sales_documents_extended WHERE id=? OR comment=?", (sales_id, suffix)),
                ("DELETE FROM entity_watchers WHERE user_email=?", (director["email"],)),
            ]
            run_db_cleanup(cleanup)
            delete_test_user(director["email"])

    def test_workbench_quick_access_filters_and_global_client_search(self):
        director = create_test_user(role="Директор", name_prefix="Workbench UX Director")
        client = TestClient(app)
        suffix = f"{os.getpid()}_{int(time.time() * 1000)}"
        client_name = f"UX Client {suffix}"
        created_client_id = 0
        created_filter_id = 0
        try:
            login = client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            create_client = client.post("/api/clients", json={
                "name": client_name,
                "inn": f"77{int(time.time()):08d}"[-10:],
                "contact": "ux-workbench@example.com",
            })
            self.assertEqual(create_client.status_code, 200)
            conn = get_connection()
            try:
                row = conn.execute("SELECT id FROM clients WHERE name=?", (client_name,)).fetchone()
                created_client_id = int(row[0])
            finally:
                conn.close()

            favorite = client.post("/api/workbench/favorites", json={
                "entity_type": "project",
                "entity_id": "42",
                "title": "UX Favorite Project",
                "meta": "UX-42 · тест",
                "view_name": "dashboard",
                "payload": {"source": "test"},
            })
            self.assertEqual(favorite.status_code, 200)
            self.assertEqual(favorite.json()["status"], "success")

            recent = client.post("/api/workbench/recent", json={
                "entity_type": "client",
                "entity_id": str(created_client_id),
                "title": client_name,
                "meta": "контрагент",
                "view_name": "clients",
                "payload": {},
            })
            self.assertEqual(recent.status_code, 200)
            self.assertEqual(recent.json()["status"], "success")

            saved_filter = client.post("/api/workbench/saved_filters", json={
                "filter_scope": "dashboard",
                "title": "UX Active Portfolio",
                "filter_payload": {"currentTab": "active", "viewMode": "kanban", "query": "UX", "department": "sales"},
            })
            self.assertEqual(saved_filter.status_code, 200)
            created_filter_id = int(saved_filter.json()["id"])

            quick = client.get("/api/workbench/quick_access")
            self.assertEqual(quick.status_code, 200)
            payload = quick.json()
            self.assertTrue(any(item["title"] == "UX Favorite Project" and item["type"] == "project" for item in payload["favorites"]))
            self.assertTrue(any(item["title"] == client_name and item["type"] == "client" for item in payload["recent"]))
            self.assertTrue(any(item["title"] == "UX Active Portfolio" and item["filter_payload"]["viewMode"] == "kanban" for item in payload["filters"]))
            self.assertIsInstance(payload["today_items"], list)

            search = client.get(f"/api/search?q={client_name}&limit=4")
            self.assertEqual(search.status_code, 200)
            self.assertTrue(any(item["entity_type"] == "client" and item["title"] == client_name for item in search.json()["items"]))

            delete_filter = client.delete(f"/api/workbench/saved_filters/{created_filter_id}")
            self.assertEqual(delete_filter.status_code, 200)
            self.assertEqual(delete_filter.json()["status"], "success")
            created_filter_id = 0

            delete_favorite = client.delete("/api/workbench/favorites/project/42")
            self.assertEqual(delete_favorite.status_code, 200)
            self.assertEqual(delete_favorite.json()["status"], "success")
        finally:
            cleanup = [
                ("DELETE FROM user_favorite_items WHERE user_email=?", (director["email"],)),
                ("DELETE FROM user_recent_items WHERE user_email=?", (director["email"],)),
                ("DELETE FROM user_saved_filters WHERE user_email=?", (director["email"],)),
            ]
            if created_client_id:
                cleanup.append(("DELETE FROM clients WHERE id=?", (created_client_id,)))
            elif client_name:
                cleanup.append(("DELETE FROM clients WHERE name=?", (client_name,)))
            run_db_cleanup(cleanup)
            if created_filter_id:
                run_db_cleanup([("DELETE FROM user_saved_filters WHERE id=?", (created_filter_id,))])
            delete_test_user(director["email"])

    def test_global_search_covers_operational_contours(self):
        director = create_test_user(role="Директор", name_prefix="Workbench Search Director")
        client = TestClient(app)
        suffix = f"GlobalSearch {os.getpid()} {int(time.time() * 1000)}"
        try:
            conn = get_connection()
            try:
                rows = [
                    ("INSERT INTO finance_payments (title, amount, status, comment) VALUES (?, 1234, 'planned', ?)", (f"{suffix} finance", suffix)),
                    ("INSERT INTO purchase_orders (item_name, item_article, supplier, status, comment) VALUES (?, ?, 'Search Supplier', 'planned', ?)", (f"{suffix} purchase", f"GS-{os.getpid()}", suffix)),
                    ("INSERT INTO stock_reservations (nomenclature_name, nomenclature_article, qty, status, comment) VALUES (?, ?, 2, 'reserved', ?)", (f"{suffix} reserve", f"RS-{os.getpid()}", suffix)),
                    ("INSERT INTO inventory_documents (doc_number, doc_type, article, warehouse, status, comment) VALUES (?, 'inventory', ?, 'Search WH', 'posted', ?)", (f"{suffix} stock doc", f"INV-{os.getpid()}", suffix)),
                    ("INSERT INTO production_orders (order_name, stage, responsible, comment) VALUES (?, 'queue', 'Search Lead', ?)", (f"{suffix} production", suffix)),
                    ("INSERT INTO contract_master (contract_number, title, status, comment) VALUES (?, ?, 'draft', ?)", (f"{suffix} contract no", f"{suffix} contract", suffix)),
                    ("INSERT INTO epl_waybills (number, route_text, cargo, status, notes) VALUES (?, ?, 'Search Cargo', 'draft', ?)", (f"{suffix} epl", f"{suffix} route", suffix)),
                    ("INSERT INTO approvals (title, item_link, route, current_step, status, history, author) VALUES (?, ?, '[]', 0, 'pending', '[]', ?)", (f"{suffix} approval", suffix, director["name"])),
                    ("INSERT INTO email_messages (account_id, uid, folder, subject, sender, sender_email, body_preview) VALUES (0, ?, 'INBOX', ?, 'Search Sender', 'search@example.com', ?)", (f"uid-{suffix}", f"{suffix} email", suffix)),
                ]
                for query, params in rows:
                    conn.execute(query, params)
                conn.commit()
            finally:
                conn.close()

            login = client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            search = client.get(f"/api/search?q={suffix}&limit=4")
            self.assertEqual(search.status_code, 200)
            entity_types = {item["entity_type"] for item in search.json()["items"]}
            self.assertTrue({
                "finance_payment",
                "purchase_order",
                "stock_reservation",
                "inventory_document",
                "production_order",
                "contract",
                "epl_waybill",
                "approval",
                "email",
            }.issubset(entity_types))
        finally:
            run_db_cleanup([
                ("DELETE FROM finance_payments WHERE comment=?", (suffix,)),
                ("DELETE FROM purchase_orders WHERE comment=?", (suffix,)),
                ("DELETE FROM stock_reservations WHERE comment=?", (suffix,)),
                ("DELETE FROM inventory_documents WHERE comment=?", (suffix,)),
                ("DELETE FROM production_orders WHERE comment=?", (suffix,)),
                ("DELETE FROM contract_master WHERE comment=?", (suffix,)),
                ("DELETE FROM epl_waybills WHERE notes=?", (suffix,)),
                ("DELETE FROM approvals WHERE item_link=?", (suffix,)),
                ("DELETE FROM email_messages WHERE body_preview=?", (suffix,)),
            ])
            delete_test_user(director["email"])


if __name__ == "__main__":
    unittest.main()
