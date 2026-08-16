import time
from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from tests.test_helpers import create_test_user, run_db_cleanup


def test_deal_keeps_business_fields_and_attached_document():
    director = create_test_user(role="Директор", name_prefix="Deal Documents")
    marker = f"DEAL_DOC_{int(time.time() * 1000)}"
    client_id = 0
    deal_id = 0
    document_id = 0
    uploaded_file_path = None
    try:
        with TestClient(app) as client:
            assert client.post("/api/login", json={"email": director["email"], "password": director["password"]}).status_code == 200
            created_client = client.post("/api/clients", json={
                "name": "ООО Проверка",
                "inn": str(int(time.time() * 1000))[-10:],
                "contact": "test@example.com",
            }).json()
            assert created_client["status"] == "success"
            client_id = int(created_client["id"])
            deal = client.post("/api/crm/deals", json={
                "title": marker,
                "client_id": client_id,
                "client_name": "ООО Проверка",
                "contact_name": "Иван Петров",
                "contact_position": "Главный инженер",
                "contact_phone": "+7 900 000-00-00",
                "contact_email": "test@example.com",
                "source": "Рекомендация",
                "stage": "proposal",
                "amount": 500000,
                "margin_percent": 20,
                "probability": 70,
                "responsible": director["name"],
                "next_action": "Согласовать КП",
                "next_action_date": "10.08.2026",
                "expected_close_date": "20.08.2026",
                "products": [{"name": "Шумоглушитель", "quantity": 2, "unit_price": 250000}],
                "co_executors": "Инженер",
            }).json()
            assert deal["status"] == "success"
            deal_id = int(deal["id"])

            document = client.post("/api/documents", json={
                "type": "outgoing",
                "document_kind_code": "commercial_proposal",
                "number": marker,
                "d_date": "08.08.2026",
                "correspondent": "ООО Проверка",
                "recipient_name": "ООО Проверка",
                "subject": "Коммерческое предложение",
                "status": "registered",
                "client_id": client_id,
                "client_source": "bitrix24",
                "client_source_id": 99123,
                "deal_id": deal_id,
            }).json()
            assert document["status"] == "success"
            document_id = int(document["id"])

            uploaded = client.post(
                f"/api/documents/{document_id}/upload",
                files={"file": ("commercial-proposal.txt", b"Commercial proposal test file", "text/plain")},
            ).json()
            assert uploaded["status"] == "success"
            uploaded_file_path = Path(__file__).resolve().parents[2] / str(uploaded["url"]).lstrip("/")

            document_row = next(item for item in client.get("/api/documents").json() if int(item["id"]) == document_id)
            assert int(document_row["client_id"]) == client_id
            assert document_row["client_source"] == "bitrix24"
            assert int(document_row["client_source_id"]) == 99123
            assert int(document_row["deal_id"]) == deal_id
            assert document_row["document_kind_code"] == "commercial_proposal"
            assert document_row["file_url"] == uploaded["url"]

            row_with_direct_document = next(item for item in client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            assert int(row_with_direct_document["documents"][0]["id"]) == document_id

            updated_document = client.put(f"/api/documents/{document_id}", json={
                "type": document_row["type"],
                "document_kind_code": document_row["document_kind_code"],
                "number": document_row["number"],
                "d_date": document_row["d_date"],
                "correspondent": document_row["correspondent"],
                "sender_name": document_row["sender_name"],
                "recipient_name": document_row["recipient_name"],
                "subject": document_row["subject"],
                "status": "registered",
                "client_id": client_id,
                "client_source": "bitrix24",
                "client_source_id": 99123,
                "deal_id": deal_id,
            }).json()
            assert updated_document["status"] == "success"
            document_after_update = next(item for item in client.get("/api/documents").json() if int(item["id"]) == document_id)
            assert int(document_after_update["client_id"]) == client_id
            assert int(document_after_update["deal_id"]) == deal_id
            assert document_after_update["document_kind_code"] == "commercial_proposal"

            detached = client.delete(f"/api/crm/deals/{deal_id}/documents/{document_id}").json()
            assert detached["status"] == "success"
            row_after_detach = next(item for item in client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            assert row_after_detach["documents"] == []

            attached = client.post(f"/api/crm/deals/{deal_id}/documents/{document_id}").json()
            assert attached["status"] == "success"

            row = next(item for item in client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            assert row["contact_name"] == "Иван Петров"
            assert row["products"][0]["name"] == "Шумоглушитель"
            assert int(row["documents"][0]["id"]) == document_id

            detached_again = client.delete(f"/api/crm/deals/{deal_id}/documents/{document_id}").json()
            assert detached_again["status"] == "success"
            row_after = next(item for item in client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            assert row_after["documents"] == []
    finally:
        if uploaded_file_path and uploaded_file_path.exists():
            uploaded_file_path.unlink()
        run_db_cleanup([
            ("DELETE FROM document_content_index WHERE document_id=?", (document_id,)),
            ("DELETE FROM document_file_blobs WHERE document_id=?", (document_id,)),
            ("DELETE FROM document_file_revisions WHERE document_id=?", (document_id,)),
            ("DELETE FROM documents WHERE id=?", (document_id,)),
            ("DELETE FROM crm_deals WHERE id=?", (deal_id,)),
            ("DELETE FROM clients WHERE id=?", (client_id,)),
            ("DELETE FROM user_sessions WHERE user_email=?", (director["email"],)),
            ("DELETE FROM notifications WHERE user_email=?", (director["email"],)),
            ("DELETE FROM users WHERE email=?", (director["email"],)),
        ])


def test_manager_must_provide_reason_when_closing_deal():
    manager = create_test_user(role="Менеджер", name_prefix="Deal Close")
    marker = f"DEAL_CLOSE_{int(time.time() * 1000)}"
    deal_id = 0
    try:
        with TestClient(app) as client:
            assert client.post("/api/login", json={"email": manager["email"], "password": manager["password"]}).status_code == 200
            payload = {
                "title": marker,
                "client_name": "ООО Проверка закрытия",
                "stage": "qualification",
                "responsible": manager["name"],
                "next_action": "Позвонить клиенту",
                "next_action_date": "10.08.2026",
            }
            created = client.post("/api/crm/deals", json=payload).json()
            assert created["status"] == "success"
            deal_id = int(created["id"])

            premature_archive = client.post(f"/api/crm/deals/{deal_id}/archive").json()
            assert premature_archive["error"] == "deal_not_closed"

            without_reason = client.put(f"/api/crm/deals/{deal_id}", json={**payload, "stage": "lost", "next_action": "", "next_action_date": ""}).json()
            assert without_reason["error"] == "close_reason_required"

            closed = client.put(f"/api/crm/deals/{deal_id}", json={**payload, "stage": "lost", "next_action": "", "next_action_date": "", "loss_reason": "Клиент выбрал другого поставщика"}).json()
            assert closed["status"] == "success"
            row = next(item for item in client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            assert row["loss_reason"] == "Клиент выбрал другого поставщика"
            assert row["actual_close_date"]

            archived = client.post(f"/api/crm/deals/{deal_id}/archive").json()
            assert archived["status"] == "success"
            archived_row = next(item for item in client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            assert int(archived_row["is_archived"]) == 1
            assert int(archived_row["archived_at"]) > 0

            restored = client.post(f"/api/crm/deals/{deal_id}/restore").json()
            assert restored["status"] == "success"
            restored_row = next(item for item in client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            assert int(restored_row["is_archived"]) == 0
    finally:
        run_db_cleanup([
            ("DELETE FROM crm_deals WHERE id=?", (deal_id,)),
            ("DELETE FROM user_sessions WHERE user_email=?", (manager["email"],)),
            ("DELETE FROM notifications WHERE user_email=?", (manager["email"],)),
            ("DELETE FROM users WHERE email=?", (manager["email"],)),
        ])


def test_manager_archives_deal_for_director_too():
    manager = create_test_user(role="Менеджер", name_prefix="Shared Deal Manager")
    director = create_test_user(role="Директор", name_prefix="Shared Deal Director")
    marker = f"SHARED_DEAL_ARCHIVE_{int(time.time() * 1000)}"
    deal_id = 0
    try:
        with TestClient(app) as manager_client, TestClient(app) as director_client:
            assert manager_client.post("/api/login", json={"email": manager["email"], "password": manager["password"]}).status_code == 200
            assert director_client.post("/api/login", json={"email": director["email"], "password": director["password"]}).status_code == 200
            created = manager_client.post("/api/crm/deals", json={
                "title": marker,
                "client_name": marker,
                "stage": "won",
                "responsible": manager["name"],
                "loss_reason": "Сотрудничество успешно завершено",
            }).json()
            assert created["status"] == "success"
            deal_id = int(created["id"])

            before = next(item for item in director_client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            assert int(before["is_archived"]) == 0

            archived = manager_client.post(f"/api/crm/deals/{deal_id}/archive").json()
            assert archived["status"] == "success"

            manager_row = next(item for item in manager_client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            director_row = next(item for item in director_client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            assert int(manager_row["is_archived"]) == 1
            assert int(director_row["is_archived"]) == 1
            assert int(manager_row["archived_at"]) == int(director_row["archived_at"])
    finally:
        run_db_cleanup([
            ("DELETE FROM crm_deals WHERE id=?", (deal_id,)),
            ("DELETE FROM user_sessions WHERE user_email IN (?, ?)", (manager["email"], director["email"])),
            ("DELETE FROM notifications WHERE user_email IN (?, ?)", (manager["email"], director["email"])),
            ("DELETE FROM users WHERE email IN (?, ?)", (manager["email"], director["email"])),
        ])
