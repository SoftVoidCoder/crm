import base64
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin

from database import get_connection
from settings import APP_ENV
from services.integration_sync_service import (
    json_load,
    safe_int,
    sync_entity_meta,
)


ADAPTERS = {
    "finance_payment": {"object_name": "Document_CashFlow", "prefix": "1C-FIN"},
    "sales_document": {"object_name": "Document_CustomerInvoice", "prefix": "1C-SAL"},
    "purchase_order": {"object_name": "Document_PurchaseOrder", "prefix": "1C-PUR"},
    "production_order": {"object_name": "Document_ProductionOrder", "prefix": "1C-PRD"},
    "stock_document": {"object_name": "Document_InventoryMovement", "prefix": "1C-STK"},
    "stock_reservation": {"object_name": "Document_StockReservation", "prefix": "1C-RES"},
    "nomenclature": {"object_name": "Catalog_Nomenclature", "prefix": "1C-NSI"},
    "counterparty": {"object_name": "Catalog_Contractors", "prefix": "1C-CL"},
}


def _stable_json(payload) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checksum(payload) -> str:
    import hashlib

    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _idempotency_key(system_name: str, entity_type: str, entity_id, direction: str, payload: dict, provided: str = "") -> str:
    clean = (provided or "").strip()
    if clean:
        return clean[:180]
    return f"{system_name}:{direction}:{entity_type}:{entity_id}:{_checksum(payload)[:24]}"[:180]


def _row_to_dict(row) -> dict:
    if not row:
        return {}
    try:
        return dict(row)
    except Exception:
        return {}


def _log_sync_event(conn, queue_id: int, system_name: str, entity_type: str, entity_id: int, state: str, message: str, payload: dict | None = None, external_id: str = ""):
    conn.execute(
        """
        INSERT INTO integration_sync_log (
            queue_id, system_name, entity_type, entity_id, state, message, payload, external_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_int(queue_id),
            system_name or "1C",
            entity_type or "",
            safe_int(entity_id),
            state or "",
            (message or "")[:500],
            json.dumps(payload or {}, ensure_ascii=False),
            external_id or "",
            int(time.time()),
        ),
    )


def _upsert_idempotency_record(conn, system_name: str, idempotency_key: str, direction: str, queue_id: int, request_hash: str, status: str, response_payload: dict | None = None):
    if not idempotency_key:
        return 0
    now = int(time.time())
    existing = _row_to_dict(conn.execute(
        """
        SELECT *
        FROM integration_idempotency_keys
        WHERE system_name=? AND idempotency_key=?
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (system_name or "1C", idempotency_key),
    ).fetchone())
    response_json = json.dumps(response_payload or {}, ensure_ascii=False)
    if existing:
        conn.execute(
            """
            UPDATE integration_idempotency_keys
            SET direction=?, queue_id=?, request_hash=?, response_payload=?, status=?, updated_at=?
            WHERE id=?
            """,
            (direction or "outbound", safe_int(queue_id), request_hash or "", response_json, status or "received", now, safe_int(existing.get("id"))),
        )
        return safe_int(existing.get("id"))
    conn.execute(
        """
        INSERT INTO integration_idempotency_keys (
            system_name, idempotency_key, direction, queue_id, request_hash, response_payload, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (system_name or "1C", idempotency_key, direction or "outbound", safe_int(queue_id), request_hash or "", response_json, status or "received", now, now),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0] if False else 0


def _record_integration_error(conn, queue_id: int, system_name: str, entity_type: str, entity_id: int, message: str, payload: dict | None = None, severity: str = "error", error_code: str = "outbound_sync_failed"):
    conn.execute(
        """
        INSERT INTO integration_error_events (
            queue_id, system_name, entity_type, entity_id, severity, error_code, message,
            traceback_text, payload, status, resolved_at, resolved_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, 'open', 0, '', ?)
        """,
        (
            safe_int(queue_id),
            system_name or "1C",
            entity_type or "",
            safe_int(entity_id),
            severity or "error",
            (error_code or "")[:120],
            (message or "")[:1000],
            json.dumps(payload or {}, ensure_ascii=False),
            int(time.time()),
        ),
    )


def _record_consistency(conn, queue_id: int, system_name: str, entity_type: str, entity_id: int, external_id: str, state: str, checksum_local: str, checksum_external: str, details: dict | None = None):
    conn.execute(
        """
        INSERT INTO integration_consistency_checks (
            queue_id, system_name, entity_type, entity_id, external_id, state,
            checksum_local, checksum_external, details_json, checked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_int(queue_id),
            system_name or "1C",
            entity_type or "",
            safe_int(entity_id),
            external_id or "",
            state or "consistent",
            checksum_local or "",
            checksum_external or "",
            json.dumps(details or {}, ensure_ascii=False),
            int(time.time()),
        ),
    )


