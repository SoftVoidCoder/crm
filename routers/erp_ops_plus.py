import json
import re
import time
from datetime import datetime

from fastapi import APIRouter, Request

from database import (
    audit_log,
    create_notification,
    delete_user_sessions_for_email,
    get_audit_logs,
    get_connection,
    get_field_access_rules,
    get_field_change_logs,
    next_safe_table_id,
    list_user_sessions,
    revoke_user_session,
)
from permissions import PERMISSION_MATRIX, has_permission, require_approved_user
from routers import projects as projects_router
from schemas import (
    DocumentLinkedTaskData,
    DocumentOCRJobData,
    DocumentTemplateData,
    DocumentTemplateFlowApplyData,
    DocumentTemplateFlowData,
    DocumentVersionRecordData,
    EDOCertificateData,
    IntegrationConnectorData,
    IntegrationFieldMappingData,
    IntegrationInboundUpdateRecordData,
    LegalArchiveEntryData,
    PrintFormRecordData,
    SecurityActionPolicyData,
    SecurityDangerRuleData,
    SecurityGuardCheckData,
    SecuritySessionControlData,
)
from services.policy_service import build_security_matrix_snapshot, evaluate_security_gate, explain_policy_error
from services.document_content_index_service import extract_text_for_revision_id, upsert_index_from_text

router = APIRouter()


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_text(value) -> str:
    return str(value or "").strip()


