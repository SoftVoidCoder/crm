import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class ProductionCostingERPIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="Costing ERP Director")

    def tearDown(self):
        delete_test_user(self.user["email"])

    def test_completed_operation_posts_cost_layers_wip_output_and_plan_fact_report(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        stamp = f"{int(time.time())}-{id(self)}"
        work_center = f"QA-COST-WC-{stamp}"
        article = f"QA-COST-MAT-{stamp}"
        order_id = 0
        operation_id = 0
        bom_item_id = 0
        bom_master_id = 0
        bom_version_id = 0
        work_center_id = 0
        calendar_id = 0

        try:
            wc_res = self.client.post("/api/production/work_centers", json={
                "center_code": work_center,
                "center_name": work_center,
                "center_type": "assembly",
                "capacity_per_hour": 5,
                "hourly_rate": 200,
                "overhead_rate": 50,
                "status": "active",
                "comment": "ERP costing test",
            })
            self.assertEqual(wc_res.status_code, 200)
            self.assertEqual(wc_res.json()["status"], "success")
            work_center_id = int(wc_res.json()["id"])

            cal_res = self.client.post("/api/production/work_center_calendars", json={
                "work_center_id": work_center_id,
                "calendar_date": "22.04.2026",
                "shift_code": "day",
                "available_hours": 8,
                "capacity_qty": 40,
                "status": "available",
                "comment": "ERP costing test",
            })
            self.assertEqual(cal_res.status_code, 200)
            calendar_id = int(cal_res.json()["id"])

            bom_res = self.client.post("/api/production/bom_master", json={
                "item_article": f"QA-FG-{stamp}",
                "item_name": "QA finished product",
                "bom_code": f"QA-BOM-{stamp}",
                "bom_name": "QA BOM costing",
                "status": "active",
                "unit": "шт",
                "output_qty": 1,
                "comment": "ERP costing master",
            })
            self.assertEqual(bom_res.status_code, 200)
            bom_master_id = int(bom_res.json()["id"])

            version_res = self.client.post("/api/production/bom_versions", json={
                "bom_id": bom_master_id,
                "version_no": "1",
                "status": "active",
                "valid_from": "22.04.2026",
                "output_qty": 1,
                "components": [{"article": article, "qty": 2, "unit": "шт"}],
                "operations": [{"operation_name": "Сборка", "work_center": work_center, "hours": 3}],
                "overhead_rules": {"method": "by_hours"},
                "comment": "ERP costing version",
            })
            self.assertEqual(version_res.status_code, 200)
            bom_version_id = int(version_res.json()["id"])

            order_res = self.client.post("/api/production/orders", json={
                "order_name": f"QA Costing Order {stamp}",
                "stage": "queue",
                "priority": "high",
                "planned_start": "22.04.2026",
                "planned_finish": "23.04.2026",
                "responsible": self.user["name"],
                "route_name": work_center,
                "planned_qty": 10,
                "planned_cost": 2000,
                "labor_hours_plan": 3,
                "comment": "ERP costing order",
            })
            self.assertEqual(order_res.status_code, 200)
            order_id = int(order_res.json()["id"])

            conn = get_connection()
            conn.execute(
                """
                INSERT INTO production_cost_layers (
                    production_order_id, operation_id, layer_type, actual_amount,
                    source_type, source_id, created_by, created_at, updated_at
                ) VALUES (?, ?, 'labor', 200, 'deleted_operation', 0, ?, ?, ?)
                """,
                (order_id, 1_900_000_001, self.user["email"], int(time.time()), int(time.time())),
            )
            conn.commit()
            conn.close()

            bom_item = self.client.post("/api/production/bom", json={
                "order_id": order_id,
                "article": article,
                "item_name": "QA material",
                "unit": "шт",
                "qty_per_unit": 2,
                "planned_qty": 20,
                "actual_qty": 0,
                "unit_cost": 50,
                "warehouse": "Основной",
                "bin_code": "A-01",
                "note": "ERP costing material",
            })
            self.assertEqual(bom_item.status_code, 200)
            bom_item_id = int(bom_item.json()["id"])

            operation = self.client.post("/api/production/operations", json={
                "order_id": order_id,
                "sequence_no": 1,
                "operation_name": "Сборка",
                "work_center": work_center,
                "status": "done",
                "planned_hours": 3,
                "actual_hours": 3,
                "planned_qty": 10,
                "completed_qty": 10,
                "scrap_qty": 0,
                "labor_rate": 200,
                "material_cost": 0,
                "overhead_cost": 150,
                "started_at": "22.04.2026 09:00",
                "finished_at": "22.04.2026 12:00",
                "note": "ERP costing operation",
            })
            self.assertEqual(operation.status_code, 200)
            operation_id = int(operation.json()["id"])
            self.assertEqual(operation.json()["costing"]["status"], "success")
            self.assertEqual(float(operation.json()["costing"]["actual_cost"]), 1750.0)

            conn = get_connection(row_factory=True)
            layers = [dict(row) for row in conn.execute(
                "SELECT layer_type, actual_amount, overhead_amount, qty FROM production_cost_layers WHERE operation_id=? ORDER BY id",
                (operation_id,),
            ).fetchall()]
            wip = [dict(row) for row in conn.execute(
                "SELECT movement_type, account_debit, account_credit, amount FROM wip_register WHERE operation_id=? ORDER BY id",
                (operation_id,),
            ).fetchall()]
            order_row = dict(conn.execute("SELECT actual_cost FROM production_orders WHERE id=?", (order_id,)).fetchone() or {})
            conn.close()

            self.assertEqual({row["layer_type"] for row in layers}, {"material", "labor", "overhead", "output"})
            self.assertIn("material_issue", {row["movement_type"] for row in wip})
            self.assertIn("labor_absorption", {row["movement_type"] for row in wip})
            self.assertIn("overhead_absorption", {row["movement_type"] for row in wip})
            self.assertIn("finished_goods_receipt", {row["movement_type"] for row in wip})
            self.assertEqual(float(order_row["actual_cost"]), 1750.0)

            report = self.client.get(f"/api/production/costing/report?order_id={order_id}")
            self.assertEqual(report.status_code, 200)
            rows = report.json()["rows"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(float(rows[0]["fact_cost"]), 1750.0)
            self.assertEqual(float(rows[0]["planned_cost"]), 2000.0)
            self.assertEqual(float(rows[0]["variance"]), -250.0)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if operation_id:
                c.execute("DELETE FROM wip_register WHERE operation_id=?", (operation_id,))
                c.execute("DELETE FROM production_cost_layers WHERE operation_id=?", (operation_id,))
                c.execute("DELETE FROM production_operations WHERE id=?", (operation_id,))
            if order_id:
                c.execute("DELETE FROM production_semifinished WHERE order_id=?", (order_id,))
                c.execute("DELETE FROM production_cost_layers WHERE production_order_id=?", (order_id,))
                c.execute("DELETE FROM production_bom_items WHERE id=?", (bom_item_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='production_order' AND entity_id=?", (order_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='production_order' AND entity_id=?", (order_id,))
                c.execute("DELETE FROM production_orders WHERE id=?", (order_id,))
            if calendar_id:
                c.execute("DELETE FROM work_center_calendars WHERE id=?", (calendar_id,))
            if work_center_id:
                c.execute("DELETE FROM work_centers WHERE id=?", (work_center_id,))
            if bom_version_id:
                c.execute("DELETE FROM bom_versions WHERE id=?", (bom_version_id,))
            if bom_master_id:
                c.execute("DELETE FROM bom_master WHERE id=?", (bom_master_id,))
            conn.commit()
            conn.close()
