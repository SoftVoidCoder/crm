import shutil, json, time, os, datetime, hashlib, re, zipfile
import qrcode
from fastapi import APIRouter, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from database import audit_log, create_notification, create_targeted_notifications, get_connection, is_postgres_backend, notify_entity_watchers
from permissions import require_approved_user, has_permission
from settings import PUBLIC_BASE_URL
from schemas import (
    ApprovalActionData,
    ApprovalData,
    ApprovalRouteTemplateData,
    ApprovalUpdate,
    CryptoSignatureProtocolData,
    CryptoSignatureSessionData,
    DocData,
    DocUpdate,
    DocumentCaseFileData,
    DocumentLegalArchiveActionData,
    DocumentClassifierData,
    DocumentLegalCardData,
    DocumentPackageApprovalData,
    DocumentPackageData,
    DocumentPackageSignData,
    DocumentWorkflowStartData,
    DocumentRetentionDispositionData,
    DocumentRetentionPolicyData,
    DocumentSignatureActionData,
    DocumentSignatureVerifyData,
    DocumentLifecycleActionData,
    DocumentRegistrationJournalData,
    KnowledgeData,
    KnowledgeReadData,
    WorkflowDefinitionData,
    WorkflowStartData,
    WorkflowTokenActionData,
)
from services.document_workflow_service import (
    compose_document_workflow,
    list_documents_for_approval,
    sync_document_workflow,
)
from services.crypto_signature_service import (
    attach_detached_signature,
    attach_validation_protocol,
    begin_signature_session,
    crypto_runtime_status,
    list_document_signature_protocols,
    list_document_signature_sessions,
    verify_signature_session,
)
from services.document_content_index_service import content_extraction_runtime_status, extract_text_from_revision, upsert_document_content_index
from services.document_storage_service import insert_document_file_blob, prepare_document_file
from services.workflow_engine_service import (
    apply_token_action,
    create_definition as workflow_create_definition,
    get_definition as workflow_get_definition,
    get_instance as workflow_get_instance,
    list_definitions as workflow_list_definitions,
    list_instances as workflow_list_instances,
    process_automation as workflow_process_automation,
    start_instance as workflow_start_instance,
)

# === ПОДКЛЮЧАЕМ МЕНЕДЖЕР WEBSOCKETS ===
from utils import manager, make_document_qr_token

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
QR_UPLOADS_DIR = os.path.join(UPLOADS_DIR, "qr")
PACKAGE_EXPORTS_DIR = os.path.join(UPLOADS_DIR, "document_packages")


def _next_local_id(cursor, table_name: str) -> int:
    cursor.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table_name} WHERE id < 2147483647")
    row = cursor.fetchone()
    if isinstance(row, dict):
        values = list(row.values())
        return int(values[0] or 1) if values else 1
    if isinstance(row, (list, tuple)):
        return int(row[0] or 1) if row else 1
    return int(row or 1)


def _safe_text(value) -> str:
    return str(value or "").strip()


def _document_correspondent_fallback(doc_type: str, sender_name: str = "", recipient_name: str = "", correspondent: str = "") -> str:
    direct = _safe_text(correspondent)
    if direct:
        return direct
    sender = _safe_text(sender_name)
    recipient = _safe_text(recipient_name)
    normalized_type = _normalize_doc_type(doc_type)
    if normalized_type == "incoming":
        return sender or recipient
    if normalized_type == "outgoing":
        return recipient or sender
    if sender and recipient:
        return f"{sender} -> {recipient}"
    return sender or recipient


def _load_json_list(raw_value):
    if not raw_value:
        return []
    try:
        data = json.loads(raw_value)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _unique_texts(values) -> list[str]:
    result = []
    for item in values or []:
        text = _safe_text(item)
        if text and text not in result:
            result.append(text)
    return result


def _safe_filename(value: str) -> str:
    raw = os.path.basename(_safe_text(value)) or "document.bin"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")
    return cleaned or "document.bin"


def _format_file_size(size_value) -> str:
    size = max(0, int(size_value or 0))
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{round(size / 1024, 1)} KB"
    return f"{round(size / (1024 * 1024), 2)} MB"


def _today_display() -> str:
    return datetime.datetime.now().strftime("%d.%m.%Y")


def _year_from_display_date(value: str = "") -> str:
    value = _safe_text(value)
    if len(value) >= 10 and value[6:10].isdigit():
        return value[6:10]
    return datetime.datetime.now().strftime("%Y")


def _add_years_display(value: str, years: int) -> str:
    base = datetime.datetime.now()
    try:
        if _safe_text(value):
            base = datetime.datetime.strptime(_safe_text(value), "%d.%m.%Y")
    except Exception:
        pass
    try:
        return base.replace(year=base.year + max(1, int(years or 1))).strftime("%d.%m.%Y")
    except ValueError:
        return base.replace(month=2, day=28, year=base.year + max(1, int(years or 1))).strftime("%d.%m.%Y")


def _normalize_doc_type(value: str) -> str:
    raw = _safe_text(value).lower()
    mapping = {
        "входящий": "incoming",
        "исходящий": "outgoing",
        "внутренний": "internal",
        "договор": "contract",
        "акт": "act",
        "счет": "invoice",
    }
    return mapping.get(raw, raw or "incoming")


def _doc_type_prefix(doc_type: str) -> str:
    mapping = {"incoming": "IN", "outgoing": "OUT", "internal": "INT", "contract": "CTR", "act": "ACT", "invoice": "INV"}
    return mapping.get(_normalize_doc_type(doc_type), "DOC")


def _resolve_public_base_url(request: Request | None = None) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    if request is not None:
        try:
            return str(request.base_url).rstrip("/")
        except Exception:
            pass
    return "http://127.0.0.1:8000"


def _build_document_qr_target_url(document_id: int, request: Request | None = None) -> str:
    base_url = _resolve_public_base_url(request)
    token = make_document_qr_token(document_id)
    return f"{base_url}/qr/doc/{int(document_id or 0)}?token={token}"


def _document_qr_disk_path(document_id: int) -> str:
    return os.path.join(QR_UPLOADS_DIR, f"doc_{int(document_id or 0)}.png")


def _document_qr_public_path(document_id: int) -> str:
    return f"/uploads/qr/doc_{int(document_id or 0)}.png"


def _write_document_qr_asset(document_id: int, request: Request | None = None) -> tuple[str, str]:
    qr_target_url = _build_document_qr_target_url(document_id, request)
    qr = qrcode.make(qr_target_url)
    os.makedirs(QR_UPLOADS_DIR, exist_ok=True)
    qr_disk_path = _document_qr_disk_path(document_id)
    qr.save(qr_disk_path)
    return _document_qr_public_path(document_id), qr_target_url


def _ensure_document_qr(cursor, document_row: dict, request: Request | None = None, force: bool = False) -> dict:
    document_id = int(document_row.get("id") or 0)
    if not document_id:
        return {"qr_code": "", "qr_payload": ""}
    expected_payload = _build_document_qr_target_url(document_id, request)
    qr_code = _safe_text(document_row.get("qr_code"))
    qr_payload = _safe_text(document_row.get("qr_payload"))
    qr_file_exists = bool(qr_code) and os.path.exists(_document_qr_disk_path(document_id))
    if not force and qr_code and qr_file_exists and qr_payload == expected_payload:
        return {"qr_code": qr_code, "qr_payload": qr_payload}
    public_qr_path, payload_url = _write_document_qr_asset(document_id, request)
    cursor.execute(
        "UPDATE documents SET qr_code=?, qr_payload=? WHERE id=?",
        (public_qr_path, payload_url, document_id),
    )
    document_row["qr_code"] = public_qr_path
    document_row["qr_payload"] = payload_url
    return {"qr_code": public_qr_path, "qr_payload": payload_url}


def _format_registration_number(pattern: str, prefix: str, year: str, next_number: int) -> str:
    pattern = _safe_text(pattern) or "{prefix}-{year}-{number}"
    values = {
        "prefix": _safe_text(prefix) or "DOC",
        "year": year,
        "number": str(max(1, int(next_number or 1))).zfill(5),
    }
    try:
        return pattern.format(**values)
    except Exception:
        return "{prefix}-{year}-{number}".format(**values)


def _row_dict(row) -> dict:
    return dict(row) if row else {}


def _json_value(row: dict, field_name: str, default=None):
    default = default if default is not None else []
    raw = row.get(field_name) if row else None
    if isinstance(default, dict):
        return _load_json_dict(raw, default)
    return _load_json_list(raw)


def _ensure_default_registration_journal(cursor, doc_type: str, actor_email: str = "") -> int:
    normalized_type = _normalize_doc_type(doc_type)
    journal_code = f"{_doc_type_prefix(normalized_type)}-DEFAULT"
    cursor.execute("SELECT id FROM document_registration_journals WHERE journal_code=? ORDER BY id DESC LIMIT 1", (journal_code,))
    row = cursor.fetchone()
    if row:
        return int(row["id"] if isinstance(row, dict) else row[0])
    now = int(time.time())
    cursor.execute(
        """
        INSERT INTO document_registration_journals (
            journal_code, journal_name, doc_type, prefix, next_number, numbering_pattern,
            is_active, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, '{prefix}-{year}-{number}', 1, ?, ?, ?)
        """,
        (
            journal_code,
            f"Журнал регистрации {_doc_type_prefix(normalized_type)}",
            normalized_type,
            _doc_type_prefix(normalized_type),
            actor_email,
            now,
            now,
        ),
    )
    return int(cursor.lastrowid)


def _ensure_lifecycle_event(cursor, document_id: int, from_state: str, to_state: str, action_name: str, actor: dict, comment: str = ""):
    cursor.execute(
        """
        INSERT INTO document_lifecycle_events (
            document_id, from_state, to_state, action_name, actor_email, actor_name, comment, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(document_id or 0),
            _safe_text(from_state),
            _safe_text(to_state),
            _safe_text(action_name) or "state_change",
            _safe_text(actor.get("email")),
            _safe_text(actor.get("name")),
            _safe_text(comment),
            int(time.time()),
        ),
    )


def _ensure_document_task_link(cursor, document: dict, task_id: int, actor: dict):
    task_id = int(task_id or 0)
    document_id = int(document.get("id") or 0)
    if not document_id or not task_id:
        return
    cursor.execute(
        "SELECT id FROM document_linked_tasks WHERE document_id=? AND task_id=? ORDER BY id DESC LIMIT 1",
        (document_id, task_id),
    )
    row = cursor.fetchone()
    now = int(time.time())
    if row:
        cursor.execute(
            """
            UPDATE document_linked_tasks
            SET title=?, assignee_name=?, deadline=?, priority=?, status=?, updated_at=?
            WHERE id=?
            """,
            (
                f"Поручение по документу №{_safe_text(document.get('number')) or document_id}",
                _safe_text(document.get("resolution_assignee")),
                _safe_text(document.get("resolution_deadline")),
                _safe_text(document.get("priority")) or "normal",
                "active",
                now,
                int(row["id"] if isinstance(row, dict) else row[0]),
            ),
        )
        return
    cursor.execute(
        """
        INSERT INTO document_linked_tasks (
            document_id, task_id, title, assignee_name, deadline, priority, status, comment, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        """,
        (
            document_id,
            task_id,
            f"Поручение по документу №{_safe_text(document.get('number')) or document_id}",
            _safe_text(document.get("resolution_assignee")),
            _safe_text(document.get("resolution_deadline")),
            _safe_text(document.get("priority")) or "normal",
            _safe_text(document.get("resolution")),
            _safe_text(actor.get("email")),
            now,
            now,
        ),
    )


def _sync_document_production_relation(cursor, document_id: int, production_order_id: int, actor: dict):
    document_id = int(document_id or 0)
    cursor.execute(
        """
        DELETE FROM document_relations
        WHERE source_entity_type='document'
          AND source_entity_id=?
          AND target_entity_type='production_order'
          AND relation_type='production_document'
        """,
        (document_id,),
    )
    production_order_id = int(production_order_id or 0)
    if not document_id or production_order_id <= 0:
        return
    cursor.execute("SELECT id FROM production_orders WHERE id=? LIMIT 1", (production_order_id,))
    if not cursor.fetchone():
        return
    cursor.execute(
        """
        INSERT INTO document_relations (
            source_entity_type, source_entity_id, target_entity_type, target_entity_id,
            relation_type, package_id, meta_json, created_by, created_at
        ) VALUES ('document', ?, 'production_order', ?, 'production_document', 0, '{}', ?, ?)
        """,
        (document_id, production_order_id, _safe_text(actor.get("email")), int(time.time())),
    )


def _document_workflow_route_context(document: dict, extra: dict | None = None) -> dict:
    context = {
        "document_id": int(document.get("id") or 0),
        "doc_type": _normalize_doc_type(document.get("type", "")),
        "priority": _safe_text(document.get("priority")) or "normal",
        "lifecycle_state": _safe_text(document.get("lifecycle_state") or document.get("status")),
        "legal_significance": _safe_text(document.get("legal_significance")),
        "confidentiality_level": _safe_text(document.get("confidentiality_level")),
        "project_id": int(document.get("project_id") or 0),
        "has_resolution": int(bool(_safe_text(document.get("resolution")) and int(document.get("resolution_task_id") or 0))),
    }
    context.update(extra or {})
    return context


def _resolve_document_workflow_route(cursor, document: dict, actor: dict, route_rules: list[dict] | None = None, route_context: dict | None = None) -> list[dict]:
    if route_rules:
        return route_rules
    context = _document_workflow_route_context(document, route_context)
    rows = [
        dict(row)
        for row in cursor.execute(
            """
            SELECT *
            FROM approval_route_templates
            WHERE entity_type IN ('', 'document') AND is_active=1
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
    ]
    for row in rows:
        conditions = _load_json_dict(row.get("conditions_json"), {})
        stages = _load_json_list(row.get("stages_json"))
        if not stages:
            continue
        if not conditions or _approval_condition_matches(conditions, context):
            return stages
    director_name = _approval_find_role_user(cursor, "Директор") or _safe_text(actor.get("name")) or _safe_text(document.get("resolution_author"))
    return [
        {
            "stage_key": "document_review",
            "stage_name": "Согласование входящего документа",
            "assignees": [director_name] if director_name else [],
            "sla_hours": 24,
            "allow_delegate": 1,
            "parallel_mode": "all",
        }
    ]


def _register_document(cursor, document: dict, journal_id: int, actor: dict, comment: str = "") -> tuple[str, int]:
    document_id = int(document.get("id") or 0)
    cursor.execute(
        """
        SELECT registration_number, journal_id
        FROM document_registration_records
        WHERE document_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (document_id,),
    )
    existing = cursor.fetchone()
    if existing:
        return _safe_text(existing["registration_number"] if isinstance(existing, dict) else existing[0]), int(existing["journal_id"] if isinstance(existing, dict) else existing[1])
    journal_id = int(journal_id or 0) or _ensure_default_registration_journal(cursor, document.get("type", ""), actor.get("email", ""))
    cursor.execute("SELECT * FROM document_registration_journals WHERE id=? AND is_active=1", (journal_id,))
    journal = _row_dict(cursor.fetchone())
    if not journal:
        journal_id = _ensure_default_registration_journal(cursor, document.get("type", ""), actor.get("email", ""))
        cursor.execute("SELECT * FROM document_registration_journals WHERE id=?", (journal_id,))
        journal = _row_dict(cursor.fetchone())
    year = _year_from_display_date(document.get("d_date", ""))
    registration_number = _format_registration_number(journal.get("numbering_pattern", ""), journal.get("prefix", ""), year, int(journal.get("next_number") or 1))
    now = int(time.time())
    cursor.execute(
        """
        INSERT INTO document_registration_records (
            document_id, journal_id, registration_number, registration_date, registered_by, status, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, 'registered', ?, ?)
        """,
        (
            document_id,
            journal_id,
            registration_number,
            _today_display(),
            actor.get("email", ""),
            json.dumps({"comment": comment or "", "source": "legal_card"}, ensure_ascii=False),
            now,
        ),
    )
    cursor.execute("UPDATE document_registration_journals SET next_number=next_number + 1, updated_at=? WHERE id=?", (now, journal_id))
    return registration_number, journal_id


def _legal_card_quality(document: dict, registration_records: list[dict], classifier: dict, case_file: dict) -> dict:
    required = set(_load_json_list(classifier.get("required_fields", ""))) if classifier else set()
    if not required:
        required = {"registration_number", "classifier_id", "case_file_id", "retention_until", "legal_significance"}
    field_map = {
        "registration_number": document.get("registration_number") or (registration_records[0].get("registration_number") if registration_records else ""),
        "classifier_id": document.get("classifier_id"),
        "case_file_id": document.get("case_file_id"),
        "retention_until": document.get("retention_until"),
        "legal_significance": document.get("legal_significance"),
        "confidentiality_level": document.get("confidentiality_level"),
        "file_url": document.get("file_url"),
    }
    missing = [field for field in sorted(required) if not field_map.get(field)]
    return {"status": "complete" if not missing else "incomplete", "missing_fields": missing, "required_fields": sorted(required)}


def _retention_allowed_roles(policy: dict, classifier: dict, case_file: dict) -> list[str]:
    return (
        _unique_texts(_json_value(case_file, "allowed_roles_json", []))
        or _unique_texts(_json_value(policy, "access_roles_json", []))
        or _unique_texts(_json_value(classifier, "allowed_roles_json", []))
    )


def _can_access_case_scope(actor: dict, document: dict, classifier: dict, case_file: dict, policy: dict) -> bool:
    role_name = _safe_text(actor.get("role"))
    actor_name = _safe_text(actor.get("name"))
    actor_email = _safe_text(actor.get("email"))
    if role_name == "Директор":
        return True
    allowed_roles = _retention_allowed_roles(policy, classifier, case_file)
    if not allowed_roles:
        return True
    if role_name in allowed_roles:
        return True
    if actor_name and actor_name == _safe_text(case_file.get("responsible_name")):
        return True
    if actor_name and actor_name == _safe_text(document.get("author")):
        return True
    if actor_email and actor_email == _safe_text(document.get("registered_by")):
        return True
    return False


def _find_retention_policy(conn, document: dict, classifier: dict, case_file: dict) -> dict:
    candidates = []
    if int(case_file.get("retention_policy_id") or 0):
        candidates.append(("id", int(case_file.get("retention_policy_id") or 0)))
    if int(classifier.get("retention_policy_id") or 0):
        candidates.append(("id", int(classifier.get("retention_policy_id") or 0)))
    if _safe_text(case_file.get("case_index")):
        candidates.append(("scope", ("case_file", _safe_text(case_file.get("case_index")))))
    if _safe_text(classifier.get("classifier_code")):
        candidates.append(("scope", ("classifier", _safe_text(classifier.get("classifier_code")))))
    if _safe_text(document.get("document_kind_code")):
        candidates.append(("scope", ("document_kind", _safe_text(document.get("document_kind_code")))))
    if _safe_text(document.get("type")):
        candidates.append(("scope", ("doc_type", _normalize_doc_type(document.get("type")))))
    for kind, value in candidates:
        if kind == "id":
            row = _row_dict(conn.execute("SELECT * FROM document_retention_policies WHERE id=? AND is_active=1", (int(value or 0),)).fetchone())
        else:
            scope_type, scope_value = value
            row = _row_dict(
                conn.execute(
                    "SELECT * FROM document_retention_policies WHERE scope_type=? AND scope_value=? AND is_active=1 ORDER BY updated_at DESC, id DESC LIMIT 1",
                    (scope_type, scope_value),
                ).fetchone()
            )
        if row:
            row["access_roles"] = _json_value(row, "access_roles_json", [])
            row["confidentiality_levels"] = _json_value(row, "confidentiality_levels_json", [])
            return row
    return {}


def _document_scope_access(conn, actor: dict, document_id: int) -> tuple[bool, dict, dict, dict, dict]:
    document = _row_dict(conn.execute("SELECT * FROM documents WHERE id=?", (int(document_id or 0),)).fetchone())
    if not document:
        return False, {}, {}, {}, {}
    classifier = _row_dict(conn.execute("SELECT * FROM document_classifiers WHERE id=?", (int(document.get("classifier_id") or 0),)).fetchone())
    case_file = _row_dict(conn.execute("SELECT * FROM document_case_files WHERE id=?", (int(document.get("case_file_id") or 0),)).fetchone())
    policy = _find_retention_policy(conn, document, classifier, case_file)
    return _can_access_case_scope(actor, document, classifier, case_file, policy), document, classifier, case_file, policy


def _retention_review_due(retention_until: str, review_before_days: int) -> str:
    target = _parse_display_datetime(retention_until)
    if not target:
        return ""
    return (target - datetime.timedelta(days=max(0, int(review_before_days or 0)))).strftime("%d.%m.%Y")


def _retention_status(document: dict, policy: dict, archive_entries: list[dict]) -> dict:
    retention_until = _safe_text(document.get("retention_until"))
    if not retention_until and archive_entries:
        retention_until = _safe_text(archive_entries[0].get("retention_until"))
    review_before_days = int(policy.get("review_before_days") or 90)
    due_dt = _parse_display_datetime(retention_until)
    now = datetime.datetime.now()
    archive_status = _safe_text(archive_entries[0].get("archive_status")) if archive_entries else ""
    if not due_dt:
        return {"status": "not_configured", "retention_until": retention_until, "days_left": None, "review_due_at": ""}
    days_left = round((due_dt - now).total_seconds() / 86400)
    review_due_at = _retention_review_due(retention_until, review_before_days)
    status = "active"
    if archive_status in {"destroyed", "written_off"}:
        status = "destroyed"
    elif archive_status in {"transferred", "moved", "external_archive"}:
        status = "transferred"
    elif days_left < 0:
        status = "expired"
    elif days_left <= review_before_days:
        status = "review_due"
    return {
        "status": status,
        "retention_until": retention_until,
        "days_left": days_left,
        "review_due_at": review_due_at,
        "archive_status": archive_status or "none",
        "review_before_days": review_before_days,
    }


def _load_document_file_revisions(conn, document_id: int) -> tuple[list[dict], dict]:
    revisions = [dict(row) for row in conn.execute("SELECT * FROM document_file_revisions WHERE document_id=? ORDER BY revision_no DESC, uploaded_at DESC, id DESC", (int(document_id or 0),)).fetchall()]
    for row in revisions:
        row["is_current"] = int(row.get("is_current") or 0)
        row["size_label"] = _format_file_size(row.get("file_size"))
    active = next((row for row in revisions if int(row.get("is_current") or 0)), revisions[0] if revisions else {})
    return revisions, active or {}


def _create_document_file_revision(cursor, document: dict, actor: dict, upload_name: str, content_type: str, file_bytes: bytes, comment: str = "", make_current: int = 1, source: str = "upload") -> dict:
    document_id = int(document.get("id") or 0)
    if not document_id:
        raise ValueError("document_id_required")
    current_row = _row_dict(cursor.execute("SELECT COALESCE(MAX(revision_no), 0) AS revision_no FROM document_file_revisions WHERE document_id=?", (document_id,)).fetchone())
    revision_no = int(current_row.get("revision_no") or 0) + 1
    storage = prepare_document_file(document_id, revision_no, upload_name, content_type, file_bytes or b"")
    if storage.get("validation_status") == "rejected":
        try:
            os.remove(storage.get("disk_path", ""))
        except Exception:
            pass
        raise ValueError("document_file_validation_failed:" + ",".join(storage.get("validation_errors") or []))
    now = int(time.time())
    should_make_current = int(make_current or 0)
    if not should_make_current:
        current_revision = _row_dict(cursor.execute("SELECT id FROM document_file_revisions WHERE document_id=? AND is_current=1 ORDER BY revision_no DESC, id DESC LIMIT 1", (document_id,)).fetchone())
        should_make_current = 0 if current_revision else 1
    if should_make_current:
        cursor.execute(
            """
            UPDATE document_file_revisions
            SET is_current=0,
                revision_status=CASE WHEN revision_status='active' THEN 'archived' ELSE revision_status END,
                archived_at=CASE WHEN archived_at=0 THEN ? ELSE archived_at END
            WHERE document_id=? AND is_current=1
            """,
            (now, document_id),
        )
        cursor.execute("UPDATE documents SET file_url=? WHERE id=?", (storage["file_url"], document_id))
    cursor.execute(
        """
        INSERT INTO document_file_revisions (
            document_id, revision_no, revision_label, original_filename, stored_filename, file_url, mime_type,
            file_size, checksum, revision_status, is_current, source, comment, uploaded_by, uploaded_at, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            revision_no,
            f"file-v{revision_no}",
            storage["original_filename"],
            storage["stored_filename"],
            storage["file_url"],
            storage["detected_mime_type"],
            int(storage["file_size"] or 0),
            storage["checksum"],
            "active" if should_make_current else "archived",
            int(should_make_current),
            _safe_text(source) or "upload",
            _safe_text(comment),
            actor.get("email", ""),
            now,
            0 if should_make_current else now,
        ),
    )
    revision_id = int(cursor.lastrowid)
    revision = {
        "id": revision_id,
        "document_id": document_id,
        "revision_no": revision_no,
        "revision_label": f"file-v{revision_no}",
        "file_url": storage["file_url"],
        "stored_filename": storage["stored_filename"],
        "original_filename": storage["original_filename"],
        "mime_type": storage["detected_mime_type"],
        "file_size": int(storage["file_size"] or 0),
        "size_label": _format_file_size(storage.get("file_size")),
        "checksum": storage["checksum"],
        "revision_status": "active" if should_make_current else "archived",
        "is_current": int(should_make_current),
        "uploaded_at": now,
        "comment": _safe_text(comment),
    }
    blob = insert_document_file_blob(cursor, document_id, revision_id, storage, actor.get("email", ""))
    revision["blob_id"] = int(blob.get("id") or 0)
    revision["storage"] = {
        "blob_id": int(blob.get("id") or 0),
        "antivirus_status": storage.get("antivirus_status", ""),
        "validation_status": storage.get("validation_status", ""),
        "detected_mime_type": storage.get("detected_mime_type", ""),
    }
    extracted = extract_text_from_revision(revision)
    index_row = upsert_document_content_index(cursor, document, revision, revision["blob_id"], extracted, source_type="file")
    revision["content_index"] = {
        "id": int(index_row.get("id") or 0),
        "extraction_status": index_row.get("extraction_status", ""),
        "extraction_method": index_row.get("extraction_method", ""),
        "confidence": index_row.get("confidence", 0),
        "content_excerpt": index_row.get("content_excerpt", ""),
    }
    return revision


def _file_revision_diff(current: dict, previous: dict) -> list[dict]:
    labels = {
        "original_filename": "Имя файла",
        "mime_type": "Тип",
        "file_size": "Размер",
        "checksum": "Контрольная сумма",
        "revision_status": "Статус",
        "file_url": "Файл",
    }
    items = []
    for field_name, title in labels.items():
        before = previous.get(field_name)
        after = current.get(field_name)
        if before == after:
            continue
        items.append({"field_name": field_name, "title": title, "before": before, "after": after})
    return items


def _parse_display_datetime(value: str) -> datetime.datetime | None:
    raw = _safe_text(value)
    if not raw:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def _signature_legal_force(signature_kind: str) -> str:
    raw = _safe_text(signature_kind).lower()
    if any(token in raw for token in ("кэп", "укэп", "qualified")):
        return "qualified"
    if any(token in raw for token in ("нэп", "унэп", "enhanced", "unqualified")):
        return "enhanced"
    return "simple"


def _certificate_status_snapshot(certificate: dict) -> tuple[str, str]:
    if not certificate:
        return "missing_certificate", "Сертификат не найден"
    if int(certificate.get("revoked_at") or 0) or _safe_text(certificate.get("status")).lower() in {"revoked", "blocked"}:
        return "revoked", "Сертификат отозван или заблокирован"
    now_dt = datetime.datetime.now()
    try:
        grace_days = max(1, int(os.getenv("KORDA_CERTIFICATE_GRACE_DAYS") or 365))
    except Exception:
        grace_days = 365
    valid_from = _parse_display_datetime(certificate.get("valid_from", ""))
    valid_to = _parse_display_datetime(certificate.get("valid_to", ""))
    if valid_from and now_dt < valid_from:
        return "not_active_yet", "Сертификат еще не вступил в силу"
    if valid_to and now_dt > valid_to + datetime.timedelta(days=grace_days):
        return "expired", "Срок действия сертификата истек"
    if _safe_text(certificate.get("status")).lower() not in {"", "active", "issued", "valid"}:
        return "inactive", "Сертификат неактивен"
    return "valid", "Сертификат действителен"


def _certificate_owned_by_actor(certificate: dict, actor: dict, signer_name: str = "") -> bool:
    owner_email = _safe_text(certificate.get("owner_email"))
    owner_name = _safe_text(certificate.get("owner_name"))
    actor_email = _safe_text(actor.get("email"))
    actor_name = _safe_text(actor.get("name"))
    signer_name = _safe_text(signer_name)
    if owner_email and owner_email == actor_email:
        return True
    if owner_name and owner_name in {actor_name, signer_name}:
        return True
    return not owner_email and not owner_name


def _load_document_archive_entries(conn, document_id: int) -> list[dict]:
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM document_legal_archive WHERE document_id=? ORDER BY created_at DESC, id DESC",
            (int(document_id or 0),),
        ).fetchall()
    ]
    for row in rows:
        row["archive_payload"] = _load_json_dict(row.get("archive_payload_json"))
        row["access_roles"] = _load_json_list(row.get("access_roles_json"))
    return rows


