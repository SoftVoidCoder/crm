import io
import os
import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DocflowFileVersioningIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.director = create_test_user(role="Директор", name_prefix="Docflow File Director")
        login = self.client.post("/api/login", json={"email": self.director["email"], "password": self.director["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        delete_test_user(self.director["email"])

    def test_document_file_versions_support_history_diff_and_restore(self):
        document_id = 0
        revision_one_id = 0
        revision_two_id = 0
        stored_paths = []
        try:
            created = self.client.post("/api/documents", json={
                "type": "incoming",
                "number": "QA-FILE-VERS-001",
                "d_date": "21.04.2026",
                "correspondent": "QA File Sender",
                "subject": "Проверка файловых ревизий",
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

            upload_one = self.client.post(
                f"/api/documents/{document_id}/upload",
                data={"comment": "Первая редакция файла", "make_current": "1"},
                files={"file": ("contract_v1.txt", io.BytesIO(b"version-one\nline-1\n"), "text/plain")},
            )
            self.assertEqual(upload_one.status_code, 200)
            revision_one_id = int(upload_one.json()["revision_id"])
            url_one = upload_one.json()["url"]
            stored_paths.append(os.path.join(BASE_DIR, url_one.lstrip("/")))

            upload_two = self.client.post(
                f"/api/documents/{document_id}/upload",
                data={"comment": "Вторая редакция файла", "make_current": "1"},
                files={"file": ("contract_v2.txt", io.BytesIO(b"version-two\nline-1\nline-2\n"), "text/plain")},
            )
            self.assertEqual(upload_two.status_code, 200)
            revision_two_id = int(upload_two.json()["revision_id"])
            url_two = upload_two.json()["url"]
            stored_paths.append(os.path.join(BASE_DIR, url_two.lstrip("/")))

            versions = self.client.get(f"/api/docflow/documents/{document_id}/file_versions")
            self.assertEqual(versions.status_code, 200)
            versions_payload = versions.json()
            self.assertEqual(int(versions_payload["active_revision"]["id"]), revision_two_id)
            self.assertEqual(len(versions_payload["revisions"]), 2)
            self.assertTrue(any(int(item["id"]) == revision_one_id and int(item["is_current"]) == 0 for item in versions_payload["revisions"]))
            self.assertTrue(any(int(item["id"]) == revision_two_id and int(item["is_current"]) == 1 for item in versions_payload["revisions"]))

            diff = self.client.get(f"/api/docflow/file_versions/{revision_two_id}/diff")
            self.assertEqual(diff.status_code, 200)
            diff_payload = diff.json()
            self.assertEqual(int(diff_payload["previous_revision_id"]), revision_one_id)
            self.assertGreaterEqual(int(diff_payload["change_count"]), 1)
            self.assertTrue(any(item["field_name"] in {"original_filename", "checksum", "file_size"} for item in diff_payload["diff_items"]))

            activate = self.client.post(f"/api/docflow/file_versions/{revision_one_id}/activate")
            self.assertEqual(activate.status_code, 200)
            self.assertEqual(int(activate.json()["active_revision"]["id"]), revision_one_id)

            legal_card = self.client.get(f"/api/docflow/documents/{document_id}/legal_card")
            self.assertEqual(legal_card.status_code, 200)
            legal_payload = legal_card.json()
            self.assertEqual(int(legal_payload["active_file_revision"]["id"]), revision_one_id)
            self.assertEqual(legal_payload["document"]["file_url"], url_one)
            self.assertGreaterEqual(len(legal_payload["file_revisions"]), 2)

            summary = self.client.get("/api/docflow/plus_summary")
            self.assertEqual(summary.status_code, 200)
            summary_payload = summary.json()
            self.assertTrue(any(int(item["document_id"]) == document_id and int(item["revisions_total"]) >= 2 for item in summary_payload["file_revision_board"]))
            self.assertTrue(any(item.get("kind") == "file_revision" and int(item.get("document_id") or 0) == document_id for item in summary_payload["timeline"]))
            self.assertGreaterEqual(int(summary_payload["metrics"]["documents_with_file_history"]), 1)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if document_id:
                c.execute("DELETE FROM document_file_revisions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_versions WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_registration_records WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_lifecycle_events WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_linked_tasks WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_legal_archive WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM document_print_forms WHERE document_id=?", (document_id,))
                c.execute("DELETE FROM documents WHERE id=?", (document_id,))
            conn.commit()
            conn.close()
            for path in stored_paths:
                if path and os.path.exists(path):
                    os.remove(path)


if __name__ == "__main__":
    unittest.main()
