import time
import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class ProductionMrpApsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="MRP APS Director")

    def tearDown(self):
        delete_test_user(self.user["email"])

    def test_mrp_aps_calculates_shortages_capacity_schedule_and_run_snapshot(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        now = int(time.time())
        stamp = f"{now}-{id(self)}"
        article = f"QA-MRP-{stamp}"
        work_center = f"QA APS Center {stamp}"
        planned_start = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
        shift_date = (datetime.now() + timedelta(days=3)).strftime("%d.%m.%Y")
        planned_finish = (datetime.now() + timedelta(days=7)).strftime("%d.%m.%Y")

        order_id = 0
        material_norm_id = 0
        labor_norm_id = 0
        shift_id = 0
        scenario_id = 0
        run_id = 0
        try:
            order_res = self.client.post("/api/production/orders", json={
                "project_id": 0,
                "client_id": 0,
                "order_name": f"QA MRP APS Order {stamp}",
                "stage": "queue",
                "priority": "high",
                "planned_start": planned_start,
                "planned_finish": planned_finish,
                "actual_finish": "",
                "progress": 20,
                "responsible": "QA Planner",
                "route_name": work_center,
                "planned_qty": 10,
                "produced_qty": 2,
                "scrap_qty": 0,
                "planned_cost": 10000,
                "actual_cost": 1000,
                "labor_hours_plan": 4,
                "labor_hours_fact": 1,
                "comment": "MRP/APS integration",
            })
            self.assertEqual(order_res.status_code, 200)
            order_id = int(order_res.json()["id"])

            mat_res = self.client.post("/api/production/material_norms/deep", json={
                "order_id": order_id,
                "article": article,
                "item_name": "QA deficit material",
                "unit": "шт",
                "norm_qty": 3,
                "scrap_rate": 10,
                "substitute_article": "",
                "comment": "MRP shortage norm",
            })
            self.assertEqual(mat_res.status_code, 200)
            material_norm_id = int(mat_res.json()["id"])

            labor_res = self.client.post("/api/production/labor_norms/deep", json={
                "order_id": order_id,
                "operation_name": "QA APS operation",
                "work_center": work_center,
                "norm_hours": 4,
                "rate_per_hour": 1000,
                "team_size": 1,
                "comment": "APS capacity norm",
            })
            self.assertEqual(labor_res.status_code, 200)
            labor_norm_id = int(labor_res.json()["id"])

            shift_res = self.client.post("/api/production/shifts/deep", json={
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "shift_date": shift_date,
                "shift_name": "QA APS shift",
                "work_center": work_center,
                "capacity_hours": 8,
                "team_name": "QA team",
                "supervisor_name": "QA Planner",
                "status": "active",
                "comment": "APS capacity bucket",
            })
            self.assertEqual(shift_res.status_code, 200)
            shift_id = int(shift_res.json()["id"])

            conn = get_connection()
            conn.execute(
                "INSERT INTO inventory_balances (article, warehouse, bin_code, qty, updated_at) VALUES (?, ?, ?, ?, ?)",
                (article, "QA-MRP", stamp, 5, now),
            )
            conn.commit()
            conn.close()

            scenario_res = self.client.post("/api/production/mrp_aps/scenarios", json={
                "scenario_name": f"QA MRP APS Scenario {stamp}",
                "planning_horizon_days": 30,
                "demand_mode": "confirmed_orders",
                "status": "active",
                "demand_multiplier": 1,
                "capacity_multiplier": 1,
                "lead_time_days": 0,
                "freeze_days": 0,
                "comment": "MRP/APS integration scenario",
            })
            self.assertEqual(scenario_res.status_code, 200)
            scenario_id = int(scenario_res.json()["id"])

            run_res = self.client.post("/api/production/mrp_aps/run", json={
                "scenario_id": scenario_id,
                "run_name": f"QA MRP APS Run {stamp}",
                "persist": 1,
            })
            self.assertEqual(run_res.status_code, 200)
            run_payload = run_res.json()
            run_id = int(run_payload["id"])
            plan = run_payload["plan"]

            self.assertGreaterEqual(plan["metrics"]["shortages"], 1)
            self.assertGreater(plan["metrics"]["scheduled_hours"], 0)
            self.assertGreaterEqual(len(plan["capacity_plan"]), 1)
            self.assertTrue(any(item["article"] == article for item in plan["shortages"]))
            self.assertTrue(any(item["work_center"] == work_center for item in plan["schedule_assignments"]))

            summary_res = self.client.get(f"/api/production/mrp_aps/summary?scenario_id={scenario_id}")
            self.assertEqual(summary_res.status_code, 200)
            summary_payload = summary_res.json()
            self.assertIn("runs", summary_payload)
            self.assertTrue(any(int(item["id"]) == run_id for item in summary_payload["runs"]))

            deep_res = self.client.get("/api/production/deep_summary")
            self.assertEqual(deep_res.status_code, 200)
            deep_payload = deep_res.json()
            self.assertIn("mrp_aps", deep_payload)
            self.assertGreaterEqual(deep_payload["metrics"]["mrp_shortages"], 1)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if run_id:
                c.execute("DELETE FROM production_mrp_runs WHERE id=?", (run_id,))
            if scenario_id:
                c.execute("DELETE FROM production_planning_scenarios WHERE id=?", (scenario_id,))
            c.execute("DELETE FROM inventory_balances WHERE article=?", (article,))
            if shift_id:
                c.execute("DELETE FROM production_shifts WHERE id=?", (shift_id,))
            if material_norm_id:
                c.execute("DELETE FROM production_material_norms WHERE id=?", (material_norm_id,))
            if labor_norm_id:
                c.execute("DELETE FROM production_labor_norms WHERE id=?", (labor_norm_id,))
            if order_id:
                c.execute("DELETE FROM production_operations WHERE order_id=?", (order_id,))
                c.execute("DELETE FROM production_orders WHERE id=?", (order_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='production_order' AND entity_id=?", (order_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='production_order' AND entity_id=?", (order_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
