import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app
from permissions import (
    ACCOUNTING_ROLE,
    DIRECTOR_ROLE,
    EMPLOYEE_ROLE,
    ENGINEERING_ROLE,
    LEGAL_ROLE,
    MANAGER_ROLE,
    PRODUCTION_ROLE,
    SECRETARY_ROLE,
    WAREHOUSE_ROLE,
)
from tests.test_helpers import create_test_user, run_db_cleanup


DOCUMENT_CREATOR_ROLES = [
    DIRECTOR_ROLE,
    MANAGER_ROLE,
    ENGINEERING_ROLE,
    WAREHOUSE_ROLE,
    ACCOUNTING_ROLE,
    LEGAL_ROLE,
    SECRETARY_ROLE,
    EMPLOYEE_ROLE,
]


@pytest.mark.parametrize("role", DOCUMENT_CREATOR_ROLES)
def test_every_document_creator_role_can_save_initial_pdf(role):
    user = create_test_user(role=role, name_prefix="Document Upload")
    document_id = 0
    uploaded_path = None
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            login = client.post("/api/login", json={"email": user["email"], "password": user["password"]})
            assert login.status_code == 200

            created = client.post(
                "/api/documents",
                json={
                    "type": "outgoing",
                    "document_kind_code": "invoice",
                    "number": f"ROLE-INVOICE-{int(time.time() * 1000)}",
                    "d_date": "09.08.2026",
                    "correspondent": "Тестовый клиент",
                    "subject": "Счёт на оплату",
                    "status": "registered",
                },
            ).json()
            assert created["status"] == "success"
            document_id = int(created["id"])

            # Binary fallback extraction used to preserve NUL and make
            # PostgreSQL reject the entire upload.
            uploaded = client.post(
                f"/api/documents/{document_id}/upload",
                files={"file": ("invoice.pdf", b"%PDF-1.4\n(Invoice\x00test)\n%%EOF", "application/pdf")},
            )
            assert uploaded.status_code == 200
            payload = uploaded.json()
            assert payload["status"] == "success"
            assert "\x00" not in payload["active_revision"]["content_index"]["content_excerpt"]
            uploaded_path = Path(__file__).resolve().parents[2] / payload["url"].lstrip("/")
    finally:
        if uploaded_path:
            uploaded_path.unlink(missing_ok=True)
        run_db_cleanup(
            [
                ("DELETE FROM document_content_index WHERE document_id=?", (document_id,)),
                ("DELETE FROM document_file_blobs WHERE document_id=?", (document_id,)),
                ("DELETE FROM document_file_revisions WHERE document_id=?", (document_id,)),
                ("DELETE FROM documents WHERE id=?", (document_id,)),
                ("DELETE FROM user_sessions WHERE user_email=?", (user["email"],)),
                ("DELETE FROM notifications WHERE user_email=?", (user["email"],)),
                ("DELETE FROM users WHERE email=?", (user["email"],)),
            ]
        )


def test_role_without_document_create_permission_is_rejected_cleanly():
    user = create_test_user(role=PRODUCTION_ROLE, name_prefix="Document Read Only")
    try:
        with TestClient(app) as client:
            client.post("/api/login", json={"email": user["email"], "password": user["password"]})
            response = client.post(
                "/api/documents",
                json={
                    "type": "outgoing",
                    "document_kind_code": "invoice",
                    "number": "FORBIDDEN-INVOICE",
                    "d_date": "09.08.2026",
                    "correspondent": "Тестовый клиент",
                    "subject": "Счёт на оплату",
                    "status": "registered",
                },
            )
            assert response.status_code == 200
            assert response.json()["error"] == "forbidden"
    finally:
        run_db_cleanup(
            [
                ("DELETE FROM user_sessions WHERE user_email=?", (user["email"],)),
                ("DELETE FROM notifications WHERE user_email=?", (user["email"],)),
                ("DELETE FROM users WHERE email=?", (user["email"],)),
            ]
        )