def _load_document_signatures(conn, document_id: int) -> tuple[list[dict], dict]:
    current_revision = _row_dict(conn.execute("SELECT * FROM document_file_revisions WHERE document_id=? AND is_current=1 ORDER BY revision_no DESC, id DESC LIMIT 1", (int(document_id or 0),)).fetchone())
    signatures = [
        dict(row)
        for row in conn.execute(
            """
            SELECT *
            FROM edo_signature_registry
            WHERE entity_type='document' AND entity_id=?
            ORDER BY created_at DESC, id DESC
            """,
            (int(document_id or 0),),
        ).fetchall()
    ]
    valid_total = 0
    qualified_total = 0
    latest_valid = {}
    current_valid_total = 0
    stale_total = 0
    for row in signatures:
        row["stamp"] = _load_json_dict(row.get("stamp_json"))
        row["verification_details"] = _load_json_dict(row.get("verification_details"))
        certificate = {}
        if int(row.get("certificate_id") or 0):
            certificate = _row_dict(conn.execute("SELECT * FROM edo_certificates WHERE id=?", (int(row.get("certificate_id") or 0),)).fetchone())
        if not certificate and _safe_text(row.get("certificate_thumbprint")):
            certificate = _row_dict(conn.execute("SELECT * FROM edo_certificates WHERE thumbprint=? ORDER BY updated_at DESC, id DESC LIMIT 1", (_safe_text(row.get("certificate_thumbprint")),)).fetchone())
        revision = {}
        if int(row.get("document_revision_id") or 0):
            revision = _row_dict(conn.execute("SELECT * FROM document_file_revisions WHERE id=?", (int(row.get("document_revision_id") or 0),)).fetchone())
        row["certificate"] = certificate
        row["revision"] = revision
        protocol = {}
        if int(row.get("validation_protocol_id") or 0):
            protocol = _row_dict(conn.execute("SELECT * FROM signature_validation_protocols WHERE id=?", (int(row.get("validation_protocol_id") or 0),)).fetchone())
        if not protocol and int(row.get("signature_session_id") or 0):
            protocol = _row_dict(conn.execute("SELECT * FROM signature_validation_protocols WHERE session_id=? ORDER BY created_at DESC, id DESC LIMIT 1", (int(row.get("signature_session_id") or 0),)).fetchone())
        if protocol:
            protocol["checks"] = _load_json_dict(protocol.get("checks_json"))
            protocol["raw_protocol"] = _load_json_dict(protocol.get("raw_protocol_json"))
        row["validation_protocol"] = protocol
        row["thumbprint_short"] = _safe_text(row.get("certificate_thumbprint"))[:12]
        row["legal_force"] = _safe_text(row.get("legal_force")) or _signature_legal_force(row.get("signature_kind", ""))
        row["verification_status"] = _safe_text(row.get("verification_status")) or "pending"
        row["verification_message"] = _safe_text(row.get("verification_message"))
        covers_current = bool(
            current_revision
            and revision
            and int(revision.get("id") or 0) == int(current_revision.get("id") or 0)
            and _safe_text(row.get("signed_hash")) == _safe_text(current_revision.get("checksum"))
        )
        row["covers_current_revision"] = int(covers_current)
        if row["verification_status"] == "valid" and not covers_current:
            row["card_status"] = "stale_revision"
            row["card_message"] = "Подпись не покрывает текущую версию файла"
            stale_total += 1
        elif row["verification_status"] == "revoked" or int(row.get("revoked_at") or 0) or _safe_text(certificate.get("status")).lower() in {"revoked", "blocked"}:
            row["card_status"] = "certificate_revoked"
            row["card_message"] = "Сертификат отозван"
        elif row["verification_status"] == "valid":
            row["card_status"] = "valid"
            row["card_message"] = "Подпись действительна"
        else:
            row["card_status"] = row["verification_status"]
            row["card_message"] = row["verification_message"] or "Подпись ожидает проверки"
        if row["verification_status"] == "valid":
            valid_total += 1
            if covers_current:
                current_valid_total += 1
            if row["legal_force"] == "qualified":
                qualified_total += 1
            if not latest_valid:
                latest_valid = row
    summary = {
        "signatures_total": len(signatures),
        "valid_signatures_total": valid_total,
        "current_revision_valid_signatures_total": current_valid_total,
        "stale_signatures_total": stale_total,
        "qualified_signatures_total": qualified_total,
        "latest_signature": signatures[0] if signatures else {},
        "latest_valid_signature": latest_valid,
        "legal_force": "qualified" if qualified_total and current_valid_total else ("signed" if current_valid_total else "unsigned"),
        "status": "complete" if current_valid_total else ("stale_revision" if stale_total else "pending"),
        "display_status": "Подпись действительна" if current_valid_total else ("Подпись не покрывает текущую версию файла" if stale_total else "Нет действительной подписи"),
    }
    return signatures, summary


def _document_signature_quality(document: dict, signatures: list[dict], archive_entries: list[dict], active_file_revision: dict) -> dict:
    missing = []
    valid_signatures = [row for row in signatures if _safe_text(row.get("verification_status")) == "valid" and int(row.get("covers_current_revision") or 0)]
    if not active_file_revision:
        missing.append("active_file_revision")
    if not valid_signatures:
        stale = any(_safe_text(row.get("verification_status")) == "valid" for row in signatures)
        missing.append("current_revision_signature" if stale else "verified_signature")
    lifecycle_state = _safe_text(document.get("lifecycle_state")) or _safe_text(document.get("status")) or "draft"
    if lifecycle_state == "archived" and not archive_entries:
        missing.append("legal_archive")
    latest_archive = archive_entries[0] if archive_entries else {}
    if latest_archive and _safe_text(latest_archive.get("archive_hash")) and active_file_revision:
        if _safe_text(latest_archive.get("archive_hash")) != _safe_text(active_file_revision.get("checksum")) and lifecycle_state == "archived":
            missing.append("archive_integrity")
    legal_force = "qualified" if any(_safe_text(row.get("legal_force")) == "qualified" for row in valid_signatures) else ("signed" if valid_signatures else "unsigned")
    return {
        "status": "complete" if not missing else "incomplete",
        "missing_fields": missing,
        "legal_force": legal_force,
        "signed_documents_ready": int(bool(active_file_revision and valid_signatures)),
        "archive_entries_total": len(archive_entries),
        "valid_signatures_total": len(valid_signatures),
    }


def _build_signature_stamp(document: dict, revision: dict, certificate: dict, signer_name: str, signer_role: str, signed_at: str, signature_kind: str, provider: str) -> dict:
    thumbprint = _safe_text(certificate.get("thumbprint"))
    return {
        "stamp_label": f"{_safe_text(signature_kind) or 'ЭП'} подписан",
        "document_number": _safe_text(document.get("number")) or f"#{int(document.get('id') or 0)}",
        "document_subject": _safe_text(document.get("subject")),
        "revision_label": _safe_text(revision.get("revision_label")) or f"file-v{int(revision.get('revision_no') or 0)}",
        "original_filename": _safe_text(revision.get("original_filename")),
        "checksum": _safe_text(revision.get("checksum")),
        "signer_name": _safe_text(signer_name),
        "signer_role": _safe_text(signer_role),
        "signed_at": _safe_text(signed_at) or _today_display(),
        "provider": _safe_text(provider) or "1С-ЭДО",
        "certificate_id": int(certificate.get("id") or 0),
        "thumbprint": thumbprint,
        "thumbprint_short": thumbprint[:12],
        "serial_number": _safe_text(certificate.get("serial_number")),
        "valid_to": _safe_text(certificate.get("valid_to")),
        "legal_force": _signature_legal_force(signature_kind),
    }


def _verify_document_signature(signature: dict, certificate: dict, revision: dict) -> tuple[str, str, dict]:
    if not signature:
        return "missing_signature", "Подпись не найдена", {}
    if not revision:
        return "missing_revision", "Ревизия файла для подписи не найдена", {}
    certificate_status, certificate_message = _certificate_status_snapshot(certificate)
    if certificate_status != "valid":
        return certificate_status, certificate_message, {"certificate_status": certificate_status}
    signed_hash = _safe_text(signature.get("signed_hash"))
    revision_hash = _safe_text(revision.get("checksum"))
    if not signed_hash or not revision_hash:
        return "hash_missing", "Нет контрольной суммы для проверки подписи", {"signed_hash": signed_hash, "revision_hash": revision_hash}
    if signed_hash != revision_hash:
        return "hash_mismatch", "Контрольная сумма файла не совпадает с подписанной ревизией", {"signed_hash": signed_hash, "revision_hash": revision_hash}
    if int(signature.get("revoked_at") or 0) or _safe_text(signature.get("signature_status")).lower() in {"revoked", "invalid"}:
        return "signature_revoked", "Подпись отозвана или помечена как недействительная", {"signature_status": signature.get("signature_status")}
    return "valid", "Подпись и сертификат успешно подтверждены", {"signed_hash": signed_hash, "revision_hash": revision_hash}


def _archive_document_snapshot(cursor, document: dict, signature: dict, revision: dict, actor: dict, data: DocumentLegalArchiveActionData | None = None) -> dict:
    archive_data = data or DocumentLegalArchiveActionData()
    document_id = int(document.get("id") or 0)
    now = int(time.time())
    archive_code = _safe_text(archive_data.archive_code) or f"ARCH-{datetime.datetime.now().strftime('%Y%m%d')}-{document_id}"
    retention_until = _safe_text(archive_data.retention_until) or _safe_text(document.get("retention_until")) or _add_years_display(document.get("d_date", ""), 5)
    access_roles = _unique_texts(archive_data.access_roles or [])
    archive_payload = {
        "document_number": _safe_text(document.get("number")),
        "document_subject": _safe_text(document.get("subject")),
        "registration_number": _safe_text(document.get("registration_number")),
        "revision_id": int(revision.get("id") or 0),
        "revision_label": _safe_text(revision.get("revision_label")),
        "file_url": _safe_text(revision.get("file_url")),
        "checksum": _safe_text(revision.get("checksum")),
        "signature_id": int(signature.get("id") or 0),
        "signed_at": _safe_text(signature.get("signed_at")),
        "signature_kind": _safe_text(signature.get("signature_kind")),
        "signer_name": _safe_text(signature.get("signer_name")),
        "certificate_id": int(signature.get("certificate_id") or 0),
        "certificate_thumbprint": _safe_text(signature.get("certificate_thumbprint")),
        "verification_status": _safe_text(signature.get("verification_status")),
    }
    cursor.execute(
        """
        INSERT INTO document_legal_archive (
            document_id, archive_code, storage_path, retention_until, archive_status, certificate_id,
            comment, created_by, created_at, updated_at, archived_revision_id, archive_hash, archive_payload_json, source_signature_id,
            policy_id, access_roles_json, transfer_basis, destruction_basis, review_due_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            archive_code,
            _safe_text(archive_data.storage_path) or f"/archive/documents/{document_id}",
            retention_until,
            _safe_text(archive_data.archive_status) or "archived",
            int(signature.get("certificate_id") or 0),
            _safe_text(archive_data.comment),
            actor.get("email", ""),
            now,
            now,
            int(revision.get("id") or 0),
            _safe_text(revision.get("checksum")),
            json.dumps(archive_payload, ensure_ascii=False),
            int(signature.get("id") or 0),
            int(archive_data.policy_id or 0),
            json.dumps(access_roles, ensure_ascii=False),
            _safe_text(archive_data.transfer_basis),
            _safe_text(archive_data.destruction_basis),
            _safe_text(archive_data.review_due_at),
        ),
    )
    archive_id = int(cursor.lastrowid or 0)
    return {"id": archive_id, "archive_code": archive_code, "archive_payload": archive_payload}


def _log_retention_action(cursor, document_id: int, archive_id: int, action_name: str, previous_status: str, new_status: str, basis_text: str, actor: dict, details: dict | None = None, storage_path: str = "", retention_until: str = "", review_due_at: str = ""):
    cursor.execute(
        """
        INSERT INTO document_retention_actions (
            document_id, archive_id, action_name, previous_status, new_status, basis_text, storage_path,
            retention_until, review_due_at, details_json, actor_email, actor_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(document_id or 0),
            int(archive_id or 0),
            _safe_text(action_name) or "review",
            _safe_text(previous_status),
            _safe_text(new_status),
            _safe_text(basis_text),
            _safe_text(storage_path),
            _safe_text(retention_until),
            _safe_text(review_due_at),
            json.dumps(details or {}, ensure_ascii=False),
            _safe_text(actor.get("email")),
            _safe_text(actor.get("name")),
            int(time.time()),
        ),
    )


