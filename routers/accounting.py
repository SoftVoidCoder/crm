import json
import os
import re
import time
from datetime import datetime, timedelta

import qrcode
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database import audit_log, get_connection, next_safe_table_id
from permissions import has_permission, require_approved_user
from schemas import EPLDriverData, EPLVehicleData, EPLWaybillActionData, EPLWaybillData, EPLWaybillReopenData

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
QR_UPLOADS_DIR = os.path.join(UPLOADS_DIR, "qr")

EPL_STAGE_ORDER = [
    "medical_pretrip",
    "mechanic_pretrip",
    "dispatcher_departure",
    "dispatcher_return",
    "medical_posttrip",
    "mechanic_posttrip",
]

EPL_STAGE_ALIASES = {
    "pretrip_medical": "medical_pretrip",
    "medical_pretrip": "medical_pretrip",
    "pretrip_technical": "mechanic_pretrip",
    "mechanic_pretrip": "mechanic_pretrip",
    "departure": "dispatcher_departure",
    "dispatcher_departure": "dispatcher_departure",
    "return": "dispatcher_return",
    "dispatcher_return": "dispatcher_return",
    "posttrip_medical": "medical_posttrip",
    "medical_posttrip": "medical_posttrip",
    "posttrip_technical": "mechanic_posttrip",
    "mechanic_posttrip": "mechanic_posttrip",
}

EPL_STAGE_META = {
    "medical_pretrip": {"status_col": "medical_pretrip_status", "time_col": "medical_pretrip_at", "label": "Предрейсовый медосмотр", "default_status": "passed", "default_role": "Медработник"},
    "mechanic_pretrip": {"status_col": "mechanic_pretrip_status", "time_col": "mechanic_pretrip_at", "label": "Предрейсовый техконтроль", "default_status": "passed", "default_role": "Механик"},
    "dispatcher_departure": {"status_col": "dispatcher_departure_status", "time_col": "dispatcher_departure_at", "label": "Выезд на линию", "default_status": "departed", "default_role": "Диспетчер"},
    "dispatcher_return": {"status_col": "dispatcher_return_status", "time_col": "dispatcher_return_at", "label": "Возврат с линии", "default_status": "returned", "default_role": "Диспетчер"},
    "medical_posttrip": {"status_col": "medical_posttrip_status", "time_col": "medical_posttrip_at", "label": "Послерейсовый медосмотр", "default_status": "passed", "default_role": "Медработник"},
    "mechanic_posttrip": {"status_col": "mechanic_posttrip_status", "time_col": "mechanic_posttrip_at", "label": "Послерейсовый техконтроль", "default_status": "passed", "default_role": "Механик"},
}

EPL_STAGE_REQUIREMENTS = {
    "mechanic_pretrip": ["medical_pretrip"],
    "dispatcher_departure": ["medical_pretrip", "mechanic_pretrip"],
    "dispatcher_return": ["dispatcher_departure"],
    "medical_posttrip": ["dispatcher_return"],
    "mechanic_posttrip": ["medical_posttrip"],
}

EPL_INTEGRATION_TERMINAL_STATUSES = {"queued", "sent", "accepted", "error"}
EPL_1C_REQUIRED_STATUSES = {"ready", "queued", "sent", "accepted"}
EPL_SYNC_ACTIVE_QUEUE_STATES = {"queued", "retry", "processing"}
EPL_LOCK_TTL_SECONDS = 15 * 60
EPL_DEMO_CLIENT_NAME = "ООО Демо Транс"
EPL_DEMO_PROJECT_CONTRACT = "2026-ЭПЛ-ДЕМО"
EPL_DEMO_PROJECT_NAME = "Демо: Электронные путевые листы"


def _api_error(status_code: int, error: str, **payload):
    return JSONResponse(status_code=status_code, content={"error": error, **payload})


