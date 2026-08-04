import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from routers.projects import TELEPHONY_RECORDINGS_DIR
from tests.test_helpers import create_test_user, delete_test_user, run_db_cleanup


class TelephonyRecordingImportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Менеджер", name_prefix="Telephony Import")
        login = self.client.post(
            "/api/login",
            json={"email": self.user["email"], "password": self.user["password"]},
        )
        self.assertEqual(login.status_code, 200)
        self.line_name = f"QA Bitrix {os.getpid()}"
        self.created_paths = []

    def tearDown(self):
        conn = get_connection(row_factory=True)
        try:
            rows = conn.execute(
                "SELECT recording_url FROM telephony_calls WHERE created_by=?",
                (self.user["email"],),
            ).fetchall()
            self.created_paths.extend(
                os.path.join(TELEPHONY_RECORDINGS_DIR, os.path.basename(row["recording_url"]))
                for row in rows
                if row["recording_url"]
            )
        finally:
            conn.close()
        run_db_cleanup([
            ("DELETE FROM telephony_calls WHERE created_by=?", (self.user["email"],)),
            ("DELETE FROM telephony_accounts WHERE created_by=?", (self.user["email"],)),
        ])
        for path in set(self.created_paths):
            try:
                os.remove(path)
            except OSError:
                pass
        delete_test_user(self.user["email"])

    @patch("routers.projects.transcribe_call_audio")
    def test_audio_import_analysis_duplicate_and_content_validation(self, transcribe):
        transcribe.return_value = {
            "transcript": "Менеджер: Добрый день. Клиент: Нужен кожух.",
            "dialog": [
                {"speaker": "manager", "text": "Добрый день.", "confidence": 0.9},
                {"speaker": "customer", "text": "Нужен кожух.", "confidence": 0.9},
            ],
            "summary": "Клиент запросил кожух.",
            "customer_need": "Шумозащитный кожух.",
            "manager_errors": [{
                "type": "не назначил следующий шаг",
                "quote": "",
                "severity": "high",
                "recommendation": "Назначить повторный звонок.",
            }],
            "next_step": "Назначить повторный звонок.",
            "deal_signal": "warm",
            "role_confidence": 0.9,
            "transcription_confidence": 0.9,
            "key_index": 2,
        }
        wav = b"RIFF" + (b"\x00" * 4) + b"WAVEfmt " + (b"\x00" * 64)

        first = self.client.post(
            "/api/telephony/calls/import_recordings",
            data={"line_name": self.line_name, "provider_name": "Bitrix24"},
            files=[("files", ("qa-call.wav", wav, "audio/wav"))],
        )
        self.assertEqual(first.status_code, 200)
        first_payload = first.json()
        self.assertEqual(first_payload["created"], 1)
        self.assertEqual(first_payload["failed"], 0)
        self.assertEqual(first_payload["results"][0]["processing_status"], "needs_review")
        self.assertEqual(first_payload["results"][0]["call_result"], "interested")
        self.assertEqual(first_payload["results"][0]["manager_errors"][0]["severity"], "high")

        duplicate = self.client.post(
            "/api/telephony/calls/import_recordings",
            data={"line_name": self.line_name, "provider_name": "Bitrix24"},
            files=[("files", ("qa-call.wav", wav, "audio/wav"))],
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json()["results"][0]["status"], "duplicate")
        self.assertEqual(transcribe.call_count, 1)

        invalid = self.client.post(
            "/api/telephony/calls/import_recordings",
            data={"line_name": self.line_name, "provider_name": "Bitrix24"},
            files=[("files", ("fake.wav", b"not audio", "audio/wav"))],
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(invalid.json()["results"][0]["error"], "invalid_audio_content")
        self.assertEqual(transcribe.call_count, 1)


if __name__ == "__main__":
    unittest.main()
