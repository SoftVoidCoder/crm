import json
from datetime import datetime, timedelta


ACTIVE_ORDER_STAGES = {"queue", "in_work", "otk", "planned", "released"}


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


def json_load(raw_value, default):
    if raw_value in (None, ""):
        return default
    try:
        return json.loads(raw_value)
    except Exception:
        return default


def row_dicts(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def parse_date(value: str):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%Y %H:%M", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def display_date(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y")


def iso_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _scope_rows(actor: dict, rows: list[dict], filter_rows_by_scope_fn) -> list[dict]:
    return filter_rows_by_scope_fn(actor, rows, "legal_entity_id", "business_unit_id") if filter_rows_by_scope_fn else rows


def _active_orders(orders: list[dict]) -> list[dict]:
    return [row for row in orders if str(row.get("stage") or "queue") in ACTIVE_ORDER_STAGES]


def _remaining_qty(order: dict, demand_multiplier: float) -> float:
    planned_qty = safe_float(order.get("planned_qty"))
    produced_qty = safe_float(order.get("produced_qty"))
    base_qty = planned_qty if planned_qty > 0 else 1.0
    remaining = max(base_qty - produced_qty, 0.0)
    return round((remaining or base_qty) * max(demand_multiplier, 0.0), 4)


def _inventory_by_article(inventory_rows: list[dict]) -> dict[str, float]:
    balances: dict[str, float] = {}
    for row in inventory_rows:
        article = str(row.get("article") or "").strip()
        if not article:
            continue
        balances[article] = balances.get(article, 0.0) + safe_float(row.get("qty"))
    return {article: round(qty, 4) for article, qty in balances.items()}


def _incoming_purchase_by_article(purchase_rows: list[dict]) -> dict[str, float]:
    incoming: dict[str, float] = {}
    for row in purchase_rows:
        status = str(row.get("status") or "")
        if status in {"received", "closed", "done", "canceled"}:
            continue
        article = str(row.get("item_article") or "").strip()
        if not article:
            continue
        qty = max(safe_float(row.get("qty")) - safe_float(row.get("delivered_qty")), 0.0)
        incoming[article] = incoming.get(article, 0.0) + qty
    return {article: round(qty, 4) for article, qty in incoming.items()}


def _material_demand_rows(orders: list[dict], material_norms: list[dict], bom_items: list[dict], demand_multiplier: float) -> list[dict]:
    by_order_norms: dict[int, list[dict]] = {}
    by_order_bom: dict[int, list[dict]] = {}
    for row in material_norms:
        by_order_norms.setdefault(safe_int(row.get("order_id")), []).append(row)
    for row in bom_items:
        by_order_bom.setdefault(safe_int(row.get("order_id")), []).append(row)

    demands = []
    for order in _active_orders(orders):
        order_id = safe_int(order.get("id"))
        remaining_qty = _remaining_qty(order, demand_multiplier)
        due_dt = parse_date(order.get("planned_finish")) or (datetime.now() + timedelta(days=14))
        norm_rows = by_order_norms.get(order_id) or []
        source_rows = norm_rows or by_order_bom.get(order_id) or []
        for item in source_rows:
            article = str(item.get("article") or "").strip()
            if not article:
                continue
            norm_qty = safe_float(item.get("norm_qty"))
            if norm_qty <= 0:
                norm_qty = safe_float(item.get("qty_per_unit")) or safe_float(item.get("planned_qty"))
            scrap_factor = 1 + (safe_float(item.get("scrap_rate")) / 100)
            required_qty = round(norm_qty * remaining_qty * scrap_factor, 4)
            if required_qty <= 0:
                continue
            demands.append(
                {
                    "order_id": order_id,
                    "order_name": order.get("order_name") or f"Заказ {order_id}",
                    "article": article,
                    "item_name": item.get("item_name") or item.get("name") or article,
                    "unit": item.get("unit") or "шт",
                    "required_qty": required_qty,
                    "need_date": display_date(due_dt),
                    "need_date_iso": iso_date(due_dt),
                    "priority": order.get("priority") or "normal",
                }
            )
    return demands