def _normalize_spaces(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_match(value: str) -> str:
    return _normalize_spaces(value).lower()


def _normalize_stage_name(value: str) -> str:
    stage = _normalize_spaces(value)
    return EPL_STAGE_ALIASES.get(stage, stage)


def _can_access_epl(actor: dict, action: str) -> bool:
    return bool(
        actor
        and (
            has_permission(actor, "finance", action)
            or has_permission(actor, "production", action)
        )
    )


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


def _json_load(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _normalize_email(value: str) -> str:
    return _normalize_spaces(value).lower()


def _today_display() -> str:
    return datetime.now().strftime("%d.%m.%Y")


def _parse_ru_date(value: str):
    value = _normalize_spaces(value)
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _is_expiring(date_text: str, days: int = 30) -> bool:
    dt = _parse_ru_date(date_text)
    if not dt:
        return False
    return dt.date() <= (datetime.now().date() + timedelta(days=days))


def _match_client_id(conn, client_name: str) -> int:
    normalized = _normalize_match(client_name)
    if not normalized:
        return 0
    c = conn.cursor()
    c.execute("SELECT id, name FROM clients")
    for row in c.fetchall():
        row_id = _safe_int(row[0])
        row_name = row[1] if len(row) > 1 else ""
        if _normalize_match(row_name) == normalized:
            return row_id
    return 0


def _resolve_epl_context(conn, project_id: int = 0, client_id: int = 0, contract_id: int = 0, object_id: int = 0) -> dict:
    c = conn.cursor()
    if project_id:
        c.execute("SELECT id, client, contract_id, object_id FROM projects WHERE id=?", (_safe_int(project_id),))
        row = c.fetchone()
        if row:
            row_client = row["client"] if hasattr(row, "keys") else row[1]
            if not client_id:
                client_id = _match_client_id(conn, row_client)
            if not contract_id:
                contract_id = _safe_int(row["contract_id"] if hasattr(row, "keys") else row[2])
            if not object_id:
                object_id = _safe_int(row["object_id"] if hasattr(row, "keys") else row[3])
    if contract_id:
        c.execute("SELECT client_id, object_id FROM contract_master WHERE id=?", (_safe_int(contract_id),))
        row = c.fetchone()
        if row:
            client_id = client_id or _safe_int(row[0])
            object_id = object_id or _safe_int(row[1])
    if object_id and not client_id:
        c.execute("SELECT client_id FROM business_objects WHERE id=?", (_safe_int(object_id),))
        row = c.fetchone()
        if row:
            client_id = _safe_int(row[0])
    return {
        "project_id": _safe_int(project_id),
        "client_id": _safe_int(client_id),
        "contract_id": _safe_int(contract_id),
        "object_id": _safe_int(object_id),
    }


def _waybill_number_fallback() -> str:
    return f"EPL-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _waybill_number_prefix(shift_date: str) -> str:
    dt = _parse_ru_date(shift_date) or datetime.now()
    return f"EPL-{dt.strftime('%Y%m%d')}-"


def _next_waybill_number(conn, shift_date: str, current_waybill_id: int = 0) -> str:
    prefix = _waybill_number_prefix(shift_date)
    c = conn.cursor()
    query = "SELECT number FROM epl_waybills WHERE number LIKE ?"
    params = [f"{prefix}%"]
    if current_waybill_id:
        query += " AND id<>?"
        params.append(_safe_int(current_waybill_id))
    c.execute(query, tuple(params))
    next_seq = 1
    for row in c.fetchall():
        value = row["number"] if hasattr(row, "keys") else row[0]
        match = re.match(rf"^{re.escape(prefix)}(\d+)$", _normalize_spaces(value))
        if match:
            next_seq = max(next_seq, _safe_int(match.group(1)) + 1)
    return f"{prefix}{next_seq:03d}"


def _ensure_waybill_number(conn, raw_number: str, shift_date: str, current_waybill_id: int = 0, existing_number: str = "") -> str:
    normalized = _normalize_spaces(raw_number)
    if normalized:
        return normalized
    existing_number = _normalize_spaces(existing_number)
    if existing_number:
        return existing_number
    return _next_waybill_number(conn, shift_date, current_waybill_id)


def _stage_is_done(stage: str, value: str) -> bool:
    normalized = _normalize_match(value)
    if not normalized:
        return False
    if stage.startswith("dispatcher_"):
        return normalized in {"departed", "returned", "done", "signed", "completed"}
    return normalized in {"passed", "done", "signed", "fit", "approved", "ok"}


def _missing_stage_labels(row: dict) -> list[str]:
    missing = []
    for stage in EPL_STAGE_ORDER:
        meta = EPL_STAGE_META[stage]
        if not _stage_is_done(stage, row.get(meta["status_col"], "")):
            missing.append(meta["label"])
    return missing


def _derive_waybill_status(row: dict) -> str:
    if all(_stage_is_done(stage, row.get(EPL_STAGE_META[stage]["status_col"], "")) for stage in EPL_STAGE_ORDER):
        return "closed"
    if _stage_is_done("dispatcher_return", row.get("dispatcher_return_status", "")):
        return "returned"
    if _stage_is_done("dispatcher_departure", row.get("dispatcher_departure_status", "")):
        return "on_route"
    if _stage_is_done("medical_pretrip", row.get("medical_pretrip_status", "")) and _stage_is_done("mechanic_pretrip", row.get("mechanic_pretrip_status", "")):
        return "ready"
    return "draft"


def _derive_integration_status(row: dict) -> str:
    current = _normalize_match(row.get("integration_status", ""))
    if current in EPL_INTEGRATION_TERMINAL_STATUSES:
        return row.get("integration_status") or "draft"
    if all(_stage_is_done(stage, row.get(EPL_STAGE_META[stage]["status_col"], "")) for stage in EPL_STAGE_ORDER):
        return "ready"
    if _stage_is_done("medical_pretrip", row.get("medical_pretrip_status", "")) and _stage_is_done("mechanic_pretrip", row.get("mechanic_pretrip_status", "")):
        return "collecting"
    return "draft"


def _vehicle_label(row: dict) -> str:
    brand_model = _normalize_spaces(f"{row.get('brand', '')} {row.get('model', '')}")
    reg = _normalize_spaces(row.get("registration_no", ""))
    garage = _normalize_spaces(row.get("garage_number", ""))
    return reg or brand_model or garage or "ТС не выбрано"


def _load_vehicle_row(conn, vehicle_id: int) -> dict | None:
    if not vehicle_id:
        return None
    c = conn.cursor()
    c.execute("SELECT * FROM epl_vehicles WHERE id=?", (_safe_int(vehicle_id),))
    row = c.fetchone()
    return dict(row) if row else None


def _validate_waybill_odometer(conn, vehicle_id: int, odometer_out, odometer_in) -> tuple[dict | None, str]:
    vehicle = _load_vehicle_row(conn, vehicle_id)
    vehicle_odometer = _safe_float((vehicle or {}).get("odometer"))
    odometer_out = _safe_float(odometer_out)
    odometer_in = _safe_float(odometer_in)

    if vehicle and odometer_out <= 0 and vehicle_odometer > 0:
        odometer_out = vehicle_odometer
    if odometer_out < 0 or odometer_in < 0:
        return None, "Показания одометра не могут быть отрицательными."
    if vehicle_odometer > 0 and odometer_out > 0 and odometer_out < vehicle_odometer:
        return None, f"Показание при выезде ({odometer_out:g}) меньше текущего одометра ТС ({vehicle_odometer:g})."
    if odometer_in > 0 and odometer_out > 0 and odometer_in < odometer_out:
        return None, f"Показание при возврате ({odometer_in:g}) не может быть меньше выезда ({odometer_out:g})."

    mileage = 0.0
    if odometer_out > 0 and odometer_in > 0:
        mileage = round(odometer_in - odometer_out, 2)
    return {
        "vehicle": vehicle,
        "odometer_out": odometer_out,
        "odometer_in": odometer_in,
        "mileage": mileage,
    }, ""


def _can_send_waybill_to_1c(row: dict) -> bool:
    return bool(
        _safe_int(row.get("driver_id"))
        and _safe_int(row.get("vehicle_id"))
        and _normalize_spaces(row.get("route_text"))
        and not _missing_stage_labels(row)
    )


def _validate_1c_transition(row: dict, target_status: str) -> tuple[bool, str]:
    target = _normalize_match(target_status)
    if target not in EPL_1C_REQUIRED_STATUSES:
        return True, ""
    if not _safe_int(row.get("driver_id")) or not _safe_int(row.get("vehicle_id")) or not _normalize_spaces(row.get("route_text")):
        return False, "Для передачи в 1С укажи водителя, транспорт и маршрут."
    missing = _missing_stage_labels(row)
    if missing:
        return False, f"Нельзя переводить ЭПЛ в 1С без всех титулов. Не хватает: {', '.join(missing)}."
    return True, ""


def _validate_stage_transition(row: dict, stage: str, status_value: str) -> tuple[bool, str]:
    stage = _normalize_stage_name(stage)
    if stage not in EPL_STAGE_META:
        return False, "Неизвестный этап ЭПЛ."
    if not _stage_is_done(stage, status_value):
        return True, ""
    required_stages = EPL_STAGE_REQUIREMENTS.get(stage, [])
    for required_stage in required_stages:
        required_meta = EPL_STAGE_META[required_stage]
        if not _stage_is_done(required_stage, row.get(required_meta["status_col"], "")):
            return False, f"Сначала закрой этап «{required_meta['label']}»."
    return True, ""


def _sync_vehicle_odometer(conn, vehicle_id: int, odometer_out, odometer_in):
    vehicle_id = _safe_int(vehicle_id)
    if not vehicle_id:
        return
    target_value = max(_safe_float(odometer_out), _safe_float(odometer_in))
    if target_value <= 0:
        return
    c = conn.cursor()
    c.execute("SELECT odometer FROM epl_vehicles WHERE id=?", (vehicle_id,))
    row = c.fetchone()
    current_value = _safe_float(row["odometer"] if hasattr(row, "keys") else (row[0] if row else 0))
    if target_value <= current_value:
        return
    c.execute("UPDATE epl_vehicles SET odometer=?, updated_at=? WHERE id=?", (target_value, int(time.time()), vehicle_id))


def _is_epl_lock_stale(lock_at) -> bool:
    lock_ts = _safe_int(lock_at)
    return lock_ts <= 0 or lock_ts < int(time.time()) - EPL_LOCK_TTL_SECONDS


def _active_epl_lock(row: dict) -> dict:
    email = _normalize_spaces((row or {}).get("edit_lock_email", ""))
    if not email or _is_epl_lock_stale((row or {}).get("edit_lock_at")):
        return {}
    return {
        "email": email,
        "name": _normalize_spaces((row or {}).get("edit_lock_name", "")),
        "at": _safe_int((row or {}).get("edit_lock_at")),
    }


def _validate_waybill_write_access(existing: dict, actor: dict, expected_version: int = 0, allow_integrated_edit: bool = False) -> tuple[bool, str]:
    current_version = max(1, _safe_int((existing or {}).get("row_version")) or 1)
    expected_version = _safe_int(expected_version)
    if expected_version and expected_version != current_version:
        return False, f"Карточка ЭПЛ уже изменилась. Обнови экран и повтори действие. Текущая версия: {current_version}."
    lock_info = _active_epl_lock(existing or {})
    actor_email = _normalize_email((actor or {}).get("email", ""))
    if lock_info and _normalize_email(lock_info.get("email")) != actor_email:
        owner = lock_info.get("name") or lock_info.get("email") or "другого пользователя"
        return False, f"Карточка ЭПЛ сейчас открыта у {owner}. Подожди освобождения или повтори позже."
    if not allow_integrated_edit and _normalize_match((existing or {}).get("integration_status", "")) in {"queued", "sent", "accepted"}:
        return False, "ЭПЛ уже ушёл в контур 1С. Для правок сначала выполни controlled reopen."
    return True, ""


def _epl_sync_payload(row: dict) -> dict:
    payload = _decorate_waybill_row(row)
    return {
        "id": _safe_int(payload.get("id")),
        "row_version": max(1, _safe_int(payload.get("row_version")) or 1),
        "number": _normalize_spaces(payload.get("number", "")),
        "issue_date": _normalize_spaces(payload.get("issue_date", "")),
        "shift_date": _normalize_spaces(payload.get("shift_date", "")),
        "waybill_type": _normalize_spaces(payload.get("waybill_type", "")),
        "status": _normalize_spaces(payload.get("status", "")),
        "integration_status": _normalize_spaces(payload.get("integration_status", "")),
        "route_text": _normalize_spaces(payload.get("route_text", "")),
        "cargo": _normalize_spaces(payload.get("cargo", "")),
        "departure_point": _normalize_spaces(payload.get("departure_point", "")),
        "destination_point": _normalize_spaces(payload.get("destination_point", "")),
        "driver_id": _safe_int(payload.get("driver_id")),
        "driver_name": _normalize_spaces(payload.get("driver_name", "")),
        "vehicle_id": _safe_int(payload.get("vehicle_id")),
        "vehicle_label": _normalize_spaces(payload.get("vehicle_label", "")),
        "project_id": _safe_int(payload.get("project_id")),
        "project_label": _normalize_spaces(payload.get("project_label", "")),
        "client_id": _safe_int(payload.get("client_id")),
        "client_label": _normalize_spaces(payload.get("client_label", "")),
        "operator_name": _normalize_spaces(payload.get("operator_name", "")),
        "external_document_id": _normalize_spaces(payload.get("external_document_id", "")),
        "readiness_percent": _safe_int(payload.get("readiness_percent")),
        "missing_stages": list(payload.get("missing_stages") or []),
    }


def _log_epl_sync_event(conn, queue_id: int, entity_id: int, state: str, message: str, payload: dict | None = None, external_id: str = ""):
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO integration_sync_log (
            queue_id, system_name, entity_type, entity_id, state, message, payload, external_id, created_at
        ) VALUES (?, '1C', 'epl_waybill', ?, ?, ?, ?, ?, ?)
        """,
        (
            _safe_int(queue_id),
            _safe_int(entity_id),
            _normalize_spaces(state),
            (message or "")[:500],
            json.dumps(payload or {}, ensure_ascii=False),
            external_id or "",
            int(time.time()),
        ),
    )


def _latest_epl_queue_row(conn, waybill_id: int) -> dict | None:
    c = conn.cursor()
    c.execute(
        """
        SELECT *
        FROM integration_sync_queue
        WHERE system_name='1C' AND entity_type='epl_waybill' AND entity_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (_safe_int(waybill_id),),
    )
    row = c.fetchone()
    if not row:
        return None
    payload = dict(row)
    payload["payload"] = _json_load(payload.get("payload"), {})
    return payload


def _upsert_epl_sync_job(conn, waybill_row: dict, actor_email: str = "", force_replay: bool = False) -> int:
    entity_id = _safe_int((waybill_row or {}).get("id"))
    if not entity_id:
        return 0
    payload = _epl_sync_payload(waybill_row)
    c = conn.cursor()
    now = int(time.time())
    queue_id = 0
    if not force_replay:
        c.execute(
            """
            SELECT id
            FROM integration_sync_queue
            WHERE system_name='1C'
              AND entity_type='epl_waybill'
              AND entity_id=?
              AND state IN ('queued', 'retry', 'failed', 'processing')
            ORDER BY id DESC
            LIMIT 1
            """,
            (entity_id,),
        )
        row = c.fetchone()
        queue_id = _safe_int(row["id"] if hasattr(row, "keys") else (row[0] if row else 0))
    if queue_id:
        c.execute(
            """
            UPDATE integration_sync_queue
            SET payload=?, state='queued', retry_count=0, last_error='', external_id='', next_retry_at=?, locked_at=0, updated_at=?
            WHERE id=?
            """,
            (json.dumps(payload, ensure_ascii=False), now, now, queue_id),
        )
        _log_epl_sync_event(conn, queue_id, entity_id, "queued", "Очередь обмена ЭПЛ обновлена", payload)
        return queue_id
    c.execute(
        """
        INSERT INTO integration_sync_queue (
            system_name, entity_type, entity_id, direction, payload, mapping_key, state,
            retry_count, last_error, external_id, next_retry_at, locked_at, created_by, created_at, updated_at
        ) VALUES ('1C', 'epl_waybill', ?, 'outbound', ?, ?, 'queued', 0, '', '', ?, 0, ?, ?, ?)
        """,
        (
            entity_id,
            json.dumps(payload, ensure_ascii=False),
            f"epl_waybill:{entity_id}",
            now,
            actor_email or "",
            now,
            now,
        ),
    )
    queue_id = c.lastrowid
    _log_epl_sync_event(conn, queue_id, entity_id, "queued", "ЭПЛ поставлен в очередь 1С", payload)
    return queue_id


def _update_latest_epl_sync_row(conn, waybill_id: int, state: str, last_error: str = "", external_id: str = "") -> int:
    latest = _latest_epl_queue_row(conn, waybill_id)
    if not latest:
        return 0
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        UPDATE integration_sync_queue
        SET state=?, last_error=?, external_id=?, locked_at=0, updated_at=?
        WHERE id=?
        """,
        (_normalize_spaces(state), _normalize_spaces(last_error), _normalize_spaces(external_id), now, _safe_int(latest.get("id"))),
    )
    _log_epl_sync_event(
        conn,
        _safe_int(latest.get("id")),
        _safe_int(waybill_id),
        _normalize_spaces(state),
        _normalize_spaces(last_error) or f"Статус обмена обновлён: {_normalize_spaces(state)}",
        latest.get("payload") if isinstance(latest.get("payload"), dict) else {},
        _normalize_spaces(external_id),
    )
    return _safe_int(latest.get("id"))


def _mark_epl_active_jobs_conflict(conn, waybill_id: int, message: str):
    c = conn.cursor()
    c.execute(
        """
        SELECT *
        FROM integration_sync_queue
        WHERE system_name='1C'
          AND entity_type='epl_waybill'
          AND entity_id=?
          AND state IN ('queued', 'retry', 'processing')
        ORDER BY id DESC
        """,
        (_safe_int(waybill_id),),
    )
    rows = [dict(row) for row in c.fetchall()]
    now = int(time.time())
    for row in rows:
        c.execute(
            """
            UPDATE integration_sync_queue
            SET state='conflict', last_error=?, locked_at=0, updated_at=?
            WHERE id=?
            """,
            ((message or "")[:500], now, _safe_int(row.get("id"))),
        )
        _log_epl_sync_event(conn, _safe_int(row.get("id")), _safe_int(waybill_id), "conflict", message, _json_load(row.get("payload"), {}))


def _decorate_waybill_row(row: dict) -> dict:
    payload = dict(row)
    payload["vehicle_label"] = _vehicle_label(payload)
    payload["driver_label"] = _normalize_spaces(payload.get("driver_name") or "")
    mileage = _safe_float(payload.get("mileage"))
    odometer_out = _safe_float(payload.get("odometer_out"))
    odometer_in = _safe_float(payload.get("odometer_in"))
    if mileage <= 0 and odometer_in >= odometer_out and odometer_out > 0:
        mileage = round(odometer_in - odometer_out, 2)
    payload["mileage"] = mileage
    done_stages = sum(1 for stage in EPL_STAGE_ORDER if _stage_is_done(stage, payload.get(EPL_STAGE_META[stage]["status_col"], "")))
    payload["readiness_percent"] = int(round((done_stages / max(len(EPL_STAGE_ORDER), 1)) * 100))
    payload["missing_stages"] = _missing_stage_labels(payload)
    payload["status"] = _derive_waybill_status(payload)
    payload["integration_status"] = _derive_integration_status(payload)
    payload["is_overdue"] = bool(_parse_ru_date(payload.get("shift_date", "")) and _parse_ru_date(payload.get("shift_date", "")).date() < datetime.now().date() and payload["status"] not in {"closed"})
    payload["project_label"] = _normalize_spaces(payload.get("project_contract") or payload.get("project_name") or "")
    payload["client_label"] = _normalize_spaces(payload.get("client_name") or "")
    payload["can_send_to_1c"] = _can_send_waybill_to_1c(payload)
    payload["row_version"] = max(1, _safe_int(payload.get("row_version")) or 1)
    payload["active_lock"] = _active_epl_lock(payload)
    payload["is_locked"] = bool(payload["active_lock"])
    return payload


def _ensure_demo_client(conn) -> int:
    c = conn.cursor()
    c.execute("SELECT id FROM clients WHERE name=?", (EPL_DEMO_CLIENT_NAME,))
    row = c.fetchone()
    if row:
        return _safe_int(row["id"] if hasattr(row, "keys") else row[0])
    c.execute(
        "INSERT INTO clients (name, inn, contact) VALUES (?, ?, ?)",
        (EPL_DEMO_CLIENT_NAME, "2309988776", "demo.transport@korda.local"),
    )
    client_id = c.lastrowid
    c.execute(
        "INSERT INTO contacts (client_id, name, phone, email, position) VALUES (?, ?, ?, ?, ?)",
        (client_id, "Анна Черкасова", "+7 (918) 555-20-20", "a.cherkasova@korda.local", "Логист"),
    )
    return client_id


def _ensure_demo_project(conn, client_name: str) -> int:
    c = conn.cursor()
    c.execute("SELECT id FROM projects WHERE contract=?", (EPL_DEMO_PROJECT_CONTRACT,))
    row = c.fetchone()
    if row:
        project_id = _safe_int(row["id"] if hasattr(row, "keys") else row[0])
        c.execute(
            "UPDATE projects SET name=?, client=?, manager=?, status=?, budget=?, costs=? WHERE id=?",
            (EPL_DEMO_PROJECT_NAME, client_name, "Логист demo", "active", 1850000, 1240000, project_id),
        )
        return project_id
    project_id = next_safe_table_id(conn, "projects")
    c.execute(
        """
        INSERT INTO projects (id, name, contract, client, manager, status, progress, budget, costs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, EPL_DEMO_PROJECT_NAME, EPL_DEMO_PROJECT_CONTRACT, client_name, "Логист demo", "active", 68, 1850000, 1240000),
    )
    return project_id


