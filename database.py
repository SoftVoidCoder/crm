import os
import re
import time
import json
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import urlparse, unquote

import psycopg
from psycopg.rows import dict_row
from utils import hash_password, is_password_hashed, encrypt_secret, is_secret_encrypted
from db_migrations import apply_sql_migrations, get_migration_status
from app_logging import get_logger
from settings import DEFAULT_ADMIN_PASSWORD, DIRECTOR_EMAIL

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logger = get_logger("database")
DATABASE_URL = (os.getenv("KORDA_DATABASE_URL", "") or "").strip() or "postgresql://korda_user:korda@localhost:5432/korda"
DB_BACKEND = "postgres"
_PARSED_DATABASE_URL = urlparse(DATABASE_URL)
DB_NAME = unquote((_PARSED_DATABASE_URL.path or "").lstrip("/")) or "korda"
DATABASE_RUNTIME_DIR = BASE_DIR
POSTGRES_DSN = DATABASE_URL
ROW_FACTORY_DICT = object()
DatabaseIntegrityError = psycopg.IntegrityError
DatabaseOperationalError = psycopg.OperationalError
CRITICAL_ENTITY_LOCK_POLICIES = {
    "finance_payment": {"ttl_seconds": 1800, "risk": "critical"},
    "purchase_order": {"ttl_seconds": 1800, "risk": "critical"},
    "sales_document": {"ttl_seconds": 1800, "risk": "critical"},
    "production_order": {"ttl_seconds": 2400, "risk": "critical"},
    "production_operation": {"ttl_seconds": 2400, "risk": "critical"},
    "production_bom_item": {"ttl_seconds": 2400, "risk": "high"},
    "production_route_template": {"ttl_seconds": 2400, "risk": "high"},
    "epl_waybill": {"ttl_seconds": 1800, "risk": "critical"},
    "inventory_document": {"ttl_seconds": 1800, "risk": "high"},
    "inventory_act": {"ttl_seconds": 1800, "risk": "high"},
}
MAX_SAFE_RUNTIME_ID = 2_147_000_000
_INIT_DB_LOCK = threading.Lock()
_INIT_DB_DONE = False
_INSERT_TABLE_RE = re.compile(r"^\s*INSERT\s+INTO\s+([^\s(]+)", re.IGNORECASE)


def is_postgres_backend() -> bool:
    return True


def next_safe_table_id(conn, table_name: str, id_column: str = "id", max_value: int = MAX_SAFE_RUNTIME_ID) -> int:
    row = conn.execute(
        f"SELECT COALESCE(MAX({id_column}), 0) FROM {table_name} WHERE {id_column} BETWEEN 1 AND ?",
        (max_value,),
    ).fetchone()
    next_id = int(_extract_scalar_value(row, 0) or 0) + 1
    if next_id <= max_value:
        return max(1, next_id)
    fallback = conn.execute(
        f"SELECT COALESCE(COUNT(*), 0) + 1 FROM {table_name} WHERE {id_column} BETWEEN 1 AND ?",
        (max_value,),
    ).fetchone()
    return max(1, min(int(_extract_scalar_value(fallback, 1) or 1), max_value))


def _sync_postgres_sequence_after_insert(conn, sql: str):
    match = _INSERT_TABLE_RE.match(str(sql or ""))
    if not match:
        return
    table_ref = (match.group(1) or "").strip()
    if not table_ref:
        return
    lookup_name = table_ref.replace('"', "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\.]*", lookup_name):
        return
    savepoint_name = f"seqsync_{int(time.time() * 1000000)}_{abs(hash(table_ref)) % 100000}"
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {savepoint_name}")
            cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", (lookup_name, "id"))
            row = cursor.fetchone()
            sequence_name = _extract_scalar_value(row, 0)
            if not sequence_name:
                cursor.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                return
            cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table_ref}")
            row = cursor.fetchone()
            max_id = int(_extract_scalar_value(row, 0) or 0)
            if max_id <= 0:
                cursor.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                return
            cursor.execute("SELECT setval(%s::regclass, %s, true)", (sequence_name, max_id))
            cursor.execute(f"RELEASE SAVEPOINT {savepoint_name}")
    except Exception:
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                cursor.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        except Exception:
            pass
        return


def _is_database_locked_error(exc: Exception) -> bool:
    return "could not obtain lock" in str(exc).lower()


def _split_sql_statements(sql_text: str) -> list[str]:
    statements = []
    current = []
    in_single = False
    in_double = False
    for char in sql_text:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        if char == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _translate_insert_or_ignore(sql_text: str) -> str:
    upper = sql_text.lstrip().upper()
    marker = "INSERT OR IGNORE INTO"
    if not upper.startswith(marker):
        return sql_text
    prefix_len = sql_text.upper().find(marker)
    body = sql_text[prefix_len + len(marker):].strip()
    values_index = body.upper().find("VALUES")
    if values_index < 0:
        return sql_text.replace("INSERT OR IGNORE", "INSERT", 1)
    head = body[:values_index].rstrip()
    tail = body[values_index:]
    return f"INSERT INTO {head} {tail} ON CONFLICT DO NOTHING"


def _translate_question_params(sql_text: str) -> str:
    result = []
    for char in sql_text:
        if char == "%":
            result.append("%%")
        elif char == "?":
            result.append("%s")
        else:
            result.append(char)
    return "".join(result)


def _translate_postgres_sql(sql_text: str) -> str:
    sql_text = (sql_text or "").strip()
    if not sql_text:
        return sql_text
    upper = sql_text.upper()
    if upper.startswith("SELECT LAST_INSERT_ROWID()"):
        return "SELECT LASTVAL()"
    sql_text = _translate_insert_or_ignore(sql_text)
    sql_text = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\b", "BIGSERIAL PRIMARY KEY", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"strftime\(\s*'%s'\s*,\s*'now'\s*\)", "EXTRACT(EPOCH FROM NOW())::BIGINT", sql_text, flags=re.IGNORECASE)
    sql_text = sql_text.replace("AUTOINCREMENT", "")
    return _translate_question_params(sql_text)


def _normalize_pg_params(params):
    if params is None:
        return ()
    if isinstance(params, tuple):
        return params
    if isinstance(params, list):
        return tuple(params)
    return tuple(params)


def _column_exists(c, table_name: str, column_name: str) -> bool:
    c.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=? AND column_name=?
        LIMIT 1
        """,
        (table_name, column_name),
    )
    return bool(c.fetchone())


def _add_column_if_missing(c, table_name: str, column_name: str, definition: str):
    if _column_exists(c, table_name, column_name):
        return
    c.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _ensure_postgres_id_defaults(conn):
    if not is_postgres_backend():
        return
    c = conn.cursor()
    c.execute(
        """
        SELECT table_name, column_name, column_default
        FROM information_schema.columns
        WHERE table_schema='public'
          AND column_name='id'
          AND data_type IN ('integer', 'bigint')
          AND identity_generation IS NULL
        ORDER BY table_name
        """
    )
    for table_name, column_name, column_default in c.fetchall():
        if table_name in {"warehouse_policies"}:
            continue
        sequence_name = f"{table_name}_{column_name}_seq"
        quoted_table = _quote_identifier(table_name)
        quoted_column = _quote_identifier(column_name)
        quoted_sequence = _quote_identifier(sequence_name)
        try:
            c.execute("SELECT pg_get_serial_sequence(?, ?)", (f"public.{table_name}", column_name))
            row = c.fetchone()
            serial_sequence = _extract_scalar_value(row, "") or ""
            if not serial_sequence:
                c.execute(f"CREATE SEQUENCE IF NOT EXISTS {quoted_sequence} AS BIGINT")
                c.execute(f"ALTER SEQUENCE {quoted_sequence} OWNED BY {quoted_table}.{quoted_column}")
                serial_sequence = sequence_name
            if not column_default:
                sequence_literal = str(serial_sequence).replace("'", "''")
                c.execute(
                    f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} "
                    f"SET DEFAULT nextval('{sequence_literal}'::regclass)"
                )
            sequence_literal = str(serial_sequence).replace("'", "''")
            c.execute(
                f"SELECT setval('{sequence_literal}'::regclass, "
                f"COALESCE((SELECT MAX({quoted_column}) FROM {quoted_table} "
                f"WHERE {quoted_column} BETWEEN 1 AND {MAX_SAFE_RUNTIME_ID}), 0) + 1, false)"
            )
        except Exception as exc:
            logger.warning("Failed to ensure id default for %s.%s: %s", table_name, column_name, exc)


def _insert_uses_implicit_numeric_id(sql_text: str) -> bool:
    table_match = re.search(r"INSERT\s+INTO\s+([^\s(]+)", sql_text, flags=re.IGNORECASE)
    table_name = (table_match.group(1).strip().strip('"').lower() if table_match else "")
    if table_name in {"users", "user_sessions"}:
        return False
    match = re.search(r"INSERT\s+INTO\s+[^\s(]+\s*\(([^)]+)\)", sql_text, flags=re.IGNORECASE)
    if not match:
        return True
    columns = [item.strip().strip('"').lower() for item in match.group(1).split(",")]
    return "id" not in columns


def _extract_scalar_value(row, default=0):
    if row in (None, ""):
        return default
    if isinstance(row, dict):
        values = list(row.values())
        return values[0] if values else default
    if isinstance(row, (list, tuple)):
        return row[0] if row else default
    return row

class CompatCursor:
    def __init__(self, conn, inner, backend: str):
        self._conn = conn
        self._inner = inner
        self._backend = backend
        self._lastrowid = 0

    def _should_use_savepoint(self, sql: str) -> bool:
        if self._backend != "postgres":
            return False
        if bool(getattr(self._conn, "autocommit", False)):
            return False
        statement = str(sql or "").strip().upper()
        return bool(statement) and not statement.startswith(("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"))

    def execute(self, sql, params=None):
        translated = _translate_postgres_sql(sql)
        params = _normalize_pg_params(params)
        savepoint_name = None
        is_insert = translated.upper().startswith("INSERT INTO")
        if self._should_use_savepoint(translated):
            savepoint_name = f"sp_{int(time.time() * 1000000)}_{id(self) % 100000}"
            self._conn.execute(f"SAVEPOINT {savepoint_name}")
        try:
            self._inner.execute(translated, params)
        except Exception:
            if savepoint_name:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                self._conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            raise
        if savepoint_name:
            self._conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        self._lastrowid = getattr(self._inner, "lastrowid", 0) or 0
        if not self._lastrowid and translated.upper().startswith("INSERT INTO") and _insert_uses_implicit_numeric_id(translated):
            try:
                self._inner.execute("SELECT LASTVAL()")
                row = self._inner.fetchone()
                self._lastrowid = int(_extract_scalar_value(row, 0) or 0)
            except Exception:
                self._lastrowid = 0
        if self._backend == "postgres" and is_insert:
            _sync_postgres_sequence_after_insert(self._conn, translated)
        return self

    def executemany(self, sql, seq_of_params):
        translated = _translate_postgres_sql(sql)
        savepoint_name = None
        is_insert = translated.upper().startswith("INSERT INTO")
        if self._should_use_savepoint(translated):
            savepoint_name = f"sp_{int(time.time() * 1000000)}_{id(self) % 100000}"
            self._conn.execute(f"SAVEPOINT {savepoint_name}")
        try:
            self._inner.executemany(translated, [_normalize_pg_params(item) for item in seq_of_params])
        except Exception:
            if savepoint_name:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                self._conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            raise
        if savepoint_name:
            self._conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        if self._backend == "postgres" and is_insert:
            _sync_postgres_sequence_after_insert(self._conn, translated)
        return self

    def _wrap_row(self, row):
        if isinstance(row, dict):
            return CompatRow(row)
        return row

    def fetchone(self):
        return self._wrap_row(self._inner.fetchone())

    def fetchall(self):
        return [self._wrap_row(row) for row in self._inner.fetchall()]

    @property
    def lastrowid(self):
        return self._lastrowid

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._inner.__exit__(exc_type, exc, tb)


class CompatConnection:
    def __init__(self, inner, backend: str):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_backend", backend)

    def cursor(self):
        return CompatCursor(self._inner, self._inner.cursor(), self._backend)

    def execute(self, sql, params=None):
        cursor = self.cursor()
        return cursor.execute(sql, params or [])

    def executemany(self, sql, seq_of_params):
        cursor = self.cursor()
        return cursor.executemany(sql, seq_of_params)

    def executescript(self, sql: str):
        statements = _split_sql_statements(sql)
        cursor = self.cursor()
        for statement in statements:
            cursor.execute(statement)
        return cursor

    def commit(self):
        return self._inner.commit()

    def rollback(self):
        return self._inner.rollback()

    def close(self):
        return self._inner.close()

    def __del__(self):
        inner = getattr(self, "_inner", None)
        if inner is None:
            return
        try:
            if not getattr(inner, "closed", True):
                inner.close()
        except Exception:
            pass

    def __setattr__(self, key, value):
        if key in {"_inner", "_backend"}:
            object.__setattr__(self, key, value)
            return
        inner = object.__getattribute__(self, "_inner")
        if key == "row_factory" and self._backend == "postgres":
            if hasattr(inner, "row_factory"):
                inner.row_factory = dict_row if value is ROW_FACTORY_DICT else value
            return
        if hasattr(inner, key):
            setattr(inner, key, value)
            return
        object.__setattr__(self, key, value)

    def __getattr__(self, item):
        return getattr(self._inner, item)


class CompatRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            try:
                return list(self.values())[key]
            except IndexError as exc:
                raise KeyError(key) from exc
        return super().__getitem__(key)


def get_lock_policy_catalog():
    return [
        {
            "entity_type": entity_type,
            "ttl_seconds": int(config.get("ttl_seconds") or 900),
            "risk": config.get("risk") or "normal",
        }
        for entity_type, config in sorted(CRITICAL_ENTITY_LOCK_POLICIES.items(), key=lambda item: item[0])
    ]


def get_lock_ttl_seconds(entity_type: str, default_ttl: int = 900) -> int:
    policy = CRITICAL_ENTITY_LOCK_POLICIES.get(str(entity_type or "").strip(), {})
    return max(60, int(policy.get("ttl_seconds") or default_ttl))


def get_database_runtime_info():
    info = {
        "backend": DB_BACKEND,
        "database_url": DATABASE_URL,
        "db_name": DB_NAME,
        "supports_wal": 0,
    }
    conn = get_connection(row_factory=True)
    try:
        migration = get_migration_status(conn)
        info["migrations_applied"] = len(migration.get("applied") or [])
        info["migrations_pending"] = len(migration.get("pending") or [])
        info["pending_migrations"] = migration.get("pending") or []
        version_row = conn.execute("SELECT version()").fetchone()
        db_row = conn.execute("SELECT current_database(), current_schema()").fetchone()
        info.update(
            {
                "integrity": "managed_by_postgres",
                "journal_mode": "mvcc",
                "synchronous": "server_managed",
                "page_count": 0,
                "page_size": 0,
                "wal_autocheckpoint": 0,
                "busy_timeout_ms": 0,
                "server_version": (version_row[0] if version_row else "")[:120],
                "current_database": db_row[0] if db_row else DB_NAME,
                "current_schema": db_row[1] if db_row else "public",
            }
        )
    finally:
        conn.close()
    return info


def _configure_connection(conn, row_factory: bool = False):
    if row_factory and hasattr(conn, "row_factory"):
        conn.row_factory = dict_row
    return CompatConnection(conn, DB_BACKEND)


def get_connection(row_factory: bool = False):
    conn = psycopg.connect(POSTGRES_DSN, autocommit=False, row_factory=dict_row if row_factory else None)
    return _configure_connection(conn, row_factory=row_factory)


@contextmanager
def db_transaction(row_factory: bool = False, mode: str = "deferred"):
    conn = get_connection(row_factory=row_factory)
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _json_dumps(data):
    return json.dumps(data, ensure_ascii=False)


def _json_loads_safe(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _promote_postgres_id_columns_to_bigint(conn):
    if not is_postgres_backend():
        return
    c = conn.cursor()
    c.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema='public'
          AND data_type='integer'
          AND (
                column_name='id'
                OR column_name LIKE '%\\_id' ESCAPE '\\'
              )
        ORDER BY table_name, ordinal_position
        """
    )
    for row in c.fetchall():
        table_name = row[0]
        column_name = row[1]
        try:
            c.execute(
                f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" TYPE BIGINT USING "{column_name}"::bigint'
            )
        except Exception:
            continue


def _db_table_exists(conn, table_name: str) -> bool:
    c = conn.cursor()
    if is_postgres_backend():
        c.execute("SELECT to_regclass(?)", (f"public.{table_name}",))
        row = c.fetchone()
        return bool(_extract_scalar_value(row, ""))
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return c.fetchone() is not None


def get_recent_attempt_count(action: str, identifier: str, window_seconds: int) -> int:
    conn = get_connection()
    c = conn.cursor()
    threshold = int(time.time()) - window_seconds
    c.execute(
        "SELECT COUNT(*) FROM auth_attempts WHERE action=? AND identifier=? AND created_at >= ?",
        (action, identifier, threshold),
    )
    count = c.fetchone()[0]
    conn.close()
    return count


def record_auth_attempt(action: str, identifier: str, success: int = 0):
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        "INSERT INTO auth_attempts (action, identifier, success, created_at) VALUES (?, ?, ?, ?)",
        (action, identifier, int(success), now),
    )
    c.execute("DELETE FROM auth_attempts WHERE created_at < ?", (now - 86400,))
    conn.commit()
    conn.close()


def clear_auth_attempts(action: str, identifier: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM auth_attempts WHERE action=? AND identifier=?", (action, identifier))
    conn.commit()
    conn.close()


def audit_log(
    action: str,
    actor_email: str = "",
    actor_name: str = "",
    entity_type: str = "",
    entity_id: str = "",
    details: dict | None = None,
    ip_address: str = "",
    user_agent: str = "",
):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO audit_log (
            action, actor_email, actor_name, entity_type, entity_id, details,
            ip_address, user_agent, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action,
            actor_email,
            actor_name,
            entity_type,
            entity_id,
            _json_dumps(details or {}),
            ip_address,
            user_agent,
            int(time.time()),
        ),
    )
    conn.commit()
    conn.close()


def get_audit_logs(limit: int = 100):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        "SELECT * FROM audit_log ORDER BY created_at DESC, id DESC LIMIT ?",
        (max(1, min(limit, 500)),),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    for row in rows:
        try:
            row["details"] = json.loads(row.get("details") or "{}")
        except Exception:
            row["details"] = {}
    return rows


def record_field_changes(
    entity_type: str,
    entity_id: str,
    before: dict | None,
    after: dict | None,
    actor_email: str = "",
    actor_name: str = "",
):
    def _stringify_change_value(value):
        if isinstance(value, (dict, list)):
            return _json_dumps(value)
        if value is None:
            return ""
        return str(value)

    before_map = before or {}
    after_map = after or {}
    changed_fields = sorted(set(before_map.keys()) | set(after_map.keys()))
    changes = []
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    for field_name in changed_fields:
        old_value = before_map.get(field_name)
        new_value = after_map.get(field_name)
        if old_value == new_value:
            continue
        changes.append(field_name)
        c.execute(
            """
            INSERT INTO field_change_log (
                entity_type, entity_id, field_name, old_value, new_value,
                actor_email, actor_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_type,
                str(entity_id),
                field_name,
                _stringify_change_value(old_value),
                _stringify_change_value(new_value),
                actor_email,
                actor_name,
                now,
            ),
        )
    conn.commit()
    conn.close()
    return changes


def get_field_change_logs(limit: int = 120, entity_type: str = "", entity_id: str = ""):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    clauses = []
    params = []
    if entity_type:
        clauses.append("entity_type=?")
        params.append(entity_type)
    if entity_id:
        clauses.append("entity_id=?")
        params.append(str(entity_id))
    sql = "SELECT * FROM field_change_log"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    c.execute(sql, tuple(params))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def record_domain_event(
    domain_name: str,
    event_name: str,
    entity_type: str = "",
    entity_id: str = "",
    actor_email: str = "",
    actor_name: str = "",
    payload: dict | None = None,
    severity: str = "info",
):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO domain_events (
                domain_name, event_name, entity_type, entity_id, actor_email, actor_name, payload, severity, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                domain_name,
                event_name,
                entity_type,
                str(entity_id or ""),
                actor_email,
                actor_name,
                _json_dumps(payload or {}),
                severity or "info",
                int(time.time()),
            ),
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


def get_domain_events(limit: int = 120, domain_name: str = "", entity_type: str = "", entity_id: str = ""):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        clauses = []
        params = []
        if domain_name:
            clauses.append("domain_name=?")
            params.append(domain_name)
        if entity_type:
            clauses.append("entity_type=?")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id=?")
            params.append(str(entity_id))
        sql = "SELECT * FROM domain_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        c.execute(sql, params)
        rows = [dict(r) for r in c.fetchall()]
    finally:
        conn.close()
    for row in rows:
        row["payload"] = _json_loads_safe(row.get("payload"), {})
    return rows


def create_notification(
    title: str,
    message: str,
    user_email: str = "",
    user_name: str = "",
    category: str = "system",
    entity_type: str = "",
    entity_id: str = "",
):
    last_error = None
    for _ in range(3):
        conn = get_connection()
        try:
            c = conn.cursor()
            now = int(time.time())
            c.execute(
                """
                INSERT INTO notifications (
                    title, message, user_email, user_name, category, entity_type, entity_id, is_read, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (title, message, user_email, user_name, category, entity_type, entity_id, now),
            )
            conn.commit()
            return c.lastrowid
        except DatabaseOperationalError as exc:
            conn.rollback()
            last_error = exc
            if not _is_database_locked_error(exc):
                raise
            time.sleep(0.2)
        finally:
            conn.close()
    logger.warning("Skipping notification write due to transient database issue: %s", last_error)
    return 0


def get_notifications_for_user(user_email: str = "", user_name: str = "", limit: int = 100):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT *
        FROM notifications
        WHERE (user_email != '' AND user_email = ?)
           OR (user_name != '' AND user_name = ?)
           OR (user_email = '' AND user_name = '')
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (user_email, user_name, max(1, min(limit, 300))),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def mark_notification_read(notification_id: int, user_email: str = "", user_name: str = ""):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE notifications
        SET is_read=1
        WHERE id=?
          AND (
            (user_email != '' AND user_email = ?)
            OR (user_name != '' AND user_name = ?)
            OR (user_email = '' AND user_name = '')
          )
        """,
        (notification_id, user_email, user_name),
    )
    conn.commit()
    conn.close()


def mark_all_notifications_read(user_email: str = "", user_name: str = ""):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE notifications
        SET is_read=1
        WHERE (
            (user_email != '' AND user_email = ?)
            OR (user_name != '' AND user_name = ?)
            OR (user_email = '' AND user_name = '')
        )
        """,
        (user_email, user_name),
    )
    conn.commit()
    conn.close()


def upsert_entity_watch(
    user_email: str,
    user_name: str,
    entity_type: str,
    entity_id: str,
    title: str = "",
    meta: str = "",
    view_name: str = "",
    condition_key: str = "any_change",
    digest_mode: str = "instant",
    event_types: list | None = None,
):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        INSERT INTO entity_watchers (
            user_email, user_name, entity_type, entity_id, title, meta, view_name, condition_key,
            digest_mode, event_types_json, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(user_email, entity_type, entity_id)
        DO UPDATE SET
            user_name=excluded.user_name,
            title=excluded.title,
            meta=excluded.meta,
            view_name=excluded.view_name,
            condition_key=excluded.condition_key,
            digest_mode=excluded.digest_mode,
            event_types_json=excluded.event_types_json,
            is_active=1,
            updated_at=excluded.updated_at
        """,
        (
            user_email or "",
            user_name or "",
            entity_type or "",
            str(entity_id or ""),
            title or "",
            meta or "",
            view_name or "",
            condition_key or "any_change",
            digest_mode or "instant",
            json.dumps(event_types or [], ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.commit()
    row = c.execute(
        "SELECT * FROM entity_watchers WHERE user_email=? AND entity_type=? AND entity_id=?",
        (user_email or "", entity_type or "", str(entity_id or "")),
    ).fetchone()
    conn.close()
    return dict(row) if isinstance(row, dict) else {}


def delete_entity_watch(user_email: str, entity_type: str, entity_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "DELETE FROM entity_watchers WHERE user_email=? AND entity_type=? AND entity_id=?",
        (user_email or "", entity_type or "", str(entity_id or "")),
    )
    conn.commit()
    conn.close()


def list_entity_watches(user_email: str, limit: int = 100):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT *
        FROM entity_watchers
        WHERE user_email=? AND is_active=1
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (user_email or "", max(1, min(limit, 300))),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def notify_entity_watchers(
    entity_type: str,
    entity_id: str,
    title: str,
    message: str,
    event_key: str = "status_changed",
    event_value: str = "",
    actor_email: str = "",
    actor_name: str = "",
    category: str = "watch",
):
    entity_type = entity_type or ""
    entity_id = str(entity_id or "")
    event_key = event_key or "status_changed"
    event_value = str(event_value or event_key)
    if not entity_type or not entity_id:
        return 0
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT *
        FROM entity_watchers
        WHERE entity_type=? AND entity_id=? AND is_active=1
        """,
        (entity_type, entity_id),
    )
    watchers = [dict(r) for r in c.fetchall()]
    conn.close()
    matched = 0
    now = int(time.time())
    status_like_events = {"status_changed", "paid", "signed", "overdue", "stage_changed"}
    for watcher in watchers:
        condition = watcher.get("condition_key") or "any_change"
        if condition not in {event_key, "any_change"} and not (condition == "status_changed" and event_key in status_like_events):
            continue
        if actor_email and watcher.get("user_email") == actor_email:
            continue
        if watcher.get("last_event_key") == event_key and str(watcher.get("last_event_value") or "") == event_value:
            continue
        create_notification(
            title or "Объект изменился",
            message or "Есть изменение по объекту, за которым ты следишь.",
            user_email=watcher.get("user_email") or "",
            user_name=watcher.get("user_name") or "",
            category=category,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        update_conn = get_connection()
        try:
            update_conn.execute(
                """
                UPDATE entity_watchers
                SET last_event_key=?, last_event_value=?, last_notified_at=?, updated_at=?
                WHERE id=?
                """,
                (event_key, event_value, now, now, watcher.get("id")),
            )
            update_conn.commit()
        finally:
            update_conn.close()
        matched += 1
    return matched


def record_error_log(
    source: str,
    message: str,
    path: str = "",
    method: str = "",
    actor_email: str = "",
    severity: str = "error",
    traceback_text: str = "",
):
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO error_logs (
                source, message, path, method, actor_email, severity, traceback_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source, message[:1000], path, method, actor_email, severity, traceback_text[:12000], int(time.time())),
        )
        conn.commit()
    except DatabaseOperationalError as exc:
        logger.warning("Skipping error_logs write due to transient database issue: %s", exc)
    except Exception as exc:
        logger.warning("Skipping error_logs write due to unexpected issue: %s", exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def get_error_logs(limit: int = 100):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        "SELECT * FROM error_logs ORDER BY created_at DESC, id DESC LIMIT ?",
        (max(1, min(limit, 500)),),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def register_backup(filename: str, file_path: str, actor_email: str = "", file_size: int = 0):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO system_backups (filename, file_path, actor_email, file_size, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (filename, file_path, actor_email, file_size, int(time.time())),
    )
    conn.commit()
    backup_id = c.lastrowid
    conn.close()
    return backup_id


def get_backups(limit: int = 50):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        "SELECT * FROM system_backups ORDER BY created_at DESC, id DESC LIMIT ?",
        (max(1, min(limit, 200)),),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def start_background_job_run(job_name: str, job_group: str = "system", status: str = "running", details: dict | None = None):
    now = int(time.time())
    with db_transaction() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO background_job_runs (job_name, job_group, status, started_at, heartbeat_at, finished_at, details)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (job_name, job_group, status, now, now, _json_dumps(details or {})),
        )
        return c.lastrowid


