import time

from fastapi.testclient import TestClient

from main import app
from permissions import DIRECTOR_ROLE, MANAGER_ROLE
from tests.test_helpers import create_test_user, run_db_cleanup


def test_only_responsible_employee_or_director_can_change_deal():
    owner = create_test_user(role=MANAGER_ROLE, name_prefix="Deal Owner")
    colleague = create_test_user(role=MANAGER_ROLE, name_prefix="Deal Viewer")
    director = create_test_user(role=DIRECTOR_ROLE, name_prefix="Deal Director")
    marker = f"DEAL_ACCESS_{int(time.time() * 1000)}"
    deal_id = 0
    payload = {
        "title": marker,
        "client_name": marker,
        "stage": "qualification",
        "responsible": owner["name"],
        "next_action": "Call the client",
        "next_action_date": "12.08.2026",
    }
    try:
        with TestClient(app) as owner_client, TestClient(app) as colleague_client, TestClient(app) as director_client:
            assert owner_client.post("/api/login", json={"email": owner["email"], "password": owner["password"]}).status_code == 200
            assert colleague_client.post("/api/login", json={"email": colleague["email"], "password": colleague["password"]}).status_code == 200
            assert director_client.post("/api/login", json={"email": director["email"], "password": director["password"]}).status_code == 200

            created = owner_client.post("/api/crm/deals", json=payload).json()
            assert created["status"] == "success"
            deal_id = int(created["id"])

            owner_row = next(item for item in owner_client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            colleague_row = next(item for item in colleague_client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            director_row = next(item for item in director_client.get("/api/crm/deals").json() if int(item["id"]) == deal_id)
            assert owner_row["can_manage"] is True
            assert colleague_row["can_manage"] is False
            assert colleague_row["access_mode"] == "read"
            assert director_row["can_manage"] is True

            forbidden_update = colleague_client.put(
                f"/api/crm/deals/{deal_id}",
                json={**payload, "next_action": "Changed by colleague"},
            ).json()
            assert forbidden_update["error"] == "forbidden"

            forbidden_archive = colleague_client.post(f"/api/crm/deals/{deal_id}/archive").json()
            assert forbidden_archive["error"] == "forbidden"

            director_update = director_client.put(
                f"/api/crm/deals/{deal_id}",
                json={**payload, "next_action": "Checked by director"},
            ).json()
            assert director_update["status"] == "success"
    finally:
        run_db_cleanup([
            ("DELETE FROM crm_deals WHERE id=?", (deal_id,)),
            ("DELETE FROM user_sessions WHERE user_email IN (?, ?, ?)", (owner["email"], colleague["email"], director["email"])),
            ("DELETE FROM notifications WHERE user_email IN (?, ?, ?)", (owner["email"], colleague["email"], director["email"])),
            ("DELETE FROM users WHERE email IN (?, ?, ?)", (owner["email"], colleague["email"], director["email"])),
        ])