def _seed_epl_demo_data(actor_email: str = "", force: bool = False) -> dict:
    now = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        client_id = _ensure_demo_client(conn)
        project_id = _ensure_demo_project(conn, EPL_DEMO_CLIENT_NAME)

        drivers_seed = [
            {
                "full_name": "Сергей Козлов",
                "personnel_number": "DRV-001",
                "license_number": "77 45 123456",
                "license_category": "B, C",
                "phone": "+7 (918) 555-01-01",
                "medical_valid_to": "30.09.2026",
                "signature_profile": "УНЭП",
                "status": "active",
                "comment": "Демо: магистральные маршруты",
            },
            {
                "full_name": "Иван Громов",
                "personnel_number": "DRV-002",
                "license_number": "23 11 654321",
                "license_category": "C, CE",
                "phone": "+7 (918) 555-02-02",
                "medical_valid_to": "15.10.2026",
                "signature_profile": "УКЭП",
                "status": "active",
                "comment": "Демо: закрытые рейсы и обмен с 1С",
            },
            {
                "full_name": "Алексей Назаров",
                "personnel_number": "DRV-003",
                "license_number": "50 09 777555",
                "license_category": "B, C",
                "phone": "+7 (918) 555-03-03",
                "medical_valid_to": "20.08.2026",
                "signature_profile": "УНЭП",
                "status": "active",
                "comment": "Демо: проблемный ЭПЛ без титулов",
            },
        ]
        vehicles_seed = [
            {
                "registration_no": "А777АА123",
                "garage_number": "ТС-001",
                "brand": "КамАЗ",
                "model": "5490",
                "trailer_registration": "АА3212 23",
                "odometer": 125480,
                "carrying_capacity": 20,
                "diagnostic_valid_to": "28.11.2026",
                "insurance_valid_to": "15.12.2026",
                "status": "active",
                "comment": "Демо: рейс в работе",
            },
            {
                "registration_no": "В321ВС123",
                "garage_number": "ТС-002",
                "brand": "ГАЗ",
                "model": "Газель Next",
                "trailer_registration": "",
                "odometer": 78348,
                "carrying_capacity": 3.5,
                "diagnostic_valid_to": "05.10.2026",
                "insurance_valid_to": "02.11.2026",
                "status": "active",
                "comment": "Демо: готово к 1С",
            },
            {
                "registration_no": "С404СС123",
                "garage_number": "ТС-003",
                "brand": "MAN",
                "model": "TGS",
                "trailer_registration": "КМ7845 23",
                "odometer": 45880,
                "carrying_capacity": 18,
                "diagnostic_valid_to": "14.09.2026",
                "insurance_valid_to": "17.11.2026",
                "status": "active",
                "comment": "Демо: архивный принятый ЭПЛ",
            },
        ]
        drivers_map = {}
        vehicles_map = {}

        for item in drivers_seed:
            c.execute("SELECT id FROM epl_drivers WHERE personnel_number=?", (item["personnel_number"],))
            row = c.fetchone()
            if row:
                driver_id = _safe_int(row["id"] if hasattr(row, "keys") else row[0])
                c.execute(
                    """
                    UPDATE epl_drivers
                    SET full_name=?, license_number=?, license_category=?, phone=?, medical_valid_to=?, signature_profile=?, status=?, comment=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        item["full_name"],
                        item["license_number"],
                        item["license_category"],
                        item["phone"],
                        item["medical_valid_to"],
                        item["signature_profile"],
                        item["status"],
                        item["comment"],
                        now,
                        driver_id,
                    ),
                )
            else:
                c.execute(
                    """
                    INSERT INTO epl_drivers (
                        full_name, personnel_number, license_number, license_category, phone, medical_valid_to,
                        signature_profile, status, comment, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["full_name"],
                        item["personnel_number"],
                        item["license_number"],
                        item["license_category"],
                        item["phone"],
                        item["medical_valid_to"],
                        item["signature_profile"],
                        item["status"],
                        item["comment"],
                        actor_email,
                        now,
                        now,
                    ),
                )
                driver_id = c.lastrowid
            drivers_map[item["personnel_number"]] = driver_id

        for item in vehicles_seed:
            c.execute("SELECT id FROM epl_vehicles WHERE registration_no=?", (item["registration_no"],))
            row = c.fetchone()
            if row:
                vehicle_id = _safe_int(row["id"] if hasattr(row, "keys") else row[0])
                c.execute(
                    """
                    UPDATE epl_vehicles
                    SET garage_number=?, brand=?, model=?, trailer_registration=?, odometer=?, carrying_capacity=?,
                        diagnostic_valid_to=?, insurance_valid_to=?, status=?, comment=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        item["garage_number"],
                        item["brand"],
                        item["model"],
                        item["trailer_registration"],
                        item["odometer"],
                        item["carrying_capacity"],
                        item["diagnostic_valid_to"],
                        item["insurance_valid_to"],
                        item["status"],
                        item["comment"],
                        now,
                        vehicle_id,
                    ),
                )
            else:
                c.execute(
                    """
                    INSERT INTO epl_vehicles (
                        registration_no, garage_number, brand, model, trailer_registration, odometer, carrying_capacity,
                        diagnostic_valid_to, insurance_valid_to, status, comment, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["registration_no"],
                        item["garage_number"],
                        item["brand"],
                        item["model"],
                        item["trailer_registration"],
                        item["odometer"],
                        item["carrying_capacity"],
                        item["diagnostic_valid_to"],
                        item["insurance_valid_to"],
                        item["status"],
                        item["comment"],
                        actor_email,
                        now,
                        now,
                    ),
                )
                vehicle_id = c.lastrowid
            vehicles_map[item["registration_no"]] = vehicle_id

        demo_waybills = [
            {
                "number": "EPL-20260412-001",
                "shift_date": "12.04.2026",
                "issue_date": "12.04.2026",
                "waybill_type": "truck",
                "driver_id": drivers_map["DRV-001"],
                "vehicle_id": vehicles_map["А777АА123"],
                "route_text": "Краснодар, склад -> Олимпийский парк, Сочи",
                "cargo": "Кабель и щитовое оборудование",
                "departure_point": "Краснодар, ул. Демонстрационная, 1",
                "destination_point": "Сочи, Олимпийский парк",
                "dispatcher_name": "Наталья Егорова",
                "medical_name": "Ольга Галкина",
                "mechanic_name": "Виктор Ковалев",
                "planned_departure": "12.04.2026 07:30",
                "actual_departure": "12.04.2026 07:42",
                "actual_return": "",
                "odometer_out": 125480,
                "odometer_in": 0,
                "fuel_issued": 120,
                "fuel_returned": 0,
                "integration_status": "collecting",
                "operator_name": "1С-ЭДО",
                "external_document_id": "",
                "last_sync_error": "",
                "notes": "Демо: рейс в работе, можно отметить возврат и закрытие титулов.",
                "stage_values": {
                    "medical_pretrip_status": "passed",
                    "medical_pretrip_at": "12.04.2026 07:05",
                    "mechanic_pretrip_status": "passed",
                    "mechanic_pretrip_at": "12.04.2026 07:18",
                    "dispatcher_departure_status": "departed",
                    "dispatcher_departure_at": "12.04.2026 07:42",
                },
                "signature_log": [
                    ("medical_pretrip", "Медработник", "Ольга Галкина", "УНЭП", "12.04.2026 07:05", "passed", "Допущен к рейсу"),
                    ("mechanic_pretrip", "Механик", "Виктор Ковалев", "УНЭП", "12.04.2026 07:18", "passed", "ТС исправно"),
                    ("dispatcher_departure", "Диспетчер", "Наталья Егорова", "УНЭП", "12.04.2026 07:42", "departed", "Рейс открыт"),
                ],
            },
            {
                "number": "EPL-20260411-002",
                "shift_date": "11.04.2026",
                "issue_date": "11.04.2026",
                "waybill_type": "truck",
                "driver_id": drivers_map["DRV-002"],
                "vehicle_id": vehicles_map["В321ВС123"],
                "route_text": "Краснодар -> Новороссийск -> Краснодар",
                "cargo": "Комплект крепежа и инструмента",
                "departure_point": "Краснодар, склад готовой продукции",
                "destination_point": "Новороссийск, терминал №3",
                "dispatcher_name": "Наталья Егорова",
                "medical_name": "Ольга Галкина",
                "mechanic_name": "Виктор Ковалев",
                "planned_departure": "11.04.2026 06:30",
                "actual_departure": "11.04.2026 06:36",
                "actual_return": "11.04.2026 18:24",
                "odometer_out": 78210,
                "odometer_in": 78348,
                "fuel_issued": 90,
                "fuel_returned": 17,
                "integration_status": "ready",
                "operator_name": "1С-ЭДО",
                "external_document_id": "",
                "last_sync_error": "",
                "notes": "Демо: полностью собранный ЭПЛ, можно поставить в очередь 1С.",
                "stage_values": {
                    "medical_pretrip_status": "passed",
                    "medical_pretrip_at": "11.04.2026 06:05",
                    "mechanic_pretrip_status": "passed",
                    "mechanic_pretrip_at": "11.04.2026 06:14",
                    "dispatcher_departure_status": "departed",
                    "dispatcher_departure_at": "11.04.2026 06:36",
                    "dispatcher_return_status": "returned",
                    "dispatcher_return_at": "11.04.2026 18:24",
                    "medical_posttrip_status": "passed",
                    "medical_posttrip_at": "11.04.2026 18:37",
                    "mechanic_posttrip_status": "passed",
                    "mechanic_posttrip_at": "11.04.2026 18:45",
                },
                "signature_log": [
                    ("medical_pretrip", "Медработник", "Ольга Галкина", "УНЭП", "11.04.2026 06:05", "passed", "Допущен к рейсу"),
                    ("mechanic_pretrip", "Механик", "Виктор Ковалев", "УНЭП", "11.04.2026 06:14", "passed", "ТС исправно"),
                    ("dispatcher_departure", "Диспетчер", "Наталья Егорова", "УНЭП", "11.04.2026 06:36", "departed", "Рейс открыт"),
                    ("dispatcher_return", "Диспетчер", "Наталья Егорова", "УНЭП", "11.04.2026 18:24", "returned", "Возврат подтвержден"),
                    ("medical_posttrip", "Медработник", "Ольга Галкина", "УНЭП", "11.04.2026 18:37", "passed", "Состояние нормальное"),
                    ("mechanic_posttrip", "Механик", "Виктор Ковалев", "УНЭП", "11.04.2026 18:45", "passed", "ТС принято"),
                    ("integration", "Оператор ЭДО", "Демо-контур", "service", "11.04.2026 18:55", "ready", "Готово к передаче"),
                ],
            },
            {
                "number": "EPL-20260410-003",
                "shift_date": "10.04.2026",
                "issue_date": "10.04.2026",
                "waybill_type": "truck",
                "driver_id": drivers_map["DRV-002"],
                "vehicle_id": vehicles_map["С404СС123"],
                "route_text": "Краснодар -> Ростов-на-Дону",
                "cargo": "Комплект климатического оборудования",
                "departure_point": "Краснодар, производственная база",
                "destination_point": "Ростов-на-Дону, объект Северный",
                "dispatcher_name": "Наталья Егорова",
                "medical_name": "Ольга Галкина",
                "mechanic_name": "Виктор Ковалев",
                "planned_departure": "10.04.2026 05:50",
                "actual_departure": "10.04.2026 06:00",
                "actual_return": "10.04.2026 21:10",
                "odometer_out": 45520,
                "odometer_in": 45880,
                "fuel_issued": 170,
                "fuel_returned": 24,
                "integration_status": "accepted",
                "operator_name": "1С-ЭДО",
                "external_document_id": "1C-DEMO-EPD-24001",
                "last_sync_error": "",
                "notes": "Демо: успешно принятый внешний документ.",
                "stage_values": {
                    "medical_pretrip_status": "passed",
                    "medical_pretrip_at": "10.04.2026 05:20",
                    "mechanic_pretrip_status": "passed",
                    "mechanic_pretrip_at": "10.04.2026 05:31",
                    "dispatcher_departure_status": "departed",
                    "dispatcher_departure_at": "10.04.2026 06:00",
                    "dispatcher_return_status": "returned",
                    "dispatcher_return_at": "10.04.2026 21:10",
                    "medical_posttrip_status": "passed",
                    "medical_posttrip_at": "10.04.2026 21:26",
                    "mechanic_posttrip_status": "passed",
                    "mechanic_posttrip_at": "10.04.2026 21:35",
                },
                "signature_log": [
                    ("medical_pretrip", "Медработник", "Ольга Галкина", "УНЭП", "10.04.2026 05:20", "passed", "Допущен к рейсу"),
                    ("mechanic_pretrip", "Механик", "Виктор Ковалев", "УНЭП", "10.04.2026 05:31", "passed", "ТС исправно"),
                    ("dispatcher_departure", "Диспетчер", "Наталья Егорова", "УНЭП", "10.04.2026 06:00", "departed", "Рейс открыт"),
                    ("dispatcher_return", "Диспетчер", "Наталья Егорова", "УНЭП", "10.04.2026 21:10", "returned", "Возврат подтвержден"),
                    ("medical_posttrip", "Медработник", "Ольга Галкина", "УНЭП", "10.04.2026 21:26", "passed", "Состояние нормальное"),
                    ("mechanic_posttrip", "Механик", "Виктор Ковалев", "УНЭП", "10.04.2026 21:35", "passed", "ТС принято"),
                    ("integration", "Оператор ЭДО", "Демо-контур", "service", "10.04.2026 21:42", "accepted", "Документ принят во внешнем контуре"),
                ],
            },
            {
                "number": "EPL-20260412-004",
                "shift_date": "12.04.2026",
                "issue_date": "12.04.2026",
                "waybill_type": "special",
                "driver_id": drivers_map["DRV-003"],
                "vehicle_id": vehicles_map["С404СС123"],
                "route_text": "Краснодар -> объект Север-2",
                "cargo": "Выезд сервисной бригады",
                "departure_point": "Краснодар, сервисный центр",
                "destination_point": "Объект Север-2",
                "dispatcher_name": "Наталья Егорова",
                "medical_name": "Ольга Галкина",
                "mechanic_name": "Виктор Ковалев",
                "planned_departure": "12.04.2026 09:15",
                "actual_departure": "",
                "actual_return": "",
                "odometer_out": 45880,
                "odometer_in": 0,
                "fuel_issued": 60,
                "fuel_returned": 0,
                "integration_status": "draft",
                "operator_name": "1С-ЭДО",
                "external_document_id": "",
                "last_sync_error": "",
                "notes": "Демо: проблемный ЭПЛ без титулов, чтобы проверить блокировку перевода в 1С.",
                "stage_values": {},
                "signature_log": [],
            },
        ]

        created = 0
        updated = 0
        if force:
            for item in demo_waybills:
                c.execute("SELECT id FROM epl_waybills WHERE number=?", (item["number"],))
                row = c.fetchone()
                if row:
                    waybill_id = _safe_int(row["id"] if hasattr(row, "keys") else row[0])
                    c.execute("DELETE FROM epl_signatures WHERE waybill_id=?", (waybill_id,))
                    c.execute("DELETE FROM epl_waybills WHERE id=?", (waybill_id,))

        for item in demo_waybills:
            stage_values = item["stage_values"]
            merged = {**item, **stage_values}
            derived_status = _derive_waybill_status(merged)
            valid, _ = _validate_1c_transition({**merged, "status": derived_status}, item["integration_status"])
            if not valid:
                continue
            c.execute("SELECT id FROM epl_waybills WHERE number=?", (item["number"],))
            row = c.fetchone()
            odometer_data, _ = _validate_waybill_odometer(conn, item["vehicle_id"], item["odometer_out"], item["odometer_in"])
            mileage = _safe_float((odometer_data or {}).get("mileage"))
            final_integration = _derive_integration_status({**merged, "status": derived_status, "integration_status": item["integration_status"]})
            if row:
                waybill_id = _safe_int(row["id"] if hasattr(row, "keys") else row[0])
                c.execute(
                    """
                    UPDATE epl_waybills
                    SET project_id=?, client_id=?, contract_id=?, object_id=?, issue_date=?, shift_date=?, waybill_type=?, driver_id=?, vehicle_id=?,
                        route_text=?, cargo=?, departure_point=?, destination_point=?, dispatcher_name=?, medical_name=?, mechanic_name=?,
                        planned_departure=?, actual_departure=?, actual_return=?, odometer_out=?, odometer_in=?, mileage=?, fuel_issued=?, fuel_returned=?,
                        medical_pretrip_status=?, medical_pretrip_at=?, mechanic_pretrip_status=?, mechanic_pretrip_at=?, dispatcher_departure_status=?, dispatcher_departure_at=?,
                        dispatcher_return_status=?, dispatcher_return_at=?, medical_posttrip_status=?, medical_posttrip_at=?, mechanic_posttrip_status=?, mechanic_posttrip_at=?,
                        status=?, integration_status=?, operator_name=?, external_document_id=?, last_sync_error=?, notes=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        project_id,
                        client_id,
                        0,
                        0,
                        item["issue_date"],
                        item["shift_date"],
                        item["waybill_type"],
                        item["driver_id"],
                        item["vehicle_id"],
                        item["route_text"],
                        item["cargo"],
                        item["departure_point"],
                        item["destination_point"],
                        item["dispatcher_name"],
                        item["medical_name"],
                        item["mechanic_name"],
                        item["planned_departure"],
                        item["actual_departure"],
                        item["actual_return"],
                        _safe_float(item["odometer_out"]),
                        _safe_float(item["odometer_in"]),
                        mileage,
                        _safe_float(item["fuel_issued"]),
                        _safe_float(item["fuel_returned"]),
                        stage_values.get("medical_pretrip_status", ""),
                        stage_values.get("medical_pretrip_at", ""),
                        stage_values.get("mechanic_pretrip_status", ""),
                        stage_values.get("mechanic_pretrip_at", ""),
                        stage_values.get("dispatcher_departure_status", ""),
                        stage_values.get("dispatcher_departure_at", ""),
                        stage_values.get("dispatcher_return_status", ""),
                        stage_values.get("dispatcher_return_at", ""),
                        stage_values.get("medical_posttrip_status", ""),
                        stage_values.get("medical_posttrip_at", ""),
                        stage_values.get("mechanic_posttrip_status", ""),
                        stage_values.get("mechanic_posttrip_at", ""),
                        derived_status,
                        final_integration,
                        item["operator_name"],
                        item["external_document_id"],
                        item["last_sync_error"],
                        item["notes"],
                        now,
                        waybill_id,
                    ),
                )
                c.execute("DELETE FROM epl_signatures WHERE waybill_id=?", (waybill_id,))
                updated += 1
            else:
                c.execute(
                    """
                    INSERT INTO epl_waybills (
                        project_id, client_id, contract_id, object_id, number, issue_date, shift_date, waybill_type, driver_id, vehicle_id,
                        route_text, cargo, departure_point, destination_point, dispatcher_name, medical_name, mechanic_name,
                        planned_departure, actual_departure, actual_return, odometer_out, odometer_in, mileage, fuel_issued, fuel_returned,
                        medical_pretrip_status, medical_pretrip_at, mechanic_pretrip_status, mechanic_pretrip_at, dispatcher_departure_status, dispatcher_departure_at,
                        dispatcher_return_status, dispatcher_return_at, medical_posttrip_status, medical_posttrip_at, mechanic_posttrip_status, mechanic_posttrip_at,
                        status, integration_status, operator_name, external_document_id, last_sync_error, notes, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        client_id,
                        0,
                        0,
                        item["number"],
                        item["issue_date"],
                        item["shift_date"],
                        item["waybill_type"],
                        item["driver_id"],
                        item["vehicle_id"],
                        item["route_text"],
                        item["cargo"],
                        item["departure_point"],
                        item["destination_point"],
                        item["dispatcher_name"],
                        item["medical_name"],
                        item["mechanic_name"],
                        item["planned_departure"],
                        item["actual_departure"],
                        item["actual_return"],
                        _safe_float(item["odometer_out"]),
                        _safe_float(item["odometer_in"]),
                        mileage,
                        _safe_float(item["fuel_issued"]),
                        _safe_float(item["fuel_returned"]),
                        stage_values.get("medical_pretrip_status", ""),
                        stage_values.get("medical_pretrip_at", ""),
                        stage_values.get("mechanic_pretrip_status", ""),
                        stage_values.get("mechanic_pretrip_at", ""),
                        stage_values.get("dispatcher_departure_status", ""),
                        stage_values.get("dispatcher_departure_at", ""),
                        stage_values.get("dispatcher_return_status", ""),
                        stage_values.get("dispatcher_return_at", ""),
                        stage_values.get("medical_posttrip_status", ""),
                        stage_values.get("medical_posttrip_at", ""),
                        stage_values.get("mechanic_posttrip_status", ""),
                        stage_values.get("mechanic_posttrip_at", ""),
                        derived_status,
                        final_integration,
                        item["operator_name"],
                        item["external_document_id"],
                        item["last_sync_error"],
                        item["notes"],
                        actor_email,
                        now,
                        now,
                    ),
                )
                waybill_id = c.lastrowid
                created += 1

            for idx, signature in enumerate(item["signature_log"], start=1):
                c.execute(
                    """
                    INSERT INTO epl_signatures (
                        waybill_id, stage, signer_role, signer_name, signature_kind, signed_at, status_mark, comment, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (waybill_id, signature[0], signature[1], signature[2], signature[3], signature[4], signature[5], signature[6], now + idx),
                )
            _sync_vehicle_odometer(conn, item["vehicle_id"], item["odometer_out"], item["odometer_in"])
            _refresh_waybill_qr(conn, waybill_id)

        conn.commit()
        return {
            "status": "success",
            "created": created,
            "updated": updated,
            "project_id": project_id,
            "client_id": client_id,
        }
    finally:
        conn.close()


def _load_epl_driver_rows() -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM epl_drivers ORDER BY status ASC, full_name ASC, id DESC")
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def _load_epl_vehicle_rows() -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM epl_vehicles ORDER BY status ASC, registration_no ASC, id DESC")
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def _load_epl_waybills_from_conn(conn, waybill_id: int = 0, decorate: bool = True) -> list[dict]:
    c = conn.cursor()
    query = """
        SELECT
            wb.*,
            COALESCE(d.full_name, '') AS driver_name,
            COALESCE(v.registration_no, '') AS registration_no,
            COALESCE(v.garage_number, '') AS garage_number,
            COALESCE(v.brand, '') AS brand,
            COALESCE(v.model, '') AS model,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract,
            COALESCE(cl.name, '') AS client_name
        FROM epl_waybills wb
        LEFT JOIN epl_drivers d ON d.id = wb.driver_id
        LEFT JOIN epl_vehicles v ON v.id = wb.vehicle_id
        LEFT JOIN projects p ON p.id = wb.project_id
        LEFT JOIN clients cl ON cl.id = wb.client_id
    """
    params = []
    if waybill_id:
        query += " WHERE wb.id=?"
        params.append(_safe_int(waybill_id))
    query += " ORDER BY wb.shift_date DESC, wb.created_at DESC, wb.id DESC"
    c.execute(query, tuple(params))
    rows = [dict(row) for row in c.fetchall()]
    if decorate:
        rows = [_decorate_waybill_row(row) for row in rows]
        _attach_epl_sync_meta(conn, rows)
    return rows


def _load_epl_waybill_row_from_conn(conn, waybill_id: int, decorate: bool = True) -> dict | None:
    rows = _load_epl_waybills_from_conn(conn, waybill_id=waybill_id, decorate=decorate)
    return rows[0] if rows else None


def _attach_epl_sync_meta(conn, rows: list[dict]):
    waybill_ids = [_safe_int(row.get("id")) for row in rows if _safe_int(row.get("id"))]
    if not waybill_ids:
        return
    c = conn.cursor()
    placeholders = ", ".join("?" for _ in waybill_ids)
    c.execute(
        f"""
        SELECT *
        FROM integration_sync_queue
        WHERE system_name='1C' AND entity_type='epl_waybill' AND entity_id IN ({placeholders})
        ORDER BY id DESC
        """,
        tuple(waybill_ids),
    )
    latest_map = {}
    for raw in c.fetchall():
        item = dict(raw)
        entity_id = _safe_int(item.get("entity_id"))
        if entity_id in latest_map:
            continue
        item["payload"] = _json_load(item.get("payload"), {})
        latest_map[entity_id] = item
    for row in rows:
        latest = latest_map.get(_safe_int(row.get("id")))
        row["sync_queue_id"] = _safe_int((latest or {}).get("id"))
        row["sync_queue_state"] = _normalize_spaces((latest or {}).get("state", ""))
        row["sync_retry_count"] = _safe_int((latest or {}).get("retry_count"))
        row["sync_next_retry_at"] = _safe_int((latest or {}).get("next_retry_at"))
        row["sync_locked_at"] = _safe_int((latest or {}).get("locked_at"))
        row["sync_last_error"] = _normalize_spaces((latest or {}).get("last_error", "")) or _normalize_spaces(row.get("last_sync_error", ""))
        row["sync_external_id"] = _normalize_spaces((latest or {}).get("external_id", "")) or _normalize_spaces(row.get("external_document_id", ""))
        row["sync_updated_at"] = _safe_int((latest or {}).get("updated_at"))


def _load_epl_waybill_rows(waybill_id: int = 0) -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        return _load_epl_waybills_from_conn(conn, waybill_id=waybill_id, decorate=True)
    finally:
        conn.close()


def _load_epl_signature_rows(waybill_id: int) -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM epl_signatures WHERE waybill_id=? ORDER BY created_at DESC, id DESC", (_safe_int(waybill_id),))
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def _load_epl_sync_queue_rows(limit: int = 120, state: str = "", waybill_id: int = 0) -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        query = """
            SELECT *
            FROM integration_sync_queue
            WHERE system_name='1C' AND entity_type='epl_waybill'
        """
        params = []
        if state:
            query += " AND state=?"
            params.append(_normalize_spaces(state))
        if waybill_id:
            query += " AND entity_id=?"
            params.append(_safe_int(waybill_id))
        query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 300)))
        c.execute(query, tuple(params))
        rows = [dict(row) for row in c.fetchall()]
        for row in rows:
            row["payload"] = _json_load(row.get("payload"), {})
        return rows
    finally:
        conn.close()


def _load_epl_sync_log_rows(waybill_id: int, limit: int = 40) -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT *
            FROM integration_sync_log
            WHERE system_name='1C' AND entity_type='epl_waybill' AND entity_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (_safe_int(waybill_id), max(1, min(limit, 120))),
        )
        rows = [dict(row) for row in c.fetchall()]
        for row in rows:
            row["payload"] = _json_load(row.get("payload"), {})
        return rows
    finally:
        conn.close()


def _load_epl_sync_conflict_rows(limit: int = 120, waybill_id: int = 0) -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        query = """
            SELECT *
            FROM integration_sync_log
            WHERE system_name='1C' AND entity_type='epl_waybill' AND state='conflict'
        """
        params = []
        if waybill_id:
            query += " AND entity_id=?"
            params.append(_safe_int(waybill_id))
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 300)))
        c.execute(query, tuple(params))
        rows = [dict(row) for row in c.fetchall()]
        for row in rows:
            row["payload"] = _json_load(row.get("payload"), {})
        return rows
    finally:
        conn.close()


def _build_epl_qr_payload(row: dict) -> str:
    payload = {
        "type": "epl",
        "id": _safe_int(row.get("id")),
        "number": row.get("number") or "",
        "shift_date": row.get("shift_date") or "",
        "driver": row.get("driver_name") or "",
        "vehicle": _vehicle_label(row),
        "status": row.get("status") or "draft",
        "integration_status": row.get("integration_status") or "draft",
    }
    return json.dumps(payload, ensure_ascii=False)


def _refresh_waybill_qr(conn, waybill_id: int):
    c = conn.cursor()
    payload = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=True)
    if not payload:
        return
    qr_payload = _build_epl_qr_payload(payload)
    os.makedirs(QR_UPLOADS_DIR, exist_ok=True)
    qr_disk_path = os.path.join(QR_UPLOADS_DIR, f"epl_{waybill_id}.png")
    qrcode.make(qr_payload).save(qr_disk_path)
    qr_url = f"/uploads/qr/epl_{waybill_id}.png?v={int(time.time())}"
    c.execute("UPDATE epl_waybills SET qr_code=?, qr_payload=? WHERE id=?", (qr_url, qr_payload, _safe_int(waybill_id)))


def _process_epl_sync_queue_item(conn, row: dict) -> dict:
    row = dict(row or {})
    queue_id = _safe_int(row.get("id"))
    entity_id = _safe_int(row.get("entity_id"))
    now = int(time.time())
    c = conn.cursor()
    payload = row.get("payload")
    if not isinstance(payload, dict):
        payload = _json_load(payload, {})
    waybill = _load_epl_waybill_row_from_conn(conn, entity_id, decorate=False)
    if not waybill:
        message = "ЭПЛ не найден. Документ удалён или недоступен для синка."
        c.execute(
            "UPDATE integration_sync_queue SET state='failed', retry_count=3, last_error=?, locked_at=0, updated_at=? WHERE id=?",
            (message, now, queue_id),
        )
        _log_epl_sync_event(conn, queue_id, entity_id, "failed", message, payload)
        return {"state": "failed", "message": message}
    payload_version = max(1, _safe_int(payload.get("row_version")) or 1)
    current_version = max(1, _safe_int(waybill.get("row_version")) or 1)
    if payload_version != current_version:
        message = "Версия ЭПЛ изменилась после постановки в очередь. Нужен replay из текущей карточки."
        c.execute(
            "UPDATE integration_sync_queue SET state='conflict', last_error=?, locked_at=0, updated_at=? WHERE id=?",
            (message, now, queue_id),
        )
        c.execute(
            "UPDATE epl_waybills SET integration_status='error', last_sync_error=?, updated_at=? WHERE id=?",
            (message, now, entity_id),
        )
        _log_epl_sync_event(conn, queue_id, entity_id, "conflict", message, payload)
        return {"state": "conflict", "message": message}
    external_id = _normalize_spaces(waybill.get("external_document_id")) or f"1C-EPL-{entity_id}"
    c.execute(
        """
        UPDATE integration_sync_queue
        SET state='sent', external_id=?, last_error='', locked_at=0, updated_at=?
        WHERE id=?
        """,
        (external_id, now, queue_id),
    )
    c.execute(
        """
        UPDATE epl_waybills
        SET integration_status='sent', external_document_id=?, last_sync_error='', updated_at=?
        WHERE id=?
        """,
        (external_id, now, entity_id),
    )
    _log_epl_sync_event(conn, queue_id, entity_id, "sent", "ЭПЛ отправлен в 1С", payload, external_id)
    return {"state": "sent", "message": "sent", "external_id": external_id}


def _epl_summary_payload() -> dict:
    drivers = _load_epl_driver_rows()
    vehicles = _load_epl_vehicle_rows()
    waybills = _load_epl_waybill_rows()
    ready_for_1c = [row for row in waybills if row.get("integration_status") == "ready"]
    on_route = [row for row in waybills if row.get("status") == "on_route"]
    blocked = [row for row in waybills if row.get("missing_stages") and row.get("status") in {"draft", "ready", "returned"}]
    sync_queue = _load_epl_sync_queue_rows(200)
    sync_conflicts = [row for row in sync_queue if row.get("state") == "conflict"]
    sync_retry = [row for row in sync_queue if row.get("state") in {"retry", "failed"}]
    alerts = []

    for driver in drivers:
        if _is_expiring(driver.get("medical_valid_to", ""), 30):
            alerts.append({
                "level": "warning",
                "title": f"Водитель: {driver.get('full_name') or 'Без имени'}",
                "text": f"Срок меддопуска истекает: {driver.get('medical_valid_to') or 'не указан'}",
            })
    for vehicle in vehicles:
        if _is_expiring(vehicle.get("diagnostic_valid_to", ""), 30):
            alerts.append({
                "level": "warning",
                "title": f"ТС: {vehicle.get('registration_no') or vehicle.get('garage_number') or 'Без номера'}",
                "text": f"Диагностика/техосмотр истекает: {vehicle.get('diagnostic_valid_to') or 'не указан'}",
            })
    for row in waybills:
        if row.get("is_overdue") and row.get("missing_stages"):
            alerts.append({
                "level": "danger",
                "title": f"ЭПЛ {row.get('number') or row.get('id')}",
                "text": f"Не закрыты титулы: {', '.join(row.get('missing_stages')[:3])}",
            })

    return {
        "metrics": {
            "waybills_total": len(waybills),
            "on_route": len(on_route),
            "ready_for_1c": len(ready_for_1c),
            "blocked": len(blocked),
            "sync_retry": len(sync_retry),
            "sync_conflicts": len(sync_conflicts),
            "drivers_active": len([row for row in drivers if row.get("status") == "active"]),
            "vehicles_active": len([row for row in vehicles if row.get("status") == "active"]),
        },
        "recent": waybills[:10],
        "alerts": alerts[:8],
        "drivers": drivers[:6],
        "vehicles": vehicles[:6],
    }


@router.get("/api/epl/summary")
def get_epl_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _epl_summary_payload()


@router.post("/api/epl/demo-seed")
def seed_epl_demo(request: Request, force: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "create"):
        return {"error": "forbidden"}
    result = _seed_epl_demo_data(actor.get("email", ""), bool(force))
    audit_log("epl_demo_seed", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_demo", entity_id=str(result.get("project_id") or 0), details={"force": bool(force), "created": result.get("created"), "updated": result.get("updated")})
    return result


@router.get("/api/epl/drivers")
def get_epl_drivers(request: Request, status: str = ""):
    actor = require_approved_user(request)
    if not _can_access_epl(actor, "read"):
        return _api_error(403, "forbidden")
    rows = _load_epl_driver_rows()
    if status:
        rows = [row for row in rows if row.get("status") == status]
    return rows


@router.post("/api/epl/drivers")
def create_epl_driver(data: EPLDriverData, request: Request):
    actor = require_approved_user(request)
    if not _can_access_epl(actor, "create"):
        return _api_error(403, "forbidden")
    now = int(time.time())
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO epl_drivers (
                full_name, personnel_number, license_number, license_category, phone, medical_valid_to,
                signature_profile, status, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _normalize_spaces(data.full_name),
                _normalize_spaces(data.personnel_number),
                _normalize_spaces(data.license_number),
                _normalize_spaces(data.license_category),
                _normalize_spaces(data.phone),
                _normalize_spaces(data.medical_valid_to),
                _normalize_spaces(data.signature_profile or "УНЭП"),
                _normalize_spaces(data.status or "active") or "active",
                _normalize_spaces(data.comment),
                actor.get("email", ""),
                now,
                now,
            ),
        )
        driver_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_driver_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_driver", entity_id=str(driver_id), details={"full_name": data.full_name, "status": data.status})
    return {"status": "success", "id": driver_id}


@router.put("/api/epl/drivers/{driver_id}")
def update_epl_driver(driver_id: int, data: EPLDriverData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            UPDATE epl_drivers
            SET full_name=?, personnel_number=?, license_number=?, license_category=?, phone=?, medical_valid_to=?,
                signature_profile=?, status=?, comment=?, updated_at=?
            WHERE id=?
            """,
            (
                _normalize_spaces(data.full_name),
                _normalize_spaces(data.personnel_number),
                _normalize_spaces(data.license_number),
                _normalize_spaces(data.license_category),
                _normalize_spaces(data.phone),
                _normalize_spaces(data.medical_valid_to),
                _normalize_spaces(data.signature_profile or "УНЭП"),
                _normalize_spaces(data.status or "active") or "active",
                _normalize_spaces(data.comment),
                int(time.time()),
                _safe_int(driver_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_driver_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_driver", entity_id=str(driver_id), details={"full_name": data.full_name, "status": data.status})
    return {"status": "success"}


@router.delete("/api/epl/drivers/{driver_id}")
def delete_epl_driver(driver_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "delete"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM epl_drivers WHERE id=?", (_safe_int(driver_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_driver_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_driver", entity_id=str(driver_id))
    return {"status": "success"}


@router.get("/api/epl/vehicles")
def get_epl_vehicles(request: Request, status: str = ""):
    actor = require_approved_user(request)
    if not _can_access_epl(actor, "read"):
        return _api_error(403, "forbidden")
    rows = _load_epl_vehicle_rows()
    if status:
        rows = [row for row in rows if row.get("status") == status]
    return rows


@router.post("/api/epl/vehicles")
def create_epl_vehicle(data: EPLVehicleData, request: Request):
    actor = require_approved_user(request)
    if not _can_access_epl(actor, "create"):
        return _api_error(403, "forbidden")
    now = int(time.time())
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO epl_vehicles (
                registration_no, garage_number, brand, model, trailer_registration, odometer, carrying_capacity,
                diagnostic_valid_to, insurance_valid_to, status, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _normalize_spaces(data.registration_no),
                _normalize_spaces(data.garage_number),
                _normalize_spaces(data.brand),
                _normalize_spaces(data.model),
                _normalize_spaces(data.trailer_registration),
                _safe_float(data.odometer),
                _safe_float(data.carrying_capacity),
                _normalize_spaces(data.diagnostic_valid_to),
                _normalize_spaces(data.insurance_valid_to),
                _normalize_spaces(data.status or "active") or "active",
                _normalize_spaces(data.comment),
                actor.get("email", ""),
                now,
                now,
            ),
        )
        vehicle_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_vehicle_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_vehicle", entity_id=str(vehicle_id), details={"registration_no": data.registration_no, "status": data.status})
    return {"status": "success", "id": vehicle_id}


@router.put("/api/epl/vehicles/{vehicle_id}")
def update_epl_vehicle(vehicle_id: int, data: EPLVehicleData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            UPDATE epl_vehicles
            SET registration_no=?, garage_number=?, brand=?, model=?, trailer_registration=?, odometer=?, carrying_capacity=?,
                diagnostic_valid_to=?, insurance_valid_to=?, status=?, comment=?, updated_at=?
            WHERE id=?
            """,
            (
                _normalize_spaces(data.registration_no),
                _normalize_spaces(data.garage_number),
                _normalize_spaces(data.brand),
                _normalize_spaces(data.model),
                _normalize_spaces(data.trailer_registration),
                _safe_float(data.odometer),
                _safe_float(data.carrying_capacity),
                _normalize_spaces(data.diagnostic_valid_to),
                _normalize_spaces(data.insurance_valid_to),
                _normalize_spaces(data.status or "active") or "active",
                _normalize_spaces(data.comment),
                int(time.time()),
                _safe_int(vehicle_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_vehicle_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_vehicle", entity_id=str(vehicle_id), details={"registration_no": data.registration_no, "status": data.status})
    return {"status": "success"}


@router.delete("/api/epl/vehicles/{vehicle_id}")
def delete_epl_vehicle(vehicle_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "delete"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM epl_vehicles WHERE id=?", (_safe_int(vehicle_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_vehicle_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_vehicle", entity_id=str(vehicle_id))
    return {"status": "success"}


@router.get("/api/epl/waybills")
def get_epl_waybills(request: Request, status: str = "", integration_status: str = "", driver_id: int = 0, vehicle_id: int = 0, project_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    rows = _load_epl_waybill_rows()
    if status:
        rows = [row for row in rows if row.get("status") == status]
    if integration_status:
        rows = [row for row in rows if row.get("integration_status") == integration_status]
    if driver_id:
        rows = [row for row in rows if _safe_int(row.get("driver_id")) == _safe_int(driver_id)]
    if vehicle_id:
        rows = [row for row in rows if _safe_int(row.get("vehicle_id")) == _safe_int(vehicle_id)]
    if project_id:
        rows = [row for row in rows if _safe_int(row.get("project_id")) == _safe_int(project_id)]
    return rows


@router.get("/api/epl/waybills/{waybill_id}")
def get_epl_waybill_detail(waybill_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    rows = _load_epl_waybill_rows(waybill_id)
    if not rows:
        return {"error": "not_found"}
    return {
        "waybill": rows[0],
        "signatures": _load_epl_signature_rows(waybill_id),
        "sync_queue": _load_epl_sync_queue_rows(limit=20, waybill_id=waybill_id),
        "sync_history": _load_epl_sync_log_rows(waybill_id, limit=40),
        "sync_conflicts": _load_epl_sync_conflict_rows(limit=20, waybill_id=waybill_id),
    }


@router.get("/api/epl/sync_queue")
def get_epl_sync_queue(request: Request, limit: int = 120, state: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_epl_sync_queue_rows(limit=limit, state=state)


@router.get("/api/epl/sync_conflicts")
def get_epl_sync_conflicts(request: Request, limit: int = 120):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_epl_sync_conflict_rows(limit=limit)


@router.post("/api/epl/sync_queue/process")
def process_epl_sync_queue(request: Request, limit: int = 20):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    processed = 0
    success = 0
    failed = 0
    try:
        c = conn.cursor()
        now = int(time.time())
        c.execute(
            """
            SELECT *
            FROM integration_sync_queue
            WHERE system_name='1C'
              AND entity_type='epl_waybill'
              AND state IN ('queued', 'retry')
              AND (next_retry_at=0 OR next_retry_at<=?)
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (now, max(1, min(limit, 100))),
        )
        rows = [dict(row) for row in c.fetchall()]
        for row in rows:
            processed += 1
            c.execute(
                "UPDATE integration_sync_queue SET state='processing', locked_at=?, updated_at=? WHERE id=?",
                (now, now, _safe_int(row.get("id"))),
            )
            outcome = _process_epl_sync_queue_item(conn, row)
            if outcome.get("state") == "sent":
                success += 1
            else:
                failed += 1
        conn.commit()
    finally:
        conn.close()
    audit_log(
        "epl_sync_queue_processed",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_sync_queue",
        entity_id="epl_waybill",
        details={"processed": processed, "success": success, "failed": failed},
    )
    return {"status": "success", "processed": processed, "success": success, "failed": failed}


@router.post("/api/epl/sync_queue/{sync_id}/retry")
def retry_epl_sync(sync_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM integration_sync_queue WHERE id=? AND entity_type='epl_waybill'", (_safe_int(sync_id),))
        row = c.fetchone()
        if not row:
            return {"error": "not_found"}
        row = dict(row)
        now = int(time.time())
        c.execute(
            """
            UPDATE integration_sync_queue
            SET state='retry', last_error='', next_retry_at=?, locked_at=0, updated_at=?
            WHERE id=?
            """,
            (now, now, _safe_int(sync_id)),
        )
        c.execute(
            "UPDATE epl_waybills SET integration_status='queued', last_sync_error='', updated_at=? WHERE id=?",
            (now, _safe_int(row.get("entity_id"))),
        )
        _log_epl_sync_event(conn, _safe_int(sync_id), _safe_int(row.get("entity_id")), "retry", "Повторная отправка ЭПЛ запрошена", _json_load(row.get("payload"), {}))
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_sync_retry_requested", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_sync_queue", entity_id=str(sync_id))
    return {"status": "success"}


@router.post("/api/epl/waybills")
def create_epl_waybill(data: EPLWaybillData, request: Request):
    actor = require_approved_user(request)
    if not _can_access_epl(actor, "create"):
        return _api_error(403, "forbidden")
    now = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        context = _resolve_epl_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
        issue_date = _normalize_spaces(data.issue_date) or _today_display()
        shift_date = _normalize_spaces(data.shift_date) or issue_date
        number = _ensure_waybill_number(conn, data.number, shift_date)
        requested_integration_status = _normalize_spaces(data.integration_status or "draft") or "draft"
        odometer_data, odometer_error = _validate_waybill_odometer(conn, data.vehicle_id, data.odometer_out, data.odometer_in)
        if not odometer_data:
            return _api_error(400, "validation_error", message=odometer_error)
        merged = {
            "project_id": context["project_id"],
            "client_id": context["client_id"],
            "contract_id": context["contract_id"],
            "object_id": context["object_id"],
            "number": number,
            "issue_date": issue_date,
            "shift_date": shift_date,
            "waybill_type": _normalize_spaces(data.waybill_type or "truck") or "truck",
            "driver_id": _safe_int(data.driver_id),
            "vehicle_id": _safe_int(data.vehicle_id),
            "route_text": _normalize_spaces(data.route_text),
            "cargo": _normalize_spaces(data.cargo),
            "departure_point": _normalize_spaces(data.departure_point),
            "destination_point": _normalize_spaces(data.destination_point),
            "dispatcher_name": _normalize_spaces(data.dispatcher_name),
            "medical_name": _normalize_spaces(data.medical_name),
            "mechanic_name": _normalize_spaces(data.mechanic_name),
            "planned_departure": _normalize_spaces(data.planned_departure),
            "actual_departure": _normalize_spaces(data.actual_departure),
            "actual_return": _normalize_spaces(data.actual_return),
            "odometer_out": odometer_data["odometer_out"],
            "odometer_in": odometer_data["odometer_in"],
            "mileage": odometer_data["mileage"],
            "fuel_issued": _safe_float(data.fuel_issued),
            "fuel_returned": _safe_float(data.fuel_returned),
            "operator_name": _normalize_spaces(data.operator_name or "1С-ЭДО") or "1С-ЭДО",
            "external_document_id": _normalize_spaces(data.external_document_id),
            "last_sync_error": _normalize_spaces(data.last_sync_error),
            "notes": _normalize_spaces(data.notes),
            "integration_status": requested_integration_status,
            "row_version": 1,
        }
        merged["status"] = _derive_waybill_status(merged)
        valid, message = _validate_1c_transition(merged, requested_integration_status)
        if not valid:
            return {"error": "validation_error", "message": message}
        merged["integration_status"] = _derive_integration_status(merged)
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO epl_waybills (
                project_id, client_id, contract_id, object_id, number, issue_date, shift_date, waybill_type, driver_id,
                vehicle_id, route_text, cargo, departure_point, destination_point, dispatcher_name, medical_name,
                mechanic_name, planned_departure, actual_departure, actual_return, odometer_out, odometer_in, mileage,
                fuel_issued, fuel_returned, status, integration_status, operator_name, external_document_id,
                last_sync_error, notes, row_version, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                merged["project_id"],
                merged["client_id"],
                merged["contract_id"],
                merged["object_id"],
                merged["number"],
                merged["issue_date"],
                merged["shift_date"],
                merged["waybill_type"],
                merged["driver_id"],
                merged["vehicle_id"],
                merged["route_text"],
                merged["cargo"],
                merged["departure_point"],
                merged["destination_point"],
                merged["dispatcher_name"],
                merged["medical_name"],
                merged["mechanic_name"],
                merged["planned_departure"],
                merged["actual_departure"],
                merged["actual_return"],
                merged["odometer_out"],
                merged["odometer_in"],
                merged["mileage"],
                merged["fuel_issued"],
                merged["fuel_returned"],
                merged["status"],
                merged["integration_status"],
                _normalize_spaces(data.operator_name or "1С-ЭДО") or "1С-ЭДО",
                merged["external_document_id"],
                merged["last_sync_error"],
                merged["notes"],
                merged["row_version"],
                actor.get("email", ""),
                now,
                now,
            ),
        )
        waybill_id = c.lastrowid
        _sync_vehicle_odometer(conn, merged["vehicle_id"], merged["odometer_out"], merged["odometer_in"])
        _refresh_waybill_qr(conn, waybill_id)
        if merged["integration_status"] == "queued":
            current_row = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=True)
            _upsert_epl_sync_job(conn, current_row or {"id": waybill_id}, actor.get("email", ""))
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_waybill_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_waybill", entity_id=str(waybill_id), details={"number": number, "shift_date": shift_date})
    return {"status": "success", "id": waybill_id}


