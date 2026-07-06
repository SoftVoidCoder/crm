import os
import time
import unittest

from fastapi.testclient import TestClient

from main import app
from database import get_connection
from tests.test_helpers import create_test_user, delete_test_user


class NSIMDMGovernanceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_mdm_rules_versions_duplicates_approval_and_reference_controls(self):
        director = create_test_user(role="Директор", name_prefix="MDM Director")
        suffix = f"{os.getpid()}-{int(time.time())}"
        position_id = 0
        hierarchy_id = 0
        classifier_code = f"QA-OKEI-{suffix}"
        imported_unit_id = 0
        duplicate_rule_id = 0
        bulk_request_id = 0
        bulk_approval_id = 0
        invalid_cell_id = 0
        try:
            login = self.client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            self.assertEqual(login.status_code, 200)

            created = self.client.post("/api/nsi/master_data/positions", json={
                "name": f"QA MDM Position {suffix}",
                "code": f"QA-MDM-POS-{suffix}",
                "department_name": "MDM Office",
                "comment": "Первичная версия",
            })
            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["status"], "success")
            self.assertEqual(created.json()["mdm_status"], "pending_approval")
            position_id = int(created.json()["id"])

            duplicate = self.client.post("/api/nsi/master_data/positions", json={
                "name": f"QA MDM Position {suffix}",
                "code": f"QA-MDM-POS-DUP-{suffix}",
                "department_name": "MDM Office",
            })
            self.assertEqual(duplicate.status_code, 200)
            self.assertEqual(duplicate.json()["error"], "duplicate_candidate")
            self.assertTrue(duplicate.json()["duplicates"])

            versions_before = self.client.get(f"/api/nsi/master_data/positions/{position_id}/versions")
            self.assertEqual(versions_before.status_code, 200)
            self.assertGreaterEqual(len(versions_before.json()), 1)
            self.assertEqual(versions_before.json()[0]["payload"]["mdm_status"], "pending_approval")

            approved = self.client.post(
                f"/api/nsi/master_data/positions/{position_id}/approve",
                json={"comment": "MDM steward approved", "target_state": "active"},
            )
            self.assertEqual(approved.status_code, 200)
            self.assertEqual(approved.json()["status"], "success")
            self.assertEqual(approved.json()["mdm_status"], "approved")

            master_data = self.client.get("/api/nsi/master_data")
            self.assertEqual(master_data.status_code, 200)
            approved_row = next(item for item in master_data.json()["positions"] if int(item["id"]) == position_id)
            self.assertEqual(approved_row["mdm_status"], "approved")
            self.assertEqual(approved_row["lifecycle_state"], "active")
            self.assertEqual(int(approved_row["is_active"]), 1)
            self.assertGreaterEqual(int(approved_row["version_no"]), 2)

            hierarchy = self.client.post("/api/nsi/mdm/hierarchies", json={
                "hierarchy_type": "org_positions",
                "entity_type": "positions",
                "entity_id": position_id,
                "node_code": f"POS-NODE-{suffix}",
                "node_name": f"QA MDM Position Node {suffix}",
                "details": {"level": "department"},
            })
            self.assertEqual(hierarchy.status_code, 200)
            self.assertEqual(hierarchy.json()["status"], "success")
            hierarchy_id = int(hierarchy.json()["id"])
            self.assertIn(f"POS-NODE-{suffix}", hierarchy.json()["path_code"])

            classifier_import = self.client.post("/api/nsi/mdm/external_classifiers/import", json={
                "classifier_type": "units",
                "source_system": "OKEI",
                "version_tag": f"QA-{suffix}",
                "items": [{"code": classifier_code, "name": f"QA imported unit {suffix}", "short_name": "qa"}],
            })
            self.assertEqual(classifier_import.status_code, 200)
            self.assertEqual(classifier_import.json()["status"], "success")
            self.assertEqual(int(classifier_import.json()["linked_units"]), 1)

            classifiers = self.client.get(f"/api/nsi/mdm/external_classifiers?classifier_type=units&source_system=OKEI")
            self.assertEqual(classifiers.status_code, 200)
            classifier_row = next(item for item in classifiers.json() if item["external_code"] == classifier_code)
            imported_unit_id = int(classifier_row["entity_id"])
            self.assertGreater(imported_unit_id, 0)

            duplicate_rule = self.client.post("/api/nsi/mdm/duplicate_rules", json={
                "entity_type": "positions",
                "rule_name": f"QA name+department {suffix}",
                "fields": ["name", "department_name"],
                "severity": "error",
                "comment": "multi-field duplicate rule",
            })
            self.assertEqual(duplicate_rule.status_code, 200)
            duplicate_rule_id = int(duplicate_rule.json()["id"])

            duplicate_by_rule = self.client.post("/api/nsi/master_data/positions", json={
                "name": f"QA MDM Position {suffix}",
                "code": f"QA-MDM-POS-RULE-{suffix}",
                "department_name": "MDM Office",
            })
            self.assertEqual(duplicate_by_rule.status_code, 200)
            self.assertEqual(duplicate_by_rule.json()["error"], "duplicate_candidate")
            self.assertTrue(any(item.get("duplicate_rule") in {"name_department", f"QA name+department {suffix}"} for item in duplicate_by_rule.json()["duplicates"]))

            bulk = self.client.post("/api/nsi/mdm/bulk_change_requests", json={
                "entity_type": "positions",
                "operation": "update_fields",
                "filter": {"ids": [position_id]},
                "changes": {"comment": "bulk approved comment"},
                "comment": "bulk MDM change with approval",
            })
            self.assertEqual(bulk.status_code, 200)
            self.assertEqual(bulk.json()["status"], "success")
            bulk_request_id = int(bulk.json()["id"])
            bulk_approval_id = int(bulk.json()["approval_id"])
            self.assertEqual(int(bulk.json()["target_count"]), 1)

            bulk_approved = self.client.post(f"/api/nsi/mdm/bulk_change_requests/{bulk_request_id}/approve", json={
                "comment": "approve bulk change",
                "target_state": "update_fields",
            })
            self.assertEqual(bulk_approved.status_code, 200)
            self.assertEqual(bulk_approved.json()["status"], "success")
            self.assertEqual(int(bulk_approved.json()["applied_count"]), 1)

            conn = get_connection()
            c = conn.cursor()
            now = int(time.time())
            c.execute(
                """
                INSERT INTO storage_cells (warehouse_id, name, code, zone_name, is_active, comment, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, '', ?, ?)
                """,
                (999999, f"QA Broken MDM Cell {suffix}", f"QA-MDM-BROKEN-CELL-{suffix}", "MDM", now, now),
            )
            invalid_cell_id = int(c.lastrowid)
            conn.commit()
            conn.close()

            controls = self.client.post("/api/nsi/mdm/controls/run")
            self.assertEqual(controls.status_code, 200)
            self.assertEqual(controls.json()["status"], "success")
            self.assertGreaterEqual(int(controls.json()["metrics"]["issues"]), 1)
            self.assertTrue(any(
                item["entity_type"] == "storage_cells"
                and int(item["entity_id"]) == invalid_cell_id
                and item["issue_type"] == "reference_error"
                for item in controls.json()["issues"]
            ))

            issues = self.client.get("/api/nsi/mdm/issues?status=open&limit=50")
            self.assertEqual(issues.status_code, 200)
            self.assertTrue(any(item["entity_type"] == "storage_cells" and int(item["entity_id"]) == invalid_cell_id for item in issues.json()))

            governance = self.client.get("/api/nsi/mdm/governance")
            self.assertEqual(governance.status_code, 200)
            self.assertEqual(governance.json()["status"], "success")
            self.assertTrue(any(item["entity_type"] == "positions" for item in governance.json()["entities"]))
        finally:
            conn = get_connection()
            c = conn.cursor()
            for entity_type, entity_id in (("positions", position_id), ("storage_cells", invalid_cell_id)):
                if entity_id:
                    c.execute("DELETE FROM nsi_mdm_versions WHERE entity_type=? AND entity_id=?", (entity_type, entity_id))
                    c.execute("DELETE FROM nsi_mdm_issues WHERE entity_type=? AND entity_id=?", (entity_type, entity_id))
                    c.execute("DELETE FROM nsi_mdm_approvals WHERE entity_type=? AND entity_id=?", (entity_type, entity_id))
            if bulk_request_id:
                c.execute("DELETE FROM nsi_mdm_approvals WHERE id=? OR (entity_type='nsi_bulk_change' AND entity_id=?)", (bulk_approval_id, bulk_request_id))
                c.execute("DELETE FROM nsi_bulk_change_requests WHERE id=?", (bulk_request_id,))
            if duplicate_rule_id:
                c.execute("DELETE FROM nsi_duplicate_rules WHERE id=?", (duplicate_rule_id,))
            if hierarchy_id:
                c.execute("DELETE FROM nsi_hierarchies WHERE id=?", (hierarchy_id,))
            c.execute("DELETE FROM nsi_external_classifiers WHERE external_code=?", (classifier_code,))
            if imported_unit_id:
                c.execute("DELETE FROM nsi_mdm_versions WHERE entity_type='units' AND entity_id=?", (imported_unit_id,))
                c.execute("DELETE FROM nsi_mdm_issues WHERE entity_type='units' AND entity_id=?", (imported_unit_id,))
                c.execute("DELETE FROM unit_master WHERE id=?", (imported_unit_id,))
            if invalid_cell_id:
                c.execute("DELETE FROM storage_cells WHERE id=?", (invalid_cell_id,))
            if position_id:
                c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='positions' AND entity_id=?)", (position_id,))
                c.execute("DELETE FROM integration_sync_queue WHERE entity_type='positions' AND entity_id=?", (position_id,))
                c.execute("DELETE FROM position_master WHERE id=?", (position_id,))
            conn.commit()
            conn.close()
            delete_test_user(director["email"])
