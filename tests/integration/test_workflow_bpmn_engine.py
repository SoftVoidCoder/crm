import os
import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class WorkflowBpmnEngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.director = create_test_user(role="Директор", name_prefix="BPMN Director")
        self.legal = create_test_user(role="Юрист", name_prefix="BPMN Legal")
        self.accounting = create_test_user(role="Бухгалтерия", name_prefix="BPMN Accounting")
        self.director_client = TestClient(app)
        self.legal_client = TestClient(app)
        self.accounting_client = TestClient(app)
        self.assertEqual(self.director_client.post("/api/login", json={"email": self.director["email"], "password": self.director["password"]}).status_code, 200)
        self.assertEqual(self.legal_client.post("/api/login", json={"email": self.legal["email"], "password": self.legal["password"]}).status_code, 200)
        self.assertEqual(self.accounting_client.post("/api/login", json={"email": self.accounting["email"], "password": self.accounting["password"]}).status_code, 200)

    def tearDown(self):
        delete_test_user(self.director["email"])
        delete_test_user(self.legal["email"])
        delete_test_user(self.accounting["email"])

    def test_bpmn_conditions_timer_rework_delegation_and_parallel_completion(self):
        suffix = f"{os.getpid()}-{int(time.time())}"
        definition_id = 0
        instance_id = 0
        try:
            created = self.director_client.post("/api/workflows/definitions", json={
                "workflow_code": f"QA-BPMN-{suffix}",
                "workflow_name": "QA BPMN договор с условиями",
                "entity_type": "document",
                "status": "active",
                "nodes": [
                    {"node_key": "start", "node_type": "start", "title": "Старт"},
                    {"node_key": "timer", "node_type": "timer", "title": "Пауза SLA", "timer_seconds": -1},
                    {"node_key": "legal", "node_type": "approval", "title": "Юридическая проверка", "role_name": "Юрист", "assignee_name": self.legal["name"], "sla_hours": 1},
                    {"node_key": "split", "node_type": "parallel_gateway", "title": "Параллельные ветки"},
                    {"node_key": "finance", "node_type": "approval", "title": "Финансовый контроль", "role_name": "Бухгалтерия", "assignee_name": self.accounting["name"], "sla_hours": 1},
                    {"node_key": "director", "node_type": "approval", "title": "Директор", "role_name": "Директор", "assignee_name": self.director["name"], "config": {"sla_seconds": -1}},
                    {"node_key": "end", "node_type": "end", "title": "Готово"},
                ],
                "edges": [
                    {"source_node_key": "start", "target_node_key": "timer", "priority": 1},
                    {"source_node_key": "timer", "target_node_key": "legal", "priority": 1},
                    {"source_node_key": "legal", "target_node_key": "split", "priority": 1},
                    {"source_node_key": "split", "target_node_key": "finance", "priority": 1},
                    {"source_node_key": "split", "target_node_key": "director", "condition": {"field": "amount", "op": ">", "value": 3000000}, "condition_label": "amount > 3000000", "priority": 2},
                    {"source_node_key": "finance", "target_node_key": "end", "priority": 1},
                    {"source_node_key": "director", "target_node_key": "end", "priority": 1},
                ],
            })
            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["status"], "success")
            definition_id = int(created.json()["id"])

            started = self.director_client.post(f"/api/workflows/definitions/{definition_id}/start", json={
                "entity_type": "document",
                "entity_id": "QA-BPMN-DOC",
                "title": "QA BPMN экземпляр",
                "context": {"amount": 5000000, "legal_entity_id": 77, "doc_type": "contract"},
            })
            self.assertEqual(started.status_code, 200)
            self.assertEqual(started.json()["status"], "success")
            instance_id = int(started.json()["id"])
            self.assertEqual(started.json()["instance"]["active_tokens"][0]["node_key"], "timer")

            timers = self.director_client.post("/api/workflows/process_automation")
            self.assertEqual(timers.status_code, 200)
            self.assertEqual(timers.json()["count"], 1)

            detail = self.director_client.get(f"/api/workflows/instances/{instance_id}")
            self.assertEqual(detail.status_code, 200)
            legal_token = next(token for token in detail.json()["instance"]["active_tokens"] if token["node_key"] == "legal")
            self.assertEqual(legal_token["assignee_name"], self.legal["name"])

            returned = self.legal_client.post(f"/api/workflows/tokens/{legal_token['id']}/actions", json={
                "action_name": "return_rework",
                "target_node_key": "legal",
                "comment": "Нужна правка условий",
            })
            self.assertEqual(returned.status_code, 200, returned.text)
            self.assertNotIn("error", returned.json(), returned.text)
            self.assertEqual(returned.json()["status"], "success")
            rework_token = next(token for token in returned.json()["instance"]["active_tokens"] if token["node_key"] == "legal")

            approved_legal = self.legal_client.post(f"/api/workflows/tokens/{rework_token['id']}/actions", json={
                "action_name": "approve",
                "comment": "Юридически ок",
            })
            self.assertEqual(approved_legal.status_code, 200)
            active_keys = {token["node_key"] for token in approved_legal.json()["instance"]["active_tokens"]}
            self.assertEqual(active_keys, {"finance", "director"})

            director_token = next(token for token in approved_legal.json()["instance"]["active_tokens"] if token["node_key"] == "director")
            delegated = self.director_client.post(f"/api/workflows/tokens/{director_token['id']}/actions", json={
                "action_name": "delegate",
                "target_user": self.accounting["name"],
                "comment": "Замещение на бухгалтерию",
            })
            self.assertEqual(delegated.status_code, 200)
            delegated_token = next(token for token in delegated.json()["instance"]["active_tokens"] if token["node_key"] == "director")
            self.assertEqual(delegated_token["assignee_name"], self.accounting["name"])

            finance_token = next(token for token in delegated.json()["instance"]["active_tokens"] if token["node_key"] == "finance")
            approved_finance = self.accounting_client.post(f"/api/workflows/tokens/{finance_token['id']}/actions", json={"action_name": "approve"})
            self.assertEqual(approved_finance.status_code, 200)
            self.assertEqual(approved_finance.json()["instance"]["status"], "running")

            delegated_token = next(token for token in approved_finance.json()["instance"]["active_tokens"] if token["node_key"] == "director")
            approved_director_branch = self.accounting_client.post(f"/api/workflows/tokens/{delegated_token['id']}/actions", json={"action_name": "approve"})
            self.assertEqual(approved_director_branch.status_code, 200)
            self.assertEqual(approved_director_branch.json()["instance"]["status"], "completed")

            conn = get_connection(row_factory=True)
            try:
                tokens = conn.execute("SELECT * FROM workflow_tokens WHERE instance_id=?", (instance_id,)).fetchall()
                self.assertGreaterEqual(len(tokens), 7)
                history = conn.execute("SELECT history_json FROM workflow_instances WHERE id=?", (instance_id,)).fetchone()["history_json"]
                self.assertIn("return_rework", history)
                self.assertIn("delegated", history)
            finally:
                conn.close()
        finally:
            conn = get_connection()
            c = conn.cursor()
            if instance_id:
                c.execute("DELETE FROM workflow_tokens WHERE instance_id=?", (instance_id,))
                c.execute("DELETE FROM workflow_instances WHERE id=?", (instance_id,))
            if definition_id:
                c.execute("DELETE FROM workflow_edges WHERE definition_id=?", (definition_id,))
                c.execute("DELETE FROM workflow_nodes WHERE definition_id=?", (definition_id,))
                c.execute("DELETE FROM workflow_definitions WHERE id=?", (definition_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