@router.put("/api/epl/waybills/{waybill_id}")
def update_epl_waybill(waybill_id: int, data: EPLWaybillData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        existing = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=False)
        if not existing:
            return {"error": "not_found"}
        valid, message = _validate_waybill_write_access(existing, actor, data.expected_version)
        if not valid:
            return {"error": "validation_error", "message": message}
        context = _resolve_epl_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
        issue_date = _normalize_spaces(data.issue_date) or existing.get("issue_date") or _today_display()
        shift_date = _normalize_spaces(data.shift_date) or existing.get("shift_date") or issue_date
        number = _ensure_waybill_number(conn, data.number, shift_date, waybill_id, existing.get("number") or "")
        requested_integration_status = _normalize_spaces(data.integration_status or existing.get("integration_status") or "draft") or "draft"
        odometer_out_value = data.odometer_out if _safe_float(data.odometer_out) > 0 else existing.get("odometer_out")
        odometer_in_value = data.odometer_in if _safe_float(data.odometer_in) > 0 else existing.get("odometer_in")
        odometer_data, odometer_error = _validate_waybill_odometer(conn, data.vehicle_id or existing.get("vehicle_id"), odometer_out_value, odometer_in_value)
        if not odometer_data:
            return {"error": "validation_error", "message": odometer_error}
        merged = {
            **existing,
            "project_id": context["project_id"],
            "client_id": context["client_id"],
            "contract_id": context["contract_id"],
            "object_id": context["object_id"],
            "number": number,
            "issue_date": issue_date,
            "shift_date": shift_date,
            "waybill_type": _normalize_spaces(data.waybill_type or existing.get("waybill_type") or "truck") or "truck",
            "driver_id": _safe_int(data.driver_id),
            "vehicle_id": _safe_int(data.vehicle_id),
            "route_text": _normalize_spaces(data.route_text),
            "cargo": _normalize_spaces(data.cargo),
            "departure_point": _normalize_spaces(data.departure_point),
            "destination_point": _normalize_spaces(data.destination_point),
            "dispatcher_name": _normalize_spaces(data.dispatcher_name),
            "medical_name": _normalize_spaces(data.medical_name),
            "mechanic_name": _normalize_spaces(data.mechanic_name),
            "planned_departure": _normalize_spaces(data.planned_departure),
            "actual_departure": _normalize_spaces(data.actual_departure),
            "actual_return": _normalize_spaces(data.actual_return),
            "odometer_out": odometer_data["odometer_out"],
            "odometer_in": odometer_data["odometer_in"],
            "mileage": odometer_data["mileage"],
            "fuel_issued": _safe_float(data.fuel_issued),
            "fuel_returned": _safe_float(data.fuel_returned),
            "operator_name": _normalize_spaces(data.operator_name or existing.get("operator_name") or "1С-ЭДО") or "1С-ЭДО",
            "external_document_id": _normalize_spaces(data.external_document_id),
            "last_sync_error": _normalize_spaces(data.last_sync_error),
            "notes": _normalize_spaces(data.notes),
            "integration_status": requested_integration_status,
            "row_version": max(1, _safe_int(existing.get("row_version")) or 1) + 1,
        }
        merged["status"] = _derive_waybill_status(merged)
        valid, message = _validate_1c_transition(merged, requested_integration_status)
        if not valid:
            return {"error": "validation_error", "message": message}
        merged["integration_status"] = _derive_integration_status(merged)
        c.execute(
            """
            UPDATE epl_waybills
            SET project_id=?, client_id=?, contract_id=?, object_id=?, number=?, issue_date=?, shift_date=?, waybill_type=?, driver_id=?,
                vehicle_id=?, route_text=?, cargo=?, departure_point=?, destination_point=?, dispatcher_name=?, medical_name=?,
                mechanic_name=?, planned_departure=?, actual_departure=?, actual_return=?, odometer_out=?, odometer_in=?, mileage=?,
                fuel_issued=?, fuel_returned=?, status=?, integration_status=?, operator_name=?, external_document_id=?, last_sync_error=?,
                notes=?, row_version=?, updated_at=?
            WHERE id=?
            """,
            (
                merged["project_id"],
                merged["client_id"],
                merged["contract_id"],
                merged["object_id"],
                merged["number"],
                merged["issue_date"],
                merged["shift_date"],
                merged["waybill_type"],
                merged["driver_id"],
                merged["vehicle_id"],
                merged["route_text"],
                merged["cargo"],
                merged["departure_point"],
                merged["destination_point"],
                merged["dispatcher_name"],
                merged["medical_name"],
                merged["mechanic_name"],
                merged["planned_departure"],
                merged["actual_departure"],
                merged["actual_return"],
                merged["odometer_out"],
                merged["odometer_in"],
                merged["mileage"],
                merged["fuel_issued"],
                merged["fuel_returned"],
                merged["status"],
                merged["integration_status"],
                _normalize_spaces(data.operator_name or existing.get("operator_name") or "1С-ЭДО") or "1С-ЭДО",
                merged["external_document_id"],
                merged["last_sync_error"],
                merged["notes"],
                merged["row_version"],
                int(time.time()),
                _safe_int(waybill_id),
            ),
        )
        _sync_vehicle_odometer(conn, merged["vehicle_id"], merged["odometer_out"], merged["odometer_in"])
        _refresh_waybill_qr(conn, waybill_id)
        if merged["integration_status"] == "queued":
            current_row = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=True)
            _upsert_epl_sync_job(conn, current_row or {"id": waybill_id}, actor.get("email", ""))
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_waybill_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_waybill", entity_id=str(waybill_id), details={"number": data.number, "status": data.status})
    return {"status": "success"}


