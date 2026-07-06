import time
from datetime import datetime

from database import get_connection


def _first_row_value(row, default=0):
    if row in (None, ""):
        return default
    if isinstance(row, dict):
        for value in row.values():
            return value
        return default
    try:
        return row[0]
    except Exception:
        return default


def build_analytics_deep_summary(
    actor: dict,
    *,
    get_connection,
    table_exists,
    filter_finance_rows_for_actor,
    filter_scope_rows_for_actor,
    load_finance_rows,
    normalize_spaces,
    parse_ru_date,
    period_key_for_date,
    safe_float,
    safe_int,
):
    finance_rows = filter_finance_rows_for_actor(actor, load_finance_rows())
    conn = get_connection(row_factory=True)
    try:
        purchase_rows = filter_scope_rows_for_actor(
            actor,
            [dict(row) for row in conn.execute("SELECT * FROM purchase_orders ORDER BY updated_at DESC, id DESC").fetchall()],
        )
        sales_rows = filter_scope_rows_for_actor(
            actor,
            [dict(row) for row in conn.execute("SELECT * FROM sales_documents_extended ORDER BY updated_at DESC, id DESC").fetchall()],
        )
        production_rows = filter_scope_rows_for_actor(
            actor,
            [dict(row) for row in conn.execute("SELECT * FROM production_orders ORDER BY updated_at DESC, id DESC").fetchall()],
        )
        budget_rows = filter_scope_rows_for_actor(
            actor,
            [dict(row) for row in conn.execute("SELECT * FROM finance_budgets ORDER BY period_key DESC, id DESC").fetchall()],
        )
        purchase_plan_rows = [dict(row) for row in conn.execute("SELECT * FROM purchase_plans ORDER BY period_key DESC, id DESC").fetchall()]
        service_rows = [dict(row) for row in conn.execute("SELECT * FROM service_cases ORDER BY updated_at DESC, id DESC").fetchall()]
        balance_rows = [dict(row) for row in conn.execute("SELECT * FROM stock_balances ORDER BY updated_at DESC, id DESC").fetchall()] if table_exists(conn, "stock_balances") else []
        movement_rows = [dict(row) for row in conn.execute("SELECT * FROM stock_movements ORDER BY id DESC LIMIT 2000").fetchall()] if table_exists(conn, "stock_movements") else []
        return_rows = [dict(row) for row in conn.execute("SELECT * FROM customer_returns ORDER BY updated_at DESC, id DESC").fetchall()]
    finally:
        conn.close()

    client_map: dict[int, dict] = {}
    project_revenue: dict[int, float] = {}
    purchase_cost_by_project: dict[int, float] = {}
    product_costs_by_project: dict[int, dict[str, float]] = {}

    for row in finance_rows:
        client_id = safe_int(row.get("client_id")) or -1
        entry = client_map.setdefault(
            client_id,
            {
                "client_id": safe_int(row.get("client_id")),
                "client_name": row.get("client_name") or "Без клиента",
                "incoming_paid": 0.0,
                "outgoing_paid": 0.0,
                "incoming_open": 0.0,
                "outgoing_open": 0.0,
            },
        )
        amount = safe_float(row.get("amount"))
        if row.get("kind") == "incoming":
            if row.get("status") == "paid":
                entry["incoming_paid"] += amount
            else:
                entry["incoming_open"] += amount
        else:
            if row.get("status") == "paid":
                entry["outgoing_paid"] += amount
            else:
                entry["outgoing_open"] += amount

    for row in sales_rows:
        project_id = safe_int(row.get("project_id"))
        project_revenue[project_id] = project_revenue.get(project_id, 0.0) + safe_float(row.get("amount"))

    for row in purchase_rows:
        project_id = safe_int(row.get("project_id"))
        article = normalize_spaces(row.get("item_article") or row.get("item_name") or "Без артикула") or "Без артикула"
        cost = (safe_float(row.get("qty")) or 0.0) * (safe_float(row.get("unit_price")) or 0.0)
        if not cost:
            cost = safe_float(row.get("delivered_qty")) * (safe_float(row.get("unit_price")) or safe_float(row.get("planned_unit_price")))
        purchase_cost_by_project[project_id] = purchase_cost_by_project.get(project_id, 0.0) + cost
        product_costs_by_project.setdefault(project_id, {})
        product_costs_by_project[project_id][article] = product_costs_by_project[project_id].get(article, 0.0) + cost

    product_map: dict[str, dict] = {}
    for row in purchase_rows:
        article = normalize_spaces(row.get("item_article") or row.get("item_name") or "Без артикула") or "Без артикула"
        item_name = row.get("item_name") or article
        project_id = safe_int(row.get("project_id"))
        cost = (safe_float(row.get("qty")) or 0.0) * (safe_float(row.get("unit_price")) or 0.0)
        if not cost:
            cost = safe_float(row.get("delivered_qty")) * (safe_float(row.get("unit_price")) or safe_float(row.get("planned_unit_price")))
        total_project_cost = purchase_cost_by_project.get(project_id, 0.0)
        revenue_share = 0.0
        if total_project_cost > 0.0001:
            revenue_share = project_revenue.get(project_id, 0.0) * (cost / total_project_cost)
        entry = product_map.setdefault(
            article,
            {
                "article": article,
                "item_name": item_name,
                "planned_revenue": 0.0,
                "planned_cost": 0.0,
                "purchase_qty": 0.0,
                "returned_amount": 0.0,
            },
        )
        entry["planned_cost"] += cost
        entry["planned_revenue"] += revenue_share
        entry["purchase_qty"] += safe_float(row.get("qty")) or safe_float(row.get("delivered_qty"))
    for row in return_rows:
        article = normalize_spaces(row.get("article") or row.get("item_name") or "Без артикула") or "Без артикула"
        entry = product_map.setdefault(
            article,
            {"article": article, "item_name": row.get("item_name") or article, "planned_revenue": 0.0, "planned_cost": 0.0, "purchase_qty": 0.0, "returned_amount": 0.0},
        )
        entry["returned_amount"] += safe_float(row.get("amount"))
    by_product = []
    for item in product_map.values():
        item["planned_revenue"] = round(item["planned_revenue"] - item["returned_amount"], 2)
        item["planned_cost"] = round(item["planned_cost"], 2)
        item["gross_margin"] = round(item["planned_revenue"] - item["planned_cost"], 2)
        item["purchase_qty"] = round(item["purchase_qty"], 2)
        by_product.append(item)
    by_product.sort(key=lambda row: abs(row.get("gross_margin", 0)), reverse=True)

    by_client = []
    for item in client_map.values():
        item["incoming_paid"] = round(item["incoming_paid"], 2)
        item["outgoing_paid"] = round(item["outgoing_paid"], 2)
        item["incoming_open"] = round(item["incoming_open"], 2)
        item["outgoing_open"] = round(item["outgoing_open"], 2)
        item["fact_margin"] = round(item["incoming_paid"] - item["outgoing_paid"], 2)
        item["open_exposure"] = round(item["incoming_open"] + item["outgoing_open"], 2)
        by_client.append(item)
    by_client.sort(key=lambda row: abs(row.get("fact_margin", 0)) + abs(row.get("open_exposure", 0)), reverse=True)

    ninety_days_ago = time.time() - (90 * 24 * 3600)
    inventory_turnover_map: dict[str, dict] = {}
    for row in balance_rows:
        warehouse = row.get("warehouse") or "Без склада"
        article = row.get("article") or row.get("item_name") or "Без артикула"
        key = f"{warehouse}::{article}"
        inventory_turnover_map[key] = {
            "warehouse": warehouse,
            "article": article,
            "item_name": row.get("item_name") or article,
            "current_qty": safe_float(row.get("qty")),
            "out_qty_90d": 0.0,
        }
    for row in movement_rows:
        created_at = safe_int(row.get("created_at"))
        if created_at and created_at < ninety_days_ago:
            continue
        movement_type = row.get("movement_type") or ""
        if movement_type not in {"remove", "writeoff", "inventory", "transfer"}:
            continue
        warehouse = row.get("from_warehouse") or row.get("warehouse") or "Без склада"
        article = row.get("article") or row.get("item_name") or "Без артикула"
        key = f"{warehouse}::{article}"
        bucket = inventory_turnover_map.setdefault(
            key,
            {"warehouse": warehouse, "article": article, "item_name": row.get("item_name") or article, "current_qty": 0.0, "out_qty_90d": 0.0},
        )
        bucket["out_qty_90d"] += abs(safe_float(row.get("qty")))
    inventory_turnover = []
    for item in inventory_turnover_map.values():
        avg_daily_out = item["out_qty_90d"] / 90 if item["out_qty_90d"] > 0 else 0.0
        item["turnover_ratio_90d"] = round(item["out_qty_90d"] / max(item["current_qty"], 1.0), 2) if item["current_qty"] > 0 else round(item["out_qty_90d"], 2)
        item["days_on_hand"] = round(item["current_qty"] / avg_daily_out, 1) if avg_daily_out > 0 else 999.0
        item["current_qty"] = round(item["current_qty"], 2)
        item["out_qty_90d"] = round(item["out_qty_90d"], 2)
        inventory_turnover.append(item)
    inventory_turnover.sort(key=lambda row: (row.get("days_on_hand", 999.0), -row.get("out_qty_90d", 0)), reverse=True)

    now_dt = datetime.now()
    open_service = [row for row in service_rows if row.get("status") not in {"closed", "done", "resolved"}]
    sla_breached = []
    due_soon = []
    for row in open_service:
        deadline = parse_ru_date(row.get("sla_deadline"))
        if not deadline:
            continue
        days_left = (deadline.date() - now_dt.date()).days
        payload = {
            "case_id": safe_int(row.get("id")),
            "title": row.get("title") or row.get("case_number") or "Кейс",
            "responsible": row.get("responsible") or "Не назначен",
            "status": row.get("status") or "open",
            "sla_deadline": row.get("sla_deadline") or "",
            "days_delta": days_left,
        }
        if days_left < 0:
            sla_breached.append(payload)
        elif days_left <= 2:
            due_soon.append(payload)
    sla_summary = {
        "open_total": len(open_service),
        "breached_total": len(sla_breached),
        "due_soon_total": len(due_soon),
        "breached": sla_breached[:8],
        "due_soon": due_soon[:8],
    }

    budget_plan_fact = []
    budget_period_map: dict[str, dict] = {}
    for row in budget_rows:
        period_key = row.get("period_key") or "без периода"
        bucket = budget_period_map.setdefault(period_key, {"period_key": period_key, "plan_amount": 0.0, "fact_amount": 0.0, "variance": 0.0, "lines": 0})
        bucket["plan_amount"] += safe_float(row.get("plan_amount"))
        bucket["fact_amount"] += safe_float(row.get("fact_amount"))
        bucket["lines"] += 1
    for item in budget_period_map.values():
        item["plan_amount"] = round(item["plan_amount"], 2)
        item["fact_amount"] = round(item["fact_amount"], 2)
        item["variance"] = round(item["fact_amount"] - item["plan_amount"], 2)
        budget_plan_fact.append(item)
    budget_plan_fact.sort(key=lambda row: row.get("period_key", ""), reverse=True)

    production_plan_fact = []
    for row in production_rows:
        production_plan_fact.append(
            {
                "order_id": safe_int(row.get("id")),
                "order_name": row.get("order_name") or "Заказ",
                "planned_qty": round(safe_float(row.get("planned_qty")), 2),
                "produced_qty": round(safe_float(row.get("produced_qty")), 2),
                "scrap_qty": round(safe_float(row.get("scrap_qty")), 2),
                "plan_cost": round(safe_float(row.get("planned_cost")), 2),
                "fact_cost": round(safe_float(row.get("actual_cost")), 2),
                "cost_variance": round(safe_float(row.get("actual_cost")) - safe_float(row.get("planned_cost")), 2),
                "stage": row.get("stage") or "queue",
            }
        )
    production_plan_fact.sort(key=lambda row: abs(row.get("cost_variance", 0)) + abs(row.get("planned_qty", 0) - row.get("produced_qty", 0)), reverse=True)

    purchase_fact_map: dict[str, dict] = {}
    for row in purchase_plan_rows:
        key = f"{row.get('period_key')}::{safe_int(row.get('project_id'))}::{row.get('item_article') or row.get('item_name')}"
        purchase_fact_map[key] = {
            "period_key": row.get("period_key") or "",
            "project_id": safe_int(row.get("project_id")),
            "item_article": row.get("item_article") or "",
            "item_name": row.get("item_name") or row.get("item_article") or "Позиция",
            "qty_plan": round(safe_float(row.get("qty_plan")), 2),
            "qty_fact": 0.0,
            "target_amount": round(safe_float(row.get("target_amount")), 2),
            "fact_amount": 0.0,
        }
    for row in purchase_rows:
        key = f"{period_key_for_date(row.get('expected_date'))}::{safe_int(row.get('project_id'))}::{row.get('item_article') or row.get('item_name')}"
        bucket = purchase_fact_map.setdefault(
            key,
            {
                "period_key": period_key_for_date(row.get("expected_date")),
                "project_id": safe_int(row.get("project_id")),
                "item_article": row.get("item_article") or "",
                "item_name": row.get("item_name") or row.get("item_article") or "Позиция",
                "qty_plan": 0.0,
                "qty_fact": 0.0,
                "target_amount": 0.0,
                "fact_amount": 0.0,
            },
        )
        qty_fact = safe_float(row.get("delivered_qty")) or safe_float(row.get("qty"))
        amount_fact = qty_fact * (safe_float(row.get("unit_price")) or safe_float(row.get("planned_unit_price")))
        bucket["qty_fact"] += qty_fact
        bucket["fact_amount"] += amount_fact
    purchase_plan_fact = []
    for item in purchase_fact_map.values():
        item["qty_fact"] = round(item["qty_fact"], 2)
        item["fact_amount"] = round(item["fact_amount"], 2)
        item["qty_variance"] = round(item["qty_fact"] - item["qty_plan"], 2)
        item["amount_variance"] = round(item["fact_amount"] - item["target_amount"], 2)
        purchase_plan_fact.append(item)
    purchase_plan_fact.sort(key=lambda row: abs(row.get("amount_variance", 0)) + abs(row.get("qty_variance", 0)), reverse=True)

    return {
        "metrics": {
            "clients_tracked": len(by_client),
            "products_tracked": len(by_product),
            "sla_breached": len(sla_breached),
            "budget_variance_total": round(sum(item.get("variance", 0) for item in budget_plan_fact), 2),
            "production_cost_variance_total": round(sum(item.get("cost_variance", 0) for item in production_plan_fact), 2),
            "purchase_amount_variance_total": round(sum(item.get("amount_variance", 0) for item in purchase_plan_fact), 2),
            "inventory_slow_items": len([item for item in inventory_turnover if item.get("days_on_hand", 0) >= 60]),
        },
        "by_client": by_client[:10],
        "by_product": by_product[:10],
        "inventory_turnover": inventory_turnover[:10],
        "sla_summary": sla_summary,
        "budget_plan_fact": budget_plan_fact[:10],
        "production_plan_fact": production_plan_fact[:10],
        "purchase_plan_fact": purchase_plan_fact[:10],
    }


