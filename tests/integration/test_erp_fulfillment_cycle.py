import time
import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class ERPFullfillmentCycleTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="Fulfillment Director")

    def tearDown(self):
        delete_test_user(self.user["email"])

    def test_sales_order_shortage_creates_supply_and_three_way_match(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        stamp = f"{int(time.time())}-{id(self)}"
        article = f"QA-FULFILL-{stamp}"
        client_id = 0
        order_id = 0
        request_id = 0
        purchase_id = 0
        receipt_id = 0
        document_id = 0
        try:
            client = self.client.post("/api/clients", json={
                "name": f"QA Fulfillment Client {stamp}",
                "inn": f"77{int(time.time()) % 100000000:08d}",
                "contact": "fulfillment@example.com",
            })
            self.assertEqual(client.status_code, 200)
            conn = get_connection()
            row = conn.execute("SELECT id FROM clients WHERE name=?", (f"QA Fulfillment Client {stamp}",)).fetchone()
            client_id = int(row[0])
            conn.close()

            order = self.client.post("/api/sales/customer_orders", json={
                "client_id": client_id,
                "order_number": f"SO-FUL-{stamp}",
                "article": article,
                "item_name": "QA fulfillment item",
                "qty": 6,
                "unit": "шт",
                "unit_price": 1000,
                "amount": 6000,
                "currency": "RUB",
                "requested_ship_date": (datetime.now() + timedelta(days=4)).strftime("%d.%m.%Y"),
                "payment_terms": "100%",
                "status": "confirmed",
                "comment": "shortage should create supply",
            })
            self.assertEqual(order.status_code, 200)
            payload = order.json()
            order_id = int(payload["id"])
            self.assertEqual(payload["fulfillment"]["status"], "success")
            request_id = int(payload["fulfillment"]["procurement_request_id"])
            purchase_id = int(payload["fulfillment"]["purchase_order_id"])

            plans = self.client.get(f"/api/fulfillment/plans?demand_type=sales_customer_order&demand_id={order_id}")
            self.assertEqual(plans.status_code, 200)
            self.assertTrue(any(float(row["planned_purchase_qty"]) == 6 for row in plans.json()))

            links = self.client.get(f"/api/fulfillment/supply_links?demand_id={order_id}&supply_type=purchase_order")
            self.assertEqual(links.status_code, 200)
            self.assertTrue(any(int(row["supply_id"]) == purchase_id for row in links.json()))

            receipt = self.client.post("/api/procurement/receipts", json={
                "purchase_id": purchase_id,
                "request_id": request_id,
                "receipt_date": datetime.now().strftime("%d.%m.%Y"),
                "article": article,
                "item_name": "QA fulfillment item",
                "accepted_qty": 6,
                "rejected_qty": 0,
                "warehouse": "QA Fulfillment WH",
                "bin_code": "F-01",
                "quality_status": "accepted",
                "status": "posted",
                "unit_cost": 1000,
                "comment": "three-way receipt",
            })
            self.assertEqual(receipt.status_code, 200)
            receipt_id = int(receipt.json()["id"])
            self.assertEqual(receipt.json()["matching"]["status"], "pending")

            document = self.client.post("/api/procurement/documents", json={
                "purchase_id": purchase_id,
                "request_id": request_id,
                "doc_type": "upd",
                "doc_number": f"UPD-FUL-{stamp}",
                "doc_date": datetime.now().strftime("%d.%m.%Y"),
                "amount": 6000,
                "vat_amount": 1000,
                "currency": "RUB",
                "status": "accepted",
                "payment_due_date": (datetime.now() + timedelta(days=10)).strftime("%d.%m.%Y"),
                "comment": "matching invoice",
            })
            self.assertEqual(document.status_code, 200, document.text)
            document_id = int(document.json()["id"])
            self.assertEqual(document.json()["matching"]["status"], "matched")

            matches = self.client.get(f"/api/procurement/three_way_matches?purchase_id={purchase_id}&status=matched")
            self.assertEqual(matches.status_code, 200)
            self.assertTrue(any(int(row["invoice_id"]) == document_id for row in matches.json()))

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM accounting_entries WHERE source_type='purchase_document' AND source_id=?", (document_id,))
            self.assertEqual(int(c.fetchone()[0]), 1)
            c.execute("SELECT COUNT(*) FROM vat_purchase_book WHERE source_type='purchase_document' AND source_id=?", (document_id,))
            self.assertGreaterEqual(int(c.fetchone()[0]), 1)
            conn.close()
        finally:
            conn = get_connection()
            c = conn.cursor()
            if document_id:
                c.execute("DELETE FROM vat_purchase_book WHERE source_type='purchase_document' AND source_id=?", (document_id,))
                c.execute("DELETE FROM tax_registers WHERE source_type='purchase_document' AND source_id=?", (document_id,))
                c.execute("DELETE FROM accounting_registers WHERE source_type='purchase_document' AND source_id=?", (document_id,))
                c.execute("DELETE FROM accounting_entries WHERE source_type='purchase_document' AND source_id=?", (document_id,))
                c.execute("DELETE FROM invoice_matching_results WHERE invoice_id=?", (document_id,))
                c.execute("DELETE FROM purchase_documents WHERE id=?", (document_id,))
            if purchase_id:
                c.execute("DELETE FROM three_way_matches WHERE purchase_id=?", (purchase_id,))
                c.execute("DELETE FROM supplier_discrepancy_acts WHERE purchase_id=?", (purchase_id,))
                c.execute("DELETE FROM supply_demand_links WHERE supply_id=? AND supply_type='purchase_order'", (purchase_id,))
                c.execute("DELETE FROM purchase_orders WHERE id=?", (purchase_id,))
            if receipt_id:
                c.execute("DELETE FROM purchase_receipts WHERE id=?", (receipt_id,))
                c.execute("DELETE FROM inventory_cost_layers WHERE source_type='purchase_receipt' AND source_id=?", (receipt_id,))
                c.execute("DELETE FROM stock_movements WHERE document_type='purchase_receipt' AND document_id=?", (receipt_id,))
            if request_id:
                c.execute("DELETE FROM procurement_requests WHERE id=?", (request_id,))
            if order_id:
                c.execute("DELETE FROM fulfillment_plan WHERE demand_type='sales_customer_order' AND demand_id=?", (order_id,))
                c.execute("DELETE FROM sales_customer_orders WHERE id=?", (order_id,))
            if article:
                c.execute("DELETE FROM inventory_lots WHERE article=?", (article,))
                c.execute("DELETE FROM inventory_balances WHERE article=?", (article,))
            if client_id:
                c.execute("DELETE FROM clients WHERE id=?", (client_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