@router.delete("/api/epl/waybills/{waybill_id}")
def delete_epl_waybill(waybill_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "delete"):
        return {"error": "forbidden"}
    qr_disk_path = os.path.join("uploads", "qr", f"epl_{_safe_int(waybill_id)}.png")
    conn = get_connection(row_factory=True)
    try:
        existing = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=False)
        if not existing:
            return {"error": "not_found"}
        valid, message = _validate_waybill_write_access(existing, actor, 0)
        if not valid:
            return {"error": "validation_error", "message": message}
        c = conn.cursor()
        c.execute(
            "DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='epl_waybill' AND entity_id=?)",
            (_safe_int(waybill_id),),
        )
        c.execute("DELETE FROM integration_sync_queue WHERE entity_type='epl_waybill' AND entity_id=?", (_safe_int(waybill_id),))
        c.execute("DELETE FROM epl_signatures WHERE waybill_id=?", (_safe_int(waybill_id),))
        c.execute("DELETE FROM epl_waybills WHERE id=?", (_safe_int(waybill_id),))
        conn.commit()
    finally:
        conn.close()
    if os.path.exists(qr_disk_path):
        try:
            os.remove(qr_disk_path)
        except OSError:
            pass
    audit_log("epl_waybill_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_waybill", entity_id=str(waybill_id))
    return {"status": "success"}


