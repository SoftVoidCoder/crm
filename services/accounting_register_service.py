import json
import time
from datetime import datetime


VAT_RATE_DEFAULT = 20.0
MUTUAL_SETTLEMENT_ACCOUNTS = ("60", "62", "76")
WIP_ACCOUNTS = ("20", "23", "25", "26")
INVENTORY_ACCOUNTS = ("10", "41", "43")
FIXED_ASSET_ACCOUNTS = ("01", "04", "08")
CURRENCY_ACCOUNTS = ("52", "55", "57", "60", "62", "76")
PAYROLL_ACCOUNTS = ("69", "70")


def _safe_text(value) -> str:
    return str(value or "").strip()


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _row_dict(row) -> dict:
    if not row:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return {}


def _row_dicts(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def _parse_date(value: str):
    text = _safe_text(value)
    if not text:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%Y %H:%M", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def period_key_for_date(value: str = "") -> str:
    dt = _parse_date(value) or datetime.now()
    return dt.strftime("%Y-%m")


def _entry_period(entry: dict) -> str:
    return _safe_text(entry.get("period_key")) or period_key_for_date(entry.get("entry_date"))


def _vat_rate(conn, vat_rate_id: int, vat_amount: float, base_amount: float) -> float:
    if vat_rate_id:
        row = _row_dict(conn.execute("SELECT rate FROM vat_rates WHERE id=?", (_safe_int(vat_rate_id),)).fetchone())
        if row:
            return round(_safe_float(row.get("rate")), 4)
    if vat_amount > 0 and base_amount > 0:
        return round(vat_amount / max(base_amount, 0.01) * 100, 4)
    return VAT_RATE_DEFAULT if vat_amount > 0 else 0.0


def _client_name(conn, client_id: int) -> str:
    if not client_id:
        return ""
    row = _row_dict(conn.execute("SELECT name FROM clients WHERE id=?", (_safe_int(client_id),)).fetchone())
    return _safe_text(row.get("name"))


def _dimension_payload(entry: dict, extra: dict | None = None) -> str:
    payload = {
        "treasury_article_id": _safe_int(entry.get("treasury_article_id")),
        "vat_rate_id": _safe_int(entry.get("vat_rate_id")),
        "contract_id": _safe_int(entry.get("contract_id")),
        "object_id": _safe_int(entry.get("object_id")),
        "description": _safe_text(entry.get("description")),
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _register_kind_for_account(account_code: str) -> str:
    code = _safe_text(account_code)
    if code.startswith(MUTUAL_SETTLEMENT_ACCOUNTS):
        return "mutual_settlement"
    if code.startswith(WIP_ACCOUNTS):
        return "wip"
    if code.startswith(INVENTORY_ACCOUNTS):
        return "accumulation"
    if code.startswith(FIXED_ASSET_ACCOUNTS):
        return "fixed_asset"
    if code.startswith(PAYROLL_ACCOUNTS):
        return "payroll"
    return "accounting"


def purge_registers_for_source(conn, source_type: str, source_id: int = 0, period_key: str = ""):
    params = [_safe_text(source_type)]
    where = "source_type=?"
    if source_id:
        where += " AND source_id=?"
        params.append(_safe_int(source_id))
    if period_key:
        where += " AND period_key=?"
        params.append(_safe_text(period_key))
    for table in ("accounting_registers", "tax_registers", "vat_purchase_book", "vat_sales_book"):
        conn.execute(f"DELETE FROM {table} WHERE {where}", tuple(params))


def purge_registers_for_period(conn, period_key: str, source_types: tuple[str, ...] | None = None):
    period_key = _safe_text(period_key)
    if not period_key:
        return
    if source_types:
        placeholders = ", ".join(["?"] * len(source_types))
        params = (period_key, *source_types)
        for table in ("accounting_registers", "tax_registers", "vat_purchase_book", "vat_sales_book"):
            conn.execute(f"DELETE FROM {table} WHERE period_key=? AND source_type IN ({placeholders})", params)
        return
    for table in ("accounting_registers", "tax_registers", "vat_purchase_book", "vat_sales_book"):
        conn.execute(f"DELETE FROM {table} WHERE period_key=?", (period_key,))


def register_accounting_entry(conn, entry: dict, actor_email: str = "") -> dict:
    entry = dict(entry or {})
    entry_id = _safe_int(entry.get("id"))
    period_key = _entry_period(entry)
    now = int(time.time())
    source_type = _safe_text(entry.get("source_type"))
    source_id = _safe_int(entry.get("source_id"))
    actor_email = _safe_text(actor_email) or _safe_text(entry.get("posted_by"))
    if entry_id:
        for table in ("accounting_registers", "tax_registers", "vat_purchase_book", "vat_sales_book"):
            conn.execute(f"DELETE FROM {table} WHERE entry_id=?", (entry_id,))
    amount = round(_safe_float(entry.get("amount")), 2)
    vat_amount = round(_safe_float(entry.get("vat_amount")), 2)
    currency = _safe_text(entry.get("currency")) or "RUB"
    created = {"accounting_registers": 0, "tax_registers": 0, "vat_purchase_book": 0, "vat_sales_book": 0}

    for side, account_code in (("debit", entry.get("account_debit")), ("credit", entry.get("account_credit"))):
        account_code = _safe_text(account_code)
        if not account_code:
            continue
        conn.execute(
            """
            INSERT INTO accounting_registers (
                register_kind, period_key, source_type, source_id, entry_id, legal_entity_id, business_unit_id,
                project_id, client_id, contract_id, object_id, account_code, balance_side, debit_amount,
                credit_amount, amount, quantity, currency, dimension_json, posted_at, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                _register_kind_for_account(account_code),
                period_key,
                source_type,
                source_id,
                entry_id,
                _safe_int(entry.get("legal_entity_id")),
                _safe_int(entry.get("business_unit_id")),
                _safe_int(entry.get("project_id")),
                _safe_int(entry.get("client_id")),
                _safe_int(entry.get("contract_id")),
                _safe_int(entry.get("object_id")),
                account_code,
                side,
                amount if side == "debit" else 0,
                amount if side == "credit" else 0,
                amount,
                currency,
                _dimension_payload(entry),
                now,
                actor_email,
                now,
            ),
        )
        created["accounting_registers"] += 1

    vat_rate = _vat_rate(conn, _safe_int(entry.get("vat_rate_id")), vat_amount, max(amount - vat_amount, 0.0))
    if vat_amount > 0:
        tax_type = "vat_input" if source_type in {"purchase_order", "purchase_document"} or _safe_text(entry.get("account_debit")).startswith("19") else "vat_output"
        conn.execute(
            """
            INSERT INTO tax_registers (
                period_key, tax_type, source_type, source_id, entry_id, legal_entity_id, client_id,
                tax_base, tax_rate, tax_amount, account_code, status, dimension_json, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'recognized', ?, ?, ?, ?)
            """,
            (
                period_key,
                tax_type,
                source_type,
                source_id,
                entry_id,
                _safe_int(entry.get("legal_entity_id")),
                _safe_int(entry.get("client_id")),
                round(max(amount - vat_amount, 0.0), 2),
                vat_rate,
                vat_amount,
                _safe_text(entry.get("account_debit") if tax_type == "vat_input" else entry.get("account_credit")),
                _dimension_payload(entry),
                actor_email,
                now,
                now,
            ),
        )
        created["tax_registers"] += 1
        book_table = "vat_purchase_book" if tax_type == "vat_input" else "vat_sales_book"
        conn.execute(
            f"""
            INSERT INTO {book_table} (
                period_key, source_type, source_id, entry_id, document_number, document_date, counterparty_id,
                counterparty_name, amount_total, vat_amount, vat_rate, currency, status, dimension_json,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'registered', ?, ?, ?, ?)
            """,
            (
                period_key,
                source_type,
                source_id,
                entry_id,
                f"{source_type}-{source_id}" if source_id else _safe_text(entry.get("description"))[:80],
                _safe_text(entry.get("entry_date")),
                _safe_int(entry.get("client_id")),
                _client_name(conn, _safe_int(entry.get("client_id"))),
                amount,
                vat_amount,
                vat_rate,
                currency,
                _dimension_payload(entry),
                actor_email,
                now,
                now,
            ),
        )
        created[book_table] += 1
    return created


def register_accounting_entry_by_id(conn, entry_id: int, actor_email: str = "") -> dict:
    row = _row_dict(conn.execute("SELECT * FROM accounting_entries WHERE id=?", (_safe_int(entry_id),)).fetchone())
    if not row:
        return {"error": "entry_not_found"}
    return register_accounting_entry(conn, row, actor_email)


def rebuild_registers_for_source(conn, source_type: str, source_id: int, actor_email: str = "") -> dict:
    purge_registers_for_source(conn, source_type, source_id)
    rows = _row_dicts(
        conn.execute(
            "SELECT * FROM accounting_entries WHERE source_type=? AND source_id=? ORDER BY id",
            (_safe_text(source_type), _safe_int(source_id)),
        )
    )
    result = {"entries": len(rows), "accounting_registers": 0, "tax_registers": 0, "vat_purchase_book": 0, "vat_sales_book": 0}
    for row in rows:
        created = register_accounting_entry(conn, row, actor_email)
        for key in result:
            if key != "entries":
                result[key] += _safe_int(created.get(key))
    return result


def rebuild_registers_for_period(conn, period_key: str, actor_email: str = "") -> dict:
    period_key = _safe_text(period_key)
    purge_registers_for_period(conn, period_key)
    rows = _row_dicts(conn.execute("SELECT * FROM accounting_entries WHERE period_key=? ORDER BY id", (period_key,)))
    result = {"period_key": period_key, "entries": len(rows), "accounting_registers": 0, "tax_registers": 0, "vat_purchase_book": 0, "vat_sales_book": 0}
    for row in rows:
        created = register_accounting_entry(conn, row, actor_email)
        for key in ("accounting_registers", "tax_registers", "vat_purchase_book", "vat_sales_book"):
            result[key] += _safe_int(created.get(key))
    rebuild_currency_revaluation(conn, period_key, actor_email)
    sync_fixed_assets_from_registers(conn, period_key, actor_email)
    return result


def rebuild_all_registers(conn, actor_email: str = "") -> dict:
    for table in ("accounting_registers", "tax_registers", "vat_purchase_book", "vat_sales_book", "currency_revaluation_runs"):
        conn.execute(f"DELETE FROM {table}")
    rows = _row_dicts(conn.execute("SELECT * FROM accounting_entries ORDER BY period_key, id"))
    result = {"entries": len(rows), "accounting_registers": 0, "tax_registers": 0, "vat_purchase_book": 0, "vat_sales_book": 0}
    periods = set()
    for row in rows:
        periods.add(_entry_period(row))
        created = register_accounting_entry(conn, row, actor_email)
        for key in ("accounting_registers", "tax_registers", "vat_purchase_book", "vat_sales_book"):
            result[key] += _safe_int(created.get(key))
    for period_key in sorted(periods):
        rebuild_currency_revaluation(conn, period_key, actor_email)
        sync_fixed_assets_from_registers(conn, period_key, actor_email)
    return result


def rebuild_currency_revaluation(conn, period_key: str, actor_email: str = "") -> dict:
    now = int(time.time())
    conn.execute("DELETE FROM currency_revaluation_runs WHERE period_key=?", (_safe_text(period_key),))
    rows = _row_dicts(
        conn.execute(
            """
            SELECT currency, legal_entity_id, account_code,
                   SUM(CASE WHEN balance_side='debit' THEN amount ELSE -amount END) AS amount_currency
            FROM accounting_registers
            WHERE period_key=? AND currency<>'RUB'
              AND (
                  account_code LIKE '52%' OR account_code LIKE '55%' OR account_code LIKE '57%'
                  OR account_code LIKE '60%' OR account_code LIKE '62%' OR account_code LIKE '76%'
              )
            GROUP BY currency, legal_entity_id, account_code
            """,
            (_safe_text(period_key),),
        )
    )
    created = 0
    rate_map = {"USD": (90.0, 92.0), "EUR": (100.0, 101.0), "CNY": (12.0, 12.4)}
    for row in rows:
        amount_currency = round(_safe_float(row.get("amount_currency")), 2)
        if not amount_currency:
            continue
        before, after = rate_map.get(_safe_text(row.get("currency")), (1.0, 1.0))
        amount_before = round(amount_currency * before, 2)
        amount_after = round(amount_currency * after, 2)
        diff = round(amount_after - amount_before, 2)
        conn.execute(
            """
            INSERT INTO currency_revaluation_runs (
                period_key, currency, legal_entity_id, amount_currency, rate_before, rate_after,
                amount_before, amount_after, exchange_difference, status, details_json, created_by, created_at, posted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'calculated', ?, ?, ?, ?)
            """,
            (
                _safe_text(period_key),
                _safe_text(row.get("currency")),
                _safe_int(row.get("legal_entity_id")),
                amount_currency,
                before,
                after,
                amount_before,
                amount_after,
                diff,
                json.dumps({"source": "accounting_registers", "account_code": _safe_text(row.get("account_code"))}, ensure_ascii=False),
                _safe_text(actor_email),
                now,
                now,
            ),
        )
        created += 1
    return {"created": created}


def sync_fixed_assets_from_registers(conn, period_key: str, actor_email: str = "") -> dict:
    rows = _row_dicts(
        conn.execute(
            """
            SELECT source_type, source_id, legal_entity_id, business_unit_id, project_id,
                   SUM(debit_amount - credit_amount) AS initial_cost
            FROM accounting_registers
            WHERE period_key=? AND account_code IN ('01', '04', '08')
            GROUP BY source_type, source_id, legal_entity_id, business_unit_id, project_id
            """,
            (_safe_text(period_key),),
        )
    )
    now = int(time.time())
    created = 0
    for row in rows:
        cost = round(_safe_float(row.get("initial_cost")), 2)
        if cost <= 0:
            continue
        asset_number = f"{_safe_text(row.get('source_type'))}-{_safe_int(row.get('source_id'))}"
        existing = _row_dict(conn.execute("SELECT id FROM fixed_assets WHERE asset_number=?", (asset_number,)).fetchone())
        if existing:
            conn.execute(
                "UPDATE fixed_assets SET initial_cost=?, residual_value=?, updated_at=? WHERE asset_number=?",
                (cost, cost, now, asset_number),
            )
            continue
        conn.execute(
            """
            INSERT INTO fixed_assets (
                asset_number, asset_name, asset_kind, legal_entity_id, business_unit_id, project_id,
                acquisition_date, commissioning_date, initial_cost, accumulated_depreciation, residual_value,
                useful_life_months, status, source_type, source_id, details_json, created_by, created_at, updated_at
            ) VALUES (?, ?, 'fixed_asset', ?, ?, ?, ?, '', ?, 0, ?, 60, 'accepted', ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_number,
                f"Актив {asset_number}",
                _safe_int(row.get("legal_entity_id")),
                _safe_int(row.get("business_unit_id")),
                _safe_int(row.get("project_id")),
                f"{period_key}-01",
                cost,
                cost,
                _safe_text(row.get("source_type")),
                _safe_int(row.get("source_id")),
                json.dumps({"period_key": period_key}, ensure_ascii=False),
                _safe_text(actor_email),
                now,
                now,
            ),
        )
        created += 1
    return {"created": created}


def period_register_summary(conn, period_key: str) -> dict:
    period_key = _safe_text(period_key)
    def count(table: str) -> int:
        return _safe_int(_row_dict(conn.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE period_key=?", (period_key,)).fetchone()).get("cnt"))

    entries_total = count("accounting_entries")
    accounting_registers_total = count("accounting_registers")
    vat_purchase_total = count("vat_purchase_book")
    vat_sales_total = count("vat_sales_book")
    tax_total = count("tax_registers")
    wip_amount = _safe_float(
        _row_dict(
            conn.execute(
                """
                SELECT SUM(debit_amount - credit_amount) AS amount
                FROM accounting_registers
                WHERE period_key=? AND register_kind='wip'
                """,
                (period_key,),
            ).fetchone()
        ).get("amount")
    )
    receivable = _safe_float(
        _row_dict(
            conn.execute(
                """
                SELECT SUM(debit_amount - credit_amount) AS amount
                FROM accounting_registers
                WHERE period_key=? AND account_code LIKE '62%'
                """,
                (period_key,),
            ).fetchone()
        ).get("amount")
    )
    payable = -_safe_float(
        _row_dict(
            conn.execute(
                """
                SELECT SUM(debit_amount - credit_amount) AS amount
                FROM accounting_registers
                WHERE period_key=? AND account_code LIKE '60%'
                """,
                (period_key,),
            ).fetchone()
        ).get("amount")
    )
    return {
        "period_key": period_key,
        "entries_total": entries_total,
        "accounting_registers_total": accounting_registers_total,
        "tax_registers_total": tax_total,
        "vat_purchase_book_total": vat_purchase_total,
        "vat_sales_book_total": vat_sales_total,
        "currency_revaluation_total": count("currency_revaluation_runs"),
        "wip_amount": round(wip_amount, 2),
        "receivable_amount": round(max(receivable, 0), 2),
        "payable_amount": round(max(payable, 0), 2),
    }


def period_close_register_checks(conn, period_key: str) -> list[dict]:
    summary = period_register_summary(conn, period_key)
    checks = []
    entries_total = _safe_int(summary.get("entries_total"))
    registers_total = _safe_int(summary.get("accounting_registers_total"))
    checks.append({
        "register_name": "accounting_registers",
        "status": "ok" if registers_total >= entries_total else "warning",
        "mismatch_count": max(entries_total - registers_total, 0),
        "examples": [summary],
    })
    vat_entries = _safe_int(
        _row_dict(
            conn.execute(
                "SELECT COUNT(*) AS cnt FROM accounting_entries WHERE period_key=? AND vat_amount>0",
                (_safe_text(period_key),),
            ).fetchone()
        ).get("cnt")
    )
    vat_books = _safe_int(summary.get("vat_purchase_book_total")) + _safe_int(summary.get("vat_sales_book_total"))
    checks.append({
        "register_name": "vat_books",
        "status": "ok" if vat_books >= vat_entries else "warning",
        "mismatch_count": max(vat_entries - vat_books, 0),
        "examples": [{"vat_entries": vat_entries, "vat_books": vat_books}],
    })
    checks.append({
        "register_name": "mutual_settlements",
        "status": "ok",
        "mismatch_count": 0,
        "examples": [{"receivable": summary.get("receivable_amount"), "payable": summary.get("payable_amount")}],
    })
    checks.append({
        "register_name": "wip",
        "status": "warning" if _safe_float(summary.get("wip_amount")) > 0 else "ok",
        "mismatch_count": 1 if _safe_float(summary.get("wip_amount")) > 0 else 0,
        "examples": [{"wip_amount": summary.get("wip_amount")}],
    })
    return checks