def build_reliability_dashboard(
    actor: dict,
    *,
    get_connection,
    integration_monitoring_payload,
    list_entity_locks,
    safe_int,
    table_exists,
    today_display,
):
    monitoring = integration_monitoring_payload(180)
    locks = list_entity_locks(limit=120)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        recent_errors = [dict(row) for row in conn.execute("SELECT * FROM error_log ORDER BY created_at DESC, id DESC LIMIT 30").fetchall()] if table_exists(conn, "error_log") else []
        backups = [dict(row) for row in conn.execute("SELECT * FROM system_backups ORDER BY created_at DESC, id DESC LIMIT 20").fetchall()] if table_exists(conn, "system_backups") else []
        negative_balances = [dict(row) for row in conn.execute("SELECT * FROM stock_balances WHERE qty < 0 ORDER BY qty ASC, updated_at DESC LIMIT 20").fetchall()] if table_exists(conn, "stock_balances") else []
        broken_bank_links = [dict(row) for row in conn.execute(
            """
            SELECT bsl.*
            FROM bank_statement_lines bsl
            LEFT JOIN finance_payments fp ON fp.id = bsl.linked_payment_id
            WHERE bsl.linked_payment_id > 0 AND fp.id IS NULL
            ORDER BY bsl.updated_at DESC, bsl.id DESC
            LIMIT 20
            """
        ).fetchall()] if table_exists(conn, "bank_statement_lines") else []
        orphan_entries = [dict(row) for row in conn.execute(
            """
            SELECT ae.*
            FROM accounting_entries ae
            LEFT JOIN finance_payments fp ON fp.id = ae.source_id AND ae.source_type='finance_payment'
            WHERE ae.source_type='finance_payment' AND ae.source_id > 0 AND fp.id IS NULL
            ORDER BY ae.created_at DESC, ae.id DESC
            LIMIT 20
            """
        ).fetchall()] if table_exists(conn, "accounting_entries") else []
        orphan_links = [dict(row) for row in conn.execute(
            """
            SELECT l.*
            FROM erp_entity_links l
            LEFT JOIN erp_process_runs p ON p.id = l.process_id
            WHERE l.process_id > 0 AND p.id IS NULL
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT 20
            """
        ).fetchall()] if table_exists(conn, "erp_entity_links") else []
        broken_project_links = [dict(row) for row in conn.execute(
            """
            SELECT p.id, p.name, p.contract_id, p.object_id
            FROM projects p
            LEFT JOIN contract_master cm ON cm.id = p.contract_id
            LEFT JOIN business_objects bo ON bo.id = p.object_id
            WHERE (p.contract_id > 0 AND cm.id IS NULL) OR (p.object_id > 0 AND bo.id IS NULL)
            ORDER BY p.id DESC
            LIMIT 20
            """
        ).fetchall()]
        stale_session_rows = [dict(row) for row in conn.execute(
            "SELECT * FROM user_sessions WHERE expires_at > ? ORDER BY last_seen_at ASC, created_at ASC LIMIT 50",
            (now,),
        ).fetchall()] if table_exists(conn, "user_sessions") else []
        inventory_acts_open = safe_int(_first_row_value(conn.execute("SELECT COUNT(*) FROM inventory_acts WHERE status NOT IN ('done','closed')").fetchone(), 0)) if table_exists(conn, "inventory_acts") else 0
        discrepancy_open = safe_int(_first_row_value(conn.execute("SELECT COUNT(*) FROM supplier_discrepancy_acts WHERE status NOT IN ('done','closed')").fetchone(), 0)) if table_exists(conn, "supplier_discrepancy_acts") else 0
        overdue_production = safe_int(_first_row_value(conn.execute(
            """
            SELECT COUNT(*) FROM production_orders
            WHERE stage NOT IN ('done','closed') AND planned_finish != '' AND planned_finish < ?
            """,
            (today_display(),),
        ).fetchone(), 0))
        unreconciled_bank = safe_int(_first_row_value(conn.execute("SELECT COUNT(*) FROM bank_statement_lines WHERE status != 'reconciled'").fetchone(), 0)) if table_exists(conn, "bank_statement_lines") else 0
        active_sessions = safe_int(_first_row_value(conn.execute("SELECT COUNT(*) FROM user_sessions WHERE expires_at > ?", (now,)).fetchone(), 0)) if table_exists(conn, "user_sessions") else 0
        no_2fa_privileged = safe_int(_first_row_value(conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='approved' AND role IN ('Директор','Бухгалтерия','Юрист') AND COALESCE(two_factor_enabled, 0)=0"
        ).fetchone(), 0))
    finally:
        conn.close()

    last_backup_age_hours = None
    if backups:
        last_backup_age_hours = round((now - safe_int(backups[0].get("created_at"))) / 3600, 1)

    module_health = [
        {
            "module": "finance",
            "status": "warning" if unreconciled_bank or orphan_entries else "ok",
            "summary": f"Не сведённых строк {unreconciled_bank}, осиротевших проводок {len(orphan_entries)}",
            "issues": unreconciled_bank + len(orphan_entries),
        },
        {
            "module": "warehouse",
            "status": "critical" if negative_balances else ("warning" if inventory_acts_open or discrepancy_open else "ok"),
            "summary": f"Отрицательных остатков {len(negative_balances)}, открытых актов {inventory_acts_open + discrepancy_open}",
            "issues": len(negative_balances) + inventory_acts_open + discrepancy_open,
        },
        {
            "module": "production",
            "status": "warning" if overdue_production else "ok",
            "summary": f"Просроченных заказов {overdue_production}",
            "issues": overdue_production,
        },
        {
            "module": "integrations",
            "status": "critical" if monitoring["metrics"].get("failed", 0) or monitoring["metrics"].get("conflicts", 0) else ("warning" if monitoring["metrics"].get("stale_processing", 0) else "ok"),
            "summary": f"failed {monitoring['metrics'].get('failed', 0)} · conflicts {monitoring['metrics'].get('conflicts', 0)} · stale {monitoring['metrics'].get('stale_processing', 0)}",
            "issues": monitoring["metrics"].get("failed", 0) + monitoring["metrics"].get("conflicts", 0) + monitoring["metrics"].get("stale_processing", 0),
        },
        {
            "module": "security",
            "status": "warning" if no_2fa_privileged or locks else "ok",
            "summary": f"Активных сессий {active_sessions}, stale-lock {len([row for row in locks if safe_int(row.get('locked_at')) < now - 900])}, privileged без 2FA {no_2fa_privileged}",
            "issues": no_2fa_privileged + len([row for row in locks if safe_int(row.get('locked_at')) < now - 900]),
        },
        {
            "module": "backup",
            "status": "critical" if not backups else ("warning" if (last_backup_age_hours or 0) > 24 else "ok"),
            "summary": "Бэкапы не найдены" if not backups else f"Последний backup {last_backup_age_hours} ч назад",
            "issues": 1 if not backups else (1 if (last_backup_age_hours or 0) > 24 else 0),
        },
    ]

    integrity_issues = [
        {"code": "negative_stock", "severity": "critical", "count": len(negative_balances), "message": "Отрицательные остатки на складе", "examples": negative_balances[:5]},
        {"code": "orphan_accounting_entries", "severity": "critical", "count": len(orphan_entries), "message": "Осиротевшие бухгалтерские проводки", "examples": orphan_entries[:5]},
        {"code": "orphan_erp_links", "severity": "warning", "count": len(orphan_links), "message": "ERP-связи без процесса", "examples": orphan_links[:5]},
        {"code": "broken_bank_links", "severity": "warning", "count": len(broken_bank_links), "message": "Банковские строки со ссылкой на несуществующую оплату", "examples": broken_bank_links[:5]},
        {"code": "broken_project_links", "severity": "warning", "count": len(broken_project_links), "message": "Проекты с битой ссылкой на договор или объект", "examples": broken_project_links[:5]},
    ]
    integrity_issues = [item for item in integrity_issues if item["count"] > 0]
    critical_count = sum(1 for item in integrity_issues if item["severity"] == "critical")
    warning_count = sum(1 for item in integrity_issues if item["severity"] != "critical") + sum(1 for item in module_health if item["status"] == "warning")

    stale_locks = [row for row in locks if safe_int(row.get("locked_at")) and safe_int(row.get("locked_at")) < now - 900][:10]
    stale_sessions = [
        row for row in stale_session_rows
        if safe_int(row.get("last_seen_at") or row.get("created_at")) and safe_int(row.get("last_seen_at") or row.get("created_at")) < now - 86400
    ][:10]
    return {
        "metrics": {
            "critical_issues": critical_count + len([row for row in module_health if row["status"] == "critical"]),
            "warning_issues": warning_count,
            "failed_sync": monitoring["metrics"].get("failed", 0),
            "stale_locks": len(stale_locks),
            "recent_errors": len(recent_errors),
            "negative_stock": len(negative_balances),
        },
        "module_health": module_health,
        "integrity_issues": integrity_issues[:12],
        "recovery": {
            "stale_locks": stale_locks,
            "stale_rows": monitoring.get("stale_rows", [])[:10],
            "recent_failures": monitoring.get("recent_failures", [])[:10],
            "recent_errors": recent_errors[:10],
            "stale_sessions": stale_sessions,
            "backups": backups[:6],
        },
        "checked_at": now,
    }


