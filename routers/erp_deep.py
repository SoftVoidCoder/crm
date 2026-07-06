import hashlib
import json
import time
from datetime import datetime

from fastapi import APIRouter, Request

from database import audit_log, get_connection, next_safe_table_id
from permissions import can_access_scope, filter_rows_by_scope, has_permission, require_approved_user
from schemas import (
    AccountingEDOOperatorData,
    AccountingExternalReportData,
    AccountingExternalStatusSyncData,
    AccountingManualOperationData,
    BankExchangeBatchData,
    BankPaymentOrderData,
    CashGapScenarioData,
    CashOperationData,
    DebtAdjustmentData,
    FinanceBudgetData,
    FinancePeriodCloseData,
    FinanceObligationData,
    FinancePaymentRequestData,
    ProductionJobData,
    ProductionBOMMasterData,
    ProductionBOMVersionData,
    ProductionLaborNormData,
    ProductionMRPRunData,
    ProductionMaterialNormData,
    ProductionPlanningScenarioData,
    ProductionReworkData,
    ProductionSemifinishedData,
    ProductionShiftData,
    ProductionTechCardData,
    ProductionWorkCenterCalendarData,
    ProductionWorkCenterData,
    SpecificationVersionData,
    TreasuryApprovalRouteData,
    TreasuryProjectLimitData,
)
from services.accounting_close_service import load_accounting_close_workspace, run_accounting_close_cycle
from services.accounting_register_service import (
    period_register_summary,
    purge_registers_for_period,
    register_accounting_entry_by_id,
    rebuild_all_registers,
    rebuild_registers_for_period,
)
from services.production_planning_service import build_mrp_aps_plan
from services.production_costing_service import (
    build_plan_fact_cost_report,
    complete_operation_costing,
    create_bom_version,
    upsert_bom_master,
    upsert_work_center,
    upsert_work_center_calendar,
)

