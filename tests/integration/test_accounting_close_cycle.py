import time
import unittest

from fastapi.testclient import TestClient

from main import app
from database import get_connection
from tests.test_helpers import create_test_user, delete_test_user


class AccountingCloseCycleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="Accounting Close")

    def tearDown(self):
        delete_test_user(self.user["email"])

    def test_close_cycle_builds_taxes_reports_and_reconciliations(self):
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

        period_key = "2099-11"
        sales_id = 0
        purchase_id = 0
        try:
            conn = get_connection(row_factory=True)
            legal_entity_row = conn.execute("SELECT id FROM legal_entities ORDER BY id LIMIT 1").fetchone()
            business_unit_row = conn.execute("SELECT id FROM business_units ORDER BY id LIMIT 1").fetchone()
            legal_entity_id = int((legal_entity_row or {}).get("id") or 0)
            business_unit_id = int((business_unit_row or {}).get("id") or 0)
            now = int(time.time())

            sales_cursor = conn.execute(
                """
                INSERT INTO sales_documents_extended (
                    legal_entity_id, business_unit_id, doc_type, doc_number, doc_date, amount, currency,
                    status, payment_status, comment, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    legal_entity_id,
                    business_unit_id,
                    "invoice",
                    "QA-CLOSE-SALE",
                    "15.11.2099",
                    120000,
                    "RUB",
                    "confirmed",
                    "planned",
                    "Тест close-cycle sale",
                    self.user["email"],
                    now,
                    now,
                ),
            )
            sales_id = int(sales_cursor.lastrowid or 0)

            purchase_cursor = conn.execute(
                """
                INSERT INTO purchase_orders (
                    legal_entity_id, business_unit_id, item_article, item_name, supplier, qty, unit_price,
                    total_amount, status, expected_date, comment, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    legal_entity_id,
                    business_unit_id,
                    "QA-CLOSE-MAT",
                    "Тестовые материалы",
                    "QA Supplier",
                    10,
                    6000,
                    60000,
                    "received",
                    "12.11.2099",
                    "Тест close-cycle purchase",
                    self.user["email"],
                    now,
                    now,
                ),
            )
            purchase_id = int(purchase_cursor.lastrowid or 0)
            conn.commit()
            conn.close()

            close_res = self.client.post(
                "/api/accounting/periods/close_cycle",
                json={"period_key": period_key, "comment": "QA close cycle"},
            )
            self.assertEqual(close_res.status_code, 200)
            payload = close_res.json()
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["period_key"], period_key)
            self.assertGreaterEqual(int(payload.get("close_run_id") or 0), 1)
            self.assertIn("workspace", payload)
            self.assertGreaterEqual(len(payload["workspace"].get("tax_accruals", [])), 3)
            self.assertGreaterEqual(len(payload["workspace"].get("report_snapshots", [])), 4)
            self.assertGreaterEqual(len(payload["workspace"].get("register_reconciliations", [])), 1)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT status FROM accounting_periods WHERE period_key=?", (period_key,))
            row = c.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "closed")

            c.execute("SELECT COUNT(*) FROM accounting_tax_accruals WHERE period_key=?", (period_key,))
            self.assertGreaterEqual(int(c.fetchone()[0]), 3)
            c.execute("SELECT COUNT(*) FROM accounting_reporting_snapshots WHERE period_key=?", (period_key,))
            self.assertGreaterEqual(int(c.fetchone()[0]), 4)
            c.execute("SELECT COUNT(*) FROM accounting_register_reconciliations WHERE period_key=?", (period_key,))
            self.assertGreaterEqual(int(c.fetchone()[0]), 1)
            c.execute("SELECT COUNT(*) FROM accounting_registers WHERE period_key=?", (period_key,))
            self.assertGreaterEqual(int(c.fetchone()[0]), 4)
            c.execute("SELECT COUNT(*) FROM vat_purchase_book WHERE period_key=?", (period_key,))
            self.assertGreaterEqual(int(c.fetchone()[0]), 1)
            c.execute("SELECT COUNT(*) FROM vat_sales_book WHERE period_key=?", (period_key,))
            self.assertGreaterEqual(int(c.fetchone()[0]), 1)
            c.execute("SELECT COUNT(*) FROM accounting_entries WHERE period_key=? AND source_type='accounting_close_vat'", (period_key,))
            self.assertGreaterEqual(int(c.fetchone()[0]), 1)
            conn.close()
        finally:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM currency_revaluation_runs WHERE period_key=?", (period_key,))
            c.execute("DELETE FROM accounting_registers WHERE period_key=?", (period_key,))
            c.execute("DELETE FROM tax_registers WHERE period_key=?", (period_key,))
            c.execute("DELETE FROM vat_purchase_book WHERE period_key=?", (period_key,))
            c.execute("DELETE FROM vat_sales_book WHERE period_key=?", (period_key,))
            c.execute("DELETE FROM accounting_entries WHERE period_key=? AND source_type IN ('accounting_close_vat', 'accounting_close_profit_tax')", (period_key,))
            c.execute("DELETE FROM accounting_tax_accruals WHERE period_key=?", (period_key,))
            c.execute("DELETE FROM accounting_reporting_snapshots WHERE period_key=?", (period_key,))
            c.execute("DELETE FROM accounting_register_reconciliations WHERE period_key=?", (period_key,))
            c.execute("DELETE FROM accounting_period_close_runs WHERE period_key=?", (period_key,))
            c.execute("DELETE FROM accounting_entries WHERE period_key=? AND source_type IN ('sales_document', 'purchase_order')", (period_key,))
            if sales_id:
                c.execute("DELETE FROM sales_documents_extended WHERE id=?", (sales_id,))
            if purchase_id:
                c.execute("DELETE FROM purchase_orders WHERE id=?", (purchase_id,))
            c.execute("DELETE FROM accounting_periods WHERE period_key=?", (period_key,))
            conn.commit()
            conn.close()