def _load_document_legal_card(conn, document_id: int, actor: dict | None = None) -> dict:
    doc = _row_dict(conn.execute("SELECT * FROM documents WHERE id=?", (int(document_id or 0),)).fetchone())
    if not doc:
        return {}
    normalized_type = _normalize_doc_type(doc.get("type", ""))
    journal = _row_dict(conn.execute("SELECT * FROM document_registration_journals WHERE id=?", (int(doc.get("registration_journal_id") or 0),)).fetchone())
    classifier = _row_dict(conn.execute("SELECT * FROM document_classifiers WHERE id=?", (int(doc.get("classifier_id") or 0),)).fetchone())
    case_file = _row_dict(conn.execute("SELECT * FROM document_case_files WHERE id=?", (int(doc.get("case_file_id") or 0),)).fetchone())
    classifier["allowed_roles"] = _json_value(classifier, "allowed_roles_json", [])
    case_file["allowed_roles"] = _json_value(case_file, "allowed_roles_json", [])
    retention_policy = _find_retention_policy(conn, doc, classifier, case_file)
    if actor and not _can_access_case_scope(actor, doc, classifier, case_file, retention_policy):
        return {"error": "forbidden"}
    registration_records = [dict(row) for row in conn.execute("SELECT * FROM document_registration_records WHERE document_id=? ORDER BY created_at DESC, id DESC", (int(document_id or 0),)).fetchall()]
    lifecycle_events = [dict(row) for row in conn.execute("SELECT * FROM document_lifecycle_events WHERE document_id=? ORDER BY created_at DESC, id DESC", (int(document_id or 0),)).fetchall()]
    versions = [dict(row) for row in conn.execute("SELECT * FROM document_versions WHERE document_id=? ORDER BY version_no DESC, created_at DESC, id DESC", (int(document_id or 0),)).fetchall()]
    templates = [dict(row) for row in conn.execute("SELECT * FROM document_templates WHERE doc_type=? AND status='active' ORDER BY updated_at DESC, id DESC", (normalized_type,)).fetchall()]
    print_forms = [dict(row) for row in conn.execute("SELECT * FROM document_print_forms WHERE document_id=? ORDER BY updated_at DESC, id DESC", (int(document_id or 0),)).fetchall()]
    file_revisions, active_file_revision = _load_document_file_revisions(conn, document_id)
    signatures, signature_summary = _load_document_signatures(conn, document_id)
    signature_sessions = list_document_signature_sessions(document_id)
    signature_protocols = list_document_signature_protocols(document_id)
    archive_entries = _load_document_archive_entries(conn, document_id)
    retention_status = _retention_status(doc, retention_policy, archive_entries)
    workflow = compose_document_workflow(conn, document_id)
    retention_actions = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM document_retention_actions WHERE document_id=? ORDER BY created_at DESC, id DESC",
            (int(document_id or 0),),
        ).fetchall()
    ]
    for row in templates:
        row["variables"] = _load_json_list(row.get("variables_json"))
    for row in versions:
        try:
            row["payload"] = json.loads(row.get("payload") or "{}")
        except Exception:
            row["payload"] = {}
    return {
        "document": doc,
        "journal": journal,
        "classifier": classifier,
        "case_file": case_file,
        "registration_records": registration_records,
        "lifecycle_events": lifecycle_events,
        "versions": versions,
        "templates": templates,
        "print_forms": print_forms,
        "file_revisions": file_revisions,
        "active_file_revision": active_file_revision,
        "signatures": signatures,
        "signature_summary": signature_summary,
        "signature_sessions": signature_sessions,
        "signature_validation_protocols": signature_protocols,
        "archive_entries": archive_entries,
        "retention_policy": retention_policy,
        "retention_status": retention_status,
        "retention_actions": retention_actions,
        "workflow": workflow,
        "allowed_roles": _retention_allowed_roles(retention_policy, classifier, case_file),
        "quality": _legal_card_quality(doc, registration_records, classifier, case_file),
        "signature_quality": _document_signature_quality(doc, signatures, archive_entries, active_file_revision),
    }


def _safe_export_filename(value: str, fallback: str = "export") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9А-Яа-я._-]+", "_", _safe_text(value)).strip("._")
    return cleaned or fallback


def _current_document_revision(conn, document_id: int) -> dict:
    return _row_dict(
        conn.execute(
            """
            SELECT *
            FROM document_file_revisions
            WHERE document_id=? AND is_current=1
            ORDER BY revision_no DESC, id DESC
            LIMIT 1
            """,
            (int(document_id or 0),),
        ).fetchone()
    )