def _load_connector(conn, connector_id: int = 0) -> dict:
    row = None
    if connector_id:
        row = conn.execute("SELECT * FROM integration_connectors WHERE id=? LIMIT 1", (safe_int(connector_id),)).fetchone()
    if not row:
        row = conn.execute(
            """
            SELECT *
            FROM integration_connectors
            WHERE connector_type='1c' AND status='active'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return {
            "id": 0,
            "connector_type": "1c",
            "provider_name": "Проверочный коннектор 1С",
            "status": "active",
            "settings": {"transport": "demo", "mode": "demo"},
            "scope": {},
        }
    connector = _row_to_dict(row)
    connector["settings"] = json_load(connector.get("settings_json"), {})
    connector["scope"] = json_load(connector.get("scope_json"), {})
    return connector


def _load_credentials(conn, connector_id: int) -> dict:
    if not connector_id:
        return {}
    row = conn.execute(
        """
        SELECT *
        FROM integration_connector_credentials
        WHERE connector_id=? AND is_active=1
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (safe_int(connector_id),),
    ).fetchone()
    return _row_to_dict(row)


def _connector_transport(connector: dict) -> str:
    settings = connector.get("settings") or {}
    return (settings.get("transport") or settings.get("mode") or settings.get("protocol") or "demo").strip().lower()


def _production_1c_requires_real_transport() -> bool:
    return APP_ENV == "production"


def _adapter_for(entity_type: str) -> dict:
    meta = sync_entity_meta(entity_type)
    adapter = ADAPTERS.get(entity_type)
    if not adapter and meta:
        adapter = {"object_name": entity_type, "prefix": meta.get("prefix") or f"1C-{entity_type.upper()[:3]}"}
    return adapter or {}


def _endpoint_for(connector: dict, adapter: dict, transport: str) -> str:
    settings = connector.get("settings") or {}
    base_url = (settings.get("base_url") or settings.get("url") or "").rstrip("/")
    endpoint_template = settings.get("endpoint_template") or settings.get("endpoint") or ""
    object_name = adapter.get("object_name") or "ExchangeObject"
    if endpoint_template:
        endpoint = endpoint_template.format(object_name=object_name, transport=transport)
        return endpoint if endpoint.startswith("http") else urljoin(f"{base_url}/", endpoint.lstrip("/"))
    if transport == "odata":
        return urljoin(f"{base_url}/", f"odata/standard.odata/{object_name}")
    if transport == "json_rpc":
        return urljoin(f"{base_url}/", "jsonrpc")
    if transport == "enterprise_data":
        return urljoin(f"{base_url}/", "hs/EnterpriseDataExchange")
    return urljoin(f"{base_url}/", "hs/korda/exchange")


def _auth_headers(connector: dict, credentials: dict | None = None) -> dict:
    settings = connector.get("settings") or {}
    credentials = credentials or {}
    headers = dict(settings.get("headers") or {})
    credential_kind = (credentials.get("credential_kind") or settings.get("auth_type") or settings.get("credential_kind") or "basic").strip().lower()
    username = credentials.get("username") or settings.get("username") or ""
    secret = (
        credentials.get("secret_value")
        or settings.get("password")
        or settings.get("token")
        or settings.get("api_key")
        or os.getenv(settings.get("secret_env") or "")
        or ""
    )
    if credential_kind in {"bearer", "token", "oauth2"} and secret:
        headers["Authorization"] = f"Bearer {secret}"
    elif credential_kind in {"api_key", "apikey"} and secret:
        headers[settings.get("api_key_header") or "X-API-Key"] = secret
    elif username and secret:
        token = base64.b64encode(f"{username}:{secret}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return headers


def _health_request(connector: dict, transport: str) -> tuple[str, str, dict | None]:
    settings = connector.get("settings") or {}
    base_url = (settings.get("base_url") or settings.get("url") or "").rstrip("/")
    explicit = settings.get("health_url") or settings.get("health_endpoint") or ""
    if explicit:
        return explicit if explicit.startswith("http") else urljoin(f"{base_url}/", explicit.lstrip("/")), (settings.get("health_http_method") or "GET").upper(), None
    if not base_url:
        return "", "GET", None
    if transport == "odata":
        return urljoin(f"{base_url}/", "odata/standard.odata/$metadata"), "GET", None
    if transport == "json_rpc":
        return _endpoint_for(connector, {"object_name": "KordaHealth"}, transport), "POST", {
            "jsonrpc": "2.0",
            "method": settings.get("health_method") or "KordaExchange.Ping",
            "params": {},
            "id": f"health-{int(time.time())}",
        }
    if transport == "enterprise_data":
        return _endpoint_for(connector, {"object_name": "KordaHealth"}, transport), "POST", {
            "format": "EnterpriseData",
            "version": settings.get("enterprise_data_version") or "1.13",
            "objects": [{"type": "KordaHealth", "payload": {"ping": True}}],
        }
    return urljoin(f"{base_url}/", "hs/korda/health"), "GET", None


def _request_body(connector: dict, row: dict, payload: dict, adapter: dict, transport: str) -> dict:
    settings = connector.get("settings") or {}
    entity_type = row.get("entity_type") or ""
    entity_id = row.get("entity_id")
    if transport == "json_rpc":
        return {
            "jsonrpc": "2.0",
            "method": settings.get("method") or "KordaExchange.Upsert",
            "params": {
                "object": adapter.get("object_name") or entity_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload": payload,
            },
            "id": row.get("correlation_id") or row.get("id"),
        }
    if transport == "enterprise_data":
        return {
            "format": "EnterpriseData",
            "version": settings.get("enterprise_data_version") or "1.13",
            "objects": [{
                "type": adapter.get("object_name") or entity_type,
                "local_id": entity_id,
                "payload": payload,
            }],
        }
    return {
        "object": adapter.get("object_name") or entity_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload,
    }


def _extract_external_id(response_payload: dict, default_external_id: str) -> str:
    candidates = [
        response_payload.get("external_id"),
        response_payload.get("externalId"),
        response_payload.get("ref"),
        response_payload.get("id"),
    ]
    result = response_payload.get("result")
    if isinstance(result, dict):
        candidates.extend([result.get("external_id"), result.get("externalId"), result.get("ref"), result.get("id")])
    data = response_payload.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("external_id"), data.get("externalId"), data.get("ref"), data.get("id")])
    for candidate in candidates:
        if str(candidate or "").strip():
            return str(candidate).strip()
    return default_external_id


