import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class TerminalAndDocflowOCRIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="RF OCR Director")
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        delete_test_user(self.user["email"])

    def test_rf_terminal_handles_wms_and_production_execution(self):
        stamp = f"{int(time.time())}-{id(self)}"
        article = f"QA-RF-{stamp}"
        source_wh = "QA RF Receive"
        source_bin = "RCV-01"
        target_wh = "QA RF Main"
        target_bin = "A-01"
        batch_code = f"LOT-RF-{stamp}"
        putaway_id = 0
        order_id = 0
        operation_id = 0
        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute(
                "INSERT INTO nomenclature (article, name, unit, price, stock, currency, group_name, default_warehouse) VALUES (?, ?, 'шт', 0, 5, 'RUB', 'QA', ?)",
                (article, "QA RF item", target_wh),
            )
            c.execute(
                """
                INSERT INTO inventory_balances (article, warehouse, bin_code, qty, updated_at)
                VALUES (?, ?, ?, 5, ?)
                ON CONFLICT(article, warehouse, bin_code) DO UPDATE SET qty=EXCLUDED.qty, updated_at=EXCLUDED.updated_at
                """,
                (article, source_wh, source_bin, int(time.time())),
            )
            c.execute(
                """
                INSERT INTO inventory_lots (article, warehouse, bin_code, batch_code, serial_no, qty, updated_at)
                VALUES (?, ?, ?, ?, '', 5, ?)
                ON CONFLICT(article, warehouse, bin_code, batch_code, serial_no) DO UPDATE SET qty=EXCLUDED.qty, updated_at=EXCLUDED.updated_at
                """,
                (article, source_wh, source_bin, batch_code, int(time.time())),
            )
            conn.commit()
            conn.close()

            putaway = self.client.post("/api/wms/putaway_tasks", json={
                "article": article,
                "item_name": "QA RF item",
                "qty": 4,
                "source_warehouse": source_wh,
                "source_bin": source_bin,
                "target_warehouse": target_wh,
                "target_bin": target_bin,
                "batch_code": batch_code,
                "priority": "high",
                "comment": "RF integration putaway",
            })
            self.assertEqual(putaway.status_code, 200)
            self.assertEqual(putaway.json()["status"], "success")
            putaway_id = int(putaway.json()["id"])

            session = self.client.post("/api/terminal/sessions", json={
                "terminal_code": f"RF-{stamp}",
                "terminal_type": "warehouse",
                "current_zone": "QA",
            })
            self.assertEqual(session.status_code, 200)
            self.assertEqual(session.json()["status"], "success")

            scan = self.client.post("/api/terminal/scan", json={
                "terminal_code": f"RF-{stamp}",
                "terminal_type": "warehouse",
                "scan_kind": "barcode",
                "scan_value": f"PUTAWAY-{putaway_id}",
                "action_name": "complete_putaway",
                "payload": {},
            })
            self.assertEqual(scan.status_code, 200)
            self.assertEqual(scan.json()["status"], "success")
            self.assertEqual(scan.json()["result"]["status"], "success")

            conn = get_connection(row_factory=True)
            task = dict(conn.execute("SELECT * FROM wms_putaway_tasks WHERE id=?", (putaway_id,)).fetchone() or {})
            target_qty = conn.execute("SELECT COALESCE(SUM(qty), 0) AS qty FROM inventory_balances WHERE article=? AND warehouse=? AND bin_code=?", (article, target_wh, target_bin)).fetchone()
            conn.close()
            self.assertEqual(task["status"], "done")
            self.assertEqual(float(target_qty["qty"]), 4)

            order = self.client.post("/api/production/orders", json={
                "project_id": 0,
                "client_id": 0,
                "order_name": f"QA RF Production {stamp}",
                "stage": "queue",
                "priority": "high",
                "planned_start": "21.04.2026",
                "planned_finish": "25.04.2026",
                "actual_finish": "",
                "progress": 0,
                "responsible": self.user["name"],
                "route_name": "QA RF route",
                "planned_qty": 4,
                "produced_qty": 0,
                "scrap_qty": 0,
                "planned_cost": 1000,
                "actual_cost": 0,
                "labor_hours_plan": 2,
                "labor_hours_fact": 0,
                "comment": "RF integration order",
            })
            self.assertEqual(order.status_code, 200)
            order_id = int(order.json()["id"])

            operation = self.client.post("/api/production/operations", json={
                "order_id": order_id,
                "sequence_no": 1,
                "operation_name": "QA RF operation",
                "work_center": "QA RF center",
                "status": "planned",
                "planned_hours": 2,
                "actual_hours": 0,
                "planned_qty": 4,
                "completed_qty": 0,
                "scrap_qty": 0,
                "labor_rate": 100,
                "material_cost": 0,
                "overhead_cost": 0,
                "started_at": "",
                "finished_at": "",
                "note": "RF operation",
            })
            self.assertEqual(operation.status_code, 200)
            operation_id = int(operation.json()["id"])

            started = self.client.post("/api/terminal/scan", json={
                "terminal_code": f"SHOP-{stamp}",
                "terminal_type": "production",
                "scan_kind": "barcode",
                "scan_value": f"OP-{operation_id}",
                "action_name": "production_start",
                "payload": {"executor_name": self.user["name"]},
            })
            self.assertEqual(started.status_code, 200)
            self.assertEqual(started.json()["status"], "success")

            completed = self.client.post("/api/terminal/scan", json={
                "terminal_code": f"SHOP-{stamp}",
                "terminal_type": "production",
                "scan_kind": "barcode",
                "scan_value": f"OP-{operation_id}",
                "action_name": "production_complete",
                "payload": {"qty": 4, "actual_hours": 2, "executor_name": self.user["name"]},
            })
            self.assertEqual(completed.status_code, 200)
            self.assertEqual(completed.json()["status"], "success")

            summary = self.client.get("/api/terminal/summary")
            self.assertEqual(summary.status_code, 200)
            self.assertGreaterEqual(summary.json()["metrics"]["production_events"], 2)
            self.assertTrue(any(int(item["operation_id"]) == operation_id for item in summary.json()["production_events"]))

            conn = get_connection(row_factory=True)
            op_row = dict(conn.execute("SELECT status, completed_qty, actual_hours FROM production_operations WHERE id=?", (operation_id,)).fetchone() or {})
            order_row = dict(conn.execute("SELECT stage, progress, produced_qty FROM production_orders WHERE id=?", (order_id,)).fetchone() or {})
            conn.close()
            self.assertEqual(op_row["status"], "done")
            self.assertEqual(float(op_row["completed_qty"]), 4)
            self.assertEqual(float(op_row["actual_hours"]), 2)
            self.assertEqual(order_row["stage"], "done")
            self.assertEqual(float(order_row["produced_qty"]), 4)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if operation_id:
                c.execute("DELETE FROM production_execution_events WHERE operation_id=?", (operation_id,))
                c.execute("DELETE FROM terminal_scan_events WHERE entity_type='production_operation' AND entity_id=?", (operation_id,))
                c.execute("DELETE FROM production_operations WHERE id=?", (operation_id,))
            if order_id:
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='production_order' AND entity_id=?", (order_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='production_order' AND entity_id=?", (order_id,))
                c.execute("DELETE FROM production_orders WHERE id=?", (order_id,))
            if putaway_id:
                c.execute("DELETE FROM terminal_scan_events WHERE entity_type='wms_putaway_task' AND entity_id=?", (putaway_id,))
                c.execute("DELETE FROM wms_putaway_tasks WHERE id=?", (putaway_id,))
            c.execute("DELETE FROM terminal_sessions WHERE terminal_code IN (?, ?)", (f"RF-{stamp}", f"SHOP-{stamp}"))
            c.execute("DELETE FROM stock_movements WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_lots WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_balances WHERE article=?", (article,))
            c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
            conn.commit()
            conn.close()

    def test_docflow_ocr_auto_apply_and_template_flow(self):
        stamp = f"{int(time.time())}-{id(self)}"
        document_id = 0
        template_id = 0
        ocr_id = 0
        flow_id = 0
        try:
            document = self.client.post("/api/documents", json={
                "type": "incoming",
                "number": f"QA-OCR-DRAFT-{stamp}",
                "d_date": "21.04.2026",
                "correspondent": "",
                "subject": "Черновик под OCR",
                "status": "draft",
                "project_id": 0,
                "contract_id": 0,
                "object_id": 0,
                "parent_id": 0,
                "priority": "normal",
            })
            self.assertEqual(document.status_code, 200)
            document_id = int(document.json()["id"])

            template = self.client.post("/api/docflow/templates", json={
                "title": f"QA OCR Template {stamp}",
                "doc_type": "incoming",
                "template_kind": "editable",
                "version_label": "v1",
                "body_text": "Входящий {number}: {subject}",
                "variables": ["number", "d_date", "correspondent", "subject"],
                "status": "active",
                "comment": "OCR template",
            })
            self.assertEqual(template.status_code, 200)
            template_id = int(template.json()["id"])

            ocr = self.client.post("/api/docflow/ocr_jobs", json={
                "document_id": document_id,
                "template_id": template_id,
                "input_text": f"Входящий № OCR-{stamp} от ООО Ромашка; ИНН 7700000000; дата 21.04.2026; сумма 120000; тема Поставка оборудования",
                "language": "rus",
                "auto_apply": 1,
            })
            self.assertEqual(ocr.status_code, 200)
            ocr_payload = ocr.json()
            self.assertEqual(ocr_payload["status"], "success")
            self.assertEqual(ocr_payload["ocr_status"], "applied")
            ocr_id = int(ocr_payload["id"])
            self.assertEqual(ocr_payload["fields"]["number"], f"OCR-{stamp}")

            conn = get_connection(row_factory=True)
            doc_row = dict(conn.execute("SELECT number, correspondent, subject FROM documents WHERE id=?", (document_id,)).fetchone() or {})
            conn.close()
            self.assertEqual(doc_row["number"], f"OCR-{stamp}")
            self.assertEqual(doc_row["correspondent"], "ООО Ромашка")
            self.assertIn("Поставка оборудования", doc_row["subject"])

            flow = self.client.post("/api/docflow/template_flows", json={
                "flow_code": f"QA-FLOW-{stamp}",
                "flow_name": "QA входящий OCR поток",
                "direction": "incoming",
                "doc_type": "incoming",
                "trigger_rules": {"source": "ocr"},
                "template_ids": [template_id],
                "required_fields": ["number", "d_date", "correspondent", "subject"],
                "status": "active",
            })
            self.assertEqual(flow.status_code, 200)
            flow_id = int(flow.json()["id"])

            applied = self.client.post(f"/api/docflow/template_flows/{flow_id}/apply", json={
                "document_id": document_id,
                "ocr_job_id": ocr_id,
                "comment": "QA apply flow",
            })
            self.assertEqual(applied.status_code, 200)
            applied_payload = applied.json()
            self.assertEqual(applied_payload["status"], "success")
            self.assertEqual(applied_payload["missing_fields"], [])
            self.assertGreater(applied_payload["version_id"], 0)
            self.assertEqual(len(applied_payload["created_print_forms"]), 1)

            summary = self.client.get("/api/docflow/plus_summary")
            self.assertEqual(summary.status_code, 200)
            summary_payload = summary.json()
            self.assertTrue(any(int(item["id"]) == ocr_id and item["status"] == "applied" for item in summary_payload["ocr_jobs"]))
            self.assertTrue(any(int(item["id"]) == flow_id for item in summary_payload["template_flows"]))
            self.assertGreaterEqual(summary_payload["metrics"]["ocr_jobs_processed"], 1)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if document_id:
                c.execute("DELETE FROM document_print_forms WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_versions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_ocr_jobs WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM documents WHERE id=?", (document_id,))
            if flow_id:
                c.execute("DELETE FROM document_template_flows WHERE id=?", (flow_id,))
            if template_id:
                c.execute("DELETE FROM document_templates WHERE id=?", (template_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
