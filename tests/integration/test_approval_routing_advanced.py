import json
import os
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class ApprovalRoutingAdvancedIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.clients = {}
        self.users = {
            "director": create_test_user(role="Директор", name_prefix="Approval Director"),
            "manager": create_test_user(role="Менеджер", name_prefix="Approval Manager"),
            "legal": create_test_user(role="Юрист", name_prefix="Approval Legal"),
        }
        for key, user in self.users.items():
            client = TestClient(app)
            login = client.post("/api/login", json={"email": user["email"], "password": user["password"]})
            self.assertEqual(login.status_code, 200)
            self.clients[key] = client

    def tearDown(self):
        for user in self.users.values():
            delete_test_user(user["email"])

    def test_approval_routing_supports_conditions_parallel_delegation_rework_and_sla(self):
        approval_id = 0
        template_id = 0
        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute(
                "UPDATE users SET abs_start=?, abs_end=?, deputy=? WHERE email=?",
                ("20.04.2026", "25.04.2026", self.users["director"]["name"], self.users["manager"]["email"]),
            )
            conn.commit()
            conn.close()

            stages = [
                {
                    "stage_key": "initial_review",
                    "stage_name": "Первичная проверка",
                    "assignees": [self.users["manager"]["name"]],
                    "sla_hours": 12,
                },
                {
                    "stage_key": "parallel_control",
                    "stage_name": "Параллельный контроль",
                    "assignees": [self.users["legal"]["name"], self.users["director"]["name"]],
                    "parallel_mode": "all",
                    "condition": {"field": "amount", "op": "gte", "value": 100000},
                    "sla_hours": 6,
                    "allow_delegate": 1,
                    "escalation_role": "Директор",
                },
                {
                    "stage_key": "final_decision",
                    "stage_name": "Финальное решение",
                    "assignees": [self.users["director"]["name"]],
                    "sla_hours": 24,
                },
            ]

            template = self.clients["director"].post(
                "/api/approvals/route_templates",
                json={
                    "route_code": f"QA-APR-{os.getpid()}",
                    "route_name": "QA Маршрут согласования",
                    "entity_type": "document",
                    "conditions": {"field": "amount", "op": "gte", "value": 100000},
                    "stages": stages,
                    "is_active": 1,
                    "comment": "Тестовый шаблон маршрута",
                },
            )
            self.assertEqual(template.status_code, 200)
            template_id = int(template.json()["id"])

            templates = self.clients["director"].get("/api/approvals/route_templates")
            self.assertEqual(templates.status_code, 200)
            self.assertTrue(any(int(item["id"]) == template_id for item in templates.json()["items"]))

            created = self.clients["director"].post(
                "/api/approvals",
                json={
                    "title": "QA Сложное согласование",
                    "item_link": "/documents/qa-approval",
                    "route": [],
                    "route_rules": stages,
                    "route_context": {"amount": 150000, "doc_type": "contract"},
                    "author": self.users["director"]["name"],
                    "entity_type": "document",
                    "entity_id": "qa-approval",
                    "required_comment_on_reject": 1,
                    "required_comment_on_return": 1,
                    "default_sla_hours": 8,
                    "escalation_role": "Директор",
                },
            )
            self.assertEqual(created.status_code, 200)
            approval_id = int(created.json()["id"])
            self.assertEqual(created.json()["active_stage"]["stage_key"], "initial_review")
            self.assertTrue(any("И.О." in name for name in created.json()["current_assignees"]))

            approvals = self.clients["director"].get("/api/approvals")
            self.assertEqual(approvals.status_code, 200)
            row = next(item for item in approvals.json() if int(item["id"]) == approval_id)
            self.assertEqual(row["active_stage"]["stage_key"], "initial_review")
            self.assertEqual(row["sla_status"], "stable")

            approve_initial = self.clients["director"].post(f"/api/approvals/{approval_id}/actions", json={"action_name": "approve"})
            self.assertEqual(approve_initial.status_code, 200)
            self.assertEqual(approve_initial.json()["active_stage"]["stage_key"], "parallel_control")
            self.assertEqual(len(approve_initial.json()["current_assignees"]), 2)

            delegate = self.clients["director"].post(
                f"/api/approvals/{approval_id}/actions",
                json={"action_name": "delegate", "target_user": self.users["manager"]["name"], "comment": "Передаю заместителю"},
            )
            self.assertEqual(delegate.status_code, 200)
            self.assertIn(self.users["manager"]["name"], delegate.json()["current_assignees"])

            approve_parallel_legal = self.clients["legal"].post(f"/api/approvals/{approval_id}/actions", json={"action_name": "approve"})
            self.assertEqual(approve_parallel_legal.status_code, 200)
            self.assertEqual(approve_parallel_legal.json()["status"], "pending")

            approve_parallel_manager = self.clients["manager"].post(f"/api/approvals/{approval_id}/actions", json={"action_name": "approve"})
            self.assertEqual(approve_parallel_manager.status_code, 200)
            self.assertEqual(approve_parallel_manager.json()["active_stage"]["stage_key"], "final_decision")

            return_rework = self.clients["director"].post(
                f"/api/approvals/{approval_id}/actions",
                json={"action_name": "return_rework", "target_stage_key": "parallel_control", "comment": "Нужны уточнения по бюджету"},
            )
            self.assertEqual(return_rework.status_code, 200)
            self.assertEqual(return_rework.json()["status"], "rework")
            self.assertEqual(return_rework.json()["active_stage"]["stage_key"], "parallel_control")

            conn = get_connection(row_factory=True)
            c = conn.cursor()
            row = dict(c.execute("SELECT approval_state FROM approvals WHERE id=?", (approval_id,)).fetchone() or {})
            state = json.loads(row.get("approval_state") or "{}")
            for stage in state.get("stages") or []:
                if stage.get("stage_key") == "parallel_control":
                    stage["due_at"] = 1
                    stage["escalated_to"] = ""
                    stage["escalated_at"] = 0
            c.execute(
                "UPDATE approvals SET approval_state=?, due_at=? WHERE id=?",
                (json.dumps(state, ensure_ascii=False), 1, approval_id),
            )
            conn.commit()
            conn.close()

            automation = self.clients["director"].post("/api/approvals/process_automation")
            self.assertEqual(automation.status_code, 200)
            self.assertGreaterEqual(int(automation.json()["count"]), 1)
            self.assertTrue(any(int(item["approval_id"]) == approval_id for item in automation.json()["processed"]))

            refreshed = self.clients["director"].get("/api/approvals")
            self.assertEqual(refreshed.status_code, 200)
            final_row = next(item for item in refreshed.json() if int(item["id"]) == approval_id)
            self.assertEqual(final_row["active_stage"]["stage_key"], "parallel_control")
            self.assertIn(self.users["director"]["name"], final_row["current_assignees"])
            self.assertEqual(final_row["sla_status"], "overdue")
            self.assertTrue(any("эскалация" in item.lower() for item in final_row["history"]))
        finally:
            conn = get_connection()
            c = conn.cursor()
            if approval_id:
                c.execute("DELETE FROM notifications WHERE entity_type='approval' AND entity_id=?", (str(approval_id),))
                c.execute("DELETE FROM approval_sla_events WHERE approval_id=?", (approval_id,))
                c.execute("DELETE FROM approval_delegations WHERE approval_id=?", (approval_id,))
                c.execute("DELETE FROM approval_action_log WHERE approval_id=?", (approval_id,))
                c.execute("DELETE FROM approvals WHERE id=?", (approval_id,))
            if template_id:
                c.execute("DELETE FROM approval_route_templates WHERE id=?", (template_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
