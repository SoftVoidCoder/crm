import time
import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class SalesFullCycleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="Sales Director")

    def tearDown(self):
        delete_test_user(self.user["email"])

    def test_sales_quote_order_reserve_ship_ar_and_margin_flow(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        stamp = f"{int(time.time())}-{id(self)}"
        article = f"QA-SALES-FULL-{stamp}"
        warehouse = "QA Sales WH"
        bin_code = "S-01"
        batch_code = f"SALES-LOT-{stamp}"
        client_id = 0
        quote_id = 0
        order_id = 0
        reservation_id = 0
        sales_document_id = 0
        schedule_id = 0
        payment_id = 0
        shipment_id = 0
        purchase_id = 0
        margin_id = 0
        try:
            client = self.client.post("/api/clients", json={
                "name": f"QA Sales Full Client {stamp}",
                "inn": f"77{int(time.time()) % 100000000:08d}",
                "contact": "sales-full@example.com",
            })
            self.assertEqual(client.status_code, 200)
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (f"QA Sales Full Client {stamp}",))
            client_id = int(c.fetchone()[0])

            now = int(time.time())
            c.execute(
                "INSERT INTO nomenclature (article, name, unit, price, stock, currency, group_name, default_warehouse, exchange_state, external_sync_id) VALUES (?, 'QA Sales Full Item', 'шт', 60000, 8, 'RUB', 'QA', ?, 'queued', '')",
                (article, warehouse),
            )
            c.execute(
                "INSERT INTO inventory_balances (article, warehouse, bin_code, qty, updated_at) VALUES (?, ?, ?, 8, ?) ON CONFLICT(article, warehouse, bin_code) DO UPDATE SET qty=EXCLUDED.qty, updated_at=EXCLUDED.updated_at",
                (article, warehouse, bin_code, now),
            )
            c.execute(
                "INSERT INTO inventory_lots (article, warehouse, bin_code, batch_code, serial_no, qty, updated_at) VALUES (?, ?, ?, ?, '', 8, ?) ON CONFLICT(article, warehouse, bin_code, batch_code, serial_no) DO UPDATE SET qty=EXCLUDED.qty, updated_at=EXCLUDED.updated_at",
                (article, warehouse, bin_code, batch_code, now),
            )
            c.execute(
                """
                INSERT INTO purchase_orders (client_id, item_article, item_name, supplier, qty, unit, unit_price, total_amount, status, expected_date, created_by, created_at, updated_at)
                VALUES (?, ?, 'QA Sales Full Item', 'QA Supplier', 8, 'шт', 60000, 480000, 'received', ?, ?, ?, ?)
                """,
                (client_id, article, datetime.now().strftime("%d.%m.%Y"), self.user["email"], now, now),
            )
            purchase_id = int(c.lastrowid)
            conn.commit()
            conn.close()

            quote = self.client.post("/api/sales/quotes", json={
                "client_id": client_id,
                "title": "QA full-cycle commercial offer",
                "quote_number": f"Q-FULL-{stamp}",
                "stage": "proposal",
                "amount": 300000,
                "currency": "RUB",
                "valid_until": (datetime.now() + timedelta(days=7)).strftime("%d.%m.%Y"),
                "probability": 80,
                "comment": "quote for full sales contour",
            })
            self.assertEqual(quote.status_code, 200)
            quote_id = int(quote.json()["id"])

            order = self.client.post("/api/sales/customer_orders", json={
                "quote_id": quote_id,
                "client_id": client_id,
                "order_number": f"SO-FULL-{stamp}",
                "article": article,
                "item_name": "QA Sales Full Item",
                "qty": 4,
                "unit_price": 75000,
                "amount": 300000,
                "currency": "RUB",
                "requested_ship_date": (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y"),
                "payment_terms": "50/50",
                "status": "confirmed",
                "comment": "full sales order",
            })
            self.assertEqual(order.status_code, 200)
            order_id = int(order.json()["id"])

            reserve = self.client.post(f"/api/sales/customer_orders/{order_id}/reserve", json={
                "warehouse": warehouse,
                "bin_code": bin_code,
                "batch_code": batch_code,
                "qty": 4,
                "comment": "reserve full sales order",
            })
            self.assertEqual(reserve.status_code, 200)
            self.assertEqual(reserve.json()["reserve_status"], "reserved")
            reservation_id = int(reserve.json()["id"])

            document = self.client.post(f"/api/sales/customer_orders/{order_id}/create_document")
            self.assertEqual(document.status_code, 200)
            self.assertEqual(document.json()["status"], "success")
            sales_document_id = int(document.json()["id"])

            schedule = self.client.post("/api/sales/payment_schedules", json={
                "customer_order_id": order_id,
                "sales_document_id": sales_document_id,
                "due_date": (datetime.now() + timedelta(days=5)).strftime("%d.%m.%Y"),
                "amount": 300000,
                "currency": "RUB",
                "status": "planned",
                "comment": "AR schedule",
            })
            self.assertEqual(schedule.status_code, 200)
            schedule_id = int(schedule.json()["id"])
            payment_id = int(schedule.json()["payment_id"])
            self.assertGreater(payment_id, 0)

            shipment = self.client.post("/api/sales/shipments", json={
                "customer_order_id": order_id,
                "sales_document_id": sales_document_id,
                "reservation_id": reservation_id,
                "article": article,
                "item_name": "QA Sales Full Item",
                "qty": 4,
                "warehouse": warehouse,
                "bin_code": bin_code,
                "batch_code": batch_code,
                "carrier": "QA Carrier",
                "status": "planned",
                "comment": "shipment task",
            })
            self.assertEqual(shipment.status_code, 200)
            shipment_id = int(shipment.json()["id"])

            ship = self.client.post(f"/api/sales/shipments/{shipment_id}/ship")
            self.assertEqual(ship.status_code, 200)
            self.assertEqual(ship.json()["status"], "success")

            margin = self.client.post("/api/sales/deal_margins/recalculate", json={
                "customer_order_id": order_id,
                "direct_cost_amount": 10000,
                "discount_amount": 0,
            })
            self.assertEqual(margin.status_code, 200)
            margin_id = int(margin.json()["id"])

            paid = self.client.post(f"/api/sales/payment_schedules/{schedule_id}/mark_paid")
            self.assertEqual(paid.status_code, 200)
            self.assertEqual(paid.json()["status"], "success")

            conn = get_connection(row_factory=True)
            c = conn.cursor()
            c.execute("SELECT qty FROM inventory_balances WHERE article=? AND warehouse=? AND bin_code=?", (article, warehouse, bin_code))
            balance = c.fetchone()
            self.assertEqual(float(balance["qty"]), 4)
            c.execute("SELECT status, fulfilled_qty FROM stock_reservations WHERE id=?", (reservation_id,))
            reservation = c.fetchone()
            self.assertEqual(reservation["status"], "fulfilled")
            self.assertEqual(float(reservation["fulfilled_qty"]), 4)
            c.execute("SELECT status FROM finance_payments WHERE id=?", (payment_id,))
            payment = c.fetchone()
            self.assertEqual(payment["status"], "paid")
            conn.close()

            summary = self.client.get("/api/sales/extended_summary")
            self.assertEqual(summary.status_code, 200)
            payload = summary.json()
            self.assertGreaterEqual(payload["metrics"]["customer_orders_open"], 1)
            self.assertGreaterEqual(payload["metrics"]["deal_margin_amount"], 1)
            self.assertTrue(any(int(row["id"]) == order_id for row in payload["customer_orders"]))
            self.assertTrue(any(int(row["id"]) == shipment_id and row["status"] == "shipped" for row in payload["shipments"]))
            self.assertTrue(any(int(row["id"]) == schedule_id and row["status"] == "paid" for row in payload["payment_schedules"]))
            self.assertTrue(any(int(row["id"]) == margin_id and float(row["margin_percent"]) > 0 for row in payload["deal_margins"]))
        finally:
            conn = get_connection()
            c = conn.cursor()
            if margin_id:
                c.execute("DELETE FROM sales_deal_margins WHERE id=?", (margin_id,))
            if shipment_id:
                c.execute("DELETE FROM sales_shipments WHERE id=?", (shipment_id,))
            if schedule_id:
                c.execute("DELETE FROM sales_payment_schedules WHERE id=?", (schedule_id,))
            if payment_id:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
                c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
            if sales_document_id:
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='sales_document' AND entity_id=?", (sales_document_id,))
                c.execute("DELETE FROM sales_documents_extended WHERE id=?", (sales_document_id,))
            if reservation_id:
                c.execute("DELETE FROM stock_reservations WHERE id=?", (reservation_id,))
            if order_id:
                c.execute("DELETE FROM sales_customer_orders WHERE id=?", (order_id,))
            if quote_id:
                c.execute("DELETE FROM sales_quotes WHERE id=?", (quote_id,))
            if purchase_id:
                c.execute("DELETE FROM purchase_orders WHERE id=?", (purchase_id,))
            c.execute("DELETE FROM stock_movements WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_lots WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_balances WHERE article=?", (article,))
            c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
            if client_id:
                c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
