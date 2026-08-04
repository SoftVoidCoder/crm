import json
import time
from datetime import datetime


DONE_STATUSES = {"done", "completed", "finished", "closed"}


def safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def safe_text(value) -> str:
    return str(value or "").strip()


def now_ts() -> int:
    return int(time.time())


def json_load(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def json_dump(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def row_dict(cursor) -> dict:
    row = cursor.fetchone()
    if not row:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(zip([col[0] for col in cursor.description], row))


def row_dicts(cursor) -> list[dict]:
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return [dict(row) for row in rows]
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def parse_date(value: str):
    text = safe_text(value)
    if not text:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def period_key(value: str = "") -> str:
    dt = parse_date(value) or datetime.now()
    return dt.strftime("%Y-%m")


def table_exists(conn, table_name: str) -> bool:
    cur = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema='public' AND table_name=?
        LIMIT 1
        """,
        (safe_text(table_name),),
    )
    return bool(cur.fetchone())


def upsert_bom_master(conn, data: dict, actor_email: str = "") -> int:
    code = safe_text(data.get("bom_code")) or safe_text(data.get("item_article")) or f"BOM-{now_ts()}"
    now = now_ts()
    existing = row_dict(conn.execute("SELECT id FROM bom_master WHERE bom_code=?", (code,)))
    payload = {
        "item_article": safe_text(data.get("item_article")),
        "item_name": safe_text(data.get("item_name")),
        "bom_code": code,
        "bom_name": safe_text(data.get("bom_name")) or safe_text(data.get("item_name")) or code,
        "status": safe_text(data.get("status")) or "draft",
        "default_version_id": safe_int(data.get("default_version_id")),
        "unit": safe_text(data.get("unit")) or "шт",
        "output_qty": safe_float(data.get("output_qty")) or 1,
        "legal_entity_id": safe_int(data.get("legal_entity_id")),
        "business_unit_id": safe_int(data.get("business_unit_id")),
        "comment": safe_text(data.get("comment")),
        "created_by": actor_email,
        "created_at": now,
        "updated_at": now,
    }
    if existing:
        conn.execute(
            """
            UPDATE bom_master
            SET item_article=?, item_name=?, bom_name=?, status=?, default_version_id=?, unit=?, output_qty=?,
                legal_entity_id=?, business_unit_id=?, comment=?, updated_at=?
            WHERE id=?
            """,
            (
                payload["item_article"],
                payload["item_name"],
                payload["bom_name"],
                payload["status"],
                payload["default_version_id"],
                payload["unit"],
                payload["output_qty"],
                payload["legal_entity_id"],
                payload["business_unit_id"],
                payload["comment"],
                now,
                safe_int(existing.get("id")),
            ),
        )
        return safe_int(existing.get("id"))
    cur = conn.execute(
        """
        INSERT INTO bom_master (
            item_article, item_name, bom_code, bom_name, status, default_version_id, unit, output_qty,
            legal_entity_id, business_unit_id, comment, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(payload[key] for key in (
            "item_article",
            "item_name",
            "bom_code",
            "bom_name",
            "status",
            "default_version_id",
            "unit",
            "output_qty",
            "legal_entity_id",
            "business_unit_id",
            "comment",
            "created_by",
            "created_at",
            "updated_at",
        )),
    )
    return safe_int(getattr(cur, "lastrowid", 0)) or safe_int(row_dict(conn.execute("SELECT id FROM bom_master WHERE bom_code=?", (code,))).get("id"))


def create_bom_version(conn, data: dict, actor_email: str = "") -> int:
    bom_id = safe_int(data.get("bom_id"))
    version_no = safe_text(data.get("version_no")) or "1"
    now = now_ts()
    existing = row_dict(conn.execute("SELECT id FROM bom_versions WHERE bom_id=? AND version_no=?", (bom_id, version_no)))
    components = data.get("components") if isinstance(data.get("components"), list) else json_load(data.get("components_json"), [])
    operations = data.get("operations") if isinstance(data.get("operations"), list) else json_load(data.get("operations_json"), [])
    overhead_rules = data.get("overhead_rules") if isinstance(data.get("overhead_rules"), dict) else json_load(data.get("overhead_rules_json"), {})
    values = (
        bom_id,
        version_no,
        safe_text(data.get("status")) or "draft",
        safe_text(data.get("valid_from")),
        safe_text(data.get("valid_to")),
        safe_float(data.get("output_qty")) or 1,
        json.dumps(components, ensure_ascii=False),
        json.dumps(operations, ensure_ascii=False),
        json.dumps(overhead_rules, ensure_ascii=False),
        safe_text(data.get("comment")),
        actor_email,
        now,
        now,
    )
    if existing:
        conn.execute(
            """
            UPDATE bom_versions
            SET status=?, valid_from=?, valid_to=?, output_qty=?, components_json=?, operations_json=?,
                overhead_rules_json=?, comment=?, updated_at=?
            WHERE id=?
            """,
            (values[2], values[3], values[4], values[5], values[6], values[7], values[8], values[9], now, safe_int(existing.get("id"))),
        )
        version_id = safe_int(existing.get("id"))
    else:
        cur = conn.execute(
            """
            INSERT INTO bom_versions (
                bom_id, version_no, status, valid_from, valid_to, output_qty, components_json, operations_json,
                overhead_rules_json, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        version_id = safe_int(getattr(cur, "lastrowid", 0)) or safe_int(row_dict(conn.execute("SELECT id FROM bom_versions WHERE bom_id=? AND version_no=?", (bom_id, version_no))).get("id"))
    if safe_text(data.get("status")) in {"active", "approved"}:
        conn.execute("UPDATE bom_master SET default_version_id=?, updated_at=? WHERE id=?", (version_id, now, bom_id))
    return version_id


def upsert_work_center(conn, data: dict, actor_email: str = "") -> int:
    code = safe_text(data.get("center_code")) or safe_text(data.get("center_name")) or f"WC-{now_ts()}"
    now = now_ts()
    existing = row_dict(conn.execute("SELECT id FROM work_centers WHERE center_code=?", (code,)))
    values = (
        code,
        safe_text(data.get("center_name")) or code,
        safe_text(data.get("center_type")) or "production",
        safe_int(data.get("legal_entity_id")),
        safe_int(data.get("business_unit_id")),
        safe_float(data.get("capacity_per_hour")),
        safe_float(data.get("hourly_rate")),
        safe_float(data.get("overhead_rate")),
        safe_text(data.get("calendar_code")),
        safe_text(data.get("status")) or "active",
        safe_text(data.get("comment")),
        actor_email,
        now,
        now,
    )
    if existing:
        conn.execute(
            """
            UPDATE work_centers
            SET center_name=?, center_type=?, legal_entity_id=?, business_unit_id=?, capacity_per_hour=?,
                hourly_rate=?, overhead_rate=?, calendar_code=?, status=?, comment=?, updated_at=?
            WHERE id=?
            """,
            (*values[1:11], now, safe_int(existing.get("id"))),
        )
        return safe_int(existing.get("id"))
    cur = conn.execute(
        """
        INSERT INTO work_centers (
            center_code, center_name, center_type, legal_entity_id, business_unit_id, capacity_per_hour,
            hourly_rate, overhead_rate, calendar_code, status, comment, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return safe_int(getattr(cur, "lastrowid", 0)) or safe_int(row_dict(conn.execute("SELECT id FROM work_centers WHERE center_code=?", (code,))).get("id"))


def upsert_work_center_calendar(conn, data: dict, actor_email: str = "") -> int:
    work_center_id = safe_int(data.get("work_center_id"))
    calendar_date = safe_text(data.get("calendar_date"))
    shift_code = safe_text(data.get("shift_code")) or "day"
    now = now_ts()
    existing = row_dict(conn.execute(
        "SELECT id FROM work_center_calendars WHERE work_center_id=? AND calendar_date=? AND shift_code=?",
        (work_center_id, calendar_date, shift_code),
    ))
    values = (
        work_center_id,
        calendar_date,
        shift_code,
        safe_float(data.get("available_hours")),
        safe_float(data.get("capacity_qty")),
        safe_text(data.get("status")) or "available",
        safe_text(data.get("comment")),
        actor_email,
        now,
        now,
    )
    if existing:
        conn.execute(
            """
            UPDATE work_center_calendars
            SET available_hours=?, capacity_qty=?, status=?, comment=?, updated_at=?
            WHERE id=?
            """,
            (values[3], values[4], values[5], values[6], now, safe_int(existing.get("id"))),
        )
        return safe_int(existing.get("id"))
    cur = conn.execute(
        """
        INSERT INTO work_center_calendars (
            work_center_id, calendar_date, shift_code, available_hours, capacity_qty, status, comment,
            created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return safe_int(getattr(cur, "lastrowid", 0)) or safe_int(row_dict(conn.execute(
        "SELECT id FROM work_center_calendars WHERE work_center_id=? AND calendar_date=? AND shift_code=?",
        (work_center_id, calendar_date, shift_code),
    )).get("id"))


def _operation_context(conn, operation_id: int) -> tuple[dict, dict]:
    operation = row_dict(conn.execute("SELECT * FROM production_operations WHERE id=?", (safe_int(operation_id),)))
    if not operation:
        return {}, {}
    order = row_dict(conn.execute("SELECT * FROM production_orders WHERE id=?", (safe_int(operation.get("order_id")),)))
    return operation, order


def _work_center(conn, operation: dict, order: dict) -> dict:
    code = safe_text(operation.get("work_center")) or safe_text(order.get("route_name"))
    if not code:
        return {}
    return row_dict(conn.execute(
        """
        SELECT *
        FROM work_centers
        WHERE center_code=? OR center_name=?
        ORDER BY CASE WHEN center_code=? THEN 0 ELSE 1 END, id DESC
        LIMIT 1
        """,
        (code, code, code),
    ))


def _material_rows(conn, order_id: int) -> list[dict]:
    rows = row_dicts(conn.execute("SELECT * FROM production_bom_items WHERE order_id=? ORDER BY id", (safe_int(order_id),)))
    if rows:
        return rows
    return row_dicts(conn.execute("SELECT * FROM production_material_norms WHERE order_id=? ORDER BY id", (safe_int(order_id),)))


def _is_final_operation(conn, operation: dict) -> bool:
    order_id = safe_int(operation.get("order_id"))
    sequence_no = safe_int(operation.get("sequence_no"))
    row = row_dict(conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM production_operations
        WHERE order_id=? AND sequence_no>?
        """,
        (order_id, sequence_no),
    ))
    return safe_int(row.get("cnt")) == 0


def _insert_layer(conn, payload: dict) -> int:
    now = now_ts()
    payload = {**payload, "created_at": now, "updated_at": now}
    keys = [
        "production_order_id",
        "operation_id",
        "layer_type",
        "item_article",
        "item_name",
        "qty",
        "unit",
        "plan_amount",
        "actual_amount",
        "overhead_amount",
        "cost_per_unit",
        "source_type",
        "source_id",
        "period_key",
        "details_json",
        "created_by",
        "created_at",
        "updated_at",
    ]
    cur = conn.execute(
        f"INSERT INTO production_cost_layers ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
        tuple(payload.get(key, 0 if key.endswith("_id") or key in {"qty", "plan_amount", "actual_amount", "overhead_amount", "cost_per_unit", "created_at", "updated_at"} else "") for key in keys),
    )
    return safe_int(getattr(cur, "lastrowid", 0))


def _insert_wip(conn, payload: dict) -> int:
    payload = {**payload, "created_at": now_ts()}
    keys = [
        "production_order_id",
        "operation_id",
        "layer_id",
        "movement_type",
        "item_article",
        "item_name",
        "qty",
        "amount",
        "status",
        "period_key",
        "account_debit",
        "account_credit",
        "details_json",
        "created_by",
        "created_at",
    ]
    cur = conn.execute(
        f"INSERT INTO wip_register ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
        tuple(payload.get(key, 0 if key.endswith("_id") or key in {"qty", "amount", "created_at"} else "") for key in keys),
    )
    return safe_int(getattr(cur, "lastrowid", 0))


def _layer(conn, order: dict, operation: dict, layer_type: str, article: str, name: str, qty: float, unit: str, plan_amount: float, actual_amount: float, overhead_amount: float, source_type: str, source_id: int, period: str, actor_email: str, details: dict, debit: str, credit: str, movement_type: str) -> int:
    total_amount = round(safe_float(actual_amount) + safe_float(overhead_amount), 2)
    qty_value = round(safe_float(qty), 4)
    layer_id = _insert_layer(conn, {
        "production_order_id": safe_int(order.get("id")),
        "operation_id": safe_int(operation.get("id")),
        "layer_type": layer_type,
        "item_article": article,
        "item_name": name,
        "qty": qty_value,
        "unit": unit or "шт",
        "plan_amount": round(safe_float(plan_amount), 2),
        "actual_amount": round(safe_float(actual_amount), 2),
        "overhead_amount": round(safe_float(overhead_amount), 2),
        "cost_per_unit": round(total_amount / qty_value, 4) if qty_value else 0,
        "source_type": source_type,
        "source_id": safe_int(source_id),
        "period_key": period,
        "details_json": json_dump(details),
        "created_by": actor_email,
    })
    if not layer_id:
        layer_id = safe_int(row_dict(conn.execute("SELECT MAX(id) AS id FROM production_cost_layers")).get("id"))
    _insert_wip(conn, {
        "production_order_id": safe_int(order.get("id")),
        "operation_id": safe_int(operation.get("id")),
        "layer_id": layer_id,
        "movement_type": movement_type,
        "item_article": article,
        "item_name": name,
        "qty": qty_value,
        "amount": total_amount,
        "status": "posted",
        "period_key": period,
        "account_debit": debit,
        "account_credit": credit,
        "details_json": json_dump(details),
        "created_by": actor_email,
    })
    return layer_id


def _ensure_output_register(conn, order: dict, operation: dict, period: str, actor_email: str, amount: float, qty: float, final_operation: bool):
    article = f"FG-{safe_int(order.get('id'))}" if final_operation else f"WIP-{safe_int(order.get('id'))}-{safe_int(operation.get('sequence_no'))}"
    name = safe_text(order.get("order_name")) or f"Заказ {safe_int(order.get('id'))}"
    movement_type = "finished_goods_receipt" if final_operation else "semifinished_receipt"
    debit = "43" if final_operation else "21"
    _layer(
        conn,
        order,
        operation,
        "output" if final_operation else "semifinished",
        article,
        name,
        qty,
        "шт",
        amount,
        amount,
        0,
        "production_operation",
        safe_int(operation.get("id")),
        period,
        actor_email,
        {"operation_name": operation.get("operation_name"), "final_operation": final_operation},
        debit,
        "20",
        movement_type,
    )
    if not final_operation:
        existing = row_dict(conn.execute(
            "SELECT id, qty FROM production_semifinished WHERE order_id=? AND article=?",
            (safe_int(order.get("id")), article),
        ))
        if existing:
            conn.execute(
                "UPDATE production_semifinished SET qty=?, unit_cost=?, status='in_stock', updated_at=? WHERE id=?",
                (qty, round(amount / qty, 4) if qty else 0, now_ts(), safe_int(existing.get("id"))),
            )
        else:
            conn.execute(
                """
                INSERT INTO production_semifinished (
                    order_id, article, item_name, qty, stage_name, warehouse, status, unit_cost,
                    comment, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'in_stock', ?, ?, ?, ?, ?)
                """,
                (
                    safe_int(order.get("id")),
                    article,
                    name,
                    qty,
                    safe_text(operation.get("operation_name")),
                    "НЗП",
                    round(amount / qty, 4) if qty else 0,
                    "Автовыпуск полуфабриката из операции",
                    actor_email,
                    now_ts(),
                    now_ts(),
                ),
            )


def complete_operation_costing(conn, operation_id: int, actor_email: str = "") -> dict:
    operation, order = _operation_context(conn, operation_id)
    if not operation or not order:
        return {"error": "operation_not_found"}
    if safe_text(operation.get("status")) not in DONE_STATUSES:
        return {"status": "skipped", "reason": "operation_not_completed", "operation_id": safe_int(operation_id)}

    operation_id = safe_int(operation.get("id"))
    order_id = safe_int(order.get("id"))
    period = period_key(operation.get("finished_at") or order.get("actual_finish") or order.get("planned_finish"))
    completed_qty = safe_float(operation.get("completed_qty")) or safe_float(operation.get("planned_qty")) or safe_float(order.get("planned_qty")) or 1
    order_qty = safe_float(order.get("planned_qty")) or completed_qty or 1
    qty_factor = completed_qty / order_qty if order_qty > 0 else 1
    work_center = _work_center(conn, operation, order)

    conn.execute("DELETE FROM wip_register WHERE operation_id=?", (operation_id,))
    conn.execute("DELETE FROM production_cost_layers WHERE operation_id=?", (operation_id,))

    material_total = 0.0
    material_plan_total = 0.0
    material_count = 0
    for item in _material_rows(conn, order_id):
        article = safe_text(item.get("article"))
        if not article:
            continue
        qty_per_unit = safe_float(item.get("qty_per_unit")) or safe_float(item.get("norm_qty"))
        planned_qty = safe_float(item.get("planned_qty")) or round(qty_per_unit * order_qty, 4)
        actual_qty = safe_float(item.get("actual_qty")) or round((qty_per_unit * completed_qty) if qty_per_unit > 0 else (planned_qty * qty_factor), 4)
        scrap_rate = safe_float(item.get("scrap_rate"))
        if scrap_rate:
            actual_qty = round(actual_qty * (1 + scrap_rate / 100), 4)
        unit_cost = safe_float(item.get("unit_cost"))
        if unit_cost <= 0:
            unit_cost = safe_float(row_dict(conn.execute("SELECT price FROM nomenclature WHERE article=? LIMIT 1", (article,))).get("price"))
        plan_amount = round(planned_qty * unit_cost * qty_factor, 2)
        actual_amount = round(actual_qty * unit_cost, 2)
        material_plan_total += plan_amount
        material_total += actual_amount
        material_count += 1
        _layer(
            conn,
            order,
            operation,
            "material",
            article,
            safe_text(item.get("item_name")) or article,
            actual_qty,
            safe_text(item.get("unit")) or "шт",
            plan_amount,
            actual_amount,
            0,
            "production_bom_item" if item.get("qty_per_unit") is not None else "production_material_norm",
            safe_int(item.get("id")),
            period,
            actor_email,
            {
                "warehouse": item.get("warehouse") or "",
                "bin_code": item.get("bin_code") or "",
                "qty_per_unit": qty_per_unit,
                "scrap_rate": scrap_rate,
            },
            "20",
            "10",
            "material_issue",
        )

    operation_material_cost = safe_float(operation.get("material_cost"))
    if material_count == 0 and operation_material_cost > 0:
        material_total = operation_material_cost
        material_plan_total = operation_material_cost
        _layer(
            conn,
            order,
            operation,
            "material",
            "MAT-OP",
            "Материалы операции",
            completed_qty,
            "шт",
            operation_material_cost,
            operation_material_cost,
            0,
            "production_operation",
            operation_id,
            period,
            actor_email,
            {"fallback": "operation.material_cost"},
            "20",
            "10",
            "material_issue",
        )

    rate = safe_float(operation.get("labor_rate")) or safe_float(work_center.get("hourly_rate"))
    planned_labor = round(safe_float(operation.get("planned_hours")) * rate, 2)
    actual_labor = round(safe_float(operation.get("actual_hours")) * rate, 2)
    if actual_labor > 0 or planned_labor > 0:
        _layer(
            conn,
            order,
            operation,
            "labor",
            safe_text(work_center.get("center_code")) or safe_text(operation.get("work_center")) or "LABOR",
            "Трудозатраты",
            safe_float(operation.get("actual_hours")),
            "ч",
            planned_labor,
            actual_labor,
            0,
            "production_operation",
            operation_id,
            period,
            actor_email,
            {"rate": rate, "work_center": operation.get("work_center")},
            "20",
            "70",
            "labor_absorption",
        )

    overhead = safe_float(operation.get("overhead_cost"))
    if overhead <= 0:
        overhead = round(safe_float(operation.get("actual_hours")) * safe_float(work_center.get("overhead_rate")), 2)
    if overhead > 0:
        _layer(
            conn,
            order,
            operation,
            "overhead",
            safe_text(work_center.get("center_code")) or safe_text(operation.get("work_center")) or "OVERHEAD",
            "Накладные расходы",
            safe_float(operation.get("actual_hours")) or completed_qty,
            "ч",
            overhead,
            0,
            overhead,
            "production_operation",
            operation_id,
            period,
            actor_email,
            {"work_center": operation.get("work_center")},
            "20",
            "25",
            "overhead_absorption",
        )

    total_actual = round(material_total + actual_labor + overhead, 2)
    final_operation = _is_final_operation(conn, operation)
    _ensure_output_register(conn, order, operation, period, actor_email, total_actual, completed_qty, final_operation)

    totals = row_dict(conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN layer_type='material' THEN actual_amount ELSE 0 END), 0) AS material_amount,
            COALESCE(SUM(CASE WHEN layer_type='labor' THEN actual_amount ELSE 0 END), 0) AS labor_amount,
            COALESCE(SUM(CASE WHEN layer_type='overhead' THEN overhead_amount ELSE 0 END), 0) AS overhead_amount,
            COALESCE(SUM(CASE WHEN layer_type IN ('material','labor') THEN actual_amount ELSE 0 END), 0)
                + COALESCE(SUM(CASE WHEN layer_type='overhead' THEN overhead_amount ELSE 0 END), 0) AS actual_cost
        FROM production_cost_layers
        WHERE production_order_id=?
          AND layer_type IN ('material', 'labor', 'overhead')
          AND EXISTS (
              SELECT 1
              FROM production_operations po
              WHERE po.id=production_cost_layers.operation_id
                AND po.order_id=production_cost_layers.production_order_id
          )
        """,
        (order_id,),
    ))
    conn.execute(
        "UPDATE production_orders SET actual_cost=?, updated_at=? WHERE id=?",
        (round(safe_float(totals.get("actual_cost")), 2), now_ts(), order_id),
    )
    return {
        "status": "success",
        "operation_id": operation_id,
        "order_id": order_id,
        "period_key": period,
        "final_operation": final_operation,
        "materials_amount": round(material_total, 2),
        "materials_plan_amount": round(material_plan_total, 2),
        "labor_amount": round(actual_labor, 2),
        "overhead_amount": round(overhead, 2),
        "actual_cost": total_actual,
        "output_qty": round(completed_qty, 4),
        "cost_per_unit": round(total_actual / completed_qty, 4) if completed_qty else 0,
    }


def build_plan_fact_cost_report(conn, production_order_id: int = 0, period: str = "") -> dict:
    params = []
    where = []
    if safe_int(production_order_id):
        where.append("po.id=?")
        params.append(safe_int(production_order_id))
    if safe_text(period):
        where.append("(pcl.period_key=? OR pcl.period_key IS NULL)")
        params.append(safe_text(period))
    query = """
        SELECT
            po.id AS order_id,
            po.order_name,
            po.stage,
            po.planned_qty,
            po.produced_qty,
            po.planned_cost,
            po.actual_cost,
            po.legal_entity_id,
            po.business_unit_id,
            COALESCE(SUM(CASE WHEN pcl.layer_type='material' THEN pcl.plan_amount ELSE 0 END), 0) AS material_plan,
            COALESCE(SUM(CASE WHEN pcl.layer_type='material' THEN pcl.actual_amount ELSE 0 END), 0) AS material_fact,
            COALESCE(SUM(CASE WHEN pcl.layer_type='labor' THEN pcl.plan_amount ELSE 0 END), 0) AS labor_plan,
            COALESCE(SUM(CASE WHEN pcl.layer_type='labor' THEN pcl.actual_amount ELSE 0 END), 0) AS labor_fact,
            COALESCE(SUM(CASE WHEN pcl.layer_type='overhead' THEN pcl.plan_amount ELSE 0 END), 0) AS overhead_plan,
            COALESCE(SUM(CASE WHEN pcl.layer_type='overhead' THEN pcl.overhead_amount ELSE 0 END), 0) AS overhead_fact,
            COALESCE(SUM(CASE WHEN pcl.layer_type IN ('output','semifinished') THEN pcl.qty ELSE 0 END), 0) AS output_qty,
            COUNT(pcl.id) AS layer_count
        FROM production_orders po
        LEFT JOIN production_cost_layers pcl
          ON pcl.production_order_id=po.id
         AND EXISTS (
             SELECT 1
             FROM production_operations operation
             WHERE operation.id=pcl.operation_id
               AND operation.order_id=po.id
         )
    """
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " GROUP BY po.id ORDER BY po.updated_at DESC, po.id DESC"
    rows = row_dicts(conn.execute(query, tuple(params)))
    report_rows = []
    for row in rows:
        planned_cost = safe_float(row.get("planned_cost")) or round(safe_float(row.get("material_plan")) + safe_float(row.get("labor_plan")) + safe_float(row.get("overhead_plan")), 2)
        fact_cost = round(safe_float(row.get("material_fact")) + safe_float(row.get("labor_fact")) + safe_float(row.get("overhead_fact")), 2)
        if fact_cost <= 0:
            fact_cost = safe_float(row.get("actual_cost"))
        produced_qty = safe_float(row.get("output_qty")) or safe_float(row.get("produced_qty"))
        variance = round(fact_cost - planned_cost, 2)
        report_rows.append({
            "order_id": safe_int(row.get("order_id")),
            "order_name": row.get("order_name") or f"Заказ {safe_int(row.get('order_id'))}",
            "stage": row.get("stage") or "",
            "planned_qty": round(safe_float(row.get("planned_qty")), 4),
            "produced_qty": round(produced_qty, 4),
            "planned_cost": round(planned_cost, 2),
            "fact_cost": round(fact_cost, 2),
            "variance": variance,
            "variance_percent": round((variance / planned_cost) * 100, 2) if planned_cost else 0,
            "unit_cost_plan": round(planned_cost / safe_float(row.get("planned_qty")), 4) if safe_float(row.get("planned_qty")) else 0,
            "unit_cost_fact": round(fact_cost / produced_qty, 4) if produced_qty else 0,
            "material_plan": round(safe_float(row.get("material_plan")), 2),
            "material_fact": round(safe_float(row.get("material_fact")), 2),
            "labor_plan": round(safe_float(row.get("labor_plan")), 2),
            "labor_fact": round(safe_float(row.get("labor_fact")), 2),
            "overhead_plan": round(safe_float(row.get("overhead_plan")), 2),
            "overhead_fact": round(safe_float(row.get("overhead_fact")), 2),
            "layer_count": safe_int(row.get("layer_count")),
            "risk_level": "risk" if variance > 0 else ("ok" if fact_cost > 0 else "neutral"),
        })
    return {
        "rows": report_rows,
        "totals": {
            "orders": len(report_rows),
            "planned_cost": round(sum(safe_float(row.get("planned_cost")) for row in report_rows), 2),
            "fact_cost": round(sum(safe_float(row.get("fact_cost")) for row in report_rows), 2),
            "variance": round(sum(safe_float(row.get("variance")) for row in report_rows), 2),
            "produced_qty": round(sum(safe_float(row.get("produced_qty")) for row in report_rows), 4),
        },
    }
