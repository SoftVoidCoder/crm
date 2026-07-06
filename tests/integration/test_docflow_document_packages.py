import io
import json
import os
import time
import unittest
import zipfile

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DocflowDocumentPackagesIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.director = create_test_user(role="Директор", name_prefix="Package Director")
        login = self.client.post("/api/login", json={"email": self.director["email"], "password": self.director["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        delete_test_user(self.director["email"])

    def _create_document_with_file(self, suffix: str, number: str, body: bytes) -> tuple[int, str]:
        created = self.client.post("/api/documents", json={
            "type": "outgoing",
            "number": number,
            "d_date": "22.04.2026",
            "correspondent": "QA Package Counterparty",
            "subject": f"Пакетный документ {number}",
            "status": "registered",
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
        upload = self.client.post(
            f"/api/documents/{document_id}/upload",
            data={"comment": "Файл комплекта", "make_current": "1"},
            files={"file": (f"{number}.txt", io.BytesIO(body), "text/plain")},
        )
        self.assertEqual(upload.status_code, 200)
        return document_id, os.path.join(BASE_DIR, upload.json()["url"].lstrip("/"))

    def test_package_approval_sign_and_zip_registry(self):
        suffix = f"{os.getpid()}-{int(time.time())}"
        package_id = 0
        approval_id = 0
        document_ids = []
        stored_paths = []
        export_paths = []
        try:
            doc_contract, path_one = self._create_document_with_file(suffix, f"QA-PACK-CTR-{suffix}", b"contract body")
            doc_invoice, path_two = self._create_document_with_file(suffix, f"QA-PACK-INV-{suffix}", b"invoice body")
            document_ids = [doc_contract, doc_invoice]
            stored_paths.extend([path_one, path_two])

            created = self.client.post("/api/docflow/packages", json={
                "package_number": f"QA-PACK-{suffix}",
                "title": "QA комплект договор счет акт",
                "package_kind": "contract_set",
                "document_ids": document_ids,
                "comment": "Собрали комплект",
            })
            self.assertEqual(created.status_code, 200)
            payload = created.json()
            self.assertEqual(payload["status"], "success")
            package_id = int(payload["id"])
            self.assertEqual(len(payload["package"]["items"]), 2)

            detail = self.client.get(f"/api/docflow/packages/{package_id}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["package"]["summary"]["documents_total"], 2)

            approval = self.client.post(f"/api/docflow/packages/{package_id}/send_approval", json={
                "route_rules": [{"stage_name": "QA согласование комплекта", "role_name": "Директор", "sla_hours": 2}],
                "comment": "На согласование",
            })
            self.assertEqual(approval.status_code, 200)
            self.assertEqual(approval.json()["status"], "success")
            approval_id = int(approval.json()["approval_id"])
            self.assertGreater(approval_id, 0)

            strict_sign = self.client.post(f"/api/docflow/packages/{package_id}/sign", json={"strict": 1})
            self.assertEqual(strict_sign.status_code, 200)
            self.assertEqual(strict_sign.json()["error"], "package_signature_gaps")

            signed = self.client.post(f"/api/docflow/packages/{package_id}/sign", json={
                "signer_name": self.director["name"],
                "signer_role": "Директор",
                "comment": "Package manifest signed",
                "strict": 0,
            })
            self.assertEqual(signed.status_code, 200)
            signed_payload = signed.json()
            self.assertEqual(signed_payload["status"], "success")
            self.assertEqual(signed_payload["package"]["status"], "signed_with_gaps")
            self.assertTrue(signed_payload["manifest"]["checksum"])
            self.assertEqual(len(signed_payload["manifest"]["items"]), 2)

            registry = self.client.get(f"/api/docflow/packages/{package_id}/export_registry")
            self.assertEqual(registry.status_code, 200)
            self.assertIn("Реестр пакета документов", registry.text)
            self.assertIn(f"QA-PACK-{suffix}", registry.text)

            archive = self.client.get(f"/api/docflow/packages/{package_id}/export_zip")
            self.assertEqual(archive.status_code, 200)
            self.assertEqual(archive.headers.get("content-type"), "application/zip")
            with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
                names = set(zipped.namelist())
                self.assertIn("registry.txt", names)
                self.assertIn("manifest.json", names)
                self.assertTrue(any(name.startswith("files/") for name in names))
                manifest = json.loads(zipped.read("manifest.json").decode("utf-8"))
                self.assertEqual(manifest["package_id"], package_id)

            conn = get_connection(row_factory=True)
            try:
                row = conn.execute("SELECT registry_file_url, export_file_url FROM document_packages WHERE id=?", (package_id,)).fetchone()
                for key in ("registry_file_url", "export_file_url"):
                    if row and row[key]:
                        export_paths.append(os.path.join(BASE_DIR, row[key].lstrip("/")))
            finally:
                conn.close()
        finally:
            conn = get_connection()
            c = conn.cursor()
            if package_id:
                c.execute("DELETE FROM document_relations WHERE package_id=?", (package_id,))
                c.execute("DELETE FROM document_package_items WHERE package_id=?", (package_id,))
                c.execute("DELETE FROM document_packages WHERE id=?", (package_id,))
            if approval_id:
                c.execute("DELETE FROM approval_sla_events WHERE approval_id=?", (approval_id,))
                c.execute("DELETE FROM approval_delegations WHERE approval_id=?", (approval_id,))
                c.execute("DELETE FROM approval_action_log WHERE approval_id=?", (approval_id,))
                c.execute("DELETE FROM approvals WHERE id=?", (approval_id,))
            for document_id in document_ids:
                c.execute("DELETE FROM document_content_index WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_file_blobs WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_file_revisions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_registration_records WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_lifecycle_events WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_versions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_linked_tasks WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_print_forms WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM documents WHERE id=?", (document_id,))
            conn.commit()
            conn.close()
            for path in stored_paths + export_paths:
                if path and os.path.exists(path):
                    os.remove(path)


if __name__ == "__main__":
    unittest.main()
