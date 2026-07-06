import json
import time

from database import get_connection


def safe_int(value) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


def safe_float(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def json_load(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def build_finance_sync_payload(payment: dict) -> dict:
    return {
        "id": payment.get("id"),
        "title": payment.get("title", ""),
        "kind": payment.get("kind", ""),
        "category": payment.get("category", ""),
        "amount": safe_float(payment.get("amount")),
        "currency": payment.get("currency", "RUB"),
        "status": payment.get("status", ""),
        "due_date": payment.get("due_date", ""),
        "paid_date": payment.get("paid_date", ""),
        "project_id": safe_int(payment.get("project_id")),
        "client_id": safe_int(payment.get("client_id")),
        "contract_id": safe_int(payment.get("contract_id")),
        "object_id": safe_int(payment.get("object_id")),
        "legal_entity_id": safe_int(payment.get("legal_entity_id")),
        "business_unit_id": safe_int(payment.get("business_unit_id")),
        "treasury_article_id": safe_int(payment.get("treasury_article_id")),
        "vat_rate_id": safe_int(payment.get("vat_rate_id")),
        "source_document_type": payment.get("source_document_type", ""),
        "source_document_id": safe_int(payment.get("source_document_id")),
    }


def build_counterparty_sync_payload(client: dict) -> dict:
    return {
        "id": safe_int(client.get("id")),
        "name": client.get("name", ""),
        "inn": client.get("inn", ""),
        "contact": client.get("contact", ""),
    }


def build_purchase_sync_payload(purchase: dict) -> dict:
    return {
        "id": purchase.get("id"),
        "project_id": safe_int(purchase.get("project_id")),
        "client_id": safe_int(purchase.get("client_id")),
        "contract_id": safe_int(purchase.get("contract_id")),
        "object_id": safe_int(purchase.get("object_id")),
        "item_article": purchase.get("item_article", ""),
        "item_name": purchase.get("item_name", ""),
        "supplier": purchase.get("supplier", ""),
        "qty": safe_float(purchase.get("qty")),
        "unit": purchase.get("unit", "шт"),
        "unit_price": safe_float(purchase.get("unit_price")),
        "total_amount": safe_float(purchase.get("total_amount")),
        "status": purchase.get("status", "planned"),
        "expected_date": purchase.get("expected_date", ""),
        "received_date": purchase.get("received_date", ""),
    }


def build_stock_document_sync_payload(document: dict) -> dict:
    return {
        "id": safe_int(document.get("id")),
        "doc_type": document.get("doc_type", "inventory"),
        "doc_number": document.get("doc_number", ""),
        "article": document.get("article", ""),
        "warehouse": document.get("warehouse", ""),
        "bin_code": document.get("bin_code", ""),
        "batch_code": document.get("batch_code", ""),
        "serial_no": document.get("serial_no", ""),
        "target_warehouse": document.get("target_warehouse", ""),
        "target_bin": document.get("target_bin", ""),
        "qty": safe_float(document.get("qty")),
        "counted_qty": safe_float(document.get("counted_qty")),
        "adjustment_qty": safe_float(document.get("adjustment_qty")),
        "reason": document.get("reason", ""),
        "status": document.get("status", "posted"),
    }


def build_sales_sync_payload(document: dict) -> dict:
    return {
        "id": document.get("id"),
        "project_id": safe_int(document.get("project_id")),
        "client_id": safe_int(document.get("client_id")),
        "contract_id": safe_int(document.get("contract_id")),
        "object_id": safe_int(document.get("object_id")),
        "doc_type": document.get("doc_type", "invoice"),
        "doc_number": document.get("doc_number", ""),
        "doc_date": document.get("doc_date", ""),
        "amount": safe_float(document.get("amount")),
        "currency": document.get("currency", "RUB"),
        "status": document.get("status", "draft"),
        "payment_status": document.get("payment_status", "planned"),
        "recipient_email": document.get("recipient_email", ""),
        "sent_status": document.get("sent_status", "draft"),
    }


def build_document_sync_payload(document: dict) -> dict:
    return {
        "id": safe_int(document.get("id")),
        "type": document.get("type", "incoming"),
        "number": document.get("number", ""),
        "d_date": document.get("d_date", ""),
        "correspondent": document.get("correspondent", ""),
        "subject": document.get("subject", ""),
        "status": document.get("status", "registered"),
        "file_url": document.get("file_url", ""),
        "project_id": safe_int(document.get("project_id")),
        "contract_id": safe_int(document.get("contract_id")),
        "object_id": safe_int(document.get("object_id")),
        "parent_id": safe_int(document.get("parent_id")),
        "priority": document.get("priority", "normal"),
    }


def build_production_sync_payload(order: dict) -> dict:
    return {
        "id": order.get("id"),
        "project_id": safe_int(order.get("project_id")),
        "client_id": safe_int(order.get("client_id")),
        "contract_id": safe_int(order.get("contract_id")),
        "object_id": safe_int(order.get("object_id")),
        "order_name": order.get("order_name", ""),
        "stage": order.get("stage", "queue"),
        "priority": order.get("priority", "normal"),
        "route_name": order.get("route_name", ""),
        "planned_qty": safe_float(order.get("planned_qty")),
        "produced_qty": safe_float(order.get("produced_qty")),
        "scrap_qty": safe_float(order.get("scrap_qty")),
        "planned_cost": safe_float(order.get("planned_cost")),
        "actual_cost": safe_float(order.get("actual_cost")),
        "labor_hours_plan": safe_float(order.get("labor_hours_plan")),
        "labor_hours_fact": safe_float(order.get("labor_hours_fact")),
        "progress": safe_int(order.get("progress")),
    }


def build_reservation_sync_payload(reservation: dict) -> dict:
    return {
        "id": reservation.get("id"),
        "project_id": safe_int(reservation.get("project_id")),
        "article": reservation.get("nomenclature_article", ""),
        "name": reservation.get("nomenclature_name", ""),
        "qty": safe_float(reservation.get("qty")),
        "fulfilled_qty": safe_float(reservation.get("fulfilled_qty")),
        "status": reservation.get("status", "reserved"),
        "warehouse": reservation.get("warehouse", ""),
        "bin_code": reservation.get("bin_code", ""),
        "batch_code": reservation.get("batch_code", ""),
        "serial_no": reservation.get("serial_no", ""),
    }


def build_nomenclature_sync_payload(item: dict) -> dict:
    return {
        "article": item.get("article", ""),
        "name": item.get("name", ""),
        "unit": item.get("unit", "шт"),
        "price": safe_float(item.get("price")),
        "stock": safe_float(item.get("stock")),
        "currency": item.get("currency", "RUB"),
        "group_name": item.get("group_name", ""),
        "default_warehouse": item.get("default_warehouse", ""),
    }


def build_simple_nsi_sync_payload(item: dict) -> dict:
    return {
        "id": safe_int(item.get("id")),
        "name": item.get("name", ""),
        "code": item.get("code", ""),
        "comment": item.get("comment", ""),
        "is_active": safe_int(item.get("is_active", 1)),
    }


def build_employee_sync_payload(item: dict) -> dict:
    return {
        "id": safe_int(item.get("id")),
        "full_name": item.get("full_name", ""),
        "personnel_number": item.get("personnel_number", ""),
        "email": item.get("email", ""),
        "phone": item.get("phone", ""),
        "position_id": safe_int(item.get("position_id")),
        "legal_entity_id": safe_int(item.get("legal_entity_id")),
        "business_unit_id": safe_int(item.get("business_unit_id")),
        "is_active": safe_int(item.get("is_active", 1)),
        "comment": item.get("comment", ""),
    }


def build_position_sync_payload(item: dict) -> dict:
    return {**build_simple_nsi_sync_payload(item), "department_name": item.get("department_name", "")}


def build_characteristic_sync_payload(item: dict) -> dict:
    return {**build_simple_nsi_sync_payload(item), "characteristic_type": item.get("characteristic_type", "")}


def build_storage_cell_sync_payload(item: dict) -> dict:
    return {
        "id": safe_int(item.get("id")),
        "warehouse_id": safe_int(item.get("warehouse_id")),
        "name": item.get("name", ""),
        "code": item.get("code", ""),
        "zone_name": item.get("zone_name", ""),
        "is_active": safe_int(item.get("is_active", 1)),
        "comment": item.get("comment", ""),
    }


def build_income_expense_article_sync_payload(item: dict) -> dict:
    return {**build_simple_nsi_sync_payload(item), "article_kind": item.get("article_kind", "expense")}


def build_cfr_sync_payload(item: dict) -> dict:
    return {
        "id": safe_int(item.get("id")),
        "name": item.get("name", ""),
        "code": item.get("code", ""),
        "legal_entity_id": safe_int(item.get("legal_entity_id")),
        "business_unit_id": safe_int(item.get("business_unit_id")),
        "manager_name": item.get("manager_name", ""),
        "is_active": safe_int(item.get("is_active", 1)),
        "comment": item.get("comment", ""),
    }


def build_operation_type_sync_payload(item: dict) -> dict:
    return {**build_simple_nsi_sync_payload(item), "module_name": item.get("module_name", ""), "flow_kind": item.get("flow_kind", "")}


def build_bank_account_sync_payload(item: dict) -> dict:
    return {
        "id": safe_int(item.get("id")),
        "name": item.get("name", ""),
        "code": item.get("code", ""),
        "bank_name": item.get("bank_name", ""),
        "account_number": item.get("account_number", ""),
        "bik": item.get("bik", ""),
        "currency": item.get("currency", "RUB"),
        "legal_entity_id": safe_int(item.get("legal_entity_id")),
        "is_active": safe_int(item.get("is_active", 1)),
        "comment": item.get("comment", ""),
    }


def sync_entity_meta(entity_type: str) -> dict | None:
    return {
        "finance_payment": {
            "table": "finance_payments", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_finance_sync_payload, "prefix": "1C-FIN",
        },
        "counterparty": {
            "table": "clients", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "", "builder": build_counterparty_sync_payload, "prefix": "1C-CL",
        },
        "purchase_order": {
            "table": "purchase_orders", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_purchase_sync_payload, "prefix": "1C-PUR",
        },
        "sales_document": {
            "table": "sales_documents_extended", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_sales_sync_payload, "prefix": "1C-SAL",
        },
        "document": {
            "table": "documents", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "", "builder": build_document_sync_payload, "prefix": "1C-DOC",
        },
        "production_order": {
            "table": "production_orders", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_production_sync_payload, "prefix": "1C-PRD",
        },
        "stock_reservation": {
            "table": "stock_reservations", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "", "builder": build_reservation_sync_payload, "prefix": "1C-RES",
        },
        "stock_document": {
            "table": "inventory_documents", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_stock_document_sync_payload, "prefix": "1C-STK",
        },
        "nomenclature": {
            "table": "nomenclature", "id_column": "article", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "", "builder": build_nomenclature_sync_payload, "prefix": "1C-NSI",
        },
        "warehouses": {
            "table": "warehouse_master", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_simple_nsi_sync_payload, "prefix": "1C-WHS",
        },
        "units": {
            "table": "unit_master", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_simple_nsi_sync_payload, "prefix": "1C-UNT",
        },
        "groups": {
            "table": "nomenclature_groups", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_simple_nsi_sync_payload, "prefix": "1C-GRP",
        },
        "employees": {
            "table": "employee_master", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_employee_sync_payload, "prefix": "1C-EMP",
        },
        "positions": {
            "table": "position_master", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_position_sync_payload, "prefix": "1C-POS",
        },
        "characteristics": {
            "table": "nomenclature_characteristics", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_characteristic_sync_payload, "prefix": "1C-CHR",
        },
        "storage_cells": {
            "table": "storage_cells", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_storage_cell_sync_payload, "prefix": "1C-CELL",
        },
        "income_expense_articles": {
            "table": "income_expense_articles", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_income_expense_article_sync_payload, "prefix": "1C-PL",
        },
        "financial_responsibility_centers": {
            "table": "financial_responsibility_centers", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_cfr_sync_payload, "prefix": "1C-CFR",
        },
        "operation_types": {
            "table": "operation_types", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_operation_type_sync_payload, "prefix": "1C-OPT",
        },
        "bank_accounts": {
            "table": "bank_accounts", "id_column": "id", "state_column": "exchange_state", "external_column": "external_sync_id", "updated_column": "updated_at", "builder": build_bank_account_sync_payload, "prefix": "1C-BANK",
        },
    }.get(entity_type)


def load_sync_queue_rows(limit: int = 120):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT *
            FROM integration_sync_queue
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        )
        rows = [dict(row) for row in c.fetchall()]
    finally:
        conn.close()
    for row in rows:
        row["payload"] = json_load(row.get("payload"), {})
    return rows


def load_sync_conflict_rows(limit: int = 120):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT *
            FROM integration_sync_log
            WHERE system_name='1C' AND state='conflict'
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        )
        rows = [dict(row) for row in c.fetchall()]
    finally:
        conn.close()
    for row in rows:
        row["payload"] = json_load(row.get("payload"), {})
    return rows


