import time
import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class ProcurementCycleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="Procurement Director")

    def tearDown(self):
        delete_test_user(self.user["email"])

    def test_procurement_request_tender_purchase_receipt_document_and_sla(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        stamp = f"{int(time.time())}-{id(self)}"
        article = f"QA-PROC-{stamp}"
        supplier_id = 0
        request_id = 0
        tender_id = 0
        bid_id = 0
        purchase_id = 0
        receipt_id = 0
        document_id = 0
        try:
            supplier = self.client.post("/api/suppliers", json={
                "supplier_name": f"QA Procurement Supplier {stamp}",
                "inn": f"77{int(time.time()) % 100000000:08d}",
                "category": "QA",
                "rating": 4.7,
                "lead_time_days": 3,
                "reliability_percent": 96,
                "payment_terms": "10 дней",
                "comment": "supplier for procurement cycle",
            })
            self.assertEqual(supplier.status_code, 200)
            supplier_id = int(supplier.json()["id"])

            required_date = (datetime.now() + timedelta(days=5)).strftime("%d.%m.%Y")
            request_res = self.client.post("/api/procurement/requests", json={
                "title": f"QA Procurement Request {stamp}",
                "item_article": article,
                "item_name": "QA procurement material",
                "qty": 12,
                "unit": "шт",
                "target_unit_price": 900,
                "required_date": required_date,
                "priority": "high",
                "status": "approved",
                "comment": "integration request",
            })
            self.assertEqual(request_res.status_code, 200)
            request_id = int(request_res.json()["id"])

            tender_res = self.client.post("/api/procurement/tenders", json={
                "request_id": request_id,
                "title": f"QA RFQ {stamp}",
                "due_date": (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y"),
                "status": "collecting_bids",
                "criteria": {"price_weight": 50, "lead_time_weight": 30, "reliability_weight": 20},
                "comment": "integration tender",
            })
            self.assertEqual(tender_res.status_code, 200)
            tender_id = int(tender_res.json()["id"])

            bid_res = self.client.post("/api/procurement/tender_bids", json={
                "tender_id": tender_id,
                "supplier_id": supplier_id,
                "price": 850,
                "currency": "RUB",
                "lead_time_days": 2,
                "payment_terms": "10 дней",
                "warranty_terms": "12 месяцев",
                "score": 92,
                "status": "submitted",
                "comment": "best bid",
            })
            self.assertEqual(bid_res.status_code, 200)
            bid_id = int(bid_res.json()["id"])

            award_res = self.client.post(f"/api/procurement/tenders/{tender_id}/award", json={
                "bid_id": bid_id,
                "decision_comment": "integration award",
                "create_purchase": 1,
            })
            self.assertEqual(award_res.status_code, 200)
            purchase_id = int(award_res.json()["purchase_id"])
            self.assertGreater(purchase_id, 0)

            receipt_res = self.client.post("/api/procurement/receipts", json={
                "purchase_id": purchase_id,
                "request_id": request_id,
                "supplier_id": supplier_id,
                "receipt_date": datetime.now().strftime("%d.%m.%Y"),
                "article": article,
                "item_name": "QA procurement material",
                "accepted_qty": 12,
                "rejected_qty": 0,
                "warehouse": "QA Procurement",
                "bin_code": "QA-01",
                "quality_status": "accepted",
                "status": "posted",
                "comment": "integration receipt",
            })
            self.assertEqual(receipt_res.status_code, 200)
            receipt_id = int(receipt_res.json()["id"])

            document_res = self.client.post("/api/procurement/documents", json={
                "purchase_id": purchase_id,
                "request_id": request_id,
                "supplier_id": supplier_id,
                "doc_type": "upd",
                "doc_number": f"UPD-{stamp}",
                "doc_date": datetime.now().strftime("%d.%m.%Y"),
                "amount": 10200,
                "vat_amount": 1700,
                "currency": "RUB",
                "status": "accepted",
                "payment_due_date": (datetime.now() + timedelta(days=10)).strftime("%d.%m.%Y"),
                "comment": "integration document",
            })
            self.assertEqual(document_res.status_code, 200)
            document_id = int(document_res.json()["id"])

            summary = self.client.get("/api/supply/extended_summary")
            self.assertEqual(summary.status_code, 200)
            payload = summary.json()
            self.assertGreaterEqual(payload["metrics"]["purchase_receipts"], 1)
            self.assertGreaterEqual(payload["metrics"]["purchase_documents"], 1)
            self.assertTrue(any(int(row["request_id"]) == request_id for row in payload["procurement_sla"]))

            requests = self.client.get("/api/procurement/requests").json()
            self.assertTrue(any(int(row["id"]) == request_id and int(row["linked_purchase_id"]) == purchase_id for row in requests))

            receipts = self.client.get("/api/procurement/receipts").json()
            self.assertTrue(any(int(row["id"]) == receipt_id for row in receipts))
        finally:
            conn = get_connection()
            c = conn.cursor()
            if document_id:
                c.execute("DELETE FROM purchase_documents WHERE id=?", (document_id,))
            if receipt_id:
                c.execute("DELETE FROM purchase_receipts WHERE id=?", (receipt_id,))
            if purchase_id:
                c.execute("DELETE FROM purchase_orders WHERE id=?", (purchase_id,))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='purchase_order' AND entity_id=?", (purchase_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='purchase_order' AND entity_id=?", (purchase_id,))
            if bid_id:
                c.execute("DELETE FROM procurement_tender_bids WHERE id=?", (bid_id,))
            if tender_id:
                c.execute("DELETE FROM procurement_tenders WHERE id=?", (tender_id,))
            if request_id:
                c.execute("DELETE FROM procurement_requests WHERE id=?", (request_id,))
            if supplier_id:
                c.execute("DELETE FROM supplier_registry WHERE id=?", (supplier_id,))
            c.execute("DELETE FROM inventory_balances WHERE article=?", (article,))
            c.execute("DELETE FROM inventory_lots WHERE article=?", (article,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
