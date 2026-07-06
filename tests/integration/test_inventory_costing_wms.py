import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class InventoryCostingWMSIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="WMS Cost Director")

    def tearDown(self):
        delete_test_user(self.user["email"])

    def test_fifo_fefo_cost_layers_packages_and_pick_strategy(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        stamp = f"{int(time.time())}-{id(self)}"
        article = f"QA-WMS-COST-{stamp}"
        wh = f"QA WH {stamp}"
        bin_a = "A-01"
        bin_b = "B-01"
        reservation_id = 0
        wave_id = 0
        pick_task_id = 0
        doc_ids = []

        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
            c.execute(
                "INSERT INTO nomenclature (article, name, unit, price, stock, currency, group_name, default_warehouse, exchange_state, external_sync_id) VALUES (?, ?, 'шт', 0, 0, 'RUB', 'QA', ?, 'queued', '')",
                (article, "QA WMS cost item", wh),
            )
            conn.commit()
            conn.close()

            policy = self.client.post("/api/stock/policy", json={
                "cost_method": "fifo",
                "allow_negative_stock": 0,
                "auto_pick_strategy": "fefo",
                "comment": "QA FEFO costing",
            })
            self.assertEqual(policy.status_code, 200)
            self.assertEqual(policy.json()["status"], "success")

            package = self.client.post("/api/stock/item_packages", json={
                "article": article,
                "package_code": "BOX",
                "package_name": "Box",
                "unit": "шт",
                "qty_per_package": 5,
                "is_default": 1,
                "comment": "QA package",
            })
            self.assertEqual(package.status_code, 200)
            self.assertEqual(package.json()["status"], "success")

            first_receipt = self.client.post("/api/stock/documents", json={
                "doc_type": "receipt_adjustment",
                "doc_number": f"QA-RCV-A-{stamp}",
                "article": article,
                "warehouse": wh,
                "bin_code": bin_a,
                "batch_code": "LOT-A",
                "lot_expiration_date": "01.05.2026",
                "qty": 2,
                "package_code": "BOX",
                "package_qty": 2,
                "unit_cost": 10,
                "comment": "late expiry receipt",
            })
            self.assertEqual(first_receipt.status_code, 200)
            self.assertEqual(first_receipt.json()["status"], "success")
            doc_ids.append(int(first_receipt.json()["id"]))

            second_receipt = self.client.post("/api/stock/documents", json={
                "doc_type": "receipt_adjustment",
                "doc_number": f"QA-RCV-B-{stamp}",
                "article": article,
                "warehouse": wh,
                "bin_code": bin_b,
                "batch_code": "LOT-B",
                "lot_expiration_date": "25.04.2026",
                "qty": 5,
                "unit_cost": 20,
                "comment": "earliest expiry receipt",
            })
            self.assertEqual(second_receipt.status_code, 200)
            self.assertEqual(second_receipt.json()["status"], "success")
            doc_ids.append(int(second_receipt.json()["id"]))

            reservation = self.client.post("/api/stock/reservations", json={
                "nomenclature_article": article,
                "nomenclature_name": "QA WMS cost item",
                "qty": 3,
                "status": "reserved",
                "comment": "FEFO reserve should pick LOT-B",
            })
            self.assertEqual(reservation.status_code, 200)
            self.assertEqual(reservation.json()["status"], "success")
            self.assertEqual(reservation.json()["reservation_status"], "reserved")
            self.assertEqual(reservation.json()["batch_code"], "LOT-B")
            self.assertEqual(reservation.json()["bin_code"], bin_b)
            reservation_id = int(reservation.json()["id"])

            wave = self.client.post("/api/wms/pick_waves", json={
                "reservation_ids": [reservation_id],
                "priority": "high",
                "comment": "FEFO wave",
            })
            self.assertEqual(wave.status_code, 200)
            wave_id = int(wave.json()["id"])

            release = self.client.post(f"/api/wms/pick_waves/{wave_id}/release")
            self.assertEqual(release.status_code, 200)

            tasks = self.client.get("/api/wms/pick_tasks")
            self.assertEqual(tasks.status_code, 200)
            task = next(row for row in tasks.json() if int(row["wave_id"]) == wave_id)
            self.assertEqual(task["batch_code"], "LOT-B")
            pick_task_id = int(task["id"])

            pick = self.client.post(f"/api/wms/pick_tasks/{pick_task_id}/pick")
            self.assertEqual(pick.status_code, 200)
            self.assertEqual(pick.json()["status"], "success")

            conn = get_connection(row_factory=True)
            c = conn.cursor()
            lot_b = dict(c.execute("SELECT qty, lot_expiration_date FROM inventory_lots WHERE article=? AND batch_code='LOT-B'", (article,)).fetchone() or {})
            issue = dict(c.execute("SELECT qty, unit_cost, amount FROM inventory_cost_layers WHERE article=? AND layer_kind='issue' ORDER BY id DESC LIMIT 1", (article,)).fetchone() or {})
            remaining = dict(c.execute("SELECT COALESCE(SUM(remaining_qty), 0) AS qty, COALESCE(SUM(remaining_qty * unit_cost), 0) AS amount FROM inventory_cost_layers WHERE article=? AND remaining_qty > 0", (article,)).fetchone() or {})
            conn.close()

            self.assertEqual(float(lot_b["qty"]), 2.0)
            self.assertEqual(lot_b["lot_expiration_date"], "2026-04-25")
            self.assertEqual(float(issue["qty"]), -3.0)
            self.assertEqual(float(issue["unit_cost"]), 20.0)
            self.assertEqual(float(issue["amount"]), -60.0)
            self.assertEqual(float(remaining["qty"]), 12.0)
            self.assertEqual(float(remaining["amount"]), 140.0)

            cost_summary = self.client.get(f"/api/stock/cost_layers?article={article}")
            self.assertEqual(cost_summary.status_code, 200)
            self.assertEqual(float(cost_summary.json()["totals"]["amount"]), 140.0)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if pick_task_id:
                c.execute("DELETE FROM wms_pick_tasks WHERE id=?", (pick_task_id,))
            if wave_id:
                c.execute("DELETE FROM wms_pick_tasks WHERE wave_id=?", (wave_id,))
                c.execute("DELETE FROM wms_pick_waves WHERE id=?", (wave_id,))
            if reservation_id:
                c.execute("DELETE FROM stock_reservations WHERE id=?", (reservation_id,))
            c.execute("DELETE FROM inventory_cost_layers WHERE article=?", (article,))
            c.execute("DELETE FROM unit_conversions WHERE article=?", (article,))
            c.execute("DELETE FROM item_packages WHERE article=?", (article,))
            c.execute("DELETE FROM stock_movements WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_documents WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_lots WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_balances WHERE article=?", (article,))
            c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
            conn.commit()
            conn.close()