def _send_to_connector(conn, connector: dict, row: dict, payload: dict, adapter: dict, attempt_no: int) -> dict:
    transport = _connector_transport(connector)
    default_external_id = f"{adapter.get('prefix') or '1C'}-{row.get('entity_id')}"
    endpoint_url = _endpoint_for(connector, adapter, transport)
    request_payload = _request_body(connector, row, payload, adapter, transport)
    message_id = _record_exchange_message(
        conn,
        connector,
        row,
        transport,
        endpoint_url,
        request_payload,
        {},
        0,
        "sending",
        "",
        attempt_no,
    )
    if _production_1c_requires_real_transport() and (transport == "demo" or not endpoint_url.strip()):
        response_payload = {
            "error": "production_1c_connector_required",
            "message": "Боевой коннектор 1С не настроен: тестовый обмен запрещён в боевой среде.",
        }
        _complete_exchange_message(conn, message_id, response_payload, 0, "failed", response_payload["message"])
        return {"ok": False, "external_id": "", "response_payload": response_payload, "http_status": 0, "message_id": message_id, "error": response_payload["message"]}
    if transport == "demo" or not endpoint_url.strip():
        response_payload = {"status": "success", "external_id": default_external_id, "transport": "demo"}
        _complete_exchange_message(conn, message_id, response_payload, 200, "success", "")
        return {"ok": True, "external_id": default_external_id, "response_payload": response_payload, "http_status": 200, "message_id": message_id}

    credentials = _load_credentials(conn, safe_int(connector.get("id")))
    body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Korda-1C-Connector/1.0"}
    headers.update(_auth_headers(connector, credentials))
    timeout = max(3, safe_int((connector.get("settings") or {}).get("timeout_seconds")) or 20)
    try:
        req = urllib.request.Request(endpoint_url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status_code = safe_int(getattr(response, "status", 200)) or 200
        try:
            response_payload = json.loads(response_body) if response_body.strip() else {}
        except Exception:
            response_payload = {"raw": response_body}
        external_id = _extract_external_id(response_payload, default_external_id)
        ok = 200 <= status_code < 300
        _complete_exchange_message(conn, message_id, response_payload, status_code, "success" if ok else "failed", "" if ok else response_body[:500])
        return {"ok": ok, "external_id": external_id, "response_payload": response_payload, "http_status": status_code, "message_id": message_id}
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        response_payload = {"error": response_body[:1000]}
        _complete_exchange_message(conn, message_id, response_payload, safe_int(exc.code), "failed", response_body[:500])
        return {"ok": False, "external_id": "", "response_payload": response_payload, "http_status": safe_int(exc.code), "message_id": message_id, "error": response_body[:500]}
    except Exception as exc:
        _complete_exchange_message(conn, message_id, {"error": str(exc)[:1000]}, 0, "failed", str(exc)[:500])
        return {"ok": False, "external_id": "", "response_payload": {"error": str(exc)[:500]}, "http_status": 0, "message_id": message_id, "error": str(exc)[:500]}


def _record_exchange_message(conn, connector: dict, row: dict, transport: str, endpoint_url: str, request_payload: dict, response_payload: dict, http_status: int, status: str, error_message: str, attempt_no: int) -> int:
    now = int(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO integration_exchange_messages (
            connector_id, queue_id, system_name, entity_type, entity_id, direction, transport, endpoint_url,
            request_payload, response_payload, http_status, status, error_message, idempotency_key,
            correlation_id, attempt_no, created_by, created_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_int(connector.get("id")),
            safe_int(row.get("id")),
            row.get("system_name") or "1C",
            row.get("entity_type") or "",
            str(row.get("entity_id") or ""),
            row.get("direction") or "outbound",
            transport or "demo",
            endpoint_url or "",
            json.dumps(request_payload or {}, ensure_ascii=False),
            json.dumps(response_payload or {}, ensure_ascii=False),
            safe_int(http_status),
            status or "draft",
            (error_message or "")[:1000],
            row.get("idempotency_key") or "",
            row.get("correlation_id") or "",
            max(1, safe_int(attempt_no) or 1),
            row.get("created_by") or "",
            now,
            now if status not in {"draft", "sending"} else 0,
        ),
    )
    return safe_int(cur.lastrowid)


def _complete_exchange_message(conn, message_id: int, response_payload: dict, http_status: int, status: str, error_message: str = ""):
    conn.execute(
        """
        UPDATE integration_exchange_messages
        SET response_payload=?, http_status=?, status=?, error_message=?, completed_at=?
        WHERE id=?
        """,
        (json.dumps(response_payload or {}, ensure_ascii=False), safe_int(http_status), status or "success", (error_message or "")[:1000], int(time.time()), safe_int(message_id)),
    )


def _upsert_external_object(conn, connector: dict, row: dict, external_id: str, checksum_local: str, checksum_external: str, message_id: int, external_url: str = ""):
    now = int(time.time())
    entity_type = row.get("entity_type") or ""
    entity_id = str(row.get("entity_id") or "")
    system_name = row.get("system_name") or "1C"
    existing = _row_to_dict(conn.execute(
        """
        SELECT id
        FROM integration_external_objects
        WHERE system_name=? AND entity_type=? AND entity_id=?
        LIMIT 1
        """,
        (system_name, entity_type, entity_id),
    ).fetchone())
    if existing:
        conn.execute(
            """
            UPDATE integration_external_objects
            SET connector_id=?, external_id=?, external_type=?, external_url=?, exchange_state='synced',
                checksum_local=?, checksum_external=?, last_message_id=?, last_synced_at=?, updated_at=?
            WHERE id=?
            """,
            (
                safe_int(connector.get("id")),
                external_id or "",
                (_adapter_for(entity_type).get("object_name") or entity_type),
                external_url or "",
                checksum_local or "",
                checksum_external or "",
                safe_int(message_id),
                now,
                now,
                safe_int(existing.get("id")),
            ),
        )
        return safe_int(existing.get("id"))
    conn.execute(
        """
        INSERT INTO integration_external_objects (
            system_name, connector_id, entity_type, entity_id, external_id, external_type, external_url,
            exchange_state, checksum_local, checksum_external, last_message_id, last_synced_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'synced', ?, ?, ?, ?, ?, ?)
        """,
        (
            system_name,
            safe_int(connector.get("id")),
            entity_type,
            entity_id,
            external_id or "",
            (_adapter_for(entity_type).get("object_name") or entity_type),
            external_url or "",
            checksum_local or "",
            checksum_external or "",
            safe_int(message_id),
            now,
            now,
            now,
        ),
    )
    return safe_int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]) if False else 0