@router.post("/api/epl/waybills/{waybill_id}/lock")
def lock_epl_waybill(waybill_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        existing = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=False)
        if not existing:
            return {"error": "not_found"}
        lock_info = _active_epl_lock(existing)
        actor_email = actor.get("email", "")
        if lock_info and _normalize_email(lock_info.get("email")) != _normalize_email(actor_email):
            owner = lock_info.get("name") or lock_info.get("email") or "другого пользователя"
            return {"error": "validation_error", "message": f"Карточка уже открыта у {owner}."}
        now = int(time.time())
        c = conn.cursor()
        c.execute(
            "UPDATE epl_waybills SET edit_lock_email=?, edit_lock_name=?, edit_lock_at=? WHERE id=?",
            (actor_email, actor.get("name", ""), now, _safe_int(waybill_id)),
        )
        locked = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=True)
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "waybill": locked}


@router.post("/api/epl/waybills/{waybill_id}/unlock")
def unlock_epl_waybill(waybill_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        existing = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=False)
        if not existing:
            return {"error": "not_found"}
        lock_info = _active_epl_lock(existing)
        actor_email = _normalize_email(actor.get("email", ""))
        if lock_info and _normalize_email(lock_info.get("email")) not in {"", actor_email}:
            return {"error": "validation_error", "message": "Карточка удерживается другим пользователем."}
        c = conn.cursor()
        c.execute("UPDATE epl_waybills SET edit_lock_email='', edit_lock_name='', edit_lock_at=0 WHERE id=?", (_safe_int(waybill_id),))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