def _shortages(material_demands: list[dict], inventory: dict[str, float], incoming: dict[str, float]) -> tuple[list[dict], list[dict]]:
    totals: dict[str, dict] = {}
    order_rows = []
    for row in material_demands:
        article = row["article"]
        bucket = totals.setdefault(
            article,
            {
                "article": article,
                "item_name": row.get("item_name") or article,
                "unit": row.get("unit") or "шт",
                "required_qty": 0.0,
                "stock_qty": round(inventory.get(article, 0.0), 4),
                "incoming_qty": round(incoming.get(article, 0.0), 4),
                "shortage_qty": 0.0,
                "orders": 0,
                "earliest_need_date": row.get("need_date", ""),
            },
        )
        bucket["required_qty"] += safe_float(row.get("required_qty"))
        bucket["orders"] += 1
        if row.get("need_date_iso") and row.get("need_date_iso") < (bucket.get("earliest_need_date_iso") or "9999-12-31"):
            bucket["earliest_need_date"] = row.get("need_date", "")
            bucket["earliest_need_date_iso"] = row.get("need_date_iso")
    shortage_rows = []
    for item in totals.values():
        available = safe_float(item.get("stock_qty")) + safe_float(item.get("incoming_qty"))
        item["required_qty"] = round(safe_float(item.get("required_qty")), 4)
        item["available_qty"] = round(available, 4)
        item["shortage_qty"] = round(max(item["required_qty"] - available, 0.0), 4)
        item["coverage_percent"] = round((available / item["required_qty"]) * 100, 1) if item["required_qty"] > 0 else 100
        item["risk_level"] = "risk" if item["shortage_qty"] > 0 else ("warning" if item["coverage_percent"] < 120 else "ok")
        if item["shortage_qty"] > 0:
            shortage_rows.append(item)

    for row in material_demands:
        article_total = totals.get(row["article"], {})
        order_rows.append(
            {
                **row,
                "stock_qty": article_total.get("stock_qty", 0),
                "incoming_qty": article_total.get("incoming_qty", 0),
                "article_shortage_qty": article_total.get("shortage_qty", 0),
                "risk_level": "risk" if article_total.get("shortage_qty", 0) else "ok",
            }
        )
    shortage_rows.sort(key=lambda row: (row.get("shortage_qty", 0), row.get("required_qty", 0)), reverse=True)
    order_rows.sort(key=lambda row: (row.get("need_date_iso", ""), row.get("risk_level") != "risk"))
    return shortage_rows, order_rows


def _labor_requirements(orders: list[dict], labor_norms: list[dict], operations: list[dict], demand_multiplier: float) -> list[dict]:
    by_order_norms: dict[int, list[dict]] = {}
    by_order_ops: dict[int, list[dict]] = {}
    for row in labor_norms:
        by_order_norms.setdefault(safe_int(row.get("order_id")), []).append(row)
    for row in operations:
        by_order_ops.setdefault(safe_int(row.get("order_id")), []).append(row)

    requirements = []
    for order in _active_orders(orders):
        order_id = safe_int(order.get("id"))
        remaining_qty = _remaining_qty(order, demand_multiplier)
        planned_qty = safe_float(order.get("planned_qty")) or remaining_qty or 1
        scale = min(max(remaining_qty / planned_qty, 0.0), 2.0) if planned_qty > 0 else 1.0
        due_dt = parse_date(order.get("planned_finish")) or (datetime.now() + timedelta(days=14))
        rows = by_order_norms.get(order_id) or by_order_ops.get(order_id) or []
        for idx, item in enumerate(rows, start=1):
            work_center = item.get("work_center") or order.get("route_name") or "Без центра"
            hours = safe_float(item.get("norm_hours")) * max(safe_int(item.get("team_size")), 1)
            if hours <= 0:
                hours = safe_float(item.get("planned_hours"))
            hours = round(hours * (scale or 1.0), 2)
            if hours <= 0:
                continue
            requirements.append(
                {
                    "order_id": order_id,
                    "order_name": order.get("order_name") or f"Заказ {order_id}",
                    "sequence_no": safe_int(item.get("sequence_no")) or idx,
                    "operation_name": item.get("operation_name") or f"Операция {idx}",
                    "work_center": work_center,
                    "required_hours": hours,
                    "due_date": display_date(due_dt),
                    "due_date_iso": iso_date(due_dt),
                    "priority": order.get("priority") or "normal",
                    "legal_entity_id": safe_int(order.get("legal_entity_id")),
                    "business_unit_id": safe_int(order.get("business_unit_id")),
                }
            )
    priority_rank = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    requirements.sort(key=lambda row: (row.get("due_date_iso", "9999-12-31"), priority_rank.get(row.get("priority"), 2), row.get("sequence_no", 0)))
    return requirements


