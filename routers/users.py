import os
import time
import json
import base64
import hashlib
import hmac
import secrets
import shutil
import struct
import subprocess
from urllib.parse import urlparse, unquote, parse_qs
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from database import (
    DATABASE_URL,
    get_connection,
    next_safe_table_id,
    audit_log,
    get_recent_attempt_count,
    record_auth_attempt,
    clear_auth_attempts,
    get_audit_logs,
    delete_user_sessions_for_email,
    list_user_sessions,
    revoke_user_session,
    record_field_changes,
    get_field_change_logs,
    create_notification,
    get_error_logs,
    register_backup,
    get_backups,
    get_field_access_rules,
    save_field_access_rule,
    delete_field_access_rule,
)
from auth_security import (
    SESSION_COOKIE_NAME,
    issue_session_for_user,
    apply_session_cookie,
    clear_session_cookie,
    get_request_user,
    destroy_request_session,
)
from permissions import get_field_permissions, get_role_permissions, require_approved_user
from services.policy_service import build_form_policy_payload
from services.system_readiness_service import build_system_readiness
from schemas import (
    AuthData,
    RoleData,
    UserInviteData,
    SignatureData,
    RemoveUserData,
    VacationData,
    HRLeaveRequestData,
    HRTimesheetEntryData,
    HREquipmentRequestData,
    HRSubstitutionRequestData,
    HRBusinessTripRequestData,
    UserScopeData,
    SessionRevokeData,
    TwoFactorCodeData,
    FieldAccessRuleData,
)
from app_logging import get_logger
from settings import BACKUP_RETENTION_COUNT
from utils import (
    send_email_task,
    DEPT_EMAILS,
    hash_password,
    verify_password,
    generate_temporary_password,
    normalize_email,
    is_valid_email,
    validate_password_strength,
)

router = APIRouter()
logger = get_logger("users")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
ALLOWED_USER_ROLES = {
    "Конструкторское бюро",
    "Производство и ОТК",
    "Склад",
    "Менеджер",
    "Бухгалтерия",
    "Юрист",
    "Секретарь / Канцелярия",
    "Сотрудник",
    "Директор",
}


def _postgres_conn_args():
    parsed = urlparse(DATABASE_URL)
    query = parse_qs(parsed.query)
    host = (query.get("host") or [parsed.hostname or "localhost"])[0]
    port = (query.get("port") or [str(parsed.port or 5432)])[0]
    return {
        "host": unquote(host or "localhost"),
        "port": str(port or 5432),
        "user": unquote(parsed.username or "postgres"),
        "password": unquote(parsed.password or ""),
        "dbname": unquote((parsed.path or "").lstrip("/")),
    }


def _legacy_postgres_snapshot_path() -> str:
    cfg = _postgres_conn_args()
    dbname = os.path.basename(cfg.get("dbname") or "")
    if not dbname:
        return ""
    return os.path.join(BASE_DIR, dbname)


def _run_postgres_dump(target_path: str):
    cfg = _postgres_conn_args()
    env = os.environ.copy()
    env["PGPASSWORD"] = cfg["password"]
    command = [
        "pg_dump",
        "-h", cfg["host"],
        "-p", cfg["port"],
        "-U", cfg["user"],
        "-d", cfg["dbname"],
        "-Fp",
        "--clean",
        "--if-exists",
        "-f", target_path,
    ]
    subprocess.run(command, check=True, env=env, capture_output=True, text=True)


def _run_postgres_restore(source_path: str):
    cfg = _postgres_conn_args()
    env = os.environ.copy()
    env["PGPASSWORD"] = cfg["password"]
    command = [
        "psql",
        "-h", cfg["host"],
        "-p", cfg["port"],
        "-U", cfg["user"],
        "-d", cfg["dbname"],
        "-v", "ON_ERROR_STOP=1",
        "-f", source_path,
    ]
    subprocess.run(command, check=True, env=env, capture_output=True, text=True)


def _refresh_legacy_postgres_snapshot(source_path: str):
    legacy_path = _legacy_postgres_snapshot_path()
    if not legacy_path or os.path.abspath(legacy_path) == os.path.abspath(source_path):
        return
    shutil.copyfile(source_path, legacy_path)


def _request_meta(request: Request):
    ip_address = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")[:500]
    return ip_address, user_agent


def _is_rate_limited(action: str, identifier: str, limit: int, window_seconds: int) -> bool:
    if not identifier:
        return False
    return get_recent_attempt_count(action, identifier, window_seconds) >= limit


