import json, time, email, datetime, asyncio, os
from email.utils import parseaddr
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.message import EmailMessage
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from database import get_connection, audit_log, create_notification, create_targeted_notifications, get_notifications_for_user, mark_notification_read, mark_all_notifications_read, get_dismissed_notification_keys, dismiss_notifications_for_user, record_error_log
from auth_security import get_request_user
from permissions import require_approved_user, require_director, has_permission
from schemas import (
    MeetingData,
    MeetingUpdate,
    GlobalChatData,
    GlobalMessageData,
    TaskData,
    TaskUpdate,
    TaskChatMessageData,
    CompanyFeedPostData,
    CompanyFeedCommentData,
    CompanyFeedReactionData,
    CompanyFeedVoteData,
    CompanyFeedPinData,
    EmailAccountData,
    EmailMessageStateData,
)
from app_logging import get_logger
from services.mail_service import (
    connect_imap_account as connect_imap_account_service,
    decode_mime_value as decode_mime_value_service,
    email_account_defaults as email_account_defaults_service,
    email_provider_key as email_provider_key_service,
    extract_plain_body as extract_plain_body_service,
    find_imap_folder_by_flag as find_imap_folder_by_flag_service,
    format_email_date as format_email_date_service,
    normalize_email_account_payload as normalize_email_account_payload_service,
    parse_imap_list_line as parse_imap_list_line_service,
    quote_imap_mailbox as quote_imap_mailbox_service,
    safe_filename as safe_filename_service,
    safe_text as safe_text_service,
    smtp_credentials as smtp_credentials_service,
    test_email_account_connection as test_email_account_connection_service,
)
from services.collaboration_service import (
    list_meetings,
    create_meeting_record,
    update_meeting_record,
    list_chats,
    create_chat_record,
    delete_chat_record,
    list_chat_messages,
    create_chat_message,
    list_tasks,
    resolve_task_executor,
    create_task_record,
    update_task_record,
    delete_task_record,
    add_task_message,
    list_company_feed,
    create_company_feed_post,
    add_company_feed_comment,
    toggle_company_feed_reaction,
    vote_company_feed_poll,
    mark_company_feed_read,
    set_company_feed_pin,
)
from services.email_ops_service import (
    list_email_accounts as list_email_accounts_service,
    create_email_account_record as create_email_account_record_service,
    update_email_account_record as update_email_account_record_service,
    delete_email_account_record as delete_email_account_record_service,
    retry_failed_email_accounts as retry_failed_email_accounts_service,
)
from services.document_workflow_service import list_documents_for_task, sync_document_workflow
from settings import MAIL_IMAP_TIMEOUT, MAIL_SMTP_TIMEOUT, MAIL_SYNC_BATCH

# === ПОДКЛЮЧАЕМ МЕНЕДЖЕР WEBSOCKETS ===
from utils import SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT, manager, decrypt_secret, encrypt_secret

router = APIRouter()
logger = get_logger("communications")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
EMAIL_ATTACHMENTS_DIR = os.path.join(UPLOADS_DIR, "email_attachments")


def _safe_text(value: str, fallback: str = "") -> str:
    return safe_text_service(value, fallback)


