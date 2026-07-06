import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from services import one_c_connector_service
from tests.test_helpers import create_test_user, delete_test_user


class _RuntimeHandler(BaseHTTPRequestHandler):
    unit_code = ""

    def log_message(self, *_args):
        return

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send_json({"status": "ok", "service": "1c"})
            return
        if self.path.startswith("/units"):
            self._send_json({"items": [{"code": self.unit_code, "name": "QA remote unit", "short_name": "qa"}]})
            return
        self.send_error(404)

    def do_POST(self):
        if self.path.startswith("/jsonrpc"):
            self._send_json({"jsonrpc": "2.0", "result": {"external_id": "REAL-1C-HEALTH"}, "id": "health"})
            return
        self.send_error(404)

    def _send_json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class RuntimeExternalWiringTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.director = create_test_user(role="Директор", name_prefix="Runtime Wiring Director")
        login = self.client.post("/api/login", json={"email": self.director["email"], "password": self.director["password"]})
        self.assertEqual(login.status_code, 200)
        self.server = HTTPServer(("127.0.0.1", 0), _RuntimeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        delete_test_user(self.director["email"])

    def test_real_http_wiring_for_1c_runtime_crypto_ocr_and_remote_nsi(self):
        suffix = f"{os.getpid()}-{int(time.time())}"
        unit_code = f"QA-REMOTE-UNIT-{suffix}"
        _RuntimeHandler.unit_code = unit_code
        connector_id = 0
        demo_connector_id = 0
        payment_id = 0
        imported_unit_id = 0
        old_app_env = one_c_connector_service.APP_ENV
        try:
            connector = self.client.post("/api/integration/1c/connectors", json={
                "provider_name": f"QA Real HTTP 1C {suffix}",
                "status": "active",
                "transport": "json_rpc",
                "base_url": self.base_url,
                "settings": {
                    "transport": "json_rpc",
                    "base_url": self.base_url,
                    "health_endpoint": "/health",
                    "timeout_seconds": 5,
                },
            })
            self.assertEqual(connector.status_code, 200)
            self.assertEqual(connector.json()["status"], "success")
            connector_id = int(connector.json()["id"])

            health = self.client.get(f"/api/integration/1c/connectors/{connector_id}/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["status"], "success")
            self.assertTrue(health.json()["ready"])
            self.assertEqual(health.json()["http_status"], 200)

            readiness = self.client.get("/api/integration/1c/readiness")
            self.assertEqual(readiness.status_code, 200)
            self.assertGreaterEqual(int(readiness.json()["active_connectors"]), 1)

            system_readiness = self.client.get("/api/system/readiness")
            self.assertEqual(system_readiness.status_code, 200)
            self.assertIn(system_readiness.json()["status"], {"green", "yellow", "red"})
            self.assertTrue(any(item["key"] == "one_c" for item in system_readiness.json()["checks"]))

            crypto = self.client.get("/api/docflow/crypto/runtime")
            self.assertEqual(crypto.status_code, 200)
            self.assertEqual(crypto.json()["status"], "success")
            self.assertIn("cryptcp", crypto.json())

            content_runtime = self.client.get("/api/docflow/content_index/runtime")
            self.assertEqual(content_runtime.status_code, 200)
            self.assertEqual(content_runtime.json()["status"], "success")
            self.assertIn("ocr", content_runtime.json())
            self.assertIn("antivirus", content_runtime.json())

            remote_import = self.client.post("/api/nsi/mdm/external_classifiers/import", json={
                "classifier_type": "units",
                "source_system": "QA_REMOTE",
                "version_tag": f"QA-{suffix}",
                "source_url": f"{self.base_url}/units",
                "limit": 20,
            })
            self.assertEqual(remote_import.status_code, 200)
            self.assertEqual(remote_import.json()["status"], "success")
            self.assertEqual(int(remote_import.json()["linked_units"]), 1)
            self.assertEqual(remote_import.json()["source"]["source_format"], "json")

            classifiers = self.client.get("/api/nsi/mdm/external_classifiers", params={"classifier_type": "units", "source_system": "QA_REMOTE"})
            self.assertEqual(classifiers.status_code, 200)
            row = next(item for item in classifiers.json() if item["external_code"] == unit_code)
            imported_unit_id = int(row["entity_id"])
            self.assertGreater(imported_unit_id, 0)

            payment = self.client.post("/api/finance/payments", json={
                "title": f"QA entity card payment {suffix}",
                "kind": "incoming",
                "category": "payment",
                "amount": 3210,
                "currency": "RUB",
                "due_date": "22.04.2026",
                "status": "planned",
                "comment": "entity card smoke",
            })
            self.assertEqual(payment.status_code, 200)
            self.assertEqual(payment.json()["status"], "success")
            payment_id = int(payment.json()["id"])
            card = self.client.get(f"/api/entity_cards/finance_payment/{payment_id}")
            self.assertEqual(card.status_code, 200)
            self.assertEqual(card.json()["status"], "success")
            self.assertEqual(card.json()["entity_type"], "finance_payment")
            self.assertIn("integration", card.json())
            self.assertIn("audit", card.json())

            demo_connector = self.client.post("/api/integration/1c/connectors", json={
                "provider_name": f"QA Demo Guard {suffix}",
                "status": "active",
                "transport": "demo",
                "settings": {"transport": "demo"},
            })
            self.assertEqual(demo_connector.status_code, 200)
            demo_connector_id = int(demo_connector.json()["id"])
            one_c_connector_service.APP_ENV = "production"
            demo_health = self.client.get(f"/api/integration/1c/connectors/{demo_connector_id}/health")
            self.assertEqual(demo_health.status_code, 200)
            self.assertEqual(demo_health.json()["status"], "error")
            self.assertFalse(demo_health.json()["ready"])
        finally:
            one_c_connector_service.APP_ENV = old_app_env
            conn = get_connection()
            c = conn.cursor()
            for current_connector_id in (connector_id, demo_connector_id):
                if current_connector_id:
                    c.execute("DELETE FROM integration_connector_runs WHERE connector_id=?", (current_connector_id,))
                    c.execute("DELETE FROM integration_connector_credentials WHERE connector_id=?", (current_connector_id,))
                    c.execute("DELETE FROM integration_exchange_messages WHERE connector_id=?", (current_connector_id,))
                    c.execute("DELETE FROM integration_connectors WHERE id=?", (current_connector_id,))
            c.execute("DELETE FROM nsi_external_classifiers WHERE external_code=?", (unit_code,))
            if payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
                c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?)", (payment_id,))
                c.execute("DELETE FROM integration_idempotency_keys WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?)", (payment_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
                c.execute("DELETE FROM audit_log WHERE entity_type='finance_payment' AND entity_id=?", (str(payment_id),))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
            if imported_unit_id:
                c.execute("DELETE FROM nsi_mdm_versions WHERE entity_type='units' AND entity_id=?", (imported_unit_id,))
                c.execute("DELETE FROM nsi_mdm_issues WHERE entity_type='units' AND entity_id=?", (imported_unit_id,))
                c.execute("DELETE FROM unit_master WHERE id=?", (imported_unit_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