def _director_from_session(request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("role") != "Директор":
        return None
    return actor


def _load_user_snapshot(email: str):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            email, name, role, status, signature, deputy, abs_start, abs_end, abs_type, abs_reason,
            is_head, hourly_rate, allowed_legal_entities, allowed_business_units, two_factor_enabled
        FROM users
        WHERE email=?
        """,
        (normalize_email(email),),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return {}
    payload = dict(row)
    for field_name in ("allowed_legal_entities", "allowed_business_units"):
        try:
            payload[field_name] = json.loads(payload.get(field_name) or "[]")
        except Exception:
            payload[field_name] = []
    payload["two_factor_enabled"] = int(payload.get("two_factor_enabled") or 0)
    payload["is_head"] = int(payload.get("is_head") or 0)
    return payload


def _resolve_self_service_target(actor: dict | None, requested_email: str = "") -> str:
    if not actor:
        return ""
    if actor.get("role") == "Директор":
        return normalize_email(requested_email or actor.get("email", ""))
    return normalize_email(actor.get("email", ""))


def _hr_fetch_all(query: str, params: tuple = ()) -> list[dict]:
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(query, params)
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _list_hr_leave_requests(target_email: str) -> list[dict]:
    return _hr_fetch_all(
        """
        SELECT *
        FROM hr_leave_requests
        WHERE user_email=?
        ORDER BY date_from DESC, id DESC
        """,
        (target_email,),
    )


def _list_hr_timesheet_entries(target_email: str) -> list[dict]:
    return _hr_fetch_all(
        """
        SELECT te.*, COALESCE(p.name, '') AS project_name, COALESCE(p.contract, '') AS project_contract
        FROM hr_timesheet_entries te
        LEFT JOIN projects p ON p.id = te.project_id
        WHERE te.user_email=?
        ORDER BY te.entry_date DESC, te.id DESC
        """,
        (target_email,),
    )


def _list_hr_equipment_requests(target_email: str) -> list[dict]:
    return _hr_fetch_all(
        """
        SELECT *
        FROM hr_equipment_requests
        WHERE user_email=?
        ORDER BY needed_by DESC, id DESC
        """,
        (target_email,),
    )


def _list_hr_substitution_requests(target_email: str) -> list[dict]:
    return _hr_fetch_all(
        """
        SELECT *
        FROM hr_substitution_requests
        WHERE user_email=?
        ORDER BY date_from DESC, id DESC
        """,
        (target_email,),
    )


def _list_hr_business_trip_requests(target_email: str) -> list[dict]:
    return _hr_fetch_all(
        """
        SELECT *
        FROM hr_business_trip_requests
        WHERE user_email=?
        ORDER BY date_from DESC, id DESC
        """,
        (target_email,),
    )


def _is_same_month(date_value: str, month_key: str) -> bool:
    parts = str(date_value or "").split(".")
    if len(parts) != 3:
        return False
    return f"{parts[1]}.{parts[2]}" == month_key


def _base32_secret(length: int = 20) -> str:
    return base64.b32encode(secrets.token_bytes(length)).decode("ascii").rstrip("=")


def _totp_code(secret: str, for_time: int | None = None, step: int = 30, digits: int = 6) -> str:
    normalized = ((secret or "").strip().upper() + "=" * 8)[:((len((secret or "").strip()) + 7) // 8) * 8]
    key = base64.b32decode(normalized, casefold=True)
    counter = int((for_time or time.time()) // step)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def _verify_totp(secret: str, otp_code: str, drift_steps: int = 1) -> bool:
    code = str(otp_code or "").strip()
    if not secret or not code or not code.isdigit():
        return False
    now = int(time.time())
    for delta in range(-drift_steps, drift_steps + 1):
        if _totp_code(secret, now + delta * 30) == code:
            return True
    return False


@router.post("/api/register")
def register(data: AuthData, bg_tasks: BackgroundTasks, request: Request):
    ip_address, user_agent = _request_meta(request)
    email = normalize_email(data.email)
    name = (data.name or "").strip()
    password = data.password or ""

    if _is_rate_limited("register_ip", ip_address, 5, 3600):
        return {"error": "Слишком много заявок. Попробуйте позже"}
    record_auth_attempt("register_ip", ip_address, 0)

    if not email or not password or not name:
        return {"error": "Заполните имя, email и пароль"}
    if not is_valid_email(email):
        return {"error": "Введите корректный email"}
    password_error = validate_password_strength(password)
    if password_error:
        return {"error": password_error}

    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (email,))
    if c.fetchone():
        conn.close()
        audit_log("register_duplicate", actor_email=email, actor_name=name, entity_type="user", entity_id=email, ip_address=ip_address, user_agent=user_agent)
        return {"error": "Email занят"}
    c.execute("INSERT INTO users (email, password, name, role, status) VALUES (?, ?, ?, ?, ?)", (email, hash_password(password), name, None, 'pending'))
    conn.commit(); conn.close()
    audit_log("register_submitted", actor_email=email, actor_name=name, entity_type="user", entity_id=email, ip_address=ip_address, user_agent=user_agent)
    bg_tasks.add_task(send_email_task, DEPT_EMAILS["Директор"], 'Новая заявка', f'Пользователь {name} ждет одобрения.')
    return {"status": "success"}

@router.post("/api/login")
def login(data: AuthData, request: Request):
    ip_address, user_agent = _request_meta(request)
    identifier_raw = (data.email or "").strip()
    identifier_email = normalize_email(identifier_raw)
    identifier_login = identifier_raw.lower()
    if _is_rate_limited("login_ip", ip_address, 15, 600) or _is_rate_limited("login_email", identifier_login or identifier_email, 7, 600):
        return {"error": "Слишком много попыток входа. Попробуйте через 10 минут"}

    record_auth_attempt("login_ip", ip_address, 0)
    record_auth_attempt("login_email", identifier_login or identifier_email, 0)

    conn = get_connection(row_factory=True); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE LOWER(email)=? OR LOWER(COALESCE(username, ''))=?", (identifier_email, identifier_login))
    user = c.fetchone()
    conn.close()
    if not user or not verify_password(data.password, user["password"]):
        audit_log("login_failed", actor_email=identifier_email, entity_type="user", entity_id=identifier_raw, ip_address=ip_address, user_agent=user_agent)
        return {"error": "Ошибка входа"}
    if int(user["two_factor_enabled"] or 0) == 1 and (user["two_factor_secret"] or "").strip():
        if not _verify_totp(user["two_factor_secret"], data.otp_code):
            audit_log("login_2fa_required", actor_email=user.get("email", ""), entity_type="user", entity_id=user.get("email", ""), ip_address=ip_address, user_agent=user_agent)
            return {"two_factor_required": True, "error": "Введите код 2FA"}
    clear_auth_attempts("login_email", identifier_login or identifier_email)
    clear_auth_attempts("login_ip", ip_address)
    payload = dict(user)
    payload.pop("password", None)
    payload.pop("two_factor_secret", None)
    audit_log("login_success", actor_email=payload.get("email", ""), actor_name=payload.get("name", ""), entity_type="user", entity_id=payload.get("email", ""), details={"status": payload.get("status"), "role": payload.get("role")}, ip_address=ip_address, user_agent=user_agent)
    session_id = issue_session_for_user(request, payload.get("email", ""))
    response = JSONResponse(payload)
    apply_session_cookie(response, session_id)
    return response


@router.get("/api/session")
def get_session(request: Request):
    user = get_request_user(request)
    if not user:
        return {"error": "unauthorized"}
    return user


@router.post("/api/logout")
def logout(request: Request):
    destroy_request_session(request)
    response = JSONResponse({"status": "success"})
    clear_session_cookie(response)
    return response


@router.get("/api/permissions")
def get_permissions(request: Request):
    user = get_request_user(request)
    if not user:
        return {"error": "unauthorized"}
    return get_role_permissions(user)


@router.get("/api/permissions/forms/{module}/{entity_type}")
def get_form_permissions(module: str, entity_type: str, request: Request):
    user = get_request_user(request)
    if not user:
        return {"error": "unauthorized"}
    return build_form_policy_payload(user, module, entity_type, get_field_permissions)


@router.get("/api/users/2fa/setup")
def setup_current_user_2fa(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT two_factor_secret, two_factor_enabled FROM users WHERE email=?", (actor.get("email", ""),))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    secret = (row["two_factor_secret"] or "").strip() or _base32_secret()
    c.execute("UPDATE users SET two_factor_secret=? WHERE email=?", (secret, actor.get("email", "")))
    conn.commit()
    conn.close()
    return {
        "status": "success",
        "secret": secret,
        "issuer": "Korda CRM",
        "account": actor.get("email", ""),
        "enabled": int(row["two_factor_enabled"] or 0),
        "manual_entry": f"Korda CRM ({actor.get('email', '')})",
    }


@router.post("/api/users/2fa/enable")
def enable_current_user_2fa(data: TwoFactorCodeData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT two_factor_secret FROM users WHERE email=?", (actor.get("email", ""),))
    row = c.fetchone()
    secret = (row["two_factor_secret"] or "").strip() if row else ""
    if not _verify_totp(secret, data.otp_code):
        conn.close()
        return {"error": "invalid_otp"}
    c.execute("UPDATE users SET two_factor_enabled=1 WHERE email=?", (actor.get("email", ""),))
    conn.commit()
    conn.close()
    audit_log("user_2fa_enabled", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="user", entity_id=actor.get("email", ""))
    return {"status": "success"}


@router.post("/api/users/2fa/disable")
def disable_current_user_2fa(data: TwoFactorCodeData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT two_factor_secret FROM users WHERE email=?", (actor.get("email", ""),))
    row = c.fetchone()
    secret = (row["two_factor_secret"] or "").strip() if row else ""
    if secret and not _verify_totp(secret, data.otp_code):
        conn.close()
        return {"error": "invalid_otp"}
    c.execute("UPDATE users SET two_factor_enabled=0 WHERE email=?", (actor.get("email", ""),))
    conn.commit()
    conn.close()
    audit_log("user_2fa_disabled", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="user", entity_id=actor.get("email", ""))
    return {"status": "success"}

@router.post("/api/recover")
def recover(data: AuthData, bg_tasks: BackgroundTasks, request: Request):
    ip_address, user_agent = _request_meta(request)
    email = normalize_email(data.email)
    if not is_valid_email(email):
        return {"status": "success"}
    if _is_rate_limited("recover_ip", ip_address, 5, 3600) or _is_rate_limited("recover_email", email, 3, 3600):
        return {"status": "success"}

    record_auth_attempt("recover_ip", ip_address, 0)
    record_auth_attempt("recover_email", email, 0)

    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT name FROM users WHERE email=?", (email,))
    if c.fetchone():
        new_p = generate_temporary_password()
        c.execute("UPDATE users SET password=? WHERE email=?", (hash_password(new_p), email)); conn.commit()
        bg_tasks.add_task(send_email_task, email, "Восстановление пароля", f"Временный пароль: {new_p}")
        audit_log("recover_requested", actor_email=email, entity_type="user", entity_id=email, ip_address=ip_address, user_agent=user_agent)
    conn.close()
    return {"status": "success"}

@router.get("/api/status/{email}")
def get_status(email: str, request: Request):
    actor = get_request_user(request)
    email = normalize_email(email)
    if not actor or (actor.get("email") != email and actor.get("role") != "Директор"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True); c = conn.cursor()
    c.execute("SELECT status, role, is_head, hourly_rate FROM users WHERE email=?", (email,)); user = c.fetchone()
    conn.close()
    return dict(user) if user else {"error": "Not found"}

@router.get("/api/users/pending")
def pending(request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True); c = conn.cursor(); c.execute("SELECT email, name, status FROM users WHERE status='pending'"); rows = [dict(r) for r in c.fetchall()]; conn.close(); return rows

@router.get("/api/users/all")
def all_users(request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved":
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True); c = conn.cursor()
    c.execute("SELECT email, name, role, status, signature, deputy, abs_start, abs_end, abs_type, abs_reason, is_head, hourly_rate, allowed_legal_entities, allowed_business_units, two_factor_enabled, CASE WHEN password IS NOT NULL AND password != '' THEN 1 ELSE 0 END AS has_password FROM users")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    for row in rows:
        for field_name in ("allowed_legal_entities", "allowed_business_units"):
            try:
                row[field_name] = json.loads(row.get(field_name) or "[]")
            except Exception:
                row[field_name] = []
        row["two_factor_enabled"] = int(row.get("two_factor_enabled") or 0)
        row["is_head"] = int(row.get("is_head") or 0)
    return rows

@router.post("/api/users/approve")
def approve(data: RoleData, request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    email = normalize_email(data.email)
    before = _load_user_snapshot(email)
    if not before:
        return {"error": "user_not_found"}
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET role=?, status='approved', is_head=? WHERE email=?", (data.role, data.is_head, email))
    if int(getattr(c, "rowcount", 0) or 0) <= 0:
        conn.close()
        return {"error": "user_not_found"}
    conn.commit()
    conn.close()
    after = _load_user_snapshot(email)
    record_field_changes("user", email, before, after, actor.get("email", ""), actor.get("name", ""))
    ip_address, user_agent = _request_meta(request)
    audit_log("user_approved", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="user", entity_id=email, details={"role": data.role, "is_head": data.is_head}, ip_address=ip_address, user_agent=user_agent)
    create_notification("Доступ одобрен", f"Твоя заявка в Korda CRM одобрена. Роль: {data.role}.", user_email=email, category="user", entity_type="user", entity_id=email)
    return {"status": "success"}


@router.post("/api/users/invite")
def invite_user(data: UserInviteData, request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}

    email = normalize_email(data.email)
    name = (data.name or "").strip()
    role = (data.role or "").strip()
    password = data.password or ""
    if not name or not email or not role:
        return {"error": "validation_error", "message": "Заполните имя, почту и роль сотрудника."}
    if role not in ALLOWED_USER_ROLES or role == "Директор":
        return {"error": "validation_error", "message": "Выберите допустимую роль сотрудника."}
    if not is_valid_email(email):
        return {"error": "validation_error", "message": "Введите корректную почту сотрудника."}
    password_error = validate_password_strength(password)
    if password_error:
        return {"error": "validation_error", "message": password_error}

    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT email FROM users WHERE email=?", (email,))
    if c.fetchone():
        conn.close()
        return {"error": "already_exists", "message": "Сотрудник с такой почтой уже есть в системе."}
    c.execute(
        "INSERT INTO users (email, password, name, role, status, is_head) VALUES (?, ?, ?, ?, 'approved', ?)",
        (email, hash_password(password), name, role, int(bool(data.is_head))),
    )
    conn.commit()
    conn.close()
    audit_log(
        "user_invited",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="user",
        entity_id=email,
        details={"role": role, "is_head": int(bool(data.is_head))},
    )
    create_notification(
        "Доступ создан",
        f"Для вас создан доступ в Korda CRM. Роль: {role}.",
        user_email=email,
        category="user",
        entity_type="user",
        entity_id=email,
    )
    return {"status": "success", "email": email}

@router.post("/api/users/make_head")
def make_head(data: RoleData, request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    email = normalize_email(data.email)
    before = _load_user_snapshot(email)
    if not before:
        return {"error": "user_not_found"}
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET is_head=? WHERE email=?", (data.is_head, email))
    if int(getattr(c, "rowcount", 0) or 0) <= 0:
        conn.close()
        return {"error": "user_not_found"}
    conn.commit()
    conn.close()
    after = _load_user_snapshot(email)
    record_field_changes("user", email, before, after, actor.get("email", ""), actor.get("name", ""))
    ip_address, user_agent = _request_meta(request)
    audit_log("user_head_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="user", entity_id=email, details={"is_head": data.is_head}, ip_address=ip_address, user_agent=user_agent)
    create_notification("Изменены права", f"Твой статус руководителя отдела был {'включён' if data.is_head else 'отключён'}.", user_email=email, category="user", entity_type="user", entity_id=email)
    return {"status": "success"}

@router.put("/api/users/role")
def update_role(data: RoleData, request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    email = normalize_email(data.email)
    before = _load_user_snapshot(email)
    if not before:
        return {"error": "user_not_found"}
    allowed_roles = {
        "Конструкторское бюро", "Производство и ОТК", "Склад", "Менеджер",
        "Бухгалтерия", "Юрист", "Секретарь / Канцелярия", "Сотрудник",
    }
    if data.role not in allowed_roles:
        return {"error": "invalid_role"}
    if before.get("role") == "Директор":
        return {"error": "protected_account"}
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET role=? WHERE email=?", (data.role, email))
    if int(getattr(c, "rowcount", 0) or 0) <= 0:
        conn.close()
        return {"error": "user_not_found"}
    conn.commit()
    conn.close()
    after = _load_user_snapshot(email)
    record_field_changes("user", email, before, after, actor.get("email", ""), actor.get("name", ""))
    ip_address, user_agent = _request_meta(request)
    audit_log("user_role_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="user", entity_id=email, details={"role": data.role}, ip_address=ip_address, user_agent=user_agent)
    create_notification("Обновлена роль", f"Твоя роль в CRM изменена на «{data.role}».", user_email=email, category="user", entity_type="user", entity_id=email)
    return {"status": "success"}

@router.post("/api/users/remove")
def remove_user(data: RemoveUserData, request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    email = normalize_email(data.email)
    before = _load_user_snapshot(email)
    conn = get_connection(); c = conn.cursor(); c.execute("UPDATE users SET status='banned' WHERE email=?", (email,)); conn.commit(); conn.close()
    delete_user_sessions_for_email(email)
    after = _load_user_snapshot(email)
    record_field_changes("user", email, before, after, actor.get("email", ""), actor.get("name", ""))
    ip_address, user_agent = _request_meta(request)
    audit_log("user_banned", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="user", entity_id=email, ip_address=ip_address, user_agent=user_agent)
    create_notification("Доступ ограничен", "Твой доступ в Korda CRM был заблокирован администратором.", user_email=email, category="user", entity_type="user", entity_id=email)
    return {"status": "success"}

@router.post("/api/users/restore")
def restore_user(data: RemoveUserData, request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    email = normalize_email(data.email)
    before = _load_user_snapshot(email)
    conn = get_connection(); c = conn.cursor(); c.execute("UPDATE users SET status='approved' WHERE email=?", (email,)); conn.commit(); conn.close()
    after = _load_user_snapshot(email)
    record_field_changes("user", email, before, after, actor.get("email", ""), actor.get("name", ""))
    ip_address, user_agent = _request_meta(request)
    audit_log("user_restored", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="user", entity_id=email, ip_address=ip_address, user_agent=user_agent)
    create_notification("Доступ восстановлен", "Твой доступ в Korda CRM снова активен.", user_email=email, category="user", entity_type="user", entity_id=email)
    return {"status": "success"}

@router.post("/api/users/signature")
def update_signature(data: SignatureData, request: Request):
    actor = get_request_user(request)
    if not actor or (actor.get("email") != normalize_email(data.email) and actor.get("role") != "Директор"):
        return {"error": "forbidden"}
    email = normalize_email(data.email)
    before = _load_user_snapshot(email)
    conn = get_connection(); c = conn.cursor(); c.execute("UPDATE users SET signature=? WHERE email=?", (data.signature, email)); conn.commit(); conn.close()
    after = _load_user_snapshot(email)
    record_field_changes("user", email, before, after, actor.get("email", ""), actor.get("name", ""))
    ip_address, user_agent = _request_meta(request)
    audit_log("user_signature_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="user", entity_id=email, details={"has_signature": bool(data.signature)}, ip_address=ip_address, user_agent=user_agent)
    return {"status": "success"}

@router.post("/api/users/vacation")
def update_vacation(data: VacationData, request: Request):
    actor = get_request_user(request)
    if not actor or (actor.get("email") != normalize_email(data.email) and actor.get("role") != "Директор"):
        return {"error": "forbidden"}
    email = normalize_email(data.email)
    before = _load_user_snapshot(email)
    conn = get_connection(); c = conn.cursor(); c.execute("UPDATE users SET abs_start=?, abs_end=?, abs_type=?, abs_reason=?, deputy=? WHERE email=?", (data.abs_start, data.abs_end, data.abs_type, data.abs_reason, data.deputy, email)); conn.commit(); conn.close()
    after = _load_user_snapshot(email)
    record_field_changes("user", email, before, after, actor.get("email", ""), actor.get("name", ""))
    ip_address, user_agent = _request_meta(request)
    audit_log("user_vacation_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="user", entity_id=email, details={"abs_start": data.abs_start, "abs_end": data.abs_end, "abs_type": data.abs_type, "deputy": data.deputy}, ip_address=ip_address, user_agent=user_agent)
    return {"status": "success"}


@router.get("/api/users/self_service/summary")
def get_self_service_summary(request: Request, user_email: str = ""):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, user_email)
    if not target_email:
        return {"error": "forbidden"}
    leave_requests = _list_hr_leave_requests(target_email)
    timesheet_entries = _list_hr_timesheet_entries(target_email)
    equipment_requests = _list_hr_equipment_requests(target_email)
    substitutions = _list_hr_substitution_requests(target_email)
    business_trips = _list_hr_business_trip_requests(target_email)
    month_key = time.strftime("%m.%Y")
    open_task_count = 0
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE executor=? AND status IN ('active', 'in_progress', 'new')
            """,
            (actor.get("name", ""),),
        )
        row = c.fetchone()
        open_task_count = int(row[0] if row else 0)
        conn.close()
    except Exception:
        open_task_count = 0
    return {
        "user_email": target_email,
        "metrics": {
            "leave_pending": len([item for item in leave_requests if item.get("status") in {"pending", "submitted"}]),
            "timesheet_hours_month": round(sum(float(item.get("hours") or 0) for item in timesheet_entries if _is_same_month(item.get("entry_date", ""), month_key)), 2),
            "equipment_open": len([item for item in equipment_requests if item.get("status") not in {"issued", "closed", "cancelled"}]),
            "substitutions_active": len([item for item in substitutions if item.get("status") in {"pending", "approved", "active"}]),
            "business_trips_open": len([item for item in business_trips if item.get("status") not in {"completed", "cancelled"}]),
            "open_tasks": open_task_count,
        },
        "leave_requests": leave_requests[:8],
        "timesheet_entries": timesheet_entries[:12],
        "equipment_requests": equipment_requests[:8],
        "substitutions": substitutions[:8],
        "business_trips": business_trips[:8],
    }