def heartbeat_background_job_run(run_id: int, details: dict | None = None):
    now = int(time.time())
    with db_transaction() as conn:
        conn.execute(
            "UPDATE background_job_runs SET heartbeat_at=?, details=? WHERE id=?",
            (now, _json_dumps(details or {}), int(run_id)),
        )


def finish_background_job_run(run_id: int, status: str = "success", details: dict | None = None):
    now = int(time.time())
    with db_transaction() as conn:
        conn.execute(
            "UPDATE background_job_runs SET status=?, finished_at=?, heartbeat_at=?, details=? WHERE id=?",
            (status, now, now, _json_dumps(details or {}), int(run_id)),
        )


def list_background_job_runs(limit: int = 50, job_group: str = "", include_stale: int = 1):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    params = [max(1, min(limit, 200))]
    sql = "SELECT * FROM background_job_runs"
    if job_group:
        sql += " WHERE job_group=?"
        params.insert(0, job_group)
    sql += " ORDER BY started_at DESC, id DESC LIMIT ?"
    c.execute(sql, tuple(params))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    now = int(time.time())
    payload = []
    for row in rows:
        row["details"] = _json_loads_safe(row.get("details"), {})
        row["is_stale"] = int(row.get("status") == "running" and _safe_int(row.get("heartbeat_at")) < now - 900)
        if include_stale or not row["is_stale"]:
            payload.append(row)
    return payload


def start_recovery_workflow_run(action_name: str, actor_email: str = "", target_scope: str = "", details: dict | None = None):
    now = int(time.time())
    with db_transaction() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO recovery_workflow_runs (action_name, actor_email, target_scope, status, started_at, finished_at, details)
            VALUES (?, ?, ?, 'running', ?, 0, ?)
            """,
            (action_name, actor_email, target_scope, now, _json_dumps(details or {})),
        )
        return c.lastrowid


def finish_recovery_workflow_run(run_id: int, status: str = "success", result_summary: dict | None = None):
    now = int(time.time())
    with db_transaction() as conn:
        conn.execute(
            """
            UPDATE recovery_workflow_runs
            SET status=?, finished_at=?, details=?
            WHERE id=?
            """,
            (status, now, _json_dumps(result_summary or {}), int(run_id)),
        )


def list_recovery_workflow_runs(limit: int = 50, status: str = ""):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    if status:
        c.execute(
            """
            SELECT *
            FROM recovery_workflow_runs
            WHERE status=?
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (status, max(1, min(limit, 200))),
        )
    else:
        c.execute(
            """
            SELECT *
            FROM recovery_workflow_runs
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["details"] = _json_loads_safe(row.get("details"), {})
    return rows


def create_user_session(user_email: str, ip_address: str = "", user_agent: str = "", ttl_seconds: int = 43200) -> str:
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    session_id = secrets.token_urlsafe(32)
    c.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now,))
    c.execute(
        """
        INSERT INTO user_sessions (session_id, user_email, ip_address, user_agent, created_at, expires_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, user_email, ip_address, user_agent[:500], now, now + ttl_seconds, now),
    )
    conn.commit()
    conn.close()
    return session_id


def list_user_sessions(user_email: str = "", limit: int = 120):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    now = int(time.time())
    c.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now,))
    if user_email:
        c.execute(
            """
            SELECT s.*, COALESCE(u.name, '') AS user_name, COALESCE(u.role, '') AS user_role
            FROM user_sessions s
            LEFT JOIN users u ON u.email = s.user_email
            WHERE s.user_email=?
            ORDER BY s.last_seen_at DESC, s.created_at DESC
            LIMIT ?
            """,
            (user_email, max(1, min(limit, 500))),
        )
    else:
        c.execute(
            """
            SELECT s.*, COALESCE(u.name, '') AS user_name, COALESCE(u.role, '') AS user_role
            FROM user_sessions s
            LEFT JOIN users u ON u.email = s.user_email
            ORDER BY s.last_seen_at DESC, s.created_at DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        )
    rows = [dict(r) for r in c.fetchall()]
    conn.commit()
    conn.close()
    return rows


def get_session_user(session_id: str):
    if not session_id:
        return None
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    now = int(time.time())
    c.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now,))
    c.execute(
        """
        SELECT u.*
        FROM user_sessions s
        JOIN users u ON u.email = s.user_email
        WHERE s.session_id=? AND s.expires_at > ?
        """,
        (session_id, now),
    )
    user = c.fetchone()
    if user:
        c.execute("UPDATE user_sessions SET last_seen_at=? WHERE session_id=?", (now, session_id))
        conn.commit()
    conn.close()
    if not user:
        return None
    payload = dict(user)
    payload.pop("password", None)
    payload["allowed_legal_entities"] = _json_loads_safe(payload.get("allowed_legal_entities"), [])
    payload["allowed_business_units"] = _json_loads_safe(payload.get("allowed_business_units"), [])
    payload["two_factor_enabled"] = int(payload.get("two_factor_enabled") or 0)
    return payload


def delete_user_session(session_id: str):
    if not session_id:
        return
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM user_sessions WHERE session_id=?", (session_id,))
    conn.commit()
    conn.close()


def revoke_user_session(session_id: str, user_email: str = ""):
    if not session_id:
        return 0
    conn = get_connection()
    c = conn.cursor()
    if user_email:
        c.execute("DELETE FROM user_sessions WHERE session_id=? AND user_email=?", (session_id, user_email))
    else:
        c.execute("DELETE FROM user_sessions WHERE session_id=?", (session_id,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def delete_user_sessions_for_email(user_email: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM user_sessions WHERE user_email=?", (user_email,))
    conn.commit()
    conn.close()


def get_field_access_rules(role: str = "", module: str = "", entity_type: str = "", is_active: int = 1):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    clauses = []
    params = []
    if role:
        clauses.append("role_name=?")
        params.append(role)
    if module:
        clauses.append("module_name=?")
        params.append(module)
    if entity_type:
        clauses.append("entity_type=?")
        params.append(entity_type)
    if is_active in (0, 1):
        clauses.append("is_active=?")
        params.append(int(is_active))
    sql = "SELECT * FROM field_access_rules"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY role_name ASC, module_name ASC, entity_type ASC, field_name ASC, id ASC"
    c.execute(sql, tuple(params))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["allowed_statuses"] = _json_loads_safe(row.get("allowed_statuses"), [])
    return rows


def save_field_access_rule(
    role_name: str,
    module_name: str,
    entity_type: str,
    field_name: str,
    can_view: int = 1,
    can_edit: int = 1,
    allowed_statuses: list | None = None,
    actor_email: str = "",
    is_active: int = 1,
):
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        INSERT INTO field_access_rules (
            role_name, module_name, entity_type, field_name, can_view, can_edit,
            allowed_statuses, is_active, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            role_name,
            module_name,
            entity_type,
            field_name,
            int(can_view),
            int(can_edit),
            _json_dumps(allowed_statuses or []),
            int(is_active),
            actor_email,
            now,
            now,
        ),
    )
    rule_id = c.lastrowid
    conn.commit()
    conn.close()
    return rule_id


def delete_field_access_rule(rule_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM field_access_rules WHERE id=?", (int(rule_id),))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def get_entity_lock(entity_type: str, entity_id: str, ttl_seconds: int = 900):
    now = int(time.time())
    ttl_seconds = get_lock_ttl_seconds(entity_type, ttl_seconds)
    stale_before = now - ttl_seconds
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("DELETE FROM entity_edit_locks WHERE locked_at < ?", (stale_before,))
    c.execute(
        """
        SELECT *
        FROM entity_edit_locks
        WHERE entity_type=? AND entity_id=?
        ORDER BY locked_at DESC, id DESC
        LIMIT 1
        """,
        (entity_type, str(entity_id)),
    )
    row = c.fetchone()
    conn.commit()
    conn.close()
    if not row:
        return None
    payload = dict(row)
    payload["ttl_seconds"] = ttl_seconds
    payload["stale_after"] = payload.get("locked_at", 0) + ttl_seconds
    payload["is_stale"] = int(payload.get("locked_at", 0) < stale_before)
    return payload


def list_entity_locks(limit: int = 120, entity_type: str = ""):
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    if entity_type:
        c.execute(
            "SELECT * FROM entity_edit_locks WHERE entity_type=? ORDER BY locked_at DESC, id DESC LIMIT ?",
            (entity_type, max(1, min(limit, 300))),
        )
    else:
        c.execute(
            "SELECT * FROM entity_edit_locks ORDER BY locked_at DESC, id DESC LIMIT ?",
            (max(1, min(limit, 300)),),
        )
    rows = [dict(row) for row in c.fetchall()]
    conn.commit()
    conn.close()
    for row in rows:
        ttl_seconds = get_lock_ttl_seconds(row.get("entity_type", ""), 900)
        row["ttl_seconds"] = ttl_seconds
        row["stale_after"] = _safe_int(row.get("locked_at")) + ttl_seconds
        row["is_stale"] = int(_safe_int(row.get("locked_at")) < (now - ttl_seconds))
    return rows


def acquire_entity_lock(
    entity_type: str,
    entity_id: str,
    actor_email: str,
    actor_name: str = "",
    session_id: str = "",
    force: int = 0,
    ttl_seconds: int = 900,
):
    now = int(time.time())
    ttl_seconds = get_lock_ttl_seconds(entity_type, ttl_seconds)
    stale_before = now - ttl_seconds
    with db_transaction(row_factory=True, mode="immediate") as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM entity_edit_locks WHERE entity_type=? AND locked_at < ?",
            (entity_type, stale_before),
        )
        c.execute(
            "SELECT * FROM entity_edit_locks WHERE entity_type=? AND entity_id=? ORDER BY locked_at DESC, id DESC LIMIT 1",
            (entity_type, str(entity_id)),
        )
        existing = c.fetchone()
        if existing:
            existing = dict(existing)
            if force or existing.get("actor_email") == actor_email or (session_id and existing.get("session_id") == session_id):
                c.execute(
                    """
                    UPDATE entity_edit_locks
                    SET actor_email=?, actor_name=?, session_id=?, locked_at=?
                    WHERE id=?
                    """,
                    (actor_email, actor_name, session_id, now, existing["id"]),
                )
                existing.update({"actor_email": actor_email, "actor_name": actor_name, "session_id": session_id, "locked_at": now})
                existing["ttl_seconds"] = ttl_seconds
                existing["stale_after"] = now + ttl_seconds
                existing["is_stale"] = 0
                return {"status": "success", "lock": existing, "replaced": 1}
            existing["ttl_seconds"] = ttl_seconds
            existing["stale_after"] = _safe_int(existing.get("locked_at")) + ttl_seconds
            existing["is_stale"] = int(_safe_int(existing.get("locked_at")) < stale_before)
            return {"error": "locked", "lock": existing}
        c.execute(
            """
            INSERT INTO entity_edit_locks (entity_type, entity_id, actor_email, actor_name, session_id, locked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entity_type, str(entity_id), actor_email, actor_name, session_id, now),
        )
        lock_id = c.lastrowid
    return {
        "status": "success",
        "lock": {
            "id": lock_id,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "actor_email": actor_email,
            "actor_name": actor_name,
            "session_id": session_id,
            "locked_at": now,
            "ttl_seconds": ttl_seconds,
            "stale_after": now + ttl_seconds,
            "is_stale": 0,
        },
        "replaced": 0,
    }


def release_entity_lock(entity_type: str, entity_id: str, actor_email: str = "", session_id: str = "", force: int = 0):
    conn = get_connection()
    c = conn.cursor()
    if force:
        c.execute("DELETE FROM entity_edit_locks WHERE entity_type=? AND entity_id=?", (entity_type, str(entity_id)))
    elif actor_email and session_id:
        c.execute(
            """
            DELETE FROM entity_edit_locks
            WHERE entity_type=? AND entity_id=? AND (actor_email=? OR session_id=?)
            """,
            (entity_type, str(entity_id), actor_email, session_id),
        )
    elif actor_email:
        c.execute(
            "DELETE FROM entity_edit_locks WHERE entity_type=? AND entity_id=? AND actor_email=?",
            (entity_type, str(entity_id), actor_email),
        )
    else:
        c.execute("DELETE FROM entity_edit_locks WHERE entity_type=? AND entity_id=?", (entity_type, str(entity_id)))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def create_erp_process_run(
    title: str,
    project_id: int = 0,
    client_id: int = 0,
    contract_id: int = 0,
    object_id: int = 0,
    request_type: str = "purchase",
    scenario: list | None = None,
    due_date: str = "",
    amount: float = 0,
    currency: str = "RUB",
    status: str = "new",
    current_stage: str = "request",
    created_by: str = "",
    payload: dict | None = None,
):
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        INSERT INTO erp_process_runs (
            title, project_id, client_id, contract_id, object_id, request_type, scenario, due_date, amount, currency,
            status, current_stage, request_id, approval_id, reservation_id, purchase_id,
            production_id, sales_doc_id, payment_id, created_by, updated_by, payload,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, 0, ?, ?, ?, ?, ?)
        """,
        (
            title,
            project_id,
            client_id,
            contract_id,
            object_id,
            request_type,
            _json_dumps(scenario or []),
            due_date,
            amount,
            currency,
            status,
            current_stage,
            created_by,
            created_by,
            _json_dumps(payload or {}),
            now,
            now,
        ),
    )
    process_id = c.lastrowid
    conn.commit()
    conn.close()
    return process_id


def update_erp_process_run(process_id: int, updates: dict, actor_email: str = ""):
    if not updates:
        return None
    allowed = {
        "title", "project_id", "client_id", "contract_id", "object_id", "request_type", "scenario", "due_date", "amount",
        "currency", "status", "current_stage", "request_id", "approval_id", "reservation_id",
        "purchase_id", "production_id", "sales_doc_id", "payment_id", "payload"
    }
    assignments = []
    values = []
    for key, value in updates.items():
        if key not in allowed:
            continue
        if key in {"scenario", "payload"}:
            value = _json_dumps(value or ([] if key == "scenario" else {}))
        assignments.append(f"{key}=?")
        values.append(value)
    if not assignments:
        return None
    assignments.append("updated_by=?")
    assignments.append("updated_at=?")
    values.extend([actor_email, int(time.time()), process_id])
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"UPDATE erp_process_runs SET {', '.join(assignments)} WHERE id=?", tuple(values))
    conn.commit()
    conn.close()
    return get_erp_process_run(process_id)


def get_erp_process_run(process_id: int):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM erp_process_runs WHERE id=?", (process_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    payload = dict(row)
    for field, default in (("scenario", []), ("payload", {})):
        try:
            payload[field] = json.loads(payload.get(field) or _json_dumps(default))
        except Exception:
            payload[field] = default
    return payload


def list_erp_process_runs(project_id: int = 0, client_id: int = 0, status: str = "", limit: int = 200):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    clauses = ["1=1"]
    params = []
    if project_id:
        clauses.append("project_id=?")
        params.append(project_id)
    if client_id:
        clauses.append("client_id=?")
        params.append(client_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    params.append(max(1, min(limit, 500)))
    c.execute(
        f"""
        SELECT *
        FROM erp_process_runs
        WHERE {' AND '.join(clauses)}
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        tuple(params),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        try:
            row["scenario"] = json.loads(row.get("scenario") or "[]")
        except Exception:
            row["scenario"] = []
        try:
            row["payload"] = json.loads(row.get("payload") or "{}")
        except Exception:
            row["payload"] = {}
    return rows


def link_erp_entities(
    process_id: int,
    source_type: str,
    source_id: int | str,
    target_type: str,
    target_id: int | str,
    relation_type: str = "related",
    project_id: int = 0,
    client_id: int = 0,
    created_by: str = "",
    details: dict | None = None,
):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO erp_entity_links (
            process_id, source_type, source_id, target_type, target_id, relation_type,
            project_id, client_id, created_by, details, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            process_id,
            source_type,
            str(source_id),
            target_type,
            str(target_id),
            relation_type,
            project_id,
            client_id,
            created_by,
            _json_dumps(details or {}),
            int(time.time()),
        ),
    )
    link_id = c.lastrowid
    conn.commit()
    conn.close()
    return link_id


def list_erp_links(process_id: int):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        "SELECT * FROM erp_entity_links WHERE process_id=? ORDER BY created_at ASC, id ASC",
        (process_id,),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        try:
            row["details"] = json.loads(row.get("details") or "{}")
        except Exception:
            row["details"] = {}
    return rows


