import io
import os
import time
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DocumentStorageContentIndexIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.director = create_test_user(role="Директор", name_prefix="Storage Index Director")
        login = self.client.post("/api/login", json={"email": self.director["email"], "password": self.director["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        delete_test_user(self.director["email"])

    def test_upload_creates_blob_content_index_and_global_search_hit(self):
        suffix = f"{os.getpid()}-{int(time.time())}"
        needle = f"архивиндексальфа{suffix}".replace("-", "")
        document_id = 0
        stored_paths = []
        try:
            created = self.client.post("/api/documents", json={
                "type": "incoming",
                "number": f"QA-STORAGE-{suffix}",
                "d_date": "22.04.2026",
                "correspondent": "QA Storage Counterparty",
                "subject": "Проверка файлового индекса",
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

            upload = self.client.post(
                f"/api/documents/{document_id}/upload",
                data={"comment": "Текстовый файл для полнотекстового индекса", "make_current": "1"},
                files={"file": ("storage_index.txt", io.BytesIO(f"Содержимое вложения {needle} сумма 777\n".encode("utf-8")), "text/plain")},
            )
            self.assertEqual(upload.status_code, 200)
            payload = upload.json()
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["active_revision"]["storage"]["validation_status"], "accepted")
            self.assertIn(payload["active_revision"]["storage"]["antivirus_status"], {"clean", "not_configured", "scan_error"})
            self.assertEqual(payload["active_revision"]["content_index"]["extraction_status"], "indexed")
            stored_paths.append(os.path.join(BASE_DIR, payload["url"].lstrip("/")))

            conn = get_connection(row_factory=True)
            try:
                blob = conn.execute(
                    "SELECT * FROM document_file_blobs WHERE document_id=? AND file_revision_id=?",
                    (document_id, int(payload["revision_id"])),
                ).fetchone()
                self.assertIsNotNone(blob)
                self.assertEqual(blob["checksum_sha256"], payload["active_revision"]["checksum"])
                index = conn.execute(
                    "SELECT * FROM document_content_index WHERE document_id=? AND file_revision_id=?",
                    (document_id, int(payload["revision_id"])),
                ).fetchone()
                self.assertIsNotNone(index)
                self.assertIn(needle, index["content_text"])
            finally:
                conn.close()

            search = self.client.get("/api/search", params={"q": needle, "limit": 8})
            self.assertEqual(search.status_code, 200)
            items = search.json()["items"]
            self.assertTrue(
                any(item.get("type") == "document" and int(item.get("entity_id") or 0) == document_id and item.get("match_source") == "document_content_index" for item in items),
                items,
            )
        finally:
            conn = get_connection()
            c = conn.cursor()
            if document_id:
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
            for path in stored_paths:
                if path and os.path.exists(path):
                    os.remove(path)


if __name__ == "__main__":
    unittest.main()
