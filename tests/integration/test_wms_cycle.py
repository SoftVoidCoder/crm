import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class WMSCycleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="WMS Director")

    def tearDown(self):
        delete_test_user(self.user["email"])

    def _balance_qty(self, article, warehouse, bin_code):
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT COALESCE(SUM(qty), 0) FROM inventory_balances WHERE article=? AND warehouse=? AND bin_code=?",
            (article, warehouse, bin_code),
        )
        qty = float(c.fetchone()[0] or 0)
        conn.close()
        return round(qty, 3)

    def test_wms_putaway_pick_cycle_count_flow(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        stamp = f"{int(time.time())}-{id(self)}"
        article = f"QA-WMS-{stamp}"
        source_wh = "QA WMS Receive"
        source_bin = "IN-01"
        target_wh = "QA WMS Main"
        target_bin = "A-01"
        batch_code = f"LOT-WMS-{stamp}"
        reservation_id = 0
        putaway_id = 0
        wave_id = 0
        pick_task_id = 0
        count_id = 0
        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
            c.execute(
                "INSERT INTO nomenclature (article, name, unit, price, stock, currency, group_name, default_warehouse, exchange_state, external_sync_id) VALUES (?, ?, 'шт', 0, 10, 'RUB', 'QA', ?, 'queued', '')",
                (article, "QA WMS item", target_wh),
            )
            c.execute(
                """
                INSERT INTO inventory_balances (article, warehouse, bin_code, qty, updated_at)
                VALUES (?, ?, ?, 10, ?)
                ON CONFLICT(article, warehouse, bin_code) DO UPDATE SET qty=EXCLUDED.qty, updated_at=EXCLUDED.updated_at
                """,
                (article, source_wh, source_bin, int(time.time())),
            )
            c.execute(
                """
                INSERT INTO inventory_lots (article, warehouse, bin_code, batch_code, serial_no, qty, updated_at)
                VALUES (?, ?, ?, ?, '', 10, ?)
                ON CONFLICT(article, warehouse, bin_code, batch_code, serial_no) DO UPDATE SET qty=EXCLUDED.qty, updated_at=EXCLUDED.updated_at
                """,
                (article, source_wh, source_bin, batch_code, int(time.time())),
            )
            conn.commit()
            conn.close()

            cell_source = self.client.post("/api/wms/cells", json={
                "warehouse": source_wh,
                "bin_code": source_bin,
                "zone_name": "Receiving",
                "cell_type": "receiving",
                "capacity_qty": 20,
                "status": "active",
            })
            self.assertEqual(cell_source.status_code, 200)
            self.assertEqual(cell_source.json().get("status"), "success")

            cell_target = self.client.post("/api/wms/cells", json={
                "warehouse": target_wh,
                "bin_code": target_bin,
                "zone_name": "Pick",
                "cell_type": "pick",
                "capacity_qty": 8,
                "abc_class": "A",
                "status": "active",
            })
            self.assertEqual(cell_target.status_code, 200)
            self.assertEqual(cell_target.json().get("status"), "success")

            putaway = self.client.post("/api/wms/putaway_tasks", json={
                "article": article,
                "item_name": "QA WMS item",
                "qty": 6,
                "source_warehouse": source_wh,
                "source_bin": source_bin,
                "target_warehouse": target_wh,
                "target_bin": target_bin,
                "batch_code": batch_code,
                "priority": "high",
                "comment": "integration putaway",
            })
            self.assertEqual(putaway.status_code, 200)
            self.assertEqual(putaway.json().get("status"), "success")
            putaway_id = int(putaway.json()["id"])

            complete = self.client.post(f"/api/wms/putaway_tasks/{putaway_id}/complete")
            self.assertEqual(complete.status_code, 200)
            self.assertEqual(complete.json().get("status"), "success")
            self.assertEqual(self._balance_qty(article, source_wh, source_bin), 4)
            self.assertEqual(self._balance_qty(article, target_wh, target_bin), 6)

            reserve = self.client.post("/api/stock/reservations", json={
                "project_id": 0,
                "nomenclature_article": article,
                "nomenclature_name": "QA WMS item",
                "qty": 3,
                "status": "reserved",
                "warehouse": target_wh,
                "bin_code": target_bin,
                "batch_code": batch_code,
                "comment": "integration WMS reserve",
            })
            self.assertEqual(reserve.status_code, 200)
            self.assertEqual(reserve.json().get("status"), "success")
            self.assertEqual(reserve.json().get("reservation_status"), "reserved")
            reservation_id = int(reserve.json()["id"])

            wave = self.client.post("/api/wms/pick_waves", json={
                "reservation_ids": [reservation_id],
                "priority": "high",
                "comment": "integration wave",
            })
            self.assertEqual(wave.status_code, 200)
            self.assertEqual(wave.json().get("status"), "success")
            wave_id = int(wave.json()["id"])

            release = self.client.post(f"/api/wms/pick_waves/{wave_id}/release")
            self.assertEqual(release.status_code, 200)
            self.assertEqual(release.json().get("status"), "success")

            tasks = self.client.get("/api/wms/pick_tasks")
            self.assertEqual(tasks.status_code, 200)
            task = next(row for row in tasks.json() if int(row["wave_id"]) == wave_id)
            pick_task_id = int(task["id"])
            pick = self.client.post(f"/api/wms/pick_tasks/{pick_task_id}/pick")
            self.assertEqual(pick.status_code, 200)
            self.assertEqual(pick.json().get("status"), "success")
            self.assertEqual(self._balance_qty(article, target_wh, target_bin), 3)

            conn = get_connection(row_factory=True)
            c = conn.cursor()
            c.execute("SELECT status, fulfilled_qty FROM stock_reservations WHERE id=?", (reservation_id,))
            reservation_row = c.fetchone()
            conn.close()
            self.assertEqual(reservation_row["status"], "fulfilled")
            self.assertEqual(float(reservation_row["fulfilled_qty"]), 3)

            count = self.client.post("/api/wms/cycle_counts", json={
                "warehouse": target_wh,
                "bin_code": target_bin,
                "comment": "integration cycle count",
            })
            self.assertEqual(count.status_code, 200)
            self.assertEqual(count.json().get("status"), "success")
            count_id = int(count.json()["id"])

            line = self.client.post(f"/api/wms/cycle_counts/{count_id}/lines", json={
                "article": article,
                "item_name": "QA WMS item",
                "warehouse": target_wh,
                "bin_code": target_bin,
                "batch_code": batch_code,
                "expected_qty": 3,
                "counted_qty": 2,
                "comment": "integration variance",
            })
            self.assertEqual(line.status_code, 200)
            self.assertEqual(line.json().get("status"), "success")

            close = self.client.post(f"/api/wms/cycle_counts/{count_id}/close")
            self.assertEqual(close.status_code, 200)
            self.assertEqual(close.json().get("status"), "success")
            self.assertEqual(self._balance_qty(article, target_wh, target_bin), 2)

            summary = self.client.get("/api/wms/summary")
            self.assertEqual(summary.status_code, 200)
            payload = summary.json()
            self.assertGreaterEqual(payload["metrics"]["cells"], 2)
            self.assertTrue(any(int(row["id"]) == count_id and row["status"] == "closed" for row in payload["cycle_counts"]))
            self.assertTrue(any(row["article"] == article and row["batch_code"] == batch_code for row in payload["lot_positions"]))

            stock_summary = self.client.get("/api/stock/extended_summary")
            self.assertEqual(stock_summary.status_code, 200)
            self.assertGreaterEqual(stock_summary.json()["metrics"]["wms_cells"], 2)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if count_id:
                c.execute("DELETE FROM wms_cycle_count_lines WHERE count_id=?", (count_id,))
                c.execute("DELETE FROM wms_cycle_counts WHERE id=?", (count_id,))
            if pick_task_id:
                c.execute("DELETE FROM wms_pick_tasks WHERE id=?", (pick_task_id,))
            if wave_id:
                c.execute("DELETE FROM wms_pick_tasks WHERE wave_id=?", (wave_id,))
                c.execute("DELETE FROM wms_pick_waves WHERE id=?", (wave_id,))
            if putaway_id:
                c.execute("DELETE FROM wms_putaway_tasks WHERE id=?", (putaway_id,))
            if reservation_id:
                c.execute("DELETE FROM stock_reservations WHERE id=?", (reservation_id,))
            c.execute("DELETE FROM wms_cell_profiles WHERE warehouse IN (?, ?)", (source_wh, target_wh))
            c.execute("DELETE FROM stock_movements WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_acts WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_documents WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_lots WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_balances WHERE article=?", (article,))
            c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