def _json_load(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _parse_notification_date(value: str):
    raw = _safe_text(value)
    if not raw:
        return None
    for pattern in (
        "%d.%m.%Y",
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.datetime.strptime(raw[:19], pattern)
        except Exception:
            continue
    return None


def _notification_ts(value, fallback: int = 0) -> int:
    if isinstance(value, (int, float)) and int(value or 0) > 0:
        return int(value)
    parsed = _parse_notification_date(str(value or ""))
    if parsed:
        return int(parsed.timestamp())
    return int(fallback or time.time())


def _notification_matches_user(value: str, actor_name: str, actor_email: str, actor_role: str = "") -> bool:
    text = _safe_text(value)
    if not text:
        return True
    lowered = text.lower()
    return (
        (actor_name and actor_name.lower() in lowered)
        or (actor_email and actor_email.lower() in lowered)
        or (actor_role and actor_role.lower() in lowered)
    )


def _approval_matches_user(row: dict, actor_name: str, actor_email: str, actor_role: str) -> bool:
    if actor_role == "Директор":
        return True
    assignees = _json_load(row.get("current_assignees"), [])
    assignee_text = " ".join([_safe_text(item) for item in assignees if _safe_text(item)])
    if _notification_matches_user(assignee_text, actor_name, actor_email, actor_role):
        return True
    route_text = json.dumps(row or {}, ensure_ascii=False)
    return _notification_matches_user(route_text, actor_name, actor_email, actor_role)


def _append_live_notification(bucket: list, **kwargs):
    payload = {
        "id": kwargs.get("id"),
        "title": kwargs.get("title") or "Уведомление",
        "message": kwargs.get("message") or "",
        "user_email": kwargs.get("user_email") or "",
        "user_name": kwargs.get("user_name") or "",
        "category": kwargs.get("category") or "system",
        "entity_type": kwargs.get("entity_type") or "",
        "entity_id": str(kwargs.get("entity_id") or ""),
        "is_read": int(kwargs.get("is_read") or 0),
        "created_at": int(kwargs.get("created_at") or time.time()),
        "synthetic": 1,
    }
    bucket.append(payload)


def _load_live_notifications(actor: dict, limit: int = 80) -> list[dict]:
    actor_name = _safe_text(actor.get("name"))
    actor_email = _safe_text(actor.get("email"))
    actor_role = _safe_text(actor.get("role"))
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    soon = today + datetime.timedelta(days=3)

    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        items: list[dict] = []

        if has_permission(actor, "emails", "read"):
            c.execute(
                """
                SELECT m.id, m.subject, m.sender, m.sender_email, m.received_at, m.created_at, a.label
                FROM email_messages m
                LEFT JOIN email_accounts a ON a.id = m.account_id
                WHERE COALESCE(m.is_deleted, 0)=0
                  AND COALESCE(m.is_archived, 0)=0
                  AND COALESCE(m.is_read, 0)=0
                ORDER BY COALESCE(m.created_at, 0) DESC, m.id DESC
                LIMIT 8
                """
            )
            for row in c.fetchall():
                item = dict(row)
                _append_live_notification(
                    items,
                    id=f"live-email-{item.get('id')}",
                    title=item.get("subject") or "Новое письмо",
                    message=f"От {_safe_text(item.get('sender')) or _safe_text(item.get('sender_email')) or 'неизвестного отправителя'} · {_safe_text(item.get('label')) or 'Почта'}",
                    category="email",
                    entity_type="email",
                    entity_id=item.get("id"),
                    created_at=_notification_ts(item.get("created_at") or item.get("received_at")),
                )

        if has_permission(actor, "tasks", "read"):
            c.execute(
                """
                SELECT id, title, executor, deadline, priority, status, updated_at
                FROM tasks
                WHERE COALESCE(status, '') NOT IN ('completed', 'canceled')
                ORDER BY id DESC
                LIMIT 160
                """
            )
            for row in c.fetchall():
                item = dict(row)
                executor = _safe_text(item.get("executor"))
                mine = not executor or actor_role == "Директор" or _notification_matches_user(executor, actor_name, actor_email, actor_role)
                deadline_dt = _parse_notification_date(item.get("deadline"))
                if not mine or not deadline_dt or deadline_dt >= today:
                    continue
                _append_live_notification(
                    items,
                    id=f"live-task-{item.get('id')}",
                    title=item.get("title") or "Просроченная задача",
                    message=f"Срок {item.get('deadline') or 'не указан'} · Исполнитель: {executor or 'не назначен'}",
                    category="task",
                    entity_type="task",
                    entity_id=item.get("id"),
                    created_at=_notification_ts(item.get("updated_at") or item.get("deadline")),
                )

        if has_permission(actor, "approvals", "read"):
            c.execute(
                """
                SELECT id, title, status, current_assignees, due_at, created_at
                FROM approvals
                WHERE COALESCE(status, '')='pending'
                ORDER BY id DESC
                LIMIT 160
                """
            )
            for row in c.fetchall():
                item = dict(row)
                if not _approval_matches_user(item, actor_name, actor_email, actor_role):
                    continue
                due_at = int(item.get("due_at") or 0)
                due_text = datetime.datetime.fromtimestamp(due_at).strftime("%d.%m.%Y %H:%M") if due_at else "без SLA"
                _append_live_notification(
                    items,
                    id=f"live-approval-{item.get('id')}",
                    title=item.get("title") or "Согласование ожидает решения",
                    message=f"Ожидает решения · срок {due_text}",
                    category="approval",
                    entity_type="approval",
                    entity_id=item.get("id"),
                    created_at=_notification_ts(due_at or item.get("created_at")),
                )

        if has_permission(actor, "clients", "read"):
            c.execute(
                """
                SELECT id, title, client_name, responsible, stage, next_action, next_action_date, updated_at
                FROM crm_leads
                ORDER BY updated_at DESC, id DESC
                LIMIT 160
                """
            )
            for row in c.fetchall():
                item = dict(row)
                responsible = _safe_text(item.get("responsible"))
                mine = not responsible or actor_role == "Директор" or _notification_matches_user(responsible, actor_name, actor_email, actor_role)
                next_action_dt = _parse_notification_date(item.get("next_action_date"))
                is_new = _safe_text(item.get("stage")).lower() in {"new", "draft", "incoming", ""}
                is_due = next_action_dt and next_action_dt <= soon
                if not mine or not (is_new or is_due):
                    continue
                _append_live_notification(
                    items,
                    id=f"live-lead-{item.get('id')}",
                    title=item.get("title") or item.get("client_name") or "Новый лид",
                    message=f"{item.get('client_name') or 'Клиент'} · Следующее действие: {_safe_text(item.get('next_action')) or 'нужно назначить'}",
                    category="lead",
                    entity_type="lead",
                    entity_id=item.get("id"),
                    created_at=_notification_ts(item.get("updated_at") or item.get("next_action_date")),
                )

        if has_permission(actor, "projects", "read"):
            c.execute(
                """
                SELECT id, title, client_name, responsible, stage, next_action, next_action_date, amount, currency, updated_at
                FROM crm_deals
                ORDER BY updated_at DESC, id DESC
                LIMIT 160
                """
            )
            for row in c.fetchall():
                item = dict(row)
                responsible = _safe_text(item.get("responsible"))
                mine = not responsible or actor_role == "Директор" or _notification_matches_user(responsible, actor_name, actor_email, actor_role)
                next_action_dt = _parse_notification_date(item.get("next_action_date"))
                if not mine or not next_action_dt or next_action_dt > soon:
                    continue
                amount = f"{int(float(item.get('amount') or 0)):,}".replace(",", " ")
                _append_live_notification(
                    items,
                    id=f"live-deal-{item.get('id')}",
                    title=item.get("title") or item.get("client_name") or "Сделка",
                    message=f"{item.get('client_name') or 'Клиент'} · {amount} {item.get('currency') or 'RUB'} · {_safe_text(item.get('next_action')) or 'нужен следующий шаг'}",
                    category="deal",
                    entity_type="deal",
                    entity_id=item.get("id"),
                    created_at=_notification_ts(item.get("updated_at") or item.get("next_action_date")),
                )

        if has_permission(actor, "finance", "read"):
            c.execute(
                """
                SELECT id, title, kind, amount, currency, due_date, status, updated_at
                FROM finance_payments
                WHERE COALESCE(status, '') NOT IN ('paid', 'posted', 'done', 'completed', 'canceled')
                ORDER BY id DESC
                LIMIT 200
                """
            )
            for row in c.fetchall():
                item = dict(row)
                due_dt = _parse_notification_date(item.get("due_date"))
                if not due_dt or due_dt > soon:
                    continue
                amount = f"{int(float(item.get('amount') or 0)):,}".replace(",", " ")
                due_text = due_dt.strftime("%d.%m.%Y")
                _append_live_notification(
                    items,
                    id=f"live-finance-{item.get('id')}",
                    title=item.get("title") or ("Входящий платёж" if _safe_text(item.get("kind")) == "incoming" else "Исходящий платёж"),
                    message=f"{amount} {item.get('currency') or 'RUB'} · срок оплаты {due_text}",
                    category="finance",
                    entity_type="finance_payment",
                    entity_id=item.get("id"),
                    created_at=_notification_ts(item.get("updated_at") or item.get("due_date")),
                )

        items.sort(key=lambda item: (0 if not item.get("is_read") else 1, -int(item.get("created_at") or 0)))
        return items[: max(1, int(limit or 80))]
    finally:
        conn.close()


def _build_notification_feed(actor: dict, limit: int = 80):
    stored = get_notifications_for_user(actor.get("email", ""), actor.get("name", ""), limit=limit)
    live = _load_live_notifications(actor, limit=limit)
    dismissed_keys = get_dismissed_notification_keys(actor.get("email", ""))
    seen_keys = set()
    merged = []

    def item_key(item: dict):
        return (
            _safe_text(item.get("entity_type")),
            _safe_text(item.get("entity_id")),
            _safe_text(item.get("title")),
            _safe_text(item.get("message")),
        )

    for item in stored:
        payload = dict(item)
        payload["synthetic"] = 0
        if f"stored:{payload.get('id')}" in dismissed_keys:
            continue
        merged.append(payload)
        seen_keys.add(item_key(payload))

    for item in live:
        if str(item.get("id") or "") in dismissed_keys:
            continue
        key = item_key(item)
        if key in seen_keys:
            continue
        merged.append(item)
        seen_keys.add(key)

    merged.sort(key=lambda item: (0 if not item.get("is_read") else 1, -int(item.get("created_at") or 0)))
    return merged[: max(1, int(limit or 80))]


def _email_provider_key(address: str) -> str:
    return email_provider_key_service(address)


def _email_account_defaults(address: str) -> dict:
    return email_account_defaults_service(address)


def _normalize_email_account_payload(data: EmailAccountData, existing: dict | None = None) -> dict:
    return normalize_email_account_payload_service(data, existing)


def _decode_mime_value(value):
    return decode_mime_value_service(value)


def _extract_plain_body(msg):
    return extract_plain_body_service(msg)


def _safe_filename(value: str) -> str:
    return safe_filename_service(value)


def _sync_attachments_for_message(c, msg, message_db_id: int):
    os.makedirs(EMAIL_ATTACHMENTS_DIR, exist_ok=True)
    c.execute("DELETE FROM email_attachments WHERE message_id=?", (message_db_id,))
    for part in msg.walk():
        filename = _decode_mime_value(part.get_filename() or "")
        if not filename:
            continue
        payload = part.get_payload(decode=True) or b""
        safe_name = _safe_filename(filename)
        stored_filename = f"{message_db_id}_{safe_name}"
        file_path = os.path.join(EMAIL_ATTACHMENTS_DIR, stored_filename)
        with open(file_path, "wb") as attachment_file:
            attachment_file.write(payload)
        c.execute(
            """
            INSERT INTO email_attachments (message_id, filename, stored_path, mime_type, size, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message_db_id,
                filename,
                f"/uploads/email_attachments/{stored_filename}",
                part.get_content_type() or "",
                len(payload),
                int(time.time()),
            ),
        )


def _format_email_date(raw_date):
    return format_email_date_service(raw_date)


def _parse_imap_list_line(line: bytes | str):
    return parse_imap_list_line_service(line)


def _find_imap_folder_by_flag(mail, flag: str, fallback: str = "Archive") -> str:
    return find_imap_folder_by_flag_service(mail, flag, fallback)


def _quote_imap_mailbox(mail, mailbox: str) -> str:
    return quote_imap_mailbox_service(mail, mailbox)


def _get_default_outbound_account():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM email_accounts
        WHERE is_active=1
        ORDER BY is_default DESC, id ASC
        LIMIT 1
        """
    )
    account = c.fetchone()
    conn.close()
    return dict(account) if account else None


def _director_only(request: Request):
    return require_director(request)


def _mail_admin(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return None
    if actor.get("role") == "Директор" or has_permission(actor, "emails", "manage_accounts"):
        return actor
    return None


def _api_error(status_code: int, error: str, **payload):
    return JSONResponse(status_code=status_code, content={"error": error, **payload})


def _is_locked_error(exc: Exception) -> bool:
    return "database is locked" in str(exc or "").lower()


def _connect_imap_account(account: dict):
    return connect_imap_account_service(account, decrypt_secret=decrypt_secret, imap_timeout=MAIL_IMAP_TIMEOUT)


def _smtp_credentials(account: dict):
    return smtp_credentials_service(
        account,
        decrypt_secret=decrypt_secret,
        default_host=SMTP_HOST,
        default_port=SMTP_PORT,
        default_user=SMTP_USER,
        default_pass=SMTP_PASS,
    )


def _register_delivery_event(account_id: int, message_id: int, recipient: str, subject: str, status: str, error_text: str = "", attempts: int = 0):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO email_delivery_events (account_id, message_id, recipient, subject, status, error_text, attempts, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (account_id, message_id, recipient, subject[:500], status, error_text[:1000], attempts, int(time.time())),
    )
    conn.commit()
    conn.close()


def _update_account_delivery_status(account_id: int, status: str, error_text: str = ""):
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    if status == "success":
        c.execute(
            """
            UPDATE email_accounts
            SET delivery_fail_count=0, last_delivery_at=?, last_delivery_error=''
            WHERE id=?
            """,
            (now, account_id),
        )
    else:
        c.execute("SELECT delivery_fail_count, last_alert_at, label, address FROM email_accounts WHERE id=?", (account_id,))
        row = c.fetchone()
        fail_count = (row[0] if row else 0) + 1
        last_alert_at = row[1] if row else 0
        label = row[2] if row else ""
        address = row[3] if row else ""
        c.execute(
            """
            UPDATE email_accounts
            SET delivery_fail_count=?, last_delivery_at=?, last_delivery_error=?
            WHERE id=?
            """,
            (fail_count, now, error_text[:500], account_id),
        )
        if fail_count >= 3 and now - (last_alert_at or 0) > 14400:
            create_notification(
                title="Проблема с отправкой почты",
                message=f"Ящик {label or address} несколько раз не смог отправить письмо. Проверь настройки SMTP.",
                category="system",
                entity_type="email_account",
                entity_id=str(account_id),
            )
            c.execute("UPDATE email_accounts SET last_alert_at=? WHERE id=?", (now, account_id))
    conn.commit()
    conn.close()


def _send_with_retry(account: dict, email_message: EmailMessage, recipient: str, subject: str, message_id: int = 0, attempts: int = 3, quiet: bool = False):
    smtp_host, smtp_port, smtp_login, smtp_pass, _sender_address = _smtp_credentials(account)
    if not recipient or not smtp_host or not smtp_login or not smtp_pass:
        return False, "smtp_not_configured"
    last_error = ""
    log_fn = logger.info if quiet else logger.warning
    for attempt in range(1, attempts + 1):
        server = None
        try:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=MAIL_SMTP_TIMEOUT)
            server.login(smtp_login, smtp_pass)
            server.send_message(email_message)
            server.quit()
            server = None
            _register_delivery_event(account.get("id", 0), message_id, recipient, subject, "success", attempts=attempt)
            _update_account_delivery_status(account.get("id", 0), "success")
            return True, ""
        except Exception as exc:
            last_error = str(exc)
            log_fn("Outbound email send failed on attempt %s for %s: %s", attempt, recipient, exc)
            if not quiet:
                record_error_log(
                    source="email_delivery",
                    message=last_error,
                    path="/api/emails/reply",
                    method="SMTP",
                    severity="warning",
                )
            fatal_auth_error = "authentication failed" in last_error.lower() or "invalid format" in last_error.lower()
            if attempt < attempts and not fatal_auth_error:
                time.sleep(min(1.2 * attempt, 2.5))
            else:
                break
        finally:
            if server is not None:
                try:
                    server.close()
                except Exception:
                    pass

    if account.get("id"):
        _register_delivery_event(account.get("id", 0), message_id, recipient, subject, "failed", error_text=last_error, attempts=min(attempts, attempt))
        _update_account_delivery_status(account.get("id", 0), "failed", last_error)
    return False, last_error or "smtp_send_failed"


def _test_email_account_connection(account: dict):
    return test_email_account_connection_service(
        account,
        connect_imap_account_fn=_connect_imap_account,
        smtp_credentials_fn=_smtp_credentials,
        smtp_timeout=MAIL_SMTP_TIMEOUT,
        logger=logger,
    )


def _sync_folder(mail, account_id: int, folder_name: str, is_archived: int):
    try:
        status, _ = mail.select(folder_name)
        if status != "OK":
            return
        status, data = mail.uid('search', None, 'ALL')
        if status != "OK":
            return
        uids = [uid.decode("utf-8") for uid in data[0].split()][-MAIL_SYNC_BATCH:]
        conn = get_connection()
        c = conn.cursor()
        for uid in reversed(uids):
            status, msg_data = mail.uid('fetch', uid, '(RFC822 FLAGS)')
            if status != "OK":
                continue
            raw_bytes = b""
            flags_blob = ""
            for part in msg_data:
                if isinstance(part, tuple):
                    raw_bytes = part[1]
                    flags_blob = part[0].decode("utf-8", errors="ignore")
                    break
            if not raw_bytes:
                continue
            msg = email.message_from_bytes(raw_bytes)
            subject = _decode_mime_value(msg.get("Subject", "")) or "Без темы"
            sender = _decode_mime_value(msg.get("From", "")) or "Неизвестный отправитель"
            sender_email = parseaddr(msg.get("From", ""))[1]
            body_text = _extract_plain_body(msg)
            body_preview = (body_text[:320] + "...") if len(body_text) > 320 else body_text
            is_read = 1 if "\\Seen" in flags_blob else 0
            received_at = _format_email_date(msg.get("Date", ""))
            created_at = int(time.time())
            c.execute(
                """
                INSERT INTO email_messages (
                    account_id, uid, folder, subject, sender, sender_email, body_preview, body_text,
                    received_at, is_read, is_archived, is_deleted, created_at, synced_at, message_id_header, reply_to_email
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                ON CONFLICT(account_id, uid, folder) DO UPDATE SET
                    subject=excluded.subject,
                    sender=excluded.sender,
                    sender_email=excluded.sender_email,
                    body_preview=excluded.body_preview,
                    body_text=excluded.body_text,
                    received_at=excluded.received_at,
                    is_read=excluded.is_read,
                    is_archived=excluded.is_archived,
                    is_deleted=0,
                    synced_at=excluded.synced_at,
                    message_id_header=excluded.message_id_header,
                    reply_to_email=excluded.reply_to_email
                """,
                (
                    account_id,
                    uid,
                    folder_name,
                    subject,
                    sender,
                    sender_email,
                    body_preview,
                    body_text,
                    received_at,
                    is_read,
                    is_archived,
                    created_at,
                    created_at,
                    (msg.get("Message-ID") or "")[:500],
                    parseaddr(msg.get("Reply-To", "") or msg.get("From", ""))[1],
                ),
            )
            c.execute("SELECT id FROM email_messages WHERE account_id=? AND uid=? AND folder=?", (account_id, uid, folder_name))
            db_message_row = c.fetchone()
            if db_message_row:
                _sync_attachments_for_message(c, msg, db_message_row[0])
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Folder sync skipped for %s/%s: %s", account_id, folder_name, exc)


def sync_email_account(account: dict, force: bool = False):
    now = int(time.time())
    if not force and int(account.get("next_retry_at") or 0) > now:
        return {"status": "deferred", "next_retry_at": int(account.get("next_retry_at") or 0)}
    conn = get_connection()
    c = conn.cursor()
    try:
        mail = _connect_imap_account(account)
        if "gmail" in str(account.get("imap_host") or "").lower():
            detected_archive = _find_imap_folder_by_flag(mail, "\\All", account.get("archive_folder") or "Archive")
            if detected_archive and detected_archive != (account.get("archive_folder") or ""):
                c.execute("UPDATE email_accounts SET archive_folder=? WHERE id=?", (detected_archive, account["id"]))
                conn.commit()
                account["archive_folder"] = detected_archive
        _sync_folder(mail, account["id"], account.get("inbox_folder") or "INBOX", 0)
        archive_folder = account.get("archive_folder") or "Archive"
        if archive_folder:
            _sync_folder(mail, account["id"], archive_folder, 1)
        mail.logout()
        c.execute(
            """
            UPDATE email_accounts
            SET last_sync_at=?, last_error='', sync_fail_count=0, next_retry_at=0, last_sync_status='ok'
            WHERE id=?
            """,
            (now, account["id"]),
        )
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        c.execute("SELECT sync_fail_count, last_alert_at, label, address FROM email_accounts WHERE id=?", (account["id"],))
        row = c.fetchone()
        fail_count = ((row[0] if row else 0) or 0) + 1
        next_retry_at = now + min(3600, (2 ** min(fail_count, 6)) * 60)
        last_alert_at = (row[1] if row else 0) or 0
        label = row[2] if row else ""
        address = row[3] if row else ""
        error_text = str(e)[:500]
        c.execute(
            """
            UPDATE email_accounts
            SET last_error=?, last_sync_at=?, sync_fail_count=?, next_retry_at=?, last_sync_status='error'
            WHERE id=?
            """,
            (error_text, now, fail_count, next_retry_at, account["id"]),
        )
        conn.commit()
        logger.warning("Mailbox sync failed for %s: %s", account.get("address"), e)
        record_error_log(
            source="email_sync",
            message=error_text,
            path="/api/email/accounts/sync",
            method="IMAP",
            severity="warning",
        )
        if fail_count >= 3 and now - last_alert_at > 14400:
            create_notification(
                title="Сбой синхронизации почты",
                message=f"Ящик {label or address} не синхронизируется. Следующая попытка будет выполнена автоматически.",
                category="system",
                entity_type="email_account",
                entity_id=str(account["id"]),
            )
            c.execute("UPDATE email_accounts SET last_alert_at=? WHERE id=?", (now, account["id"]))
            conn.commit()
        return {"status": "error", "error": error_text, "next_retry_at": next_retry_at}
    finally:
        conn.close()


def _load_email_account(account_id: int):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM email_accounts WHERE id=?", (account_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def _sync_active_email_accounts(force: bool = False):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM email_accounts WHERE is_active=1 ORDER BY is_default DESC, id ASC")
    accounts = [dict(row) for row in c.fetchall()]
    conn.close()
    for account in accounts:
        sync_email_account(account, force=force)


def _mailbox_summary():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            a.id,
            a.label,
            a.address,
            a.login,
            a.imap_host,
            a.smtp_host,
            a.smtp_login,
            a.inbox_folder,
            a.archive_folder,
            a.is_default,
            a.is_active,
            a.last_sync_at,
            a.last_error,
            a.last_sync_status,
            a.sync_fail_count,
            a.next_retry_at,
            a.delivery_fail_count,
            a.last_delivery_at,
            a.last_delivery_error,
            SUM(CASE WHEN m.is_deleted=0 AND m.is_archived=0 THEN 1 ELSE 0 END) AS total_inbox,
            SUM(CASE WHEN m.is_deleted=0 AND m.is_archived=0 AND m.is_read=0 THEN 1 ELSE 0 END) AS unread_count,
            SUM(CASE WHEN m.is_deleted=0 AND m.is_archived=1 THEN 1 ELSE 0 END) AS archived_count
        FROM email_accounts a
        LEFT JOIN email_messages m ON m.account_id = a.id
        GROUP BY a.id
        ORDER BY a.is_default DESC, a.id ASC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _mail_message_action(message_id: int, action: str):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT m.*, a.login, a.password, a.imap_host, a.imap_port, a.archive_folder
        FROM email_messages m
        JOIN email_accounts a ON a.id = m.account_id
        WHERE m.id=?
        """,
        (message_id,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "Письмо не найдено"
    message = dict(row)
    try:
        mail = _connect_imap_account(message)
        source_folder = message.get("folder") or "INBOX"
        uid = str(message.get("uid") or "")
        if action == "archive":
            archive_folder = message.get("archive_folder") or "Archive"
            if message.get("imap_host") and "gmail" in str(message.get("imap_host")).lower():
                mail.select("INBOX")
                mail.uid("STORE", uid, "-X-GM-LABELS", "(\\Inbox)")
            else:
                archive_folder = _find_imap_folder_by_flag(mail, "\\All", archive_folder)
                mail.select(_quote_imap_mailbox(mail, source_folder))
                mail.uid("COPY", uid, _quote_imap_mailbox(mail, archive_folder))
                mail.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                mail.expunge()
            c.execute("UPDATE email_messages SET is_archived=1, is_deleted=0 WHERE id=?", (message_id,))
        elif action == "restore":
            archive_folder = message.get("archive_folder") or "Archive"
            if message.get("imap_host") and "gmail" in str(message.get("imap_host")).lower():
                mail.select("INBOX")
                mail.uid("STORE", uid, "+X-GM-LABELS", "(\\Inbox)")
            else:
                archive_folder = _find_imap_folder_by_flag(mail, "\\All", archive_folder)
                mail.select(_quote_imap_mailbox(mail, archive_folder))
                mail.uid("COPY", uid, _quote_imap_mailbox(mail, "INBOX"))
                mail.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                mail.expunge()
            c.execute("UPDATE email_messages SET is_archived=0, is_deleted=0 WHERE id=?", (message_id,))
        elif action == "delete":
            mail.select(_quote_imap_mailbox(mail, source_folder))
            mail.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            mail.expunge()
            c.execute("UPDATE email_messages SET is_deleted=1 WHERE id=?", (message_id,))
        mail.logout()
        conn.commit()
        conn.close()
        return True, ""
    except Exception as e:
        conn.close()
        return False, str(e)


def _load_message_with_account(message_id: int):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT m.*, a.address, a.login, a.password, a.smtp_host, a.smtp_port, a.smtp_login, a.smtp_password
        FROM email_messages m
        JOIN email_accounts a ON a.id = m.account_id
        WHERE m.id=?
        """,
        (message_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


# Настоящая отправка SMTP-писем (ТЗ 2.7.2)
def send_smtp_notification(to_email, subject, text):
    account = _get_default_outbound_account()
    if not account:
        return False
    smtp_host, smtp_port, smtp_login, smtp_pass, sender_address = _smtp_credentials(account or {})
    if not smtp_host or not smtp_login or not smtp_pass:
        logger.info("SMTP notification skipped: outbound account is not fully configured")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = sender_address
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(text, 'plain', 'utf-8'))
        ok, error = _send_with_retry(account or {}, msg, to_email, subject, attempts=1, quiet=True)
        if not ok:
            logger.info("send_smtp_notification skipped/failed quietly: %s", error)
        return ok
    except Exception as e:
        logger.info("SMTP notification build failed quietly: %s", e)
        return False

@router.get("/api/meetings")
def get_meetings(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "meetings", "read"):
        return {"error": "forbidden"}
    return list_meetings()

@router.post("/api/meetings")
async def create_meeting(data: MeetingData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "meetings", "create"):
        return {"error": "forbidden"}
    meeting_id = create_meeting_record(
        title=data.title,
        m_date=data.m_date,
        m_time=data.m_time,
        participants=data.participants,
        agenda=data.agenda,
    )
    for participant in data.participants or []:
        create_targeted_notifications(
            "Новое совещание",
            f"{actor.get('name', 'Система')} пригласил(а) вас на «{data.title}» — {data.m_date or 'дата не указана'} {data.m_time or ''}".strip(),
            user_name=_safe_text(participant),
            role=_safe_text(participant),
            category="meeting",
            entity_type="meeting",
            entity_id=str(meeting_id),
            exclude_email=actor.get("email", ""),
        )
    await manager.broadcast({"type": "meetings"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "id": meeting_id}

@router.put("/api/meetings/{m_id}")
async def update_meeting(m_id: int, data: MeetingUpdate, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "meetings", "update"):
        return {"error": "forbidden"}
    update_meeting_record(
        meeting_id=m_id,
        title=data.title,
        m_date=data.m_date,
        m_time=data.m_time,
        participants=data.participants,
        agenda=data.agenda,
        decisions=data.decisions,
        status=data.status,
    )
    meeting_state = "отменено" if _safe_text(data.status).lower() in {"cancelled", "canceled"} else "обновлено"
    for participant in data.participants or []:
        create_targeted_notifications(
            "Совещание обновлено",
            f"Совещание «{data.title}» {meeting_state}. Дата: {data.m_date or 'не указана'} {data.m_time or ''}".strip(),
            user_name=_safe_text(participant),
            role=_safe_text(participant),
            category="meeting",
            entity_type="meeting",
            entity_id=str(m_id),
            exclude_email=actor.get("email", ""),
        )
    await manager.broadcast({"type": "meetings"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success"}

@router.get("/api/chats")
def get_chats(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "read"):
        return {"error": "forbidden"}
    return list_chats(user_name=actor.get("name", ""), user_role=actor.get("role", ""))

@router.post("/api/chats")
async def create_chat(data: GlobalChatData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "create"):
        return {"error": "forbidden"}
    chat_id = create_chat_record(name=data.name, creator=actor.get("name", ""), participants=data.participants)
    for participant in data.participants or []:
        create_targeted_notifications(
            "Вас добавили в корпоративный чат",
            f"{actor.get('name', 'Система')} добавил(а) вас в чат «{data.name}».",
            user_name=_safe_text(participant),
            role=_safe_text(participant),
            category="chat",
            entity_type="chat",
            entity_id=str(chat_id),
            exclude_email=actor.get("email", ""),
        )
    await manager.broadcast({"type": "chats"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "id": chat_id}

@router.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "delete"):
        return {"error": "forbidden"}
    delete_chat_record(chat_id)
    await manager.broadcast({"type": "chats"})
    return {"status": "success"}

@router.get("/api/chats/{chat_id}/messages")
def get_messages(chat_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "read"):
        return {"error": "forbidden"}
    return list_chat_messages(chat_id)

@router.post("/api/chats/{chat_id}/messages")
async def post_message(chat_id: int, data: GlobalMessageData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "create"):
        return {"error": "forbidden"}
    create_chat_message(
        chat_id=chat_id,
        user=actor.get("name", ""),
        role=actor.get("role", ""),
        text=data.text,
    )
    chat_conn = get_connection(row_factory=True)
    try:
        chat_row = dict(chat_conn.execute("SELECT name, type, participants FROM global_chats WHERE id=?", (chat_id,)).fetchone() or {})
    finally:
        chat_conn.close()
    try:
        chat_participants = json.loads(chat_row.get("participants") or "[]")
    except Exception:
        chat_participants = []
    for participant in chat_participants:
        create_targeted_notifications(
            "Новое сообщение в чате",
            f"{actor.get('name', 'Пользователь')} в «{chat_row.get('name') or 'Корпоративный чат'}»: {_safe_text(data.text)[:140]}",
            user_name=_safe_text(participant),
            role=_safe_text(participant),
            category="chat",
            entity_type="chat",
            entity_id=str(chat_id),
            exclude_email=actor.get("email", ""),
            fallback_to_director=False,
        )
    await manager.broadcast({"type": "chats"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success"}

@router.get("/api/email/accounts")
def get_email_accounts(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "emails", "read"):
        return {"error": "forbidden"}
    return list_email_accounts_service(
        mailbox_summary_fn=_mailbox_summary,
        can_manage_accounts=has_permission(actor, "emails", "manage_accounts"),
    )


@router.post("/api/email/accounts")
def create_email_account(data: EmailAccountData, request: Request):
    actor = _mail_admin(request)
    if not actor:
        return _api_error(403, "forbidden")
    result = create_email_account_record_service(
        data,
        actor=actor,
        get_connection=get_connection,
        normalize_payload_fn=_normalize_email_account_payload,
        encrypt_secret_fn=encrypt_secret,
        audit_log_fn=audit_log,
        load_account_fn=_load_email_account,
        sync_account_fn=sync_email_account,
        is_locked_error_fn=_is_locked_error,
    )
    if result.get("error"):
        return _api_error(int(result.get("status_code") or 400), result["error"], message=result.get("message", ""))
    return result


@router.put("/api/email/accounts/{account_id}")
def update_email_account(account_id: int, data: EmailAccountData, request: Request):
    actor = _mail_admin(request)
    if not actor:
        return _api_error(403, "forbidden")
    return update_email_account_record_service(
        account_id,
        data,
        actor=actor,
        get_connection=get_connection,
        normalize_payload_fn=_normalize_email_account_payload,
        encrypt_secret_fn=encrypt_secret,
        audit_log_fn=audit_log,
        load_account_fn=_load_email_account,
        sync_account_fn=sync_email_account,
    )


@router.delete("/api/email/accounts/{account_id}")
def delete_email_account(account_id: int, request: Request):
    actor = _mail_admin(request)
    if not actor:
        return _api_error(403, "forbidden")
    return delete_email_account_record_service(
        account_id,
        actor=actor,
        get_connection=get_connection,
        audit_log_fn=audit_log,
    )


@router.post("/api/email/accounts/{account_id}/sync")
def sync_email_account_route(account_id: int, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "read"):
        return {"error": "forbidden"}
    account = _load_email_account(account_id)
    if not account:
        return {"error": "not_found"}
    return sync_email_account(account, force=True)


@router.post("/api/email/accounts/{account_id}/test")
def test_email_account_route(account_id: int, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "manage_accounts"):
        return {"error": "forbidden"}
    account = _load_email_account(account_id)
    if not account:
        return {"error": "not_found"}
    result = _test_email_account_connection(account)
    audit_log(
        "email_account_tested",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="email_account",
        entity_id=str(account_id),
        details={"status": result.get("status")},
    )
    return result


@router.post("/api/email/retry_failed")
def retry_failed_email_ops(request: Request, account_id: int = 0):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "read"):
        return {"error": "forbidden"}
    return retry_failed_email_accounts_service(
        account_id,
        get_connection=get_connection,
        sync_account_fn=sync_email_account,
    )


@router.get("/api/emails")
def get_emails(request: Request, account_id: int = 0, filter_name: str = "all", query: str = "", force_refresh: int = 0):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "read"):
        return {"error": "forbidden"}
    if force_refresh:
        if account_id:
            account = _load_email_account(account_id)
            if account and account.get("is_active"):
                sync_email_account(account, force=True)
        else:
            _sync_active_email_accounts(force=True)

    conn = get_connection(row_factory=True)
    c = conn.cursor()
    clauses = ["m.is_deleted=0"]
    params = []
    if account_id:
        clauses.append("m.account_id=?")
        params.append(account_id)
    if filter_name == "new":
        clauses.append("m.is_archived=0")
        clauses.append("m.is_read=0")
    elif filter_name == "read":
        clauses.append("m.is_archived=0")
        clauses.append("m.is_read=1")
    elif filter_name == "archived":
        clauses.append("m.is_archived=1")
    else:
        clauses.append("m.is_archived=0")
    if query:
        clauses.append("(m.subject LIKE ? OR m.sender LIKE ? OR m.body_text LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like, like])
    sql = f"""
        SELECT m.*, a.label AS account_label, a.address AS account_address, a.last_error AS account_error
        FROM email_messages m
        JOIN email_accounts a ON a.id = m.account_id
        WHERE {' AND '.join(clauses)}
        ORDER BY m.created_at DESC, m.id DESC
        LIMIT 120
    """
    c.execute(sql, params)
    rows = [dict(row) for row in c.fetchall()]
    message_ids = [row["id"] for row in rows]
    attachments_map = {}
    if message_ids:
        placeholders = ",".join("?" for _ in message_ids)
        c.execute(
            f"SELECT * FROM email_attachments WHERE message_id IN ({placeholders}) ORDER BY id ASC",
            message_ids,
        )
        for attachment in c.fetchall():
            item = dict(attachment)
            attachments_map.setdefault(item["message_id"], []).append(item)
    conn.close()
    for row in rows:
        row["attachments"] = attachments_map.get(row["id"], [])
    return rows


@router.get("/api/notifications")
def get_notifications(request: Request, limit: int = 80):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    return _build_notification_feed(actor, limit=limit)


@router.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    mark_notification_read(notification_id, actor.get("email", ""), actor.get("name", ""))
    return {"status": "success"}


@router.post("/api/notifications/read_all")
def read_all_notifications(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    mark_all_notifications_read(actor.get("email", ""), actor.get("name", ""))
    return {"status": "success"}


@router.delete("/api/notifications")
def clear_notifications(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    feed = _build_notification_feed(actor, limit=300)
    keys = [
        str(item.get("id") or "") if int(item.get("synthetic") or 0) else f"stored:{item.get('id')}"
        for item in feed
        if item.get("id") not in (None, "")
    ]
    cleared = dismiss_notifications_for_user(actor.get("email", ""), keys)
    return {"status": "success", "cleared": cleared}


@router.post("/api/emails/{message_id}/read")
def mark_email_read(message_id: int, data: EmailMessageStateData, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "read"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE email_messages SET is_read=? WHERE id=?", (int(bool(data.read)), message_id))
    conn.commit()
    conn.close()
    return {"status": "success"}


@router.post("/api/emails/{message_id}/archive")
def archive_email(message_id: int, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "archive"):
        return {"error": "forbidden"}
    ok, error = _mail_message_action(message_id, "archive")
    return {"status": "success"} if ok else {"error": error}


@router.post("/api/emails/{message_id}/restore")
def restore_email(message_id: int, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "archive"):
        return {"error": "forbidden"}
    ok, error = _mail_message_action(message_id, "restore")
    return {"status": "success"} if ok else {"error": error}


@router.delete("/api/emails/{message_id}")
def delete_email(message_id: int, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "delete"):
        return {"error": "forbidden"}
    ok, error = _mail_message_action(message_id, "delete")
    return {"status": "success"} if ok else {"error": error}


@router.post("/api/emails/{message_id}/reply")
async def reply_email(message_id: int, request: Request, body: str = Form(...), files: list[UploadFile] = File(default=[])):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "emails", "reply"):
        return {"error": "forbidden"}
    message = _load_message_with_account(message_id)
    if not message:
        return {"error": "not_found"}
    to_email = message.get("reply_to_email") or message.get("sender_email")
    if not to_email:
        return {"error": "Не найден адрес получателя для ответа"}

    email_message = EmailMessage()
    email_message["From"] = message.get("address", "")
    email_message["To"] = to_email
    subject = message.get("subject") or "Без темы"
    email_message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if message.get("message_id_header"):
        email_message["In-Reply-To"] = message["message_id_header"]
        email_message["References"] = message["message_id_header"]
    email_message.set_content(body)

    for upload in files or []:
        payload = await upload.read()
        if not payload:
            continue
        content_type = upload.content_type or "application/octet-stream"
        maintype, _, subtype = content_type.partition("/")
        email_message.add_attachment(payload, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=upload.filename or "attachment")

    try:
        outbound_account = {
            "id": message.get("account_id"),
            "address": message.get("address"),
            "login": message.get("login"),
            "password": message.get("password"),
            "smtp_host": message.get("smtp_host"),
            "smtp_port": message.get("smtp_port"),
            "smtp_login": message.get("smtp_login"),
            "smtp_password": message.get("smtp_password"),
        }
        ok, error = _send_with_retry(outbound_account, email_message, to_email, email_message["Subject"], message_id=message_id)
        conn = get_connection()
        c = conn.cursor()
        if not ok:
            c.execute(
                "UPDATE email_messages SET delivery_status='failed', last_action_error=?, last_action_at=? WHERE id=?",
                (error[:500], int(time.time()), message_id),
            )
            conn.commit()
            conn.close()
            return {"error": error}
        c.execute(
            "UPDATE email_messages SET delivery_status='replied', last_action_error='', last_action_at=? WHERE id=?",
            (int(time.time()), message_id),
        )
        conn.commit()
        conn.close()
        create_notification(
            title="Ответ на письмо отправлен",
            message=f"{actor.get('name', 'Пользователь')} ответил(а) на письмо «{subject}»",
            category="email",
            entity_type="email",
            entity_id=str(message_id),
        )
        await manager.broadcast({"type": "notifications"})
        return {"status": "success"}
    except Exception as e:
        logger.warning("Reply email failed: %s", e)
        return {"error": str(e)}

@router.get("/api/tasks")
def get_tasks(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "tasks", "read"):
        return {"error": "forbidden"}
    return list_tasks()


def _task_access_flags(actor: dict, task: dict):
    actor_name = _safe_text(actor.get("name")).strip()
    executor = _safe_text(task.get("executor")).strip()
    is_director = _safe_text(actor.get("role")).strip() == "Директор"
    is_author = bool(actor_name) and actor_name == _safe_text(task.get("author")).strip()
    is_executor = bool(actor_name) and (executor == actor_name or executor.startswith(f"{actor_name} (И.О."))
    return {
        "is_director": is_director,
        "is_author": is_author,
        "is_executor": is_executor,
        "can_manage": is_director or is_author,
        "can_work": is_director or is_author or is_executor,
    }

@router.post("/api/tasks")
async def create_task(data: TaskData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "tasks", "create"):
        return {"error": "forbidden"}
    resolution = resolve_task_executor(data.executor)
    actual_executor = resolution["actual_executor"]
    task_id = create_task_record(
        title=data.title,
        description=data.description,
        author=actor.get("name", data.author),
        executor=actual_executor,
        deadline=data.deadline,
        recurrence=data.recurrence,
        priority=data.priority,
        project_id=data.project_id,
    )
    if resolution["executor_email"]:
        mail_text = f"Здравствуйте!\n\nВам назначена новая задача в Korda CRM:\n\nТема: {data.title}\nДедлайн: {data.deadline}\nОписание: {data.description}\n\nС уважением,\nСистема уведомлений Korda CRM"
        asyncio.create_task(asyncio.to_thread(send_smtp_notification, resolution["executor_email"], f"Новое поручение: {data.title}", mail_text))
    create_targeted_notifications(
        title="Новое поручение",
        message=f"{actor.get('name', data.author)} назначил(а) задачу «{data.title}» с дедлайном {data.deadline or 'без срока'}",
        user_email=resolution["executor_email"],
        user_name=resolution["executor_lookup_name"],
        role=resolution["executor_lookup_name"],
        category="task",
        entity_type="task",
        entity_id=str(task_id),
        exclude_email=actor.get("email", ""),
    )
    await manager.broadcast({"type": "tasks"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "id": task_id}

@router.put("/api/tasks/{task_id}")
async def update_task(task_id: int, data: TaskUpdate, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "tasks", "update"):
        return {"error": "forbidden"}
    task_conn = get_connection(row_factory=True)
    try:
        task_before = dict(task_conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone() or {})
    finally:
        task_conn.close()
    if not task_before:
        return {"error": "not_found", "message": "Поручение не найдено."}
    access = _task_access_flags(actor, task_before)
    update_payload = data.model_dump(exclude_none=True) if hasattr(data, "model_dump") else data.dict(exclude_none=True)
    changed_fields = set(update_payload.keys())
    if changed_fields == {"status"}:
        if not access["can_work"]:
            return {"error": "forbidden", "message": "Менять статус может исполнитель, автор поручения или директор."}
    elif changed_fields and not access["can_manage"]:
        return {"error": "forbidden", "message": "Изменять поручение может только его автор или директор."}
    update_task_record(
        task_id=task_id,
        status=data.status,
        executor=data.executor,
        history=data.history,
        priority=data.priority,
        title=data.title,
        description=data.description,
        deadline=data.deadline,
        project_id=data.project_id,
    )
    if data.executor and data.executor != task_before.get("executor"):
        executor_resolution = resolve_task_executor(data.executor)
        create_targeted_notifications(
            "Вам передано поручение",
            f"{actor.get('name', 'Система')} передал(а) вам задачу «{data.title or task_before.get('title') or 'Без названия'}».",
            user_email=executor_resolution.get("executor_email", ""),
            user_name=executor_resolution.get("executor_lookup_name", data.executor),
            role=executor_resolution.get("executor_lookup_name", data.executor),
            category="task",
            entity_type="task",
            entity_id=str(task_id),
            exclude_email=actor.get("email", ""),
        )
    completed_statuses = {"completed", "done", "closed"}
    if _safe_text(data.status).lower() in completed_statuses and _safe_text(task_before.get("status")).lower() not in completed_statuses:
        create_targeted_notifications(
            "Поручение выполнено",
            f"{actor.get('name', 'Исполнитель')} завершил(а) задачу «{data.title or task_before.get('title') or 'Без названия'}».",
            user_name=task_before.get("author", ""),
            category="task",
            entity_type="task",
            entity_id=str(task_id),
            exclude_email=actor.get("email", ""),
        )
    conn = get_connection(row_factory=True)
    try:
        for document_id in list_documents_for_task(conn, int(task_id or 0)):
            sync_document_workflow(conn, document_id, actor, f"Статус задачи -> {_safe_text(data.status or '')}", "workflow_task_sync")
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast({"type": "tasks"})
    await manager.broadcast({"type": "documents"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success"}


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "tasks", "update"):
        return {"error": "forbidden", "message": "Недостаточно прав для удаления поручения."}
    conn = get_connection(row_factory=True)
    try:
        task = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone() or {})
    finally:
        conn.close()
    if not task:
        return {"error": "not_found", "message": "Поручение не найдено."}
    if not _task_access_flags(actor, task)["can_manage"]:
        return {"error": "forbidden", "message": "Удалить поручение может только тот, кто его создал, или директор."}
    if not delete_task_record(task_id):
        return {"error": "not_found", "message": "Поручение уже удалено."}
    create_targeted_notifications(
        "Поручение удалено",
        f"{actor.get('name', 'Пользователь')} удалил(а) поручение «{task.get('title') or 'Без названия'}».",
        user_name=task.get("executor", ""),
        category="task",
        entity_type="task",
        entity_id=str(task_id),
        exclude_email=actor.get("email", ""),
        fallback_to_director=False,
    )
    await manager.broadcast({"type": "tasks"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success"}


@router.post("/api/tasks/{task_id}/messages")
async def post_task_message(task_id: int, data: TaskChatMessageData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "tasks", "update"):
        return {"error": "forbidden"}
    message_conn = get_connection(row_factory=True)
    try:
        task_row = dict(message_conn.execute("SELECT title, author, executor FROM tasks WHERE id=?", (task_id,)).fetchone() or {})
    finally:
        message_conn.close()
    if not task_row:
        return {"error": "not_found", "message": "Поручение не найдено."}
    if not _task_access_flags(actor, task_row)["can_work"]:
        return {"error": "forbidden", "message": "Комментарии доступны исполнителю, автору поручения и директору."}
    text = _safe_text(data.text).strip()
    if not text:
        return {"error": "validation_error", "message": "Напишите комментарий к задаче."}
    message = add_task_message(task_id=task_id, user=actor.get("name", "Пользователь"), role=actor.get("role", "Сотрудник"), text=text)
    for recipient_name in {task_row.get("author", ""), task_row.get("executor", "")}:
        if not recipient_name:
            continue
        create_targeted_notifications(
            "Новый комментарий к поручению",
            f"{actor.get('name', 'Пользователь')}: {text[:160]}",
            user_name=recipient_name,
            category="task",
            entity_type="task",
            entity_id=str(task_id),
            exclude_email=actor.get("email", ""),
            fallback_to_director=False,
        )
    await manager.broadcast({"type": "tasks"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "message_item": message}


@router.get("/api/feed/posts")
def get_company_feed(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "read"):
        return {"error": "forbidden"}
    return list_company_feed(user_email=actor.get("email", ""), user_role=actor.get("role", ""))


@router.post("/api/feed/posts")
async def create_feed_post(data: CompanyFeedPostData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "create"):
        return {"error": "forbidden"}
    title = _safe_text(data.title).strip()
    content = _safe_text(data.content).strip()
    if not title and not content:
        return {"error": "validation_error", "message": "Заполните заголовок или текст публикации."}
    if data.post_type == "poll" and len([opt for opt in data.poll_options if _safe_text(opt.get("label", "")).strip()]) < 2:
        return {"error": "validation_error", "message": "Для опроса нужны минимум два варианта ответа."}
    poll_options = []
    for index, option in enumerate(data.poll_options or []):
        label = _safe_text(option.get("label", "")).strip()
        if not label:
            continue
        poll_options.append({"id": _safe_text(option.get("id") or f"opt_{index + 1}"), "label": label})
    post_id = create_company_feed_post(
        author_name=actor.get("name", "Пользователь"),
        author_role=actor.get("role", "Сотрудник"),
        post_type=_safe_text(data.post_type or "announcement"),
        title=title,
        content=content,
        poll_options=poll_options,
        target_roles=[_safe_text(role).strip() for role in (data.target_roles or []) if _safe_text(role).strip()],
        is_pinned=int(data.is_pinned or 0),
    )
    create_notification(
        title="Новая запись в ленте",
        message=f"{actor.get('name', 'Пользователь')} опубликовал(а) запись «{title or content[:48]}»",
        category="chat",
        entity_type="feed_post",
        entity_id=str(post_id),
    )
    await manager.broadcast({"type": "feed"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "id": post_id}


@router.post("/api/feed/posts/{post_id}/comments")
async def create_feed_comment(post_id: int, data: CompanyFeedCommentData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "create"):
        return {"error": "forbidden"}
    text = _safe_text(data.text).strip()
    if not text:
        return {"error": "validation_error", "message": "Комментарий не может быть пустым."}
    add_company_feed_comment(post_id=post_id, user_name=actor.get("name", "Пользователь"), user_role=actor.get("role", "Сотрудник"), comment_text=text)
    await manager.broadcast({"type": "feed"})
    return {"status": "success"}


@router.post("/api/feed/posts/{post_id}/react")
async def react_feed_post(post_id: int, data: CompanyFeedReactionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "create"):
        return {"error": "forbidden"}
    reaction_key = _safe_text(data.reaction_key or "like").strip() or "like"
    toggle_company_feed_reaction(post_id=post_id, user_email=actor.get("email", ""), user_name=actor.get("name", "Пользователь"), reaction_key=reaction_key)
    await manager.broadcast({"type": "feed"})
    return {"status": "success"}


@router.post("/api/feed/posts/{post_id}/vote")
async def vote_feed_post(post_id: int, data: CompanyFeedVoteData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "create"):
        return {"error": "forbidden"}
    option_key = _safe_text(data.option_key).strip()
    if not option_key:
        return {"error": "validation_error", "message": "Выберите вариант ответа."}
    vote_company_feed_poll(post_id=post_id, user_email=actor.get("email", ""), user_name=actor.get("name", "Пользователь"), option_key=option_key)
    await manager.broadcast({"type": "feed"})
    return {"status": "success"}


@router.post("/api/feed/posts/{post_id}/read")
async def read_feed_post(post_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "read"):
        return {"error": "forbidden"}
    mark_company_feed_read(post_id=post_id, user_email=actor.get("email", ""))
    return {"status": "success"}


@router.post("/api/feed/posts/{post_id}/pin")
async def pin_feed_post(post_id: int, data: CompanyFeedPinData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "update"):
        return {"error": "forbidden"}
    if actor.get("role") != "Директор":
        return {"error": "forbidden", "message": "Закреплять записи может только директор."}
    set_company_feed_pin(post_id=post_id, is_pinned=int(data.is_pinned or 0))
    await manager.broadcast({"type": "feed"})
    return {"status": "success"}
