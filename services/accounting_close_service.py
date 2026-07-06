import json
from datetime import datetime

from services.accounting_register_service import (
    period_close_register_checks,
    period_register_summary,
    rebuild_registers_for_period,
    register_accounting_entry_by_id,
)


CLOSE_ENTRY_SOURCES = ("accounting_close_vat", "accounting_close_profit_tax")
RECONCILIATION_SOURCE_TABLES = {
    "sales_document": "sales_documents_extended",
    "purchase_order": "purchase_orders",
    "production_order": "production_orders",
    "manual_operation": "accounting_manual_operations",
    "debt_adjustment": "accounting_debt_adjustments",
    "cash_operation": "cash_operations",
    "bank_statement": "bank_statement_lines",
    "finance_payment": "finance_payments",
}


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


def _json_load(raw_value, default):
    if raw_value in (None, ""):
        return default
    try:
        return json.loads(raw_value)
    except Exception:
        return default


def _row_dicts(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public' AND table_name=?
        """,
        (table_name,),
    ).fetchone()
    return bool(row)


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


def _period_title(period_key: str) -> str:
    try:
        dt = datetime.strptime(f"{period_key}-01", "%Y-%m-%d")
    except ValueError:
        return period_key
    return dt.strftime("%m.%Y")


def _scope_rows(actor: dict | None, rows: list[dict], filter_rows_by_scope_fn):
    if not actor or not filter_rows_by_scope_fn:
        return rows
    return filter_rows_by_scope_fn(actor, rows, "legal_entity_id", "business_unit_id")


def _ensure_period(conn, period_key: str):
    row = conn.execute("SELECT id FROM accounting_periods WHERE period_key=?", (period_key,)).fetchone()
    if row:
        return
    now = int(datetime.now().timestamp())
    conn.execute(
        """
        INSERT INTO accounting_periods (period_key, status, opened_at, closed_at, closed_by, comment)
        VALUES (?, 'open', ?, 0, '', '')
        """,
        (period_key, now),
    )


def _load_period_row(conn, period_key: str) -> dict:
    _ensure_period(conn, period_key)
    row = conn.execute("SELECT * FROM accounting_periods WHERE period_key=?", (period_key,)).fetchone()
    return dict(row) if row else {}


def _closing_net_by_account(entries: list[dict]) -> dict[str, float]:
    balances: dict[str, float] = {}
    for row in entries:
        amount = _safe_float(row.get("amount"))
        debit = str(row.get("account_debit") or "").strip()
        credit = str(row.get("account_credit") or "").strip()
        if debit:
            balances[debit] = balances.get(debit, 0.0) + amount
        if credit:
            balances[credit] = balances.get(credit, 0.0) - amount
    return {code: round(value, 2) for code, value in balances.items() if code}


def _trial_balance_rows(entries_before: list[dict], entries_period: list[dict], account_names: dict[str, str]) -> list[dict]:
    opening = _closing_net_by_account(entries_before)
    turnover_debit: dict[str, float] = {}
    turnover_credit: dict[str, float] = {}
    for row in entries_period:
        amount = round(_safe_float(row.get("amount")), 2)
        debit = str(row.get("account_debit") or "").strip()
        credit = str(row.get("account_credit") or "").strip()
        if debit:
            turnover_debit[debit] = turnover_debit.get(debit, 0.0) + amount
        if credit:
            turnover_credit[credit] = turnover_credit.get(credit, 0.0) + amount

    rows = []
    for code in sorted(set(opening) | set(turnover_debit) | set(turnover_credit)):
        open_balance = round(opening.get(code, 0.0), 2)
        debit_total = round(turnover_debit.get(code, 0.0), 2)
        credit_total = round(turnover_credit.get(code, 0.0), 2)
        close_balance = round(open_balance + debit_total - credit_total, 2)
        rows.append(
            {
                "account_code": code,
                "account_name": account_names.get(code, ""),
                "opening_debit": open_balance if open_balance > 0 else 0.0,
                "opening_credit": abs(open_balance) if open_balance < 0 else 0.0,
                "turnover_debit": debit_total,
                "turnover_credit": credit_total,
                "closing_debit": close_balance if close_balance > 0 else 0.0,
                "closing_credit": abs(close_balance) if close_balance < 0 else 0.0,
                "net_balance": close_balance,
            }
        )
    return rows


def _balance_sheet_lines_from_trial(rows: list[dict]) -> list[dict]:
    balances = {row.get("account_code"): _safe_float(row.get("net_balance")) for row in rows}
    receivables = round(sum(value for code, value in balances.items() if str(code).startswith("62") and value > 0), 2)
    payables = round(abs(sum(value for code, value in balances.items() if str(code).startswith("60") and value < 0)), 2)
    inventory = round(sum(value for code, value in balances.items() if str(code).startswith(("10", "41", "43")) and value > 0), 2)
    vat_asset = round(sum(value for code, value in balances.items() if str(code).startswith("19") and value > 0), 2)
    vat_due = round(abs(sum(value for code, value in balances.items() if str(code).startswith("68.02") and value < 0)), 2)
    income_tax_due = round(abs(sum(value for code, value in balances.items() if str(code).startswith("68.04") and value < 0)), 2)
    cash = round(sum(value for code, value in balances.items() if str(code).startswith(("50", "51", "52", "55", "57")) and value > 0), 2)
    equity = round(sum(value for code, value in balances.items() if str(code).startswith(("80", "84", "99"))), 2)
    return [
        {"line_name": "Денежные средства", "section": "assets", "value": cash},
        {"line_name": "Запасы", "section": "assets", "value": inventory},
        {"line_name": "Дебиторская задолженность", "section": "assets", "value": receivables},
        {"line_name": "НДС к вычету", "section": "assets", "value": vat_asset},
        {"line_name": "Кредиторская задолженность", "section": "liabilities", "value": payables},
        {"line_name": "НДС к уплате", "section": "liabilities", "value": vat_due},
        {"line_name": "Налог на прибыль", "section": "liabilities", "value": income_tax_due},
        {"line_name": "Собственный капитал", "section": "equity", "value": equity},
    ]


def _pnl_rows(entries_period: list[dict], income_tax_amount: float) -> list[dict]:
    sales_revenue = round(sum(_safe_float(row.get("amount")) for row in entries_period if str(row.get("account_credit") or "").startswith("90.01")), 2)
    other_income = round(sum(_safe_float(row.get("amount")) for row in entries_period if str(row.get("account_credit") or "").startswith("91.01")), 2)
    purchase_cost = round(sum(_safe_float(row.get("amount")) for row in entries_period if row.get("source_type") == "purchase_order" and str(row.get("account_debit") or "").startswith("10")), 2)
    other_expense = round(sum(_safe_float(row.get("amount")) for row in entries_period if str(row.get("account_debit") or "").startswith("91.02")), 2)
    vat_expense = round(sum(_safe_float(row.get("amount")) for row in entries_period if str(row.get("account_debit") or "").startswith("90.03")), 2)
    gross_profit = round(sales_revenue - purchase_cost, 2)
    profit_before_tax = round(sales_revenue + other_income - purchase_cost - other_expense - vat_expense, 2)
    net_profit = round(profit_before_tax - income_tax_amount, 2)
    return [
        {"line_name": "Выручка", "section": "income", "value": sales_revenue},
        {"line_name": "Прочие доходы", "section": "income", "value": other_income},
        {"line_name": "Закупки и материалы", "section": "expense", "value": purchase_cost},
        {"line_name": "Прочие расходы", "section": "expense", "value": other_expense},
        {"line_name": "НДС по реализации", "section": "expense", "value": vat_expense},
        {"line_name": "Валовая прибыль", "section": "result", "value": gross_profit},
        {"line_name": "Прибыль до налога", "section": "result", "value": profit_before_tax},
        {"line_name": "Налог на прибыль", "section": "tax", "value": income_tax_amount},
        {"line_name": "Чистая прибыль", "section": "result", "value": net_profit},
    ]


def _insert_accounting_entry(conn, payload: dict, now_ts: int):
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
            payload.get("period_key", ""),
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
            now_ts,
        ),
    )
    entry_id = getattr(cursor, "lastrowid", 0) or 0
    if entry_id:
        register_accounting_entry_by_id(conn, entry_id, payload.get("posted_by", ""))


def _period_rows(conn, table_name: str, date_field: str, period_key: str) -> list[dict]:
    if not _table_exists(conn, table_name):
        return []
    rows = _row_dicts(conn.execute(f"SELECT * FROM {table_name} ORDER BY id DESC"))
    return [row for row in rows if _period_key(row.get(date_field) or "") == period_key]


def _build_reconciliation(conn, period_key: str, base_entries: list[dict]) -> tuple[list[dict], list[dict]]:
    entries_by_source: dict[tuple[str, int], int] = {}
    for row in base_entries:
        source_key = (str(row.get("source_type") or ""), _safe_int(row.get("source_id")))
        if source_key[0] and source_key[1]:
            entries_by_source[source_key] = entries_by_source.get(source_key, 0) + 1

    sales_missing = [row for row in _period_rows(conn, "sales_documents_extended", "doc_date", period_key) if (_safe_int(row.get("id")) and ("sales_document", _safe_int(row.get("id"))) not in entries_by_source)]
    purchases_missing = [row for row in _period_rows(conn, "purchase_orders", "received_date", period_key) + _period_rows(conn, "purchase_orders", "expected_date", period_key) if (_safe_int(row.get("id")) and ("purchase_order", _safe_int(row.get("id"))) not in entries_by_source)]
    payments_open = [row for row in _period_rows(conn, "finance_payments", "paid_date", period_key) + _period_rows(conn, "finance_payments", "due_date", period_key) if str(row.get("status") or "") != "paid"]
    bank_unreconciled = [row for row in _period_rows(conn, "bank_statement_lines", "line_date", period_key) if str(row.get("status") or "") != "reconciled"]
    acts_draft = [row for row in _row_dicts(conn.execute("SELECT * FROM reconciliation_acts WHERE period_key=? ORDER BY id DESC", (period_key,))) if str(row.get("status") or "") not in {"done", "closed", "signed"}] if _table_exists(conn, "reconciliation_acts") else []

    orphan_examples = []
    orphan_count = 0
    for source_type, table_name in RECONCILIATION_SOURCE_TABLES.items():
        if not _table_exists(conn, table_name):
            continue
        source_ids = {
            _safe_int(row["id"])
            for row in _row_dicts(conn.execute(f"SELECT id FROM {table_name}"))
            if _safe_int(row.get("id"))
        }
        for row in base_entries:
            if row.get("source_type") != source_type:
                continue
            source_id = _safe_int(row.get("source_id"))
            if source_id and source_id not in source_ids:
                orphan_count += 1
                if len(orphan_examples) < 5:
                    orphan_examples.append(
                        {
                            "source_type": source_type,
                            "source_id": source_id,
                            "description": row.get("description", ""),
                            "amount": _safe_float(row.get("amount")),
                        }
                    )

    items = [
        {
            "register_name": "Документы реализации без проводок",
            "status": "ok" if not sales_missing else "warning",
            "mismatch_count": len({int(row["id"]) for row in sales_missing if _safe_int(row.get("id"))}),
            "examples": [{"id": _safe_int(row.get("id")), "title": row.get("doc_number") or row.get("comment") or "Реализация"} for row in sales_missing[:5]],
        },
        {
            "register_name": "Закупки без проводок",
            "status": "ok" if not purchases_missing else "warning",
            "mismatch_count": len({int(row["id"]) for row in purchases_missing if _safe_int(row.get("id"))}),
            "examples": [{"id": _safe_int(row.get("id")), "title": row.get("item_name") or row.get("supplier") or "Закупка"} for row in purchases_missing[:5]],
        },
        {
            "register_name": "Непроведенные оплаты",
            "status": "ok" if not payments_open else "warning",
            "mismatch_count": len({int(row["id"]) for row in payments_open if _safe_int(row.get("id"))}),
            "examples": [{"id": _safe_int(row.get("id")), "title": row.get("title") or "Платеж", "status": row.get("status", "")} for row in payments_open[:5]],
        },
        {
            "register_name": "Несверенные банковские строки",
            "status": "ok" if not bank_unreconciled else "warning",
            "mismatch_count": len({int(row["id"]) for row in bank_unreconciled if _safe_int(row.get("id"))}),
            "examples": [{"id": _safe_int(row.get("id")), "title": row.get("counterparty") or "Банк", "status": row.get("status", "")} for row in bank_unreconciled[:5]],
        },
        {
            "register_name": "Черновики актов сверки",
            "status": "ok" if not acts_draft else "warning",
            "mismatch_count": len({int(row["id"]) for row in acts_draft if _safe_int(row.get("id"))}),
            "examples": [{"id": _safe_int(row.get("id")), "title": row.get("act_number") or "Акт сверки", "status": row.get("status", "")} for row in acts_draft[:5]],
        },
        {
            "register_name": "Осиротевшие проводки",
            "status": "ok" if orphan_count == 0 else "critical",
            "mismatch_count": orphan_count,
            "examples": orphan_examples,
        },
    ]

    checklist = []
    for item in items:
        level = "pass"
        if item["status"] == "warning":
            level = "warn"
        elif item["status"] == "critical":
            level = "block"
        checklist.append(
            {
                "code": item["register_name"],
                "status": level,
                "title": item["register_name"],
                "message": "Ок" if item["mismatch_count"] == 0 else f"Найдено расхождений: {item['mismatch_count']}",
            }
        )
    return items, checklist


def run_accounting_close_cycle(
    conn,
    *,
    actor: dict,
    period_key: str,
    comment: str = "",
    rebuild_auto_fn=None,
):
    period_key = (period_key or "").strip() or _period_key("")
    period_row = _load_period_row(conn, period_key)
    if str(period_row.get("status") or "") == "closed":
        workspace = load_accounting_close_workspace(conn, actor=actor, period_key=period_key)
        return {"status": "success", "period_key": period_key, "already_closed": True, "workspace": workspace}

    if rebuild_auto_fn:
        rebuild_auto_fn(conn, actor)

    now_ts = int(datetime.now().timestamp())
    actor_email = actor.get("email", "")

    conn.execute(
        "DELETE FROM accounting_entries WHERE period_key=? AND source_type IN (?, ?)",
        (period_key, *CLOSE_ENTRY_SOURCES),
    )
    conn.execute("DELETE FROM accounting_tax_accruals WHERE period_key=?", (period_key,))
    conn.execute("DELETE FROM accounting_reporting_snapshots WHERE period_key=?", (period_key,))
    conn.execute("DELETE FROM accounting_register_reconciliations WHERE period_key=?", (period_key,))

    account_rows = _row_dicts(conn.execute("SELECT code, name FROM account_chart ORDER BY code"))
    account_names = {str(row.get("code") or ""): row.get("name", "") for row in account_rows if row.get("code")}

    entries_before = _row_dicts(conn.execute("SELECT * FROM accounting_entries WHERE period_key < ? ORDER BY id", (period_key,)))
    base_entries = _row_dicts(conn.execute("SELECT * FROM accounting_entries WHERE period_key=? ORDER BY id", (period_key,)))

    vat_input = round(sum(_safe_float(row.get("vat_amount")) for row in base_entries if row.get("source_type") == "purchase_order"), 2)
    vat_output = round(sum(_safe_float(row.get("vat_amount")) for row in base_entries if row.get("source_type") == "sales_document"), 2)
    vat_net = round(vat_output - vat_input, 2)
    vat_recovery = round(abs(vat_net), 2) if vat_net < 0 else 0.0
    profit_before_tax = next((row["value"] for row in _pnl_rows(base_entries, 0.0) if row["line_name"] == "Прибыль до налога"), 0.0)
    income_tax_rate = 0.2
    income_tax_amount = round(max(_safe_float(profit_before_tax), 0.0) * income_tax_rate, 2)

    close_entry_date = f"{period_key}-28"
    if vat_input > 0:
        _insert_accounting_entry(
            conn,
            {
                "source_type": "accounting_close_vat",
                "source_id": 0,
                "entry_date": close_entry_date,
                "period_key": period_key,
                "account_debit": "68.02",
                "account_credit": "19.03",
                "amount": vat_input,
                "vat_amount": 0,
                "currency": "RUB",
                "description": f"Закрытие входящего НДС за {_period_title(period_key)}",
                "posted_by": actor_email,
            },
            now_ts,
        )
    if income_tax_amount > 0:
        _insert_accounting_entry(
            conn,
            {
                "source_type": "accounting_close_profit_tax",
                "source_id": 0,
                "entry_date": close_entry_date,
                "period_key": period_key,
                "account_debit": "99",
                "account_credit": "68.04",
                "amount": income_tax_amount,
                "vat_amount": 0,
                "currency": "RUB",
                "description": f"Начисление налога на прибыль за {_period_title(period_key)}",
                "posted_by": actor_email,
            },
            now_ts,
        )

    register_build = rebuild_registers_for_period(conn, period_key, actor_email)
    entries_period = _row_dicts(conn.execute("SELECT * FROM accounting_entries WHERE period_key=? ORDER BY id", (period_key,)))
    trial_balance = _trial_balance_rows(entries_before, entries_period, account_names)
    balance_sheet = _balance_sheet_lines_from_trial(trial_balance)
    pnl_rows = _pnl_rows(entries_period, income_tax_amount)
    register_reconciliations, checklist = _build_reconciliation(conn, period_key, base_entries)
    erp_register_checks = period_close_register_checks(conn, period_key)
    register_reconciliations.extend(erp_register_checks)
    for check in erp_register_checks:
        status = "pass" if check.get("status") == "ok" else "warn"
        checklist.append(
            {
                "key": f"erp_register_{check.get('register_name')}",
                "label": f"ERP-регистр: {check.get('register_name')}",
                "status": status,
                "message": f"{check.get('register_name')}: расхождений {check.get('mismatch_count', 0)}",
            }
        )
    mismatches_count = sum(_safe_int(item.get("mismatch_count")) for item in register_reconciliations)

    tax_rows = [
        {
            "tax_type": "vat_input",
            "tax_name": "НДС входящий",
            "tax_base": vat_input,
            "tax_rate": 0,
            "amount": vat_input,
            "account_debit": "19.03",
            "account_credit": "60.01",
            "status": "recognized",
            "details_json": {"period_key": period_key},
        },
        {
            "tax_type": "vat_output",
            "tax_name": "НДС исходящий",
            "tax_base": vat_output,
            "tax_rate": 0,
            "amount": vat_output,
            "account_debit": "90.03",
            "account_credit": "68.02",
            "status": "recognized",
            "details_json": {"period_key": period_key},
        },
        {
            "tax_type": "vat_net",
            "tax_name": "НДС к уплате" if vat_net >= 0 else "НДС к возмещению",
            "tax_base": vat_output - vat_input,
            "tax_rate": 0,
            "amount": abs(vat_net),
            "account_debit": "68.02",
            "account_credit": "19.03",
            "status": "payable" if vat_net >= 0 else "recoverable",
            "details_json": {"vat_input": vat_input, "vat_output": vat_output, "vat_recovery": vat_recovery},
        },
        {
            "tax_type": "income_tax",
            "tax_name": "Налог на прибыль",
            "tax_base": _safe_float(profit_before_tax),
            "tax_rate": income_tax_rate,
            "amount": income_tax_amount,
            "account_debit": "99",
            "account_credit": "68.04",
            "status": "accrued" if income_tax_amount > 0 else "zero",
            "details_json": {"period_key": period_key},
        },
    ]
    for item in tax_rows:
        conn.execute(
            """
            INSERT INTO accounting_tax_accruals (
                period_key, tax_type, tax_name, tax_base, tax_rate, amount, account_debit, account_credit,
                status, details_json, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                period_key,
                item["tax_type"],
                item["tax_name"],
                round(_safe_float(item["tax_base"]), 2),
                round(_safe_float(item["tax_rate"]), 4),
                round(_safe_float(item["amount"]), 2),
                item["account_debit"],
                item["account_credit"],
                item["status"],
                json.dumps(item["details_json"], ensure_ascii=False),
                actor_email,
                now_ts,
                now_ts,
            ),
        )

    report_rows = [
        ("trial_balance", "Оборотно-сальдовая ведомость", trial_balance, sum(_safe_float(row.get("turnover_debit")) for row in trial_balance)),
        ("balance_sheet", "Баланс", balance_sheet, sum(_safe_float(row.get("value")) for row in balance_sheet if row.get("section") == "assets")),
        ("pnl", "Отчет о прибылях и убытках", pnl_rows, next((row["value"] for row in pnl_rows if row["line_name"] == "Чистая прибыль"), 0.0)),
        ("tax_registers", "Налоговые регистры", tax_rows, sum(_safe_float(row.get("amount")) for row in tax_rows)),
    ]
    for report_type, report_name, payload, amount_total in report_rows:
        conn.execute(
            """
            INSERT INTO accounting_reporting_snapshots (
                period_key, report_type, report_name, status, report_payload, amount_total, line_count, created_by, created_at
            ) VALUES (?, ?, ?, 'actual', ?, ?, ?, ?, ?)
            """,
            (
                period_key,
                report_type,
                report_name,
                json.dumps(payload, ensure_ascii=False),
                round(_safe_float(amount_total), 2),
                len(payload),
                actor_email,
                now_ts,
            ),
        )

    for item in register_reconciliations:
        conn.execute(
            """
            INSERT INTO accounting_register_reconciliations (
                period_key, register_name, status, mismatch_count, summary_json, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                period_key,
                item["register_name"],
                item["status"],
                _safe_int(item["mismatch_count"]),
                json.dumps({"examples": item.get("examples", [])}, ensure_ascii=False),
                actor_email,
                now_ts,
                now_ts,
            ),
        )

    close_status = "closed_with_warnings" if mismatches_count else "closed"
    summary_payload = {
        "period_key": period_key,
        "entries_total": len(entries_period),
        "mismatches_count": mismatches_count,
        "tax_total": round(abs(vat_net) + income_tax_amount, 2),
        "reports_total": len(report_rows),
        "register_build": register_build,
        "register_summary": period_register_summary(conn, period_key),
        "checklist": checklist,
    }
    cursor = conn.execute(
        """
        INSERT INTO accounting_period_close_runs (
            period_key, status, entries_total, checks_passed, mismatches_count, tax_amount, report_count,
            summary_json, created_by, created_at, closed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            period_key,
            close_status,
            len(entries_period),
            len([item for item in checklist if item["status"] == "pass"]),
            mismatches_count,
            round(abs(vat_net) + income_tax_amount, 2),
            len(report_rows),
            json.dumps(summary_payload, ensure_ascii=False),
            actor_email,
            now_ts,
            now_ts,
        ),
    )
    close_run_id = getattr(cursor, "lastrowid", 0) or 0

    conn.execute(
        """
        UPDATE accounting_periods
        SET status='closed', closed_at=?, closed_by=?, comment=?
        WHERE period_key=?
        """,
        (now_ts, actor_email, comment or "", period_key),
    )

    workspace = load_accounting_close_workspace(conn, actor=actor, period_key=period_key)
    return {
        "status": "success",
        "period_key": period_key,
        "close_run_id": close_run_id,
        "warnings": [item["message"] for item in checklist if item["status"] != "pass"],
        "workspace": workspace,
    }


