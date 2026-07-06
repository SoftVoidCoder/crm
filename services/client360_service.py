from database import get_connection


def build_client_dossier(
    *,
    actor: dict,
    client_id: int,
    db_name: str,
    can_access_project,
    filter_rows_by_scope,
    init_claims_table,
    init_courts_table,
    json_load,
    load_epl_waybills_for_links,
    load_finance_rows,
    load_production_rows,
    load_purchase_rows,
    load_sales_rows,
    load_service_cases,
    normalize_match,
    project_payload,
    safe_float,
    safe_int,
    table_exists,
):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM clients WHERE id=?", (client_id,))
    client = c.fetchone()
    if not client:
        conn.close()
        return {"error": "not_found"}

    client_data = dict(client)
    client_name = normalize_match(client_data.get("name", ""))

    c.execute("SELECT * FROM contacts WHERE client_id=? ORDER BY name ASC", (client_id,))
    contacts = [dict(row) for row in c.fetchall()]

    c.execute("SELECT * FROM projects ORDER BY id DESC")
    projects = []
    for row in c.fetchall():
        project = project_payload(dict(row))
        if not can_access_project(actor, project):
            continue
        if client_name and client_name in normalize_match(project.get("client", "")):
            projects.append(project)

    project_ids = {project["id"] for project in projects}

    finance_rows = [row for row in load_finance_rows() if int(row.get("client_id") or 0) == client_id]
    purchases = [row for row in load_purchase_rows() if int(row.get("client_id") or 0) == client_id or int(row.get("project_id") or 0) in project_ids]
    sales = [row for row in load_sales_rows() if int(row.get("client_id") or 0) == client_id or int(row.get("project_id") or 0) in project_ids]
    production = [row for row in load_production_rows() if int(row.get("client_id") or 0) == client_id or int(row.get("project_id") or 0) in project_ids]
    service_cases = [row for row in load_service_cases() if int(row.get("client_id") or 0) == client_id or int(row.get("project_id") or 0) in project_ids]
    epl_waybills = load_epl_waybills_for_links(project_ids, client_id)

    sales_quotes = []
    if table_exists(conn, "sales_quotes"):
        c.execute(
            """
            SELECT *
            FROM sales_quotes
            WHERE client_id=?
            ORDER BY updated_at DESC, id DESC
            """,
            (client_id,),
        )
        sales_quotes = [dict(row) for row in c.fetchall()]

    client_terms = []
    if table_exists(conn, "client_sales_terms"):
        c.execute(
            """
            SELECT cst.*, COALESCE(pl.name, '') AS price_list_name
            FROM client_sales_terms cst
            LEFT JOIN price_lists pl ON pl.id = cst.price_list_id
            WHERE cst.client_id=?
            ORDER BY cst.updated_at DESC, cst.id DESC
            """,
            (client_id,),
        )
        client_terms = [dict(row) for row in c.fetchall()]

    supplier_names = sorted({
        (row.get("supplier") or "").strip()
        for row in purchases
        if (row.get("supplier") or "").strip()
    })
    supplier_registry = []
    if supplier_names and table_exists(conn, "supplier_registry"):
        placeholders = ",".join("?" for _ in supplier_names)
        c.execute(
            f"""
            SELECT *
            FROM supplier_registry
            WHERE supplier_name IN ({placeholders})
            ORDER BY rating DESC, supplier_name ASC
            """,
            supplier_names,
        )
        supplier_registry = [dict(row) for row in c.fetchall()]

    bank_lines = []
    if table_exists(conn, "bank_statement_lines"):
        c.execute(
            """
            SELECT bsl.*, COALESCE(ba.name, '') AS bank_account_name, COALESCE(ba.legal_entity_id, 0) AS legal_entity_id,
                   0 AS business_unit_id, COALESCE(fp.title, '') AS payment_title
            FROM bank_statement_lines bsl
            LEFT JOIN bank_accounts ba ON ba.id = bsl.bank_account_id
            LEFT JOIN finance_payments fp ON fp.id = bsl.linked_payment_id
            WHERE bsl.client_id=?
            ORDER BY bsl.line_date DESC, bsl.id DESC
            LIMIT 20
            """,
            (client_id,),
        )
        bank_lines = filter_rows_by_scope(actor, [dict(row) for row in c.fetchall()])

    telephony_calls = []
    if table_exists(conn, "telephony_calls"):
        c.execute(
            """
            SELECT tc.*, COALESCE(ta.line_name, '') AS line_name
            FROM telephony_calls tc
            LEFT JOIN telephony_accounts ta ON ta.id = tc.account_id
            WHERE tc.client_id=? OR tc.project_id IN (
                SELECT id FROM projects
                WHERE id IN ({project_ids_placeholder})
            )
            ORDER BY tc.call_at DESC, tc.id DESC
            LIMIT 20
            """.replace(
                "{project_ids_placeholder}",
                ",".join("?" for _ in project_ids) if project_ids else "0",
            ),
            (client_id, *project_ids) if project_ids else (client_id,),
        )
        telephony_calls = [dict(row) for row in c.fetchall()]

    c.execute("SELECT * FROM documents ORDER BY id DESC")
    documents = []
    for row in c.fetchall():
        item = dict(row)
        if item.get("project_id") in project_ids or client_name in normalize_match(item.get("correspondent", "")):
            documents.append(item)

    init_claims_table()
    init_courts_table()
    c.execute("SELECT * FROM claims ORDER BY id DESC")
    claims = []
    for row in c.fetchall():
        item = dict(row)
        if item.get("proj_id") in project_ids or client_name in normalize_match(item.get("addressee", "")) or client_name in normalize_match(item.get("initiator", "")):
            claims.append(item)

    c.execute("SELECT * FROM court_cases ORDER BY id DESC")
    court_cases = []
    for row in c.fetchall():
        item = dict(row)
        if item.get("proj_id") in project_ids or client_name in normalize_match(item.get("plaintiff", "")) or client_name in normalize_match(item.get("defendant", "")):
            court_cases.append(item)
    conn.close()

    active_projects = [project for project in projects if project.get("status") == "active"]
    total_revenue = sum(safe_float(project.get("budget")) for project in projects)
    total_costs = sum(safe_float(project.get("costs")) for project in projects)
    receivable = sum(safe_float(row.get("amount")) for row in finance_rows if row.get("kind") == "incoming" and row.get("status") != "paid")
    payable = sum(safe_float(row.get("amount")) for row in finance_rows if row.get("kind") == "outgoing" and row.get("status") != "paid")
    purchases_total = sum(safe_float(row.get("total_amount")) for row in purchases)
    quotes_total = sum(safe_float(row.get("amount")) for row in sales_quotes)
    bank_turnover = sum(safe_float(row.get("amount")) for row in bank_lines)
    max_discount = max((safe_float(row.get("discount_percent")) for row in client_terms), default=0)
    epl_active = [row for row in epl_waybills if row.get("status") in {"ready", "on_route", "returned"}]
    epl_ready = [row for row in epl_waybills if row.get("integration_status") == "ready"]

    timeline = []
    for project in projects[:6]:
        timeline.append({
            "type": "project",
            "title": project.get("name", "Проект"),
            "meta": f"Договор {project.get('contract', '—')} · Статус {project.get('status', '—')}",
            "time": "",
        })
    for payment in finance_rows[:6]:
        timeline.append({
            "type": "finance",
            "title": payment.get("title", "Финансовая операция"),
            "meta": f"{'Входящий' if payment.get('kind') == 'incoming' else 'Исходящий'} · {int(safe_float(payment.get('amount'))):,} ₽".replace(",", " "),
            "time": payment.get("due_date") or payment.get("paid_date") or "",
        })
    for quote in sales_quotes[:4]:
        timeline.append({
            "type": "quote",
            "title": quote.get("title", "Коммерческое предложение"),
            "meta": f"{quote.get('quote_number', 'без номера')} · {quote.get('stage', 'draft')}",
            "time": quote.get("valid_until") or "",
        })
    for document in documents[:4]:
        timeline.append({
            "type": "document",
            "title": document.get("subject", "Документ"),
            "meta": f"{document.get('type', 'Документ')} · {document.get('number', '—')}",
            "time": document.get("d_date") or "",
        })
    for item in purchases[:4]:
        timeline.append({
            "type": "purchase",
            "title": item.get("item_name", "Закупка"),
            "meta": f"{item.get('supplier', 'Поставщик')} · {item.get('status', '—')}",
            "time": item.get("expected_date") or item.get("received_date") or "",
        })
    for item in epl_waybills[:4]:
        timeline.append({
            "type": "epl",
            "title": item.get("number", "ЭПЛ"),
            "meta": f"{item.get('route_text', 'Маршрут не указан')} · {item.get('status', 'draft')} · 1С {item.get('integration_status', 'draft')}",
            "time": item.get("shift_date") or "",
        })
    for item in service_cases[:4]:
        timeline.append({
            "type": "service",
            "title": item.get("title", "Сервисный кейс"),
            "meta": f"{item.get('status', '—')} · {item.get('case_type', 'service')}",
            "time": item.get("sla_deadline") or "",
        })
    for call in telephony_calls[:4]:
        timeline.append({
            "type": "call",
            "title": call.get("contact_name") or call.get("phone_number") or "Звонок",
            "meta": f"{call.get('direction', 'call')} · {call.get('status', 'answered')} · {call.get('line_name', 'линия')}",
            "time": call.get("call_at") or "",
        })

    return {
        "client": client_data,
        "contacts": contacts,
        "projects": projects,
        "finance": finance_rows,
        "sales_quotes": sales_quotes[:12],
        "client_terms": client_terms[:12],
        "supplier_registry": supplier_registry[:12],
        "bank_lines": bank_lines[:12],
        "telephony_calls": telephony_calls[:12],
        "purchases": purchases[:12],
        "sales": sales[:12],
        "production": production[:12],
        "epl_waybills": epl_waybills[:12],
        "service_cases": service_cases[:12],
        "documents": documents[:12],
        "claims": claims[:12],
        "court_cases": court_cases[:12],
        "timeline": timeline[:12],
        "metrics": {
            "projects_total": len(projects),
            "active_projects": len(active_projects),
            "revenue_total": round(total_revenue, 2),
            "costs_total": round(total_costs, 2),
            "receivable_open": round(receivable, 2),
            "payable_open": round(payable, 2),
            "purchases_total": round(purchases_total, 2),
            "quotes_total": round(quotes_total, 2),
            "discount_max": round(max_discount, 2),
            "bank_turnover": round(bank_turnover, 2),
            "calls_total": len(telephony_calls),
            "epl_total": len(epl_waybills),
            "epl_active": len(epl_active),
            "epl_ready": len(epl_ready),
            "service_open": len([row for row in service_cases if row.get("status") in {"open", "in_work"}]),
        },
    }