def load_saved_reports(*, db_name: str, json_load, owner_email: str = "", report_type: str = ""):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    clauses = []
    params = []
    if owner_email:
        clauses.append("(owner_email=? OR scope='shared')")
        params.append(owner_email)
    if report_type:
        clauses.append("report_type=?")
        params.append(report_type)
    sql = "SELECT * FROM saved_reports"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY updated_at DESC, id DESC"
    c.execute(sql, tuple(params))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["filters"] = json_load(row.get("filters"), {})
        row["layout"] = json_load(row.get("layout"), {})
    return rows


def build_analytics_dashboard_hub(
    actor: dict,
    *,
    saved_reports: list[dict],
    finance_payload: dict,
    analytics_payload: dict,
    reliability_payload: dict | None = None,
):
    role_name = (actor or {}).get("role") or ""
    owner_email = (actor or {}).get("email") or ""
    finance_metrics = finance_payload.get("metrics") or {}
    analytics_metrics = analytics_payload.get("metrics") or {}
    reliability_metrics = (reliability_payload or {}).get("metrics") or {}

    def _role_widget(label: str, value, hint: str, dimension: str = "", value_id: int = 0, value_key: str = ""):
        return {
            "label": label,
            "value": value,
            "hint": hint,
            "drilldown": {
                "dimension": dimension,
                "value_id": value_id,
                "value": value_key,
            } if dimension else {},
        }

    private_views = []
    shared_views = []
    views_by_type: dict[str, int] = {}
    for row in saved_reports or []:
        layout = row.get("layout") or {}
        filters = row.get("filters") or {}
        target_role = layout.get("target_role") or filters.get("target_role") or ""
        tags = layout.get("tags") or filters.get("tags") or []
        item = {
            "id": row.get("id"),
            "title": row.get("title") or "ERP view",
            "report_type": row.get("report_type") or "finance_analytics",
            "scope": row.get("scope") or "private",
            "target_role": target_role,
            "dashboard_kind": layout.get("dashboard_kind") or "table",
            "is_default": int(layout.get("is_default") or 0),
            "tags": tags if isinstance(tags, list) else [],
            "description": layout.get("description") or filters.get("description") or "",
            "updated_at": row.get("updated_at") or 0,
            "owner_email": row.get("owner_email") or "",
        }
        views_by_type[item["report_type"]] = views_by_type.get(item["report_type"], 0) + 1
        if item["scope"] in {"shared", "team"} or item["target_role"]:
            shared_views.append(item)
        if item["owner_email"] == owner_email or item["scope"] == "private":
            private_views.append(item)

    role_dashboards = [
        {
            "role_name": "Директор",
            "title": "Панель управления",
            "description": "Деньги, риски, управленческая аналитика и приоритетные отклонения по компании.",
            "is_current": role_name == "Директор",
            "widgets": [
                _role_widget("P&L факт", finance_metrics.get("pnl_fact") or 0, "Управленческий итог по деньгам"),
                _role_widget("Кассовый разрыв", finance_metrics.get("cash_gap_plan") or 0, "Плановый кассовый разрыв"),
                _role_widget("Проблемы данных", reliability_metrics.get("warning_issues") or 0, "Системные и справочные замечания"),
                _role_widget("Залежалый склад", analytics_metrics.get("inventory_slow_items") or 0, "Залежалые остатки", "warehouse"),
            ],
            "recommended_report_types": ["dashboard_hub", "analytics_deep", "reliability_dashboard"],
        },
        {
            "role_name": "Бухгалтерия",
            "title": "Платежи и взаиморасчёты",
            "description": "Открытые деньги, возраст долга, юрлица, подразделения и детализация в платёжную первичку.",
            "is_current": role_name == "Бухгалтерия",
            "widgets": [
                _role_widget("Дебиторка", finance_metrics.get("receivable_open") or 0, "Открытые входящие"),
                _role_widget("Кредиторка", finance_metrics.get("payable_open") or 0, "Открытые исходящие"),
                _role_widget("Юрлица", len(finance_payload.get("by_legal_entity") or []), "Срез по юрлицам", "legal_entity"),
                _role_widget("Подразделения", len(finance_payload.get("by_business_unit") or []), "Срез по подразделениям", "business_unit"),
            ],
            "recommended_report_types": ["finance_analytics", "analytics_drilldown", "dashboard_hub"],
        },
        {
            "role_name": "Менеджер",
            "title": "Продажи и клиенты",
            "description": "Клиентская маржинальность, задолженность клиентов и ролевые срезы по клиентам.",
            "is_current": role_name == "Менеджер",
            "widgets": [
                _role_widget("Клиенты", analytics_metrics.get("clients_tracked") or 0, "Клиентская аналитика", "client"),
                _role_widget("Сервис просрочен", analytics_metrics.get("sla_breached") or 0, "Просроченные клиентские кейсы", "sla"),
                _role_widget("Личные витрины", len(private_views), "Личные аналитические витрины"),
                _role_widget("Общие витрины", len(shared_views), "Командные аналитические панели"),
            ],
            "recommended_report_types": ["analytics_deep", "dashboard_hub"],
        },
        {
            "role_name": "Склад и закупки",
            "title": "Склад и снабжение",
            "description": "Склады, продуктовая аналитика, залежалые остатки и план-факт закупок.",
            "is_current": role_name == "Склад и закупки",
            "widgets": [
                _role_widget("Склады", len(finance_payload.get("warehouse_turnover") or []), "Оборот и проблемные склады", "warehouse"),
                _role_widget("Продукты", analytics_metrics.get("products_tracked") or 0, "Продуктовая аналитика", "product"),
                _role_widget("Отклонение закупок", analytics_metrics.get("purchase_amount_variance_total") or 0, "Отклонение закупок"),
                _role_widget("Залежалый склад", analytics_metrics.get("inventory_slow_items") or 0, "Залежалые позиции", "warehouse"),
            ],
            "recommended_report_types": ["analytics_deep", "dashboard_hub"],
        },
        {
            "role_name": "Производство и ОТК",
            "title": "Контроль производства",
            "description": "Выпуск, отклонение себестоимости, незавершённое производство и норматив-факт по заказам.",
            "is_current": role_name == "Производство и ОТК",
            "widgets": [
                _role_widget("Отклонение себестоимости", analytics_metrics.get("production_cost_variance_total") or 0, "Отклонение себестоимости"),
                _role_widget("Заказы", len(analytics_payload.get("production_plan_fact") or []), "Заказы в план-факте", "production_order"),
                _role_widget("Предупреждения", reliability_metrics.get("warning_issues") or 0, "Системные сигналы"),
                _role_widget("Сохранённые панели", len(shared_views), "Общие производственные витрины"),
            ],
            "recommended_report_types": ["analytics_deep", "reliability_dashboard", "dashboard_hub"],
        },
        {
            "role_name": "Операционный центр",
            "title": "Ops monitoring",
            "description": "Monitoring, recovery и role-based runbooks по интеграциям и надёжности.",
            "is_current": role_name in {"Директор", "Бухгалтерия", "Менеджер"},
            "widgets": [
                _role_widget("Failed sync", reliability_metrics.get("failed_sync") or 0, "Проблемы интеграций"),
                _role_widget("Integrity", reliability_metrics.get("critical_issues") or 0, "Критичные integrity issues"),
                _role_widget("Saved types", len(views_by_type), "Типы сохранённых BI-срезов"),
                _role_widget("Role dashboards", 6, "Наборы витрин по ролям"),
            ],
            "recommended_report_types": ["operations_monitoring", "reliability_dashboard", "dashboard_hub"],
        },
    ]
    return {
        "current_role": role_name,
        "saved_views": {
            "private": private_views[:12],
            "shared": shared_views[:12],
            "by_type": [{"report_type": key, "count": value} for key, value in sorted(views_by_type.items(), key=lambda item: item[0])],
        },
        "role_dashboards": role_dashboards,
        "metrics": {
            "saved_private_total": len(private_views),
            "saved_shared_total": len(shared_views),
            "saved_types_total": len(views_by_type),
            "role_dashboards_total": len(role_dashboards),
        },
    }


