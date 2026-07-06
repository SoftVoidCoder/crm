import io
import os
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DocflowSignaturesLegalityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.director = create_test_user(role="Директор", name_prefix="Docflow Sign Director")
        login = self.client.post("/api/login", json={"email": self.director["email"], "password": self.director["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        delete_test_user(self.director["email"])

    def test_document_supports_signature_verification_and_legal_archive(self):
        document_id = 0
        certificate_id = 0
        stored_paths = []
        try:
            created = self.client.post("/api/documents", json={
                "type": "outgoing",
                "number": "QA-SIGN-LEGAL-001",
                "d_date": "21.04.2026",
                "correspondent": "QA Sign Counterparty",
                "subject": "Проверка ЭП и юридической значимости",
                "status": "draft",
                "project_id": 0,
                "contract_id": 0,
                "object_id": 0,
                "parent_id": 0,
                "priority": "high",
                "resolution": "",
                "resolution_author": "",
                "resolution_deadline": "",
                "resolution_assignee": "",
                "resolution_task_id": 0,
            })
            self.assertEqual(created.status_code, 200)
            document_id = int(created.json()["id"])

            upload = self.client.post(
                f"/api/documents/{document_id}/upload",
                data={"comment": "Исходная редакция для подписи", "make_current": "1"},
                files={"file": ("signed_contract.txt", io.BytesIO(b"qualified-signature-body\nline-2\n"), "text/plain")},
            )
            self.assertEqual(upload.status_code, 200)
            stored_paths.append(os.path.join(BASE_DIR, upload.json()["url"].lstrip("/")))

            certificate = self.client.post("/api/docflow/certificates", json={
                "owner_name": self.director["name"],
                "owner_email": self.director["email"],
                "signer_role": "Директор",
                "provider_name": "КриптоПро",
                "thumbprint": "QA-CERT-THUMBPRINT-001",
                "serial_number": "QA-CERT-SERIAL-001",
                "valid_from": "20.04.2026",
                "valid_to": "30.04.2026",
                "status": "active",
                "comment": "Тестовый квалифицированный сертификат",
            })
            self.assertEqual(certificate.status_code, 200)
            certificate_id = int(certificate.json()["id"])

            sign = self.client.post(f"/api/docflow/documents/{document_id}/signatures", json={
                "certificate_id": certificate_id,
                "signature_kind": "КЭП",
                "signature_provider": "КриптоПро",
                "comment": "Документ подписан квалифицированной подписью",
            })
            self.assertEqual(sign.status_code, 200)
            sign_payload = sign.json()
            self.assertEqual(sign_payload["document"]["lifecycle_state"], "signed")
            self.assertGreaterEqual(int(sign_payload["signature_summary"]["valid_signatures_total"]), 1)
            self.assertEqual(sign_payload["signature_summary"]["legal_force"], "qualified")
            self.assertEqual(sign_payload["signatures"][0]["verification_status"], "valid")
            self.assertEqual(sign_payload["signatures"][0]["stamp"]["document_number"], "QA-SIGN-LEGAL-001")
            self.assertEqual(sign_payload["signature_quality"]["status"], "complete")

            signatures = self.client.get(f"/api/docflow/documents/{document_id}/signatures")
            self.assertEqual(signatures.status_code, 200)
            self.assertGreaterEqual(int(signatures.json()["signature_summary"]["signatures_total"]), 1)

            verify = self.client.post(f"/api/docflow/documents/{document_id}/verify_signatures", json={
                "comment": "Повторная проверка сертификата и хеша",
                "force": 1,
            })
            self.assertEqual(verify.status_code, 200)
            self.assertGreaterEqual(int(verify.json()["valid_total"]), 1)
            self.assertTrue(all(item["status"] == "valid" for item in verify.json()["processed"]))

            archive = self.client.post(f"/api/docflow/documents/{document_id}/archive_legal", json={
                "comment": "Передача документа в юридический архив",
            })
            self.assertEqual(archive.status_code, 200)
            archive_payload = archive.json()
            self.assertEqual(archive_payload["document"]["lifecycle_state"], "archived")
            self.assertGreaterEqual(len(archive_payload["archive_entries"]), 1)
            self.assertEqual(
                archive_payload["archive_entries"][0]["archive_hash"],
                archive_payload["active_file_revision"]["checksum"],
            )

            legal_card = self.client.get(f"/api/docflow/documents/{document_id}/legal_card")
            self.assertEqual(legal_card.status_code, 200)
            legal_payload = legal_card.json()
            self.assertEqual(legal_payload["signature_quality"]["legal_force"], "qualified")
            self.assertGreaterEqual(len(legal_payload["signatures"]), 1)
            self.assertGreaterEqual(len(legal_payload["archive_entries"]), 1)

            summary = self.client.get("/api/docflow/plus_summary")
            self.assertEqual(summary.status_code, 200)
            summary_payload = summary.json()
            self.assertTrue(any(int(item["document_id"]) == document_id for item in summary_payload["signature_board"]))
            self.assertTrue(any(item.get("kind") == "signature" and int(item.get("document_id") or 0) == document_id for item in summary_payload["timeline"]))
            self.assertGreaterEqual(int(summary_payload["metrics"]["signatures_total"]), 1)
            self.assertGreaterEqual(int(summary_payload["metrics"]["documents_with_valid_signatures"]), 1)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if document_id:
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