def _load_entity_row(conn, entity_type: str, entity_id):
    meta = sync_entity_meta(entity_type)
    if not meta:
        return {}
    if entity_type == "nomenclature":
        article = str(entity_id or "").strip()
        row = conn.execute("SELECT * FROM nomenclature WHERE article=? ORDER BY id DESC LIMIT 1", (article,)).fetchone()
        if not row and safe_int(entity_id):
            row = conn.execute("SELECT * FROM nomenclature WHERE id=? ORDER BY id DESC LIMIT 1", (safe_int(entity_id),)).fetchone()
        return _row_to_dict(row)
    return _row_to_dict(conn.execute(
        f"SELECT * FROM {meta['table']} WHERE {meta['id_column']}=? ORDER BY {meta['id_column']} DESC LIMIT 1",
        (entity_id,),
    ).fetchone())


def _set_entity_state(conn, entity_type: str, entity_id, exchange_state: str, external_id: str = ""):
    meta = sync_entity_meta(entity_type)
    if not meta:
        return
    assignments = [f"{meta['state_column']}=?"]
    params = [exchange_state or "draft"]
    if meta.get("external_column"):
        assignments.append(f"{meta['external_column']}=?")
        params.append(external_id or "")
    if meta.get("updated_column"):
        assignments.append(f"{meta['updated_column']}=?")
        params.append(int(time.time()))
    params.append(entity_id)
    conn.execute(f"UPDATE {meta['table']} SET {', '.join(assignments)} WHERE {meta['id_column']}=?", tuple(params))


def _queue_entity_id(entity_type: str, entity: dict, requested_entity_id) -> int:
    if entity_type == "nomenclature":
        return safe_int(entity.get("id") or requested_entity_id)
    return safe_int(entity.get("id") or requested_entity_id)


