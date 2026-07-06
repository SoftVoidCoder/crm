import os
import time
import unittest

from fastapi.testclient import TestClient

from main import app
from database import get_connection
from tests.test_helpers import create_test_user, delete_test_user, run_db_cleanup


class ExecutiveBoardroomAndExternalReportingTests(unittest.TestCase):
    def test_executive_summary_includes_boardroom_bottlenecks(self):
        director = create_test_user(role="Директор", name_prefix="Boardroom Director")
        client = TestClient(app)
        created = {
            "client_id": 0,
            "project_id": 0,
            "payment_id": 0,
            "resource_id": 0,
            "service_id": 0,
            "approval_id": 0,
        }
        project_name = f"Boardroom Project {os.getpid()}-{int(time.time())}"
        client_name = f"Boardroom Client {os.getpid()}-{int(time.time())}"
        try:
            login = client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            create_client_response = client.post("/api/clients", json={
                "name": client_name,
                "inn": f"77{os.getpid():08d}"[-10:],
                "contact": "boardroom@example.com",
            })
            self.assertEqual(create_client_response.status_code, 200)

            create_project_response = client.post("/api/projects", json={
                "name": project_name,
                "contract": "BR-001",
                "client": client_name,
                "manager": director["name"],
                "budget": 500000,
                "costs": 0,
                "team": [],
                "checklist": [],
                "allowed_roles": ["Директор", "Менеджер", "Бухгалтерия"],
                "nomenclature": [],
                "archive_details": {},
            })
            self.assertEqual(create_project_response.status_code, 200)

            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM clients WHERE name=?", (client_name,))
            created["client_id"] = int(c.fetchone()[0])
            c.execute("SELECT id FROM projects WHERE name=? ORDER BY id DESC LIMIT 1", (project_name,))
            created["project_id"] = int(c.fetchone()[0])
            conn.close()

            payment = client.post("/api/finance/payments", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "treasury_article_id": 0,
                "vat_rate_id": 0,
                "source_document_type": "",
                "source_document_id": 0,
                "title": "Просроченная дебиторка boardroom",
                "kind": "incoming",
                "category": "payment",
                "amount": 185000,
                "currency": "RUB",
                "due_date": "01.04.2026",
                "paid_date": "",
                "status": "planned",
                "comment": "Тест кассового риска",
            })
            self.assertEqual(payment.status_code, 200)
            created["payment_id"] = int(payment.json()["id"])

            resource = client.post("/api/resources/allocations", json={
                "project_id": created["project_id"],
                "contract_id": 0,
                "object_id": 0,
                "department": "Проектный офис",
                "resource_name": "QA Bottleneck Lead",
                "role_name": "Руководитель проекта",
                "load_percent": 135,
                "date_from": "20.04.2026",
                "date_to": "30.04.2026",
                "status": "planned",
                "comment": "Перегрузка ресурса",
                "crew_name": "",
                "crew_type": "",
                "location": "Москва",
            })
            self.assertEqual(resource.status_code, 200)
            created["resource_id"] = int(resource.json()["id"])

            service = client.post("/api/service/cases", json={
                "project_id": created["project_id"],
                "client_id": created["client_id"],
                "contract_id": 0,
                "object_id": 0,
                "case_number": f"BR-SVC-{os.getpid()}",
                "title": "Критичный сервисный кейс",
                "case_type": "maintenance",
                "status": "open",
                "priority": "high",
                "defect": "Задержка выполнения SLA",
                "warranty_until": "31.12.2026",
                "sla_deadline": "01.04.2026",
                "responsible": director["name"],
                "resolution": "",
            })
            self.assertEqual(service.status_code, 200)
            created["service_id"] = int(service.json()["id"])

            approval = client.post("/api/approvals", json={
                "title": "Boardroom overdue approval",
                "item_link": f"/projects/{created['project_id']}",
                "route": [director["name"]],
                "author": director["name"],
                "entity_type": "project",
                "entity_id": str(created["project_id"]),
                "default_sla_hours": 24,
            })
            self.assertEqual(approval.status_code, 200)
            created["approval_id"] = int(approval.json()["id"])

            conn = get_connection()
            c = conn.cursor()
            c.execute(
                "UPDATE approvals SET due_at=?, last_action_at=? WHERE id=?",
                (int(time.time()) - 7200, int(time.time()) - 7200, created["approval_id"]),
            )
            conn.commit()
            conn.close()

            executive = client.get("/api/executive/summary")
            self.assertEqual(executive.status_code, 200)
            payload = executive.json()
            self.assertGreaterEqual(int(payload["metrics"]["blocked_approvals"]), 1)
            self.assertGreater(float(payload["metrics"]["cash_overdue_receivables"]), 0)
            self.assertGreaterEqual(int(payload["metrics"]["service_sla_breached"]), 1)
            self.assertGreaterEqual(int(payload["metrics"]["resource_hotspots"]), 1)
            self.assertTrue(any(item["category"] == "approval" for item in payload["boardroom_bottlenecks"]))
            self.assertTrue(any(item["category"] == "cash" for item in payload["boardroom_bottlenecks"]))
            self.assertTrue(any(item["category"] == "resource" for item in payload["boardroom_bottlenecks"]))
            self.assertTrue(any(item["category"] == "sla" for item in payload["boardroom_heatmap"]))
        finally:
            run_db_cleanup([
                ("DELETE FROM approvals WHERE id=?", (created["approval_id"],)),
                ("DELETE FROM service_cases WHERE id=?", (created["service_id"],)),
                ("DELETE FROM resource_allocations WHERE id=?", (created["resource_id"],)),
                ("DELETE FROM finance_payments WHERE id=?", (created["payment_id"],)),
                ("DELETE FROM projects WHERE id=?", (created["project_id"],)),
                ("DELETE FROM clients WHERE id=?", (created["client_id"],)),
            ])
            delete_test_user(director["email"])

    def test_accounting_external_reporting_flow_and_deep_summary(self):
        accounting = create_test_user(role="Бухгалтерия", name_prefix="External Reporting Accounting")
        client = TestClient(app)
        created = {"operator_id": 0, "submission_id": 0}
        period_key = "2099-10"
        try:
            login = client.post("/api/login", json={"email": accounting["email"], "password": accounting["password"]})
            self.assertEqual(login.status_code, 200)

            close_cycle = client.post(
                "/api/accounting/periods/close_cycle",
                json={"period_key": period_key, "comment": "QA external reporting"},
            )
            self.assertEqual(close_cycle.status_code, 200)
            close_payload = close_cycle.json()
            self.assertEqual(close_payload["status"], "success")

            operator = client.post("/api/accounting/edo_operators", json={
                "operator_name": "QA Tax Gateway",
                "provider_name": "1С-ЭДО",
                "contour_type": "tax",
                "api_endpoint": "https://edo.example.test/api",
                "account_login": "qa-accounting",
                "credential_ref": "vault://qa/external-reporting",
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "status": "active",
                "capabilities": ["reporting", "edo", "tax"],
                "retry_policy": {"max_retries": 3, "delay_minutes": 15},
                "idempotency_namespace": f"qa-tax-{int(time.time())}",
            })
            self.assertEqual(operator.status_code, 200)
            created["operator_id"] = int(operator.json()["id"])

            submission = client.post("/api/accounting/external_reporting/submissions", json={
                "operator_id": created["operator_id"],
                "contour_type": "tax",
                "report_type": "vat_return",
                "period_key": period_key,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "comment": "Первичная отправка отчётности",
            })
            self.assertEqual(submission.status_code, 200)
            submission_payload = submission.json()
            self.assertEqual(submission_payload["status"], "success")
            self.assertEqual(int(submission_payload["deduplicated"]), 0)
            created["submission_id"] = int(submission_payload["id"])
            self.assertIn(submission_payload["submission"]["submission_status"], {"sent", "accepted"})

            duplicate = client.post("/api/accounting/external_reporting/submissions", json={
                "operator_id": created["operator_id"],
                "contour_type": "tax",
                "report_type": "vat_return",
                "period_key": period_key,
                "legal_entity_id": 0,
                "business_unit_id": 0,
                "comment": "Повтор той же отчётности",
            })
            self.assertEqual(duplicate.status_code, 200)
            duplicate_payload = duplicate.json()
            self.assertEqual(int(duplicate_payload["deduplicated"]), 1)
            self.assertEqual(int(duplicate_payload["id"]), created["submission_id"])

            sync_status = client.post(
                f"/api/accounting/external_reporting/submissions/{created['submission_id']}/sync_status",
                json={
                    "submission_status": "accepted",
                    "protocol_number": f"PROT-{created['submission_id']}",
                    "receipt_number": f"RCPT-{created['submission_id']}",
                    "message": "Отчётность принята оператором",
                    "response_payload": {"accepted_by": "qa-operator"},
                },
            )
            self.assertEqual(sync_status.status_code, 200)
            self.assertEqual(sync_status.json()["submission"]["submission_status"], "accepted")

            submissions = client.get("/api/accounting/external_reporting/submissions")
            self.assertEqual(submissions.status_code, 200)
            self.assertTrue(any(int(item["id"]) == created["submission_id"] and item["submission_status"] == "accepted" for item in submissions.json()))

            deep_summary = client.get("/api/accounting/deep_summary")
            self.assertEqual(deep_summary.status_code, 200)
            payload = deep_summary.json()
            self.assertTrue(any(int(item["id"]) == created["operator_id"] for item in payload["edo_operators"]))
            self.assertTrue(any(int(item["id"]) == created["submission_id"] and item["submission_status"] == "accepted" for item in payload["external_submissions"]))
            self.assertGreaterEqual(int(payload["external_reporting_metrics"]["submissions_accepted"]), 1)
            self.assertGreaterEqual(int(payload["external_reporting_metrics"]["operators_active"]), 1)
            self.assertTrue(any(int(item["submission_id"]) == created["submission_id"] for item in payload["external_events"]))
        finally:
            run_db_cleanup([
                ("DELETE FROM accounting_external_submission_events WHERE submission_id=?", (created["submission_id"],)),
                ("DELETE FROM accounting_external_submissions WHERE id=?", (created["submission_id"],)),
                ("DELETE FROM accounting_edo_operators WHERE id=?", (created["operator_id"],)),
                ("DELETE FROM accounting_entries WHERE period_key=? AND source_type IN ('accounting_close_vat', 'accounting_close_profit_tax')", (period_key,)),
                ("DELETE FROM accounting_tax_accruals WHERE period_key=?", (period_key,)),
                ("DELETE FROM accounting_reporting_snapshots WHERE period_key=?", (period_key,)),
                ("DELETE FROM accounting_register_reconciliations WHERE period_key=?", (period_key,)),
                ("DELETE FROM accounting_period_close_runs WHERE period_key=?", (period_key,)),
                ("DELETE FROM accounting_periods WHERE period_key=?", (period_key,)),
            ])
            delete_test_user(accounting["email"])


if __name__ == "__main__":
    unittest.main()