def _capacity_buckets(shifts: list[dict], capacity_multiplier: float, horizon_start: datetime, horizon_end: datetime) -> list[dict]:
    buckets = []
    for shift in shifts:
        shift_dt = parse_date(shift.get("shift_date"))
        if not shift_dt or shift_dt < horizon_start or shift_dt > horizon_end:
            continue
        capacity = round(safe_float(shift.get("capacity_hours")) * max(capacity_multiplier, 0.0), 2)
        if capacity <= 0:
            continue
        buckets.append(
            {
                "shift_id": safe_int(shift.get("id")),
                "shift_name": shift.get("shift_name") or shift.get("work_center") or "Смена",
                "shift_date": shift.get("shift_date") or display_date(shift_dt),
                "shift_date_iso": iso_date(shift_dt),
                "work_center": shift.get("work_center") or "Без центра",
                "capacity_hours": capacity,
                "planned_hours": 0.0,
                "free_hours": capacity,
                "assignments": [],
            }
        )
    buckets.sort(key=lambda row: (row["shift_date_iso"], row["work_center"], row["shift_id"]))
    return buckets


def _schedule(requirements: list[dict], buckets: list[dict], lead_time_days: int) -> tuple[list[dict], list[dict], list[dict]]:
    bucket_by_center: dict[str, list[dict]] = {}
    for bucket in buckets:
        bucket_by_center.setdefault(bucket["work_center"], []).append(bucket)

    assignments = []
    unscheduled = []
    for req in requirements:
        remaining = safe_float(req.get("required_hours"))
        center_buckets = bucket_by_center.get(req["work_center"], [])
        if not center_buckets:
            unscheduled.append({**req, "reason": "Нет смен по рабочему центру"})
            continue
        due_dt = parse_date(req.get("due_date")) or datetime.now()
        target_dt = due_dt - timedelta(days=max(lead_time_days, 0))
        target_iso = iso_date(target_dt)
        for bucket in center_buckets:
            if remaining <= 0:
                break
            if bucket["shift_date_iso"] < datetime.now().strftime("%Y-%m-%d"):
                continue
            if bucket["free_hours"] <= 0:
                continue
            take = min(remaining, bucket["free_hours"])
            assignment = {
                "order_id": req["order_id"],
                "order_name": req["order_name"],
                "operation_name": req["operation_name"],
                "work_center": req["work_center"],
                "shift_id": bucket["shift_id"],
                "shift_name": bucket["shift_name"],
                "shift_date": bucket["shift_date"],
                "planned_hours": round(take, 2),
                "due_date": req["due_date"],
                "is_late": bucket["shift_date_iso"] > req.get("due_date_iso", "9999-12-31"),
                "is_inside_target": bucket["shift_date_iso"] <= target_iso,
            }
            bucket["assignments"].append(assignment)
            bucket["planned_hours"] = round(bucket["planned_hours"] + take, 2)
            bucket["free_hours"] = round(max(bucket["capacity_hours"] - bucket["planned_hours"], 0.0), 2)
            assignments.append(assignment)
            remaining = round(remaining - take, 2)
        if remaining > 0:
            unscheduled.append({**req, "remaining_hours": remaining, "reason": "Не хватило мощности в горизонте"})

    load_rows = []
    for bucket in buckets:
        load_percent = round((bucket["planned_hours"] / bucket["capacity_hours"]) * 100, 1) if bucket["capacity_hours"] > 0 else 0
        load_rows.append(
            {
                **bucket,
                "load_percent": load_percent,
                "risk_level": "risk" if load_percent > 100 else ("warning" if load_percent >= 85 else "ok"),
                "assignments_total": len(bucket["assignments"]),
            }
        )
    load_rows.sort(key=lambda row: (row["shift_date_iso"], row["work_center"]))
    return assignments, unscheduled, load_rows


