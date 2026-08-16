import time

from fastapi.testclient import TestClient

from main import app
from permissions import DIRECTOR_ROLE, MANAGER_ROLE
from tests.test_helpers import create_test_user, run_db_cleanup


def test_manager_transfers_lead_and_loses_access():
    first = create_test_user(role=MANAGER_ROLE, name_prefix="Lead Transfer One")
    second = create_test_user(role=MANAGER_ROLE, name_prefix="Lead Transfer Two")
    director = create_test_user(role=DIRECTOR_ROLE, name_prefix="Lead Transfer Director")
    marker = f"LEAD_TRANSFER_{int(time.time() * 1000)}"
    lead_id = 0
    try:
        with TestClient(app) as first_client, TestClient(app) as second_client, TestClient(app) as director_client:
            assert first_client.post("/api/login", json={"email": first["email"], "password": first["password"]}).status_code == 200
            assert second_client.post("/api/login", json={"email": second["email"], "password": second["password"]}).status_code == 200
            assert director_client.post("/api/login", json={"email": director["email"], "password": director["password"]}).status_code == 200

            created = first_client.post(
                "/api/crm/leads",
                json={
                    "title": marker,
                    "client_name": "Transfer test company",
                    "stage": "new",
                    "responsible": second["name"],
                    "next_action": "First call",
                },
            ).json()
            assert created["status"] == "success"
            lead_id = int(created["id"])

            first_rows = first_client.get("/api/crm/leads").json()
            second_rows = second_client.get("/api/crm/leads").json()
            assert lead_id in {int(row["id"]) for row in first_rows}
            assert lead_id not in {int(row["id"]) for row in second_rows}
            assert next(row for row in first_rows if int(row["id"]) == lead_id)["responsible"] == first["name"]

            forbidden_before_transfer = second_client.post(
                "/api/crm/activities",
                json={"entity_type": "lead", "entity_id": lead_id, "activity_type": "call", "subject": "Foreign call"},
            ).json()
            assert forbidden_before_transfer["error"] == "forbidden"

            transferred = first_client.post(
                f"/api/crm/leads/{lead_id}/transfer",
                json={"manager_email": second["email"]},
            ).json()
            assert transferred["status"] == "success"
            assert transferred["manager_email"] == second["email"]

            first_after = first_client.get("/api/crm/leads").json()
            second_after = second_client.get("/api/crm/leads").json()
            assert lead_id not in {int(row["id"]) for row in first_after}
            assert lead_id in {int(row["id"]) for row in second_after}

            old_owner_activity = first_client.post(
                "/api/crm/activities",
                json={"entity_type": "lead", "entity_id": lead_id, "activity_type": "call", "subject": "Old owner"},
            ).json()
            assert old_owner_activity["error"] == "forbidden"

            new_owner_activity = second_client.post(
                "/api/crm/activities",
                json={"entity_type": "lead", "entity_id": lead_id, "activity_type": "call", "subject": "New owner"},
            ).json()
            assert new_owner_activity["status"] == "success"

            transferred_to_director = second_client.post(
                f"/api/crm/leads/{lead_id}/transfer",
                json={"manager_email": director["email"]},
            ).json()
            assert transferred_to_director["status"] == "success"
            assert transferred_to_director["manager_email"] == director["email"]
            assert lead_id not in {int(row["id"]) for row in second_client.get("/api/crm/leads").json()}
            assert lead_id in {int(row["id"]) for row in director_client.get("/api/crm/leads").json()}
    finally:
        cleanup = []
        if lead_id:
            cleanup.extend(
                [
                    ("DELETE FROM crm_activities WHERE entity_type='lead' AND entity_id=?", (lead_id,)),
                    ("DELETE FROM crm_leads WHERE id=?", (lead_id,)),
                    ("DELETE FROM audit_log WHERE entity_type IN ('crm_lead', 'crm_activity') AND entity_id=?", (str(lead_id),)),
                ]
            )
        cleanup.extend(
            [
                ("DELETE FROM notifications WHERE user_email IN (?, ?, ?) AND entity_type='crm_lead'", (first["email"], second["email"], director["email"])),
                ("DELETE FROM audit_log WHERE actor_email IN (?, ?, ?)", (first["email"], second["email"], director["email"])),
                ("DELETE FROM user_sessions WHERE user_email IN (?, ?, ?)", (first["email"], second["email"], director["email"])),
                ("DELETE FROM users WHERE email IN (?, ?, ?)", (first["email"], second["email"], director["email"])),
            ]
        )
        run_db_cleanup(cleanup)


def test_manager_converts_lead_to_deal_with_client_data():
    manager = create_test_user(role=MANAGER_ROLE, name_prefix="Lead Convert Manager")
    marker = f"LEAD_CONVERT_{int(time.time() * 1000)}"
    lead_id = 0
    deal_id = 0
    try:
        with TestClient(app) as client:
            assert client.post("/api/login", json={"email": manager["email"], "password": manager["password"]}).status_code == 200

            created = client.post(
                "/api/crm/leads",
                json={
                    "title": marker,
                    "client_name": "Convert test company",
                    "contact_name": "Test Contact",
                    "contact_phone": "+7 900 000-00-01",
                    "contact_email": "contact@example.test",
                    "source": "Bitrix24",
                    "stage": "qualified",
                    "probability": 65,
                    "budget": 1250000,
                    "next_action": "Prepare proposal",
                    "next_action_date": "2026-08-20",
                    "comment": "Confirmed requirement",
                },
            ).json()
            assert created["status"] == "success"
            lead_id = int(created["id"])

            converted = client.post(f"/api/crm/leads/{lead_id}/convert").json()
            assert converted["status"] == "success"
            deal_id = int(converted["deal_id"])

            lead = next(row for row in client.get("/api/crm/leads").json() if int(row["id"]) == lead_id)
            assert lead["stage"] == "won"
            assert int(lead["linked_deal_id"]) == deal_id

            deal = next(row for row in client.get("/api/crm/deals").json() if int(row["id"]) == deal_id)
            assert deal["client_name"] == "Convert test company"
            assert deal["contact_name"] == "Test Contact"
            assert deal["contact_phone"] == "+7 900 000-00-01"
            assert deal["contact_email"] == "contact@example.test"
            assert deal["source"] == "Bitrix24"
            assert float(deal["amount"]) == 1250000

            converted_again = client.post(f"/api/crm/leads/{lead_id}/convert").json()
            assert int(converted_again["deal_id"]) == deal_id
    finally:
        cleanup = []
        if deal_id:
            cleanup.append(("DELETE FROM crm_deals WHERE id=?", (deal_id,)))
        if lead_id:
            cleanup.extend(
                [
                    ("DELETE FROM crm_activities WHERE entity_type='lead' AND entity_id=?", (lead_id,)),
                    ("DELETE FROM crm_leads WHERE id=?", (lead_id,)),
                    ("DELETE FROM audit_log WHERE entity_type IN ('crm_lead', 'crm_deal') AND entity_id IN (?, ?)", (str(lead_id), str(deal_id))),
                ]
            )
        cleanup.extend(
            [
                ("DELETE FROM user_sessions WHERE user_email=?", (manager["email"],)),
                ("DELETE FROM audit_log WHERE actor_email=?", (manager["email"],)),
                ("DELETE FROM users WHERE email=?", (manager["email"],)),
            ]
        )
        run_db_cleanup(cleanup)
