import io
import json
import os
import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DocflowCryptoSignatureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.director = create_test_user(role="Директор", name_prefix="Crypto Sign Director")
        login = self.client.post("/api/login", json={"email": self.director["email"], "password": self.director["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        delete_test_user(self.director["email"])

    def test_detached_signature_is_bound_to_file_revision_checksum(self):
        suffix = f"{os.getpid()}-{int(time.time())}"
        document_id = 0
        certificate_id = 0
        session_id = 0
        stored_paths = []
        try:
            created = self.client.post("/api/documents", json={
                "type": "outgoing",
                "number": f"QA-CRYPTO-SIGN-{suffix}",
                "d_date": "22.04.2026",
                "correspondent": "QA Crypto Counterparty",
                "subject": "Detached CAdES signature checksum binding",
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
                data={"comment": "Версия для detached подписи", "make_current": "1"},
                files={"file": ("crypto_contract.txt", io.BytesIO(b"crypto-signature-body-v1\n"), "text/plain")},
            )
            self.assertEqual(upload.status_code, 200)
            stored_paths.append(os.path.join(BASE_DIR, upload.json()["url"].lstrip("/")))

            certificate = self.client.post("/api/docflow/certificates", json={
                "owner_name": self.director["name"],
                "owner_email": self.director["email"],
                "signer_role": "Директор",
                "provider_name": "КриптоПро",
                "thumbprint": f"QA-CRYPTO-THUMB-{suffix}",
                "serial_number": f"QA-CRYPTO-SERIAL-{suffix}",
                "valid_from": "20.04.2026",
                "valid_to": "30.04.2026",
                "status": "active",
                "comment": "Тестовый сертификат для detached подписи",
            })
            self.assertEqual(certificate.status_code, 200)
            certificate_id = int(certificate.json()["id"])

            start = self.client.post(f"/api/docflow/documents/{document_id}/signature_sessions", json={
                "certificate_id": certificate_id,
                "signature_kind": "КЭП",
                "signature_provider": "КриптоПро",
                "signature_format": "CAdES detached",
                "comment": "Сессия реальной detached подписи",
            })
            self.assertEqual(start.status_code, 200)
            self.assertEqual(start.json()["status"], "success")
            session_id = int(start.json()["session_id"])
            signing_payload = start.json()["signing_payload"]
            signed_checksum = signing_payload["checksum"]

            detached_payload = {
                "format": "CAdES detached",
                "document_checksum": signed_checksum,
                "certificate_thumbprint": f"QA-CRYPTO-THUMB-{suffix}",
                "timestamp": "2026-04-22T12:00:00+03:00",
                "timestamp_status": "present",
                "ocsp_status": "good",
                "crl_status": "clear",
                "signature_value": f"qa-detached-{signed_checksum[:16]}",
            }
            detached = self.client.post(
                f"/api/docflow/signature_sessions/{session_id}/detached",
                data={"comment": "Detached .sig загружен из КриптоПро"},
                files={"file": ("crypto_contract.sig", io.BytesIO(json.dumps(detached_payload).encode("utf-8")), "application/pkcs7-signature")},
            )
            self.assertEqual(detached.status_code, 200)
            self.assertEqual(detached.json()["status"], "success")
            stored_paths.append(os.path.join(BASE_DIR, detached.json()["session"]["detached_signature_url"].lstrip("/")))

            verified = self.client.post(f"/api/docflow/signature_sessions/{session_id}/verify", json={
                "comment": "Проверка detached .sig",
                "force": 1,
            })
            self.assertEqual(verified.status_code, 200)
            verified_payload = verified.json()
            self.assertEqual(verified_payload["status"], "success")
            self.assertEqual(verified_payload["verification"]["status"], "valid")
            self.assertGreater(int(verified_payload["signature_id"]), 0)
            self.assertGreater(int(verified_payload["protocol_id"]), 0)

            card = self.client.get(f"/api/docflow/documents/{document_id}/legal_card")
            self.assertEqual(card.status_code, 200)
            card_payload = card.json()
            self.assertEqual(card_payload["signature_summary"]["display_status"], "Подпись действительна")
            self.assertEqual(int(card_payload["signatures"][0]["covers_current_revision"]), 1)
            self.assertEqual(card_payload["signatures"][0]["detached_signature_checksum"], detached.json()["session"]["detached_signature_checksum"])
            self.assertGreaterEqual(len(card_payload["signature_validation_protocols"]), 1)

            protocol = self.client.post(f"/api/docflow/signature_sessions/{session_id}/protocols", json={
                "protocol_status": "attached",
                "protocol_number": f"QA-PROTOCOL-{suffix}",
                "validation_result": "valid",
                "validation_message": "Юридический протокол приложен",
                "provider": "КриптоПро",
                "checks": {"manual_review": "accepted"},
                "raw_protocol": {"source": "qa"},
            })
            self.assertEqual(protocol.status_code, 200)
            self.assertEqual(protocol.json()["status"], "success")

            second_upload = self.client.post(
                f"/api/documents/{document_id}/upload",
                data={"comment": "Новая версия после подписи", "make_current": "1"},
                files={"file": ("crypto_contract_v2.txt", io.BytesIO(b"crypto-signature-body-v2\n"), "text/plain")},
            )
            self.assertEqual(second_upload.status_code, 200)
            stored_paths.append(os.path.join(BASE_DIR, second_upload.json()["url"].lstrip("/")))

            stale_card = self.client.get(f"/api/docflow/documents/{document_id}/legal_card")
            self.assertEqual(stale_card.status_code, 200)
            stale_payload = stale_card.json()
            self.assertEqual(stale_payload["signature_summary"]["status"], "stale_revision")
            self.assertEqual(stale_payload["signature_summary"]["display_status"], "Подпись не покрывает текущую версию файла")
            self.assertEqual(int(stale_payload["signatures"][0]["covers_current_revision"]), 0)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if document_id:
                c.execute("DELETE FROM signature_validation_protocols WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM signature_sessions WHERE document_id=?", (document_id,))
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
