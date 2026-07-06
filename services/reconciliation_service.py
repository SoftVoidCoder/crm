import json
import time


def reconciliation_entity_config():
    return {
        "finance_payment": {"table": "finance_payments", "id_field": "id", "display_field": "id", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "purchase_order": {"table": "purchase_orders", "id_field": "id", "display_field": "id", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "sales_document": {"table": "sales_documents_extended", "id_field": "id", "display_field": "doc_number", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "production_order": {"table": "production_orders", "id_field": "id", "display_field": "order_name", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "stock_reservation": {"table": "stock_reservations", "id_field": "id", "display_field": "nomenclature_article", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "nomenclature": {"table": "nomenclature", "id_field": "id", "display_field": "article", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "warehouses": {"table": "warehouse_master", "id_field": "id", "display_field": "code", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "units": {"table": "unit_master", "id_field": "id", "display_field": "code", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "groups": {"table": "nomenclature_groups", "id_field": "id", "display_field": "code", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "employees": {"table": "employee_master", "id_field": "id", "display_field": "personnel_number", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "positions": {"table": "position_master", "id_field": "id", "display_field": "code", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "characteristics": {"table": "nomenclature_characteristics", "id_field": "id", "display_field": "code", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "storage_cells": {"table": "storage_cells", "id_field": "id", "display_field": "code", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "income_expense_articles": {"table": "income_expense_articles", "id_field": "id", "display_field": "code", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "financial_responsibility_centers": {"table": "financial_responsibility_centers", "id_field": "id", "display_field": "code", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "operation_types": {"table": "operation_types", "id_field": "id", "display_field": "code", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "bank_accounts": {"table": "bank_accounts", "id_field": "id", "display_field": "code", "external_field": "external_sync_id", "state_field": "exchange_state"},
        "epl_waybill": {"table": "epl_waybills", "id_field": "id", "display_field": "number", "external_field": "external_document_id", "state_field": "integration_status"},
    }


def find_reconciliation_queue_row(c, entity_type: str, queue_entity_id, display_key: str = "", external_id: str = "", safe_int_fn=None):
    safe_int_fn = safe_int_fn or (lambda value: int(value or 0))
    if str(queue_entity_id or "").isdigit():
        c.execute(
            """
            SELECT state, external_id, last_error, mapping_key
            FROM integration_sync_queue
            WHERE system_name='1C' AND entity_type=? AND entity_id=?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (entity_type, safe_int_fn(queue_entity_id)),
        )
        row = c.fetchone()
        if row:
            return row
    mapping_candidates = [
        f"{entity_type}:{display_key}" if display_key else "",
        f"{entity_type}:{queue_entity_id}" if str(queue_entity_id or "") else "",
    ]
    for mapping_key in [item for item in mapping_candidates if item]:
        c.execute(
            """
            SELECT state, external_id, last_error, mapping_key
            FROM integration_sync_queue
            WHERE system_name='1C' AND entity_type=? AND mapping_key=?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (entity_type, mapping_key),
        )
        row = c.fetchone()
        if row:
            return row
    if external_id:
        c.execute(
            """
            SELECT state, external_id, last_error, mapping_key
            FROM integration_sync_queue
            WHERE system_name='1C' AND entity_type=? AND external_id=?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (entity_type, external_id),
        )
        row = c.fetchone()
        if row:
            return row
    return None


def collect_reconciliation_entity_issues(c, entity_type: str, meta: dict, *, normalize_spaces_fn, safe_int_fn):
    c.execute(f"SELECT * FROM {meta['table']}")
    rows = [dict(row) for row in c.fetchall()]
    entity_issues = []
    for row in rows:
        queue_entity_id = row.get(meta["id_field"])
        entity_id = str(row.get(meta.get("display_field") or meta["id_field"]) or row.get(meta["id_field"]) or "")
        external_id = normalize_spaces_fn(row.get(meta["external_field"], ""))
        local_state = normalize_spaces_fn(row.get(meta["state_field"], "")) or "draft"
        queue_row = find_reconciliation_queue_row(c, entity_type, queue_entity_id, entity_id, external_id, safe_int_fn=safe_int_fn)
        queue_state = queue_row["state"] if queue_row else ""
        queue_external_id = normalize_spaces_fn(queue_row["external_id"]) if queue_row else ""
        last_error = normalize_spaces_fn(queue_row["last_error"]) if queue_row else ""
        if local_state in {"synced", "ready", "sent", "posted", "paid", "issued"} and not external_id:
            entity_issues.append({"row_id": queue_entity_id, "entity_id": entity_id, "issue": "missing_external_id", "state": local_state})
        if queue_state in {"failed", "conflict"}:
            entity_issues.append({"row_id": queue_entity_id, "entity_id": entity_id, "issue": queue_state, "state": local_state, "last_error": last_error})
        if external_id and queue_external_id and external_id != queue_external_id:
            entity_issues.append({"row_id": queue_entity_id, "entity_id": entity_id, "issue": "external_id_mismatch", "state": local_state, "local_external_id": external_id, "queue_external_id": queue_external_id})
        if local_state not in {"draft", ""} and not queue_row and not external_id:
            entity_issues.append({"row_id": queue_entity_id, "entity_id": entity_id, "issue": "no_sync_trace", "state": local_state})
    return rows, entity_issues


def run_integration_reconciliation(
    *,
    get_connection,
    actor_email: str,
    normalize_spaces_fn,
    safe_int_fn,
):
    config = reconciliation_entity_config()
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        summary = {"entities": {}, "issues": []}
        total_mismatches = 0
        for entity_type, meta in config.items():
            rows, entity_issues = collect_reconciliation_entity_issues(
                c,
                entity_type,
                meta,
                normalize_spaces_fn=normalize_spaces_fn,
                safe_int_fn=safe_int_fn,
            )
            total_mismatches += len(entity_issues)
            summary["entities"][entity_type] = {
                "rows": len(rows),
                "mismatches": len(entity_issues),
                "issues": entity_issues[:25],
            }
            summary["issues"].extend([{**item, "entity_type": entity_type} for item in entity_issues[:10]])
        now = int(time.time())
        c.execute(
            """
            INSERT INTO integration_reconciliation_runs (system_name, summary, mismatch_count, created_by, created_at)
            VALUES ('1C', ?, ?, ?, ?)
            """,
            (json.dumps(summary, ensure_ascii=False), total_mismatches, actor_email, now),
        )
        run_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()
    summary["run_id"] = run_id
    summary["mismatch_count"] = total_mismatches
    return summary


def load_reconciliation_runs(*, get_connection, json_load_fn, limit: int = 20):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM integration_reconciliation_runs ORDER BY created_at DESC, id DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        )
        rows = [dict(row) for row in c.fetchall()]
    finally:
        conn.close()
    for row in rows:
        row["summary"] = json_load_fn(row.get("summary"), {})
    return rows