router = APIRouter()


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _json_load(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _row_dicts(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def _now_ts() -> int:
    return int(time.time())


def _safe_text(value) -> str:
    return str(value or "").strip()


def _payload_checksum(payload) -> str:
    packed = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _parse_date(value: str):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%Y %H:%M", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _period_key(value: str = "") -> str:
    dt = _parse_date(value) or datetime.now()
    return dt.strftime("%Y-%m")


def _report_payload_from_snapshot(conn, report_type: str, period_key: str) -> dict:
    row = conn.execute(
        """
        SELECT report_payload, amount_total, line_count, report_name
        FROM accounting_reporting_snapshots
        WHERE period_key=? AND report_type=?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (_safe_text(period_key), _safe_text(report_type)),
    ).fetchone()
    if not row:
        return {}
    payload = _json_load(row[0], [])
    return {
        "report_type": _safe_text(report_type),
        "period_key": _safe_text(period_key),
        "report_name": _safe_text(row[3]),
        "line_count": _safe_int(row[2]),
        "amount_total": round(_safe_float(row[1]), 2),
        "lines": payload,
    }


def _external_retry_policy(operator_row: dict) -> dict:
    policy = _json_load((operator_row or {}).get("retry_policy_json"), {})
    return {
        "max_retries": max(0, _safe_int(policy.get("max_retries", 3))),
        "delay_minutes": max(1, _safe_int(policy.get("delay_minutes", 15))),
    }


def _operator_payload(row: dict) -> dict:
    return {
        **row,
        "capabilities": _json_load(row.get("capabilities_json"), []),
        "retry_policy": _external_retry_policy(row),
    }


def _submission_payload(row: dict) -> dict:
    return {
        **row,
        "payload": _json_load(row.get("payload_json"), {}),
        "response_payload": _json_load(row.get("response_json"), {}),
    }


def _load_external_event_rows(conn, actor: dict | None = None, limit: int = 60) -> list[dict]:
    rows = _row_dicts(
        conn.execute(
            """
            SELECT
                ev.*,
                sub.report_type,
                sub.period_key,
                sub.submission_status,
                op.operator_name,
                op.provider_name,
                sub.legal_entity_id,
                sub.business_unit_id
            FROM accounting_external_submission_events ev
            LEFT JOIN accounting_external_submissions sub ON sub.id = ev.submission_id
            LEFT JOIN accounting_edo_operators op ON op.id = sub.operator_id
            ORDER BY ev.created_at DESC, ev.id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        )
    )
    return _scope_rows(actor, rows) if actor else rows


def _load_external_operator_rows(conn, actor: dict | None = None) -> list[dict]:
    rows = [_operator_payload(row) for row in _row_dicts(conn.execute("SELECT * FROM accounting_edo_operators ORDER BY updated_at DESC, id DESC"))]
    return _scope_rows(actor, rows) if actor else rows


def _load_external_submission_rows(conn, actor: dict | None = None, limit: int = 120) -> list[dict]:
    rows = [
        _submission_payload(row)
        for row in _row_dicts(
            conn.execute(
                """
                SELECT
                    sub.*,
                    COALESCE(op.operator_name, '') AS operator_name,
                    COALESCE(op.provider_name, '') AS provider_name
                FROM accounting_external_submissions sub
                LEFT JOIN accounting_edo_operators op ON op.id = sub.operator_id
                ORDER BY sub.updated_at DESC, sub.id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 400)),),
            )
        )
    ]
    return _scope_rows(actor, rows) if actor else rows


def _log_external_submission_event(conn, submission_id: int, event_type: str, status: str, message: str, actor_email: str = "", payload: dict | None = None):
    conn.execute(
        """
        INSERT INTO accounting_external_submission_events (
            id, submission_id, event_type, status, message, payload_json, actor_email, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            next_safe_table_id(conn, "accounting_external_submission_events"),
            _safe_int(submission_id),
            _safe_text(event_type),
            _safe_text(status),
            _safe_text(message),
            json.dumps(payload or {}, ensure_ascii=False),
            _safe_text(actor_email),
            _now_ts(),
        ),
    )


def _scope_rows(actor: dict, rows: list[dict]) -> list[dict]:
    return filter_rows_by_scope(actor, rows, "legal_entity_id", "business_unit_id")


def _fetch_rows(query: str, params: tuple = (), scoped_actor: dict | None = None) -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        rows = _row_dicts(conn.execute(query, params))
    finally:
        conn.close()
    return _scope_rows(scoped_actor, rows) if scoped_actor else rows


def _production_order_scope(conn, order_id: int) -> dict:
    row = conn.execute(
        "SELECT id, project_id, client_id, contract_id, object_id, legal_entity_id, business_unit_id, order_name FROM production_orders WHERE id=?",
        (_safe_int(order_id),),
    ).fetchone()
    return dict(row) if row else {}


def _shift_scope(conn, shift_id: int) -> dict:
    row = conn.execute(
        "SELECT id, legal_entity_id, business_unit_id, work_center, shift_name FROM production_shifts WHERE id=?",
        (_safe_int(shift_id),),
    ).fetchone()
    return dict(row) if row else {}


def _can_access_order(actor: dict, conn, order_id: int) -> bool:
    scope = _production_order_scope(conn, order_id)
    if not scope:
        return False
    return can_access_scope(actor, scope.get("legal_entity_id"), scope.get("business_unit_id"))


def _can_access_shift(actor: dict, conn, shift_id: int) -> bool:
    scope = _shift_scope(conn, shift_id)
    if not scope:
        return False
    return can_access_scope(actor, scope.get("legal_entity_id"), scope.get("business_unit_id"))


def _delete_row_with_scope(request: Request, module: str, action: str, table: str, record_id: int, entity_type: str, scope_loader):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, module, action):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        scope = scope_loader(conn, record_id)
        if not scope:
            return {"error": "not_found"}
        if not can_access_scope(actor, scope.get("legal_entity_id"), scope.get("business_unit_id")):
            return {"error": "forbidden_scope"}
        conn.execute(f"DELETE FROM {table} WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log(
        f"{entity_type}_deleted",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type=entity_type,
        entity_id=str(record_id),
        details={},
    )
    return {"status": "success"}


def _planning_scenario_payload(row: dict) -> dict:
    payload = _json_load(row.get("payload_json"), {})
    return {**row, "payload": payload}


def _load_production_mrp_aps(actor: dict, scenario: dict | None = None) -> dict:
    conn = get_connection(row_factory=True)
    try:
        orders = _row_dicts(conn.execute("SELECT * FROM production_orders ORDER BY updated_at DESC, id DESC"))
        operations = _row_dicts(conn.execute("SELECT * FROM production_operations ORDER BY updated_at DESC, id DESC"))
        bom_items = _row_dicts(conn.execute("SELECT * FROM production_bom_items ORDER BY updated_at DESC, id DESC"))
        material_norms = _row_dicts(conn.execute("SELECT * FROM production_material_norms ORDER BY updated_at DESC, id DESC"))
        labor_norms = _row_dicts(conn.execute("SELECT * FROM production_labor_norms ORDER BY updated_at DESC, id DESC"))
        shifts = _row_dicts(conn.execute("SELECT * FROM production_shifts ORDER BY shift_date ASC, id ASC"))
        inventory_rows = _row_dicts(conn.execute("SELECT * FROM inventory_balances ORDER BY updated_at DESC, id DESC"))
        purchase_rows = _row_dicts(conn.execute("SELECT * FROM purchase_orders ORDER BY updated_at DESC, id DESC"))
        scenarios = [_planning_scenario_payload(row) for row in _row_dicts(conn.execute("SELECT * FROM production_planning_scenarios ORDER BY updated_at DESC, id DESC"))]
        runs = _row_dicts(conn.execute("SELECT * FROM production_mrp_runs ORDER BY created_at DESC, id DESC LIMIT 20"))
        selected = scenario or next((row for row in scenarios if row.get("status") == "active"), None) or (scenarios[0] if scenarios else None)
        plan = build_mrp_aps_plan(
            actor=actor,
            orders=orders,
            operations=operations,
            bom_items=bom_items,
            material_norms=material_norms,
            labor_norms=labor_norms,
            shifts=shifts,
            inventory_rows=inventory_rows,
            purchase_rows=purchase_rows,
            scenarios=scenarios,
            filter_rows_by_scope_fn=filter_rows_by_scope,
            scenario=selected,
        )
        for run in runs:
            run["payload"] = _json_load(run.get("payload_json"), {})
        plan["runs"] = runs
        return plan
    finally:
        conn.close()


def _production_timeline_for_order(order: dict, operations: list[dict], route_templates: list[dict]) -> dict:
    route_rows = sorted(route_templates, key=lambda row: (_safe_int(row.get("sequence_no")), _safe_int(row.get("id"))))
    op_rows = sorted(operations, key=lambda row: (_safe_int(row.get("sequence_no")), _safe_int(row.get("id"))))
    used_ops: set[int] = set()
    steps: list[dict] = []

    for route in route_rows:
        matched = None
        for op in op_rows:
            op_id = _safe_int(op.get("id"))
            if op_id in used_ops:
                continue
            same_sequence = _safe_int(op.get("sequence_no")) == _safe_int(route.get("sequence_no"))
            same_name = str(op.get("operation_name") or "").strip() == str(route.get("operation_name") or "").strip()
            if same_sequence or same_name:
                matched = op
                used_ops.add(op_id)
                break
        step = {
            "sequence_no": _safe_int(route.get("sequence_no")),
            "operation_name": route.get("operation_name") or (matched or {}).get("operation_name") or "Этап",
            "work_center": route.get("work_center") or (matched or {}).get("work_center") or "",
            "status": (matched or {}).get("status") or "planned",
            "planned_hours": _safe_float((matched or {}).get("planned_hours")) or _safe_float(route.get("planned_hours")),
            "actual_hours": _safe_float((matched or {}).get("actual_hours")),
            "planned_qty": _safe_float((matched or {}).get("planned_qty")) or _safe_float(route.get("planned_qty")),
            "completed_qty": _safe_float((matched or {}).get("completed_qty")),
            "scrap_qty": _safe_float((matched or {}).get("scrap_qty")),
            "started_at": (matched or {}).get("started_at") or "",
            "finished_at": (matched or {}).get("finished_at") or "",
            "note": (matched or {}).get("note") or route.get("note") or "",
            "variance_hours": round(_safe_float((matched or {}).get("actual_hours")) - (_safe_float((matched or {}).get("planned_hours")) or _safe_float(route.get("planned_hours"))), 2),
        }
        steps.append(step)

    for op in op_rows:
        if _safe_int(op.get("id")) in used_ops:
            continue
        steps.append(
            {
                "sequence_no": _safe_int(op.get("sequence_no")),
                "operation_name": op.get("operation_name") or "Операция",
                "work_center": op.get("work_center") or "",
                "status": op.get("status") or "planned",
                "planned_hours": _safe_float(op.get("planned_hours")),
                "actual_hours": _safe_float(op.get("actual_hours")),
                "planned_qty": _safe_float(op.get("planned_qty")),
                "completed_qty": _safe_float(op.get("completed_qty")),
                "scrap_qty": _safe_float(op.get("scrap_qty")),
                "started_at": op.get("started_at") or "",
                "finished_at": op.get("finished_at") or "",
                "note": op.get("note") or "",
                "variance_hours": round(_safe_float(op.get("actual_hours")) - _safe_float(op.get("planned_hours")), 2),
            }
        )

    steps.sort(key=lambda row: (_safe_int(row.get("sequence_no")), str(row.get("operation_name") or "")))
    current_marked = False
    done_steps = 0
    for step in steps:
        status = str(step.get("status") or "planned")
        is_done = status == "done"
        if is_done:
            done_steps += 1
        is_current = False
        if not current_marked and status in {"planned", "in_progress", "otk"}:
            is_current = True
            current_marked = True
        step["is_current"] = is_current
        step["risk_level"] = "risk" if _safe_float(step.get("variance_hours")) > 0.5 or _safe_float(step.get("scrap_qty")) > 0 else ("done" if is_done else "active")
    if steps and not current_marked:
        steps[-1]["is_current"] = True

    completion_percent = round((done_steps / len(steps)) * 100, 1) if steps else _safe_float(order.get("progress"))
    return {
        "order_id": _safe_int(order.get("id")),
        "order_name": order.get("order_name") or "",
        "route_name": order.get("route_name") or "",
        "stage": order.get("stage") or "queue",
        "progress": _safe_float(order.get("progress")),
        "completion_percent": completion_percent,
        "steps": steps,
    }


def _production_change_log(actor: dict, allowed_order_ids: set[int], work_centers: set[str], limit: int = 40) -> list[dict]:
    entity_types = (
        "production_order",
        "production_operation",
        "production_bom_item",
        "production_route_template",
        "production_spec_version",
        "production_tech_card",
        "production_job",
        "production_material_norm",
        "production_labor_norm",
        "production_semifinished",
        "production_rework",
    )
    placeholders = ",".join("?" for _ in entity_types)
    conn = get_connection(row_factory=True)
    try:
        rows = _row_dicts(
            conn.execute(
                f"SELECT * FROM audit_log WHERE entity_type IN ({placeholders}) ORDER BY created_at DESC, id DESC LIMIT ?",
                (*entity_types, max(limit * 4, 80)),
            )
        )
    finally:
        conn.close()

    payload = []
    for row in rows:
        details = _json_load(row.get("details"), {})
        entity_type = row.get("entity_type") or ""
        order_id = 0
        if entity_type == "production_order":
            order_id = _safe_int(row.get("entity_id"))
        else:
            order_id = _safe_int(details.get("order_id"))
        work_center = str(details.get("work_center") or details.get("shift_name") or "")
        if order_id and allowed_order_ids and order_id not in allowed_order_ids:
            continue
        if not order_id and work_centers and work_center and work_center not in work_centers:
            continue
        title = (
            details.get("order_name")
            or details.get("operation_name")
            or details.get("item_name")
            or details.get("article")
            or details.get("title")
            or details.get("label")
            or details.get("defect_name")
            or details.get("shift_name")
            or entity_type
        )
        payload.append(
            {
                "id": _safe_int(row.get("id")),
                "action": row.get("action") or "",
                "actor_name": row.get("actor_name") or row.get("actor_email") or "Система",
                "entity_type": entity_type,
                "entity_id": row.get("entity_id") or "",
                "order_id": order_id,
                "title": title,
                "work_center": work_center,
                "details": details,
                "created_at": _safe_int(row.get("created_at")),
            }
        )
        if len(payload) >= limit:
            break
    return payload


def _load_production_deep(actor: dict) -> dict:
    orders = _fetch_rows("SELECT * FROM production_orders ORDER BY updated_at DESC, id DESC", scoped_actor=actor)
    allowed_order_ids = {row["id"] for row in orders}
    order_project_ids = {int(row.get("project_id") or 0) for row in orders if _safe_int(row.get("project_id"))}
    operations = [row for row in _fetch_rows("SELECT * FROM production_operations ORDER BY updated_at DESC, id DESC") if _safe_int(row.get("order_id")) in allowed_order_ids]
    bom_items = [row for row in _fetch_rows("SELECT * FROM production_bom_items ORDER BY updated_at DESC, id DESC") if _safe_int(row.get("order_id")) in allowed_order_ids]
    route_templates = [row for row in _fetch_rows("SELECT * FROM production_route_templates ORDER BY sequence_no ASC, updated_at DESC, id DESC") if _safe_int(row.get("order_id")) in allowed_order_ids]
    spec_versions = [
        {**row, "snapshot_items": _json_load(row.get("snapshot"), [])}
        for row in _fetch_rows("SELECT * FROM specification_versions ORDER BY created_at DESC, id DESC")
        if _safe_int(row.get("order_id")) in allowed_order_ids or _safe_int(row.get("project_id")) in order_project_ids
    ]
    tech_cards = [row for row in _fetch_rows("SELECT * FROM production_tech_cards ORDER BY updated_at DESC, id DESC") if _safe_int(row.get("order_id")) in allowed_order_ids]
    shifts = _fetch_rows("SELECT * FROM production_shifts ORDER BY shift_date DESC, id DESC", scoped_actor=actor)
    jobs = [row for row in _fetch_rows("SELECT * FROM production_jobs ORDER BY updated_at DESC, id DESC") if _safe_int(row.get("order_id")) in allowed_order_ids]
    material_norms = [row for row in _fetch_rows("SELECT * FROM production_material_norms ORDER BY updated_at DESC, id DESC") if _safe_int(row.get("order_id")) in allowed_order_ids]
    labor_norms = [row for row in _fetch_rows("SELECT * FROM production_labor_norms ORDER BY updated_at DESC, id DESC") if _safe_int(row.get("order_id")) in allowed_order_ids]
    semifinished = [row for row in _fetch_rows("SELECT * FROM production_semifinished ORDER BY updated_at DESC, id DESC") if _safe_int(row.get("order_id")) in allowed_order_ids]
    rework = [row for row in _fetch_rows("SELECT * FROM production_rework ORDER BY updated_at DESC, id DESC") if _safe_int(row.get("order_id")) in allowed_order_ids]

    work_centers = {}
    for shift in shifts:
        key = shift.get("work_center") or "Без центра"
        bucket = work_centers.setdefault(key, {"work_center": key, "capacity_hours": 0.0, "planned_hours": 0.0, "actual_hours": 0.0, "jobs_total": 0, "in_progress": 0})
        bucket["capacity_hours"] += _safe_float(shift.get("capacity_hours"))
    for item in operations:
        key = item.get("work_center") or "Без центра"
        bucket = work_centers.setdefault(key, {"work_center": key, "capacity_hours": 0.0, "planned_hours": 0.0, "actual_hours": 0.0, "jobs_total": 0, "in_progress": 0})
        bucket["planned_hours"] += _safe_float(item.get("planned_hours"))
        bucket["actual_hours"] += _safe_float(item.get("actual_hours"))
        if item.get("status") in {"in_progress", "otk"}:
            bucket["in_progress"] += 1
    for item in jobs:
        key = item.get("work_center") or "Без центра"
        bucket = work_centers.setdefault(key, {"work_center": key, "capacity_hours": 0.0, "planned_hours": 0.0, "actual_hours": 0.0, "jobs_total": 0, "in_progress": 0})
        bucket["jobs_total"] += 1
        if item.get("status") in {"queued", "in_progress"}:
            bucket["in_progress"] += 1
    work_center_load = []
    for item in work_centers.values():
        capacity = _safe_float(item["capacity_hours"])
        planned = _safe_float(item["planned_hours"])
        item["load_percent"] = round((planned / capacity) * 100, 1) if capacity > 0 else 0
        item["free_hours"] = round(max(capacity - planned, 0), 2)
        item["risk_level"] = "risk" if item["load_percent"] >= 90 or _safe_int(item["in_progress"]) >= 3 else ("warning" if item["load_percent"] >= 70 else "ok")
        work_center_load.append(item)
    work_center_load.sort(key=lambda row: (row.get("load_percent", 0), row.get("in_progress", 0)), reverse=True)

    plan_fact = []
    order_costing = []
    bottlenecks = []
    norm_fact_board = []
    order_timelines = []
    wip_board = {"queue": [], "in_work": [], "otk": [], "done": []}
    for order in orders:
        order_id = _safe_int(order.get("id"))
        order_ops = [row for row in operations if _safe_int(row.get("order_id")) == order_id]
        order_bom = [row for row in bom_items if _safe_int(row.get("order_id")) == order_id]
        order_routes = [row for row in route_templates if _safe_int(row.get("order_id")) == order_id]
        order_norms = [row for row in material_norms if _safe_int(row.get("order_id")) == order_id]
        order_labor = [row for row in labor_norms if _safe_int(row.get("order_id")) == order_id]
        order_rework = [row for row in rework if _safe_int(row.get("order_id")) == order_id]
        order_semi = [row for row in semifinished if _safe_int(row.get("order_id")) == order_id]

        fact_hours = _safe_float(order.get("labor_hours_fact")) or sum(_safe_float(row.get("actual_hours")) for row in order_ops)
        material_plan = sum(_safe_float(row.get("norm_qty")) for row in order_norms) or sum(_safe_float(row.get("planned_qty")) for row in order_bom)
        material_fact = sum(_safe_float(row.get("actual_qty")) for row in order_bom)
        labor_plan_cost = sum(_safe_float(row.get("norm_hours")) * _safe_float(row.get("rate_per_hour")) * max(1, _safe_int(row.get("team_size"))) for row in order_labor)
        labor_fact_cost = sum(_safe_float(row.get("actual_hours")) * _safe_float(row.get("labor_rate")) for row in order_ops)
        material_cost = sum(_safe_float(row.get("actual_qty") or row.get("planned_qty")) * _safe_float(row.get("unit_cost")) for row in order_bom)
        overhead_cost = sum(_safe_float(row.get("overhead_cost")) for row in order_ops)
        rework_cost = sum(_safe_float(row.get("extra_cost")) for row in order_rework)
        semifinished_cost = sum(_safe_float(row.get("qty")) * _safe_float(row.get("unit_cost")) for row in order_semi)
        total_cost = round(material_cost + labor_fact_cost + overhead_cost + rework_cost + semifinished_cost, 2)
        fact_qty = _safe_float(order.get("produced_qty"))

        plan_fact.append(
            {
                "order_id": order_id,
                "order_name": order.get("order_name", ""),
                "planned_qty": _safe_float(order.get("planned_qty")),
                "fact_qty": fact_qty,
                "qty_gap": round(fact_qty - _safe_float(order.get("planned_qty")), 2),
                "planned_hours": _safe_float(order.get("labor_hours_plan")),
                "fact_hours": round(fact_hours, 2),
                "hours_gap": round(fact_hours - _safe_float(order.get("labor_hours_plan")), 2),
                "material_plan": round(material_plan, 2),
                "material_fact": round(material_fact, 2),
                "status": order.get("stage", "queue"),
            }
        )
        order_costing.append(
            {
                "order_id": order_id,
                "order_name": order.get("order_name", ""),
                "material_cost": round(material_cost, 2),
                "labor_plan_cost": round(labor_plan_cost, 2),
                "labor_fact_cost": round(labor_fact_cost, 2),
                "overhead_cost": round(overhead_cost, 2),
                "rework_cost": round(rework_cost, 2),
                "semifinished_cost": round(semifinished_cost, 2),
                "total_cost": total_cost,
                "unit_cost": round(total_cost / fact_qty, 2) if fact_qty > 0 else 0,
            }
        )
        material_gap = round(material_fact - material_plan, 2)
        labor_plan_hours = _safe_float(order.get("labor_hours_plan")) or sum(_safe_float(row.get("norm_hours")) * max(1, _safe_int(row.get("team_size"))) for row in order_labor)
        labor_gap = round(fact_hours - labor_plan_hours, 2)
        cost_gap = round(total_cost - _safe_float(order.get("planned_cost")), 2)
        norm_fact_board.append(
            {
                "order_id": order_id,
                "order_name": order.get("order_name", ""),
                "material_plan": round(material_plan, 2),
                "material_fact": round(material_fact, 2),
                "material_gap": material_gap,
                "labor_plan_hours": round(labor_plan_hours, 2),
                "labor_fact_hours": round(fact_hours, 2),
                "labor_gap_hours": labor_gap,
                "planned_cost": round(_safe_float(order.get("planned_cost")), 2),
                "actual_cost": total_cost,
                "cost_gap": cost_gap,
                "scrap_qty": _safe_float(order.get("scrap_qty")) or sum(_safe_float(row.get("scrap_qty")) for row in order_ops),
                "risk_level": "risk" if material_gap > 0 or labor_gap > 0 or cost_gap > 0 else ("ok" if total_cost > 0 else "neutral"),
            }
        )
        timeline = _production_timeline_for_order(order, order_ops, order_routes)
        order_timelines.append(timeline)
        stage_key = order.get("stage") if str(order.get("stage") or "") in wip_board else "queue"
        overdue = bool(order.get("planned_finish") and (_parse_date(order.get("planned_finish")) or datetime.max) < datetime.now() and stage_key != "done")
        wip_board[stage_key].append(
            {
                "order_id": order_id,
                "order_name": order.get("order_name", ""),
                "responsible": order.get("responsible") or "",
                "priority": order.get("priority") or "normal",
                "planned_finish": order.get("planned_finish") or "",
                "progress": _safe_float(order.get("progress")),
                "produced_qty": _safe_float(order.get("produced_qty")),
                "planned_qty": _safe_float(order.get("planned_qty")),
                "current_step": next((step.get("operation_name") for step in timeline["steps"] if step.get("is_current")), ""),
                "overdue": overdue,
            }
        )
    for center in work_center_load[:8]:
        if center.get("load_percent", 0) >= 90 or center.get("in_progress", 0) >= 3:
            bottlenecks.append(
                {
                    "work_center": center.get("work_center"),
                    "load_percent": center.get("load_percent", 0),
                    "in_progress": center.get("in_progress", 0),
                    "message": "Высокая загрузка центра" if center.get("load_percent", 0) >= 90 else "Есть очередь по заданиям",
                }
            )

    shift_board = []
    for shift in shifts:
        work_center = shift.get("work_center") or "Без центра"
        related_ops = [row for row in operations if (row.get("work_center") or "Без центра") == work_center]
        related_jobs = [row for row in jobs if _safe_int(row.get("shift_id")) == _safe_int(shift.get("id")) or (row.get("work_center") or "Без центра") == work_center]
        planned_hours = round(sum(_safe_float(row.get("planned_hours")) for row in related_ops), 2)
        actual_hours = round(sum(_safe_float(row.get("actual_hours")) for row in related_ops), 2)
        capacity = _safe_float(shift.get("capacity_hours"))
        shift_board.append(
            {
                "id": _safe_int(shift.get("id")),
                "shift_name": shift.get("shift_name") or work_center,
                "shift_date": shift.get("shift_date") or "",
                "work_center": work_center,
                "capacity_hours": capacity,
                "planned_hours": planned_hours,
                "actual_hours": actual_hours,
                "jobs_total": len(related_jobs),
                "open_jobs": len([row for row in related_jobs if row.get("status") != "done"]),
                "supervisor_name": shift.get("supervisor_name") or "",
                "team_name": shift.get("team_name") or "",
                "load_percent": round((planned_hours / capacity) * 100, 1) if capacity > 0 else 0,
                "risk_level": "risk" if capacity > 0 and planned_hours > capacity else ("warning" if capacity > 0 and planned_hours >= capacity * 0.8 else "ok"),
                "status": shift.get("status") or "planned",
            }
        )
    shift_board.sort(key=lambda row: (row.get("load_percent", 0), row.get("open_jobs", 0)), reverse=True)
    norm_fact_board.sort(key=lambda row: (row.get("risk_level") == "risk", abs(_safe_float(row.get("cost_gap"))), abs(_safe_float(row.get("labor_gap_hours")))), reverse=True)
    work_centers_in_scope = {str(row.get("work_center") or "") for row in work_center_load if row.get("work_center")}
    change_log = _production_change_log(actor, allowed_order_ids, work_centers_in_scope)
    mrp_aps = _load_production_mrp_aps(actor)
    costing_report = {"rows": [], "totals": {}}
    conn = get_connection(row_factory=True)
    try:
        costing_report = build_plan_fact_cost_report(conn)
    finally:
        conn.close()
    costing_report["rows"] = [row for row in costing_report.get("rows", []) if _safe_int(row.get("order_id")) in allowed_order_ids]
    costing_report["totals"] = {
        "orders": len(costing_report["rows"]),
        "planned_cost": round(sum(_safe_float(row.get("planned_cost")) for row in costing_report["rows"]), 2),
        "fact_cost": round(sum(_safe_float(row.get("fact_cost")) for row in costing_report["rows"]), 2),
        "variance": round(sum(_safe_float(row.get("variance")) for row in costing_report["rows"]), 2),
        "produced_qty": round(sum(_safe_float(row.get("produced_qty")) for row in costing_report["rows"]), 4),
    }

    return {
        "route_templates": route_templates,
        "spec_versions": spec_versions,
        "tech_cards": tech_cards,
        "shifts": shifts,
        "jobs": jobs,
        "material_norms": material_norms,
        "labor_norms": labor_norms,
        "semifinished": semifinished,
        "rework": rework,
        "work_center_load": work_center_load,
        "shift_board": shift_board,
        "wip_board": wip_board,
        "order_timelines": order_timelines,
        "norm_fact_board": norm_fact_board,
        "change_log": change_log,
        "plan_fact": plan_fact,
        "order_costing": order_costing,
        "costing_report": costing_report,
        "bottlenecks": bottlenecks,
        "mrp_aps": mrp_aps,
        "metrics": {
            "spec_versions": len(spec_versions),
            "route_templates": len(route_templates),
            "tech_cards": len(tech_cards),
            "shifts": len(shifts),
            "jobs_open": len([row for row in jobs if row.get("status") != "done"]),
            "rework_open": len([row for row in rework if row.get("status") not in {"done", "closed"}]),
            "semifinished_qty": round(sum(_safe_float(row.get("qty")) for row in semifinished), 2),
            "overloaded_centers": len([row for row in work_center_load if row.get("risk_level") == "risk"]),
            "norm_drift_orders": len([row for row in norm_fact_board if row.get("risk_level") == "risk"]),
            "mrp_shortages": mrp_aps.get("metrics", {}).get("shortages", 0),
            "aps_unscheduled": mrp_aps.get("metrics", {}).get("unscheduled_operations", 0),
        },
    }


@router.get("/api/production/deep_summary")
def get_production_deep_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    return _load_production_deep(actor)


@router.get("/api/production/mrp_aps/summary")
def get_production_mrp_aps_summary(request: Request, scenario_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    scenario = None
    if scenario_id:
        conn = get_connection(row_factory=True)
        try:
            row = conn.execute("SELECT * FROM production_planning_scenarios WHERE id=?", (_safe_int(scenario_id),)).fetchone()
            scenario = _planning_scenario_payload(dict(row)) if row else None
        finally:
            conn.close()
    return _load_production_mrp_aps(actor, scenario=scenario)


@router.post("/api/production/mrp_aps/scenarios")
def create_production_planning_scenario(data: ProductionPlanningScenarioData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    payload = {
        "demand_multiplier": _safe_float(data.demand_multiplier) or 1,
        "capacity_multiplier": _safe_float(data.capacity_multiplier) or 1,
        "lead_time_days": _safe_int(data.lead_time_days),
        "freeze_days": _safe_int(data.freeze_days),
        "comment": data.comment or "",
    }
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.execute(
            """
            INSERT INTO production_planning_scenarios (
                scenario_name, planning_horizon_days, demand_mode, status, payload_json, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.scenario_name or f"MRP/APS {_now_ts()}",
                _safe_int(data.planning_horizon_days) or 30,
                data.demand_mode or "confirmed_orders",
                data.status or "active",
                json.dumps(payload, ensure_ascii=False),
                actor.get("email", ""),
                _now_ts(),
                _now_ts(),
            ),
        )
        scenario_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("production_planning_scenario_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_planning_scenario", entity_id=str(scenario_id), details={"scenario_name": data.scenario_name})
    return {"status": "success", "id": scenario_id}


@router.delete("/api/production/mrp_aps/scenarios/{scenario_id}")
def delete_production_planning_scenario(scenario_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "delete"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        conn.execute("DELETE FROM production_planning_scenarios WHERE id=?", (_safe_int(scenario_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("production_planning_scenario_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_planning_scenario", entity_id=str(scenario_id), details={})
    return {"status": "success"}


@router.post("/api/production/mrp_aps/run")
def run_production_mrp_aps(data: ProductionMRPRunData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    scenario = None
    conn = get_connection(row_factory=True)
    try:
        if data.scenario_id:
            row = conn.execute("SELECT * FROM production_planning_scenarios WHERE id=?", (_safe_int(data.scenario_id),)).fetchone()
            scenario = _planning_scenario_payload(dict(row)) if row else None
        plan = _load_production_mrp_aps(actor, scenario=scenario)
        run_id = 0
        if int(data.persist or 1):
            cursor = conn.execute(
                """
                INSERT INTO production_mrp_runs (
                    scenario_id, run_name, horizon_start, horizon_end, status, demand_total, shortages_total,
                    overloaded_centers, payload_json, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _safe_int(data.scenario_id),
                    data.run_name or f"MRP/APS {_now_ts()}",
                    plan.get("horizon", {}).get("start", ""),
                    plan.get("horizon", {}).get("end", ""),
                    "calculated",
                    _safe_int(plan.get("metrics", {}).get("active_orders")),
                    _safe_int(plan.get("metrics", {}).get("shortages")),
                    _safe_int(plan.get("metrics", {}).get("overloaded_buckets")),
                    json.dumps(plan, ensure_ascii=False),
                    actor.get("email", ""),
                    _now_ts(),
                ),
            )
            run_id = cursor.lastrowid
            conn.commit()
    finally:
        conn.close()
    audit_log("production_mrp_aps_run", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_mrp_run", entity_id=str(run_id), details={"scenario_id": data.scenario_id, "shortages": plan.get("metrics", {}).get("shortages", 0)})
    return {"status": "success", "id": run_id, "plan": plan}


@router.post("/api/production/mrp_aps/replan")
def replan_production_mrp_aps(data: ProductionMRPRunData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    return run_production_mrp_aps(data, request)


@router.get("/api/production/bom_master")
def get_production_bom_master(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        rows = _row_dicts(conn.execute("SELECT * FROM bom_master ORDER BY updated_at DESC, id DESC"))
    finally:
        conn.close()
    return [row for row in rows if can_access_scope(actor, row.get("legal_entity_id"), row.get("business_unit_id"))]


@router.post("/api/production/bom_master")
def create_production_bom_master(data: ProductionBOMMasterData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    if not can_access_scope(actor, data.legal_entity_id, data.business_unit_id):
        return {"error": "forbidden_scope"}
    conn = get_connection(row_factory=True)
    try:
        payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
        record_id = upsert_bom_master(conn, payload, actor.get("email", ""))
        conn.commit()
    finally:
        conn.close()
    audit_log("production_bom_master_upserted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="bom_master", entity_id=str(record_id), details={"bom_code": data.bom_code, "item_article": data.item_article})
    return {"status": "success", "id": record_id}


@router.get("/api/production/bom_versions")
def get_production_bom_versions(request: Request, bom_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        params = []
        query = """
            SELECT bv.*, bm.item_article, bm.item_name, bm.bom_code, bm.bom_name, bm.legal_entity_id, bm.business_unit_id
            FROM bom_versions bv
            LEFT JOIN bom_master bm ON bm.id=bv.bom_id
        """
        if bom_id:
            query += " WHERE bv.bom_id=?"
            params.append(_safe_int(bom_id))
        query += " ORDER BY bv.updated_at DESC, bv.id DESC"
        rows = _row_dicts(conn.execute(query, tuple(params)))
    finally:
        conn.close()
    return [row for row in rows if can_access_scope(actor, row.get("legal_entity_id"), row.get("business_unit_id"))]


@router.post("/api/production/bom_versions")
def create_production_bom_version(data: ProductionBOMVersionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        bom = dict(conn.execute("SELECT * FROM bom_master WHERE id=?", (_safe_int(data.bom_id),)).fetchone() or {})
        if not bom:
            return {"error": "bom_not_found"}
        if not can_access_scope(actor, bom.get("legal_entity_id"), bom.get("business_unit_id")):
            return {"error": "forbidden_scope"}
        payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
        record_id = create_bom_version(conn, payload, actor.get("email", ""))
        conn.commit()
    finally:
        conn.close()
    audit_log("production_bom_version_upserted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="bom_version", entity_id=str(record_id), details={"bom_id": data.bom_id, "version_no": data.version_no, "status": data.status})
    return {"status": "success", "id": record_id}


@router.get("/api/production/work_centers")
def get_production_work_centers(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        rows = _row_dicts(conn.execute("SELECT * FROM work_centers ORDER BY updated_at DESC, id DESC"))
    finally:
        conn.close()
    return [row for row in rows if can_access_scope(actor, row.get("legal_entity_id"), row.get("business_unit_id"))]


@router.post("/api/production/work_centers")
def create_production_work_center(data: ProductionWorkCenterData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    if not can_access_scope(actor, data.legal_entity_id, data.business_unit_id):
        return {"error": "forbidden_scope"}
    conn = get_connection(row_factory=True)
    try:
        payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
        record_id = upsert_work_center(conn, payload, actor.get("email", ""))
        conn.commit()
    finally:
        conn.close()
    audit_log("production_work_center_upserted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="work_center", entity_id=str(record_id), details={"center_code": data.center_code, "center_name": data.center_name})
    return {"status": "success", "id": record_id}


@router.get("/api/production/work_center_calendars")
def get_production_work_center_calendars(request: Request, work_center_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        params = []
        query = """
            SELECT wcc.*, wc.center_code, wc.center_name, wc.legal_entity_id, wc.business_unit_id
            FROM work_center_calendars wcc
            LEFT JOIN work_centers wc ON wc.id=wcc.work_center_id
        """
        if work_center_id:
            query += " WHERE wcc.work_center_id=?"
            params.append(_safe_int(work_center_id))
        query += " ORDER BY wcc.calendar_date DESC, wcc.shift_code"
        rows = _row_dicts(conn.execute(query, tuple(params)))
    finally:
        conn.close()
    return [row for row in rows if can_access_scope(actor, row.get("legal_entity_id"), row.get("business_unit_id"))]


@router.post("/api/production/work_center_calendars")
def create_production_work_center_calendar(data: ProductionWorkCenterCalendarData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        work_center = dict(conn.execute("SELECT * FROM work_centers WHERE id=?", (_safe_int(data.work_center_id),)).fetchone() or {})
        if not work_center:
            return {"error": "work_center_not_found"}
        if not can_access_scope(actor, work_center.get("legal_entity_id"), work_center.get("business_unit_id")):
            return {"error": "forbidden_scope"}
        payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
        record_id = upsert_work_center_calendar(conn, payload, actor.get("email", ""))
        conn.commit()
    finally:
        conn.close()
    audit_log("production_work_center_calendar_upserted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="work_center_calendar", entity_id=str(record_id), details={"work_center_id": data.work_center_id, "calendar_date": data.calendar_date})
    return {"status": "success", "id": record_id}


@router.post("/api/production/costing/operations/{operation_id}/rebuild")
def rebuild_production_operation_costing(operation_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        operation = dict(conn.execute("SELECT * FROM production_operations WHERE id=?", (_safe_int(operation_id),)).fetchone() or {})
        if not operation:
            return {"error": "operation_not_found"}
        if not _can_access_order(actor, conn, operation.get("order_id")):
            return {"error": "forbidden_scope"}
        result = complete_operation_costing(conn, operation_id, actor.get("email", ""))
        conn.commit()
    finally:
        conn.close()
    audit_log("production_operation_costing_rebuilt", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_operation", entity_id=str(operation_id), details=result)
    return result


@router.get("/api/production/costing/report")
def get_production_costing_report(request: Request, order_id: int = 0, period_key: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        if order_id and not _can_access_order(actor, conn, order_id):
            return {"error": "forbidden_scope"}
        payload = build_plan_fact_cost_report(conn, order_id, period_key)
    finally:
        conn.close()
    allowed_order_ids = {_safe_int(row.get("id")) for row in _fetch_rows("SELECT id, legal_entity_id, business_unit_id FROM production_orders", scoped_actor=actor)}
    payload["rows"] = [row for row in payload.get("rows", []) if _safe_int(row.get("order_id")) in allowed_order_ids]
    payload["totals"] = {
        "orders": len(payload["rows"]),
        "planned_cost": round(sum(_safe_float(row.get("planned_cost")) for row in payload["rows"]), 2),
        "fact_cost": round(sum(_safe_float(row.get("fact_cost")) for row in payload["rows"]), 2),
        "variance": round(sum(_safe_float(row.get("variance")) for row in payload["rows"]), 2),
        "produced_qty": round(sum(_safe_float(row.get("produced_qty")) for row in payload["rows"]), 4),
    }
    return payload


@router.get("/api/production/spec_versions")
def get_production_spec_versions(request: Request, order_id: int = 0, project_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    payload = _load_production_deep(actor).get("spec_versions", [])
    if order_id:
        payload = [row for row in payload if _safe_int(row.get("order_id")) == _safe_int(order_id)]
    if project_id:
        payload = [row for row in payload if _safe_int(row.get("project_id")) == _safe_int(project_id)]
    return payload


@router.post("/api/production/spec_versions")
def create_production_spec_version(data: SpecificationVersionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        scope = _production_order_scope(conn, data.order_id)
        if data.order_id and (not scope or not can_access_scope(actor, scope.get("legal_entity_id"), scope.get("business_unit_id"))):
            return {"error": "forbidden_scope"}
        snapshot_items = list(data.items or [])
        if not snapshot_items and data.order_id:
            snapshot_items = _row_dicts(conn.execute("SELECT article, item_name, unit, qty_per_unit, planned_qty, actual_qty, unit_cost, warehouse, bin_code, note FROM production_bom_items WHERE order_id=? ORDER BY id", (_safe_int(data.order_id),)))
        cursor = conn.execute(
            """
            INSERT INTO specification_versions (project_id, order_id, label, comment, version_status, snapshot, actor_email, actor_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _safe_int(data.project_id or scope.get("project_id")),
                _safe_int(data.order_id),
                (data.label or "").strip() or f"SPEC-{_now_ts()}",
                data.comment or "",
                data.version_status or "draft",
                json.dumps(snapshot_items, ensure_ascii=False),
                actor.get("email", ""),
                actor.get("name", ""),
                _now_ts(),
            ),
        )
        spec_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("production_spec_version_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_spec_version", entity_id=str(spec_id), details={"order_id": data.order_id, "label": data.label})
    return {"status": "success", "id": spec_id}


@router.delete("/api/production/spec_versions/{spec_id}")
def delete_production_spec_version(spec_id: int, request: Request):
    return _delete_row_with_scope(
        request,
        "production",
        "delete",
        "specification_versions",
        spec_id,
        "production_spec_version",
        lambda conn, record_id: (
            dict(conn.execute(
                """
                SELECT sv.id, po.legal_entity_id, po.business_unit_id
                FROM specification_versions sv
                LEFT JOIN production_orders po ON po.id = sv.order_id
                WHERE sv.id=?
                """,
                (_safe_int(record_id),),
            ).fetchone() or {})
        ),
    )


@router.get("/api/production/tech_cards/deep")
def get_production_tech_cards(request: Request, order_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    rows = _load_production_deep(actor).get("tech_cards", [])
    return [row for row in rows if not order_id or _safe_int(row.get("order_id")) == _safe_int(order_id)]


@router.post("/api/production/tech_cards/deep")
def create_production_tech_card(data: ProductionTechCardData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        scope = _production_order_scope(conn, data.order_id)
        if not scope or not can_access_scope(actor, scope.get("legal_entity_id"), scope.get("business_unit_id")):
            return {"error": "forbidden_scope"}
        cursor = conn.execute(
            """
            INSERT INTO production_tech_cards (order_id, title, work_center, setup_minutes, run_minutes, instruction, quality_points, status, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.order_id), data.title, data.work_center, data.setup_minutes, data.run_minutes, data.instruction, data.quality_points, data.status, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("production_tech_card_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_tech_card", entity_id=str(record_id), details={"order_id": data.order_id, "title": data.title})
    return {"status": "success", "id": record_id}


@router.delete("/api/production/tech_cards/deep/{record_id}")
def delete_production_tech_card(record_id: int, request: Request):
    return _delete_row_with_scope(
        request,
        "production",
        "delete",
        "production_tech_cards",
        record_id,
        "production_tech_card",
        lambda conn, rid: dict(conn.execute("SELECT pt.id, po.legal_entity_id, po.business_unit_id FROM production_tech_cards pt LEFT JOIN production_orders po ON po.id = pt.order_id WHERE pt.id=?", (_safe_int(rid),)).fetchone() or {}),
    )


@router.get("/api/production/shifts/deep")
def get_production_shifts(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    return _load_production_deep(actor).get("shifts", [])


@router.post("/api/production/shifts/deep")
def create_production_shift(data: ProductionShiftData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    if not can_access_scope(actor, data.legal_entity_id, data.business_unit_id):
        return {"error": "forbidden_scope"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.execute(
            """
            INSERT INTO production_shifts (legal_entity_id, business_unit_id, shift_date, shift_name, work_center, capacity_hours, team_name, supervisor_name, status, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.legal_entity_id), _safe_int(data.business_unit_id), data.shift_date, data.shift_name, data.work_center, data.capacity_hours, data.team_name, data.supervisor_name, data.status, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        shift_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("production_shift_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_shift", entity_id=str(shift_id), details={"work_center": data.work_center, "shift_name": data.shift_name})
    return {"status": "success", "id": shift_id}


@router.delete("/api/production/shifts/deep/{shift_id}")
def delete_production_shift(shift_id: int, request: Request):
    return _delete_row_with_scope(request, "production", "delete", "production_shifts", shift_id, "production_shift", _shift_scope)


@router.get("/api/production/jobs/deep")
def get_production_jobs(request: Request, order_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    rows = _load_production_deep(actor).get("jobs", [])
    return [row for row in rows if not order_id or _safe_int(row.get("order_id")) == _safe_int(order_id)]


@router.post("/api/production/jobs/deep")
def create_production_job(data: ProductionJobData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        if data.order_id and not _can_access_order(actor, conn, data.order_id):
            return {"error": "forbidden_scope"}
        if data.shift_id and not _can_access_shift(actor, conn, data.shift_id):
            return {"error": "forbidden_scope"}
        cursor = conn.execute(
            """
            INSERT INTO production_jobs (order_id, shift_id, operation_id, title, work_center, executor_name, planned_qty, completed_qty, status, started_at, finished_at, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.order_id), _safe_int(data.shift_id), _safe_int(data.operation_id), data.title, data.work_center, data.executor_name, data.planned_qty, data.completed_qty, data.status, data.started_at, data.finished_at, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        job_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("production_job_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_job", entity_id=str(job_id), details={"order_id": data.order_id, "title": data.title})
    return {"status": "success", "id": job_id}


@router.delete("/api/production/jobs/deep/{job_id}")
def delete_production_job(job_id: int, request: Request):
    return _delete_row_with_scope(
        request,
        "production",
        "delete",
        "production_jobs",
        job_id,
        "production_job",
        lambda conn, rid: dict(conn.execute(
            """
            SELECT pj.id, COALESCE(po.legal_entity_id, ps.legal_entity_id, 0) AS legal_entity_id, COALESCE(po.business_unit_id, ps.business_unit_id, 0) AS business_unit_id
            FROM production_jobs pj
            LEFT JOIN production_orders po ON po.id = pj.order_id
            LEFT JOIN production_shifts ps ON ps.id = pj.shift_id
            WHERE pj.id=?
            """,
            (_safe_int(rid),),
        ).fetchone() or {}),
    )


@router.get("/api/production/material_norms/deep")
def get_production_material_norms(request: Request, order_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    rows = _load_production_deep(actor).get("material_norms", [])
    return [row for row in rows if not order_id or _safe_int(row.get("order_id")) == _safe_int(order_id)]


@router.post("/api/production/material_norms/deep")
def create_production_material_norm(data: ProductionMaterialNormData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        if not _can_access_order(actor, conn, data.order_id):
            return {"error": "forbidden_scope"}
        cursor = conn.execute(
            """
            INSERT INTO production_material_norms (order_id, article, item_name, unit, norm_qty, scrap_rate, substitute_article, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.order_id), data.article, data.item_name, data.unit or "шт", data.norm_qty, data.scrap_rate, data.substitute_article, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("production_material_norm_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_material_norm", entity_id=str(record_id), details={"order_id": data.order_id, "article": data.article})
    return {"status": "success", "id": record_id}


@router.delete("/api/production/material_norms/deep/{record_id}")
def delete_production_material_norm(record_id: int, request: Request):
    return _delete_row_with_scope(request, "production", "delete", "production_material_norms", record_id, "production_material_norm", lambda conn, rid: dict(conn.execute("SELECT pmn.id, po.legal_entity_id, po.business_unit_id FROM production_material_norms pmn LEFT JOIN production_orders po ON po.id = pmn.order_id WHERE pmn.id=?", (_safe_int(rid),)).fetchone() or {}))


@router.get("/api/production/labor_norms/deep")
def get_production_labor_norms(request: Request, order_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    rows = _load_production_deep(actor).get("labor_norms", [])
    return [row for row in rows if not order_id or _safe_int(row.get("order_id")) == _safe_int(order_id)]


@router.post("/api/production/labor_norms/deep")
def create_production_labor_norm(data: ProductionLaborNormData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        if not _can_access_order(actor, conn, data.order_id):
            return {"error": "forbidden_scope"}
        cursor = conn.execute(
            """
            INSERT INTO production_labor_norms (order_id, operation_name, work_center, norm_hours, rate_per_hour, team_size, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.order_id), data.operation_name, data.work_center, data.norm_hours, data.rate_per_hour, _safe_int(data.team_size) or 1, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("production_labor_norm_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_labor_norm", entity_id=str(record_id), details={"order_id": data.order_id, "operation_name": data.operation_name})
    return {"status": "success", "id": record_id}


@router.delete("/api/production/labor_norms/deep/{record_id}")
def delete_production_labor_norm(record_id: int, request: Request):
    return _delete_row_with_scope(request, "production", "delete", "production_labor_norms", record_id, "production_labor_norm", lambda conn, rid: dict(conn.execute("SELECT pln.id, po.legal_entity_id, po.business_unit_id FROM production_labor_norms pln LEFT JOIN production_orders po ON po.id = pln.order_id WHERE pln.id=?", (_safe_int(rid),)).fetchone() or {}))


@router.get("/api/production/semifinished/deep")
def get_production_semifinished(request: Request, order_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    rows = _load_production_deep(actor).get("semifinished", [])
    return [row for row in rows if not order_id or _safe_int(row.get("order_id")) == _safe_int(order_id)]


@router.post("/api/production/semifinished/deep")
def create_production_semifinished(data: ProductionSemifinishedData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        if not _can_access_order(actor, conn, data.order_id):
            return {"error": "forbidden_scope"}
        cursor = conn.execute(
            """
            INSERT INTO production_semifinished (order_id, article, item_name, qty, stage_name, warehouse, status, unit_cost, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.order_id), data.article, data.item_name, data.qty, data.stage_name, data.warehouse, data.status, data.unit_cost, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("production_semifinished_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_semifinished", entity_id=str(record_id), details={"order_id": data.order_id, "article": data.article})
    return {"status": "success", "id": record_id}


@router.delete("/api/production/semifinished/deep/{record_id}")
def delete_production_semifinished(record_id: int, request: Request):
    return _delete_row_with_scope(request, "production", "delete", "production_semifinished", record_id, "production_semifinished", lambda conn, rid: dict(conn.execute("SELECT ps.id, po.legal_entity_id, po.business_unit_id FROM production_semifinished ps LEFT JOIN production_orders po ON po.id = ps.order_id WHERE ps.id=?", (_safe_int(rid),)).fetchone() or {}))


@router.get("/api/production/rework/deep")
def get_production_rework(request: Request, order_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    rows = _load_production_deep(actor).get("rework", [])
    return [row for row in rows if not order_id or _safe_int(row.get("order_id")) == _safe_int(order_id)]


@router.post("/api/production/rework/deep")
def create_production_rework(data: ProductionReworkData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        if not _can_access_order(actor, conn, data.order_id):
            return {"error": "forbidden_scope"}
        cursor = conn.execute(
            """
            INSERT INTO production_rework (order_id, related_operation_id, defect_name, qty, reason, rework_route, status, extra_cost, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.order_id), _safe_int(data.related_operation_id), data.defect_name, data.qty, data.reason, data.rework_route, data.status, data.extra_cost, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("production_rework_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_rework", entity_id=str(record_id), details={"order_id": data.order_id, "defect_name": data.defect_name})
    return {"status": "success", "id": record_id}


@router.delete("/api/production/rework/deep/{record_id}")
def delete_production_rework(record_id: int, request: Request):
    return _delete_row_with_scope(request, "production", "delete", "production_rework", record_id, "production_rework", lambda conn, rid: dict(conn.execute("SELECT pr.id, po.legal_entity_id, po.business_unit_id FROM production_rework pr LEFT JOIN production_orders po ON po.id = pr.order_id WHERE pr.id=?", (_safe_int(rid),)).fetchone() or {}))


def _auto_create_payment_from_request(conn, request_row: dict, actor: dict):
    if _safe_int(request_row.get("linked_payment_id")) or request_row.get("request_status") not in {"approved", "to_pay", "paid"}:
        return 0
    now = _now_ts()
    status = "paid" if request_row.get("request_status") == "paid" else "planned"
    cursor = conn.execute(
        """
        INSERT INTO finance_payments (
            project_id, client_id, legal_entity_id, business_unit_id, title, kind, category, amount, currency,
            due_date, paid_date, status, comment, exchange_state, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'outgoing', 'payment', ?, ?, ?, '', ?, ?, 'draft', ?, ?, ?)
        """,
        (
            _safe_int(request_row.get("project_id")),
            _safe_int(request_row.get("client_id")),
            _safe_int(request_row.get("legal_entity_id")),
            _safe_int(request_row.get("business_unit_id")),
            request_row.get("title", "") or "Заявка на оплату",
            _safe_float(request_row.get("amount")),
            request_row.get("currency", "RUB") or "RUB",
            request_row.get("due_date", ""),
            status,
            request_row.get("comment", ""),
            actor.get("email", ""),
            now,
            now,
        ),
    )
    payment_id = cursor.lastrowid
    conn.execute("UPDATE finance_payment_requests SET linked_payment_id=?, updated_at=? WHERE id=?", (payment_id, now, _safe_int(request_row.get("id"))))
    return payment_id


def _load_finance_deep(actor: dict) -> dict:
    conn = get_connection(row_factory=True)
    try:
        payments = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM finance_payments ORDER BY COALESCE(paid_date, due_date) DESC, id DESC")))
        requests = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM finance_payment_requests ORDER BY updated_at DESC, id DESC")))
        limits = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM treasury_project_limits ORDER BY period_key DESC, id DESC")))
        budgets = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM finance_budgets ORDER BY period_key DESC, id DESC")))
        obligations = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM finance_obligations ORDER BY due_date DESC, id DESC")))
        scenarios = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM finance_cash_gap_scenarios ORDER BY period_key DESC, id DESC")))
        routes = _scope_rows(actor, [_serialize_route(item) for item in _row_dicts(conn.execute("SELECT * FROM treasury_approval_routes ORDER BY is_default DESC, min_amount, id"))])
        bank_orders = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM bank_payment_orders ORDER BY updated_at DESC, id DESC LIMIT 120")))
        exchange_batches = _row_dicts(conn.execute("SELECT * FROM bank_exchange_batches ORDER BY created_at DESC, id DESC LIMIT 60"))
    finally:
        conn.close()

    calendar = []
    by_due = {}
    for item in [*payments, *obligations]:
        due = str(item.get("due_date") or "без срока").strip() or "без срока"
        bucket = by_due.setdefault(due, {"due_date": due, "incoming": 0.0, "outgoing": 0.0, "obligations": 0.0, "payments": 0.0})
        amount = _safe_float(item.get("amount"))
        if "obligation_type" in item:
            bucket["obligations"] += amount
            bucket["outgoing"] += amount
        else:
            bucket["payments"] += amount
            if item.get("kind") == "incoming":
                bucket["incoming"] += amount
            else:
                bucket["outgoing"] += amount
    for row in by_due.values():
        row["net"] = round(row["incoming"] - row["outgoing"], 2)
        calendar.append(row)
    calendar.sort(key=lambda item: item.get("due_date", ""))

    linked_paid = {_safe_int(payment.get("id")): _safe_float(payment.get("amount")) for payment in payments}
    reconciliation = []
    for item in obligations:
        linked_payment_id = _safe_int(item.get("linked_payment_id"))
        paid_amount = linked_paid.get(linked_payment_id, 0.0)
        reconciliation.append(
            {
                "obligation_id": item.get("id"),
                "title": item.get("title", ""),
                "amount": _safe_float(item.get("amount")),
                "paid_amount": round(paid_amount, 2),
                "open_amount": round(_safe_float(item.get("amount")) - paid_amount, 2),
                "status": item.get("status", "open"),
                "due_date": item.get("due_date", ""),
            }
        )

    budget_variance = []
    by_article_actual: dict[str, float] = {}
    for payment in payments:
        article_name = payment.get("treasury_article_name") or payment.get("title") or "Без статьи"
        by_article_actual.setdefault(article_name, 0.0)
        by_article_actual[article_name] += _safe_float(payment.get("amount"))
    for item in budgets:
        gap = round(_safe_float(item.get("fact_amount")) - _safe_float(item.get("plan_amount")), 2)
        budget_variance.append(
            {
                "budget_id": item.get("id"),
                "budget_type": item.get("budget_type", "pnl"),
                "article_name": item.get("article_name", ""),
                "period_key": item.get("period_key", ""),
                "plan_amount": _safe_float(item.get("plan_amount")),
                "fact_amount": _safe_float(item.get("fact_amount")),
                "gap": gap,
                "factor": "positive" if gap > 0 else "negative" if gap < 0 else "flat",
            }
        )
    factor_variance = []
    for item in budgets:
        article_name = item.get("article_name", "") or "Без статьи"
        actual = round(by_article_actual.get(article_name, _safe_float(item.get("fact_amount"))), 2)
        plan = round(_safe_float(item.get("plan_amount")), 2)
        factor_variance.append(
            {
                "article_name": article_name,
                "budget_type": item.get("budget_type", "pnl"),
                "plan_amount": plan,
                "actual_amount": actual,
                "variance": round(actual - plan, 2),
                "driver": "treasury_flow" if actual else "budget_only",
            }
        )
    budget_variance.sort(key=lambda item: abs(item.get("gap", 0)), reverse=True)
    factor_variance.sort(key=lambda item: abs(item.get("variance", 0)), reverse=True)

    management_balance = {
        "cash": round(sum(_safe_float(row.get("amount")) for row in payments if row.get("status") == "paid" and row.get("kind") == "incoming") - sum(_safe_float(row.get("amount")) for row in payments if row.get("status") == "paid" and row.get("kind") == "outgoing"), 2),
        "receivables": round(sum(_safe_float(row.get("amount")) for row in payments if row.get("kind") == "incoming" and row.get("status") != "paid"), 2),
        "payables": round(sum(_safe_float(row.get("amount")) for row in payments if row.get("kind") == "outgoing" and row.get("status") != "paid") + sum(_safe_float(row.get("amount")) for row in obligations if row.get("status") != "closed"), 2),
        "approval_pipeline": round(sum(_safe_float(row.get("amount")) for row in requests if row.get("request_status") not in {"paid", "closed"}), 2),
    }
    management_balance["net_working_capital"] = round(management_balance["cash"] + management_balance["receivables"] - management_balance["payables"], 2)

    approval_board = []
    for item in requests:
        matched = next((route for route in routes if _route_match(route, _safe_int(item.get("legal_entity_id")), _safe_int(item.get("business_unit_id")), _safe_float(item.get("amount")), item.get("currency", "RUB"))), None)
        stages = (matched or {}).get("stages", [])
        pending_stage = next((stage for stage in stages if stage.get("role")), {})
        approval_board.append(
            {
                "request_id": item.get("id"),
                "title": item.get("title", ""),
                "amount": _safe_float(item.get("amount")),
                "request_status": item.get("request_status", "draft"),
                "approval_status": item.get("approval_status", "draft"),
                "route_name": (matched or {}).get("route_name", "Без маршрута"),
                "stages_total": len(stages),
                "pending_role": pending_stage.get("role", item.get("approver_name") or "Назначить"),
                "coverage": "matched" if matched else "manual",
            }
        )

    bank_exchange_metrics = {
        "orders_draft": len([row for row in bank_orders if row.get("status") == "draft"]),
        "orders_exported": len([row for row in bank_orders if row.get("status") == "exported"]),
        "orders_executed": len([row for row in bank_orders if row.get("status") == "executed"]),
        "batches_total": len(exchange_batches),
    }

    return {
        "payment_requests": requests,
        "project_limits": limits,
        "budgets": budgets,
        "obligations": obligations,
        "cash_gap_scenarios": scenarios,
        "payment_calendar": calendar[:40],
        "payment_obligation_reconciliation": reconciliation[:60],
        "budget_variance": budget_variance[:40],
        "factor_variance": factor_variance[:40],
        "management_balance": management_balance,
        "treasury_routes": routes,
        "treasury_approval_board": approval_board[:60],
        "bank_payment_orders": bank_orders[:60],
        "exchange_batches": exchange_batches[:40],
        "bank_exchange_metrics": bank_exchange_metrics,
        "metrics": {
            "requests_open": len([row for row in requests if row.get("request_status") not in {"paid", "closed"}]),
            "obligations_open": len([row for row in obligations if row.get("status") not in {"closed", "paid"}]),
            "project_limits": len(limits),
            "budgets": len(budgets),
            "cash_gap_scenarios": len(scenarios),
            "cash_gap_plan": round(sum(item.get("net", 0) for item in calendar), 2),
            "treasury_routes": len(routes),
            "bank_orders": len(bank_orders),
        },
    }


@router.get("/api/finance/deep_summary")
def get_finance_deep_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_finance_deep(actor)


@router.get("/api/finance/payment_requests")
def get_finance_payment_requests(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_finance_deep(actor).get("payment_requests", [])


@router.post("/api/finance/payment_requests")
def create_finance_payment_request(data: FinancePaymentRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "create"):
        return {"error": "forbidden"}
    if not can_access_scope(actor, data.legal_entity_id, data.business_unit_id):
        return {"error": "forbidden_scope"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.execute(
            """
            INSERT INTO finance_payment_requests (project_id, client_id, legal_entity_id, business_unit_id, title, amount, currency, due_date, approver_name, approval_status, request_status, linked_payment_id, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.project_id), _safe_int(data.client_id), _safe_int(data.legal_entity_id), _safe_int(data.business_unit_id), data.title, data.amount, data.currency, data.due_date, data.approver_name, data.approval_status, data.request_status, _safe_int(data.linked_payment_id), data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        request_id = cursor.lastrowid
        row = dict(conn.execute("SELECT * FROM finance_payment_requests WHERE id=?", (request_id,)).fetchone() or {})
        payment_id = _auto_create_payment_from_request(conn, row, actor)
        conn.commit()
    finally:
        conn.close()
    audit_log("finance_payment_request_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="finance_payment_request", entity_id=str(request_id), details={"title": data.title, "payment_id": payment_id})
    return {"status": "success", "id": request_id, "linked_payment_id": payment_id}


@router.delete("/api/finance/payment_requests/{request_id}")
def delete_finance_payment_request(request_id: int, request: Request):
    return _delete_row_with_scope(request, "finance", "delete", "finance_payment_requests", request_id, "finance_payment_request", lambda conn, rid: dict(conn.execute("SELECT id, legal_entity_id, business_unit_id FROM finance_payment_requests WHERE id=?", (_safe_int(rid),)).fetchone() or {}))


@router.get("/api/finance/project_limits")
def get_finance_project_limits(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_finance_deep(actor).get("project_limits", [])


@router.post("/api/finance/project_limits")
def create_finance_project_limit(data: TreasuryProjectLimitData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "manage_limits"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        if data.business_unit_id and not can_access_scope(actor, 0, data.business_unit_id):
            return {"error": "forbidden_scope"}
        conn.execute(
            """
            INSERT INTO treasury_project_limits (period_key, project_id, business_unit_id, amount_limit, status, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(period_key, project_id, business_unit_id) DO UPDATE SET amount_limit=excluded.amount_limit, status=excluded.status, comment=excluded.comment, updated_at=excluded.updated_at
            """,
            ((data.period_key or "").strip() or _period_key(""), _safe_int(data.project_id), _safe_int(data.business_unit_id), _safe_float(data.amount_limit), data.status or "active", data.comment or "", actor.get("email", ""), _now_ts(), _now_ts()),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("finance_project_limit_saved", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="treasury_project_limit", entity_id=str(data.project_id), details={"period_key": data.period_key, "amount_limit": data.amount_limit})
    return {"status": "success"}


@router.delete("/api/finance/project_limits/{record_id}")
def delete_finance_project_limit(record_id: int, request: Request):
    return _delete_row_with_scope(request, "finance", "manage_limits", "treasury_project_limits", record_id, "treasury_project_limit", lambda conn, rid: dict(conn.execute("SELECT tpl.id, 0 AS legal_entity_id, tpl.business_unit_id FROM treasury_project_limits tpl WHERE tpl.id=?", (_safe_int(rid),)).fetchone() or {}))


@router.get("/api/finance/budgets/deep")
def get_finance_budgets(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_finance_deep(actor).get("budgets", [])


@router.post("/api/finance/budgets/deep")
def create_finance_budget(data: FinanceBudgetData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    if data.business_unit_id and not can_access_scope(actor, 0, data.business_unit_id):
        return {"error": "forbidden_scope"}
    conn = get_connection(row_factory=True)
    try:
        conn.execute(
            """
            INSERT INTO finance_budgets (budget_type, period_key, project_id, business_unit_id, article_name, plan_amount, fact_amount, status, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (data.budget_type or "pnl", (data.period_key or "").strip() or _period_key(""), _safe_int(data.project_id), _safe_int(data.business_unit_id), data.article_name, data.plan_amount, data.fact_amount, data.status, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("finance_budget_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="finance_budget", entity_id="new", details={"budget_type": data.budget_type, "article_name": data.article_name})
    return {"status": "success"}


@router.delete("/api/finance/budgets/deep/{record_id}")
def delete_finance_budget(record_id: int, request: Request):
    return _delete_row_with_scope(request, "finance", "delete", "finance_budgets", record_id, "finance_budget", lambda conn, rid: dict(conn.execute("SELECT fb.id, 0 AS legal_entity_id, fb.business_unit_id FROM finance_budgets fb WHERE fb.id=?", (_safe_int(rid),)).fetchone() or {}))


@router.get("/api/finance/obligations/deep")
def get_finance_obligations(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_finance_deep(actor).get("obligations", [])


@router.post("/api/finance/obligations/deep")
def create_finance_obligation(data: FinanceObligationData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "create"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        conn.execute(
            """
            INSERT INTO finance_obligations (project_id, client_id, contract_id, supplier_name, obligation_type, title, amount, currency, due_date, linked_payment_id, status, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.project_id), _safe_int(data.client_id), _safe_int(data.contract_id), data.supplier_name, data.obligation_type, data.title, data.amount, data.currency, data.due_date, _safe_int(data.linked_payment_id), data.status, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("finance_obligation_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="finance_obligation", entity_id="new", details={"title": data.title, "amount": data.amount})
    return {"status": "success"}


@router.delete("/api/finance/obligations/deep/{record_id}")
def delete_finance_obligation(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "delete"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        conn.execute("DELETE FROM finance_obligations WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("finance_obligation_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="finance_obligation", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.get("/api/finance/cash_gap_scenarios")
def get_finance_cash_gap_scenarios(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_finance_deep(actor).get("cash_gap_scenarios", [])


@router.post("/api/finance/cash_gap_scenarios")
def create_finance_cash_gap_scenario(data: CashGapScenarioData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        conn.execute(
            """
            INSERT INTO finance_cash_gap_scenarios (period_key, scenario_name, opening_balance, expected_inflow, expected_outflow, gap_amount, action_plan, status, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ((data.period_key or "").strip() or _period_key(""), data.scenario_name, data.opening_balance, data.expected_inflow, data.expected_outflow, data.gap_amount or round(_safe_float(data.opening_balance) + _safe_float(data.expected_inflow) - _safe_float(data.expected_outflow), 2), data.action_plan, data.status, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("finance_cash_gap_scenario_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="finance_cash_gap_scenario", entity_id="new", details={"scenario_name": data.scenario_name})
    return {"status": "success"}


@router.delete("/api/finance/cash_gap_scenarios/{record_id}")
def delete_finance_cash_gap_scenario(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "delete"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        conn.execute("DELETE FROM finance_cash_gap_scenarios WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("finance_cash_gap_scenario_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="finance_cash_gap_scenario", entity_id=str(record_id), details={})
    return {"status": "success"}


def _ensure_open_period(conn, date_text: str) -> tuple[bool, str]:
    period_key = _period_key(date_text)
    row = conn.execute("SELECT status FROM accounting_periods WHERE period_key=?", (period_key,)).fetchone()
    if row and str(row["status"] if hasattr(row, "keys") else row[0]) == "closed":
        return False, period_key
    return True, period_key


def _insert_accounting_entry(conn, payload: dict):
    cursor = conn.execute(
        """
        INSERT INTO accounting_entries (
            source_type, source_id, entry_date, period_key, legal_entity_id, business_unit_id, project_id, client_id,
            contract_id, object_id, treasury_article_id, vat_rate_id, account_debit, account_credit, amount, vat_amount,
            currency, description, posted_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.get("source_type", ""),
            _safe_int(payload.get("source_id")),
            payload.get("entry_date", ""),
            payload.get("period_key", _period_key(payload.get("entry_date", ""))),
            _safe_int(payload.get("legal_entity_id")),
            _safe_int(payload.get("business_unit_id")),
            _safe_int(payload.get("project_id")),
            _safe_int(payload.get("client_id")),
            _safe_int(payload.get("contract_id")),
            _safe_int(payload.get("object_id")),
            _safe_int(payload.get("treasury_article_id")),
            _safe_int(payload.get("vat_rate_id")),
            payload.get("account_debit", ""),
            payload.get("account_credit", ""),
            round(_safe_float(payload.get("amount")), 2),
            round(_safe_float(payload.get("vat_amount")), 2),
            payload.get("currency", "RUB") or "RUB",
            payload.get("description", ""),
            payload.get("posted_by", ""),
            _now_ts(),
        ),
    )
    entry_id = getattr(cursor, "lastrowid", 0) or 0
    if entry_id:
        register_accounting_entry_by_id(conn, entry_id, payload.get("posted_by", ""))


def _rebuild_auto_accounting(conn, actor: dict) -> dict:
    auto_types = ("sales_document", "purchase_order", "production_order", "manual_operation", "debt_adjustment", "cash_operation", "bank_statement")
    conn.execute(
        f"""
        DELETE FROM accounting_entries
        WHERE source_type IN ({', '.join(['?'] * len(auto_types))})
          AND COALESCE(period_key, '') NOT IN (
              SELECT period_key FROM accounting_periods WHERE status='closed'
          )
        """,
        auto_types,
    )
    for period in _row_dicts(conn.execute("SELECT period_key FROM accounting_periods WHERE status<>'closed'")):
        purge_registers_for_period(conn, period.get("period_key"), auto_types)
    created = 0

    purchase_rows = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM purchase_orders")))
    for row in purchase_rows:
        amount = _safe_float(row.get("total_amount")) or round(_safe_float(row.get("qty")) * _safe_float(row.get("unit_price")), 2)
        if amount <= 0:
            continue
        date_text = row.get("received_date") or row.get("expected_date") or ""
        vat = round(amount * 0.2 / 1.2, 2)
        base = round(amount - vat, 2)
        payload = {
            "source_type": "purchase_order",
            "source_id": row.get("id"),
            "entry_date": date_text,
            "period_key": _period_key(date_text),
            "legal_entity_id": row.get("legal_entity_id"),
            "business_unit_id": row.get("business_unit_id"),
            "project_id": row.get("project_id"),
            "client_id": row.get("client_id"),
            "contract_id": row.get("contract_id"),
            "object_id": row.get("object_id"),
            "currency": "RUB",
            "description": row.get("item_name") or "Закупка",
            "posted_by": actor.get("email", ""),
        }
        if not _ensure_open_period(conn, payload["entry_date"])[0]:
            continue
        _insert_accounting_entry(conn, {**payload, "account_debit": "10", "account_credit": "60.01", "amount": base, "vat_amount": 0})
        _insert_accounting_entry(conn, {**payload, "account_debit": "19.03", "account_credit": "60.01", "amount": vat, "vat_amount": vat})
        created += 2

    sales_rows = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM sales_documents_extended")))
    for row in sales_rows:
        amount = _safe_float(row.get("amount"))
        if amount <= 0:
            continue
        date_text = row.get("doc_date") or ""
        vat = round(amount * 0.2 / 1.2, 2)
        base = round(amount - vat, 2)
        payload = {
            "source_type": "sales_document",
            "source_id": row.get("id"),
            "entry_date": date_text,
            "period_key": _period_key(date_text),
            "legal_entity_id": row.get("legal_entity_id"),
            "business_unit_id": row.get("business_unit_id"),
            "project_id": row.get("project_id"),
            "client_id": row.get("client_id"),
            "contract_id": row.get("contract_id"),
            "object_id": row.get("object_id"),
            "currency": row.get("currency", "RUB"),
            "description": f"{row.get('doc_type', 'sale')} {row.get('doc_number', '')}".strip(),
            "posted_by": actor.get("email", ""),
        }
        if not _ensure_open_period(conn, payload["entry_date"])[0]:
            continue
        _insert_accounting_entry(conn, {**payload, "account_debit": "62.01", "account_credit": "90.01", "amount": base, "vat_amount": 0})
        _insert_accounting_entry(conn, {**payload, "account_debit": "90.03", "account_credit": "68.02", "amount": vat, "vat_amount": vat})
        created += 2

    production_rows = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM production_orders")))
    for row in production_rows:
        amount = _safe_float(row.get("actual_cost")) or _safe_float(row.get("planned_cost"))
        if amount <= 0:
            continue
        entry_date = row.get("actual_finish") or row.get("planned_finish") or ""
        if not _ensure_open_period(conn, entry_date)[0]:
            continue
        _insert_accounting_entry(conn, {"source_type": "production_order", "source_id": row.get("id"), "entry_date": entry_date, "period_key": _period_key(entry_date), "legal_entity_id": row.get("legal_entity_id"), "business_unit_id": row.get("business_unit_id"), "project_id": row.get("project_id"), "client_id": row.get("client_id"), "contract_id": row.get("contract_id"), "object_id": row.get("object_id"), "account_debit": "43", "account_credit": "20", "amount": amount, "currency": "RUB", "description": row.get("order_name") or "Выпуск продукции", "posted_by": actor.get("email", "")})
        created += 1

    manual_rows = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM accounting_manual_operations")))
    for row in manual_rows:
        entry_date = row.get("entry_date", "")
        if not _ensure_open_period(conn, entry_date)[0]:
            continue
        _insert_accounting_entry(conn, {"source_type": "manual_operation", "source_id": row.get("id"), "entry_date": entry_date, "period_key": row.get("period_key", _period_key(entry_date)), "legal_entity_id": row.get("legal_entity_id"), "business_unit_id": row.get("business_unit_id"), "project_id": row.get("project_id"), "client_id": row.get("client_id"), "account_debit": row.get("account_debit"), "account_credit": row.get("account_credit"), "amount": row.get("amount"), "vat_amount": row.get("vat_amount"), "description": row.get("description") or "Ручная операция", "posted_by": actor.get("email", "")})
        created += 1

    debt_rows = _row_dicts(conn.execute("SELECT * FROM accounting_debt_adjustments"))
    for row in debt_rows:
        entry_date = row.get("adjustment_date", "")
        if not _ensure_open_period(conn, entry_date)[0]:
            continue
        _insert_accounting_entry(conn, {"source_type": "debt_adjustment", "source_id": row.get("id"), "entry_date": entry_date, "period_key": _period_key(entry_date), "client_id": row.get("client_id"), "contract_id": row.get("contract_id"), "account_debit": row.get("account_debit") or "91.02", "account_credit": row.get("account_credit") or "62.01", "amount": row.get("amount"), "description": row.get("reason") or "Корректировка долга", "posted_by": actor.get("email", "")})
        created += 1

    cash_rows = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM cash_operations")))
    for row in cash_rows:
        direction = row.get("direction", "incoming")
        entry_date = row.get("operation_date", "")
        if not _ensure_open_period(conn, entry_date)[0]:
            continue
        _insert_accounting_entry(conn, {"source_type": "cash_operation", "source_id": row.get("id"), "entry_date": entry_date, "period_key": _period_key(entry_date), "legal_entity_id": row.get("legal_entity_id"), "business_unit_id": row.get("business_unit_id"), "project_id": row.get("project_id"), "account_debit": row.get("account_debit") or ("50" if direction == "incoming" else "71"), "account_credit": row.get("account_credit") or ("62.01" if direction == "incoming" else "50"), "amount": row.get("amount"), "currency": row.get("currency", "RUB"), "description": row.get("comment") or row.get("counterparty_name") or "Кассовая операция", "posted_by": actor.get("email", "")})
        created += 1

    bank_rows = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM bank_statement_lines")))
    for row in bank_rows:
        if _safe_int(row.get("linked_payment_id")):
            continue
        direction = row.get("direction", "incoming")
        entry_date = row.get("line_date", "")
        if not _ensure_open_period(conn, entry_date)[0]:
            continue
        _insert_accounting_entry(conn, {"source_type": "bank_statement", "source_id": row.get("id"), "entry_date": entry_date, "period_key": _period_key(entry_date), "client_id": row.get("client_id"), "account_debit": "51" if direction == "incoming" else "76", "account_credit": "76" if direction == "incoming" else "51", "amount": row.get("amount"), "description": row.get("purpose") or row.get("counterparty") or "Банковская выписка", "posted_by": actor.get("email", "")})
        created += 1
    touched_periods = {
        row.get("period_key")
        for row in _row_dicts(
            conn.execute(
                f"SELECT DISTINCT period_key FROM accounting_entries WHERE source_type IN ({', '.join(['?'] * len(auto_types))})",
                auto_types,
            )
        )
        if row.get("period_key")
    }
    for period_key in touched_periods:
        rebuild_registers_for_period(conn, period_key, actor.get("email", ""))
    return {"created": created}


def _balance_from_entries(conn, actor: dict) -> dict:
    entries = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM accounting_entries ORDER BY id DESC")))
    chart = {row["code"]: row for row in _row_dicts(conn.execute("SELECT * FROM account_chart"))}
    balances = {}
    for row in entries:
        debit = row.get("account_debit", "")
        credit = row.get("account_credit", "")
        amount = _safe_float(row.get("amount"))
        balances[debit] = balances.get(debit, 0.0) + amount
        balances[credit] = balances.get(credit, 0.0) - amount
    assets = liabilities = 0.0
    for code, balance in balances.items():
        account_type = (chart.get(code) or {}).get("account_type", "active")
        if account_type == "active":
            assets += max(balance, 0.0)
        elif account_type == "passive":
            liabilities += abs(min(balance, 0.0))
        else:
            if balance >= 0:
                assets += balance
            else:
                liabilities += abs(balance)
    return {
        "assets": round(assets, 2),
        "liabilities": round(liabilities, 2),
        "equity": round(assets - liabilities, 2),
        "balances": [{"account_code": code, "balance": round(value, 2), "account_name": (chart.get(code) or {}).get("name", "")} for code, value in sorted(balances.items()) if code],
    }


def _account_chart_view(accounts: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for item in accounts:
        code = str(item.get("code") or "")
        group_code = code.split(".")[0] if code else "other"
        groups.setdefault(group_code, []).append(item)
    chart_groups = []
    for group_code, rows in sorted(groups.items(), key=lambda pair: pair[0]):
        chart_groups.append(
            {
                "group_code": group_code,
                "title": rows[0].get("parent_code") or group_code,
                "accounts": rows,
                "active_accounts": len([row for row in rows if int(row.get("is_active", 1)) == 1]),
            }
        )
    return {"groups": chart_groups, "total": len(accounts)}


def _posting_templates(conn) -> list[dict]:
    return _row_dicts(conn.execute("SELECT * FROM accounting_posting_templates WHERE is_active=1 ORDER BY priority, source_type, id"))


def _name_maps(conn) -> tuple[dict, dict]:
    clients = {int(row["id"]): row.get("name", "") for row in _row_dicts(conn.execute("SELECT id, name FROM clients"))}
    contracts = {}
    try:
        contracts = {int(row["id"]): row.get("title") or row.get("contract_number") or f"Договор {row['id']}" for row in _row_dicts(conn.execute("SELECT id, title, contract_number FROM contract_master"))}
    except Exception:
        contracts = {}
    return clients, contracts


def _settlement_aging(rows: list[dict], key_name: str, label_name: str) -> list[dict]:
    now = datetime.now()
    output = []
    for item in rows:
        due_dt = _parse_date(item.get("due_date", ""))
        days = (now - due_dt).days if due_dt else 0
        bucket = "future"
        if days > 60:
            bucket = "60+"
        elif days > 30:
            bucket = "31-60"
        elif days > 0:
            bucket = "1-30"
        output.append(
            {
                key_name: item.get(key_name),
                label_name: item.get(label_name) or f"{key_name} {item.get(key_name)}",
                "balance": round(_safe_float(item.get("balance")), 2),
                "days_overdue": max(days, 0),
                "aging_bucket": bucket,
            }
        )
    output.sort(key=lambda row: (row.get("days_overdue", 0), abs(row.get("balance", 0))), reverse=True)
    return output


def _balance_sheet_lines(balance: dict) -> list[dict]:
    balances = {row.get("account_code"): _safe_float(row.get("balance")) for row in balance.get("balances", [])}
    receivables = round(sum(value for code, value in balances.items() if str(code).startswith("62")), 2)
    payables = round(abs(sum(value for code, value in balances.items() if str(code).startswith("60"))), 2)
    inventory = round(sum(value for code, value in balances.items() if str(code).startswith(("10", "41", "43")) and value > 0), 2)
    vat_asset = round(sum(value for code, value in balances.items() if str(code).startswith("19") and value > 0), 2)
    tax_due = round(abs(sum(value for code, value in balances.items() if str(code).startswith("68.02") and value < 0)), 2)
    cash = round(sum(value for code, value in balances.items() if str(code).startswith(("50", "51", "52", "55", "57")) and value > 0), 2)
    return [
        {"line_name": "Денежные средства", "section": "assets", "value": cash},
        {"line_name": "Запасы", "section": "assets", "value": inventory},
        {"line_name": "Дебиторская задолженность", "section": "assets", "value": receivables},
        {"line_name": "НДС к вычету", "section": "assets", "value": vat_asset},
        {"line_name": "Кредиторская задолженность", "section": "liabilities", "value": payables},
        {"line_name": "НДС к уплате", "section": "liabilities", "value": tax_due},
        {"line_name": "Собственный капитал", "section": "equity", "value": _safe_float(balance.get("equity"))},
    ]


def _route_match(route: dict, legal_entity_id: int, business_unit_id: int, amount: float, currency: str) -> bool:
    if _safe_int(route.get("legal_entity_id")) not in {0, legal_entity_id}:
        return False
    if _safe_int(route.get("business_unit_id")) not in {0, business_unit_id}:
        return False
    if (route.get("currency") or "RUB") not in {"", currency, "RUB" if not currency else currency}:
        return False
    return _safe_float(route.get("min_amount")) <= amount <= (_safe_float(route.get("max_amount")) or amount)


def _serialize_route(route: dict) -> dict:
    item = dict(route)
    item["stages"] = _json_load(item.get("stages_json"), [])
    return item


def _load_accounting_deep(actor: dict) -> dict:
    conn = get_connection(row_factory=True)
    try:
        rebuild_result = _rebuild_auto_accounting(conn, actor)
        conn.commit()
        entries = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM accounting_entries ORDER BY created_at DESC, id DESC LIMIT 300")))
        accounts = _row_dicts(conn.execute("SELECT * FROM account_chart ORDER BY code"))
        posting_templates = _posting_templates(conn)
        manual_operations = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM accounting_manual_operations ORDER BY updated_at DESC, id DESC")))
        debt_adjustments = _row_dicts(conn.execute("SELECT * FROM accounting_debt_adjustments ORDER BY updated_at DESC, id DESC"))
        cash_operations = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM cash_operations ORDER BY operation_date DESC, id DESC")))
        bank_accounts = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM bank_accounts ORDER BY created_at DESC, id DESC")))
        bank_statements = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM bank_statement_lines ORDER BY line_date DESC, id DESC LIMIT 200")))
        bank_payment_orders = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM bank_payment_orders ORDER BY updated_at DESC, id DESC LIMIT 120")))
        exchange_batches = _row_dicts(conn.execute("SELECT * FROM bank_exchange_batches ORDER BY created_at DESC, id DESC LIMIT 60"))
        edo_operators = _load_external_operator_rows(conn, actor)
        external_submissions = _load_external_submission_rows(conn, actor, limit=160)
        external_events = _load_external_event_rows(conn, actor, limit=80)
        edo_certificates = _row_dicts(conn.execute("SELECT * FROM edo_certificates ORDER BY updated_at DESC, id DESC LIMIT 120"))
        edo_signatures = _row_dicts(conn.execute("SELECT * FROM edo_signature_registry ORDER BY created_at DESC, id DESC LIMIT 240"))
        payments = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM finance_payments ORDER BY COALESCE(paid_date, due_date) DESC, id DESC")))
        obligations = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM finance_obligations ORDER BY due_date DESC, id DESC")))
        vat_rates = {int(row["id"]): dict(row) for row in _row_dicts(conn.execute("SELECT * FROM vat_rates ORDER BY rate, id"))}
        balance = _balance_from_entries(conn, actor)
        clients_map, contracts_map = _name_maps(conn)

        purchase_book = [row for row in entries if row.get("source_type") == "purchase_order" and _safe_float(row.get("vat_amount")) > 0]
        sales_book = [row for row in entries if row.get("source_type") == "sales_document" and _safe_float(row.get("vat_amount")) > 0]
        vat_input = round(sum(_safe_float(row.get("vat_amount")) for row in purchase_book), 2)
        vat_output = round(sum(_safe_float(row.get("vat_amount")) for row in sales_book), 2)
        by_vat_rate: dict[int, dict] = {}
        for row in entries:
            rate_id = _safe_int(row.get("vat_rate_id"))
            if not rate_id or _safe_float(row.get("vat_amount")) <= 0:
                continue
            bucket = by_vat_rate.setdefault(rate_id, {"vat_rate_id": rate_id, "rate_name": (vat_rates.get(rate_id) or {}).get("name", f"Ставка {rate_id}"), "rate": _safe_float((vat_rates.get(rate_id) or {}).get("rate")), "input": 0.0, "output": 0.0})
            if row.get("source_type") == "purchase_order":
                bucket["input"] += _safe_float(row.get("vat_amount"))
            elif row.get("source_type") == "sales_document":
                bucket["output"] += _safe_float(row.get("vat_amount"))

        by_client: dict[int, dict] = {}
        by_contract: dict[int, dict] = {}
        for row in payments:
            if row.get("status") == "paid":
                continue
            amount = _safe_float(row.get("amount"))
            client_id = _safe_int(row.get("client_id"))
            contract_id = _safe_int(row.get("contract_id"))
            sign = 1 if row.get("kind") == "incoming" else -1
            if client_id:
                bucket = by_client.setdefault(client_id, {"client_id": client_id, "client_name": clients_map.get(client_id) or f"Контрагент {client_id}", "balance": 0.0, "due_date": row.get("due_date", "")})
                bucket["balance"] += sign * amount
            if contract_id:
                bucket = by_contract.setdefault(contract_id, {"contract_id": contract_id, "contract_name": contracts_map.get(contract_id) or f"Договор {contract_id}", "balance": 0.0, "due_date": row.get("due_date", "")})
                bucket["balance"] += sign * amount
        for row in obligations:
            contract_id = _safe_int(row.get("contract_id"))
            client_id = _safe_int(row.get("client_id"))
            amount = _safe_float(row.get("amount"))
            if client_id:
                bucket = by_client.setdefault(client_id, {"client_id": client_id, "client_name": clients_map.get(client_id) or f"Контрагент {client_id}", "balance": 0.0, "due_date": row.get("due_date", "")})
                bucket["balance"] -= amount
            if contract_id:
                bucket = by_contract.setdefault(contract_id, {"contract_id": contract_id, "contract_name": contracts_map.get(contract_id) or f"Договор {contract_id}", "balance": 0.0, "due_date": row.get("due_date", "")})
                bucket["balance"] -= amount
        advances = {
            "issued": round(sum(_safe_float(row.get("amount")) for row in entries if str(row.get("account_debit") or "").startswith("60.02")), 2),
            "received": round(sum(_safe_float(row.get("amount")) for row in entries if str(row.get("account_credit") or "").startswith("62.02")), 2),
        }
        vat_by_rate = []
        for item in by_vat_rate.values():
            item["net"] = round(item["output"] - item["input"], 2)
            vat_by_rate.append(item)
        vat_by_rate.sort(key=lambda row: row.get("rate", 0))
        settlement_counterparties = _settlement_aging(list(by_client.values()), "client_id", "client_name")
        settlement_contracts = _settlement_aging(list(by_contract.values()), "contract_id", "contract_name")
        balance_sheet_lines = _balance_sheet_lines(balance)
        close_cycle = load_accounting_close_workspace(
            conn,
            actor=actor,
            period_key=_period_key(""),
            filter_rows_by_scope_fn=filter_rows_by_scope,
        )
        signatures_valid = len([row for row in edo_signatures if _safe_text(row.get("verification_status")) == "valid"])
        signatures_invalid = len([row for row in edo_signatures if _safe_text(row.get("verification_status")) in {"invalid", "revoked", "expired"}])
        expiring_threshold = datetime.now().timestamp() + 30 * 24 * 3600
        certificates_expiring_soon = len(
            [
                row
                for row in edo_certificates
                if _safe_text(row.get("status")) == "active"
                and (_parse_date(row.get("valid_to")) is not None)
                and _parse_date(row.get("valid_to")).timestamp() <= expiring_threshold
            ]
        )
        external_metrics = {
            "operators_total": len(edo_operators),
            "operators_active": len([row for row in edo_operators if _safe_text(row.get("status")) == "active"]),
            "submissions_total": len(external_submissions),
            "submissions_waiting": len([row for row in external_submissions if _safe_text(row.get("submission_status")) in {"queued", "sent", "retry"}]),
            "submissions_failed": len([row for row in external_submissions if _safe_text(row.get("submission_status")) in {"failed", "rejected"}]),
            "submissions_accepted": len([row for row in external_submissions if _safe_text(row.get("submission_status")) == "accepted"]),
            "tax_reports_submitted": len([row for row in external_submissions if _safe_text(row.get("contour_type")) == "tax" and _safe_text(row.get("submission_status")) in {"sent", "accepted"}]),
            "verified_signatures": signatures_valid,
            "invalid_signatures": signatures_invalid,
            "certificates_expiring": certificates_expiring_soon,
        }
        balance["current_ratio"] = round((balance.get("assets", 0) / balance.get("liabilities", 1)) if balance.get("liabilities") else balance.get("assets", 0), 2)
        balance["debt_load"] = round(((next((line["value"] for line in balance_sheet_lines if line["line_name"] == "Кредиторская задолженность"), 0) + next((line["value"] for line in balance_sheet_lines if line["line_name"] == "НДС к уплате"), 0)) / (balance.get("assets", 1) or 1)), 2)
        return {
            "accounts": accounts,
            "account_chart_view": _account_chart_view(accounts),
            "posting_templates": posting_templates,
            "entries": entries,
            "manual_operations": manual_operations,
            "debt_adjustments": debt_adjustments,
            "cash_operations": cash_operations,
            "bank_accounts": bank_accounts,
            "bank_statements": bank_statements,
            "bank_payment_orders": bank_payment_orders,
            "exchange_batches": exchange_batches,
            "purchase_book": purchase_book[:80],
            "sales_book": sales_book[:80],
            "vat_summary": {"input": vat_input, "output": vat_output, "net": round(vat_output - vat_input, 2)},
            "vat_by_rate": vat_by_rate,
            "tax_registers": [
                {"register_name": "НДС входящий", "value": vat_input},
                {"register_name": "НДС исходящий", "value": vat_output},
                {"register_name": "НДС к уплате", "value": round(max(vat_output - vat_input, 0), 2)},
                {"register_name": "НДС к возмещению", "value": round(max(vat_input - vat_output, 0), 2)},
            ],
            "counterparty_settlements": settlement_counterparties,
            "contract_settlements": settlement_contracts,
            "advances": advances,
            "management_balance": balance,
            "balance_sheet_lines": balance_sheet_lines,
            "close_cycle": close_cycle,
            "edo_operators": edo_operators[:40],
            "external_submissions": external_submissions[:80],
            "external_events": external_events[:60],
            "edo_exchange_health": {
                "verified_signatures": signatures_valid,
                "invalid_signatures": signatures_invalid,
                "certificates_expiring": certificates_expiring_soon,
            },
            "external_reporting_metrics": external_metrics,
            "metrics": {
                "accounts_total": len(accounts),
                "entries_total": len(entries),
                "manual_operations": len(manual_operations),
                "cash_operations": len(cash_operations),
                "vat_net": round(vat_output - vat_input, 2),
                "auto_generated_entries": rebuild_result.get("created", 0),
                "posting_templates": len(posting_templates),
                "bank_orders": len(bank_payment_orders),
                "close_runs": len(close_cycle.get("close_runs", [])),
                "tax_accruals": len(close_cycle.get("tax_accruals", [])),
                "external_submissions": external_metrics["submissions_total"],
                "external_failures": external_metrics["submissions_failed"],
                "edo_operators": external_metrics["operators_total"],
            },
        }
    finally:
        conn.close()


@router.get("/api/accounting/deep_summary")
def get_accounting_deep_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_accounting_deep(actor)


@router.post("/api/accounting/rebuild_auto")
def rebuild_accounting_auto(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "post"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        result = _rebuild_auto_accounting(conn, actor)
        conn.commit()
    finally:
        conn.close()
    audit_log("accounting_auto_rebuilt", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="accounting_entries", entity_id="auto", details=result)
    return {"status": "success", **result}


@router.get("/api/accounting/registers/summary")
def get_accounting_registers_summary(request: Request, period_key: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    period_key = (period_key or "").strip() or _period_key("")
    conn = get_connection(row_factory=True)
    try:
        summary = period_register_summary(conn, period_key)
        registers = _row_dicts(conn.execute("SELECT * FROM accounting_registers WHERE period_key=? ORDER BY id DESC LIMIT 80", (period_key,)))
        tax = _row_dicts(conn.execute("SELECT * FROM tax_registers WHERE period_key=? ORDER BY id DESC LIMIT 80", (period_key,)))
        vat_purchase = _row_dicts(conn.execute("SELECT * FROM vat_purchase_book WHERE period_key=? ORDER BY id DESC LIMIT 80", (period_key,)))
        vat_sales = _row_dicts(conn.execute("SELECT * FROM vat_sales_book WHERE period_key=? ORDER BY id DESC LIMIT 80", (period_key,)))
        revaluation = _row_dicts(conn.execute("SELECT * FROM currency_revaluation_runs WHERE period_key=? ORDER BY id DESC LIMIT 40", (period_key,)))
        assets = _row_dicts(conn.execute("SELECT * FROM fixed_assets ORDER BY updated_at DESC, id DESC LIMIT 80"))
    finally:
        conn.close()
    return {
        "status": "success",
        "summary": summary,
        "accounting_registers": registers,
        "tax_registers": tax,
        "vat_purchase_book": vat_purchase,
        "vat_sales_book": vat_sales,
        "currency_revaluation_runs": revaluation,
        "fixed_assets": assets,
    }


@router.post("/api/accounting/registers/rebuild")
def rebuild_accounting_registers(request: Request, period_key: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "post"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        if (period_key or "").strip():
            result = rebuild_registers_for_period(conn, period_key.strip(), actor.get("email", ""))
        else:
            result = rebuild_all_registers(conn, actor.get("email", ""))
        conn.commit()
    finally:
        conn.close()
    audit_log("accounting_registers_rebuilt", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="accounting_registers", entity_id=period_key or "all", details=result)
    return {"status": "success", **result}


@router.post("/api/accounting/periods/close_cycle")
def close_accounting_period_cycle(data: FinancePeriodCloseData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "close_period"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        result = run_accounting_close_cycle(
            conn,
            actor=actor,
            period_key=(data.period_key or "").strip() or _period_key(""),
            comment=data.comment or "",
            rebuild_auto_fn=_rebuild_auto_accounting,
        )
        conn.commit()
    finally:
        conn.close()
    audit_log(
        "accounting_period_close_cycle",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="accounting_period",
        entity_id=result.get("period_key", ""),
        details={
            "close_run_id": result.get("close_run_id", 0),
            "already_closed": bool(result.get("already_closed")),
            "warnings": result.get("warnings", []),
        },
    )
    return result


@router.get("/api/accounting/edo_operators")
def get_accounting_edo_operators(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        return _load_external_operator_rows(conn, actor)
    finally:
        conn.close()


@router.post("/api/accounting/edo_operators")
def create_accounting_edo_operator(data: AccountingEDOOperatorData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    if (data.legal_entity_id or data.business_unit_id) and not can_access_scope(actor, data.legal_entity_id, data.business_unit_id):
        return {"error": "forbidden_scope"}
    now = _now_ts()
    conn = get_connection(row_factory=True)
    try:
        operator_id = next_safe_table_id(conn, "accounting_edo_operators")
        namespace = _safe_text(data.idempotency_namespace) or f"{_safe_text(data.provider_name or 'operator').lower()}:{operator_id}"
        conn.execute(
            """
            INSERT INTO accounting_edo_operators (
                id, operator_name, provider_name, contour_type, api_endpoint, account_login, credential_ref,
                legal_entity_id, business_unit_id, status, capabilities_json, retry_policy_json,
                idempotency_namespace, last_sync_at, last_error, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?, ?)
            """,
            (
                operator_id,
                _safe_text(data.operator_name) or f"Оператор {operator_id}",
                _safe_text(data.provider_name) or "1С-ЭДО",
                _safe_text(data.contour_type) or "reporting",
                _safe_text(data.api_endpoint),
                _safe_text(data.account_login),
                _safe_text(data.credential_ref),
                _safe_int(data.legal_entity_id),
                _safe_int(data.business_unit_id),
                _safe_text(data.status) or "active",
                json.dumps(data.capabilities or [], ensure_ascii=False),
                json.dumps(data.retry_policy or {}, ensure_ascii=False),
                namespace,
                actor.get("email", ""),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("accounting_edo_operator_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="accounting_edo_operator", entity_id=str(operator_id), details={"provider_name": data.provider_name, "contour_type": data.contour_type})
    return {"status": "success", "id": operator_id, "idempotency_namespace": namespace}


@router.get("/api/accounting/external_reporting/submissions")
def get_accounting_external_submissions(request: Request, limit: int = 120):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        return _load_external_submission_rows(conn, actor, limit=limit)
    finally:
        conn.close()


@router.post("/api/accounting/external_reporting/submissions")
def create_accounting_external_submission(data: AccountingExternalReportData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "export"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        operator = dict(conn.execute("SELECT * FROM accounting_edo_operators WHERE id=?", (_safe_int(data.operator_id),)).fetchone() or {})
        if not operator:
            return {"error": "operator_not_found"}
        operator = _operator_payload(operator)
        legal_entity_id = _safe_int(data.legal_entity_id) or _safe_int(operator.get("legal_entity_id"))
        business_unit_id = _safe_int(data.business_unit_id) or _safe_int(operator.get("business_unit_id"))
        if (legal_entity_id or business_unit_id) and not can_access_scope(actor, legal_entity_id, business_unit_id):
            return {"error": "forbidden_scope"}
        period_key = _safe_text(data.period_key) or _period_key("")
        report_type = _safe_text(data.report_type) or "regulated_report"
        payload = data.payload or _report_payload_from_snapshot(conn, report_type, period_key)
        payload = payload or {"report_type": report_type, "period_key": period_key, "generated_from": "manual_submission"}
        checksum = _payload_checksum(payload)
        namespace = _safe_text(operator.get("idempotency_namespace")) or f"{_safe_text(operator.get('provider_name')).lower()}:{_safe_int(operator.get('id'))}"
        idempotency_key = _safe_text(data.idempotency_key) or f"{namespace}:{report_type}:{period_key}:{legal_entity_id}:{checksum[:16]}"
        existing = dict(conn.execute("SELECT * FROM accounting_external_submissions WHERE idempotency_key=? ORDER BY updated_at DESC, id DESC LIMIT 1", (idempotency_key,)).fetchone() or {})
        if existing and not int(data.force_resend or 0):
            return {"status": "success", "id": _safe_int(existing.get("id")), "deduplicated": 1, "submission": _submission_payload(existing)}
        now = _now_ts()
        submission_id = next_safe_table_id(conn, "accounting_external_submissions")
        operator_active = _safe_text(operator.get("status")) == "active"
        submission_status = "sent" if operator_active else "failed"
        external_submission_id = f"{_safe_text(operator.get('provider_name') or 'EXT').upper()}-{submission_id}" if operator_active else ""
        last_error = "" if operator_active else "operator_inactive"
        retry_policy = _external_retry_policy(operator)
        next_retry_at = 0 if operator_active else now + retry_policy["delay_minutes"] * 60
        conn.execute(
            """
            INSERT INTO accounting_external_submissions (
                id, operator_id, contour_type, report_type, period_key, legal_entity_id, business_unit_id,
                entity_type, entity_id, payload_json, checksum, idempotency_key, submission_status,
                exchange_direction, external_submission_id, protocol_number, receipt_number, retry_count,
                next_retry_at, submitted_at, accepted_at, last_error, response_json, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'outbound', ?, '', '', 0, ?, ?, 0, ?, '{}', ?, ?, ?, ?)
            """,
            (
                submission_id,
                _safe_int(operator.get("id")),
                _safe_text(data.contour_type) or _safe_text(operator.get("contour_type")) or "reporting",
                report_type,
                period_key,
                legal_entity_id,
                business_unit_id,
                _safe_text(data.entity_type),
                _safe_int(data.entity_id),
                json.dumps(payload, ensure_ascii=False),
                checksum,
                idempotency_key,
                submission_status,
                external_submission_id,
                next_retry_at,
                now if operator_active else 0,
                last_error,
                _safe_text(data.comment),
                actor.get("email", ""),
                now,
                now,
            ),
        )
        _log_external_submission_event(conn, submission_id, "submit", submission_status, "Отправка регламентированной отчетности во внешний контур", actor.get("email", ""), {"report_type": report_type, "period_key": period_key, "operator_id": operator.get("id")})
        conn.execute(
            "UPDATE accounting_edo_operators SET last_sync_at=?, last_error=?, updated_at=? WHERE id=?",
            (now if operator_active else _safe_int(operator.get("last_sync_at")), last_error, now, _safe_int(operator.get("id"))),
        )
        conn.commit()
        created = dict(conn.execute("SELECT * FROM accounting_external_submissions WHERE id=?", (submission_id,)).fetchone() or {})
    finally:
        conn.close()
    audit_log("accounting_external_submission_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="accounting_external_submission", entity_id=str(submission_id), details={"report_type": report_type, "period_key": period_key, "submission_status": submission_status})
    return {"status": "success", "id": submission_id, "submission": _submission_payload(created), "deduplicated": 0}


@router.post("/api/accounting/external_reporting/submissions/{submission_id}/retry")
def retry_accounting_external_submission(submission_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "export"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        submission = dict(conn.execute("SELECT * FROM accounting_external_submissions WHERE id=?", (_safe_int(submission_id),)).fetchone() or {})
        if not submission:
            return {"error": "not_found"}
        if (_safe_int(submission.get("legal_entity_id")) or _safe_int(submission.get("business_unit_id"))) and not can_access_scope(actor, _safe_int(submission.get("legal_entity_id")), _safe_int(submission.get("business_unit_id"))):
            return {"error": "forbidden_scope"}
        operator = dict(conn.execute("SELECT * FROM accounting_edo_operators WHERE id=?", (_safe_int(submission.get("operator_id")),)).fetchone() or {})
        if not operator:
            return {"error": "operator_not_found"}
        operator = _operator_payload(operator)
        retry_policy = _external_retry_policy(operator)
        retry_count = _safe_int(submission.get("retry_count")) + 1
        if retry_policy["max_retries"] and retry_count > retry_policy["max_retries"]:
            return {"error": "retry_limit_exceeded"}
        now = _now_ts()
        operator_active = _safe_text(operator.get("status")) == "active"
        submission_status = "sent" if operator_active else "failed"
        next_retry_at = 0 if operator_active else now + retry_policy["delay_minutes"] * 60
        last_error = "" if operator_active else "operator_inactive"
        external_submission_id = _safe_text(submission.get("external_submission_id")) or f"{_safe_text(operator.get('provider_name') or 'EXT').upper()}-{submission_id}"
        conn.execute(
            """
            UPDATE accounting_external_submissions
            SET submission_status=?, retry_count=?, next_retry_at=?, submitted_at=?, last_error=?, external_submission_id=?, updated_at=?
            WHERE id=?
            """,
            (submission_status, retry_count, next_retry_at, now if operator_active else _safe_int(submission.get("submitted_at")), last_error, external_submission_id, now, _safe_int(submission_id)),
        )
        _log_external_submission_event(conn, submission_id, "retry", submission_status, "Повторная отправка во внешний контур", actor.get("email", ""), {"retry_count": retry_count})
        conn.execute(
            "UPDATE accounting_edo_operators SET last_sync_at=?, last_error=?, updated_at=? WHERE id=?",
            (now if operator_active else _safe_int(operator.get("last_sync_at")), last_error, now, _safe_int(operator.get("id"))),
        )
        conn.commit()
        refreshed = dict(conn.execute("SELECT * FROM accounting_external_submissions WHERE id=?", (_safe_int(submission_id),)).fetchone() or {})
    finally:
        conn.close()
    audit_log("accounting_external_submission_retried", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="accounting_external_submission", entity_id=str(submission_id), details={"retry_count": retry_count, "submission_status": submission_status})
    return {"status": "success", "submission": _submission_payload(refreshed)}


@router.post("/api/accounting/external_reporting/submissions/{submission_id}/sync_status")
def sync_accounting_external_submission_status(submission_id: int, data: AccountingExternalStatusSyncData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        submission = dict(conn.execute("SELECT * FROM accounting_external_submissions WHERE id=?", (_safe_int(submission_id),)).fetchone() or {})
        if not submission:
            return {"error": "not_found"}
        if (_safe_int(submission.get("legal_entity_id")) or _safe_int(submission.get("business_unit_id"))) and not can_access_scope(actor, _safe_int(submission.get("legal_entity_id")), _safe_int(submission.get("business_unit_id"))):
            return {"error": "forbidden_scope"}
        operator = dict(conn.execute("SELECT * FROM accounting_edo_operators WHERE id=?", (_safe_int(submission.get("operator_id")),)).fetchone() or {})
        now = _now_ts()
        submission_status = _safe_text(data.submission_status) or _safe_text(submission.get("submission_status")) or "sent"
        external_submission_id = _safe_text(data.external_submission_id) or _safe_text(submission.get("external_submission_id"))
        protocol_number = _safe_text(data.protocol_number) or _safe_text(submission.get("protocol_number"))
        receipt_number = _safe_text(data.receipt_number) or _safe_text(submission.get("receipt_number"))
        message = _safe_text(data.message)
        response_payload = data.response_payload or _json_load(submission.get("response_json"), {})
        response_payload = {**response_payload, **(data.response_payload or {})}
        accepted_at = now if submission_status == "accepted" else _safe_int(submission.get("accepted_at"))
        last_error = message if submission_status in {"failed", "rejected"} else ""
        conn.execute(
            """
            UPDATE accounting_external_submissions
            SET submission_status=?, external_submission_id=?, protocol_number=?, receipt_number=?,
                accepted_at=?, last_error=?, response_json=?, updated_at=?
            WHERE id=?
            """,
            (
                submission_status,
                external_submission_id,
                protocol_number,
                receipt_number,
                accepted_at,
                last_error,
                json.dumps(response_payload, ensure_ascii=False),
                now,
                _safe_int(submission_id),
            ),
        )
        _log_external_submission_event(conn, submission_id, "status_sync", submission_status, message or "Синхронизация статуса внешнего контура", actor.get("email", ""), response_payload)
        if operator:
            conn.execute(
                "UPDATE accounting_edo_operators SET last_sync_at=?, last_error=?, updated_at=? WHERE id=?",
                (now, last_error, now, _safe_int(operator.get("id"))),
            )
        conn.commit()
        refreshed = dict(conn.execute("SELECT * FROM accounting_external_submissions WHERE id=?", (_safe_int(submission_id),)).fetchone() or {})
    finally:
        conn.close()
    audit_log("accounting_external_submission_synced", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="accounting_external_submission", entity_id=str(submission_id), details={"submission_status": submission_status, "protocol_number": protocol_number, "receipt_number": receipt_number})
    return {"status": "success", "submission": _submission_payload(refreshed)}


@router.get("/api/accounting/accounts")
def get_accounting_accounts(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _fetch_rows("SELECT * FROM account_chart ORDER BY code")


@router.get("/api/finance/treasury_routes")
def get_treasury_routes(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_finance_deep(actor).get("treasury_routes", [])


@router.post("/api/finance/treasury_routes")
def create_treasury_route(data: TreasuryApprovalRouteData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "manage_limits"):
        return {"error": "forbidden"}
    if not can_access_scope(actor, data.legal_entity_id, data.business_unit_id):
        return {"error": "forbidden_scope"}
    stages = [stage for stage in data.stages if str(stage.get("role") or "").strip()]
    if not stages:
        return {"error": "stages_required"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.execute(
            """
            INSERT INTO treasury_approval_routes (
                route_name, legal_entity_id, business_unit_id, min_amount, max_amount, currency, stages_json,
                is_default, is_active, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.route_name or "Маршрут казначейства",
                _safe_int(data.legal_entity_id),
                _safe_int(data.business_unit_id),
                _safe_float(data.min_amount),
                _safe_float(data.max_amount),
                data.currency or "RUB",
                json.dumps(stages, ensure_ascii=False),
                int(data.is_default or 0),
                int(data.is_active or 1),
                data.comment or "",
                actor.get("email", ""),
                _now_ts(),
                _now_ts(),
            ),
        )
        route_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("treasury_route_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="treasury_approval_route", entity_id=str(route_id), details={"route_name": data.route_name})
    return {"status": "success", "id": route_id}


@router.delete("/api/finance/treasury_routes/{route_id}")
def delete_treasury_route(route_id: int, request: Request):
    return _delete_row_with_scope(
        request,
        "finance",
        "delete",
        "treasury_approval_routes",
        route_id,
        "treasury_approval_route",
        lambda conn, rid: dict(conn.execute("SELECT id, legal_entity_id, business_unit_id FROM treasury_approval_routes WHERE id=?", (_safe_int(rid),)).fetchone() or {}),
    )


@router.get("/api/banking/payment_orders")
def get_bank_payment_orders(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_accounting_deep(actor).get("bank_payment_orders", [])


@router.post("/api/banking/payment_orders")
def create_bank_payment_order(data: BankPaymentOrderData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    if not can_access_scope(actor, data.legal_entity_id, data.business_unit_id):
        return {"error": "forbidden_scope"}
    conn = get_connection(row_factory=True)
    try:
        payment = dict(conn.execute("SELECT * FROM finance_payments WHERE id=?", (_safe_int(data.payment_id),)).fetchone() or {})
        if not payment:
            return {"error": "payment_not_found"}
        cursor = conn.execute(
            """
            INSERT INTO bank_payment_orders (
                payment_id, bank_account_id, legal_entity_id, business_unit_id, order_date, amount, currency, counterparty,
                purpose, status, external_payment_id, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _safe_int(data.payment_id),
                _safe_int(data.bank_account_id),
                _safe_int(data.legal_entity_id),
                _safe_int(data.business_unit_id),
                data.order_date or datetime.now().strftime("%d.%m.%Y"),
                round(_safe_float(data.amount) or _safe_float(payment.get("amount")), 2),
                data.currency or payment.get("currency", "RUB") or "RUB",
                data.counterparty or payment.get("client_name") or payment.get("title") or "",
                data.purpose or payment.get("comment") or payment.get("title") or "Платежное поручение",
                data.status or "draft",
                data.external_payment_id or "",
                data.comment or "",
                actor.get("email", ""),
                _now_ts(),
                _now_ts(),
            ),
        )
        order_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("bank_payment_order_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="bank_payment_order", entity_id=str(order_id), details={"payment_id": data.payment_id})
    return {"status": "success", "id": order_id}


@router.post("/api/banking/exchange_batches/export")
def export_bank_exchange_batch(data: BankExchangeBatchData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "export"):
        return {"error": "forbidden"}
    order_ids = [_safe_int(item) for item in data.payment_order_ids if _safe_int(item)]
    if not order_ids:
        return {"error": "orders_required"}
    conn = get_connection(row_factory=True)
    try:
        placeholders = ", ".join(["?"] * len(order_ids))
        orders = _scope_rows(actor, _row_dicts(conn.execute(f"SELECT * FROM bank_payment_orders WHERE id IN ({placeholders}) ORDER BY id", tuple(order_ids))))
        if not orders:
            return {"error": "orders_not_found"}
        payload_items = [
            {
                "payment_order_id": int(item["id"]),
                "payment_id": _safe_int(item.get("payment_id")),
                "order_date": item.get("order_date", ""),
                "amount": round(_safe_float(item.get("amount")), 2),
                "currency": item.get("currency", "RUB"),
                "counterparty": item.get("counterparty", ""),
                "purpose": item.get("purpose", ""),
            }
            for item in orders
        ]
        total_amount = round(sum(item["amount"] for item in payload_items), 2)
        cursor = conn.execute(
            """
            INSERT INTO bank_exchange_batches (
                provider_name, direction, batch_type, bank_account_id, status, payload_json, total_amount,
                item_count, comment, created_by, created_at, updated_at
            ) VALUES (?, 'outbound', ?, ?, 'exported', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.provider_name or "bank_api",
                data.batch_type or "payment_exchange",
                _safe_int(data.bank_account_id),
                json.dumps({"items": payload_items}, ensure_ascii=False),
                total_amount,
                len(payload_items),
                data.comment or "",
                actor.get("email", ""),
                _now_ts(),
                _now_ts(),
            ),
        )
        batch_id = cursor.lastrowid
        conn.executemany(
            "UPDATE bank_payment_orders SET status='exported', exchange_batch_id=?, updated_at=? WHERE id=?",
            [(batch_id, _now_ts(), int(item["payment_order_id"])) for item in payload_items],
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("bank_exchange_exported", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="bank_exchange_batch", entity_id=str(batch_id), details={"count": len(order_ids)})
    return {"status": "success", "id": batch_id, "payload": {"items": payload_items}, "total_amount": total_amount}


@router.post("/api/banking/exchange_batches/import_result")
def import_bank_exchange_result(data: BankExchangeBatchData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "reconcile"):
        return {"error": "forbidden"}
    result_items = [item for item in data.result_items if _safe_int(item.get("payment_order_id"))]
    if not result_items:
        return {"error": "result_items_required"}
    conn = get_connection(row_factory=True)
    try:
        applied = []
        for item in result_items:
            order_id = _safe_int(item.get("payment_order_id"))
            status = str(item.get("status") or "imported")
            order = dict(conn.execute("SELECT * FROM bank_payment_orders WHERE id=?", (order_id,)).fetchone() or {})
            if not order:
                continue
            conn.execute(
                "UPDATE bank_payment_orders SET status=?, external_payment_id=?, updated_at=? WHERE id=?",
                (status, str(item.get("external_payment_id") or ""), _now_ts(), order_id),
            )
            if status == "executed" and _safe_int(order.get("payment_id")):
                conn.execute(
                    "UPDATE finance_payments SET status='paid', paid_date=?, updated_at=? WHERE id=?",
                    (str(item.get("executed_at") or datetime.now().strftime("%d.%m.%Y")), _now_ts(), _safe_int(order.get("payment_id"))),
                )
            applied.append({"payment_order_id": order_id, "status": status})
        cursor = conn.execute(
            """
            INSERT INTO bank_exchange_batches (
                provider_name, direction, batch_type, bank_account_id, status, payload_json, total_amount,
                item_count, comment, created_by, created_at, updated_at
            ) VALUES (?, 'inbound', ?, ?, 'imported', ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                data.provider_name or "bank_api",
                data.batch_type or "payment_exchange",
                _safe_int(data.bank_account_id),
                json.dumps({"items": result_items}, ensure_ascii=False),
                len(result_items),
                data.comment or "",
                actor.get("email", ""),
                _now_ts(),
                _now_ts(),
            ),
        )
        batch_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("bank_exchange_imported", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="bank_exchange_batch", entity_id=str(batch_id), details={"count": len(result_items)})
    return {"status": "success", "id": batch_id, "applied": applied}


@router.get("/api/accounting/manual_operations")
def get_accounting_manual_operations(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_accounting_deep(actor).get("manual_operations", [])


@router.get("/api/accounting/manual_operations/deep")
def get_accounting_manual_operations_deep(request: Request):
    return get_accounting_manual_operations(request)


@router.post("/api/accounting/manual_operations")
def create_accounting_manual_operation(data: AccountingManualOperationData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "post"):
        return {"error": "forbidden"}
    if not can_access_scope(actor, data.legal_entity_id, data.business_unit_id):
        return {"error": "forbidden_scope"}
    conn = get_connection(row_factory=True)
    try:
        is_open, period_key = _ensure_open_period(conn, data.entry_date)
        if not is_open:
            return {"error": f"period_closed:{period_key}"}
        conn.execute(
            """
            INSERT INTO accounting_manual_operations (entry_date, period_key, legal_entity_id, business_unit_id, project_id, client_id, account_debit, account_credit, amount, vat_amount, description, status, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (data.entry_date, period_key, _safe_int(data.legal_entity_id), _safe_int(data.business_unit_id), _safe_int(data.project_id), _safe_int(data.client_id), data.account_debit, data.account_credit, data.amount, data.vat_amount, data.description, data.status, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("accounting_manual_operation_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="accounting_manual_operation", entity_id="new", details={"description": data.description, "amount": data.amount})
    return {"status": "success"}


@router.post("/api/accounting/manual_operations/deep")
def create_accounting_manual_operation_deep(data: AccountingManualOperationData, request: Request):
    return create_accounting_manual_operation(data, request)


@router.delete("/api/accounting/manual_operations/{record_id}")
def delete_accounting_manual_operation(record_id: int, request: Request):
    return _delete_row_with_scope(request, "finance", "delete", "accounting_manual_operations", record_id, "accounting_manual_operation", lambda conn, rid: dict(conn.execute("SELECT id, legal_entity_id, business_unit_id FROM accounting_manual_operations WHERE id=?", (_safe_int(rid),)).fetchone() or {}))


@router.get("/api/accounting/debt_adjustments")
def get_accounting_debt_adjustments(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_accounting_deep(actor).get("debt_adjustments", [])


@router.post("/api/accounting/debt_adjustments")
def create_accounting_debt_adjustment(data: DebtAdjustmentData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "post"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        is_open, period_key = _ensure_open_period(conn, data.adjustment_date)
        if not is_open:
            return {"error": f"period_closed:{period_key}"}
        conn.execute(
            """
            INSERT INTO accounting_debt_adjustments (client_id, contract_id, adjustment_date, amount, adjustment_kind, reason, account_debit, account_credit, status, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.client_id), _safe_int(data.contract_id), data.adjustment_date, data.amount, data.adjustment_kind, data.reason, data.account_debit or "91.02", data.account_credit or "62.01", data.status, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("accounting_debt_adjustment_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="accounting_debt_adjustment", entity_id="new", details={"amount": data.amount, "reason": data.reason})
    return {"status": "success"}


@router.delete("/api/accounting/debt_adjustments/{record_id}")
def delete_accounting_debt_adjustment(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "delete"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        conn.execute("DELETE FROM accounting_debt_adjustments WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("accounting_debt_adjustment_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="accounting_debt_adjustment", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.get("/api/accounting/cash_operations")
def get_accounting_cash_operations(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_accounting_deep(actor).get("cash_operations", [])


@router.get("/api/accounting/cash_operations/deep")
def get_accounting_cash_operations_deep(request: Request):
    return get_accounting_cash_operations(request)


@router.post("/api/accounting/cash_operations")
def create_accounting_cash_operation(data: CashOperationData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "post"):
        return {"error": "forbidden"}
    if not can_access_scope(actor, data.legal_entity_id, data.business_unit_id):
        return {"error": "forbidden_scope"}
    conn = get_connection(row_factory=True)
    try:
        is_open, period_key = _ensure_open_period(conn, data.operation_date)
        if not is_open:
            return {"error": f"period_closed:{period_key}"}
        conn.execute(
            """
            INSERT INTO cash_operations (legal_entity_id, business_unit_id, project_id, operation_date, direction, category, amount, currency, cashbox_name, counterparty_name, linked_payment_id, account_debit, account_credit, status, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_safe_int(data.legal_entity_id), _safe_int(data.business_unit_id), _safe_int(data.project_id), data.operation_date, data.direction, data.category, data.amount, data.currency, data.cashbox_name, data.counterparty_name, _safe_int(data.linked_payment_id), data.account_debit, data.account_credit, data.status, data.comment, actor.get("email", ""), _now_ts(), _now_ts()),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("accounting_cash_operation_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="cash_operation", entity_id="new", details={"amount": data.amount, "direction": data.direction})
    return {"status": "success", "period_key": period_key}


@router.post("/api/accounting/cash_operations/deep")
def create_accounting_cash_operation_deep(data: CashOperationData, request: Request):
    return create_accounting_cash_operation(data, request)


@router.delete("/api/accounting/cash_operations/{record_id}")
def delete_accounting_cash_operation(record_id: int, request: Request):
    return _delete_row_with_scope(request, "finance", "delete", "cash_operations", record_id, "cash_operation", lambda conn, rid: dict(conn.execute("SELECT id, legal_entity_id, business_unit_id FROM cash_operations WHERE id=?", (_safe_int(rid),)).fetchone() or {}))
