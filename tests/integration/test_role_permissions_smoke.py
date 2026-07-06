import unittest

from fastapi.testclient import TestClient

from main import app
from database import get_connection
from tests.test_helpers import create_test_user, delete_test_user


class RolePermissionsSmokeTests(unittest.TestCase):
    def test_role_matrix_scope_and_policy_smoke(self):
        users = {
            "director": create_test_user(role="Директор", name_prefix="Smoke Director"),
            "manager": create_test_user(role="Менеджер", name_prefix="Smoke Manager"),
            "accounting": create_test_user(role="Бухгалтерия", name_prefix="Smoke Accounting"),
            "production": create_test_user(role="Производство и ОТК", name_prefix="Smoke Production"),
            "warehouse": create_test_user(role="Склад", name_prefix="Smoke Warehouse"),
            "legal": create_test_user(role="Юрист", name_prefix="Smoke Legal"),
            "employee": create_test_user(role="Сотрудник", name_prefix="Smoke Employee"),
        }
        clients = {key: TestClient(app) for key in users}
        created_ids = {
            "field_rules": [],
            "legal_entity_id": 0,
            "business_unit_id": 0,
            "payment_allowed_id": 0,
            "payment_blocked_id": 0,
        }
        try:
            for key, user in users.items():
                login = clients[key].post("/api/login", json={"email": user["email"], "password": user["password"]})
                self.assertEqual(login.status_code, 200, msg=f"login failed for {key}")

            director_permissions = clients["director"].get("/api/permissions")
            self.assertEqual(director_permissions.status_code, 200)
            director_json = director_permissions.json()
            self.assertIn("read", director_json["permissions"]["executive"])
            self.assertIn("audit", director_json["permissions"]["system"])

            manager_permissions = clients["manager"].get("/api/permissions").json()
            self.assertIn("create", manager_permissions["permissions"]["projects"])
            self.assertIn("finance", manager_permissions["permissions"]["projects"])
            self.assertEqual(manager_permissions["permissions"]["executive"], [])

            accounting_permissions = clients["accounting"].get("/api/permissions").json()
            self.assertIn("post", accounting_permissions["permissions"]["finance"])
            self.assertIn("close_period", accounting_permissions["permissions"]["finance"])
            self.assertIn("confirm", accounting_permissions["permissions"]["sales"])

            production_permissions = clients["production"].get("/api/permissions").json()
            self.assertIn("complete", production_permissions["permissions"]["production"])
            self.assertIn("receive", production_permissions["permissions"]["supply"])

            warehouse_permissions = clients["warehouse"].get("/api/permissions").json()
            self.assertIn("receive", warehouse_permissions["permissions"]["supply"])
            self.assertIn("reserve", warehouse_permissions["permissions"]["supply"])
            self.assertEqual(warehouse_permissions["permissions"]["executive"], [])

            legal_permissions = clients["legal"].get("/api/permissions").json()
            self.assertIn("approve", legal_permissions["permissions"]["approvals"])
            self.assertIn("create", legal_permissions["permissions"]["documents"])
            self.assertEqual(legal_permissions["permissions"]["finance"], ["read"])

            employee_permissions = clients["employee"].get("/api/permissions").json()
            self.assertIn("create", employee_permissions["permissions"]["tasks"])
            self.assertIn("read", employee_permissions["permissions"]["documents"])
            self.assertEqual(employee_permissions["permissions"]["finance"], [])

            director_pending = clients["director"].get("/api/users/pending")
            self.assertEqual(director_pending.status_code, 200)
            self.assertIsInstance(director_pending.json(), list)
            for key in ("manager", "accounting", "production", "warehouse", "legal", "employee"):
                forbidden = clients[key].get("/api/users/pending")
                self.assertEqual(forbidden.status_code, 200)
                self.assertEqual(forbidden.json()["error"], "forbidden")

            amount_rule = clients["director"].post("/api/users/field_rules", json={
                "role": "Бухгалтерия",
                "module": "finance",
                "entity_type": "finance_payment",
                "field_name": "amount",
                "can_view": 1,
                "can_edit": 0,
                "allowed_statuses": [],
                "is_active": 1,
            })
            self.assertEqual(amount_rule.status_code, 200)
            created_ids["field_rules"].append(int(amount_rule.json()["id"]))

            status_rule = clients["director"].post("/api/users/field_rules", json={
                "role": "Бухгалтерия",
                "module": "finance",
                "entity_type": "finance_payment",
                "field_name": "status",
                "can_view": 1,
                "can_edit": 1,
                "allowed_statuses": ["planned", "paid"],
                "is_active": 1,
            })
            self.assertEqual(status_rule.status_code, 200)
            created_ids["field_rules"].append(int(status_rule.json()["id"]))

            accounting_form = clients["accounting"].get("/api/permissions/forms/finance/finance_payment")
            self.assertEqual(accounting_form.status_code, 200)
            accounting_form_json = accounting_form.json()
            self.assertIn("amount", accounting_form_json["readonly_fields"])
            self.assertEqual(accounting_form_json["restricted_status_fields"]["status"], ["planned", "paid"])
            self.assertIn("Разрешённые статусы", accounting_form_json["messages"]["status"])

            master_data = clients["director"].get("/api/finance/master_data")
            self.assertEqual(master_data.status_code, 200)
            default_legal = int(master_data.json()["legal_entities"][0]["id"])
            default_bu = int(master_data.json()["business_units"][0]["id"])

            created_le = clients["director"].post("/api/finance/master_data/legal_entities", json={
                "name": "Smoke Scope LE",
                "short_name": "SmokeLE",
                "inn": "7700001111",
                "kpp": "770001111",
                "ogrn": "1247700001111",
                "vat_mode": "osno",
                "default_currency": "RUB",
                "is_active": 1,
            })
            self.assertEqual(created_le.status_code, 200)
            created_ids["legal_entity_id"] = int(created_le.json()["id"])

            created_bu = clients["director"].post("/api/finance/master_data/business_units", json={
                "legal_entity_id": created_ids["legal_entity_id"],
                "name": "Smoke Scope BU",
                "code": "SMOKE-BU",
                "manager_name": users["director"]["name"],
                "is_active": 1,
            })
            self.assertEqual(created_bu.status_code, 200)
            created_ids["business_unit_id"] = int(created_bu.json()["id"])

            payment_allowed = clients["director"].post("/api/finance/payments", json={
                "title": "Smoke Scope Allowed",
                "kind": "incoming",
                "category": "payment",
                "amount": 33333,
                "currency": "RUB",
                "status": "planned",
                "due_date": "18.04.2026",
                "legal_entity_id": created_ids["legal_entity_id"],
                "business_unit_id": created_ids["business_unit_id"],
            })
            self.assertEqual(payment_allowed.status_code, 200)
            created_ids["payment_allowed_id"] = int(payment_allowed.json()["id"])

            payment_blocked = clients["director"].post("/api/finance/payments", json={
                "title": "Smoke Scope Blocked",
                "kind": "incoming",
                "category": "payment",
                "amount": 44444,
                "currency": "RUB",
                "status": "planned",
                "due_date": "18.04.2026",
                "legal_entity_id": default_legal,
                "business_unit_id": default_bu,
            })
            self.assertEqual(payment_blocked.status_code, 200)
            created_ids["payment_blocked_id"] = int(payment_blocked.json()["id"])

            for key in ("manager", "warehouse"):
                scoped = clients["director"].put("/api/users/access_scope", json={
                    "email": users[key]["email"],
                    "allowed_legal_entities": [created_ids["legal_entity_id"]],
                    "allowed_business_units": [created_ids["business_unit_id"]],
                    "two_factor_enabled": 0,
                })
                self.assertEqual(scoped.status_code, 200)
                self.assertEqual(scoped.json()["status"], "success")

                permissions = clients[key].get("/api/permissions")
                self.assertEqual(permissions.status_code, 200)
                scope = permissions.json()["scope"]
                self.assertEqual(scope["legal_entities"], [created_ids["legal_entity_id"]])
                self.assertEqual(scope["business_units"], [created_ids["business_unit_id"]])

                visible_payments = clients[key].get("/api/finance/payments")
                self.assertEqual(visible_payments.status_code, 200)
                titles = {item["title"] for item in visible_payments.json()}
                self.assertIn("Smoke Scope Allowed", titles)
                self.assertNotIn("Smoke Scope Blocked", titles)
        finally:
            conn = get_connection()
            c = conn.cursor()
            if created_ids["payment_allowed_id"]:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (created_ids["payment_allowed_id"],))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (created_ids["payment_allowed_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (created_ids["payment_allowed_id"],))
                c.execute("DELETE FROM finance_payments WHERE id=?", (created_ids["payment_allowed_id"],))
            if created_ids["payment_blocked_id"]:
                c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (created_ids["payment_blocked_id"],))
                c.execute("DELETE FROM integration_sync_log WHERE entity_type='finance_payment' AND entity_id=?", (created_ids["payment_blocked_id"],))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (created_ids["payment_blocked_id"],))
                c.execute("DELETE FROM finance_payments WHERE id=?", (created_ids["payment_blocked_id"],))
            if created_ids["business_unit_id"]:
                c.execute("DELETE FROM business_units WHERE id=?", (created_ids["business_unit_id"],))
            if created_ids["legal_entity_id"]:
                c.execute("DELETE FROM legal_entities WHERE id=?", (created_ids["legal_entity_id"],))
            if created_ids["field_rules"]:
                placeholders = ", ".join(["?"] * len(created_ids["field_rules"]))
                c.execute(
                    f"DELETE FROM field_access_rules WHERE id IN ({placeholders})",
                    tuple(created_ids["field_rules"]),
                )
            conn.commit()
            conn.close()
            for user in users.values():
                delete_test_user(user["email"])


if __name__ == "__main__":
    unittest.main()