def enqueue_one_c_export(entity_type: str, entity_id, actor_email: str = "", connector_id: int = 0, provided_idempotency_key: str = "") -> dict:
    conn = get_connection(row_factory=True)
    try:
        meta = sync_entity_meta(entity_type)
        if not meta:
            return {"status": "error", "error": "unsupported_entity", "entity_type": entity_type}
        entity = _load_entity_row(conn, entity_type, entity_id)
        if not entity:
            return {"status": "error", "error": "entity_not_found", "entity_type": entity_type, "entity_id": entity_id}
        payload = meta["builder"](entity)
        queue_entity_id = _queue_entity_id(entity_type, entity, entity_id)
        checksum = _checksum(payload)
        idempotency_key = _idempotency_key("1C", entity_type, queue_entity_id, "outbound", payload, provided_idempotency_key)
        request_hash = _checksum({"entity_type": entity_type, "entity_id": queue_entity_id, "direction": "outbound", "payload": payload})
        now = int(time.time())
        row = conn.execute(
            """
            SELECT id
            FROM integration_sync_queue
            WHERE system_name='1C' AND entity_type=? AND entity_id=? AND state IN ('queued', 'retry', 'failed', 'processing', 'synced')
            ORDER BY id DESC LIMIT 1
            """,
            (entity_type, queue_entity_id),
        ).fetchone()
        if row:
            queue_id = safe_int(row[0])
            conn.execute(
                """
                UPDATE integration_sync_queue
                SET payload=?, state='queued', last_error='', next_retry_at=?, locked_at=0, updated_at=?,
                    idempotency_key=?, checksum=?, consistency_state='pending', connector_id=?,
                    correlation_id=CASE WHEN correlation_id='' THEN ? ELSE correlation_id END
                WHERE id=?
                """,
                (
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                    idempotency_key,
                    checksum,
                    safe_int(connector_id),
                    f"1C-{entity_type}-{queue_entity_id}-{now}",
                    queue_id,
                ),
            )
        else:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO integration_sync_queue (
                    system_name, entity_type, entity_id, direction, payload, mapping_key, state,
                    retry_count, last_error, external_id, next_retry_at, locked_at, created_by, created_at, updated_at,
                    idempotency_key, correlation_id, attempt_limit, priority, last_attempt_at, processed_at,
                    checksum, consistency_state, connector_id
                ) VALUES ('1C', ?, ?, 'outbound', ?, ?, 'queued', 0, '', '', ?, 0, ?, ?, ?, ?, ?, 5, 100, 0, 0, ?, 'pending', ?)
                """,
                (
                    entity_type,
                    queue_entity_id,
                    json.dumps(payload, ensure_ascii=False),
                    f"{entity_type}:{entity_id}",
                    now,
                    actor_email or "",
                    now,
                    now,
                    idempotency_key,
                    f"1C-{entity_type}-{queue_entity_id}-{now}",
                    checksum,
                    safe_int(connector_id),
                ),
            )
            queue_id = safe_int(cur.lastrowid)
        _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, "queued", {"queue_id": queue_id})
        _log_sync_event(conn, queue_id, "1C", entity_type, queue_entity_id, "queued", "Queued for 1C exchange", payload)
        state_entity_id = payload.get("article") if entity_type == "nomenclature" else entity.get(meta["id_column"])
        _set_entity_state(conn, entity_type, state_entity_id, "queued", entity.get(meta.get("external_column") or "", ""))
        conn.commit()
        return {"status": "success", "queue_id": queue_id, "entity_type": entity_type, "entity_id": queue_entity_id}
    finally:
        conn.close()


def _start_connector_run(conn, connector: dict, run_kind: str = "sync") -> int:
    now = int(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO integration_connector_runs (
            connector_id, connector_type, provider_name, run_kind, status, processed, success, failed,
            details_json, started_at, finished_at
        ) VALUES (?, ?, ?, ?, 'running', 0, 0, 0, '{}', ?, 0)
        """,
        (
            safe_int(connector.get("id")),
            connector.get("connector_type") or "1c",
            connector.get("provider_name") or "1C",
            run_kind or "sync",
            now,
        ),
    )
    return safe_int(cur.lastrowid)


def _finish_connector_run(conn, run_id: int, status: str, processed: int, success: int, failed: int, details: dict):
    if not run_id:
        return
    finished_at = int(time.time())
    conn.execute(
        """
        UPDATE integration_connector_runs
        SET status=?, processed=?, success=?, failed=?, details_json=?, finished_at=?
        WHERE id=?
        """,
        (status or "success", safe_int(processed), safe_int(success), safe_int(failed), json.dumps(details or {}, ensure_ascii=False), finished_at, safe_int(run_id)),
    )
    row = _row_to_dict(conn.execute("SELECT connector_id FROM integration_connector_runs WHERE id=?", (safe_int(run_id),)).fetchone())
    connector_id = safe_int(row.get("connector_id"))
    if connector_id:
        conn.execute(
            "UPDATE integration_connectors SET last_sync_at=?, last_error=?, updated_at=? WHERE id=?",
            (finished_at, "" if safe_int(failed) == 0 else f"failed={safe_int(failed)}", finished_at, connector_id),
        )