def _latest_valid_document_signature(conn, document_id: int, revision: dict | None = None) -> dict:
    revision = revision or {}
    params = [int(document_id or 0)]
    revision_filter = ""
    if int(revision.get("id") or 0):
        revision_filter = " AND document_revision_id=? AND signed_hash=?"
        params.extend([int(revision.get("id") or 0), _safe_text(revision.get("checksum"))])
    return _row_dict(
        conn.execute(
            f"""
            SELECT *
            FROM edo_signature_registry
            WHERE entity_type='document' AND entity_id=? AND verification_status='valid'
              AND COALESCE(revoked_at, 0)=0 {revision_filter}
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
    )


def _document_package_summary(conn, package_id: int) -> dict:
    package = _row_dict(conn.execute("SELECT * FROM document_packages WHERE id=?", (int(package_id or 0),)).fetchone())
    if not package:
        return {}
    package["summary"] = _load_json_dict(package.get("summary_json"))
    items = [
        dict(row)
        for row in conn.execute(
            """
            SELECT *
            FROM document_package_items
            WHERE package_id=?
            ORDER BY order_no ASC, id ASC
            """,
            (int(package_id or 0),),
        ).fetchall()
    ]
    enriched = []
    for item in items:
        item["meta"] = _load_json_dict(item.get("meta_json"))
        entity_type = _safe_text(item.get("entity_type")) or "document"
        entity_id = int(item.get("entity_id") or 0)
        if entity_type == "document":
            document = _row_dict(conn.execute("SELECT * FROM documents WHERE id=?", (entity_id,)).fetchone())
            revision = _current_document_revision(conn, entity_id)
            signature = _latest_valid_document_signature(conn, entity_id, revision)
            item["document"] = document
            item["current_revision"] = revision
            item["latest_valid_signature"] = signature
            item["title"] = _safe_text(item.get("title")) or _safe_text(document.get("number")) or _safe_text(document.get("subject")) or f"Документ #{entity_id}"
            item["checksum"] = _safe_text(item.get("checksum")) or _safe_text(revision.get("checksum"))
            item["file_revision_id"] = int(item.get("file_revision_id") or revision.get("id") or 0)
            item["signature_id"] = int(item.get("signature_id") or signature.get("id") or 0)
        elif entity_type == "email":
            email = _row_dict(conn.execute("SELECT id, subject, sender, sender_email, received_at FROM email_messages WHERE id=?", (entity_id,)).fetchone())
            item["email"] = email
            item["title"] = _safe_text(item.get("title")) or _safe_text(email.get("subject")) or f"Письмо #{entity_id}"
        elif entity_type == "approval":
            approval = _row_dict(conn.execute("SELECT id, title, status, author, created_at FROM approvals WHERE id=?", (entity_id,)).fetchone())
            item["approval"] = approval
            item["title"] = _safe_text(item.get("title")) or _safe_text(approval.get("title")) or f"Согласование #{entity_id}"
        enriched.append(item)
    package["items"] = enriched
    package["relations"] = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM document_relations WHERE package_id=? ORDER BY created_at DESC, id DESC",
            (int(package_id or 0),),
        ).fetchall()
    ]
    return package


def _insert_document_package_item(cursor, package_id: int, item: dict, order_no: int, actor: dict):
    now = int(time.time())
    entity_type = _safe_text(item.get("entity_type")) or "document"
    entity_id = int(item.get("entity_id") or item.get("document_id") or 0)
    if not entity_id:
        return
    cursor.execute(
        """
        INSERT INTO document_package_items (
            package_id, entity_type, entity_id, item_role, order_no, required, item_status,
            title, meta_json, file_revision_id, checksum, signature_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'included', ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(package_id, entity_type, entity_id)
        DO UPDATE SET
            item_role=excluded.item_role,
            order_no=excluded.order_no,
            required=excluded.required,
            title=excluded.title,
            meta_json=excluded.meta_json,
            updated_at=excluded.updated_at
        """,
        (
            int(package_id or 0),
            entity_type,
            entity_id,
            _safe_text(item.get("item_role")) or _safe_text(item.get("role")) or ("document" if entity_type == "document" else entity_type),
            int(item.get("order_no") or order_no or 1),
            int(item.get("required", 1)),
            _safe_text(item.get("title")),
            json.dumps(item.get("meta") or item.get("payload") or {}, ensure_ascii=False),
            int(item.get("file_revision_id") or 0),
            _safe_text(item.get("checksum")),
            int(item.get("signature_id") or 0),
            now,
            now,
        ),
    )
    cursor.execute(
        """
        INSERT INTO document_relations (
            source_entity_type, source_entity_id, target_entity_type, target_entity_id,
            relation_type, package_id, meta_json, created_by, created_at
        ) VALUES ('document_package', ?, ?, ?, 'package_item', ?, ?, ?, ?)
        """,
        (
            int(package_id or 0),
            entity_type,
            entity_id,
            int(package_id or 0),
            json.dumps({"role": _safe_text(item.get("item_role")) or _safe_text(item.get("role"))}, ensure_ascii=False),
            actor.get("email", ""),
            now,
        ),
    )


def _rebuild_package_summary(cursor, package_id: int) -> dict:
    package = _row_dict(cursor.execute("SELECT * FROM document_packages WHERE id=?", (int(package_id or 0),)).fetchone())
    if not package:
        return {}
    items = [
        dict(row)
        for row in cursor.execute(
            "SELECT * FROM document_package_items WHERE package_id=? ORDER BY order_no ASC, id ASC",
            (int(package_id or 0),),
        ).fetchall()
    ]
    documents_total = len([item for item in items if _safe_text(item.get("entity_type")) == "document"])
    missing_files = 0
    signed_total = 0
    for item in items:
        if _safe_text(item.get("entity_type")) != "document":
            continue
        document_id = int(item.get("entity_id") or 0)
        revision = _row_dict(
            cursor.execute(
                "SELECT * FROM document_file_revisions WHERE document_id=? AND is_current=1 ORDER BY revision_no DESC, id DESC LIMIT 1",
                (document_id,),
            ).fetchone()
        )
        if not revision:
            missing_files += 1
            continue
        signature = _row_dict(
            cursor.execute(
                """
                SELECT *
                FROM edo_signature_registry
                WHERE entity_type='document' AND entity_id=? AND verification_status='valid'
                  AND document_revision_id=? AND signed_hash=? AND COALESCE(revoked_at, 0)=0
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (document_id, int(revision.get("id") or 0), _safe_text(revision.get("checksum"))),
            ).fetchone()
        )
        if signature:
            signed_total += 1
    summary = {
        "items_total": len(items),
        "documents_total": documents_total,
        "missing_files": missing_files,
        "signed_documents_total": signed_total,
        "approval_id": int(package.get("approval_id") or 0),
    }
    cursor.execute(
        "UPDATE document_packages SET summary_json=?, updated_at=? WHERE id=?",
        (json.dumps(summary, ensure_ascii=False), int(time.time()), int(package_id or 0)),
    )
    return summary


def _package_manifest(package: dict) -> dict:
    items = []
    gaps = []
    for item in package.get("items") or []:
        entity_type = _safe_text(item.get("entity_type"))
        revision = item.get("current_revision") or {}
        signature = item.get("latest_valid_signature") or {}
        manifest_item = {
            "entity_type": entity_type,
            "entity_id": int(item.get("entity_id") or 0),
            "role": _safe_text(item.get("item_role")),
            "title": _safe_text(item.get("title")),
            "file_revision_id": int(revision.get("id") or item.get("file_revision_id") or 0),
            "checksum": _safe_text(revision.get("checksum")) or _safe_text(item.get("checksum")),
            "signature_id": int(signature.get("id") or item.get("signature_id") or 0),
            "signature_status": _safe_text(signature.get("verification_status")),
        }
        if entity_type == "document":
            if not manifest_item["file_revision_id"]:
                gaps.append({"entity_id": manifest_item["entity_id"], "reason": "file_revision_required"})
            if not manifest_item["signature_id"]:
                gaps.append({"entity_id": manifest_item["entity_id"], "reason": "valid_signature_missing"})
        items.append(manifest_item)
    manifest = {
        "package_id": int(package.get("id") or 0),
        "package_number": _safe_text(package.get("package_number")),
        "title": _safe_text(package.get("title")),
        "status": _safe_text(package.get("status")),
        "generated_at": int(time.time()),
        "items": items,
        "gaps": gaps,
    }
    manifest["checksum"] = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return manifest


def _package_registry_text(package: dict, manifest: dict | None = None) -> str:
    manifest = manifest or _package_manifest(package)
    lines = [
        f"Реестр пакета документов: {package.get('package_number') or package.get('id')}",
        f"Название: {package.get('title') or ''}",
        f"Статус: {package.get('status') or ''}",
        f"Checksum пакета: {manifest.get('checksum') or package.get('package_checksum') or ''}",
        "",
        "Состав:",
    ]
    for idx, item in enumerate(manifest.get("items") or [], 1):
        lines.append(
            f"{idx}. {item.get('entity_type')} #{item.get('entity_id')} · {item.get('role') or ''} · "
            f"{item.get('title') or ''} · rev {item.get('file_revision_id') or '-'} · "
            f"checksum {item.get('checksum') or '-'} · signature {item.get('signature_id') or '-'}"
        )
    if manifest.get("gaps"):
        lines += ["", "Пробелы:"]
        for gap in manifest.get("gaps") or []:
            lines.append(f"- document #{gap.get('entity_id')}: {gap.get('reason')}")
    return "\n".join(lines) + "\n"


def _write_package_registry_file(cursor, package_id: int, package: dict | None = None, manifest: dict | None = None) -> str:
    if not package:
        conn = get_connection(row_factory=True)
        try:
            package = _document_package_summary(conn, package_id)
        finally:
            conn.close()
    manifest = manifest or _package_manifest(package)
    os.makedirs(PACKAGE_EXPORTS_DIR, exist_ok=True)
    filename = f"package_{int(package_id or 0)}_registry_{int(time.time())}.txt"
    path = os.path.join(PACKAGE_EXPORTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as buffer:
        buffer.write(_package_registry_text(package, manifest))
    url = f"/uploads/document_packages/{filename}"
    cursor.execute("UPDATE document_packages SET registry_file_url=?, updated_at=? WHERE id=?", (url, int(time.time()), int(package_id or 0)))
    return path


def _resolve_signing_certificate(cursor, data: DocumentSignatureActionData, actor: dict) -> dict:
    certificate = {}
    if int(data.certificate_id or 0):
        cursor.execute("SELECT * FROM edo_certificates WHERE id=?", (int(data.certificate_id or 0),))
        certificate = _row_dict(cursor.fetchone())
    elif _safe_text(data.certificate_thumbprint):
        cursor.execute("SELECT * FROM edo_certificates WHERE thumbprint=? ORDER BY updated_at DESC, id DESC LIMIT 1", (_safe_text(data.certificate_thumbprint),))
        certificate = _row_dict(cursor.fetchone())
    else:
        cursor.execute("SELECT * FROM edo_certificates WHERE owner_email=? ORDER BY updated_at DESC, id DESC LIMIT 1", (_safe_text(actor.get("email")),))
        certificate = _row_dict(cursor.fetchone())
    return certificate


def _update_signature_verification(cursor, signature: dict, verification_status: str, verification_message: str, verification_details: dict):
    now = int(time.time())
    cursor.execute(
        """
        UPDATE edo_signature_registry
        SET verification_status=?, verification_message=?, verification_details=?, signature_status=?
        WHERE id=?
        """,
        (
            verification_status,
            verification_message,
            json.dumps(verification_details or {}, ensure_ascii=False),
            "verified" if verification_status == "valid" else "invalid",
            int(signature.get("id") or 0),
        ),
    )
    if int(signature.get("certificate_id") or 0):
        cursor.execute(
            "UPDATE edo_certificates SET last_checked_at=?, last_verified_result=?, updated_at=? WHERE id=?",
            (now, verification_status, now, int(signature.get("certificate_id") or 0)),
        )


def _resolution_changed(previous, data: DocUpdate | DocData) -> bool:
    return bool(
        not previous
        or _safe_text(previous["resolution"]) != _safe_text(data.resolution)
        or _safe_text(previous["resolution_deadline"]) != _safe_text(data.resolution_deadline)
        or _safe_text(previous["resolution_assignee"]) != _safe_text(data.resolution_assignee)
    )


def _absence_grace_days() -> int:
    return max(0, int(os.getenv("KORDA_SUBSTITUTE_GRACE_DAYS") or 120))


def _is_absence_effective(abs_start: str = "", abs_end: str = "") -> bool:
    if not _safe_text(abs_start) or not _safe_text(abs_end):
        return False
    try:
        start_date = datetime.datetime.strptime(_safe_text(abs_start), "%d.%m.%Y").date()
        end_date = datetime.datetime.strptime(_safe_text(abs_end), "%d.%m.%Y").date()
    except Exception:
        return False
    today = datetime.date.today()
    return start_date <= today <= end_date + datetime.timedelta(days=_absence_grace_days())


def _resolve_actual_executor(cursor, assignee: str) -> str:
    requested_assignee = _safe_text(assignee)
    if not requested_assignee:
        return ""
    cursor.execute("SELECT abs_start, abs_end, deputy FROM users WHERE name=?", (requested_assignee,))
    user_row = cursor.fetchone()
    if not user_row or not user_row["deputy"] or not user_row["abs_start"] or not user_row["abs_end"]:
        return requested_assignee
    if _is_absence_effective(user_row["abs_start"], user_row["abs_end"]):
        return f"{user_row['deputy']} (И.О. {requested_assignee})"
    return requested_assignee


def _resolution_task_payload(doc_id: int, data: DocUpdate | DocData, actor: dict, executor: str) -> dict:
    subject = _safe_text(data.subject) or "Без темы"
    document_number = _safe_text(data.number) or f"#{doc_id}"
    resolution_text = _safe_text(data.resolution)
    description_lines = [
        f"Документ: №{document_number}",
        f"Тема: {subject}",
        f"Корреспондент: {_safe_text(data.correspondent) or 'Не указан'}",
    ]
    if int(data.project_id or 0):
        description_lines.append(f"Проект ID: {int(data.project_id or 0)}")
    if _safe_text(data.resolution_deadline):
        description_lines.append(f"Срок исполнения: {_safe_text(data.resolution_deadline)}")
    description_lines.append("")
    description_lines.append("Резолюция:")
    description_lines.append(resolution_text)
    return {
        "title": f"Резолюция по документу №{document_number}",
        "description": "\n".join(description_lines).strip(),
        "author": _safe_text(actor.get("name")) or _safe_text(data.resolution_author) or "Система",
        "executor": executor,
        "deadline": _safe_text(data.resolution_deadline),
        "priority": _safe_text(data.priority) or "normal",
        "project_id": int(data.project_id or 0),
        "status": "active",
    }


def _append_resolution_task_history(history: list, actor_name: str, message: str):
    now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    history.append(f"📝 {actor_name} {message} ({now})")


def _resolve_document_master_links(cursor, project_id: int = 0, contract_id: int = 0, object_id: int = 0):
    resolved_project_id = int(project_id or 0)
    resolved_contract_id = int(contract_id or 0)
    resolved_object_id = int(object_id or 0)
    if resolved_project_id:
        cursor.execute("SELECT contract_id, object_id FROM projects WHERE id=?", (resolved_project_id,))
        row = cursor.fetchone()
        if row:
            resolved_contract_id = resolved_contract_id or int(row["contract_id"] or 0)
            resolved_object_id = resolved_object_id or int(row["object_id"] or 0)
    return resolved_project_id, resolved_contract_id, resolved_object_id


def _sync_resolution_task(cursor, doc_id: int, data: DocUpdate | DocData, actor: dict, previous=None):
    resolution_text = _safe_text(data.resolution)
    requested_assignee = _safe_text(data.resolution_assignee)
    previous_task_id = int((previous["resolution_task_id"] if previous else 0) or 0)
    if not resolution_text or not requested_assignee:
        return 0, None

    actual_executor = _resolve_actual_executor(cursor, requested_assignee)
    recipient_name = _safe_text(actual_executor.split(" (И.О.")[0])
    task_payload = _resolution_task_payload(doc_id, data, actor, actual_executor)
    actor_name = _safe_text(actor.get("name")) or "Система"
    task_changed = _resolution_changed(previous, data)

    if previous_task_id:
        cursor.execute("SELECT id, history FROM tasks WHERE id=?", (previous_task_id,))
        existing_task = cursor.fetchone()
        if existing_task:
            history = _load_json_list(existing_task["history"])
            if task_changed:
                _append_resolution_task_history(history, actor_name, f"обновил(а) поручение по документу №{_safe_text(data.number) or doc_id}")
            cursor.execute(
                """
                UPDATE tasks
                SET title=?, description=?, author=?, executor=?, deadline=?, priority=?, project_id=?, history=?
                WHERE id=?
                """,
                (
                    task_payload["title"],
                    task_payload["description"],
                    task_payload["author"],
                    task_payload["executor"],
                    task_payload["deadline"],
                    task_payload["priority"],
                    task_payload["project_id"],
                    json.dumps(history),
                    previous_task_id,
                ),
            )
            return previous_task_id, {"action": "updated" if task_changed else "synced", "recipient_name": recipient_name}

    task_id = _next_local_id(cursor, "tasks")
    cursor.execute(
        """
        INSERT INTO tasks (id, title, description, author, executor, deadline, status, created_at, recurrence, priority, project_id, history)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            task_payload["title"],
            task_payload["description"],
            task_payload["author"],
            task_payload["executor"],
            task_payload["deadline"],
            task_payload["status"],
            time.strftime("%d.%m.%Y %H:%M"),
            "none",
            task_payload["priority"],
            task_payload["project_id"],
            "[]",
        ),
    )
    return task_id, {"action": "created", "recipient_name": recipient_name}

@router.get("/api/documents")
def get_documents(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM documents ORDER BY id DESC")
        rows = [dict(r) for r in c.fetchall()]
        updated = False
        for row in rows:
            relation = c.execute(
                """
                SELECT target_entity_id
                FROM document_relations
                WHERE source_entity_type='document'
                  AND source_entity_id=?
                  AND target_entity_type='production_order'
                  AND relation_type='production_document'
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(row.get("id") or 0),),
            ).fetchone()
            row["production_order_id"] = int((relation or {}).get("target_entity_id") or 0) if isinstance(relation, dict) else int((relation[0] if relation else 0) or 0)
            prev_qr_code = _safe_text(row.get("qr_code"))
            prev_qr_payload = _safe_text(row.get("qr_payload"))
            qr_state = _ensure_document_qr(c, row, request)
            if qr_state.get("qr_code") != prev_qr_code or qr_state.get("qr_payload") != prev_qr_payload:
                updated = True
        if updated:
            conn.commit()
    finally:
        conn.close()
    return rows

@router.post("/api/documents")
async def create_document(data: DocData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "create"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        doc_id = _next_local_id(c, "documents")
        correspondent = _document_correspondent_fallback(data.type, data.sender_name, data.recipient_name, data.correspondent)

        qr_code_path, qr_payload = _write_document_qr_asset(doc_id, request)

        project_id, contract_id, object_id = _resolve_document_master_links(c, data.project_id, data.contract_id, data.object_id)
        resolution_task_id, task_sync = _sync_resolution_task(c, doc_id, data, actor)
        c.execute(
            """
            INSERT INTO documents (
                id, type, document_kind_code, number, d_date, correspondent, sender_name, recipient_name, source_number, source_date,
                delivery_method, signer_name, executor_name, subject, status, file_url, qr_code, qr_payload,
                client_id, client_source, client_source_id, deal_id, project_id, contract_id, object_id, parent_id, priority, resolution, resolution_author, resolution_deadline, resolution_assignee, resolution_task_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                data.type,
                data.document_kind_code,
                data.number,
                data.d_date,
                correspondent,
                data.sender_name,
                data.recipient_name,
                data.source_number,
                data.source_date,
                data.delivery_method,
                data.signer_name,
                data.executor_name,
                data.subject,
                data.status,
                "",
                qr_code_path,
                qr_payload,
                int(data.client_id or 0),
                str(data.client_source or "").strip(),
                int(data.client_source_id or 0),
                int(data.deal_id or 0),
                project_id,
                contract_id,
                object_id,
                data.parent_id,
                data.priority,
                data.resolution,
                data.resolution_author,
                data.resolution_deadline,
                data.resolution_assignee,
                resolution_task_id,
            ),
        )
        # Preserve the creator for auditing and for the mandatory first upload.
        # A role with documents:create may attach its own initial file without
        # receiving permission to edit every document in the company register.
        c.execute("UPDATE documents SET registered_by=? WHERE id=?", (actor.get("email", ""), doc_id))
        _sync_document_production_relation(c, doc_id, data.production_order_id, actor)
        _ensure_lifecycle_event(c, doc_id, "", data.status or "draft", "created", actor, "Документ создан")
        conn.commit()
    finally:
        conn.close()
    audit_log("document_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document", entity_id=str(doc_id), details={"subject": data.subject, "type": data.type})
    if data.resolution and data.resolution_assignee:
        create_targeted_notifications(
            "Новая резолюция по документу",
            f"Документ №{data.number}: {data.subject}",
            user_name=data.resolution_assignee,
            category="document",
            entity_type="document",
            entity_id=str(doc_id),
        )
    if task_sync and task_sync["action"] == "created":
        create_targeted_notifications(
            "Новое поручение по резолюции",
            f"По документу №{data.number} создано поручение: {data.subject}",
            user_name=task_sync["recipient_name"],
            category="task",
            entity_type="task",
            entity_id=str(resolution_task_id),
        )
    await manager.broadcast({"type": "documents"})
    if task_sync:
        await manager.broadcast({"type": "tasks"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "id": doc_id, "resolution_task_id": resolution_task_id}

@router.post("/api/documents/{doc_id}/upload")
async def upload_doc_file(doc_id: int, request: Request, file: UploadFile = File(...), comment: str = Form(""), make_current: int = Form(1)):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM documents WHERE id=?", (doc_id,))
        document = _row_dict(c.fetchone())
        if not document:
            return {"error": "document_not_found"}
        existing_revision = c.execute(
            "SELECT id FROM document_file_revisions WHERE document_id=? LIMIT 1",
            (doc_id,),
        ).fetchone()
        is_initial_creator_upload = (
            not existing_revision
            and not _safe_text(document.get("file_url"))
            and has_permission(actor, "documents", "create")
            and _safe_text(document.get("registered_by")).lower() == _safe_text(actor.get("email")).lower()
        )
        if not has_permission(actor, "documents", "update") and not is_initial_creator_upload:
            return {"error": "forbidden"}
        access_ok, _, _, _, _ = _document_scope_access(conn, actor, doc_id)
        if not access_ok:
            return {"error": "forbidden"}
        file_bytes = await file.read()
        try:
            revision = _create_document_file_revision(c, document, actor, file.filename or "", file.content_type or "", file_bytes, comment, make_current, "upload")
        except ValueError as exc:
            return {"error": "file_validation_failed", "message": str(exc)}
        conn.commit()
    finally:
        conn.close()
    audit_log(
        "document_file_uploaded",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="document",
        entity_id=str(doc_id),
        details={"revision_id": revision["id"], "revision_no": revision["revision_no"], "filename": revision["original_filename"], "file_url": revision["file_url"]},
    )
    await manager.broadcast({"type": "documents"})
    return {"status": "success", "url": revision["file_url"], "revision_id": revision["id"], "revision_no": revision["revision_no"], "active_revision": revision}

@router.put("/api/documents/{doc_id}")
async def update_document(doc_id: int, data: DocUpdate, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        project_id, contract_id, object_id = _resolve_document_master_links(c, data.project_id, data.contract_id, data.object_id)
        c.execute("SELECT * FROM documents WHERE id=?", (doc_id,))
        previous = c.fetchone()
        correspondent = _document_correspondent_fallback(data.type, data.sender_name, data.recipient_name, data.correspondent)
        resolution_task_id, task_sync = _sync_resolution_task(c, doc_id, data, actor, previous)
        c.execute(
            """
            UPDATE documents
            SET type=?, document_kind_code=?, number=?, d_date=?, correspondent=?, sender_name=?, recipient_name=?, source_number=?, source_date=?, delivery_method=?, signer_name=?, executor_name=?, subject=?, status=?, client_id=?, client_source=?, client_source_id=?, deal_id=?, project_id=?, contract_id=?, object_id=?, parent_id=?, priority=?,
                resolution=?, resolution_author=?, resolution_deadline=?, resolution_assignee=?, resolution_task_id=?
            WHERE id=?
            """,
            (
                data.type,
                data.document_kind_code,
                data.number,
                data.d_date,
                correspondent,
                data.sender_name,
                data.recipient_name,
                data.source_number,
                data.source_date,
                data.delivery_method,
                data.signer_name,
                data.executor_name,
                data.subject,
                data.status,
                int(data.client_id or 0),
                str(data.client_source or "").strip(),
                int(data.client_source_id or 0),
                int(data.deal_id or 0),
                project_id,
                contract_id,
                object_id,
                data.parent_id,
                data.priority,
                data.resolution,
                data.resolution_author,
                data.resolution_deadline,
                data.resolution_assignee,
                resolution_task_id,
                doc_id,
            ),
        )
        previous_status = _safe_text(previous["lifecycle_state"] or previous["status"]) if previous else ""
        if previous_status != _safe_text(data.status):
            _ensure_lifecycle_event(c, doc_id, previous_status, data.status, "status_update", actor, "Обновление базовой карточки")
        if resolution_task_id:
            _ensure_document_task_link(
                c,
                {
                    "id": doc_id,
                    "number": data.number,
                    "resolution_assignee": data.resolution_assignee,
                    "resolution_deadline": data.resolution_deadline,
                    "priority": data.priority,
                    "resolution": data.resolution,
                },
                resolution_task_id,
                actor,
            )
        _sync_document_production_relation(c, doc_id, data.production_order_id, actor)
        if previous and int(previous.get("workflow_started_at") or 0):
            sync_document_workflow(conn, int(doc_id or 0), actor, "Обновление документа в workflow", "workflow_document_sync")
        conn.commit()
        should_notify_resolution = bool(
            data.resolution and data.resolution_assignee and (
                not previous
                or previous["resolution"] != data.resolution
                or previous["resolution_deadline"] != data.resolution_deadline
                or previous["resolution_assignee"] != data.resolution_assignee
            )
        )
    finally:
        conn.close()
    audit_log("document_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document", entity_id=str(doc_id), details={"subject": data.subject, "status": data.status, "resolution_deadline": data.resolution_deadline, "resolution_assignee": data.resolution_assignee})
    if previous_status != _safe_text(data.status):
        notify_entity_watchers(
            "document",
            str(doc_id),
            "Документ подписан" if _safe_text(data.status) == "signed" else "Статус документа изменился",
            f"Документ №{data.number or doc_id}: {previous_status or '—'} → {data.status or '—'}",
            event_key="signed" if _safe_text(data.status) == "signed" else "status_changed",
            event_value=_safe_text(data.status),
            actor_email=actor.get("email", ""),
            actor_name=actor.get("name", ""),
            category="document",
        )
    if should_notify_resolution:
        create_targeted_notifications(
            "Новая резолюция по документу",
            f"Документ №{data.number}: {data.subject}",
            user_name=data.resolution_assignee,
            category="document",
            entity_type="document",
            entity_id=str(doc_id),
        )
    if task_sync and should_notify_resolution:
        create_targeted_notifications(
            "Поручение по резолюции обновлено" if task_sync["action"] == "updated" else "Новое поручение по резолюции",
            f"По документу №{data.number} назначено поручение: {data.subject}",
            user_name=task_sync["recipient_name"],
            category="task",
            entity_type="task",
            entity_id=str(resolution_task_id),
        )
    await manager.broadcast({"type": "documents"})
    if task_sync:
        await manager.broadcast({"type": "tasks"})
    if should_notify_resolution or task_sync:
        await manager.broadcast({"type": "notifications"})
    return {"status": "success", "resolution_task_id": resolution_task_id}


@router.post("/api/documents/qr/regenerate")
async def regenerate_document_qr_codes(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        rows = [dict(row) for row in cursor.execute("SELECT * FROM documents ORDER BY id DESC").fetchall()]
        regenerated = []
        for row in rows:
            qr_state = _ensure_document_qr(cursor, row, request, force=True)
            regenerated.append({
                "id": int(row.get("id") or 0),
                "number": row.get("number") or "",
                "qr_code": qr_state.get("qr_code") or "",
                "qr_payload": qr_state.get("qr_payload") or "",
            })
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast({"type": "documents"})
    return {"status": "success", "count": len(regenerated), "items": regenerated}

@router.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "delete"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM document_registration_records WHERE document_id=?", (doc_id,))
        c.execute("DELETE FROM document_lifecycle_events WHERE document_id=?", (doc_id,))
        c.execute("DELETE FROM document_versions WHERE document_id=?", (doc_id,))
        c.execute("DELETE FROM document_content_index WHERE document_id=?", (doc_id,))
        c.execute("DELETE FROM document_file_blobs WHERE document_id=?", (doc_id,))
        c.execute("DELETE FROM document_file_revisions WHERE document_id=?", (doc_id,))
        c.execute("DELETE FROM document_linked_tasks WHERE document_id=?", (doc_id,))
        c.execute("DELETE FROM document_legal_archive WHERE document_id=?", (doc_id,))
        c.execute("DELETE FROM document_print_forms WHERE document_id=?", (doc_id,))
        c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast({"type": "documents"})
    return {"status": "success"}

@router.post("/api/documents/batch_scan")
async def batch_scan_documents(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    processed = []
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        rows = [
            dict(row)
            for row in cursor.execute(
                """
                SELECT * FROM documents
                WHERE COALESCE(qr_code, '') <> ''
                  AND COALESCE(registration_number, '') = ''
                ORDER BY id DESC
                LIMIT 25
                """
            ).fetchall()
        ]
        for row in rows:
            registration_number, journal_id = _register_document(cursor, row, int(row.get("registration_journal_id") or 0), actor, "batch_scan")
            lifecycle_state = _safe_text(row.get("lifecycle_state")) or _safe_text(row.get("status")) or "draft"
            target_state = "registered" if lifecycle_state in {"", "draft", "new"} else lifecycle_state
            cursor.execute(
                """
                UPDATE documents
                SET registration_number=?, registration_journal_id=?, lifecycle_state=?,
                    status=CASE WHEN status IN ('draft', 'new', '') THEN ? ELSE status END,
                    registered_at=CASE WHEN registered_at=0 THEN ? ELSE registered_at END,
                    registered_by=CASE WHEN registered_by='' THEN ? ELSE registered_by END
                WHERE id=?
                """,
                (
                    registration_number,
                    journal_id,
                    target_state,
                    target_state,
                    int(time.time()),
                    actor.get("email", ""),
                    int(row.get("id") or 0),
                ),
            )
            if lifecycle_state != target_state:
                _ensure_lifecycle_event(cursor, int(row.get("id") or 0), lifecycle_state, target_state, "batch_scan_register", actor, "Пакетное распознавание и регистрация")
            processed.append({"document_id": int(row.get("id") or 0), "registration_number": registration_number})
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast({"type": "documents"})
    return {"status": "success", "processed": processed, "count": len(processed), "message": f"Распознано и зарегистрировано документов: {len(processed)}"}


@router.get("/api/docflow/legal_directories")
def get_docflow_legal_directories(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        journals = [dict(row) for row in conn.execute("SELECT * FROM document_registration_journals ORDER BY doc_type ASC, journal_name ASC, id DESC").fetchall()]
        classifiers = [dict(row) for row in conn.execute("SELECT * FROM document_classifiers ORDER BY doc_type ASC, name ASC, id DESC").fetchall()]
        case_files = [dict(row) for row in conn.execute("SELECT * FROM document_case_files ORDER BY status ASC, case_index ASC, id DESC").fetchall()]
        retention_policies = [dict(row) for row in conn.execute("SELECT * FROM document_retention_policies ORDER BY scope_type ASC, scope_value ASC, updated_at DESC").fetchall()]
    finally:
        conn.close()
    for row in classifiers:
        row["required_fields"] = _load_json_list(row.get("required_fields"))
        row["allowed_roles"] = _load_json_list(row.get("allowed_roles_json"))
    for row in case_files:
        row["allowed_roles"] = _load_json_list(row.get("allowed_roles_json"))
    for row in retention_policies:
        row["access_roles"] = _load_json_list(row.get("access_roles_json"))
        row["confidentiality_levels"] = _load_json_list(row.get("confidentiality_levels_json"))
    return {"status": "success", "journals": journals, "classifiers": classifiers, "case_files": case_files, "retention_policies": retention_policies}


@router.get("/api/docflow/crypto/runtime")
def get_docflow_crypto_runtime(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    return crypto_runtime_status()


@router.get("/api/docflow/content_index/runtime")
def get_docflow_content_index_runtime(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    return content_extraction_runtime_status()


@router.post("/api/docflow/registration_journals")
def create_docflow_registration_journal(data: DocumentRegistrationJournalData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    doc_type = _normalize_doc_type(data.doc_type)
    journal_code = _safe_text(data.journal_code) or f"{_doc_type_prefix(doc_type)}-{now}"
    prefix = _safe_text(data.prefix) or _doc_type_prefix(doc_type)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_registration_journals (
                journal_code, journal_name, doc_type, prefix, next_number, numbering_pattern,
                is_active, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                journal_code,
                data.journal_name or f"Журнал {prefix}",
                doc_type,
                prefix,
                data.numbering_pattern or "{prefix}-{year}-{number}",
                int(data.is_active or 0),
                actor.get("email", ""),
                now,
                now,
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("document_registration_journal_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_registration_journal", entity_id=str(record_id), details={"journal_code": journal_code, "doc_type": doc_type})
    return {"status": "success", "id": record_id, "journal_code": journal_code}


@router.post("/api/docflow/classifiers")
def create_docflow_classifier(data: DocumentClassifierData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    classifier_code = _safe_text(data.classifier_code) or f"CLS-{now}"
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_classifiers (
                classifier_code, name, doc_type, category, required_fields, default_lifecycle,
                retention_years, is_active, created_by, created_at, updated_at, allowed_roles_json, retention_policy_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                classifier_code,
                data.name or classifier_code,
                _normalize_doc_type(data.doc_type),
                data.category,
                json.dumps(data.required_fields or [], ensure_ascii=False),
                data.default_lifecycle or "draft",
                max(1, int(data.retention_years or 5)),
                int(data.is_active or 0),
                actor.get("email", ""),
                now,
                now,
                json.dumps(_unique_texts(data.allowed_roles or []), ensure_ascii=False),
                int(data.retention_policy_id or 0),
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("document_classifier_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_classifier", entity_id=str(record_id), details={"classifier_code": classifier_code})
    return {"status": "success", "id": record_id, "classifier_code": classifier_code}


@router.post("/api/docflow/case_files")
def create_docflow_case_file(data: DocumentCaseFileData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    case_index = _safe_text(data.case_index) or f"CASE-{datetime.datetime.now().strftime('%Y')}-{now}"
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_case_files (
                case_index, title, department, retention_years, opened_at, closed_at, status,
                responsible_name, created_by, created_at, updated_at, case_category, allowed_roles_json,
                retention_policy_id, transfer_basis_default, destruction_basis_default
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_index,
                data.title or case_index,
                data.department,
                max(1, int(data.retention_years or 5)),
                data.opened_at or _today_display(),
                data.closed_at,
                data.status or "open",
                data.responsible_name,
                actor.get("email", ""),
                now,
                now,
                data.case_category,
                json.dumps(_unique_texts(data.allowed_roles or []), ensure_ascii=False),
                int(data.retention_policy_id or 0),
                data.transfer_basis_default,
                data.destruction_basis_default,
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("document_case_file_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_case_file", entity_id=str(record_id), details={"case_index": case_index})
    return {"status": "success", "id": record_id, "case_index": case_index}


@router.get("/api/docflow/retention_policies")
def get_docflow_retention_policies(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM document_retention_policies ORDER BY scope_type ASC, scope_value ASC, updated_at DESC").fetchall()]
    finally:
        conn.close()
    for row in rows:
        row["access_roles"] = _load_json_list(row.get("access_roles_json"))
        row["confidentiality_levels"] = _load_json_list(row.get("confidentiality_levels_json"))
    return {"status": "success", "items": rows}


@router.post("/api/docflow/retention_policies")
def create_docflow_retention_policy(data: DocumentRetentionPolicyData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    policy_code = _safe_text(data.policy_code) or f"RET-{now}"
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_retention_policies (
                policy_code, policy_name, scope_type, scope_value, retention_years, review_before_days,
                auto_archive, transfer_basis_default, destruction_basis_default, access_roles_json,
                confidentiality_levels_json, is_active, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy_code,
                data.policy_name or policy_code,
                _safe_text(data.scope_type) or "doc_type",
                _safe_text(data.scope_value),
                max(1, int(data.retention_years or 5)),
                max(0, int(data.review_before_days or 0)),
                int(data.auto_archive or 0),
                data.transfer_basis_default,
                data.destruction_basis_default,
                json.dumps(_unique_texts(data.access_roles or []), ensure_ascii=False),
                json.dumps(_unique_texts(data.confidentiality_levels or []), ensure_ascii=False),
                int(data.is_active or 0),
                data.comment,
                actor.get("email", ""),
                now,
                now,
            ),
        )
        record_id = int(cursor.lastrowid or 0)
        conn.commit()
    finally:
        conn.close()
    audit_log("document_retention_policy_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_retention_policy", entity_id=str(record_id), details={"policy_code": policy_code, "scope_type": data.scope_type, "scope_value": data.scope_value})
    return {"status": "success", "id": record_id, "policy_code": policy_code}


@router.get("/api/docflow/documents/{document_id}/legal_card")
def get_document_legal_card(document_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        card = _load_document_legal_card(conn, document_id, actor)
    finally:
        conn.close()
    if not card:
        return {"error": "document_not_found"}
    if card.get("error"):
        return {"error": card.get("error")}
    return {"status": "success", **card}


@router.get("/api/docflow/documents/{document_id}/signatures")
def get_document_signatures(document_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        card = _load_document_legal_card(conn, document_id, actor)
    finally:
        conn.close()
    if not card:
        return {"error": "document_not_found"}
    if card.get("error"):
        return {"error": card.get("error")}
    return {
        "status": "success",
        "document": card.get("document", {}),
        "signatures": card.get("signatures", []),
        "signature_sessions": card.get("signature_sessions", []),
        "signature_validation_protocols": card.get("signature_validation_protocols", []),
        "signature_summary": card.get("signature_summary", {}),
        "signature_quality": card.get("signature_quality", {}),
        "archive_entries": card.get("archive_entries", []),
        "retention_policy": card.get("retention_policy", {}),
        "retention_status": card.get("retention_status", {}),
    }


@router.get("/api/docflow/packages")
def list_document_packages(request: Request, limit: int = 80):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM document_packages ORDER BY updated_at DESC, id DESC LIMIT ?",
                (max(1, min(int(limit or 80), 200)),),
            ).fetchall()
        ]
        items = []
        for row in rows:
            row["summary"] = _load_json_dict(row.get("summary_json"))
            row["items"] = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM document_package_items WHERE package_id=? ORDER BY order_no ASC, id ASC",
                    (int(row.get("id") or 0),),
                ).fetchall()
            ]
            items.append(row)
    finally:
        conn.close()
    return {"status": "success", "items": items}


@router.get("/api/docflow/packages/{package_id}")
def get_document_package(package_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        package = _document_package_summary(conn, package_id)
    finally:
        conn.close()
    if not package:
        return {"error": "package_not_found"}
    return {"status": "success", "package": package}


@router.post("/api/docflow/packages")
async def create_document_package(data: DocumentPackageData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        raw_items = []
        for document_id in data.document_ids or []:
            raw_items.append({"entity_type": "document", "entity_id": int(document_id or 0), "item_role": "document"})
        for item in data.items or []:
            if isinstance(item, dict):
                raw_items.append(item)
        if not raw_items and any([data.project_id, data.client_id, data.contract_id, data.object_id]):
            clauses = []
            params = []
            for field_name, value in (("project_id", data.project_id), ("contract_id", data.contract_id), ("object_id", data.object_id)):
                if int(value or 0):
                    clauses.append(f"{field_name}=?")
                    params.append(int(value or 0))
            if clauses:
                docs = cursor.execute(
                    f"SELECT id FROM documents WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT 80",
                    tuple(params),
                ).fetchall()
                raw_items = [{"entity_type": "document", "entity_id": int(row["id"] if isinstance(row, dict) else row[0])} for row in docs]
        if not raw_items:
            return {"error": "package_items_required"}
        package_id = _next_local_id(cursor, "document_packages")
        package_number = _safe_text(data.package_number) or f"PACK-{datetime.datetime.now().strftime('%Y%m%d')}-{package_id}"
        title = _safe_text(data.title) or f"Пакет документов {package_number}"
        cursor.execute(
            """
            INSERT INTO document_packages (
                id, package_number, title, package_kind, status, project_id, client_id, contract_id,
                object_id, summary_json, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, '{}', ?, ?, ?, ?)
            """,
            (
                package_id,
                package_number,
                title,
                _safe_text(data.package_kind) or "contract_set",
                int(data.project_id or 0),
                int(data.client_id or 0),
                int(data.contract_id or 0),
                int(data.object_id or 0),
                _safe_text(data.comment),
                actor.get("email", ""),
                now,
                now,
            ),
        )
        order_no = 1
        for item in raw_items:
            _insert_document_package_item(cursor, package_id, item, order_no, actor)
            order_no += 1
        summary = _rebuild_package_summary(cursor, package_id)
        conn.commit()
        package = _document_package_summary(conn, package_id)
    finally:
        conn.close()
    audit_log("document_package_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_package", entity_id=str(package_id), details={"package_number": package_number, "items": summary.get("items_total", 0)})
    await manager.broadcast({"type": "documents"})
    return {"status": "success", "id": package_id, "package": package}


@router.post("/api/docflow/packages/{package_id}/send_approval")
async def send_document_package_to_approval(package_id: int, data: DocumentPackageApprovalData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        package = _row_dict(cursor.execute("SELECT * FROM document_packages WHERE id=?", (int(package_id or 0),)).fetchone())
        if not package:
            return {"error": "package_not_found"}
        if int(package.get("approval_id") or 0):
            approval_id = int(package.get("approval_id") or 0)
            conn.commit()
        else:
            route_rules = data.route_rules or [{"stage_name": "Согласование пакета", "role_name": "Директор", "sla_hours": int(data.default_sla_hours or 24)}]
            approval_id, payload = _create_approval_record(
                cursor,
                ApprovalData(
                    title=f"Пакет документов {package.get('package_number') or package_id}: {package.get('title') or ''}",
                    item_link=f"/docflow/packages/{package_id}",
                    route=[],
                    route_rules=route_rules,
                    route_context={"package_id": int(package_id or 0), "package_kind": package.get("package_kind", "")},
                    author=actor.get("name", ""),
                    entity_type="document_package",
                    entity_id=str(package_id),
                    default_sla_hours=int(data.default_sla_hours or 24),
                ),
                actor,
            )
            if not approval_id:
                return payload
            cursor.execute(
                "UPDATE document_packages SET status='approval_pending', approval_id=?, updated_at=? WHERE id=?",
                (approval_id, int(time.time()), int(package_id or 0)),
            )
            _rebuild_package_summary(cursor, package_id)
            conn.commit()
            _approval_notify_users("Новое согласование пакета", f"Тебе назначено согласование пакета «{package.get('title') or package_id}».", approval_id, payload.get("current_assignees") or [])
    finally:
        conn.close()
    audit_log("document_package_sent_to_approval", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_package", entity_id=str(package_id), details={"approval_id": approval_id, "comment": data.comment})
    await manager.broadcast({"type": "approvals"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "approval_id": approval_id}


@router.post("/api/docflow/packages/{package_id}/sign")
async def sign_document_package(package_id: int, data: DocumentPackageSignData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        package = _document_package_summary(conn, package_id)
        if not package:
            return {"error": "package_not_found"}
        manifest = _package_manifest(package)
        if manifest.get("gaps") and int(data.strict or 0):
            return {"error": "package_signature_gaps", "gaps": manifest.get("gaps")}
        cursor = conn.cursor()
        for item in manifest.get("items") or []:
            cursor.execute(
                """
                UPDATE document_package_items
                SET file_revision_id=?, checksum=?, signature_id=?,
                    item_status=?, updated_at=?
                WHERE package_id=? AND entity_type=? AND entity_id=?
                """,
                (
                    int(item.get("file_revision_id") or 0),
                    _safe_text(item.get("checksum")),
                    int(item.get("signature_id") or 0),
                    "signed" if int(item.get("signature_id") or 0) else "signature_gap",
                    int(time.time()),
                    int(package_id or 0),
                    _safe_text(item.get("entity_type")),
                    int(item.get("entity_id") or 0),
                ),
            )
        summary = _load_json_dict(package.get("summary_json"))
        summary["signed_manifest"] = manifest
        summary["signed_by"] = _safe_text(data.signer_name) or actor.get("name", "")
        summary["signed_comment"] = _safe_text(data.comment)
        status = "signed" if not manifest.get("gaps") else "signed_with_gaps"
        registry_path = _write_package_registry_file(cursor, package_id, package, manifest)
        cursor.execute(
            """
            UPDATE document_packages
            SET status=?, package_checksum=?, signed_by=?, signed_at=?, summary_json=?, updated_at=?
            WHERE id=?
            """,
            (
                status,
                manifest.get("checksum", ""),
                _safe_text(data.signer_name) or actor.get("name", ""),
                int(time.time()),
                json.dumps(summary, ensure_ascii=False),
                int(time.time()),
                int(package_id or 0),
            ),
        )
        conn.commit()
        package = _document_package_summary(conn, package_id)
    finally:
        conn.close()
    audit_log("document_package_signed", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_package", entity_id=str(package_id), details={"status": status, "checksum": manifest.get("checksum"), "gaps": manifest.get("gaps"), "registry_path": registry_path})
    await manager.broadcast({"type": "documents"})
    return {"status": "success", "package": package, "manifest": manifest}


@router.get("/api/docflow/packages/{package_id}/export_registry")
def export_document_package_registry(package_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        package = _document_package_summary(conn, package_id)
        if not package:
            return {"error": "package_not_found"}
        cursor = conn.cursor()
        manifest = _package_manifest(package)
        path = _write_package_registry_file(cursor, package_id, package, manifest)
        conn.commit()
    finally:
        conn.close()
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=os.path.basename(path))


@router.get("/api/docflow/packages/{package_id}/export_zip")
def export_document_package_zip(package_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        package = _document_package_summary(conn, package_id)
        if not package:
            return {"error": "package_not_found"}
        manifest = _package_manifest(package)
        os.makedirs(PACKAGE_EXPORTS_DIR, exist_ok=True)
        base_name = _safe_export_filename(package.get("package_number") or f"package_{package_id}", f"package_{package_id}")
        filename = f"{base_name}_{int(time.time())}.zip"
        path = os.path.join(PACKAGE_EXPORTS_DIR, filename)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("registry.txt", _package_registry_text(package, manifest))
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for idx, item in enumerate(package.get("items") or [], 1):
                if _safe_text(item.get("entity_type")) != "document":
                    continue
                revision = item.get("current_revision") or {}
                stored = _safe_text(revision.get("stored_filename"))
                if not stored:
                    continue
                disk_path = os.path.join(UPLOADS_DIR, stored)
                if not os.path.exists(disk_path):
                    continue
                archive_name = f"files/{idx:03d}_{_safe_export_filename(revision.get('original_filename') or stored, stored)}"
                archive.write(disk_path, archive_name)
        export_url = f"/uploads/document_packages/{filename}"
        conn.execute("UPDATE document_packages SET export_file_url=?, updated_at=? WHERE id=?", (export_url, int(time.time()), int(package_id or 0)))
        conn.commit()
    finally:
        conn.close()
    return FileResponse(path, media_type="application/zip", filename=filename)


@router.post("/api/docflow/documents/{document_id}/signature_sessions")
def start_document_signature_session(document_id: int, data: CryptoSignatureSessionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
    result = begin_signature_session(document_id, payload, actor)
    if result.get("error"):
        return result
    audit_log(
        "document_signature_session_started",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="document",
        entity_id=str(document_id),
        details={"session_id": result.get("session_id"), "file_revision_id": data.file_revision_id, "signature_format": data.signature_format},
    )
    return result


@router.post("/api/docflow/signature_sessions/{session_id}/detached")
async def upload_document_detached_signature(session_id: int, request: Request, file: UploadFile = File(...), comment: str = Form("")):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    signature_bytes = await file.read()
    result = attach_detached_signature(session_id, file.filename or "detached.sig", signature_bytes, actor, comment)
    if result.get("error"):
        return result
    audit_log(
        "document_detached_signature_uploaded",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="signature_session",
        entity_id=str(session_id),
        details={"filename": file.filename, "size": len(signature_bytes or b"")},
    )
    return result


@router.post("/api/docflow/signature_sessions/{session_id}/verify")
async def verify_document_signature_session(session_id: int, data: DocumentSignatureVerifyData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    result = verify_signature_session(session_id, actor, force=int(data.force or 0))
    if result.get("error"):
        return result
    session = result.get("session") or {}
    document_id = int(session.get("document_id") or 0)
    audit_log(
        "document_detached_signature_verified",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="document",
        entity_id=str(document_id),
        details={"session_id": session_id, "signature_id": result.get("signature_id"), "protocol_id": result.get("protocol_id"), "status": (result.get("verification") or {}).get("status"), "comment": data.comment},
    )
    if (result.get("verification") or {}).get("status") == "valid" and document_id:
        notify_entity_watchers(
            "document",
            str(document_id),
            "Документ подписан",
            "Detached ЭП проверена и привязана к версии файла.",
            event_key="signed",
            event_value="detached_valid",
            actor_email=actor.get("email", ""),
            actor_name=actor.get("name", ""),
            category="document",
        )
        await manager.broadcast({"type": "documents"})
        await manager.broadcast({"type": "notifications"})
    return result


@router.post("/api/docflow/signature_sessions/{session_id}/protocols")
def attach_document_signature_protocol(session_id: int, data: CryptoSignatureProtocolData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
    result = attach_validation_protocol(session_id, payload, actor)
    if result.get("error"):
        return result
    audit_log(
        "document_signature_protocol_attached",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="signature_session",
        entity_id=str(session_id),
        details={"protocol_id": result.get("protocol_id"), "protocol_number": data.protocol_number, "validation_result": data.validation_result},
    )
    return result


@router.post("/api/docflow/documents/{document_id}/signatures")
async def sign_document(document_id: int, data: DocumentSignatureActionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    archive_id = 0
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id=?", (int(document_id or 0),))
        document = _row_dict(cursor.fetchone())
        if not document:
            return {"error": "document_not_found"}
        classifier = _row_dict(cursor.execute("SELECT * FROM document_classifiers WHERE id=?", (int(document.get("classifier_id") or 0),)).fetchone())
        case_file = _row_dict(cursor.execute("SELECT * FROM document_case_files WHERE id=?", (int(document.get("case_file_id") or 0),)).fetchone())
        retention_policy = _find_retention_policy(conn, document, classifier, case_file)
        if not _can_access_case_scope(actor, document, classifier, case_file, retention_policy):
            return {"error": "forbidden"}
        _, active_revision = _load_document_file_revisions(conn, document_id)
        if not active_revision:
            return {"error": "document_file_revision_required"}
        certificate = _resolve_signing_certificate(cursor, data, actor)
        if not certificate:
            return {"error": "certificate_not_found"}
        if not _certificate_owned_by_actor(certificate, actor, data.signer_name):
            return {"error": "certificate_owner_mismatch"}
        certificate_status, certificate_message = _certificate_status_snapshot(certificate)
        if certificate_status != "valid":
            return {"error": certificate_status, "message": certificate_message}
        signed_at = _safe_text(data.signed_at) or datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        signer_name = _safe_text(data.signer_name) or _safe_text(certificate.get("owner_name")) or actor.get("name", "")
        signer_role = _safe_text(data.signer_role) or _safe_text(certificate.get("signer_role")) or actor.get("role", "")
        signature_kind = _safe_text(data.signature_kind) or "КЭП"
        legal_force = _signature_legal_force(signature_kind)
        stamp = _build_signature_stamp(document, active_revision, certificate, signer_name, signer_role, signed_at, signature_kind, data.signature_provider)
        verification_status, verification_message, verification_details = _verify_document_signature(
            {
                "signature_status": data.comment and "signed" or "signed",
                "signed_hash": active_revision.get("checksum"),
                "signature_kind": signature_kind,
            },
            certificate,
            active_revision,
        )
        cursor.execute(
            """
            INSERT INTO edo_signature_registry (
                entity_type, entity_id, signer_name, signer_role, certificate_thumbprint, signature_provider,
                signature_status, signed_at, comment, created_by, created_at, certificate_id, document_revision_id,
                signature_kind, verification_status, verification_message, stamp_json, signed_hash, verification_details,
                revoked_at, legal_force
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                "document",
                int(document_id or 0),
                signer_name,
                signer_role,
                _safe_text(certificate.get("thumbprint")),
                _safe_text(data.signature_provider) or "1С-ЭДО",
                "verified" if verification_status == "valid" else "invalid",
                signed_at,
                _safe_text(data.comment),
                actor.get("email", ""),
                int(time.time()),
                int(certificate.get("id") or 0),
                int(active_revision.get("id") or 0),
                signature_kind,
                verification_status,
                verification_message,
                json.dumps(stamp, ensure_ascii=False),
                _safe_text(active_revision.get("checksum")),
                json.dumps(verification_details, ensure_ascii=False),
                legal_force,
            ),
        )
        signature_id = int(cursor.lastrowid or 0)
        current_state = _safe_text(document.get("lifecycle_state")) or _safe_text(document.get("status")) or "draft"
        target_legal_significance = "qualified_signature" if legal_force == "qualified" else "signed"
        cursor.execute(
            "UPDATE documents SET lifecycle_state='signed', status='signed', legal_significance=? WHERE id=?",
            (target_legal_significance, int(document_id or 0)),
        )
        _ensure_lifecycle_event(cursor, int(document_id or 0), current_state, "signed", "document_signed", actor, data.comment)
        if int(data.force_archive or 0):
            archive_action = DocumentLegalArchiveActionData(
                comment=data.comment,
                policy_id=int(retention_policy.get("id") or 0),
                access_roles=_retention_allowed_roles(retention_policy, classifier, case_file),
                transfer_basis=_safe_text(case_file.get("transfer_basis_default")) or _safe_text(retention_policy.get("transfer_basis_default")),
                destruction_basis=_safe_text(case_file.get("destruction_basis_default")) or _safe_text(retention_policy.get("destruction_basis_default")),
                review_due_at=_retention_review_due(_safe_text(document.get("retention_until")), int(retention_policy.get("review_before_days") or 90)),
            )
            archive_info = _archive_document_snapshot(
                cursor,
                dict(document, lifecycle_state="signed", status="signed", legal_significance=target_legal_significance),
                {
                    "id": signature_id,
                    "certificate_id": certificate.get("id", 0),
                    "certificate_thumbprint": certificate.get("thumbprint", ""),
                    "verification_status": verification_status,
                    "signature_kind": signature_kind,
                    "signer_name": signer_name,
                    "signed_at": signed_at,
                },
                active_revision,
                actor,
                archive_action,
            )
            archive_id = int(archive_info.get("id") or 0)
            _log_retention_action(cursor, int(document_id or 0), archive_id, "archive", "", "archived", data.comment, actor, {"source": "sign_document"}, retention_until=_safe_text(document.get("retention_until")), review_due_at=archive_action.review_due_at)
            cursor.execute("UPDATE documents SET lifecycle_state='archived', status='archived' WHERE id=?", (int(document_id or 0),))
            _ensure_lifecycle_event(cursor, int(document_id or 0), "signed", "archived", "legal_archive_created", actor, data.comment)
        conn.commit()
        card = _load_document_legal_card(conn, document_id, actor)
    finally:
        conn.close()
    audit_log(
        "document_signed",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="document",
        entity_id=str(document_id),
        details={"certificate_id": data.certificate_id, "signature_kind": data.signature_kind, "archive_id": archive_id},
    )
    notify_entity_watchers(
        "document",
        str(document_id),
        "Документ подписан",
        f"Документ №{document.get('number') or document_id} подписан: {document.get('subject') or ''}",
        event_key="signed",
        event_value="signed",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        category="document",
    )
    await manager.broadcast({"type": "documents"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "signature_id": signature_id, "archive_id": archive_id, **card}


@router.post("/api/docflow/documents/{document_id}/verify_signatures")
def verify_document_signatures(document_id: int, data: DocumentSignatureVerifyData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    processed = []
    valid_total = 0
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id=?", (int(document_id or 0),))
        document = _row_dict(cursor.fetchone())
        if not document:
            return {"error": "document_not_found"}
        signatures = [
            dict(row)
            for row in cursor.execute(
                "SELECT * FROM edo_signature_registry WHERE entity_type='document' AND entity_id=? ORDER BY created_at DESC, id DESC",
                (int(document_id or 0),),
            ).fetchall()
        ]
        if not signatures:
            return {"error": "signatures_not_found"}
        for signature in signatures:
            certificate = {}
            if int(signature.get("certificate_id") or 0):
                cursor.execute("SELECT * FROM edo_certificates WHERE id=?", (int(signature.get("certificate_id") or 0),))
                certificate = _row_dict(cursor.fetchone())
            if not certificate and _safe_text(signature.get("certificate_thumbprint")):
                cursor.execute("SELECT * FROM edo_certificates WHERE thumbprint=? ORDER BY updated_at DESC, id DESC LIMIT 1", (_safe_text(signature.get("certificate_thumbprint")),))
                certificate = _row_dict(cursor.fetchone())
            revision = {}
            if int(signature.get("document_revision_id") or 0):
                cursor.execute("SELECT * FROM document_file_revisions WHERE id=?", (int(signature.get("document_revision_id") or 0),))
                revision = _row_dict(cursor.fetchone())
            verification_status, verification_message, verification_details = _verify_document_signature(signature, certificate, revision)
            _update_signature_verification(cursor, signature, verification_status, verification_message, verification_details)
            if verification_status == "valid":
                valid_total += 1
            processed.append({"signature_id": int(signature.get("id") or 0), "status": verification_status, "message": verification_message})
        if valid_total:
            current_significance = "qualified_signature" if any(_safe_text(item.get("legal_force")) == "qualified" for item in signatures) else "signed"
            cursor.execute("UPDATE documents SET legal_significance=? WHERE id=?", (current_significance, int(document_id or 0)))
        conn.commit()
        card = _load_document_legal_card(conn, document_id, actor)
    finally:
        conn.close()
    audit_log(
        "document_signatures_verified",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="document",
        entity_id=str(document_id),
        details={"processed": processed, "comment": data.comment},
    )
    return {"status": "success", "processed": processed, "valid_total": valid_total, **card}


@router.post("/api/docflow/documents/{document_id}/archive_legal")
def archive_document_legal(document_id: int, data: DocumentLegalArchiveActionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id=?", (int(document_id or 0),))
        document = _row_dict(cursor.fetchone())
        if not document:
            return {"error": "document_not_found"}
        classifier = _row_dict(cursor.execute("SELECT * FROM document_classifiers WHERE id=?", (int(document.get("classifier_id") or 0),)).fetchone())
        case_file = _row_dict(cursor.execute("SELECT * FROM document_case_files WHERE id=?", (int(document.get("case_file_id") or 0),)).fetchone())
        retention_policy = _find_retention_policy(conn, document, classifier, case_file)
        if not _can_access_case_scope(actor, document, classifier, case_file, retention_policy):
            return {"error": "forbidden"}
        if int(document.get("workflow_started_at") or 0):
            workflow = sync_document_workflow(conn, int(document_id or 0), actor, data.comment, "workflow_archive_guard")
            if workflow and not workflow.get("can_archive"):
                return {"error": "workflow_incomplete", "workflow": workflow}
        signatures, _ = _load_document_signatures(conn, document_id)
        signature = next((row for row in signatures if _safe_text(row.get("verification_status")) == "valid"), {})
        if not signature:
            return {"error": "verified_signature_required"}
        revision = signature.get("revision") or {}
        if not revision:
            _, revision = _load_document_file_revisions(conn, document_id)
        if not revision:
            return {"error": "document_file_revision_required"}
        archive_action = DocumentLegalArchiveActionData(
            archive_code=data.archive_code,
            storage_path=data.storage_path,
            retention_until=data.retention_until,
            archive_status=data.archive_status,
            comment=data.comment,
            policy_id=int(data.policy_id or retention_policy.get("id") or 0),
            access_roles=data.access_roles or _retention_allowed_roles(retention_policy, classifier, case_file),
            transfer_basis=data.transfer_basis or _safe_text(case_file.get("transfer_basis_default")) or _safe_text(retention_policy.get("transfer_basis_default")),
            destruction_basis=data.destruction_basis or _safe_text(case_file.get("destruction_basis_default")) or _safe_text(retention_policy.get("destruction_basis_default")),
            review_due_at=data.review_due_at or _retention_review_due(_safe_text(data.retention_until) or _safe_text(document.get("retention_until")), int(retention_policy.get("review_before_days") or 90)),
        )
        archive_info = _archive_document_snapshot(cursor, document, signature, revision, actor, archive_action)
        current_state = _safe_text(document.get("lifecycle_state")) or _safe_text(document.get("status")) or "signed"
        cursor.execute("UPDATE documents SET lifecycle_state='archived', status='archived' WHERE id=?", (int(document_id or 0),))
        _ensure_lifecycle_event(cursor, int(document_id or 0), current_state, "archived", "legal_archive_created", actor, data.comment)
        _log_retention_action(cursor, int(document_id or 0), int(archive_info.get("id") or 0), "archive", "", archive_action.archive_status or "archived", data.comment, actor, {"policy_id": archive_action.policy_id}, storage_path=archive_action.storage_path, retention_until=archive_action.retention_until or _safe_text(document.get("retention_until")), review_due_at=archive_action.review_due_at)
        sync_document_workflow(conn, int(document_id or 0), actor, data.comment, "workflow_archived")
        conn.commit()
        card = _load_document_legal_card(conn, document_id, actor)
    finally:
        conn.close()
    audit_log(
        "document_legal_archived",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="document",
        entity_id=str(document_id),
        details={"archive_id": archive_info.get("id", 0), "archive_code": archive_info.get("archive_code", "")},
    )
    return {"status": "success", "archive_id": archive_info.get("id", 0), "archive_code": archive_info.get("archive_code", ""), **card}


@router.post("/api/docflow/documents/{document_id}/retention_disposition")
def apply_document_retention_disposition(document_id: int, data: DocumentRetentionDispositionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id=?", (int(document_id or 0),))
        document = _row_dict(cursor.fetchone())
        if not document:
            return {"error": "document_not_found"}
        classifier = _row_dict(cursor.execute("SELECT * FROM document_classifiers WHERE id=?", (int(document.get("classifier_id") or 0),)).fetchone())
        case_file = _row_dict(cursor.execute("SELECT * FROM document_case_files WHERE id=?", (int(document.get("case_file_id") or 0),)).fetchone())
        retention_policy = _find_retention_policy(conn, document, classifier, case_file)
        if not _can_access_case_scope(actor, document, classifier, case_file, retention_policy):
            return {"error": "forbidden"}
        archive_entries = _load_document_archive_entries(conn, document_id)
        archive_row = {}
        if int(data.archive_id or 0):
            archive_row = next((row for row in archive_entries if int(row.get("id") or 0) == int(data.archive_id or 0)), {})
        if not archive_row and archive_entries:
            archive_row = archive_entries[0]
        if not archive_row:
            return {"error": "archive_entry_not_found"}
        current_status = _safe_text(archive_row.get("archive_status")) or "archived"
        action_name = _safe_text(data.action_name) or "review"
        target_status = _safe_text(data.archive_status)
        basis_text = _safe_text(data.basis_text) or _safe_text(data.comment)
        if not target_status:
            target_status = {
                "review": current_status,
                "transfer": "transferred",
                "move": "moved",
                "destroy": "destroyed",
                "extend": current_status,
            }.get(action_name, current_status)
        review_due_at = _safe_text(data.review_due_at) or _safe_text(archive_row.get("review_due_at")) or _retention_review_due(_safe_text(data.retention_until) or _safe_text(archive_row.get("retention_until")) or _safe_text(document.get("retention_until")), int(retention_policy.get("review_before_days") or 90))
        retention_until = _safe_text(data.retention_until) or _safe_text(archive_row.get("retention_until")) or _safe_text(document.get("retention_until"))
        storage_path = _safe_text(data.storage_path) or _safe_text(archive_row.get("storage_path"))
        transfer_basis = _safe_text(archive_row.get("transfer_basis"))
        destruction_basis = _safe_text(archive_row.get("destruction_basis"))
        if not basis_text and action_name in {"transfer", "move"}:
            basis_text = transfer_basis or _safe_text(case_file.get("transfer_basis_default")) or _safe_text(retention_policy.get("transfer_basis_default"))
        if not basis_text and action_name == "destroy":
            basis_text = destruction_basis or _safe_text(case_file.get("destruction_basis_default")) or _safe_text(retention_policy.get("destruction_basis_default"))
        if action_name in {"transfer", "move"} and basis_text:
            transfer_basis = basis_text
        if action_name == "destroy" and basis_text:
            destruction_basis = basis_text
        cursor.execute(
            """
            UPDATE document_legal_archive
            SET archive_status=?, storage_path=?, retention_until=?, review_due_at=?, transfer_basis=?, destruction_basis=?, updated_at=?
            WHERE id=?
            """,
            (
                target_status,
                storage_path,
                retention_until,
                review_due_at,
                transfer_basis,
                destruction_basis,
                int(time.time()),
                int(archive_row.get("id") or 0),
            ),
        )
        if retention_until:
            cursor.execute("UPDATE documents SET retention_until=? WHERE id=?", (retention_until, int(document_id or 0)))
        if target_status in {"destroyed", "written_off"}:
            cursor.execute("UPDATE documents SET lifecycle_state='archived', status='archived' WHERE id=?", (int(document_id or 0),))
        _log_retention_action(cursor, int(document_id or 0), int(archive_row.get("id") or 0), action_name, current_status, target_status, basis_text, actor, {"comment": data.comment}, storage_path=storage_path, retention_until=retention_until, review_due_at=review_due_at)
        conn.commit()
        card = _load_document_legal_card(conn, document_id, actor)
    finally:
        conn.close()
    audit_log("document_retention_disposition_applied", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document", entity_id=str(document_id), details={"action_name": data.action_name, "archive_status": target_status, "basis_text": basis_text})
    return {"status": "success", **card}


@router.get("/api/docflow/documents/{document_id}/file_versions")
def get_document_file_versions(document_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        access_ok, scoped_document, _, _, _ = _document_scope_access(conn, actor, document_id)
        if not scoped_document:
            return {"error": "document_not_found"}
        if not access_ok:
            return {"error": "forbidden"}
        document = _row_dict(conn.execute("SELECT id, number, subject, file_url FROM documents WHERE id=?", (int(document_id or 0),)).fetchone())
        revisions, active_revision = _load_document_file_revisions(conn, document_id)
    finally:
        conn.close()
    return {"status": "success", "document": document, "active_revision": active_revision, "revisions": revisions}


@router.get("/api/docflow/file_versions/{record_id}/diff")
def get_document_file_version_diff(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        current = _row_dict(conn.execute("SELECT * FROM document_file_revisions WHERE id=?", (int(record_id or 0),)).fetchone())
        if not current:
            return {"error": "file_revision_not_found"}
        access_ok, scoped_document, _, _, _ = _document_scope_access(conn, actor, int(current.get("document_id") or 0))
        if not scoped_document:
            return {"error": "document_not_found"}
        if not access_ok:
            return {"error": "forbidden"}
        previous = _row_dict(
            conn.execute(
                """
                SELECT *
                FROM document_file_revisions
                WHERE document_id=? AND revision_no < ?
                ORDER BY revision_no DESC, id DESC
                LIMIT 1
                """,
                (int(current.get("document_id") or 0), int(current.get("revision_no") or 0)),
            ).fetchone()
        )
    finally:
        conn.close()
    diff_items = _file_revision_diff(current, previous)
    current["size_label"] = _format_file_size(current.get("file_size"))
    if previous:
        previous["size_label"] = _format_file_size(previous.get("file_size"))
    return {
        "status": "success",
        "document_id": int(current.get("document_id") or 0),
        "revision_id": int(current.get("id") or 0),
        "revision_label": current.get("revision_label") or f"file-v{int(current.get('revision_no') or 0)}",
        "previous_revision_id": int(previous.get("id") or 0),
        "current_revision": current,
        "previous_revision": previous,
        "diff_items": diff_items,
        "change_count": len(diff_items),
    }


@router.post("/api/docflow/file_versions/{record_id}/activate")
def activate_document_file_version(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        current = _row_dict(cursor.execute("SELECT * FROM document_file_revisions WHERE id=?", (int(record_id or 0),)).fetchone())
        if not current:
            return {"error": "file_revision_not_found"}
        document_id = int(current.get("document_id") or 0)
        if not document_id:
            return {"error": "document_not_found"}
        access_ok, scoped_document, _, _, _ = _document_scope_access(conn, actor, document_id)
        if not scoped_document:
            return {"error": "document_not_found"}
        if not access_ok:
            return {"error": "forbidden"}
        now = int(time.time())
        cursor.execute(
            """
            UPDATE document_file_revisions
            SET is_current=0,
                revision_status=CASE WHEN revision_status='active' THEN 'archived' ELSE revision_status END,
                archived_at=CASE WHEN archived_at=0 THEN ? ELSE archived_at END
            WHERE document_id=? AND is_current=1 AND id<>?
            """,
            (now, document_id, int(record_id or 0)),
        )
        cursor.execute("UPDATE document_file_revisions SET is_current=1, revision_status='active', archived_at=0 WHERE id=?", (int(record_id or 0),))
        cursor.execute("UPDATE documents SET file_url=? WHERE id=?", (current.get("file_url", ""), document_id))
        conn.commit()
        revisions, active_revision = _load_document_file_revisions(conn, document_id)
    finally:
        conn.close()
    audit_log(
        "document_file_revision_activated",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="document",
        entity_id=str(document_id),
        details={"revision_id": int(record_id or 0), "revision_no": int(current.get("revision_no") or 0), "filename": current.get("original_filename", "")},
    )
    return {"status": "success", "document_id": document_id, "active_revision": active_revision, "revisions": revisions}


@router.post("/api/docflow/documents/{document_id}/legal_card")
def update_document_legal_card(document_id: int, data: DocumentLegalCardData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id=?", (int(document_id or 0),))
        document = _row_dict(cursor.fetchone())
        if not document:
            return {"error": "document_not_found"}
        classifier = {}
        case_file = {}
        classifier_id = int(data.classifier_id or document.get("classifier_id") or 0)
        case_file_id = int(data.case_file_id or document.get("case_file_id") or 0)
        if classifier_id:
            cursor.execute("SELECT * FROM document_classifiers WHERE id=? AND is_active=1", (classifier_id,))
            classifier = _row_dict(cursor.fetchone())
            if not classifier:
                return {"error": "classifier_not_found"}
        if case_file_id:
            cursor.execute("SELECT * FROM document_case_files WHERE id=?", (case_file_id,))
            case_file = _row_dict(cursor.fetchone())
            if not case_file:
                return {"error": "case_file_not_found"}
        retention_policy = _find_retention_policy(conn, dict(document, document_kind_code=data.document_kind_code or document.get("document_kind_code", "")), classifier, case_file)
        if not _can_access_case_scope(actor, document, classifier, case_file, retention_policy):
            return {"error": "forbidden"}
        registration_number = _safe_text(document.get("registration_number"))
        journal_id = int(data.journal_id or document.get("registration_journal_id") or 0)
        if int(data.auto_register or 0) and not registration_number:
            registration_number, journal_id = _register_document(cursor, document, journal_id, actor, data.comment)
        retention_years = int((case_file or {}).get("retention_years") or (classifier or {}).get("retention_years") or (retention_policy or {}).get("retention_years") or 5)
        retention_until = _safe_text(data.retention_until) or _safe_text(document.get("retention_until")) or _add_years_display(document.get("d_date", ""), retention_years)
        lifecycle_state = _safe_text(document.get("lifecycle_state")) or _safe_text((classifier or {}).get("default_lifecycle")) or "draft"
        if classifier and _safe_text(document.get("lifecycle_state")) in {"", "draft"}:
            lifecycle_state = _safe_text(classifier.get("default_lifecycle")) or lifecycle_state
        now = int(time.time())
        cursor.execute(
            """
            UPDATE documents
            SET registration_number=?, registration_journal_id=?, classifier_id=?, case_file_id=?,
                lifecycle_state=?, legal_significance=?, confidentiality_level=?, retention_until=?,
                registered_at=CASE WHEN registered_at=0 THEN ? ELSE registered_at END,
                registered_by=CASE WHEN registered_by='' THEN ? ELSE registered_by END,
                document_kind_code=?, case_index=?
            WHERE id=?
            """,
            (
                registration_number,
                journal_id,
                classifier_id,
                case_file_id,
                lifecycle_state,
                data.legal_significance or document.get("legal_significance") or "standard",
                data.confidentiality_level or document.get("confidentiality_level") or "internal",
                retention_until,
                now if registration_number else 0,
                actor.get("email", "") if registration_number else "",
                data.document_kind_code or document.get("document_kind_code") or (classifier or {}).get("classifier_code", ""),
                (case_file or {}).get("case_index", document.get("case_index", "")),
                int(document_id or 0),
            ),
        )
        _ensure_lifecycle_event(cursor, int(document_id or 0), document.get("lifecycle_state", ""), lifecycle_state, "legal_card_updated", actor, data.comment)
        sync_document_workflow(conn, int(document_id or 0), actor, data.comment, "workflow_legal_card_sync")
        conn.commit()
        card = _load_document_legal_card(conn, document_id, actor)
    finally:
        conn.close()
    audit_log("document_legal_card_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document", entity_id=str(document_id), details={"registration_number": registration_number, "classifier_id": data.classifier_id, "case_file_id": data.case_file_id})
    return {"status": "success", **card}


@router.post("/api/docflow/documents/{document_id}/lifecycle")
def advance_document_lifecycle(document_id: int, data: DocumentLifecycleActionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    target_state = _safe_text(data.target_state) or _safe_text(data.action_name)
    allowed_states = {"draft", "registered", "review", "approved", "signed", "archived", "cancelled", "rejected"}
    if target_state not in allowed_states:
        return {"error": "invalid_lifecycle_state", "allowed": sorted(allowed_states)}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id=?", (int(document_id or 0),))
        document = _row_dict(cursor.fetchone())
        if not document:
            return {"error": "document_not_found"}
        if target_state == "archived" and int(document.get("workflow_started_at") or 0):
            workflow = sync_document_workflow(conn, int(document_id or 0), actor, data.comment, "workflow_archive_guard")
            if workflow and not workflow.get("can_archive"):
                return {"error": "workflow_incomplete", "workflow": workflow}
        from_state = _safe_text(document.get("lifecycle_state")) or _safe_text(document.get("status")) or "draft"
        cursor.execute("UPDATE documents SET lifecycle_state=?, status=? WHERE id=?", (target_state, target_state, int(document_id or 0)))
        _ensure_lifecycle_event(cursor, int(document_id or 0), from_state, target_state, data.action_name or "advance", actor, data.comment)
        sync_document_workflow(conn, int(document_id or 0), actor, data.comment, "workflow_lifecycle_sync")
        conn.commit()
        card = _load_document_legal_card(conn, document_id, actor)
    finally:
        conn.close()
    audit_log("document_lifecycle_advanced", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document", entity_id=str(document_id), details={"from_state": from_state, "to_state": target_state, "action": data.action_name})
    notify_entity_watchers(
        "document",
        str(document_id),
        "Документ подписан" if target_state == "signed" else "Статус документа изменился",
        f"Документ №{document.get('number') or document_id}: {from_state or '—'} → {target_state or '—'}",
        event_key="signed" if target_state == "signed" else "status_changed",
        event_value=target_state,
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        category="document",
    )
    return {"status": "success", **card}


@router.get("/api/docflow/documents/{document_id}/workflow")
def get_document_workflow(document_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        card = _load_document_legal_card(conn, document_id, actor)
        if card.get("error"):
            return card
        workflow = compose_document_workflow(conn, int(document_id or 0))
    finally:
        conn.close()
    return {"status": "success", "workflow": workflow, **card}


@router.post("/api/docflow/documents/{document_id}/workflow/start")
async def start_document_workflow(document_id: int, data: DocumentWorkflowStartData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update") or not has_permission(actor, "approvals", "create"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id=?", (int(document_id or 0),))
        document = _row_dict(cursor.fetchone())
        if not document:
            return {"error": "document_not_found"}
        if not _safe_text(document.get("resolution")) or not int(document.get("resolution_task_id") or 0):
            return {"error": "resolution_task_required"}
        existing_workflow = compose_document_workflow(conn, int(document_id or 0))
        if int(document.get("workflow_started_at") or 0) and int(existing_workflow.get("approval", {}).get("id") or 0):
            return {"status": "success", "approval_id": int(existing_workflow.get("approval", {}).get("id") or 0), "workflow": existing_workflow, **_load_document_legal_card(conn, document_id, actor)}
        _ensure_document_task_link(cursor, document, int(document.get("resolution_task_id") or 0), actor)
        route_context = _document_workflow_route_context(document, data.route_context or {})
        route_rules = _resolve_document_workflow_route(cursor, document, actor, data.route_rules or [], route_context)
        approval_title = _safe_text(data.approval_title) or f"Согласование входящего документа №{_safe_text(document.get('number')) or document_id}"
        approval_id, approval_payload = _create_approval_record(
            cursor,
            ApprovalData(
                title=approval_title,
                item_link=f"/documents/{int(document_id or 0)}",
                route=[],
                route_rules=route_rules,
                route_context=route_context,
                author=_safe_text(actor.get("name")),
                entity_type="document",
                entity_id=str(int(document_id or 0)),
                required_comment_on_reject=1,
                required_comment_on_return=1,
                escalation_role="Директор",
            ),
            actor,
        )
        if not approval_id:
            return approval_payload
        now = int(time.time())
        cursor.execute(
            """
            UPDATE documents
            SET workflow_started_at=?, workflow_completed_at=0, approval_id=?, workflow_stage='incoming',
                workflow_status='in_progress', workflow_block_reason=''
            WHERE id=?
            """,
            (now, approval_id, int(document_id or 0)),
        )
        _ensure_lifecycle_event(cursor, int(document_id or 0), _safe_text(document.get("lifecycle_state") or document.get("status")), _safe_text(document.get("lifecycle_state") or document.get("status")), "workflow_started", actor, data.comment or "Запущена сквозная цепочка документа")
        workflow = sync_document_workflow(conn, int(document_id or 0), actor, data.comment, "workflow_started")
        conn.commit()
        card = _load_document_legal_card(conn, document_id, actor)
    finally:
        conn.close()
    _approval_notify_users("Новое согласование", f"Тебе назначено согласование «{approval_title}».", approval_id, approval_payload.get("current_assignees") or [])
    audit_log("document_workflow_started", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document", entity_id=str(document_id), details={"approval_id": approval_id, "workflow_stage": workflow.get("stage", "")})
    await manager.broadcast({"type": "approvals"})
    await manager.broadcast({"type": "documents"})
    await manager.broadcast({"type": "tasks"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "approval_id": approval_id, "workflow": workflow, **card}

@router.get("/api/knowledge")
def get_knowledge(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "knowledge", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM knowledge_base ORDER BY id DESC")
    res = []
    for r in c.fetchall():
        d = dict(r); d['required_roles'] = json.loads(d['required_roles']); d['read_by'] = json.loads(d['read_by'])
        res.append(d)
    conn.close()
    return res

@router.post("/api/knowledge")
async def create_knowledge(data: KnowledgeData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "knowledge", "create"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    knowledge_id = _next_local_id(c, "knowledge_base")
    c.execute("INSERT INTO knowledge_base (id, title, content, file_url, author, created_at, required_roles, read_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (knowledge_id, data.title, data.content, "", data.author, time.strftime("%d.%m.%Y %H:%M"), json.dumps(data.required_roles), "[]"))
    conn.commit()
    conn.close()
    await manager.broadcast({"type": "knowledge"})
    return {"status": "success"}

@router.post("/api/knowledge/{k_id}/read")
async def read_knowledge(k_id: int, data: KnowledgeReadData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "knowledge", "read"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT read_by FROM knowledge_base WHERE id=?", (k_id,))
    row = c.fetchone()
    if row:
        read_by = json.loads(row[0]) if row[0] else []
        if data.user not in read_by:
            read_by.append(data.user)
            c.execute("UPDATE knowledge_base SET read_by=? WHERE id=?", (json.dumps(read_by), k_id))
            conn.commit()
            await manager.broadcast({"type": "knowledge"})
    conn.close()
    return {"status": "success"}

def _load_json_dict(raw_value, default=None):
    fallback = default if isinstance(default, dict) else {}
    if not raw_value:
        return dict(fallback)
    try:
        data = json.loads(raw_value)
        return data if isinstance(data, dict) else dict(fallback)
    except Exception:
        return dict(fallback)


def _approval_now_ts() -> int:
    return int(time.time())


def _approval_display_ts(ts_value: int) -> str:
    ts = int(ts_value or 0)
    if not ts:
        return ""
    return datetime.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


def _approval_format_route_name(stage: dict) -> str:
    names = [_safe_text(name) for name in (stage.get("assignees") or []) if _safe_text(name)]
    return " и ".join(names)


def _approval_find_role_user(cursor, role_name: str) -> str:
    role_name = _safe_text(role_name)
    if not role_name:
        return ""
    cursor.execute(
        """
        SELECT name
        FROM users
        WHERE role=? AND status='approved'
        ORDER BY is_head DESC, name ASC
        LIMIT 1
        """,
        (role_name,),
    )
    row = cursor.fetchone()
    if not row:
        return ""
    return _safe_text(row["name"] if isinstance(row, dict) else row[0])


def _approval_resolve_substitute(cursor, person_name: str) -> str:
    person_name = _safe_text(person_name)
    if not person_name:
        return ""
    cursor.execute("SELECT abs_start, abs_end, deputy FROM users WHERE name=?", (person_name,))
    u_row = cursor.fetchone()
    if not u_row or not u_row["deputy"] or not u_row["abs_start"] or not u_row["abs_end"]:
        return person_name
    if _is_absence_effective(u_row["abs_start"], u_row["abs_end"]):
        return f"{u_row['deputy']} (И.О. {person_name})"
    return person_name


def _approval_condition_matches(condition: dict, context: dict) -> bool:
    if not condition:
        return True
    if "all" in condition:
        return all(_approval_condition_matches(item, context) for item in condition.get("all") or [])
    if "any" in condition:
        options = condition.get("any") or []
        return any(_approval_condition_matches(item, context) for item in options) if options else True
    field_name = _safe_text(condition.get("field"))
    if not field_name:
        return True
    current = context.get(field_name)
    op = _safe_text(condition.get("op")).lower() or "eq"
    expected = condition.get("value")
    if op == "eq":
        return current == expected
    if op == "ne":
        return current != expected
    if op == "gt":
        return float(current or 0) > float(expected or 0)
    if op == "gte":
        return float(current or 0) >= float(expected or 0)
    if op == "lt":
        return float(current or 0) < float(expected or 0)
    if op == "lte":
        return float(current or 0) <= float(expected or 0)
    if op == "in":
        return current in (expected or [])
    if op == "not_in":
        return current not in (expected or [])
    if op == "truthy":
        return bool(current)
    return True


def _approval_normalize_stage(cursor, raw_stage, order_no: int, previous_stage_key: str, context: dict, data: ApprovalData) -> dict | None:
    if isinstance(raw_stage, str):
        stage = {
            "stage_name": f"Этап {order_no}",
            "assignees": [_safe_text(name) for name in raw_stage.split(" и ") if _safe_text(name)],
        }
    else:
        stage = dict(raw_stage or {})
    if not _approval_condition_matches(stage.get("condition") or {}, context):
        return None
    stage_key = _safe_text(stage.get("stage_key")) or f"stage_{order_no}"
    assignees = [_safe_text(name) for name in (stage.get("assignees") or []) if _safe_text(name)]
    if not assignees and _safe_text(stage.get("role_name")):
        role_user = _approval_find_role_user(cursor, stage.get("role_name"))
        if role_user:
            assignees = [role_user]
    if not assignees and _safe_text(stage.get("assignee")):
        assignees = [_safe_text(stage.get("assignee"))]
    resolved_assignees = []
    for name in assignees:
        resolved_name = _approval_resolve_substitute(cursor, name)
        if resolved_name and resolved_name not in resolved_assignees:
            resolved_assignees.append(resolved_name)
    if not resolved_assignees:
        return None
    return {
        "stage_key": stage_key,
        "stage_name": _safe_text(stage.get("stage_name")) or f"Этап {order_no}",
        "assignees": resolved_assignees,
        "original_assignees": assignees or list(resolved_assignees),
        "parallel_mode": "any" if _safe_text(stage.get("parallel_mode")).lower() == "any" else "all",
        "sla_hours": max(1, int(stage.get("sla_hours") or data.default_sla_hours or 24)),
        "status": "queued",
        "approved_by": [],
        "returned_from": [],
        "started_at": 0,
        "due_at": 0,
        "completed_at": 0,
        "allow_delegate": int(stage.get("allow_delegate", 1)),
        "require_comment_on_reject": int(stage.get("require_comment_on_reject", data.required_comment_on_reject or 0)),
        "require_comment_on_return": int(stage.get("require_comment_on_return", data.required_comment_on_return or 0)),
        "return_to_stage_key": _safe_text(stage.get("return_to_stage_key")) or _safe_text(previous_stage_key),
        "escalation_role": _safe_text(stage.get("escalation_role")) or _safe_text(data.escalation_role),
        "escalated_to": "",
        "escalated_at": 0,
        "condition": stage.get("condition") or {},
        "comments": [],
        "order_no": order_no,
    }


def _approval_activate_stage(stages: list[dict], stage_key: str, now_ts: int):
    for stage in stages:
        if _safe_text(stage.get("stage_key")) != _safe_text(stage_key):
            continue
        stage["status"] = "pending" if _safe_text(stage.get("status")) != "rework" else "rework"
        stage["started_at"] = now_ts
        stage["due_at"] = now_ts + max(1, int(stage.get("sla_hours") or 24)) * 3600
        return stage
    return {}


def _approval_next_stage(stages: list[dict], current_stage_key: str) -> dict:
    found = False
    for stage in sorted(stages, key=lambda item: int(item.get("order_no") or 0)):
        if not found:
            if _safe_text(stage.get("stage_key")) == _safe_text(current_stage_key):
                found = True
            continue
        if _safe_text(stage.get("status")) in {"queued", "rework"}:
            return stage
    return {}


def _approval_legacy_state(row: dict) -> dict:
    legacy_route = _load_json_list(row.get("route"))
    history = _load_json_list(row.get("history"))
    current_step = int(row.get("current_step") or 0)
    status = _safe_text(row.get("status")) or "pending"
    stages = []
    for idx, item in enumerate(legacy_route, start=1):
        names = [_safe_text(name) for name in _safe_text(item).split(" и ") if _safe_text(name)]
        stage_status = "approved" if idx - 1 < current_step else "queued"
        if idx - 1 == current_step:
            if status == "rejected":
                stage_status = "rejected"
            elif status == "completed":
                stage_status = "approved"
            else:
                stage_status = "pending"
        if status == "completed" and idx - 1 > current_step:
            stage_status = "approved"
        stages.append({
            "stage_key": f"legacy_{idx}",
            "stage_name": f"Этап {idx}",
            "assignees": names,
            "original_assignees": list(names),
            "parallel_mode": "all",
            "sla_hours": 24,
            "status": stage_status,
            "approved_by": [],
            "returned_from": [],
            "started_at": 0,
            "due_at": 0,
            "completed_at": 0,
            "allow_delegate": 1,
            "require_comment_on_reject": 0,
            "require_comment_on_return": 0,
            "return_to_stage_key": f"legacy_{max(1, idx - 1)}" if idx > 1 else "",
            "escalation_role": "",
            "escalated_to": "",
            "escalated_at": 0,
            "condition": {},
            "comments": [],
            "order_no": idx,
        })
    current_stage = next((stage for stage in stages if stage.get("status") in {"pending", "rework"}), {})
    return {
        "stages": stages,
        "history": history,
        "current_stage_key": _safe_text(current_stage.get("stage_key")),
        "route_context": _load_json_dict(row.get("route_context")),
    }


def _approval_load_state(row: dict) -> dict:
    state = _load_json_dict(row.get("approval_state"))
    if not state.get("stages"):
        state = _approval_legacy_state(row)
    state["history"] = state.get("history") if isinstance(state.get("history"), list) else _load_json_list(row.get("history"))
    state["route_context"] = state.get("route_context") if isinstance(state.get("route_context"), dict) else _load_json_dict(row.get("route_context"))
    return state


def _approval_sla_status(due_at: int, status: str) -> str:
    if _safe_text(status) in {"completed", "rejected"}:
        return "closed"
    due_at = int(due_at or 0)
    if not due_at:
        return "stable"
    now_ts = _approval_now_ts()
    if due_at <= now_ts:
        return "overdue"
    if due_at <= now_ts + 4 * 3600:
        return "warning"
    return "stable"


def _approval_history_line(prefix: str, actor_name: str, comment: str = "", stage_name: str = "") -> str:
    suffix = f" · {comment}" if _safe_text(comment) else ""
    stage_suffix = f" [{stage_name}]" if _safe_text(stage_name) else ""
    return f"{prefix} {actor_name}{stage_suffix}{suffix} ({time.strftime('%d.%m.%Y %H:%M')})"


def _approval_log_action(cursor, approval_id: int, stage_key: str, action_name: str, actor: dict, target_user: str = "", comment: str = "", payload: dict | None = None):
    cursor.execute(
        """
        INSERT INTO approval_action_log (
            approval_id, stage_key, action_name, actor_email, actor_name, target_user, comment, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(approval_id or 0),
            _safe_text(stage_key),
            _safe_text(action_name),
            actor.get("email", ""),
            actor.get("name", ""),
            _safe_text(target_user),
            _safe_text(comment),
            json.dumps(payload or {}, ensure_ascii=False),
            _approval_now_ts(),
        ),
    )


def _approval_record_sla_event(cursor, approval_id: int, stage_key: str, event_type: str, risk_level: str, actor_name: str = "", comment: str = "", due_at: int = 0):
    cursor.execute(
        """
        INSERT INTO approval_sla_events (
            approval_id, stage_key, event_type, risk_level, due_at, actor_name, comment, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (int(approval_id or 0), _safe_text(stage_key), _safe_text(event_type), _safe_text(risk_level), int(due_at or 0), _safe_text(actor_name), _safe_text(comment), _approval_now_ts()),
    )


def _approval_compose_payload(row: dict, state: dict, actor: dict | None = None) -> dict:
    stages = sorted(state.get("stages") or [], key=lambda item: int(item.get("order_no") or 0))
    current_stage = next((stage for stage in stages if _safe_text(stage.get("stage_key")) == _safe_text(state.get("current_stage_key"))), {})
    route = [_approval_format_route_name(stage) for stage in stages]
    current_step = next((idx for idx, stage in enumerate(stages) if _safe_text(stage.get("stage_key")) == _safe_text(state.get("current_stage_key"))), max(0, len(route) - 1))
    pending_users = [_safe_text(name) for name in (current_stage.get("assignees") or []) if _safe_text(name)]
    stage_sla_status = _approval_sla_status(current_stage.get("due_at"), row.get("status"))
    available_actions = []
    actor_name = _safe_text((actor or {}).get("name"))
    if actor_name and (actor_name in pending_users or _safe_text((actor or {}).get("role")) == "Директор"):
        available_actions = ["approve", "reject", "return_rework", "delegate"]
    payload = dict(row)
    payload["route"] = route
    payload["current_step"] = current_step
    payload["history"] = list(state.get("history") or [])
    payload["route_context"] = state.get("route_context") or {}
    payload["route_steps"] = stages
    payload["current_stage_key"] = _safe_text(state.get("current_stage_key"))
    payload["current_assignees"] = pending_users
    payload["active_stage"] = current_stage
    payload["pending_users"] = pending_users
    payload["sla_status"] = stage_sla_status
    payload["due_at"] = int(current_stage.get("due_at") or row.get("due_at") or 0)
    payload["due_at_display"] = _approval_display_ts(payload["due_at"])
    payload["available_actions"] = available_actions
    payload["approval_state"] = {"stages": stages, "route_context": payload["route_context"]}
    return payload


def _approval_save(cursor, row: dict, state: dict):
    stages = sorted(state.get("stages") or [], key=lambda item: int(item.get("order_no") or 0))
    current_stage = next((stage for stage in stages if _safe_text(stage.get("status")) in {"pending", "rework"}), {})
    route = [_approval_format_route_name(stage) for stage in stages]
    current_step = next((idx for idx, stage in enumerate(stages) if _safe_text(stage.get("stage_key")) == _safe_text(current_stage.get("stage_key"))), max(0, len(route) - 1 if route else 0))
    current_assignees = [name for name in (current_stage.get("assignees") or []) if _safe_text(name)]
    state["current_stage_key"] = _safe_text(current_stage.get("stage_key"))
    state["route_context"] = state.get("route_context") or _load_json_dict(row.get("route_context"))
    cursor.execute(
        """
        UPDATE approvals
        SET route=?, current_step=?, status=?, history=?, entity_type=?, entity_id=?, route_rules=?, route_context=?,
            current_stage_key=?, current_assignees=?, approval_state=?, due_at=?, completed_at=?,
            required_comment_on_reject=?, required_comment_on_return=?, last_action_at=?, escalation_role=?
        WHERE id=?
        """,
        (
            json.dumps(route, ensure_ascii=False),
            current_step,
            row.get("status", "pending"),
            json.dumps(state.get("history") or [], ensure_ascii=False),
            row.get("entity_type", ""),
            row.get("entity_id", ""),
            json.dumps(row.get("route_rules") or [], ensure_ascii=False),
            json.dumps(state.get("route_context") or {}, ensure_ascii=False),
            state.get("current_stage_key", ""),
            json.dumps(current_assignees, ensure_ascii=False),
            json.dumps({"stages": stages, "history": state.get("history") or [], "route_context": state.get("route_context") or {}, "current_stage_key": state.get("current_stage_key", "")}, ensure_ascii=False),
            int(current_stage.get("due_at") or 0),
            int(row.get("completed_at") or 0),
            int(row.get("required_comment_on_reject") or 0),
            int(row.get("required_comment_on_return") or 0),
            int(row.get("last_action_at") or 0),
            row.get("escalation_role", ""),
            int(row.get("id") or 0),
        ),
    )


def _approval_notify_users(title: str, message: str, approval_id: int, users: list[str]):
    for user_name in users:
        if not _safe_text(user_name):
            continue
        create_targeted_notifications(
            title,
            message,
            user_name=_safe_text(user_name).split(" (И.О.")[0],
            role=_safe_text(user_name),
            category="approval",
            entity_type="approval",
            entity_id=str(approval_id),
        )


@router.get("/api/approvals")
def get_approvals(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM approvals ORDER BY id DESC").fetchall()]
    finally:
        conn.close()
    return [_approval_compose_payload(row, _approval_load_state(row), actor) for row in rows]


@router.get("/api/approvals/route_templates")
def get_approval_route_templates(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM approval_route_templates ORDER BY updated_at DESC, id DESC").fetchall()]
    finally:
        conn.close()
    for row in rows:
        row["conditions"] = _load_json_dict(row.get("conditions_json"))
        row["stages"] = _load_json_list(row.get("stages_json"))
    return {"status": "success", "items": rows}


@router.post("/api/approvals/route_templates")
def create_approval_route_template(data: ApprovalRouteTemplateData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "create"):
        return {"error": "forbidden"}
    now_ts = _approval_now_ts()
    route_code = _safe_text(data.route_code) or f"APR-{now_ts}"
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO approval_route_templates (
                route_code, route_name, entity_type, conditions_json, stages_json, is_active, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                route_code,
                data.route_name or route_code,
                data.entity_type,
                json.dumps(data.conditions or {}, ensure_ascii=False),
                json.dumps(data.stages or [], ensure_ascii=False),
                int(data.is_active or 0),
                data.comment,
                actor.get("email", ""),
                now_ts,
                now_ts,
            ),
        )
        template_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()
    audit_log("approval_route_template_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="approval_route_template", entity_id=str(template_id), details={"route_code": route_code})
    return {"status": "success", "id": template_id, "route_code": route_code}


@router.get("/api/workflows/definitions")
def get_workflow_definitions(request: Request, entity_type: str = "", include_inactive: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        items = workflow_list_definitions(conn, entity_type=entity_type, include_inactive=bool(int(include_inactive or 0)))
    finally:
        conn.close()
    return {"status": "success", "items": items}


@router.get("/api/workflows/definitions/{definition_id}")
def get_workflow_definition(definition_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        definition = workflow_get_definition(conn, definition_id)
    finally:
        conn.close()
    if not definition:
        return {"error": "workflow_definition_not_found"}
    return {"status": "success", "definition": definition}


@router.post("/api/workflows/definitions")
async def create_workflow_definition(data: WorkflowDefinitionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "create"):
        return {"error": "forbidden"}
    payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
    conn = get_connection(row_factory=True)
    try:
        result = workflow_create_definition(conn, payload, actor)
        if result.get("error"):
            conn.rollback()
            return result
        conn.commit()
    finally:
        conn.close()
    audit_log("workflow_definition_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="workflow_definition", entity_id=str(result.get("id")), details={"workflow_code": result.get("workflow_code")})
    await manager.broadcast({"type": "approvals"})
    return result


@router.post("/api/workflows/definitions/{definition_id}/start")
async def start_workflow_instance(definition_id: int, data: WorkflowStartData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "create"):
        return {"error": "forbidden"}
    payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
    conn = get_connection(row_factory=True)
    try:
        result = workflow_start_instance(conn, definition_id, payload, actor)
        if result.get("error"):
            conn.rollback()
            return result
        conn.commit()
    finally:
        conn.close()
    audit_log("workflow_instance_started", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="workflow_instance", entity_id=str(result.get("id")), details={"definition_id": definition_id, "entity_type": payload.get("entity_type"), "entity_id": payload.get("entity_id")})
    await manager.broadcast({"type": "approvals"})
    await manager.broadcast({"type": "notifications"})
    return result


@router.get("/api/workflows/instances")
def get_workflow_instances(request: Request, status: str = "", limit: int = 80):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        items = workflow_list_instances(conn, status=status, limit=limit)
    finally:
        conn.close()
    return {"status": "success", "items": items}


@router.get("/api/workflows/instances/{instance_id}")
def get_workflow_instance(instance_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        instance = workflow_get_instance(conn, instance_id)
    finally:
        conn.close()
    if not instance:
        return {"error": "workflow_instance_not_found"}
    return {"status": "success", "instance": instance}


@router.post("/api/workflows/tokens/{token_id}/actions")
async def apply_workflow_token_action(token_id: int, data: WorkflowTokenActionData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
    conn = get_connection(row_factory=True)
    try:
        result = apply_token_action(conn, token_id, payload, actor)
        if result.get("error"):
            conn.rollback()
            return result
        conn.commit()
    finally:
        conn.close()
    audit_log("workflow_token_action", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="workflow_token", entity_id=str(token_id), details={"action": payload.get("action_name"), "instance_id": (result.get("instance") or {}).get("id")})
    await manager.broadcast({"type": "approvals"})
    await manager.broadcast({"type": "notifications"})
    return result


@router.post("/api/workflows/process_automation")
async def process_workflow_automation(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        result = workflow_process_automation(conn, actor)
        conn.commit()
    finally:
        conn.close()
    audit_log("workflow_automation_processed", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="workflow", entity_id="", details={"count": result.get("count", 0)})
    await manager.broadcast({"type": "approvals"})
    await manager.broadcast({"type": "notifications"})
    return result


def _create_approval_record(cursor, data: ApprovalData, actor: dict) -> tuple[int, dict]:
    approval_id = _next_local_id(cursor, "approvals")
    stages = []
    route_source = data.route_rules or data.route
    previous_stage_key = ""
    order_no = 1
    for raw_stage in route_source:
        normalized = _approval_normalize_stage(cursor, raw_stage, order_no, previous_stage_key, data.route_context or {}, data)
        if not normalized:
            continue
        stages.append(normalized)
        previous_stage_key = normalized["stage_key"]
        order_no += 1
    if not stages:
        return 0, {"error": "empty_route"}
    now_ts = _approval_now_ts()
    current_stage = _approval_activate_stage(stages, stages[0]["stage_key"], now_ts)
    history = [_approval_history_line("▶", actor.get("name", data.author), "маршрут запущен", current_stage.get("stage_name", ""))]
    row = {
        "id": approval_id,
        "title": data.title,
        "item_link": data.item_link,
        "status": "pending",
        "author": data.author or actor.get("name", ""),
        "entity_type": data.entity_type,
        "entity_id": data.entity_id,
        "route_rules": data.route_rules or [],
        "required_comment_on_reject": int(data.required_comment_on_reject or 0),
        "required_comment_on_return": int(data.required_comment_on_return or 0),
        "last_action_at": now_ts,
        "completed_at": 0,
        "escalation_role": data.escalation_role or "",
    }
    state = {"stages": stages, "history": history, "route_context": data.route_context or {}, "current_stage_key": current_stage.get("stage_key", "")}
    cursor.execute(
        """
        INSERT INTO approvals (
            id, title, item_link, route, current_step, status, history, author, created_at,
            entity_type, entity_id, route_rules, route_context, current_stage_key, current_assignees,
            approval_state, due_at, completed_at, required_comment_on_reject, required_comment_on_return,
            last_action_at, escalation_role
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            approval_id,
            data.title,
            data.item_link,
            json.dumps([_approval_format_route_name(stage) for stage in stages], ensure_ascii=False),
            0,
            "pending",
            json.dumps(history, ensure_ascii=False),
            data.author or actor.get("name", ""),
            time.strftime("%d.%m.%Y %H:%M"),
            data.entity_type,
            data.entity_id,
            json.dumps(data.route_rules or [], ensure_ascii=False),
            json.dumps(data.route_context or {}, ensure_ascii=False),
            current_stage.get("stage_key", ""),
            json.dumps(current_stage.get("assignees") or [], ensure_ascii=False),
            json.dumps(state, ensure_ascii=False),
            int(current_stage.get("due_at") or 0),
            0,
            int(data.required_comment_on_reject or 0),
            int(data.required_comment_on_return or 0),
            now_ts,
            data.escalation_role or "",
        ),
    )
    _approval_log_action(cursor, approval_id, current_stage.get("stage_key", ""), "created", actor, comment="Маршрут согласования создан", payload={"title": data.title})
    payload = _approval_compose_payload(dict(row, created_at=time.strftime("%d.%m.%Y %H:%M"), route="[]", history="[]"), state, actor)
    return approval_id, payload


@router.post("/api/approvals")
async def create_approval(data: ApprovalData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "create"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        approval_id, payload = _create_approval_record(cursor, data, actor)
        if not approval_id:
            return payload
        conn.commit()
        if _safe_text(data.entity_type) == "document" and _safe_text(data.entity_id).isdigit():
            sync_document_workflow(conn, int(data.entity_id), actor, action_name="workflow_approval_created")
            conn.commit()
    finally:
        conn.close()
    _approval_notify_users("Новое согласование", f"Тебе назначено согласование «{data.title}».", approval_id, payload.get("current_assignees") or [])
    audit_log("approval_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="approval", entity_id=str(approval_id), details={"title": data.title, "stage": payload.get("current_stage_key", ""), "assignees": payload.get("current_assignees", [])})
    await manager.broadcast({"type": "approvals"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "id": approval_id, **payload}


@router.post("/api/approvals/{a_id}/actions")
async def apply_approval_action(a_id: int, data: ApprovalActionData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    action_name = _safe_text(data.action_name).lower()
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM approvals WHERE id=?", (int(a_id or 0),))
        row = dict(cursor.fetchone() or {})
        if not row:
            return {"error": "approval_not_found"}
        state = _approval_load_state(row)
        stages = sorted(state.get("stages") or [], key=lambda item: int(item.get("order_no") or 0))
        current_stage = next((stage for stage in stages if _safe_text(stage.get("stage_key")) == _safe_text(state.get("current_stage_key"))), {})
        if not current_stage:
            return {"error": "approval_stage_not_found"}
        actor_name = actor.get("name", "")
        can_override = _safe_text(actor.get("role")) == "Директор"
        pending_assignees = [_safe_text(name) for name in (current_stage.get("assignees") or []) if _safe_text(name)]
        if action_name in {"approve", "reject", "return_rework", "delegate"} and actor_name not in pending_assignees and not can_override:
            return {"error": "approval_action_forbidden", "pending_assignees": pending_assignees}
        comment = _safe_text(data.comment or data.reason)
        now_ts = _approval_now_ts()
        if action_name == "approve":
            if actor_name not in current_stage["approved_by"]:
                current_stage["approved_by"].append(actor_name)
            state.setdefault("history", []).append(_approval_history_line("✅", actor_name, comment, current_stage.get("stage_name", "")))
            completed_stage = current_stage.get("parallel_mode") == "any" or len(current_stage["approved_by"]) >= len(current_stage.get("assignees") or [])
            if completed_stage:
                current_stage["status"] = "approved"
                current_stage["completed_at"] = now_ts
                next_stage = _approval_next_stage(stages, current_stage.get("stage_key", ""))
                if next_stage:
                    _approval_activate_stage(stages, next_stage.get("stage_key", ""), now_ts)
                    row["status"] = "pending"
                    _approval_notify_users("Следующий этап согласования", f"Согласование «{row.get('title', '')}» перешло на следующий этап.", int(a_id or 0), next_stage.get("assignees") or [])
                else:
                    row["status"] = "completed"
                    row["completed_at"] = now_ts
            else:
                row["status"] = "pending"
            row["last_action_at"] = now_ts
            _approval_log_action(cursor, a_id, current_stage.get("stage_key", ""), "approve", actor, comment=comment, payload={"approved_by": current_stage.get("approved_by")})
        elif action_name == "reject":
            if int(current_stage.get("require_comment_on_reject") or row.get("required_comment_on_reject") or 0) and not comment:
                return {"error": "comment_required_on_reject"}
            current_stage["status"] = "rejected"
            current_stage["completed_at"] = now_ts
            row["status"] = "rejected"
            row["completed_at"] = now_ts
            row["last_action_at"] = now_ts
            state.setdefault("history", []).append(_approval_history_line("❌", actor_name, comment or "без комментария", current_stage.get("stage_name", "")))
            _approval_log_action(cursor, a_id, current_stage.get("stage_key", ""), "reject", actor, comment=comment)
        elif action_name == "return_rework":
            if int(current_stage.get("require_comment_on_return") or row.get("required_comment_on_return") or 0) and not comment:
                return {"error": "comment_required_on_return"}
            target_stage_key = _safe_text(data.target_stage_key) or _safe_text(current_stage.get("return_to_stage_key"))
            target_stage = next((stage for stage in stages if _safe_text(stage.get("stage_key")) == target_stage_key), {})
            if not target_stage:
                return {"error": "target_stage_not_found"}
            current_order = int(current_stage.get("order_no") or 0)
            target_order = int(target_stage.get("order_no") or 0)
            for stage in stages:
                if int(stage.get("order_no") or 0) >= target_order:
                    if _safe_text(stage.get("stage_key")) == target_stage_key:
                        stage["status"] = "rework"
                        stage["approved_by"] = []
                        stage["started_at"] = now_ts
                        stage["due_at"] = now_ts + max(1, int(stage.get("sla_hours") or 24)) * 3600
                    elif int(stage.get("order_no") or 0) >= current_order:
                        stage["status"] = "queued"
                        stage["approved_by"] = []
                        stage["started_at"] = 0
                        stage["due_at"] = 0
                        stage["completed_at"] = 0
            current_stage["status"] = "returned"
            current_stage.setdefault("returned_from", []).append({"by": actor_name, "at": now_ts, "target_stage_key": target_stage_key, "comment": comment})
            state["current_stage_key"] = target_stage_key
            row["status"] = "rework"
            row["completed_at"] = 0
            row["last_action_at"] = now_ts
            state.setdefault("history", []).append(_approval_history_line("↩", actor_name, comment, target_stage.get("stage_name", "")))
            _approval_log_action(cursor, a_id, current_stage.get("stage_key", ""), "return_rework", actor, target_user=target_stage_key, comment=comment)
            _approval_notify_users("Маршрут возвращён на доработку", f"Согласование «{row.get('title', '')}» возвращено на этап {target_stage.get('stage_name', '')}.", int(a_id or 0), target_stage.get("assignees") or [])
        elif action_name == "delegate":
            if not int(current_stage.get("allow_delegate") or 0):
                return {"error": "delegation_disabled"}
            target_user = _safe_text(data.target_user)
            if not target_user:
                return {"error": "target_user_required"}
            replaced = False
            updated_assignees = []
            for assignee in current_stage.get("assignees") or []:
                if not replaced and assignee == actor_name:
                    updated_assignees.append(target_user)
                    replaced = True
                else:
                    updated_assignees.append(assignee)
            if not replaced and can_override:
                updated_assignees.append(target_user)
            deduped = []
            for name in updated_assignees:
                if _safe_text(name) and name not in deduped:
                    deduped.append(name)
            current_stage["assignees"] = deduped
            cursor.execute(
                """
                INSERT INTO approval_delegations (
                    approval_id, stage_key, from_user, to_user, status, reason, delegated_by, delegated_at, resolved_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, 0)
                """,
                (int(a_id or 0), current_stage.get("stage_key", ""), actor_name, target_user, comment, actor.get("email", ""), now_ts),
            )
            row["status"] = "pending"
            row["last_action_at"] = now_ts
            state.setdefault("history", []).append(_approval_history_line("⇄", actor_name, f"делегировал(а) -> {target_user}. {comment}".strip(), current_stage.get("stage_name", "")))
            _approval_log_action(cursor, a_id, current_stage.get("stage_key", ""), "delegate", actor, target_user=target_user, comment=comment)
            _approval_notify_users("Тебе делегировали согласование", f"Согласование «{row.get('title', '')}» передано тебе.", int(a_id or 0), [target_user])
        else:
            return {"error": "unsupported_approval_action", "allowed": ["approve", "reject", "return_rework", "delegate"]}
        _approval_save(cursor, row, state)
        for document_id in list_documents_for_approval(conn, int(a_id or 0)):
            sync_document_workflow(conn, document_id, actor, comment, "workflow_approval_sync")
        conn.commit()
        payload = _approval_compose_payload(row, state, actor)
    finally:
        conn.close()
    audit_log("approval_action_applied", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="approval", entity_id=str(a_id), details={"action": action_name, "status": payload.get("status", ""), "current_stage_key": payload.get("current_stage_key", "")})
    if payload.get("status") in {"completed", "rejected", "rework"}:
        result_label = {
            "completed": "согласовано",
            "rejected": "отклонено",
            "rework": "возвращено на доработку",
        }.get(payload.get("status"), "обновлено")
        create_targeted_notifications(
            "Результат согласования",
            f"Согласование «{row.get('title', '')}» {result_label}.",
            user_name=row.get("author", ""),
            category="approval",
            entity_type="approval",
            entity_id=str(a_id),
            exclude_email=actor.get("email", ""),
            fallback_to_director=False,
        )
    await manager.broadcast({"type": "approvals"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", **payload}


@router.post("/api/approvals/process_automation")
async def process_approval_automation(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "update"):
        return {"error": "forbidden"}
    processed = []
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        rows = [dict(row) for row in cursor.execute("SELECT * FROM approvals WHERE status IN ('pending', 'rework') ORDER BY id DESC").fetchall()]
        now_ts = _approval_now_ts()
        for row in rows:
            state = _approval_load_state(row)
            stages = state.get("stages") or []
            current_stage = next((stage for stage in stages if _safe_text(stage.get("stage_key")) == _safe_text(state.get("current_stage_key"))), {})
            if not current_stage:
                continue
            due_at = int(current_stage.get("due_at") or 0)
            if not due_at or due_at > now_ts or _safe_text(current_stage.get("escalated_to")):
                continue
            escalation_target = ""
            for assignee in current_stage.get("assignees") or []:
                base_name = _safe_text(assignee).split(" (И.О.")[0]
                cursor.execute("SELECT deputy FROM users WHERE name=?", (base_name,))
                deputy_row = cursor.fetchone()
                deputy_name = _safe_text(deputy_row["deputy"] if deputy_row and isinstance(deputy_row, dict) else deputy_row[0] if deputy_row else "")
                if deputy_name:
                    escalation_target = deputy_name
                    break
            if not escalation_target:
                escalation_target = _approval_find_role_user(cursor, current_stage.get("escalation_role") or row.get("escalation_role") or "Директор")
            if not escalation_target:
                continue
            current_stage["escalated_to"] = escalation_target
            current_stage["escalated_at"] = now_ts
            if escalation_target not in (current_stage.get("assignees") or []):
                current_stage["assignees"] = list(current_stage.get("assignees") or []) + [escalation_target]
            row["last_action_at"] = now_ts
            row["status"] = "pending"
            state.setdefault("history", []).append(_approval_history_line("⏱", actor.get("name", "Система"), f"эскалация -> {escalation_target}", current_stage.get("stage_name", "")))
            _approval_record_sla_event(cursor, row.get("id", 0), current_stage.get("stage_key", ""), "escalated", "overdue", actor.get("name", "Система"), f"Эскалация на {escalation_target}", due_at)
            _approval_log_action(cursor, row.get("id", 0), current_stage.get("stage_key", ""), "auto_escalate", actor, target_user=escalation_target, comment="Автоэскалация по сроку реакции", payload={"due_at": due_at})
            _approval_save(cursor, row, state)
            for document_id in list_documents_for_approval(conn, int(row.get("id") or 0)):
                sync_document_workflow(conn, document_id, actor, "Автоэскалация согласования", "workflow_approval_sync")
            processed.append({"approval_id": int(row.get("id") or 0), "stage_key": current_stage.get("stage_key", ""), "escalated_to": escalation_target, "due_at": due_at})
            _approval_notify_users("Эскалация согласования", f"По согласованию «{row.get('title', '')}» сработала автоэскалация.", int(row.get("id") or 0), [escalation_target])
        conn.commit()
    finally:
        conn.close()
    await manager.broadcast({"type": "approvals"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success", "processed": processed, "count": len(processed)}


@router.put("/api/approvals/{a_id}")
async def update_approval(a_id: int, data: ApprovalUpdate, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "approvals", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM approvals WHERE id=?", (int(a_id or 0),))
        row = dict(cursor.fetchone() or {})
        if not row:
            return {"error": "approval_not_found"}
        state = data.approval_state or _approval_load_state(row)
        if data.route:
            for idx, item in enumerate(data.route, start=1):
                if idx - 1 < len(state.get("stages") or []):
                    state["stages"][idx - 1]["assignees"] = [_safe_text(name) for name in _safe_text(item).split(" и ") if _safe_text(name)]
        if data.current_stage_key:
            state["current_stage_key"] = data.current_stage_key
        state["history"] = list(data.history or state.get("history") or [])
        row["status"] = data.status or row.get("status", "pending")
        row["last_action_at"] = _approval_now_ts()
        row["completed_at"] = row["last_action_at"] if row["status"] in {"completed", "rejected"} else 0
        _approval_save(cursor, row, state)
        for document_id in list_documents_for_approval(conn, int(a_id or 0)):
            sync_document_workflow(conn, document_id, actor, "Обновление согласования", "workflow_approval_sync")
        conn.commit()
        payload = _approval_compose_payload(row, state, actor)
    finally:
        conn.close()
    audit_log("approval_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="approval", entity_id=str(a_id), details={"status": payload.get("status", ""), "current_step": payload.get("current_step", 0)})
    await manager.broadcast({"type": "approvals"})
    return {"status": "success", **payload}