def load_accounting_close_workspace(
    conn,
    *,
    actor: dict | None = None,
    period_key: str = "",
    filter_rows_by_scope_fn=None,
):
    period_key = (period_key or "").strip() or _period_key("")
    period_row = _load_period_row(conn, period_key)
    account_names = {
        str(row.get("code") or ""): row.get("name", "")
        for row in _row_dicts(conn.execute("SELECT code, name FROM account_chart ORDER BY code"))
        if row.get("code")
    }
    entries_before = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM accounting_entries WHERE period_key < ? ORDER BY id", (period_key,))), filter_rows_by_scope_fn)
    entries_period = _scope_rows(actor, _row_dicts(conn.execute("SELECT * FROM accounting_entries WHERE period_key=? ORDER BY id", (period_key,))), filter_rows_by_scope_fn)
    tax_rows = _row_dicts(conn.execute("SELECT * FROM accounting_tax_accruals WHERE period_key=? ORDER BY id DESC", (period_key,)))
    for row in tax_rows:
        row["details_json"] = _json_load(row.get("details_json"), {})
    report_rows = _row_dicts(conn.execute("SELECT * FROM accounting_reporting_snapshots WHERE period_key=? ORDER BY id DESC", (period_key,)))
    for row in report_rows:
        row["report_payload"] = _json_load(row.get("report_payload"), [])
    reconciliation_rows = _row_dicts(conn.execute("SELECT * FROM accounting_register_reconciliations WHERE period_key=? ORDER BY id DESC", (period_key,)))
    for row in reconciliation_rows:
        row["summary_json"] = _json_load(row.get("summary_json"), {})
    close_runs = _row_dicts(conn.execute("SELECT * FROM accounting_period_close_runs ORDER BY created_at DESC, id DESC LIMIT 20"))
    for row in close_runs:
        row["summary_json"] = _json_load(row.get("summary_json"), {})
    periods = _row_dicts(conn.execute("SELECT * FROM accounting_periods ORDER BY period_key DESC, id DESC LIMIT 24"))

    trial_balance = _trial_balance_rows(entries_before, entries_period, account_names)
    _, checklist = _build_reconciliation(conn, period_key, entries_period)
    last_close = next((row for row in close_runs if row.get("period_key") == period_key), None)
    register_summary = period_register_summary(conn, period_key)

    return {
        "selected_period_key": period_key,
        "selected_period_title": _period_title(period_key),
        "selected_period": period_row,
        "periods": periods,
        "entries_total": len(entries_period),
        "trial_balance": trial_balance[:24],
        "tax_accruals": tax_rows[:12],
        "report_snapshots": report_rows[:12],
        "register_reconciliations": reconciliation_rows[:12],
        "register_summary": register_summary,
        "checklist": checklist,
        "close_runs": close_runs,
        "last_close": last_close or {},
    }