def _json_load(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _now_ts() -> int:
    return int(time.time())


def _today_display() -> str:
    return datetime.now().strftime("%d.%m.%Y")


def _format_file_size(size_value) -> str:
    size = max(0, _safe_int(size_value))
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{round(size / 1024, 1)} KB"
    return f"{round(size / (1024 * 1024), 2)} MB"


def _row_dicts(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def _director_only(request: Request):
    actor = require_approved_user(request)
    if not actor or actor.get("role") != "Директор":
        return None
    return actor


def _security_policy_for(actor: dict, module_name: str, entity_type: str, action_name: str, status_name: str = "") -> dict | None:
    conn = get_connection(row_factory=True)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM security_action_policies
            WHERE role_name=? AND module_name=? AND action_name=? AND is_active=1
              AND (entity_type='' OR entity_type=?)
              AND (status_name='' OR status_name=?)
            ORDER BY
                CASE WHEN entity_type=? THEN 2 ELSE 1 END DESC,
                CASE WHEN status_name=? THEN 2 ELSE 1 END DESC,
                id DESC
            LIMIT 1
            """,
            (
                actor.get("role", ""),
                module_name,
                action_name,
                entity_type,
                status_name,
                entity_type,
                status_name,
            ),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _danger_rule_for(module_name: str, entity_type: str, action_name: str) -> dict | None:
    conn = get_connection(row_factory=True)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM security_danger_rules
            WHERE module_name=? AND action_name=? AND is_active=1
              AND (entity_type='' OR entity_type=?)
            ORDER BY CASE WHEN entity_type=? THEN 2 ELSE 1 END DESC, id DESC
            LIMIT 1
            """,
            (module_name, action_name, entity_type, entity_type),
        ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["blocked_roles"] = _json_load(payload.get("blocked_roles"), [])
        return payload
    finally:
        conn.close()


def _security_gate(actor: dict, module_name: str, entity_type: str, action_name: str, status_name: str = "", reason: str = "") -> dict | None:
    return evaluate_security_gate(
        actor,
        module_name,
        entity_type,
        action_name,
        status_name=status_name,
        reason=reason,
        get_policy_fn=_security_policy_for,
        get_danger_rule_fn=_danger_rule_for,
    )


def _doc_row(conn, document_id: int) -> dict:
    row = conn.execute("SELECT * FROM documents WHERE id=?", (_safe_int(document_id),)).fetchone()
    return dict(row) if row else {}


def _normalized_doc_type(value: str) -> str:
    raw = _safe_text(value).lower()
    if raw in {"incoming", "входящий"}:
        return "incoming"
    if raw in {"outgoing", "исходящий"}:
        return "outgoing"
    if raw.startswith("internal") or raw in {"order", "memo", "приказ", "служебная"}:
        return "internal"
    if raw in {"draft", "drafts", "черновик"}:
        return "draft"
    return raw or "unknown"


def _doc_type_label(value: str) -> str:
    mapping = {
        "incoming": "Входящий",
        "outgoing": "Исходящий",
        "internal": "Внутренний",
        "draft": "Черновик",
        "unknown": "Без типа",
    }
    return mapping.get(value, value or "Без типа")


def _template_family_key(title: str) -> str:
    raw = _safe_text(title).lower()
    if not raw:
        return "template"
    for token in (" v", " версия ", " ver.", " rev.", "ред."):
        idx = raw.find(token)
        if idx > 0:
            raw = raw[:idx]
            break
    return raw.strip() or "template"


def _parse_ddmmyyyy_ts(value: str) -> int:
    raw = _safe_text(value)
    if not raw:
        return 0
    try:
        return int(datetime.strptime(raw, "%d.%m.%Y").timestamp())
    except Exception:
        return 0


def _payload_diff(current_payload: dict, previous_payload: dict) -> list[dict]:
    keys = sorted(set((current_payload or {}).keys()) | set((previous_payload or {}).keys()))
    diff = []
    for key in keys:
        before = previous_payload.get(key)
        after = current_payload.get(key)
        if before == after:
            continue
        diff.append({"field_name": key, "before": before, "after": after})
    return diff


def _extract_ocr_fields(text: str) -> dict:
    raw = _safe_text(text)
    compact = " ".join(raw.split())
    fields = {
        "doc_type": "incoming",
        "number": "",
        "d_date": "",
        "correspondent": "",
        "subject": "",
        "amount": 0.0,
        "inn": "",
    }
    lowered = compact.lower()
    if "исход" in lowered or "outgoing" in lowered:
        fields["doc_type"] = "outgoing"
    if "договор" in lowered:
        fields["doc_type"] = "contract"
    if "акт" in lowered:
        fields["doc_type"] = "act"
    if "счет" in lowered or "счёт" in lowered or "invoice" in lowered:
        fields["doc_type"] = "invoice"
    number_match = re.search(r"(?:№|N|номер|number)\s*[:#-]?\s*([A-Za-zА-Яа-я0-9/_-]+)", compact, re.IGNORECASE)
    if number_match:
        fields["number"] = number_match.group(1)
    date_match = re.search(r"(\d{2}[.]\d{2}[.]\d{4}|\d{4}-\d{2}-\d{2})", compact)
    if date_match:
        value = date_match.group(1)
        if "-" in value:
            yyyy, mm, dd = value.split("-")
            value = f"{dd}.{mm}.{yyyy}"
        fields["d_date"] = value
    inn_match = re.search(r"ИНН\s*[:#-]?\s*(\d{10,12})", compact, re.IGNORECASE)
    if inn_match:
        fields["inn"] = inn_match.group(1)
    amount_match = re.search(r"(?:сумма|amount|итого)\s*[:#-]?\s*([0-9\s]+(?:[,.]\d{1,2})?)", compact, re.IGNORECASE)
    if amount_match:
        fields["amount"] = float(amount_match.group(1).replace(" ", "").replace(",", "."))
    correspondent_match = re.search(r"(?:от|from|корреспондент)\s*[:#-]?\s*([^;,.]{3,80})", compact, re.IGNORECASE)
    if correspondent_match:
        fields["correspondent"] = correspondent_match.group(1).strip()
    subject_match = re.search(r"(?:тема|subject|основание)\s*[:#-]?\s*([^;]{3,140})", compact, re.IGNORECASE)
    if subject_match:
        fields["subject"] = subject_match.group(1).strip()
    if not fields["subject"]:
        fields["subject"] = compact[:120] or "Распознанный документ"
    return fields


def _process_ocr_payload(data: DocumentOCRJobData, document: dict | None = None) -> dict:
    source_text = _safe_text(data.input_text)
    extraction_status = ""
    extraction_method = ""
    extraction_message = ""
    extraction_confidence = 0.0
    if not source_text and _safe_int(data.file_revision_id):
        extracted = extract_text_for_revision_id(_safe_int(data.file_revision_id), data.language or "rus+eng")
        source_text = _safe_text(extracted.get("text"))
        extraction_status = _safe_text(extracted.get("status"))
        extraction_method = _safe_text(extracted.get("method"))
        extraction_message = _safe_text(extracted.get("message"))
        extraction_confidence = float(extracted.get("confidence") or 0)
    if not source_text and document:
        source_text = " ".join(
            _safe_text(document.get(key))
            for key in ("type", "number", "d_date", "correspondent", "subject", "file_url")
            if _safe_text(document.get(key))
        )
    recognized = source_text or _safe_text(data.source_file) or "Пустой источник OCR"
    fields = _extract_ocr_fields(recognized)
    filled = len([value for value in fields.values() if value not in ("", 0, 0.0)])
    confidence = round(max(extraction_confidence, min(0.99, 0.45 + filled * 0.08 + min(len(recognized), 1000) / 10000)), 2)
    return {
        "recognized_text": recognized,
        "fields": fields,
        "confidence": confidence,
        "extraction_status": extraction_status or ("indexed" if source_text else "manual"),
        "extraction_method": extraction_method or ("input_text" if data.input_text else "document_fields"),
        "extraction_message": extraction_message,
    }


def _template_flow_payload(row: dict) -> dict:
    item = dict(row or {})
    item["trigger_rules"] = _json_load(item.get("trigger_rules_json"), {})
    item["template_ids"] = _json_load(item.get("template_ids_json"), [])
    item["required_fields"] = _json_load(item.get("required_fields_json"), [])
    return item


def _unique_texts(values) -> list[str]:
    result = []
    for item in values or []:
        text = _safe_text(item)
        if text and text not in result:
            result.append(text)
    return result


def _case_scope_allowed(actor: dict, classifier: dict, case_file: dict, policy: dict) -> bool:
    role_name = _safe_text(actor.get("role"))
    if role_name == "Директор":
        return True
    allowed_roles = (
        _unique_texts(_json_load(case_file.get("allowed_roles_json"), []))
        or _unique_texts(_json_load(policy.get("access_roles_json"), []))
        or _unique_texts(_json_load(classifier.get("allowed_roles_json"), []))
    )
    if not allowed_roles:
        return True
    if role_name in allowed_roles:
        return True
    if _safe_text(actor.get("name")) and _safe_text(actor.get("name")) == _safe_text(case_file.get("responsible_name")):
        return True
    return False


def _document_timeline_for(document_id: int, summary: dict | None = None) -> list[dict]:
    base = summary or _load_docflow_summary()
    items = [item for item in (base.get("timeline") or []) if _safe_int(item.get("document_id")) == _safe_int(document_id)]
    return sorted(items, key=lambda item: int(item.get("timestamp") or 0), reverse=True)


def _workflow_progress(stage: str, status: str) -> int:
    stage = _safe_text(stage)
    status = _safe_text(status)
    if status == "completed":
        return 100
    if stage == "incoming":
        return 10
    if stage == "task":
        return 30
    if stage == "approval":
        return 55
    if stage == "execution":
        return 80
    if stage == "archive":
        return 95 if status == "ready" else 100
    return 0


def _load_docflow_summary(actor: dict | None = None) -> dict:
    conn = get_connection(row_factory=True)
    try:
        documents = _row_dicts(conn.execute("SELECT * FROM documents ORDER BY d_date DESC, id DESC"))
        templates = _row_dicts(conn.execute("SELECT * FROM document_templates ORDER BY updated_at DESC, id DESC"))
        ocr_jobs = _row_dicts(conn.execute("SELECT * FROM document_ocr_jobs ORDER BY updated_at DESC, id DESC LIMIT 160"))
        template_flows = _row_dicts(conn.execute("SELECT * FROM document_template_flows ORDER BY updated_at DESC, id DESC"))
        versions = _row_dicts(conn.execute("SELECT * FROM document_versions ORDER BY created_at DESC, id DESC"))
        file_revisions = _row_dicts(conn.execute("SELECT * FROM document_file_revisions ORDER BY uploaded_at DESC, id DESC"))
        linked_tasks = _row_dicts(conn.execute("SELECT * FROM document_linked_tasks ORDER BY updated_at DESC, id DESC"))
        signatures = _row_dicts(
            conn.execute(
                """
                SELECT s.*, d.number AS document_number, d.subject AS document_subject
                FROM edo_signature_registry s
                LEFT JOIN documents d ON d.id = s.entity_id
                WHERE s.entity_type='document'
                ORDER BY s.created_at DESC, s.id DESC
                """
            )
        )
        certificates = _row_dicts(conn.execute("SELECT * FROM edo_certificates ORDER BY updated_at DESC, id DESC"))
        archive_rows = _row_dicts(
            conn.execute(
                """
                SELECT a.*, d.number AS document_number, d.subject AS document_subject
                FROM document_legal_archive a
                LEFT JOIN documents d ON d.id = a.document_id
                ORDER BY a.updated_at DESC, a.id DESC
                """
            )
        )
        print_forms = _row_dicts(
            conn.execute(
                """
                SELECT pf.*, d.number AS document_number, t.title AS template_title
                FROM document_print_forms pf
                LEFT JOIN documents d ON d.id = pf.document_id
                LEFT JOIN document_templates t ON t.id = pf.template_id
                ORDER BY pf.updated_at DESC, pf.id DESC
                """
            )
        )
        registration_journals = _row_dicts(conn.execute("SELECT * FROM document_registration_journals ORDER BY updated_at DESC, id DESC"))
        registration_records = _row_dicts(conn.execute("SELECT * FROM document_registration_records ORDER BY created_at DESC, id DESC LIMIT 200"))
        classifiers = _row_dicts(conn.execute("SELECT * FROM document_classifiers ORDER BY updated_at DESC, id DESC"))
        case_files = _row_dicts(conn.execute("SELECT * FROM document_case_files ORDER BY updated_at DESC, id DESC"))
        workflow_rows = _row_dicts(conn.execute("SELECT * FROM approvals WHERE entity_type='document' ORDER BY last_action_at DESC, id DESC"))
        lifecycle_events = _row_dicts(conn.execute("SELECT * FROM document_lifecycle_events ORDER BY created_at DESC, id DESC LIMIT 200"))
        retention_policies = _row_dicts(conn.execute("SELECT * FROM document_retention_policies ORDER BY scope_type ASC, scope_value ASC, updated_at DESC"))
        retention_actions = _row_dicts(conn.execute("SELECT * FROM document_retention_actions ORDER BY created_at DESC, id DESC LIMIT 200"))
    finally:
        conn.close()
    for row in templates:
        row["variables"] = _json_load(row.get("variables_json"), [])
        row["normalized_doc_type"] = _normalized_doc_type(row.get("doc_type"))
    for row in ocr_jobs:
        row["extracted_fields"] = _json_load(row.get("extracted_fields_json"), {})
    template_flows = [_template_flow_payload(row) for row in template_flows]
    for row in versions:
        row["payload"] = _json_load(row.get("payload"), {})
    for row in file_revisions:
        row["size_label"] = _format_file_size(row.get("file_size"))
    for row in signatures:
        row["stamp"] = _json_load(row.get("stamp_json"), {})
        row["verification_details"] = _json_load(row.get("verification_details"), {})
    by_document_versions: dict[int, list[dict]] = {}
    file_revisions_by_document: dict[int, list[dict]] = {}
    current_file_revision_by_document: dict[int, dict] = {}
    signatures_by_document: dict[int, list[dict]] = {}
    latest_signature_by_document: dict[int, dict] = {}
    for row in versions:
        doc_id = _safe_int(row.get("document_id"))
        if doc_id:
            by_document_versions.setdefault(doc_id, []).append(row)
    for row in file_revisions:
        doc_id = _safe_int(row.get("document_id"))
        if not doc_id:
            continue
        file_revisions_by_document.setdefault(doc_id, []).append(row)
        if _safe_int(row.get("is_current")) and doc_id not in current_file_revision_by_document:
            current_file_revision_by_document[doc_id] = row
    for row in signatures:
        doc_id = _safe_int(row.get("entity_id"))
        if not doc_id:
            continue
        signatures_by_document.setdefault(doc_id, []).append(row)
        if doc_id not in latest_signature_by_document:
            latest_signature_by_document[doc_id] = row
    for rows in by_document_versions.values():
        rows.sort(key=lambda item: (_safe_int(item.get("version_no")), _safe_int(item.get("created_at"))))
        previous = {}
        for row in rows:
            payload = row.get("payload") or {}
            row["diff_items"] = _payload_diff(payload, previous)
            row["change_count"] = len(row["diff_items"])
            previous = payload
    expiring_certificates = [
        row for row in certificates
        if _safe_text(row.get("valid_to")) and _safe_text(row.get("status")) == "active"
    ][:8]
    document_map = {int(row.get("id") or 0): row for row in documents}
    classifier_map = {int(row.get("id") or 0): row for row in classifiers}
    case_file_map = {int(row.get("id") or 0): row for row in case_files}
    policy_map = {int(row.get("id") or 0): row for row in retention_policies}
    workflow_approval_by_document: dict[int, dict] = {}
    journal_map = {int(row.get("id") or 0): row for row in registration_journals}
    print_forms_by_document: dict[int, list[dict]] = {}
    archive_by_document: dict[int, list[dict]] = {}
    for row in print_forms:
        print_forms_by_document.setdefault(_safe_int(row.get("document_id")), []).append(row)
    for row in archive_rows:
        archive_by_document.setdefault(_safe_int(row.get("document_id")), []).append(row)
    for row in workflow_rows:
        doc_id = _safe_int(row.get("entity_id"))
        if doc_id and doc_id not in workflow_approval_by_document:
            workflow_approval_by_document[doc_id] = row
    for row in classifiers:
        row["required_fields"] = _json_load(row.get("required_fields"), [])
        row["allowed_roles"] = _json_load(row.get("allowed_roles_json"), [])
    for row in case_files:
        row["allowed_roles"] = _json_load(row.get("allowed_roles_json"), [])
    for row in retention_policies:
        row["access_roles"] = _json_load(row.get("access_roles_json"), [])
        row["confidentiality_levels"] = _json_load(row.get("confidentiality_levels_json"), [])
    if actor:
        visible_documents = []
        visible_document_ids = set()
        for row in documents:
            classifier = classifier_map.get(_safe_int(row.get("classifier_id")), {})
            case_file = case_file_map.get(_safe_int(row.get("case_file_id")), {})
            policy = {}
            if _safe_int(case_file.get("retention_policy_id")):
                policy = policy_map.get(_safe_int(case_file.get("retention_policy_id")), {})
            elif _safe_int(classifier.get("retention_policy_id")):
                policy = policy_map.get(_safe_int(classifier.get("retention_policy_id")), {})
            elif _safe_text(row.get("document_kind_code")):
                policy = next((item for item in retention_policies if item.get("is_active") and _safe_text(item.get("scope_type")) == "document_kind" and _safe_text(item.get("scope_value")) == _safe_text(row.get("document_kind_code"))), {})
            elif _safe_text(classifier.get("classifier_code")):
                policy = next((item for item in retention_policies if item.get("is_active") and _safe_text(item.get("scope_type")) == "classifier" and _safe_text(item.get("scope_value")) == _safe_text(classifier.get("classifier_code"))), {})
            elif _safe_text(case_file.get("case_index")):
                policy = next((item for item in retention_policies if item.get("is_active") and _safe_text(item.get("scope_type")) == "case_file" and _safe_text(item.get("scope_value")) == _safe_text(case_file.get("case_index"))), {})
            else:
                policy = next((item for item in retention_policies if item.get("is_active") and _safe_text(item.get("scope_type")) == "doc_type" and _safe_text(item.get("scope_value")) == _normalized_doc_type(row.get("type"))), {})
            if _case_scope_allowed(actor, classifier, case_file, policy):
                visible_documents.append(row)
                visible_document_ids.add(_safe_int(row.get("id")))
        documents = visible_documents
        document_map = {int(row.get("id") or 0): row for row in documents}
        versions = [row for row in versions if _safe_int(row.get("document_id")) in visible_document_ids]
        file_revisions = [row for row in file_revisions if _safe_int(row.get("document_id")) in visible_document_ids]
        linked_tasks = [row for row in linked_tasks if _safe_int(row.get("document_id")) in visible_document_ids]
        signatures = [row for row in signatures if _safe_int(row.get("entity_id")) in visible_document_ids]
        archive_rows = [row for row in archive_rows if _safe_int(row.get("document_id")) in visible_document_ids]
        print_forms = [row for row in print_forms if _safe_int(row.get("document_id")) in visible_document_ids]
        registration_records = [row for row in registration_records if _safe_int(row.get("document_id")) in visible_document_ids]
        lifecycle_events = [row for row in lifecycle_events if _safe_int(row.get("document_id")) in visible_document_ids]
        retention_actions = [row for row in retention_actions if _safe_int(row.get("document_id")) in visible_document_ids]
    by_document_versions = {}
    file_revisions_by_document = {}
    current_file_revision_by_document = {}
    signatures_by_document = {}
    latest_signature_by_document = {}
    for row in versions:
        doc_id = _safe_int(row.get("document_id"))
        if doc_id:
            by_document_versions.setdefault(doc_id, []).append(row)
    for row in file_revisions:
        doc_id = _safe_int(row.get("document_id"))
        if not doc_id:
            continue
        file_revisions_by_document.setdefault(doc_id, []).append(row)
        if _safe_int(row.get("is_current")) and doc_id not in current_file_revision_by_document:
            current_file_revision_by_document[doc_id] = row
    for row in signatures:
        doc_id = _safe_int(row.get("entity_id"))
        if not doc_id:
            continue
        signatures_by_document.setdefault(doc_id, []).append(row)
        if doc_id not in latest_signature_by_document:
            latest_signature_by_document[doc_id] = row
    for rows in by_document_versions.values():
        rows.sort(key=lambda item: (_safe_int(item.get("version_no")), _safe_int(item.get("created_at"))))
        previous = {}
        for row in rows:
            payload = row.get("payload") or {}
            row["diff_items"] = _payload_diff(payload, previous)
            row["change_count"] = len(row["diff_items"])
            previous = payload
    version_coverage = {key: len(value) for key, value in by_document_versions.items()}
    timeline = []
    for row in documents[:30]:
        normalized_type = _normalized_doc_type(row.get("type"))
        document_id = int(row.get("id") or 0)
        timeline.append({
            "kind": "document",
            "title": f"Документ №{_safe_text(row.get('number')) or row.get('id')}",
            "meta": _safe_text(row.get("subject")) or "Без темы",
            "status": _safe_text(row.get("status")) or "registered",
            "document_id": document_id,
            "doc_type": normalized_type,
            "doc_type_label": _doc_type_label(normalized_type),
            "timestamp": int(row.get("id") or 0),
        })
    for row in versions[:30]:
        document_id = _safe_int(row.get("document_id"))
        doc = document_map.get(document_id, {})
        version_label = _safe_text(row.get("version_label")) or f"v{_safe_int(row.get('version_no'))}"
        timeline.append({
            "kind": "version",
            "title": f"Версия {version_label}",
            "meta": f"Документ №{_safe_text(doc.get('number')) or document_id}",
            "status": _safe_text(row.get("version_status")) or "draft",
            "document_id": document_id,
            "change_count": _safe_int(row.get("change_count")),
            "timestamp": _safe_int(row.get("created_at")),
        })
    for row in file_revisions[:30]:
        document_id = _safe_int(row.get("document_id"))
        doc = document_map.get(document_id, {})
        timeline.append({
            "kind": "file_revision",
            "title": _safe_text(row.get("revision_label")) or f"file-v{_safe_int(row.get('revision_no'))}",
            "meta": f"{_safe_text(row.get('original_filename')) or 'Файл'} · {_format_file_size(row.get('file_size'))}",
            "status": _safe_text(row.get("revision_status")) or ("active" if _safe_int(row.get("is_current")) else "archived"),
            "document_id": document_id,
            "is_current": _safe_int(row.get("is_current")),
            "timestamp": _safe_int(row.get("uploaded_at")),
        })
    for row in signatures[:30]:
        document_id = _safe_int(row.get("entity_id"))
        timeline.append({
            "kind": "signature",
            "title": _safe_text(row.get("signature_kind")) or "ЭП",
            "meta": f"Документ №{_safe_text(row.get('document_number')) or document_id} · {_safe_text(row.get('signer_name')) or 'Подписант'}",
            "status": _safe_text(row.get("verification_status")) or _safe_text(row.get("signature_status")) or "pending",
            "document_id": document_id,
            "timestamp": _safe_int(row.get("created_at")),
        })
    for row in retention_actions[:20]:
        document_id = _safe_int(row.get("document_id"))
        doc = document_map.get(document_id, {})
        timeline.append({
            "kind": "retention_action",
            "title": _safe_text(row.get("action_name")) or "retention",
            "meta": f"Документ №{_safe_text(doc.get('number')) or document_id} · {_safe_text(row.get('basis_text')) or 'без основания'}",
            "status": _safe_text(row.get("new_status")) or "review",
            "document_id": document_id,
            "timestamp": _safe_int(row.get("created_at")),
        })
    for row in linked_tasks[:30]:
        document_id = _safe_int(row.get("document_id"))
        doc = document_map.get(document_id, {})
        timeline.append({
            "kind": "task",
            "title": _safe_text(row.get("title")) or "Связанное поручение",
            "meta": f"Документ №{_safe_text(doc.get('number')) or document_id}",
            "status": _safe_text(row.get("status")) or "active",
            "document_id": document_id,
            "timestamp": _safe_int(row.get("updated_at") or row.get("created_at")),
        })
    for row in print_forms[:20]:
        document_id = _safe_int(row.get("document_id"))
        timeline.append({
            "kind": "print_form",
            "title": _safe_text(row.get("form_name")) or f"Печатная форма {(_safe_text(row.get('format_type')) or 'pdf').upper()}",
            "meta": f"Документ №{_safe_text(row.get('document_number')) or document_id}",
            "status": _safe_text(row.get("status")) or "generated",
            "document_id": document_id,
            "timestamp": _safe_int(row.get("updated_at") or row.get("created_at")),
        })
    for row in archive_rows[:20]:
        document_id = _safe_int(row.get("document_id"))
        timeline.append({
            "kind": "archive",
            "title": _safe_text(row.get("archive_code")) or "Архивная запись",
            "meta": f"Документ №{_safe_text(row.get('document_number')) or document_id}",
            "status": _safe_text(row.get("archive_status")) or "archived",
            "document_id": document_id,
            "timestamp": _safe_int(row.get("updated_at") or row.get("created_at")),
        })
    for row in lifecycle_events[:30]:
        document_id = _safe_int(row.get("document_id"))
        timeline.append({
            "kind": "lifecycle",
            "title": _safe_text(row.get("action_name")) or "Смена стадии",
            "meta": f"{_safe_text(row.get('from_state')) or 'start'} → {_safe_text(row.get('to_state')) or 'draft'}",
            "status": _safe_text(row.get("to_state")) or "draft",
            "document_id": document_id,
            "timestamp": _safe_int(row.get("created_at")),
        })
    for row in get_audit_logs(limit=80):
        if _safe_text(row.get("entity_type")) not in {"document", "document_template", "document_version", "document_print_form", "edo_certificate"}:
            continue
        details = row.get("details") or {}
        title = _safe_text(details.get("subject")) or _safe_text(details.get("title")) or _safe_text(details.get("owner_email")) or _safe_text(row.get("entity_type"))
        timeline.append({
            "kind": "audit",
            "title": _safe_text(row.get("action")) or "document_event",
            "meta": title,
            "status": "logged",
            "document_id": _safe_int(row.get("entity_id")),
            "timestamp": _safe_int(row.get("created_at")),
        })
    timeline.sort(key=lambda item: (int(item.get("timestamp") or 0), int(item.get("document_id") or 0)), reverse=True)
    type_breakdown = {}
    strict_type_breakdown = {}
    template_catalog = []
    template_families = []
    templates_by_type: dict[str, list[dict]] = {}
    families: dict[tuple[str, str], list[dict]] = {}
    for row in documents:
        key = _normalized_doc_type(row.get("type"))
        type_breakdown[key] = type_breakdown.get(key, 0) + 1
        strict_type_breakdown[_doc_type_label(key)] = strict_type_breakdown.get(_doc_type_label(key), 0) + 1
    for row in templates:
        templates_by_type.setdefault(row.get("normalized_doc_type") or "unknown", []).append(row)
        family_key = _template_family_key(row.get("title"))
        families.setdefault((row.get("normalized_doc_type") or "unknown", family_key), []).append(row)
    for doc_type, rows in sorted(templates_by_type.items()):
        status_counts: dict[str, int] = {}
        for row in rows:
            status_counts[row.get("status") or "draft"] = status_counts.get(row.get("status") or "draft", 0) + 1
        documents_total = type_breakdown.get(doc_type, 0)
        template_catalog.append(
            {
                "doc_type": doc_type,
                "doc_type_label": _doc_type_label(doc_type),
                "templates_total": len(rows),
                "active_total": len([row for row in rows if row.get("status") == "active"]),
                "latest_version": max((_safe_text(row.get("version_label")) for row in rows), default="v1"),
                "status_breakdown": status_counts,
                "documents_total": documents_total,
                "coverage_percent": round((len(rows) / documents_total) * 100, 1) if documents_total else 0,
            }
        )
    for (doc_type, family_key), rows in sorted(families.items()):
        rows.sort(key=lambda item: (_safe_text(item.get("version_label")), _safe_int(item.get("updated_at")), _safe_int(item.get("id"))), reverse=True)
        template_families.append(
            {
                "doc_type": doc_type,
                "doc_type_label": _doc_type_label(doc_type),
                "family_key": family_key,
                "title": rows[0].get("title", ""),
                "versions_total": len(rows),
                "latest_version": _safe_text(rows[0].get("version_label")) or "v1",
                "active_total": len([row for row in rows if row.get("status") == "active"]),
                "statuses": sorted({row.get("status") or "draft" for row in rows}),
            }
        )
    now_ts = _now_ts()
    coverage_gaps = []
    doc_typing_issues = []
    legal_card_board = []
    legal_card_gaps = []
    file_revision_board = []
    file_revision_gaps = []
    signature_board = []
    signature_gaps = []
    retention_policy_board = []
    retention_policy_gaps = []
    for row in documents:
        document_id = _safe_int(row.get("id"))
        normalized_type = _normalized_doc_type(row.get("type"))
        lifecycle_state = row.get("lifecycle_state") or row.get("status") or "draft"
        classifier = classifier_map.get(_safe_int(row.get("classifier_id")), {})
        case_file = case_file_map.get(_safe_int(row.get("case_file_id")), {})
        retention_policy = {}
        if _safe_int(case_file.get("retention_policy_id")):
            retention_policy = policy_map.get(_safe_int(case_file.get("retention_policy_id")), {})
        elif _safe_int(classifier.get("retention_policy_id")):
            retention_policy = policy_map.get(_safe_int(classifier.get("retention_policy_id")), {})
        elif _safe_text(row.get("document_kind_code")):
            retention_policy = next((item for item in retention_policies if item.get("is_active") and _safe_text(item.get("scope_type")) == "document_kind" and _safe_text(item.get("scope_value")) == _safe_text(row.get("document_kind_code"))), {})
        elif _safe_text(classifier.get("classifier_code")):
            retention_policy = next((item for item in retention_policies if item.get("is_active") and _safe_text(item.get("scope_type")) == "classifier" and _safe_text(item.get("scope_value")) == _safe_text(classifier.get("classifier_code"))), {})
        elif _safe_text(case_file.get("case_index")):
            retention_policy = next((item for item in retention_policies if item.get("is_active") and _safe_text(item.get("scope_type")) == "case_file" and _safe_text(item.get("scope_value")) == _safe_text(case_file.get("case_index"))), {})
        elif _safe_text(row.get("type")):
            retention_policy = next((item for item in retention_policies if item.get("is_active") and _safe_text(item.get("scope_type")) == "doc_type" and _safe_text(item.get("scope_value")) == normalized_type), {})
        missing = []
        if not version_coverage.get(document_id):
            missing.append("version")
        if not print_forms_by_document.get(document_id):
            missing.append("print_form")
        if normalized_type in {"outgoing", "internal"} and not archive_by_document.get(document_id) and _safe_text(row.get("status")) == "archived":
            missing.append("legal_archive")
        if normalized_type == "unknown" or not _safe_text(row.get("type")):
            doc_typing_issues.append(
                {
                    "document_id": document_id,
                    "number": row.get("number", ""),
                    "subject": row.get("subject", ""),
                    "raw_type": _safe_text(row.get("type")) or "empty",
                    "suggested_type": "internal" if _safe_text(row.get("correspondent")).lower().startswith("отдел") else "incoming",
                    "status": row.get("status", ""),
                }
            )
        if missing:
            coverage_gaps.append(
                {
                    "document_id": document_id,
                    "number": row.get("number", ""),
                    "subject": row.get("subject", ""),
                    "doc_type": normalized_type,
                    "doc_type_label": _doc_type_label(normalized_type),
                    "status": row.get("status", ""),
                    "missing": missing,
                }
            )
        required_fields = set(_json_load(classifier.get("required_fields"), [])) if classifier else set()
        if not required_fields:
            required_fields = {"registration_number", "classifier_id", "case_file_id", "retention_until", "legal_significance"}
        legal_field_values = {
            "registration_number": row.get("registration_number"),
            "classifier_id": row.get("classifier_id"),
            "case_file_id": row.get("case_file_id"),
            "retention_until": row.get("retention_until"),
            "legal_significance": row.get("legal_significance"),
            "confidentiality_level": row.get("confidentiality_level"),
            "file_url": row.get("file_url"),
        }
        missing_legal = [field for field in sorted(required_fields) if not legal_field_values.get(field)]
        legal_card_item = {
            "document_id": document_id,
            "number": row.get("number", ""),
            "registration_number": row.get("registration_number", ""),
            "subject": row.get("subject", ""),
            "doc_type": normalized_type,
            "lifecycle_state": row.get("lifecycle_state") or row.get("status") or "draft",
            "legal_significance": row.get("legal_significance", ""),
            "confidentiality_level": row.get("confidentiality_level", ""),
            "retention_until": row.get("retention_until", ""),
            "classifier_name": classifier.get("name", ""),
            "case_index": row.get("case_index") or case_file_map.get(_safe_int(row.get("case_file_id")), {}).get("case_index", ""),
            "journal_name": journal_map.get(_safe_int(row.get("registration_journal_id")), {}).get("journal_name", ""),
            "quality_status": "complete" if not missing_legal else "incomplete",
            "missing_legal": missing_legal,
        }
        legal_card_board.append(legal_card_item)
        if missing_legal:
            legal_card_gaps.append(legal_card_item)
        current_file_revision = current_file_revision_by_document.get(document_id, {})
        file_revision_history = file_revisions_by_document.get(document_id, [])
        document_signatures = signatures_by_document.get(document_id, [])
        latest_signature = latest_signature_by_document.get(document_id, {})
        valid_signatures = [item for item in document_signatures if _safe_text(item.get("verification_status")) == "valid"]
        valid_current_signatures = [
            item for item in valid_signatures
            if current_file_revision
            and _safe_int(item.get("document_revision_id")) == _safe_int(current_file_revision.get("id"))
            and _safe_text(item.get("signed_hash")) == _safe_text(current_file_revision.get("checksum"))
        ]
        stale_signature_count = len(valid_signatures) - len(valid_current_signatures)
        revoked_signature_count = len([
            item for item in document_signatures
            if _safe_text(item.get("verification_status")) in {"revoked", "signature_revoked"} or _safe_int(item.get("revoked_at"))
        ])
        file_revision_item = {
            "document_id": document_id,
            "number": row.get("number", ""),
            "subject": row.get("subject", ""),
            "file_url": row.get("file_url", ""),
            "revisions_total": len(file_revision_history),
            "active_revision_label": current_file_revision.get("revision_label", ""),
            "active_filename": current_file_revision.get("original_filename", ""),
            "mime_type": current_file_revision.get("mime_type", ""),
            "size_label": current_file_revision.get("size_label", ""),
            "revision_status": current_file_revision.get("revision_status", ""),
            "is_current": _safe_int(current_file_revision.get("is_current")),
            "checksum_short": (_safe_text(current_file_revision.get("checksum"))[:12] if current_file_revision else ""),
            "history_gap_reason": "",
        }
        if file_revision_history or _safe_text(row.get("file_url")):
            if not file_revision_history:
                file_revision_item["history_gap_reason"] = "файл есть, но нет истории ревизий"
                file_revision_gaps.append(file_revision_item)
            elif not current_file_revision:
                file_revision_item["history_gap_reason"] = "нет активной версии файла"
                file_revision_gaps.append(file_revision_item)
            file_revision_board.append(file_revision_item)
        signature_item = {
            "document_id": document_id,
            "number": row.get("number", ""),
            "subject": row.get("subject", ""),
            "lifecycle_state": lifecycle_state,
            "signatures_total": len(document_signatures),
            "valid_signatures_total": len(valid_signatures),
            "current_revision_valid_signatures_total": len(valid_current_signatures),
            "stale_signatures_total": stale_signature_count,
            "revoked_signatures_total": revoked_signature_count,
            "signature_display_status": "подпись действительна" if valid_current_signatures else ("сертификат отозван" if revoked_signature_count else ("подпись не покрывает текущую версию файла" if stale_signature_count else "нет действительной подписи")),
            "signature_kind": latest_signature.get("signature_kind", ""),
            "signer_name": latest_signature.get("signer_name", ""),
            "verification_status": latest_signature.get("verification_status", ""),
            "legal_force": latest_signature.get("legal_force", ""),
            "thumbprint_short": _safe_text(latest_signature.get("certificate_thumbprint"))[:12],
            "archive_total": len(archive_by_document.get(document_id, [])),
            "gap_reason": "",
        }
        if document_signatures or lifecycle_state in {"signed", "archived", "approved"}:
            if not current_file_revision:
                signature_item["gap_reason"] = "нет активной ревизии файла для подписи"
            elif not valid_current_signatures:
                if stale_signature_count:
                    signature_item["gap_reason"] = "подпись не покрывает текущую версию файла"
                elif revoked_signature_count:
                    signature_item["gap_reason"] = "сертификат отозван"
                else:
                    signature_item["gap_reason"] = "нет валидной ЭП/КЭП"
            elif lifecycle_state == "archived" and not archive_by_document.get(document_id):
                signature_item["gap_reason"] = "архивная запись не оформлена"
            signature_board.append(signature_item)
            if signature_item["gap_reason"]:
                signature_gaps.append(signature_item)
        retention_until = _safe_text(row.get("retention_until")) or (_safe_text(archive_by_document.get(document_id, [{}])[0].get("retention_until")) if archive_by_document.get(document_id) else "")
        retention_ts = _parse_ddmmyyyy_ts(retention_until)
        review_before_days = _safe_int(retention_policy.get("review_before_days") or 90)
        days_left = round((retention_ts - now_ts) / 86400) if retention_ts else None
        retention_status = "not_configured"
        if retention_until:
            retention_status = "expired" if days_left is not None and days_left < 0 else ("review_due" if days_left is not None and days_left <= review_before_days else "active")
        retention_item = {
            "document_id": document_id,
            "number": row.get("number", ""),
            "subject": row.get("subject", ""),
            "policy_name": retention_policy.get("policy_name", ""),
            "scope_type": retention_policy.get("scope_type", ""),
            "retention_until": retention_until,
            "days_left": days_left,
            "review_before_days": review_before_days,
            "archive_status": archive_by_document.get(document_id, [{}])[0].get("archive_status", "") if archive_by_document.get(document_id) else "",
            "allowed_roles": _unique_texts(case_file.get("allowed_roles", []) or retention_policy.get("access_roles", []) or classifier.get("allowed_roles", [])),
            "status": retention_status,
            "gap_reason": "",
        }
        if not retention_policy:
            retention_item["gap_reason"] = "не назначена policy хранения"
        elif not retention_until:
            retention_item["gap_reason"] = "не задан срок хранения"
        elif days_left is not None and days_left <= review_before_days and not archive_by_document.get(document_id):
            retention_item["gap_reason"] = "нужен архивный review или перемещение"
        retention_policy_board.append(retention_item)
        if retention_item["gap_reason"]:
            retention_policy_gaps.append(retention_item)
    print_coverage = []
    print_format_matrix = []
    for doc_type, total in sorted(type_breakdown.items()):
        doc_ids = [int(row.get("id")) for row in documents if _normalized_doc_type(row.get("type")) == doc_type]
        with_print = len([doc_id for doc_id in doc_ids if print_forms_by_document.get(doc_id)])
        format_rows = [row for row in print_forms if _normalized_doc_type(document_map.get(_safe_int(row.get("document_id")), {}).get("type")) == doc_type]
        print_coverage.append(
            {
                "doc_type": doc_type,
                "doc_type_label": _doc_type_label(doc_type),
                "documents_total": total,
                "with_print_forms": with_print,
                "coverage_percent": round((with_print / total) * 100, 1) if total else 0,
            }
        )
        print_format_matrix.append(
            {
                "doc_type": doc_type,
                "doc_type_label": _doc_type_label(doc_type),
                "pdf_total": len([row for row in format_rows if _safe_text(row.get("format_type")).lower() == "pdf"]),
                "docx_total": len([row for row in format_rows if _safe_text(row.get("format_type")).lower() == "docx"]),
                "missing_print_forms": max(total - with_print, 0),
            }
        )
    legal_archive_board = []
    archive_risks = []
    workflow_board = []
    workflow_gaps = []
    now_ts = _now_ts()
    for row in archive_rows:
        retention_ts = _parse_ddmmyyyy_ts(row.get("retention_until"))
        legal_archive_board.append(
            {
                "document_id": _safe_int(row.get("document_id")),
                "archive_code": row.get("archive_code", ""),
                "document_number": row.get("document_number", ""),
                "document_subject": row.get("document_subject", ""),
                "retention_until": row.get("retention_until", ""),
                "archive_status": row.get("archive_status", "archived"),
                "storage_path": row.get("storage_path", ""),
                "retention_days_left": round((retention_ts - now_ts) / 86400) if retention_ts else None,
            }
        )
        if retention_ts and retention_ts <= now_ts + 90 * 86400:
            archive_risks.append(
                {
                    "document_id": _safe_int(row.get("document_id")),
                    "archive_code": row.get("archive_code", ""),
                    "document_number": row.get("document_number", ""),
                    "document_subject": row.get("document_subject", ""),
                    "retention_until": row.get("retention_until", ""),
                    "days_left": round((retention_ts - now_ts) / 86400),
                }
            )
    for row in documents:
        document_id = _safe_int(row.get("id"))
        if not _safe_int(row.get("workflow_started_at")):
            continue
        approval_row = workflow_approval_by_document.get(document_id, {})
        task_row = next((item for item in linked_tasks if _safe_int(item.get("document_id")) == document_id), {})
        archive_row = archive_by_document.get(document_id, [{}])[0] if archive_by_document.get(document_id) else {}
        workflow_item = {
            "document_id": document_id,
            "number": row.get("number", ""),
            "subject": row.get("subject", ""),
            "workflow_stage": _safe_text(row.get("workflow_stage")),
            "workflow_status": _safe_text(row.get("workflow_status")),
            "block_reason": _safe_text(row.get("workflow_block_reason")),
            "progress_percent": _workflow_progress(row.get("workflow_stage"), row.get("workflow_status")),
            "task_status": task_row.get("status", ""),
            "approval_status": approval_row.get("status", ""),
            "archive_status": archive_row.get("archive_status", ""),
        }
        workflow_board.append(workflow_item)
        if workflow_item["workflow_status"] == "blocked":
            workflow_gaps.append(workflow_item)
    return {
        "documents": documents,
        "templates": templates,
        "ocr_jobs": ocr_jobs,
        "template_flows": template_flows,
        "versions": versions,
        "file_revisions": file_revisions,
        "template_catalog": template_catalog,
        "template_families": template_families,
        "linked_tasks": linked_tasks,
        "signatures": signatures,
        "certificates": certificates,
        "archive": archive_rows,
        "legal_archive_board": legal_archive_board,
        "archive_risks": archive_risks[:20],
        "print_forms": print_forms,
        "registration_journals": registration_journals,
        "registration_records": registration_records,
        "classifiers": classifiers,
        "case_files": case_files,
        "retention_policies": retention_policies,
        "retention_actions": retention_actions,
        "lifecycle_events": lifecycle_events,
        "legal_card_board": legal_card_board[:80],
        "legal_card_gaps": legal_card_gaps[:40],
        "file_revision_board": file_revision_board[:80],
        "file_revision_gaps": file_revision_gaps[:40],
        "signature_board": signature_board[:80],
        "signature_gaps": signature_gaps[:40],
        "workflow_board": workflow_board[:80],
        "workflow_gaps": workflow_gaps[:40],
        "retention_policy_board": retention_policy_board[:80],
        "retention_policy_gaps": retention_policy_gaps[:40],
        "print_coverage": print_coverage,
        "print_format_matrix": print_format_matrix,
        "coverage_gaps": coverage_gaps[:40],
        "doc_typing_issues": doc_typing_issues[:30],
        "timeline": timeline[:40],
        "type_breakdown": type_breakdown,
        "strict_type_breakdown": strict_type_breakdown,
        "metrics": {
            "documents_total": len(documents),
            "templates_total": len(templates),
            "ocr_jobs_total": len(ocr_jobs),
            "ocr_jobs_processed": len([row for row in ocr_jobs if row.get("status") in {"processed", "applied"}]),
            "template_flows_total": len(template_flows),
            "versions_total": len(versions),
            "file_revisions_total": len(file_revisions),
            "linked_tasks_open": len([row for row in linked_tasks if row.get("status") in {"new", "active", "in_work"}]),
            "signatures_total": len(signatures),
            "documents_with_valid_signatures": len([doc_id for doc_id, rows in signatures_by_document.items() if any(_safe_text(item.get("verification_status")) == "valid" for item in rows)]),
            "archive_total": len(archive_rows),
            "print_forms_total": len(print_forms),
            "certificates_active": len([row for row in certificates if row.get("status") == "active"]),
            "certificates_expiring": len(expiring_certificates),
            "signature_gaps": len(signature_gaps),
            "coverage_gaps": len(coverage_gaps),
            "doc_types_strict": len(strict_type_breakdown),
            "typing_issues": len(doc_typing_issues),
            "archive_risks": len(archive_risks),
            "template_families": len(template_families),
            "registration_journals_total": len(registration_journals),
            "registered_documents": len([row for row in documents if _safe_text(row.get("registration_number"))]),
            "classifiers_total": len(classifiers),
            "case_files_total": len(case_files),
            "retention_policies_total": len(retention_policies),
            "retention_actions_total": len(retention_actions),
            "workflow_started_total": len(workflow_board),
            "workflow_gaps_total": len(workflow_gaps),
            "legal_card_gaps": len(legal_card_gaps),
            "lifecycle_events": len(lifecycle_events),
            "documents_with_file_history": len(file_revisions_by_document),
            "documents_without_file_history": len(file_revision_gaps),
            "retention_policy_gaps": len(retention_policy_gaps),
        },
    }


@router.get("/api/docflow/plus_summary")
def get_docflow_plus_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    return _load_docflow_summary(actor)


@router.get("/api/docflow/deep_summary")
def get_docflow_deep_summary(request: Request):
    return get_docflow_plus_summary(request)


@router.get("/api/docflow/documents/{document_id}/timeline")
def get_document_timeline(document_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    summary = _load_docflow_summary()
    return {"document_id": _safe_int(document_id), "timeline": _document_timeline_for(document_id, summary)}


@router.get("/api/docflow/versions/{record_id}/diff")
def get_document_version_diff(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        current = dict(conn.execute("SELECT * FROM document_versions WHERE id=?", (_safe_int(record_id),)).fetchone() or {})
        if not current:
            return {"error": "version_not_found"}
        current["payload"] = _json_load(current.get("payload"), {})
        previous = conn.execute(
            """
            SELECT *
            FROM document_versions
            WHERE document_id=? AND version_no < ?
            ORDER BY version_no DESC, id DESC
            LIMIT 1
            """,
            (_safe_int(current.get("document_id")), _safe_int(current.get("version_no"))),
        ).fetchone()
        previous_payload = _json_load(dict(previous or {}).get("payload"), {}) if previous else {}
        diff_items = _payload_diff(current.get("payload"), previous_payload)
    finally:
        conn.close()
    return {
        "document_id": _safe_int(current.get("document_id")),
        "version_id": _safe_int(record_id),
        "version_label": current.get("version_label") or f"v{_safe_int(current.get('version_no'))}",
        "previous_version_id": _safe_int(dict(previous or {}).get("id")) if previous else 0,
        "diff_items": diff_items,
        "change_count": len(diff_items),
    }


@router.post("/api/docflow/templates")
def create_document_template(data: DocumentTemplateData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_template", "update", data.status)
    if gate:
        return gate
    now = _now_ts()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_templates (
                title, doc_type, template_kind, version_label, body_text, variables_json,
                status, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.title,
                data.doc_type,
                data.template_kind,
                data.version_label,
                data.body_text,
                json.dumps(data.variables or [], ensure_ascii=False),
                data.status,
                data.comment,
                actor.get("email", ""),
                now,
                now,
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("document_template_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_template", entity_id=str(record_id), details={"title": data.title, "doc_type": data.doc_type})
    return {"status": "success", "id": record_id}


@router.post("/api/documents/templates/deep")
def create_document_template_deep(data: DocumentTemplateData, request: Request):
    return create_document_template(data, request)


@router.get("/api/docflow/ocr_jobs")
def get_docflow_ocr_jobs(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        rows = _row_dicts(conn.execute("SELECT * FROM document_ocr_jobs ORDER BY updated_at DESC, id DESC LIMIT 200"))
    finally:
        conn.close()
    for row in rows:
        row["extracted_fields"] = _json_load(row.get("extracted_fields_json"), {})
    return rows


@router.post("/api/docflow/ocr_jobs")
def create_docflow_ocr_job(data: DocumentOCRJobData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    now = _now_ts()
    conn = get_connection(row_factory=True)
    try:
        document = _doc_row(conn, data.document_id) if data.document_id else {}
        processed = _process_ocr_payload(data, document)
        status = "processed"
        if data.auto_apply and document:
            fields = processed["fields"]
            conn.execute(
                """
                UPDATE documents
                SET type=COALESCE(NULLIF(?, ''), type), number=COALESCE(NULLIF(?, ''), number),
                    d_date=COALESCE(NULLIF(?, ''), d_date), correspondent=COALESCE(NULLIF(?, ''), correspondent),
                    subject=COALESCE(NULLIF(?, ''), subject)
                WHERE id=?
                """,
                (
                    fields.get("doc_type", ""),
                    fields.get("number", ""),
                    fields.get("d_date", ""),
                    fields.get("correspondent", ""),
                    fields.get("subject", ""),
                    _safe_int(data.document_id),
                ),
            )
            status = "applied"
        job_id = next_safe_table_id(conn, "document_ocr_jobs")
        conn.execute(
            """
            INSERT INTO document_ocr_jobs (
                id, document_id, file_revision_id, source_file, input_text, recognized_text, confidence,
                language, status, extracted_fields_json, template_id, created_by, created_at, updated_at, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                _safe_int(data.document_id),
                _safe_int(data.file_revision_id),
                data.source_file or "",
                data.input_text or "",
                processed["recognized_text"],
                processed["confidence"],
                data.language or "rus",
                status,
                json.dumps(processed["fields"], ensure_ascii=False),
                _safe_int(data.template_id),
                actor.get("email", ""),
                now,
                now,
                now,
            ),
        )
        if _safe_int(data.file_revision_id):
            upsert_index_from_text(conn, _safe_int(data.document_id), _safe_int(data.file_revision_id), processed["recognized_text"], processed["confidence"], source_type="ocr")
        conn.commit()
    finally:
        conn.close()
    audit_log("document_ocr_processed", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_ocr_job", entity_id=str(job_id), details={"document_id": data.document_id, "status": status})
    return {"status": "success", "id": job_id, "ocr_status": status, **processed}


@router.post("/api/docflow/ocr_jobs/{job_id}/process")
def process_docflow_ocr_job(job_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        row = dict(conn.execute("SELECT * FROM document_ocr_jobs WHERE id=?", (_safe_int(job_id),)).fetchone() or {})
        if not row:
            return {"error": "not_found"}
        data = DocumentOCRJobData(document_id=_safe_int(row.get("document_id")), file_revision_id=_safe_int(row.get("file_revision_id")), source_file=row.get("source_file") or "", input_text=row.get("input_text") or row.get("recognized_text") or "", language=row.get("language") or "rus", template_id=_safe_int(row.get("template_id")))
        processed = _process_ocr_payload(data, _doc_row(conn, data.document_id))
        conn.execute(
            "UPDATE document_ocr_jobs SET recognized_text=?, confidence=?, status='processed', extracted_fields_json=?, updated_at=?, processed_at=? WHERE id=?",
            (processed["recognized_text"], processed["confidence"], json.dumps(processed["fields"], ensure_ascii=False), _now_ts(), _now_ts(), _safe_int(job_id)),
        )
        if _safe_int(data.file_revision_id):
            upsert_index_from_text(conn, _safe_int(data.document_id), _safe_int(data.file_revision_id), processed["recognized_text"], processed["confidence"], source_type="ocr")
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "id": _safe_int(job_id), **processed}


@router.get("/api/docflow/template_flows")
def get_docflow_template_flows(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        rows = [_template_flow_payload(row) for row in _row_dicts(conn.execute("SELECT * FROM document_template_flows ORDER BY updated_at DESC, id DESC"))]
    finally:
        conn.close()
    return {"items": rows}


@router.post("/api/docflow/template_flows")
def create_docflow_template_flow(data: DocumentTemplateFlowData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    now = _now_ts()
    flow_id = 0
    conn = get_connection()
    try:
        flow_id = next_safe_table_id(conn, "document_template_flows")
        flow_code = _safe_text(data.flow_code) or f"FLOW-{flow_id}"
        conn.execute(
            """
            INSERT INTO document_template_flows (
                id, flow_code, flow_name, direction, doc_type, trigger_rules_json,
                template_ids_json, required_fields_json, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                flow_id,
                flow_code,
                data.flow_name or flow_code,
                data.direction or "incoming",
                data.doc_type or data.direction or "incoming",
                json.dumps(data.trigger_rules or {}, ensure_ascii=False),
                json.dumps(data.template_ids or [], ensure_ascii=False),
                json.dumps(data.required_fields or [], ensure_ascii=False),
                data.status or "active",
                actor.get("email", ""),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("document_template_flow_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_template_flow", entity_id=str(flow_id), details={"flow_code": data.flow_code})
    return {"status": "success", "id": flow_id}


@router.post("/api/docflow/template_flows/{flow_id}/apply")
def apply_docflow_template_flow(flow_id: int, data: DocumentTemplateFlowApplyData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        flow = _template_flow_payload(dict(conn.execute("SELECT * FROM document_template_flows WHERE id=?", (_safe_int(flow_id),)).fetchone() or {}))
        if not flow:
            return {"error": "flow_not_found"}
        doc = _doc_row(conn, data.document_id)
        if not doc:
            return {"error": "document_not_found"}
        ocr_job = dict(conn.execute("SELECT * FROM document_ocr_jobs WHERE id=?", (_safe_int(data.ocr_job_id),)).fetchone() or {}) if data.ocr_job_id else {}
        extracted = _json_load(ocr_job.get("extracted_fields_json"), {})
        missing = [field for field in (flow.get("required_fields") or []) if not _safe_text(extracted.get(field) or doc.get(field))]
        template_ids = [_safe_int(item) for item in flow.get("template_ids") or [] if _safe_int(item)]
        current_version = conn.execute("SELECT COALESCE(MAX(version_no), 0) AS version_no FROM document_versions WHERE document_id=?", (_safe_int(data.document_id),)).fetchone()
        version_no = _safe_int(dict(current_version or {}).get("version_no")) + 1
        version_payload = {
            "document_id": _safe_int(data.document_id),
            "flow_id": _safe_int(flow_id),
            "flow_code": flow.get("flow_code", ""),
            "flow_name": flow.get("flow_name", ""),
            "direction": flow.get("direction", ""),
            "doc_type": flow.get("doc_type", ""),
            "template_ids": template_ids,
            "required_fields": flow.get("required_fields") or [],
            "missing_fields": missing,
            "ocr_job_id": _safe_int(data.ocr_job_id),
            "extracted_fields": extracted,
            "document_snapshot": {
                "type": doc.get("type", ""),
                "number": doc.get("number", ""),
                "d_date": doc.get("d_date", ""),
                "correspondent": doc.get("correspondent", ""),
                "subject": doc.get("subject", ""),
                "status": doc.get("status", ""),
            },
        }
        version_cursor = conn.execute(
            """
            INSERT INTO document_versions (
                document_id, version_no, version_label, version_status, payload, file_url, comment, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _safe_int(data.document_id),
                version_no,
                f"flow-{flow.get('flow_code') or flow_id}-v{version_no}",
                "blocked" if missing else "generated",
                json.dumps(version_payload, ensure_ascii=False),
                doc.get("file_url", ""),
                data.comment or f"Применен шаблонный поток {flow.get('flow_code') or flow_id}",
                actor.get("email", ""),
                _now_ts(),
            ),
        )
        version_id = _safe_int(version_cursor.lastrowid)
        created_forms = []
        for template_id in template_ids:
            cursor = conn.execute(
                """
                INSERT INTO document_print_forms (
                    document_id, template_id, format_type, form_name, file_url, status,
                    generated_at, comment, created_by, created_at, updated_at
                ) VALUES (?, ?, 'docx', ?, '', ?, ?, ?, ?, ?, ?)
                """,
                (
                    _safe_int(data.document_id),
                    template_id,
                    f"{flow.get('flow_name') or 'Template flow'} #{data.document_id}",
                    "blocked" if missing else "generated",
                    _today_display(),
                    data.comment or f"Шаблонный поток {flow.get('flow_code')}",
                    actor.get("email", ""),
                    _now_ts(),
                    _now_ts(),
                ),
            )
            created_forms.append(_safe_int(cursor.lastrowid))
        if ocr_job:
            conn.execute("UPDATE document_ocr_jobs SET status='applied', updated_at=? WHERE id=?", (_now_ts(), _safe_int(data.ocr_job_id)))
        conn.commit()
    finally:
        conn.close()
    audit_log("document_template_flow_applied", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_template_flow", entity_id=str(flow_id), details={"document_id": data.document_id, "version_id": version_id, "missing_fields": missing})
    return {"status": "success", "id": _safe_int(flow_id), "version_id": version_id, "created_print_forms": created_forms, "missing_fields": missing}


@router.delete("/api/docflow/templates/{record_id}")
def delete_document_template(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "delete"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_template", "delete")
    if gate:
        return gate
    conn = get_connection()
    try:
        conn.execute("DELETE FROM document_templates WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("document_template_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_template", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.post("/api/docflow/versions")
def create_document_version(data: DocumentVersionRecordData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_version", "update", data.version_status)
    if gate:
        return gate
    conn = get_connection(row_factory=True)
    try:
        doc = _doc_row(conn, data.document_id)
        if not doc:
            return {"error": "document_not_found"}
        current_version = conn.execute("SELECT COALESCE(MAX(version_no), 0) AS version_no FROM document_versions WHERE document_id=?", (_safe_int(data.document_id),)).fetchone()
        version_no = _safe_int(dict(current_version or {}).get("version_no")) + 1
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_versions (
                document_id, version_no, version_label, version_status, payload, file_url, comment, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _safe_int(data.document_id),
                version_no,
                data.version_label or f"v{version_no}",
                data.version_status,
                json.dumps(data.payload or {}, ensure_ascii=False),
                data.file_url,
                data.comment,
                actor.get("email", ""),
                _now_ts(),
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("document_version_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_version", entity_id=str(record_id), details={"document_id": data.document_id, "version_no": version_no})
    return {"status": "success", "id": record_id, "version_no": version_no}


@router.post("/api/docflow/documents/{document_id}/snapshot")
def snapshot_document_version(document_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_version", "update", "snapshot")
    if gate:
        return gate
    conn = get_connection(row_factory=True)
    try:
        doc = _doc_row(conn, document_id)
        if not doc:
            return {"error": "document_not_found"}
        current_version = conn.execute("SELECT COALESCE(MAX(version_no), 0) AS version_no FROM document_versions WHERE document_id=?", (_safe_int(document_id),)).fetchone()
        version_no = _safe_int(dict(current_version or {}).get("version_no")) + 1
        payload = {
            "id": doc.get("id"),
            "type": doc.get("type"),
            "number": doc.get("number"),
            "d_date": doc.get("d_date"),
            "correspondent": doc.get("correspondent"),
            "subject": doc.get("subject"),
            "status": doc.get("status"),
            "project_id": doc.get("project_id"),
            "contract_id": doc.get("contract_id"),
            "object_id": doc.get("object_id"),
            "resolution": doc.get("resolution"),
            "resolution_assignee": doc.get("resolution_assignee"),
        }
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_versions (
                document_id, version_no, version_label, version_status, payload, file_url, comment, created_by, created_at
            ) VALUES (?, ?, ?, 'snapshot', ?, ?, ?, ?, ?)
            """,
            (
                _safe_int(document_id),
                version_no,
                f"snapshot-{version_no}",
                json.dumps(payload, ensure_ascii=False),
                doc.get("file_url", ""),
                "Автоснимок карточки документа",
                actor.get("email", ""),
                _now_ts(),
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("document_snapshot_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document", entity_id=str(document_id), details={"version_id": record_id, "version_no": version_no})
    return {"status": "success", "id": record_id, "version_no": version_no}


@router.delete("/api/docflow/versions/{record_id}")
def delete_document_version(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "delete"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_version", "delete")
    if gate:
        return gate
    conn = get_connection()
    try:
        conn.execute("DELETE FROM document_versions WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("document_version_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_version", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.post("/api/docflow/linked_tasks")
def create_document_linked_task(data: DocumentLinkedTaskData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_linked_task", "route", data.status)
    if gate:
        return gate
    conn = get_connection(row_factory=True)
    try:
        doc = _doc_row(conn, data.document_id)
        if not doc:
            return {"error": "document_not_found"}
        task_id = _safe_int(data.task_id)
        if not task_id:
            task_id = next_safe_table_id(conn, "tasks")
            conn.execute(
                """
                INSERT INTO tasks (id, title, description, author, executor, deadline, status, created_at, recurrence, priority, project_id, history)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'none', ?, ?, '[]')
                """,
                (
                    task_id,
                    data.title or f"Поручение по документу №{doc.get('number') or doc.get('id')}",
                    data.comment or f"Связанное поручение по документу: {doc.get('subject') or 'без темы'}",
                    actor.get("name", ""),
                    data.assignee_name,
                    data.deadline,
                    data.status or "active",
                    datetime.now().strftime("%d.%m.%Y %H:%M"),
                    data.priority or "normal",
                    _safe_int(doc.get("project_id")),
                ),
            )
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_linked_tasks (
                document_id, task_id, title, assignee_name, deadline, priority, status, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _safe_int(data.document_id),
                task_id,
                data.title or f"Поручение по документу №{doc.get('number') or doc.get('id')}",
                data.assignee_name,
                data.deadline,
                data.priority or "normal",
                data.status or "active",
                data.comment,
                actor.get("email", ""),
                _now_ts(),
                _now_ts(),
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    if data.assignee_name:
        create_notification(
            "Новое поручение по документу",
            f"Документ №{doc.get('number') or doc.get('id')}: {doc.get('subject') or 'без темы'}",
            user_name=data.assignee_name,
            category="document",
            entity_type="document",
            entity_id=str(data.document_id),
        )
    audit_log("document_linked_task_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document", entity_id=str(data.document_id), details={"link_id": record_id, "task_id": task_id})
    return {"status": "success", "id": record_id, "task_id": task_id}


@router.delete("/api/docflow/linked_tasks/{record_id}")
def delete_document_linked_task(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "delete"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_linked_task", "delete")
    if gate:
        return gate
    conn = get_connection()
    try:
        conn.execute("DELETE FROM document_linked_tasks WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("document_linked_task_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_linked_task", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.post("/api/docflow/certificates")
def create_edo_certificate(data: EDOCertificateData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "edo_certificate", "update", data.status)
    if gate:
        return gate
    now = _now_ts()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO edo_certificates (
                owner_name, owner_email, signer_role, provider_name, thumbprint, serial_number,
                valid_from, valid_to, status, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.owner_name,
                data.owner_email,
                data.signer_role,
                data.provider_name,
                data.thumbprint,
                data.serial_number,
                data.valid_from,
                data.valid_to,
                data.status,
                data.comment,
                actor.get("email", ""),
                now,
                now,
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("edo_certificate_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="edo_certificate", entity_id=str(record_id), details={"owner_email": data.owner_email, "provider": data.provider_name})
    return {"status": "success", "id": record_id}


@router.post("/api/edo/certificates/deep")
def create_edo_certificate_deep(data: EDOCertificateData, request: Request):
    return create_edo_certificate(data, request)


@router.delete("/api/docflow/certificates/{record_id}")
def delete_edo_certificate(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "delete"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "edo_certificate", "delete")
    if gate:
        return gate
    conn = get_connection()
    try:
        conn.execute("DELETE FROM edo_certificates WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("edo_certificate_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="edo_certificate", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.post("/api/docflow/archive")
def create_legal_archive_entry(data: LegalArchiveEntryData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_archive", "archive", data.archive_status)
    if gate:
        return gate
    now = _now_ts()
    conn = get_connection(row_factory=True)
    try:
        doc = _doc_row(conn, data.document_id)
        if not doc:
            return {"error": "document_not_found"}
        archive_code = data.archive_code or f"ARCH-{datetime.now().strftime('%Y%m%d')}-{_safe_int(data.document_id)}"
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_legal_archive (
                document_id, archive_code, storage_path, retention_until, archive_status, certificate_id,
                comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _safe_int(data.document_id),
                archive_code,
                data.storage_path or f"/archive/documents/{_safe_int(data.document_id)}",
                data.retention_until,
                data.archive_status or "archived",
                _safe_int(data.certificate_id),
                data.comment,
                actor.get("email", ""),
                now,
                now,
            ),
        )
        record_id = cursor.lastrowid
        conn.execute("UPDATE documents SET status='archived' WHERE id=?", (_safe_int(data.document_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("document_archived", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document", entity_id=str(data.document_id), details={"archive_id": record_id, "archive_code": archive_code})
    return {"status": "success", "id": record_id, "archive_code": archive_code}


@router.delete("/api/docflow/archive/{record_id}")
def delete_legal_archive_entry(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "delete"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_archive", "delete")
    if gate:
        return gate
    conn = get_connection()
    try:
        conn.execute("DELETE FROM document_legal_archive WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("document_archive_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_archive", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.post("/api/docflow/print_forms")
def create_print_form_record(data: PrintFormRecordData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "update"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_print_form", "export", data.status)
    if gate:
        return gate
    now = _now_ts()
    file_url = data.file_url or f"/generated/print_forms/document_{_safe_int(data.document_id)}_{now}.{(data.format_type or 'pdf').lower()}"
    conn = get_connection(row_factory=True)
    try:
        if not _doc_row(conn, data.document_id):
            return {"error": "document_not_found"}
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO document_print_forms (
                document_id, template_id, format_type, form_name, file_url, status, generated_at,
                comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _safe_int(data.document_id),
                _safe_int(data.template_id),
                data.format_type or "pdf",
                data.form_name or "Печатная форма",
                file_url,
                data.status or "generated",
                _today_display(),
                data.comment,
                actor.get("email", ""),
                now,
                now,
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("document_print_form_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_print_form", entity_id=str(record_id), details={"document_id": data.document_id, "format_type": data.format_type})
    return {"status": "success", "id": record_id, "file_url": file_url}


@router.post("/api/docflow/documents/{document_id}/generate_print_set")
def generate_document_print_set(document_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "documents", "export") or has_permission(actor, "documents", "update")):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_print_form", "export", "generated")
    if gate:
        return gate
    now = _now_ts()
    conn = get_connection(row_factory=True)
    try:
        doc = _doc_row(conn, document_id)
        if not doc:
            return {"error": "document_not_found"}
        normalized_type = _normalized_doc_type(doc.get("type"))
        templates = _row_dicts(
            conn.execute(
                """
                SELECT *
                FROM document_templates
                WHERE doc_type IN (?, ?)
                  AND status IN ('active', 'draft')
                ORDER BY CASE WHEN status='active' THEN 2 ELSE 1 END DESC, updated_at DESC, id DESC
                LIMIT 3
                """,
                (normalized_type, doc.get("type", "")),
            )
        )
        created = []
        for template in templates:
            format_type = "docx" if _safe_text(template.get("template_kind")) == "editable" else "pdf"
            file_url = f"/generated/print_forms/document_{_safe_int(document_id)}_{template.get('id')}_{now}.{format_type}"
            cursor = conn.execute(
                """
                INSERT INTO document_print_forms (
                    document_id, template_id, format_type, form_name, file_url, status, generated_at,
                    comment, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'generated', ?, ?, ?, ?, ?)
                """,
                (
                    _safe_int(document_id),
                    _safe_int(template.get("id")),
                    format_type,
                    _safe_text(template.get("title")) or f"Print set {_safe_int(document_id)}",
                    file_url,
                    _today_display(),
                    f"Автогенерация print set для {_doc_type_label(normalized_type)}",
                    actor.get("email", ""),
                    now,
                    now,
                ),
            )
            created.append({"id": cursor.lastrowid, "template_id": _safe_int(template.get("id")), "format_type": format_type, "file_url": file_url})
        conn.commit()
    finally:
        conn.close()
    audit_log("document_print_set_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document", entity_id=str(document_id), details={"count": len(created)})
    return {"status": "success", "count": len(created), "items": created}


@router.delete("/api/docflow/print_forms/{record_id}")
def delete_print_form_record(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "delete"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "documents", "document_print_form", "delete")
    if gate:
        return gate
    conn = get_connection()
    try:
        conn.execute("DELETE FROM document_print_forms WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("document_print_form_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_print_form", entity_id=str(record_id), details={})
    return {"status": "success"}


def _load_integration_plus_summary() -> dict:
    conn = get_connection(row_factory=True)
    try:
        mappings = _row_dicts(conn.execute("SELECT * FROM integration_field_mappings ORDER BY updated_at DESC, id DESC"))
        inbound_updates = _row_dicts(conn.execute("SELECT * FROM integration_inbound_updates ORDER BY created_at DESC, id DESC LIMIT 200"))
        connectors = _row_dicts(conn.execute("SELECT * FROM integration_connectors ORDER BY updated_at DESC, id DESC"))
        saved_reports = _row_dicts(conn.execute("SELECT * FROM saved_reports ORDER BY updated_at DESC, id DESC LIMIT 60"))
        bank_accounts = _row_dicts(conn.execute("SELECT * FROM bank_accounts ORDER BY updated_at DESC, id DESC LIMIT 60"))
        telephony_accounts = _row_dicts(conn.execute("SELECT * FROM telephony_accounts ORDER BY updated_at DESC, id DESC LIMIT 60"))
        bank_lines = _row_dicts(conn.execute("SELECT * FROM bank_statement_lines ORDER BY updated_at DESC, id DESC LIMIT 200"))
        bank_batches = _row_dicts(conn.execute("SELECT * FROM bank_exchange_batches ORDER BY updated_at DESC, id DESC LIMIT 40"))
        bank_orders = _row_dicts(conn.execute("SELECT * FROM bank_payment_orders ORDER BY updated_at DESC, id DESC LIMIT 120"))
        telephony_calls = _row_dicts(conn.execute("SELECT * FROM telephony_calls ORDER BY created_at DESC, id DESC LIMIT 200"))
        connector_runs = _row_dicts(conn.execute("SELECT * FROM integration_connector_runs ORDER BY started_at DESC, id DESC LIMIT 80"))
    finally:
        conn.close()
    for row in connectors:
        row["settings"] = _json_load(row.get("settings_json"), {})
        row["scope"] = _json_load(row.get("scope_json"), {})
    for row in saved_reports:
        row["filters"] = _json_load(row.get("filters"), {})
        row["layout"] = _json_load(row.get("layout"), {})
    entity_catalog = sorted(set(projects_router._reconciliation_entity_config().keys()) | {"finance_payment"})
    mapping_matrix = []
    for entity_type in entity_catalog:
        if entity_type == "finance_payment":
            expected_fields = sorted((projects_router._build_finance_sync_payload({}) or {}).keys())
        else:
            meta = projects_router._sync_entity_meta(entity_type)
            expected_fields = sorted((meta.get("builder")({}) or {}).keys()) if meta and meta.get("builder") else []
        entity_rows = [row for row in mappings if _safe_text(row.get("entity_type")) == entity_type]
        active_rows = [row for row in entity_rows if int(row.get("is_active") or 0) == 1]
        directions: dict[str, int] = {}
        for row in active_rows:
            directions[row.get("direction") or "bidirectional"] = directions.get(row.get("direction") or "bidirectional", 0) + 1
        mapping_matrix.append(
            {
                "entity_type": entity_type,
                "expected_fields_total": len(expected_fields),
                "mapped_total": len(entity_rows),
                "active_mapped_total": len(active_rows),
                "required_total": len([row for row in active_rows if int(row.get("is_required") or 0) == 1]),
                "coverage_percent": round((len(active_rows) / len(expected_fields)) * 100, 1) if expected_fields else 0,
                "directions": directions,
            }
        )
    queue_rows = projects_router._load_sync_queue_rows(180)
    conflict_rows = projects_router._load_sync_conflict_rows(120)
    reconciliation_runs = projects_router._load_reconciliation_runs(20)
    monitoring = projects_router._integration_monitoring_payload(180)
    production_quality = projects_router._integration_production_quality_payload(180)
    recent_inbound_errors = [row for row in inbound_updates if row.get("apply_status") in {"error", "conflict"}][:10]
    recent_preview = [row for row in inbound_updates if row.get("apply_status") in {"preview", "received"}][:20]
    connector_health = []
    now = _now_ts()
    for row in connectors:
        last_sync_at = _safe_int(row.get("last_sync_at"))
        connector_health.append(
            {
                "id": _safe_int(row.get("id")),
                "connector_type": row.get("connector_type", ""),
                "provider_name": row.get("provider_name", ""),
                "status": row.get("status", "draft"),
                "last_sync_minutes_ago": round((now - last_sync_at) / 60) if last_sync_at else None,
                "last_error": row.get("last_error", ""),
            }
        )
    bank_unreconciled = [row for row in bank_lines if row.get("status") != "reconciled"]
    telephony_unlinked = [row for row in telephony_calls if not _safe_int(row.get("client_id")) and not _safe_int(row.get("project_id"))]
    bi_vitrines = [
        row for row in saved_reports
        if _safe_text(row.get("scope")) in {"shared", "team"} or _safe_text(row.get("report_type")) in {"analytics_deep", "reliability_dashboard", "finance_analytics", "operations_monitoring"}
    ]
    operator_recovery_board = {
        "failed_queue": len([row for row in queue_rows if row.get("state") == "failed"]),
        "retry_queue": len([row for row in queue_rows if row.get("state") == "retry"]),
        "stale_processing": len(monitoring.get("stale_rows") or []),
        "recent_conflicts": len(conflict_rows),
        "inbound_errors": len(recent_inbound_errors),
        "bank_unreconciled": len(bank_unreconciled),
        "telephony_unlinked": len(telephony_unlinked),
        "production_open_errors": production_quality.get("open_errors", 0),
        "idempotency_collisions": production_quality.get("idempotency_collisions", 0),
        "consistency_alerts": production_quality.get("consistency_alerts", 0),
    }
    bank_exchange_board = {
        "orders_open": len([row for row in bank_orders if row.get("status") in {"draft", "approved", "ready"}]),
        "orders_exported": len([row for row in bank_orders if row.get("status") in {"exported", "sent"}]),
        "unreconciled_lines": len(bank_unreconciled),
        "latest_batches": bank_batches[:12],
    }
    telephony_board = {
        "accounts_total": len(telephony_accounts),
        "calls_total": len(telephony_calls),
        "unlinked_calls": len(telephony_unlinked),
        "missed_calls": len([row for row in telephony_calls if row.get("status") == "missed"]),
        "recent_unlinked": telephony_unlinked[:12],
    }
    return {
        "mappings": mappings,
        "mapping_matrix": mapping_matrix,
        "inbound_updates": inbound_updates,
        "recent_preview": recent_preview,
        "connectors": connectors,
        "connector_health": connector_health,
        "connector_runs": connector_runs,
        "queue": queue_rows,
        "conflicts": conflict_rows,
        "reconciliation_runs": reconciliation_runs,
        "monitoring": monitoring,
        "production_quality": production_quality,
        "saved_reports": saved_reports,
        "bi_vitrines": bi_vitrines[:20],
        "bank_accounts": bank_accounts,
        "bank_exchange_board": bank_exchange_board,
        "telephony_accounts": telephony_accounts,
        "telephony_board": telephony_board,
        "operator_recovery_board": operator_recovery_board,
        "recent_inbound_errors": recent_inbound_errors,
        "metrics": {
            "mappings_total": len(mappings),
            "queue_open": len([row for row in queue_rows if row.get("state") in {"queued", "retry", "processing"}]),
            "queue_failed": len([row for row in queue_rows if row.get("state") in {"failed", "conflict"}]),
            "reconciliation_runs": len(reconciliation_runs),
            "inbound_received": len(inbound_updates),
            "inbound_errors": len(recent_inbound_errors),
            "connectors_total": len(connectors),
            "production_open_errors": production_quality.get("open_errors", 0),
            "consistency_alerts": production_quality.get("consistency_alerts", 0),
            "idempotency_keys_total": production_quality.get("idempotency_keys_total", 0),
            "bank_accounts_total": len(bank_accounts),
            "telephony_accounts_total": len(telephony_accounts),
            "bi_reports_total": len(saved_reports),
            "mapping_coverage_entities": len([row for row in mapping_matrix if row.get("active_mapped_total")]),
        },
    }


def _integration_preview_inbound_record(record: dict) -> dict:
    conn = get_connection(row_factory=True)
    try:
        payload = _json_load(record.get("payload"), {})
        entity_type = _safe_text(record.get("entity_type"))
        target = None
        target_id = 0
        if entity_type == "finance_payment":
            target = projects_router._find_finance_payment_by_sync_item(conn, {
                "entity_id": _safe_int(record.get("entity_id")),
                "external_id": _safe_text(record.get("external_id")),
                "amount": payload.get("amount") or 0,
                "status": payload.get("status") or "",
            })
            target_id = _safe_int((target or {}).get("id"))
        else:
            target = projects_router._load_sync_entity_row(conn, entity_type, _safe_int(record.get("entity_id")))
            if not target and _safe_text(record.get("external_id")):
                meta = projects_router._sync_entity_meta(entity_type)
                if meta and meta.get("external_column"):
                    row = conn.execute(
                        f"SELECT {meta['id_column']} FROM {meta['table']} WHERE {meta['external_column']}=? ORDER BY ROWID DESC LIMIT 1",
                        (_safe_text(record.get("external_id")),),
                    ).fetchone()
                    if row:
                        target = projects_router._load_sync_entity_row(conn, entity_type, row[0])
                        target_id = _safe_int(row[0])
            else:
                target_id = _safe_int((target or {}).get("id"))
        if not target:
            return {"record_id": _safe_int(record.get("id")), "entity_type": entity_type, "matched": False, "changes": []}
        changes = []
        compare_fields = {"status", "comment", "currency", "amount", "due_date", "paid_date", "payment_status", "stage", "unit", "price", "group_name", "default_warehouse"}
        for key, value in (payload or {}).items():
            if key not in compare_fields and key not in target:
                continue
            current = target.get(key)
            if str(current or "") == str(value or ""):
                continue
            changes.append({"field_name": key, "before": current, "after": value})
        top_level_status = _safe_text(record.get("result_message"))
        return {
            "record_id": _safe_int(record.get("id")),
            "entity_type": entity_type,
            "matched": True,
            "target_id": target_id or _safe_int((target or {}).get("id")),
            "external_id": _safe_text(record.get("external_id")),
            "changes": changes,
            "apply_mode": _safe_text(record.get("apply_mode")) or "apply",
            "current_status": _safe_text((target or {}).get("status")),
            "preview_note": top_level_status,
        }
    finally:
        conn.close()


def _apply_saved_inbound_record(record_id: int, actor: dict) -> dict:
    conn = get_connection(row_factory=True)
    try:
        row = dict(conn.execute("SELECT * FROM integration_inbound_updates WHERE id=?", (_safe_int(record_id),)).fetchone() or {})
        if not row:
            return {"error": "inbound_not_found"}
        item = {
            "entity_type": row.get("entity_type", ""),
            "entity_id": _safe_int(row.get("entity_id")),
            "external_id": row.get("external_id", ""),
            "payload": _json_load(row.get("payload"), {}),
            "status": _json_load(row.get("payload"), {}).get("status", ""),
            "amount": _json_load(row.get("payload"), {}).get("amount", 0),
            "currency": _json_load(row.get("payload"), {}).get("currency", "RUB"),
            "due_date": _json_load(row.get("payload"), {}).get("due_date", ""),
            "paid_date": _json_load(row.get("payload"), {}).get("paid_date", ""),
            "comment": _json_load(row.get("payload"), {}).get("comment", ""),
            "exchange_state": _json_load(row.get("payload"), {}).get("exchange_state", "synced"),
            "allow_amount_override": _safe_int(_json_load(row.get("payload"), {}).get("allow_amount_override", 0)),
        }
        if row.get("entity_type") == "finance_payment":
            outcome = projects_router._apply_inbound_finance_sync_item(conn, item, actor.get("email", ""), row.get("system_name") or "1C")
        else:
            outcome = projects_router._apply_generic_inbound_sync_item(conn, item, actor.get("email", ""), row.get("system_name") or "1C")
        apply_status = "applied" if outcome.get("state") == "applied" else ("conflict" if outcome.get("state") == "conflict" else "error")
        conn.execute(
            "UPDATE integration_inbound_updates SET apply_status=?, result_message=? WHERE id=?",
            (apply_status, json.dumps(outcome, ensure_ascii=False)[:1000], _safe_int(record_id)),
        )
        conn.commit()
        return {"status": "success", "id": _safe_int(record_id), "apply_status": apply_status, "outcome": outcome}
    finally:
        conn.close()


def _auto_resolve_reconciliation(actor: dict) -> dict:
    initial = projects_router._run_integration_reconciliation(actor)
    config = projects_router._reconciliation_entity_config()
    resolved = 0
    requeued = 0
    now = _now_ts()
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        for issue in initial.get("issues") or []:
            entity_type = _safe_text(issue.get("entity_type"))
            meta = config.get(entity_type)
            if not meta:
                continue
            row_id = _safe_int(issue.get("row_id"))
            entity_key = _safe_text(issue.get("entity_id"))
            queue_row = projects_router._find_reconciliation_queue_row(c, entity_type, row_id, entity_key, _safe_text(issue.get("local_external_id")))
            if issue.get("issue") in {"missing_external_id", "external_id_mismatch"} and queue_row and _safe_text(queue_row["external_id"]):
                updates = [f"{meta['external_field']}=?", f"{meta['state_field']}=?"]
                params = [_safe_text(queue_row["external_id"]), "synced" if _safe_text(queue_row["state"]) == "synced" else _safe_text(issue.get("state")) or "queued"]
                if meta.get("updated_column"):
                    updates.append(f"{meta['updated_column']}=?")
                    params.append(now)
                params.append(row_id)
                c.execute(f"UPDATE {meta['table']} SET {', '.join(updates)} WHERE {meta['id_field']}=?", tuple(params))
                resolved += 1
            elif issue.get("issue") == "no_sync_trace":
                if entity_type == "finance_payment":
                    payment = projects_router._get_finance_payment_row_from_conn(conn, row_id)
                    if payment:
                        projects_router._upsert_finance_sync_job(conn, payment, actor.get("email", ""))
                        requeued += 1
                elif entity_type != "epl_waybill":
                    if projects_router._upsert_entity_sync_job(conn, entity_type, row_id, actor.get("email", "")):
                        requeued += 1
            elif issue.get("issue") in {"failed", "conflict"}:
                c.execute(
                    """
                    UPDATE integration_sync_queue
                    SET state='retry', last_error='', next_retry_at=?, locked_at=0, updated_at=?
                    WHERE system_name='1C' AND entity_type=? AND entity_id=? AND state IN ('failed', 'conflict')
                    """,
                    (now, now, entity_type, row_id),
                )
                if c.rowcount:
                    requeued += c.rowcount
        conn.commit()
    finally:
        conn.close()
    processed = projects_router.process_due_1c_sync_queue(25)
    final = projects_router._run_integration_reconciliation(actor)
    return {
        "status": "success",
        "resolved": resolved,
        "requeued": requeued,
        "processed": processed,
        "before_mismatches": _safe_int(initial.get("mismatch_count")),
        "after_mismatches": _safe_int(final.get("mismatch_count")),
        "run_id": _safe_int(final.get("run_id")),
    }


def _sync_connector_record(record_id: int, actor: dict) -> dict:
    conn = get_connection(row_factory=True)
    try:
        connector = dict(conn.execute("SELECT * FROM integration_connectors WHERE id=?", (_safe_int(record_id),)).fetchone() or {})
        if not connector:
            return {"error": "connector_not_found"}
        connector_type = _safe_text(connector.get("connector_type"))
        result = {"connector_type": connector_type, "id": _safe_int(record_id)}
        now = _now_ts()
        run_cursor = conn.execute(
            """
            INSERT INTO integration_connector_runs (
                connector_id, connector_type, provider_name, run_kind, status,
                processed, success, failed, details_json, started_at, finished_at
            ) VALUES (?, ?, ?, 'sync', 'running', 0, 0, 0, '{}', ?, 0)
            """,
            (_safe_int(record_id), connector_type, connector.get("provider_name") or "", now),
        )
        run_id = run_cursor.lastrowid
        if connector_type == "1c":
            queue_result = projects_router.process_due_1c_sync_queue(25)
            reconciliation = projects_router._run_integration_reconciliation(actor)
            result.update({"queue": queue_result, "reconciliation": {"run_id": reconciliation.get("run_id"), "mismatch_count": reconciliation.get("mismatch_count", 0)}})
        elif connector_type == "bank":
            orders = _row_dicts(conn.execute("SELECT * FROM bank_payment_orders WHERE status IN ('draft', 'approved', 'ready') ORDER BY id ASC LIMIT 40"))
            unreconciled = _row_dicts(conn.execute("SELECT * FROM bank_statement_lines WHERE status != 'reconciled' ORDER BY id DESC LIMIT 40"))
            batch_id = 0
            if orders:
                total_amount = round(sum(_safe_int(0) + float(row.get("amount") or 0) for row in orders), 2)
                payload_json = json.dumps({"orders": orders}, ensure_ascii=False)
                cursor = conn.execute(
                    """
                    INSERT INTO bank_exchange_batches (
                        provider_name, direction, batch_type, bank_account_id, status, payload_json, total_amount, item_count,
                        exported_file, imported_file, comment, created_by, created_at, updated_at
                    ) VALUES (?, 'outbound', 'payment_exchange', ?, 'exported', ?, ?, ?, ?, '', ?, ?, ?, ?)
                    """,
                    (
                        connector.get("provider_name") or "bank_api",
                        _safe_int(orders[0].get("bank_account_id")),
                        payload_json,
                        total_amount,
                        len(orders),
                        f"/generated/bank_exchange/batch_{now}.json",
                        "Экспорт через integration+ connector sync",
                        actor.get("email", ""),
                        now,
                        now,
                    ),
                )
                batch_id = cursor.lastrowid
                order_ids = [int(row["id"]) for row in orders]
                placeholders = ", ".join(["?"] * len(order_ids))
                conn.execute(f"UPDATE bank_payment_orders SET status='exported', exchange_batch_id=?, updated_at=? WHERE id IN ({placeholders})", (batch_id, now, *order_ids))
            result.update({"batch_id": batch_id, "exported_orders": len(orders), "unreconciled_lines": len(unreconciled)})
        elif connector_type == "telephony":
            calls = _row_dicts(conn.execute("SELECT * FROM telephony_calls WHERE (client_id=0 OR project_id=0) ORDER BY id DESC LIMIT 60"))
            linked = 0
            for call in calls:
                context = projects_router._resolve_telephony_context(conn, call.get("phone_number", ""), _safe_int(call.get("client_id")), _safe_int(call.get("project_id")))
                if context.get("client_id") or context.get("project_id") or context.get("contact_name"):
                    conn.execute(
                        """
                        UPDATE telephony_calls
                        SET client_id=?, project_id=?, contact_name=CASE WHEN contact_name='' THEN ? ELSE contact_name END
                        WHERE id=?
                        """,
                        (context.get("client_id", 0), context.get("project_id", 0), context.get("contact_name", ""), _safe_int(call.get("id"))),
                    )
                    linked += 1
            result.update({"linked_calls": linked, "scanned_calls": len(calls)})
        elif connector_type == "bi":
            defaults = [
                ("analytics_deep", "BI · Глубокая аналитика"),
                ("finance_analytics", "BI · Финансы"),
                ("reliability_dashboard", "BI · Надёжность"),
                ("operations_monitoring", "BI · Операции"),
            ]
            created = 0
            for report_type, title in defaults:
                exists = conn.execute("SELECT id FROM saved_reports WHERE report_type=? AND title=? ORDER BY id DESC LIMIT 1", (report_type, title)).fetchone()
                if exists:
                    continue
                conn.execute(
                    """
                    INSERT INTO saved_reports (report_type, title, filters, layout, scope, owner_email, created_at, updated_at)
                    VALUES (?, ?, '{}', '{}', 'shared', ?, ?, ?)
                    """,
                    (report_type, title, actor.get("email", ""), now, now),
                )
                created += 1
            total = _safe_int((conn.execute("SELECT COUNT(*) FROM saved_reports WHERE scope='shared'").fetchone() or [0])[0])
            result.update({"created_vitrines": created, "shared_vitrines_total": total})
        else:
            conn.execute(
                "UPDATE integration_connector_runs SET status='failed', failed=1, details_json=?, finished_at=? WHERE id=?",
                (json.dumps({"error": "unsupported_connector_type", **result}, ensure_ascii=False), now, run_id),
            )
            conn.commit()
            return {"error": "unsupported_connector_type"}
        processed = _safe_int((result.get("queue") or {}).get("processed") if isinstance(result.get("queue"), dict) else 0)
        processed = processed or _safe_int(result.get("exported_orders")) or _safe_int(result.get("scanned_calls")) or _safe_int(result.get("created_vitrines"))
        failed = _safe_int((result.get("queue") or {}).get("failed") if isinstance(result.get("queue"), dict) else 0)
        success = max(0, processed - failed)
        if processed == 0 and not failed:
            success = 1
        conn.execute(
            """
            UPDATE integration_connector_runs
            SET status='success', processed=?, success=?, failed=?, details_json=?, finished_at=?
            WHERE id=?
            """,
            (processed, success, failed, json.dumps(result, ensure_ascii=False), now, run_id),
        )
        conn.execute(
            "UPDATE integration_connectors SET last_sync_at=?, last_error='', status='active', updated_at=? WHERE id=?",
            (now, now, _safe_int(record_id)),
        )
        conn.commit()
        return {"status": "success", **result}
    finally:
        conn.close()


@router.get("/api/integration/plus_summary")
def get_integration_plus_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    return _load_integration_plus_summary()


@router.get("/api/integration/deep_summary")
def get_integration_deep_summary(request: Request):
    return get_integration_plus_summary(request)


@router.post("/api/integration/mappings/designer")
def create_integration_mapping(data: IntegrationFieldMappingData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "finance", "integration_mapping", "sync_1c")
    if gate:
        return gate
    now = _now_ts()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO integration_field_mappings (
                system_name, entity_type, local_field, external_field, direction,
                transform_rule, is_required, is_active, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.system_name or "1C",
                data.entity_type,
                data.local_field,
                data.external_field,
                data.direction or "bidirectional",
                data.transform_rule,
                int(data.is_required or 0),
                int(data.is_active or 1),
                actor.get("email", ""),
                now,
                now,
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("integration_mapping_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_mapping", entity_id=str(record_id), details={"entity_type": data.entity_type, "local_field": data.local_field, "external_field": data.external_field})
    return {"status": "success", "id": record_id}


@router.post("/api/integration/mappings/bootstrap/{entity_type}")
def bootstrap_integration_mappings(entity_type: str, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    if entity_type == "finance_payment":
        expected_fields = sorted((projects_router._build_finance_sync_payload({}) or {}).keys())
    else:
        meta = projects_router._sync_entity_meta(entity_type)
        if not meta or not meta.get("builder"):
            return {"error": "unsupported_entity"}
        expected_fields = sorted((meta["builder"]({}) or {}).keys())
    now = _now_ts()
    created = 0
    conn = get_connection(row_factory=True)
    try:
        existing = {
            (_safe_text(row.get("entity_type")), _safe_text(row.get("local_field")), _safe_text(row.get("external_field")))
            for row in _row_dicts(conn.execute("SELECT entity_type, local_field, external_field FROM integration_field_mappings WHERE system_name='1C'"))
        }
        for field_name in expected_fields:
            key = (entity_type, field_name, field_name)
            if key in existing:
                continue
            conn.execute(
                """
                INSERT INTO integration_field_mappings (
                    system_name, entity_type, local_field, external_field, direction,
                    transform_rule, is_required, is_active, created_by, created_at, updated_at
                ) VALUES ('1C', ?, ?, ?, 'bidirectional', '', ?, 1, ?, ?, ?)
                """,
                (
                    entity_type,
                    field_name,
                    field_name,
                    1 if field_name in {"id", "status", "amount", "currency"} else 0,
                    actor.get("email", ""),
                    now,
                    now,
                ),
            )
            created += 1
        conn.commit()
    finally:
        conn.close()
    audit_log("integration_mapping_bootstrap", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_mapping", entity_id=entity_type, details={"created": created})
    return {"status": "success", "entity_type": entity_type, "created": created}


@router.delete("/api/integration/mappings/designer/{record_id}")
def delete_integration_mapping(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "finance", "integration_mapping", "delete")
    if gate:
        return gate
    conn = get_connection()
    try:
        conn.execute("DELETE FROM integration_field_mappings WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("integration_mapping_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_mapping", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.post("/api/integration/inbound_updates")
def create_integration_inbound_update(data: IntegrationInboundUpdateRecordData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "finance", "integration_inbound", "sync_1c")
    if gate:
        return gate
    conn = get_connection(row_factory=True)
    try:
        now = _now_ts()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO integration_inbound_updates (
                system_name, entity_type, entity_id, external_id, payload, apply_mode, apply_status, result_message, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'received', '', ?, ?)
            """,
            (
                data.system_name or "1C",
                data.entity_type,
                _safe_int(data.entity_id),
                data.external_id,
                json.dumps(data.payload or {}, ensure_ascii=False),
                data.apply_mode or "apply",
                actor.get("email", ""),
                now,
            ),
        )
        record_id = cursor.lastrowid
        outcome = {"status": "received"}
        apply_status = "received"
        result_message = _safe_text(data.comment)
        if (data.apply_mode or "apply") == "preview":
            preview = _integration_preview_inbound_record({
                "id": record_id,
                "entity_type": data.entity_type,
                "entity_id": _safe_int(data.entity_id),
                "external_id": data.external_id,
                "payload": json.dumps(data.payload or {}, ensure_ascii=False),
                "apply_mode": data.apply_mode or "preview",
                "result_message": data.comment or "",
            })
            outcome = preview
            apply_status = "preview"
            result_message = f"Preview changes: {len(preview.get('changes') or [])}"
        elif (data.apply_mode or "apply") != "queue_only":
            payload = {
                "entity_type": data.entity_type,
                "entity_id": _safe_int(data.entity_id),
                "external_id": data.external_id,
                "payload": data.payload or {},
            }
            if data.entity_type == "finance_payment":
                outcome = projects_router._apply_inbound_finance_sync_item(conn, payload, actor.get("email", ""), data.system_name or "1C")
            else:
                outcome = projects_router._apply_generic_inbound_sync_item(conn, payload, actor.get("email", ""), data.system_name or "1C")
            if outcome.get("state") == "applied" or outcome.get("status") in {"synced", "success"}:
                apply_status = "applied"
                result_message = "Inbound-обновление применено"
            else:
                apply_status = "error"
                result_message = outcome.get("message") or outcome.get("error") or "Не удалось применить inbound-обновление"
        conn.execute(
            "UPDATE integration_inbound_updates SET apply_status=?, result_message=? WHERE id=?",
            (apply_status, result_message, record_id),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("integration_inbound_received", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=data.entity_type or "integration_inbound", entity_id=str(data.entity_id or record_id), details={"record_id": record_id, "apply_status": apply_status, "external_id": data.external_id})
    return {"status": "success", "id": record_id, "apply_status": apply_status, "outcome": outcome}


@router.get("/api/integration/inbound_updates/{record_id}/preview")
def preview_integration_inbound_update(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        row = dict(conn.execute("SELECT * FROM integration_inbound_updates WHERE id=?", (_safe_int(record_id),)).fetchone() or {})
    finally:
        conn.close()
    if not row:
        return {"error": "inbound_not_found"}
    return _integration_preview_inbound_record(row)


@router.post("/api/integration/inbound_updates/{record_id}/apply")
def apply_integration_inbound_update(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    return _apply_saved_inbound_record(record_id, actor)


@router.delete("/api/integration/inbound_updates/{record_id}")
def delete_integration_inbound_update(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "finance", "integration_inbound", "delete")
    if gate:
        return gate
    conn = get_connection()
    try:
        conn.execute("DELETE FROM integration_inbound_updates WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("integration_inbound_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_inbound", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.post("/api/integration/connectors")
def create_integration_connector(data: IntegrationConnectorData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "finance", "integration_connector", "sync_1c", data.status)
    if gate:
        return gate
    now = _now_ts()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO integration_connectors (
                connector_type, provider_name, status, settings_json, scope_json,
                last_sync_at, last_error, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                data.connector_type,
                data.provider_name,
                data.status or "active",
                json.dumps(data.settings or {}, ensure_ascii=False),
                json.dumps(data.scope or {}, ensure_ascii=False),
                data.last_error or "",
                actor.get("email", ""),
                now,
                now,
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("integration_connector_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_connector", entity_id=str(record_id), details={"connector_type": data.connector_type, "provider_name": data.provider_name})
    return {"status": "success", "id": record_id}


@router.post("/api/integration/connectors/{record_id}/heartbeat")
def heartbeat_integration_connector(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    now = _now_ts()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE integration_connectors SET last_sync_at=?, last_error='', status='active', updated_at=? WHERE id=?",
            (now, now, _safe_int(record_id)),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("integration_connector_heartbeat", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_connector", entity_id=str(record_id), details={})
    return {"status": "success", "last_sync_at": now}


@router.post("/api/integration/connectors/{record_id}/sync")
def sync_integration_connector(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    result = _sync_connector_record(record_id, actor)
    if result.get("status") == "success":
        audit_log("integration_connector_sync", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_connector", entity_id=str(record_id), details=result)
    return result


@router.delete("/api/integration/connectors/{record_id}")
def delete_integration_connector(record_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    gate = _security_gate(actor, "finance", "integration_connector", "delete")
    if gate:
        return gate
    conn = get_connection()
    try:
        conn.execute("DELETE FROM integration_connectors WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("integration_connector_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_connector", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.post("/api/integration/reconciliation/auto_resolve")
def auto_resolve_integration_reconciliation(request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    result = _auto_resolve_reconciliation(actor)
    audit_log("integration_reconciliation_auto_resolve", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_reconciliation", entity_id=str(result.get("run_id") or ""), details=result)
    return result


def _load_security_plus_summary() -> dict:
    conn = get_connection(row_factory=True)
    try:
        policies = _row_dicts(conn.execute("SELECT * FROM security_action_policies ORDER BY role_name ASC, module_name ASC, action_name ASC, id DESC"))
        danger_rules = _row_dicts(conn.execute("SELECT * FROM security_danger_rules ORDER BY module_name ASC, action_name ASC, id DESC"))
        users = _row_dicts(conn.execute("SELECT email, name, role, status, two_factor_enabled FROM users ORDER BY name ASC"))
    finally:
        conn.close()
    field_rules = get_field_access_rules(is_active=1)
    for row in danger_rules:
        row["blocked_roles"] = _json_load(row.get("blocked_roles"), [])
    matrix = build_security_matrix_snapshot(
        permission_matrix=PERMISSION_MATRIX,
        field_rules=field_rules,
        action_policies=policies,
        danger_rules=danger_rules,
    )
    sessions = list_user_sessions(limit=160)
    audit_rows = get_audit_logs(limit=240)
    field_changes = get_field_change_logs(limit=240)
    risky_actions = [
        row for row in audit_rows
        if any(token in str(row.get("action") or "") for token in ("delete", "revoke", "recover", "close", "sync", "backup"))
    ][:40]
    action_totals = {}
    for row in audit_rows:
        action = _safe_text(row.get("action")) or "unknown"
        action_totals[action] = action_totals.get(action, 0) + 1
    top_actions = [{"action": key, "count": value} for key, value in sorted(action_totals.items(), key=lambda item: item[1], reverse=True)[:12]]
    field_totals = {}
    for row in field_changes:
        key = f"{row.get('entity_type')}.{row.get('field_name')}"
        field_totals[key] = field_totals.get(key, 0) + 1
    top_field_changes = [{"field_key": key, "count": value} for key, value in sorted(field_totals.items(), key=lambda item: item[1], reverse=True)[:12]]
    return {
        "policies": policies,
        "danger_rules": danger_rules,
        "field_rules": field_rules,
        "policy_matrix": matrix["rows"],
        "sessions": sessions,
        "audit_rows": audit_rows,
        "field_changes": field_changes,
        "top_actions": top_actions,
        "top_field_changes": top_field_changes,
        "risky_actions": risky_actions,
        "users": users,
        "metrics": {
            "policies_total": len(policies),
            "danger_rules_total": len(danger_rules),
            "field_rules_total": len(field_rules),
            "sessions_total": len(sessions),
            "two_factor_users": len([row for row in users if int(row.get("two_factor_enabled") or 0) == 1]),
            "field_changes_total": len(field_changes),
            "risky_actions_total": len(risky_actions),
            "matrix_rows_total": matrix["metrics"]["matrix_rows_total"],
            "matrix_rows_covered": matrix["metrics"]["matrix_rows_covered"],
            "matrix_coverage_percent": matrix["metrics"]["matrix_coverage_percent"],
        },
    }


@router.get("/api/security/plus_summary")
def get_security_plus_summary(request: Request):
    actor = _director_only(request)
    if not actor:
        return {"error": "forbidden"}
    return _load_security_plus_summary()


@router.get("/api/security/deep_summary")
def get_security_deep_summary(request: Request):
    return get_security_plus_summary(request)


@router.get("/api/security/sessions/deep")
def get_security_sessions_deep(request: Request, user_email: str = "", limit: int = 160):
    actor = _director_only(request)
    if not actor:
        return {"error": "forbidden"}
    return list_user_sessions(user_email or None, limit=max(1, min(_safe_int(limit) or 160, 500)))


@router.post("/api/security/guard/check")
def check_security_guard(data: SecurityGuardCheckData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    gate = _security_gate(
        actor,
        _safe_text(data.module_name),
        _safe_text(data.entity_type),
        _safe_text(data.action_name),
        _safe_text(data.status_name),
        _safe_text(data.reason),
    )
    if gate:
        payload = dict(gate)
        payload["message"] = explain_policy_error(gate)
        audit_log(
            "security_guard_blocked" if payload.get("error") != "reason_required" else "security_guard_reason_requested",
            actor_email=actor.get("email", ""),
            actor_name=actor.get("name", ""),
            entity_type=data.entity_type,
            entity_id=data.action_name,
            details={"module_name": data.module_name, "status_name": data.status_name, "error": payload.get("error")},
        )
        return payload
    audit_log(
        "security_guard_allowed",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type=data.entity_type,
        entity_id=data.action_name,
        details={"module_name": data.module_name, "status_name": data.status_name, "reason_supplied": bool(_safe_text(data.reason))},
    )
    return {"status": "allow", "message": "Действие разрешено policy-layer."}


@router.post("/api/security/action_policies")
def create_security_action_policy(data: SecurityActionPolicyData, request: Request):
    actor = _director_only(request)
    if not actor:
        return {"error": "forbidden"}
    now = _now_ts()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO security_action_policies (
                role_name, module_name, entity_type, action_name, status_name,
                allow_execute, require_2fa, require_reason, is_active, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.role_name,
                data.module_name,
                data.entity_type,
                data.action_name,
                data.status_name,
                int(data.allow_execute or 0),
                int(data.require_2fa or 0),
                int(data.require_reason or 0),
                int(data.is_active or 1),
                actor.get("email", ""),
                now,
                now,
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("security_action_policy_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="security_action_policy", entity_id=str(record_id), details={"role_name": data.role_name, "module_name": data.module_name, "action_name": data.action_name})
    return {"status": "success", "id": record_id}


@router.delete("/api/security/action_policies/{record_id}")
def delete_security_action_policy(record_id: int, request: Request):
    actor = _director_only(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        conn.execute("DELETE FROM security_action_policies WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("security_action_policy_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="security_action_policy", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.post("/api/security/danger_rules")
def create_security_danger_rule(data: SecurityDangerRuleData, request: Request):
    actor = _director_only(request)
    if not actor:
        return {"error": "forbidden"}
    now = _now_ts()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO security_danger_rules (
                module_name, entity_type, action_name, risk_level, require_2fa,
                require_reason, blocked_roles, is_active, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.module_name,
                data.entity_type,
                data.action_name,
                data.risk_level or "medium",
                int(data.require_2fa or 0),
                int(data.require_reason or 0),
                json.dumps(data.blocked_roles or [], ensure_ascii=False),
                int(data.is_active or 1),
                data.comment,
                actor.get("email", ""),
                now,
                now,
            ),
        )
        record_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    audit_log("security_danger_rule_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="security_danger_rule", entity_id=str(record_id), details={"module_name": data.module_name, "action_name": data.action_name, "risk_level": data.risk_level})
    return {"status": "success", "id": record_id}


@router.delete("/api/security/danger_rules/{record_id}")
def delete_security_danger_rule(record_id: int, request: Request):
    actor = _director_only(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        conn.execute("DELETE FROM security_danger_rules WHERE id=?", (_safe_int(record_id),))
        conn.commit()
    finally:
        conn.close()
    audit_log("security_danger_rule_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="security_danger_rule", entity_id=str(record_id), details={})
    return {"status": "success"}


@router.post("/api/security/sessions/control")
def control_security_sessions(data: SecuritySessionControlData, request: Request):
    actor = _director_only(request)
    if not actor:
        return {"error": "forbidden"}
    action_name = _safe_text(data.action_name) or "revoke_all"
    affected = 0
    if action_name == "revoke_one" and data.session_id:
        affected = revoke_user_session(data.session_id, data.user_email or "")
    elif action_name == "revoke_all" and data.user_email:
        rows_before = list_user_sessions(data.user_email, limit=500)
        delete_user_sessions_for_email(data.user_email)
        affected = len(rows_before)
    elif action_name == "revoke_stale":
        threshold = _now_ts() - max(60, _safe_int(data.older_than_minutes) * 60)
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE last_seen_at > 0 AND last_seen_at < ?", (threshold,))
            affected = cursor.rowcount
            conn.commit()
        finally:
            conn.close()
    else:
        return {"error": "invalid_action"}
    audit_log("security_sessions_controlled", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="user_session", entity_id=data.user_email or data.session_id or action_name, details={"action_name": action_name, "affected": affected, "reason": data.reason})
    return {"status": "success", "affected": affected}