def build_integration_monitoring_payload(*, queue_rows: list[dict], conflict_rows: list[dict], now: int | None = None, stale_seconds: int = 900) -> dict:
    checked_at = now or int(time.time())
    stale_lock_threshold = checked_at - stale_seconds
    metrics = {
        "queued": 0,
        "retry": 0,
        "processing": 0,
        "failed": 0,
        "synced": 0,
        "conflicts": len(conflict_rows),
        "stale_processing": 0,
    }
    entity_health: dict[str, dict] = {}
    stale_rows = []
    recent_failures = []
    for row in queue_rows:
        state = row.get("state") or "queued"
        metrics[state] = metrics.get(state, 0) + 1
        if state == "processing" and safe_int(row.get("locked_at")) and safe_int(row.get("locked_at")) < stale_lock_threshold:
            metrics["stale_processing"] += 1
            stale_rows.append(row)
        if state in {"failed", "retry"}:
            recent_failures.append(row)
        entity_type = row.get("entity_type") or "unknown"
        entity_entry = entity_health.setdefault(entity_type, {
            "entity_type": entity_type, "queued": 0, "retry": 0, "processing": 0, "failed": 0, "synced": 0, "stale": 0,
        })
        entity_entry[state] = entity_entry.get(state, 0) + 1
        if row in stale_rows:
            entity_entry["stale"] += 1
    entity_rows = sorted(entity_health.values(), key=lambda item: (item.get("failed", 0), item.get("retry", 0), item.get("processing", 0)), reverse=True)
    return {
        "metrics": metrics,
        "entity_health": entity_rows[:20],
        "stale_rows": stale_rows[:20],
        "recent_failures": recent_failures[:20],
        "recent_conflicts": conflict_rows[:20],
        "checked_at": checked_at,
    }