def build_analytics_drilldown(
    actor: dict,
    *,
    dimension: str,
    value: str = "",
    value_id: int = 0,
    limit: int = 50,
    get_connection,
    table_exists,
    filter_finance_rows_for_actor,
    filter_scope_rows_for_actor,
    load_finance_rows,
    safe_float,
    safe_int,
    normalize_spaces,
):
    dimension = (dimension or "").strip().lower()
    value = (value or "").strip()
    limit = max(1, min(int(limit or 50), 200))
    rows = []
    summary = {}
    finance_rows = filter_finance_rows_for_actor(actor, load_finance_rows())
    conn = get_connection(row_factory=True)
    try:
        purchase_rows = filter_scope_rows_for_actor(actor, [dict(row) for row in conn.execute("SELECT * FROM purchase_orders ORDER BY updated_at DESC, id DESC").fetchall()])
        sales_rows = filter_scope_rows_for_actor(actor, [dict(row) for row in conn.execute("SELECT * FROM sales_documents_extended ORDER BY updated_at DESC, id DESC").fetchall()])
        production_rows = filter_scope_rows_for_actor(actor, [dict(row) for row in conn.execute("SELECT * FROM production_orders ORDER BY updated_at DESC, id DESC").fetchall()])
        service_rows = filter_scope_rows_for_actor(actor, [dict(row) for row in conn.execute("SELECT * FROM service_cases ORDER BY updated_at DESC, id DESC").fetchall()])
        budget_rows = filter_scope_rows_for_actor(actor, [dict(row) for row in conn.execute("SELECT * FROM finance_budgets ORDER BY period_key DESC, id DESC").fetchall()])
        return_rows = [dict(row) for row in conn.execute("SELECT * FROM customer_returns ORDER BY updated_at DESC, id DESC").fetchall()]
        balance_rows = [dict(row) for row in conn.execute("SELECT * FROM stock_balances ORDER BY updated_at DESC, id DESC").fetchall()] if table_exists(conn, "stock_balances") else []
        movement_rows = [dict(row) for row in conn.execute("SELECT * FROM stock_movements ORDER BY id DESC LIMIT 3000").fetchall()] if table_exists(conn, "stock_movements") else []
        operation_rows = [dict(row) for row in conn.execute("SELECT * FROM production_operations ORDER BY updated_at DESC, id DESC").fetchall()] if table_exists(conn, "production_operations") else []
    finally:
        conn.close()

    if dimension == "client":
        client_id = safe_int(value_id)
        target_name = normalize_spaces(value)
        for row in finance_rows:
            if not ((client_id and safe_int(row.get("client_id")) == client_id) or (target_name and normalize_spaces(row.get("client_name")) == target_name)):
                continue
            rows.append({"entity_type": "finance_payment", "entity_id": safe_int(row.get("id")), "title": row.get("title") or "Платёж", "meta": f"{row.get('kind') or 'payment'} · {row.get('status') or 'draft'}", "amount": round(safe_float(row.get("amount")), 2), "date": row.get("due_date") or row.get("paid_date") or "", "status": row.get("status") or "", "navigate_to": "finance"})
        for row in sales_rows:
            if client_id and safe_int(row.get("client_id")) == client_id:
                rows.append({"entity_type": "sales_document", "entity_id": safe_int(row.get("id")), "title": row.get("doc_number") or row.get("doc_type") or "Реализация", "meta": f"{row.get('shipment_status') or 'not_shipped'} · {row.get('payment_status') or 'planned'}", "amount": round(safe_float(row.get("amount")), 2), "date": row.get("doc_date") or "", "status": row.get("status") or "", "navigate_to": "sales"})
        for row in return_rows:
            if client_id and safe_int(row.get("client_id")) == client_id:
                rows.append({"entity_type": "customer_return", "entity_id": safe_int(row.get("id")), "title": row.get("return_number") or row.get("item_name") or "Возврат", "meta": row.get("reason") or "Возврат клиента", "amount": round(safe_float(row.get("amount")), 2), "date": "", "status": row.get("status") or "", "navigate_to": "sales"})
        for row in service_rows:
            if client_id and safe_int(row.get("client_id")) == client_id:
                rows.append({"entity_type": "service_case", "entity_id": safe_int(row.get("id")), "title": row.get("title") or row.get("case_number") or "Сервис", "meta": row.get("responsible") or "Не назначен", "amount": 0.0, "date": row.get("sla_deadline") or "", "status": row.get("status") or "", "navigate_to": "service"})
        summary = {"rows_total": len(rows), "total_amount": round(sum(safe_float(item.get("amount")) for item in rows), 2)}
    elif dimension == "product":
        target_key = normalize_spaces(value)
        for row in purchase_rows:
            if normalize_spaces(row.get("item_article") or row.get("item_name")) != target_key:
                continue
            qty = safe_float(row.get("delivered_qty")) or safe_float(row.get("qty"))
            unit_price = safe_float(row.get("unit_price")) or safe_float(row.get("planned_unit_price"))
            rows.append({"entity_type": "purchase_order", "entity_id": safe_int(row.get("id")), "title": row.get("item_name") or row.get("item_article") or "Закупка", "meta": f"{row.get('supplier') or 'Поставщик?'} · qty {round(qty, 2)}", "amount": round(qty * unit_price, 2), "date": row.get("expected_date") or "", "status": row.get("status") or "", "navigate_to": "supply"})
        for row in return_rows:
            if normalize_spaces(row.get("article") or row.get("item_name")) == target_key:
                rows.append({"entity_type": "customer_return", "entity_id": safe_int(row.get("id")), "title": row.get("item_name") or row.get("article") or "Возврат", "meta": row.get("reason") or "Возврат клиента", "amount": round(safe_float(row.get("amount")), 2), "date": "", "status": row.get("status") or "", "navigate_to": "sales"})
        for row in balance_rows:
            if normalize_spaces(row.get("article") or row.get("item_name")) == target_key:
                rows.append({"entity_type": "stock_balance", "entity_id": safe_int(row.get("id")), "title": row.get("item_name") or row.get("article") or "Остаток", "meta": f"{row.get('warehouse') or 'Склад?'} / {row.get('bin_code') or 'ячейка?'}", "amount": round(safe_float(row.get("qty")), 2), "date": "", "status": "balance", "navigate_to": "nomenclature"})
        for row in movement_rows:
            if normalize_spaces(row.get("article") or row.get("item_name")) == target_key:
                rows.append({"entity_type": "stock_movement", "entity_id": safe_int(row.get("id")), "title": row.get("item_name") or row.get("article") or "Движение", "meta": f"{row.get('movement_type') or 'move'} · {row.get('from_warehouse') or ''} → {row.get('to_warehouse') or ''}", "amount": round(safe_float(row.get("qty")), 2), "date": "", "status": row.get("movement_type") or "", "navigate_to": "nomenclature"})
        summary = {"rows_total": len(rows)}
    elif dimension == "warehouse":
        target_key = normalize_spaces(value)
        for row in balance_rows:
            if normalize_spaces(row.get("warehouse")) == target_key:
                rows.append({"entity_type": "stock_balance", "entity_id": safe_int(row.get("id")), "title": row.get("item_name") or row.get("article") or "Остаток", "meta": f"{row.get('bin_code') or 'ячейка?'} · qty {round(safe_float(row.get('qty')), 2)}", "amount": round(safe_float(row.get("qty")), 2), "date": "", "status": "balance", "navigate_to": "nomenclature"})
        for row in movement_rows:
            if normalize_spaces(row.get("from_warehouse")) == target_key or normalize_spaces(row.get("to_warehouse")) == target_key:
                rows.append({"entity_type": "stock_movement", "entity_id": safe_int(row.get("id")), "title": row.get("item_name") or row.get("article") or "Движение", "meta": f"{row.get('movement_type') or 'move'} · {row.get('from_warehouse') or ''} → {row.get('to_warehouse') or ''}", "amount": round(safe_float(row.get("qty")), 2), "date": "", "status": row.get("movement_type") or "", "navigate_to": "nomenclature"})
        summary = {"rows_total": len(rows)}
    elif dimension in {"legal_entity", "business_unit", "treasury_article"}:
        for row in finance_rows:
            matched = False
            if dimension == "legal_entity":
                matched = (value_id and safe_int(row.get("legal_entity_id")) == safe_int(value_id)) or (value and normalize_spaces(row.get("legal_entity_name")) == normalize_spaces(value))
            elif dimension == "business_unit":
                matched = (value_id and safe_int(row.get("business_unit_id")) == safe_int(value_id)) or (value and normalize_spaces(row.get("business_unit_name")) == normalize_spaces(value))
            else:
                matched = value and normalize_spaces(row.get("treasury_article_name")) == normalize_spaces(value)
            if matched:
                rows.append({"entity_type": "finance_payment", "entity_id": safe_int(row.get("id")), "title": row.get("title") or "Платёж", "meta": f"{row.get('client_name') or 'Без клиента'} · {row.get('kind') or 'payment'}", "amount": round(safe_float(row.get("amount")), 2), "date": row.get("due_date") or row.get("paid_date") or "", "status": row.get("status") or "", "navigate_to": "finance"})
        summary = {"rows_total": len(rows), "total_amount": round(sum(safe_float(item.get("amount")) for item in rows), 2)}
    elif dimension == "budget_period":
        for row in budget_rows:
            if value and (row.get("period_key") or "") != value:
                continue
            rows.append({"entity_type": "finance_budget", "entity_id": safe_int(row.get("id")), "title": row.get("article_name") or "Budget line", "meta": row.get("budget_type") or "pnl", "amount": round(safe_float(row.get("fact_amount")) - safe_float(row.get("plan_amount")), 2), "date": row.get("period_key") or "", "status": row.get("status") or "", "navigate_to": "finance"})
        summary = {"rows_total": len(rows), "variance_total": round(sum(safe_float(item.get("amount")) for item in rows), 2)}
    elif dimension == "production_order":
        target_id = safe_int(value_id)
        matched_order_ids = {
            safe_int(row.get("id"))
            for row in production_rows
            if safe_int(row.get("id")) == target_id or (value and normalize_spaces(row.get("order_name")) == normalize_spaces(value))
        }
        for row in production_rows:
            if safe_int(row.get("id")) in matched_order_ids:
                rows.append({"entity_type": "production_order", "entity_id": safe_int(row.get("id")), "title": row.get("order_name") or "Заказ", "meta": f"{row.get('stage') or 'queue'} · {row.get('responsible') or 'без ответственного'}", "amount": round(safe_float(row.get("actual_cost")) - safe_float(row.get("planned_cost")), 2), "date": row.get("planned_finish") or "", "status": row.get("stage") or "", "navigate_to": "production"})
        for row in operation_rows:
            if safe_int(row.get("order_id")) in matched_order_ids:
                rows.append({"entity_type": "production_operation", "entity_id": safe_int(row.get("id")), "title": row.get("operation_name") or "Операция", "meta": f"{row.get('work_center') or 'центр?'} · {row.get('status') or 'planned'}", "amount": round(safe_float(row.get("actual_hours")) - safe_float(row.get("planned_hours")), 2), "date": row.get("finished_at") or row.get("started_at") or "", "status": row.get("status") or "", "navigate_to": "production"})
        summary = {"rows_total": len(rows)}
    elif dimension == "sla":
        for row in service_rows:
            if row.get("status") in {"closed", "done", "resolved"}:
                continue
            rows.append({"entity_type": "service_case", "entity_id": safe_int(row.get("id")), "title": row.get("title") or row.get("case_number") or "Сервис", "meta": f"{row.get('responsible') or 'не назначен'} · deadline {row.get('sla_deadline') or '—'}", "amount": 0.0, "date": row.get("sla_deadline") or "", "status": row.get("status") or "", "navigate_to": "service"})
        summary = {"rows_total": len(rows)}

    return {
        "dimension": dimension,
        "label": value or (str(value_id) if value_id else dimension),
        "summary": summary,
        "rows": rows[:limit],
    }


