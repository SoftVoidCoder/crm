import time


def resolve_telephony_context(conn, *, phone_number: str = "", client_id: int = 0, project_id: int = 0):
    c = conn.cursor()
    resolved_client_id = int(client_id or 0)
    resolved_project_id = int(project_id or 0)
    contact_name = ""
    normalized_phone = "".join(ch for ch in str(phone_number or "") if ch.isdigit())
    if normalized_phone and not resolved_client_id:
        c.execute(
            """
            SELECT ct.name, COALESCE(ct.client_id, 0) AS client_id
            FROM contacts ct
            WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(ct.phone, ''), '+', ''), ' ', ''), '-', ''), '(', ''), ')', '') LIKE ?
            ORDER BY ct.id DESC
            LIMIT 1
            """,
            (f"%{normalized_phone[-10:]}%",),
        )
        row = c.fetchone()
        if row:
            contact_name = row[0] or ""
            resolved_client_id = int(row[1] or 0)
    if resolved_client_id and not resolved_project_id:
        c.execute(
            """
            SELECT id
            FROM projects
            WHERE client=COALESCE((SELECT name FROM clients WHERE id=?), client)
            ORDER BY id DESC
            LIMIT 1
            """,
            (resolved_client_id,),
        )
        row = c.fetchone()
        if row:
            resolved_project_id = int(row[0] or 0)
    return {
        "client_id": resolved_client_id,
        "project_id": resolved_project_id,
        "contact_name": contact_name,
    }


def resolve_bank_line_context(
    conn,
    *,
    counterparty: str = "",
    client_id: int = 0,
    payment_id: int = 0,
    amount: float = 0,
    direction: str = "incoming",
    safe_int_fn,
    safe_float_fn,
):
    c = conn.cursor()
    resolved_client_id = safe_int_fn(client_id)
    resolved_payment_id = safe_int_fn(payment_id)
    if not resolved_client_id and str(counterparty or "").strip():
        c.execute(
            """
            SELECT id
            FROM clients
            WHERE LOWER(name)=LOWER(?)
               OR LOWER(contact)=LOWER(?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (counterparty.strip(), counterparty.strip()),
        )
        row = c.fetchone()
        resolved_client_id = safe_int_fn(row[0]) if row else 0
    if not resolved_payment_id:
        c.execute(
            """
            SELECT id
            FROM finance_payments
            WHERE ABS(amount - ?) < 0.0001
              AND kind=?
              AND (? = 0 OR client_id = ?)
              AND status IN ('planned', 'issued', 'partially_paid', 'overdue')
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (safe_float_fn(amount), "incoming" if direction == "incoming" else "outgoing", resolved_client_id, resolved_client_id),
        )
        row = c.fetchone()
        resolved_payment_id = safe_int_fn(row[0]) if row else 0
    return {"client_id": resolved_client_id, "payment_id": resolved_payment_id}


def list_bank_accounts(*, get_connection, filter_rows_by_scope_fn, actor):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT ba.*, le.short_name AS legal_entity_name
            FROM bank_accounts ba
            LEFT JOIN legal_entities le ON le.id = ba.legal_entity_id
            ORDER BY ba.updated_at DESC, ba.id DESC
            """
        )
        rows = [dict(row) for row in c.fetchall()]
        return filter_rows_by_scope_fn(actor, rows)
    finally:
        conn.close()


def create_bank_account_record(*, get_connection, actor, data, safe_int_fn):
    conn = get_connection()
    try:
        c = conn.cursor()
        now = int(time.time())
        c.execute(
            """
            INSERT INTO bank_accounts (name, bank_name, account_number, bik, currency, legal_entity_id, is_active, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.name, data.bank_name, data.account_number, data.bik, data.currency, safe_int_fn(data.legal_entity_id),
                1 if int(data.is_active or 0) else 0, actor.get("email", ""), now, now,
            ),
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