@router.post("/api/epl/waybills/{waybill_id}/sync/replay")
def replay_epl_sync(waybill_id: int, data: EPLWaybillActionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        existing = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=False)
        if not existing:
            return {"error": "not_found"}
        valid, message = _validate_waybill_write_access(existing, actor, data.expected_version, allow_integrated_edit=True)
        if not valid:
            return {"error": "validation_error", "message": message}
        if not _can_send_waybill_to_1c(existing):
            return {"error": "validation_error", "message": "Replay доступен только для ЭПЛ, у которого собраны все титулы."}
        now = int(time.time())
        next_version = max(1, _safe_int(existing.get("row_version")) or 1) + 1
        c = conn.cursor()
        c.execute(
            """
            UPDATE epl_waybills
            SET integration_status='queued', external_document_id='', last_sync_error='', row_version=?, updated_at=?
            WHERE id=?
            """,
            (next_version, now, _safe_int(waybill_id)),
        )
        c.execute(
            """
            INSERT INTO epl_signatures (
                waybill_id, stage, signer_role, signer_name, signature_kind, signed_at, status_mark, comment, created_at
            ) VALUES (?, 'integration', ?, ?, 'service', ?, 'queued', ?, ?)
            """,
            (
                _safe_int(waybill_id),
                _normalize_spaces(data.signer_role or "Оператор ЭДО") or "Оператор ЭДО",
                _normalize_spaces(data.signer_name or actor.get("name", "")),
                _normalize_spaces(data.signed_at) or _today_display(),
                _normalize_spaces(data.comment) or "Replay ЭПЛ в очередь 1С",
                now,
            ),
        )
        current_row = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=True)
        queue_id = _upsert_epl_sync_job(conn, current_row or {"id": waybill_id}, actor.get("email", ""), force_replay=True)
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_sync_replay_requested", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_waybill", entity_id=str(waybill_id), details={"queue_id": queue_id})
    return {"status": "success", "queue_id": queue_id}