def list_erp_process_audit(process_id: int, limit: int = 120):
    process = get_erp_process_run(process_id)
    if not process:
        return []
    refs = [("erp_process", str(process_id))]
    for entity_key, entity_type in (
        ("request_id", "internal_request"),
        ("approval_id", "approval"),
        ("reservation_id", "stock_reservation"),
        ("purchase_id", "purchase"),
        ("production_id", "production_order"),
        ("sales_doc_id", "sales_document"),
        ("payment_id", "finance_payment"),
    ):
        value = process.get(entity_key)
        if value:
            refs.append((entity_type, str(value)))
    where_parts = []
    params = []
    for entity_type, entity_id in refs:
        where_parts.append("(entity_type=? AND entity_id=?)")
        params.extend([entity_type, entity_id])
    params.append(max(1, min(limit, 300)))
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        f"""
        SELECT *
        FROM audit_log
        WHERE {' OR '.join(where_parts)}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        tuple(params),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        try:
            row["details"] = json.loads(row.get("details") or "{}")
        except Exception:
            row["details"] = {}
    return rows

def _init_db_once():
    conn = get_connection()
    if is_postgres_backend():
        conn._inner.autocommit = True
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (email TEXT PRIMARY KEY, password TEXT, name TEXT, role TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, name TEXT, contract TEXT, client TEXT, manager TEXT, status TEXT, progress INTEGER, checkedState TEXT, comments TEXT, deadlines TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, inn TEXT, kpp TEXT DEFAULT '', ogrn TEXT DEFAULT '', legal_address TEXT DEFAULT '', contact TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS meetings (id INTEGER PRIMARY KEY, title TEXT, m_date TEXT, m_time TEXT, participants TEXT, agenda TEXT, decisions TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS calendar_events (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', event_date TEXT DEFAULT '', start_time TEXT DEFAULT '', end_time TEXT DEFAULT '', scope TEXT DEFAULT 'personal', owner_email TEXT DEFAULT '', owner_name TEXT DEFAULT '', department TEXT DEFAULT '', project_id INTEGER DEFAULT 0, meeting_id INTEGER DEFAULT 0, status TEXT DEFAULT 'planned', location TEXT DEFAULT '', description TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS crm_leads (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', client_name TEXT DEFAULT '', contact_name TEXT DEFAULT '', contact_email TEXT DEFAULT '', contact_phone TEXT DEFAULT '', source TEXT DEFAULT '', stage TEXT DEFAULT 'new', probability REAL DEFAULT 0, budget REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', responsible TEXT DEFAULT '', next_action TEXT DEFAULT '', next_action_date TEXT DEFAULT '', priority TEXT DEFAULT 'normal', tags_json TEXT DEFAULT '[]', comment TEXT DEFAULT '', linked_client_id INTEGER DEFAULT 0, linked_project_id INTEGER DEFAULT 0, linked_deal_id INTEGER DEFAULT 0, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS crm_deals (id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER DEFAULT 0, title TEXT DEFAULT '', client_id INTEGER DEFAULT 0, client_name TEXT DEFAULT '', contract_number TEXT DEFAULT '', stage TEXT DEFAULT 'qualification', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', margin_percent REAL DEFAULT 0, probability REAL DEFAULT 0, responsible TEXT DEFAULT '', next_action TEXT DEFAULT '', next_action_date TEXT DEFAULT '', expected_close_date TEXT DEFAULT '', priority TEXT DEFAULT 'normal', status_color TEXT DEFAULT '', tags_json TEXT DEFAULT '[]', comment TEXT DEFAULT '', project_id INTEGER DEFAULT 0, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS crm_activities (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT DEFAULT 'lead', entity_id INTEGER DEFAULT 0, activity_type TEXT DEFAULT 'note', subject TEXT DEFAULT '', summary TEXT DEFAULT '', due_date TEXT DEFAULT '', status TEXT DEFAULT 'open', owner_name TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS outreach_prospects (id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT DEFAULT '', company_inn TEXT DEFAULT '', contact_name TEXT DEFAULT '', position TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '', website TEXT DEFAULT '', city TEXT DEFAULT '', contact_method TEXT DEFAULT '', source_name TEXT DEFAULT '', source_file TEXT DEFAULT '', status TEXT DEFAULT 'new', priority TEXT DEFAULT 'normal', manager_name TEXT DEFAULT '', manager_email TEXT DEFAULT '', planned_contact_date TEXT DEFAULT '', next_action TEXT DEFAULT '', next_action_date TEXT DEFAULT '', last_contact_at TEXT DEFAULT '', last_channel TEXT DEFAULT '', last_result TEXT DEFAULT '', attempts_count INTEGER DEFAULT 0, is_processed INTEGER DEFAULT 0, do_not_contact INTEGER DEFAULT 0, converted_client_id INTEGER DEFAULT 0, converted_lead_id INTEGER DEFAULT 0, tags_json TEXT DEFAULT '[]', notes TEXT DEFAULT '', extra_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS outreach_activities (id INTEGER PRIMARY KEY AUTOINCREMENT, prospect_id INTEGER DEFAULT 0, activity_type TEXT DEFAULT 'call', result_status TEXT DEFAULT '', summary TEXT DEFAULT '', next_action TEXT DEFAULT '', next_action_date TEXT DEFAULT '', channel TEXT DEFAULT '', manager_name TEXT DEFAULT '', manager_email TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS outreach_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, report_date TEXT DEFAULT '', manager_name TEXT DEFAULT '', manager_email TEXT DEFAULT '', plan_total INTEGER DEFAULT 0, processed_total INTEGER DEFAULT 0, calls_total INTEGER DEFAULT 0, emails_total INTEGER DEFAULT 0, meetings_total INTEGER DEFAULT 0, converted_total INTEGER DEFAULT 0, summary TEXT DEFAULT '', blockers TEXT DEFAULT '', next_day_focus TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(report_date, manager_email))''')
    c.execute('''CREATE TABLE IF NOT EXISTS outreach_import_batches (id INTEGER PRIMARY KEY AUTOINCREMENT, source_filename TEXT DEFAULT '', source_name TEXT DEFAULT '', rows_total INTEGER DEFAULT 0, created_total INTEGER DEFAULT 0, updated_total INTEGER DEFAULT 0, skipped_total INTEGER DEFAULT 0, default_manager_name TEXT DEFAULT '', actor_email TEXT DEFAULT '', actor_name TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS global_chats (id INTEGER PRIMARY KEY, name TEXT, type TEXT, creator TEXT, participants TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS global_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, "user" TEXT, role TEXT, text TEXT, time TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, type TEXT, number TEXT, d_date TEXT, correspondent TEXT, sender_name TEXT DEFAULT '', recipient_name TEXT DEFAULT '', source_number TEXT DEFAULT '', source_date TEXT DEFAULT '', delivery_method TEXT DEFAULT '', signer_name TEXT DEFAULT '', executor_name TEXT DEFAULT '', subject TEXT, status TEXT, file_url TEXT, qr_code TEXT, resolution TEXT DEFAULT '', resolution_author TEXT DEFAULT '', resolution_deadline TEXT DEFAULT '', resolution_assignee TEXT DEFAULT '', resolution_task_id INTEGER DEFAULT 0, registration_number TEXT DEFAULT '', registration_journal_id INTEGER DEFAULT 0, classifier_id INTEGER DEFAULT 0, case_file_id INTEGER DEFAULT 0, lifecycle_state TEXT DEFAULT 'draft', legal_significance TEXT DEFAULT 'standard', confidentiality_level TEXT DEFAULT 'internal', retention_until TEXT DEFAULT '', registered_at INTEGER DEFAULT 0, registered_by TEXT DEFAULT '', document_kind_code TEXT DEFAULT '', case_index TEXT DEFAULT '', workflow_stage TEXT DEFAULT '', workflow_status TEXT DEFAULT '', workflow_started_at INTEGER DEFAULT 0, workflow_completed_at INTEGER DEFAULT 0, approval_id INTEGER DEFAULT 0, workflow_block_reason TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, title TEXT, description TEXT, author TEXT, executor TEXT, deadline TEXT, status TEXT, created_at TEXT, recurrence TEXT DEFAULT 'none', priority TEXT DEFAULT 'normal', project_id INTEGER DEFAULT 0, history TEXT DEFAULT '[]', chat TEXT DEFAULT '[]', updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS company_feed_posts (id INTEGER PRIMARY KEY, author_name TEXT DEFAULT '', author_role TEXT DEFAULT '', post_type TEXT DEFAULT 'announcement', title TEXT DEFAULT '', content TEXT DEFAULT '', poll_options TEXT DEFAULT '[]', target_roles TEXT DEFAULT '[]', is_pinned INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS company_feed_comments (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER DEFAULT 0, user_name TEXT DEFAULT '', user_role TEXT DEFAULT '', comment_text TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS company_feed_reactions (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER DEFAULT 0, user_email TEXT DEFAULT '', user_name TEXT DEFAULT '', reaction_key TEXT DEFAULT 'like', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS company_feed_votes (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER DEFAULT 0, user_email TEXT DEFAULT '', user_name TEXT DEFAULT '', option_key TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS company_feed_reads (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER DEFAULT 0, user_email TEXT DEFAULT '', read_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS knowledge_base (id INTEGER PRIMARY KEY, title TEXT, content TEXT, file_url TEXT, author TEXT, created_at TEXT, required_roles TEXT, read_by TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS approvals (id INTEGER PRIMARY KEY, title TEXT, item_link TEXT, route TEXT, current_step INTEGER, status TEXT, history TEXT, author TEXT, created_at TEXT, entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', route_rules TEXT DEFAULT '[]', route_context TEXT DEFAULT '{}', current_stage_key TEXT DEFAULT '', current_assignees TEXT DEFAULT '[]', approval_state TEXT DEFAULT '{}', due_at INTEGER DEFAULT 0, completed_at INTEGER DEFAULT 0, required_comment_on_reject INTEGER DEFAULT 0, required_comment_on_return INTEGER DEFAULT 0, last_action_at INTEGER DEFAULT 0, escalation_role TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS auth_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, identifier TEXT, success INTEGER DEFAULT 0, created_at INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, actor_email TEXT, actor_name TEXT, entity_type TEXT, entity_id TEXT, details TEXT, ip_address TEXT, user_agent TEXT, created_at INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS field_change_log (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', field_name TEXT DEFAULT '', old_value TEXT DEFAULT '', new_value TEXT DEFAULT '', actor_email TEXT DEFAULT '', actor_name TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_sessions (session_id TEXT PRIMARY KEY, user_email TEXT, ip_address TEXT, user_agent TEXT, created_at INTEGER, expires_at INTEGER, last_seen_at INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS field_access_rules (id INTEGER PRIMARY KEY AUTOINCREMENT, role_name TEXT DEFAULT '', module_name TEXT DEFAULT '', entity_type TEXT DEFAULT '', field_name TEXT DEFAULT '', can_view INTEGER DEFAULT 1, can_edit INTEGER DEFAULT 1, allowed_statuses TEXT DEFAULT '[]', is_active INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS entity_edit_locks (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', actor_email TEXT DEFAULT '', actor_name TEXT DEFAULT '', session_id TEXT DEFAULT '', locked_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, message TEXT, user_email TEXT DEFAULT '', user_name TEXT DEFAULT '', category TEXT DEFAULT 'system', entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', is_read INTEGER DEFAULT 0, created_at INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS entity_watchers (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT DEFAULT '', user_name TEXT DEFAULT '', entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', title TEXT DEFAULT '', meta TEXT DEFAULT '', view_name TEXT DEFAULT '', condition_key TEXT DEFAULT 'any_change', digest_mode TEXT DEFAULT 'instant', event_types_json TEXT DEFAULT '[]', is_active INTEGER DEFAULT 1, last_event_key TEXT DEFAULT '', last_event_value TEXT DEFAULT '', last_notified_at INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(user_email, entity_type, entity_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS error_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, message TEXT, path TEXT, method TEXT, actor_email TEXT, severity TEXT DEFAULT 'error', traceback_text TEXT DEFAULT '', created_at INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS system_backups (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, file_path TEXT, actor_email TEXT DEFAULT '', file_size INTEGER DEFAULT 0, created_at INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS background_job_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_name TEXT DEFAULT '', job_group TEXT DEFAULT 'system', status TEXT DEFAULT 'running', started_at INTEGER DEFAULT 0, heartbeat_at INTEGER DEFAULT 0, finished_at INTEGER DEFAULT 0, details TEXT DEFAULT '{}')''')
    c.execute('''CREATE TABLE IF NOT EXISTS recovery_workflow_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, action_name TEXT DEFAULT '', actor_email TEXT DEFAULT '', target_scope TEXT DEFAULT '', status TEXT DEFAULT 'running', started_at INTEGER DEFAULT 0, finished_at INTEGER DEFAULT 0, details TEXT DEFAULT '{}')''')
    c.execute('''CREATE TABLE IF NOT EXISTS finance_payments (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, title TEXT DEFAULT '', kind TEXT DEFAULT 'incoming', category TEXT DEFAULT 'payment', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', due_date TEXT DEFAULT '', paid_date TEXT DEFAULT '', status TEXT DEFAULT 'planned', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS legal_entities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', short_name TEXT DEFAULT '', inn TEXT DEFAULT '', kpp TEXT DEFAULT '', ogrn TEXT DEFAULT '', vat_mode TEXT DEFAULT 'osno', default_currency TEXT DEFAULT 'RUB', is_active INTEGER DEFAULT 1, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS business_units (id INTEGER PRIMARY KEY AUTOINCREMENT, legal_entity_id INTEGER DEFAULT 0, name TEXT DEFAULT '', code TEXT DEFAULT '', manager_name TEXT DEFAULT '', is_active INTEGER DEFAULT 1, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS treasury_articles (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', code TEXT DEFAULT '', flow_kind TEXT DEFAULT 'incoming', category TEXT DEFAULT '', is_active INTEGER DEFAULT 1, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS vat_rates (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', rate REAL DEFAULT 0, is_default INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS account_chart (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT DEFAULT '', name TEXT DEFAULT '', account_type TEXT DEFAULT 'active', kind TEXT DEFAULT 'balance', parent_code TEXT DEFAULT '', is_system INTEGER DEFAULT 1, is_active INTEGER DEFAULT 1, UNIQUE(code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounting_periods (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', status TEXT DEFAULT 'open', opened_at INTEGER DEFAULT 0, closed_at INTEGER DEFAULT 0, closed_by TEXT DEFAULT '', comment TEXT DEFAULT '', UNIQUE(period_key))''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounting_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT DEFAULT '', source_id INTEGER DEFAULT 0, entry_date TEXT DEFAULT '', period_key TEXT DEFAULT '', legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, object_id INTEGER DEFAULT 0, treasury_article_id INTEGER DEFAULT 0, vat_rate_id INTEGER DEFAULT 0, account_debit TEXT DEFAULT '', account_credit TEXT DEFAULT '', amount REAL DEFAULT 0, vat_amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', description TEXT DEFAULT '', posted_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounting_period_close_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', status TEXT DEFAULT 'draft', entries_total INTEGER DEFAULT 0, checks_passed INTEGER DEFAULT 0, mismatches_count INTEGER DEFAULT 0, tax_amount REAL DEFAULT 0, report_count INTEGER DEFAULT 0, summary_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, closed_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounting_tax_accruals (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', tax_type TEXT DEFAULT '', tax_name TEXT DEFAULT '', tax_base REAL DEFAULT 0, tax_rate REAL DEFAULT 0, amount REAL DEFAULT 0, account_debit TEXT DEFAULT '', account_credit TEXT DEFAULT '', status TEXT DEFAULT 'draft', details_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounting_reporting_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', report_type TEXT DEFAULT '', report_name TEXT DEFAULT '', status TEXT DEFAULT 'actual', report_payload TEXT DEFAULT '{}', amount_total REAL DEFAULT 0, line_count INTEGER DEFAULT 0, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "accounting_edo_operators"):
        c.execute('''CREATE TABLE IF NOT EXISTS accounting_edo_operators (id BIGINT PRIMARY KEY, operator_name TEXT DEFAULT '', provider_name TEXT DEFAULT '1С-ЭДО', contour_type TEXT DEFAULT 'reporting', api_endpoint TEXT DEFAULT '', account_login TEXT DEFAULT '', credential_ref TEXT DEFAULT '', legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, status TEXT DEFAULT 'active', capabilities_json TEXT DEFAULT '[]', retry_policy_json TEXT DEFAULT '{}', idempotency_namespace TEXT DEFAULT '', last_sync_at INTEGER DEFAULT 0, last_error TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "accounting_external_submissions"):
        c.execute('''CREATE TABLE IF NOT EXISTS accounting_external_submissions (id BIGINT PRIMARY KEY, operator_id INTEGER DEFAULT 0, contour_type TEXT DEFAULT 'reporting', report_type TEXT DEFAULT '', period_key TEXT DEFAULT '', legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, payload_json TEXT DEFAULT '{}', checksum TEXT DEFAULT '', idempotency_key TEXT DEFAULT '', submission_status TEXT DEFAULT 'draft', exchange_direction TEXT DEFAULT 'outbound', external_submission_id TEXT DEFAULT '', protocol_number TEXT DEFAULT '', receipt_number TEXT DEFAULT '', retry_count INTEGER DEFAULT 0, next_retry_at INTEGER DEFAULT 0, submitted_at INTEGER DEFAULT 0, accepted_at INTEGER DEFAULT 0, last_error TEXT DEFAULT '', response_json TEXT DEFAULT '{}', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "accounting_external_submission_events"):
        c.execute('''CREATE TABLE IF NOT EXISTS accounting_external_submission_events (id BIGINT PRIMARY KEY, submission_id INTEGER DEFAULT 0, event_type TEXT DEFAULT '', status TEXT DEFAULT '', message TEXT DEFAULT '', payload_json TEXT DEFAULT '{}', actor_email TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounting_register_reconciliations (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', register_name TEXT DEFAULT '', status TEXT DEFAULT 'ok', mismatch_count INTEGER DEFAULT 0, summary_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounting_registers (id INTEGER PRIMARY KEY AUTOINCREMENT, register_kind TEXT DEFAULT 'accounting', period_key TEXT DEFAULT '', source_type TEXT DEFAULT '', source_id INTEGER DEFAULT 0, entry_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, object_id INTEGER DEFAULT 0, account_code TEXT DEFAULT '', balance_side TEXT DEFAULT '', debit_amount REAL DEFAULT 0, credit_amount REAL DEFAULT 0, amount REAL DEFAULT 0, quantity REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', dimension_json TEXT DEFAULT '{}', posted_at INTEGER DEFAULT 0, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tax_registers (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', tax_type TEXT DEFAULT '', source_type TEXT DEFAULT '', source_id INTEGER DEFAULT 0, entry_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, tax_base REAL DEFAULT 0, tax_rate REAL DEFAULT 0, tax_amount REAL DEFAULT 0, account_code TEXT DEFAULT '', status TEXT DEFAULT 'recognized', dimension_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS vat_purchase_book (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', source_type TEXT DEFAULT '', source_id INTEGER DEFAULT 0, entry_id INTEGER DEFAULT 0, document_number TEXT DEFAULT '', document_date TEXT DEFAULT '', counterparty_id INTEGER DEFAULT 0, counterparty_name TEXT DEFAULT '', amount_total REAL DEFAULT 0, vat_amount REAL DEFAULT 0, vat_rate REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', status TEXT DEFAULT 'draft', dimension_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS vat_sales_book (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', source_type TEXT DEFAULT '', source_id INTEGER DEFAULT 0, entry_id INTEGER DEFAULT 0, document_number TEXT DEFAULT '', document_date TEXT DEFAULT '', counterparty_id INTEGER DEFAULT 0, counterparty_name TEXT DEFAULT '', amount_total REAL DEFAULT 0, vat_amount REAL DEFAULT 0, vat_rate REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', status TEXT DEFAULT 'draft', dimension_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS currency_revaluation_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', currency TEXT DEFAULT '', legal_entity_id INTEGER DEFAULT 0, amount_currency REAL DEFAULT 0, rate_before REAL DEFAULT 0, rate_after REAL DEFAULT 0, amount_before REAL DEFAULT 0, amount_after REAL DEFAULT 0, exchange_difference REAL DEFAULT 0, status TEXT DEFAULT 'draft', details_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, posted_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS fixed_assets (id INTEGER PRIMARY KEY AUTOINCREMENT, asset_number TEXT DEFAULT '', asset_name TEXT DEFAULT '', asset_kind TEXT DEFAULT 'fixed_asset', legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, project_id INTEGER DEFAULT 0, acquisition_date TEXT DEFAULT '', commissioning_date TEXT DEFAULT '', initial_cost REAL DEFAULT 0, accumulated_depreciation REAL DEFAULT 0, residual_value REAL DEFAULT 0, useful_life_months INTEGER DEFAULT 0, depreciation_account TEXT DEFAULT '02', cost_account TEXT DEFAULT '01', expense_account TEXT DEFAULT '20', status TEXT DEFAULT 'draft', source_type TEXT DEFAULT '', source_id INTEGER DEFAULT 0, details_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(asset_number))''')
    c.execute('''CREATE TABLE IF NOT EXISTS treasury_limits (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, treasury_article_id INTEGER DEFAULT 0, amount_limit REAL DEFAULT 0, status TEXT DEFAULT 'active', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(period_key, legal_entity_id, business_unit_id, treasury_article_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS reconciliation_acts (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, period_key TEXT DEFAULT '', act_number TEXT DEFAULT '', amount_receivable REAL DEFAULT 0, amount_payable REAL DEFAULT 0, details TEXT DEFAULT '{}', status TEXT DEFAULT 'draft', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_sync_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, system_name TEXT DEFAULT '1C', entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, direction TEXT DEFAULT 'outbound', payload TEXT DEFAULT '{}', mapping_key TEXT DEFAULT '', state TEXT DEFAULT 'queued', retry_count INTEGER DEFAULT 0, last_error TEXT DEFAULT '', external_id TEXT DEFAULT '', next_retry_at INTEGER DEFAULT 0, locked_at INTEGER DEFAULT 0, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, idempotency_key TEXT DEFAULT '', correlation_id TEXT DEFAULT '', attempt_limit INTEGER DEFAULT 5, priority INTEGER DEFAULT 100, last_attempt_at INTEGER DEFAULT 0, processed_at INTEGER DEFAULT 0, checksum TEXT DEFAULT '', consistency_state TEXT DEFAULT 'pending', connector_id INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_sync_log (id INTEGER PRIMARY KEY AUTOINCREMENT, queue_id INTEGER DEFAULT 0, system_name TEXT DEFAULT '1C', entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, state TEXT DEFAULT '', message TEXT DEFAULT '', payload TEXT DEFAULT '{}', external_id TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_field_mappings (id INTEGER PRIMARY KEY AUTOINCREMENT, system_name TEXT DEFAULT '1C', entity_type TEXT DEFAULT '', local_field TEXT DEFAULT '', external_field TEXT DEFAULT '', direction TEXT DEFAULT 'bidirectional', transform_rule TEXT DEFAULT '', is_required INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_reconciliation_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, system_name TEXT DEFAULT '1C', summary TEXT DEFAULT '{}', mismatch_count INTEGER DEFAULT 0, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_idempotency_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, system_name TEXT DEFAULT '1C', idempotency_key TEXT DEFAULT '', direction TEXT DEFAULT 'outbound', queue_id INTEGER DEFAULT 0, request_hash TEXT DEFAULT '', response_payload TEXT DEFAULT '{}', status TEXT DEFAULT 'received', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_error_events (id INTEGER PRIMARY KEY AUTOINCREMENT, queue_id INTEGER DEFAULT 0, system_name TEXT DEFAULT '1C', entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, severity TEXT DEFAULT 'error', error_code TEXT DEFAULT '', message TEXT DEFAULT '', traceback_text TEXT DEFAULT '', payload TEXT DEFAULT '{}', status TEXT DEFAULT 'open', resolved_at INTEGER DEFAULT 0, resolved_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_consistency_checks (id INTEGER PRIMARY KEY AUTOINCREMENT, queue_id INTEGER DEFAULT 0, system_name TEXT DEFAULT '1C', entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, external_id TEXT DEFAULT '', state TEXT DEFAULT 'consistent', checksum_local TEXT DEFAULT '', checksum_external TEXT DEFAULT '', details_json TEXT DEFAULT '{}', checked_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_connector_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, connector_id INTEGER DEFAULT 0, connector_type TEXT DEFAULT '', provider_name TEXT DEFAULT '', run_kind TEXT DEFAULT 'sync', status TEXT DEFAULT 'running', processed INTEGER DEFAULT 0, success INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, details_json TEXT DEFAULT '{}', started_at INTEGER DEFAULT 0, finished_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_connector_credentials (id INTEGER PRIMARY KEY AUTOINCREMENT, connector_id INTEGER DEFAULT 0, credential_kind TEXT DEFAULT 'basic', username TEXT DEFAULT '', secret_value TEXT DEFAULT '', secret_ref TEXT DEFAULT '', is_active INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_external_objects (id INTEGER PRIMARY KEY AUTOINCREMENT, system_name TEXT DEFAULT '1C', connector_id INTEGER DEFAULT 0, entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', external_id TEXT DEFAULT '', external_type TEXT DEFAULT '', external_url TEXT DEFAULT '', exchange_state TEXT DEFAULT 'synced', checksum_local TEXT DEFAULT '', checksum_external TEXT DEFAULT '', last_message_id INTEGER DEFAULT 0, last_synced_at INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(system_name, entity_type, entity_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_exchange_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, connector_id INTEGER DEFAULT 0, queue_id INTEGER DEFAULT 0, system_name TEXT DEFAULT '1C', entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', direction TEXT DEFAULT 'outbound', transport TEXT DEFAULT 'demo', endpoint_url TEXT DEFAULT '', request_payload TEXT DEFAULT '{}', response_payload TEXT DEFAULT '{}', http_status INTEGER DEFAULT 0, status TEXT DEFAULT 'draft', error_message TEXT DEFAULT '', idempotency_key TEXT DEFAULT '', correlation_id TEXT DEFAULT '', attempt_no INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, completed_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS edo_signature_registry (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, signer_name TEXT DEFAULT '', signer_role TEXT DEFAULT '', certificate_thumbprint TEXT DEFAULT '', signature_provider TEXT DEFAULT '1С-ЭДО', signature_status TEXT DEFAULT 'signed', signed_at TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, certificate_id INTEGER DEFAULT 0, document_revision_id INTEGER DEFAULT 0, signature_kind TEXT DEFAULT 'КЭП', verification_status TEXT DEFAULT 'pending', verification_message TEXT DEFAULT '', stamp_json TEXT DEFAULT '{}', signed_hash TEXT DEFAULT '', verification_details TEXT DEFAULT '{}', revoked_at INTEGER DEFAULT 0, legal_force TEXT DEFAULT 'unsigned', signature_session_id INTEGER DEFAULT 0, validation_protocol_id INTEGER DEFAULT 0, detached_signature_url TEXT DEFAULT '', detached_signature_checksum TEXT DEFAULT '', signature_format TEXT DEFAULT 'CAdES detached', time_stamp_status TEXT DEFAULT '', ocsp_status TEXT DEFAULT '', crl_status TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS signature_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, file_revision_id INTEGER DEFAULT 0, revision_checksum TEXT DEFAULT '', certificate_id INTEGER DEFAULT 0, certificate_thumbprint TEXT DEFAULT '', signer_name TEXT DEFAULT '', signer_role TEXT DEFAULT '', signature_kind TEXT DEFAULT 'КЭП', signature_provider TEXT DEFAULT 'КриптоПро', signature_format TEXT DEFAULT 'CAdES detached', status TEXT DEFAULT 'created', detached_signature_filename TEXT DEFAULT '', detached_signature_url TEXT DEFAULT '', detached_signature_checksum TEXT DEFAULT '', verification_status TEXT DEFAULT 'pending', verification_message TEXT DEFAULT '', certificate_status TEXT DEFAULT '', ocsp_status TEXT DEFAULT '', crl_status TEXT DEFAULT '', time_stamp_status TEXT DEFAULT '', validation_protocol_id INTEGER DEFAULT 0, signature_registry_id INTEGER DEFAULT 0, signing_payload_json TEXT DEFAULT '{}', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, completed_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS signature_validation_protocols (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER DEFAULT 0, signature_id INTEGER DEFAULT 0, document_id INTEGER DEFAULT 0, file_revision_id INTEGER DEFAULT 0, revision_checksum TEXT DEFAULT '', protocol_status TEXT DEFAULT 'draft', protocol_number TEXT DEFAULT '', validation_result TEXT DEFAULT '', validation_message TEXT DEFAULT '', provider TEXT DEFAULT 'КриптоПро', checks_json TEXT DEFAULT '{}', raw_protocol_json TEXT DEFAULT '{}', attached_file_url TEXT DEFAULT '', attached_file_checksum TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchase_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, item_article TEXT DEFAULT '', item_name TEXT DEFAULT '', supplier TEXT DEFAULT '', qty REAL DEFAULT 0, unit TEXT DEFAULT 'шт', unit_price REAL DEFAULT 0, total_amount REAL DEFAULT 0, status TEXT DEFAULT 'planned', expected_date TEXT DEFAULT '', received_date TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales_documents_extended (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, doc_type TEXT DEFAULT 'invoice', doc_number TEXT DEFAULT '', doc_date TEXT DEFAULT '', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', status TEXT DEFAULT 'draft', payment_status TEXT DEFAULT 'planned', linked_payment_id INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, order_name TEXT DEFAULT '', stage TEXT DEFAULT 'queue', priority TEXT DEFAULT 'normal', planned_start TEXT DEFAULT '', planned_finish TEXT DEFAULT '', actual_finish TEXT DEFAULT '', progress INTEGER DEFAULT 0, responsible TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_operations (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER DEFAULT 0, sequence_no INTEGER DEFAULT 1, operation_name TEXT DEFAULT '', work_center TEXT DEFAULT '', status TEXT DEFAULT 'planned', planned_hours REAL DEFAULT 0, actual_hours REAL DEFAULT 0, planned_qty REAL DEFAULT 0, completed_qty REAL DEFAULT 0, scrap_qty REAL DEFAULT 0, labor_rate REAL DEFAULT 0, material_cost REAL DEFAULT 0, overhead_cost REAL DEFAULT 0, started_at TEXT DEFAULT '', finished_at TEXT DEFAULT '', note TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_bom_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER DEFAULT 0, article TEXT DEFAULT '', item_name TEXT DEFAULT '', unit TEXT DEFAULT 'шт', qty_per_unit REAL DEFAULT 0, planned_qty REAL DEFAULT 0, actual_qty REAL DEFAULT 0, unit_cost REAL DEFAULT 0, warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', note TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_route_templates (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER DEFAULT 0, sequence_no INTEGER DEFAULT 1, operation_name TEXT DEFAULT '', work_center TEXT DEFAULT '', planned_hours REAL DEFAULT 0, planned_qty REAL DEFAULT 0, labor_rate REAL DEFAULT 0, note TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "terminal_sessions"):
        c.execute('''CREATE TABLE IF NOT EXISTS terminal_sessions (id BIGINT PRIMARY KEY, terminal_code TEXT DEFAULT '', terminal_type TEXT DEFAULT 'warehouse', device_uid TEXT DEFAULT '', operator_name TEXT DEFAULT '', current_zone TEXT DEFAULT '', status TEXT DEFAULT 'active', last_seen_at INTEGER DEFAULT 0, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "terminal_scan_events"):
        c.execute('''CREATE TABLE IF NOT EXISTS terminal_scan_events (id BIGINT PRIMARY KEY, session_id INTEGER DEFAULT 0, terminal_type TEXT DEFAULT '', scan_kind TEXT DEFAULT '', scan_value TEXT DEFAULT '', entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, action_name TEXT DEFAULT '', result_status TEXT DEFAULT '', result_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "production_execution_events"):
        c.execute('''CREATE TABLE IF NOT EXISTS production_execution_events (id BIGINT PRIMARY KEY, order_id INTEGER DEFAULT 0, operation_id INTEGER DEFAULT 0, job_id INTEGER DEFAULT 0, event_type TEXT DEFAULT '', qty REAL DEFAULT 0, scrap_qty REAL DEFAULT 0, work_center TEXT DEFAULT '', executor_name TEXT DEFAULT '', payload_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS stock_reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, nomenclature_article TEXT DEFAULT '', nomenclature_name TEXT DEFAULT '', qty REAL DEFAULT 0, status TEXT DEFAULT 'reserved', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS expense_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, title TEXT DEFAULT '', request_type TEXT DEFAULT 'payment', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', approver_role TEXT DEFAULT 'Директор', approver_name TEXT DEFAULT '', due_date TEXT DEFAULT '', linked_payment_id INTEGER DEFAULT 0, status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', approved_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS internal_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, title TEXT DEFAULT '', request_type TEXT DEFAULT 'purchase', target_role TEXT DEFAULT '', assignee_name TEXT DEFAULT '', priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'new', deadline TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS resource_allocations (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, department TEXT DEFAULT '', resource_name TEXT DEFAULT '', role_name TEXT DEFAULT '', load_percent INTEGER DEFAULT 0, date_from TEXT DEFAULT '', date_to TEXT DEFAULT '', status TEXT DEFAULT 'planned', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS hr_leave_requests (id BIGINT PRIMARY KEY, user_email TEXT DEFAULT '', user_name TEXT DEFAULT '', leave_type TEXT DEFAULT 'vacation', date_from TEXT DEFAULT '', date_to TEXT DEFAULT '', deputy_name TEXT DEFAULT '', status TEXT DEFAULT 'pending', comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, approved_by TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS hr_timesheet_entries (id BIGINT PRIMARY KEY, user_email TEXT DEFAULT '', user_name TEXT DEFAULT '', entry_date TEXT DEFAULT '', project_id INTEGER DEFAULT 0, hours REAL DEFAULT 0, work_mode TEXT DEFAULT 'office', status TEXT DEFAULT 'submitted', comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, approved_by TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS hr_equipment_requests (id BIGINT PRIMARY KEY, user_email TEXT DEFAULT '', user_name TEXT DEFAULT '', category TEXT DEFAULT 'workplace', item_name TEXT DEFAULT '', qty INTEGER DEFAULT 1, needed_by TEXT DEFAULT '', justification TEXT DEFAULT '', status TEXT DEFAULT 'pending', comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, approved_by TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS hr_substitution_requests (id BIGINT PRIMARY KEY, user_email TEXT DEFAULT '', user_name TEXT DEFAULT '', substitute_name TEXT DEFAULT '', date_from TEXT DEFAULT '', date_to TEXT DEFAULT '', reason TEXT DEFAULT '', status TEXT DEFAULT 'pending', comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, approved_by TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS hr_business_trip_requests (id BIGINT PRIMARY KEY, user_email TEXT DEFAULT '', user_name TEXT DEFAULT '', destination TEXT DEFAULT '', date_from TEXT DEFAULT '', date_to TEXT DEFAULT '', purpose TEXT DEFAULT '', transport_mode TEXT DEFAULT '', estimated_cost REAL DEFAULT 0, status TEXT DEFAULT 'pending', comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, approved_by TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS service_cases (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, case_number TEXT DEFAULT '', title TEXT DEFAULT '', case_type TEXT DEFAULT 'warranty', status TEXT DEFAULT 'open', priority TEXT DEFAULT 'normal', defect TEXT DEFAULT '', warranty_until TEXT DEFAULT '', sla_deadline TEXT DEFAULT '', responsible TEXT DEFAULT '', resolution TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS project_budget_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, line_type TEXT DEFAULT 'cost', category TEXT DEFAULT '', plan_amount REAL DEFAULT 0, fact_amount REAL DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS stock_movements (id INTEGER PRIMARY KEY AUTOINCREMENT, article TEXT DEFAULT '', name TEXT DEFAULT '', qty REAL DEFAULT 0, movement_type TEXT DEFAULT 'add', from_warehouse TEXT DEFAULT '', from_bin TEXT DEFAULT '', to_warehouse TEXT DEFAULT '', to_bin TEXT DEFAULT '', comment TEXT DEFAULT '', actor_email TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory_balances (id INTEGER PRIMARY KEY AUTOINCREMENT, article TEXT DEFAULT '', warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', qty REAL DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(article, warehouse, bin_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory_lots (id INTEGER PRIMARY KEY AUTOINCREMENT, article TEXT DEFAULT '', warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', batch_code TEXT DEFAULT '', serial_no TEXT DEFAULT '', lot_expiration_date TEXT DEFAULT '', qty REAL DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(article, warehouse, bin_code, batch_code, serial_no))''')
    c.execute('''CREATE TABLE IF NOT EXISTS specification_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, label TEXT DEFAULT '', comment TEXT DEFAULT '', snapshot TEXT DEFAULT '[]', actor_email TEXT DEFAULT '', actor_name TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_tech_cards (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER DEFAULT 0, title TEXT DEFAULT '', work_center TEXT DEFAULT '', setup_minutes REAL DEFAULT 0, run_minutes REAL DEFAULT 0, instruction TEXT DEFAULT '', quality_points TEXT DEFAULT '', status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, shift_date TEXT DEFAULT '', shift_name TEXT DEFAULT '', work_center TEXT DEFAULT '', capacity_hours REAL DEFAULT 0, team_name TEXT DEFAULT '', supervisor_name TEXT DEFAULT '', status TEXT DEFAULT 'planned', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER DEFAULT 0, shift_id INTEGER DEFAULT 0, operation_id INTEGER DEFAULT 0, title TEXT DEFAULT '', work_center TEXT DEFAULT '', executor_name TEXT DEFAULT '', planned_qty REAL DEFAULT 0, completed_qty REAL DEFAULT 0, status TEXT DEFAULT 'queued', started_at TEXT DEFAULT '', finished_at TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_material_norms (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER DEFAULT 0, article TEXT DEFAULT '', item_name TEXT DEFAULT '', unit TEXT DEFAULT 'шт', norm_qty REAL DEFAULT 0, scrap_rate REAL DEFAULT 0, substitute_article TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_labor_norms (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER DEFAULT 0, operation_name TEXT DEFAULT '', work_center TEXT DEFAULT '', norm_hours REAL DEFAULT 0, rate_per_hour REAL DEFAULT 0, team_size INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_semifinished (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER DEFAULT 0, article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, stage_name TEXT DEFAULT '', warehouse TEXT DEFAULT '', status TEXT DEFAULT 'in_stock', unit_cost REAL DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_rework (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER DEFAULT 0, related_operation_id INTEGER DEFAULT 0, defect_name TEXT DEFAULT '', qty REAL DEFAULT 0, reason TEXT DEFAULT '', rework_route TEXT DEFAULT '', status TEXT DEFAULT 'open', extra_cost REAL DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_planning_scenarios (id INTEGER PRIMARY KEY AUTOINCREMENT, scenario_name TEXT DEFAULT '', planning_horizon_days INTEGER DEFAULT 30, demand_mode TEXT DEFAULT 'confirmed_orders', status TEXT DEFAULT 'draft', payload_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_mrp_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, scenario_id INTEGER DEFAULT 0, run_name TEXT DEFAULT '', horizon_start TEXT DEFAULT '', horizon_end TEXT DEFAULT '', status TEXT DEFAULT 'calculated', demand_total INTEGER DEFAULT 0, shortages_total INTEGER DEFAULT 0, overloaded_centers INTEGER DEFAULT 0, payload_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bom_master (id INTEGER PRIMARY KEY AUTOINCREMENT, item_article TEXT DEFAULT '', item_name TEXT DEFAULT '', bom_code TEXT DEFAULT '', bom_name TEXT DEFAULT '', status TEXT DEFAULT 'draft', default_version_id INTEGER DEFAULT 0, unit TEXT DEFAULT 'шт', output_qty REAL DEFAULT 1, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(bom_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS bom_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, bom_id INTEGER DEFAULT 0, version_no TEXT DEFAULT '1', status TEXT DEFAULT 'draft', valid_from TEXT DEFAULT '', valid_to TEXT DEFAULT '', output_qty REAL DEFAULT 1, components_json TEXT DEFAULT '[]', operations_json TEXT DEFAULT '[]', overhead_rules_json TEXT DEFAULT '{}', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(bom_id, version_no))''')
    c.execute('''CREATE TABLE IF NOT EXISTS work_centers (id INTEGER PRIMARY KEY AUTOINCREMENT, center_code TEXT DEFAULT '', center_name TEXT DEFAULT '', center_type TEXT DEFAULT 'production', legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, capacity_per_hour REAL DEFAULT 0, hourly_rate REAL DEFAULT 0, overhead_rate REAL DEFAULT 0, calendar_code TEXT DEFAULT '', status TEXT DEFAULT 'active', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(center_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS work_center_calendars (id INTEGER PRIMARY KEY AUTOINCREMENT, work_center_id INTEGER DEFAULT 0, calendar_date TEXT DEFAULT '', shift_code TEXT DEFAULT 'day', available_hours REAL DEFAULT 0, capacity_qty REAL DEFAULT 0, status TEXT DEFAULT 'available', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(work_center_id, calendar_date, shift_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_cost_layers (id INTEGER PRIMARY KEY AUTOINCREMENT, production_order_id INTEGER DEFAULT 0, operation_id INTEGER DEFAULT 0, layer_type TEXT DEFAULT '', item_article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, unit TEXT DEFAULT 'шт', plan_amount REAL DEFAULT 0, actual_amount REAL DEFAULT 0, overhead_amount REAL DEFAULT 0, cost_per_unit REAL DEFAULT 0, source_type TEXT DEFAULT '', source_id INTEGER DEFAULT 0, period_key TEXT DEFAULT '', details_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wip_register (id INTEGER PRIMARY KEY AUTOINCREMENT, production_order_id INTEGER DEFAULT 0, operation_id INTEGER DEFAULT 0, layer_id INTEGER DEFAULT 0, movement_type TEXT DEFAULT '', item_article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, amount REAL DEFAULT 0, status TEXT DEFAULT 'posted', period_key TEXT DEFAULT '', account_debit TEXT DEFAULT '', account_credit TEXT DEFAULT '', details_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS finance_payment_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, title TEXT DEFAULT '', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', due_date TEXT DEFAULT '', approver_name TEXT DEFAULT '', approval_status TEXT DEFAULT 'draft', request_status TEXT DEFAULT 'draft', linked_payment_id INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS treasury_project_limits (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', project_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, amount_limit REAL DEFAULT 0, status TEXT DEFAULT 'active', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(period_key, project_id, business_unit_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS finance_budgets (id INTEGER PRIMARY KEY AUTOINCREMENT, budget_type TEXT DEFAULT 'pnl', period_key TEXT DEFAULT '', project_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, article_name TEXT DEFAULT '', plan_amount REAL DEFAULT 0, fact_amount REAL DEFAULT 0, status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS finance_obligations (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, supplier_name TEXT DEFAULT '', obligation_type TEXT DEFAULT 'supplier', title TEXT DEFAULT '', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', due_date TEXT DEFAULT '', linked_payment_id INTEGER DEFAULT 0, status TEXT DEFAULT 'open', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS finance_cash_gap_scenarios (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', scenario_name TEXT DEFAULT '', opening_balance REAL DEFAULT 0, expected_inflow REAL DEFAULT 0, expected_outflow REAL DEFAULT 0, gap_amount REAL DEFAULT 0, action_plan TEXT DEFAULT '', status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounting_manual_operations (id INTEGER PRIMARY KEY AUTOINCREMENT, entry_date TEXT DEFAULT '', period_key TEXT DEFAULT '', legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, account_debit TEXT DEFAULT '', account_credit TEXT DEFAULT '', amount REAL DEFAULT 0, vat_amount REAL DEFAULT 0, description TEXT DEFAULT '', status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounting_debt_adjustments (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, adjustment_date TEXT DEFAULT '', amount REAL DEFAULT 0, adjustment_kind TEXT DEFAULT 'writeoff', reason TEXT DEFAULT '', account_debit TEXT DEFAULT '', account_credit TEXT DEFAULT '', status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cash_operations (id INTEGER PRIMARY KEY AUTOINCREMENT, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, project_id INTEGER DEFAULT 0, operation_date TEXT DEFAULT '', direction TEXT DEFAULT 'incoming', category TEXT DEFAULT 'cash', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', cashbox_name TEXT DEFAULT '', counterparty_name TEXT DEFAULT '', linked_payment_id INTEGER DEFAULT 0, account_debit TEXT DEFAULT '', account_credit TEXT DEFAULT '', status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS erp_process_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, request_type TEXT DEFAULT 'purchase', scenario TEXT DEFAULT '[]', due_date TEXT DEFAULT '', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', status TEXT DEFAULT 'new', current_stage TEXT DEFAULT 'request', request_id INTEGER DEFAULT 0, approval_id INTEGER DEFAULT 0, reservation_id INTEGER DEFAULT 0, purchase_id INTEGER DEFAULT 0, production_id INTEGER DEFAULT 0, sales_doc_id INTEGER DEFAULT 0, payment_id INTEGER DEFAULT 0, created_by TEXT DEFAULT '', updated_by TEXT DEFAULT '', payload TEXT DEFAULT '{}', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS erp_entity_links (id INTEGER PRIMARY KEY AUTOINCREMENT, process_id INTEGER DEFAULT 0, source_type TEXT DEFAULT '', source_id TEXT DEFAULT '', target_type TEXT DEFAULT '', target_id TEXT DEFAULT '', relation_type TEXT DEFAULT 'related', project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, created_by TEXT DEFAULT '', details TEXT DEFAULT '{}', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS business_objects (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER DEFAULT 0, name TEXT DEFAULT '', code TEXT DEFAULT '', address TEXT DEFAULT '', city TEXT DEFAULT '', region TEXT DEFAULT '', responsible_name TEXT DEFAULT '', responsible_email TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS contract_master (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, object_id INTEGER DEFAULT 0, contract_number TEXT DEFAULT '', title TEXT DEFAULT '', status TEXT DEFAULT 'draft', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', start_date TEXT DEFAULT '', end_date TEXT DEFAULT '', manager_name TEXT DEFAULT '', manager_email TEXT DEFAULT '', comment TEXT DEFAULT '', custom_fields TEXT DEFAULT '[]', contract_type TEXT DEFAULT 'standard', category TEXT DEFAULT '', folder TEXT DEFAULT 'Все договоры', vat_mode TEXT DEFAULT 'with_vat', risk_level TEXT DEFAULT 'normal', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS epl_drivers (id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT DEFAULT '', personnel_number TEXT DEFAULT '', license_number TEXT DEFAULT '', license_category TEXT DEFAULT '', phone TEXT DEFAULT '', medical_valid_to TEXT DEFAULT '', signature_profile TEXT DEFAULT 'УНЭП', status TEXT DEFAULT 'active', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS epl_vehicles (id INTEGER PRIMARY KEY AUTOINCREMENT, registration_no TEXT DEFAULT '', garage_number TEXT DEFAULT '', brand TEXT DEFAULT '', model TEXT DEFAULT '', trailer_registration TEXT DEFAULT '', odometer REAL DEFAULT 0, carrying_capacity REAL DEFAULT 0, diagnostic_valid_to TEXT DEFAULT '', insurance_valid_to TEXT DEFAULT '', status TEXT DEFAULT 'active', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS epl_waybills (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, object_id INTEGER DEFAULT 0, number TEXT DEFAULT '', issue_date TEXT DEFAULT '', shift_date TEXT DEFAULT '', waybill_type TEXT DEFAULT 'truck', driver_id INTEGER DEFAULT 0, vehicle_id INTEGER DEFAULT 0, route_text TEXT DEFAULT '', cargo TEXT DEFAULT '', departure_point TEXT DEFAULT '', destination_point TEXT DEFAULT '', dispatcher_name TEXT DEFAULT '', medical_name TEXT DEFAULT '', mechanic_name TEXT DEFAULT '', planned_departure TEXT DEFAULT '', actual_departure TEXT DEFAULT '', actual_return TEXT DEFAULT '', odometer_out REAL DEFAULT 0, odometer_in REAL DEFAULT 0, mileage REAL DEFAULT 0, fuel_issued REAL DEFAULT 0, fuel_returned REAL DEFAULT 0, medical_pretrip_status TEXT DEFAULT '', medical_pretrip_at TEXT DEFAULT '', mechanic_pretrip_status TEXT DEFAULT '', mechanic_pretrip_at TEXT DEFAULT '', dispatcher_departure_status TEXT DEFAULT '', dispatcher_departure_at TEXT DEFAULT '', dispatcher_return_status TEXT DEFAULT '', dispatcher_return_at TEXT DEFAULT '', medical_posttrip_status TEXT DEFAULT '', medical_posttrip_at TEXT DEFAULT '', mechanic_posttrip_status TEXT DEFAULT '', mechanic_posttrip_at TEXT DEFAULT '', status TEXT DEFAULT 'draft', integration_status TEXT DEFAULT 'draft', operator_name TEXT DEFAULT '1С-ЭДО', external_document_id TEXT DEFAULT '', last_sync_error TEXT DEFAULT '', qr_code TEXT DEFAULT '', qr_payload TEXT DEFAULT '', notes TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS epl_signatures (id INTEGER PRIMARY KEY AUTOINCREMENT, waybill_id INTEGER DEFAULT 0, stage TEXT DEFAULT '', signer_role TEXT DEFAULT '', signer_name TEXT DEFAULT '', signature_kind TEXT DEFAULT 'УНЭП', signed_at TEXT DEFAULT '', status_mark TEXT DEFAULT '', comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')

    c.execute('''CREATE TABLE IF NOT EXISTS nomenclature (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, article TEXT, unit TEXT, price REAL, is_active INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS warehouse_master (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', code TEXT DEFAULT '', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS unit_master (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', code TEXT DEFAULT '', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS nomenclature_groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', code TEXT DEFAULT '', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS employee_master (id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT DEFAULT '', personnel_number TEXT DEFAULT '', email TEXT DEFAULT '', phone TEXT DEFAULT '', position_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', external_sync_id TEXT DEFAULT '', exchange_state TEXT DEFAULT 'draft', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS position_master (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', code TEXT DEFAULT '', department_name TEXT DEFAULT '', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', external_sync_id TEXT DEFAULT '', exchange_state TEXT DEFAULT 'draft', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS nomenclature_characteristics (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', code TEXT DEFAULT '', characteristic_type TEXT DEFAULT '', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', external_sync_id TEXT DEFAULT '', exchange_state TEXT DEFAULT 'draft', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS storage_cells (id INTEGER PRIMARY KEY AUTOINCREMENT, warehouse_id INTEGER DEFAULT 0, name TEXT DEFAULT '', code TEXT DEFAULT '', zone_name TEXT DEFAULT '', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', external_sync_id TEXT DEFAULT '', exchange_state TEXT DEFAULT 'draft', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS income_expense_articles (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', code TEXT DEFAULT '', article_kind TEXT DEFAULT 'expense', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', external_sync_id TEXT DEFAULT '', exchange_state TEXT DEFAULT 'draft', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS financial_responsibility_centers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', code TEXT DEFAULT '', legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, manager_name TEXT DEFAULT '', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', external_sync_id TEXT DEFAULT '', exchange_state TEXT DEFAULT 'draft', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS operation_types (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', code TEXT DEFAULT '', module_name TEXT DEFAULT '', flow_kind TEXT DEFAULT '', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', external_sync_id TEXT DEFAULT '', exchange_state TEXT DEFAULT 'draft', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory_documents (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_type TEXT DEFAULT 'inventory', doc_number TEXT DEFAULT '', article TEXT DEFAULT '', warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', batch_code TEXT DEFAULT '', serial_no TEXT DEFAULT '', target_warehouse TEXT DEFAULT '', target_bin TEXT DEFAULT '', qty REAL DEFAULT 0, counted_qty REAL DEFAULT 0, adjustment_qty REAL DEFAULT 0, reason TEXT DEFAULT '', comment TEXT DEFAULT '', status TEXT DEFAULT 'posted', actor_email TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, name TEXT, phone TEXT, email TEXT, position TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS email_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT, address TEXT, login TEXT, password TEXT, imap_host TEXT, imap_port INTEGER DEFAULT 993, smtp_host TEXT, smtp_port INTEGER DEFAULT 465, inbox_folder TEXT DEFAULT 'INBOX', archive_folder TEXT DEFAULT 'Archive', is_default INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1, last_sync_at INTEGER DEFAULT 0, last_error TEXT DEFAULT '', created_at INTEGER, updated_at INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS email_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, uid TEXT, folder TEXT DEFAULT 'INBOX', subject TEXT, sender TEXT, sender_email TEXT, body_preview TEXT, body_text TEXT, received_at TEXT, is_read INTEGER DEFAULT 0, is_archived INTEGER DEFAULT 0, is_deleted INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0, synced_at INTEGER DEFAULT 0, UNIQUE(account_id, uid, folder))''')
    c.execute('''CREATE TABLE IF NOT EXISTS email_attachments (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id INTEGER, filename TEXT, stored_path TEXT, mime_type TEXT DEFAULT '', size INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0, UNIQUE(message_id, filename))''')
    c.execute('''CREATE TABLE IF NOT EXISTS bank_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', bank_name TEXT DEFAULT '', account_number TEXT DEFAULT '', bik TEXT DEFAULT '', currency TEXT DEFAULT 'RUB', legal_entity_id INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bank_statement_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, bank_account_id INTEGER DEFAULT 0, line_date TEXT DEFAULT '', amount REAL DEFAULT 0, direction TEXT DEFAULT 'incoming', counterparty TEXT DEFAULT '', purpose TEXT DEFAULT '', client_id INTEGER DEFAULT 0, linked_payment_id INTEGER DEFAULT 0, external_line_id TEXT DEFAULT '', status TEXT DEFAULT 'imported', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS nsi_mdm_rules (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT DEFAULT '', field_name TEXT DEFAULT '', rule_type TEXT DEFAULT '', rule_value TEXT DEFAULT '', severity TEXT DEFAULT 'error', is_active INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS nsi_mdm_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, version_no INTEGER DEFAULT 1, lifecycle_state TEXT DEFAULT 'draft', payload TEXT DEFAULT '{}', changed_by TEXT DEFAULT '', changed_at INTEGER DEFAULT 0, change_reason TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS nsi_mdm_issues (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, issue_type TEXT DEFAULT '', severity TEXT DEFAULT 'error', status TEXT DEFAULT 'open', message TEXT DEFAULT '', details_json TEXT DEFAULT '{}', created_at INTEGER DEFAULT 0, resolved_at INTEGER DEFAULT 0, resolved_by TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS nsi_mdm_approvals (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, target_state TEXT DEFAULT 'active', status TEXT DEFAULT 'requested', requested_by TEXT DEFAULT '', decided_by TEXT DEFAULT '', comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, decided_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS nsi_hierarchies (id INTEGER PRIMARY KEY AUTOINCREMENT, hierarchy_type TEXT DEFAULT 'mdm', entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, parent_entity_id INTEGER DEFAULT 0, node_code TEXT DEFAULT '', node_name TEXT DEFAULT '', path_code TEXT DEFAULT '', level_no INTEGER DEFAULT 0, sort_order INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1, valid_from TEXT DEFAULT '', valid_to TEXT DEFAULT '', details_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS nsi_external_classifiers (id INTEGER PRIMARY KEY AUTOINCREMENT, classifier_type TEXT DEFAULT '', source_system TEXT DEFAULT '', external_code TEXT DEFAULT '', external_parent_code TEXT DEFAULT '', name TEXT DEFAULT '', short_name TEXT DEFAULT '', entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, effective_from TEXT DEFAULT '', effective_to TEXT DEFAULT '', version_tag TEXT DEFAULT '', status TEXT DEFAULT 'active', data_json TEXT DEFAULT '{}', imported_by TEXT DEFAULT '', imported_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(classifier_type, source_system, external_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS nsi_duplicate_rules (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT DEFAULT '', rule_name TEXT DEFAULT '', fields_json TEXT DEFAULT '[]', match_mode TEXT DEFAULT 'all', severity TEXT DEFAULT 'error', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS nsi_bulk_change_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, request_number TEXT DEFAULT '', entity_type TEXT DEFAULT '', operation TEXT DEFAULT 'update_fields', filter_json TEXT DEFAULT '{}', changes_json TEXT DEFAULT '{}', preview_json TEXT DEFAULT '{}', status TEXT DEFAULT 'draft', approval_id INTEGER DEFAULT 0, target_count INTEGER DEFAULT 0, applied_count INTEGER DEFAULT 0, requested_by TEXT DEFAULT '', approved_by TEXT DEFAULT '', comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, approved_at INTEGER DEFAULT 0, applied_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounting_posting_templates (id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT DEFAULT '', source_label TEXT DEFAULT '', account_debit TEXT DEFAULT '', account_credit TEXT DEFAULT '', vat_mode TEXT DEFAULT 'none', amount_rule TEXT DEFAULT 'full', priority INTEGER DEFAULT 100, is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(source_type, account_debit, account_credit, amount_rule))''')
    c.execute('''CREATE TABLE IF NOT EXISTS treasury_approval_routes (id INTEGER PRIMARY KEY AUTOINCREMENT, route_name TEXT DEFAULT '', legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, min_amount REAL DEFAULT 0, max_amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', stages_json TEXT DEFAULT '[]', is_default INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bank_payment_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id INTEGER DEFAULT 0, bank_account_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, order_date TEXT DEFAULT '', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', counterparty TEXT DEFAULT '', purpose TEXT DEFAULT '', status TEXT DEFAULT 'draft', exchange_batch_id INTEGER DEFAULT 0, external_payment_id TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bank_exchange_batches (id INTEGER PRIMARY KEY AUTOINCREMENT, provider_name TEXT DEFAULT 'bank_api', direction TEXT DEFAULT 'outbound', batch_type TEXT DEFAULT 'payment_exchange', bank_account_id INTEGER DEFAULT 0, status TEXT DEFAULT 'draft', payload_json TEXT DEFAULT '{}', total_amount REAL DEFAULT 0, item_count INTEGER DEFAULT 0, exported_file TEXT DEFAULT '', imported_file TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS telephony_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, provider_name TEXT DEFAULT '', line_name TEXT DEFAULT '', external_line_id TEXT DEFAULT '', is_active INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS telephony_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, project_id INTEGER DEFAULT 0, contact_name TEXT DEFAULT '', phone_number TEXT DEFAULT '', direction TEXT DEFAULT 'inbound', status TEXT DEFAULT 'answered', duration_sec INTEGER DEFAULT 0, call_at TEXT DEFAULT '', summary TEXT DEFAULT '', recording_url TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS saved_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, report_type TEXT DEFAULT '', title TEXT DEFAULT '', filters TEXT DEFAULT '{}', layout TEXT DEFAULT '{}', scope TEXT DEFAULT 'private', owner_email TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "user_favorite_items"):
        c.execute('''CREATE TABLE IF NOT EXISTS user_favorite_items (id BIGINT PRIMARY KEY, user_email TEXT DEFAULT '', entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', title TEXT DEFAULT '', meta TEXT DEFAULT '', view_name TEXT DEFAULT '', payload_json TEXT DEFAULT '{}', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "user_recent_items"):
        c.execute('''CREATE TABLE IF NOT EXISTS user_recent_items (id BIGINT PRIMARY KEY, user_email TEXT DEFAULT '', entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', title TEXT DEFAULT '', meta TEXT DEFAULT '', view_name TEXT DEFAULT '', payload_json TEXT DEFAULT '{}', touched_at INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "user_saved_filters"):
        c.execute('''CREATE TABLE IF NOT EXISTS user_saved_filters (id BIGINT PRIMARY KEY, user_email TEXT DEFAULT '', filter_scope TEXT DEFAULT 'dashboard', title TEXT DEFAULT '', filter_payload_json TEXT DEFAULT '{}', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "user_form_drafts"):
        c.execute('''CREATE TABLE IF NOT EXISTS user_form_drafts (id BIGINT PRIMARY KEY, user_email TEXT DEFAULT '', draft_key TEXT DEFAULT '', entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', title TEXT DEFAULT '', payload_json TEXT DEFAULT '{}', source_view TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(user_email, draft_key))''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_templates (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', doc_type TEXT DEFAULT 'incoming', template_kind TEXT DEFAULT 'catalog', version_label TEXT DEFAULT 'v1', body_text TEXT DEFAULT '', variables_json TEXT DEFAULT '[]', status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "document_ocr_jobs"):
        c.execute('''CREATE TABLE IF NOT EXISTS document_ocr_jobs (id BIGINT PRIMARY KEY, document_id INTEGER DEFAULT 0, file_revision_id INTEGER DEFAULT 0, source_file TEXT DEFAULT '', input_text TEXT DEFAULT '', recognized_text TEXT DEFAULT '', confidence REAL DEFAULT 0, language TEXT DEFAULT 'rus', status TEXT DEFAULT 'queued', extracted_fields_json TEXT DEFAULT '{}', template_id INTEGER DEFAULT 0, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, processed_at INTEGER DEFAULT 0)''')
    if not _db_table_exists(conn, "document_template_flows"):
        c.execute('''CREATE TABLE IF NOT EXISTS document_template_flows (id BIGINT PRIMARY KEY, flow_code TEXT DEFAULT '', flow_name TEXT DEFAULT '', direction TEXT DEFAULT 'incoming', doc_type TEXT DEFAULT 'incoming', trigger_rules_json TEXT DEFAULT '{}', template_ids_json TEXT DEFAULT '[]', required_fields_json TEXT DEFAULT '[]', status TEXT DEFAULT 'active', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, version_no INTEGER DEFAULT 1, version_label TEXT DEFAULT '', version_status TEXT DEFAULT 'draft', payload TEXT DEFAULT '{}', file_url TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_file_revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, revision_no INTEGER DEFAULT 1, revision_label TEXT DEFAULT '', original_filename TEXT DEFAULT '', stored_filename TEXT DEFAULT '', file_url TEXT DEFAULT '', mime_type TEXT DEFAULT '', file_size INTEGER DEFAULT 0, checksum TEXT DEFAULT '', revision_status TEXT DEFAULT 'active', is_current INTEGER DEFAULT 0, source TEXT DEFAULT 'upload', comment TEXT DEFAULT '', uploaded_by TEXT DEFAULT '', uploaded_at INTEGER DEFAULT 0, archived_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_file_blobs (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, file_revision_id INTEGER DEFAULT 0, original_filename TEXT DEFAULT '', stored_filename TEXT DEFAULT '', file_url TEXT DEFAULT '', declared_mime_type TEXT DEFAULT '', detected_mime_type TEXT DEFAULT '', file_size INTEGER DEFAULT 0, checksum_sha256 TEXT DEFAULT '', storage_backend TEXT DEFAULT 'local', storage_key TEXT DEFAULT '', antivirus_status TEXT DEFAULT 'not_configured', antivirus_details TEXT DEFAULT '', validation_status TEXT DEFAULT 'accepted', validation_errors_json TEXT DEFAULT '[]', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_content_index (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, file_revision_id INTEGER DEFAULT 0, blob_id INTEGER DEFAULT 0, source_type TEXT DEFAULT 'file', content_text TEXT DEFAULT '', content_excerpt TEXT DEFAULT '', language TEXT DEFAULT 'simple', extraction_status TEXT DEFAULT 'pending', extraction_method TEXT DEFAULT '', confidence REAL DEFAULT 0, checksum_sha256 TEXT DEFAULT '', indexed_at INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', COALESCE(content_text, ''))) STORED, UNIQUE(file_revision_id, source_type))''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_linked_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, task_id INTEGER DEFAULT 0, title TEXT DEFAULT '', assignee_name TEXT DEFAULT '', deadline TEXT DEFAULT '', priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'active', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS edo_certificates (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_name TEXT DEFAULT '', owner_email TEXT DEFAULT '', signer_role TEXT DEFAULT '', provider_name TEXT DEFAULT '1С-ЭДО', thumbprint TEXT DEFAULT '', serial_number TEXT DEFAULT '', valid_from TEXT DEFAULT '', valid_to TEXT DEFAULT '', status TEXT DEFAULT 'active', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, issued_by TEXT DEFAULT '', subject_dn TEXT DEFAULT '', algorithm TEXT DEFAULT '', key_usage TEXT DEFAULT '', verification_url TEXT DEFAULT '', revoked_at INTEGER DEFAULT 0, last_checked_at INTEGER DEFAULT 0, last_verified_result TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_legal_archive (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, archive_code TEXT DEFAULT '', storage_path TEXT DEFAULT '', retention_until TEXT DEFAULT '', archive_status TEXT DEFAULT 'archived', certificate_id INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, archived_revision_id INTEGER DEFAULT 0, archive_hash TEXT DEFAULT '', archive_payload_json TEXT DEFAULT '{}', source_signature_id INTEGER DEFAULT 0, policy_id INTEGER DEFAULT 0, access_roles_json TEXT DEFAULT '[]', transfer_basis TEXT DEFAULT '', destruction_basis TEXT DEFAULT '', review_due_at TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_print_forms (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, template_id INTEGER DEFAULT 0, format_type TEXT DEFAULT 'pdf', form_name TEXT DEFAULT '', file_url TEXT DEFAULT '', status TEXT DEFAULT 'generated', generated_at TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_registration_journals (id INTEGER PRIMARY KEY AUTOINCREMENT, journal_code TEXT DEFAULT '', journal_name TEXT DEFAULT '', doc_type TEXT DEFAULT '', prefix TEXT DEFAULT '', next_number INTEGER DEFAULT 1, numbering_pattern TEXT DEFAULT '{prefix}-{year}-{number}', is_active INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(journal_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_registration_records (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, journal_id INTEGER DEFAULT 0, registration_number TEXT DEFAULT '', registration_date TEXT DEFAULT '', registered_by TEXT DEFAULT '', status TEXT DEFAULT 'registered', details_json TEXT DEFAULT '{}', created_at INTEGER DEFAULT 0, UNIQUE(document_id, journal_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_classifiers (id INTEGER PRIMARY KEY AUTOINCREMENT, classifier_code TEXT DEFAULT '', name TEXT DEFAULT '', doc_type TEXT DEFAULT '', category TEXT DEFAULT '', required_fields TEXT DEFAULT '[]', default_lifecycle TEXT DEFAULT 'draft', retention_years INTEGER DEFAULT 5, is_active INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, allowed_roles_json TEXT DEFAULT '[]', retention_policy_id INTEGER DEFAULT 0, UNIQUE(classifier_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_case_files (id INTEGER PRIMARY KEY AUTOINCREMENT, case_index TEXT DEFAULT '', title TEXT DEFAULT '', department TEXT DEFAULT '', retention_years INTEGER DEFAULT 5, opened_at TEXT DEFAULT '', closed_at TEXT DEFAULT '', status TEXT DEFAULT 'open', responsible_name TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, case_category TEXT DEFAULT '', allowed_roles_json TEXT DEFAULT '[]', retention_policy_id INTEGER DEFAULT 0, transfer_basis_default TEXT DEFAULT '', destruction_basis_default TEXT DEFAULT '', UNIQUE(case_index))''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_retention_policies (id INTEGER PRIMARY KEY AUTOINCREMENT, policy_code TEXT DEFAULT '', policy_name TEXT DEFAULT '', scope_type TEXT DEFAULT 'doc_type', scope_value TEXT DEFAULT '', retention_years INTEGER DEFAULT 5, review_before_days INTEGER DEFAULT 90, auto_archive INTEGER DEFAULT 0, transfer_basis_default TEXT DEFAULT '', destruction_basis_default TEXT DEFAULT '', access_roles_json TEXT DEFAULT '[]', confidentiality_levels_json TEXT DEFAULT '[]', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(policy_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_retention_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, archive_id INTEGER DEFAULT 0, action_name TEXT DEFAULT 'review', previous_status TEXT DEFAULT '', new_status TEXT DEFAULT '', basis_text TEXT DEFAULT '', storage_path TEXT DEFAULT '', retention_until TEXT DEFAULT '', review_due_at TEXT DEFAULT '', details_json TEXT DEFAULT '{}', actor_email TEXT DEFAULT '', actor_name TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_lifecycle_events (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER DEFAULT 0, from_state TEXT DEFAULT '', to_state TEXT DEFAULT '', action_name TEXT DEFAULT '', actor_email TEXT DEFAULT '', actor_name TEXT DEFAULT '', comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_packages (id INTEGER PRIMARY KEY AUTOINCREMENT, package_number TEXT DEFAULT '', title TEXT DEFAULT '', package_kind TEXT DEFAULT 'contract_set', status TEXT DEFAULT 'draft', project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, object_id INTEGER DEFAULT 0, approval_id INTEGER DEFAULT 0, package_checksum TEXT DEFAULT '', registry_file_url TEXT DEFAULT '', export_file_url TEXT DEFAULT '', signed_by TEXT DEFAULT '', signed_at INTEGER DEFAULT 0, summary_json TEXT DEFAULT '{}', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(package_number))''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_package_items (id INTEGER PRIMARY KEY AUTOINCREMENT, package_id INTEGER DEFAULT 0, entity_type TEXT DEFAULT 'document', entity_id INTEGER DEFAULT 0, item_role TEXT DEFAULT 'document', order_no INTEGER DEFAULT 1, required INTEGER DEFAULT 1, item_status TEXT DEFAULT 'included', title TEXT DEFAULT '', meta_json TEXT DEFAULT '{}', file_revision_id INTEGER DEFAULT 0, checksum TEXT DEFAULT '', signature_id INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(package_id, entity_type, entity_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS document_relations (id INTEGER PRIMARY KEY AUTOINCREMENT, source_entity_type TEXT DEFAULT '', source_entity_id INTEGER DEFAULT 0, target_entity_type TEXT DEFAULT '', target_entity_id INTEGER DEFAULT 0, relation_type TEXT DEFAULT 'related', package_id INTEGER DEFAULT 0, meta_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS approval_route_templates (id INTEGER PRIMARY KEY AUTOINCREMENT, route_code TEXT DEFAULT '', route_name TEXT DEFAULT '', entity_type TEXT DEFAULT '', conditions_json TEXT DEFAULT '{}', stages_json TEXT DEFAULT '[]', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(route_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS approval_action_log (id INTEGER PRIMARY KEY AUTOINCREMENT, approval_id INTEGER DEFAULT 0, stage_key TEXT DEFAULT '', action_name TEXT DEFAULT '', actor_email TEXT DEFAULT '', actor_name TEXT DEFAULT '', target_user TEXT DEFAULT '', comment TEXT DEFAULT '', payload_json TEXT DEFAULT '{}', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS approval_delegations (id INTEGER PRIMARY KEY AUTOINCREMENT, approval_id INTEGER DEFAULT 0, stage_key TEXT DEFAULT '', from_user TEXT DEFAULT '', to_user TEXT DEFAULT '', status TEXT DEFAULT 'active', reason TEXT DEFAULT '', delegated_by TEXT DEFAULT '', delegated_at INTEGER DEFAULT 0, resolved_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS approval_sla_events (id INTEGER PRIMARY KEY AUTOINCREMENT, approval_id INTEGER DEFAULT 0, stage_key TEXT DEFAULT '', event_type TEXT DEFAULT '', risk_level TEXT DEFAULT 'stable', due_at INTEGER DEFAULT 0, actor_name TEXT DEFAULT '', comment TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS workflow_definitions (id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_code TEXT DEFAULT '', workflow_name TEXT DEFAULT '', entity_type TEXT DEFAULT '', trigger_event TEXT DEFAULT 'manual', version INTEGER DEFAULT 1, status TEXT DEFAULT 'draft', conditions_json TEXT DEFAULT '{}', settings_json TEXT DEFAULT '{}', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(workflow_code, version))''')
    c.execute('''CREATE TABLE IF NOT EXISTS workflow_nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, definition_id INTEGER DEFAULT 0, node_key TEXT DEFAULT '', node_type TEXT DEFAULT 'approval', title TEXT DEFAULT '', role_name TEXT DEFAULT '', assignee_name TEXT DEFAULT '', parallel_mode TEXT DEFAULT 'all', sla_hours INTEGER DEFAULT 24, timer_seconds INTEGER DEFAULT 0, config_json TEXT DEFAULT '{}', x INTEGER DEFAULT 0, y INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(definition_id, node_key))''')
    c.execute('''CREATE TABLE IF NOT EXISTS workflow_edges (id INTEGER PRIMARY KEY AUTOINCREMENT, definition_id INTEGER DEFAULT 0, source_node_key TEXT DEFAULT '', target_node_key TEXT DEFAULT '', condition_json TEXT DEFAULT '{}', condition_label TEXT DEFAULT '', priority INTEGER DEFAULT 100, created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS workflow_instances (id INTEGER PRIMARY KEY AUTOINCREMENT, definition_id INTEGER DEFAULT 0, workflow_code TEXT DEFAULT '', entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', title TEXT DEFAULT '', status TEXT DEFAULT 'running', current_node_key TEXT DEFAULT '', context_json TEXT DEFAULT '{}', history_json TEXT DEFAULT '[]', started_by TEXT DEFAULT '', started_at INTEGER DEFAULT 0, completed_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS workflow_tokens (id INTEGER PRIMARY KEY AUTOINCREMENT, instance_id INTEGER DEFAULT 0, definition_id INTEGER DEFAULT 0, node_key TEXT DEFAULT '', node_type TEXT DEFAULT '', token_status TEXT DEFAULT 'queued', assignee_name TEXT DEFAULT '', role_name TEXT DEFAULT '', due_at INTEGER DEFAULT 0, parent_token_id INTEGER DEFAULT 0, branch_key TEXT DEFAULT '', decision TEXT DEFAULT '', comment TEXT DEFAULT '', delegated_from TEXT DEFAULT '', escalated_to TEXT DEFAULT '', started_at INTEGER DEFAULT 0, completed_at INTEGER DEFAULT 0, completed_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_inbound_updates (id INTEGER PRIMARY KEY AUTOINCREMENT, system_name TEXT DEFAULT '1C', entity_type TEXT DEFAULT '', entity_id INTEGER DEFAULT 0, external_id TEXT DEFAULT '', payload TEXT DEFAULT '{}', apply_mode TEXT DEFAULT 'apply', apply_status TEXT DEFAULT 'received', result_message TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS integration_connectors (id INTEGER PRIMARY KEY AUTOINCREMENT, connector_type TEXT DEFAULT '1c', provider_name TEXT DEFAULT '', status TEXT DEFAULT 'active', settings_json TEXT DEFAULT '{}', scope_json TEXT DEFAULT '{}', last_sync_at INTEGER DEFAULT 0, last_error TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS security_action_policies (id INTEGER PRIMARY KEY AUTOINCREMENT, role_name TEXT DEFAULT '', module_name TEXT DEFAULT '', entity_type TEXT DEFAULT '', action_name TEXT DEFAULT '', status_name TEXT DEFAULT '', allow_execute INTEGER DEFAULT 1, require_2fa INTEGER DEFAULT 0, require_reason INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS security_danger_rules (id INTEGER PRIMARY KEY AUTOINCREMENT, module_name TEXT DEFAULT '', entity_type TEXT DEFAULT '', action_name TEXT DEFAULT '', risk_level TEXT DEFAULT 'medium', require_2fa INTEGER DEFAULT 0, require_reason INTEGER DEFAULT 1, blocked_roles TEXT DEFAULT '[]', is_active INTEGER DEFAULT 1, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales_quotes (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, object_id INTEGER DEFAULT 0, title TEXT DEFAULT '', quote_number TEXT DEFAULT '', stage TEXT DEFAULT 'draft', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', valid_until TEXT DEFAULT '', responsible TEXT DEFAULT '', probability INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales_customer_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, quote_id INTEGER DEFAULT 0, sales_document_id INTEGER DEFAULT 0, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, object_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, order_number TEXT DEFAULT '', article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, unit TEXT DEFAULT 'шт', unit_price REAL DEFAULT 0, amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', status TEXT DEFAULT 'draft', requested_ship_date TEXT DEFAULT '', payment_terms TEXT DEFAULT '', reserve_status TEXT DEFAULT 'none', reservation_id INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales_shipments (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_order_id INTEGER DEFAULT 0, sales_document_id INTEGER DEFAULT 0, reservation_id INTEGER DEFAULT 0, shipment_number TEXT DEFAULT '', article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', batch_code TEXT DEFAULT '', serial_no TEXT DEFAULT '', planned_ship_date TEXT DEFAULT '', shipped_at TEXT DEFAULT '', status TEXT DEFAULT 'planned', carrier TEXT DEFAULT '', tracking_no TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales_payment_schedules (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_order_id INTEGER DEFAULT 0, sales_document_id INTEGER DEFAULT 0, payment_id INTEGER DEFAULT 0, schedule_number TEXT DEFAULT '', due_date TEXT DEFAULT '', amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', status TEXT DEFAULT 'planned', paid_amount REAL DEFAULT 0, paid_date TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales_deal_margins (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_order_id INTEGER DEFAULT 0, sales_document_id INTEGER DEFAULT 0, revenue_amount REAL DEFAULT 0, direct_cost_amount REAL DEFAULT 0, purchase_cost_amount REAL DEFAULT 0, discount_amount REAL DEFAULT 0, margin_amount REAL DEFAULT 0, margin_percent REAL DEFAULT 0, status TEXT DEFAULT 'calculated', calculation_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS customer_returns (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, sales_document_id INTEGER DEFAULT 0, return_number TEXT DEFAULT '', article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', status TEXT DEFAULT 'draft', reason TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', manager_name TEXT DEFAULT '', client_id INTEGER DEFAULT 0, project_id INTEGER DEFAULT 0, target_amount REAL DEFAULT 0, target_docs INTEGER DEFAULT 0, actual_amount REAL DEFAULT 0, status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS price_lists (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', currency TEXT DEFAULT 'RUB', valid_from TEXT DEFAULT '', valid_to TEXT DEFAULT '', item_article TEXT DEFAULT '', item_name TEXT DEFAULT '', unit TEXT DEFAULT 'шт', base_price REAL DEFAULT 0, min_price REAL DEFAULT 0, status TEXT DEFAULT 'active', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS client_sales_terms (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER DEFAULT 0, price_list_id INTEGER DEFAULT 0, discount_percent REAL DEFAULT 0, discount_amount REAL DEFAULT 0, payment_delay_days INTEGER DEFAULT 0, credit_limit REAL DEFAULT 0, shipment_priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'active', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS supplier_registry (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_name TEXT DEFAULT '', legal_entity_name TEXT DEFAULT '', inn TEXT DEFAULT '', category TEXT DEFAULT '', rating REAL DEFAULT 0, lead_time_days INTEGER DEFAULT 0, reliability_percent REAL DEFAULT 100, payment_terms TEXT DEFAULT '', comment TEXT DEFAULT '', is_active INTEGER DEFAULT 1, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchase_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, period_key TEXT DEFAULT '', supplier_id INTEGER DEFAULT 0, project_id INTEGER DEFAULT 0, item_article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty_plan REAL DEFAULT 0, unit TEXT DEFAULT 'шт', target_unit_price REAL DEFAULT 0, target_amount REAL DEFAULT 0, status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS supplier_delivery_schedules (id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER DEFAULT 0, supplier_id INTEGER DEFAULT 0, scheduled_date TEXT DEFAULT '', planned_qty REAL DEFAULT 0, delivered_qty REAL DEFAULT 0, status TEXT DEFAULT 'planned', transport_no TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS supplier_returns (id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER DEFAULT 0, supplier_id INTEGER DEFAULT 0, article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', status TEXT DEFAULT 'draft', reason TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS supplier_discrepancy_acts (id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER DEFAULT 0, supplier_id INTEGER DEFAULT 0, act_number TEXT DEFAULT '', article TEXT DEFAULT '', item_name TEXT DEFAULT '', planned_qty REAL DEFAULT 0, actual_qty REAL DEFAULT 0, planned_unit_price REAL DEFAULT 0, actual_unit_price REAL DEFAULT 0, status TEXT DEFAULT 'open', reason TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS procurement_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, object_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, request_number TEXT DEFAULT '', title TEXT DEFAULT '', item_article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, unit TEXT DEFAULT 'шт', target_unit_price REAL DEFAULT 0, required_date TEXT DEFAULT '', priority TEXT DEFAULT 'normal', requested_by TEXT DEFAULT '', status TEXT DEFAULT 'draft', linked_purchase_id INTEGER DEFAULT 0, selected_supplier_id INTEGER DEFAULT 0, approved_by TEXT DEFAULT '', approved_at INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS procurement_tenders (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER DEFAULT 0, tender_number TEXT DEFAULT '', title TEXT DEFAULT '', due_date TEXT DEFAULT '', status TEXT DEFAULT 'draft', criteria_json TEXT DEFAULT '{}', selected_supplier_id INTEGER DEFAULT 0, selected_bid_id INTEGER DEFAULT 0, decision_comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS procurement_tender_bids (id INTEGER PRIMARY KEY AUTOINCREMENT, tender_id INTEGER DEFAULT 0, supplier_id INTEGER DEFAULT 0, supplier_name TEXT DEFAULT '', price REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', lead_time_days INTEGER DEFAULT 0, payment_terms TEXT DEFAULT '', warranty_terms TEXT DEFAULT '', score REAL DEFAULT 0, status TEXT DEFAULT 'submitted', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchase_receipts (id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER DEFAULT 0, request_id INTEGER DEFAULT 0, supplier_id INTEGER DEFAULT 0, receipt_number TEXT DEFAULT '', receipt_date TEXT DEFAULT '', article TEXT DEFAULT '', item_name TEXT DEFAULT '', accepted_qty REAL DEFAULT 0, rejected_qty REAL DEFAULT 0, warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', quality_status TEXT DEFAULT 'accepted', status TEXT DEFAULT 'posted', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchase_documents (id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER DEFAULT 0, request_id INTEGER DEFAULT 0, supplier_id INTEGER DEFAULT 0, doc_type TEXT DEFAULT 'invoice', doc_number TEXT DEFAULT '', doc_date TEXT DEFAULT '', amount REAL DEFAULT 0, vat_amount REAL DEFAULT 0, currency TEXT DEFAULT 'RUB', status TEXT DEFAULT 'draft', payment_due_date TEXT DEFAULT '', linked_payment_id INTEGER DEFAULT 0, file_ref TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS fulfillment_plan (id INTEGER PRIMARY KEY AUTOINCREMENT, demand_type TEXT DEFAULT '', demand_id INTEGER DEFAULT 0, demand_number TEXT DEFAULT '', project_id INTEGER DEFAULT 0, client_id INTEGER DEFAULT 0, contract_id INTEGER DEFAULT 0, object_id INTEGER DEFAULT 0, legal_entity_id INTEGER DEFAULT 0, business_unit_id INTEGER DEFAULT 0, item_article TEXT DEFAULT '', item_name TEXT DEFAULT '', unit TEXT DEFAULT 'шт', demand_qty REAL DEFAULT 0, available_qty REAL DEFAULT 0, reserved_qty REAL DEFAULT 0, shortage_qty REAL DEFAULT 0, planned_purchase_qty REAL DEFAULT 0, planned_production_qty REAL DEFAULT 0, linked_supply_qty REAL DEFAULT 0, shipped_qty REAL DEFAULT 0, invoiced_qty REAL DEFAULT 0, status TEXT DEFAULT 'draft', strategy TEXT DEFAULT 'purchase', need_by_date TEXT DEFAULT '', details_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(demand_type, demand_id, item_article))''')
    c.execute('''CREATE TABLE IF NOT EXISTS supply_demand_links (id INTEGER PRIMARY KEY AUTOINCREMENT, demand_type TEXT DEFAULT '', demand_id INTEGER DEFAULT 0, demand_number TEXT DEFAULT '', supply_type TEXT DEFAULT '', supply_id INTEGER DEFAULT 0, supply_number TEXT DEFAULT '', item_article TEXT DEFAULT '', item_name TEXT DEFAULT '', unit TEXT DEFAULT 'шт', qty REAL DEFAULT 0, status TEXT DEFAULT 'planned', link_kind TEXT DEFAULT '', source_plan_id INTEGER DEFAULT 0, details_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS three_way_matches (id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER DEFAULT 0, receipt_id INTEGER DEFAULT 0, invoice_id INTEGER DEFAULT 0, supplier_id INTEGER DEFAULT 0, item_article TEXT DEFAULT '', item_name TEXT DEFAULT '', unit TEXT DEFAULT 'шт', ordered_qty REAL DEFAULT 0, received_qty REAL DEFAULT 0, invoiced_qty REAL DEFAULT 0, ordered_amount REAL DEFAULT 0, received_amount REAL DEFAULT 0, invoice_amount REAL DEFAULT 0, vat_amount REAL DEFAULT 0, qty_variance REAL DEFAULT 0, amount_variance REAL DEFAULT 0, vat_variance REAL DEFAULT 0, status TEXT DEFAULT 'pending', discrepancy_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS invoice_matching_results (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_type TEXT DEFAULT '', invoice_id INTEGER DEFAULT 0, match_type TEXT DEFAULT 'two_way', source_type TEXT DEFAULT '', source_id INTEGER DEFAULT 0, counterparty_id INTEGER DEFAULT 0, expected_amount REAL DEFAULT 0, invoice_amount REAL DEFAULT 0, amount_variance REAL DEFAULT 0, expected_qty REAL DEFAULT 0, actual_qty REAL DEFAULT 0, qty_variance REAL DEFAULT 0, status TEXT DEFAULT 'pending', discrepancy_type TEXT DEFAULT '', details_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory_acts (id INTEGER PRIMARY KEY AUTOINCREMENT, warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', article TEXT DEFAULT '', item_name TEXT DEFAULT '', expected_qty REAL DEFAULT 0, counted_qty REAL DEFAULT 0, batch_code TEXT DEFAULT '', serial_no TEXT DEFAULT '', adjustment_qty REAL DEFAULT 0, status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', linked_document_id INTEGER DEFAULT 0, created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory_regrading_docs (id INTEGER PRIMARY KEY AUTOINCREMENT, warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', from_article TEXT DEFAULT '', from_name TEXT DEFAULT '', to_article TEXT DEFAULT '', to_name TEXT DEFAULT '', qty REAL DEFAULT 0, status TEXT DEFAULT 'draft', reason TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS warehouse_quality_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, quality_status TEXT DEFAULT 'hold', defect_kind TEXT DEFAULT '', decision TEXT DEFAULT 'inspect', status TEXT DEFAULT 'open', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS warehouse_policies (id INTEGER PRIMARY KEY CHECK (id = 1), cost_method TEXT DEFAULT 'fifo', allow_negative_stock INTEGER DEFAULT 0, auto_pick_strategy TEXT DEFAULT 'best_fit', comment TEXT DEFAULT '', updated_by TEXT DEFAULT '', updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory_cost_layers (id INTEGER PRIMARY KEY AUTOINCREMENT, article TEXT DEFAULT '', item_name TEXT DEFAULT '', warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', batch_code TEXT DEFAULT '', serial_no TEXT DEFAULT '', lot_expiration_date TEXT DEFAULT '', layer_kind TEXT DEFAULT 'receipt', qty REAL DEFAULT 0, remaining_qty REAL DEFAULT 0, unit TEXT DEFAULT 'шт', unit_cost REAL DEFAULT 0, amount REAL DEFAULT 0, source_type TEXT DEFAULT '', source_id INTEGER DEFAULT 0, movement_id INTEGER DEFAULT 0, cost_method TEXT DEFAULT 'fifo', status TEXT DEFAULT 'open', details_json TEXT DEFAULT '{}', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS unit_conversions (id INTEGER PRIMARY KEY AUTOINCREMENT, article TEXT DEFAULT '', from_unit TEXT DEFAULT '', to_unit TEXT DEFAULT '', factor REAL DEFAULT 1, is_base INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(article, from_unit, to_unit))''')
    c.execute('''CREATE TABLE IF NOT EXISTS item_packages (id INTEGER PRIMARY KEY AUTOINCREMENT, article TEXT DEFAULT '', package_code TEXT DEFAULT '', package_name TEXT DEFAULT '', unit TEXT DEFAULT 'шт', qty_per_package REAL DEFAULT 1, weight_kg REAL DEFAULT 0, volume_m3 REAL DEFAULT 0, barcode TEXT DEFAULT '', is_default INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(article, package_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS wms_cell_profiles (id INTEGER PRIMARY KEY AUTOINCREMENT, warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', zone_name TEXT DEFAULT '', cell_type TEXT DEFAULT 'storage', capacity_qty REAL DEFAULT 0, capacity_weight REAL DEFAULT 0, abc_class TEXT DEFAULT '', status TEXT DEFAULT 'active', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, UNIQUE(warehouse, bin_code))''')
    c.execute('''CREATE TABLE IF NOT EXISTS wms_putaway_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_id INTEGER DEFAULT 0, article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, source_warehouse TEXT DEFAULT '', source_bin TEXT DEFAULT '', target_warehouse TEXT DEFAULT '', target_bin TEXT DEFAULT '', batch_code TEXT DEFAULT '', serial_no TEXT DEFAULT '', priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'open', assigned_to TEXT DEFAULT '', completed_at INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wms_pick_waves (id INTEGER PRIMARY KEY AUTOINCREMENT, wave_number TEXT DEFAULT '', project_id INTEGER DEFAULT 0, source_type TEXT DEFAULT 'reservation', status TEXT DEFAULT 'draft', priority TEXT DEFAULT 'normal', planned_ship_date TEXT DEFAULT '', assigned_to TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wms_pick_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, wave_id INTEGER DEFAULT 0, reservation_id INTEGER DEFAULT 0, article TEXT DEFAULT '', item_name TEXT DEFAULT '', qty REAL DEFAULT 0, picked_qty REAL DEFAULT 0, warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', batch_code TEXT DEFAULT '', serial_no TEXT DEFAULT '', status TEXT DEFAULT 'open', assigned_to TEXT DEFAULT '', picked_at INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wms_cycle_counts (id INTEGER PRIMARY KEY AUTOINCREMENT, count_number TEXT DEFAULT '', warehouse TEXT DEFAULT '', zone_name TEXT DEFAULT '', bin_code TEXT DEFAULT '', status TEXT DEFAULT 'draft', planned_date TEXT DEFAULT '', started_at INTEGER DEFAULT 0, closed_at INTEGER DEFAULT 0, assigned_to TEXT DEFAULT '', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wms_cycle_count_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, count_id INTEGER DEFAULT 0, article TEXT DEFAULT '', item_name TEXT DEFAULT '', warehouse TEXT DEFAULT '', bin_code TEXT DEFAULT '', batch_code TEXT DEFAULT '', serial_no TEXT DEFAULT '', expected_qty REAL DEFAULT 0, counted_qty REAL DEFAULT 0, variance_qty REAL DEFAULT 0, status TEXT DEFAULT 'draft', comment TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0)''')

    now_ts = int(time.time())

    c.execute("SELECT COUNT(*) FROM global_chats")
    if c.fetchone()[0] == 0:
        default_chats = [(1, 'Общий чат (Вся компания)', 'system', 'system', '[]'), (2, 'Совещания и Планерки', 'system', 'system', '[]'), (3, 'Конструкторское бюро', 'role', 'system', '["Конструкторское бюро"]'), (4, 'Производство и ОТК', 'role', 'system', '["Производство и ОТК"]'), (5, 'Менеджеры (Логистика)', 'role', 'system', '["Менеджер"]'), (6, 'Бухгалтерия', 'role', 'system', '["Бухгалтерия"]'), (7, 'Юристы', 'role', 'system', '["Юрист"]')]
        c.executemany("INSERT INTO global_chats VALUES (?, ?, ?, ?, ?)", default_chats)

    c.execute("SELECT COUNT(*) FROM calendar_events")
    if c.fetchone()[0] == 0:
        demo_calendar_events = [
            ('Личный фокус по ключевым лидам', '02.07.2026', '09:30', '10:00', 'personal', 'admin', 'Администратор', '', 0, 0, 'planned', 'Кабинет директора', 'Проверить следующие действия по новым запросам.', 'system', now_ts, now_ts),
            ('План продаж отдела', '02.07.2026', '11:00', '12:00', 'department', '', 'Система', 'Менеджер', 0, 0, 'planned', 'Отдел продаж', 'Сверка воронки, активностей и просроченных касаний.', 'system', now_ts, now_ts),
            ('Общая штаб-планерка', '03.07.2026', '10:00', '11:00', 'shared', '', 'Система', '', 0, 0, 'planned', 'Переговорная А', 'Общий операционный статус по компании.', 'system', now_ts, now_ts),
        ]
        c.executemany(
            """
            INSERT INTO calendar_events (
                title, event_date, start_time, end_time, scope, owner_email, owner_name, department,
                project_id, meeting_id, status, location, description, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            demo_calendar_events,
        )

    c.execute("SELECT COUNT(*) FROM crm_leads")
    if c.fetchone()[0] == 0:
        demo_leads = [
            ('Запрос на термочехлы для блока ТЭЦ', 'АО ЭнергоТепло', 'Виктор Смирнов', 'v.smirnov@energo.example', '+7 911 111-22-33', 'Почта', 'qualified', 48, 1850000, 'RUB', 'Администратор', 'Подтвердить ТЗ и бюджет', '03.07.2026', 'high', '["энергетика","теплоизоляция"]', 'Клиент вернулся после первого КП.', 0, 0, 0, 'system', now_ts, now_ts),
            ('Потенциальный проект по шумозащите', 'ООО ПромШум', 'Мария Лапина', 'lapina@promshum.example', '+7 921 555-77-88', 'Сайт', 'proposal', 62, 940000, 'RUB', 'Администратор', 'Созвон по условиям монтажа', '04.07.2026', 'normal', '["монтаж","сервис"]', 'Нужно показать кейсы и сроки.', 0, 0, 0, 'system', now_ts, now_ts),
            ('Входящий интерес по экрану турбины', 'ПАО МашЭнерго', 'Ирина Белова', 'belova@mashenergo.example', '+7 981 222-44-55', 'Тендер', 'new', 18, 3200000, 'RUB', 'Администратор', 'Первичный квалификационный звонок', '05.07.2026', 'high', '["тендер","турбина"]', 'Пока без точной спецификации.', 0, 0, 0, 'system', now_ts, now_ts),
        ]
        c.executemany(
            """
            INSERT INTO crm_leads (
                title, client_name, contact_name, contact_email, contact_phone, source, stage, probability, budget, currency,
                responsible, next_action, next_action_date, priority, tags_json, comment, linked_client_id, linked_project_id, linked_deal_id, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            demo_leads,
        )

    c.execute("SELECT COUNT(*) FROM crm_deals")
    if c.fetchone()[0] == 0:
        demo_deals = [
            (1, 'Сделка: ЭнергоТепло / 2026-КП-014', 0, 'АО ЭнергоТепло', '2026-КП-014', 'negotiation', 1450000, 'RUB', 27, 64, 'Администратор', 'Согласовать скидку и срок поставки', '04.07.2026', '18.07.2026', 'high', 'attention', '["переговоры","горячая"]', 'Клиент ждёт ответ по скидке и графику.', 0, 'system', now_ts, now_ts),
            (2, 'Сделка: ПромШум / пилотный объект', 0, 'ООО ПромШум', '2026-КП-018', 'proposal', 780000, 'RUB', 31, 52, 'Администратор', 'Дослать уточнённое КП', '03.07.2026', '15.07.2026', 'normal', 'accent', '["пилот","сервис"]', 'Нужно приложить условия сервисного выезда.', 0, 'system', now_ts, now_ts),
        ]
        c.executemany(
            """
            INSERT INTO crm_deals (
                lead_id, title, client_id, client_name, contract_number, stage, amount, currency, margin_percent, probability,
                responsible, next_action, next_action_date, expected_close_date, priority, status_color, tags_json, comment, project_id, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            demo_deals,
        )

    c.execute("SELECT COUNT(*) FROM crm_activities")
    if c.fetchone()[0] == 0:
        demo_activities = [
            ('lead', 1, 'call', 'Квалификация лида', 'Подтвердить состав оборудования и срок запуска площадки.', '03.07.2026', 'open', 'Администратор', 'system', now_ts, now_ts),
            ('lead', 2, 'email', 'Отправить кейсы', 'Дослать клиенту 2 кейса по сервису и монтажу.', '04.07.2026', 'open', 'Администратор', 'system', now_ts, now_ts),
            ('deal', 1, 'meeting', 'Коммерческий комитет', 'Согласовать диапазон скидки и отгрузочный слот.', '04.07.2026', 'open', 'Администратор', 'system', now_ts, now_ts),
            ('deal', 2, 'task', 'Обновить КП', 'Подготовить расширенное КП с планом-графиком.', '03.07.2026', 'open', 'Администратор', 'system', now_ts, now_ts),
        ]
        c.executemany(
            """
            INSERT INTO crm_activities (
                entity_type, entity_id, activity_type, subject, summary, due_date, status, owner_name, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            demo_activities,
        )

    c.execute("SELECT COUNT(*) FROM company_feed_posts")
    if c.fetchone()[0] == 0:
        demo_posts = [
            (
                1,
                'Администратор',
                'Директор',
                'announcement',
                'Старт недели',
                'Проверяем просроченные задачи, обновляем статусы по активным проектам и фиксируем блокеры до 12:00.',
                '[]',
                '[]',
                1,
                now_ts,
                now_ts,
            ),
            (
                2,
                'Администратор',
                'Директор',
                'poll',
                'Формат планёрки',
                'Какой формат утренней планёрки удобнее для команд?',
                '[{"id":"opt_1","label":"Короткий статус 15 минут"},{"id":"opt_2","label":"Детальный разбор 30 минут"},{"id":"opt_3","label":"Только по проблемным проектам"}]',
                '[]',
                0,
                now_ts,
                now_ts,
            ),
        ]
        c.executemany(
            "INSERT INTO company_feed_posts (id, author_name, author_role, post_type, title, content, poll_options, target_roles, is_pinned, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            demo_posts,
        )

    c.execute("SELECT COUNT(*) FROM tasks")
    if c.fetchone()[0] == 0:
        seed_tasks = [
            (1, 'Проверить договор по проекту DEMO-ERP-PROD', 'Сверить сумму, сроки и реквизиты перед отправкой клиенту.', 'Илья Осипов', 'Илья Осипов', '03.07.2026 12:00', 'active', '01.07.2026 09:10', 'none', 'high', 1, '["Создано для демонстрации Task Center"]', '[{"user":"Мария Демо","role":"Менеджер","text":"Договор уже в карточке проекта, нужны только замечания по условиям оплаты.","time":"01.07.2026 09:15","created_at":' + str(now_ts) + '}]', now_ts),
            (2, 'Подтвердить статус оплаты счета', 'Уточнить в бухгалтерии, прошла ли предоплата по счету и нужен ли перенос отгрузки.', 'Мария Демо', 'Илья Осипов', '02.07.2026 17:30', 'active', '01.07.2026 08:40', 'none', 'normal', 1, '[]', '[]', now_ts),
            (3, 'Закрыть комментарии по производственному заказу', 'Проверить ответ КБ и отметить задачу выполненной.', 'Илья Осипов', 'Павел Демо', '30.06.2026 18:00', 'completed', '30.06.2026 10:00', 'none', 'normal', 1, '["Исполнитель подтвердил выполнение"]', '[{"user":"Павел Демо","role":"Производство и ОТК","text":"Маршрут уточнен, заказ можно закрывать.","time":"30.06.2026 17:20","created_at":' + str(now_ts) + '}]', now_ts),
        ]
        c.executemany(
            "INSERT INTO tasks (id, title, description, author, executor, deadline, status, created_at, recurrence, priority, project_id, history, chat, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            seed_tasks,
        )

    for col, default in [('budget', 'REAL DEFAULT 0'), ('costs', 'REAL DEFAULT 0'), ('chat', "TEXT DEFAULT '[]'"), ('files', "TEXT DEFAULT '[]'"), ('logs', "TEXT DEFAULT '[]'"), ('team', "TEXT DEFAULT '[]'"), ('checklist', "TEXT DEFAULT '[]'"), ('escalations', "TEXT DEFAULT '{}'"), ('archive_details', "TEXT DEFAULT '{}'"), ('taskFiles', "TEXT DEFAULT '{}'"), ('subtasks', "TEXT DEFAULT '{}'"), ('time_logs', "TEXT DEFAULT '[]'"), ('allowed_roles', "TEXT DEFAULT '[]'"), ('nomenclature', "TEXT DEFAULT '[]'")]:
        try: c.execute(f"ALTER TABLE projects ADD COLUMN {col} {default}")
        except: pass
        
    for col, default in [('signature', "TEXT DEFAULT ''"), ('vacation_until', "TEXT DEFAULT ''"), ('deputy', "TEXT DEFAULT ''"), ('abs_start', "TEXT DEFAULT ''"), ('abs_end', "TEXT DEFAULT ''"), ('abs_type', "TEXT DEFAULT ''"), ('abs_reason', "TEXT DEFAULT ''"), ('is_head', "INTEGER DEFAULT 0"), ('hourly_rate', "INTEGER DEFAULT 500"), ('allowed_legal_entities', "TEXT DEFAULT '[]'"), ('allowed_business_units', "TEXT DEFAULT '[]'"), ('two_factor_enabled', "INTEGER DEFAULT 0"), ('two_factor_secret', "TEXT DEFAULT ''")]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col} {default}")
        except: pass

    for col, default in [('route_name', "TEXT DEFAULT ''"), ('planned_qty', 'REAL DEFAULT 0'), ('produced_qty', 'REAL DEFAULT 0'), ('scrap_qty', 'REAL DEFAULT 0'), ('planned_cost', 'REAL DEFAULT 0'), ('actual_cost', 'REAL DEFAULT 0'), ('labor_hours_plan', 'REAL DEFAULT 0'), ('labor_hours_fact', 'REAL DEFAULT 0')]:
        try: c.execute(f"ALTER TABLE production_orders ADD COLUMN {col} {default}")
        except: pass
    for col, default in [('responsible', "TEXT DEFAULT ''")]:
        for table_name in ("purchase_orders", "sales_documents_extended"):
            try:
                _add_column_if_missing(c, table_name, col, default)
            except Exception:
                pass
    for col, default in [('digest_mode', "TEXT DEFAULT 'instant'"), ('event_types_json', "TEXT DEFAULT '[]'")]:
        try:
            _add_column_if_missing(c, "entity_watchers", col, default)
        except Exception:
            pass
    for col, default in [('legal_entity_id', 'INTEGER DEFAULT 0'), ('business_unit_id', 'INTEGER DEFAULT 0')]:
        for table_name in ("purchase_orders", "sales_documents_extended", "production_orders", "stock_reservations"):
            try:
                _add_column_if_missing(c, table_name, col, default)
            except Exception:
                pass

    try: c.execute("ALTER TABLE documents ADD COLUMN qr_code TEXT DEFAULT ''")
    except: pass

    for col, default in [
        ("kpp", "TEXT DEFAULT ''"),
        ("ogrn", "TEXT DEFAULT ''"),
        ("legal_address", "TEXT DEFAULT ''"),
    ]:
        try:
            _add_column_if_missing(c, "clients", col, default)
        except Exception:
            pass
    
    try: c.execute("ALTER TABLE documents ADD COLUMN project_id INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN contract_id INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN object_id INTEGER DEFAULT 0")
    except: pass

    try: c.execute("ALTER TABLE documents ADD COLUMN parent_id INTEGER DEFAULT 0")
    except: pass

    try: c.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT DEFAULT 'none'")
    except: pass

    try: c.execute("ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'normal'")
    except: pass
    try: c.execute("ALTER TABLE tasks ADD COLUMN project_id INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE tasks ADD COLUMN history TEXT DEFAULT '[]'")
    except: pass
    try: c.execute("ALTER TABLE tasks ADD COLUMN chat TEXT DEFAULT '[]'")
    except: pass
    try: c.execute("ALTER TABLE tasks ADD COLUMN updated_at INTEGER DEFAULT 0")
    except: pass
    for col, default in [
        ("entity_type", "TEXT DEFAULT ''"),
        ("entity_id", "TEXT DEFAULT ''"),
        ("route_rules", "TEXT DEFAULT '[]'"),
        ("route_context", "TEXT DEFAULT '{}'"),
        ("current_stage_key", "TEXT DEFAULT ''"),
        ("current_assignees", "TEXT DEFAULT '[]'"),
        ("approval_state", "TEXT DEFAULT '{}'"),
        ("due_at", "INTEGER DEFAULT 0"),
        ("completed_at", "INTEGER DEFAULT 0"),
        ("required_comment_on_reject", "INTEGER DEFAULT 0"),
        ("required_comment_on_return", "INTEGER DEFAULT 0"),
        ("last_action_at", "INTEGER DEFAULT 0"),
        ("escalation_role", "TEXT DEFAULT ''"),
    ]:
        try:
            _add_column_if_missing(c, "approvals", col, default)
        except Exception:
            pass
    for col, default in [
        ("certificate_id", "INTEGER DEFAULT 0"),
        ("document_revision_id", "INTEGER DEFAULT 0"),
        ("signature_kind", "TEXT DEFAULT 'КЭП'"),
        ("verification_status", "TEXT DEFAULT 'pending'"),
        ("verification_message", "TEXT DEFAULT ''"),
        ("stamp_json", "TEXT DEFAULT '{}'"),
        ("signed_hash", "TEXT DEFAULT ''"),
        ("verification_details", "TEXT DEFAULT '{}'"),
        ("revoked_at", "INTEGER DEFAULT 0"),
        ("legal_force", "TEXT DEFAULT 'unsigned'"),
        ("signature_session_id", "INTEGER DEFAULT 0"),
        ("validation_protocol_id", "INTEGER DEFAULT 0"),
        ("detached_signature_url", "TEXT DEFAULT ''"),
        ("detached_signature_checksum", "TEXT DEFAULT ''"),
        ("signature_format", "TEXT DEFAULT 'CAdES detached'"),
        ("time_stamp_status", "TEXT DEFAULT ''"),
        ("ocsp_status", "TEXT DEFAULT ''"),
        ("crl_status", "TEXT DEFAULT ''"),
    ]:
        try:
            _add_column_if_missing(c, "edo_signature_registry", col, default)
        except Exception:
            pass
    for col, default in [
        ("issued_by", "TEXT DEFAULT ''"),
        ("subject_dn", "TEXT DEFAULT ''"),
        ("algorithm", "TEXT DEFAULT ''"),
        ("key_usage", "TEXT DEFAULT ''"),
        ("verification_url", "TEXT DEFAULT ''"),
        ("revoked_at", "INTEGER DEFAULT 0"),
        ("last_checked_at", "INTEGER DEFAULT 0"),
        ("last_verified_result", "TEXT DEFAULT ''"),
    ]:
        try:
            _add_column_if_missing(c, "edo_certificates", col, default)
        except Exception:
            pass
    for col, default in [
        ("archived_revision_id", "INTEGER DEFAULT 0"),
        ("archive_hash", "TEXT DEFAULT ''"),
        ("archive_payload_json", "TEXT DEFAULT '{}'"),
        ("source_signature_id", "INTEGER DEFAULT 0"),
        ("policy_id", "INTEGER DEFAULT 0"),
        ("access_roles_json", "TEXT DEFAULT '[]'"),
        ("transfer_basis", "TEXT DEFAULT ''"),
        ("destruction_basis", "TEXT DEFAULT ''"),
        ("review_due_at", "TEXT DEFAULT ''"),
    ]:
        try:
            _add_column_if_missing(c, "document_legal_archive", col, default)
        except Exception:
            pass
    for col, default in [
        ("allowed_roles_json", "TEXT DEFAULT '[]'"),
        ("retention_policy_id", "INTEGER DEFAULT 0"),
    ]:
        try:
            _add_column_if_missing(c, "document_classifiers", col, default)
        except Exception:
            pass
    for col, default in [
        ("case_category", "TEXT DEFAULT ''"),
        ("allowed_roles_json", "TEXT DEFAULT '[]'"),
        ("retention_policy_id", "INTEGER DEFAULT 0"),
        ("transfer_basis_default", "TEXT DEFAULT ''"),
        ("destruction_basis_default", "TEXT DEFAULT ''"),
    ]:
        try:
            _add_column_if_missing(c, "document_case_files", col, default)
        except Exception:
            pass
    try: c.execute("ALTER TABLE documents ADD COLUMN priority TEXT DEFAULT 'normal'")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN resolution TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN resolution_author TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN resolution_deadline TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN resolution_assignee TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN resolution_task_id INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN external_sync_id TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN exchange_state TEXT DEFAULT 'draft'")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN sync_comment TEXT DEFAULT ''")
    except: pass
    for col, default in [
        ("sender_name", "TEXT DEFAULT ''"),
        ("recipient_name", "TEXT DEFAULT ''"),
        ("source_number", "TEXT DEFAULT ''"),
        ("source_date", "TEXT DEFAULT ''"),
        ("delivery_method", "TEXT DEFAULT ''"),
        ("signer_name", "TEXT DEFAULT ''"),
        ("executor_name", "TEXT DEFAULT ''"),
    ]:
        try:
            _add_column_if_missing(c, "documents", col, default)
        except Exception:
            pass
    for col, default in [
        ("registration_number", "TEXT DEFAULT ''"),
        ("registration_journal_id", "INTEGER DEFAULT 0"),
        ("classifier_id", "INTEGER DEFAULT 0"),
        ("case_file_id", "INTEGER DEFAULT 0"),
        ("lifecycle_state", "TEXT DEFAULT 'draft'"),
        ("legal_significance", "TEXT DEFAULT 'standard'"),
        ("confidentiality_level", "TEXT DEFAULT 'internal'"),
        ("retention_until", "TEXT DEFAULT ''"),
        ("registered_at", "INTEGER DEFAULT 0"),
        ("registered_by", "TEXT DEFAULT ''"),
        ("document_kind_code", "TEXT DEFAULT ''"),
        ("case_index", "TEXT DEFAULT ''"),
        ("workflow_stage", "TEXT DEFAULT ''"),
        ("workflow_status", "TEXT DEFAULT ''"),
        ("workflow_started_at", "INTEGER DEFAULT 0"),
        ("workflow_completed_at", "INTEGER DEFAULT 0"),
        ("approval_id", "INTEGER DEFAULT 0"),
        ("workflow_block_reason", "TEXT DEFAULT ''"),
    ]:
        try:
            _add_column_if_missing(c, "documents", col, default)
        except Exception:
            pass
    try: c.execute("ALTER TABLE email_messages ADD COLUMN message_id_header TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE email_messages ADD COLUMN reply_to_email TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE sales_documents_extended ADD COLUMN sent_status TEXT DEFAULT 'draft'")
    except: pass
    try: c.execute("ALTER TABLE sales_documents_extended ADD COLUMN recipient_email TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE sales_documents_extended ADD COLUMN sent_at TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE sales_documents_extended ADD COLUMN delivered_at TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE sales_documents_extended ADD COLUMN confirmed_at TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE resource_allocations ADD COLUMN crew_name TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE resource_allocations ADD COLUMN crew_type TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE resource_allocations ADD COLUMN location TEXT DEFAULT ''")
    except: pass
    for table in (
        "hr_leave_requests",
        "hr_timesheet_entries",
        "hr_equipment_requests",
        "hr_substitution_requests",
        "hr_business_trip_requests",
    ):
        try: c.execute(f"ALTER TABLE {table} ADD COLUMN approved_by TEXT DEFAULT ''")
        except: pass
        try: c.execute(f"ALTER TABLE {table} ADD COLUMN updated_at INTEGER DEFAULT 0")
        except: pass
    for col, default in [
        ("warehouse", "TEXT DEFAULT ''"),
        ("bin_code", "TEXT DEFAULT ''"),
        ("batch_code", "TEXT DEFAULT ''"),
        ("serial_no", "TEXT DEFAULT ''"),
        ("fulfilled_qty", "REAL DEFAULT 0"),
        ("released_at", "INTEGER DEFAULT 0"),
        ("released_by", "TEXT DEFAULT ''"),
    ]:
        try:
            _add_column_if_missing(c, "stock_reservations", col, default)
        except Exception:
            pass
    try: c.execute("ALTER TABLE stock_movements ADD COLUMN batch_code TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE stock_movements ADD COLUMN serial_no TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE stock_movements ADD COLUMN reservation_id INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE stock_movements ADD COLUMN document_id INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE stock_movements ADD COLUMN document_type TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE stock_movements ADD COLUMN reason TEXT DEFAULT ''")
    except: pass
    for table in ("inventory_lots", "inventory_documents", "stock_movements", "wms_putaway_tasks", "wms_pick_tasks"):
        try:
            _add_column_if_missing(c, table, "lot_expiration_date", "TEXT DEFAULT ''")
        except Exception:
            pass
    for table in ("inventory_documents", "stock_movements"):
        for col, default in [
            ("unit", "TEXT DEFAULT 'шт'"),
            ("package_code", "TEXT DEFAULT ''"),
            ("package_qty", "REAL DEFAULT 0"),
            ("unit_cost", "REAL DEFAULT 0"),
            ("cost_amount", "REAL DEFAULT 0"),
        ]:
            try:
                _add_column_if_missing(c, table, col, default)
            except Exception:
                pass
    for col, default in [
        ("row_version", "INTEGER DEFAULT 1"),
        ("edit_lock_email", "TEXT DEFAULT ''"),
        ("edit_lock_name", "TEXT DEFAULT ''"),
        ("edit_lock_at", "INTEGER DEFAULT 0"),
    ]:
        try: c.execute(f"ALTER TABLE epl_waybills ADD COLUMN {col} {default}")
        except: pass
    for table in (
        "projects",
        "finance_payments",
        "purchase_orders",
        "sales_documents_extended",
        "production_orders",
        "expense_requests",
        "internal_requests",
        "resource_allocations",
        "service_cases",
        "erp_process_runs",
    ):
        try: c.execute(f"ALTER TABLE {table} ADD COLUMN contract_id INTEGER DEFAULT 0")
        except: pass
        try: c.execute(f"ALTER TABLE {table} ADD COLUMN object_id INTEGER DEFAULT 0")
        except: pass

    for col, default in [
        ('contract_type', "TEXT DEFAULT 'standard'"),
        ('category', "TEXT DEFAULT ''"),
        ('folder', "TEXT DEFAULT 'Все договоры'"),
        ('vat_mode', "TEXT DEFAULT 'with_vat'"),
        ('risk_level', "TEXT DEFAULT 'normal'"),
    ]:
        try:
            _add_column_if_missing(c, "contract_master", col, default)
        except Exception:
            pass

    for col, default in [
        ('legal_entity_id', 'INTEGER DEFAULT 0'),
        ('business_unit_id', 'INTEGER DEFAULT 0'),
        ('treasury_article_id', 'INTEGER DEFAULT 0'),
        ('vat_rate_id', 'INTEGER DEFAULT 0'),
        ('source_document_type', "TEXT DEFAULT ''"),
        ('source_document_id', 'INTEGER DEFAULT 0'),
        ('exchange_state', "TEXT DEFAULT 'draft'"),
        ('external_sync_id', "TEXT DEFAULT ''"),
        ('posted_at', 'INTEGER DEFAULT 0'),
    ]:
        try: c.execute(f"ALTER TABLE finance_payments ADD COLUMN {col} {default}")
        except: pass

    for table in ("sales_documents_extended", "purchase_orders"):
        for col, default in [
            ('legal_entity_id', 'INTEGER DEFAULT 0'),
            ('business_unit_id', 'INTEGER DEFAULT 0'),
            ('vat_rate_id', 'INTEGER DEFAULT 0'),
            ('exchange_state', "TEXT DEFAULT 'draft'"),
            ('external_sync_id', "TEXT DEFAULT ''"),
        ]:
            try: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {default}")
            except: pass
    for col, default in [
        ('supplier_id', 'INTEGER DEFAULT 0'),
        ('planned_unit_price', 'REAL DEFAULT 0'),
        ('planned_delivery_date', "TEXT DEFAULT ''"),
        ('delivered_qty', 'REAL DEFAULT 0'),
        ('request_status', "TEXT DEFAULT 'draft'"),
        ('approval_status', "TEXT DEFAULT 'not_required'"),
        ('schedule_status', "TEXT DEFAULT 'planned'"),
        ('lead_time_days', 'INTEGER DEFAULT 0'),
    ]:
        try:
            _add_column_if_missing(c, "purchase_orders", col, default)
        except Exception:
            pass
    for col, default in [
        ('customer_order_no', "TEXT DEFAULT ''"),
        ('shipment_status', "TEXT DEFAULT 'not_shipped'"),
        ('payment_due_date', "TEXT DEFAULT ''"),
        ('planned_ship_date', "TEXT DEFAULT ''"),
        ('shipped_at', "TEXT DEFAULT ''"),
        ('reserve_status', "TEXT DEFAULT 'none'"),
        ('reserve_qty', 'REAL DEFAULT 0'),
        ('price_list_id', 'INTEGER DEFAULT 0'),
        ('discount_percent', 'REAL DEFAULT 0'),
        ('discount_amount', 'REAL DEFAULT 0'),
    ]:
        try: c.execute(f"ALTER TABLE sales_documents_extended ADD COLUMN {col} {default}")
        except: pass
    for col, default in [
        ('source_type', "TEXT DEFAULT ''"),
        ('source_id', 'INTEGER DEFAULT 0'),
        ('reserved_for_order_no', "TEXT DEFAULT ''"),
    ]:
        try:
            _add_column_if_missing(c, "stock_reservations", col, default)
        except Exception:
            pass
    for table in ("production_orders", "stock_reservations"):
        for col, default in [
            ('exchange_state', "TEXT DEFAULT 'draft'"),
            ('external_sync_id', "TEXT DEFAULT ''"),
        ]:
            try: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {default}")
            except: pass
    for table in ("clients", "inventory_documents"):
        for col, default in [
            ('exchange_state', "TEXT DEFAULT 'draft'"),
            ('external_sync_id', "TEXT DEFAULT ''"),
        ]:
            try:
                _add_column_if_missing(c, table, col, default)
            except Exception:
                pass
    for table in ("warehouse_master", "unit_master", "nomenclature_groups"):
        for col, default in [
            ('external_sync_id', "TEXT DEFAULT ''"),
            ('exchange_state', "TEXT DEFAULT 'draft'"),
        ]:
            try: c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {default}")
            except: pass
    for col, default in [
        ('order_id', 'INTEGER DEFAULT 0'),
        ('version_status', "TEXT DEFAULT 'draft'"),
    ]:
        try: c.execute(f"ALTER TABLE specification_versions ADD COLUMN {col} {default}")
        except: pass
    for col, default in [
        ('code', "TEXT DEFAULT ''"),
        ('comment', "TEXT DEFAULT ''"),
        ('external_sync_id', "TEXT DEFAULT ''"),
        ('exchange_state', "TEXT DEFAULT 'draft'"),
    ]:
        try: c.execute(f"ALTER TABLE bank_accounts ADD COLUMN {col} {default}")
        except: pass

    for table in (
        "nomenclature",
        "clients",
        "inventory_documents",
        "warehouse_master",
        "unit_master",
        "nomenclature_groups",
        "employee_master",
        "position_master",
        "nomenclature_characteristics",
        "storage_cells",
        "income_expense_articles",
        "financial_responsibility_centers",
        "operation_types",
        "bank_accounts",
    ):
        for col, default in [
            ("mdm_status", "TEXT DEFAULT 'draft'"),
            ("lifecycle_state", "TEXT DEFAULT 'draft'"),
            ("version_no", "INTEGER DEFAULT 1"),
            ("quality_score", "INTEGER DEFAULT 0"),
            ("steward_email", "TEXT DEFAULT ''"),
            ("approved_by", "TEXT DEFAULT ''"),
            ("approved_at", "INTEGER DEFAULT 0"),
            ("validation_errors", "TEXT DEFAULT '[]'"),
            ("duplicate_key", "TEXT DEFAULT ''"),
        ]:
            try:
                _add_column_if_missing(c, table, col, default)
            except Exception:
                pass
    try:
        _add_column_if_missing(c, "nomenclature", "is_active", "INTEGER DEFAULT 1")
    except Exception:
        pass

    for col, default in [
        ("idempotency_key", "TEXT DEFAULT ''"),
        ("correlation_id", "TEXT DEFAULT ''"),
        ("attempt_limit", "INTEGER DEFAULT 5"),
        ("priority", "INTEGER DEFAULT 100"),
        ("last_attempt_at", "INTEGER DEFAULT 0"),
        ("processed_at", "INTEGER DEFAULT 0"),
        ("checksum", "TEXT DEFAULT ''"),
        ("consistency_state", "TEXT DEFAULT 'pending'"),
        ("connector_id", "INTEGER DEFAULT 0"),
    ]:
        try:
            _add_column_if_missing(c, "integration_sync_queue", col, default)
        except Exception:
            pass

    # === МИГРАЦИЯ ДЛЯ СКЛАДА ===
    try: c.execute("ALTER TABLE nomenclature ADD COLUMN stock REAL DEFAULT 0")
    except: pass
        
    try: c.execute("ALTER TABLE nomenclature ADD COLUMN currency TEXT DEFAULT 'RUB'")
    except: pass
    try: c.execute("ALTER TABLE nomenclature ADD COLUMN group_name TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE nomenclature ADD COLUMN default_warehouse TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE nomenclature ADD COLUMN external_sync_id TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE nomenclature ADD COLUMN exchange_state TEXT DEFAULT 'draft'")
    except: pass

    c.execute("INSERT OR IGNORE INTO warehouse_policies (id, cost_method, allow_negative_stock, auto_pick_strategy, comment, updated_by, updated_at) VALUES (1, 'fifo', 0, 'best_fit', '', '', 0)")
        
    director_email = DIRECTOR_EMAIL or "ilyu5haosipow@yandex.ru"
    c.execute("SELECT * FROM users WHERE email=?", (director_email,))
    if not c.fetchone():
        default_admin_password = DEFAULT_ADMIN_PASSWORD or secrets.token_urlsafe(10)
        c.execute(
            "INSERT INTO users (email, password, name, role, status, is_head) VALUES (?, ?, ?, ?, ?, ?)",
            (director_email, hash_password(default_admin_password), 'Илья Осипов', 'Директор', 'approved', 1)
        )

    c.execute("SELECT email, password FROM users")
    for email, password in c.fetchall():
        if password and not is_password_hashed(password):
            c.execute("UPDATE users SET password=? WHERE email=?", (hash_password(password), email))

    c.execute("SELECT id, password FROM email_accounts")
    for account_id, password in c.fetchall():
        if password and not is_secret_encrypted(password):
            c.execute("UPDATE email_accounts SET password=? WHERE id=?", (encrypt_secret(password), account_id))

    try:
        applied_migrations = apply_sql_migrations(conn, int(time.time()))
        if applied_migrations:
            logger.info("Applied SQL migrations: %s", ", ".join(applied_migrations))
    except Exception as exc:
        logger.exception("Failed to apply migrations: %s", exc)
        raise

    _promote_postgres_id_columns_to_bigint(conn)
    _ensure_postgres_id_defaults(conn)

    c.execute("SELECT id, smtp_password FROM email_accounts")
    for account_id, smtp_password in c.fetchall():
        if smtp_password and not is_secret_encrypted(smtp_password):
            c.execute("UPDATE email_accounts SET smtp_password=? WHERE id=?", (encrypt_secret(smtp_password), account_id))

    now = int(time.time())
    c.execute("SELECT COUNT(*) FROM legal_entities")
    if c.fetchone()[0] == 0:
        c.execute(
            """
            INSERT INTO legal_entities (name, short_name, inn, kpp, ogrn, vat_mode, default_currency, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            ("ООО Korda CRM", "Korda", "2310999001", "231001001", "1242300000001", "osno", "RUB", now, now),
        )

    c.execute("SELECT COUNT(*) FROM business_units")
    if c.fetchone()[0] == 0:
        c.execute(
            """
            INSERT INTO business_units (legal_entity_id, name, code, manager_name, is_active, created_at, updated_at)
            VALUES (1, ?, ?, ?, 1, ?, ?)
            """,
            ("Центральный офис", "HQ", "Илья Осипов", now, now),
        )

    c.execute("SELECT COUNT(*) FROM treasury_articles")
    if c.fetchone()[0] == 0:
        treasury_seed = [
            ("Поступления от клиентов", "DDS_IN_CLIENT", "incoming", "revenue"),
            ("Авансы от клиентов", "DDS_IN_ADVANCE", "incoming", "advance"),
            ("Оплата поставщикам", "DDS_OUT_SUPPLIER", "outgoing", "supplier"),
            ("Операционные расходы", "DDS_OUT_OPEX", "outgoing", "expense"),
            ("Налоги и сборы", "DDS_OUT_TAX", "outgoing", "tax"),
        ]
        c.executemany(
            "INSERT INTO treasury_articles (name, code, flow_kind, category, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            [(name, code, flow_kind, category, now, now) for name, code, flow_kind, category in treasury_seed],
        )

    c.execute("SELECT COUNT(*) FROM vat_rates")
    if c.fetchone()[0] == 0:
        vat_seed = [("Без НДС", 0, 0), ("НДС 10%", 10, 0), ("НДС 20%", 20, 1)]
        c.executemany(
            "INSERT INTO vat_rates (name, rate, is_default, is_active) VALUES (?, ?, ?, 1)",
            vat_seed,
        )

    c.execute("SELECT COUNT(*) FROM warehouse_master")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO warehouse_master (name, code, is_active, comment, created_at, updated_at) VALUES (?, ?, 1, '', ?, ?)",
            [("Основной склад", "MAIN", now, now), ("Приемка", "RECEIPT", now, now), ("Монтаж", "INSTALL", now, now)],
        )

    c.execute("SELECT COUNT(*) FROM unit_master")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO unit_master (name, code, is_active, comment, created_at, updated_at) VALUES (?, ?, 1, '', ?, ?)",
            [("шт", "PCS", now, now), ("м", "M", now, now), ("кг", "KG", now, now), ("компл", "KIT", now, now)],
        )

    c.execute("SELECT COUNT(*) FROM nomenclature_groups")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO nomenclature_groups (name, code, is_active, comment, created_at, updated_at) VALUES (?, ?, 1, '', ?, ?)",
            [("Материалы", "MAT", now, now), ("Комплектующие", "COMP", now, now), ("Готовая продукция", "FG", now, now)],
        )
    c.execute("SELECT COUNT(*) FROM position_master")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO position_master (name, code, department_name, is_active, comment, created_at, updated_at) VALUES (?, ?, ?, 1, '', ?, ?)",
            [("Менеджер проекта", "PM", "Проекты", now, now), ("Бухгалтер", "ACC", "Финансы", now, now), ("Кладовщик", "WHM", "Склад", now, now)],
        )
    c.execute("SELECT COUNT(*) FROM nomenclature_characteristics")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO nomenclature_characteristics (name, code, characteristic_type, is_active, comment, created_at, updated_at) VALUES (?, ?, ?, 1, '', ?, ?)",
            [("Цвет / исполнение", "CHAR-COLOR", "variant", now, now), ("Размер", "CHAR-SIZE", "dimension", now, now)],
        )
    c.execute("SELECT COUNT(*) FROM storage_cells")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO storage_cells (warehouse_id, name, code, zone_name, is_active, comment, created_at, updated_at) VALUES (?, ?, ?, ?, 1, '', ?, ?)",
            [(1, "A-01", "MAIN-A01", "Основная", now, now), (1, "A-02", "MAIN-A02", "Основная", now, now), (2, "RCV-01", "RECEIPT-01", "Приемка", now, now)],
        )
    c.execute("SELECT COUNT(*) FROM income_expense_articles")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO income_expense_articles (name, code, article_kind, is_active, comment, created_at, updated_at) VALUES (?, ?, ?, 1, '', ?, ?)",
            [("Выручка по договорам", "PL-IN-REVENUE", "income", now, now), ("Материалы и комплектующие", "PL-EX-MAT", "expense", now, now), ("ФОТ", "PL-EX-PAYROLL", "expense", now, now)],
        )
    c.execute("SELECT COUNT(*) FROM financial_responsibility_centers")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO financial_responsibility_centers (name, code, legal_entity_id, business_unit_id, manager_name, is_active, comment, created_at, updated_at) VALUES (?, ?, 1, 1, ?, 1, '', ?, ?)",
            ("Центральный ЦФО", "CFR-HQ", "Илья Осипов", now, now),
        )
    c.execute("SELECT COUNT(*) FROM operation_types")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO operation_types (name, code, module_name, flow_kind, is_active, comment, created_at, updated_at) VALUES (?, ?, ?, ?, 1, '', ?, ?)",
            [("Закупка", "PURCHASE", "supply", "outgoing", now, now), ("Реализация", "SALE", "sales", "incoming", now, now), ("Складское движение", "STOCK_MOVE", "nsi", "internal", now, now)],
        )

    c.execute("SELECT COUNT(*) FROM account_chart")
    if c.fetchone()[0] == 0:
        chart_seed = [
            ("51", "Расчетные счета", "active", "balance", ""),
            ("50", "Касса", "active", "balance", ""),
            ("60.01", "Расчеты с поставщиками", "passive", "balance", "60"),
            ("60.02", "Авансы выданные", "active", "balance", "60"),
            ("62.01", "Расчеты с покупателями", "active", "balance", "62"),
            ("62.02", "Авансы полученные", "passive", "balance", "62"),
            ("68.02", "НДС", "passive", "tax", "68"),
            ("19.03", "НДС по приобретенным ценностям", "active", "tax", "19"),
            ("90.01", "Выручка", "passive", "pnl", "90"),
            ("90.03", "НДС с продаж", "passive", "tax", "90"),
            ("91.02", "Прочие расходы", "active", "pnl", "91"),
            ("26", "Общехозяйственные расходы", "active", "pnl", ""),
            ("10", "Материалы", "active", "balance", ""),
            ("20", "Основное производство", "active", "pnl", ""),
            ("43", "Готовая продукция", "active", "balance", ""),
        ]
        c.executemany(
            "INSERT INTO account_chart (code, name, account_type, kind, parent_code, is_system, is_active) VALUES (?, ?, ?, ?, ?, 1, 1)",
            chart_seed,
        )

    c.executemany(
        "INSERT OR IGNORE INTO account_chart (code, name, account_type, kind, parent_code, is_system, is_active) VALUES (?, ?, ?, ?, ?, 1, 1)",
        [
            ("01", "Основные средства", "active", "balance", ""),
            ("02", "Амортизация ОС", "passive", "balance", ""),
            ("08", "Вложения во внеоборотные активы", "active", "balance", ""),
            ("19", "НДС по приобретенным ценностям", "active", "tax", ""),
            ("23", "Вспомогательные производства", "active", "pnl", ""),
            ("25", "Общепроизводственные расходы", "active", "pnl", ""),
            ("41", "Товары", "active", "balance", ""),
            ("44", "Расходы на продажу", "active", "pnl", ""),
            ("45", "Товары отгруженные", "active", "balance", ""),
            ("52", "Валютные счета", "active", "balance", ""),
            ("55", "Специальные счета в банках", "active", "balance", ""),
            ("57", "Переводы в пути", "active", "balance", ""),
            ("60", "Расчеты с поставщиками", "passive", "balance", ""),
            ("62", "Расчеты с покупателями", "active", "balance", ""),
            ("66", "Краткосрочные кредиты и займы", "passive", "balance", ""),
            ("67", "Долгосрочные кредиты и займы", "passive", "balance", ""),
            ("68", "Расчеты по налогам и сборам", "passive", "tax", ""),
            ("68.04", "Налог на прибыль", "passive", "tax", "68"),
            ("69", "Расчеты по соцстрахованию", "passive", "balance", ""),
            ("70", "Расчеты с персоналом по оплате труда", "passive", "balance", ""),
            ("71", "Расчеты с подотчетными лицами", "active", "balance", ""),
            ("73", "Расчеты с персоналом по прочим операциям", "active", "balance", ""),
            ("76", "Расчеты с разными дебиторами и кредиторами", "active_passive", "balance", ""),
            ("79", "Внутрихозяйственные расчеты", "active_passive", "balance", ""),
            ("84", "Нераспределенная прибыль", "passive", "balance", ""),
            ("90", "Продажи", "active_passive", "pnl", ""),
            ("90.02", "Себестоимость продаж", "active", "pnl", "90"),
            ("90.07", "Расходы на продажу", "active", "pnl", "90"),
            ("91", "Прочие доходы и расходы", "active_passive", "pnl", ""),
            ("91.01", "Прочие доходы", "passive", "pnl", "91"),
            ("91.09", "Сальдо прочих доходов и расходов", "active_passive", "pnl", "91"),
            ("94", "Недостачи и потери от порчи ценностей", "active", "pnl", ""),
            ("97", "Расходы будущих периодов", "active", "balance", ""),
            ("99", "Прибыли и убытки", "active_passive", "pnl", ""),
        ],
    )

    c.execute("SELECT COUNT(*) FROM accounting_posting_templates")
    if c.fetchone()[0] == 0:
        c.executemany(
            """
            INSERT INTO accounting_posting_templates (
                source_type, source_label, account_debit, account_credit, vat_mode, amount_rule, priority, is_active, comment, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            [
                ("finance_payment:incoming:payment", "Входящий платеж", "51", "62.01", "none", "full", 10, "Оплата от покупателя", now, now),
                ("finance_payment:outgoing:payment", "Исходящий платеж", "60.01", "51", "none", "full", 10, "Оплата поставщику", now, now),
                ("purchase_order:base", "Поступление материалов", "10", "60.01", "split_purchase_vat", "base", 20, "База закупки", now, now),
                ("purchase_order:vat", "НДС по закупке", "19.03", "60.01", "split_purchase_vat", "vat", 21, "Входящий НДС", now, now),
                ("sales_document:revenue", "Выручка", "62.01", "90.01", "split_sales_vat", "base", 20, "Отражение выручки", now, now),
                ("sales_document:vat", "НДС с продаж", "90.03", "68.02", "split_sales_vat", "vat", 21, "Исходящий НДС", now, now),
                ("production_order", "Выпуск продукции", "43", "20", "none", "full", 30, "Факт выпуска", now, now),
                ("manual_operation", "Ручная операция", "76", "91.01", "manual", "full", 50, "Свободная типовая операция", now, now),
                ("cash_operation:incoming", "Приход по кассе", "50", "62.01", "none", "full", 40, "Кассовый приход", now, now),
                ("cash_operation:outgoing", "Расход по кассе", "71", "50", "none", "full", 40, "Кассовый расход", now, now),
                ("bank_statement:incoming", "Банковская выписка входящая", "51", "76", "none", "full", 60, "Входящий банк", now, now),
                ("bank_statement:outgoing", "Банковская выписка исходящая", "76", "51", "none", "full", 60, "Исходящий банк", now, now),
            ],
        )

    current_period = datetime.now().strftime("%Y-%m")
    c.execute("SELECT id FROM accounting_periods WHERE period_key=?", (current_period,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO accounting_periods (period_key, status, opened_at, closed_at, closed_by, comment) VALUES (?, 'open', ?, 0, '', '')",
            (current_period, now),
        )

    c.execute("CREATE INDEX IF NOT EXISTS idx_users_status_role ON users(status, role)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_projects_status_manager ON projects(status, manager)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_executor ON tasks(status, executor)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_auth_attempts_action_identifier_created ON auth_attempts(action, identifier, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_field_change_entity_created ON field_change_log(entity_type, entity_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_email_expires ON user_sessions(user_email, expires_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_field_access_rules_lookup ON field_access_rules(role_name, module_name, entity_type, field_name, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_entity_edit_locks_entity ON entity_edit_locks(entity_type, entity_id, locked_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_email_accounts_active_default ON email_accounts(is_active, is_default)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_email_messages_account_flags_created ON email_messages(account_id, is_archived, is_deleted, is_read, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_read_created ON notifications(user_email, user_name, is_read, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_entity_watchers_entity_active ON entity_watchers(entity_type, entity_id, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_entity_watchers_user_updated ON entity_watchers(user_email, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_user_favorite_items_user_entity ON user_favorite_items(user_email, entity_type, entity_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_user_recent_items_user_touched ON user_recent_items(user_email, touched_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_user_saved_filters_user_scope ON user_saved_filters(user_email, filter_scope, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_user_form_drafts_user_updated ON user_form_drafts(user_email, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_error_logs_created_at ON error_logs(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_system_backups_created_at ON system_backups(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_email_attachments_message_id ON email_attachments(message_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_finance_payments_client_status_due ON finance_payments(client_id, status, due_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_finance_payments_project_created ON finance_payments(project_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_purchase_orders_project_status ON purchase_orders(project_id, status, expected_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_documents_project_type ON sales_documents_extended(project_id, doc_type, doc_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_orders_project_stage ON production_orders(project_id, stage, planned_finish)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_stock_reservations_project_article ON stock_reservations(project_id, nomenclature_article, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_expense_requests_project_status ON expense_requests(project_id, status, due_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_internal_requests_project_status ON internal_requests(project_id, status, deadline)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_resource_allocations_project_dates ON resource_allocations(project_id, date_from, date_to)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hr_leave_requests_user_status ON hr_leave_requests(user_email, status, date_from)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hr_timesheet_entries_user_date ON hr_timesheet_entries(user_email, entry_date, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hr_equipment_requests_user_status ON hr_equipment_requests(user_email, status, needed_by)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hr_substitution_requests_user_dates ON hr_substitution_requests(user_email, date_from, date_to)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hr_business_trip_requests_user_dates ON hr_business_trip_requests(user_email, date_from, date_to)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_service_cases_project_status ON service_cases(project_id, status, sla_deadline)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_budget_lines_project_type ON project_budget_lines(project_id, line_type, category)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_stock_movements_article_created ON stock_movements(article, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_stock_movements_document ON stock_movements(document_type, document_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inventory_balances_article_wh_bin ON inventory_balances(article, warehouse, bin_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inventory_lots_article_wh_bin_batch ON inventory_lots(article, warehouse, bin_code, batch_code, serial_no)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inventory_lots_article_expiry ON inventory_lots(article, lot_expiration_date, updated_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inventory_cost_layers_article_remaining ON inventory_cost_layers(article, warehouse, bin_code, batch_code, serial_no, remaining_qty)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inventory_cost_layers_source ON inventory_cost_layers(source_type, source_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_unit_conversions_article_units ON unit_conversions(article, from_unit, to_unit)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_item_packages_article_default ON item_packages(article, is_default, package_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_stock_reservations_article_status_location ON stock_reservations(nomenclature_article, status, warehouse, bin_code, batch_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inventory_documents_type_created ON inventory_documents(doc_type, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_master_active_name ON warehouse_master(is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_unit_master_active_name ON unit_master(is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nomenclature_groups_active_name ON nomenclature_groups(is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nsi_mdm_versions_entity ON nsi_mdm_versions(entity_type, entity_id, version_no DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nsi_mdm_issues_status_entity ON nsi_mdm_issues(status, entity_type, entity_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nsi_mdm_approvals_entity ON nsi_mdm_approvals(entity_type, entity_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nsi_hierarchies_entity_parent ON nsi_hierarchies(entity_type, entity_id, parent_entity_id, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nsi_hierarchies_type_path ON nsi_hierarchies(hierarchy_type, path_code, sort_order)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nsi_external_classifiers_type_code ON nsi_external_classifiers(classifier_type, source_system, external_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nsi_external_classifiers_entity ON nsi_external_classifiers(entity_type, entity_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nsi_duplicate_rules_entity_active ON nsi_duplicate_rules(entity_type, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nsi_bulk_change_requests_status ON nsi_bulk_change_requests(status, entity_type, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_employee_master_active_name ON employee_master(is_active, full_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_employee_master_scope ON employee_master(legal_entity_id, business_unit_id, position_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_position_master_active_name ON position_master(is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_characteristics_active_name ON nomenclature_characteristics(is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_storage_cells_wh_active_name ON storage_cells(warehouse_id, is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_income_expense_articles_kind_active ON income_expense_articles(article_kind, is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cfr_scope_active ON financial_responsibility_centers(legal_entity_id, business_unit_id, is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_operation_types_module_active ON operation_types(module_name, is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_quotes_client_stage_valid ON sales_quotes(client_id, stage, valid_until)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_customer_orders_client_status ON sales_customer_orders(client_id, status, requested_ship_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_customer_orders_project_article ON sales_customer_orders(project_id, article, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_shipments_order_status ON sales_shipments(customer_order_id, status, planned_ship_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_payment_schedules_due_status ON sales_payment_schedules(status, due_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_deal_margins_order_doc ON sales_deal_margins(customer_order_id, sales_document_id, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fulfillment_plan_demand ON fulfillment_plan(demand_type, demand_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fulfillment_plan_article_status ON fulfillment_plan(item_article, status, need_by_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_supply_demand_links_demand ON supply_demand_links(demand_type, demand_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_supply_demand_links_supply ON supply_demand_links(supply_type, supply_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_three_way_matches_purchase_status ON three_way_matches(purchase_id, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_invoice_matching_invoice_status ON invoice_matching_results(invoice_type, invoice_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_plans_period_manager ON sales_plans(period_key, manager_name, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_price_lists_item_status ON price_lists(item_article, status, valid_to)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_client_sales_terms_client_status ON client_sales_terms(client_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_customer_returns_client_status ON customer_returns(client_id, status, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_supplier_registry_active_name ON supplier_registry(is_active, supplier_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_purchase_plans_period_supplier ON purchase_plans(period_key, supplier_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_supplier_delivery_purchase_status ON supplier_delivery_schedules(purchase_id, status, scheduled_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_supplier_returns_supplier_status ON supplier_returns(supplier_id, status, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_supplier_discrepancy_purchase_status ON supplier_discrepancy_acts(purchase_id, status, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inventory_acts_wh_status_created ON inventory_acts(warehouse, status, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inventory_regrading_wh_status_created ON inventory_regrading_docs(warehouse, status, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_quality_wh_status_created ON warehouse_quality_reports(warehouse, status, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_specification_versions_project_created ON specification_versions(project_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_business_objects_client_name ON business_objects(client_id, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_contract_master_project_client ON contract_master(project_id, client_id, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_contract_master_number_status ON contract_master(contract_number, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_contract_master_registry ON contract_master(folder, contract_type, risk_level, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_calendar_events_scope_date ON calendar_events(scope, department, owner_email, event_date, start_time)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crm_leads_stage_next ON crm_leads(stage, responsible, next_action_date, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crm_deals_stage_next ON crm_deals(stage, responsible, next_action_date, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crm_activities_entity ON crm_activities(entity_type, entity_id, due_date, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_outreach_prospects_status_manager_due ON outreach_prospects(status, manager_email, next_action_date, planned_contact_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_outreach_prospects_processed_priority ON outreach_prospects(is_processed, priority, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_outreach_activities_prospect_created ON outreach_activities(prospect_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_outreach_reports_date_manager ON outreach_reports(report_date, manager_email)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_epl_drivers_status_medical ON epl_drivers(status, medical_valid_to)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_epl_vehicles_status_diag ON epl_vehicles(status, diagnostic_valid_to)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_epl_waybills_shift_status ON epl_waybills(shift_date, status, integration_status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_epl_waybills_project_driver_vehicle ON epl_waybills(project_id, driver_id, vehicle_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_epl_waybills_contract_object ON epl_waybills(contract_id, object_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_epl_signatures_waybill_stage ON epl_signatures(waybill_id, stage, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_documents_contract_object ON documents(contract_id, object_id, d_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_erp_process_runs_status_stage ON erp_process_runs(status, current_stage, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_erp_process_runs_project_client ON erp_process_runs(project_id, client_id, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_erp_process_runs_contract_object ON erp_process_runs(contract_id, object_id, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_erp_entity_links_process_created ON erp_entity_links(process_id, created_at ASC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_finance_payments_contract_object ON finance_payments(contract_id, object_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_finance_payments_master_exchange ON finance_payments(legal_entity_id, business_unit_id, treasury_article_id, exchange_state)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_purchase_orders_contract_object ON purchase_orders(contract_id, object_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_purchase_orders_scope_exchange ON purchase_orders(legal_entity_id, business_unit_id, exchange_state, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_documents_contract_object ON sales_documents_extended(contract_id, object_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_documents_exchange_state ON sales_documents_extended(exchange_state, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_documents_scope_exchange ON sales_documents_extended(legal_entity_id, business_unit_id, exchange_state, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_purchase_orders_exchange_state ON purchase_orders(exchange_state, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_orders_contract_object ON production_orders(contract_id, object_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_orders_scope_exchange ON production_orders(legal_entity_id, business_unit_id, exchange_state, stage)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_stock_reservations_scope_exchange ON stock_reservations(legal_entity_id, business_unit_id, exchange_state, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_expense_requests_contract_object ON expense_requests(contract_id, object_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_internal_requests_contract_object ON internal_requests(contract_id, object_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_resource_allocations_contract_object ON resource_allocations(contract_id, object_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_service_cases_contract_object ON service_cases(contract_id, object_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_legal_entities_active_name ON legal_entities(is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_business_units_legal_active ON business_units(legal_entity_id, is_active, name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_treasury_articles_flow_active ON treasury_articles(flow_kind, is_active, code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_vat_rates_default_active ON vat_rates(is_default, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_account_chart_code_active ON account_chart(code, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_periods_status_key ON accounting_periods(status, period_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_entries_period_source ON accounting_entries(period_key, source_type, source_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_entries_project_client ON accounting_entries(project_id, client_id, entry_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_close_runs_period_created ON accounting_period_close_runs(period_key, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_tax_accruals_period_type ON accounting_tax_accruals(period_key, tax_type, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_reports_period_type ON accounting_reporting_snapshots(period_key, report_type, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_edo_operators_scope_status ON accounting_edo_operators(legal_entity_id, business_unit_id, contour_type, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_edo_operators_provider ON accounting_edo_operators(provider_name, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_external_submissions_period_status ON accounting_external_submissions(period_key, submission_status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_external_submissions_operator_period ON accounting_external_submissions(operator_id, report_type, period_key, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_external_submissions_idempotency ON accounting_external_submissions(idempotency_key, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_external_events_submission ON accounting_external_submission_events(submission_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_terminal_sessions_type_status ON terminal_sessions(terminal_type, status, last_seen_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_terminal_scan_events_session_created ON terminal_scan_events(session_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_terminal_scan_events_entity ON terminal_scan_events(entity_type, entity_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_execution_events_operation ON production_execution_events(operation_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_execution_events_order ON production_execution_events(order_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_reconciliation_period_status ON accounting_register_reconciliations(period_key, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_registers_period_source ON accounting_registers(period_key, source_type, source_id, entry_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_registers_account_period ON accounting_registers(account_code, period_key, legal_entity_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_registers_kind_dims ON accounting_registers(register_kind, legal_entity_id, client_id, project_id, period_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tax_registers_period_type ON tax_registers(period_key, tax_type, source_type, source_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_vat_purchase_book_period_status ON vat_purchase_book(period_key, status, source_type, source_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_vat_sales_book_period_status ON vat_sales_book(period_key, status, source_type, source_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_currency_revaluation_period_currency ON currency_revaluation_runs(period_key, currency, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fixed_assets_status_scope ON fixed_assets(status, legal_entity_id, business_unit_id, asset_kind)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_treasury_limits_period_dims ON treasury_limits(period_key, legal_entity_id, business_unit_id, treasury_article_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_reconciliation_acts_client_period ON reconciliation_acts(client_id, period_key, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_field_mappings_entity_active ON integration_field_mappings(system_name, entity_type, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_reconciliation_runs_created ON integration_reconciliation_runs(system_name, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sync_queue_state_retry ON integration_sync_queue(state, next_retry_at, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sync_queue_entity ON integration_sync_queue(entity_type, entity_id, system_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sync_queue_idempotency ON integration_sync_queue(system_name, idempotency_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sync_queue_consistency ON integration_sync_queue(consistency_state, processed_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sync_log_queue_created ON integration_sync_log(queue_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_idempotency_key ON integration_idempotency_keys(system_name, idempotency_key, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_errors_status_created ON integration_error_events(status, severity, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_errors_entity ON integration_error_events(system_name, entity_type, entity_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_consistency_entity ON integration_consistency_checks(system_name, entity_type, entity_id, checked_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_connector_runs_connector ON integration_connector_runs(connector_id, started_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_credentials_connector ON integration_connector_credentials(connector_id, is_active, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_external_objects_entity ON integration_external_objects(system_name, entity_type, entity_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_external_objects_external ON integration_external_objects(system_name, external_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_exchange_messages_queue ON integration_exchange_messages(queue_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_exchange_messages_entity ON integration_exchange_messages(system_name, entity_type, entity_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edo_signature_entity_created ON edo_signature_registry(entity_type, entity_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edo_signature_verify_status ON edo_signature_registry(entity_type, verification_status, signed_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edo_signature_revision ON edo_signature_registry(entity_type, entity_id, document_revision_id, verification_status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_signature_sessions_document ON signature_sessions(document_id, created_at DESC, id DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_signature_sessions_revision ON signature_sessions(file_revision_id, revision_checksum)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_signature_protocols_document ON signature_validation_protocols(document_id, created_at DESC, id DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_signature_protocols_session ON signature_validation_protocols(session_id, created_at DESC, id DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_ocr_jobs_document_status ON document_ocr_jobs(document_id, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_ocr_jobs_template_status ON document_ocr_jobs(template_id, status, processed_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_template_flows_direction_status ON document_template_flows(direction, doc_type, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bank_accounts_legal_active ON bank_accounts(legal_entity_id, is_active, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bank_statement_lines_account_status ON bank_statement_lines(bank_account_id, status, line_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bank_statement_lines_payment ON bank_statement_lines(linked_payment_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posting_templates_source_active ON accounting_posting_templates(source_type, is_active, priority)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_treasury_routes_scope_amount ON treasury_approval_routes(legal_entity_id, business_unit_id, is_active, min_amount, max_amount)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bank_payment_orders_status_date ON bank_payment_orders(status, order_date, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bank_payment_orders_payment ON bank_payment_orders(payment_id, bank_account_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bank_exchange_batches_status_created ON bank_exchange_batches(status, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_background_jobs_group_status_started ON background_job_runs(job_group, status, started_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_recovery_workflows_status_started ON recovery_workflow_runs(status, started_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_telephony_accounts_active ON telephony_accounts(is_active, provider_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_telephony_calls_client_project ON telephony_calls(client_id, project_id, call_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_saved_reports_owner_type ON saved_reports(owner_email, report_type, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_templates_type_status ON document_templates(doc_type, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_versions_doc_created ON document_versions(document_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_file_revisions_doc_uploaded ON document_file_revisions(document_id, uploaded_at DESC, id DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_file_revisions_doc_current ON document_file_revisions(document_id, is_current, revision_status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_file_blobs_revision ON document_file_blobs(file_revision_id, checksum_sha256)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_file_blobs_checksum ON document_file_blobs(checksum_sha256, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_content_index_doc ON document_content_index(document_id, indexed_at DESC, id DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_content_index_revision ON document_content_index(file_revision_id, source_type)")
    try:
        c.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        c.execute("CREATE INDEX IF NOT EXISTS idx_document_content_index_text_trgm ON document_content_index USING gin (content_text gin_trgm_ops)")
    except Exception:
        pass
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_document_content_index_fts ON document_content_index USING gin (search_vector)")
    except Exception:
        pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_linked_tasks_doc_status ON document_linked_tasks(document_id, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edo_certificates_owner_status ON edo_certificates(owner_email, status, valid_to)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edo_certificates_thumbprint_status ON edo_certificates(thumbprint, status, valid_to)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_legal_archive_doc_status ON document_legal_archive(document_id, archive_status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_legal_archive_signature ON document_legal_archive(document_id, source_signature_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_legal_archive_policy_status ON document_legal_archive(policy_id, archive_status, retention_until)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_print_forms_doc_format ON document_print_forms(document_id, format_type, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_retention_policies_scope_active ON document_retention_policies(scope_type, scope_value, is_active, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_retention_actions_doc_created ON document_retention_actions(document_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_packages_status_updated ON document_packages(status, updated_at DESC, id DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_packages_project ON document_packages(project_id, client_id, contract_id, object_id, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_package_items_package ON document_package_items(package_id, order_no, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_package_items_entity ON document_package_items(entity_type, entity_id, package_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_relations_source ON document_relations(source_entity_type, source_entity_id, relation_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_relations_target ON document_relations(target_entity_type, target_entity_id, relation_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_relations_package ON document_relations(package_id, relation_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_case_files_policy_status ON document_case_files(retention_policy_id, status, case_index)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_classifiers_policy_doc_type ON document_classifiers(retention_policy_id, doc_type, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_approvals_status_stage_due ON approvals(status, current_step, due_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_approvals_entity_lookup ON approvals(entity_type, entity_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_approvals_current_assignees ON approvals(status, current_stage_key, last_action_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_approval_route_templates_entity_active ON approval_route_templates(entity_type, is_active, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_approval_action_log_approval_created ON approval_action_log(approval_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_approval_delegations_approval_stage ON approval_delegations(approval_id, stage_key, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_approval_sla_events_approval_created ON approval_sla_events(approval_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_workflow_definitions_entity_active ON workflow_definitions(entity_type, is_active, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_workflow_nodes_definition ON workflow_nodes(definition_id, node_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_workflow_edges_definition_source ON workflow_edges(definition_id, source_node_key, priority)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_workflow_instances_status_entity ON workflow_instances(status, entity_type, entity_id, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_workflow_tokens_instance_status ON workflow_tokens(instance_id, token_status, due_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_workflow_tokens_assignee_status ON workflow_tokens(assignee_name, token_status, due_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_documents_registration_number ON documents(registration_number)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_documents_case_lifecycle ON documents(case_file_id, lifecycle_state, registered_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_documents_workflow_stage_status ON documents(workflow_stage, workflow_status, workflow_started_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_registration_records_doc ON document_registration_records(document_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_classifiers_type_active ON document_classifiers(doc_type, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_case_files_status ON document_case_files(status, case_index)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_lifecycle_doc_created ON document_lifecycle_events(document_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_inbound_updates_entity_created ON integration_inbound_updates(system_name, entity_type, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_integration_connectors_type_status ON integration_connectors(connector_type, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_security_action_policies_role_module ON security_action_policies(role_name, module_name, action_name, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_security_danger_rules_action_active ON security_danger_rules(module_name, action_name, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_operations_order_seq ON production_operations(order_id, sequence_no, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_operations_status_center ON production_operations(status, work_center, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_bom_order_article ON production_bom_items(order_id, article, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_route_templates_order_seq ON production_route_templates(order_id, sequence_no, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_spec_versions_order_created ON specification_versions(order_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_tech_cards_order_center ON production_tech_cards(order_id, work_center, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_shifts_scope_date ON production_shifts(legal_entity_id, business_unit_id, shift_date DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_jobs_order_shift ON production_jobs(order_id, shift_id, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_material_norms_order_article ON production_material_norms(order_id, article)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_labor_norms_order_center ON production_labor_norms(order_id, work_center)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_semifinished_order_status ON production_semifinished(order_id, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_rework_order_status ON production_rework(order_id, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_planning_scenarios_status ON production_planning_scenarios(status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_mrp_runs_scenario_created ON production_mrp_runs(scenario_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bom_master_article_status ON bom_master(item_article, status, legal_entity_id, business_unit_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bom_versions_bom_status ON bom_versions(bom_id, status, valid_from)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_work_centers_scope_status ON work_centers(legal_entity_id, business_unit_id, status, center_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_work_center_calendars_center_date ON work_center_calendars(work_center_id, calendar_date, shift_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_cost_layers_order_operation ON production_cost_layers(production_order_id, operation_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_production_cost_layers_period_type ON production_cost_layers(period_key, layer_type, source_type, source_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wip_register_order_operation ON wip_register(production_order_id, operation_id, period_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wip_register_period_type ON wip_register(period_key, movement_type, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_procurement_requests_scope_status ON procurement_requests(legal_entity_id, business_unit_id, status, required_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_procurement_tenders_request_status ON procurement_tenders(request_id, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_procurement_bids_tender_score ON procurement_tender_bids(tender_id, score DESC, price ASC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_purchase_receipts_purchase_date ON purchase_receipts(purchase_id, receipt_date DESC, id DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_purchase_documents_purchase_type ON purchase_documents(purchase_id, doc_type, status, doc_date DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wms_cells_wh_bin ON wms_cell_profiles(warehouse, bin_code, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wms_putaway_status_target ON wms_putaway_tasks(status, target_warehouse, target_bin)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wms_pick_waves_status ON wms_pick_waves(status, planned_ship_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wms_pick_tasks_wave_status ON wms_pick_tasks(wave_id, status, warehouse, bin_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wms_cycle_counts_scope_status ON wms_cycle_counts(warehouse, zone_name, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wms_cycle_count_lines_count ON wms_cycle_count_lines(count_id, article, warehouse, bin_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_finance_payment_requests_scope_status ON finance_payment_requests(legal_entity_id, business_unit_id, request_status, due_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_treasury_project_limits_period_project ON treasury_project_limits(period_key, project_id, business_unit_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_finance_budgets_type_period ON finance_budgets(budget_type, period_key, project_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_finance_obligations_due_status ON finance_obligations(due_date, status, project_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_finance_cash_gap_period_status ON finance_cash_gap_scenarios(period_key, status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_manual_ops_period_scope ON accounting_manual_operations(period_key, legal_entity_id, business_unit_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounting_debt_adjustments_client_date ON accounting_debt_adjustments(client_id, adjustment_date DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cash_operations_scope_date ON cash_operations(legal_entity_id, business_unit_id, operation_date DESC)")
    conn.commit(); conn.close()


def init_db(max_retries: int = 8, retry_delay: float = 0.35):
    global _INIT_DB_DONE
    if _INIT_DB_DONE:
        return
    with _INIT_DB_LOCK:
        if _INIT_DB_DONE:
            return
        last_error = None
        for attempt in range(max(1, int(max_retries))):
            try:
                _init_db_once()
                _INIT_DB_DONE = True
                return
            except Exception as exc:
                if not _is_database_locked_error(exc):
                    raise
                last_error = exc
                delay = max(0.1, float(retry_delay)) * (attempt + 1)
                logger.warning(
                    "init_db retry %s/%s due to transient database lock; sleeping %.2fs",
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)
        if last_error is not None:
            raise last_error