def run_saved_report_payload(
    report: dict,
    actor: dict,
    *,
    finance_analytics_fn,
    analytics_deep_fn,
    dashboard_hub_fn,
    analytics_drilldown_fn,
    integration_monitoring_fn,
    operations_monitoring_fn,
    reliability_dashboard_fn,
):
    report_type = report.get("report_type") or "finance_analytics"
    if report_type == "finance_analytics":
        return finance_analytics_fn(actor)
    if report_type == "analytics_deep":
        return analytics_deep_fn(actor)
    if report_type == "dashboard_hub":
        return dashboard_hub_fn(actor)
    if report_type == "analytics_drilldown":
        filters = report.get("filters") or {}
        return analytics_drilldown_fn(
            actor,
            filters.get("dimension") or filters.get("metric") or "",
            filters.get("value") or "",
            filters.get("value_id") or 0,
            filters.get("limit") or 50,
        )
    if report_type == "integration_monitoring":
        return integration_monitoring_fn(120)
    if report_type == "operations_monitoring":
        return operations_monitoring_fn(actor)
    if report_type == "reliability_dashboard":
        return reliability_dashboard_fn(actor)
    return {"error": "unsupported_report_type"}


def build_operations_monitoring(
    actor: dict,
    *,
    db_name: str,
    filter_rows_by_scope,
    integration_monitoring_payload,
    list_entity_locks,
    load_reconciliation_runs,
    reliability_dashboard_payload,
):
    monitoring = integration_monitoring_payload(120)
    locks = list_entity_locks(limit=80)
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT bsl.*, ba.name AS bank_account_name, ba.legal_entity_id, 0 AS business_unit_id, fp.title AS payment_title, COALESCE(cl.name, '') AS client_name
        FROM bank_statement_lines bsl
        LEFT JOIN bank_accounts ba ON ba.id = bsl.bank_account_id
        LEFT JOIN finance_payments fp ON fp.id = bsl.linked_payment_id
        LEFT JOIN clients cl ON cl.id = bsl.client_id
        WHERE bsl.status != 'reconciled'
        ORDER BY bsl.created_at DESC, bsl.id DESC
        LIMIT 30
        """
    )
    bank_lines = filter_rows_by_scope(actor, [dict(row) for row in c.fetchall()])
    c.execute(
        """
        SELECT tc.*, ta.line_name, COALESCE(cl.name, '') AS client_name, COALESCE(p.name, '') AS project_name, COALESCE(p.contract, '') AS project_contract
        FROM telephony_calls tc
        LEFT JOIN telephony_accounts ta ON ta.id = tc.account_id
        LEFT JOIN clients cl ON cl.id = tc.client_id
        LEFT JOIN projects p ON p.id = tc.project_id
        WHERE tc.status IN ('missed', 'failed')
        ORDER BY tc.created_at DESC, tc.id DESC
        LIMIT 30
        """
    )
    telephony_rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return {
        "integration": monitoring,
        "locks": locks,
        "bank_unreconciled": bank_lines,
        "missed_calls": telephony_rows,
        "reconciliation_runs": load_reconciliation_runs(10),
        "reliability": reliability_dashboard_payload(actor),
    }