@router.post("/api/epl/waybills/{waybill_id}/reopen")
def reopen_epl_waybill(waybill_id: int, data: EPLWaybillReopenData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        existing = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=False)
        if not existing:
            return {"error": "not_found"}
        valid, message = _validate_waybill_write_access(existing, actor, data.expected_version, allow_integrated_edit=True)
        if not valid:
            return {"error": "validation_error", "message": message}
        now = int(time.time())
        target_integration_status = "ready" if _can_send_waybill_to_1c(existing) else _derive_integration_status({**existing, "integration_status": "draft"})
        if target_integration_status in {"queued", "sent", "accepted"}:
            target_integration_status = "ready"
        c = conn.cursor()
        _mark_epl_active_jobs_conflict(conn, waybill_id, "ЭПЛ переоткрыт для controlled reopen. Предыдущая отправка отменена.")
        c.execute(
            """
            UPDATE epl_waybills
            SET integration_status=?, external_document_id='', last_sync_error='', row_version=?, edit_lock_email=?, edit_lock_name=?, edit_lock_at=?, updated_at=?
            WHERE id=?
            """,
            (
                target_integration_status,
                max(1, _safe_int(existing.get("row_version")) or 1) + 1,
                actor.get("email", ""),
                actor.get("name", ""),
                now,
                now,
                _safe_int(waybill_id),
            ),
        )
        c.execute(
            """
            INSERT INTO epl_signatures (
                waybill_id, stage, signer_role, signer_name, signature_kind, signed_at, status_mark, comment, created_at
            ) VALUES (?, 'integration', ?, ?, 'service', ?, 'reopened', ?, ?)
            """,
            (
                _safe_int(waybill_id),
                "Оператор ЭДО",
                _normalize_spaces(actor.get("name", "")),
                _today_display(),
                _normalize_spaces(data.comment) or "Controlled reopen ЭПЛ",
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("epl_waybill_reopened", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_waybill", entity_id=str(waybill_id), details={"comment": data.comment})
    return {"status": "success"}


@router.post("/api/epl/waybills/{waybill_id}/actions")
def create_epl_waybill_action(waybill_id: int, data: EPLWaybillActionData, request: Request):
    actor = require_approved_user(request)
    if not _can_access_epl(actor, "update"):
        return _api_error(403, "forbidden")
    stage = _normalize_stage_name(data.stage)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        existing = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=False)
        if not existing:
            return _api_error(404, "not_found")

        if stage == "integration":
            valid, message = _validate_waybill_write_access(existing, actor, data.expected_version, allow_integrated_edit=True)
            if not valid:
                return _api_error(409, "validation_error", message=message)
            integration_status = _normalize_spaces(data.integration_status or data.status_value or existing.get("integration_status") or "draft") or "draft"
            if integration_status == "queued" and _normalize_match(existing.get("integration_status", "")) in {"sent", "accepted"}:
                return _api_error(409, "validation_error", message="Для повторной отправки после 1С используй replay или controlled reopen.")
            valid, message = _validate_1c_transition(existing, integration_status)
            if not valid:
                return _api_error(400, "validation_error", message=message)
            next_version = max(1, _safe_int(existing.get("row_version")) or 1) + 1
            c.execute(
                """
                UPDATE epl_waybills
                SET integration_status=?, external_document_id=?, last_sync_error=?, row_version=?, updated_at=?
                WHERE id=?
                """,
                (
                    integration_status,
                    _normalize_spaces(data.external_document_id),
                    _normalize_spaces(data.last_sync_error if _normalize_match(integration_status) == "error" else ""),
                    next_version,
                    now,
                    _safe_int(waybill_id),
                ),
            )
            if integration_status == "queued":
                current_row = _load_epl_waybill_row_from_conn(conn, waybill_id, decorate=True)
                _upsert_epl_sync_job(conn, current_row or {"id": waybill_id}, actor.get("email", ""))
            elif integration_status in {"error", "sent", "accepted"}:
                _update_latest_epl_sync_row(
                    conn,
                    waybill_id,
                    "failed" if integration_status == "error" else integration_status,
                    _normalize_spaces(data.last_sync_error if integration_status == "error" else data.comment),
                    _normalize_spaces(data.external_document_id),
                )
            c.execute(
                """
                INSERT INTO epl_signatures (
                    waybill_id, stage, signer_role, signer_name, signature_kind, signed_at, status_mark, comment, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _safe_int(waybill_id),
                    "integration",
                    _normalize_spaces(data.signer_role or "Оператор ЭДО") or "Оператор ЭДО",
                    _normalize_spaces(data.signer_name or actor.get("name", "")),
                    _normalize_spaces(data.signature_kind or "service") or "service",
                    _normalize_spaces(data.signed_at) or _today_display(),
                    integration_status,
                    _normalize_spaces(data.comment),
                    now,
                ),
            )
            latest = {
                **existing,
                "integration_status": integration_status,
                "external_document_id": _normalize_spaces(data.external_document_id),
                "last_sync_error": _normalize_spaces(data.last_sync_error if _normalize_match(integration_status) == "error" else ""),
                "row_version": next_version,
            }
        elif stage in EPL_STAGE_META:
            valid, message = _validate_waybill_write_access(existing, actor, data.expected_version)
            if not valid:
                return _api_error(409, "validation_error", message=message)
            meta = EPL_STAGE_META[stage]
            status_value = _normalize_spaces(data.status_value or meta["default_status"]) or meta["default_status"]
            valid, message = _validate_stage_transition(existing, stage, status_value)
            if not valid:
                return _api_error(400, "validation_error", message=message)
            signed_at = _normalize_spaces(data.signed_at) or _today_display()
            updates = {
                meta["status_col"]: status_value,
                meta["time_col"]: signed_at,
                "row_version": max(1, _safe_int(existing.get("row_version")) or 1) + 1,
                "updated_at": now,
            }
            if stage == "dispatcher_departure" and not _normalize_spaces(existing.get("actual_departure", "")):
                updates["actual_departure"] = signed_at
            if stage == "dispatcher_return" and not _normalize_spaces(existing.get("actual_return", "")):
                updates["actual_return"] = signed_at
            merged = {**existing, **updates}
            updates["status"] = _derive_waybill_status(merged)
            if _normalize_match(existing.get("integration_status", "")) not in EPL_INTEGRATION_TERMINAL_STATUSES:
                updates["integration_status"] = _derive_integration_status({**existing, **updates})
            assignments = ", ".join(f"{column}=?" for column in updates.keys())
            c.execute(f"UPDATE epl_waybills SET {assignments} WHERE id=?", (*updates.values(), _safe_int(waybill_id)))
            c.execute(
                """
                INSERT INTO epl_signatures (
                    waybill_id, stage, signer_role, signer_name, signature_kind, signed_at, status_mark, comment, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _safe_int(waybill_id),
                    stage,
                    _normalize_spaces(data.signer_role or meta["default_role"]) or meta["default_role"],
                    _normalize_spaces(data.signer_name or actor.get("name", "")),
                    _normalize_spaces(data.signature_kind or "УНЭП") or "УНЭП",
                    signed_at,
                    status_value,
                    _normalize_spaces(data.comment),
                    now,
                ),
            )
            latest = {**existing, **updates}
        else:
            return _api_error(400, "unknown_stage", stage=stage)

        _sync_vehicle_odometer(conn, latest.get("vehicle_id"), latest.get("odometer_out"), latest.get("odometer_in"))
        _refresh_waybill_qr(conn, waybill_id)
        conn.commit()
    finally:
        conn.close()

    audit_log("epl_waybill_action", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="epl_waybill", entity_id=str(waybill_id), details={"stage": stage, "status_value": data.status_value, "integration_status": data.integration_status})
    return {"status": "success"}
