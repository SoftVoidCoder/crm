import time


def list_email_accounts(*, mailbox_summary_fn, can_manage_accounts: bool):
    rows = mailbox_summary_fn()
    if can_manage_accounts:
        return rows
    for row in rows:
        row.pop("login", None)
        row.pop("imap_host", None)
        row.pop("smtp_host", None)
        row.pop("smtp_login", None)
        row.pop("inbox_folder", None)
        row.pop("archive_folder", None)
    return rows


def create_email_account_record(
    data,
    *,
    actor: dict,
    get_connection,
    normalize_payload_fn,
    encrypt_secret_fn,
    audit_log_fn,
    load_account_fn,
    sync_account_fn,
    is_locked_error_fn,
):
    now = int(time.time())
    payload = normalize_payload_fn(data)
    if not payload["address"] or not payload["password"]:
        return {"error": "validation_error", "message": "Укажи почту и пароль ящика", "status_code": 400}

    account_id = 0
    locked = False
    for _ in range(3):
        conn = get_connection()
        try:
            c = conn.cursor()
            if data.is_default:
                c.execute("UPDATE email_accounts SET is_default=0")
            c.execute(
                """
                INSERT INTO email_accounts (
                    label, address, login, password, imap_host, imap_port, smtp_host, smtp_port,
                    smtp_login, smtp_password, inbox_folder, archive_folder, is_default, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["label"],
                    payload["address"],
                    payload["login"],
                    encrypt_secret_fn(payload["password"]),
                    payload["imap_host"],
                    payload["imap_port"],
                    payload["smtp_host"],
                    payload["smtp_port"],
                    payload["smtp_login"],
                    encrypt_secret_fn(payload["smtp_password"] or payload["password"]),
                    payload["inbox_folder"],
                    payload["archive_folder"],
                    payload["is_default"],
                    payload["is_active"],
                    now,
                    now,
                ),
            )
            account_id = c.lastrowid
            conn.commit()
            locked = False
            break
        except Exception as exc:
            conn.rollback()
            if not is_locked_error_fn(exc):
                raise
            locked = True
            time.sleep(0.2)
        finally:
            conn.close()
    if locked:
        return {"error": "db_locked", "message": "База данных временно занята. Повтори операцию.", "status_code": 503}
    audit_log_fn(
        "email_account_created",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="email_account",
        entity_id=str(account_id),
        details={"label": data.label, "address": data.address},
    )
    account = load_account_fn(account_id)
    if account and account.get("is_active"):
        sync_account_fn(account, force=True)
    return {"status": "success", "id": account_id}


def update_email_account_record(
    account_id: int,
    data,
    *,
    actor: dict,
    get_connection,
    normalize_payload_fn,
    encrypt_secret_fn,
    audit_log_fn,
    load_account_fn,
    sync_account_fn,
):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        now = int(time.time())
        c.execute("SELECT * FROM email_accounts WHERE id=?", (account_id,))
        existing_row = c.fetchone()
        existing = dict(existing_row) if existing_row else {}
        payload = normalize_payload_fn(data, existing=existing)
        if data.is_default:
            c.execute("UPDATE email_accounts SET is_default=0")
        c.execute("SELECT password, smtp_password FROM email_accounts WHERE id=?", (account_id,))
        existing_credentials = c.fetchone()
        password_to_save = encrypt_secret_fn(payload["password"]) if payload["password"] else (existing_credentials[0] if existing_credentials else "")
        smtp_password_to_save = encrypt_secret_fn(payload["smtp_password"]) if payload["smtp_password"] else (existing_credentials[1] if existing_credentials else "")
        c.execute(
            """
            UPDATE email_accounts
            SET label=?, address=?, login=?, password=?, imap_host=?, imap_port=?, smtp_host=?, smtp_port=?, smtp_login=?, smtp_password=?,
                inbox_folder=?, archive_folder=?, is_default=?, is_active=?, updated_at=?
            WHERE id=?
            """,
            (
                payload["label"],
                payload["address"],
                payload["login"],
                password_to_save,
                payload["imap_host"],
                payload["imap_port"],
                payload["smtp_host"],
                payload["smtp_port"],
                payload["smtp_login"],
                smtp_password_to_save,
                payload["inbox_folder"],
                payload["archive_folder"],
                payload["is_default"],
                payload["is_active"],
                now,
                account_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log_fn(
        "email_account_updated",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="email_account",
        entity_id=str(account_id),
        details={"label": data.label, "address": data.address},
    )
    account = load_account_fn(account_id)
    if account and account.get("is_active"):
        sync_account_fn(account, force=True)
    return {"status": "success"}


def delete_email_account_record(account_id: int, *, actor: dict, get_connection, audit_log_fn):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM email_messages WHERE account_id=?", (account_id,))
        c.execute("DELETE FROM email_accounts WHERE id=?", (account_id,))
        conn.commit()
    finally:
        conn.close()
    audit_log_fn(
        "email_account_deleted",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="email_account",
        entity_id=str(account_id),
    )
    return {"status": "success"}


def retry_failed_email_accounts(account_id: int = 0, *, get_connection, sync_account_fn):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        params = []
        sql = """
            SELECT *
            FROM email_accounts
            WHERE is_active=1
              AND (last_sync_status='error' OR sync_fail_count > 0 OR next_retry_at > 0)
        """
        if account_id:
            sql += " AND id=?"
            params.append(account_id)
        sql += " ORDER BY is_default DESC, id ASC"
        c.execute(sql, params)
        accounts = [dict(row) for row in c.fetchall()]
    finally:
        conn.close()

    retried = []
    failed = []
    for account in accounts:
        result = sync_account_fn(account, force=True)
        account_result = {
            "account_id": account["id"],
            "address": account.get("address", ""),
            "status": result.get("status", "unknown"),
        }
        if result.get("error"):
            account_result["error"] = result["error"]
            failed.append(account_result)
        else:
            retried.append(account_result)

    return {
        "status": "success",
        "retried_accounts": retried,
        "failed_accounts": failed,
        "count": len(retried),
    }
