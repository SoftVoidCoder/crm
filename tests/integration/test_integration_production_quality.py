import json
import os
import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class IntegrationProductionQualityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.director = create_test_user(role="Директор", name_prefix="Integration Prod Director")
        login = self.client.post("/api/login", json={"email": self.director["email"], "password": self.director["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        delete_test_user(self.director["email"])

    def test_production_integration_retry_idempotency_errors_and_consistency(self):
        suffix = f"{os.getpid()}-{int(time.time())}"
        payment_id = 0
        queue_id = 0
        error_queue_id = 0
        batch_key = f"QA-PROD-INBOUND-{suffix}"
        error_key = f"QA-PROD-ERR-{suffix}"
        try:
            created = self.client.post("/api/finance/payments", json={
                "project_id": 0,
                "client_id": 0,
                "title": f"QA Production Integration {suffix}",
                "kind": "incoming",
                "category": "payment",
                "amount": 12345,
                "currency": "RUB",
                "due_date": "20.04.2026",
                "paid_date": "",
                "status": "issued",
                "comment": "production integration quality",
            })
            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["status"], "success")
            payment_id = int(created.json()["id"])

            conn = get_connection()
            c = conn.cursor()
            c.execute(
                """
                SELECT id, idempotency_key, checksum, attempt_limit, consistency_state
                FROM integration_sync_queue
                WHERE entity_type='finance_payment' AND entity_id=?
                ORDER BY id DESC LIMIT 1
                """,
                (payment_id,),
            )
            row = c.fetchone()
            conn.close()
            self.assertIsNotNone(row)
            queue_id = int(row[0])
            self.assertTrue(row[1])
            self.assertTrue(row[2])
            self.assertGreaterEqual(int(row[3]), 1)
            self.assertEqual(row[4], "pending")

            processed = self.client.post("/api/integration/1c/process", params={"limit": 100})
            self.assertEqual(processed.status_code, 200)
            self.assertEqual(processed.json()["status"], "success")

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT state, processed_at, consistency_state, external_id FROM integration_sync_queue WHERE id=?", (queue_id,))
            processed_row = c.fetchone()
            conn.close()
            self.assertEqual(processed_row[0], "synced")
            self.assertGreater(int(processed_row[1]), 0)
            self.assertEqual(processed_row[2], "consistent")
            self.assertEqual(processed_row[3], f"1C-FIN-{payment_id}")

            inbound_payload = {
                "source_system": "1C",
                "idempotency_key": batch_key,
                "correlation_id": f"QA-CORR-{suffix}",
                "items": [{
                    "entity_type": "finance_payment",
                    "entity_id": payment_id,
                    "external_id": f"1C-FIN-{payment_id}",
                    "status": "paid",
                    "amount": 12345,
                    "currency": "RUB",
                    "paid_date": "20.04.2026",
                    "comment": "inbound applied once",
                }],
            }
            inbound_first = self.client.post("/api/integration/1c/inbound", json=inbound_payload)
            self.assertEqual(inbound_first.status_code, 200)
            self.assertEqual(inbound_first.json()["status"], "success")
            self.assertEqual(inbound_first.json()["applied"], 1)

            inbound_second = self.client.post("/api/integration/1c/inbound", json=inbound_payload)
            self.assertEqual(inbound_second.status_code, 200)
            self.assertEqual(inbound_second.json()["status"], "success")
            self.assertTrue(inbound_second.json()["idempotent"])

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT status FROM finance_payments WHERE id=?", (payment_id,))
            self.assertEqual(c.fetchone()[0], "paid")
            c.execute("SELECT COUNT(*) FROM integration_idempotency_keys WHERE idempotency_key=?", (batch_key,))
            self.assertEqual(int(c.fetchone()[0]), 1)
            conn.close()

            conn = get_connection()
            c = conn.cursor()
            now = int(time.time())
            c.execute(
                """
                INSERT INTO integration_sync_queue (
                    system_name, entity_type, entity_id, direction, payload, mapping_key, state,
                    retry_count, next_retry_at, locked_at, created_by, created_at, updated_at,
                    idempotency_key, attempt_limit, priority
                ) VALUES ('1C', 'qa_unsupported_entity', ?, 'outbound', ?, ?, 'queued', 0, 0, 0, ?, ?, ?, ?, 1, 1)
                """,
                (
                    payment_id,
                    json.dumps({"id": payment_id, "qa": suffix}, ensure_ascii=False),
                    f"qa_unsupported_entity:{payment_id}",
                    self.director["email"],
                    now,
                    now,
                    error_key,
                ),
            )
            error_queue_id = int(c.lastrowid)
            conn.commit()
            conn.close()

            failed = self.client.post("/api/integration/1c/process", params={"limit": 100})
            self.assertEqual(failed.status_code, 200)
            self.assertEqual(failed.json()["status"], "success")

            errors = self.client.get("/api/integration/production/errors", params={"limit": 80})
            self.assertEqual(errors.status_code, 200)
            open_errors = errors.json()["errors"]
            matching_error = next((item for item in open_errors if int(item["queue_id"]) == error_queue_id), None)
            self.assertIsNotNone(matching_error)
            self.assertEqual(matching_error["error_code"], "outbound_sync_failed")

            health = self.client.get("/api/integration/production/health")
            self.assertEqual(health.status_code, 200)
            self.assertGreaterEqual(int(health.json()["quality"]["open_errors"]), 1)
            self.assertGreaterEqual(int(health.json()["quality"]["idempotency_keys_total"]), 1)

            retry = self.client.post(f"/api/integration/production/queue/{error_queue_id}/retry")
            self.assertEqual(retry.status_code, 200)
            self.assertEqual(retry.json()["status"], "success")

            resolved = self.client.post(f"/api/integration/production/errors/{int(matching_error['id'])}/resolve")
            self.assertEqual(resolved.status_code, 200)
            self.assertEqual(resolved.json()["status"], "success")

            consistency = self.client.post("/api/integration/production/consistency/run", params={"limit": 100})
            self.assertEqual(consistency.status_code, 200)
            self.assertEqual(consistency.json()["status"], "success")
            self.assertGreaterEqual(int(consistency.json()["checked"]), 1)

            idem = self.client.get("/api/integration/production/idempotency", params={"limit": 80})
            self.assertEqual(idem.status_code, 200)
            self.assertTrue(any(item["idempotency_key"] == batch_key for item in idem.json()["items"]))
        finally:
            conn = get_connection()
            c = conn.cursor()
            queue_ids = [item for item in [queue_id, error_queue_id] if item]
            for current_queue_id in queue_ids:
                c.execute("DELETE FROM integration_consistency_checks WHERE queue_id=?", (current_queue_id,))
                c.execute("DELETE FROM integration_error_events WHERE queue_id=?", (current_queue_id,))
                c.execute("DELETE FROM integration_sync_log WHERE queue_id=?", (current_queue_id,))
                c.execute("DELETE FROM integration_idempotency_keys WHERE queue_id=?", (current_queue_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE id=?", (current_queue_id,))
            c.execute("DELETE FROM integration_idempotency_keys WHERE idempotency_key IN (?, ?)", (batch_key, error_key))
            if payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
                c.execute("DELETE FROM integration_consistency_checks WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM integration_error_events WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?)", (payment_id,))
                c.execute("DELETE FROM integration_idempotency_keys WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?)", (payment_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
