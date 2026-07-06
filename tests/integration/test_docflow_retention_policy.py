import io
import os
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DocflowRetentionPolicyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.clients = {}
        self.users = {
            "director": create_test_user(role="Директор", name_prefix="Docflow Retention Director"),
            "manager": create_test_user(role="Менеджер", name_prefix="Docflow Retention Manager"),
        }
        for key, user in self.users.items():
            client = TestClient(app)
            login = client.post("/api/login", json={"email": user["email"], "password": user["password"]})
            self.assertEqual(login.status_code, 200)
            self.clients[key] = client

    def tearDown(self):
        for user in self.users.values():
            delete_test_user(user["email"])

    def test_retention_policy_controls_archive_and_case_access(self):
        document_id = 0
        certificate_id = 0
        classifier_id = 0
        case_file_id = 0
        policy_id = 0
        stored_paths = []
        try:
            created = self.clients["director"].post("/api/documents", json={
                "type": "outgoing",
                "number": "QA-RET-001",
                "d_date": "21.04.2026",
                "correspondent": "QA Archive Counterparty",
                "subject": "Проверка политики хранения",
                "status": "draft",
                "project_id": 0,
                "contract_id": 0,
                "object_id": 0,
                "parent_id": 0,
                "priority": "normal",
                "resolution": "",
                "resolution_author": "",
                "resolution_deadline": "",
                "resolution_assignee": "",
                "resolution_task_id": 0,
            })
            self.assertEqual(created.status_code, 200)
            document_id = int(created.json()["id"])

            upload = self.clients["director"].post(
                f"/api/documents/{document_id}/upload",
                data={"comment": "Редакция для архивной policy", "make_current": "1"},
                files={"file": ("retention_policy.txt", io.BytesIO(b"archive-policy-body\n"), "text/plain")},
            )
            self.assertEqual(upload.status_code, 200)
            stored_paths.append(os.path.join(BASE_DIR, upload.json()["url"].lstrip("/")))

            policy = self.clients["director"].post("/api/docflow/retention_policies", json={
                "policy_code": "QA-RET-POL-001",
                "policy_name": "QA Policy Directors Only",
                "scope_type": "doc_type",
                "scope_value": "outgoing",
                "retention_years": 3,
                "review_before_days": 45,
                "auto_archive": 0,
                "transfer_basis_default": "Передача в внешний архив по описи",
                "destruction_basis_default": "Уничтожение по акту комиссии",
                "access_roles": ["Директор"],
                "confidentiality_levels": ["internal", "confidential"],
                "is_active": 1,
                "comment": "Только директор и ответственные по делу",
            })
            self.assertEqual(policy.status_code, 200)
            policy_id = int(policy.json()["id"])

            classifier = self.clients["director"].post("/api/docflow/classifiers", json={
                "classifier_code": "QA-RET-CLS-001",
                "name": "Архивные исходящие",
                "doc_type": "outgoing",
                "category": "archive_control",
                "required_fields": ["registration_number", "classifier_id", "case_file_id", "retention_until", "legal_significance"],
                "default_lifecycle": "registered",
                "retention_years": 3,
                "is_active": 1,
                "allowed_roles": ["Директор"],
                "retention_policy_id": policy_id,
            })
            self.assertEqual(classifier.status_code, 200)
            classifier_id = int(classifier.json()["id"])

            case_file = self.clients["director"].post("/api/docflow/case_files", json={
                "case_index": "QA-RET-CASE-001",
                "title": "Дело архивного доступа",
                "department": "Юридический отдел",
                "retention_years": 3,
                "opened_at": "21.04.2026",
                "closed_at": "",
                "status": "open",
                "responsible_name": self.users["director"]["name"],
                "case_category": "contract_archive",
                "allowed_roles": ["Директор"],
                "retention_policy_id": policy_id,
                "transfer_basis_default": "Передача в внешний архив по описи",
                "destruction_basis_default": "Уничтожение по акту комиссии",
            })
            self.assertEqual(case_file.status_code, 200)
            case_file_id = int(case_file.json()["id"])

            legal_card = self.clients["director"].post(f"/api/docflow/documents/{document_id}/legal_card", json={
                "journal_id": 0,
                "classifier_id": classifier_id,
                "case_file_id": case_file_id,
                "legal_significance": "standard",
                "confidentiality_level": "internal",
                "retention_until": "21.04.2029",
                "document_kind_code": "RET-OUT",
                "auto_register": 1,
                "comment": "Назначение policy хранения",
            })
            self.assertEqual(legal_card.status_code, 200)
            self.assertEqual(int(legal_card.json()["retention_policy"]["id"]), policy_id)
            self.assertEqual(legal_card.json()["retention_status"]["status"], "active")
            self.assertIn("Директор", legal_card.json()["allowed_roles"])

            certificate = self.clients["director"].post("/api/docflow/certificates", json={
                "owner_name": self.users["director"]["name"],
                "owner_email": self.users["director"]["email"],
                "signer_role": "Директор",
                "provider_name": "КриптоПро",
                "thumbprint": "QA-RET-CERT-001",
                "serial_number": "QA-RET-SERIAL-001",
                "valid_from": "20.04.2026",
                "valid_to": "30.04.2026",
                "status": "active",
                "comment": "Сертификат для retention test",
            })
            self.assertEqual(certificate.status_code, 200)
            certificate_id = int(certificate.json()["id"])

            sign = self.clients["director"].post(f"/api/docflow/documents/{document_id}/signatures", json={
                "certificate_id": certificate_id,
                "signature_kind": "КЭП",
                "signature_provider": "КриптоПро",
                "comment": "Подпись под policy-controlled документом",
            })
            self.assertEqual(sign.status_code, 200)

            archive = self.clients["director"].post(f"/api/docflow/documents/{document_id}/archive_legal", json={
                "comment": "Архивирование по retention policy",
            })
            self.assertEqual(archive.status_code, 200)
            self.assertGreaterEqual(len(archive.json()["archive_entries"]), 1)

            denied = self.clients["manager"].get(f"/api/docflow/documents/{document_id}/legal_card")
            self.assertEqual(denied.status_code, 200)
            self.assertEqual(denied.json()["error"], "forbidden")

            disposition = self.clients["director"].post(f"/api/docflow/documents/{document_id}/retention_disposition", json={
                "action_name": "transfer",
                "basis_text": "Передача по акту N-17",
                "storage_path": "/archive/external/2026/qa-ret-001",
                "comment": "Выведено в внешний архив",
            })
            self.assertEqual(disposition.status_code, 200)
            disposition_payload = disposition.json()
            self.assertEqual(disposition_payload["archive_entries"][0]["archive_status"], "transferred")
            self.assertEqual(disposition_payload["archive_entries"][0]["transfer_basis"], "Передача по акту N-17")
            self.assertTrue(any(item["action_name"] == "transfer" for item in disposition_payload["retention_actions"]))

            director_summary = self.clients["director"].get("/api/docflow/plus_summary")
            self.assertEqual(director_summary.status_code, 200)
            summary_payload = director_summary.json()
            self.assertTrue(any(int(item["document_id"]) == document_id for item in summary_payload["retention_policy_board"]))
            self.assertGreaterEqual(int(summary_payload["metrics"]["retention_policies_total"]), 1)
            self.assertGreaterEqual(int(summary_payload["metrics"]["retention_actions_total"]), 1)

            manager_summary = self.clients["manager"].get("/api/docflow/plus_summary")
            self.assertEqual(manager_summary.status_code, 200)
            self.assertFalse(any(int(item["document_id"]) == document_id for item in manager_summary.json()["retention_policy_board"]))
        finally:
            conn = get_connection()
            c = conn.cursor()
            if document_id:
                c.execute("DELETE FROM document_retention_actions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM edo_signature_registry WHERE entity_type='document' AND entity_id=?", (document_id,))
                c.execute("DELETE FROM document_legal_archive WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_file_revisions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_registration_records WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_lifecycle_events WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_versions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_linked_tasks WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_print_forms WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM documents WHERE id=?", (document_id,))
            if classifier_id:
                c.execute("DELETE FROM document_classifiers WHERE id=?", (classifier_id,))
            if case_file_id:
                c.execute("DELETE FROM document_case_files WHERE id=?", (case_file_id,))
            if policy_id:
                c.execute("DELETE FROM document_retention_policies WHERE id=?", (policy_id,))
            if certificate_id:
                c.execute("DELETE FROM edo_certificates WHERE id=?", (certificate_id,))
            conn.commit()
            conn.close()
            for path in stored_paths:
                if path and os.path.exists(path):
                    os.remove(path)


if __name__ == "__main__":
    unittest.main()
