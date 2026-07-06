import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class AccountingRegistersERPModelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="Accounting Registers")
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        delete_test_user(self.user["email"])

    def _cleanup_period(self, period_key: str, payment_id: int = 0):
        conn = get_connection()
        c = conn.cursor()
        if payment_id:
            c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
            c.execute("DELETE FROM accounting_registers WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
            c.execute("DELETE FROM tax_registers WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
            c.execute("DELETE FROM vat_purchase_book WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
            c.execute("DELETE FROM vat_sales_book WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
            c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
            c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
        c.execute("DELETE FROM currency_revaluation_runs WHERE period_key=?", (period_key,))
        c.execute("DELETE FROM accounting_registers WHERE period_key=?", (period_key,))
        c.execute("DELETE FROM tax_registers WHERE period_key=?", (period_key,))
        c.execute("DELETE FROM vat_purchase_book WHERE period_key=?", (period_key,))
        c.execute("DELETE FROM vat_sales_book WHERE period_key=?", (period_key,))
        c.execute("DELETE FROM accounting_tax_accruals WHERE period_key=?", (period_key,))
        c.execute("DELETE FROM accounting_reporting_snapshots WHERE period_key=?", (period_key,))
        c.execute("DELETE FROM accounting_register_reconciliations WHERE period_key=?", (period_key,))
        c.execute("DELETE FROM accounting_period_close_runs WHERE period_key=?", (period_key,))
        c.execute("DELETE FROM accounting_entries WHERE period_key=? AND source_type IN ('accounting_close_vat', 'accounting_close_profit_tax')", (period_key,))
        c.execute("DELETE FROM accounting_periods WHERE period_key=?", (period_key,))
        conn.commit()
        conn.close()

    def test_finance_payment_posts_accounting_tax_vat_and_currency_registers(self):
        period_key = "2099-12"
        payment_id = 0
        self._cleanup_period(period_key)
        try:
            conn = get_connection(row_factory=True)
            try:
                vat_rate = conn.execute("SELECT id FROM vat_rates WHERE rate=20 AND is_active=1 ORDER BY id LIMIT 1").fetchone()
                vat_rate_id = int((vat_rate or {}).get("id") or 0)
                legal_entity = conn.execute("SELECT id FROM legal_entities ORDER BY id LIMIT 1").fetchone()
                legal_entity_id = int((legal_entity or {}).get("id") or 0)
            finally:
                conn.close()

            created = self.client.post("/api/finance/payments", json={
                "legal_entity_id": legal_entity_id,
                "business_unit_id": 0,
                "vat_rate_id": vat_rate_id,
                "title": "QA ERP регистр оплата",
                "kind": "incoming",
                "category": "invoice",
                "amount": 120000,
                "currency": "USD",
                "due_date": "10.12.2099",
                "paid_date": "15.12.2099",
                "status": "paid",
                "comment": "Проверка полной модели регистров",
            })
            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["status"], "success")
            payment_id = int(created.json()["id"])

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
            self.assertEqual(int(c.fetchone()[0]), 1)
            c.execute("SELECT COUNT(*) FROM accounting_registers WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
            self.assertEqual(int(c.fetchone()[0]), 2)
            c.execute("SELECT COUNT(*) FROM tax_registers WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
            self.assertEqual(int(c.fetchone()[0]), 1)
            c.execute("SELECT COUNT(*) FROM vat_sales_book WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
            self.assertEqual(int(c.fetchone()[0]), 1)
            conn.close()

            summary = self.client.get("/api/accounting/registers/summary", params={"period_key": period_key})
            self.assertEqual(summary.status_code, 200)
            summary_payload = summary.json()
            self.assertEqual(summary_payload["status"], "success")
            self.assertGreaterEqual(summary_payload["summary"]["accounting_registers_total"], 2)
            self.assertGreaterEqual(summary_payload["summary"]["vat_sales_book_total"], 1)

            close_res = self.client.post("/api/accounting/periods/close_cycle", json={
                "period_key": period_key,
                "comment": "QA close with ERP registers",
            })
            self.assertEqual(close_res.status_code, 200)
            payload = close_res.json()
            self.assertEqual(payload["status"], "success")
            self.assertIn("register_summary", payload["workspace"])
            self.assertGreaterEqual(payload["workspace"]["register_summary"]["accounting_registers_total"], 2)
            self.assertTrue(
                any(row["register_name"] == "vat_books" for row in payload["workspace"]["register_reconciliations"]),
                payload["workspace"]["register_reconciliations"],
            )

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM currency_revaluation_runs WHERE period_key=? AND currency='USD'", (period_key,))
            self.assertGreaterEqual(int(c.fetchone()[0]), 1)
            c.execute("SELECT COUNT(*) FROM accounting_period_close_runs WHERE period_key=?", (period_key,))
            self.assertGreaterEqual(int(c.fetchone()[0]), 1)
            conn.close()
        finally:
            self._cleanup_period(period_key, payment_id)


if __name__ == "__main__":
    unittest.main()