def build_mrp_aps_plan(
    *,
    actor: dict,
    orders: list[dict],
    operations: list[dict],
    bom_items: list[dict],
    material_norms: list[dict],
    labor_norms: list[dict],
    shifts: list[dict],
    inventory_rows: list[dict],
    purchase_rows: list[dict],
    scenarios: list[dict],
    filter_rows_by_scope_fn=None,
    scenario: dict | None = None,
) -> dict:
    scenario_payload = json_load((scenario or {}).get("payload_json"), {}) if scenario else {}
    horizon_days = safe_int((scenario or {}).get("planning_horizon_days")) or safe_int(scenario_payload.get("planning_horizon_days")) or 30
    demand_multiplier = safe_float(scenario_payload.get("demand_multiplier")) or 1.0
    capacity_multiplier = safe_float(scenario_payload.get("capacity_multiplier")) or 1.0
    lead_time_days = safe_int(scenario_payload.get("lead_time_days"))
    horizon_start = datetime.now()
    horizon_end = horizon_start + timedelta(days=horizon_days)

    scoped_orders = _scope_rows(actor, orders, filter_rows_by_scope_fn)
    allowed_order_ids = {safe_int(row.get("id")) for row in scoped_orders}
    scoped_shifts = _scope_rows(actor, shifts, filter_rows_by_scope_fn)
    scoped_operations = [row for row in operations if safe_int(row.get("order_id")) in allowed_order_ids]
    scoped_bom = [row for row in bom_items if safe_int(row.get("order_id")) in allowed_order_ids]
    scoped_material_norms = [row for row in material_norms if safe_int(row.get("order_id")) in allowed_order_ids]
    scoped_labor_norms = [row for row in labor_norms if safe_int(row.get("order_id")) in allowed_order_ids]

    inventory = _inventory_by_article(inventory_rows)
    incoming = _incoming_purchase_by_article(purchase_rows)
    material_demands = _material_demand_rows(scoped_orders, scoped_material_norms, scoped_bom, demand_multiplier)
    shortages, material_plan = _shortages(material_demands, inventory, incoming)
    labor_requirements = _labor_requirements(scoped_orders, scoped_labor_norms, scoped_operations, demand_multiplier)
    buckets = _capacity_buckets(scoped_shifts, capacity_multiplier, horizon_start, horizon_end)
    assignments, unscheduled, capacity_plan = _schedule(labor_requirements, buckets, lead_time_days)

    overloaded = [row for row in capacity_plan if row.get("risk_level") == "risk"]
    late_assignments = [row for row in assignments if row.get("is_late")]
    recommendations = []
    if shortages:
        recommendations.append(f"Создать закупки/перемещения по {len(shortages)} дефицитным позициям.")
    if unscheduled:
        recommendations.append(f"Добавить смены или перенести сроки по {len(unscheduled)} операциям без мощности.")
    if late_assignments:
        recommendations.append(f"Перепланировать {len(late_assignments)} поздних назначений до контрольной даты.")
    if overloaded:
        recommendations.append(f"Разгрузить {len(overloaded)} перегруженных смен/центров.")
    if not recommendations:
        recommendations.append("План выполним в текущем горизонте без критичных дефицитов.")

    active_orders = _active_orders(scoped_orders)
    return {
        "scenario": scenario or {},
        "horizon": {"start": display_date(horizon_start), "end": display_date(horizon_end), "days": horizon_days},
        "scenarios": scenarios,
        "material_plan": material_plan[:120],
        "shortages": shortages[:80],
        "labor_requirements": labor_requirements[:120],
        "capacity_plan": capacity_plan[:120],
        "schedule_assignments": assignments[:160],
        "unscheduled_operations": unscheduled[:80],
        "recommendations": recommendations,
        "metrics": {
            "active_orders": len(active_orders),
            "material_positions": len({row.get("article") for row in material_plan if row.get("article")}),
            "shortages": len(shortages),
            "shortage_qty_total": round(sum(safe_float(row.get("shortage_qty")) for row in shortages), 2),
            "required_hours": round(sum(safe_float(row.get("required_hours")) for row in labor_requirements), 2),
            "scheduled_hours": round(sum(safe_float(row.get("planned_hours")) for row in assignments), 2),
            "unscheduled_operations": len(unscheduled),
            "late_assignments": len(late_assignments),
            "overloaded_buckets": len(overloaded),
        },
    }
