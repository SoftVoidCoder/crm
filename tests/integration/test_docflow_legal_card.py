import os
import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class DocflowLegalCardIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.director = create_test_user(role="Директор", name_prefix="Docflow Legal Director")
        login = self.client.post("/api/login", json={"email": self.director["email"], "password": self.director["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        delete_test_user(self.director["email"])

    def test_document_legal_card_registers_classifies_cases_and_lifecycle(self):
        suffix = f"{os.getpid()}-{int(time.time())}"
        document_id = 0
        template_id = 0
        version_id = 0
        journal_id = 0
        classifier_id = 0
        case_file_id = 0
        try:
            created = self.client.post("/api/documents", json={
                "type": "incoming",
                "number": f"QA-LEGAL-{suffix}",
                "d_date": "20.04.2026",
                "correspondent": "QA Legal Sender",
                "subject": "Юридически значимая карточка",
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
            self.assertEqual(created.json()["status"], "success")
            document_id = int(created.json()["id"])

            template = self.client.post("/api/docflow/templates", json={
                "title": f"QA Legal Template {suffix}",
                "doc_type": "incoming",
                "template_kind": "legal_card",
                "version_label": "v1",
                "body_text": "Юридически значимый шаблон: {number} {subject}",
                "variables": ["number", "subject", "registration_number"],
                "status": "active",
                "comment": "Шаблон для юридической карточки",
            })
            self.assertEqual(template.status_code, 200)
            template_id = int(template.json()["id"])

            version = self.client.post("/api/docflow/versions", json={
                "document_id": document_id,
                "version_label": "legal-v1",
                "version_status": "draft",
                "payload": {"subject": "Юридически значимая карточка", "kind": "legal_card"},
                "file_url": "",
                "comment": "Версия карточки для юридического следа",
            })
            self.assertEqual(version.status_code, 200)
            version_id = int(version.json()["id"])

            journal = self.client.post("/api/docflow/registration_journals", json={
                "journal_code": f"QA-JRN-{suffix}",
                "journal_name": "QA Журнал входящих",
                "doc_type": "incoming",
                "prefix": "QAIN",
                "numbering_pattern": "{prefix}/{year}/{number}",
                "is_active": 1,
            })
            self.assertEqual(journal.status_code, 200)
            journal_id = int(journal.json()["id"])

            classifier = self.client.post("/api/docflow/classifiers", json={
                "classifier_code": f"QA-CLS-{suffix}",
                "name": "QA Договорная переписка",
                "doc_type": "incoming",
                "category": "legal_correspondence",
                "required_fields": ["registration_number", "classifier_id", "case_file_id", "retention_until", "legal_significance", "confidentiality_level"],
                "default_lifecycle": "registered",
                "retention_years": 7,
                "is_active": 1,
            })
            self.assertEqual(classifier.status_code, 200)
            classifier_id = int(classifier.json()["id"])

            case_file = self.client.post("/api/docflow/case_files", json={
                "case_index": f"QA-CASE-{suffix}",
                "title": "QA Номенклатурное дело",
                "department": "Юридический отдел",
                "retention_years": 7,
                "opened_at": "20.04.2026",
                "status": "open",
                "responsible_name": self.director["name"],
            })
            self.assertEqual(case_file.status_code, 200)
            case_file_id = int(case_file.json()["id"])

            legal_card = self.client.post(f"/api/docflow/documents/{document_id}/legal_card", json={
                "journal_id": journal_id,
                "classifier_id": classifier_id,
                "case_file_id": case_file_id,
                "legal_significance": "original",
                "confidentiality_level": "confidential",
                "document_kind_code": "LEGAL-IN",
                "auto_register": 1,
                "comment": "Регистрация юридически значимого документа",
            })
            self.assertEqual(legal_card.status_code, 200)
            legal_payload = legal_card.json()
            self.assertEqual(legal_payload["status"], "success")
            self.assertEqual(legal_payload["quality"]["status"], "complete")
            self.assertTrue(legal_payload["document"]["registration_number"].startswith("QAIN/2026/"))
            self.assertEqual(int(legal_payload["document"]["classifier_id"]), classifier_id)
            self.assertEqual(int(legal_payload["document"]["case_file_id"]), case_file_id)
            self.assertEqual(legal_payload["document"]["lifecycle_state"], "registered")
            self.assertEqual(legal_payload["case_file"]["case_index"], f"QA-CASE-{suffix}")
            self.assertGreaterEqual(len(legal_payload["registration_records"]), 1)
            self.assertTrue(any(int(item["id"]) == version_id for item in legal_payload["versions"]))
            self.assertTrue(any(int(item["id"]) == template_id for item in legal_payload["templates"]))

            lifecycle = self.client.post(f"/api/docflow/documents/{document_id}/lifecycle", json={
                "action_name": "sign",
                "target_state": "signed",
                "comment": "Подписано юридическим отделом",
            })
            self.assertEqual(lifecycle.status_code, 200)
            self.assertEqual(lifecycle.json()["document"]["lifecycle_state"], "signed")
            self.assertTrue(any(item["to_state"] == "signed" for item in lifecycle.json()["lifecycle_events"]))

            fetched = self.client.get(f"/api/docflow/documents/{document_id}/legal_card")
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(fetched.json()["document"]["registration_number"], legal_payload["document"]["registration_number"])
            self.assertEqual(fetched.json()["quality"]["status"], "complete")
            self.assertTrue(any(item["payload"].get("kind") == "legal_card" for item in fetched.json()["versions"]))

            directories = self.client.get("/api/docflow/legal_directories")
            self.assertEqual(directories.status_code, 200)
            self.assertTrue(any(int(item["id"]) == journal_id for item in directories.json()["journals"]))
            self.assertTrue(any(int(item["id"]) == classifier_id for item in directories.json()["classifiers"]))
            self.assertTrue(any(int(item["id"]) == case_file_id for item in directories.json()["case_files"]))

            summary = self.client.get("/api/docflow/plus_summary")
            self.assertEqual(summary.status_code, 200)
            summary_payload = summary.json()
            self.assertIn("legal_card_board", summary_payload)
            self.assertTrue(any(int(item["document_id"]) == document_id and item["quality_status"] == "complete" for item in summary_payload["legal_card_board"]))
            self.assertGreaterEqual(int(summary_payload["metrics"]["registered_documents"]), 1)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if document_id:
                c.execute("DELETE FROM document_registration_records WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_lifecycle_events WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_versions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_linked_tasks WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_legal_archive WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_print_forms WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM documents WHERE id=?", (document_id,))
            if version_id:
                c.execute("DELETE FROM document_versions WHERE id=?", (version_id,))
            if template_id:
                c.execute("DELETE FROM document_templates WHERE id=?", (template_id,))
            if journal_id:
                c.execute("DELETE FROM document_registration_journals WHERE id=?", (journal_id,))
            if classifier_id:
                c.execute("DELETE FROM document_classifiers WHERE id=?", (classifier_id,))
            if case_file_id:
                c.execute("DELETE FROM document_case_files WHERE id=?", (case_file_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
