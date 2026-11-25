import json, time, email, datetime, asyncio, os, secrets, imaplib, html, mimetypes, base64, socket
import xml.etree.ElementTree as ET
from email.utils import parseaddr
import smtplib
import httpx
import requests
from requests.adapters import HTTPAdapter
from requests_ntlm import HttpNtlmAuth
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.message import EmailMessage
from fastapi import APIRouter, BackgroundTasks, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
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
from services.mail_oauth_service import (
    MailOAuthError,
    build_authorization_url as build_mail_oauth_authorization_url,
    build_oauth_account_payload,
    build_redirect_uri as build_mail_oauth_redirect_uri,
    exchange_code as exchange_mail_oauth_code,
    fetch_oauth_identity,
    provider_status as mail_oauth_provider_status,
    refresh_access_token as refresh_mail_oauth_access_token,
    sync_google_account,
    sync_microsoft_account,
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
import settings
from settings import MAIL_IMAP_TIMEOUT, MAIL_SMTP_TIMEOUT, MAIL_SYNC_BATCH, PUBLIC_BASE_URL

# === ПОДКЛЮЧАЕМ МЕНЕДЖЕР WEBSOCKETS ===
from utils import SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT, manager, decrypt_secret, encrypt_secret

router = APIRouter()
logger = get_logger("communications")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
EMAIL_ATTACHMENTS_DIR = os.path.join(UPLOADS_DIR, "email_attachments")
EMAIL_OAUTH_STATES: dict[str, dict] = {}
EXCHANGE_EWS_HOST = "mail.korda.spb.ru"
EXCHANGE_EWS_LIVE_IP = {"ip": "", "at": 0.0}
EXCHANGE_XML_NS = {
    "m": "http://schemas.microsoft.com/exchange/services/2006/messages",
    "t": "http://schemas.microsoft.com/exchange/services/2006/types",
}


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
            owner_clause, owner_params = _mail_account_owner_clause(actor)
            c.execute(
                f"""
                SELECT m.id, m.subject, m.sender, m.sender_email, m.received_at, m.created_at, a.label
                FROM email_messages m
                LEFT JOIN email_accounts a ON a.id = m.account_id
                JOIN email_account_owners eo ON eo.account_id = a.id
                WHERE COALESCE(m.is_deleted, 0)=0
                  AND COALESCE(m.is_archived, 0)=0
                  AND COALESCE(m.is_read, 0)=0
                  AND {owner_clause}
                ORDER BY COALESCE(m.created_at, 0) DESC, m.id DESC
                LIMIT 8
                """,
                owner_params,
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


def _mail_owner_email(actor: dict | None) -> str:
    return _safe_text((actor or {}).get("email")).lower()


def _mail_account_owner_clause(actor: dict | None, alias: str = "eo") -> tuple[str, list[str]]:
    owner_email = _mail_owner_email(actor)
    if not owner_email:
        return "1=0", []
    return f"LOWER(COALESCE({alias}.owner_email, ''))=?", [owner_email]


def _api_error(status_code: int, error: str, **payload):
    return JSONResponse(status_code=status_code, content={"error": error, **payload})


def _hydrate_email_oauth_row(row: dict | None) -> dict | None:
    if not row:
        return row
    smtp_login = _safe_text(row.get("smtp_login"))
    if smtp_login.startswith("oauth:"):
        provider = smtp_login.split(":", 1)[1].strip()
        row["auth_type"] = "oauth"
        row["oauth_provider"] = provider
        row["oauth_access_token"] = row.get("smtp_password") or ""
        row["oauth_refresh_token"] = row.get("password") or ""
        row["oauth_expires_at"] = int(row.get("last_delivery_at") or 0)
    else:
        row["auth_type"] = "password"
        row["oauth_provider"] = ""
        row["oauth_access_token"] = ""
        row["oauth_refresh_token"] = ""
        row["oauth_expires_at"] = 0
    return row


def _email_oauth_base_url(request: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    return str(request.base_url).rstrip("/")


def _email_oauth_return_html(title: str, message: str, *, ok: bool = True) -> HTMLResponse:
    status = "success" if ok else "error"
    safe_title = html.escape(title or "")
    safe_message = html.escape(message or "")
    page_html = f"""
    <!doctype html>
    <html lang="ru">
    <head>
      <meta charset="utf-8">
      <title>{safe_title}</title>
      <style>
        body {{ font-family: Inter, Arial, sans-serif; background:#f6f7fb; color:#111827; display:grid; place-items:center; min-height:100vh; margin:0; }}
        .card {{ width:min(520px, calc(100vw - 32px)); background:#fff; border:1px solid #e5e7eb; border-radius:8px; padding:28px; box-shadow:0 18px 50px rgba(15,23,42,.08); }}
        h1 {{ font-size:22px; margin:0 0 10px; }}
        p {{ font-size:15px; line-height:1.5; color:#4b5563; margin:0 0 18px; }}
        .pill {{ display:inline-flex; border-radius:999px; padding:6px 10px; font-size:13px; background:{'#dcfce7' if ok else '#fee2e2'}; color:{'#166534' if ok else '#991b1b'}; margin-bottom:14px; }}
        button {{ border:0; border-radius:6px; background:#1f2937; color:#fff; padding:10px 14px; cursor:pointer; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="pill">{status}</div>
        <h1>{safe_title}</h1>
        <p>{safe_message}</p>
        <button onclick="window.location.href='/app#emailsView'">Вернуться в CRM</button>
      </div>
      <script>
        if (window.opener) {{
          window.opener.postMessage({{ type: 'korda-email-oauth', status: '{status}' }}, window.location.origin);
          setTimeout(() => window.close(), 900);
        }} else {{
          setTimeout(() => window.location.href = '/app#emailsView', 1800);
        }}
      </script>
    </body>
    </html>
    """
    return HTMLResponse(page_html)


def _save_oauth_access_token(account_id: int, encrypted_access_token: str, expires_at: int):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE email_accounts SET smtp_password=?, last_delivery_at=?, updated_at=? WHERE id=?",
            (encrypted_access_token, int(expires_at or 0), int(time.time()), account_id),
        )
        conn.commit()
    finally:
        conn.close()


def _save_oauth_message(row: dict):
    now = int(time.time())
    body_text = _safe_text(row.get("body_text"))
    body_preview = (body_text[:320] + "...") if len(body_text) > 320 else body_text
    conn = get_connection()
    try:
        c = conn.cursor()
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
                int(row.get("account_id") or 0),
                _safe_text(row.get("uid")),
                _safe_text(row.get("folder"), "INBOX"),
                _safe_text(row.get("subject"), "Без темы"),
                _safe_text(row.get("sender"), "Неизвестный отправитель"),
                _safe_text(row.get("sender_email")),
                body_preview,
                body_text,
                _safe_text(row.get("received_at")),
                int(row.get("is_read") or 0),
                int(row.get("is_archived") or 0),
                now,
                now,
                _safe_text(row.get("message_id_header"))[:500],
                _safe_text(row.get("reply_to_email")),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _upsert_oauth_email_account(provider: str, payload: dict, actor: dict) -> int:
    now = int(time.time())
    owner_email = _mail_owner_email(actor)
    owner_name = _safe_text(actor.get("name"))
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT a.id, a.password
            FROM email_accounts a
            JOIN email_account_owners eo ON eo.account_id = a.id
            WHERE LOWER(a.address)=LOWER(?) AND LOWER(COALESCE(eo.owner_email, ''))=?
            ORDER BY a.id ASC
            LIMIT 1
            """,
            (payload["address"], owner_email),
        )
        existing = c.fetchone()
        account_id = int(existing["id"]) if existing else 0
        refresh_token = payload.get("oauth_refresh_token") or (existing["password"] if existing else "")
        if account_id:
            c.execute(
                """
                UPDATE email_accounts
                SET label=?, address=?, login=?, imap_host=?, imap_port=?, smtp_host=?, smtp_port=?,
                    smtp_login=?, smtp_password=?, password=?, inbox_folder=?, archive_folder=?, is_active=1,
                    last_delivery_at=?, updated_at=?, last_error='', last_sync_status='ok'
                WHERE id=?
                """,
                (
                    payload["label"],
                    payload["address"],
                    payload["login"],
                    payload["imap_host"],
                    payload["imap_port"],
                    payload["smtp_host"],
                    payload["smtp_port"],
                    f"oauth:{provider}",
                    payload["oauth_access_token"],
                    refresh_token,
                    payload["inbox_folder"],
                    payload["archive_folder"],
                    payload["oauth_expires_at"],
                    now,
                    account_id,
                ),
            )
        else:
            c.execute(
                """
                INSERT INTO email_accounts (
                    label, address, login, password, imap_host, imap_port, smtp_host, smtp_port,
                    smtp_login, smtp_password, inbox_folder, archive_folder, is_default, is_active,
                    last_delivery_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?)
                """,
                (
                    payload["label"],
                    payload["address"],
                    payload["login"],
                    refresh_token,
                    payload["imap_host"],
                    payload["imap_port"],
                    payload["smtp_host"],
                    payload["smtp_port"],
                    f"oauth:{provider}",
                    payload["oauth_access_token"],
                    payload["inbox_folder"],
                    payload["archive_folder"],
                    payload["oauth_expires_at"],
                    now,
                    now,
                ),
            )
            account_id = c.lastrowid
        c.execute("DELETE FROM email_account_owners WHERE account_id=?", (account_id,))
        c.execute(
            """
            INSERT INTO email_account_owners (account_id, owner_email, owner_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (account_id, owner_email, owner_name, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log(
        "email_oauth_connected",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="email_account",
        entity_id=str(account_id),
        details={"provider": provider, "address": payload.get("address", "")},
    )
    return account_id


def _is_locked_error(exc: Exception) -> bool:
    return "database is locked" in str(exc or "").lower()


def _connect_imap_account(account: dict):
    account = _hydrate_email_oauth_row(dict(account or {}))
    if account.get("auth_type") == "oauth" and account.get("oauth_provider") == "yandex":
        access_token = refresh_mail_oauth_access_token(
            "yandex",
            account,
            decrypt_secret=decrypt_secret,
            encrypt_secret=encrypt_secret,
            settings_module=settings,
            save_token_fn=_save_oauth_access_token,
        )
        mailbox = imaplib.IMAP4_SSL(
            account["imap_host"],
            int(account.get("imap_port") or 993),
            timeout=MAIL_IMAP_TIMEOUT,
        )
        auth_string = f"user={account.get('login') or account.get('address')}\1auth=Bearer {access_token}\1\1"
        mailbox.authenticate("XOAUTH2", lambda _: auth_string.encode("utf-8"))
        return mailbox
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


def _is_korda_exchange_account(account: dict) -> bool:
    address = _safe_text(account.get("address")).lower()
    host = _safe_text(account.get("imap_host")).lower()
    return address.endswith("@korda.spb.ru") or host == "mail.korda.spb.ru"


class _ExchangeHostAdapter(HTTPAdapter):
    # Requests builds per-request pool settings; set both SNI and certificate hostname there.
    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(request, verify, cert)
        pool_kwargs["server_hostname"] = EXCHANGE_EWS_HOST
        pool_kwargs["assert_hostname"] = EXCHANGE_EWS_HOST
        return host_params, pool_kwargs


def _exchange_ews_session_for(ip: str) -> requests.Session:
    session = requests.Session()
    session.mount(f"https://{ip}/", _ExchangeHostAdapter())
    session.headers["Host"] = EXCHANGE_EWS_HOST
    session.ews_url = f"https://{ip}/EWS/Exchange.asmx"
    return session


def _exchange_ews_session() -> requests.Session:
    # mail.korda.spb.ru has a dead A record (94.159.95.60): a request that lands on it hangs until timeout.
    if EXCHANGE_EWS_LIVE_IP["ip"] and time.time() - EXCHANGE_EWS_LIVE_IP["at"] < 600:
        return _exchange_ews_session_for(EXCHANGE_EWS_LIVE_IP["ip"])
    try:
        ips = list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(EXCHANGE_EWS_HOST, 443, type=socket.SOCK_STREAM)))
    except OSError as exc:
        raise RuntimeError(f"Не удаётся найти сервер {EXCHANGE_EWS_HOST}: {exc}") from exc
    for ip in ips:
        session = _exchange_ews_session_for(ip)
        try:
            session.get(session.ews_url, timeout=(5, 10))
        except requests.RequestException:
            session.close()
            continue
        EXCHANGE_EWS_LIVE_IP.update(ip=ip, at=time.time())
        return session
    raise RuntimeError(f"Korda Mail недоступен: ни один адрес {EXCHANGE_EWS_HOST} не отвечает")


def _exchange_ews_request(account: dict, body_xml: str, session=None) -> ET.Element:
    _smtp_host, _smtp_port, login, password, _sender = _smtp_credentials(account)
    if not login or not password:
        raise RuntimeError("Не указан логин или пароль Korda Mail")
    envelope = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types">
  <soap:Header><t:RequestServerVersion Version="Exchange2013" /></soap:Header>
  <soap:Body>{body_xml}</soap:Body>
</soap:Envelope>'''
    session = session or _exchange_ews_session()
    try:
        response = session.post(
            session.ews_url,
            data=envelope.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
            auth=HttpNtlmAuth(login, password),
            timeout=(10, max(60, MAIL_IMAP_TIMEOUT)),
        )
    except (requests.ConnectionError, requests.Timeout):
        EXCHANGE_EWS_LIVE_IP["ip"] = ""
        raise
    if response.status_code == 401:
        raise RuntimeError("Korda Mail: неверный логин или пароль (authentication failed)")
    if response.status_code >= 300:
        raise RuntimeError(f"Korda Mail вернул HTTP {response.status_code}")
    root = ET.fromstring(response.content)
    response_code = root.findtext(".//m:ResponseCode", namespaces=EXCHANGE_XML_NS)
    if response_code and response_code != "NoError":
        raise RuntimeError(response_code)
    return root


def _exchange_ews_item_ids(account: dict, limit: int = MAIL_SYNC_BATCH, session=None) -> list[tuple[str, str]]:
    root = _exchange_ews_request(account, f'''
<m:FindItem Traversal="Shallow">
  <m:ItemShape><t:BaseShape>IdOnly</t:BaseShape></m:ItemShape>
  <m:IndexedPageItemView MaxEntriesReturned="{max(1, int(limit or 1))}" Offset="0" BasePoint="Beginning" />
  <m:SortOrder><t:FieldOrder Order="Descending"><t:FieldURI FieldURI="item:DateTimeReceived" /></t:FieldOrder></m:SortOrder>
  <m:ParentFolderIds><t:DistinguishedFolderId Id="inbox" /></m:ParentFolderIds>
</m:FindItem>''', session=session)
    return [
        (node.get("Id", ""), node.get("ChangeKey", ""))
        for node in root.findall(".//t:ItemId", EXCHANGE_XML_NS)
        if node.get("Id")
    ]


def _parse_exchange_ews_messages(root: ET.Element, account_id: int) -> list[dict]:
    rows = []
    for message in root.findall(".//t:Message", EXCHANGE_XML_NS):
        item_id = message.find("./t:ItemId", EXCHANGE_XML_NS)
        uid = item_id.get("Id", "") if item_id is not None else ""
        if not uid:
            continue
        received_at = message.findtext("./t:DateTimeReceived", default="", namespaces=EXCHANGE_XML_NS)
        try:
            parsed_date = datetime.datetime.fromisoformat(received_at.replace("Z", "+00:00"))
            received_at = parsed_date.astimezone().strftime("%d.%m.%Y %H:%M")
        except (TypeError, ValueError):
            pass
        sender_name = message.findtext("./t:From/t:Mailbox/t:Name", default="", namespaces=EXCHANGE_XML_NS)
        sender_email = message.findtext("./t:From/t:Mailbox/t:EmailAddress", default="", namespaces=EXCHANGE_XML_NS)
        reply_to = message.findtext("./t:ReplyTo/t:Mailbox/t:EmailAddress", default="", namespaces=EXCHANGE_XML_NS)
        rows.append({
            "account_id": account_id,
            "uid": uid,
            "folder": "INBOX",
            "subject": message.findtext("./t:Subject", default="Без темы", namespaces=EXCHANGE_XML_NS),
            "sender": sender_name or sender_email or "Неизвестный отправитель",
            "sender_email": sender_email,
            "body_text": message.findtext("./t:Body", default="", namespaces=EXCHANGE_XML_NS),
            "received_at": received_at,
            "is_read": int(message.findtext("./t:IsRead", default="false", namespaces=EXCHANGE_XML_NS).lower() == "true"),
            "is_archived": 0,
            "message_id_header": message.findtext("./t:InternetMessageId", default="", namespaces=EXCHANGE_XML_NS),
            "reply_to_email": reply_to or sender_email,
        })
    return rows


def _sync_exchange_ews_account(account: dict) -> int:
    saved = 0
    with _exchange_ews_session() as session:
        item_ids = _exchange_ews_item_ids(account, session=session)
        if not item_ids:
            return 0
        for offset in range(0, len(item_ids), 10):
            ids_xml = "".join(
                f'<t:ItemId Id="{html.escape(item_id, quote=True)}" ChangeKey="{html.escape(change_key, quote=True)}" />'
                for item_id, change_key in item_ids[offset:offset + 10]
            )
            root = _exchange_ews_request(account, f'''
<m:GetItem>
  <m:ItemShape><t:BaseShape>AllProperties</t:BaseShape><t:BodyType>Text</t:BodyType></m:ItemShape>
  <m:ItemIds>{ids_xml}</m:ItemIds>
</m:GetItem>''', session=session)
            rows = _parse_exchange_ews_messages(root, int(account.get("id") or 0))
            for row in rows:
                _save_oauth_message(row)
            saved += len(rows)
    return saved


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


def _store_sent_email(account_id: int, message_id: int, recipient: str, subject: str, email_message: EmailMessage):
    attachment_names = [
        _safe_text(part.get_filename()) or "attachment.bin"
        for part in email_message.iter_attachments()
    ]
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO email_sent_messages (
                account_id, source_message_id, recipient, subject, body_text, attachments_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                message_id,
                recipient,
                subject[:500],
                _email_message_plain_body(email_message),
                json.dumps(attachment_names, ensure_ascii=False),
                int(time.time()),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Sent email history could not be stored: %s", exc)
    finally:
        if conn is not None:
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

    ews_ok, ews_error = _send_exchange_ews(account, email_message, recipient, subject, message_id=message_id)
    if ews_ok:
        return True, ""
    if ews_error and ews_error != "ews_not_supported":
        if account.get("id"):
            _register_delivery_event(account.get("id", 0), message_id, recipient, subject, "failed", error_text=f"EWS: {ews_error}", attempts=1)
            _update_account_delivery_status(account.get("id", 0), "failed", f"EWS: {ews_error}")
        return False, f"EWS: {ews_error}"

    for attempt in range(1, attempts + 1):
        server = None
        try:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=MAIL_SMTP_TIMEOUT)
            server.login(smtp_login, smtp_pass)
            server.send_message(email_message)
            server.quit()
            server = None
            _register_delivery_event(account.get("id", 0), message_id, recipient, subject, "success", attempts=attempt)
            _store_sent_email(account.get("id", 0), message_id, recipient, subject, email_message)
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


def _email_message_plain_body(email_message: EmailMessage) -> str:
    try:
        body_part = email_message.get_body(preferencelist=("plain",))
        if body_part:
            return body_part.get_content() or ""
    except Exception:
        pass
    try:
        return email_message.get_content() or ""
    except Exception:
        return ""


def _send_exchange_ews(account: dict, email_message: EmailMessage, recipient: str, subject: str, message_id: int = 0):
    smtp_host, _smtp_port, smtp_login, smtp_pass, sender_address = _smtp_credentials(account)
    host_hint = _safe_text(smtp_host).lower()
    address_hint = _safe_text(sender_address or account.get("address")).lower()
    if "korda.spb.ru" not in host_hint and not address_hint.endswith("@korda.spb.ru"):
        return False, "ews_not_supported"
    if not recipient or not smtp_login or not smtp_pass:
        return False, "smtp_not_configured"

    attachments_xml = []
    for attachment in email_message.iter_attachments():
        payload = attachment.get_payload(decode=True) or b""
        if not payload:
            continue
        filename = _safe_text(attachment.get_filename()) or "attachment.bin"
        attachments_xml.append(
            """
            <t:FileAttachment>
              <t:Name>{filename}</t:Name>
              <t:Content>{content}</t:Content>
            </t:FileAttachment>
            """.format(
                filename=html.escape(filename),
                content=base64.b64encode(payload).decode("ascii"),
            )
        )

    attachments_block = ""
    if attachments_xml:
        attachments_block = "<t:Attachments>" + "".join(attachments_xml) + "</t:Attachments>"

    body = _email_message_plain_body(email_message)
    soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Header>
    <t:RequestServerVersion Version="Exchange2013" />
  </soap:Header>
  <soap:Body>
    <m:CreateItem MessageDisposition="SendAndSaveCopy">
      <m:SavedItemFolderId>
        <t:DistinguishedFolderId Id="sentitems"/>
      </m:SavedItemFolderId>
      <m:Items>
        <t:Message>
          <t:Subject>{html.escape(subject or "Без темы")}</t:Subject>
          <t:Body BodyType="Text">{html.escape(body or " ")}</t:Body>
          <t:ToRecipients>
            <t:Mailbox><t:EmailAddress>{html.escape(recipient)}</t:EmailAddress></t:Mailbox>
          </t:ToRecipients>
          {attachments_block}
        </t:Message>
      </m:Items>
    </m:CreateItem>
  </soap:Body>
</soap:Envelope>"""

    try:
        with _exchange_ews_session() as session:
            response = session.post(
                session.ews_url,
                data=soap.encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=utf-8"},
                auth=HttpNtlmAuth(smtp_login, smtp_pass),
                timeout=MAIL_SMTP_TIMEOUT,
            )
        text = response.text or ""
        if response.status_code < 300 and 'ResponseClass="Success"' in text and "<m:ResponseCode>NoError</m:ResponseCode>" in text:
            _register_delivery_event(account.get("id", 0), message_id, recipient, subject, "success", attempts=1)
            _store_sent_email(account.get("id", 0), message_id, recipient, subject, email_message)
            _update_account_delivery_status(account.get("id", 0), "success")
            return True, ""
        error = f"ews_failed:{response.status_code}"
        if "<m:ResponseCode>" in text:
            error = text.split("<m:ResponseCode>", 1)[1].split("</m:ResponseCode>", 1)[0]
        return False, error[:500]
    except Exception as exc:
        return False, str(exc)[:500] or "ews_send_failed"


def _test_email_account_connection(account: dict):
    if _is_korda_exchange_account(account):
        result = {"status": "success", "imap": {"ok": False, "error": ""}, "smtp": {"ok": False, "error": ""}}
        try:
            _exchange_ews_item_ids(account, limit=1)
            result["imap"]["ok"] = True
            result["smtp"]["ok"] = True
        except Exception as exc:
            result["status"] = "error"
            result["imap"]["error"] = str(exc)
            result["smtp"]["error"] = str(exc)
        return result
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
    account = _hydrate_email_oauth_row(dict(account or {}))
    now = int(time.time())
    if not force and int(account.get("next_retry_at") or 0) > now:
        return {"status": "deferred", "next_retry_at": int(account.get("next_retry_at") or 0)}
    conn = get_connection()
    c = conn.cursor()
    try:
        if _is_korda_exchange_account(account):
            _sync_exchange_ews_account(account)
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
        if account.get("auth_type") == "oauth" and account.get("oauth_provider") in {"google", "microsoft"}:
            provider = account.get("oauth_provider")
            access_token = refresh_mail_oauth_access_token(
                provider,
                account,
                decrypt_secret=decrypt_secret,
                encrypt_secret=encrypt_secret,
                settings_module=settings,
                save_token_fn=_save_oauth_access_token,
            )
            if provider == "google":
                sync_google_account(account, access_token=access_token, batch_size=MAIL_SYNC_BATCH, save_message_fn=_save_oauth_message)
            else:
                sync_microsoft_account(account, access_token=access_token, batch_size=MAIL_SYNC_BATCH, save_message_fn=_save_oauth_message)
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


def _load_email_account(account_id: int, actor: dict | None = None):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    sql = """
        SELECT email_accounts.*, eo.owner_email, eo.owner_name
        FROM email_accounts
        LEFT JOIN email_account_owners eo ON eo.account_id = email_accounts.id
        WHERE email_accounts.id=?
    """
    params: list = [account_id]
    if actor is not None:
        owner_clause, owner_params = _mail_account_owner_clause(actor)
        sql += f" AND {owner_clause}"
        params.extend(owner_params)
    c.execute(sql, params)
    row = c.fetchone()
    conn.close()
    return _hydrate_email_oauth_row(dict(row)) if row else None


def _parse_email_document_ids(raw_value: str = "") -> list[int]:
    raw = _safe_text(raw_value)
    if not raw:
        return []
    values = []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            values = parsed
        else:
            values = [parsed]
    except Exception:
        values = raw.replace(";", ",").split(",")
    result: list[int] = []
    for value in values:
        try:
            item = int(value)
        except Exception:
            continue
        if item > 0 and item not in result:
            result.append(item)
    return result


def _upload_url_to_disk_path(file_url: str = "") -> str:
    raw = _safe_text(file_url)
    if not raw.startswith("/uploads/"):
        return ""
    relative = raw.removeprefix("/uploads/").replace("\\", "/")
    parts = [part for part in relative.split("/") if part and part not in {".", ".."}]
    if not parts:
        return ""
    disk_path = os.path.abspath(os.path.join(UPLOADS_DIR, *parts))
    uploads_root = os.path.abspath(UPLOADS_DIR)
    try:
        if os.path.commonpath([uploads_root, disk_path]) != uploads_root:
            return ""
    except Exception:
        return ""
    return disk_path


def _load_email_reply_documents(document_ids: list[int]) -> list[dict]:
    if not document_ids:
        return []
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    placeholders = ",".join("?" for _ in document_ids)
    c.execute(
        f"""
        SELECT
            d.id,
            d.type,
            d.number,
            d.d_date,
            d.correspondent,
            d.subject,
            d.file_url,
            r.original_filename,
            r.mime_type,
            r.file_url AS revision_file_url
        FROM documents d
        LEFT JOIN document_file_revisions r ON r.document_id = d.id AND r.is_current=1
        WHERE d.id IN ({placeholders})
        """,
        document_ids,
    )
    rows_by_id = {int(row["id"]): dict(row) for row in c.fetchall()}
    conn.close()
    result = []
    for doc_id in document_ids:
        row = rows_by_id.get(int(doc_id))
        if not row:
            continue
        file_url = _safe_text(row.get("revision_file_url") or row.get("file_url"))
        disk_path = _upload_url_to_disk_path(file_url)
        if not disk_path or not os.path.isfile(disk_path):
            row["missing_file"] = True
        row["disk_path"] = disk_path
        row["file_url"] = file_url
        result.append(row)
    return result


def _format_email_document_note(documents: list[dict]) -> str:
    lines = []
    for doc in documents:
        parts = [
            f"Документ #{doc.get('id')}",
            _safe_text(doc.get("number")),
            _safe_text(doc.get("d_date")),
            _safe_text(doc.get("subject")),
        ]
        primary = " | ".join([part for part in parts if part])
        meta = []
        if _safe_text(doc.get("type")):
            meta.append(f"тип: {_safe_text(doc.get('type'))}")
        if _safe_text(doc.get("correspondent")):
            meta.append(f"контрагент: {_safe_text(doc.get('correspondent'))}")
        if doc.get("missing_file"):
            meta.append("файл не найден")
        lines.append(f"- {primary}" + (f" ({'; '.join(meta)})" if meta else ""))
    return "\n".join(lines)


def _sync_active_email_accounts(force: bool = False, actor: dict | None = None):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    sql = """
        SELECT email_accounts.*, eo.owner_email, eo.owner_name
        FROM email_accounts
        JOIN email_account_owners eo ON eo.account_id = email_accounts.id
        WHERE email_accounts.is_active=1
    """
    params: list = []
    if actor is not None:
        owner_clause, owner_params = _mail_account_owner_clause(actor)
        sql += f" AND {owner_clause}"
        params.extend(owner_params)
    sql += " ORDER BY is_default DESC, id ASC"
    c.execute(sql, params)
    accounts = [_hydrate_email_oauth_row(dict(row)) for row in c.fetchall()]
    conn.close()
    for account in accounts:
        sync_email_account(account, force=force)


def _mailbox_summary(actor: dict):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    owner_clause, owner_params = _mail_account_owner_clause(actor)
    c.execute(
        f"""
        SELECT
            a.id,
            a.label,
            a.address,
            eo.owner_email,
            eo.owner_name,
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
        JOIN email_account_owners eo ON eo.account_id = a.id
        LEFT JOIN email_messages m ON m.account_id = a.id
        WHERE {owner_clause}
        GROUP BY a.id, eo.owner_email, eo.owner_name
        ORDER BY a.is_default DESC, a.id ASC
        """,
        owner_params,
    )
    rows = [_hydrate_email_oauth_row(dict(row)) for row in c.fetchall()]
    conn.close()
    return rows


def _mail_message_action(message_id: int, action: str, actor: dict):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    owner_clause, owner_params = _mail_account_owner_clause(actor)
    c.execute(
        f"""
        SELECT m.*, a.login, a.password, a.imap_host, a.imap_port, a.archive_folder
        FROM email_messages m
        JOIN email_accounts a ON a.id = m.account_id
        JOIN email_account_owners eo ON eo.account_id = a.id
        WHERE m.id=? AND {owner_clause}
        """,
        [message_id, *owner_params],
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


def _load_message_with_account(message_id: int, actor: dict):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    owner_clause, owner_params = _mail_account_owner_clause(actor)
    c.execute(
        f"""
        SELECT m.*, a.address, a.login, a.password, a.smtp_host, a.smtp_port, a.smtp_login, a.smtp_password
        FROM email_messages m
        JOIN email_accounts a ON a.id = m.account_id
        JOIN email_account_owners eo ON eo.account_id = a.id
        WHERE m.id=? AND {owner_clause}
        """,
        [message_id, *owner_params],
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
        mailbox_summary_fn=lambda: _mailbox_summary(actor),
        can_manage_accounts=has_permission(actor, "emails", "manage_accounts"),
    )


@router.get("/api/email/oauth/providers")
def get_email_oauth_providers(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "emails", "read"):
        return {"error": "forbidden"}
    base_url = _email_oauth_base_url(request)
    rows = mail_oauth_provider_status(settings)
    for row in rows:
        row["redirect_uri"] = build_mail_oauth_redirect_uri(base_url, row["provider"])
    return rows


@router.get("/api/email/oauth/{provider}/start")
def start_email_oauth(provider: str, request: Request):
    actor = _mail_admin(request)
    if not actor:
        return _api_error(403, "forbidden")
    provider = _safe_text(provider).lower()
    base_url = _email_oauth_base_url(request)
    redirect_uri = build_mail_oauth_redirect_uri(base_url, provider)
    if not redirect_uri:
        return _api_error(400, "oauth_base_url_missing", message="Не задан публичный адрес CRM для OAuth callback.")
    state = secrets.token_urlsafe(32)
    EMAIL_OAUTH_STATES[state] = {
        "provider": provider,
        "actor_email": actor.get("email", ""),
        "actor_name": actor.get("name", ""),
        "created_at": int(time.time()),
    }
    try:
        auth_url = build_mail_oauth_authorization_url(provider, state=state, redirect_uri=redirect_uri, settings_module=settings)
    except MailOAuthError as exc:
        EMAIL_OAUTH_STATES.pop(state, None)
        return _api_error(400, str(exc), message="Провайдер OAuth ещё не настроен на сервере.")
    return {"status": "success", "auth_url": auth_url, "redirect_uri": redirect_uri}


@router.get("/api/email/oauth/{provider}/callback")
def finish_email_oauth(provider: str, request: Request, code: str = "", state: str = "", error: str = ""):
    provider = _safe_text(provider).lower()
    if error:
        return _email_oauth_return_html("Подключение отменено", f"Провайдер вернул ошибку: {error}", ok=False)
    state_data = EMAIL_OAUTH_STATES.pop(state, None)
    if not state_data or state_data.get("provider") != provider or int(time.time()) - int(state_data.get("created_at") or 0) > 900:
        return _email_oauth_return_html("Не удалось подключить почту", "Сессия подключения устарела. Открой CRM и начни вход заново.", ok=False)
    if not code:
        return _email_oauth_return_html("Не удалось подключить почту", "Провайдер не передал код авторизации.", ok=False)
    actor = {
        "email": state_data.get("actor_email", ""),
        "name": state_data.get("actor_name", ""),
    }
    base_url = _email_oauth_base_url(request)
    redirect_uri = build_mail_oauth_redirect_uri(base_url, provider)
    try:
        token_payload = exchange_mail_oauth_code(provider, code=code, redirect_uri=redirect_uri, settings_module=settings)
        identity = fetch_oauth_identity(provider, token_payload)
        if not identity.get("address"):
            raise MailOAuthError("email_address_missing")
        payload = build_oauth_account_payload(provider, identity, token_payload, encrypt_secret=encrypt_secret)
        account_id = _upsert_oauth_email_account(provider, payload, actor)
        account = _load_email_account(account_id)
        if account:
            sync_email_account(account, force=True)
    except Exception as exc:
        logger.warning("Email OAuth callback failed for %s: %s", provider, exc)
        return _email_oauth_return_html("Почта не подключилась", "CRM получила ответ провайдера, но не смогла завершить привязку. Проверь настройки OAuth-приложения и повтори вход.", ok=False)
    return _email_oauth_return_html("Почта подключена", f"Ящик {payload.get('address')} добавлен в CRM и первая синхронизация запущена.")


def _sync_saved_email_account(account: dict, background_tasks: BackgroundTasks, force: bool = True):
    if not _is_korda_exchange_account(account):
        return sync_email_account(account, force=force)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE email_accounts SET last_sync_status='pending', last_error='', next_retry_at=0, last_sync_at=? WHERE id=?",
            (int(time.time()), account["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    background_tasks.add_task(sync_email_account, account, force=force)
    return {"status": "pending"}


@router.post("/api/email/accounts")
def create_email_account(data: EmailAccountData, request: Request, background_tasks: BackgroundTasks):
    actor = _mail_admin(request)
    if not actor:
        return _api_error(403, "forbidden")
    conn = get_connection(row_factory=True)
    try:
        existing = conn.execute(
            """
            SELECT a.id
            FROM email_accounts a
            JOIN email_account_owners eo ON eo.account_id=a.id
            WHERE LOWER(a.address)=LOWER(?) AND LOWER(COALESCE(eo.owner_email, ''))=?
            ORDER BY a.id ASC
            LIMIT 1
            """,
            (_safe_text(data.address), _mail_owner_email(actor)),
        ).fetchone()
    finally:
        conn.close()
    if existing:
        account_id = int(existing["id"])
        result = update_email_account_record_service(
            account_id,
            data,
            actor=actor,
            get_connection=get_connection,
            normalize_payload_fn=_normalize_email_account_payload,
            encrypt_secret_fn=encrypt_secret,
            audit_log_fn=audit_log,
            load_account_fn=_load_email_account,
            sync_account_fn=lambda account, force: _sync_saved_email_account(account, background_tasks, force),
        )
        result["id"] = account_id
        return result
    result = create_email_account_record_service(
        data,
        actor=actor,
        get_connection=get_connection,
        normalize_payload_fn=_normalize_email_account_payload,
        encrypt_secret_fn=encrypt_secret,
        audit_log_fn=audit_log,
        load_account_fn=_load_email_account,
        sync_account_fn=lambda account, force: _sync_saved_email_account(account, background_tasks, force),
        is_locked_error_fn=_is_locked_error,
    )
    if result.get("error"):
        return _api_error(int(result.get("status_code") or 400), result["error"], message=result.get("message", ""))
    return result


@router.put("/api/email/accounts/{account_id}")
def update_email_account(account_id: int, data: EmailAccountData, request: Request, background_tasks: BackgroundTasks):
    actor = _mail_admin(request)
    if not actor:
        return _api_error(403, "forbidden")
    if not _load_email_account(account_id, actor):
        return _api_error(404, "not_found")
    return update_email_account_record_service(
        account_id,
        data,
        actor=actor,
        get_connection=get_connection,
        normalize_payload_fn=_normalize_email_account_payload,
        encrypt_secret_fn=encrypt_secret,
        audit_log_fn=audit_log,
        load_account_fn=_load_email_account,
        sync_account_fn=lambda account, force: _sync_saved_email_account(account, background_tasks, force),
    )


@router.delete("/api/email/accounts/{account_id}")
def delete_email_account(account_id: int, request: Request):
    actor = _mail_admin(request)
    if not actor:
        return _api_error(403, "forbidden")
    if not _load_email_account(account_id, actor):
        return _api_error(404, "not_found")
    return delete_email_account_record_service(
        account_id,
        actor=actor,
        get_connection=get_connection,
        audit_log_fn=audit_log,
    )


@router.post("/api/email/accounts/{account_id}/sync")
def sync_email_account_route(account_id: int, request: Request, background_tasks: BackgroundTasks):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "read"):
        return {"error": "forbidden"}
    account = _load_email_account(account_id, actor)
    if not account:
        return {"error": "not_found"}
    if _is_korda_exchange_account(account):
        if account.get("last_sync_status") == "pending" and int(time.time()) - int(account.get("last_sync_at") or 0) < 180:
            return {"status": "pending"}
        _sync_saved_email_account(account, background_tasks)
        return {"status": "pending"}
    return sync_email_account(account, force=True)


@router.post("/api/email/accounts/{account_id}/test")
def test_email_account_route(account_id: int, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "manage_accounts"):
        return {"error": "forbidden"}
    account = _load_email_account(account_id, actor)
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
def retry_failed_email_ops(request: Request, background_tasks: BackgroundTasks, account_id: int = 0):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "read"):
        return {"error": "forbidden"}
    return retry_failed_email_accounts_service(
        account_id,
        get_connection=get_connection,
        sync_account_fn=lambda account, force: _sync_saved_email_account(account, background_tasks, force),
        owner_email=_mail_owner_email(actor),
    )


@router.get("/api/emails")
def get_emails(request: Request, account_id: int = 0, filter_name: str = "all", query: str = "", sender_email: str = "", force_refresh: int = 0):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "read"):
        return {"error": "forbidden"}
    if force_refresh:
        if account_id:
            account = _load_email_account(account_id, actor)
            if account and account.get("is_active"):
                sync_email_account(account, force=True)
        else:
            _sync_active_email_accounts(force=True, actor=actor)

    conn = get_connection(row_factory=True)
    c = conn.cursor()
    owner_clause, owner_params = _mail_account_owner_clause(actor)
    if filter_name == "recent_sent":
        recent_since = int(time.time()) - 1800
        sent_clauses = ["s.created_at>=?", owner_clause]
        sent_params = [recent_since, *owner_params]
        if account_id:
            sent_clauses.append("s.account_id=?")
            sent_params.append(account_id)
        if query:
            sent_clauses.append("(s.subject LIKE ? OR s.recipient LIKE ? OR s.body_text LIKE ?)")
            like = f"%{query}%"
            sent_params.extend([like, like, like])
        c.execute(
            f"""
            SELECT
                s.id,
                s.account_id,
                s.source_message_id AS message_id,
                s.recipient,
                s.subject,
                'success' AS status,
                s.body_text,
                s.attachments_json,
                s.created_at,
                a.label AS account_label,
                a.address AS account_address
            FROM email_sent_messages s
            JOIN email_accounts a ON a.id = s.account_id
            JOIN email_account_owners eo ON eo.account_id = a.id
            WHERE {' AND '.join(sent_clauses)}
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT 80
            """,
            sent_params,
        )
        rows = []
        for row in c.fetchall():
            item = dict(row)
            sent_at = int(item.get("created_at") or 0)
            rows.append({
                "id": f"sent_{item.get('id')}",
                "is_sent_event": 1,
                "account_id": item.get("account_id"),
                "account_label": item.get("account_label") or item.get("account_address") or "Korda Mail",
                "account_address": item.get("account_address") or "",
                "subject": item.get("subject") or "Без темы",
                "sender": item.get("account_address") or "",
                "sender_email": item.get("account_address") or "",
                "recipient": item.get("recipient") or "",
                "body_preview": item.get("body_text") or "Письмо отправлено из CRM.",
                "body_text": item.get("body_text") or f"Кому: {item.get('recipient') or ''}",
                "received_at": datetime.datetime.fromtimestamp(sent_at).strftime("%d.%m.%Y %H:%M") if sent_at else "",
                "created_at": sent_at,
                "is_read": 1,
                "is_archived": 0,
                "delivery_status": "sent",
                "attachments": [
                    {"filename": filename, "stored_path": ""}
                    for filename in _json_load(item.get("attachments_json"), [])
                    if _safe_text(filename)
                ],
            })
        inbox_clauses = ["m.is_deleted=0", "m.created_at>=?", owner_clause]
        inbox_params = [recent_since, *owner_params]
        if account_id:
            inbox_clauses.append("m.account_id=?")
            inbox_params.append(account_id)
        if query:
            inbox_clauses.append("(m.subject LIKE ? OR m.sender LIKE ? OR m.body_text LIKE ?)")
            like = f"%{query}%"
            inbox_params.extend([like, like, like])
        if sender_email:
            inbox_clauses.append("LOWER(COALESCE(m.sender_email, ''))=LOWER(?)")
            inbox_params.append(sender_email.strip())
        c.execute(
            f"""
            SELECT m.*, a.label AS account_label, a.address AS account_address, a.last_error AS account_error
            FROM email_messages m
            JOIN email_accounts a ON a.id = m.account_id
            JOIN email_account_owners eo ON eo.account_id = a.id
            WHERE {' AND '.join(inbox_clauses)}
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT 80
            """,
            inbox_params,
        )
        inbox_rows = [dict(row) for row in c.fetchall()]
        message_ids = [row["id"] for row in inbox_rows]
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
        for row in inbox_rows:
            row["attachments"] = attachments_map.get(row["id"], [])
            rows.append(row)
        rows.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
        rows = rows[:120]
        conn.close()
        return rows

    clauses = ["m.is_deleted=0"]
    params = []
    clauses.append(owner_clause)
    params.extend(owner_params)
    if account_id:
        clauses.append("m.account_id=?")
        params.append(account_id)
    if filter_name == "new":
        clauses.append("m.is_archived=0")
        clauses.append("m.is_read=0")
    elif filter_name == "read":
        clauses.append("m.is_archived=0")
        clauses.append("m.is_read=1")
    elif filter_name == "replied":
        clauses.append("m.is_archived=0")
        clauses.append("m.delivery_status='replied'")
    elif filter_name == "archived":
        clauses.append("m.is_archived=1")
    else:
        clauses.append("m.is_archived=0")
    if query:
        clauses.append("(m.subject LIKE ? OR m.sender LIKE ? OR m.body_text LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like, like])
    if sender_email:
        clauses.append("LOWER(COALESCE(m.sender_email, ''))=LOWER(?)")
        params.append(sender_email.strip())
    sql = f"""
        SELECT m.*, a.label AS account_label, a.address AS account_address, a.last_error AS account_error
        FROM email_messages m
        JOIN email_accounts a ON a.id = m.account_id
        JOIN email_account_owners eo ON eo.account_id = a.id
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
    for row in rows:
        row["attachments"] = attachments_map.get(row["id"], [])
    if sender_email:
        sent_clauses = [owner_clause, "LOWER(COALESCE(s.recipient, ''))=LOWER(?)"]
        sent_params = [*owner_params, sender_email.strip()]
        if account_id:
            sent_clauses.append("s.account_id=?")
            sent_params.append(account_id)
        if query:
            sent_clauses.append("(s.subject LIKE ? OR s.body_text LIKE ?)")
            like = f"%{query}%"
            sent_params.extend([like, like])
        c.execute(
            f"""
            SELECT s.*, s.source_message_id AS message_id, a.label AS account_label, a.address AS account_address
            FROM email_sent_messages s
            JOIN email_accounts a ON a.id = s.account_id
            JOIN email_account_owners eo ON eo.account_id = a.id
            WHERE {' AND '.join(sent_clauses)}
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT 120
            """,
            sent_params,
        )
        for event_row in c.fetchall():
            item = dict(event_row)
            sent_at = int(item.get("created_at") or 0)
            attachment_names = _json_load(item.get("attachments_json"), [])
            rows.append({
                "id": f"sent_{item.get('id')}",
                "is_sent_event": 1,
                "account_id": item.get("account_id"),
                "account_label": item.get("account_label") or item.get("account_address") or "Korda Mail",
                "account_address": item.get("account_address") or "",
                "subject": item.get("subject") or "Без темы",
                "sender": item.get("account_address") or "",
                "sender_email": item.get("account_address") or "",
                "recipient": item.get("recipient") or "",
                "body_preview": item.get("body_text") or "Текст старого отправления не сохранён.",
                "body_text": item.get("body_text") or "Текст старого отправления не сохранён.",
                "received_at": datetime.datetime.fromtimestamp(sent_at).strftime("%d.%m.%Y %H:%M") if sent_at else "",
                "created_at": sent_at,
                "is_read": 1,
                "is_archived": 0,
                "delivery_status": "sent",
                "attachments": [
                    {"filename": filename, "stored_path": ""}
                    for filename in attachment_names
                    if _safe_text(filename)
                ],
            })
        rows.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
        rows = rows[:160]
    conn.close()
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
    c.execute(
        """
        UPDATE email_messages
        SET is_read=?
        WHERE id=?
          AND account_id IN (
            SELECT account_id FROM email_account_owners WHERE LOWER(COALESCE(owner_email, ''))=?
          )
        """,
        (int(bool(data.read)), message_id, _mail_owner_email(actor)),
    )
    changed = c.rowcount
    conn.commit()
    conn.close()
    if changed < 1:
        return {"error": "not_found"}
    return {"status": "success"}


@router.post("/api/emails/{message_id}/archive")
def archive_email(message_id: int, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "archive"):
        return {"error": "forbidden"}
    ok, error = _mail_message_action(message_id, "archive", actor)
    return {"status": "success"} if ok else {"error": error}


@router.post("/api/emails/{message_id}/restore")
def restore_email(message_id: int, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "archive"):
        return {"error": "forbidden"}
    ok, error = _mail_message_action(message_id, "restore", actor)
    return {"status": "success"} if ok else {"error": error}


@router.delete("/api/emails/{message_id}")
def delete_email(message_id: int, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved" or not has_permission(actor, "emails", "delete"):
        return {"error": "forbidden"}
    ok, error = _mail_message_action(message_id, "delete", actor)
    return {"status": "success"} if ok else {"error": error}


@router.post("/api/emails/{message_id}/reply")
async def reply_email(
    message_id: int,
    request: Request,
    body: str = Form(""),
    document_ids: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "emails", "reply"):
        return {"error": "forbidden"}
    message = _load_message_with_account(message_id, actor)
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
    parsed_document_ids = _parse_email_document_ids(document_ids)
    if parsed_document_ids and not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    selected_documents = _load_email_reply_documents(parsed_document_ids)
    missing_documents = [doc for doc in selected_documents if doc.get("missing_file")]
    if missing_documents:
        return {"error": "document_file_missing", "message": "У выбранного документа не найден файл. Открой карточку документа и прикрепи файл."}
    document_note = _format_email_document_note(selected_documents)
    message_body = body
    if document_note:
        message_body = f"{body.rstrip()}\n\nПрикрепленные документы из CRM:\n{document_note}"
    if not message_body.strip() and selected_documents:
        message_body = "Направляю документы из CRM."
    email_message.set_content(message_body or " ")

    for upload in files or []:
        payload = await upload.read()
        if not payload:
            continue
        content_type = upload.content_type or "application/octet-stream"
        maintype, _, subtype = content_type.partition("/")
        email_message.add_attachment(payload, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=upload.filename or "attachment")

    for doc in selected_documents:
        disk_path = doc.get("disk_path") or ""
        if not disk_path or not os.path.isfile(disk_path):
            continue
        with open(disk_path, "rb") as fh:
            payload = fh.read()
        if not payload:
            continue
        filename = _safe_text(doc.get("original_filename")) or os.path.basename(disk_path) or f"document_{doc.get('id')}.bin"
        content_type = _safe_text(doc.get("mime_type")) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        maintype, _, subtype = content_type.partition("/")
        email_message.add_attachment(payload, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=filename)

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
