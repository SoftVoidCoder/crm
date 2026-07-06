import io
import os
import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DocflowClosedWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.clients = {}
        self.users = {
            "director": create_test_user(role="Директор", name_prefix="Docflow Workflow Director"),
            "manager": create_test_user(role="Менеджер", name_prefix="Docflow Workflow Manager"),
        }
        for key, user in self.users.items():
            client = TestClient(app)
            login = client.post("/api/login", json={"email": user["email"], "password": user["password"]})
            self.assertEqual(login.status_code, 200)
            self.clients[key] = client

    def tearDown(self):
        for user in self.users.values():
            delete_test_user(user["email"])

    def test_incoming_document_runs_through_task_approval_execution_and_archive(self):
        suffix = f"{os.getpid()}-{int(time.time())}"
        document_id = 0
        approval_id = 0
        task_id = 0
        certificate_id = 0
        stored_paths = []
        try:
            created = self.clients["director"].post("/api/documents", json={
                "type": "incoming",
                "number": f"QA-WF-{suffix}",
                "d_date": "21.04.2026",
                "correspondent": "QA Workflow Sender",
                "subject": "Сквозной маршрут входящего документа",
                "status": "registered",
                "project_id": 0,
                "contract_id": 0,
                "object_id": 0,
                "parent_id": 0,
                "priority": "high",
                "resolution": "Подготовить исполнение и закрыть документ по маршруту.",
                "resolution_author": self.users["director"]["name"],
                "resolution_deadline": "25.04.2026",
                "resolution_assignee": self.users["manager"]["name"],
                "resolution_task_id": 0,
            })
            self.assertEqual(created.status_code, 200)
            document_id = int(created.json()["id"])
            task_id = int(created.json()["resolution_task_id"])
            self.assertGreater(task_id, 0)

            upload = self.clients["director"].post(
                f"/api/documents/{document_id}/upload",
                data={"comment": "Файл для сквозного workflow", "make_current": "1"},
                files={"file": ("workflow.txt", io.BytesIO(b"workflow-body\n"), "text/plain")},
            )
            self.assertEqual(upload.status_code, 200)
            stored_paths.append(os.path.join(BASE_DIR, upload.json()["url"].lstrip("/")))

            started = self.clients["director"].post(
                f"/api/docflow/documents/{document_id}/workflow/start",
                json={
                    "approval_title": f"QA workflow {suffix}",
                    "route_rules": [
                        {
                            "stage_key": "director_review",
                            "stage_name": "Проверка директором",
                            "assignees": [self.users["director"]["name"]],
                            "sla_hours": 12,
                        }
                    ],
                    "route_context": {"qa_case": 1},
                    "comment": "Старт сквозного маршрута",
                },
            )
            self.assertEqual(started.status_code, 200)
            approval_id = int(started.json()["approval_id"])
            self.assertEqual(started.json()["workflow"]["stage"], "approval")
            self.assertEqual(started.json()["workflow"]["status"], "in_progress")

            blocked_archive = self.clients["director"].post(
                f"/api/docflow/documents/{document_id}/archive_legal",
                json={"comment": "Рано отправлять в архив"},
            )
            self.assertEqual(blocked_archive.status_code, 200)
            self.assertEqual(blocked_archive.json()["error"], "workflow_incomplete")
            self.assertEqual(blocked_archive.json()["workflow"]["blocking_reason"], "approval_pending")

            approved = self.clients["director"].post(f"/api/approvals/{approval_id}/actions", json={"action_name": "approve"})
            self.assertEqual(approved.status_code, 200)
            self.assertEqual(approved.json()["status"], "completed")

            workflow_after_approval = self.clients["director"].get(f"/api/docflow/documents/{document_id}/workflow")
            self.assertEqual(workflow_after_approval.status_code, 200)
            self.assertEqual(workflow_after_approval.json()["workflow"]["stage"], "execution")
            self.assertEqual(workflow_after_approval.json()["workflow"]["blocking_reason"], "task_execution_pending")

            task_done = self.clients["manager"].put(f"/api/tasks/{task_id}", json={"status": "done"})
            self.assertEqual(task_done.status_code, 200)

            workflow_ready = self.clients["director"].get(f"/api/docflow/documents/{document_id}/workflow")
            self.assertEqual(workflow_ready.status_code, 200)
            self.assertEqual(workflow_ready.json()["workflow"]["stage"], "archive")
            self.assertEqual(workflow_ready.json()["workflow"]["status"], "ready")
            self.assertTrue(workflow_ready.json()["workflow"]["can_archive"])

            certificate = self.clients["director"].post("/api/docflow/certificates", json={
                "owner_name": self.users["director"]["name"],
                "owner_email": self.users["director"]["email"],
                "signer_role": "Директор",
                "provider_name": "КриптоПро",
                "thumbprint": f"QA-WF-CERT-{suffix}",
                "serial_number": f"QA-WF-SERIAL-{suffix}",
                "valid_from": "20.04.2026",
                "valid_to": "30.04.2026",
                "status": "active",
                "comment": "Сертификат для сквозного маршрута",
            })
            self.assertEqual(certificate.status_code, 200)
            certificate_id = int(certificate.json()["id"])

            sign = self.clients["director"].post(f"/api/docflow/documents/{document_id}/signatures", json={
                "certificate_id": certificate_id,
                "signature_kind": "КЭП",
                "signature_provider": "КриптоПро",
                "comment": "Подпись для архивирования после исполнения",
            })
            self.assertEqual(sign.status_code, 200)

            verify = self.clients["director"].post(f"/api/docflow/documents/{document_id}/verify_signatures", json={"force": 1})
            self.assertEqual(verify.status_code, 200)
            self.assertGreaterEqual(int(verify.json()["valid_total"]), 1)

            archive = self.clients["director"].post(
                f"/api/docflow/documents/{document_id}/archive_legal",
                json={"comment": "Документ закрыт и передан в архив"},
            )
            self.assertEqual(archive.status_code, 200)
            self.assertEqual(archive.json()["document"]["lifecycle_state"], "archived")
            self.assertEqual(archive.json()["workflow"]["status"], "completed")
            self.assertEqual(archive.json()["workflow"]["stage"], "archive")

            summary = self.clients["director"].get("/api/docflow/plus_summary")
            self.assertEqual(summary.status_code, 200)
            summary_payload = summary.json()
            self.assertTrue(any(int(item["document_id"]) == document_id and item["workflow_status"] == "completed" for item in summary_payload["workflow_board"]))
            self.assertGreaterEqual(int(summary_payload["metrics"]["workflow_started_total"]), 1)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if approval_id:
                c.execute("DELETE FROM approval_sla_events WHERE approval_id=?", (approval_id,))
                c.execute("DELETE FROM approval_delegations WHERE approval_id=?", (approval_id,))
                c.execute("DELETE FROM approval_action_log WHERE approval_id=?", (approval_id,))
                c.execute("DELETE FROM approvals WHERE id=?", (approval_id,))
            if task_id:
                c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            if document_id:
                c.execute("DELETE FROM notifications WHERE entity_type='document' AND entity_id=?", (str(document_id),))
                c.execute("DELETE FROM notifications WHERE entity_type='task' AND entity_id=?", (str(task_id),))
                c.execute("DELETE FROM notifications WHERE entity_type='approval' AND entity_id=?", (str(approval_id),))
                c.execute("DELETE FROM edo_signature_registry WHERE entity_type='document' AND entity_id=?", (document_id,))
                c.execute("DELETE FROM document_legal_archive WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_file_revisions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_registration_records WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_lifecycle_events WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_versions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_linked_tasks WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_print_forms WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM documents WHERE id=?", (document_id,))
            if certificate_id:
                c.execute("DELETE FROM edo_certificates WHERE id=?", (certificate_id,))
            conn.commit()
            conn.close()
            for path in stored_paths:
                if path and os.path.exists(path):
                    os.remove(path)


if __name__ == "__main__":
    unittest.main()
