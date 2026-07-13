import json
import re
import time
from datetime import datetime

from fastapi import APIRouter, Request

from database import audit_log, delete_entity_watch, get_connection, list_entity_watches, next_safe_table_id, upsert_entity_watch
from permissions import has_permission, require_approved_user
from schemas import WorkbenchBulkActionData, WorkbenchFormDraftData, WorkbenchQuickItemData, WorkbenchSavedFilterData, WorkbenchWatchData
from services.document_content_index_service import search_document_content
from services.entity_card_service import build_entity_card

router = APIRouter()


@router.get("/api/entity_cards/{entity_type}/{entity_id}")
def get_entity_card(entity_type: str, entity_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    return build_entity_card(entity_type, entity_id, actor)


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_text(value) -> str:
    return str(value or "").strip()


def _format_search_numeric(value) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    normalized = text.replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", normalized, re.IGNORECASE):
        return text
    try:
        number = float(normalized)
    except Exception:
        return text
    if number.is_integer():
        return f"{int(number):,}".replace(",", " ")
    return f"{number:,.2f}".replace(",", " ").replace(".", ",")


def _search_meta_field_value(field_name: str, value) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    key = _safe_text(field_name).lower()
    if any(marker in key for marker in ("amount", "sum", "qty", "price", "cost", "budget", "total")):
        return _format_search_numeric(text)
    return text


def _json_load(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _row_dicts(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def _now_ts() -> int:
    return int(time.time())


def _parse_due_date(value: str):
    raw = _safe_text(value)
    if not raw:
        return None
    for pattern in ("%d.%m.%Y", "%d.%m.%Y %H:%M", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw[:16], pattern)
        except Exception:
            continue
    return None


def _days_until(value: str):
    due = _parse_due_date(value)
    if not due:
        return None
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (due.replace(hour=0, minute=0, second=0, microsecond=0) - today).days


def _quick_item_payload(row: dict) -> dict:
    payload = dict(row or {})
    payload["type"] = payload.get("entity_type") or payload.get("type") or ""
    payload["id"] = payload.get("entity_id") or payload.get("id") or ""
    payload["view"] = payload.get("view_name") or payload.get("view") or ""
    payload["payload"] = _json_load(payload.get("payload_json"), {})
    return payload


def _saved_filter_payload(row: dict) -> dict:
    payload = dict(row or {})
    payload["filter_payload"] = _json_load(payload.get("filter_payload_json"), {})
    return payload


def _form_draft_payload(row: dict) -> dict:
    payload = dict(row or {})
    payload["payload"] = _json_load(payload.get("payload_json"), {})
    return payload


def _watch_payload(row: dict) -> dict:
    payload = dict(row or {})
    payload["type"] = payload.get("entity_type") or payload.get("type") or ""
    payload["id"] = payload.get("entity_id") or payload.get("id") or ""
    payload["view"] = payload.get("view_name") or payload.get("view") or ""
    payload["event_types"] = _json_load(payload.get("event_types_json"), [])
    return payload


def _bulk_action_config(entity_type: str) -> dict:
    configs = {
        "sales_document": {"table": "sales_documents_extended", "module": "sales", "status_field": "status", "assignee_field": "responsible", "label": "Документ продажи"},
        "purchase_order": {"table": "purchase_orders", "module": "supply", "status_field": "status", "assignee_field": "responsible", "label": "Закупка"},
        "production_order": {"table": "production_orders", "module": "production", "status_field": "stage", "assignee_field": "responsible", "label": "Производственный заказ"},
        "wms_cell": {"table": "wms_cell_profiles", "module": "nsi", "status_field": "status", "assignee_field": "", "label": "WMS-ячейка"},
        "wms_putaway_task": {"table": "wms_putaway_tasks", "module": "nsi", "status_field": "status", "assignee_field": "assigned_to", "label": "WMS-размещение"},
        "wms_pick_wave": {"table": "wms_pick_waves", "module": "nsi", "status_field": "status", "assignee_field": "assigned_to", "label": "WMS-волна"},
        "wms_pick_task": {"table": "wms_pick_tasks", "module": "nsi", "status_field": "status", "assignee_field": "assigned_to", "label": "WMS-подбор"},
        "wms_cycle_count": {"table": "wms_cycle_counts", "module": "nsi", "status_field": "status", "assignee_field": "assigned_to", "label": "WMS-пересчёт"},
        "procurement_request": {"table": "procurement_requests", "module": "supply", "status_field": "status", "assignee_field": "requested_by", "label": "Заявка на закупку"},
        "approval": {"table": "approvals", "module": "approvals", "status_field": "status", "assignee_field": "", "timestamp_field": "last_action_at", "label": "Согласование"},
        "epl_waybill": {"table": "epl_waybills", "module": "accounting", "status_field": "status", "assignee_field": "dispatcher_name", "label": "ЭПЛ"},
    }
    return configs.get(_safe_text(entity_type), {})


def _upsert_quick_item(table: str, actor: dict, data: WorkbenchQuickItemData, touched: bool = False) -> int:
    now = _now_ts()
    conn = get_connection(row_factory=True)
    try:
        existing = conn.execute(
            f"SELECT id FROM {table} WHERE user_email=? AND entity_type=? AND entity_id=? LIMIT 1",
            (actor.get("email", ""), data.entity_type, str(data.entity_id)),
        ).fetchone()
        if existing:
            row_id = _safe_int(dict(existing).get("id"))
            if touched:
                conn.execute(
                    f"""
                    UPDATE {table}
                    SET title=?, meta=?, view_name=?, payload_json=?, touched_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (data.title, data.meta, data.view_name, json.dumps(data.payload or {}, ensure_ascii=False), now, now, row_id),
                )
            else:
                conn.execute(
                    f"""
                    UPDATE {table}
                    SET title=?, meta=?, view_name=?, payload_json=?, updated_at=?
                    WHERE id=?
                    """,
                    (data.title, data.meta, data.view_name, json.dumps(data.payload or {}, ensure_ascii=False), now, row_id),
                )
        else:
            row_id = next_safe_table_id(conn, table)
            if touched:
                conn.execute(
                    f"""
                    INSERT INTO {table} (
                        id, user_email, entity_type, entity_id, title, meta, view_name, payload_json,
                        touched_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (row_id, actor.get("email", ""), data.entity_type, str(data.entity_id), data.title, data.meta, data.view_name, json.dumps(data.payload or {}, ensure_ascii=False), now, now, now),
                )
            else:
                conn.execute(
                    f"""
                    INSERT INTO {table} (
                        id, user_email, entity_type, entity_id, title, meta, view_name, payload_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (row_id, actor.get("email", ""), data.entity_type, str(data.entity_id), data.title, data.meta, data.view_name, json.dumps(data.payload or {}, ensure_ascii=False), now, now),
                )
        conn.commit()
    finally:
        conn.close()
    return row_id


def _project_is_overdue(project: dict) -> bool:
    if _safe_text(project.get("status")) != "active":
        return False
    deadlines = _json_load(project.get("deadlines"), {})
    checked = _json_load(project.get("checkedState"), {})
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for key, value in (deadlines or {}).items():
        due = _parse_due_date(value)
        if not due or due.replace(hour=0, minute=0, second=0, microsecond=0) >= today:
            continue
        stage_key = f"task_{key}_"
        has_open = any(str(flag_key).startswith(stage_key) and not str(flag_value).startswith("✅") for flag_key, flag_value in (checked or {}).items())
        if has_open or not checked:
            return True
    return False


def _my_day_items(actor: dict) -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        items: list[dict] = []
        actor_name = _safe_text(actor.get("name"))
        actor_email = _safe_text(actor.get("email"))
        actor_role = _safe_text(actor.get("role"))
        if has_permission(actor, "tasks", "read"):
            task_rows = _row_dicts(
                conn.execute(
                    """
                    SELECT *
                    FROM tasks
                    WHERE status NOT IN ('completed', 'canceled')
                    ORDER BY id DESC
                    LIMIT 120
                    """
                )
            )
            for row in task_rows:
                executor = _safe_text(row.get("executor"))
                mine = not executor or actor_role == "Директор" or actor_name in executor or actor_email in executor
                days = _days_until(row.get("deadline"))
                if mine and (days is None or days <= 1):
                    items.append({
                        "kind": "task",
                        "title": row.get("title") or "Поручение",
                        "meta": f"{executor or 'исполнитель не задан'} · {row.get('deadline') or 'без срока'}",
                        "urgency": "risk" if days is not None and days < 0 else "attention",
                        "view": "tasks",
                        "entity_type": "task",
                        "entity_id": _safe_int(row.get("id")),
                    })
        if has_permission(actor, "approvals", "read"):
            approval_rows = _row_dicts(
                conn.execute(
                    """
                    SELECT *
                    FROM approvals
                    WHERE status='pending'
                    ORDER BY id DESC
                    LIMIT 120
                    """
                )
            )
            for row in approval_rows:
                route_text = json.dumps(row, ensure_ascii=False)
                mine = actor_role == "Директор" or actor_name in route_text or actor_role in route_text
                if mine:
                    items.append({
                        "kind": "approval",
                        "title": row.get("title") or "Согласование",
                        "meta": "ожидает решения",
                        "urgency": "attention",
                        "view": "approvals",
                        "entity_type": "approval",
                        "entity_id": _safe_int(row.get("id")),
                    })
        if has_permission(actor, "documents", "read"):
            doc_rows = _row_dicts(
                conn.execute(
                    """
                    SELECT id, type, number, d_date, subject, status
                    FROM documents
                    WHERE COALESCE(status, '') NOT IN ('archived', 'closed', 'completed')
                    ORDER BY id DESC
                    LIMIT 80
                    """
                )
            )
            for row in doc_rows[:18]:
                status = _safe_text(row.get("status")).lower()
                if status in {"draft", "new", "registered", "pending", ""}:
                    items.append({
                        "kind": "document",
                        "title": row.get("number") or row.get("subject") or "Документ",
                        "meta": f"{row.get('type') or 'document'} · {row.get('d_date') or 'без даты'}",
                        "urgency": "muted" if status == "draft" else "attention",
                        "view": "documents",
                        "entity_type": "document",
                        "entity_id": _safe_int(row.get("id")),
                    })
        note_rows = _row_dicts(
            conn.execute(
                """
                SELECT id, title, message, category, entity_type, entity_id
                FROM notifications
                WHERE is_read=0 AND (user_email='' OR user_email=? OR user_name=?)
                ORDER BY created_at DESC, id DESC
                LIMIT 10
                """,
                (actor_email, actor_name),
            )
        )
        for row in note_rows:
            items.append({
                "kind": "notification",
                "title": row.get("title") or "Уведомление",
                "meta": row.get("message") or "",
                "urgency": "attention",
                "view": "profile",
                "entity_type": row.get("entity_type") or "notification",
                "entity_id": row.get("entity_id") or _safe_int(row.get("id")),
            })
        if has_permission(actor, "projects", "read"):
            project_rows = _row_dicts(
                conn.execute(
                    """
                    SELECT id, name, contract, client, status, deadlines, checkedState
                    FROM projects
                    WHERE status='active'
                    ORDER BY id DESC
                    LIMIT 80
                    """
                )
            )
            for row in project_rows:
                if _project_is_overdue(row):
                    items.append({
                        "kind": "project",
                        "title": row.get("name") or row.get("contract") or "Проект",
                        "meta": f"{row.get('client') or ''} · просрочка этапа",
                        "urgency": "risk",
                        "view": "dashboard",
                        "entity_type": "project",
                        "entity_id": _safe_int(row.get("id")),
                    })
        order = {"risk": 0, "attention": 1, "muted": 2}
        return sorted(items, key=lambda item: (order.get(item.get("urgency"), 9), item.get("kind", "")))[:20]
    finally:
        conn.close()


@router.get("/api/workbench/quick_access")
def get_workbench_quick_access(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    email = actor.get("email", "")
    conn = get_connection(row_factory=True)
    try:
        favorites = [_quick_item_payload(row) for row in _row_dicts(conn.execute("SELECT * FROM user_favorite_items WHERE user_email=? ORDER BY updated_at DESC, id DESC LIMIT 40", (email,)))]
        recent = [_quick_item_payload(row) for row in _row_dicts(conn.execute("SELECT * FROM user_recent_items WHERE user_email=? ORDER BY touched_at DESC, id DESC LIMIT 40", (email,)))]
        filters = [_saved_filter_payload(row) for row in _row_dicts(conn.execute("SELECT * FROM user_saved_filters WHERE user_email=? ORDER BY updated_at DESC, id DESC LIMIT 40", (email,)))]
    finally:
        conn.close()
    watches = [_watch_payload(row) for row in list_entity_watches(email, limit=80)]
    return {"favorites": favorites, "recent": recent, "filters": filters, "watches": watches, "today_items": _my_day_items(actor)}


@router.get("/api/workbench/my_day")
def get_workbench_my_day(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    return {"items": _my_day_items(actor)}


@router.get("/api/workbench/form_drafts")
def list_form_drafts(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        rows = _row_dicts(
            conn.execute(
                """
                SELECT *
                FROM user_form_drafts
                WHERE user_email=?
                ORDER BY updated_at DESC, id DESC
                LIMIT 80
                """,
                (actor.get("email", ""),),
            )
        )
    finally:
        conn.close()
    return {"drafts": [_form_draft_payload(row) for row in rows]}


@router.get("/api/workbench/form_drafts/{draft_key}")
def get_form_draft(draft_key: str, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    key = _safe_text(draft_key)
    if not key:
        return {"error": "draft_key_required"}
    conn = get_connection(row_factory=True)
    try:
        row = conn.execute(
            "SELECT * FROM user_form_drafts WHERE user_email=? AND draft_key=? LIMIT 1",
            (actor.get("email", ""), key),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"error": "form_draft_not_found"}
    return {"draft": _form_draft_payload(dict(row))}


@router.post("/api/workbench/form_drafts")
def save_form_draft(data: WorkbenchFormDraftData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    key = _safe_text(data.draft_key)
    if not key:
        return {"error": "draft_key_required"}
    now = _now_ts()
    email = actor.get("email", "")
    payload_json = json.dumps(data.payload or {}, ensure_ascii=False)
    conn = get_connection(row_factory=True)
    try:
        existing = conn.execute(
            "SELECT id FROM user_form_drafts WHERE user_email=? AND draft_key=? LIMIT 1",
            (email, key),
        ).fetchone()
        if existing:
            row_id = _safe_int(dict(existing).get("id"))
            conn.execute(
                """
                UPDATE user_form_drafts
                SET entity_type=?, entity_id=?, title=?, payload_json=?, source_view=?, updated_at=?
                WHERE id=? AND user_email=?
                """,
                (data.entity_type, str(data.entity_id or ""), data.title, payload_json, data.source_view, now, row_id, email),
            )
        else:
            row_id = next_safe_table_id(conn, "user_form_drafts")
            conn.execute(
                """
                INSERT INTO user_form_drafts (
                    id, user_email, draft_key, entity_type, entity_id, title, payload_json,
                    source_view, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row_id, email, key, data.entity_type, str(data.entity_id or ""), data.title, payload_json, data.source_view, now, now),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM user_form_drafts WHERE id=? LIMIT 1", (row_id,)).fetchone()
    finally:
        conn.close()
    return {"status": "success", "draft": _form_draft_payload(dict(row)) if row else {"id": row_id, "draft_key": key, "payload": data.payload or {}}}


@router.delete("/api/workbench/form_drafts/{draft_key}")
def delete_form_draft(draft_key: str, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    key = _safe_text(draft_key)
    if not key:
        return {"error": "draft_key_required"}
    conn = get_connection()
    try:
        conn.execute("DELETE FROM user_form_drafts WHERE user_email=? AND draft_key=?", (actor.get("email", ""), key))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


@router.post("/api/workbench/favorites")
def save_workbench_favorite(data: WorkbenchQuickItemData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    row_id = _upsert_quick_item("user_favorite_items", actor, data)
    audit_log("workbench_favorite_saved", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=data.entity_type, entity_id=str(data.entity_id), details={"title": data.title})
    return {"status": "success", "id": row_id}


@router.delete("/api/workbench/favorites/{entity_type}/{entity_id}")
def delete_workbench_favorite(entity_type: str, entity_id: str, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        conn.execute("DELETE FROM user_favorite_items WHERE user_email=? AND entity_type=? AND entity_id=?", (actor.get("email", ""), entity_type, str(entity_id)))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


@router.get("/api/workbench/watches")
def get_workbench_watches(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    return {"watches": [_watch_payload(row) for row in list_entity_watches(actor.get("email", ""), limit=120)]}


@router.post("/api/workbench/watches")
def save_workbench_watch(data: WorkbenchWatchData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    row = upsert_entity_watch(
        actor.get("email", ""),
        actor.get("name", ""),
        data.entity_type,
        str(data.entity_id),
        data.title,
        data.meta,
        data.view_name,
        data.condition_key,
        data.digest_mode,
        data.event_types,
    )
    audit_log("workbench_watch_saved", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=data.entity_type, entity_id=str(data.entity_id), details={"title": data.title, "condition": data.condition_key})
    return {"status": "success", "watch": _watch_payload(row)}


@router.get("/api/workbench/watch_digest")
def get_workbench_watch_digest(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    email = actor.get("email", "")
    name = actor.get("name", "")
    conn = get_connection(row_factory=True)
    try:
        watches = [_watch_payload(row) for row in list_entity_watches(email, limit=160)]
        events = _row_dicts(
            conn.execute(
                """
                SELECT *
                FROM notifications
                WHERE category='watch'
                  AND (user_email=? OR (?<>'' AND user_name=?))
                ORDER BY created_at DESC, id DESC
                LIMIT 120
                """,
                (email, name, name),
            )
        )
    finally:
        conn.close()
    buckets: dict[str, dict] = {}
    for event in events:
        key = event.get("entity_type") or "other"
        bucket = buckets.setdefault(key, {"entity_type": key, "count": 0, "latest_at": 0})
        bucket["count"] += 1
        bucket["latest_at"] = max(_safe_int(bucket.get("latest_at")), _safe_int(event.get("created_at")))
    return {"watches": watches, "events": events, "summary": list(buckets.values())}


@router.delete("/api/workbench/watches/{entity_type}/{entity_id}")
def delete_workbench_watch(entity_type: str, entity_id: str, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    delete_entity_watch(actor.get("email", ""), entity_type, str(entity_id))
    audit_log("workbench_watch_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=entity_type, entity_id=str(entity_id))
    return {"status": "success"}


@router.post("/api/workbench/recent")
def save_workbench_recent(data: WorkbenchQuickItemData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    row_id = _upsert_quick_item("user_recent_items", actor, data, touched=True)
    return {"status": "success", "id": row_id}


@router.post("/api/workbench/saved_filters")
def save_workbench_filter(data: WorkbenchSavedFilterData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    now = _now_ts()
    conn = get_connection()
    try:
        email = actor.get("email", "")
        scope = data.filter_scope or "dashboard"
        existing = conn.execute(
            "SELECT id FROM user_saved_filters WHERE user_email=? AND filter_scope=? AND title=? LIMIT 1",
            (email, scope, data.title),
        ).fetchone()
        if existing:
            row_id = _safe_int(existing[0])
            conn.execute(
                """
                UPDATE user_saved_filters
                SET filter_payload_json=?, updated_at=?
                WHERE id=? AND user_email=?
                """,
                (json.dumps(data.filter_payload or {}, ensure_ascii=False), now, row_id, email),
            )
        else:
            row_id = next_safe_table_id(conn, "user_saved_filters")
            conn.execute(
                """
                INSERT INTO user_saved_filters (
                    id, user_email, filter_scope, title, filter_payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (row_id, email, scope, data.title, json.dumps(data.filter_payload or {}, ensure_ascii=False), now, now),
            )
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "id": row_id}


@router.delete("/api/workbench/saved_filters/{filter_id}")
def delete_workbench_filter(filter_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        conn.execute("DELETE FROM user_saved_filters WHERE id=? AND user_email=?", (_safe_int(filter_id), actor.get("email", "")))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


@router.post("/api/workbench/bulk_actions")
def apply_workbench_bulk_action(data: WorkbenchBulkActionData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    config = _bulk_action_config(data.entity_type)
    action = _safe_text(data.action)
    ids = [_safe_int(row_id) for row_id in (data.ids or []) if _safe_int(row_id) > 0]
    if not config or not action or not ids:
        return {"error": "bulk_action_invalid"}
    module = config.get("module") or ""
    required_action = "read" if action == "export" else "delete" if action == "delete" else "update"
    if action == "send_1c":
        required_action = "export"
    if not (has_permission(actor, module, required_action) or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    table = config["table"]
    timestamp_field = config.get("timestamp_field") or "updated_at"
    placeholders = ",".join("?" for _ in ids)
    conn = get_connection(row_factory=True)
    processed = 0
    rows: list[dict] = []
    now = _now_ts()
    try:
        rows = _row_dicts(conn.execute(f"SELECT * FROM {table} WHERE id IN ({placeholders})", tuple(ids)))
        found_ids = [_safe_int(row.get("id")) for row in rows]
        if action == "export":
            return {"status": "success", "count": len(rows), "items": rows, "entity_type": data.entity_type}
        if action == "delete":
            if found_ids:
                delete_placeholders = ",".join("?" for _ in found_ids)
                conn.execute(f"DELETE FROM {table} WHERE id IN ({delete_placeholders})", tuple(found_ids))
                processed = len(found_ids)
        elif action == "update_status":
            status_field = config.get("status_field") or ""
            if not status_field or not _safe_text(data.status):
                return {"error": "bulk_action_invalid"}
            if found_ids:
                update_placeholders = ",".join("?" for _ in found_ids)
                conn.execute(
                    f"UPDATE {table} SET {status_field}=?, {timestamp_field}=? WHERE id IN ({update_placeholders})",
                    (_safe_text(data.status), now, *found_ids),
                )
                processed = len(found_ids)
        elif action == "assign":
            assignee_field = config.get("assignee_field") or ""
            if not assignee_field or not _safe_text(data.assignee):
                return {"error": "bulk_action_not_supported"}
            if found_ids:
                update_placeholders = ",".join("?" for _ in found_ids)
                conn.execute(
                    f"UPDATE {table} SET {assignee_field}=?, {timestamp_field}=? WHERE id IN ({update_placeholders})",
                    (_safe_text(data.assignee), now, *found_ids),
                )
                processed = len(found_ids)
        elif action == "send_1c":
            conn.close()
            from services.one_c_connector_service import enqueue_one_c_export
            queued = []
            failed = []
            for row_id in ids:
                outcome = enqueue_one_c_export(data.entity_type, row_id, actor.get("email", ""), data.connector_id)
                if outcome.get("status") == "success":
                    queued.append(outcome)
                else:
                    failed.append(outcome)
            audit_log("workbench_bulk_send_1c", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=data.entity_type, entity_id=",".join(str(item) for item in ids[:20]), details={"queued": len(queued), "failed": len(failed)})
            return {"status": "success", "count": len(queued), "queued": len(queued), "failed": len(failed), "errors": failed[:20]}
        else:
            return {"error": "bulk_action_not_supported"}
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    audit_log("workbench_bulk_action", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=data.entity_type, entity_id=",".join(str(item) for item in ids[:20]), details={"action": action, "count": processed, "status": data.status, "assignee": data.assignee})
    return {"status": "success", "count": processed, "entity_type": data.entity_type, "action": action}


def _search_rows(
    conn,
    sql: str,
    params: tuple,
    entity_type: str,
    view: str,
    title_fields: tuple[str, ...],
    meta_fields: tuple[str, ...],
    limit: int,
    type_label: str = "",
) -> list[dict]:
    rows = _row_dicts(conn.execute(sql, params))
    result = []
    for row in rows[:limit]:
        title = next((_safe_text(row.get(field)) for field in title_fields if _safe_text(row.get(field))), f"{entity_type} #{row.get('id')}")
        meta = " · ".join(_search_meta_field_value(field, row.get(field)) for field in meta_fields if _safe_text(row.get(field)))
        result.append({
            "type": entity_type,
            "type_label": type_label or entity_type,
            "entity_type": entity_type,
            "entity_id": _safe_int(row.get("id")),
            "title": title,
            "desc": meta,
            "view": view,
        })
    return result


SEARCH_SOURCES = [
    {
        "permission": ("clients", "read"),
        "entity_type": "lead",
        "type_label": "Лид",
        "view": "leads",
        "sql": """
            SELECT id, title, client_name, contact_name, contact_email, contact_phone, source, stage, next_action, next_action_date
            FROM crm_leads
            WHERE LOWER(
                COALESCE(title,'') || ' ' || COALESCE(client_name,'') || ' ' ||
                COALESCE(contact_name,'') || ' ' || COALESCE(contact_email,'') || ' ' ||
                COALESCE(contact_phone,'') || ' ' || COALESCE(source,'') || ' ' ||
                COALESCE(stage,'') || ' ' || COALESCE(next_action,'')
            ) LIKE ?
            ORDER BY updated_at DESC, id DESC LIMIT ?
        """,
        "title_fields": ("title", "client_name"),
        "meta_fields": ("contact_name", "contact_email", "contact_phone", "stage", "next_action", "next_action_date"),
    },
    {
        "permission": ("clients", "read"),
        "entity_type": "deal",
        "type_label": "Сделка",
        "view": "deals",
        "sql": """
            SELECT id, title, client_name, contract_number, stage, responsible, next_action, next_action_date,
                   CAST(amount AS TEXT) AS amount_text, currency
            FROM crm_deals
            WHERE LOWER(
                COALESCE(title,'') || ' ' || COALESCE(client_name,'') || ' ' ||
                COALESCE(contract_number,'') || ' ' || COALESCE(stage,'') || ' ' ||
                COALESCE(responsible,'') || ' ' || COALESCE(next_action,'') || ' ' ||
                COALESCE(comment,'') || ' ' || COALESCE(CAST(amount AS TEXT),'')
            ) LIKE ?
            ORDER BY updated_at DESC, id DESC LIMIT ?
        """,
        "title_fields": ("title", "contract_number"),
        "meta_fields": ("client_name", "stage", "responsible", "next_action", "next_action_date", "amount_text", "currency"),
    },
    {
        "permission": ("finance", "read"),
        "entity_type": "finance_payment",
        "type_label": "Финансы",
        "view": "finance",
        "sql": """
            SELECT id, title, kind, category, status, due_date, paid_date,
                   CAST(amount AS TEXT) AS amount_text, currency
            FROM finance_payments
            WHERE LOWER(
                COALESCE(title,'') || ' ' || COALESCE(kind,'') || ' ' ||
                COALESCE(category,'') || ' ' || COALESCE(status,'') || ' ' ||
                COALESCE(comment,'') || ' ' || COALESCE(CAST(amount AS TEXT),'')
            ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("title",),
        "meta_fields": ("kind", "status", "amount_text", "currency", "due_date"),
    },
    {
        "permission": ("finance", "read"),
        "entity_type": "finance_request",
        "type_label": "Заявка на оплату",
        "view": "finance",
        "sql": """
            SELECT id, title, request_status, approval_status, due_date,
                   CAST(amount AS TEXT) AS amount_text, currency, approver_name
            FROM finance_payment_requests
            WHERE LOWER(
                COALESCE(title,'') || ' ' || COALESCE(request_status,'') || ' ' ||
                COALESCE(approval_status,'') || ' ' || COALESCE(approver_name,'') || ' ' ||
                COALESCE(comment,'') || ' ' || COALESCE(CAST(amount AS TEXT),'')
            ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("title",),
        "meta_fields": ("request_status", "approval_status", "amount_text", "currency", "due_date", "approver_name"),
    },
    {
        "permission": ("finance", "read"),
        "entity_type": "finance_obligation",
        "type_label": "Обязательство",
        "view": "finance",
        "sql": """
            SELECT id, title, supplier_name, obligation_type, status, due_date,
                   CAST(amount AS TEXT) AS amount_text, currency
            FROM finance_obligations
            WHERE LOWER(
                COALESCE(title,'') || ' ' || COALESCE(supplier_name,'') || ' ' ||
                COALESCE(obligation_type,'') || ' ' || COALESCE(status,'') || ' ' ||
                COALESCE(comment,'') || ' ' || COALESCE(CAST(amount AS TEXT),'')
            ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("title", "supplier_name"),
        "meta_fields": ("obligation_type", "status", "amount_text", "currency", "due_date"),
    },
    {
        "permission": ("supply", "read"),
        "entity_type": "purchase_order",
        "type_label": "Закупка",
        "view": "supply",
        "sql": """
            SELECT id, item_name, item_article, supplier, status, expected_date,
                   CAST(total_amount AS TEXT) AS amount_text
            FROM purchase_orders
            WHERE LOWER(
                COALESCE(item_name,'') || ' ' || COALESCE(item_article,'') || ' ' ||
                COALESCE(supplier,'') || ' ' || COALESCE(status,'') || ' ' ||
                COALESCE(comment,'')
            ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("item_name", "item_article"),
        "meta_fields": ("item_article", "supplier", "status", "amount_text", "expected_date"),
    },
    {
        "permission": ("supply", "read"),
        "entity_type": "procurement_request",
        "type_label": "Заявка закупки",
        "view": "supply",
        "sql": """
            SELECT id, title, request_number, item_name, item_article, priority, status, required_date
            FROM procurement_requests
            WHERE LOWER(
                COALESCE(title,'') || ' ' || COALESCE(request_number,'') || ' ' ||
                COALESCE(item_name,'') || ' ' || COALESCE(item_article,'') || ' ' ||
                COALESCE(priority,'') || ' ' || COALESCE(status,'') || ' ' ||
                COALESCE(comment,'')
            ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("title", "request_number", "item_name"),
        "meta_fields": ("request_number", "item_article", "priority", "status", "required_date"),
    },
    {
        "permission": ("supply", "read"),
        "entity_type": "stock_reservation",
        "type_label": "Резерв склада",
        "view": "supply",
        "sql": """
            SELECT id, nomenclature_name, nomenclature_article, status,
                   CAST(qty AS TEXT) AS qty_text, comment
            FROM stock_reservations
            WHERE LOWER(
                COALESCE(nomenclature_name,'') || ' ' || COALESCE(nomenclature_article,'') || ' ' ||
                COALESCE(status,'') || ' ' || COALESCE(comment,'')
            ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("nomenclature_name", "nomenclature_article"),
        "meta_fields": ("nomenclature_article", "status", "qty_text", "comment"),
    },
    {
        "permission": ("supply", "read"),
        "entity_type": "inventory_document",
        "type_label": "Складской документ",
        "view": "nomenclature",
        "sql": """
            SELECT id, doc_number, doc_type, article, warehouse, bin_code, status, reason
            FROM inventory_documents
            WHERE LOWER(
                COALESCE(doc_number,'') || ' ' || COALESCE(doc_type,'') || ' ' ||
                COALESCE(article,'') || ' ' || COALESCE(warehouse,'') || ' ' ||
                COALESCE(bin_code,'') || ' ' || COALESCE(status,'') || ' ' ||
                COALESCE(reason,'') || ' ' || COALESCE(comment,'')
            ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("doc_number", "article", "doc_type"),
        "meta_fields": ("doc_type", "article", "warehouse", "bin_code", "status"),
    },
    {
        "permission": ("production", "read"),
        "entity_type": "production_order",
        "type_label": "Производство",
        "view": "production",
        "sql": """
            SELECT id, order_name, stage, priority, responsible, planned_finish, comment
            FROM production_orders
            WHERE LOWER(
                COALESCE(order_name,'') || ' ' || COALESCE(stage,'') || ' ' ||
                COALESCE(priority,'') || ' ' || COALESCE(responsible,'') || ' ' ||
                COALESCE(comment,'')
            ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("order_name",),
        "meta_fields": ("stage", "priority", "responsible", "planned_finish"),
    },
    {
        "permission": ("projects", "read"),
        "entity_type": "contract",
        "type_label": "Договор",
        "view": "contract360",
        "sql": """
            SELECT id, contract_number, title, status, manager_name,
                   CAST(amount AS TEXT) AS amount_text, currency, end_date
            FROM contract_master
            WHERE LOWER(
                COALESCE(contract_number,'') || ' ' || COALESCE(title,'') || ' ' ||
                COALESCE(status,'') || ' ' || COALESCE(manager_name,'') || ' ' ||
                COALESCE(comment,'') || ' ' || COALESCE(CAST(amount AS TEXT),'')
            ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("contract_number", "title"),
        "meta_fields": ("title", "status", "manager_name", "amount_text", "currency", "end_date"),
    },
    {
        "permission": ("finance", "read"),
        "entity_type": "epl_waybill",
        "type_label": "ЭПЛ",
        "view": "accounting",
        "sql": """
            SELECT ew.id, ew.number, ew.route_text, ew.cargo, ew.status, ew.integration_status,
                   ew.shift_date, ed.full_name AS driver_name, ev.registration_no AS vehicle_no
            FROM epl_waybills ew
            LEFT JOIN epl_drivers ed ON ed.id = ew.driver_id
            LEFT JOIN epl_vehicles ev ON ev.id = ew.vehicle_id
            WHERE LOWER(
                COALESCE(ew.number,'') || ' ' || COALESCE(ew.route_text,'') || ' ' ||
                COALESCE(ew.cargo,'') || ' ' || COALESCE(ew.status,'') || ' ' ||
                COALESCE(ew.integration_status,'') || ' ' || COALESCE(ew.external_document_id,'') || ' ' ||
                COALESCE(ed.full_name,'') || ' ' || COALESCE(ev.registration_no,'')
            ) LIKE ?
            ORDER BY ew.id DESC LIMIT ?
        """,
        "title_fields": ("number", "route_text"),
        "meta_fields": ("driver_name", "vehicle_no", "status", "integration_status", "shift_date"),
    },
    {
        "permission": ("approvals", "read"),
        "entity_type": "approval",
        "type_label": "Согласование",
        "view": "approvals",
        "sql": """
            SELECT id, title, item_link, status, author, entity_type AS linked_entity_type
            FROM approvals
            WHERE LOWER(
                COALESCE(title,'') || ' ' || COALESCE(item_link,'') || ' ' ||
                COALESCE(status,'') || ' ' || COALESCE(author,'') || ' ' ||
                COALESCE(entity_type,'') || ' ' || COALESCE(entity_id,'')
            ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("title", "item_link"),
        "meta_fields": ("status", "author", "linked_entity_type"),
    },
    {
        "permission": ("emails", "read"),
        "entity_type": "email",
        "type_label": "Письмо",
        "view": "emails",
        "sql": """
            SELECT id, subject, sender, sender_email, folder, received_at, body_preview
            FROM email_messages
            WHERE COALESCE(is_deleted, 0) = 0
              AND LOWER(
                COALESCE(subject,'') || ' ' || COALESCE(sender,'') || ' ' ||
                COALESCE(sender_email,'') || ' ' || COALESCE(body_preview,'')
              ) LIKE ?
            ORDER BY id DESC LIMIT ?
        """,
        "title_fields": ("subject", "sender"),
        "meta_fields": ("sender", "sender_email", "folder", "received_at"),
    },
]


@router.get("/api/search")
def global_search(request: Request, q: str = "", limit: int = 8):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    query = _safe_text(q).lower()
    if len(query) < 1:
        return {"items": []}
    search_terms = [query]
    for token in query.split():
        token = _safe_text(token).lower()
        if token and token not in search_terms:
            search_terms.append(token)
    max_rows = max(1, min(_safe_int(limit) or 8, 20))
    conn = get_connection(row_factory=True)
    try:
        items = []
        seen: set[tuple[str, int, str]] = set()

        def merge_rows(found_rows: list[dict]):
            for item in found_rows:
                key = (
                    _safe_text(item.get("entity_type") or item.get("type")),
                    _safe_int(item.get("entity_id") or item.get("id")),
                    _safe_text(item.get("view")),
                )
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)

        for term in search_terms:
            like = f"%{term}%"
            if has_permission(actor, "projects", "read"):
                merge_rows(_search_rows(
                    conn,
                    "SELECT id, name, contract, client, manager FROM projects WHERE LOWER(COALESCE(name,'') || ' ' || COALESCE(contract,'') || ' ' || COALESCE(client,'') || ' ' || COALESCE(manager,'')) LIKE ? ORDER BY id DESC LIMIT ?",
                    (like, max_rows),
                    "project",
                    "dashboard",
                    ("name", "contract"),
                    ("contract", "client", "manager"),
                    max_rows,
                ))
            if has_permission(actor, "clients", "read"):
                merge_rows(_search_rows(
                    conn,
                    "SELECT id, name, inn, contact FROM clients WHERE LOWER(COALESCE(name,'') || ' ' || COALESCE(inn,'') || ' ' || COALESCE(contact,'')) LIKE ? ORDER BY id DESC LIMIT ?",
                    (like, max_rows),
                    "client",
                    "clients",
                    ("name",),
                    ("inn", "contact"),
                    max_rows,
                ))
            if has_permission(actor, "documents", "read"):
                merge_rows(_search_rows(
                    conn,
                    "SELECT id, number, subject, correspondent, type, status FROM documents WHERE LOWER(COALESCE(number,'') || ' ' || COALESCE(subject,'') || ' ' || COALESCE(correspondent,'')) LIKE ? ORDER BY id DESC LIMIT ?",
                    (like, max_rows),
                    "document",
                    "documents",
                    ("number", "subject"),
                    ("type", "status", "correspondent"),
                    max_rows,
                ))
                for row in search_document_content(conn, term, max_rows):
                    title = _safe_text(row.get("number")) or _safe_text(row.get("subject")) or f"Документ #{row.get('id')}"
                    filename = _safe_text(row.get("original_filename")) or "вложение"
                    excerpt = _safe_text(row.get("content_excerpt"))
                    merge_rows([{
                        "type": "document",
                        "type_label": "Текст вложения",
                        "entity_type": "document",
                        "entity_id": _safe_int(row.get("id")),
                        "title": title,
                        "desc": " · ".join(part for part in (filename, excerpt[:180]) if part),
                        "view": "documents",
                        "match_source": "document_content_index",
                    }])
            if has_permission(actor, "tasks", "read"):
                merge_rows(_search_rows(
                    conn,
                    "SELECT id, title, executor, status, deadline FROM tasks WHERE LOWER(COALESCE(title,'') || ' ' || COALESCE(executor,'')) LIKE ? ORDER BY id DESC LIMIT ?",
                    (like, max_rows),
                    "task",
                    "tasks",
                    ("title",),
                    ("executor", "status", "deadline"),
                    max_rows,
                ))
            for source in SEARCH_SOURCES:
                module, action = source["permission"]
                if not has_permission(actor, module, action):
                    continue
                merge_rows(_search_rows(
                    conn,
                    source["sql"],
                    (like, max_rows),
                    source["entity_type"],
                    source["view"],
                    source["title_fields"],
                    source["meta_fields"],
                    max_rows,
                    source["type_label"],
                ))
        return {"items": items[:max_rows * (4 + len(SEARCH_SOURCES))]}
    finally:
        conn.close()
