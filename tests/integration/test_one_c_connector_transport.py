import os
import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class OneCConnectorTransportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.director = create_test_user(role="Директор", name_prefix="OneC Director")
        login = self.client.post("/api/login", json={"email": self.director["email"], "password": self.director["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        delete_test_user(self.director["email"])

    def test_finance_payment_exports_to_1c_connector_and_records_transport_trace(self):
        suffix = f"{os.getpid()}-{int(time.time())}"
        connector_id = 0
        payment_id = 0
        queue_id = 0
        try:
            connector = self.client.post("/api/integration/1c/connectors", json={
                "provider_name": f"QA Demo 1C {suffix}",
                "transport": "demo",
                "status": "active",
                "settings": {"transport": "demo"},
            })
            self.assertEqual(connector.status_code, 200)
            self.assertEqual(connector.json()["status"], "success")
            connector_id = int(connector.json()["id"])

            created = self.client.post("/api/finance/payments", json={
                "project_id": 0,
                "client_id": 0,
                "title": f"QA 1C Connector Payment {suffix}",
                "kind": "incoming",
                "category": "payment",
                "amount": 9876,
                "currency": "RUB",
                "due_date": "22.04.2026",
                "paid_date": "",
                "status": "issued",
                "comment": "connector transport test",
            })
            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["status"], "success")
            payment_id = int(created.json()["id"])

            conn = get_connection()
            c = conn.cursor()
            c.execute(
                """
                SELECT id
                FROM integration_sync_queue
                WHERE entity_type='finance_payment' AND entity_id=?
                ORDER BY id DESC LIMIT 1
                """,
                (payment_id,),
            )
            queue_id = int(c.fetchone()[0])
            c.execute("UPDATE integration_sync_queue SET connector_id=?, priority=-1000, created_at=0 WHERE id=?", (connector_id, queue_id))
            conn.commit()
            conn.close()

            processed = self.client.post("/api/integration/1c/process", params={"limit": 1})
            self.assertEqual(processed.status_code, 200)
            self.assertEqual(processed.json()["status"], "success")

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT state, external_id, connector_id FROM integration_sync_queue WHERE id=?", (queue_id,))
            queue_row = c.fetchone()
            self.assertEqual(queue_row[0], "synced")
            self.assertEqual(queue_row[1], f"1C-FIN-{payment_id}")
            self.assertEqual(int(queue_row[2]), connector_id)

            c.execute("SELECT exchange_state, external_sync_id FROM finance_payments WHERE id=?", (payment_id,))
            payment_row = c.fetchone()
            self.assertEqual(payment_row[0], "synced")
            self.assertEqual(payment_row[1], f"1C-FIN-{payment_id}")

            c.execute(
                """
                SELECT external_id, exchange_state, last_message_id
                FROM integration_external_objects
                WHERE entity_type='finance_payment' AND entity_id=?
                ORDER BY id DESC LIMIT 1
                """,
                (str(payment_id),),
            )
            external_row = c.fetchone()
            self.assertIsNotNone(external_row)
            self.assertEqual(external_row[0], f"1C-FIN-{payment_id}")
            self.assertEqual(external_row[1], "synced")
            self.assertGreater(int(external_row[2]), 0)

            c.execute(
                """
                SELECT transport, http_status, status
                FROM integration_exchange_messages
                WHERE queue_id=?
                ORDER BY id DESC LIMIT 1
                """,
                (queue_id,),
            )
            message_row = c.fetchone()
            self.assertEqual(message_row[0], "demo")
            self.assertEqual(int(message_row[1]), 200)
            self.assertEqual(message_row[2], "success")
            conn.close()

            messages = self.client.get("/api/integration/1c/exchange_messages", params={"entity_type": "finance_payment", "entity_id": str(payment_id)})
            self.assertEqual(messages.status_code, 200)
            self.assertEqual(messages.json()["status"], "success")
            self.assertTrue(messages.json()["items"])
        finally:
            conn = get_connection()
            c = conn.cursor()
            if queue_id:
                c.execute("DELETE FROM integration_exchange_messages WHERE queue_id=?", (queue_id,))
                c.execute("DELETE FROM integration_external_objects WHERE entity_type='finance_payment' AND entity_id=?", (str(payment_id),))
                c.execute("DELETE FROM integration_consistency_checks WHERE queue_id=?", (queue_id,))
                c.execute("DELETE FROM integration_error_events WHERE queue_id=?", (queue_id,))
                c.execute("DELETE FROM integration_sync_log WHERE queue_id=?", (queue_id,))
                c.execute("DELETE FROM integration_idempotency_keys WHERE queue_id=?", (queue_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE id=?", (queue_id,))
            if payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
            if connector_id:
                c.execute("DELETE FROM integration_connector_credentials WHERE connector_id=?", (connector_id,))
                c.execute("DELETE FROM integration_connector_runs WHERE connector_id=?", (connector_id,))
                c.execute("DELETE FROM integration_connectors WHERE id=?", (connector_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