def list_bank_statement_lines(*, get_connection, unreconciled: int = 0):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        sql = """
            SELECT bsl.*, ba.name AS bank_account_name, fp.title AS payment_title
            FROM bank_statement_lines bsl
            LEFT JOIN bank_accounts ba ON ba.id = bsl.bank_account_id
            LEFT JOIN finance_payments fp ON fp.id = bsl.linked_payment_id
        """
        if unreconciled:
            sql += " WHERE bsl.status != 'reconciled'"
        sql += " ORDER BY bsl.line_date DESC, bsl.id DESC"
        c.execute(sql)
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def import_bank_statement_records(
    *,
    get_connection,
    actor,
    data,
    safe_int_fn,
    safe_float_fn,
    today_display_fn,
):
    conn = get_connection()
    try:
        c = conn.cursor()
        now = int(time.time())
        created = []
        for line in data.lines or []:
            payload = line.model_dump() if hasattr(line, "model_dump") else line.dict()
            context = resolve_bank_line_context(
                conn,
                counterparty=payload.get("counterparty") or "",
                client_id=safe_int_fn(payload.get("client_id")),
                payment_id=safe_int_fn(payload.get("payment_id")),
                amount=safe_float_fn(payload.get("amount")),
                direction=payload.get("direction") or "incoming",
                safe_int_fn=safe_int_fn,
                safe_float_fn=safe_float_fn,
            )
            c.execute(
                """
                INSERT INTO bank_statement_lines (
                    bank_account_id, line_date, amount, direction, counterparty, purpose, client_id,
                    linked_payment_id, external_line_id, status, comment, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    safe_int_fn(data.bank_account_id or payload.get("bank_account_id")),
                    payload.get("line_date") or today_display_fn(),
                    safe_float_fn(payload.get("amount")),
                    payload.get("direction") or "incoming",
                    payload.get("counterparty") or "",
                    payload.get("purpose") or "",
                    context["client_id"],
                    context["payment_id"],
                    payload.get("external_line_id") or "",
                    "reconciled" if context["payment_id"] else "imported",
                    payload.get("comment") or "",
                    actor.get("email", ""),
                    now,
                    now,
                ),
            )
            created.append(c.lastrowid)
        conn.commit()
        return created
    finally:
        conn.close()


def reconcile_bank_statement_record(
    *,
    get_connection,
    line_id: int,
    payment_id: int,
    safe_int_fn,
    safe_float_fn,
    today_display_fn,
    get_finance_payment_row_fn,
    rebuild_finance_accounting_entries_fn,
    upsert_finance_sync_job_fn,
    actor_email: str = "",
):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM bank_statement_lines WHERE id=?", (line_id,))
        line = c.fetchone()
        if not line:
            return {"error": "not_found"}
        line = dict(line)
        resolved_payment_id = safe_int_fn(payment_id)
        if not resolved_payment_id:
            c.execute(
                """
                SELECT id
                FROM finance_payments
                WHERE ABS(amount - ?) < 0.0001
                  AND (? = 0 OR client_id = ?)
                  AND status IN ('planned', 'issued', 'partially_paid', 'overdue')
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (safe_float_fn(line.get("amount")), safe_int_fn(line.get("client_id")), safe_int_fn(line.get("client_id"))),
            )
            row = c.fetchone()
            resolved_payment_id = safe_int_fn(row["id"]) if row else 0
        if not resolved_payment_id:
            return {"error": "payment_not_found"}
        now = int(time.time())
        c.execute(
            """
            UPDATE bank_statement_lines
            SET linked_payment_id=?, status='reconciled', updated_at=?
            WHERE id=?
            """,
            (resolved_payment_id, now, line_id),
        )
        c.execute(
            """
            UPDATE finance_payments
            SET status='paid', paid_date=CASE WHEN paid_date='' THEN ? ELSE paid_date END, updated_at=?
            WHERE id=?
            """,
            (line.get("line_date") or today_display_fn(), now, resolved_payment_id),
        )
        payment = get_finance_payment_row_fn(conn, resolved_payment_id)
        if payment:
            rebuild_finance_accounting_entries_fn(conn, payment, actor_email)
            upsert_finance_sync_job_fn(conn, payment, actor_email)
        conn.commit()
        return {"status": "success", "payment_id": resolved_payment_id}
    finally:
        conn.close()


def list_telephony_accounts(*, get_connection):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM telephony_accounts ORDER BY updated_at DESC, id DESC")
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def create_telephony_account_record(*, get_connection, actor, data):
    conn = get_connection()
    try:
        c = conn.cursor()
        now = int(time.time())
        c.execute(
            """
            INSERT INTO telephony_accounts (provider_name, line_name, external_line_id, is_active, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (data.provider_name, data.line_name, data.external_line_id, 1 if int(data.is_active or 0) else 0, actor.get("email", ""), now, now),
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


def list_telephony_calls(*, get_connection, client_id: int = 0):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        if client_id:
            c.execute(
                """
                SELECT tc.*, ta.line_name, COALESCE(cl.name, '') AS client_name, COALESCE(p.name, '') AS project_name, COALESCE(p.contract, '') AS project_contract
                FROM telephony_calls tc
                LEFT JOIN telephony_accounts ta ON ta.id = tc.account_id
                LEFT JOIN clients cl ON cl.id = tc.client_id
                LEFT JOIN projects p ON p.id = tc.project_id
                WHERE tc.client_id=?
                ORDER BY tc.call_at DESC, tc.id DESC
                """,
                (client_id,),
            )
        else:
            c.execute(
                """
                SELECT tc.*, ta.line_name, COALESCE(cl.name, '') AS client_name, COALESCE(p.name, '') AS project_name, COALESCE(p.contract, '') AS project_contract
                FROM telephony_calls tc
                LEFT JOIN telephony_accounts ta ON ta.id = tc.account_id
                LEFT JOIN clients cl ON cl.id = tc.client_id
                LEFT JOIN projects p ON p.id = tc.project_id
                ORDER BY tc.call_at DESC, tc.id DESC
                """
            )
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def create_telephony_call_record(
    *,
    get_connection,
    actor,
    data,
    safe_int_fn,
    now_timestamp: int,
    call_at: str,
):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        account_id = safe_int_fn(data.account_id)
        if not account_id:
            c.execute("SELECT id FROM telephony_accounts WHERE is_active=1 ORDER BY updated_at DESC, id DESC LIMIT 1")
            row = c.fetchone()
            account_id = safe_int_fn(row[0]) if row else 0
        context = resolve_telephony_context(conn, phone_number=data.phone_number, client_id=data.client_id, project_id=data.project_id)
        resolved_client_id = context["client_id"]
        resolved_project_id = context["project_id"]
        resolved_contact_name = (data.contact_name or "").strip() or context["contact_name"] or ""
        c.execute(
            """
            INSERT INTO telephony_calls (
                account_id, client_id, project_id, contact_name, phone_number, direction, status,
                duration_sec, call_at, summary, recording_url, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                resolved_client_id,
                resolved_project_id,
                resolved_contact_name,
                data.phone_number,
                data.direction or "inbound",
                data.status or "answered",
                safe_int_fn(data.duration_sec),
                call_at,
                data.summary,
                data.recording_url,
                actor.get("email", ""),
                now_timestamp,
            ),
        )
        conn.commit()
        return {
            "id": c.lastrowid,
            "client_id": resolved_client_id,
            "project_id": resolved_project_id,
            "contact_name": resolved_contact_name,
            "auto_linked": int(bool(context["contact_name"] or resolved_client_id or resolved_project_id)),
        }
    finally:
        conn.close()
