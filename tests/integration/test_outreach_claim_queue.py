import time

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from permissions import MANAGER_ROLE
from tests.test_helpers import create_test_user, run_db_cleanup


def test_manager_claims_free_client_and_hides_it_from_other_managers():
    manager_one = create_test_user(role=MANAGER_ROLE, name_prefix="Claim Manager One")
    manager_two = create_test_user(role=MANAGER_ROLE, name_prefix="Claim Manager Two")
    marker = f"CLAIM_QUEUE_{int(time.time() * 1000)}"
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO outreach_prospects (
                company_name, source_name, status, priority, manager_name, manager_email,
                created_by, created_at, updated_at
            ) VALUES (?, 'Bitrix24 API', 'new', 'normal', '', '', 'test', ?, ?)
            """,
            (marker, int(time.time()), int(time.time())),
        )
        prospect_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()

    try:
        with TestClient(app) as first_client, TestClient(app) as second_client:
            assert first_client.post("/api/login", json={"email": manager_one["email"], "password": manager_one["password"]}).status_code == 200
            assert second_client.post("/api/login", json={"email": manager_two["email"], "password": manager_two["password"]}).status_code == 200

            first_free = first_client.get("/api/outreach/prospects", params={"scope": "free"}).json()
            second_free = second_client.get("/api/outreach/prospects", params={"scope": "free"}).json()
            assert prospect_id in {int(row["id"]) for row in first_free}
            assert prospect_id in {int(row["id"]) for row in second_free}

            claimed = first_client.post(f"/api/outreach/prospects/{prospect_id}/claim")
            assert claimed.status_code == 200
            assert claimed.json()["status"] == "success"

            lost_race = second_client.post(f"/api/outreach/prospects/{prospect_id}/claim")
            assert lost_race.status_code == 200
            assert lost_race.json()["error"] == "already_claimed"

            first_mine = first_client.get("/api/outreach/prospects", params={"scope": "mine"}).json()
            second_mine = second_client.get("/api/outreach/prospects", params={"scope": "mine"}).json()
            second_free_after = second_client.get("/api/outreach/prospects", params={"scope": "free"}).json()
            second_default = second_client.get("/api/outreach/prospects").json()
            assert prospect_id in {int(row["id"]) for row in first_mine}
            assert prospect_id not in {int(row["id"]) for row in second_mine}
            assert prospect_id not in {int(row["id"]) for row in second_free_after}
            assert prospect_id not in {int(row["id"]) for row in second_default}

            forbidden_activity = second_client.post(
                "/api/outreach/activities",
                json={"prospect_id": prospect_id, "activity_type": "call", "summary": "foreign client"},
            )
            assert forbidden_activity.json()["error"] == "forbidden"

            own_activity = first_client.post(
                "/api/outreach/activities",
                json={"prospect_id": prospect_id, "activity_type": "call", "summary": "own client"},
            )
            assert own_activity.json()["status"] == "success"

            rejection = first_client.post(
                "/api/outreach/activities",
                json={
                    "prospect_id": prospect_id,
                    "activity_type": "note",
                    "result_status": "do_not_contact",
                    "prospect_status": "do_not_contact",
                    "summary": "Причина отказа: нет бюджета",
                },
            )
            assert rejection.json()["status"] == "success"
            rejected_card = next(
                row
                for row in first_client.get("/api/outreach/prospects", params={"scope": "mine"}).json()
                if int(row["id"]) == prospect_id
            )
            assert rejected_card["status"] == "do_not_contact"
            assert rejected_card["activities"][0]["summary"] == "Причина отказа: нет бюджета"

            manager_bitrix_status = first_client.get("/api/integrations/bitrix24/status").json()
            assert manager_bitrix_status.get("error") != "forbidden"
            assert first_client.post("/api/integrations/bitrix24/configure", json={"webhook_url": ""}).json()["error"] == "forbidden"
    finally:
        run_db_cleanup(
            [
                ("DELETE FROM outreach_activities WHERE prospect_id=?", (prospect_id,)),
                ("DELETE FROM outreach_prospects WHERE id=?", (prospect_id,)),
                ("DELETE FROM user_sessions WHERE user_email IN (?, ?)", (manager_one["email"], manager_two["email"])),
                ("DELETE FROM users WHERE email IN (?, ?)", (manager_one["email"], manager_two["email"])),
            ]
        )