def process_due_1c_sync_queue(limit: int = 10, epl_processor=None) -> dict:
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        SELECT *
        FROM integration_sync_queue
        WHERE system_name='1C'
          AND state IN ('queued', 'retry')
          AND (next_retry_at=0 OR next_retry_at<=?)
        ORDER BY priority ASC, created_at ASC, id ASC
        LIMIT ?
        """,
        (now, max(1, min(limit, 100))),
    )
    rows = [_row_to_dict(row) for row in c.fetchall()]
    connector = _load_connector(conn, safe_int(rows[0].get("connector_id")) if rows else 0)
    run_id = _start_connector_run(conn, connector) if rows else 0
    processed = 0
    success = 0
    failed = 0
    details = {"transport": _connector_transport(connector), "messages": []}
    try:
        for row in rows:
            processed += 1
            queue_id = safe_int(row.get("id"))
            entity_type = row.get("entity_type") or ""
            entity_id = safe_int(row.get("entity_id"))
            payload = json_load(row.get("payload"), {})
            adapter = _adapter_for(entity_type)
            idempotency_key = (row.get("idempotency_key") or "").strip() or _idempotency_key("1C", entity_type, entity_id, row.get("direction") or "outbound", payload)
            request_hash = _checksum({"entity_type": entity_type, "entity_id": entity_id, "direction": row.get("direction") or "outbound", "payload": payload})
            checksum = (row.get("checksum") or "").strip() or _checksum(payload)
            attempt_limit = max(1, safe_int(row.get("attempt_limit")) or 5)
            attempt_no = safe_int(row.get("retry_count")) + 1
            selected_connector = _load_connector(conn, safe_int(row.get("connector_id")) or safe_int(connector.get("id")))
            c.execute(
                """
                UPDATE integration_sync_queue
                SET state='processing', locked_at=?, last_attempt_at=?, updated_at=?,
                    idempotency_key=?, checksum=?, consistency_state='pending', connector_id=?
                WHERE id=?
                """,
                (now, now, now, idempotency_key, checksum, safe_int(selected_connector.get("id")), queue_id),
            )
            _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, "processing", {"queue_id": queue_id})
            try:
                if entity_type == "epl_waybill" and epl_processor:
                    outcome = epl_processor(conn, row)
                    if outcome.get("state") == "sent":
                        _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, "synced", outcome)
                        success += 1
                        continue
                    raise ValueError(outcome.get("error") or "epl_sync_failed")
                if not adapter:
                    raise ValueError(f"unsupported entity type: {entity_type}")
                send_result = _send_to_connector(conn, selected_connector, {**row, "idempotency_key": idempotency_key}, payload, adapter, attempt_no)
                details["messages"].append({"queue_id": queue_id, "message_id": send_result.get("message_id"), "ok": send_result.get("ok")})
                if not send_result.get("ok"):
                    raise ValueError(send_result.get("error") or f"1C transport failed with HTTP {send_result.get('http_status')}")
                external_id = send_result.get("external_id") or f"{adapter.get('prefix')}-{entity_id}"
                now = int(time.time())
                c.execute(
                    """
                    UPDATE integration_sync_queue
                    SET state='synced', external_id=?, last_error='', locked_at=0,
                        processed_at=?, updated_at=?, checksum=?, consistency_state='consistent', connector_id=?
                    WHERE id=?
                    """,
                    (external_id, now, now, checksum, safe_int(selected_connector.get("id")), queue_id),
                )
                if entity_type == "finance_payment":
                    c.execute(
                        """
                        UPDATE finance_payments
                        SET exchange_state='synced', external_sync_id=?, updated_at=?
                        WHERE id=?
                        """,
                        (external_id, now, entity_id),
                    )
                else:
                    state_entity_id = payload.get("article") if entity_type == "nomenclature" else entity_id
                    _set_entity_state(conn, entity_type, state_entity_id, "synced", external_id)
                _log_sync_event(conn, queue_id, "1C", entity_type, entity_id, "synced", "Synced with 1C connector", payload, external_id)
                _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, "synced", {"queue_id": queue_id, "external_id": external_id})
                _record_consistency(conn, queue_id, "1C", entity_type, entity_id, external_id, "consistent", checksum, checksum, {"source": "one_c_connector", "transport": _connector_transport(selected_connector)})
                _upsert_external_object(conn, selected_connector, row, external_id, checksum, checksum, safe_int(send_result.get("message_id")))
                success += 1
            except Exception as exc:
                retry_count = safe_int(row.get("retry_count")) + 1
                backoff_seconds = min(86400, 30 * (2 ** min(retry_count, 8)))
                next_retry_at = int(time.time()) + backoff_seconds
                failed_state = "failed" if retry_count >= attempt_limit else "retry"
                c.execute(
                    """
                    UPDATE integration_sync_queue
                    SET state=?, retry_count=?, last_error=?, next_retry_at=?, locked_at=0,
                        last_attempt_at=?, updated_at=?, consistency_state=?
                    WHERE id=?
                    """,
                    (failed_state, retry_count, str(exc)[:500], 0 if failed_state == "failed" else next_retry_at, int(time.time()), int(time.time()), "failed" if failed_state == "failed" else "pending", queue_id),
                )
                if entity_type == "finance_payment":
                    c.execute("UPDATE finance_payments SET exchange_state='failed', updated_at=? WHERE id=?", (int(time.time()), entity_id))
                elif entity_type == "epl_waybill":
                    c.execute("UPDATE epl_waybills SET integration_status='error', last_sync_error=?, updated_at=? WHERE id=?", (str(exc)[:500], int(time.time()), entity_id))
                elif sync_entity_meta(entity_type):
                    state_entity_id = payload.get("article") if entity_type == "nomenclature" else entity_id
                    _set_entity_state(conn, entity_type, state_entity_id, "failed", "")
                _log_sync_event(conn, queue_id, "1C", entity_type, entity_id, "failed", str(exc), payload)
                _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, failed_state, {"queue_id": queue_id, "error": str(exc)[:500], "retry_count": retry_count})
                _record_integration_error(conn, queue_id, "1C", entity_type, entity_id, str(exc), payload, "critical" if failed_state == "failed" else "error", "outbound_sync_failed")
                failed += 1
        _finish_connector_run(conn, run_id, "success" if failed == 0 else "partial", processed, success, failed, details)
        conn.commit()
        return {"processed": processed, "success": success, "failed": failed, "connector_id": safe_int(connector.get("id")), "transport": details.get("transport")}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check_one_c_connector_health(connector_id: int = 0) -> dict:
    conn = get_connection(row_factory=True)
    try:
        connector = _load_connector(conn, connector_id)
        transport = _connector_transport(connector)
        endpoint_url, method, payload = _health_request(connector, transport)
        credentials = _load_credentials(conn, safe_int(connector.get("id")))
        run_id = _start_connector_run(conn, connector, "health_check") if safe_int(connector.get("id")) else 0
        if transport == "demo":
            if _production_1c_requires_real_transport():
                result = {
                    "status": "error",
                    "ready": False,
                    "mode": "demo",
                    "connector_id": safe_int(connector.get("id")),
                    "provider_name": connector.get("provider_name") or "Проверочный коннектор 1С",
                    "transport": transport,
                    "endpoint_url": endpoint_url,
                    "message": "Боевой коннектор 1С не настроен: тестовый режим запрещён в боевой среде.",
                }
                _finish_connector_run(conn, run_id, "failed", 1, 0, 1, result)
                conn.commit()
                return result
            result = {
                "status": "success",
                "ready": True,
                "mode": "demo",
                "connector_id": safe_int(connector.get("id")),
                "provider_name": connector.get("provider_name") or "Проверочный коннектор 1С",
                "transport": transport,
                "endpoint_url": endpoint_url,
                "message": "Активен тестовый коннектор; для боевого обмена 1С укажите адрес сервера, транспорт и учётные данные.",
            }
            _finish_connector_run(conn, run_id, "success", 1, 1, 0, result)
            conn.commit()
            return result
        if not endpoint_url:
            result = {
                "status": "error",
                "ready": False,
                "connector_id": safe_int(connector.get("id")),
                "provider_name": connector.get("provider_name") or "1C",
                "transport": transport,
                "endpoint_url": "",
                "message": "Не задан адрес сервера или endpoint проверки для коннектора 1С.",
            }
            _finish_connector_run(conn, run_id, "failed", 1, 0, 1, result)
            conn.commit()
            return result
        headers = {"Accept": "application/json, application/xml, text/plain;q=0.9", "User-Agent": "Korda-1C-Connector/1.0"}
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        headers.update(_auth_headers(connector, credentials))
        timeout = max(3, safe_int((connector.get("settings") or {}).get("timeout_seconds")) or 20)
        started = time.time()
        try:
            req = urllib.request.Request(endpoint_url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_body = response.read(4096).decode("utf-8", errors="replace")
                status_code = safe_int(getattr(response, "status", 200)) or 200
            elapsed_ms = int((time.time() - started) * 1000)
            ok = 200 <= status_code < 300
            result = {
                "status": "success" if ok else "error",
                "ready": ok,
                "connector_id": safe_int(connector.get("id")),
                "provider_name": connector.get("provider_name") or "1C",
                "transport": transport,
                "endpoint_url": endpoint_url,
                "http_status": status_code,
                "elapsed_ms": elapsed_ms,
                "message": "Endpoint 1С доступен" if ok else response_body[:500],
            }
            _finish_connector_run(conn, run_id, "success" if ok else "failed", 1, 1 if ok else 0, 0 if ok else 1, result)
            conn.commit()
            return result
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            result = {
                "status": "error",
                "ready": False,
                "connector_id": safe_int(connector.get("id")),
                "provider_name": connector.get("provider_name") or "1C",
                "transport": transport,
                "endpoint_url": endpoint_url,
                "http_status": safe_int(exc.code),
                "message": response_body[:500],
            }
            _finish_connector_run(conn, run_id, "failed", 1, 0, 1, result)
            conn.commit()
            return result
        except Exception as exc:
            result = {
                "status": "error",
                "ready": False,
                "connector_id": safe_int(connector.get("id")),
                "provider_name": connector.get("provider_name") or "1C",
                "transport": transport,
                "endpoint_url": endpoint_url,
                "http_status": 0,
                "message": str(exc)[:500],
            }
            _finish_connector_run(conn, run_id, "failed", 1, 0, 1, result)
            conn.commit()
            return result
    finally:
        conn.close()


def one_c_readiness_summary() -> dict:
    connectors = list_connectors(20)
    active = [item for item in connectors if (item.get("status") or "").lower() == "active"]
    checks = []
    for connector in active[:5]:
        checks.append(check_one_c_connector_health(safe_int(connector.get("id"))))
    return {
        "status": "success",
        "connectors_total": len(connectors),
        "active_connectors": len(active),
        "ready_connectors": sum(1 for item in checks if item.get("ready")),
        "checks": checks,
        "missing": [] if checks else ["active_1c_connector"],
    }


def create_or_update_connector(data: dict, actor_email: str = "") -> dict:
    conn = get_connection(row_factory=True)
    try:
        now = int(time.time())
        connector_id = safe_int(data.get("id"))
        settings = dict(data.get("settings") or {})
        for key in ("transport", "mode", "base_url", "endpoint_template", "timeout_seconds", "enterprise_data_version", "method"):
            if data.get(key) not in (None, ""):
                settings[key] = data.get(key)
        scope = data.get("scope") or {}
        if connector_id:
            conn.execute(
                """
                UPDATE integration_connectors
                SET provider_name=?, status=?, settings_json=?, scope_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    data.get("provider_name") or "1C",
                    data.get("status") or "active",
                    json.dumps(settings, ensure_ascii=False),
                    json.dumps(scope, ensure_ascii=False),
                    now,
                    connector_id,
                ),
            )
        else:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO integration_connectors (
                    connector_type, provider_name, status, settings_json, scope_json,
                    last_sync_at, last_error, created_by, created_at, updated_at
                ) VALUES ('1c', ?, ?, ?, ?, 0, '', ?, ?, ?)
                """,
                (
                    data.get("provider_name") or "1C",
                    data.get("status") or "active",
                    json.dumps(settings, ensure_ascii=False),
                    json.dumps(scope, ensure_ascii=False),
                    actor_email or "",
                    now,
                    now,
                ),
            )
            connector_id = safe_int(cur.lastrowid)
        conn.commit()
        return {"status": "success", "id": connector_id}
    finally:
        conn.close()


def save_connector_credential(connector_id: int, data: dict, actor_email: str = "") -> dict:
    conn = get_connection(row_factory=True)
    try:
        now = int(time.time())
        conn.execute("UPDATE integration_connector_credentials SET is_active=0, updated_at=? WHERE connector_id=?", (now, safe_int(connector_id)))
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO integration_connector_credentials (
                connector_id, credential_kind, username, secret_value, secret_ref, is_active,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                safe_int(connector_id),
                data.get("credential_kind") or "basic",
                data.get("username") or "",
                data.get("secret_value") or data.get("password") or "",
                data.get("secret_ref") or "",
                actor_email or "",
                now,
                now,
            ),
        )
        credential_id = safe_int(cur.lastrowid)
        conn.commit()
        return {"status": "success", "id": credential_id, "connector_id": safe_int(connector_id)}
    finally:
        conn.close()


def list_connectors(limit: int = 100) -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        rows = [_row_to_dict(row) for row in conn.execute(
            "SELECT * FROM integration_connectors WHERE connector_type='1c' ORDER BY updated_at DESC, id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()]
    finally:
        conn.close()
    for row in rows:
        row["settings"] = json_load(row.get("settings_json"), {})
        row["scope"] = json_load(row.get("scope_json"), {})
        row.pop("settings_json", None)
        row.pop("scope_json", None)
    return rows


def list_exchange_messages(limit: int = 120, entity_type: str = "", entity_id: str = "") -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        params = []
        query = "SELECT * FROM integration_exchange_messages"
        conditions = []
        if entity_type:
            conditions.append("entity_type=?")
            params.append(entity_type)
        if entity_id:
            conditions.append("entity_id=?")
            params.append(str(entity_id))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        rows = [_row_to_dict(row) for row in conn.execute(query, tuple(params)).fetchall()]
    finally:
        conn.close()
    for row in rows:
        row["request_payload"] = json_load(row.get("request_payload"), {})
        row["response_payload"] = json_load(row.get("response_payload"), {})
    return rows


def list_external_objects(limit: int = 120, entity_type: str = "", entity_id: str = "") -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        params = []
        query = "SELECT * FROM integration_external_objects"
        conditions = []
        if entity_type:
            conditions.append("entity_type=?")
            params.append(entity_type)
        if entity_id:
            conditions.append("entity_id=?")
            params.append(str(entity_id))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        return [_row_to_dict(row) for row in conn.execute(query, tuple(params)).fetchall()]
    finally:
        conn.close()