@router.get("/api/users/self_service/leave_requests")
def get_self_service_leave_requests(request: Request, user_email: str = ""):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    return _list_hr_leave_requests(_resolve_self_service_target(actor, user_email))


@router.post("/api/users/self_service/leave_requests")
def create_self_service_leave_request(data: HRLeaveRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, data.user_email)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    record_id = next_safe_table_id(conn, "hr_leave_requests")
    c.execute("SELECT name FROM users WHERE email=?", (target_email,))
    row = c.fetchone()
    user_name = (dict(row) if row else {}).get("name", actor.get("name", ""))
    c.execute(
        """
        INSERT INTO hr_leave_requests (id, user_email, user_name, leave_type, date_from, date_to, deputy_name, status, comment, created_at, updated_at, approved_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (record_id, target_email, user_name, data.leave_type, data.date_from, data.date_to, data.deputy_name, data.status or "pending", data.comment, now, now, actor.get("email", "") if actor.get("role") == "Директор" else ""),
    )
    conn.commit()
    conn.close()
    audit_log("hr_leave_request_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_leave_request", entity_id=str(record_id), details={"user_email": target_email, "leave_type": data.leave_type, "date_from": data.date_from, "date_to": data.date_to})
    return {"status": "success", "id": record_id}


@router.put("/api/users/self_service/leave_requests/{record_id}")
def update_self_service_leave_request(record_id: int, data: HRLeaveRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, data.user_email)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT user_email FROM hr_leave_requests WHERE id=?", (record_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    stored_email = (dict(row) if row else {}).get("user_email", "")
    if actor.get("role") != "Директор" and stored_email != actor.get("email", ""):
        conn.close()
        return {"error": "forbidden"}
    c.execute(
        """
        UPDATE hr_leave_requests
        SET user_email=?, leave_type=?, date_from=?, date_to=?, deputy_name=?, status=?, comment=?, updated_at=?, approved_by=?
        WHERE id=?
        """,
        (target_email or stored_email, data.leave_type, data.date_from, data.date_to, data.deputy_name, data.status or "pending", data.comment, now, actor.get("email", "") if actor.get("role") == "Директор" else "", record_id),
    )
    conn.commit()
    conn.close()
    audit_log("hr_leave_request_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_leave_request", entity_id=str(record_id), details={"user_email": target_email or stored_email, "status": data.status})
    return {"status": "success", "id": record_id}


@router.delete("/api/users/self_service/leave_requests/{record_id}")
def delete_self_service_leave_request(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT user_email FROM hr_leave_requests WHERE id=?", (record_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    stored_email = (dict(row) if row else {}).get("user_email", "")
    if actor.get("role") != "Директор" and stored_email != actor.get("email", ""):
        conn.close()
        return {"error": "forbidden"}
    c.execute("DELETE FROM hr_leave_requests WHERE id=?", (record_id,))
    conn.commit()
    conn.close()
    audit_log("hr_leave_request_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_leave_request", entity_id=str(record_id), details={"user_email": stored_email})
    return {"status": "success", "id": record_id}


@router.get("/api/users/self_service/timesheets")
def get_self_service_timesheets(request: Request, user_email: str = ""):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    return _list_hr_timesheet_entries(_resolve_self_service_target(actor, user_email))


@router.post("/api/users/self_service/timesheets")
def create_self_service_timesheet(data: HRTimesheetEntryData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, data.user_email)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    record_id = next_safe_table_id(conn, "hr_timesheet_entries")
    c.execute("SELECT name FROM users WHERE email=?", (target_email,))
    row = c.fetchone()
    user_name = (dict(row) if row else {}).get("name", actor.get("name", ""))
    c.execute(
        """
        INSERT INTO hr_timesheet_entries (id, user_email, user_name, entry_date, project_id, hours, work_mode, status, comment, created_at, updated_at, approved_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (record_id, target_email, user_name, data.entry_date, data.project_id, data.hours, data.work_mode, data.status or "submitted", data.comment, now, now, actor.get("email", "") if actor.get("role") == "Директор" else ""),
    )
    conn.commit()
    conn.close()
    audit_log("hr_timesheet_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_timesheet_entry", entity_id=str(record_id), details={"user_email": target_email, "entry_date": data.entry_date, "hours": data.hours})
    return {"status": "success", "id": record_id}


@router.put("/api/users/self_service/timesheets/{record_id}")
def update_self_service_timesheet(record_id: int, data: HRTimesheetEntryData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, data.user_email)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT user_email FROM hr_timesheet_entries WHERE id=?", (record_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    stored_email = (dict(row) if row else {}).get("user_email", "")
    if actor.get("role") != "Директор" and stored_email != actor.get("email", ""):
        conn.close()
        return {"error": "forbidden"}
    c.execute(
        """
        UPDATE hr_timesheet_entries
        SET user_email=?, entry_date=?, project_id=?, hours=?, work_mode=?, status=?, comment=?, updated_at=?, approved_by=?
        WHERE id=?
        """,
        (target_email or stored_email, data.entry_date, data.project_id, data.hours, data.work_mode, data.status or "submitted", data.comment, now, actor.get("email", "") if actor.get("role") == "Директор" else "", record_id),
    )
    conn.commit()
    conn.close()
    audit_log("hr_timesheet_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_timesheet_entry", entity_id=str(record_id), details={"user_email": target_email or stored_email, "hours": data.hours, "status": data.status})
    return {"status": "success", "id": record_id}


@router.delete("/api/users/self_service/timesheets/{record_id}")
def delete_self_service_timesheet(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT user_email FROM hr_timesheet_entries WHERE id=?", (record_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    stored_email = (dict(row) if row else {}).get("user_email", "")
    if actor.get("role") != "Директор" and stored_email != actor.get("email", ""):
        conn.close()
        return {"error": "forbidden"}
    c.execute("DELETE FROM hr_timesheet_entries WHERE id=?", (record_id,))
    conn.commit()
    conn.close()
    audit_log("hr_timesheet_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_timesheet_entry", entity_id=str(record_id), details={"user_email": stored_email})
    return {"status": "success", "id": record_id}


@router.get("/api/users/self_service/equipment_requests")
def get_self_service_equipment_requests(request: Request, user_email: str = ""):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    return _list_hr_equipment_requests(_resolve_self_service_target(actor, user_email))


@router.post("/api/users/self_service/equipment_requests")
def create_self_service_equipment_request(data: HREquipmentRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, data.user_email)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    record_id = next_safe_table_id(conn, "hr_equipment_requests")
    c.execute("SELECT name FROM users WHERE email=?", (target_email,))
    row = c.fetchone()
    user_name = (dict(row) if row else {}).get("name", actor.get("name", ""))
    c.execute(
        """
        INSERT INTO hr_equipment_requests (id, user_email, user_name, category, item_name, qty, needed_by, justification, status, comment, created_at, updated_at, approved_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (record_id, target_email, user_name, data.category, data.item_name, data.qty, data.needed_by, data.justification, data.status or "pending", data.comment, now, now, actor.get("email", "") if actor.get("role") == "Директор" else ""),
    )
    conn.commit()
    conn.close()
    audit_log("hr_equipment_request_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_equipment_request", entity_id=str(record_id), details={"user_email": target_email, "item_name": data.item_name, "qty": data.qty})
    return {"status": "success", "id": record_id}


@router.put("/api/users/self_service/equipment_requests/{record_id}")
def update_self_service_equipment_request(record_id: int, data: HREquipmentRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, data.user_email)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT user_email FROM hr_equipment_requests WHERE id=?", (record_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    stored_email = (dict(row) if row else {}).get("user_email", "")
    if actor.get("role") != "Директор" and stored_email != actor.get("email", ""):
        conn.close()
        return {"error": "forbidden"}
    c.execute(
        """
        UPDATE hr_equipment_requests
        SET user_email=?, category=?, item_name=?, qty=?, needed_by=?, justification=?, status=?, comment=?, updated_at=?, approved_by=?
        WHERE id=?
        """,
        (target_email or stored_email, data.category, data.item_name, data.qty, data.needed_by, data.justification, data.status or "pending", data.comment, now, actor.get("email", "") if actor.get("role") == "Директор" else "", record_id),
    )
    conn.commit()
    conn.close()
    audit_log("hr_equipment_request_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_equipment_request", entity_id=str(record_id), details={"user_email": target_email or stored_email, "status": data.status, "item_name": data.item_name})
    return {"status": "success", "id": record_id}


@router.delete("/api/users/self_service/equipment_requests/{record_id}")
def delete_self_service_equipment_request(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT user_email FROM hr_equipment_requests WHERE id=?", (record_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    stored_email = (dict(row) if row else {}).get("user_email", "")
    if actor.get("role") != "Директор" and stored_email != actor.get("email", ""):
        conn.close()
        return {"error": "forbidden"}
    c.execute("DELETE FROM hr_equipment_requests WHERE id=?", (record_id,))
    conn.commit()
    conn.close()
    audit_log("hr_equipment_request_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_equipment_request", entity_id=str(record_id), details={"user_email": stored_email})
    return {"status": "success", "id": record_id}


@router.get("/api/users/self_service/substitutions")
def get_self_service_substitutions(request: Request, user_email: str = ""):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    return _list_hr_substitution_requests(_resolve_self_service_target(actor, user_email))


@router.post("/api/users/self_service/substitutions")
def create_self_service_substitution(data: HRSubstitutionRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, data.user_email)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    record_id = next_safe_table_id(conn, "hr_substitution_requests")
    c.execute("SELECT name FROM users WHERE email=?", (target_email,))
    row = c.fetchone()
    user_name = (dict(row) if row else {}).get("name", actor.get("name", ""))
    c.execute(
        """
        INSERT INTO hr_substitution_requests (id, user_email, user_name, substitute_name, date_from, date_to, reason, status, comment, created_at, updated_at, approved_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (record_id, target_email, user_name, data.substitute_name, data.date_from, data.date_to, data.reason, data.status or "pending", data.comment, now, now, actor.get("email", "") if actor.get("role") == "Директор" else ""),
    )
    conn.commit()
    conn.close()
    audit_log("hr_substitution_request_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_substitution_request", entity_id=str(record_id), details={"user_email": target_email, "substitute_name": data.substitute_name})
    return {"status": "success", "id": record_id}


@router.put("/api/users/self_service/substitutions/{record_id}")
def update_self_service_substitution(record_id: int, data: HRSubstitutionRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, data.user_email)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT user_email FROM hr_substitution_requests WHERE id=?", (record_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    stored_email = (dict(row) if row else {}).get("user_email", "")
    if actor.get("role") != "Директор" and stored_email != actor.get("email", ""):
        conn.close()
        return {"error": "forbidden"}
    c.execute(
        """
        UPDATE hr_substitution_requests
        SET user_email=?, substitute_name=?, date_from=?, date_to=?, reason=?, status=?, comment=?, updated_at=?, approved_by=?
        WHERE id=?
        """,
        (target_email or stored_email, data.substitute_name, data.date_from, data.date_to, data.reason, data.status or "pending", data.comment, now, actor.get("email", "") if actor.get("role") == "Директор" else "", record_id),
    )
    conn.commit()
    conn.close()
    audit_log("hr_substitution_request_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_substitution_request", entity_id=str(record_id), details={"user_email": target_email or stored_email, "status": data.status})
    return {"status": "success", "id": record_id}


@router.delete("/api/users/self_service/substitutions/{record_id}")
def delete_self_service_substitution(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT user_email FROM hr_substitution_requests WHERE id=?", (record_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    stored_email = (dict(row) if row else {}).get("user_email", "")
    if actor.get("role") != "Директор" and stored_email != actor.get("email", ""):
        conn.close()
        return {"error": "forbidden"}
    c.execute("DELETE FROM hr_substitution_requests WHERE id=?", (record_id,))
    conn.commit()
    conn.close()
    audit_log("hr_substitution_request_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_substitution_request", entity_id=str(record_id), details={"user_email": stored_email})
    return {"status": "success", "id": record_id}


@router.get("/api/users/self_service/business_trips")
def get_self_service_business_trips(request: Request, user_email: str = ""):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    return _list_hr_business_trip_requests(_resolve_self_service_target(actor, user_email))


@router.post("/api/users/self_service/business_trips")
def create_self_service_business_trip(data: HRBusinessTripRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, data.user_email)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    record_id = next_safe_table_id(conn, "hr_business_trip_requests")
    c.execute("SELECT name FROM users WHERE email=?", (target_email,))
    row = c.fetchone()
    user_name = (dict(row) if row else {}).get("name", actor.get("name", ""))
    c.execute(
        """
        INSERT INTO hr_business_trip_requests (id, user_email, user_name, destination, date_from, date_to, purpose, transport_mode, estimated_cost, status, comment, created_at, updated_at, approved_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (record_id, target_email, user_name, data.destination, data.date_from, data.date_to, data.purpose, data.transport_mode, data.estimated_cost, data.status or "pending", data.comment, now, now, actor.get("email", "") if actor.get("role") == "Директор" else ""),
    )
    conn.commit()
    conn.close()
    audit_log("hr_business_trip_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_business_trip_request", entity_id=str(record_id), details={"user_email": target_email, "destination": data.destination, "date_from": data.date_from, "date_to": data.date_to})
    return {"status": "success", "id": record_id}


@router.put("/api/users/self_service/business_trips/{record_id}")
def update_self_service_business_trip(record_id: int, data: HRBusinessTripRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    target_email = _resolve_self_service_target(actor, data.user_email)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT user_email FROM hr_business_trip_requests WHERE id=?", (record_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    stored_email = (dict(row) if row else {}).get("user_email", "")
    if actor.get("role") != "Директор" and stored_email != actor.get("email", ""):
        conn.close()
        return {"error": "forbidden"}
    c.execute(
        """
        UPDATE hr_business_trip_requests
        SET user_email=?, destination=?, date_from=?, date_to=?, purpose=?, transport_mode=?, estimated_cost=?, status=?, comment=?, updated_at=?, approved_by=?
        WHERE id=?
        """,
        (target_email or stored_email, data.destination, data.date_from, data.date_to, data.purpose, data.transport_mode, data.estimated_cost, data.status or "pending", data.comment, now, actor.get("email", "") if actor.get("role") == "Директор" else "", record_id),
    )
    conn.commit()
    conn.close()
    audit_log("hr_business_trip_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_business_trip_request", entity_id=str(record_id), details={"user_email": target_email or stored_email, "status": data.status, "destination": data.destination})
    return {"status": "success", "id": record_id}


@router.delete("/api/users/self_service/business_trips/{record_id}")
def delete_self_service_business_trip(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT user_email FROM hr_business_trip_requests WHERE id=?", (record_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    stored_email = (dict(row) if row else {}).get("user_email", "")
    if actor.get("role") != "Директор" and stored_email != actor.get("email", ""):
        conn.close()
        return {"error": "forbidden"}
    c.execute("DELETE FROM hr_business_trip_requests WHERE id=?", (record_id,))
    conn.commit()
    conn.close()
    audit_log("hr_business_trip_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="hr_business_trip_request", entity_id=str(record_id), details={"user_email": stored_email})
    return {"status": "success", "id": record_id}


@router.put("/api/users/access_scope")
def update_access_scope(data: UserScopeData, request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    email = normalize_email(data.email)
    before = _load_user_snapshot(email)
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE users
        SET allowed_legal_entities=?, allowed_business_units=?, two_factor_enabled=?
        WHERE email=?
        """,
        (
            json.dumps(sorted({int(item) for item in (data.allowed_legal_entities or []) if int(item) > 0}), ensure_ascii=False),
            json.dumps(sorted({int(item) for item in (data.allowed_business_units or []) if int(item) > 0}), ensure_ascii=False),
            1 if int(data.two_factor_enabled or 0) else 0,
            email,
        ),
    )
    conn.commit()
    conn.close()
    after = _load_user_snapshot(email)
    record_field_changes("user", email, before, after, actor.get("email", ""), actor.get("name", ""))
    ip_address, user_agent = _request_meta(request)
    audit_log(
        "user_access_scope_updated",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="user",
        entity_id=email,
        details={
            "allowed_legal_entities": after.get("allowed_legal_entities", []),
            "allowed_business_units": after.get("allowed_business_units", []),
            "two_factor_enabled": after.get("two_factor_enabled", 0),
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return {"status": "success"}


@router.get("/api/users/field_rules")
def list_field_rules(request: Request, role: str = "", module: str = "", entity_type: str = ""):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    return get_field_access_rules(role=role, module=module, entity_type=entity_type, is_active=1)


@router.post("/api/users/field_rules")
def create_field_rule(data: FieldAccessRuleData, request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    role = (data.role or "").strip()
    module = (data.module or "").strip()
    entity_type = (data.entity_type or "").strip()
    field_name = (data.field_name or "").strip()
    if not (role and module and entity_type and field_name):
        return {"error": "invalid_rule"}
    rule_id = save_field_access_rule(
        role_name=role,
        module_name=module,
        entity_type=entity_type,
        field_name=field_name,
        can_view=int(data.can_view or 0),
        can_edit=int(data.can_edit or 0),
        allowed_statuses=data.allowed_statuses or [],
        actor_email=actor.get("email", ""),
        is_active=int(data.is_active or 0),
    )
    audit_log(
        "field_access_rule_created",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="field_access_rule",
        entity_id=str(rule_id),
        details={"role": role, "module": module, "entity_type": entity_type, "field_name": field_name},
    )
    return {"status": "success", "id": rule_id}


@router.delete("/api/users/field_rules/{rule_id}")
def remove_field_rule(rule_id: int, request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    deleted = delete_field_access_rule(rule_id)
    if not deleted:
        return {"error": "not_found"}
    audit_log(
        "field_access_rule_deleted",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="field_access_rule",
        entity_id=str(rule_id),
    )
    return {"status": "success", "id": rule_id}


@router.get("/api/users/sessions")
def get_user_sessions(request: Request, user_email: str = "", limit: int = 120):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    normalized_target = normalize_email(user_email)
    if actor.get("role") != "Директор" and normalized_target and normalized_target != actor.get("email"):
        return {"error": "forbidden"}
    if actor.get("role") != "Директор" and not normalized_target:
        normalized_target = actor.get("email", "")
    rows = list_user_sessions(normalized_target, limit=limit)
    current_session_id = request.cookies.get(SESSION_COOKIE_NAME, "")
    for row in rows:
        row["is_current"] = row.get("session_id") == current_session_id
    return rows


@router.post("/api/users/sessions/revoke")
def revoke_session(data: SessionRevokeData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    normalized_user = normalize_email(data.user_email)
    if actor.get("role") != "Директор":
        normalized_user = actor.get("email", "")
    revoked = revoke_user_session(data.session_id, normalized_user)
    if not revoked:
        return {"error": "not_found"}
    ip_address, user_agent = _request_meta(request)
    audit_log(
        "user_session_revoked",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="user_session",
        entity_id=data.session_id,
        details={"user_email": normalized_user},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return {"status": "success", "revoked": revoked}


@router.get("/api/audit/logs")
def audit_logs(request: Request, limit: int = 100):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    return get_audit_logs(limit=limit)


@router.get("/api/audit/field_changes")
def audit_field_changes(request: Request, limit: int = 120, entity_type: str = "", entity_id: str = ""):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    return get_field_change_logs(limit=limit, entity_type=entity_type, entity_id=entity_id)


@router.get("/api/system/errors")
def system_errors(request: Request, limit: int = 100):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    return get_error_logs(limit=limit)


@router.get("/api/system/backups")
def system_backups(request: Request, limit: int = 50):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    return get_backups(limit=limit)


@router.get("/api/system/readiness")
def system_readiness(request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    return build_system_readiness()


@router.post("/api/system/backup")
def create_backup(request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"korda_backup_{timestamp}.sql"
    file_path = os.path.join(BACKUP_DIR, filename)

    _run_postgres_dump(file_path)
    _refresh_legacy_postgres_snapshot(file_path)

    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    register_backup(filename, file_path, actor_email=actor.get("email", ""), file_size=file_size)
    audit_log("system_backup_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="backup", entity_id=filename, details={"size": file_size})

    backups = get_backups(limit=BACKUP_RETENTION_COUNT + 10)
    stale = backups[BACKUP_RETENTION_COUNT:]
    for item in stale:
        stale_filename = item.get("filename", "")
        stale_path = item.get("file_path", "")
        should_delete_row = not stale_path or not os.path.exists(stale_path)
        if stale_path and os.path.exists(stale_path):
            try:
                os.remove(stale_path)
                should_delete_row = True
            except Exception as exc:
                logger.exception("Failed to prune old backup %s: %s", stale_path, exc)
        if should_delete_row:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM system_backups WHERE filename=?", (stale_filename,))
            conn.commit()
            conn.close()

    return {"status": "success", "filename": filename, "size": file_size}


@router.get("/api/system/backups/{filename}")
def download_backup(filename: str, request: Request):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Некорректное имя файла")
    file_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Backup не найден")
    return FileResponse(file_path, media_type="application/octet-stream", filename=filename)


@router.post("/api/system/restore")
async def restore_backup(
    request: Request,
    filename: str = Form(default=""),
    upload: UploadFile | None = File(default=None),
):
    actor = _director_from_session(request)
    if not actor:
        return {"error": "forbidden"}

    restore_source = ""
    imported_name = ""
    if upload and upload.filename:
        lower_filename = upload.filename.lower()
        if not (lower_filename.endswith(".sql") or lower_filename.endswith(".db")):
            return {"error": "Можно восстановить только backup .sql или legacy .db"}
        imports_dir = os.path.join(BACKUP_DIR, "imports")
        os.makedirs(imports_dir, exist_ok=True)
        imported_name = f"import_{int(time.time())}_{os.path.basename(upload.filename)}"
        restore_source = os.path.join(imports_dir, imported_name)
        payload = await upload.read()
        with open(restore_source, "wb") as imported_file:
            imported_file.write(payload)
    elif filename:
        if "/" in filename or ".." in filename:
            return {"error": "Некорректное имя backup-файла"}
        restore_source = os.path.join(BACKUP_DIR, filename)
        if not os.path.exists(restore_source):
            return {"error": "Backup не найден"}
    else:
        return {"error": "Выберите backup для восстановления"}

    try:
        safety_backup_name = f"korda_prerestore_{time.strftime('%Y%m%d_%H%M%S')}.sql"
        safety_backup_path = os.path.join(BACKUP_DIR, safety_backup_name)
        _run_postgres_dump(safety_backup_path)
        register_backup(
            safety_backup_name,
            safety_backup_path,
            actor_email=actor.get("email", ""),
            file_size=os.path.getsize(safety_backup_path) if os.path.exists(safety_backup_path) else 0,
        )

        _run_postgres_restore(restore_source)
    except Exception as exc:
        logger.exception("Backup restore failed: %s", exc)
        return {"error": f"Не удалось восстановить backup: {exc}"}

    audit_log(
        "system_backup_restored",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="backup",
        entity_id=filename or imported_name,
        details={"source": filename or imported_name, "pre_restore_backup": safety_backup_name},
    )
    create_notification(
        "Backup восстановлен",
        f"{actor.get('name', 'Директор')} восстановил(а) систему из backup {filename or imported_name}.",
        category="system",
        entity_type="backup",
        entity_id=filename or imported_name,
    )
    return {"status": "success", "source": filename or imported_name}
