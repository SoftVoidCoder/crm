import os, re, secrets, shutil, json, time, csv, io, hashlib
import httpx
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from database import (
    DB_NAME,
    ROW_FACTORY_DICT,
    DatabaseIntegrityError,
    get_connection,
    next_safe_table_id,
    get_database_runtime_info,
    audit_log,
    get_audit_logs,
    get_field_change_logs,
    get_domain_events,
    record_domain_event,
    create_notification,
    notify_entity_watchers,
    create_erp_process_run,
    update_erp_process_run,
    get_erp_process_run,
    list_erp_process_runs,
    link_erp_entities,
    list_erp_links,
    list_erp_process_audit,
    acquire_entity_lock,
    release_entity_lock,
    get_entity_lock,
    list_entity_locks,
    get_lock_policy_catalog,
    list_background_job_runs,
    start_recovery_workflow_run,
    finish_recovery_workflow_run,
    list_recovery_workflow_runs,
    get_backups,
)
from permissions import require_approved_user, require_director, can_access_project, can_edit_project, has_permission, can_access_scope, filter_rows_by_scope, has_field_permission, get_allowed_statuses
from settings import DADATA_SECRET, DADATA_TOKEN
from schemas import ClientData, ProjectData, ProjectUpdate, NomenclatureData, ContactData, StockMovement, TenderParseData, ContractScanData, FinancePaymentData, FinanceMasterRecordData, PurchaseOrderData, SalesDocumentData, ProductionOrderData, ProductionOperationData, ProductionBOMItemData, ProductionRouteTemplateData, StockReservationData, SalesQuoteData, CustomerReturnData, SalesPlanData, PriceListData, ClientSalesTermData, SupplierRegistryData, PurchasePlanData, SupplierDeliveryScheduleData, SupplierReturnData, SupplierDiscrepancyActData, ExpenseApprovalData, InternalRequestData, ResourceAllocationData, ServiceCaseData, BudgetLineData, StockMovementDetailedData, SpecificationVersionData, ERPFlowStartData, ERPFlowAdvanceData, ClientMergeData, NomenclatureMergeData, StockReservationFulfillData, BusinessObjectData, ContractMasterData, TreasuryLimitData, FinancePeriodCloseData, ReconciliationActData, EDOSignatureData, FinanceInboundSyncData, NSIMasterRecordData, MDMGovernanceActionData, NSIHierarchyData, NSIExternalClassifierData, NSIExternalClassifierImportData, NSIDuplicateRuleData, NSIBulkChangeRequestData, InventoryDocumentData, InventoryActData, InventoryRegradingData, WarehouseQualityReportData, WarehousePolicyData, IntegrationSyncBatchData, BankAccountData, BankStatementImportData, BankStatementReconcileData, TelephonyAccountData, TelephonyCallData, SavedReportData, EntityLockData, SystemRecoveryActionData
from routers.accounting import _load_epl_waybill_rows
from services.analytics_ops_service import (
    build_analytics_deep_summary,
    build_analytics_dashboard_hub,
    build_analytics_drilldown,
    build_operations_monitoring,
    build_reliability_dashboard,
    load_saved_reports as load_saved_reports_service,
    run_saved_report_payload as run_saved_report_payload_service,
)
from services.accounting_close_service import run_accounting_close_cycle
from services.accounting_register_service import purge_registers_for_source, register_accounting_entry_by_id, rebuild_registers_for_source
from services.client360_service import build_client_dossier
from services.integration_sync_service import (
    build_finance_sync_payload as build_finance_sync_payload_service,
    build_purchase_sync_payload as build_purchase_sync_payload_service,
    build_sales_sync_payload as build_sales_sync_payload_service,
    build_document_sync_payload as build_document_sync_payload_service,
    build_production_sync_payload as build_production_sync_payload_service,
    build_reservation_sync_payload as build_reservation_sync_payload_service,
    build_nomenclature_sync_payload as build_nomenclature_sync_payload_service,
    build_simple_nsi_sync_payload as build_simple_nsi_sync_payload_service,
    build_employee_sync_payload as build_employee_sync_payload_service,
    build_position_sync_payload as build_position_sync_payload_service,
    build_characteristic_sync_payload as build_characteristic_sync_payload_service,
    build_storage_cell_sync_payload as build_storage_cell_sync_payload_service,
    build_income_expense_article_sync_payload as build_income_expense_article_sync_payload_service,
    build_cfr_sync_payload as build_cfr_sync_payload_service,
    build_operation_type_sync_payload as build_operation_type_sync_payload_service,
    build_bank_account_sync_payload as build_bank_account_sync_payload_service,
    sync_entity_meta as sync_entity_meta_service,
    load_sync_queue_rows as load_sync_queue_rows_service,
    load_sync_conflict_rows as load_sync_conflict_rows_service,
    build_integration_monitoring_payload,
)
from services.one_c_connector_service import process_due_1c_sync_queue as process_due_1c_sync_queue_service
from services.nsi_external_sources_service import fetch_external_classifier_items
from services.master_data_service import (
    ensure_client_reference as ensure_client_reference_service,
    user_email_by_name as user_email_by_name_service,
    extract_project_object_payload as extract_project_object_payload_service,
    propagate_project_master_links as propagate_project_master_links_service,
    sync_project_master_data as _sync_project_master_data_service,
    resolve_master_context as _resolve_master_context_service,
    load_contract_directory as load_contract_directory_service,
    load_business_objects_directory as load_business_objects_directory_service,
    sync_contract_back_to_project as sync_contract_back_to_project_service,
    replace_project_client_name as replace_project_client_name_service,
)
from services.policy_service import enforce_field_update_permissions, explain_policy_error
from services.operations_integrations_service import (
    list_bank_accounts as list_bank_accounts_service,
    create_bank_account_record as create_bank_account_record_service,
    list_bank_statement_lines as list_bank_statement_lines_service,
    import_bank_statement_records as import_bank_statement_records_service,
    reconcile_bank_statement_record as reconcile_bank_statement_record_service,
    list_telephony_accounts as list_telephony_accounts_service,
    create_telephony_account_record as create_telephony_account_record_service,
    list_telephony_calls as list_telephony_calls_service,
    create_telephony_call_record as create_telephony_call_record_service,
)
from services.event_stream_service import build_unified_event_stream
from services.reconciliation_service import (
    reconciliation_entity_config as reconciliation_entity_config_service,
    collect_reconciliation_entity_issues as collect_reconciliation_entity_issues_service,
    run_integration_reconciliation as run_integration_reconciliation_service,
    load_reconciliation_runs as load_reconciliation_runs_service,
)
from services.erp_workflow_service import (
    start_erp_process_record as start_erp_process_record_service,
    advance_erp_process_record as advance_erp_process_record_service,
)
from services.production_costing_service import complete_operation_costing
from services.inventory_costing_service import (
    consume_cost_layers,
    costing_summary as inventory_costing_summary,
    qty_to_base,
    receipt_cost_layer,
    transfer_cost_layers,
    update_lot_expiration,
)

# === ПОДКЛЮЧАЕМ МЕНЕДЖЕР WEBSOCKETS ===
from utils import manager 

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
MAX_PROJECT_UPLOAD_BYTES = int(os.getenv("KORDA_MAX_PROJECT_UPLOAD_BYTES", str(50 * 1024 * 1024)))
BLOCKED_PROJECT_UPLOAD_EXTENSIONS = {
    ".app",
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".dmg",
    ".exe",
    ".hta",
    ".htm",
    ".html",
    ".jar",
    ".js",
    ".jse",
    ".mjs",
    ".msi",
    ".ps1",
    ".reg",
    ".scr",
    ".sh",
    ".svg",
    ".vb",
    ".vbe",
    ".vbs",
    ".wsf",
}
ERP_FULL_DEMO_CLIENT_NAME = "ООО Демо Контур ERP"
ERP_FULL_DEMO_PROJECTS = [
    {"key": "sales", "name": "Демо: Продажи и закупки", "contract": "DEMO-ERP-SALES", "budget": 4200000, "costs": 1850000, "progress": 62},
    {"key": "production", "name": "Демо: Производство и склад", "contract": "DEMO-ERP-PROD", "budget": 5100000, "costs": 2760000, "progress": 54},
    {"key": "finance", "name": "Демо: Финансы и казначейство", "contract": "DEMO-ERP-FIN", "budget": 3100000, "costs": 1210000, "progress": 71},
    {"key": "service", "name": "Демо: Сервис и сроки реакции", "contract": "DEMO-ERP-SVC", "budget": 1680000, "costs": 640000, "progress": 47},
    {"key": "docflow", "name": "Демо: Документы и интеграции", "contract": "DEMO-ERP-DOC", "budget": 2560000, "costs": 930000, "progress": 66},
]


def _api_error(status_code: int, error: str, **payload):
    return JSONResponse(status_code=status_code, content={"error": error, **payload})


def _safe_upload_filename(value: str) -> str:
    raw = os.path.basename(str(value or "").replace("\\", "/")) or "file.bin"
    cleaned = re.sub(r"[^A-Za-zА-Яа-я0-9._-]+", "_", raw).strip("._")
    return cleaned[:140] or "file.bin"


def _next_table_id(conn, table_name: str) -> int:
    return next_safe_table_id(conn, table_name)


def _ensure_demo_row(conn, table_name: str, lookup: dict, payload: dict, update_fields: list[str] | None = None) -> tuple[int, bool]:
    c = conn.cursor()
    where_clause = " AND ".join(f"{field}=?" for field in lookup.keys())
    c.execute(f"SELECT id FROM {table_name} WHERE {where_clause} LIMIT 1", tuple(lookup.values()))
    row = c.fetchone()
    if row:
        record_id = _safe_int(row[0])
        fields_to_update = update_fields or [field for field in payload.keys() if field != "id"]
        if fields_to_update:
            assignments = ", ".join(f"{field}=?" for field in fields_to_update)
            values = [payload.get(field) for field in fields_to_update]
            c.execute(f"UPDATE {table_name} SET {assignments} WHERE id=?", (*values, record_id))
        return record_id, False
    insert_payload = dict(payload)
    if "id" in insert_payload and not _safe_int(insert_payload.get("id")):
        insert_payload["id"] = _next_table_id(conn, table_name)
    fields = list(insert_payload.keys())
    c.execute(
        f"INSERT INTO {table_name} ({', '.join(fields)}) VALUES ({', '.join(['?'] * len(fields))})",
        tuple(insert_payload[field] for field in fields),
    )
    return _safe_int(insert_payload.get("id") or c.lastrowid), True

from pydantic import BaseModel
class ClaimData(BaseModel):
    proj_id: int
    number: str
    d_date: str
    initiator: str
    addressee: str
    amount: float
    status: str
    date_sent: str
    deadline: str
    date_answered: str

class CourtCaseData(BaseModel):
    proj_id: int
    number: str
    court_name: str
    plaintiff: str
    defendant: str
    amount: float
    instance: str
    stage: str
    next_hearing: str


class CalendarEventData(BaseModel):
    title: str = ""
    event_date: str = ""
    start_time: str = ""
    end_time: str = ""
    scope: str = "personal"
    owner_email: str = ""
    owner_name: str = ""
    department: str = ""
    project_id: int = 0
    meeting_id: int = 0
    status: str = "planned"
    location: str = ""
    description: str = ""


class CRMLeadData(BaseModel):
    title: str = ""
    client_name: str = ""
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    source: str = ""
    stage: str = "new"
    probability: float = 0
    budget: float = 0
    currency: str = "RUB"
    responsible: str = ""
    next_action: str = ""
    next_action_date: str = ""
    priority: str = "normal"
    tags: list[str] = []
    comment: str = ""
    linked_client_id: int = 0
    linked_project_id: int = 0
    linked_deal_id: int = 0


class CRMDealData(BaseModel):
    lead_id: int = 0
    title: str = ""
    client_id: int = 0
    client_name: str = ""
    contract_number: str = ""
    stage: str = "qualification"
    amount: float = 0
    currency: str = "RUB"
    margin_percent: float = 0
    probability: float = 0
    responsible: str = ""
    next_action: str = ""
    next_action_date: str = ""
    expected_close_date: str = ""
    priority: str = "normal"
    status_color: str = ""
    tags: list[str] = []
    comment: str = ""
    project_id: int = 0


class CRMActivityData(BaseModel):
    entity_type: str = "lead"
    entity_id: int = 0
    activity_type: str = "note"
    subject: str = ""
    summary: str = ""
    due_date: str = ""
    status: str = "open"
    owner_name: str = ""


class OutreachProspectData(BaseModel):
    company_name: str = ""
    company_inn: str = ""
    contact_name: str = ""
    position: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    city: str = ""
    contact_method: str = ""
    source_name: str = ""
    source_file: str = ""
    status: str = "new"
    priority: str = "normal"
    manager_name: str = ""
    manager_email: str = ""
    planned_contact_date: str = ""
    next_action: str = ""
    next_action_date: str = ""
    notes: str = ""
    tags: list[str] = []
    do_not_contact: int = 0
    extra: dict = {}


class OutreachImportData(BaseModel):
    filename: str = ""
    source_name: str = ""
    default_manager_name: str = ""
    default_manager_email: str = ""
    planned_contact_date: str = ""
    rows: list[dict] = []


class OutreachBulkActionData(BaseModel):
    ids: list[int] = []
    action: str = "assign"
    manager_name: str = ""
    manager_email: str = ""
    planned_contact_date: str = ""
    status: str = ""
    note: str = ""


class OutreachActivityData(BaseModel):
    prospect_id: int = 0
    activity_type: str = "call"
    result_status: str = ""
    summary: str = ""
    next_action: str = ""
    next_action_date: str = ""
    channel: str = ""
    prospect_status: str = ""


class OutreachReportData(BaseModel):
    report_date: str = ""
    plan_total: int = 0
    processed_total: int = 0
    calls_total: int = 0
    emails_total: int = 0
    meetings_total: int = 0
    converted_total: int = 0
    summary: str = ""
    blockers: str = ""
    next_day_focus: str = ""


def _json_load(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _load_project_row(proj_id: int):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM projects WHERE id=?", (proj_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def _project_payload(row: dict):
    d = dict(row)
    if 'checkedState' not in d and 'checkedstate' in d:
        d['checkedState'] = d.pop('checkedstate')
    if 'taskFiles' not in d and 'taskfiles' in d:
        d['taskFiles'] = d.pop('taskfiles')
    for f in ['checkedState', 'comments', 'deadlines', 'chat', 'files', 'logs', 'team', 'checklist', 'escalations', 'archive_details', 'taskFiles', 'subtasks', 'time_logs', 'allowed_roles', 'nomenclature']:
        if f in d:
            d[f] = json.loads(d[f]) if d[f] else ({} if f in ['checkedState', 'comments', 'deadlines', 'escalations', 'archive_details', 'taskFiles', 'subtasks'] else [])
    return d


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _normalize_match(value: str) -> str:
    return _normalize_spaces(value).lower()


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _today_display() -> str:
    return datetime.now().strftime("%d.%m.%Y")


def _now_display_dt() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def _outreach_allowed(actor: dict, action: str = "read") -> bool:
    if not actor:
        return False
    if actor.get("role") == "Директор":
        return True
    if action == "read":
        return has_permission(actor, "clients", "read") or has_permission(actor, "projects", "read")
    if action == "create":
        return has_permission(actor, "clients", "create") or has_permission(actor, "projects", "create")
    return has_permission(actor, "clients", "update") or has_permission(actor, "projects", "update")


def _normalize_outreach_status(value: str) -> str:
    normalized = _normalize_match(value)
    mapping = {
        "": "new",
        "new": "new",
        "новый": "new",
        "не обработан": "new",
        "необработан": "new",
        "assigned": "assigned",
        "назначен": "assigned",
        "in_progress": "in_progress",
        "in progress": "in_progress",
        "в работе": "in_progress",
        "работаем": "in_progress",
        "no_answer": "no_answer",
        "не дозвонились": "no_answer",
        "нет ответа": "no_answer",
        "follow_up": "follow_up",
        "повторный контакт": "follow_up",
        "перезвонить": "follow_up",
        "warm": "warm",
        "теплый": "warm",
        "meeting": "meeting",
        "встреча": "meeting",
        "converted": "converted",
        "converted_to_lead": "converted",
        "конвертирован": "converted",
        "лид": "converted",
        "won": "converted",
        "do_not_contact": "do_not_contact",
        "не беспокоить": "do_not_contact",
        "refused": "do_not_contact",
        "archive": "archived",
        "archived": "archived",
        "архив": "archived",
    }
    return mapping.get(normalized, "new")


def _normalize_outreach_priority(value: str) -> str:
    normalized = _normalize_match(value)
    mapping = {
        "high": "high",
        "высокий": "high",
        "urgent": "high",
        "normal": "normal",
        "обычный": "normal",
        "средний": "normal",
        "low": "low",
        "низкий": "low",
    }
    return mapping.get(normalized, "normal")


def _clean_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    return digits[-11:] if digits else ""


def _outreach_header_key(value: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", "", str(value or "").strip().lower())


def _outreach_pick(row: dict, aliases: tuple[str, ...]) -> str:
    if not row:
        return ""
    direct_aliases = [alias for alias in aliases if alias in row]
    for alias in direct_aliases:
        value = row.get(alias)
        if _normalize_spaces(value):
            return _normalize_spaces(value)
    normalized = {_outreach_header_key(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_outreach_header_key(alias))
        if _normalize_spaces(value):
            return _normalize_spaces(value)
    return ""


def _outreach_contact_name(row: dict) -> str:
    full_name = _outreach_pick(
        row,
        (
            "contact_name",
            "contact",
            "person",
            "fio",
            "ФИО",
            "Контакт",
            "Контактное лицо",
            "Полное имя",
            "Имя контакта",
            "CONTACT_NAME",
            "FULL_NAME",
        ),
    )
    if full_name:
        return full_name
    parts = [
        _outreach_pick(row, ("Фамилия", "LAST_NAME")),
        _outreach_pick(row, ("Имя", "NAME", "FIRST_NAME")),
        _outreach_pick(row, ("Отчество", "SECOND_NAME", "MIDDLE_NAME")),
    ]
    return _normalize_spaces(" ".join(part for part in parts if part))


OUTREACH_IMPORT_ALIASES = {
    "company_name": (
        "company_name",
        "company",
        "client",
        "Название",
        "title",
        "Название компании",
        "Компания",
        "Контрагент",
        "Организация",
        "Название организации",
        "Название лида",
        "Лид",
        "Название сделки",
        "COMPANY",
        "COMPANY_NAME",
        "COMPANY_TITLE",
        "CONTACT_COMPANY",
        "TITLE",
        "LEAD_TITLE",
    ),
    "company_inn": ("company_inn", "inn", "ИНН", "ИНН компании", "RQ_INN", "COMPANY_INN"),
    "phone": (
        "phone",
        "telephone",
        "mobile",
        "Телефон",
        "Мобильный",
        "Телефон рабочий",
        "Рабочий телефон",
        "Мобильный телефон",
        "Телефон мобильный",
        "Телефон (раб.)",
        "Телефон (моб.)",
        "PHONE",
        "PHONE_WORK",
        "PHONE_MOBILE",
    ),
    "email": (
        "email",
        "mail",
        "e-mail",
        "Email",
        "E-mail",
        "Почта",
        "Эл. почта",
        "Email рабочий",
        "E-mail рабочий",
        "Рабочий email",
        "Рабочий e-mail",
        "EMAIL",
        "EMAIL_WORK",
    ),
    "contact_method": ("contact_method", "preferred_channel", "how_to_contact", "Способ связи", "Как связаться", "Канал связи"),
    "position": ("position", "role", "Должность", "Позиция", "POST", "CONTACT_POST"),
    "website": ("website", "site", "url", "Сайт", "Веб-сайт", "WEB", "WEB_WORK"),
    "city": ("city", "Город", "Регион", "Адрес город", "ADDRESS_CITY", "COMPANY_ADDRESS_CITY"),
    "source_name": ("source_name", "source", "Источник", "Источник лида", "SOURCE", "SOURCE_ID", "SOURCE_DESCRIPTION"),
    "status": ("status", "Статус", "Стадия", "STATUS", "STATUS_ID", "STAGE_ID"),
    "priority": ("priority", "Приоритет", "PRIORITY"),
    "manager_name": ("manager_name", "manager", "Менеджер", "Ответственный", "Ответственный менеджер", "ASSIGNED_BY", "ASSIGNED_BY_NAME"),
    "manager_email": ("manager_email", "manager_mail", "Email ответственного", "E-mail ответственного", "ASSIGNED_BY_EMAIL"),
    "planned_contact_date": ("planned_contact_date", "План", "Дата контакта", "Плановая дата контакта"),
    "next_action": ("next_action", "Следующее действие", "Следующее дело", "NEXT_ACTIVITY_SUBJECT"),
    "next_action_date": ("next_action_date", "Дата следующего шага", "Дата следующего дела", "NEXT_ACTIVITY_DATE"),
    "notes": ("notes", "note", "comment", "Комментарий", "Комментарии", "COMMENTS", "Описание", "Description", "DESCRIPTION"),
    "tags": ("tags", "Теги", "TAG", "TAGS"),
    "result": ("result", "Результат", "RESULT"),
    "do_not_contact": ("do_not_contact", "Не звонить", "DNC"),
}


def _normalize_outreach_row(row: dict):
    company_name = _outreach_pick(row, OUTREACH_IMPORT_ALIASES["company_name"])
    contact_name = _outreach_contact_name(row)
    phone = _outreach_pick(row, OUTREACH_IMPORT_ALIASES["phone"])
    email = _outreach_pick(row, OUTREACH_IMPORT_ALIASES["email"])
    contact_method = _outreach_pick(row, OUTREACH_IMPORT_ALIASES["contact_method"]) or ("phone" if phone else "email" if email else "")
    known_keys = {_outreach_header_key(alias) for aliases in OUTREACH_IMPORT_ALIASES.values() for alias in aliases}
    known_keys.update({_outreach_header_key(alias) for alias in ("Фамилия", "Имя", "Отчество", "LAST_NAME", "NAME", "FIRST_NAME", "SECOND_NAME", "MIDDLE_NAME", "ID", "CONTACT_ID", "COMPANY_ID")})
    return {
        "company_name": company_name,
        "company_inn": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["company_inn"]),
        "contact_name": contact_name,
        "position": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["position"]),
        "phone": phone,
        "email": email,
        "website": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["website"]),
        "city": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["city"]),
        "contact_method": contact_method,
        "source_name": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["source_name"]),
        "status": _normalize_outreach_status(_outreach_pick(row, OUTREACH_IMPORT_ALIASES["status"])),
        "priority": _normalize_outreach_priority(_outreach_pick(row, OUTREACH_IMPORT_ALIASES["priority"])),
        "manager_name": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["manager_name"]),
        "manager_email": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["manager_email"]),
        "planned_contact_date": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["planned_contact_date"]),
        "next_action": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["next_action"]),
        "next_action_date": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["next_action_date"]),
        "notes": _outreach_pick(row, OUTREACH_IMPORT_ALIASES["notes"]),
        "tags": [item.strip() for item in str(_outreach_pick(row, OUTREACH_IMPORT_ALIASES["tags"])).split(",") if item.strip()],
        "do_not_contact": 1 if _outreach_status_from_result(_outreach_pick(row, OUTREACH_IMPORT_ALIASES["result"])) == "do_not_contact" else _safe_int(_outreach_pick(row, OUTREACH_IMPORT_ALIASES["do_not_contact"]) or 0),
        "extra": {key: value for key, value in (row or {}).items() if _outreach_header_key(key) not in known_keys},
    }


def _outreach_duplicate_key(item: dict) -> str:
    inn = _normalize_match(item.get("company_inn") or "")
    if inn:
        return f"inn:{inn}"
    email = _normalize_match(item.get("email") or "")
    if email:
        return f"email:{email}"
    phone = _clean_phone(item.get("phone") or "")
    company = _normalize_match(item.get("company_name") or "")
    if company and phone:
        return f"company_phone:{company}:{phone}"
    if company:
        return f"company:{company}"
    return ""


def _outreach_known_import_keys() -> set[str]:
    keys = {_outreach_header_key(alias) for aliases in OUTREACH_IMPORT_ALIASES.values() for alias in aliases}
    keys.update({_outreach_header_key(alias) for alias in ("Фамилия", "Имя", "Отчество", "LAST_NAME", "NAME", "FIRST_NAME", "SECOND_NAME", "MIDDLE_NAME", "ID", "CONTACT_ID", "COMPANY_ID")})
    return keys


def _outreach_item_lookup_keys(item: dict) -> list[str]:
    return [
        _outreach_duplicate_key(item),
        f"email:{_normalize_match(item.get('email') or '')}" if item.get("email") else "",
        f"company_phone:{_normalize_match(item.get('company_name') or '')}:{_clean_phone(item.get('phone') or '')}" if item.get("company_name") and item.get("phone") else "",
        f"company:{_normalize_match(item.get('company_name') or '')}" if item.get("company_name") else "",
    ]


def _outreach_existing_key_map(rows: list[dict]) -> dict[str, dict]:
    existing_keys = {}
    for row in rows:
        normalized = {
            "company_name": row.get("company_name", ""),
            "company_inn": row.get("company_inn", ""),
            "phone": row.get("phone", ""),
            "email": row.get("email", ""),
        }
        for key in _outreach_item_lookup_keys(normalized):
            if key:
                existing_keys[key] = row
    return existing_keys


def _outreach_import_preview_counts(data: OutreachImportData, existing_rows: list[dict]) -> dict:
    known_keys = _outreach_known_import_keys()
    raw_columns = []
    seen_columns = set()
    for raw in data.rows or []:
        for key in (raw or {}).keys():
            normalized = _outreach_header_key(key)
            if normalized and normalized not in seen_columns:
                seen_columns.add(normalized)
                raw_columns.append(str(key))
    recognized_columns = [key for key in raw_columns if _outreach_header_key(key) in known_keys]
    existing_keys = _outreach_existing_key_map(existing_rows)
    created = 0
    updated = 0
    skipped = 0
    problems = []
    default_manager_name = _normalize_spaces(data.default_manager_name)
    default_manager_email = _normalize_spaces(data.default_manager_email)
    default_plan_date = _normalize_spaces(data.planned_contact_date)
    source_name = _normalize_spaces(data.source_name)
    for index, raw in enumerate(data.rows or [], start=1):
        item = _normalize_outreach_row(raw or {})
        if not item["company_name"] and not item["phone"] and not item["email"]:
            skipped += 1
            problems.append({"row": index, "reason": "нет компании, телефона и email"})
            continue
        item["manager_name"] = item["manager_name"] or default_manager_name
        item["manager_email"] = item["manager_email"] or default_manager_email
        item["planned_contact_date"] = item["planned_contact_date"] or default_plan_date
        item["source_name"] = item["source_name"] or source_name
        lookup_keys = _outreach_item_lookup_keys(item)
        match = next((existing_keys.get(key) for key in lookup_keys if key and existing_keys.get(key)), None)
        if match:
            updated += 1
        else:
            created += 1
        virtual_row = {"id": match.get("id") if match else -created, **item}
        for key in lookup_keys:
            if key:
                existing_keys[key] = virtual_row
    return {
        "rows_total": len(data.rows or []),
        "columns_total": len(raw_columns),
        "recognized_columns": len(recognized_columns),
        "unrecognized_columns": max(0, len(raw_columns) - len(recognized_columns)),
        "recognized_column_names": recognized_columns,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "problem_rows": skipped,
        "problems": problems[:20],
    }


def _outreach_status_from_result(value: str) -> str:
    normalized = _normalize_match(value)
    mapping = {
        "": "",
        "нет ответа": "no_answer",
        "не дозвонились": "no_answer",
        "no_answer": "no_answer",
        "перезвонить": "follow_up",
        "follow_up": "follow_up",
        "callback": "follow_up",
        "интерес": "warm",
        "warm": "warm",
        "встреча": "meeting",
        "meeting": "meeting",
        "конвертирован": "converted",
        "lead": "converted",
        "converted": "converted",
        "отказ": "do_not_contact",
        "не интересно": "do_not_contact",
        "do_not_contact": "do_not_contact",
    }
    return mapping.get(normalized, "")


def _load_outreach_activities_map(conn, prospect_ids: list[int]) -> dict[int, list[dict]]:
    if not prospect_ids:
        return {}
    c = conn.cursor()
    placeholders = ",".join("?" for _ in prospect_ids)
    c.execute(
        f"SELECT * FROM outreach_activities WHERE prospect_id IN ({placeholders}) ORDER BY created_at DESC, id DESC",
        tuple(prospect_ids),
    )
    bucket: dict[int, list[dict]] = {}
    for row in c.fetchall():
        item = dict(row)
        bucket.setdefault(_safe_int(item.get("prospect_id")), []).append(item)
    return bucket


def _decorate_outreach_rows(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    conn = get_connection(row_factory=True)
    try:
        activities_map = _load_outreach_activities_map(conn, [_safe_int(row.get("id")) for row in rows])
    finally:
        conn.close()
    now = datetime.now()
    today_key = now.strftime("%Y%m%d")
    decorated = []
    for row in rows:
        item = dict(row)
        item["tags"] = _json_load(item.get("tags_json"), [])
        item["extra"] = _json_load(item.get("extra_json"), {})
        item["activities"] = activities_map.get(_safe_int(item.get("id")), [])
        item["processed_state"] = "processed" if _safe_int(item.get("is_processed")) else "pending"
        next_date = item.get("next_action_date") or item.get("planned_contact_date") or ""
        next_dt = None
        if next_date:
            try:
                next_dt = datetime.strptime(next_date, "%d.%m.%Y")
            except Exception:
                next_dt = None
        status = item.get("status")
        is_closed = status in {"converted", "archived", "do_not_contact"}
        created_ts = _safe_int(item.get("created_at"))
        first_contact_age = (int(time.time()) - created_ts) if created_ts else 0
        first_contact_overdue = bool(
            not is_closed
            and item.get("manager_email")
            and _safe_int(item.get("attempts_count")) == 0
            and first_contact_age >= 24 * 60 * 60
        )
        item["is_first_contact_overdue"] = first_contact_overdue
        item["overdue_reason"] = "SLA первого контакта 24ч" if first_contact_overdue else ""
        item["is_overdue"] = bool((next_dt and next_dt.date() < now.date() and not is_closed) or first_contact_overdue)
        item["is_due_today"] = bool(next_dt and next_dt.strftime("%Y%m%d") == today_key)
        decorated.append(item)
    return decorated


def _outreach_manager_matches(row: dict, manager: dict) -> bool:
    row_email = _normalize_match(row.get("manager_email", ""))
    row_name = _normalize_match(row.get("manager_name", ""))
    manager_email = _normalize_match(manager.get("email", ""))
    manager_name = _normalize_match(manager.get("name", ""))
    return bool((manager_email and row_email == manager_email) or (not manager_email and manager_name and row_name == manager_name))


def _outreach_report_matches(row: dict, manager: dict) -> bool:
    row_email = _normalize_match(row.get("manager_email", ""))
    row_name = _normalize_match(row.get("manager_name", ""))
    manager_email = _normalize_match(manager.get("email", ""))
    manager_name = _normalize_match(manager.get("name", ""))
    return bool((manager_email and row_email == manager_email) or (not manager_email and manager_name and row_name == manager_name))


def _display_datetime_is_today(value: str, today: str) -> bool:
    return str(value or "").strip().startswith(today)


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public' AND table_name=?
        """,
        (table_name,),
    ).fetchone()
    return bool(row)


def _request_session_id(request: Request) -> str:
    return request.cookies.get("korda_session_id", "") if request else ""


def _assert_entity_lock(request: Request, actor: dict, entity_type: str, entity_id) -> dict | None:
    lock = get_entity_lock(entity_type, str(entity_id))
    if not lock:
        return None
    if lock.get("actor_email") == actor.get("email", ""):
        return None
    session_id = _request_session_id(request)
    if session_id and lock.get("session_id") == session_id:
        return None
    return lock


def _enforce_field_permissions(actor: dict, module: str, entity_type: str, incoming: dict, existing: dict | None = None):
    result = enforce_field_update_permissions(
        actor,
        module,
        entity_type,
        incoming,
        existing,
        has_field_permission_fn=has_field_permission,
        get_allowed_statuses_fn=get_allowed_statuses,
    )
    if result and not result.get("message"):
        result["message"] = explain_policy_error(result)
    return result


def _load_epl_waybills_for_links(project_ids: set[int] | None = None, client_id: int = 0) -> list[dict]:
    project_ids = {int(item) for item in (project_ids or set()) if int(item)}
    rows = []
    for row in _load_epl_waybill_rows():
        row_project_id = _safe_int(row.get("project_id"))
        row_client_id = _safe_int(row.get("client_id"))
        if client_id and row_client_id == _safe_int(client_id):
            rows.append(row)
            continue
        if project_ids and row_project_id in project_ids:
            rows.append(row)
    return rows


def _erp_stage_label(value: str) -> str:
    return {
        "request": "Заявка",
        "approval": "Согласование",
        "reserve": "Резерв",
        "purchase": "Закупка",
        "production": "Производство",
        "shipment": "Отгрузка",
        "payment": "Оплата",
        "done": "Закрыто",
    }.get(value or "", value or "Этап")


def _entity_label(value: str) -> str:
    return {
        "entity": "запись",
        "finance_payment": "платёж",
        "document": "документ канцелярии",
        "sales_document": "документ реализации",
        "purchase_order": "заказ поставщику",
        "production_order": "производственный заказ",
        "stock_reservation": "резерв склада",
        "nomenclature": "номенклатура",
        "client": "клиент",
        "project": "проект",
    }.get((value or "").strip(), value or "запись")


def _status_label(value: str) -> str:
    return {
        "queued": "в очереди",
        "retry": "повторная отправка",
        "failed": "ошибка",
        "processing": "в обработке",
        "conflict": "конфликт",
        "synced": "синхронизировано",
        "pending": "ожидает",
        "active": "активно",
        "done": "завершено",
    }.get((value or "").strip(), value or "неизвестно")


def _normalize_duplicate_key(value: str) -> str:
    return _normalize_spaces(value).lower()


def _normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def _resolve_telephony_context(conn, phone_number: str = "", client_id: int = 0, project_id: int = 0) -> dict:
    resolved = {"client_id": _safe_int(client_id), "project_id": _safe_int(project_id), "contact_name": ""}
    normalized_phone = _normalize_phone(phone_number)
    if not normalized_phone:
        return resolved
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute(
        """
        SELECT ct.id, ct.client_id, ct.name, ct.phone, cl.name AS client_name
        FROM contacts ct
        LEFT JOIN clients cl ON cl.id = ct.client_id
        WHERE COALESCE(ct.phone, '') != ''
        ORDER BY ct.id DESC
        """
    )
    contacts = [dict(row) for row in c.fetchall()]
    matched_rows = []
    for row in contacts:
        contact_phone = _normalize_phone(row.get("phone"))
        if not contact_phone:
            continue
        if normalized_phone == contact_phone or normalized_phone.endswith(contact_phone[-10:]) or contact_phone.endswith(normalized_phone[-10:]):
            matched_rows.append(row)
    if matched_rows:
        if resolved["client_id"]:
            preferred = next((row for row in matched_rows if _safe_int(row.get("client_id")) == resolved["client_id"]), None)
        else:
            preferred = None
        chosen = preferred or matched_rows[0]
        if not resolved["client_id"]:
            resolved["client_id"] = _safe_int(chosen.get("client_id"))
        resolved["contact_name"] = chosen.get("name") or ""
    if resolved["client_id"] and not resolved["project_id"]:
        c.execute("SELECT name FROM clients WHERE id=?", (resolved["client_id"],))
        client_row = c.fetchone()
        client_name = (client_row["name"] if client_row else "") if client_row else ""
        if client_name:
            c.execute("SELECT id FROM projects WHERE client=? ORDER BY id DESC LIMIT 1", (client_name,))
            project_row = c.fetchone()
            if project_row:
                resolved["project_id"] = _safe_int(project_row["id"])
    return resolved


def _resolve_bank_line_context(conn, counterparty: str = "", client_id: int = 0, payment_id: int = 0, amount: float = 0, direction: str = "incoming") -> dict:
    resolved = {"client_id": _safe_int(client_id), "payment_id": _safe_int(payment_id)}
    c = conn.cursor()
    if not resolved["client_id"] and (counterparty or "").strip():
        target = _normalize_duplicate_key(counterparty)
        c.execute("SELECT id, name FROM clients ORDER BY id DESC")
        for row in c.fetchall():
            candidate_id, candidate_name = _safe_int(row[0]), row[1] or ""
            normalized_name = _normalize_duplicate_key(candidate_name)
            if normalized_name and (normalized_name == target or normalized_name in target or target in normalized_name):
                resolved["client_id"] = candidate_id
                break
    if not resolved["payment_id"] and _safe_float(amount) > 0:
        expected_kind = "incoming" if (direction or "incoming") == "incoming" else "outgoing"
        c.execute(
            """
            SELECT id
            FROM finance_payments
            WHERE ABS(amount - ?) < 0.0001
              AND kind = ?
              AND (? = 0 OR client_id = ?)
              AND status IN ('planned', 'issued', 'partially_paid', 'overdue')
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (_safe_float(amount), expected_kind, resolved["client_id"], resolved["client_id"]),
        )
        row = c.fetchone()
        if row:
            resolved["payment_id"] = _safe_int(row[0])
    return resolved


def _load_users_directory():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT email, name, role, status, is_head, hourly_rate FROM users ORDER BY name ASC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _custom_fields_map(custom_fields) -> dict[str, str]:
    mapping = {}
    for item in custom_fields or []:
        if not isinstance(item, dict):
            continue
        key = _normalize_match(item.get("name") or item.get("label") or "")
        if key:
            mapping[key] = _normalize_spaces(item.get("value") or "")
    return mapping


def _match_client_id(conn, client_name: str) -> int:
    normalized = _normalize_match(client_name)
    if not normalized:
        return 0
    c = conn.cursor()
    c.execute("SELECT id, name FROM clients")
    for row in c.fetchall():
        row_id = int(row[0] or 0)
        row_name = row[1] if len(row) > 1 else ""
        if _normalize_match(row_name) == normalized:
            return row_id
    return 0


def _sync_project_master_data(conn, project: dict, actor: dict | None = None) -> dict:
    return _sync_project_master_data_service(
        conn,
        project,
        actor,
        safe_int=_safe_int,
        safe_float=_safe_float,
        normalize_spaces=_normalize_spaces,
        ensure_client_reference_fn=_ensure_client_reference,
        extract_project_object_payload_fn=lambda payload: extract_project_object_payload_service(
            payload,
            normalize_spaces=_normalize_spaces,
            custom_fields_map=_custom_fields_map,
        ),
        user_email_by_name_fn=lambda db_conn, user_name: user_email_by_name_service(
            db_conn,
            user_name,
            normalize_spaces=_normalize_spaces,
        ),
        propagate_project_master_links_fn=_propagate_project_master_links,
    )


def _resolve_master_context(conn, project_id: int = 0, client_id: int = 0, contract_id: int = 0, object_id: int = 0, autocreate: bool = True) -> dict:
    return _resolve_master_context_service(
        conn,
        project_id,
        client_id,
        contract_id,
        object_id,
        autocreate,
        safe_int=_safe_int,
        load_project_row=_load_project_row,
        project_payload=_project_payload,
        match_client_id=_match_client_id,
        sync_project_master_data_fn=_sync_project_master_data,
    )


def _load_contract_directory():
    return load_contract_directory_service(DB_NAME, json_load=_json_load)


def _load_business_objects_directory(client_id: int = 0):
    return load_business_objects_directory_service(DB_NAME, client_id)


def _user_email_by_name(conn, user_name: str) -> str:
    return user_email_by_name_service(conn, user_name, normalize_spaces=_normalize_spaces)


def _ensure_client_reference(conn, client_name: str) -> int:
    return ensure_client_reference_service(conn, client_name, normalize_spaces=_normalize_spaces, match_client_id=_match_client_id)


def _propagate_project_master_links(conn, project_id: int, client_id: int, contract_id: int, object_id: int):
    return propagate_project_master_links_service(conn, project_id, client_id, contract_id, object_id)


def _replace_project_client_name(conn, old_names: list[str], new_name: str):
    return replace_project_client_name_service(conn, old_names, new_name)


def _sync_contract_back_to_project(conn, contract_id: int):
    return sync_contract_back_to_project_service(
        conn,
        contract_id,
        safe_int=_safe_int,
        safe_float=_safe_float,
        project_payload=_project_payload,
    )


def _default_scenario_for_request_type(request_type: str) -> list[str]:
    request_type = (request_type or "").strip().lower()
    mapping = {
        "purchase": ["request", "approval", "reserve", "purchase", "payment"],
        "production": ["request", "approval", "reserve", "production", "shipment", "payment"],
        "sales": ["request", "approval", "shipment", "payment"],
        "service": ["request", "approval", "production", "payment"],
    }
    return mapping.get(request_type, ["request", "approval", "purchase", "shipment", "payment"])


def _load_import_rows(upload: UploadFile):
    filename = (upload.filename or "").lower()
    raw = upload.file.read()
    text = raw.decode("utf-8-sig", errors="ignore")
    if filename.endswith(".json"):
        data = json.loads(text or "[]")
        return data if isinstance(data, list) else []
    if filename.endswith(".csv") or filename.endswith(".txt"):
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]
    raise HTTPException(status_code=400, detail="Поддерживаются только CSV и JSON")


def _normalize_client_row(row: dict):
    return {
        "name": _normalize_spaces(row.get("name") or row.get("client") or row.get("Название") or row.get("Контрагент") or ""),
        "inn": _normalize_spaces(str(row.get("inn") or row.get("ИНН") or "")),
        "kpp": _normalize_spaces(str(row.get("kpp") or row.get("КПП") or "")),
        "ogrn": _normalize_spaces(str(row.get("ogrn") or row.get("ОГРН") or "")),
        "legal_address": _normalize_spaces(row.get("legal_address") or row.get("address") or row.get("Юридический адрес") or row.get("Адрес") or ""),
        "contact": _normalize_spaces(row.get("contact") or row.get("contacts") or row.get("Контакты") or row.get("email") or ""),
    }


def _lookup_company_by_inn(inn: str) -> dict:
    normalized_inn = re.sub(r"\D+", "", str(inn or ""))
    if not normalized_inn:
        return {"error": "inn_required"}
    if len(normalized_inn) not in {10, 12}:
        return {"error": "inn_invalid"}
    if not DADATA_TOKEN:
        return {"status": "integration_not_configured"}
    headers = {
        "Authorization": f"Token {DADATA_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if DADATA_SECRET:
        headers["X-Secret"] = DADATA_SECRET
    payload = {"query": normalized_inn}
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json() if response.content else {}
    except Exception as exc:
        return {"error": f"lookup_failed: {exc}"}
    suggestions = data.get("suggestions") if isinstance(data, dict) else []
    if not suggestions:
        return {"error": "not_found"}
    item = suggestions[0] or {}
    item_data = item.get("data") or {}
    address_data = item_data.get("address") or {}
    managers = item_data.get("management") or {}
    result = {
        "inn": normalized_inn,
        "name": _normalize_spaces(item.get("value") or item_data.get("name", {}).get("short_with_opf") or item_data.get("name", {}).get("full_with_opf") or ""),
        "kpp": _normalize_spaces(item_data.get("kpp") or ""),
        "ogrn": _normalize_spaces(item_data.get("ogrn") or ""),
        "legal_address": _normalize_spaces(address_data.get("unrestricted_value") or address_data.get("value") or ""),
        "contact": _normalize_spaces(managers.get("name") or ""),
        "status": _normalize_spaces((item_data.get("state") or {}).get("status") or ""),
    }
    return {"status": "success", "client": result}


def _normalize_nomenclature_row(row: dict):
    def number(value, default=0.0):
        try:
            return float(str(value or default).replace(",", "."))
        except Exception:
            return float(default)
    return {
        "name": _normalize_spaces(row.get("name") or row.get("Наименование") or row.get("product") or ""),
        "article": _normalize_spaces(row.get("article") or row.get("Артикул") or row.get("sku") or ""),
        "unit": _normalize_spaces(row.get("unit") or row.get("Ед. изм.") or row.get("uom") or "шт") or "шт",
        "price": number(row.get("price") or row.get("Цена") or 0),
        "stock": number(row.get("stock") or row.get("Остаток") or 0),
        "currency": _normalize_spaces(row.get("currency") or row.get("Валюта") or "RUB") or "RUB",
        "group_name": _normalize_spaces(row.get("group_name") or row.get("Группа") or row.get("category") or ""),
        "default_warehouse": _normalize_spaces(row.get("default_warehouse") or row.get("Склад") or row.get("warehouse") or ""),
    }




def _rewrite_project_nomenclature_articles(conn, article_map: dict[str, dict]):
    c = conn.cursor()
    c.execute("SELECT id, nomenclature FROM projects")
    rows = c.fetchall()
    for project_id, raw_items in rows:
        try:
            items = json.loads(raw_items or "[]")
        except Exception:
            items = []
        changed = False
        for item in items:
            article = _normalize_spaces(item.get("article") or "")
            if article in article_map:
                master = article_map[article]
                item["article"] = master["article"]
                if master.get("name"):
                    item["name"] = master["name"]
                changed = True
        if changed:
            c.execute("UPDATE projects SET nomenclature=? WHERE id=?", (json.dumps(items, ensure_ascii=False), project_id))


def _rewrite_erp_payload_articles(conn, article_map: dict[str, dict]):
    c = conn.cursor()
    c.execute("SELECT id, payload FROM erp_process_runs")
    rows = c.fetchall()
    for process_id, payload_raw in rows:
        try:
            payload = json.loads(payload_raw or "{}")
        except Exception:
            payload = {}
        article = _normalize_spaces(payload.get("item_article") or "")
        if article and article in article_map:
            payload["item_article"] = article_map[article]["article"]
            if article_map[article].get("name"):
                payload["item_name"] = article_map[article]["name"]
            c.execute("UPDATE erp_process_runs SET payload=?, updated_at=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), int(time.time()), process_id))


def _is_overdue(status: str, due_date: str) -> bool:
    if status == "paid" or not due_date:
        return False
    try:
        due = datetime.strptime(due_date, "%d.%m.%Y")
        return due.date() < datetime.now().date()
    except Exception:
        return False


def _load_finance_rows():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            fp.*,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract,
            COALESCE(cl.name, '') AS client_name,
            COALESCE(le.short_name, le.name, '') AS legal_entity_name,
            COALESCE(bu.name, '') AS business_unit_name,
            COALESCE(ta.name, '') AS treasury_article_name,
            COALESCE(vr.name, '') AS vat_rate_name,
            COALESCE(vr.rate, 0) AS vat_rate_value
        FROM finance_payments fp
        LEFT JOIN projects p ON p.id = fp.project_id
        LEFT JOIN clients cl ON cl.id = fp.client_id
        LEFT JOIN legal_entities le ON le.id = fp.legal_entity_id
        LEFT JOIN business_units bu ON bu.id = fp.business_unit_id
        LEFT JOIN treasury_articles ta ON ta.id = fp.treasury_article_id
        LEFT JOIN vat_rates vr ON vr.id = fp.vat_rate_id
        ORDER BY fp.created_at DESC, fp.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _parse_display_date(value: str):
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%Y %H:%M", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def _period_key_for_date(value: str = "") -> str:
    dt = _parse_display_date(value) or datetime.now()
    return dt.strftime("%Y-%m")


def _load_directory_rows(table_name: str, order_by: str = "id ASC") -> list[dict]:
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(f"SELECT * FROM {table_name} ORDER BY {order_by}")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _default_master_ids(conn) -> dict:
    c = conn.cursor()
    defaults = {
        "legal_entity_id": 0,
        "business_unit_id": 0,
        "treasury_article_id": 0,
        "vat_rate_id": 0,
    }
    c.execute("SELECT id FROM legal_entities WHERE is_active=1 ORDER BY id ASC LIMIT 1")
    row = c.fetchone()
    defaults["legal_entity_id"] = _safe_int(row[0]) if row else 0
    if defaults["legal_entity_id"]:
        c.execute("SELECT id FROM business_units WHERE is_active=1 AND legal_entity_id=? ORDER BY id ASC LIMIT 1", (defaults["legal_entity_id"],))
        row = c.fetchone()
        defaults["business_unit_id"] = _safe_int(row[0]) if row else 0
    c.execute("SELECT id FROM treasury_articles WHERE is_active=1 AND flow_kind='incoming' ORDER BY id ASC LIMIT 1")
    row = c.fetchone()
    defaults["treasury_article_id"] = _safe_int(row[0]) if row else 0
    c.execute("SELECT id FROM vat_rates WHERE is_active=1 AND is_default=1 ORDER BY id ASC LIMIT 1")
    row = c.fetchone()
    defaults["vat_rate_id"] = _safe_int(row[0]) if row else 0
    if not defaults["vat_rate_id"]:
        c.execute("SELECT id FROM vat_rates WHERE is_active=1 ORDER BY id ASC LIMIT 1")
        row = c.fetchone()
        defaults["vat_rate_id"] = _safe_int(row[0]) if row else 0
    return defaults


def _get_vat_rate_value(conn, vat_rate_id: int) -> float:
    if not vat_rate_id:
        return 0.0
    c = conn.cursor()
    c.execute("SELECT rate FROM vat_rates WHERE id=?", (vat_rate_id,))
    row = c.fetchone()
    return _safe_float(row[0]) if row else 0.0


def _resolve_finance_dimensions(conn, data: FinancePaymentData, context: dict) -> dict:
    defaults = _default_master_ids(conn)
    legal_entity_id = _safe_int(data.legal_entity_id) or defaults["legal_entity_id"]
    business_unit_id = _safe_int(data.business_unit_id) or defaults["business_unit_id"]
    treasury_article_id = _safe_int(data.treasury_article_id)
    if not treasury_article_id:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM treasury_articles WHERE is_active=1 AND flow_kind=? ORDER BY id ASC LIMIT 1",
            ("incoming" if data.kind == "incoming" else "outgoing",),
        )
        row = c.fetchone()
        treasury_article_id = _safe_int(row[0]) if row else defaults["treasury_article_id"]
    vat_rate_id = _safe_int(data.vat_rate_id) or defaults["vat_rate_id"]
    return {
        "project_id": _safe_int(context.get("project_id")),
        "client_id": _safe_int(context.get("client_id")),
        "contract_id": _safe_int(context.get("contract_id")),
        "object_id": _safe_int(context.get("object_id")),
        "legal_entity_id": legal_entity_id,
        "business_unit_id": business_unit_id,
        "treasury_article_id": treasury_article_id,
        "vat_rate_id": vat_rate_id,
        "source_document_type": (data.source_document_type or "").strip(),
        "source_document_id": _safe_int(data.source_document_id),
    }


def _resolve_ops_scope_dimensions(conn, legal_entity_id: int = 0, business_unit_id: int = 0) -> dict:
    defaults = _default_master_ids(conn)
    resolved_legal_entity_id = _safe_int(legal_entity_id) or defaults["legal_entity_id"]
    resolved_business_unit_id = _safe_int(business_unit_id)
    c = conn.cursor()
    if resolved_business_unit_id:
        c.execute("SELECT legal_entity_id FROM business_units WHERE id=?", (resolved_business_unit_id,))
        row = c.fetchone()
        if row:
            business_unit_legal_entity = _safe_int(row[0])
            if business_unit_legal_entity and not resolved_legal_entity_id:
                resolved_legal_entity_id = business_unit_legal_entity
    if resolved_legal_entity_id and not resolved_business_unit_id:
        c.execute(
            "SELECT id FROM business_units WHERE is_active=1 AND legal_entity_id=? ORDER BY id ASC LIMIT 1",
            (resolved_legal_entity_id,),
        )
        row = c.fetchone()
        resolved_business_unit_id = _safe_int(row[0]) if row else 0
    if resolved_business_unit_id and resolved_legal_entity_id:
        c.execute("SELECT legal_entity_id FROM business_units WHERE id=?", (resolved_business_unit_id,))
        row = c.fetchone()
        if row and _safe_int(row[0]) and _safe_int(row[0]) != resolved_legal_entity_id:
            resolved_business_unit_id = 0
            c.execute(
                "SELECT id FROM business_units WHERE is_active=1 AND legal_entity_id=? ORDER BY id ASC LIMIT 1",
                (resolved_legal_entity_id,),
            )
            row = c.fetchone()
            resolved_business_unit_id = _safe_int(row[0]) if row else 0
    return {
        "legal_entity_id": resolved_legal_entity_id,
        "business_unit_id": resolved_business_unit_id,
    }


def _account_pair_for_payment(kind: str, category: str) -> tuple[str, str]:
    if kind == "incoming":
        if category in {"invoice", "act"}:
            return ("62.01", "90.01")
        return ("51", "62.01")
    if category in {"expense", "payment"}:
        return ("60.01", "51")
    return ("76.09", "51")


def _is_period_closed(conn, period_key: str) -> bool:
    c = conn.cursor()
    c.execute("SELECT status FROM accounting_periods WHERE period_key=?", (period_key,))
    row = c.fetchone()
    return bool(row and (row[0] or "") == "closed")


def _ensure_accounting_period(conn, period_key: str):
    if not period_key:
        period_key = _period_key_for_date("")
    c = conn.cursor()
    c.execute("SELECT id FROM accounting_periods WHERE period_key=?", (period_key,))
    if c.fetchone():
        return
    now = int(time.time())
    c.execute(
        "INSERT INTO accounting_periods (period_key, status, opened_at, closed_at, closed_by, comment) VALUES (?, 'open', ?, 0, '', '')",
        (period_key, now),
    )


def _vat_amount_for_payment(conn, amount: float, vat_rate_id: int) -> float:
    rate = _get_vat_rate_value(conn, vat_rate_id)
    if rate <= 0:
        return 0.0
    return round(_safe_float(amount) * rate / (100 + rate), 2)


def _payment_exchange_state(status: str) -> str:
    if status == "paid":
        return "ready"
    if status in {"issued", "partially_paid"}:
        return "pending"
    return "draft"


def _build_finance_sync_payload(payment: dict) -> dict:
    return build_finance_sync_payload_service(payment)


def _build_purchase_sync_payload(purchase: dict) -> dict:
    return build_purchase_sync_payload_service(purchase)


def _build_sales_sync_payload(document: dict) -> dict:
    return build_sales_sync_payload_service(document)


def _build_document_sync_payload(document: dict) -> dict:
    return build_document_sync_payload_service(document)


def _build_production_sync_payload(order: dict) -> dict:
    return build_production_sync_payload_service(order)


def _build_reservation_sync_payload(reservation: dict) -> dict:
    return build_reservation_sync_payload_service(reservation)


def _build_nomenclature_sync_payload(item: dict) -> dict:
    return build_nomenclature_sync_payload_service(item)


def _build_simple_nsi_sync_payload(item: dict) -> dict:
    return build_simple_nsi_sync_payload_service(item)


def _build_employee_sync_payload(item: dict) -> dict:
    return build_employee_sync_payload_service(item)


def _build_position_sync_payload(item: dict) -> dict:
    return build_position_sync_payload_service(item)


def _build_characteristic_sync_payload(item: dict) -> dict:
    return build_characteristic_sync_payload_service(item)


def _build_storage_cell_sync_payload(item: dict) -> dict:
    return build_storage_cell_sync_payload_service(item)


def _build_income_expense_article_sync_payload(item: dict) -> dict:
    return build_income_expense_article_sync_payload_service(item)


def _build_cfr_sync_payload(item: dict) -> dict:
    return build_cfr_sync_payload_service(item)


def _build_operation_type_sync_payload(item: dict) -> dict:
    return build_operation_type_sync_payload_service(item)


def _build_bank_account_sync_payload(item: dict) -> dict:
    return build_bank_account_sync_payload_service(item)


def _log_sync_event(conn, queue_id: int, system_name: str, entity_type: str, entity_id: int, state: str, message: str, payload: dict | None = None, external_id: str = ""):
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO integration_sync_log (
            queue_id, system_name, entity_type, entity_id, state, message, payload, external_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            queue_id,
            system_name,
            entity_type,
            entity_id,
            state,
            (message or "")[:500],
            json.dumps(payload or {}, ensure_ascii=False),
            external_id or "",
            int(time.time()),
        ),
    )


def _stable_json_payload(payload) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_checksum(payload) -> str:
    return hashlib.sha256(_stable_json_payload(payload).encode("utf-8")).hexdigest()


def _integration_idempotency_key(system_name: str, entity_type: str, entity_id, direction: str, payload: dict, provided: str = "") -> str:
    clean = (provided or "").strip()
    if clean:
        return clean[:180]
    fingerprint = _payload_checksum({"entity_type": entity_type, "entity_id": entity_id, "direction": direction, "payload": payload})
    return f"{system_name}:{direction}:{entity_type}:{entity_id}:{fingerprint[:24]}"[:180]


def _sync_row_to_dict(row, columns: list[str]) -> dict:
    if not row:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return dict(zip(columns, row))


def _get_idempotency_record(conn, system_name: str, idempotency_key: str) -> dict:
    if not idempotency_key:
        return {}
    columns = ["id", "system_name", "idempotency_key", "direction", "queue_id", "request_hash", "response_payload", "status", "created_at", "updated_at"]
    c = conn.cursor()
    c.execute(
        """
        SELECT id, system_name, idempotency_key, direction, queue_id, request_hash, response_payload, status, created_at, updated_at
        FROM integration_idempotency_keys
        WHERE system_name=? AND idempotency_key=?
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (system_name or "1C", idempotency_key),
    )
    return _sync_row_to_dict(c.fetchone(), columns)


def _upsert_idempotency_record(conn, system_name: str, idempotency_key: str, direction: str, queue_id: int, request_hash: str, status: str, response_payload: dict | None = None) -> int:
    if not idempotency_key:
        return 0
    now = int(time.time())
    c = conn.cursor()
    existing = _get_idempotency_record(conn, system_name, idempotency_key)
    response_json = json.dumps(response_payload or {}, ensure_ascii=False)
    if existing:
        record_id = _safe_int(existing.get("id"))
        c.execute(
            """
            UPDATE integration_idempotency_keys
            SET direction=?, queue_id=?, request_hash=?, response_payload=?, status=?, updated_at=?
            WHERE id=?
            """,
            (direction or existing.get("direction") or "outbound", queue_id or _safe_int(existing.get("queue_id")), request_hash or existing.get("request_hash", ""), response_json, status or existing.get("status", "received"), now, record_id),
        )
        return record_id
    c.execute(
        """
        INSERT INTO integration_idempotency_keys (
            system_name, idempotency_key, direction, queue_id, request_hash, response_payload, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (system_name or "1C", idempotency_key, direction or "outbound", queue_id, request_hash or "", response_json, status or "received", now, now),
    )
    return c.lastrowid


def _record_integration_error_event(conn, queue_id: int, system_name: str, entity_type: str, entity_id: int, message: str, payload: dict | None = None, severity: str = "error", error_code: str = "", traceback_text: str = "") -> int:
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        INSERT INTO integration_error_events (
            queue_id, system_name, entity_type, entity_id, severity, error_code, message,
            traceback_text, payload, status, resolved_at, resolved_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 0, '', ?)
        """,
        (
            _safe_int(queue_id),
            system_name or "1C",
            entity_type or "",
            _safe_int(entity_id),
            severity or "error",
            (error_code or "")[:120],
            (message or "")[:1000],
            (traceback_text or "")[:2000],
            json.dumps(payload or {}, ensure_ascii=False),
            now,
        ),
    )
    return c.lastrowid


def _record_integration_consistency(conn, queue_id: int, system_name: str, entity_type: str, entity_id: int, external_id: str, state: str, checksum_local: str, checksum_external: str, details: dict | None = None) -> int:
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        INSERT INTO integration_consistency_checks (
            queue_id, system_name, entity_type, entity_id, external_id, state,
            checksum_local, checksum_external, details_json, checked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _safe_int(queue_id),
            system_name or "1C",
            entity_type or "",
            _safe_int(entity_id),
            external_id or "",
            state or "consistent",
            checksum_local or "",
            checksum_external or "",
            json.dumps(details or {}, ensure_ascii=False),
            now,
        ),
    )
    return c.lastrowid


def _enqueue_sync_job(conn, entity_type: str, entity_id: int, payload: dict, created_by: str = "", mapping_key: str = "", system_name: str = "1C", direction: str = "outbound", idempotency_key: str = "", correlation_id: str = "", connector_id: int = 0, attempt_limit: int = 5, priority: int = 100) -> int:
    c = conn.cursor()
    now = int(time.time())
    checksum = _payload_checksum(payload)
    idempotency_key = _integration_idempotency_key(system_name, entity_type, entity_id, direction, payload, idempotency_key)
    request_hash = _payload_checksum({"entity_type": entity_type, "entity_id": entity_id, "direction": direction, "payload": payload})
    existing_idempotency = _get_idempotency_record(conn, system_name, idempotency_key)
    existing_queue_id = _safe_int(existing_idempotency.get("queue_id")) if existing_idempotency else 0
    if existing_queue_id:
        c.execute("SELECT id FROM integration_sync_queue WHERE id=? LIMIT 1", (existing_queue_id,))
        if c.fetchone():
            _log_sync_event(conn, existing_queue_id, system_name, entity_type, _safe_int(entity_id), "idempotent", "Повторная постановка пропущена по idempotency_key", payload)
            return existing_queue_id
    c.execute(
        """
        INSERT INTO integration_sync_queue (
            system_name, entity_type, entity_id, direction, payload, mapping_key, state,
            retry_count, last_error, external_id, next_retry_at, locked_at, created_by, created_at, updated_at,
            idempotency_key, correlation_id, attempt_limit, priority, last_attempt_at, processed_at,
            checksum, consistency_state, connector_id
        ) VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, '', '', ?, 0, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 'pending', ?)
        """,
        (
            system_name or "1C",
            entity_type,
            entity_id,
            direction or "outbound",
            json.dumps(payload or {}, ensure_ascii=False),
            mapping_key or f"{entity_type}:{entity_id}",
            now,
            created_by or "",
            now,
            now,
            idempotency_key,
            correlation_id or f"{system_name or '1C'}-{entity_type}-{entity_id}-{now}",
            max(1, _safe_int(attempt_limit) or 5),
            max(1, _safe_int(priority) or 100),
            checksum,
            _safe_int(connector_id),
        ),
    )
    queue_id = c.lastrowid
    _upsert_idempotency_record(conn, system_name, idempotency_key, direction, queue_id, request_hash, "queued", {"queue_id": queue_id})
    _log_sync_event(conn, queue_id, system_name, entity_type, entity_id, "queued", "Документ поставлен в очередь обмена", payload)
    return queue_id


def _upsert_finance_sync_job(conn, payment: dict, actor_email: str = ""):
    payload = _build_finance_sync_payload(payment)
    c = conn.cursor()
    now = int(time.time())
    payment_id = _safe_int(payment.get("id"))
    checksum = _payload_checksum(payload)
    idempotency_key = _integration_idempotency_key("1C", "finance_payment", payment_id, "outbound", payload)
    request_hash = _payload_checksum({"entity_type": "finance_payment", "entity_id": payment_id, "direction": "outbound", "payload": payload})
    c.execute(
        """
        SELECT id, retry_count
        FROM integration_sync_queue
        WHERE system_name='1C' AND entity_type='finance_payment' AND entity_id=? AND state IN ('queued', 'retry', 'failed', 'processing')
        ORDER BY id DESC LIMIT 1
        """,
        (payment_id,),
    )
    row = c.fetchone()
    exchange_state = _payment_exchange_state(payment.get("status", ""))
    if exchange_state == "draft":
        c.execute(
            "UPDATE finance_payments SET exchange_state=?, external_sync_id='' WHERE id=?",
            (exchange_state, payment_id),
        )
        return 0
    if row:
        queue_id = _safe_int(row[0])
        c.execute(
            """
            UPDATE integration_sync_queue
            SET payload=?, state='queued', last_error='', next_retry_at=?, locked_at=0, updated_at=?,
                idempotency_key=?, checksum=?, consistency_state='pending',
                correlation_id=CASE WHEN correlation_id='' THEN ? ELSE correlation_id END,
                attempt_limit=CASE WHEN attempt_limit=0 THEN 5 ELSE attempt_limit END
            WHERE id=?
            """,
            (json.dumps(payload, ensure_ascii=False), now, now, idempotency_key, checksum, f"1C-finance_payment-{payment_id}-{now}", queue_id),
        )
        _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, "queued", {"queue_id": queue_id})
        _log_sync_event(conn, queue_id, "1C", "finance_payment", payment_id, "queued", "Очередь обмена обновлена", payload)
    else:
        queue_id = _enqueue_sync_job(conn, "finance_payment", payment_id, payload, actor_email, f"finance:{payment.get('id')}")
    c.execute(
        "UPDATE finance_payments SET exchange_state=? WHERE id=?",
        ("queued", payment_id),
    )
    return queue_id


def _sync_entity_meta(entity_type: str) -> dict | None:
    return sync_entity_meta_service(entity_type)


def _load_sync_entity_row(conn, entity_type: str, entity_id):
    meta = _sync_entity_meta(entity_type)
    if not meta:
        return None
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    if entity_type == "nomenclature":
        if isinstance(entity_id, str) and entity_id.strip():
            c.execute("SELECT * FROM nomenclature WHERE article=? ORDER BY id DESC LIMIT 1", (entity_id,))
        else:
            c.execute("SELECT * FROM nomenclature WHERE id=? ORDER BY id DESC LIMIT 1", (_safe_int(entity_id),))
    else:
        c.execute(
            f"SELECT * FROM {meta['table']} WHERE {meta['id_column']}=? ORDER BY {meta['id_column']} DESC LIMIT 1",
            (entity_id,),
        )
    row = c.fetchone()
    return dict(row) if row else None


def _set_sync_entity_state(conn, entity_type: str, entity_id, exchange_state: str, external_id: str = ""):
    meta = _sync_entity_meta(entity_type)
    if not meta:
        return
    c = conn.cursor()
    params = [exchange_state]
    assignments = [f"{meta['state_column']}=?"]
    if meta.get("external_column"):
        assignments.append(f"{meta['external_column']}=?")
        params.append(external_id or "")
    if meta.get("updated_column"):
        assignments.append(f"{meta['updated_column']}=?")
        params.append(int(time.time()))
    params.append(entity_id)
    if entity_type == "nomenclature" and not isinstance(entity_id, str):
        c.execute(
            f"UPDATE {meta['table']} SET {', '.join(assignments)} WHERE id=?",
            tuple(params),
        )
    else:
        c.execute(
            f"UPDATE {meta['table']} SET {', '.join(assignments)} WHERE {meta['id_column']}=?",
            tuple(params),
        )


def _upsert_entity_sync_job(conn, entity_type: str, entity_id, actor_email: str = "") -> int:
    meta = _sync_entity_meta(entity_type)
    entity = _load_sync_entity_row(conn, entity_type, entity_id)
    if not meta or not entity:
        return 0
    payload = meta["builder"](entity)
    queue_entity_id = _safe_int(entity.get("id") or entity_id)
    checksum = _payload_checksum(payload)
    idempotency_key = _integration_idempotency_key("1C", entity_type, queue_entity_id, "outbound", payload)
    request_hash = _payload_checksum({"entity_type": entity_type, "entity_id": queue_entity_id, "direction": "outbound", "payload": payload})
    c = conn.cursor()
    c.execute(
        """
        SELECT id
        FROM integration_sync_queue
        WHERE system_name='1C' AND entity_type=? AND entity_id=? AND state IN ('queued', 'retry', 'failed', 'processing', 'synced')
        ORDER BY id DESC LIMIT 1
        """,
        (entity_type, queue_entity_id),
    )
    row = c.fetchone()
    now = int(time.time())
    if row:
        queue_id = _safe_int(row[0])
        c.execute(
            """
            UPDATE integration_sync_queue
            SET payload=?, state='queued', last_error='', next_retry_at=?, locked_at=0, updated_at=?,
                idempotency_key=?, checksum=?, consistency_state='pending',
                correlation_id=CASE WHEN correlation_id='' THEN ? ELSE correlation_id END,
                attempt_limit=CASE WHEN attempt_limit=0 THEN 5 ELSE attempt_limit END
            WHERE id=?
            """,
            (json.dumps(payload, ensure_ascii=False), now, now, idempotency_key, checksum, f"1C-{entity_type}-{queue_entity_id}-{now}", queue_id),
        )
        _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, "queued", {"queue_id": queue_id})
        _log_sync_event(conn, queue_id, "1C", entity_type, _safe_int(entity.get("id") or 0), "queued", "Очередь обмена обновлена", payload)
    else:
        queue_id = _enqueue_sync_job(conn, entity_type, queue_entity_id, payload, actor_email, f"{entity_type}:{entity_id}")
    _set_sync_entity_state(conn, entity_type, entity_id, "queued", entity.get(meta.get("external_column", ""), ""))
    return queue_id


def _delete_sync_entity_cascade(conn, entity_type: str, entity_id):
    c = conn.cursor()
    c.execute(
        "DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type=? AND entity_id=?)",
        (entity_type, entity_id),
    )
    c.execute("DELETE FROM integration_sync_queue WHERE entity_type=? AND entity_id=?", (entity_type, entity_id))


def _generic_inbound_state_already_applied(conn, item: dict, entity_type: str) -> bool:
    meta = _sync_entity_meta(entity_type)
    if not meta:
        return False
    entity = _load_sync_entity_row(conn, entity_type, item.get("entity_id"))
    if not entity:
        return False
    external_id = (item.get("external_id") or "").strip()
    if external_id and meta.get("external_column") and (entity.get(meta["external_column"]) or "").strip() != external_id:
        return False
    expected_exchange_state = (item.get("exchange_state") or "synced").strip() or "synced"
    if (entity.get(meta["state_column"]) or "").strip() != expected_exchange_state:
        return False
    status_value = (item.get("status") or "").strip()
    if status_value and "status" in entity and (entity.get("status") or "").strip() != status_value:
        return False
    payload = item.get("payload") or {}
    if entity_type == "sales_document":
        payment_status = (payload.get("payment_status") or status_value or "").strip()
        if payment_status and (entity.get("payment_status") or "").strip() != payment_status:
            return False
    if entity_type == "production_order":
        stage_value = (payload.get("stage") or status_value or "").strip()
        if stage_value and (entity.get("stage") or "").strip() != stage_value:
            return False
    if entity_type == "nomenclature":
        comparable_fields = ("unit", "group_name", "default_warehouse")
        for field in comparable_fields:
            if payload.get(field) is not None and (entity.get(field) or "").strip() != str(payload.get(field) or "").strip():
                return False
        if payload.get("price") is not None and abs(_safe_float(entity.get("price")) - _safe_float(payload.get("price"))) > 0.0001:
            return False
    return True


def _finance_inbound_state_already_applied(conn, item: dict) -> bool:
    payment = _find_finance_payment_by_sync_item(conn, item)
    if not payment:
        return False
    external_id = (item.get("external_id") or "").strip()
    if external_id and (payment.get("external_sync_id") or "").strip() != external_id:
        return False
    expected_status = _normalize_finance_status(item.get("status"), payment.get("status", "planned"))
    if expected_status and (payment.get("status") or "").strip() != expected_status:
        return False
    inbound_amount = _safe_float(item.get("amount"))
    if inbound_amount and abs(_safe_float(payment.get("amount")) - inbound_amount) > 0.01:
        return False
    expected_currency = (item.get("currency") or "").strip()
    if expected_currency and (payment.get("currency") or "").strip() != expected_currency:
        return False
    expected_due_date = (item.get("due_date") or "").strip()
    if expected_due_date and (payment.get("due_date") or "").strip() != expected_due_date:
        return False
    expected_paid_date = (item.get("paid_date") or "").strip()
    if expected_paid_date and (payment.get("paid_date") or "").strip() != expected_paid_date:
        return False
    return (payment.get("exchange_state") or "").strip() == "synced"


def _integration_batch_state_already_applied(conn, items: list[dict]) -> bool:
    if not items:
        return True
    for item in items:
        entity_type = (item.get("entity_type") or "").strip()
        if entity_type == "finance_payment":
            if not _finance_inbound_state_already_applied(conn, item):
                return False
            continue
        if not _generic_inbound_state_already_applied(conn, item, entity_type):
            return False
    return True


def _apply_generic_inbound_sync_item(conn, item: dict, actor_email: str = "", source_system: str = "1C") -> dict:
    item = _normalize_inbound_sync_item(item, "")
    if item.get("_validation_errors"):
        return {"state": "conflict", "reason": "validation_failed", "errors": item.get("_validation_errors") or [], "entity_type": item.get("entity_type") or ""}
    entity_type = (item.get("entity_type") or "").strip()
    meta = _sync_entity_meta(entity_type)
    payload = {key: value for key, value in item.items() if not key.startswith("_")}
    idempotency_key = _integration_idempotency_key(source_system, entity_type or "unknown", item.get("entity_id") or item.get("external_id") or 0, "inbound", payload, item.get("idempotency_key", ""))
    request_hash = _payload_checksum({"source_system": source_system, "direction": "inbound", "payload": payload})
    existing_idempotency = _get_idempotency_record(conn, source_system, idempotency_key)
    if existing_idempotency and existing_idempotency.get("request_hash") == request_hash and existing_idempotency.get("status") in {"applied", "inbound_applied"}:
        if _generic_inbound_state_already_applied(conn, payload, entity_type):
            cached = _json_load(existing_idempotency.get("response_payload"), {})
            cached["idempotent"] = True
            return cached or {"state": "applied", "idempotent": True, "entity_type": entity_type}
    if existing_idempotency and existing_idempotency.get("request_hash") and existing_idempotency.get("request_hash") != request_hash:
        _record_integration_error_event(conn, _safe_int(existing_idempotency.get("queue_id")), source_system, entity_type or "unknown", _safe_int(item.get("entity_id")), "Повторный idempotency_key пришёл с другим payload", payload, "critical", "idempotency_hash_mismatch")
        return {"state": "conflict", "reason": "idempotency_hash_mismatch", "entity_type": entity_type}
    if not meta:
        _log_sync_event(conn, 0, source_system, entity_type or "unknown", _safe_int(item.get("entity_id")), "conflict", "Неподдерживаемый тип сущности для inbound sync", payload, (item.get("external_id") or "").strip())
        _record_integration_error_event(conn, 0, source_system, entity_type or "unknown", _safe_int(item.get("entity_id")), "Неподдерживаемый тип сущности для inbound sync", payload, "warning", "unsupported_entity")
        return {"state": "conflict", "reason": "unsupported_entity", "entity_type": entity_type}
    entity_id = item.get("entity_id")
    entity = _load_sync_entity_row(conn, entity_type, entity_id)
    if not entity:
        external_id = (item.get("external_id") or "").strip()
        if external_id and meta.get("external_column"):
            c = conn.cursor()
            c.execute(
                f"SELECT {meta['id_column']} FROM {meta['table']} WHERE {meta['external_column']}=? ORDER BY {meta['id_column']} DESC LIMIT 1",
                (external_id,),
            )
            row = c.fetchone()
            if row:
                entity_id = row[0]
                entity = _load_sync_entity_row(conn, entity_type, entity_id)
    if not entity:
        _log_sync_event(conn, 0, source_system, entity_type, _safe_int(item.get("entity_id")), "conflict", "Входящий документ 1С не удалось сопоставить с сущностью CRM", payload, (item.get("external_id") or "").strip())
        _record_integration_error_event(conn, 0, source_system, entity_type, _safe_int(item.get("entity_id")), "Входящий документ 1С не удалось сопоставить с сущностью CRM", payload, "warning", "entity_not_found")
        return {"state": "conflict", "reason": "entity_not_found", "entity_type": entity_type}
    c = conn.cursor()
    queue_id = 0
    queue_entity_id = _safe_int(entity.get("id") or item.get("entity_id"))
    c.execute(
        """
        SELECT id
        FROM integration_sync_queue
        WHERE system_name='1C' AND entity_type=? AND entity_id=?
        ORDER BY updated_at DESC, id DESC LIMIT 1
        """,
        (entity_type, queue_entity_id),
    )
    row = c.fetchone()
    if row:
        queue_id = _safe_int(row[0])
    external_id = (item.get("external_id") or entity.get(meta.get("external_column", ""), "") or "").strip()
    exchange_state = (item.get("exchange_state") or "synced").strip() or "synced"
    updates = []
    params = []
    status_value = (item.get("status") or "").strip()
    if status_value and "status" in entity:
        updates.append("status=?")
        params.append(status_value)
    comment_value = (item.get("comment") or "").strip()
    if comment_value and "comment" in entity:
        merged_comment = "\n".join([part for part in [entity.get("comment", "").strip(), f"[{source_system}] {comment_value}"] if part]).strip()
        updates.append("comment=?")
        params.append(merged_comment[:1000])
    if entity_type == "sales_document":
        payment_status = (item.get("payload") or {}).get("payment_status") or status_value
        if payment_status and "payment_status" in entity:
            updates.append("payment_status=?")
            params.append(payment_status)
    if entity_type == "production_order":
        stage_value = (item.get("payload") or {}).get("stage") or status_value
        if stage_value and "stage" in entity:
            updates.append("stage=?")
            params.append(stage_value)
    if entity_type == "nomenclature":
        inbound = item.get("payload") or {}
        if inbound.get("unit") is not None:
            updates.append("unit=?")
            params.append((inbound.get("unit") or entity.get("unit") or "шт").strip() or "шт")
        if inbound.get("price") is not None:
            updates.append("price=?")
            params.append(_safe_float(inbound.get("price")))
        if inbound.get("group_name") is not None:
            updates.append("group_name=?")
            params.append((inbound.get("group_name") or "").strip())
        if inbound.get("default_warehouse") is not None:
            updates.append("default_warehouse=?")
            params.append((inbound.get("default_warehouse") or "").strip())
    updates.append(f"{meta['state_column']}=?")
    params.append(exchange_state)
    if meta.get("external_column"):
        updates.append(f"{meta['external_column']}=?")
        params.append(external_id)
    if meta.get("updated_column"):
        updates.append(f"{meta['updated_column']}=?")
        params.append(int(time.time()))
    params.append(entity.get(meta["id_column"]))
    c.execute(
        f"UPDATE {meta['table']} SET {', '.join(updates)} WHERE {meta['id_column']}=?",
        tuple(params),
    )
    c.execute(
        """
        UPDATE integration_sync_queue
        SET state='synced', direction='outbound', external_id=?, last_error='', locked_at=0, next_retry_at=0,
            processed_at=?, updated_at=?, consistency_state='consistent'
        WHERE system_name='1C' AND entity_type=? AND entity_id=?
        """,
        (external_id, int(time.time()), int(time.time()), entity_type, _safe_int(entity.get("id") or 0)),
    )
    _log_sync_event(conn, queue_id, source_system, entity_type, _safe_int(entity.get("id") or 0), "inbound_synced", "Входящий ответ 1С применён к сущности", payload, external_id)
    outcome = {"state": "applied", "entity_type": entity_type, "entity_id": entity.get(meta["id_column"])}
    _upsert_idempotency_record(conn, source_system, idempotency_key, "inbound", queue_id, request_hash, "applied", outcome)
    _record_integration_consistency(conn, queue_id, source_system, entity_type, _safe_int(entity.get("id") or 0), external_id, "consistent", _payload_checksum(meta["builder"](_load_sync_entity_row(conn, entity_type, entity.get(meta["id_column"])) or entity)), _payload_checksum(meta["builder"](_load_sync_entity_row(conn, entity_type, entity.get(meta["id_column"])) or entity)), {"source": "inbound_apply"})
    return outcome


def _rebuild_finance_accounting_entries(conn, payment: dict, actor_email: str = "") -> dict:
    payment_id = _safe_int(payment.get("id"))
    period_key = _period_key_for_date(payment.get("paid_date") or payment.get("due_date") or "")
    _ensure_accounting_period(conn, period_key)
    if _is_period_closed(conn, period_key):
        raise HTTPException(status_code=400, detail="Период закрыт. Разносить проводки в закрытый период нельзя.")
    c = conn.cursor()
    c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
    purge_registers_for_source(conn, "finance_payment", payment_id)
    account_debit, account_credit = _account_pair_for_payment(payment.get("kind", ""), payment.get("category", ""))
    amount = round(_safe_float(payment.get("amount")), 2)
    vat_amount = _vat_amount_for_payment(conn, amount, _safe_int(payment.get("vat_rate_id")))
    entry_date = payment.get("paid_date") or payment.get("due_date") or _today_display()
    c.execute(
        """
        INSERT INTO accounting_entries (
            source_type, source_id, entry_date, period_key, legal_entity_id, business_unit_id, project_id,
            client_id, contract_id, object_id, treasury_article_id, vat_rate_id, account_debit,
            account_credit, amount, vat_amount, currency, description, posted_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "finance_payment",
            payment_id,
            entry_date,
            period_key,
            _safe_int(payment.get("legal_entity_id")),
            _safe_int(payment.get("business_unit_id")),
            _safe_int(payment.get("project_id")),
            _safe_int(payment.get("client_id")),
            _safe_int(payment.get("contract_id")),
            _safe_int(payment.get("object_id")),
            _safe_int(payment.get("treasury_article_id")),
            _safe_int(payment.get("vat_rate_id")),
            account_debit,
            account_credit,
            amount,
            vat_amount,
            payment.get("currency", "RUB"),
            payment.get("title", "") or "Финансовая операция",
            actor_email or "",
            int(time.time()),
        ),
    )
    entry_id = getattr(c, "lastrowid", 0) or 0
    if entry_id:
        register_accounting_entry_by_id(conn, entry_id, actor_email or "")
    else:
        rebuild_registers_for_source(conn, "finance_payment", payment_id, actor_email or "")
    c.execute("UPDATE finance_payments SET posted_at=?, updated_at=? WHERE id=?", (int(time.time()), int(time.time()), payment_id))
    return {"period_key": period_key, "vat_amount": vat_amount, "account_debit": account_debit, "account_credit": account_credit}


def _load_finance_master_data():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    payload = {
        "legal_entities": [dict(row) for row in c.execute("SELECT * FROM legal_entities WHERE is_active=1 ORDER BY name ASC").fetchall()],
        "business_units": [
            dict(row)
            for row in c.execute(
                """
                SELECT bu.*, COALESCE(le.short_name, le.name, '') AS legal_entity_name
                FROM business_units bu
                LEFT JOIN legal_entities le ON le.id = bu.legal_entity_id
                WHERE bu.is_active=1
                ORDER BY bu.name ASC
                """
            ).fetchall()
        ],
        "treasury_articles": [dict(row) for row in c.execute("SELECT * FROM treasury_articles WHERE is_active=1 ORDER BY flow_kind ASC, name ASC").fetchall()],
        "vat_rates": [dict(row) for row in c.execute("SELECT * FROM vat_rates WHERE is_active=1 ORDER BY is_default DESC, rate ASC, id ASC").fetchall()],
        "account_chart": [dict(row) for row in c.execute("SELECT * FROM account_chart WHERE is_active=1 ORDER BY code ASC").fetchall()],
    }
    payload["defaults"] = _default_master_ids(conn)
    conn.close()
    return payload


def _finance_master_data_for_actor(actor: dict):
    payload = _load_finance_master_data()
    if not actor or actor.get("role") == "Директор":
        return payload
    payload["legal_entities"] = filter_rows_by_scope(actor, payload.get("legal_entities", []))
    allowed_legal_ids = {int(item.get("id") or 0) for item in payload["legal_entities"]}
    payload["business_units"] = [
        row for row in filter_rows_by_scope(actor, payload.get("business_units", []))
        if not allowed_legal_ids or int(row.get("legal_entity_id") or 0) in allowed_legal_ids
    ]
    return payload


def _load_accounting_entries(limit: int = 120):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            ae.*,
            COALESCE(fp.title, '') AS source_title,
            COALESCE(cl.name, '') AS client_name,
            COALESCE(p.contract, p.name, '') AS project_label,
            COALESCE(le.short_name, le.name, '') AS legal_entity_name,
            COALESCE(bu.name, '') AS business_unit_name,
            COALESCE(ta.name, '') AS treasury_article_name,
            COALESCE(vr.name, '') AS vat_rate_name
        FROM accounting_entries ae
        LEFT JOIN finance_payments fp ON fp.id = ae.source_id AND ae.source_type='finance_payment'
        LEFT JOIN clients cl ON cl.id = ae.client_id
        LEFT JOIN projects p ON p.id = ae.project_id
        LEFT JOIN legal_entities le ON le.id = ae.legal_entity_id
        LEFT JOIN business_units bu ON bu.id = ae.business_unit_id
        LEFT JOIN treasury_articles ta ON ta.id = ae.treasury_article_id
        LEFT JOIN vat_rates vr ON vr.id = ae.vat_rate_id
        ORDER BY ae.created_at DESC, ae.id DESC
        LIMIT ?
        """,
        (max(1, min(limit, 500)),),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_accounting_periods():
    return _load_directory_rows("accounting_periods", "period_key DESC, id DESC")


def _load_treasury_limits():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            tl.*,
            COALESCE(le.short_name, le.name, '') AS legal_entity_name,
            COALESCE(bu.name, '') AS business_unit_name,
            COALESCE(ta.name, '') AS treasury_article_name
        FROM treasury_limits tl
        LEFT JOIN legal_entities le ON le.id = tl.legal_entity_id
        LEFT JOIN business_units bu ON bu.id = tl.business_unit_id
        LEFT JOIN treasury_articles ta ON ta.id = tl.treasury_article_id
        ORDER BY tl.period_key DESC, tl.updated_at DESC, tl.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_reconciliation_acts():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            ra.*,
            COALESCE(cl.name, '') AS client_name,
            COALESCE(cm.contract_number, '') AS contract_number
        FROM reconciliation_acts ra
        LEFT JOIN clients cl ON cl.id = ra.client_id
        LEFT JOIN contract_master cm ON cm.id = ra.contract_id
        ORDER BY ra.created_at DESC, ra.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["details"] = _json_load(row.get("details"), {})
    return rows


def _filter_finance_rows_for_actor(actor: dict, rows: list[dict]):
    return filter_rows_by_scope(actor, rows, "legal_entity_id", "business_unit_id")


def _assert_finance_scope(actor: dict, legal_entity_id: int = 0, business_unit_id: int = 0):
    return can_access_scope(actor, legal_entity_id, business_unit_id)


def _filter_scope_rows_for_actor(actor: dict, rows: list[dict]):
    return filter_rows_by_scope(actor, rows, "legal_entity_id", "business_unit_id")


def _production_order_in_scope(conn, actor: dict, order_id: int) -> bool:
    c = conn.cursor()
    c.execute("SELECT legal_entity_id, business_unit_id FROM production_orders WHERE id=?", (order_id,))
    row = c.fetchone()
    if not row:
        return False
    return _assert_finance_scope(actor, _safe_int(row[0]), _safe_int(row[1]))


def _load_sync_queue_rows(limit: int = 120):
    return load_sync_queue_rows_service(limit)


def _load_sync_conflict_rows(limit: int = 120):
    return load_sync_conflict_rows_service(limit)


def _load_edo_signature_rows(limit: int = 120):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM edo_signature_registry ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _integration_monitoring_payload(limit: int = 120) -> dict:
    queue_rows = _load_sync_queue_rows(limit)
    conflict_rows = _load_sync_conflict_rows(limit)
    payload = build_integration_monitoring_payload(queue_rows=queue_rows, conflict_rows=conflict_rows)
    payload["production_quality"] = _integration_production_quality_payload(limit)
    return payload


def _integration_production_quality_payload(limit: int = 120) -> dict:
    conn = get_connection(row_factory=True)
    try:
        queue_rows = [dict(row) for row in conn.execute("SELECT * FROM integration_sync_queue ORDER BY updated_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()]
        errors = [dict(row) for row in conn.execute("SELECT * FROM integration_error_events ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()]
        idempotency_rows = [dict(row) for row in conn.execute("SELECT * FROM integration_idempotency_keys ORDER BY updated_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()]
        consistency_rows = [dict(row) for row in conn.execute("SELECT * FROM integration_consistency_checks ORDER BY checked_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()]
    finally:
        conn.close()
    now = int(time.time())
    state_totals: dict[str, int] = {}
    for row in queue_rows:
        state = (row.get("state") or "unknown").strip() or "unknown"
        state_totals[state] = state_totals.get(state, 0) + 1
    unresolved_errors = [row for row in errors if row.get("status") == "open"]
    stale_processing = [
        row for row in queue_rows
        if row.get("state") == "processing" and _safe_int(row.get("locked_at")) and _safe_int(row.get("locked_at")) < now - 900
    ]
    consistency_alerts = [row for row in consistency_rows if row.get("state") not in {"consistent", "ok"}]
    retryable = [row for row in queue_rows if row.get("state") in {"retry", "failed", "conflict"}]
    return {
        "queue_state_totals": state_totals,
        "open_errors": len(unresolved_errors),
        "critical_errors": len([row for row in unresolved_errors if row.get("severity") == "critical"]),
        "stale_processing": len(stale_processing),
        "retryable_total": len(retryable),
        "idempotency_keys_total": len(idempotency_rows),
        "idempotency_collisions": len([row for row in unresolved_errors if row.get("error_code") == "idempotency_hash_mismatch"]),
        "consistency_alerts": len(consistency_alerts),
        "latest_errors": unresolved_errors[:20],
        "latest_consistency": consistency_rows[:20],
        "latest_idempotency": idempotency_rows[:20],
    }


def _run_integration_consistency_checks(actor: dict, limit: int = 200) -> dict:
    conn = get_connection(row_factory=True)
    checked = 0
    consistent = 0
    mismatches = 0
    missing = 0
    alerts = []
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT *
            FROM integration_sync_queue
            WHERE system_name='1C' AND state='synced'
            ORDER BY processed_at DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        )
        rows = [dict(row) for row in c.fetchall()]
        for row in rows:
            checked += 1
            queue_id = _safe_int(row.get("id"))
            entity_type = row.get("entity_type", "")
            entity_id = _safe_int(row.get("entity_id"))
            external_checksum = (row.get("checksum") or "").strip() or _payload_checksum(_json_load(row.get("payload"), {}))
            local_payload = None
            if entity_type == "finance_payment":
                payment = _get_finance_payment_row_from_conn(conn, entity_id)
                if payment:
                    local_payload = _build_finance_sync_payload(payment)
            else:
                meta = _sync_entity_meta(entity_type)
                if meta:
                    entity = _load_sync_entity_row(conn, entity_type, entity_id)
                    if entity:
                        local_payload = meta["builder"](entity)
            if local_payload is None:
                state = "missing_local"
                local_checksum = ""
                missing += 1
            else:
                local_checksum = _payload_checksum(local_payload)
                state = "consistent" if local_checksum == external_checksum else "mismatch"
                if state == "consistent":
                    consistent += 1
                else:
                    mismatches += 1
            _record_integration_consistency(
                conn,
                queue_id,
                row.get("system_name") or "1C",
                entity_type,
                entity_id,
                row.get("external_id") or "",
                state,
                local_checksum,
                external_checksum,
                {"actor": actor.get("email", ""), "source": "manual_consistency_run"},
            )
            c.execute("UPDATE integration_sync_queue SET consistency_state=?, updated_at=? WHERE id=?", (state, int(time.time()), queue_id))
            if state != "consistent":
                alerts.append({"queue_id": queue_id, "entity_type": entity_type, "entity_id": entity_id, "state": state})
        conn.commit()
    finally:
        conn.close()
    return {
        "checked": checked,
        "consistent": consistent,
        "mismatches": mismatches,
        "missing_local": missing,
        "alerts": alerts[:50],
    }


def _check_treasury_limit(conn, dims: dict, amount: float, due_date: str, payment_id: int = 0) -> dict:
    period_key = _period_key_for_date(due_date)
    c = conn.cursor()
    c.execute(
        """
        SELECT id, amount_limit
        FROM treasury_limits
        WHERE period_key=? AND legal_entity_id=? AND business_unit_id=? AND treasury_article_id=? AND status='active'
        ORDER BY id DESC LIMIT 1
        """,
        (period_key, dims["legal_entity_id"], dims["business_unit_id"], dims["treasury_article_id"]),
    )
    row = c.fetchone()
    if not row:
        return {"ok": True, "period_key": period_key, "amount_limit": 0, "planned_total": 0}
    limit_id = _safe_int(row[0])
    amount_limit = _safe_float(row[1])
    period_fragment = f"{period_key[5:7]}.{period_key[:4]}"
    params = [dims["legal_entity_id"], dims["business_unit_id"], dims["treasury_article_id"], period_fragment]
    query = """
        SELECT COALESCE(SUM(amount), 0)
        FROM finance_payments
        WHERE kind='outgoing'
          AND legal_entity_id=?
          AND business_unit_id=?
          AND treasury_article_id=?
          AND substr(due_date, 4, 7)=?
    """
    if payment_id:
        query += " AND id != ?"
        params.append(payment_id)
    c.execute(query, tuple(params))
    planned_total = _safe_float(c.fetchone()[0]) + _safe_float(amount)
    return {
        "ok": planned_total <= amount_limit + 0.0001,
        "period_key": period_key,
        "limit_id": limit_id,
        "amount_limit": amount_limit,
        "planned_total": round(planned_total, 2),
    }


def _finance_erp_summary(rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else _load_finance_rows()
    journal_rows = _load_accounting_entries(limit=400)
    limit_rows = _load_treasury_limits()
    queue_rows = _load_sync_queue_rows(limit=400)
    conflict_rows = _load_sync_conflict_rows(limit=200)
    signatures = _load_edo_signature_rows(limit=400)
    open_incoming = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "incoming" and row.get("status") != "paid")
    open_outgoing = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "outgoing" and row.get("status") != "paid")
    posted_total = sum(_safe_float(row.get("amount")) for row in journal_rows)
    receivable = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "incoming" and row.get("status") != "paid")
    payable = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "outgoing" and row.get("status") != "paid")
    overdue = [row for row in rows if _is_overdue(row.get("status", ""), row.get("due_date", ""))]
    active_limits = [row for row in limit_rows if row.get("status") == "active"]
    exceeded_limits = []
    for row in active_limits:
        planned_total = sum(
            _safe_float(item.get("amount"))
            for item in rows
            if item.get("kind") == "outgoing"
            and _safe_int(item.get("legal_entity_id")) == _safe_int(row.get("legal_entity_id"))
            and _safe_int(item.get("business_unit_id")) == _safe_int(row.get("business_unit_id"))
            and _safe_int(item.get("treasury_article_id")) == _safe_int(row.get("treasury_article_id"))
            and _period_key_for_date(item.get("due_date")) == row.get("period_key")
        )
        if planned_total > _safe_float(row.get("amount_limit")) + 0.0001:
            exceeded_limits.append({**row, "planned_total": round(planned_total, 2)})
    return {
        "metrics": {
            "receivable_open": round(receivable, 2),
            "payable_open": round(payable, 2),
            "posted_total": round(posted_total, 2),
            "cash_gap": round(open_incoming - open_outgoing, 2),
            "queued_sync": len([row for row in queue_rows if row.get("state") in {"queued", "retry", "processing"}]),
            "failed_sync": len([row for row in queue_rows if row.get("state") == "failed"]),
            "sync_conflicts": len(conflict_rows),
            "open_periods": len([row for row in _load_accounting_periods() if row.get("status") == "open"]),
            "edo_signed": len([row for row in signatures if row.get("signature_status") == "signed"]),
            "overdue_count": len(overdue),
            "limit_breaches": len(exceeded_limits),
        },
        "limit_breaches": exceeded_limits[:8],
        "failed_sync": [row for row in queue_rows if row.get("state") == "failed"][:8],
        "sync_conflicts": conflict_rows[:8],
        "recent_entries": journal_rows[:8],
    }


def _parse_ru_date(value: str = "") -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(value, pattern)
        except Exception:
            continue
    return None


FINANCE_STATUS_ALIASES = {
    "paid": "paid",
    "оплачено": "paid",
    "оплачен": "paid",
    "проведено": "paid",
    "completed": "paid",
    "issued": "issued",
    "выставлено": "issued",
    "выставлен": "issued",
    "posted": "issued",
    "partially_paid": "partially_paid",
    "частично оплачено": "partially_paid",
    "частично оплачен": "partially_paid",
    "partial": "partially_paid",
    "overdue": "overdue",
    "просрочено": "overdue",
    "просрочен": "overdue",
    "planned": "planned",
    "plan": "planned",
    "план": "planned",
    "запланировано": "planned",
}


def _normalize_finance_status(value: str = "", fallback: str = "planned") -> str:
    normalized = _normalize_spaces(value).lower()
    return FINANCE_STATUS_ALIASES.get(normalized, fallback or "planned")


def _finance_analytics(rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else _load_finance_rows()
    today = datetime.now()
    paid_incoming = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "incoming" and row.get("status") == "paid")
    paid_outgoing = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "outgoing" and row.get("status") == "paid")
    planned_incoming = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "incoming")
    planned_outgoing = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "outgoing")
    receivable_rows = [row for row in rows if row.get("kind") == "incoming" and row.get("status") != "paid"]
    payable_rows = [row for row in rows if row.get("kind") == "outgoing" and row.get("status") != "paid"]

    def build_aging(items: list[dict], sign: str):
        buckets = {"current": 0.0, "1_30": 0.0, "31_60": 0.0, "60_plus": 0.0}
        for item in items:
            amount = _safe_float(item.get("amount"))
            due_dt = _parse_ru_date(item.get("due_date"))
            if not due_dt:
                buckets["current"] += amount
                continue
            days = (today.date() - due_dt.date()).days
            if days <= 0:
                buckets["current"] += amount
            elif days <= 30:
                buckets["1_30"] += amount
            elif days <= 60:
                buckets["31_60"] += amount
            else:
                buckets["60_plus"] += amount
        return {
            "kind": sign,
            "current": round(buckets["current"], 2),
            "bucket_1_30": round(buckets["1_30"], 2),
            "bucket_31_60": round(buckets["31_60"], 2),
            "bucket_60_plus": round(buckets["60_plus"], 2),
        }

    project_map: dict[int, dict] = {}
    article_map: dict[str, dict] = {}
    legal_entity_map: dict[int, dict] = {}
    business_unit_map: dict[int, dict] = {}
    for row in rows:
        project_id = _safe_int(row.get("project_id"))
        project_key = project_id or -1
        entry = project_map.setdefault(project_key, {
            "project_id": project_id,
            "project_label": row.get("project_contract") or row.get("project_name") or "Без проекта",
            "incoming_paid": 0.0,
            "outgoing_paid": 0.0,
            "incoming_plan": 0.0,
            "outgoing_plan": 0.0,
            "receivable_open": 0.0,
            "payable_open": 0.0,
        })
        amount = _safe_float(row.get("amount"))
        kind = row.get("kind")
        status = row.get("status")
        if kind == "incoming":
            entry["incoming_plan"] += amount
            if status == "paid":
                entry["incoming_paid"] += amount
            else:
                entry["receivable_open"] += amount
        else:
            entry["outgoing_plan"] += amount
            if status == "paid":
                entry["outgoing_paid"] += amount
            else:
                entry["payable_open"] += amount
        article_label = row.get("treasury_article_name") or "Без статьи ДДС"
        article_entry = article_map.setdefault(article_label, {"article_name": article_label, "incoming": 0.0, "outgoing": 0.0})
        article_entry["incoming" if kind == "incoming" else "outgoing"] += amount
        legal_entity_id = _safe_int(row.get("legal_entity_id"))
        legal_entity_label = row.get("legal_entity_name") or "Без юрлица"
        legal_entry = legal_entity_map.setdefault(
            legal_entity_id or -1,
            {"legal_entity_id": legal_entity_id, "legal_entity_name": legal_entity_label, "incoming": 0.0, "outgoing": 0.0, "open": 0.0},
        )
        legal_entry["incoming" if kind == "incoming" else "outgoing"] += amount
        if status != "paid":
            legal_entry["open"] += amount
        business_unit_id = _safe_int(row.get("business_unit_id"))
        business_unit_label = row.get("business_unit_name") or "Без подразделения"
        business_entry = business_unit_map.setdefault(
            business_unit_id or -1,
            {"business_unit_id": business_unit_id, "business_unit_name": business_unit_label, "incoming": 0.0, "outgoing": 0.0, "open": 0.0},
        )
        business_entry["incoming" if kind == "incoming" else "outgoing"] += amount
        if status != "paid":
            business_entry["open"] += amount

    top_projects = []
    for item in project_map.values():
        item["fact_margin"] = round(item["incoming_paid"] - item["outgoing_paid"], 2)
        item["plan_margin"] = round(item["incoming_plan"] - item["outgoing_plan"], 2)
        for key in ("incoming_paid", "outgoing_paid", "incoming_plan", "outgoing_plan", "receivable_open", "payable_open"):
            item[key] = round(item[key], 2)
        top_projects.append(item)
    top_projects.sort(key=lambda item: abs(item.get("plan_margin", 0)), reverse=True)

    cashflow_by_article = []
    for item in article_map.values():
        item["net"] = round(item["incoming"] - item["outgoing"], 2)
        item["incoming"] = round(item["incoming"], 2)
        item["outgoing"] = round(item["outgoing"], 2)
        cashflow_by_article.append(item)
    cashflow_by_article.sort(key=lambda item: abs(item.get("net", 0)), reverse=True)

    by_legal_entity = []
    for item in legal_entity_map.values():
        item["incoming"] = round(item["incoming"], 2)
        item["outgoing"] = round(item["outgoing"], 2)
        item["open"] = round(item["open"], 2)
        item["net"] = round(item["incoming"] - item["outgoing"], 2)
        by_legal_entity.append(item)
    by_legal_entity.sort(key=lambda item: abs(item.get("net", 0)), reverse=True)

    by_business_unit = []
    for item in business_unit_map.values():
        item["incoming"] = round(item["incoming"], 2)
        item["outgoing"] = round(item["outgoing"], 2)
        item["open"] = round(item["open"], 2)
        item["net"] = round(item["incoming"] - item["outgoing"], 2)
        by_business_unit.append(item)
    by_business_unit.sort(key=lambda item: abs(item.get("net", 0)), reverse=True)

    warehouse_map: dict[str, dict] = {}
    for row in _load_stock_movements():
        warehouse = row.get("to_warehouse") or row.get("from_warehouse") or "Без склада"
        entry = warehouse_map.setdefault(warehouse, {"warehouse": warehouse, "qty_in": 0.0, "qty_out": 0.0, "documents": 0})
        qty = _safe_float(row.get("qty"))
        movement_type = row.get("movement_type")
        if movement_type in {"add", "transfer", "receipt_adjustment"}:
            if row.get("to_warehouse"):
                entry["qty_in"] += qty
        if movement_type in {"remove", "writeoff", "inventory"}:
            if row.get("from_warehouse"):
                entry["qty_out"] += qty
        if movement_type == "transfer":
            if row.get("from_warehouse"):
                source_entry = warehouse_map.setdefault(row.get("from_warehouse"), {"warehouse": row.get("from_warehouse"), "qty_in": 0.0, "qty_out": 0.0, "documents": 0})
                source_entry["qty_out"] += qty
            if row.get("to_warehouse"):
                target_entry = warehouse_map.setdefault(row.get("to_warehouse"), {"warehouse": row.get("to_warehouse"), "qty_in": 0.0, "qty_out": 0.0, "documents": 0})
                target_entry["qty_in"] += qty
        entry["documents"] += 1
    warehouse_turnover = []
    for item in warehouse_map.values():
        item["qty_in"] = round(item["qty_in"], 3)
        item["qty_out"] = round(item["qty_out"], 3)
        item["net_qty"] = round(item["qty_in"] - item["qty_out"], 3)
        warehouse_turnover.append(item)
    warehouse_turnover.sort(key=lambda item: abs(item.get("qty_in", 0)) + abs(item.get("qty_out", 0)), reverse=True)

    return {
        "metrics": {
            "pnl_fact": round(paid_incoming - paid_outgoing, 2),
            "pnl_plan": round(planned_incoming - planned_outgoing, 2),
            "dds_in_fact": round(paid_incoming, 2),
            "dds_out_fact": round(paid_outgoing, 2),
            "dds_in_plan": round(planned_incoming, 2),
            "dds_out_plan": round(planned_outgoing, 2),
            "cash_gap_fact": round(paid_incoming - paid_outgoing, 2),
            "cash_gap_plan": round(planned_incoming - planned_outgoing, 2),
            "receivable_open": round(sum(_safe_float(row.get("amount")) for row in receivable_rows), 2),
            "payable_open": round(sum(_safe_float(row.get("amount")) for row in payable_rows), 2),
        },
        "aging": {
            "receivable": build_aging(receivable_rows, "receivable"),
            "payable": build_aging(payable_rows, "payable"),
        },
        "top_projects": top_projects[:8],
        "cashflow_by_article": cashflow_by_article[:8],
        "by_legal_entity": by_legal_entity[:8],
        "by_business_unit": by_business_unit[:8],
        "warehouse_turnover": warehouse_turnover[:8],
    }


def _analytics_deep_summary(actor: dict) -> dict:
    return build_analytics_deep_summary(
        actor,
        get_connection=get_connection,
        table_exists=_table_exists,
        filter_finance_rows_for_actor=_filter_finance_rows_for_actor,
        filter_scope_rows_for_actor=_filter_scope_rows_for_actor,
        load_finance_rows=_load_finance_rows,
        normalize_spaces=_normalize_spaces,
        parse_ru_date=_parse_ru_date,
        period_key_for_date=_period_key_for_date,
        safe_float=_safe_float,
        safe_int=_safe_int,
    )


def _reliability_dashboard_payload(actor: dict) -> dict:
    return build_reliability_dashboard(
        actor,
        get_connection=get_connection,
        integration_monitoring_payload=_integration_monitoring_payload,
        list_entity_locks=list_entity_locks,
        safe_int=_safe_int,
        table_exists=_table_exists,
        today_display=_today_display,
    )


def _system_runtime_payload(actor: dict) -> dict:
    runtime = get_database_runtime_info()
    background_jobs = list_background_job_runs(limit=30)
    recovery_runs = list_recovery_workflow_runs(limit=20)
    backups = get_backups(limit=10)
    locks = list_entity_locks(limit=120)
    runtime["lock_policies"] = get_lock_policy_catalog()
    runtime["active_locks"] = len(locks)
    runtime["stale_locks"] = sum(1 for row in locks if _safe_int(row.get("is_stale")))
    return {
        "database": runtime,
        "background_jobs": background_jobs,
        "recovery_runs": recovery_runs,
        "backups": backups,
        "lock_policies": runtime["lock_policies"],
        "reliability": _reliability_dashboard_payload(actor),
    }


def _system_event_stream_payload(limit: int = 120, entity_type: str = "") -> list[dict]:
    return build_unified_event_stream(
        audit_rows=get_audit_logs(limit=max(limit, 120)),
        field_changes=get_field_change_logs(limit=max(limit, 120), entity_type=entity_type),
        domain_rows=get_domain_events(limit=max(limit, 120), entity_type=entity_type),
        limit=limit,
        entity_type=entity_type,
    )


def _run_system_recovery_action(actor: dict, data: SystemRecoveryActionData):
    action_name = _normalize_spaces(data.action_name or "")
    older_than_minutes = max(1, _safe_int(data.older_than_minutes or 15))
    stale_only = int(data.stale_only or 0)
    force_failed = int(data.force_failed or 0)
    target_scope = f"older_than={older_than_minutes}m"
    run_id = start_recovery_workflow_run(
        action_name,
        actor_email=actor.get("email", ""),
        target_scope=target_scope,
        details={"comment": data.comment or "", "stale_only": stale_only, "force_failed": force_failed},
    )
    result = {"action_name": action_name, "affected": 0, "details": {}}
    status = "success"
    conn = None
    try:
        now = int(time.time())
        stale_before = now - older_than_minutes * 60
        conn = get_connection()
        c = conn.cursor()
        if action_name == "release_stale_locks":
            if stale_only:
                c.execute("DELETE FROM entity_edit_locks WHERE locked_at < ?", (stale_before,))
            else:
                c.execute("DELETE FROM entity_edit_locks")
            result["affected"] = c.rowcount
        elif action_name == "revoke_stale_sessions":
            if stale_only:
                c.execute("DELETE FROM user_sessions WHERE last_seen_at < ?", (stale_before,))
            else:
                c.execute("DELETE FROM user_sessions")
            result["affected"] = c.rowcount
        elif action_name == "recover_sync_queue":
            states = ("failed", "processing", "retry") if force_failed else ("processing", "retry")
            placeholders = ", ".join("?" for _ in states)
            c.execute(
                f"""
                UPDATE integration_sync_queue
                SET state='retry', locked_at=0, next_retry_at=0, updated_at=?
                WHERE state IN ({placeholders})
                  AND (? = 0 OR updated_at < ?)
                """,
                (now, *states, stale_only, stale_before),
            )
            result["affected"] = c.rowcount
        elif action_name == "checkpoint":
            result["details"]["checkpoint"] = [{"status": "managed_by_postgres"}]
            result["affected"] = 1
        else:
            status = "failed"
            result = {"error": "unsupported_action", "action_name": action_name}
        conn.commit()
    except Exception as exc:
        status = "failed"
        result = {"error": str(exc)[:500], "action_name": action_name, "affected": 0}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    finish_recovery_workflow_run(run_id, status, result)
    result["run_id"] = run_id
    return result


def _analytics_dashboard_hub(actor: dict) -> dict:
    finance_payload = _finance_analytics(_filter_finance_rows_for_actor(actor, _load_finance_rows()))
    analytics_payload = _analytics_deep_summary(actor)
    reliability_payload = _reliability_dashboard_payload(actor)
    saved_reports = _load_saved_reports(actor.get("email", ""))
    return build_analytics_dashboard_hub(
        actor,
        saved_reports=saved_reports,
        finance_payload=finance_payload,
        analytics_payload=analytics_payload,
        reliability_payload=reliability_payload,
    )


def _analytics_drilldown_payload(actor: dict, dimension: str, value: str = "", value_id: int = 0, limit: int = 50) -> dict:
    return build_analytics_drilldown(
        actor,
        dimension=dimension,
        value=value,
        value_id=value_id,
        limit=limit,
        get_connection=get_connection,
        table_exists=_table_exists,
        filter_finance_rows_for_actor=_filter_finance_rows_for_actor,
        filter_scope_rows_for_actor=_filter_scope_rows_for_actor,
        load_finance_rows=_load_finance_rows,
        safe_float=_safe_float,
        safe_int=_safe_int,
        normalize_spaces=_normalize_spaces,
    )


def process_due_1c_sync_queue(limit: int = 10) -> dict:
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
    rows = [dict(row) for row in c.fetchall()]
    processed = 0
    success = 0
    failed = 0
    for row in rows:
        processed += 1
        queue_id = _safe_int(row.get("id"))
        entity_type = row.get("entity_type", "")
        entity_id = _safe_int(row.get("entity_id"))
        payload = _json_load(row.get("payload"), {})
        idempotency_key = (row.get("idempotency_key") or "").strip() or _integration_idempotency_key("1C", entity_type, entity_id, row.get("direction") or "outbound", payload)
        request_hash = _payload_checksum({"entity_type": entity_type, "entity_id": entity_id, "direction": row.get("direction") or "outbound", "payload": payload})
        checksum = (row.get("checksum") or "").strip() or _payload_checksum(payload)
        attempt_limit = max(1, _safe_int(row.get("attempt_limit")) or 5)
        c.execute(
            """
            UPDATE integration_sync_queue
            SET state='processing', locked_at=?, last_attempt_at=?, updated_at=?,
                idempotency_key=?, checksum=?, consistency_state='pending'
            WHERE id=?
            """,
            (now, now, now, idempotency_key, checksum, queue_id),
        )
        _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, "processing", {"queue_id": queue_id})
        try:
            if entity_type == "finance_payment":
                external_id = f"1C-FIN-{entity_id}"
                c.execute(
                    """
                    UPDATE integration_sync_queue
                    SET state='synced', external_id=?, last_error='', locked_at=0,
                        processed_at=?, updated_at=?, checksum=?, consistency_state='consistent'
                    WHERE id=?
                    """,
                    (external_id, now, now, checksum, queue_id),
                )
                c.execute(
                    """
                    UPDATE finance_payments
                    SET exchange_state='synced', external_sync_id=?, updated_at=?
                    WHERE id=?
                    """,
                    (external_id, now, entity_id),
                )
                _log_sync_event(conn, queue_id, "1C", entity_type, entity_id, "synced", "Документ синхронизирован с 1С", payload, external_id)
                _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, "synced", {"queue_id": queue_id, "external_id": external_id})
                _record_integration_consistency(conn, queue_id, "1C", entity_type, entity_id, external_id, "consistent", checksum, checksum, {"source": "outbound_process"})
                success += 1
            elif _sync_entity_meta(entity_type):
                meta = _sync_entity_meta(entity_type)
                external_id = f"{meta['prefix']}-{entity_id}"
                c.execute(
                    """
                    UPDATE integration_sync_queue
                    SET state='synced', external_id=?, last_error='', locked_at=0,
                        processed_at=?, updated_at=?, checksum=?, consistency_state='consistent'
                    WHERE id=?
                    """,
                    (external_id, now, now, checksum, queue_id),
                )
                _set_sync_entity_state(conn, entity_type, entity_id if entity_type != "nomenclature" else payload.get("article") or entity_id, "synced", external_id)
                _log_sync_event(conn, queue_id, "1C", entity_type, entity_id, "synced", "Сущность синхронизирована с 1С", payload, external_id)
                _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, "synced", {"queue_id": queue_id, "external_id": external_id})
                _record_integration_consistency(conn, queue_id, "1C", entity_type, entity_id, external_id, "consistent", checksum, checksum, {"source": "outbound_process"})
                success += 1
            elif entity_type == "epl_waybill":
                from routers import accounting as accounting_router

                outcome = accounting_router._process_epl_sync_queue_item(conn, row)
                if outcome.get("state") == "sent":
                    _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, "synced", outcome)
                    success += 1
                else:
                    failed += 1
            else:
                raise ValueError(f"unsupported entity type: {entity_type}")
        except Exception as exc:
            retry_count = _safe_int(row.get("retry_count")) + 1
            backoff_seconds = min(86400, 30 * (2 ** min(retry_count, 8)))
            next_retry_at = now + backoff_seconds
            failed_state = "failed" if retry_count >= attempt_limit else "retry"
            c.execute(
                """
                UPDATE integration_sync_queue
                SET state=?, retry_count=?, last_error=?, next_retry_at=?, locked_at=0,
                    last_attempt_at=?, updated_at=?, consistency_state=?
                WHERE id=?
                """,
                (failed_state, retry_count, str(exc)[:500], 0 if failed_state == "failed" else next_retry_at, now, now, "failed" if failed_state == "failed" else "pending", queue_id),
            )
            if entity_type == "finance_payment":
                c.execute(
                    "UPDATE finance_payments SET exchange_state='failed', updated_at=? WHERE id=?",
                    (now, entity_id),
                )
            elif entity_type == "epl_waybill":
                c.execute(
                    "UPDATE epl_waybills SET integration_status='error', last_sync_error=?, updated_at=? WHERE id=?",
                    (str(exc)[:500], now, entity_id),
                )
            elif _sync_entity_meta(entity_type):
                _set_sync_entity_state(conn, entity_type, entity_id if entity_type != "nomenclature" else payload.get("article") or entity_id, "failed", "")
            _log_sync_event(conn, queue_id, "1C", entity_type, entity_id, "failed", str(exc), payload)
            _upsert_idempotency_record(conn, "1C", idempotency_key, "outbound", queue_id, request_hash, failed_state, {"queue_id": queue_id, "error": str(exc)[:500], "retry_count": retry_count})
            _record_integration_error_event(conn, queue_id, "1C", entity_type, entity_id, str(exc), payload, "critical" if failed_state == "failed" else "error", "outbound_sync_failed")
            failed += 1
    conn.commit()
    conn.close()
    return {"processed": processed, "success": success, "failed": failed}


def process_due_1c_sync_queue(limit: int = 10) -> dict:
    from routers import accounting as accounting_router

    return process_due_1c_sync_queue_service(limit, epl_processor=accounting_router._process_epl_sync_queue_item)


INBOUND_ENTITY_ALIASES = {
    "finance_payment": {"finance_payment", "payment", "платеж", "платёж", "оплата", "финансовая операция", "счет", "счёт", "счет на оплату", "счёт на оплату"},
    "document": {"document", "doc", "документ", "канцелярия", "входящий документ", "исходящий документ", "внутренний документ", "письмо", "договор", "акт", "упд"},
    "sales_document": {"sales_document", "sales", "sale", "реализация", "счет покупателю", "счёт покупателю", "акт реализации", "накладная", "отгрузка"},
    "purchase_order": {"purchase_order", "purchase", "закупка", "заказ поставщику", "поступление", "поступление товаров"},
    "production_order": {"production_order", "production", "производственный заказ", "производство"},
    "stock_reservation": {"stock_reservation", "reservation", "резерв", "резерв склада", "резервирование"},
    "nomenclature": {"nomenclature", "номенклатура", "товар", "материал", "позиция"},
}

INBOUND_STATUS_ALIASES_BY_ENTITY = {
    "sales_document": {
        "подписано": "signed",
        "подписан": "signed",
        "проведено": "signed",
        "выставлено": "issued",
        "оплачено": "paid",
        "частично оплачено": "partially_paid",
    },
    "document": {
        "зарегистрирован": "registered",
        "зарегистрировано": "registered",
        "зарегистрировать": "registered",
        "черновик": "draft",
        "подписан": "signed",
        "подписано": "signed",
        "в архив": "archived",
        "архив": "archived",
        "закрыт": "closed",
        "закрыто": "closed",
    },
    "purchase_order": {
        "получено": "received",
        "поступило": "received",
        "проведено": "received",
        "заказано": "ordered",
        "в пути": "in_transit",
    },
    "production_order": {
        "завершено": "done",
        "выполнено": "done",
        "в работе": "in_progress",
        "очередь": "queue",
    },
    "stock_reservation": {
        "исполнено": "fulfilled",
        "отгружено": "fulfilled",
        "зарезервировано": "reserved",
        "отменено": "cancelled",
    },
}

INBOUND_FIELD_ALIASES = {
    "entity_type": ("entity_type", "тип", "тип сущности", "тип_сущности", "тип документа", "тип_документа", "document_type"),
    "entity_id": ("entity_id", "id", "идентификатор", "идентификатор записи", "внутренний идентификатор", "внутренний_идентификатор", "record_id"),
    "external_id": ("external_id", "external_sync_id", "externalId", "внешний идентификатор", "внешний_идентификатор", "ссылка 1с", "ссылка_1с", "guid", "uid", "номер 1с"),
    "status": ("status", "статус", "состояние"),
    "amount": ("amount", "сумма", "итого", "total"),
    "currency": ("currency", "валюта"),
    "due_date": ("due_date", "срок оплаты", "дата план", "плановая дата", "дата платежа план", "дата_платежа_план"),
    "paid_date": ("paid_date", "дата оплаты", "дата платежа", "дата_оплаты", "дата_платежа"),
    "comment": ("comment", "комментарий", "примечание"),
    "source_document_type": ("source_document_type", "документ основание тип", "тип документа основания", "source_type"),
    "source_document_id": ("source_document_id", "документ основание id", "идентификатор документа основания", "source_id"),
    "exchange_state": ("exchange_state", "состояние обмена", "статус обмена"),
    "allow_amount_override": ("allow_amount_override", "разрешить изменение суммы", "изменить сумму", "перезаписать сумму"),
    "idempotency_key": ("idempotency_key", "ключ идемпотентности", "ключ_идемпотентности"),
    "payload": ("payload", "данные", "реквизиты"),
    "type": ("type", "вид", "вид документа", "тип канцелярии", "document_kind"),
    "number": ("number", "номер", "номер документа", "номер_документа", "document_number", "doc_number"),
    "d_date": ("d_date", "date", "дата", "дата документа", "дата_документа", "doc_date"),
    "correspondent": ("correspondent", "контрагент", "отправитель", "получатель", "корреспондент", "организация"),
    "subject": ("subject", "тема", "назначение", "описание", "содержание"),
    "file_url": ("file_url", "ссылка на файл", "ссылка_на_файл", "файл", "скан", "scan_url"),
    "project_id": ("project_id", "проект", "ид проекта", "идентификатор проекта"),
    "contract_id": ("contract_id", "договор id", "ид договора", "идентификатор договора"),
    "object_id": ("object_id", "объект id", "ид объекта", "идентификатор объекта"),
    "parent_id": ("parent_id", "родительский документ", "документ основание"),
    "priority": ("priority", "приоритет", "важность"),
}


def _inbound_key_lookup(item: dict) -> dict:
    return {_normalize_spaces(str(key)).lower(): key for key in item.keys()}


def _inbound_value(item: dict, field_name: str, default=None):
    lookup = _inbound_key_lookup(item)
    for alias in INBOUND_FIELD_ALIASES.get(field_name, (field_name,)):
        actual = lookup.get(_normalize_spaces(alias).lower())
        if actual is not None:
            return item.get(actual)
    return default


def _parse_inbound_float(value):
    if value in (None, ""):
        return None
    try:
        if isinstance(value, str):
            value = value.replace("\u00a0", " ").replace(" ", "").replace(",", ".")
        return float(value)
    except Exception:
        return None


def _parse_inbound_bool(value) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    normalized = _normalize_spaces(str(value)).lower()
    return 1 if normalized in {"1", "true", "yes", "да", "истина", "разрешено"} else 0


def _normalize_inbound_date(value):
    if value in (None, ""):
        return "", False
    dt = _parse_ru_date(str(value))
    if not dt:
        return str(value).strip(), True
    return dt.strftime("%d.%m.%Y"), False


def _normalize_inbound_entity_type(value: str = "", default_entity_type: str = "") -> str:
    normalized = _normalize_spaces(str(value or "")).lower()
    if not normalized:
        return default_entity_type
    for entity_type, aliases in INBOUND_ENTITY_ALIASES.items():
        if normalized in aliases:
            return entity_type
    return normalized


def _normalize_inbound_document_type(value: str = "") -> str:
    normalized = _normalize_spaces(str(value or "")).lower()
    mapping = {
        "incoming": "incoming",
        "входящий": "incoming",
        "входящее": "incoming",
        "outgoing": "outgoing",
        "исходящий": "outgoing",
        "исходящее": "outgoing",
        "internal": "internal",
        "internal_order": "internal_order",
        "внутренний": "internal",
        "внутреннее": "internal",
        "приказ": "internal_order",
        "contract": "contract",
        "договор": "contract",
        "act": "act",
        "акт": "act",
        "invoice": "invoice",
        "счет": "invoice",
        "счёт": "invoice",
        "упд": "outgoing",
    }
    return mapping.get(normalized, normalized or "incoming")


def _normalize_inbound_sync_item(raw_item, default_entity_type: str = "") -> dict:
    if not isinstance(raw_item, dict):
        return {"_raw": raw_item, "_validation_errors": ["Строка пакета должна быть объектом JSON."]}
    payload = _inbound_value(raw_item, "payload", {}) or {}
    if not isinstance(payload, dict):
        payload = {}
    normalized = dict(payload)
    raw_entity_type = _inbound_value(raw_item, "entity_type", "")
    entity_type = _normalize_inbound_entity_type(raw_entity_type, default_entity_type)
    doc_type_hint = _inbound_value(raw_item, "type", "") or (raw_entity_type if default_entity_type == "document" and entity_type not in {"document", "finance_payment", "sales_document", "purchase_order", "production_order", "stock_reservation", "stock_document", "nomenclature"} else "")
    if default_entity_type == "document" and entity_type not in {"document", "finance_payment", "sales_document", "purchase_order", "production_order", "stock_reservation", "stock_document", "nomenclature"}:
        entity_type = "document"
    entity_id_raw = _inbound_value(raw_item, "entity_id", 0)
    amount_raw = _inbound_value(raw_item, "amount", None)
    amount_value = _parse_inbound_float(amount_raw)
    due_date, due_invalid = _normalize_inbound_date(_inbound_value(raw_item, "due_date", ""))
    paid_date, paid_invalid = _normalize_inbound_date(_inbound_value(raw_item, "paid_date", ""))
    status_raw = _inbound_value(raw_item, "status", "")
    status_value = str(status_raw or "").strip()
    if entity_type == "finance_payment" and status_value:
        status_value = FINANCE_STATUS_ALIASES.get(_normalize_spaces(status_value).lower(), status_value)
    elif entity_type in INBOUND_STATUS_ALIASES_BY_ENTITY and status_value:
        status_value = INBOUND_STATUS_ALIASES_BY_ENTITY[entity_type].get(_normalize_spaces(status_value).lower(), status_value)
    normalized.update({
        "entity_type": entity_type,
        "entity_id": _safe_int(entity_id_raw),
        "external_id": str(_inbound_value(raw_item, "external_id", "") or "").strip(),
        "status": status_value,
        "amount": amount_value if amount_value is not None else 0,
        "currency": str(_inbound_value(raw_item, "currency", "RUB") or "RUB").strip() or "RUB",
        "due_date": due_date,
        "paid_date": paid_date,
        "comment": str(_inbound_value(raw_item, "comment", "") or "").strip(),
        "source_document_type": str(_inbound_value(raw_item, "source_document_type", "") or "").strip(),
        "source_document_id": _safe_int(_inbound_value(raw_item, "source_document_id", 0)),
        "exchange_state": str(_inbound_value(raw_item, "exchange_state", "synced") or "synced").strip() or "synced",
        "allow_amount_override": _parse_inbound_bool(_inbound_value(raw_item, "allow_amount_override", 0)),
        "idempotency_key": str(_inbound_value(raw_item, "idempotency_key", "") or "").strip(),
        "payload": payload,
        "_raw": raw_item,
        "_validation_errors": [],
    })
    if entity_type == "document":
        doc_date, doc_date_invalid = _normalize_inbound_date(_inbound_value(raw_item, "d_date", ""))
        normalized.update({
            "type": _normalize_inbound_document_type(doc_type_hint or _inbound_value(raw_item, "type", "")),
            "number": str(_inbound_value(raw_item, "number", "") or "").strip(),
            "d_date": doc_date,
            "correspondent": str(_inbound_value(raw_item, "correspondent", "") or "").strip(),
            "subject": str(_inbound_value(raw_item, "subject", "") or "").strip(),
            "file_url": str(_inbound_value(raw_item, "file_url", "") or "").strip(),
            "project_id": _safe_int(_inbound_value(raw_item, "project_id", 0)),
            "contract_id": _safe_int(_inbound_value(raw_item, "contract_id", 0)),
            "object_id": _safe_int(_inbound_value(raw_item, "object_id", 0)),
            "parent_id": _safe_int(_inbound_value(raw_item, "parent_id", 0)),
            "priority": str(_inbound_value(raw_item, "priority", "normal") or "normal").strip() or "normal",
        })
        if doc_date_invalid:
            normalized["_validation_errors"].append("Дата документа должна быть в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.")
    if amount_raw not in (None, "") and amount_value is None:
        normalized["_validation_errors"].append("Сумма должна быть числом.")
    if due_invalid:
        normalized["_validation_errors"].append("Срок оплаты должен быть датой в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.")
    if paid_invalid:
        normalized["_validation_errors"].append("Дата оплаты должна быть датой в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.")
    if entity_type == "finance_payment" and status_raw and _normalize_spaces(str(status_raw)).lower() not in FINANCE_STATUS_ALIASES:
        normalized["_validation_errors"].append("Неизвестный статус оплаты. Используй: план, выставлено, оплачено, частично оплачено, просрочено.")
    if entity_type == "document":
        if not normalized.get("number") and not normalized.get("external_id"):
            normalized["_validation_errors"].append("Для документа нужен номер документа или внешний идентификатор 1С.")
        if not normalized.get("subject"):
            normalized["_validation_errors"].append("Для документа нужна тема или описание.")
    return normalized


def _normalize_inbound_items(items: list, default_entity_type: str = "") -> list[dict]:
    return [_normalize_inbound_sync_item(item, default_entity_type) for item in (items or [])]


def _inbound_compare_change(changes: list, field_name: str, before, after):
    if after in (None, ""):
        return
    if str(before or "") != str(after or ""):
        changes.append({"field": field_name, "before": before, "after": after})


def _preview_inbound_sync_item(conn, item: dict, index: int = 0, default_entity_type: str = "finance_payment") -> dict:
    normalized = _normalize_inbound_sync_item(item, default_entity_type)
    entity_type = normalized.get("entity_type") or default_entity_type
    if entity_type == "document":
        return _preview_inbound_document_sync_item(conn, item, index)
    errors = list(normalized.get("_validation_errors") or [])
    warnings = []
    changes = []
    target = None
    target_id = 0
    if not entity_type:
        errors.append("Не указан тип документа.")
    if entity_type == "finance_payment":
        has_lookup = bool(normalized.get("entity_id") or normalized.get("external_id") or (normalized.get("source_document_type") and normalized.get("source_document_id")))
        if not has_lookup:
            errors.append("Нужен внутренний идентификатор, внешний идентификатор или документ-основание.")
        target = _find_finance_payment_by_sync_item(conn, normalized) if not errors else None
        if target:
            target_id = _safe_int(target.get("id"))
            inbound_amount = _safe_float(normalized.get("amount"))
            current_amount = _safe_float(target.get("amount"))
            if inbound_amount and abs(inbound_amount - current_amount) > 0.01 and not _safe_int(normalized.get("allow_amount_override")):
                warnings.append(f"Сумма 1С {inbound_amount:g} не совпадает с CRM {current_amount:g}.")
            _inbound_compare_change(changes, "статус", target.get("status"), normalized.get("status"))
            _inbound_compare_change(changes, "сумма", current_amount, inbound_amount if inbound_amount else "")
            _inbound_compare_change(changes, "дата оплаты", target.get("paid_date"), normalized.get("paid_date"))
            _inbound_compare_change(changes, "внешний идентификатор", target.get("external_sync_id"), normalized.get("external_id"))
        elif not errors:
            warnings.append("Документ не найден в CRM. При применении попадёт в конфликты обмена.")
    else:
        meta = _sync_entity_meta(entity_type)
        if not meta:
            errors.append("Тип документа пока не поддержан для переноса из 1С.")
        elif not (normalized.get("entity_id") or normalized.get("external_id")):
            errors.append("Нужен внутренний или внешний идентификатор документа.")
        else:
            target = _load_sync_entity_row(conn, entity_type, normalized.get("entity_id"))
            if not target and normalized.get("external_id") and meta.get("external_column"):
                row = conn.execute(
                    f"SELECT {meta['id_column']} FROM {meta['table']} WHERE {meta['external_column']}=? ORDER BY {meta['id_column']} DESC LIMIT 1",
                    (normalized.get("external_id"),),
                ).fetchone()
                if row:
                    target = _load_sync_entity_row(conn, entity_type, row[0])
            if target:
                target_id = _safe_int(target.get("id") or target.get(meta["id_column"]))
                _inbound_compare_change(changes, "статус", target.get("status"), normalized.get("status"))
                _inbound_compare_change(changes, "комментарий", target.get("comment"), normalized.get("comment"))
                _inbound_compare_change(changes, "внешний идентификатор", target.get(meta.get("external_column", "")), normalized.get("external_id"))
                for key, value in (normalized.get("payload") or {}).items():
                    if key in target:
                        _inbound_compare_change(changes, key, target.get(key), value)
            else:
                warnings.append("Документ не найден в CRM. При применении попадёт в конфликты обмена.")
    state = "error" if errors else ("conflict" if warnings else "ready")
    return {
        "index": index,
        "state": state,
        "entity_type": entity_type,
        "entity_label": _entity_label(entity_type),
        "target_id": target_id,
        "external_id": normalized.get("external_id") or "",
        "errors": errors,
        "warnings": warnings,
        "changes": changes[:12],
        "normalized": {key: value for key, value in normalized.items() if not key.startswith("_")},
    }


def _preview_inbound_batch(items: list, default_entity_type: str = "finance_payment") -> dict:
    conn = get_connection(row_factory=True)
    try:
        rows = [_preview_inbound_sync_item(conn, item, idx + 1, default_entity_type) for idx, item in enumerate(items or [])]
    finally:
        conn.close()
    return {
        "status": "success",
        "total": len(rows),
        "ready": len([row for row in rows if row.get("state") == "ready"]),
        "conflicts": len([row for row in rows if row.get("state") == "conflict"]),
        "errors": len([row for row in rows if row.get("state") == "error"]),
        "rows": rows[:200],
    }


def _next_document_id(conn) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM documents WHERE id < 2147483647").fetchone()
    if isinstance(row, dict):
        return _safe_int(next(iter(row.values()), 1)) or 1
    return _safe_int(row[0] if row else 1) or 1


def _find_document_by_inbound_item(conn, item: dict) -> dict | None:
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    entity_id = _safe_int(item.get("entity_id"))
    if entity_id:
        row = c.execute("SELECT * FROM documents WHERE id=? LIMIT 1", (entity_id,)).fetchone()
        if row:
            return dict(row)
    external_id = (item.get("external_id") or "").strip()
    if external_id:
        try:
            row = c.execute("SELECT * FROM documents WHERE external_sync_id=? ORDER BY id DESC LIMIT 1", (external_id,)).fetchone()
            if row:
                return dict(row)
        except Exception:
            pass
        row = c.execute(
            """
            SELECT entity_id
            FROM integration_external_objects
            WHERE system_name='1C' AND entity_type='document' AND external_id=?
            ORDER BY updated_at DESC, id DESC LIMIT 1
            """,
            (external_id,),
        ).fetchone()
        if row:
            target_id = row.get("entity_id") if isinstance(row, dict) else row[0]
            found = c.execute("SELECT * FROM documents WHERE id=? LIMIT 1", (_safe_int(target_id),)).fetchone()
            if found:
                return dict(found)
    number = (item.get("number") or "").strip()
    if number:
        row = c.execute(
            """
            SELECT * FROM documents
            WHERE number=? AND type=? AND COALESCE(correspondent, '')=?
            ORDER BY id DESC LIMIT 1
            """,
            (number, item.get("type") or "incoming", item.get("correspondent") or ""),
        ).fetchone()
        if row:
            return dict(row)
        row = c.execute("SELECT * FROM documents WHERE number=? ORDER BY id DESC LIMIT 1", (number,)).fetchone()
        if row:
            return dict(row)
    return None


def _preview_inbound_document_sync_item(conn, item: dict, index: int = 0) -> dict:
    normalized = _normalize_inbound_sync_item(item, "document")
    errors = list(normalized.get("_validation_errors") or [])
    warnings = []
    changes = []
    target = _find_document_by_inbound_item(conn, normalized) if not errors else None
    if target:
        _inbound_compare_change(changes, "вид", target.get("type"), normalized.get("type"))
        _inbound_compare_change(changes, "номер", target.get("number"), normalized.get("number"))
        _inbound_compare_change(changes, "дата", target.get("d_date"), normalized.get("d_date"))
        _inbound_compare_change(changes, "контрагент", target.get("correspondent"), normalized.get("correspondent"))
        _inbound_compare_change(changes, "тема", target.get("subject"), normalized.get("subject"))
        _inbound_compare_change(changes, "статус", target.get("status"), normalized.get("status"))
        _inbound_compare_change(changes, "файл", target.get("file_url"), normalized.get("file_url"))
        _inbound_compare_change(changes, "внешний идентификатор", target.get("external_sync_id"), normalized.get("external_id"))
    elif not errors:
        changes.append({"field": "действие", "before": "нет в Korda", "after": "будет создан документ"})
    state = "error" if errors else "ready"
    return {
        "index": index,
        "state": state,
        "entity_type": "document",
        "entity_label": _entity_label("document"),
        "target_id": _safe_int((target or {}).get("id")),
        "external_id": normalized.get("external_id") or "",
        "errors": errors,
        "warnings": warnings,
        "changes": changes[:12],
        "normalized": {key: value for key, value in normalized.items() if not key.startswith("_")},
    }


def _preview_document_import_batch(items: list) -> dict:
    conn = get_connection(row_factory=True)
    try:
        rows = [_preview_inbound_document_sync_item(conn, item, idx + 1) for idx, item in enumerate(items or [])]
    finally:
        conn.close()
    return {
        "status": "success",
        "total": len(rows),
        "ready": len([row for row in rows if row.get("state") == "ready"]),
        "conflicts": len([row for row in rows if row.get("state") == "conflict"]),
        "errors": len([row for row in rows if row.get("state") == "error"]),
        "rows": rows[:500],
    }


def _apply_inbound_document_sync_item(conn, item: dict, actor_email: str = "", source_system: str = "1C") -> dict:
    item = _normalize_inbound_sync_item(item, "document")
    payload = {key: value for key, value in item.items() if not key.startswith("_")}
    if item.get("_validation_errors"):
        _record_integration_error_event(conn, 0, source_system, "document", _safe_int(item.get("entity_id")), "; ".join(item.get("_validation_errors") or []), payload, "warning", "document_inbound_validation_failed")
        return {"state": "conflict", "reason": "validation_failed", "errors": item.get("_validation_errors") or [], "entity_type": "document"}
    c = conn.cursor()
    now = int(time.time())
    document = _find_document_by_inbound_item(conn, item)
    external_id = (item.get("external_id") or "").strip()
    status_value = item.get("status") or "registered"
    if document:
        doc_id = _safe_int(document.get("id"))
        c.execute(
            """
            UPDATE documents
            SET type=?, number=?, d_date=?, correspondent=?, subject=?, status=?,
                file_url=CASE WHEN ?<>'' THEN ? ELSE file_url END,
                project_id=?, contract_id=?, object_id=?, parent_id=?, priority=?,
                external_sync_id=?, exchange_state='synced', sync_comment=?
            WHERE id=?
            """,
            (
                item.get("type") or document.get("type") or "incoming",
                item.get("number") or document.get("number") or "",
                item.get("d_date") or document.get("d_date") or "",
                item.get("correspondent") or document.get("correspondent") or "",
                item.get("subject") or document.get("subject") or "",
                status_value,
                item.get("file_url") or "",
                item.get("file_url") or "",
                _safe_int(item.get("project_id") or document.get("project_id")),
                _safe_int(item.get("contract_id") or document.get("contract_id")),
                _safe_int(item.get("object_id") or document.get("object_id")),
                _safe_int(item.get("parent_id") or document.get("parent_id")),
                item.get("priority") or document.get("priority") or "normal",
                external_id or document.get("external_sync_id") or "",
                (item.get("comment") or f"Обновлено из {source_system}")[:1000],
                doc_id,
            ),
        )
        action = "updated"
    else:
        doc_id = _next_document_id(conn)
        c.execute(
            """
            INSERT INTO documents (
                id, type, number, d_date, correspondent, subject, status, file_url, qr_code,
                project_id, contract_id, object_id, parent_id, priority,
                external_sync_id, exchange_state, sync_comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, 'synced', ?)
            """,
            (
                doc_id,
                item.get("type") or "incoming",
                item.get("number") or external_id or f"1C-DOC-{doc_id}",
                item.get("d_date") or _today_display(),
                item.get("correspondent") or "",
                item.get("subject") or item.get("number") or external_id or "Документ из 1С",
                status_value,
                item.get("file_url") or "",
                _safe_int(item.get("project_id")),
                _safe_int(item.get("contract_id")),
                _safe_int(item.get("object_id")),
                _safe_int(item.get("parent_id")),
                item.get("priority") or "normal",
                external_id,
                (item.get("comment") or f"Создано при переносе из {source_system}")[:1000],
            ),
        )
        action = "created"
    if external_id:
        c.execute(
            """
            INSERT INTO integration_external_objects (
                system_name, entity_type, entity_id, external_id, external_type, exchange_state, last_synced_at, created_at, updated_at
            ) VALUES (?, 'document', ?, ?, ?, 'synced', ?, ?, ?)
            ON CONFLICT(system_name, entity_type, entity_id) DO UPDATE SET
                external_id=excluded.external_id,
                external_type=excluded.external_type,
                exchange_state='synced',
                last_synced_at=excluded.last_synced_at,
                updated_at=excluded.updated_at
            """,
            (source_system or "1C", str(doc_id), external_id, item.get("type") or "document", now, now, now),
        )
    _log_sync_event(conn, 0, source_system, "document", doc_id, "inbound_synced", "Документ перенесён из 1С в канцелярию", payload, external_id)
    audit_log("document_imported_from_1c", actor_email=actor_email or "", actor_name="", entity_type="document", entity_id=str(doc_id), details={"action": action, "external_id": external_id, "number": item.get("number")})
    return {"state": "applied", "entity_type": "document", "entity_id": doc_id, "action": action}


def _find_finance_payment_by_sync_item(conn, item: dict) -> dict | None:
    c = conn.cursor()
    payment_id = _safe_int(item.get("entity_id"))
    if payment_id:
        payment = _get_finance_payment_row_from_conn(conn, payment_id)
        if payment:
            return payment
    external_id = (item.get("external_id") or "").strip()
    if external_id:
        c.execute("SELECT id FROM finance_payments WHERE external_sync_id=? ORDER BY id DESC LIMIT 1", (external_id,))
        row = c.fetchone()
        if row:
            return _get_finance_payment_row_from_conn(conn, _safe_int(row[0]))
        c.execute(
            """
            SELECT entity_id
            FROM integration_sync_queue
            WHERE system_name='1C' AND entity_type='finance_payment' AND external_id=?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (external_id,),
        )
        row = c.fetchone()
        if row:
            return _get_finance_payment_row_from_conn(conn, _safe_int(row[0]))
    source_document_type = (item.get("source_document_type") or "").strip()
    source_document_id = _safe_int(item.get("source_document_id"))
    if source_document_type and source_document_id:
        c.execute(
            """
            SELECT id
            FROM finance_payments
            WHERE source_document_type=? AND source_document_id=?
            ORDER BY updated_at DESC, id DESC LIMIT 1
            """,
            (source_document_type, source_document_id),
        )
        row = c.fetchone()
        if row:
            return _get_finance_payment_row_from_conn(conn, _safe_int(row[0]))
    return None


def _apply_inbound_finance_sync_item(conn, item: dict, actor_email: str = "", source_system: str = "1C") -> dict:
    item = _normalize_inbound_sync_item(item, "finance_payment")
    payload = {key: value for key, value in item.items() if not key.startswith("_")}
    if item.get("_validation_errors"):
        _record_integration_error_event(conn, 0, source_system, "finance_payment", _safe_int(item.get("entity_id")), "; ".join(item.get("_validation_errors") or []), payload, "warning", "inbound_validation_failed")
        return {"state": "conflict", "reason": "validation_failed", "errors": item.get("_validation_errors") or []}
    idempotency_key = _integration_idempotency_key(source_system, "finance_payment", item.get("entity_id") or item.get("external_id") or 0, "inbound", payload, item.get("idempotency_key", ""))
    request_hash = _payload_checksum({"source_system": source_system, "direction": "inbound", "payload": payload})
    existing_idempotency = _get_idempotency_record(conn, source_system, idempotency_key)
    if existing_idempotency and existing_idempotency.get("request_hash") == request_hash and existing_idempotency.get("status") in {"applied", "inbound_applied"}:
        if _finance_inbound_state_already_applied(conn, payload):
            cached = _json_load(existing_idempotency.get("response_payload"), {})
            cached["idempotent"] = True
            return cached or {"state": "applied", "idempotent": True}
    if existing_idempotency and existing_idempotency.get("request_hash") and existing_idempotency.get("request_hash") != request_hash:
        _record_integration_error_event(conn, _safe_int(existing_idempotency.get("queue_id")), source_system, "finance_payment", _safe_int(item.get("entity_id")), "Повторный idempotency_key пришёл с другим payload", payload, "critical", "idempotency_hash_mismatch")
        return {"state": "conflict", "reason": "idempotency_hash_mismatch"}
    payment = _find_finance_payment_by_sync_item(conn, item)
    queue_id = 0
    c = conn.cursor()
    if not payment:
        _log_sync_event(conn, 0, source_system, "finance_payment", _safe_int(item.get("entity_id")), "conflict", "Входящий документ 1С не удалось сопоставить с финансовой операцией", payload, (item.get("external_id") or "").strip())
        _record_integration_error_event(conn, 0, source_system, "finance_payment", _safe_int(item.get("entity_id")), "Входящий документ 1С не удалось сопоставить с финансовой операцией", payload, "warning", "payment_not_found")
        return {"state": "conflict", "reason": "payment_not_found"}
    payment_id = _safe_int(payment.get("id"))
    c.execute(
        """
        SELECT id
        FROM integration_sync_queue
        WHERE system_name='1C' AND entity_type='finance_payment' AND entity_id=?
        ORDER BY updated_at DESC, id DESC LIMIT 1
        """,
        (payment_id,),
    )
    row = c.fetchone()
    if row:
        queue_id = _safe_int(row[0])
    inbound_amount = _safe_float(item.get("amount"))
    current_amount = _safe_float(payment.get("amount"))
    if inbound_amount and abs(inbound_amount - current_amount) > 0.01 and not _safe_int(item.get("allow_amount_override")):
        _log_sync_event(conn, queue_id, source_system, "finance_payment", payment_id, "conflict", f"Сумма 1С ({inbound_amount}) не совпадает с CRM ({current_amount})", payload, (item.get("external_id") or "").strip())
        _record_integration_error_event(conn, queue_id, source_system, "finance_payment", payment_id, f"Сумма 1С ({inbound_amount}) не совпадает с CRM ({current_amount})", payload, "warning", "amount_mismatch")
        return {"state": "conflict", "reason": "amount_mismatch", "payment_id": payment_id}
    if item.get("source_document_type") and payment.get("source_document_type") and item.get("source_document_type") != payment.get("source_document_type"):
        _log_sync_event(conn, queue_id, source_system, "finance_payment", payment_id, "conflict", "Тип документа-источника 1С не совпадает с CRM", payload, (item.get("external_id") or "").strip())
        _record_integration_error_event(conn, queue_id, source_system, "finance_payment", payment_id, "Тип документа-источника 1С не совпадает с CRM", payload, "warning", "source_document_type_mismatch")
        return {"state": "conflict", "reason": "source_document_type_mismatch", "payment_id": payment_id}
    updated_amount = inbound_amount if inbound_amount and (_safe_int(item.get("allow_amount_override")) or abs(inbound_amount - current_amount) <= 0.01) else current_amount
    updated_status = _normalize_finance_status(item.get("status"), payment.get("status", "planned"))
    updated_due_date = (item.get("due_date") or payment.get("due_date") or "").strip()
    updated_paid_date = (item.get("paid_date") or payment.get("paid_date") or "").strip()
    if updated_status == "paid" and not updated_paid_date:
        updated_paid_date = _today_display()
    new_exchange_state = "synced" if updated_status in {"paid", "issued", "partially_paid", "overdue"} else (item.get("exchange_state") or "synced")
    c.execute(
        """
        UPDATE finance_payments
        SET amount=?, currency=?, due_date=?, paid_date=?, status=?, comment=?, external_sync_id=?, exchange_state=?, updated_at=?
        WHERE id=?
        """,
        (
            updated_amount,
            (item.get("currency") or payment.get("currency") or "RUB"),
            updated_due_date,
            updated_paid_date,
            updated_status,
            (item.get("comment") or payment.get("comment") or "")[:1000],
            (item.get("external_id") or payment.get("external_sync_id") or "").strip(),
            new_exchange_state,
            int(time.time()),
            payment_id,
        ),
    )
    refreshed = _get_finance_payment_row_from_conn(conn, payment_id)
    try:
        if refreshed:
            _rebuild_finance_accounting_entries(conn, refreshed, actor_email or "system:inbound_sync")
    except Exception as exc:
        _log_sync_event(conn, queue_id, source_system, "finance_payment", payment_id, "conflict", f"Не удалось применить проводки по входящему sync: {exc}", payload, (item.get("external_id") or "").strip())
        _record_integration_error_event(conn, queue_id, source_system, "finance_payment", payment_id, f"Не удалось применить проводки по входящему sync: {exc}", payload, "error", "accounting_rebuild_failed")
        return {"state": "conflict", "reason": "accounting_rebuild_failed", "payment_id": payment_id}
    c.execute(
        """
        UPDATE integration_sync_queue
        SET state='synced', direction='outbound', external_id=?, last_error='', locked_at=0, next_retry_at=0,
            processed_at=?, updated_at=?, consistency_state='consistent'
        WHERE system_name='1C' AND entity_type='finance_payment' AND entity_id=?
        """,
        ((item.get("external_id") or payment.get("external_sync_id") or "").strip(), int(time.time()), int(time.time()), payment_id),
    )
    _log_sync_event(conn, queue_id, source_system, "finance_payment", payment_id, "inbound_synced", "Входящий ответ 1С применён к финансовой операции", payload, (item.get("external_id") or "").strip())
    outcome = {"state": "applied", "payment_id": payment_id}
    _upsert_idempotency_record(conn, source_system, idempotency_key, "inbound", queue_id, request_hash, "applied", outcome)
    latest_payment = _get_finance_payment_row_from_conn(conn, payment_id) or refreshed or payment
    latest_checksum = _payload_checksum(_build_finance_sync_payload(latest_payment))
    _record_integration_consistency(conn, queue_id, source_system, "finance_payment", payment_id, (item.get("external_id") or payment.get("external_sync_id") or "").strip(), "consistent", latest_checksum, latest_checksum, {"source": "inbound_apply"})
    return outcome


def _finance_status_from_sales(payment_status: str) -> str:
    if payment_status == "paid":
        return "paid"
    if payment_status == "partially_paid":
        return "partially_paid"
    if payment_status in {"issued", "sent", "awaiting_payment"}:
        return "issued"
    return "planned"


def _finance_status_from_purchase(status: str) -> str:
    if status == "received":
        return "paid"
    if status in {"ordered", "in_transit"}:
        return "issued"
    return "planned"


def _finance_status_from_expense(status: str) -> str | None:
    if status == "rejected":
        return None
    if status == "paid":
        return "paid"
    if status == "approved":
        return "issued"
    return "planned"


def _delete_finance_payment_cascade(conn, payment_id: int):
    c = conn.cursor()
    c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
    c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?)", (payment_id,))
    c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
    c.execute("DELETE FROM edo_signature_registry WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
    c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))


def _delete_entity_runtime_links(conn, entity_type: str, entity_id: int):
    c = conn.cursor()
    c.execute("DELETE FROM notifications WHERE entity_type=? AND entity_id=?", (entity_type, str(entity_id)))
    c.execute("DELETE FROM erp_entity_links WHERE target_type=? AND target_id=?", (entity_type, str(entity_id)))
    process_field_map = {
        "internal_request": "request_id",
        "purchase": "purchase_id",
        "production_order": "production_id",
        "sales_document": "sales_doc_id",
    }
    field_name = process_field_map.get(entity_type)
    if field_name:
        c.execute(f"UPDATE erp_process_runs SET {field_name}=0, updated_at=? WHERE {field_name}=?", (int(time.time()), entity_id))


def _delete_source_finance_payment(conn, source_type: str, source_id: int) -> int:
    c = conn.cursor()
    c.execute(
        """
        SELECT id
        FROM finance_payments
        WHERE source_document_type=? AND source_document_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (source_type, source_id),
    )
    row = c.fetchone()
    payment_id = _safe_int(row[0]) if row else 0
    if payment_id:
        _delete_finance_payment_cascade(conn, payment_id)
    return payment_id


def _upsert_source_finance_payment(conn, source_type: str, source_id: int, payment_data: dict, actor_email: str = "", existing_payment_id: int = 0) -> int:
    c = conn.cursor()
    payment_id = _safe_int(existing_payment_id)
    if not payment_id:
        c.execute(
            """
            SELECT id
            FROM finance_payments
            WHERE source_document_type=? AND source_document_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (source_type, source_id),
        )
        row = c.fetchone()
        payment_id = _safe_int(row[0]) if row else 0
    if payment_data.get("status") is None:
        if payment_id:
            _delete_finance_payment_cascade(conn, payment_id)
        return 0
    dims = {
        "legal_entity_id": _safe_int(payment_data.get("legal_entity_id")),
        "business_unit_id": _safe_int(payment_data.get("business_unit_id")),
        "treasury_article_id": _safe_int(payment_data.get("treasury_article_id")),
        "vat_rate_id": _safe_int(payment_data.get("vat_rate_id")),
    }
    if payment_data.get("kind") == "outgoing":
        limit_check = _check_treasury_limit(
            conn,
            dims,
            _safe_float(payment_data.get("amount")),
            payment_data.get("due_date", "") or payment_data.get("paid_date", ""),
            payment_id,
        )
        if not limit_check["ok"]:
            raise HTTPException(
                status_code=400,
                detail=f"Лимит по статье ДДС превышен. План: {limit_check['planned_total']}, лимит: {limit_check['amount_limit']}",
            )
    now = int(time.time())
    columns = (
        payment_data["project_id"],
        payment_data["client_id"],
        payment_data["contract_id"],
        payment_data["object_id"],
        payment_data["legal_entity_id"],
        payment_data["business_unit_id"],
        payment_data["treasury_article_id"],
        payment_data["vat_rate_id"],
        source_type,
        source_id,
        payment_data["title"],
        payment_data["kind"],
        payment_data["category"],
        _safe_float(payment_data["amount"]),
        payment_data["currency"],
        payment_data["due_date"],
        payment_data["paid_date"],
        payment_data["status"],
        payment_data["comment"],
        _payment_exchange_state(payment_data["status"]),
    )
    if payment_id:
        c.execute(
            """
            UPDATE finance_payments
            SET project_id=?, client_id=?, contract_id=?, object_id=?, legal_entity_id=?, business_unit_id=?, treasury_article_id=?,
                vat_rate_id=?, source_document_type=?, source_document_id=?, title=?, kind=?, category=?, amount=?, currency=?, due_date=?,
                paid_date=?, status=?, comment=?, exchange_state=?, updated_at=?
            WHERE id=?
            """,
            (*columns, now, payment_id),
        )
    else:
        c.execute(
            """
            INSERT INTO finance_payments (
                project_id, client_id, contract_id, object_id, legal_entity_id, business_unit_id, treasury_article_id,
                vat_rate_id, source_document_type, source_document_id, title, kind, category, amount, currency, due_date,
                paid_date, status, comment, exchange_state, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*columns, actor_email or "", now, now),
        )
        payment_id = c.lastrowid
    payment_row = _get_finance_payment_row_from_conn(conn, payment_id)
    if payment_row:
        _rebuild_finance_accounting_entries(conn, payment_row, actor_email)
        _upsert_finance_sync_job(conn, payment_row, actor_email)
    return payment_id


def _sync_sales_finance_link(conn, document_id: int, actor_email: str = "") -> int:
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute("SELECT * FROM sales_documents_extended WHERE id=?", (document_id,))
    row = c.fetchone()
    if not row:
        return 0
    doc = dict(row)
    context = _resolve_master_context(conn, _safe_int(doc.get("project_id")), _safe_int(doc.get("client_id")), _safe_int(doc.get("contract_id")), _safe_int(doc.get("object_id")))
    dims = _resolve_finance_dimensions(
        conn,
        FinancePaymentData(
            project_id=context["project_id"],
            client_id=context["client_id"],
            contract_id=context["contract_id"],
            object_id=context["object_id"],
            legal_entity_id=_safe_int(doc.get("legal_entity_id")),
            business_unit_id=_safe_int(doc.get("business_unit_id")),
            kind="incoming",
            category=doc.get("doc_type", "invoice"),
            amount=_safe_float(doc.get("amount")),
            currency=doc.get("currency", "RUB"),
            due_date=doc.get("payment_due_date") or doc.get("doc_date", ""),
            paid_date=doc.get("confirmed_at", "") if doc.get("payment_status") == "paid" else "",
            status=_finance_status_from_sales(doc.get("payment_status", "planned")),
            comment=doc.get("comment", ""),
            source_document_type="sales_document",
            source_document_id=document_id,
        ),
        context,
    )
    payment_id = _upsert_source_finance_payment(
        conn,
        "sales_document",
        document_id,
        {
            **context,
            **dims,
            "title": f"Реализация {doc.get('doc_number') or f'#{document_id}'}",
            "kind": "incoming",
            "category": doc.get("doc_type", "invoice"),
            "amount": _safe_float(doc.get("amount")),
            "currency": doc.get("currency", "RUB"),
            "due_date": doc.get("payment_due_date") or doc.get("doc_date", ""),
            "paid_date": doc.get("confirmed_at", "") if doc.get("payment_status") == "paid" else "",
            "status": _finance_status_from_sales(doc.get("payment_status", "planned")),
            "comment": doc.get("comment", "") or "Автосвязь из документа реализации",
        },
        actor_email,
        _safe_int(doc.get("linked_payment_id")),
    )
    c.execute("UPDATE sales_documents_extended SET linked_payment_id=?, updated_at=? WHERE id=?", (payment_id, int(time.time()), document_id))
    return payment_id


def _sync_purchase_finance_link(conn, purchase_id: int, actor_email: str = "") -> int:
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute("SELECT * FROM purchase_orders WHERE id=?", (purchase_id,))
    row = c.fetchone()
    if not row:
        return 0
    purchase = dict(row)
    context = _resolve_master_context(conn, _safe_int(purchase.get("project_id")), _safe_int(purchase.get("client_id")), _safe_int(purchase.get("contract_id")), _safe_int(purchase.get("object_id")))
    dims = _resolve_finance_dimensions(
        conn,
        FinancePaymentData(
            project_id=context["project_id"],
            client_id=context["client_id"],
            contract_id=context["contract_id"],
            object_id=context["object_id"],
            legal_entity_id=_safe_int(purchase.get("legal_entity_id")),
            business_unit_id=_safe_int(purchase.get("business_unit_id")),
            kind="outgoing",
            category="purchase",
            amount=_safe_float(purchase.get("total_amount")),
            currency="RUB",
            due_date=purchase.get("expected_date", ""),
            paid_date=purchase.get("received_date", "") if purchase.get("status") == "received" else "",
            status=_finance_status_from_purchase(purchase.get("status", "planned")),
            comment=purchase.get("comment", ""),
            source_document_type="purchase_order",
            source_document_id=purchase_id,
        ),
        context,
    )
    return _upsert_source_finance_payment(
        conn,
        "purchase_order",
        purchase_id,
        {
            **context,
            **dims,
            "title": f"Закупка: {purchase.get('item_name') or purchase.get('item_article') or purchase_id}",
            "kind": "outgoing",
            "category": "purchase",
            "amount": _safe_float(purchase.get("total_amount")),
            "currency": "RUB",
            "due_date": purchase.get("expected_date", ""),
            "paid_date": purchase.get("received_date", "") if purchase.get("status") == "received" else "",
            "status": _finance_status_from_purchase(purchase.get("status", "planned")),
            "comment": purchase.get("comment", "") or f"Автосвязь закупки · поставщик {purchase.get('supplier', '—')}",
        },
        actor_email,
    )


def _sync_expense_finance_link(conn, request_id: int, actor_email: str = "") -> int:
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute("SELECT * FROM expense_requests WHERE id=?", (request_id,))
    row = c.fetchone()
    if not row:
        return 0
    expense = dict(row)
    finance_status = _finance_status_from_expense(expense.get("status", "draft"))
    context = _resolve_master_context(conn, _safe_int(expense.get("project_id")), _safe_int(expense.get("client_id")), _safe_int(expense.get("contract_id")), _safe_int(expense.get("object_id")))
    dims = _resolve_finance_dimensions(
        conn,
        FinancePaymentData(
            project_id=context["project_id"],
            client_id=context["client_id"],
            contract_id=context["contract_id"],
            object_id=context["object_id"],
            kind="outgoing",
            category=expense.get("request_type", "expense"),
            amount=_safe_float(expense.get("amount")),
            currency=expense.get("currency", "RUB"),
            due_date=expense.get("due_date", ""),
            paid_date=_today_display() if finance_status == "paid" else "",
            status=finance_status or "planned",
            comment=expense.get("comment", ""),
            source_document_type="expense_request",
            source_document_id=request_id,
        ),
        context,
    )
    payment_id = _upsert_source_finance_payment(
        conn,
        "expense_request",
        request_id,
        {
            **context,
            **dims,
            "title": expense.get("title", "") or f"Расход #{request_id}",
            "kind": "outgoing",
            "category": expense.get("request_type", "expense"),
            "amount": _safe_float(expense.get("amount")),
            "currency": expense.get("currency", "RUB"),
            "due_date": expense.get("due_date", ""),
            "paid_date": _today_display() if finance_status == "paid" else "",
            "status": finance_status,
            "comment": expense.get("comment", "") or "Автосвязь из заявки на расход",
        },
        actor_email,
        _safe_int(expense.get("linked_payment_id")),
    )
    c.execute("UPDATE expense_requests SET linked_payment_id=?, updated_at=? WHERE id=?", (payment_id, int(time.time()), request_id))
    return payment_id


def _finance_dashboard_payload(rows: list[dict]):
    incoming_open = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "incoming" and row.get("status") != "paid")
    outgoing_open = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "outgoing" and row.get("status") != "paid")
    received_total = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "incoming" and row.get("status") == "paid")
    spent_total = sum(_safe_float(row.get("amount")) for row in rows if row.get("kind") == "outgoing" and row.get("status") == "paid")
    overdue_receivables = sum(
        _safe_float(row.get("amount"))
        for row in rows
        if row.get("kind") == "incoming" and _is_overdue(row.get("status", ""), row.get("due_date", ""))
    )
    overdue_payables = sum(
        _safe_float(row.get("amount"))
        for row in rows
        if row.get("kind") == "outgoing" and _is_overdue(row.get("status", ""), row.get("due_date", ""))
    )
    return {
        "metrics": {
            "incoming_open": round(incoming_open, 2),
            "outgoing_open": round(outgoing_open, 2),
            "received_total": round(received_total, 2),
            "spent_total": round(spent_total, 2),
            "overdue_receivables": round(overdue_receivables, 2),
            "overdue_payables": round(overdue_payables, 2),
            "cash_gap": round(received_total - spent_total + incoming_open - outgoing_open, 2),
        },
        "recent": rows[:10],
        "overdue": [row for row in rows if _is_overdue(row.get("status", ""), row.get("due_date", ""))][:10],
    }


def _load_purchase_rows():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            po.*,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract,
            COALESCE(cl.name, '') AS client_name,
            COALESCE(le.short_name, le.name, '') AS legal_entity_name,
            COALESCE(bu.name, '') AS business_unit_name,
            COALESCE(fp.id, 0) AS linked_payment_id,
            COALESCE(fp.status, '') AS linked_payment_status,
            COALESCE(fp.exchange_state, '') AS linked_payment_exchange_state
        FROM purchase_orders po
        LEFT JOIN projects p ON p.id = po.project_id
        LEFT JOIN clients cl ON cl.id = po.client_id
        LEFT JOIN legal_entities le ON le.id = po.legal_entity_id
        LEFT JOIN business_units bu ON bu.id = po.business_unit_id
        LEFT JOIN finance_payments fp ON fp.source_document_type='purchase_order' AND fp.source_document_id = po.id
        ORDER BY po.created_at DESC, po.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_sales_rows():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            sd.*,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract,
            COALESCE(cl.name, '') AS client_name,
            COALESCE(le.short_name, le.name, '') AS legal_entity_name,
            COALESCE(bu.name, '') AS business_unit_name,
            COALESCE(fp.status, '') AS linked_payment_status,
            COALESCE(fp.exchange_state, '') AS linked_payment_exchange_state
        FROM sales_documents_extended sd
        LEFT JOIN projects p ON p.id = sd.project_id
        LEFT JOIN clients cl ON cl.id = sd.client_id
        LEFT JOIN legal_entities le ON le.id = sd.legal_entity_id
        LEFT JOIN business_units bu ON bu.id = sd.business_unit_id
        LEFT JOIN finance_payments fp ON fp.id = sd.linked_payment_id
        ORDER BY sd.created_at DESC, sd.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_production_rows():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            pr.*,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract,
            COALESCE(cl.name, '') AS client_name,
            COALESCE(le.short_name, le.name, '') AS legal_entity_name,
            COALESCE(bu.name, '') AS business_unit_name,
            COALESCE(po.operations_count, 0) AS operations_count,
            COALESCE(po.planned_hours_total, 0) AS ops_planned_hours,
            COALESCE(po.actual_hours_total, 0) AS ops_actual_hours,
            COALESCE(po.planned_qty_total, 0) AS ops_planned_qty,
            COALESCE(po.completed_qty_total, 0) AS ops_completed_qty,
            COALESCE(po.scrap_qty_total, 0) AS ops_scrap_qty,
            COALESCE(po.actual_cost_total, 0) AS ops_actual_cost
        FROM production_orders pr
        LEFT JOIN projects p ON p.id = pr.project_id
        LEFT JOIN clients cl ON cl.id = pr.client_id
        LEFT JOIN legal_entities le ON le.id = pr.legal_entity_id
        LEFT JOIN business_units bu ON bu.id = pr.business_unit_id
        LEFT JOIN (
            SELECT
                order_id,
                COUNT(*) AS operations_count,
                COALESCE(SUM(planned_hours), 0) AS planned_hours_total,
                COALESCE(SUM(actual_hours), 0) AS actual_hours_total,
                COALESCE(SUM(planned_qty), 0) AS planned_qty_total,
                COALESCE(SUM(completed_qty), 0) AS completed_qty_total,
                COALESCE(SUM(scrap_qty), 0) AS scrap_qty_total,
                COALESCE(SUM((actual_hours * labor_rate) + material_cost + overhead_cost), 0) AS actual_cost_total
            FROM production_operations
            GROUP BY order_id
        ) po ON po.order_id = pr.id
        ORDER BY pr.created_at DESC, pr.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    bom_totals = _load_production_bom_totals()
    for row in rows:
        bom = bom_totals.get(int(row.get("id") or 0), {})
        row["planned_qty_total"] = round(max(_safe_float(row.get("planned_qty")), _safe_float(row.get("ops_planned_qty"))), 2)
        row["produced_qty_total"] = round(max(_safe_float(row.get("produced_qty")), _safe_float(row.get("ops_completed_qty"))), 2)
        row["scrap_qty_total"] = round(max(_safe_float(row.get("scrap_qty")), _safe_float(row.get("ops_scrap_qty"))), 2)
        row["labor_hours_total"] = round(max(_safe_float(row.get("labor_hours_fact")), _safe_float(row.get("ops_actual_hours"))), 2)
        row["bom_items_count"] = _safe_int(bom.get("bom_items_count"))
        row["planned_material_cost"] = round(_safe_float(bom.get("planned_material_cost")), 2)
        row["actual_material_cost"] = round(_safe_float(bom.get("actual_material_cost")), 2)
        row["actual_cost_total"] = round(max(_safe_float(row.get("actual_cost")), _safe_float(row.get("ops_actual_cost")), _safe_float(bom.get("actual_material_cost"))), 2)
        row["planned_cost_total"] = round(max(_safe_float(row.get("planned_cost")), _safe_float(bom.get("planned_material_cost"))), 2)
        if not _safe_int(row.get("progress")) and _safe_float(row.get("planned_qty_total")) > 0:
            row["progress"] = min(100, round((_safe_float(row.get("produced_qty_total")) / _safe_float(row.get("planned_qty_total"))) * 100))
    return rows


def _load_production_operation_rows(order_id: int = 0):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    params = []
    query = """
        SELECT
            po.*,
            COALESCE(pr.order_name, '') AS order_name,
            COALESCE(pr.stage, '') AS order_stage,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract,
            COALESCE(cl.name, '') AS client_name
        FROM production_operations po
        LEFT JOIN production_orders pr ON pr.id = po.order_id
        LEFT JOIN projects p ON p.id = pr.project_id
        LEFT JOIN clients cl ON cl.id = pr.client_id
    """
    if order_id:
        query += " WHERE po.order_id=?"
        params.append(order_id)
    query += " ORDER BY po.order_id DESC, po.sequence_no ASC, po.id ASC"
    c.execute(query, tuple(params))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["actual_cost"] = round((_safe_float(row.get("actual_hours")) * _safe_float(row.get("labor_rate"))) + _safe_float(row.get("material_cost")) + _safe_float(row.get("overhead_cost")), 2)
    return rows


def _load_production_bom_totals():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            order_id,
            COUNT(*) AS bom_items_count,
            COALESCE(SUM(planned_qty * unit_cost), 0) AS planned_material_cost,
            COALESCE(SUM(actual_qty * unit_cost), 0) AS actual_material_cost
        FROM production_bom_items
        GROUP BY order_id
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return {int(row.get("order_id") or 0): row for row in rows}


def _load_production_bom_rows(order_id: int = 0):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    params = []
    query = """
        SELECT
            pb.*,
            COALESCE(pr.order_name, '') AS order_name,
            COALESCE(n.name, pb.item_name) AS nomenclature_name
        FROM production_bom_items pb
        LEFT JOIN production_orders pr ON pr.id = pb.order_id
        LEFT JOIN nomenclature n ON n.article = pb.article
    """
    if order_id:
        query += " WHERE pb.order_id=?"
        params.append(order_id)
    query += " ORDER BY pb.order_id DESC, pb.id DESC"
    c.execute(query, tuple(params))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["planned_cost"] = round(_safe_float(row.get("planned_qty")) * _safe_float(row.get("unit_cost")), 2)
        row["actual_cost"] = round(_safe_float(row.get("actual_qty")) * _safe_float(row.get("unit_cost")), 2)
    return rows


def _load_production_route_rows(order_id: int = 0):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    params = []
    query = """
        SELECT
            rt.*,
            COALESCE(pr.order_name, '') AS order_name
        FROM production_route_templates rt
        LEFT JOIN production_orders pr ON pr.id = rt.order_id
    """
    if order_id:
        query += " WHERE rt.order_id=?"
        params.append(order_id)
    query += " ORDER BY rt.order_id DESC, rt.sequence_no ASC, rt.id ASC"
    c.execute(query, tuple(params))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["planned_cost"] = round(_safe_float(row.get("planned_hours")) * _safe_float(row.get("labor_rate")), 2)
    return rows


def _rebuild_production_bom_rollup(conn, order_id: int):
    c = conn.cursor()
    c.execute(
        """
        SELECT
            COALESCE(SUM(planned_qty * unit_cost), 0),
            COALESCE(SUM(actual_qty * unit_cost), 0),
            COUNT(*)
        FROM production_bom_items
        WHERE order_id=?
        """,
        (order_id,),
    )
    planned_material_cost, actual_material_cost, bom_items_count = c.fetchone()
    c.execute("SELECT planned_cost, actual_cost, comment FROM production_orders WHERE id=?", (order_id,))
    row = c.fetchone()
    if not row:
        return
    planned_cost = max(_safe_float(row[0]), round(_safe_float(planned_material_cost), 2))
    actual_cost = max(_safe_float(row[1]), round(_safe_float(actual_material_cost), 2))
    comment = row[2] or ""
    if bom_items_count and "BOM:" not in comment:
        comment = (comment.strip() + ("\n" if comment.strip() else "") + f"BOM: {bom_items_count} поз.").strip()
    c.execute(
        "UPDATE production_orders SET planned_cost=?, actual_cost=?, comment=?, updated_at=? WHERE id=?",
        (planned_cost, actual_cost, comment, int(time.time()), order_id),
    )


def _apply_route_templates_to_order(conn, order_id: int, actor_email: str = ""):
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM production_route_templates WHERE order_id=?", (order_id,))
    if _safe_int(c.fetchone()[0]) == 0:
        return {"created": 0}
    c.execute("DELETE FROM production_operations WHERE order_id=?", (order_id,))
    now = int(time.time())
    c.execute(
        """
        SELECT sequence_no, operation_name, work_center, planned_hours, planned_qty, labor_rate, note
        FROM production_route_templates
        WHERE order_id=?
        ORDER BY sequence_no ASC, id ASC
        """,
        (order_id,),
    )
    created = 0
    for sequence_no, operation_name, work_center, planned_hours, planned_qty, labor_rate, note in c.fetchall():
        c.execute(
            """
            INSERT INTO production_operations (
                order_id, sequence_no, operation_name, work_center, status, planned_hours, actual_hours,
                planned_qty, completed_qty, scrap_qty, labor_rate, material_cost, overhead_cost,
                started_at, finished_at, note, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'planned', ?, 0, ?, 0, 0, ?, 0, 0, '', '', ?, ?, ?, ?)
            """,
            (order_id, sequence_no, operation_name, work_center, planned_hours, planned_qty, labor_rate, note or "", actor_email or "", now, now),
        )
        created += 1
    _sync_production_order_rollup(conn, order_id)
    return {"created": created}


def _load_inventory_discrepancy_rows(limit: int = 120):
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute(
        """
        SELECT
            d.*,
            COALESCE(n.name, '') AS nomenclature_name,
            COALESCE(n.unit, 'шт') AS unit
        FROM inventory_documents d
        LEFT JOIN nomenclature n ON n.article = d.article
        WHERE ABS(COALESCE(d.adjustment_qty, 0)) > 0.0001
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT ?
        """,
        (max(1, min(limit, 500)),),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _sync_production_order_rollup(conn, order_id: int):
    c = conn.cursor()
    c.execute("SELECT planned_qty, actual_finish, stage FROM production_orders WHERE id=?", (order_id,))
    order_row = c.fetchone()
    if not order_row:
        return
    planned_qty = _safe_float(order_row[0])
    current_actual_finish = order_row[1] or ""
    current_stage = order_row[2] or "queue"
    c.execute(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(actual_hours), 0),
            COALESCE(SUM(completed_qty), 0),
            COALESCE(SUM(scrap_qty), 0),
            COALESCE(SUM((actual_hours * labor_rate) + material_cost + overhead_cost), 0),
            SUM(CASE WHEN status IN ('done', 'completed') THEN 1 ELSE 0 END),
            SUM(CASE WHEN status IN ('in_progress', 'otk', 'done', 'completed') THEN 1 ELSE 0 END)
        FROM production_operations
        WHERE order_id=?
        """,
        (order_id,),
    )
    row = c.fetchone()
    operations_count = _safe_int(row[0])
    labor_hours_fact = round(_safe_float(row[1]), 2)
    produced_qty = round(_safe_float(row[2]), 2)
    scrap_qty = round(_safe_float(row[3]), 2)
    actual_cost = round(_safe_float(row[4]), 2)
    try:
        c.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN layer_type IN ('material','labor') THEN actual_amount ELSE 0 END), 0)
                + COALESCE(SUM(CASE WHEN layer_type='overhead' THEN overhead_amount ELSE 0 END), 0)
            FROM production_cost_layers
            WHERE production_order_id=? AND layer_type IN ('material', 'labor', 'overhead')
            """,
            (order_id,),
        )
        actual_cost = round(max(actual_cost, _safe_float((c.fetchone() or [0])[0])), 2)
    except Exception:
        pass
    completed_ops = _safe_int(row[5])
    active_ops = _safe_int(row[6])
    progress = 0
    if planned_qty > 0:
        progress = min(100, round((produced_qty / planned_qty) * 100))
    elif operations_count:
        progress = min(100, round((completed_ops / operations_count) * 100))
    stage = current_stage
    if operations_count and completed_ops == operations_count:
        stage = "done"
    elif active_ops:
        stage = "in_work"
    elif operations_count:
        stage = "queue"
    actual_finish = current_actual_finish
    if stage == "done" and not actual_finish:
        actual_finish = _today_display()
    c.execute(
        """
        UPDATE production_orders
        SET produced_qty=?, scrap_qty=?, actual_cost=?, labor_hours_fact=?, progress=?, stage=?, actual_finish=?, updated_at=?
        WHERE id=?
        """,
        (produced_qty, scrap_qty, actual_cost, labor_hours_fact, progress, stage, actual_finish, int(time.time()), order_id),
    )


def _load_stock_reservations():
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute(
        """
        SELECT
            sr.*,
            COALESCE(le.short_name, le.name, '') AS legal_entity_name,
            COALESCE(bu.name, '') AS business_unit_name
        FROM stock_reservations sr
        LEFT JOIN legal_entities le ON le.id = sr.legal_entity_id
        LEFT JOIN business_units bu ON bu.id = sr.business_unit_id
        ORDER BY sr.created_at DESC, sr.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _enrich_stock_reservation_rows(rows: list[dict]):
    enriched = []
    for row in rows:
        item = dict(row)
        qty = _safe_float(item.get("qty"))
        fulfilled = _safe_float(item.get("fulfilled_qty"))
        item["qty"] = round(qty, 3)
        item["fulfilled_qty"] = round(fulfilled, 3)
        item["remaining_qty"] = round(max(qty - fulfilled, 0), 3)
        enriched.append(item)
    return enriched


def _load_expense_request_rows():
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute(
        """
        SELECT
            er.*,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract,
            COALESCE(cl.name, '') AS client_name,
            COALESCE(fp.status, '') AS linked_payment_status,
            COALESCE(fp.exchange_state, '') AS linked_payment_exchange_state
        FROM expense_requests er
        LEFT JOIN projects p ON p.id = er.project_id
        LEFT JOIN clients cl ON cl.id = er.client_id
        LEFT JOIN finance_payments fp ON fp.id = er.linked_payment_id
        ORDER BY er.created_at DESC, er.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_internal_request_rows():
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute(
        """
        SELECT
            ir.*,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract
        FROM internal_requests ir
        LEFT JOIN projects p ON p.id = ir.project_id
        ORDER BY ir.created_at DESC, ir.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_resource_allocations():
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute(
        """
        SELECT
            ra.*,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract
        FROM resource_allocations ra
        LEFT JOIN projects p ON p.id = ra.project_id
        ORDER BY ra.date_from ASC, ra.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_service_cases():
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute(
        """
        SELECT
            sc.*,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract,
            COALESCE(cl.name, '') AS client_name
        FROM service_cases sc
        LEFT JOIN projects p ON p.id = sc.project_id
        LEFT JOIN clients cl ON cl.id = sc.client_id
        ORDER BY sc.created_at DESC, sc.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_budget_lines():
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute(
        """
        SELECT
            bl.*,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract
        FROM project_budget_lines bl
        LEFT JOIN projects p ON p.id = bl.project_id
        ORDER BY bl.created_at DESC, bl.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_stock_movements(article: str = ""):
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    if article:
        c.execute("SELECT * FROM stock_movements WHERE article=? ORDER BY created_at DESC, id DESC", (article,))
    else:
        c.execute("SELECT * FROM stock_movements ORDER BY created_at DESC, id DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_inventory_balances(article: str = ""):
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    if article:
        c.execute(
            """
            SELECT ib.*, COALESCE(n.name, '') AS nomenclature_name, COALESCE(n.unit, 'шт') AS unit
            FROM inventory_balances ib
            LEFT JOIN nomenclature n ON n.article = ib.article
            WHERE ib.article=?
            ORDER BY ib.warehouse ASC, ib.bin_code ASC, ib.id ASC
            """,
            (article,),
        )
    else:
        c.execute(
            """
            SELECT ib.*, COALESCE(n.name, '') AS nomenclature_name, COALESCE(n.unit, 'шт') AS unit
            FROM inventory_balances ib
            LEFT JOIN nomenclature n ON n.article = ib.article
            ORDER BY ib.article ASC, ib.warehouse ASC, ib.bin_code ASC, ib.id ASC
            """
        )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _load_inventory_lots(article: str = ""):
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    if article:
        c.execute(
            """
            SELECT il.*, COALESCE(n.name, '') AS nomenclature_name, COALESCE(n.unit, 'шт') AS unit
            FROM inventory_lots il
            LEFT JOIN nomenclature n ON n.article = il.article
            WHERE il.article=?
            ORDER BY il.warehouse ASC, il.bin_code ASC, il.batch_code ASC, il.serial_no ASC, il.id ASC
            """,
            (article,),
        )
    else:
        c.execute(
            """
            SELECT il.*, COALESCE(n.name, '') AS nomenclature_name, COALESCE(n.unit, 'шт') AS unit
            FROM inventory_lots il
            LEFT JOIN nomenclature n ON n.article = il.article
            ORDER BY il.article ASC, il.warehouse ASC, il.bin_code ASC, il.batch_code ASC, il.serial_no ASC, il.id ASC
            """
        )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _nsi_master_config(entity_type: str) -> dict | None:
    entity_type = (entity_type or "").strip()
    now_ts = int(time.time())
    config = {
        "warehouses": {
            "table": "warehouse_master",
            "label": "warehouse_master",
            "fields": ["name", "code", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _normalize_spaces(data.name),
                _normalize_spaces(data.code) or re.sub(r"[^A-Z0-9]+", "-", _normalize_match(data.name).upper())[:32] or f"WH-{now_ts}",
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
        },
        "units": {
            "table": "unit_master",
            "label": "unit_master",
            "fields": ["name", "code", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _normalize_spaces(data.name),
                _normalize_spaces(data.code) or re.sub(r"[^A-Z0-9]+", "-", _normalize_match(data.name).upper())[:32] or f"UNIT-{now_ts}",
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
        },
        "groups": {
            "table": "nomenclature_groups",
            "label": "nomenclature_group",
            "fields": ["name", "code", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _normalize_spaces(data.name),
                _normalize_spaces(data.code) or re.sub(r"[^A-Z0-9]+", "-", _normalize_match(data.name).upper())[:32] or f"GRP-{now_ts}",
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
        },
        "employees": {
            "table": "employee_master",
            "label": "employee_master",
            "fields": ["full_name", "personnel_number", "email", "phone", "position_id", "legal_entity_id", "business_unit_id", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _normalize_spaces(data.name),
                _normalize_spaces(data.personnel_number),
                _normalize_spaces(data.email),
                _normalize_spaces(data.phone),
                _safe_int(data.position_id),
                _safe_int(data.legal_entity_id),
                _safe_int(data.business_unit_id),
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
        },
        "positions": {
            "table": "position_master",
            "label": "position_master",
            "fields": ["name", "code", "department_name", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _normalize_spaces(data.name),
                _normalize_spaces(data.code) or re.sub(r"[^A-Z0-9]+", "-", _normalize_match(data.name).upper())[:32] or f"POS-{now_ts}",
                _normalize_spaces(data.department_name),
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
        },
        "characteristics": {
            "table": "nomenclature_characteristics",
            "label": "nomenclature_characteristic",
            "fields": ["name", "code", "characteristic_type", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _normalize_spaces(data.name),
                _normalize_spaces(data.code) or re.sub(r"[^A-Z0-9]+", "-", _normalize_match(data.name).upper())[:32] or f"CHAR-{now_ts}",
                _normalize_spaces(data.characteristic_type),
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
        },
        "storage_cells": {
            "table": "storage_cells",
            "label": "storage_cell",
            "fields": ["warehouse_id", "name", "code", "zone_name", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _safe_int(data.warehouse_id),
                _normalize_spaces(data.name),
                _normalize_spaces(data.code) or re.sub(r"[^A-Z0-9]+", "-", _normalize_match(data.name).upper())[:32] or f"CELL-{now_ts}",
                _normalize_spaces(data.zone_name),
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
        },
        "income_expense_articles": {
            "table": "income_expense_articles",
            "label": "income_expense_article",
            "fields": ["name", "code", "article_kind", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _normalize_spaces(data.name),
                _normalize_spaces(data.code) or re.sub(r"[^A-Z0-9]+", "-", _normalize_match(data.name).upper())[:32] or f"PL-{now_ts}",
                (_normalize_spaces(data.article_kind) or "expense") if _normalize_spaces(data.article_kind) in {"income", "expense"} else "expense",
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
        },
        "financial_responsibility_centers": {
            "table": "financial_responsibility_centers",
            "label": "financial_responsibility_center",
            "fields": ["name", "code", "legal_entity_id", "business_unit_id", "manager_name", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _normalize_spaces(data.name),
                _normalize_spaces(data.code) or re.sub(r"[^A-Z0-9]+", "-", _normalize_match(data.name).upper())[:32] or f"CFR-{now_ts}",
                _safe_int(data.legal_entity_id),
                _safe_int(data.business_unit_id),
                _normalize_spaces(data.manager_name),
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
        },
        "operation_types": {
            "table": "operation_types",
            "label": "operation_type",
            "fields": ["name", "code", "module_name", "flow_kind", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _normalize_spaces(data.name),
                _normalize_spaces(data.code) or re.sub(r"[^A-Z0-9]+", "-", _normalize_match(data.name).upper())[:32] or f"OP-{now_ts}",
                _normalize_spaces(data.module_name),
                _normalize_spaces(data.flow_kind),
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
        },
        "bank_accounts": {
            "table": "bank_accounts",
            "label": "bank_account",
            "fields": ["name", "code", "bank_name", "account_number", "bik", "currency", "legal_entity_id", "is_active", "comment", "updated_at"],
            "payload": lambda data: (
                _normalize_spaces(data.name),
                _normalize_spaces(data.code) or re.sub(r"[^A-Z0-9]+", "-", _normalize_match(data.name or data.bank_name).upper())[:32] or f"BA-{now_ts}",
                _normalize_spaces(data.bank_name),
                _normalize_spaces(data.account_number),
                _normalize_spaces(data.bik),
                _normalize_spaces(data.currency) or "RUB",
                _safe_int(data.legal_entity_id),
                1 if _safe_int(data.is_active) else 0,
                _normalize_spaces(data.comment),
                now_ts,
            ),
            "finance_only": True,
        },
    }
    return config.get(entity_type)


def _load_nsi_master_data(actor: dict | None = None):
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    payload = {
        "warehouses": [dict(row) for row in c.execute("SELECT * FROM warehouse_master ORDER BY is_active DESC, name ASC").fetchall()],
        "units": [dict(row) for row in c.execute("SELECT * FROM unit_master ORDER BY is_active DESC, name ASC").fetchall()],
        "groups": [dict(row) for row in c.execute("SELECT * FROM nomenclature_groups ORDER BY is_active DESC, name ASC").fetchall()],
        "positions": [dict(row) for row in c.execute("SELECT * FROM position_master ORDER BY is_active DESC, name ASC").fetchall()],
        "characteristics": [dict(row) for row in c.execute("SELECT * FROM nomenclature_characteristics ORDER BY is_active DESC, name ASC").fetchall()],
        "income_expense_articles": [dict(row) for row in c.execute("SELECT * FROM income_expense_articles ORDER BY is_active DESC, article_kind ASC, name ASC").fetchall()],
        "operation_types": [dict(row) for row in c.execute("SELECT * FROM operation_types ORDER BY is_active DESC, module_name ASC, name ASC").fetchall()],
        "legal_entities": [dict(row) for row in c.execute("SELECT * FROM legal_entities WHERE is_active=1 ORDER BY name ASC").fetchall()],
        "business_units": [
            dict(row) for row in c.execute(
                """
                SELECT bu.*, le.short_name AS legal_entity_name
                FROM business_units bu
                LEFT JOIN legal_entities le ON le.id = bu.legal_entity_id
                WHERE bu.is_active=1
                ORDER BY bu.name ASC
                """
            ).fetchall()
        ],
        "employees": [
            dict(row) for row in c.execute(
                """
                SELECT em.*, pm.name AS position_name, le.short_name AS legal_entity_name, bu.name AS business_unit_name
                FROM employee_master em
                LEFT JOIN position_master pm ON pm.id = em.position_id
                LEFT JOIN legal_entities le ON le.id = em.legal_entity_id
                LEFT JOIN business_units bu ON bu.id = em.business_unit_id
                ORDER BY em.is_active DESC, em.full_name ASC
                """
            ).fetchall()
        ],
        "storage_cells": [
            dict(row) for row in c.execute(
                """
                SELECT sc.*, wm.name AS warehouse_name
                FROM storage_cells sc
                LEFT JOIN warehouse_master wm ON wm.id = sc.warehouse_id
                ORDER BY sc.is_active DESC, COALESCE(wm.name, ''), sc.name ASC
                """
            ).fetchall()
        ],
        "financial_responsibility_centers": [
            dict(row) for row in c.execute(
                """
                SELECT frc.*, le.short_name AS legal_entity_name, bu.name AS business_unit_name
                FROM financial_responsibility_centers frc
                LEFT JOIN legal_entities le ON le.id = frc.legal_entity_id
                LEFT JOIN business_units bu ON bu.id = frc.business_unit_id
                ORDER BY frc.is_active DESC, frc.name ASC
                """
            ).fetchall()
        ],
        "bank_accounts": [
            dict(row) for row in c.execute(
                """
                SELECT ba.*, le.short_name AS legal_entity_name
                FROM bank_accounts ba
                LEFT JOIN legal_entities le ON le.id = ba.legal_entity_id
                ORDER BY ba.is_active DESC, ba.updated_at DESC, ba.id DESC
                """
            ).fetchall()
        ],
    }
    conn.close()
    if actor:
        payload["legal_entities"] = filter_rows_by_scope(actor, payload.get("legal_entities", []))
        allowed_legal_ids = {int(item.get("id") or 0) for item in payload["legal_entities"]}
        payload["business_units"] = [row for row in filter_rows_by_scope(actor, payload.get("business_units", [])) if not allowed_legal_ids or int(row.get("legal_entity_id") or 0) in allowed_legal_ids]
        payload["employees"] = filter_rows_by_scope(actor, payload.get("employees", []))
        payload["financial_responsibility_centers"] = filter_rows_by_scope(actor, payload.get("financial_responsibility_centers", []))
        if has_permission(actor, "finance", "read") or has_permission(actor, "finance", "manage_master"):
            payload["bank_accounts"] = filter_rows_by_scope(actor, payload.get("bank_accounts", []))
        else:
            payload["bank_accounts"] = []
    payload["defaults"] = {
        "warehouse_id": _safe_int((payload.get("warehouses") or [{}])[0].get("id") if payload.get("warehouses") else 0),
        "legal_entity_id": _safe_int((payload.get("legal_entities") or [{}])[0].get("id") if payload.get("legal_entities") else 0),
        "business_unit_id": _safe_int((payload.get("business_units") or [{}])[0].get("id") if payload.get("business_units") else 0),
        "position_id": _safe_int((payload.get("positions") or [{}])[0].get("id") if payload.get("positions") else 0),
    }
    return payload


def _master_table_name(entity_type: str) -> str:
    config = _nsi_master_config(entity_type)
    return config["table"] if config else ""


_NSI_MDM_ENTITY_TYPES = (
    "warehouses",
    "units",
    "groups",
    "employees",
    "positions",
    "characteristics",
    "storage_cells",
    "income_expense_articles",
    "financial_responsibility_centers",
    "operation_types",
    "bank_accounts",
    "nomenclature",
)


def _nsi_mdm_config(entity_type: str) -> dict | None:
    entity_type = (entity_type or "").strip()
    if entity_type == "nomenclature":
        return {
            "entity_type": entity_type,
            "table": "nomenclature",
            "id_column": "id",
            "name_column": "name",
            "code_column": "article",
            "required": ["name", "article", "unit", "group_name", "default_warehouse"],
            "label": "nomenclature",
        }
    config = _nsi_master_config(entity_type)
    if not config:
        return None
    name_column = "full_name" if entity_type == "employees" else "name"
    code_column = {
        "employees": "personnel_number",
        "bank_accounts": "account_number",
    }.get(entity_type, "code")
    required = {
        "warehouses": ["name", "code"],
        "units": ["name", "code"],
        "groups": ["name", "code"],
        "employees": ["full_name", "personnel_number", "legal_entity_id", "business_unit_id", "position_id"],
        "positions": ["name", "code"],
        "characteristics": ["name", "code", "characteristic_type"],
        "storage_cells": ["warehouse_id", "name", "code"],
        "income_expense_articles": ["name", "code", "article_kind"],
        "financial_responsibility_centers": ["name", "code", "legal_entity_id", "business_unit_id"],
        "operation_types": ["name", "code", "module_name", "flow_kind"],
        "bank_accounts": ["name", "account_number", "bank_name", "bik", "legal_entity_id"],
    }.get(entity_type, ["name", "code"])
    return {
        "entity_type": entity_type,
        "table": config["table"],
        "id_column": "id",
        "name_column": name_column,
        "code_column": code_column,
        "required": required,
        "label": config["label"],
    }


_NSI_CRITICAL_ENTITY_TYPES = set(_NSI_MDM_ENTITY_TYPES)


_NSI_BUILTIN_DUPLICATE_RULES = {
    "nomenclature": [
        {"rule_name": "article", "fields": ["article"]},
        {"rule_name": "name_unit_group", "fields": ["name", "unit", "group_name"]},
    ],
    "bank_accounts": [
        {"rule_name": "account_bik_legal", "fields": ["account_number", "bik", "legal_entity_id"]},
        {"rule_name": "bank_name_bik", "fields": ["bank_name", "bik"]},
    ],
    "employees": [
        {"rule_name": "personnel_number_legal", "fields": ["personnel_number", "legal_entity_id"]},
        {"rule_name": "email", "fields": ["email"]},
        {"rule_name": "full_name_position_legal", "fields": ["full_name", "position_id", "legal_entity_id"]},
    ],
    "storage_cells": [
        {"rule_name": "warehouse_code", "fields": ["warehouse_id", "code"]},
        {"rule_name": "warehouse_name", "fields": ["warehouse_id", "name"]},
    ],
    "positions": [
        {"rule_name": "name_department", "fields": ["name", "department_name"]},
        {"rule_name": "code", "fields": ["code"]},
    ],
    "warehouses": [{"rule_name": "code_name", "fields": ["code", "name"]}],
    "units": [{"rule_name": "code_name", "fields": ["code", "name"]}],
    "groups": [{"rule_name": "code_name", "fields": ["code", "name"]}],
    "operation_types": [{"rule_name": "module_flow_code", "fields": ["module_name", "flow_kind", "code"]}],
}


def _nsi_duplicate_rules(conn, entity_type: str) -> list[dict]:
    rules = list(_NSI_BUILTIN_DUPLICATE_RULES.get(entity_type, []))
    rows = _select_all_dicts(conn, "SELECT * FROM nsi_duplicate_rules WHERE entity_type=? AND is_active=1 ORDER BY id", (entity_type,))
    for row in rows:
        fields = _json_load(row.get("fields_json"), [])
        if fields:
            rules.append({"rule_name": row.get("rule_name") or f"rule_{row.get('id')}", "fields": fields, "severity": row.get("severity") or "error"})
    return rules


def _nsi_field_match_expr(field: str) -> str:
    if field.endswith("_id") or field in {"is_active"}:
        return f"COALESCE({field}, 0)=?"
    return f"LOWER(TRIM(COALESCE({field}, '')))=LOWER(TRIM(?))"


def _row_to_dict(cursor, row) -> dict:
    if not row:
        return {}
    if isinstance(row, dict):
        return dict(row)
    columns = [getattr(col, "name", col[0]) for col in (cursor.description or [])]
    return dict(zip(columns, row))


def _select_one_dict(conn, sql: str, params: tuple = ()) -> dict:
    c = conn.cursor()
    c.execute(sql, params)
    return _row_to_dict(c, c.fetchone())


def _select_all_dicts(conn, sql: str, params: tuple = ()) -> list[dict]:
    c = conn.cursor()
    c.execute(sql, params)
    return [_row_to_dict(c, row) for row in c.fetchall()]


def _nsi_mdm_load_row(conn, entity_type: str, item_id: int) -> dict:
    config = _nsi_mdm_config(entity_type)
    if not config or not _safe_int(item_id):
        return {}
    return _select_one_dict(
        conn,
        f"SELECT * FROM {config['table']} WHERE {config['id_column']}=?",
        (_safe_int(item_id),),
    )


def _nsi_mdm_reference_exists(conn, table: str, row_id: int, active_only: bool = True) -> bool:
    if not _safe_int(row_id):
        return False
    where_active = " AND is_active=1" if active_only else ""
    row = _select_one_dict(conn, f"SELECT id FROM {table} WHERE id=?{where_active} LIMIT 1", (_safe_int(row_id),))
    return bool(row)


def _nsi_mdm_reference_issues(conn, entity_type: str, row: dict) -> list[dict]:
    issues = []
    if entity_type in {"employees", "financial_responsibility_centers", "bank_accounts"}:
        legal_entity_id = _safe_int(row.get("legal_entity_id"))
        if not _nsi_mdm_reference_exists(conn, "legal_entities", legal_entity_id):
            issues.append({"issue_type": "reference_error", "severity": "error", "field": "legal_entity_id", "message": "Юрлицо обязательно и должно быть активным"})
    if entity_type in {"employees", "financial_responsibility_centers"}:
        business_unit_id = _safe_int(row.get("business_unit_id"))
        if not _nsi_mdm_reference_exists(conn, "business_units", business_unit_id):
            issues.append({"issue_type": "reference_error", "severity": "error", "field": "business_unit_id", "message": "Бизнес-единица обязательна и должна быть активной"})
    if entity_type == "employees" and not _nsi_mdm_reference_exists(conn, "position_master", _safe_int(row.get("position_id"))):
        issues.append({"issue_type": "reference_error", "severity": "error", "field": "position_id", "message": "Должность обязательна и должна быть активной"})
    if entity_type == "storage_cells" and not _nsi_mdm_reference_exists(conn, "warehouse_master", _safe_int(row.get("warehouse_id"))):
        issues.append({"issue_type": "reference_error", "severity": "error", "field": "warehouse_id", "message": "Склад обязателен и должен быть активным"})
    if entity_type == "nomenclature":
        group_name = _normalize_spaces(row.get("group_name", ""))
        warehouse_name = _normalize_spaces(row.get("default_warehouse", ""))
        if group_name and not _select_one_dict(conn, "SELECT id FROM nomenclature_groups WHERE name=? AND is_active=1 LIMIT 1", (group_name,)):
            issues.append({"issue_type": "reference_error", "severity": "warning", "field": "group_name", "message": "Группа номенклатуры не найдена в НСИ"})
        if warehouse_name and not _select_one_dict(conn, "SELECT id FROM warehouse_master WHERE name=? AND is_active=1 LIMIT 1", (warehouse_name,)):
            issues.append({"issue_type": "reference_error", "severity": "warning", "field": "default_warehouse", "message": "Склад по умолчанию не найден в НСИ"})
    return issues


def _nsi_mdm_duplicate_candidates(conn, entity_type: str, item_id: int, row: dict) -> list[dict]:
    config = _nsi_mdm_config(entity_type)
    if not config:
        return []
    table = config["table"]
    name_column = config["name_column"]
    code_column = config["code_column"]
    candidates = []
    code = _normalize_spaces(row.get(code_column, ""))
    if code:
        candidates.extend(
            _select_all_dicts(
                conn,
                f"SELECT id, {name_column} AS name, {code_column} AS code FROM {table} WHERE LOWER(TRIM({code_column}))=LOWER(TRIM(?)) AND id<>? LIMIT 5",
                (code, _safe_int(item_id)),
            )
        )
    name = _normalize_spaces(row.get(name_column, ""))
    if entity_type == "nomenclature":
        name = ""
    if name:
        candidates.extend(
            _select_all_dicts(
                conn,
                f"SELECT id, {name_column} AS name, {code_column} AS code FROM {table} WHERE LOWER(TRIM({name_column}))=LOWER(TRIM(?)) AND id<>? LIMIT 5",
                (name, _safe_int(item_id)),
            )
        )
    for rule in _nsi_duplicate_rules(conn, entity_type):
        fields = [field for field in rule.get("fields", []) if field in row]
        if not fields:
            continue
        values = []
        where = []
        skip_rule = False
        for field in fields:
            raw_value = row.get(field)
            if field.endswith("_id") or field in {"is_active"}:
                value = _safe_int(raw_value)
                if value <= 0:
                    skip_rule = True
                    break
                values.append(value)
            else:
                value = _normalize_spaces(raw_value)
                if not value:
                    skip_rule = True
                    break
                values.append(value)
            where.append(_nsi_field_match_expr(field))
        if skip_rule:
            continue
        query = f"SELECT id, {name_column} AS name, {code_column} AS code FROM {table} WHERE {' AND '.join(where)} AND id<>? LIMIT 5"
        for candidate in _select_all_dicts(conn, query, tuple(values + [_safe_int(item_id)])):
            candidate["duplicate_rule"] = rule.get("rule_name") or ",".join(fields)
            candidates.append(candidate)
    unique = {}
    for item in candidates:
        unique[_safe_int(item.get("id"))] = item
    return list(unique.values())


def _nsi_mdm_validate_row(conn, entity_type: str, row: dict, item_id: int = 0) -> dict:
    config = _nsi_mdm_config(entity_type)
    issues = []
    if not config:
        return {"quality_score": 0, "issues": [{"issue_type": "config_error", "severity": "error", "message": "Неподдерживаемый тип НСИ"}], "duplicates": []}
    for field in config["required"]:
        value = row.get(field)
        missing = (_safe_int(value) <= 0) if field.endswith("_id") else not _normalize_spaces(value)
        if missing:
            issues.append({"issue_type": "required_field", "severity": "error", "field": field, "message": f"Поле {field} обязательно"})
    issues.extend(_nsi_mdm_reference_issues(conn, entity_type, row))
    duplicates = _nsi_mdm_duplicate_candidates(conn, entity_type, item_id or _safe_int(row.get("id")), row)
    if duplicates:
        issues.append({"issue_type": "duplicate_candidate", "severity": "error", "field": config["code_column"], "message": "Найден возможный дубль НСИ"})
    error_count = len([issue for issue in issues if issue.get("severity") == "error"])
    warning_count = len([issue for issue in issues if issue.get("severity") == "warning"])
    score = max(0, 100 - error_count * 30 - warning_count * 15)
    duplicate_key = _normalize_duplicate_key(row.get(config["code_column"]) or row.get(config["name_column"]) or "")
    return {"quality_score": score, "issues": issues, "duplicates": duplicates, "duplicate_key": duplicate_key}


def _nsi_mdm_update_row_state(conn, entity_type: str, item_id: int, report: dict, *, mdm_status: str = "", lifecycle_state: str = ""):
    config = _nsi_mdm_config(entity_type)
    if not config:
        return
    issues = report.get("issues") or []
    has_errors = any(issue.get("severity") == "error" for issue in issues)
    target_status = mdm_status or ("needs_fix" if has_errors else "pending_approval")
    target_lifecycle = lifecycle_state or ("blocked" if has_errors else "draft")
    c = conn.cursor()
    c.execute(
        f"""
        UPDATE {config['table']}
        SET quality_score=?, validation_errors=?, duplicate_key=?, mdm_status=?, lifecycle_state=?
        WHERE id=?
        """,
        (
            _safe_int(report.get("quality_score")),
            json.dumps(issues, ensure_ascii=False),
            report.get("duplicate_key", ""),
            target_status,
            target_lifecycle,
            _safe_int(item_id),
        ),
    )


def _record_nsi_mdm_version(conn, entity_type: str, item_id: int, actor: dict, reason: str = "") -> int:
    row = _nsi_mdm_load_row(conn, entity_type, item_id)
    if not row:
        return 0
    current = _select_one_dict(
        conn,
        "SELECT COALESCE(MAX(version_no), 0) AS version_no FROM nsi_mdm_versions WHERE entity_type=? AND entity_id=?",
        (entity_type, _safe_int(item_id)),
    )
    version_no = _safe_int(current.get("version_no")) + 1
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO nsi_mdm_versions (entity_type, entity_id, version_no, lifecycle_state, payload, changed_by, changed_at, change_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_type,
            _safe_int(item_id),
            version_no,
            row.get("lifecycle_state", "draft"),
            json.dumps(row, ensure_ascii=False),
            actor.get("email", ""),
            int(time.time()),
            reason or "save",
        ),
    )
    config = _nsi_mdm_config(entity_type)
    if config:
        c.execute(f"UPDATE {config['table']} SET version_no=? WHERE id=?", (version_no, _safe_int(item_id)))
    return version_no


def _run_nsi_mdm_controls(conn, actor: dict, persist: bool = False) -> dict:
    now = int(time.time())
    if persist:
        conn.execute(
            "UPDATE nsi_mdm_issues SET status='resolved', resolved_at=?, resolved_by=? WHERE status='open'",
            (now, actor.get("email", "")),
        )
    metrics = {"entities": 0, "records": 0, "approved": 0, "needs_fix": 0, "duplicates": 0, "issues": 0, "quality_score": 100}
    entity_payload = []
    issue_payload = []
    total_score = 0
    scored_records = 0
    for entity_type in _NSI_MDM_ENTITY_TYPES:
        config = _nsi_mdm_config(entity_type)
        if not config:
            continue
        rows = _select_all_dicts(conn, f"SELECT * FROM {config['table']} ORDER BY id ASC")
        entity_metrics = {"entity_type": entity_type, "records": len(rows), "approved": 0, "needs_fix": 0, "duplicates": 0, "issues": 0, "quality_score": 100}
        score_sum = 0
        for row in rows:
            item_id = _safe_int(row.get("id"))
            report = _nsi_mdm_validate_row(conn, entity_type, row, item_id)
            score_sum += _safe_int(report.get("quality_score"))
            scored_records += 1
            total_score += _safe_int(report.get("quality_score"))
            if row.get("mdm_status") == "approved" and not report.get("issues"):
                entity_metrics["approved"] += 1
                metrics["approved"] += 1
            if report.get("duplicates"):
                entity_metrics["duplicates"] += 1
                metrics["duplicates"] += 1
            if report.get("issues"):
                entity_metrics["needs_fix"] += 1
                entity_metrics["issues"] += len(report["issues"])
                metrics["needs_fix"] += 1
                metrics["issues"] += len(report["issues"])
            if persist:
                _nsi_mdm_update_row_state(conn, entity_type, item_id, report, mdm_status=("approved" if row.get("mdm_status") == "approved" and not report.get("issues") else ""), lifecycle_state=("active" if row.get("mdm_status") == "approved" and not report.get("issues") else ""))
                for issue in report.get("issues") or []:
                    c = conn.cursor()
                    c.execute(
                        """
                        INSERT INTO nsi_mdm_issues (entity_type, entity_id, issue_type, severity, status, message, details_json, created_at)
                        VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
                        """,
                        (
                            entity_type,
                            item_id,
                            issue.get("issue_type", ""),
                            issue.get("severity", "error"),
                            issue.get("message", ""),
                            json.dumps({"field": issue.get("field", ""), "duplicates": report.get("duplicates", [])}, ensure_ascii=False),
                            now,
                        ),
                    )
            for issue in report.get("issues") or []:
                issue_payload.append({"entity_type": entity_type, "entity_id": item_id, **issue, "duplicates": report.get("duplicates", [])})
        entity_metrics["quality_score"] = round(score_sum / len(rows), 1) if rows else 100
        entity_payload.append(entity_metrics)
        metrics["records"] += len(rows)
        metrics["entities"] += 1
    metrics["quality_score"] = round(total_score / scored_records, 1) if scored_records else 100
    return {"status": "success", "metrics": metrics, "entities": entity_payload, "issues": issue_payload[:200]}


def _load_inventory_document_rows(limit: int = 200):
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute(
        """
        SELECT d.*, COALESCE(n.name, '') AS nomenclature_name, COALESCE(n.unit, 'шт') AS unit
        FROM inventory_documents d
        LEFT JOIN nomenclature n ON n.article = d.article
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT ?
        """,
        (max(1, min(limit, 500)),),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _next_inventory_doc_number(doc_type: str) -> str:
    prefix = {
        "inventory": "INV",
        "writeoff": "WRF",
        "transfer": "TRF",
        "receipt_adjustment": "RCP",
    }.get((doc_type or "inventory").strip(), "DOC")
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _inventory_qty_at_source(c, article: str, warehouse: str = "", bin_code: str = "", batch_code: str = "", serial_no: str = "") -> float:
    article = _normalize_spaces(article)
    warehouse, bin_code = _normalize_stock_location(warehouse, bin_code)
    batch_code, serial_no = _normalize_stock_lot(batch_code, serial_no)
    _bootstrap_inventory_lots_for_article(c, article)
    if batch_code or serial_no:
        c.execute(
            """
            SELECT COALESCE(SUM(qty), 0)
            FROM inventory_lots
            WHERE article=? AND warehouse=? AND bin_code=? AND batch_code=? AND serial_no=?
            """,
            (article, warehouse, bin_code, batch_code, serial_no),
        )
    else:
        c.execute(
            """
            SELECT COALESCE(SUM(qty), 0)
            FROM inventory_lots
            WHERE article=? AND warehouse=? AND bin_code=?
            """,
            (article, warehouse, bin_code),
        )
    return round(_safe_float(c.fetchone()[0]), 3)


def _apply_inventory_document(conn, doc_id: int, article: str, item_name: str, data: InventoryDocumentData, actor_email: str = "") -> dict:
    c = conn.cursor()
    doc_type = (data.doc_type or "inventory").strip()
    warehouse, bin_code = _normalize_stock_location(data.warehouse, data.bin_code)
    target_warehouse, target_bin = _normalize_stock_location(data.target_warehouse, data.target_bin)
    batch_code, serial_no = _normalize_stock_lot(data.batch_code, data.serial_no)
    lot_expiration_date = (getattr(data, "lot_expiration_date", "") or "").strip()
    unit = (getattr(data, "unit", "шт") or "шт").strip() or "шт"
    unit_cost = _safe_float(getattr(data, "unit_cost", 0))
    now = int(time.time())
    qty, qty_details = qty_to_base(conn, article, data.qty, getattr(data, "unit", "шт"), getattr(data, "package_code", ""), getattr(data, "package_qty", 0))
    qty = round(qty, 3)
    counted_qty_base, _count_details = qty_to_base(conn, article, data.counted_qty, getattr(data, "unit", "шт"), getattr(data, "package_code", ""), getattr(data, "package_qty", 0) if _safe_float(data.counted_qty) else 0)
    counted_qty = round(counted_qty_base, 3)
    movement_qty = qty
    movement_type = "add"
    from_warehouse = ""
    from_bin = ""
    to_warehouse = ""
    to_bin = ""

    c.execute("SELECT stock FROM nomenclature WHERE article=?", (article,))
    current_stock = _safe_float((c.fetchone() or [0])[0])
    actual_at_source = _inventory_qty_at_source(c, article, warehouse, bin_code, batch_code, serial_no)

    if doc_type == "inventory":
        adjustment_qty = round(counted_qty - actual_at_source, 3)
        movement_qty = abs(adjustment_qty)
        if abs(adjustment_qty) < 0.0001:
            c.execute("UPDATE inventory_documents SET adjustment_qty=?, status='posted', updated_at=? WHERE id=?", (0, now, doc_id))
            return {"movement_type": "inventory", "adjustment_qty": 0, "new_stock": round(current_stock, 3)}
        if adjustment_qty > 0:
            movement_type = "add"
            to_warehouse, to_bin = warehouse, bin_code
            _upsert_inventory_balance(c, article, warehouse, bin_code, adjustment_qty)
            _upsert_inventory_lot(c, article, warehouse, bin_code, batch_code, serial_no, adjustment_qty)
            receipt_cost_layer(conn, article, item_name, warehouse, bin_code, batch_code, serial_no, adjustment_qty, unit_cost, actor_email, "inventory_document", doc_id, lot_expiration_date, unit, {"doc_type": doc_type, **qty_details})
            new_stock = round(current_stock + adjustment_qty, 3)
        else:
            movement_type = "remove"
            from_warehouse, from_bin = warehouse, bin_code
            cost_allocations, cost_missing = consume_cost_layers(conn, article, abs(adjustment_qty), warehouse, bin_code, batch_code, serial_no, actor_email, "inventory_document", doc_id, details={"doc_type": doc_type})
            if cost_missing > 0:
                raise HTTPException(status_code=400, detail="Недостаточно слоёв себестоимости для корректировки")
            allocations, missing = _consume_inventory_lots(c, article, abs(adjustment_qty), warehouse, bin_code, batch_code, serial_no)
            if missing > 0:
                raise HTTPException(status_code=400, detail="Недостаточно остатков для корректировки инвентаризации")
            _upsert_inventory_balance(c, article, warehouse, bin_code, adjustment_qty)
            if allocations:
                batch_code = allocations[0].get("batch_code", batch_code)
                serial_no = allocations[0].get("serial_no", serial_no)
            new_stock = round(current_stock + adjustment_qty, 3)
        c.execute("UPDATE inventory_documents SET adjustment_qty=?, status='posted', updated_at=? WHERE id=?", (adjustment_qty, now, doc_id))
    elif doc_type == "writeoff":
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Для списания требуется количество больше нуля")
        cost_allocations, cost_missing = consume_cost_layers(conn, article, qty, warehouse, bin_code, batch_code, serial_no, actor_email, "inventory_document", doc_id, details={"doc_type": doc_type})
        if cost_missing > 0:
            raise HTTPException(status_code=400, detail="Недостаточно слоёв себестоимости для списания")
        allocations, missing = _consume_inventory_lots(c, article, qty, warehouse, bin_code, batch_code, serial_no)
        if missing > 0:
            raise HTTPException(status_code=400, detail="Недостаточно остатков для списания")
        _upsert_inventory_balance(c, article, warehouse, bin_code, -qty)
        if allocations:
            batch_code = allocations[0].get("batch_code", batch_code)
            serial_no = allocations[0].get("serial_no", serial_no)
        movement_type = "remove"
        from_warehouse, from_bin = warehouse, bin_code
        new_stock = round(current_stock - qty, 3)
        c.execute("UPDATE inventory_documents SET adjustment_qty=?, status='posted', updated_at=? WHERE id=?", (-qty, now, doc_id))
    elif doc_type == "transfer":
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Для перемещения требуется количество больше нуля")
        cost_allocations, cost_missing = consume_cost_layers(conn, article, qty, warehouse, bin_code, batch_code, serial_no, actor_email, "inventory_document", doc_id, details={"doc_type": doc_type})
        if cost_missing > 0:
            raise HTTPException(status_code=400, detail="Недостаточно слоёв себестоимости для перемещения")
        allocations, missing = _consume_inventory_lots(c, article, qty, warehouse, bin_code, batch_code, serial_no)
        if missing > 0:
            raise HTTPException(status_code=400, detail="Недостаточно остатков для перемещения")
        _upsert_inventory_balance(c, article, warehouse, bin_code, -qty)
        _upsert_inventory_balance(c, article, target_warehouse, target_bin, qty)
        for allocation in allocations or [{"batch_code": batch_code, "serial_no": serial_no, "qty": qty}]:
            _upsert_inventory_lot(c, article, target_warehouse, target_bin, allocation.get("batch_code", ""), allocation.get("serial_no", ""), allocation.get("qty", qty))
        transfer_cost_layers(conn, cost_allocations, article, item_name, target_warehouse, target_bin, actor_email, "inventory_document", doc_id, lot_expiration_date)
        movement_type = "transfer"
        from_warehouse, from_bin = warehouse, bin_code
        to_warehouse, to_bin = target_warehouse, target_bin
        new_stock = round(current_stock, 3)
        c.execute("UPDATE inventory_documents SET adjustment_qty=0, status='posted', updated_at=? WHERE id=?", (now, doc_id))
    elif doc_type == "receipt_adjustment":
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Для приходной корректировки требуется количество больше нуля")
        _upsert_inventory_balance(c, article, warehouse, bin_code, qty)
        _upsert_inventory_lot(c, article, warehouse, bin_code, batch_code, serial_no, qty)
        receipt_cost_layer(conn, article, item_name, warehouse, bin_code, batch_code, serial_no, qty, unit_cost, actor_email, "inventory_document", doc_id, lot_expiration_date, unit, {"doc_type": doc_type, **qty_details})
        movement_type = "add"
        to_warehouse, to_bin = warehouse, bin_code
        new_stock = round(current_stock + qty, 3)
        c.execute("UPDATE inventory_documents SET adjustment_qty=?, status='posted', updated_at=? WHERE id=?", (qty, now, doc_id))
    else:
        raise HTTPException(status_code=400, detail="Неподдерживаемый тип складского документа")

    c.execute("UPDATE nomenclature SET stock=?, exchange_state='queued' WHERE article=?", (new_stock, article))
    _cleanup_inventory_tables(c)
    c.execute(
        """
        INSERT INTO stock_movements (
            article, name, qty, movement_type, from_warehouse, from_bin, to_warehouse, to_bin,
            comment, actor_email, created_at, batch_code, serial_no, reservation_id, document_id, document_type, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            article,
            item_name,
            movement_qty,
            movement_type,
            from_warehouse,
            from_bin,
            to_warehouse,
            to_bin,
            data.comment or data.reason or f"Складской документ {doc_type}",
            actor_email,
            now,
            batch_code,
            serial_no,
            doc_id,
            doc_type,
            data.reason or "",
        ),
    )
    if lot_expiration_date:
        update_lot_expiration(conn, article, to_warehouse or warehouse, to_bin or bin_code, batch_code, serial_no, lot_expiration_date)
    return {"movement_type": movement_type, "adjustment_qty": round(counted_qty - actual_at_source, 3) if doc_type == "inventory" else (qty if movement_type == "add" else -qty if movement_type == "remove" else 0), "new_stock": new_stock}


def _normalize_stock_location(warehouse: str = "", bin_code: str = "") -> tuple[str, str]:
    return (warehouse or "Основной склад").strip() or "Основной склад", (bin_code or "A-01").strip() or "A-01"


def _normalize_stock_lot(batch_code: str = "", serial_no: str = "") -> tuple[str, str]:
    return (batch_code or "").strip(), (serial_no or "").strip()


def _upsert_inventory_balance(c, article: str, warehouse: str, bin_code: str, delta: float):
    warehouse, bin_code = _normalize_stock_location(warehouse, bin_code)
    c.execute(
        "SELECT id, qty FROM inventory_balances WHERE article=? AND warehouse=? AND bin_code=?",
        (article, warehouse, bin_code),
    )
    existing_balance = c.fetchone()
    now = int(time.time())
    if existing_balance:
        if isinstance(existing_balance, dict):
            balance_id = existing_balance.get("id")
            current_qty = existing_balance.get("qty")
        else:
            balance_id, current_qty = existing_balance
        c.execute(
            "UPDATE inventory_balances SET qty=?, updated_at=? WHERE id=?",
            (round(_safe_float(current_qty) + delta, 3), now, balance_id),
        )
    else:
        c.execute(
            """
            INSERT INTO inventory_balances (article, warehouse, bin_code, qty, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (article, warehouse, bin_code, round(delta, 3), now),
        )


def _upsert_inventory_lot(c, article: str, warehouse: str, bin_code: str, batch_code: str, serial_no: str, delta: float, lot_expiration_date: str = ""):
    warehouse, bin_code = _normalize_stock_location(warehouse, bin_code)
    batch_code, serial_no = _normalize_stock_lot(batch_code, serial_no)
    c.execute(
        "SELECT id, qty FROM inventory_lots WHERE article=? AND warehouse=? AND bin_code=? AND batch_code=? AND serial_no=?",
        (article, warehouse, bin_code, batch_code, serial_no),
    )
    existing_lot = c.fetchone()
    now = int(time.time())
    if existing_lot:
        if isinstance(existing_lot, dict):
            lot_id = existing_lot.get("id")
            current_qty = existing_lot.get("qty")
        else:
            lot_id, current_qty = existing_lot
        if lot_expiration_date:
            c.execute(
                "UPDATE inventory_lots SET qty=?, lot_expiration_date=?, updated_at=? WHERE id=?",
                (round(_safe_float(current_qty) + delta, 3), lot_expiration_date, now, lot_id),
            )
        else:
            c.execute(
                "UPDATE inventory_lots SET qty=?, updated_at=? WHERE id=?",
                (round(_safe_float(current_qty) + delta, 3), now, lot_id),
            )
    else:
        c.execute(
            """
            INSERT INTO inventory_lots (article, warehouse, bin_code, batch_code, serial_no, lot_expiration_date, qty, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (article, warehouse, bin_code, batch_code, serial_no, lot_expiration_date or "", round(delta, 3), now),
        )


def _cleanup_inventory_tables(c):
    c.execute("DELETE FROM inventory_balances WHERE ABS(qty) < 0.0001")
    c.execute("DELETE FROM inventory_lots WHERE ABS(qty) < 0.0001")


def _bootstrap_inventory_lots_for_article(c, article: str):
    c.execute("SELECT COUNT(*) FROM inventory_lots WHERE article=?", (article,))
    if _safe_int(c.fetchone()[0]) > 0:
        return
    c.execute("SELECT warehouse, bin_code, qty FROM inventory_balances WHERE article=?", (article,))
    for row in c.fetchall():
        if isinstance(row, dict):
            warehouse = row.get("warehouse")
            bin_code = row.get("bin_code")
            qty = row.get("qty")
        else:
            warehouse, bin_code, qty = row
        qty_value = _safe_float(qty)
        if abs(qty_value) < 0.0001:
            continue
        c.execute(
            """
            INSERT OR IGNORE INTO inventory_lots (article, warehouse, bin_code, batch_code, serial_no, lot_expiration_date, qty, updated_at)
            VALUES (?, ?, ?, '', '', '', ?, ?)
            """,
            (article, warehouse or "Основной склад", bin_code or "A-01", qty_value, int(time.time())),
        )


def _available_reserved_qty(c, article: str, warehouse: str = "", bin_code: str = "", batch_code: str = "", serial_no: str = "", exclude_reservation_id: int = 0) -> float:
    clauses = ["nomenclature_article=?", "status IN ('reserved','partial')"]
    params = [article]
    if warehouse:
        clauses.append("warehouse=?")
        params.append(warehouse)
    if bin_code:
        clauses.append("bin_code=?")
        params.append(bin_code)
    if batch_code:
        clauses.append("batch_code=?")
        params.append(batch_code)
    if serial_no:
        clauses.append("serial_no=?")
        params.append(serial_no)
    if exclude_reservation_id:
        clauses.append("id!=?")
        params.append(exclude_reservation_id)
    c.execute(f"SELECT COALESCE(SUM(qty - fulfilled_qty), 0) FROM stock_reservations WHERE {' AND '.join(clauses)}", tuple(params))
    return round(_safe_float(c.fetchone()[0]), 3)


def _pick_inventory_source(c, article: str, qty: float):
    _bootstrap_inventory_lots_for_article(c, article)
    c.execute(
        """
        SELECT warehouse, bin_code, batch_code, serial_no, qty
        FROM inventory_lots
        WHERE article=? AND qty > 0
        ORDER BY qty DESC, updated_at ASC, id ASC
        """,
        (article,),
    )
    lots = []
    for row in c.fetchall():
        if isinstance(row, dict):
            warehouse = row.get("warehouse")
            bin_code = row.get("bin_code")
            batch_code = row.get("batch_code")
            serial_no = row.get("serial_no")
            lot_qty = row.get("qty")
        else:
            warehouse, bin_code, batch_code, serial_no, lot_qty = row
        reserved_qty = _available_reserved_qty(c, article, warehouse, bin_code, batch_code, serial_no)
        free_qty = round(_safe_float(lot_qty) - reserved_qty, 3)
        if free_qty <= 0:
            continue
        lots.append({
            "warehouse": warehouse or "Основной склад",
            "bin_code": bin_code or "A-01",
            "batch_code": batch_code or "",
            "serial_no": serial_no or "",
            "qty": round(_safe_float(lot_qty), 3),
            "free_qty": free_qty,
        })
    if not lots:
        return None
    perfect = next((lot for lot in lots if lot["free_qty"] >= qty), None)
    return perfect or lots[0]


def _consume_inventory_lots(c, article: str, qty: float, warehouse: str = "", bin_code: str = "", batch_code: str = "", serial_no: str = ""):
    _bootstrap_inventory_lots_for_article(c, article)
    clauses = ["article=?", "qty > 0"]
    params = [article]
    if warehouse:
        clauses.append("warehouse=?")
        params.append(warehouse)
    if bin_code:
        clauses.append("bin_code=?")
        params.append(bin_code)
    if batch_code:
        clauses.append("batch_code=?")
        params.append(batch_code)
    if serial_no:
        clauses.append("serial_no=?")
        params.append(serial_no)
    c.execute(
        f"""
        SELECT id, warehouse, bin_code, batch_code, serial_no, qty
        FROM inventory_lots
        WHERE {' AND '.join(clauses)}
        ORDER BY updated_at ASC, id ASC
        """,
        tuple(params),
    )
    remaining = round(_safe_float(qty), 3)
    allocations = []
    for row in c.fetchall():
        if isinstance(row, dict):
            lot_id = row.get("id")
            lot_wh = row.get("warehouse")
            lot_bin = row.get("bin_code")
            lot_batch = row.get("batch_code")
            lot_serial = row.get("serial_no")
            lot_qty = row.get("qty")
        else:
            lot_id, lot_wh, lot_bin, lot_batch, lot_serial, lot_qty = row
        if remaining <= 0:
            break
        available = round(_safe_float(lot_qty), 3)
        if available <= 0:
            continue
        used = min(available, remaining)
        c.execute(
            "UPDATE inventory_lots SET qty=?, updated_at=? WHERE id=?",
            (round(available - used, 3), int(time.time()), lot_id),
            )
        allocations.append({
            "warehouse": lot_wh or "Основной склад",
            "bin_code": lot_bin or "A-01",
            "batch_code": lot_batch or "",
            "serial_no": lot_serial or "",
            "qty": round(used, 3),
        })
        remaining = round(remaining - used, 3)
    if remaining > 0:
        return None, remaining
    return allocations, 0


def _load_specification_versions(project_id: int):
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute("SELECT * FROM specification_versions WHERE project_id=? ORDER BY created_at DESC, id DESC", (project_id,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["snapshot"] = _json_load(row.get("snapshot"), [])
    return rows


def _tokenize(value: str):
    return [tok for tok in re.findall(r"[a-zA-Zа-яА-Я0-9]+", (value or "").lower()) if len(tok) >= 3]


def _extract_number(value: str) -> float:
    cleaned = re.sub(r"[^\d,\.]", "", value or "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0


def _extract_money(text: str) -> float:
    patterns = [
        r"(?:нмцк|начальная\s+цена|цена\s+договора|стоимость)\D{0,20}([\d\s]+(?:[.,]\d+)?)",
        r"([\d\s]+(?:[.,]\d+)?)\s*(?:руб|₽)"
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            amount = _extract_number(match.group(1))
            if amount > 0:
                return amount
    return 0


def _extract_first(patterns, text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return _normalize_spaces(match.group(1))
    return ""


def _build_contract_number(conn) -> str:
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM projects")
    next_number = (c.fetchone()[0] or 0) + 1
    return f"{datetime.now().year}-КРД-{str(next_number).zfill(3)}"


def _match_nomenclature(text: str):
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute("SELECT * FROM nomenclature ORDER BY name ASC")
    rows = c.fetchall()
    conn.close()

    text_lower = (text or "").lower()
    source_tokens = set(_tokenize(text))
    matches = []

    for row in rows:
        item = dict(row)
        name = item.get("name", "")
        article = item.get("article", "")
        item_tokens = set(_tokenize(f"{name} {article}"))
        common = sorted(source_tokens & item_tokens)
        score = len(common) * 2

        if name and name.lower() in text_lower:
            score += 4
        if article and article.lower() in text_lower:
            score += 5

        if score < 4:
            continue

        matches.append({
            "name": name,
            "article": article,
            "unit": item.get("unit") or "шт",
            "price": item.get("price") or 0,
            "qty": 1,
            "match_reason": "Совпадения: " + ", ".join(common[:4]) if common else ("Точное совпадение артикула" if article and article.lower() in text_lower else "Точное совпадение названия"),
            "score": score
        })

    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:5]


def _parse_tender_payload(source: str, text: str):
    raw_text = "\n".join(part for part in [source, text] if part).strip()
    if not raw_text:
        return {
            "name": "",
            "client": "",
            "inn": "",
            "deadline": "",
            "budget": 0,
            "summary": "",
            "suggested_nomenclature": [],
            "archive_details": {}
        }

    combined = _normalize_spaces(raw_text)
    title = _extract_first([
        r"(?:наименование\s+закупки|предмет\s+закупки|предмет\s+договора)\s*[:\-]\s*([^\n\r]+)",
        r"(?:объект\s+закупки)\s*[:\-]\s*([^\n\r]+)"
    ], raw_text)
    if not title:
        lines = [line.strip(" -") for line in re.split(r"[\r\n]+", text or source or "") if line.strip()]
        title = lines[0] if lines else "Проект из тендера"

    client = _extract_first([
        r"(?:заказчик|организация[- ]заказчик|контрагент)\s*[:\-]\s*([^\n\r]+)",
        r"(?:поставщик|покупатель)\s*[:\-]\s*([^\n\r]+)"
    ], raw_text)
    inn = _extract_first([r"(?:инн)\s*[:\-]?\s*([0-9]{10,12})"], raw_text)
    deadline = _extract_first([
        r"(?:дата\s+окончания|окончание\s+подачи|срок\s+подачи|дедлайн)\s*[:\-]?\s*(\d{2}[./]\d{2}[./]\d{4})",
        r"(\d{2}[./]\d{2}[./]\d{4})"
    ], raw_text).replace("/", ".")
    budget = _extract_money(combined)
    suggested = _match_nomenclature(combined)

    summary_parts = []
    if client:
        summary_parts.append(f"Заказчик: {client}")
    if inn:
        summary_parts.append(f"ИНН: {inn}")
    if deadline:
        summary_parts.append(f"Дедлайн: {deadline}")
    if budget:
        summary_parts.append(f"Бюджет: {int(budget):,} ₽".replace(",", " "))

    archive_details = {
        "tender_source": {
            "url": source.strip(),
            "raw_excerpt": (text or "").strip()[:1500],
            "client": client,
            "inn": inn,
            "deadline": deadline,
            "budget": budget,
            "captured_at": time.strftime("%d.%m.%Y %H:%M")
        }
    }

    return {
        "name": title,
        "client": client,
        "inn": inn,
        "deadline": deadline,
        "budget": budget,
        "summary": " • ".join(summary_parts) if summary_parts else "Тендер распознан частично. Проверь данные перед созданием проекта.",
        "suggested_nomenclature": suggested,
        "archive_details": archive_details
    }


def _scan_contract_text(text: str):
    body = text or ""
    body_lower = body.lower()
    findings = []

    def add_finding(severity: str, title: str, details: str):
        findings.append({"severity": severity, "title": title, "details": details})

    penalty_matches = re.finditer(r"(штраф|пени|неустойк)[^.:\n]{0,80}?(\d+(?:[.,]\d+)?)\s*%", body_lower, flags=re.IGNORECASE)
    for match in penalty_matches:
        percent = _extract_number(match.group(2))
        if percent > 0.1:
            add_finding("high", "Повышенная неустойка", f"Найдена ставка {percent}% за нарушение сроков. Это выше внутреннего ориентира 0.1% в день.")
            break

    payment_match = re.search(r"(оплат[аы]|платеж)[^.:\n]{0,80}?(\d{1,3})\s*(?:календарн\w*\s*)?дн", body_lower, flags=re.IGNORECASE)
    if payment_match:
        days = int(payment_match.group(2))
        if days > 30:
            add_finding("high" if days >= 60 else "medium", "Длинный срок оплаты", f"В договоре фигурирует срок оплаты {days} дней. Для сделки это может создать кассовый разрыв.")

    if "форс-маж" not in body_lower and "непреодолимой силы" not in body_lower:
        add_finding("high", "Нет блока про форс-мажор", "В тексте не найден пункт о форс-мажоре или обстоятельствах непреодолимой силы.")

    if "в одностороннем порядке" in body_lower:
        add_finding("medium", "Одностороннее расторжение", "Есть формулировка о расторжении в одностороннем порядке. Нужно проверить, не слишком ли она односторонняя в пользу заказчика.")

    warranty_match = re.search(r"гарант\w*[^.\n]{0,60}?(\d{1,3})\s*(месяц|мес|год|лет)", body_lower, flags=re.IGNORECASE)
    if warranty_match:
        warranty_value = int(warranty_match.group(1))
        warranty_unit = warranty_match.group(2)
        months = warranty_value * 12 if warranty_unit.startswith("год") or warranty_unit.startswith("лет") else warranty_value
        if months > 24:
            add_finding("medium", "Увеличенная гарантия", f"Обнаружен гарантийный срок {warranty_value} {warranty_unit}. Это выше типового порога 24 месяца.")

    if "акт" not in body_lower and "приемк" not in body_lower:
        add_finding("medium", "Слабый блок приемки", "В тексте почти не видно механики приемки и закрывающих актов. Это часто приводит к спорам по срокам и оплате.")

    if "ограничен" not in body_lower and "лимит ответствен" not in body_lower:
        add_finding("low", "Нет ограничения ответственности", "Не найдено явного ограничения ответственности поставщика. Это стоит отдельно проверить юристу.")

    severity_weights = {"high": 22, "medium": 12, "low": 5}
    score = max(0, 100 - sum(severity_weights[item["severity"]] for item in findings))

    if score >= 75:
        status = "Риски умеренные"
    elif score >= 45:
        status = "Нужна проверка юриста"
    else:
        status = "Высокий риск"

    recommendations = []
    if any(item["title"] == "Повышенная неустойка" for item in findings):
        recommendations.append("Снизить неустойку до внутреннего стандарта или ограничить общий размер ответственности.")
    if any(item["title"] == "Длинный срок оплаты" for item in findings):
        recommendations.append("Согласовать более короткий срок оплаты или авансовый платеж.")
    if any(item["title"] == "Нет блока про форс-мажор" for item in findings):
        recommendations.append("Добавить стандартный раздел про форс-мажор и порядок уведомления.")
    if not recommendations:
        recommendations.append("Критичных отклонений по базовым правилам не найдено, но ручная вычитка всё равно нужна.")

    return {
        "score": score,
        "status": status,
        "findings": findings,
        "recommendations": recommendations,
        "scanned_at": time.strftime("%d.%m.%Y %H:%M"),
        "source_length": len(body)
    }


def _get_process_project(process: dict):
    project_id = _safe_int(process.get("project_id"))
    if not project_id:
        return None
    row = _load_project_row(project_id)
    return _project_payload(row) if row else None


def _can_access_process(actor: dict, process: dict) -> bool:
    if not actor or not process:
        return False
    if actor.get("role") == "Директор":
        return True
    project = _get_process_project(process)
    if project:
        return can_access_project(actor, project)
    return has_permission(actor, "requests", "read")


def _build_duplicate_groups(rows: list[dict], key_name: str, label_fields: tuple[str, ...]):
    groups = {}
    for row in rows:
        key = _normalize_duplicate_key(row.get(key_name) or "")
        if not key:
            continue
        groups.setdefault(key, []).append(row)
    duplicates = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        duplicates.append({
            "key": key,
            "count": len(items),
            "items": [
                {
                    "id": item.get("id"),
                    **{field: item.get(field, "") for field in label_fields},
                }
                for item in items[:5]
            ],
        })
    return sorted(duplicates, key=lambda item: (-item["count"], item["key"]))


def _build_erp_data_quality():
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT id, name, inn, contact FROM clients ORDER BY id DESC")
    clients = [dict(row) for row in c.fetchall()]
    c.execute("SELECT id, name, article, unit, stock FROM nomenclature ORDER BY id DESC")
    nomenclature = [dict(row) for row in c.fetchall()]
    c.execute("SELECT id FROM projects")
    project_ids = {int(row["id"]) for row in c.fetchall()}
    c.execute("SELECT id FROM clients")
    client_ids = {int(row["id"]) for row in c.fetchall()}
    c.execute("SELECT project_id, client_id FROM finance_payments")
    finance_rows = [dict(row) for row in c.fetchall()]
    c.execute("SELECT project_id, client_id FROM purchase_orders")
    purchase_rows = [dict(row) for row in c.fetchall()]
    c.execute("SELECT project_id, client_id FROM sales_documents_extended")
    sales_rows = [dict(row) for row in c.fetchall()]
    c.execute("SELECT project_id FROM internal_requests")
    request_rows = [dict(row) for row in c.fetchall()]
    conn.close()

    orphans = {
        "finance_missing_project": len([row for row in finance_rows if _safe_int(row.get("project_id")) and _safe_int(row.get("project_id")) not in project_ids]),
        "finance_missing_client": len([row for row in finance_rows if _safe_int(row.get("client_id")) and _safe_int(row.get("client_id")) not in client_ids]),
        "purchases_missing_project": len([row for row in purchase_rows if _safe_int(row.get("project_id")) and _safe_int(row.get("project_id")) not in project_ids]),
        "sales_missing_project": len([row for row in sales_rows if _safe_int(row.get("project_id")) and _safe_int(row.get("project_id")) not in project_ids]),
        "requests_missing_project": len([row for row in request_rows if _safe_int(row.get("project_id")) and _safe_int(row.get("project_id")) not in project_ids]),
    }
    return {
        "clients_duplicates": _build_duplicate_groups(clients, "name", ("name", "inn", "contact"))[:8],
        "clients_duplicate_inn": _build_duplicate_groups(clients, "inn", ("name", "inn", "contact"))[:8],
        "nomenclature_duplicates": _build_duplicate_groups(nomenclature, "article", ("name", "article", "unit", "stock"))[:8],
        "orphans": orphans,
        "counts": {
            "clients": len(clients),
            "nomenclature": len(nomenclature),
            "orphans_total": sum(orphans.values()),
        }
    }


def _build_erp_summary():
    process_rows = list_erp_process_runs(limit=300)
    finance_rows = _load_finance_rows()
    resource_rows = _load_resource_allocations()
    reservations = _load_stock_reservations()
    quality = _build_erp_data_quality()

    overdue_processes = [
        row for row in process_rows
        if row.get("status") not in {"done", "cancelled"} and _is_overdue(row.get("status", ""), row.get("due_date", ""))
    ]
    stage_counts = {}
    for row in process_rows:
        stage = row.get("current_stage") or "request"
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    return {
        "metrics": {
            "processes_total": len(process_rows),
            "active": len([row for row in process_rows if row.get("status") in {"new", "in_progress", "pending"}]),
            "blocked_approvals": len([row for row in process_rows if row.get("current_stage") == "approval" and row.get("status") != "done"]),
            "stock_reserved_qty": round(sum(_safe_float(row.get("qty")) for row in reservations if row.get("status") == "reserved"), 2),
            "open_money": round(sum(_safe_float(row.get("amount")) for row in finance_rows if row.get("status") != "paid"), 2),
            "overdue_processes": len(overdue_processes),
            "avg_load": round(sum(_safe_int(row.get("load_percent")) for row in resource_rows) / len(resource_rows), 1) if resource_rows else 0,
            "data_issues": int(quality["counts"]["orphans_total"]) + len(quality["clients_duplicates"]) + len(quality["nomenclature_duplicates"]),
        },
        "stage_counts": stage_counts,
        "pipeline_amount": round(sum(_safe_float(row.get("amount")) for row in process_rows if row.get("status") != "done"), 2),
        "recent": process_rows[:12],
        "overdue": overdue_processes[:8],
        "quality": quality,
    }


def _enrich_process_rows(rows: list[dict]):
    if not rows:
        return []
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT id, name, contract FROM projects")
    projects = {int(row["id"]): dict(row) for row in c.fetchall()}
    c.execute("SELECT id, name FROM clients")
    clients = {int(row["id"]): dict(row) for row in c.fetchall()}
    c.execute("SELECT id, contract_number, title FROM contract_master")
    contracts = {int(row["id"]): dict(row) for row in c.fetchall()}
    c.execute("SELECT id, name FROM business_objects")
    objects = {int(row["id"]): dict(row) for row in c.fetchall()}
    conn.close()
    enriched = []
    for row in rows:
        item = dict(row)
        project = projects.get(_safe_int(item.get("project_id")), {})
        client = clients.get(_safe_int(item.get("client_id")), {})
        contract = contracts.get(_safe_int(item.get("contract_id")), {})
        business_object = objects.get(_safe_int(item.get("object_id")), {})
        item["project_name"] = project.get("name", "")
        item["project_contract"] = project.get("contract", "")
        item["client_name"] = client.get("name", "")
        item["contract_number"] = contract.get("contract_number", "")
        item["contract_title"] = contract.get("title", "")
        item["object_name"] = business_object.get("name", "")
        item["stage_label"] = _erp_stage_label(item.get("current_stage", ""))
        enriched.append(item)
    return enriched


def _insert_approval_step(conn, title: str, author_name: str, approver_name: str, item_link: str = ""):
    approval_id = next_safe_table_id(conn, "approvals")
    route = [approver_name] if approver_name else []
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO approvals (id, title, item_link, route, current_step, status, history, author, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            approval_id,
            title,
            item_link or f"/erp/process/{approval_id}",
            json.dumps(route),
            0,
            "pending",
            "[]",
            author_name,
            time.strftime("%d.%m.%Y %H:%M"),
        ),
    )
    return approval_id


def _autoroute_process_via_rules(process_id: int, actor: dict, request: Request):
    process = get_erp_process_run(process_id)
    if not process:
        return {"error": "not_found"}
    scenario = process.get("scenario") or _default_scenario_for_request_type(process.get("request_type", ""))
    payload = process.get("payload") or {}
    completed = []
    for stage in [item for item in scenario if item != "request"]:
        if process.get("current_stage") == "done":
            break
        if stage == "approval":
            approver_name = payload.get("approver_name", "")
            if approver_name and approver_name != actor.get("name", "") and actor.get("role") != "Директор":
                break
        result = advance_erp_process(
            process_id,
            ERPFlowAdvanceData(
                target_stage=stage,
                approver_name=payload.get("approver_name", ""),
                approver_role=payload.get("approver_role", "Директор"),
                item_article=payload.get("item_article", ""),
                item_name=payload.get("item_name", ""),
                qty=_safe_float(payload.get("qty")),
                unit=payload.get("unit", "шт"),
                unit_price=_safe_float(payload.get("unit_price")),
                supplier=payload.get("supplier", ""),
                order_name=payload.get("order_name", ""),
                responsible=payload.get("responsible", ""),
                recipient_email=payload.get("recipient_email", ""),
                payment_kind=payload.get("payment_kind", "incoming"),
                comment=payload.get("comment", ""),
                amount=_safe_float(process.get("amount")),
                currency=process.get("currency", "RUB"),
                due_date=process.get("due_date", ""),
            ),
            request,
        )
        if isinstance(result, dict) and result.get("error"):
            return {"status": "partial", "completed": completed, "error": result.get("error"), "process": get_erp_process_run(process_id)}
        completed.append(stage)
        process = get_erp_process_run(process_id) or process
    return {"status": "success", "completed": completed, "process": process}

def init_claims_table():
    conn = get_connection(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS claims (id INTEGER PRIMARY KEY, proj_id INTEGER, number TEXT, d_date TEXT, initiator TEXT, addressee TEXT, amount REAL, status TEXT, date_sent TEXT, deadline TEXT, date_answered TEXT, files TEXT, history TEXT)''')
    conn.commit()
    conn.close()

def init_courts_table():
    conn = get_connection(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS court_cases (id INTEGER PRIMARY KEY, proj_id INTEGER, number TEXT, court_name TEXT, plaintiff TEXT, defendant TEXT, amount REAL, instance TEXT, stage TEXT, next_hearing TEXT, files TEXT, history TEXT)''')
    conn.commit()
    conn.close()

@router.get("/api/claims")
def get_claims(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    init_claims_table(); conn = get_connection(row_factory=True); c = conn.cursor()
    c.execute("SELECT * FROM claims ORDER BY id DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

@router.post("/api/claims")
async def create_claim(data: ClaimData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    init_claims_table(); conn = get_connection(); c = conn.cursor(); cid = next_safe_table_id(conn, "claims")
    c.execute("INSERT INTO claims (id, proj_id, number, d_date, initiator, addressee, amount, status, date_sent, deadline, date_answered, files, history) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (cid, data.proj_id, data.number, data.d_date, data.initiator, data.addressee, data.amount, data.status, data.date_sent, data.deadline, data.date_answered, '[]', '[]'))
    conn.commit(); conn.close(); await manager.broadcast({"type": "claims"})
    return {"status": "success", "id": cid}

@router.put("/api/claims/{claim_id}")
async def update_claim(claim_id: int, data: ClaimData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    init_claims_table(); conn = get_connection(); c = conn.cursor()
    c.execute("UPDATE claims SET proj_id=?, number=?, d_date=?, initiator=?, addressee=?, amount=?, status=?, date_sent=?, deadline=?, date_answered=? WHERE id=?", (data.proj_id, data.number, data.d_date, data.initiator, data.addressee, data.amount, data.status, data.date_sent, data.deadline, data.date_answered, claim_id))
    conn.commit(); conn.close(); await manager.broadcast({"type": "claims"})
    return {"status": "success"}

@router.get("/api/court_cases")
def get_court_cases(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    init_courts_table(); conn = get_connection(row_factory=True); c = conn.cursor()
    c.execute("SELECT * FROM court_cases ORDER BY id DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

@router.post("/api/court_cases")
async def create_court_case(data: CourtCaseData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    init_courts_table(); conn = get_connection(); c = conn.cursor(); cid = next_safe_table_id(conn, "court_cases")
    c.execute("INSERT INTO court_cases (id, proj_id, number, court_name, plaintiff, defendant, amount, instance, stage, next_hearing, files, history) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (cid, data.proj_id, data.number, data.court_name, data.plaintiff, data.defendant, data.amount, data.instance, data.stage, data.next_hearing, '[]', '[]'))
    conn.commit(); conn.close(); await manager.broadcast({"type": "court_cases"})
    return {"status": "success", "id": cid}

@router.put("/api/court_cases/{case_id}")
async def update_court_case(case_id: int, data: CourtCaseData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    init_courts_table(); conn = get_connection(); c = conn.cursor()
    c.execute("UPDATE court_cases SET proj_id=?, number=?, court_name=?, plaintiff=?, defendant=?, amount=?, instance=?, stage=?, next_hearing=? WHERE id=?", (data.proj_id, data.number, data.court_name, data.plaintiff, data.defendant, data.amount, data.instance, data.stage, data.next_hearing, case_id))
    conn.commit(); conn.close(); await manager.broadcast({"type": "court_cases"})
    return {"status": "success"}

@router.get("/api/test_server")
def test_server():
    return {"message": "БРАТУХА, СЕРВЕР ОБНОВИЛСЯ И ВИДИТ НОВЫЙ КОД!"}

@router.get("/api/clients")
def get_clients(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "clients", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True); c = conn.cursor(); c.execute("SELECT * FROM clients")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


@router.get("/api/clients/lookup_inn")
def lookup_client_inn(inn: str, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "clients", "read"):
        return {"error": "forbidden"}
    result = _lookup_company_by_inn(inn)
    return result

@router.post("/api/clients")
def create_client(data: ClientData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "clients", "create"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO clients (name, inn, kpp, ogrn, legal_address, contact) VALUES (?, ?, ?, ?, ?, ?)",
        (data.name, data.inn, data.kpp, data.ogrn, data.legal_address, data.contact),
    )
    client_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"status": "success", "id": client_id}


@router.post("/api/clients/import")
async def import_clients(request: Request, upload: UploadFile = File(...)):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "clients", "import") or has_permission(actor, "clients", "create") or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    rows = _load_import_rows(upload)
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM clients")
    existing = [dict(row) for row in c.fetchall()]
    by_inn = {_normalize_duplicate_key(row.get("inn") or ""): row for row in existing if row.get("inn")}
    by_name = {_normalize_duplicate_key(row.get("name") or ""): row for row in existing if row.get("name")}
    created = 0
    updated = 0
    skipped = 0
    for raw in rows:
        item = _normalize_client_row(raw)
        if not item["name"]:
            skipped += 1
            continue
        inn_key = _normalize_duplicate_key(item["inn"])
        name_key = _normalize_duplicate_key(item["name"])
        match = (inn_key and by_inn.get(inn_key)) or by_name.get(name_key)
        if match:
            new_contact = item["contact"] or match.get("contact") or ""
            new_inn = item["inn"] or match.get("inn") or ""
            new_kpp = item["kpp"] or match.get("kpp") or ""
            new_ogrn = item["ogrn"] or match.get("ogrn") or ""
            new_legal_address = item["legal_address"] or match.get("legal_address") or ""
            c.execute(
                "UPDATE clients SET name=?, inn=?, kpp=?, ogrn=?, legal_address=?, contact=? WHERE id=?",
                (item["name"], new_inn, new_kpp, new_ogrn, new_legal_address, new_contact, match["id"]),
            )
            updated += 1
            normalized = {"id": match["id"], "name": item["name"], "inn": new_inn, "kpp": new_kpp, "ogrn": new_ogrn, "legal_address": new_legal_address, "contact": new_contact}
            by_name[name_key] = normalized
            if new_inn:
                by_inn[_normalize_duplicate_key(new_inn)] = normalized
        else:
            c.execute(
                "INSERT INTO clients (name, inn, kpp, ogrn, legal_address, contact) VALUES (?, ?, ?, ?, ?, ?)",
                (item["name"], item["inn"], item["kpp"], item["ogrn"], item["legal_address"], item["contact"]),
            )
            client_id = c.lastrowid
            created += 1
            normalized = {"id": client_id, "name": item["name"], "inn": item["inn"], "kpp": item["kpp"], "ogrn": item["ogrn"], "legal_address": item["legal_address"], "contact": item["contact"]}
            by_name[name_key] = normalized
            if item["inn"]:
                by_inn[inn_key] = normalized
    conn.commit()
    conn.close()
    audit_log("clients_imported", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="client_import", entity_id=upload.filename or "clients", details={"created": created, "updated": updated, "skipped": skipped})
    return {"status": "success", "created": created, "updated": updated, "skipped": skipped}


@router.post("/api/clients/merge")
def merge_clients(data: ClientMergeData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "clients", "merge") or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    duplicate_ids = [int(item) for item in data.duplicate_ids if int(item) != int(data.master_id)]
    if not duplicate_ids:
        return {"error": "duplicates_required"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM clients WHERE id=?", (data.master_id,))
    master = c.fetchone()
    if not master:
        conn.close()
        return {"error": "master_not_found"}
    c.execute(f"SELECT * FROM clients WHERE id IN ({','.join('?' for _ in duplicate_ids)})", tuple(duplicate_ids))
    duplicates = [dict(row) for row in c.fetchall()]
    if not duplicates:
        conn.close()
        return {"error": "duplicates_not_found"}
    master = dict(master)
    merged_contact = master.get("contact") or next((row.get("contact", "") for row in duplicates if row.get("contact")), "")
    merged_inn = master.get("inn") or next((row.get("inn", "") for row in duplicates if row.get("inn")), "")
    merged_kpp = master.get("kpp") or next((row.get("kpp", "") for row in duplicates if row.get("kpp")), "")
    merged_ogrn = master.get("ogrn") or next((row.get("ogrn", "") for row in duplicates if row.get("ogrn")), "")
    merged_legal_address = master.get("legal_address") or next((row.get("legal_address", "") for row in duplicates if row.get("legal_address")), "")
    old_names = [row.get("name", "") for row in duplicates if row.get("name")]
    c.execute(
        "UPDATE clients SET inn=?, kpp=?, ogrn=?, legal_address=?, contact=? WHERE id=?",
        (merged_inn, merged_kpp, merged_ogrn, merged_legal_address, merged_contact, data.master_id),
    )
    for table in ("contacts", "finance_payments", "purchase_orders", "sales_documents_extended", "expense_requests", "service_cases", "erp_process_runs", "erp_entity_links", "epl_waybills"):
        c.execute(f"UPDATE {table} SET client_id=? WHERE client_id IN ({','.join('?' for _ in duplicate_ids)})", (data.master_id, *duplicate_ids))
    _replace_project_client_name(conn, old_names, master.get("name", ""))
    c.execute(f"DELETE FROM clients WHERE id IN ({','.join('?' for _ in duplicate_ids)})", tuple(duplicate_ids))
    conn.commit()
    conn.close()
    audit_log("clients_merged", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="client", entity_id=str(data.master_id), details={"duplicates": duplicate_ids, "master_name": master.get("name", "")})
    return {"status": "success", "master_id": data.master_id, "merged": len(duplicate_ids)}


@router.get("/api/clients/{client_id}/dossier")
def get_client_dossier(client_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "clients", "read"):
        return {"error": "forbidden"}
    return build_client_dossier(
        actor=actor,
        client_id=client_id,
        db_name=DB_NAME,
        can_access_project=can_access_project,
        filter_rows_by_scope=filter_rows_by_scope,
        init_claims_table=init_claims_table,
        init_courts_table=init_courts_table,
        json_load=_json_load,
        load_epl_waybills_for_links=_load_epl_waybills_for_links,
        load_finance_rows=_load_finance_rows,
        load_production_rows=_load_production_rows,
        load_purchase_rows=_load_purchase_rows,
        load_sales_rows=_load_sales_rows,
        load_service_cases=_load_service_cases,
        normalize_match=_normalize_match,
        project_payload=_project_payload,
        safe_float=_safe_float,
        safe_int=_safe_int,
        table_exists=_table_exists,
    )


@router.get("/api/outreach/prospects")
def get_outreach_prospects(
    request: Request,
    search: str = "",
    status: str = "",
    manager: str = "",
    processed: str = "",
    only_overdue: int = 0,
    only_due_today: int = 0,
):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM outreach_prospects ORDER BY is_processed ASC, updated_at DESC, id DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    search_key = _normalize_match(search)
    manager_key = _normalize_match(manager)
    status_key = _normalize_outreach_status(status) if status else ""
    processed_key = _normalize_match(processed)
    visible = []
    for row in _decorate_outreach_rows(rows):
        if status_key and row.get("status") != status_key:
            continue
        if manager_key:
            haystack_manager = _normalize_match(f"{row.get('manager_name', '')} {row.get('manager_email', '')}")
            if manager_key not in haystack_manager:
                continue
        if processed_key in {"yes", "processed", "done", "1"} and not _safe_int(row.get("is_processed")):
            continue
        if processed_key in {"no", "pending", "0"} and _safe_int(row.get("is_processed")):
            continue
        if only_overdue and not row.get("is_overdue"):
            continue
        if only_due_today and not row.get("is_due_today"):
            continue
        if search_key:
            haystack = " ".join([
                row.get("company_name", ""),
                row.get("contact_name", ""),
                row.get("phone", ""),
                row.get("email", ""),
                row.get("notes", ""),
                row.get("source_name", ""),
                row.get("city", ""),
                row.get("last_result", ""),
            ])
            if search_key not in _normalize_match(haystack):
                continue
        visible.append(row)
    return visible


@router.post("/api/outreach/prospects")
def create_outreach_prospect(data: OutreachProspectData, request: Request):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "create"):
        return {"error": "forbidden"}
    company_name = _normalize_spaces(data.company_name)
    if not company_name:
        return {"error": "validation_error", "message": "Укажите компанию."}
    now = int(time.time())
    status_value = _normalize_outreach_status(data.status)
    is_processed = 1 if status_value not in {"new", "assigned"} else 0
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO outreach_prospects (
            company_name, company_inn, contact_name, position, phone, email, website, city, contact_method, source_name, source_file,
            status, priority, manager_name, manager_email, planned_contact_date, next_action, next_action_date, last_contact_at, last_channel, last_result,
            attempts_count, is_processed, do_not_contact, converted_client_id, converted_lead_id, tags_json, notes, extra_json, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '', 0, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_name,
            _normalize_spaces(data.company_inn),
            _normalize_spaces(data.contact_name),
            _normalize_spaces(data.position),
            _normalize_spaces(data.phone),
            _normalize_spaces(data.email),
            _normalize_spaces(data.website),
            _normalize_spaces(data.city),
            _normalize_spaces(data.contact_method) or ("phone" if data.phone else "email" if data.email else ""),
            _normalize_spaces(data.source_name),
            _normalize_spaces(data.source_file),
            status_value,
            _normalize_outreach_priority(data.priority),
            _normalize_spaces(data.manager_name),
            _normalize_spaces(data.manager_email),
            _normalize_spaces(data.planned_contact_date),
            _normalize_spaces(data.next_action),
            _normalize_spaces(data.next_action_date),
            is_processed,
            1 if _safe_int(data.do_not_contact) else 0,
            json.dumps(data.tags or [], ensure_ascii=False),
            _normalize_spaces(data.notes),
            json.dumps(data.extra or {}, ensure_ascii=False),
            actor.get("email", ""),
            now,
            now,
        ),
    )
    prospect_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("outreach_prospect_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="outreach_prospect", entity_id=str(prospect_id), details={"company_name": company_name})
    return {"status": "success", "id": prospect_id}


@router.post("/api/outreach/prospects/import_rows")
def import_outreach_prospects(data: OutreachImportData, request: Request):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "create"):
        return {"error": "forbidden"}
    if not data.rows:
        return {"error": "items_required", "message": "Добавьте хотя бы одну строку для импорта."}
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM outreach_prospects")
    existing_rows = [dict(row) for row in c.fetchall()]
    existing_keys = _outreach_existing_key_map(existing_rows)
    created = 0
    updated = 0
    skipped = 0
    default_manager_name = _normalize_spaces(data.default_manager_name)
    default_manager_email = _normalize_spaces(data.default_manager_email)
    default_plan_date = _normalize_spaces(data.planned_contact_date)
    source_filename = _normalize_spaces(data.filename)
    source_name = _normalize_spaces(data.source_name)
    for raw in data.rows:
        item = _normalize_outreach_row(raw or {})
        if not item["company_name"] and not item["phone"] and not item["email"]:
            skipped += 1
            continue
        item["manager_name"] = item["manager_name"] or default_manager_name
        item["manager_email"] = item["manager_email"] or default_manager_email
        item["planned_contact_date"] = item["planned_contact_date"] or default_plan_date
        item["source_name"] = item["source_name"] or source_name
        lookup_keys = _outreach_item_lookup_keys(item)
        match = next((existing_keys.get(key) for key in lookup_keys if key and existing_keys.get(key)), None)
        item_status = item["status"] or "new"
        item_processed = 1 if item_status not in {"new", "assigned"} else 0
        if match:
            merged_status = match.get("status") if match.get("status") in {"converted", "warm", "meeting", "do_not_contact"} else item_status or match.get("status") or "new"
            merged_processed = _safe_int(match.get("is_processed")) or item_processed
            merged_notes = item["notes"] or match.get("notes") or ""
            c.execute(
                """
                UPDATE outreach_prospects
                SET company_name=?, company_inn=?, contact_name=?, position=?, phone=?, email=?, website=?, city=?, contact_method=?, source_name=?, source_file=?,
                    status=?, priority=?, manager_name=?, manager_email=?, planned_contact_date=?, next_action=?, next_action_date=?, is_processed=?, do_not_contact=?,
                    tags_json=?, notes=?, extra_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    item["company_name"] or match.get("company_name") or "",
                    item["company_inn"] or match.get("company_inn") or "",
                    item["contact_name"] or match.get("contact_name") or "",
                    item["position"] or match.get("position") or "",
                    item["phone"] or match.get("phone") or "",
                    item["email"] or match.get("email") or "",
                    item["website"] or match.get("website") or "",
                    item["city"] or match.get("city") or "",
                    item["contact_method"] or match.get("contact_method") or "",
                    item["source_name"] or match.get("source_name") or "",
                    source_filename or match.get("source_file") or "",
                    merged_status,
                    item["priority"] or match.get("priority") or "normal",
                    item["manager_name"] or match.get("manager_name") or "",
                    item["manager_email"] or match.get("manager_email") or "",
                    item["planned_contact_date"] or match.get("planned_contact_date") or "",
                    item["next_action"] or match.get("next_action") or "",
                    item["next_action_date"] or match.get("next_action_date") or "",
                    merged_processed,
                    1 if _safe_int(item.get("do_not_contact")) or merged_status == "do_not_contact" else _safe_int(match.get("do_not_contact")),
                    json.dumps(item.get("tags") or _json_load(match.get("tags_json"), []), ensure_ascii=False),
                    merged_notes,
                    json.dumps(item.get("extra") or _json_load(match.get("extra_json"), {}), ensure_ascii=False),
                    now,
                    _safe_int(match.get("id")),
                ),
            )
            updated += 1
        else:
            c.execute(
                """
                INSERT INTO outreach_prospects (
                    company_name, company_inn, contact_name, position, phone, email, website, city, contact_method, source_name, source_file,
                    status, priority, manager_name, manager_email, planned_contact_date, next_action, next_action_date, last_contact_at, last_channel, last_result,
                    attempts_count, is_processed, do_not_contact, converted_client_id, converted_lead_id, tags_json, notes, extra_json, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '', 0, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["company_name"],
                    item["company_inn"],
                    item["contact_name"],
                    item["position"],
                    item["phone"],
                    item["email"],
                    item["website"],
                    item["city"],
                    item["contact_method"],
                    item["source_name"],
                    source_filename,
                    item_status,
                    item["priority"],
                    item["manager_name"],
                    item["manager_email"],
                    item["planned_contact_date"],
                    item["next_action"],
                    item["next_action_date"],
                    item_processed,
                    1 if _safe_int(item.get("do_not_contact")) or item_status == "do_not_contact" else 0,
                    json.dumps(item.get("tags") or [], ensure_ascii=False),
                    item["notes"],
                    json.dumps(item.get("extra") or {}, ensure_ascii=False),
                    actor.get("email", ""),
                    now,
                    now,
                ),
            )
            new_id = c.lastrowid
            created += 1
            virtual_row = {"id": new_id, **item, "is_processed": item_processed}
            for key in lookup_keys:
                if key:
                    existing_keys[key] = virtual_row
    c.execute(
        """
        INSERT INTO outreach_import_batches (
            source_filename, source_name, rows_total, created_total, updated_total, skipped_total,
            default_manager_name, actor_email, actor_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_filename,
            source_name,
            len(data.rows),
            created,
            updated,
            skipped,
            default_manager_name,
            actor.get("email", ""),
            actor.get("name", ""),
            now,
        ),
    )
    batch_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("outreach_imported", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="outreach_import", entity_id=str(batch_id), details={"filename": source_filename, "rows_total": len(data.rows), "created": created, "updated": updated, "skipped": skipped})
    return {"status": "success", "batch_id": batch_id, "created": created, "updated": updated, "skipped": skipped}


@router.post("/api/outreach/prospects/import_preview")
def preview_outreach_import(data: OutreachImportData, request: Request):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "create"):
        return {"error": "forbidden"}
    if not data.rows:
        return {"error": "items_required", "message": "Добавьте хотя бы одну строку для предпросмотра."}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM outreach_prospects")
        existing_rows = [dict(row) for row in c.fetchall()]
    finally:
        conn.close()
    return {"status": "success", **_outreach_import_preview_counts(data, existing_rows)}


@router.put("/api/outreach/prospects/{prospect_id}")
def update_outreach_prospect(prospect_id: int, data: OutreachProspectData, request: Request):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM outreach_prospects WHERE id=?", (_safe_int(prospect_id),))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found", "message": "Карточка базы не найдена."}
    current = dict(row)
    now = int(time.time())
    status_value = _normalize_outreach_status(data.status or current.get("status") or "new")
    is_processed = 1 if status_value not in {"new", "assigned"} or _safe_int(current.get("is_processed")) else 0
    c.execute(
        """
        UPDATE outreach_prospects
        SET company_name=?, company_inn=?, contact_name=?, position=?, phone=?, email=?, website=?, city=?, contact_method=?, source_name=?, source_file=?,
            status=?, priority=?, manager_name=?, manager_email=?, planned_contact_date=?, next_action=?, next_action_date=?, is_processed=?, do_not_contact=?,
            tags_json=?, notes=?, extra_json=?, updated_at=?
        WHERE id=?
        """,
        (
            _normalize_spaces(data.company_name) or current.get("company_name") or "",
            _normalize_spaces(data.company_inn) or current.get("company_inn") or "",
            _normalize_spaces(data.contact_name) or current.get("contact_name") or "",
            _normalize_spaces(data.position) or current.get("position") or "",
            _normalize_spaces(data.phone) or current.get("phone") or "",
            _normalize_spaces(data.email) or current.get("email") or "",
            _normalize_spaces(data.website) or current.get("website") or "",
            _normalize_spaces(data.city) or current.get("city") or "",
            _normalize_spaces(data.contact_method) or current.get("contact_method") or "",
            _normalize_spaces(data.source_name) or current.get("source_name") or "",
            _normalize_spaces(data.source_file) or current.get("source_file") or "",
            status_value,
            _normalize_outreach_priority(data.priority or current.get("priority") or "normal"),
            _normalize_spaces(data.manager_name) or current.get("manager_name") or "",
            _normalize_spaces(data.manager_email) or current.get("manager_email") or "",
            _normalize_spaces(data.planned_contact_date) or current.get("planned_contact_date") or "",
            _normalize_spaces(data.next_action) or current.get("next_action") or "",
            _normalize_spaces(data.next_action_date) or current.get("next_action_date") or "",
            is_processed,
            1 if _safe_int(data.do_not_contact) or status_value == "do_not_contact" else 0,
            json.dumps(data.tags or _json_load(current.get("tags_json"), []), ensure_ascii=False),
            _normalize_spaces(data.notes) or current.get("notes") or "",
            json.dumps(data.extra or _json_load(current.get("extra_json"), {}), ensure_ascii=False),
            now,
            _safe_int(prospect_id),
        ),
    )
    conn.commit()
    conn.close()
    audit_log("outreach_prospect_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="outreach_prospect", entity_id=str(prospect_id), details={"company_name": data.company_name, "status": status_value})
    return {"status": "success"}


@router.post("/api/outreach/prospects/bulk")
def bulk_update_outreach_prospects(data: OutreachBulkActionData, request: Request):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "update"):
        return {"error": "forbidden"}
    ids = [_safe_int(item) for item in (data.ids or []) if _safe_int(item)]
    if not ids:
        return {"error": "bulk_action_invalid", "message": "Выберите хотя бы одну строку."}
    status_value = _normalize_outreach_status(data.status) if data.status else ""
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    placeholders = ",".join("?" for _ in ids)
    c.execute(f"SELECT * FROM outreach_prospects WHERE id IN ({placeholders})", tuple(ids))
    rows = [dict(row) for row in c.fetchall()]
    updated = 0
    for row in rows:
        next_status = status_value or row.get("status") or "new"
        next_processed = _safe_int(row.get("is_processed"))
        if data.action in {"mark_processed", "apply"} and not next_processed:
            next_processed = 1
        if next_status not in {"new", "assigned"}:
            next_processed = 1
        next_notes = row.get("notes") or ""
        if data.note:
            prefix = f"[{_now_display_dt()}] {actor.get('name', '')}: "
            next_notes = f"{prefix}{_normalize_spaces(data.note)}\n{next_notes}".strip()
        c.execute(
            """
            UPDATE outreach_prospects
            SET manager_name=?, manager_email=?, planned_contact_date=?, status=?, is_processed=?, do_not_contact=?, notes=?, updated_at=?
            WHERE id=?
            """,
            (
                _normalize_spaces(data.manager_name) or row.get("manager_name") or "",
                _normalize_spaces(data.manager_email) or row.get("manager_email") or "",
                _normalize_spaces(data.planned_contact_date) or row.get("planned_contact_date") or "",
                next_status,
                next_processed,
                1 if next_status == "do_not_contact" else _safe_int(row.get("do_not_contact")),
                next_notes,
                now,
                _safe_int(row.get("id")),
            ),
        )
        updated += 1
    conn.commit()
    conn.close()
    audit_log("outreach_bulk_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="outreach_prospect", entity_id="bulk", details={"ids": ids, "action": data.action, "status": status_value, "manager_name": data.manager_name, "planned_contact_date": data.planned_contact_date})
    return {"status": "success", "updated": updated}


@router.get("/api/outreach/imports")
def get_outreach_import_batches(request: Request):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM outreach_import_batches ORDER BY created_at DESC, id DESC LIMIT 20")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


@router.post("/api/outreach/activities")
def create_outreach_activity(data: OutreachActivityData, request: Request):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "update"):
        return {"error": "forbidden"}
    prospect_id = _safe_int(data.prospect_id)
    if not prospect_id:
        return {"error": "validation_error", "message": "Не выбрана карточка базы."}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM outreach_prospects WHERE id=?", (prospect_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found", "message": "Карточка базы не найдена."}
    prospect = dict(row)
    now = int(time.time())
    channel = _normalize_spaces(data.channel) or _normalize_spaces(data.activity_type) or "call"
    result_status = _normalize_spaces(data.result_status)
    c.execute(
        """
        INSERT INTO outreach_activities (
            prospect_id, activity_type, result_status, summary, next_action, next_action_date, channel, manager_name, manager_email, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prospect_id,
            _normalize_spaces(data.activity_type) or "call",
            result_status,
            _normalize_spaces(data.summary),
            _normalize_spaces(data.next_action),
            _normalize_spaces(data.next_action_date),
            channel,
            actor.get("name", ""),
            actor.get("email", ""),
            now,
        ),
    )
    activity_id = c.lastrowid
    status_from_result = _outreach_status_from_result(result_status)
    next_status = _normalize_outreach_status(data.prospect_status or status_from_result or prospect.get("status") or "new")
    attempts_inc = 1 if (data.activity_type or "").strip() in {"call", "email", "message", "meeting"} else 0
    next_processed = 1 if attempts_inc or next_status not in {"new", "assigned"} or _safe_int(prospect.get("is_processed")) else 0
    c.execute(
        """
        UPDATE outreach_prospects
        SET status=?, next_action=?, next_action_date=?, planned_contact_date=?, last_contact_at=?, last_channel=?, last_result=?, attempts_count=?, is_processed=?, do_not_contact=?, updated_at=?
        WHERE id=?
        """,
        (
            next_status,
            _normalize_spaces(data.next_action) or prospect.get("next_action") or "",
            _normalize_spaces(data.next_action_date) or prospect.get("next_action_date") or "",
            _normalize_spaces(data.next_action_date) or prospect.get("planned_contact_date") or "",
            _now_display_dt(),
            channel,
            result_status,
            _safe_int(prospect.get("attempts_count")) + attempts_inc,
            next_processed,
            1 if next_status == "do_not_contact" else _safe_int(prospect.get("do_not_contact")),
            now,
            prospect_id,
        ),
    )
    conn.commit()
    conn.close()
    audit_log("outreach_activity_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="outreach_activity", entity_id=str(activity_id), details={"prospect_id": prospect_id, "activity_type": data.activity_type, "result_status": result_status})
    return {"status": "success", "id": activity_id}


@router.get("/api/outreach/reports")
def get_outreach_reports(request: Request, report_date: str = "", manager_email: str = ""):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM outreach_reports ORDER BY report_date DESC, updated_at DESC, id DESC LIMIT 120")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    report_key = _normalize_spaces(report_date)
    manager_key = _normalize_match(manager_email)
    visible = []
    for row in rows:
        if report_key and row.get("report_date") != report_key:
            continue
        if manager_key and manager_key not in _normalize_match(row.get("manager_email", "")):
            continue
        visible.append(row)
    return visible


@router.get("/api/outreach/manager_control")
def get_outreach_manager_control(request: Request):
    actor = require_approved_user(request)
    if not actor or not (actor.get("role") == "Директор" or _safe_int(actor.get("is_head"))):
        return []
    if not _outreach_allowed(actor, "read"):
        return {"error": "forbidden"}
    today = _today_display()
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM outreach_prospects ORDER BY updated_at DESC, id DESC")
    prospects = _decorate_outreach_rows([dict(row) for row in c.fetchall()])
    c.execute("SELECT * FROM outreach_reports WHERE report_date=? ORDER BY updated_at DESC, id DESC", (today,))
    reports = [dict(row) for row in c.fetchall()]
    conn.close()

    managers: dict[str, dict] = {}

    def add_manager(name: str, email: str):
        key = _normalize_match(email or name)
        if not key:
            return
        if key not in managers:
            managers[key] = {"name": _normalize_spaces(name), "email": _normalize_spaces(email)}

    for row in prospects:
        add_manager(row.get("manager_name", ""), row.get("manager_email", ""))
    for report in reports:
        add_manager(report.get("manager_name", ""), report.get("manager_email", ""))

    rows = []
    for manager in managers.values():
        manager_prospects = [row for row in prospects if _outreach_manager_matches(row, manager)]
        report = next((item for item in reports if _outreach_report_matches(item, manager)), None)
        calls_today = 0
        emails_today = 0
        for prospect in manager_prospects:
            for activity in prospect.get("activities", []) if isinstance(prospect.get("activities"), list) else []:
                created_at = _safe_int(activity.get("created_at"))
                if not created_at or datetime.fromtimestamp(created_at).strftime("%d.%m.%Y") != today:
                    continue
                if activity.get("activity_type") == "call":
                    calls_today += 1
                if activity.get("activity_type") == "email":
                    emails_today += 1
        processed_today = sum(1 for row in manager_prospects if _display_datetime_is_today(row.get("last_contact_at", ""), today))
        converted_today = sum(1 for row in manager_prospects if row.get("status") == "converted" and _display_datetime_is_today(row.get("last_contact_at", ""), today))
        rows.append(
            {
                "name": manager.get("name") or manager.get("email") or "Без имени",
                "email": manager.get("email", ""),
                "plan": _safe_int(report.get("plan_total")) if report else sum(1 for row in manager_prospects if row.get("is_due_today")),
                "processed": _safe_int(report.get("processed_total")) if report else processed_today,
                "calls": _safe_int(report.get("calls_total")) if report else calls_today,
                "emails": _safe_int(report.get("emails_total")) if report else emails_today,
                "overdue": sum(1 for row in manager_prospects if row.get("is_overdue")),
                "first_contact_overdue": sum(1 for row in manager_prospects if row.get("is_first_contact_overdue")),
                "warm": sum(1 for row in manager_prospects if row.get("status") in {"warm", "meeting"}),
                "leads": _safe_int(report.get("converted_total")) if report else converted_today,
                "submitted": bool(report),
            }
        )

    return sorted(
        rows,
        key=lambda item: (
            1 if item.get("submitted") else 0,
            -_safe_int(item.get("overdue")),
            _normalize_match(item.get("name") or item.get("email") or ""),
        ),
    )


@router.post("/api/outreach/reports")
def save_outreach_report(data: OutreachReportData, request: Request):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "update"):
        return {"error": "forbidden"}
    report_date = _normalize_spaces(data.report_date) or _today_display()
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT id FROM outreach_reports WHERE report_date=? AND manager_email=?", (report_date, actor.get("email", "")))
    row = c.fetchone()
    if row:
        report_id = _safe_int(row.get("id") if isinstance(row, dict) else row[0])
        c.execute(
            """
            UPDATE outreach_reports
            SET manager_name=?, plan_total=?, processed_total=?, calls_total=?, emails_total=?, meetings_total=?, converted_total=?, summary=?, blockers=?, next_day_focus=?, updated_at=?
            WHERE id=?
            """,
            (
                actor.get("name", ""),
                _safe_int(data.plan_total),
                _safe_int(data.processed_total),
                _safe_int(data.calls_total),
                _safe_int(data.emails_total),
                _safe_int(data.meetings_total),
                _safe_int(data.converted_total),
                _normalize_spaces(data.summary),
                _normalize_spaces(data.blockers),
                _normalize_spaces(data.next_day_focus),
                now,
                report_id,
            ),
        )
    else:
        c.execute(
            """
            INSERT INTO outreach_reports (
                report_date, manager_name, manager_email, plan_total, processed_total, calls_total, emails_total, meetings_total, converted_total,
                summary, blockers, next_day_focus, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_date,
                actor.get("name", ""),
                actor.get("email", ""),
                _safe_int(data.plan_total),
                _safe_int(data.processed_total),
                _safe_int(data.calls_total),
                _safe_int(data.emails_total),
                _safe_int(data.meetings_total),
                _safe_int(data.converted_total),
                _normalize_spaces(data.summary),
                _normalize_spaces(data.blockers),
                _normalize_spaces(data.next_day_focus),
                now,
                now,
            ),
        )
        report_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("outreach_report_saved", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="outreach_report", entity_id=str(report_id), details={"report_date": report_date})
    return {"status": "success", "id": report_id}


@router.post("/api/outreach/prospects/{prospect_id}/convert")
def convert_outreach_prospect(prospect_id: int, request: Request):
    actor = require_approved_user(request)
    if not _outreach_allowed(actor, "create"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM outreach_prospects WHERE id=?", (_safe_int(prospect_id),))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found", "message": "Карточка базы не найдена."}
    prospect = dict(row)
    existing_lead_id = _safe_int(prospect.get("converted_lead_id"))
    if existing_lead_id:
        conn.close()
        return {"status": "success", "lead_id": existing_lead_id, "client_id": _safe_int(prospect.get("converted_client_id"))}
    client_id = 0
    if prospect.get("company_inn"):
        c.execute("SELECT id FROM clients WHERE inn=? LIMIT 1", (_normalize_spaces(prospect.get("company_inn")),))
        found = c.fetchone()
        if found:
            client_id = _safe_int(found.get("id") if isinstance(found, dict) else found[0])
    if not client_id and prospect.get("company_name"):
        c.execute("SELECT id FROM clients WHERE LOWER(name)=LOWER(?) LIMIT 1", (_normalize_spaces(prospect.get("company_name")),))
        found = c.fetchone()
        if found:
            client_id = _safe_int(found.get("id") if isinstance(found, dict) else found[0])
    if not client_id:
        c.execute(
            "INSERT INTO clients (name, inn, kpp, ogrn, legal_address, contact) VALUES (?, ?, '', '', '', ?)",
            (
                _normalize_spaces(prospect.get("company_name")),
                _normalize_spaces(prospect.get("company_inn")),
                _normalize_spaces(" / ".join(part for part in [prospect.get("contact_name"), prospect.get("phone"), prospect.get("email")] if part)),
            ),
        )
        client_id = c.lastrowid
    now = int(time.time())
    c.execute(
        """
        INSERT INTO crm_leads (
            title, client_name, contact_name, contact_email, contact_phone, source, stage, probability, budget, currency,
            responsible, next_action, next_action_date, priority, tags_json, comment, linked_client_id, linked_project_id, linked_deal_id, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
        """,
        (
            _normalize_spaces(prospect.get("company_name")) or f"Лид из базы #{prospect_id}",
            _normalize_spaces(prospect.get("company_name")),
            _normalize_spaces(prospect.get("contact_name")),
            _normalize_spaces(prospect.get("email")),
            _normalize_spaces(prospect.get("phone")),
            f"outreach:{_normalize_spaces(prospect.get('source_name')) or 'manual'}",
            "qualified",
            35,
            0,
            "RUB",
            _normalize_spaces(prospect.get("manager_name")) or actor.get("name", ""),
            _normalize_spaces(prospect.get("next_action")) or "Связаться и квалифицировать",
            _normalize_spaces(prospect.get("next_action_date")),
            _normalize_outreach_priority(prospect.get("priority") or "normal"),
            prospect.get("tags_json") or "[]",
            _normalize_spaces(prospect.get("notes")),
            client_id,
            actor.get("email", ""),
            now,
            now,
        ),
    )
    lead_id = c.lastrowid
    c.execute(
        """
        UPDATE outreach_prospects
        SET status='converted', is_processed=1, converted_client_id=?, converted_lead_id=?, updated_at=?
        WHERE id=?
        """,
        (client_id, lead_id, now, prospect_id),
    )
    conn.commit()
    conn.close()
    audit_log("outreach_prospect_converted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="outreach_prospect", entity_id=str(prospect_id), details={"lead_id": lead_id, "client_id": client_id})
    return {"status": "success", "lead_id": lead_id, "client_id": client_id}


@router.get("/api/business_objects")
def get_business_objects(request: Request, client_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "read"):
        return {"error": "forbidden"}
    return _load_business_objects_directory(client_id)


@router.post("/api/business_objects")
def create_business_object(data: BusinessObjectData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO business_objects (
            client_id, name, code, address, city, region, responsible_name, responsible_email,
            comment, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.client_id,
            _normalize_spaces(data.name),
            _normalize_spaces(data.code),
            _normalize_spaces(data.address),
            _normalize_spaces(data.city),
            _normalize_spaces(data.region),
            _normalize_spaces(data.responsible_name),
            _normalize_spaces(data.responsible_email),
            _normalize_spaces(data.comment),
            actor.get("email", ""),
            now,
            now,
        ),
    )
    object_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("business_object_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="business_object", entity_id=str(object_id), details={"name": data.name, "client_id": data.client_id})
    return {"status": "success", "id": object_id}


@router.put("/api/business_objects/{object_id}")
def update_business_object(object_id: int, data: BusinessObjectData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE business_objects
        SET client_id=?, name=?, code=?, address=?, city=?, region=?, responsible_name=?, responsible_email=?, comment=?, updated_at=?
        WHERE id=?
        """,
        (
            data.client_id,
            _normalize_spaces(data.name),
            _normalize_spaces(data.code),
            _normalize_spaces(data.address),
            _normalize_spaces(data.city),
            _normalize_spaces(data.region),
            _normalize_spaces(data.responsible_name),
            _normalize_spaces(data.responsible_email),
            _normalize_spaces(data.comment),
            now,
            object_id,
        ),
    )
    conn.commit()
    conn.close()
    audit_log("business_object_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="business_object", entity_id=str(object_id), details={"name": data.name, "client_id": data.client_id})
    return {"status": "success"}


@router.get("/api/contracts")
def get_contract_registry(
    request: Request,
    client_id: int = 0,
    project_id: int = 0,
    search: str = "",
    folder: str = "",
    contract_type: str = "",
    vat_mode: str = "",
    risk_level: str = "",
    status: str = "",
    overdue_only: int = 0,
):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "read"):
        return {"error": "forbidden"}
    rows = _load_contract_directory()
    visible = []
    search_normalized = _normalize_match(search)
    today = datetime.now()
    for row in rows:
        if client_id and _safe_int(row.get("client_id")) != client_id:
            continue
        if project_id and _safe_int(row.get("project_id")) != project_id:
            continue
        project = _load_project_row(_safe_int(row.get("project_id"))) if _safe_int(row.get("project_id")) else None
        if project and not can_access_project(actor, _project_payload(project)):
            continue
        if folder and _normalize_match(row.get("folder", "")) != _normalize_match(folder):
            continue
        if contract_type and _normalize_match(row.get("contract_type", "")) != _normalize_match(contract_type):
            continue
        if vat_mode and _normalize_match(row.get("vat_mode", "")) != _normalize_match(vat_mode):
            continue
        if risk_level and _normalize_match(row.get("risk_level", "")) != _normalize_match(risk_level):
            continue
        if status and _normalize_match(row.get("status", "")) != _normalize_match(status):
            continue
        end_date = _parse_ru_date(row.get("end_date", ""))
        row["is_overdue"] = int(bool(end_date and end_date.date() < today.date() and _normalize_match(row.get("status", "")) not in {"closed", "completed", "done"}))
        if overdue_only and not row["is_overdue"]:
            continue
        if search_normalized:
            haystack = " ".join([
                row.get("contract_number", ""),
                row.get("title", ""),
                row.get("client_name", ""),
                row.get("project_name", ""),
                row.get("manager_name", ""),
                row.get("folder", ""),
                row.get("category", ""),
                row.get("contract_type", ""),
            ])
            if search_normalized not in _normalize_match(haystack):
                continue
        visible.append(row)
    return visible


@router.post("/api/contracts")
def create_contract_master(data: ContractMasterData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    context = _resolve_master_context(conn, data.project_id, data.client_id, 0, data.object_id, autocreate=False)
    client_id = context["client_id"] or data.client_id
    object_id = context["object_id"] or data.object_id
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO contract_master (
            project_id, client_id, object_id, contract_number, title, status, amount, currency,
            start_date, end_date, manager_name, manager_email, comment, custom_fields,
            contract_type, category, folder, vat_mode, risk_level, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.project_id,
            client_id,
            object_id,
            _normalize_spaces(data.contract_number),
            _normalize_spaces(data.title),
            _normalize_spaces(data.status) or "draft",
            _safe_float(data.amount),
            _normalize_spaces(data.currency) or "RUB",
            _normalize_spaces(data.start_date),
            _normalize_spaces(data.end_date),
            _normalize_spaces(data.manager_name),
            _normalize_spaces(data.manager_email) or _user_email_by_name(conn, data.manager_name),
            _normalize_spaces(data.comment),
            json.dumps(data.custom_fields or [], ensure_ascii=False),
            _normalize_spaces(data.contract_type) or "standard",
            _normalize_spaces(data.category),
            _normalize_spaces(data.folder) or "Все договоры",
            _normalize_spaces(data.vat_mode) or "with_vat",
            _normalize_spaces(data.risk_level) or "normal",
            actor.get("email", ""),
            now,
            now,
        ),
    )
    contract_id = c.lastrowid
    if data.project_id:
        _propagate_project_master_links(conn, data.project_id, client_id, contract_id, object_id)
        _sync_contract_back_to_project(conn, contract_id)
    conn.commit()
    conn.close()
    audit_log("contract_master_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="contract_master", entity_id=str(contract_id), details={"contract_number": data.contract_number, "project_id": data.project_id, "client_id": client_id})
    return {"status": "success", "id": contract_id}


@router.put("/api/contracts/{contract_id}")
def update_contract_master(contract_id: int, data: ContractMasterData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    context = _resolve_master_context(conn, data.project_id, data.client_id, contract_id, data.object_id, autocreate=False)
    client_id = context["client_id"] or data.client_id
    object_id = context["object_id"] or data.object_id
    c = conn.cursor()
    c.execute(
        """
        UPDATE contract_master
        SET project_id=?, client_id=?, object_id=?, contract_number=?, title=?, status=?, amount=?, currency=?,
            start_date=?, end_date=?, manager_name=?, manager_email=?, comment=?, custom_fields=?,
            contract_type=?, category=?, folder=?, vat_mode=?, risk_level=?, updated_at=?
        WHERE id=?
        """,
        (
            data.project_id,
            client_id,
            object_id,
            _normalize_spaces(data.contract_number),
            _normalize_spaces(data.title),
            _normalize_spaces(data.status) or "draft",
            _safe_float(data.amount),
            _normalize_spaces(data.currency) or "RUB",
            _normalize_spaces(data.start_date),
            _normalize_spaces(data.end_date),
            _normalize_spaces(data.manager_name),
            _normalize_spaces(data.manager_email) or _user_email_by_name(conn, data.manager_name),
            _normalize_spaces(data.comment),
            json.dumps(data.custom_fields or [], ensure_ascii=False),
            _normalize_spaces(data.contract_type) or "standard",
            _normalize_spaces(data.category),
            _normalize_spaces(data.folder) or "Все договоры",
            _normalize_spaces(data.vat_mode) or "with_vat",
            _normalize_spaces(data.risk_level) or "normal",
            now,
            contract_id,
        ),
    )
    if data.project_id:
        _propagate_project_master_links(conn, data.project_id, client_id, contract_id, object_id)
    _sync_contract_back_to_project(conn, contract_id)
    conn.commit()
    conn.close()
    audit_log("contract_master_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="contract_master", entity_id=str(contract_id), details={"contract_number": data.contract_number, "project_id": data.project_id, "client_id": client_id})
    return {"status": "success"}


@router.post("/api/projects/{proj_id}/contract_master/sync")
def sync_project_contract_master(proj_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    row = _load_project_row(proj_id)
    if not row:
        return {"error": "not_found"}
    project = _project_payload(row)
    if not can_edit_project(actor, project):
        return {"error": "forbidden"}
    conn = get_connection()
    result = _sync_project_master_data(conn, project, actor)
    conn.commit()
    conn.close()
    audit_log("project_contract_synced", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="project", entity_id=str(proj_id), details=result)
    return {"status": "success", **result}


@router.get("/api/contracts/{contract_id}/card")
def get_contract_card(contract_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "read"):
        return {"error": "forbidden"}
    init_claims_table()
    init_courts_table()
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            cm.*,
            COALESCE(cl.name, '') AS client_name,
            COALESCE(cl.inn, '') AS client_inn,
            COALESCE(cl.contact, '') AS client_contact,
            COALESCE(bo.name, '') AS object_name,
            COALESCE(bo.address, '') AS object_address,
            COALESCE(bo.city, '') AS object_city,
            COALESCE(bo.region, '') AS object_region,
            COALESCE(bo.responsible_name, '') AS object_responsible_name,
            COALESCE(bo.responsible_email, '') AS object_responsible_email,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract
        FROM contract_master cm
        LEFT JOIN clients cl ON cl.id = cm.client_id
        LEFT JOIN business_objects bo ON bo.id = cm.object_id
        LEFT JOIN projects p ON p.id = cm.project_id
        WHERE cm.id=?
        """,
        (contract_id,),
    )
    contract_row = c.fetchone()
    if not contract_row:
        conn.close()
        return {"error": "not_found"}
    contract = dict(contract_row)
    contract["custom_fields"] = _json_load(contract.get("custom_fields"), [])
    primary_project = _load_project_row(_safe_int(contract.get("project_id"))) if _safe_int(contract.get("project_id")) else None
    if primary_project and not can_access_project(actor, _project_payload(primary_project)):
        conn.close()
        return {"error": "forbidden"}

    c.execute("SELECT * FROM projects WHERE contract_id=? ORDER BY id DESC", (contract_id,))
    projects = []
    for row in c.fetchall():
        project = _project_payload(dict(row))
        if can_access_project(actor, project):
            projects.append(project)
    if primary_project and not any(int(item.get("id") or 0) == int(primary_project["id"]) for item in projects):
        primary_payload = _project_payload(primary_project)
        if can_access_project(actor, primary_payload):
            projects.insert(0, primary_payload)
    project_ids = {int(item.get("id") or 0) for item in projects}

    finance = [row for row in _load_finance_rows() if _safe_int(row.get("contract_id")) == contract_id or _safe_int(row.get("project_id")) in project_ids]
    purchases = [row for row in _load_purchase_rows() if _safe_int(row.get("contract_id")) == contract_id or _safe_int(row.get("project_id")) in project_ids]
    sales = [row for row in _load_sales_rows() if _safe_int(row.get("contract_id")) == contract_id or _safe_int(row.get("project_id")) in project_ids]
    production = [row for row in _load_production_rows() if _safe_int(row.get("contract_id")) == contract_id or _safe_int(row.get("project_id")) in project_ids]
    expenses = [row for row in _load_expense_request_rows() if _safe_int(row.get("contract_id")) == contract_id or _safe_int(row.get("project_id")) in project_ids]
    requests_rows = [row for row in _load_internal_request_rows() if _safe_int(row.get("contract_id")) == contract_id or _safe_int(row.get("project_id")) in project_ids]
    resources = [row for row in _load_resource_allocations() if _safe_int(row.get("contract_id")) == contract_id or _safe_int(row.get("project_id")) in project_ids]
    service_cases = [row for row in _load_service_cases() if _safe_int(row.get("contract_id")) == contract_id or _safe_int(row.get("project_id")) in project_ids]
    erp_processes = [row for row in list_erp_process_runs(limit=300) if _safe_int(row.get("contract_id")) == contract_id or _safe_int(row.get("project_id")) in project_ids]
    erp_processes = [row for row in _enrich_process_rows(erp_processes) if _can_access_process(actor, row)]

    c.execute("SELECT * FROM documents WHERE contract_id=? ORDER BY id DESC", (contract_id,))
    documents = [dict(row) for row in c.fetchall()]
    if project_ids:
        placeholders = ",".join("?" for _ in project_ids)
        c.execute(f"SELECT * FROM documents WHERE project_id IN ({placeholders}) ORDER BY id DESC", tuple(project_ids))
        seen = {int(item.get("id") or 0) for item in documents}
        for row in c.fetchall():
            item = dict(row)
            if int(item.get("id") or 0) not in seen:
                documents.append(item)

    tasks = []
    claims_rows = []
    court_rows = []
    if project_ids:
        placeholders = ",".join("?" for _ in project_ids)
        c.execute(f"SELECT * FROM tasks WHERE project_id IN ({placeholders}) ORDER BY id DESC", tuple(project_ids))
        tasks = [dict(row) for row in c.fetchall()]
        c.execute(f"SELECT * FROM claims WHERE proj_id IN ({placeholders}) ORDER BY id DESC", tuple(project_ids))
        claims_rows = [dict(row) for row in c.fetchall()]
        c.execute(f"SELECT * FROM court_cases WHERE proj_id IN ({placeholders}) ORDER BY id DESC", tuple(project_ids))
        court_rows = [dict(row) for row in c.fetchall()]

    users = {item.get("name", ""): item for item in _load_users_directory()}
    employee_names = []
    for project in projects:
        if project.get("manager"):
            employee_names.append(project["manager"])
        employee_names.extend(project.get("team") or [])
    for row in resources:
        if row.get("resource_name"):
            employee_names.append(row["resource_name"])
    for row in service_cases:
        if row.get("responsible"):
            employee_names.append(row["responsible"])
    if contract.get("manager_name"):
        employee_names.append(contract["manager_name"])
    employees = []
    for name in sorted({_normalize_spaces(name) for name in employee_names if _normalize_spaces(name)}):
        user = users.get(name, {})
        related_load = sum(_safe_int(item.get("load_percent")) for item in resources if _normalize_spaces(item.get("resource_name")) == name)
        employees.append({
            "name": name,
            "email": user.get("email", ""),
            "role": user.get("role", ""),
            "is_head": _safe_int(user.get("is_head")),
            "load_percent": related_load,
            "from_resources": related_load > 0,
        })

    audit_rows = []
    for row in get_audit_logs(limit=250):
        if row.get("entity_type") in {"contract_master", "business_object"} and (
            row.get("entity_id") == str(contract_id) or row.get("entity_id") == str(_safe_int(contract.get("object_id")))
        ):
            audit_rows.append(row)
        elif row.get("entity_type") == "project" and row.get("entity_id") in {str(item.get("id")) for item in projects}:
            audit_rows.append(row)

    timeline = []
    for item in projects[:5]:
        timeline.append({"title": item.get("name", "Проект"), "meta": f"Проект · {item.get('status', '—')}", "time": ""})
    for item in documents[:5]:
        timeline.append({"title": item.get("subject", "Документ"), "meta": f"{item.get('type', 'Документ')} · {item.get('number', '—')}", "time": item.get("d_date", "")})
    for item in finance[:5]:
        timeline.append({"title": item.get("title", "Финансовая операция"), "meta": f"{'Входящий' if item.get('kind') == 'incoming' else 'Исходящий'} · {item.get('status') or 'planned'} · {int(_safe_float(item.get('amount'))):,} ₽".replace(",", " "), "time": item.get("due_date") or item.get("paid_date") or ""})
    for item in erp_processes[:5]:
        timeline.append({"title": item.get("title", "ERP процесс"), "meta": f"ERP · {_erp_stage_label(item.get('current_stage', ''))}", "time": item.get("due_date", "")})

    conn.close()
    receivable_open = round(sum(_safe_float(item.get("amount")) for item in finance if item.get("kind") == "incoming" and item.get("status") != "paid"), 2)
    payable_open = round(sum(_safe_float(item.get("amount")) for item in finance if item.get("kind") == "outgoing" and item.get("status") != "paid"), 2)
    revenue_total = round(sum(_safe_float(item.get("amount")) for item in sales), 2)
    purchase_total = round(sum(_safe_float(item.get("total_amount")) for item in purchases), 2)
    return {
        "contract": contract,
        "client": {"id": _safe_int(contract.get("client_id")), "name": contract.get("client_name", ""), "inn": contract.get("client_inn", ""), "contact": contract.get("client_contact", "")},
        "object": {
            "id": _safe_int(contract.get("object_id")),
            "name": contract.get("object_name", ""),
            "address": contract.get("object_address", ""),
            "city": contract.get("object_city", ""),
            "region": contract.get("object_region", ""),
            "responsible_name": contract.get("object_responsible_name", ""),
            "responsible_email": contract.get("object_responsible_email", ""),
        },
        "projects": projects,
        "employees": employees,
        "finance": finance[:20],
        "purchases": purchases[:20],
        "sales": sales[:20],
        "production": production[:20],
        "expenses": expenses[:20],
        "requests": requests_rows[:20],
        "resources": resources[:20],
        "service_cases": service_cases[:20],
        "documents": documents[:20],
        "tasks": tasks[:20],
        "claims": claims_rows[:20],
        "courts": court_rows[:20],
        "erp_processes": erp_processes[:20],
        "audit": audit_rows[:20],
        "timeline": timeline[:16],
        "metrics": {
            "projects_total": len(projects),
            "documents_total": len(documents),
            "tasks_total": len(tasks),
            "claims_total": len(claims_rows) + len(court_rows),
            "receivable_open": receivable_open,
            "payable_open": payable_open,
            "revenue_total": revenue_total,
            "purchase_total": purchase_total,
            "margin": round(revenue_total - purchase_total, 2),
            "employees_total": len(employees),
            "active_processes": len([row for row in erp_processes if row.get("status") != "done"]),
        },
    }


def _can_manage_calendar_event(actor: dict, row: dict) -> bool:
    if not actor:
        return False
    if actor.get("role") == "Директор":
        return True
    actor_email = _normalize_match(actor.get("email", ""))
    actor_name = _normalize_match(actor.get("name", ""))
    return actor_email in {
        _normalize_match(row.get("owner_email", "")),
        _normalize_match(row.get("created_by", "")),
    } or actor_name == _normalize_match(row.get("owner_name", ""))


def _load_calendar_events_for_actor(actor: dict) -> list[dict]:
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM calendar_events ORDER BY event_date ASC, start_time ASC, updated_at DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    if not actor:
        return []
    if actor.get("role") == "Директор":
        return rows
    actor_email = _normalize_match(actor.get("email", ""))
    actor_name = _normalize_match(actor.get("name", ""))
    actor_role = _normalize_match(actor.get("role", ""))
    visible = []
    for row in rows:
        scope = _normalize_match(row.get("scope", "personal"))
        if scope == "shared":
            visible.append(row)
            continue
        if scope == "department" and _normalize_match(row.get("department", "")) == actor_role:
            visible.append(row)
            continue
        if scope == "personal" and (
            _normalize_match(row.get("owner_email", "")) == actor_email
            or _normalize_match(row.get("owner_name", "")) == actor_name
        ):
            visible.append(row)
    return visible


def _load_crm_activities(entity_type: str = "", entity_id: int = 0) -> list[dict]:
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    if entity_type and entity_id:
        c.execute(
            "SELECT * FROM crm_activities WHERE entity_type=? AND entity_id=? ORDER BY status='done', due_date ASC, updated_at DESC",
            (_normalize_spaces(entity_type), _safe_int(entity_id)),
        )
    else:
        c.execute("SELECT * FROM crm_activities ORDER BY status='done', due_date ASC, updated_at DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def _decorate_crm_rows(rows: list[dict], entity_type: str) -> list[dict]:
    activity_rows = _load_crm_activities(entity_type)
    by_entity: dict[int, list[dict]] = {}
    for row in activity_rows:
        by_entity.setdefault(_safe_int(row.get("entity_id")), []).append(row)
    for row in rows:
        row["tags"] = _json_load(row.get("tags_json"), [])
        activities = by_entity.get(_safe_int(row.get("id")), [])
        row["activities"] = activities[:8]
        row["activity_open_count"] = len([item for item in activities if _normalize_match(item.get("status", "")) != "done"])
        row["activity_done_count"] = len([item for item in activities if _normalize_match(item.get("status", "")) == "done"])
    return rows


@router.get("/api/calendar/events")
def get_calendar_events(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "meetings", "read"):
        return {"error": "forbidden"}
    return _load_calendar_events_for_actor(actor)


@router.post("/api/calendar/events")
def create_calendar_event(data: CalendarEventData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "meetings", "create"):
        return {"error": "forbidden"}
    now = int(time.time())
    scope = _normalize_spaces(data.scope) or "personal"
    owner_email = _normalize_spaces(data.owner_email) or actor.get("email", "")
    owner_name = _normalize_spaces(data.owner_name) or actor.get("name", "")
    department = _normalize_spaces(data.department)
    if scope == "department" and not department:
        department = actor.get("role", "")
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO calendar_events (
            title, event_date, start_time, end_time, scope, owner_email, owner_name, department,
            project_id, meeting_id, status, location, description, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _normalize_spaces(data.title),
            _normalize_spaces(data.event_date),
            _normalize_spaces(data.start_time),
            _normalize_spaces(data.end_time),
            scope,
            owner_email,
            owner_name,
            department,
            _safe_int(data.project_id),
            _safe_int(data.meeting_id),
            _normalize_spaces(data.status) or "planned",
            _normalize_spaces(data.location),
            _normalize_spaces(data.description),
            actor.get("email", ""),
            now,
            now,
        ),
    )
    event_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("calendar_event_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="calendar_event", entity_id=str(event_id), details={"title": data.title, "scope": scope})
    return {"status": "success", "id": event_id}


@router.put("/api/calendar/events/{event_id}")
def update_calendar_event(event_id: int, data: CalendarEventData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "meetings", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM calendar_events WHERE id=?", (_safe_int(event_id),))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    row = dict(row)
    if not _can_manage_calendar_event(actor, row):
        conn.close()
        return {"error": "forbidden"}
    now = int(time.time())
    scope = _normalize_spaces(data.scope) or row.get("scope", "personal")
    owner_email = _normalize_spaces(data.owner_email) or row.get("owner_email", "") or actor.get("email", "")
    owner_name = _normalize_spaces(data.owner_name) or row.get("owner_name", "") or actor.get("name", "")
    department = _normalize_spaces(data.department) or (actor.get("role", "") if scope == "department" else row.get("department", ""))
    c.execute(
        """
        UPDATE calendar_events
        SET title=?, event_date=?, start_time=?, end_time=?, scope=?, owner_email=?, owner_name=?, department=?,
            project_id=?, meeting_id=?, status=?, location=?, description=?, updated_at=?
        WHERE id=?
        """,
        (
            _normalize_spaces(data.title),
            _normalize_spaces(data.event_date),
            _normalize_spaces(data.start_time),
            _normalize_spaces(data.end_time),
            scope,
            owner_email,
            owner_name,
            department,
            _safe_int(data.project_id),
            _safe_int(data.meeting_id),
            _normalize_spaces(data.status) or "planned",
            _normalize_spaces(data.location),
            _normalize_spaces(data.description),
            now,
            _safe_int(event_id),
        ),
    )
    conn.commit()
    conn.close()
    audit_log("calendar_event_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="calendar_event", entity_id=str(event_id), details={"title": data.title, "scope": scope})
    return {"status": "success"}


@router.delete("/api/calendar/events/{event_id}")
def delete_calendar_event(event_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "meetings", "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM calendar_events WHERE id=?", (_safe_int(event_id),))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    row = dict(row)
    if not _can_manage_calendar_event(actor, row):
        conn.close()
        return {"error": "forbidden"}
    c.execute("DELETE FROM calendar_events WHERE id=?", (_safe_int(event_id),))
    conn.commit()
    conn.close()
    audit_log("calendar_event_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="calendar_event", entity_id=str(event_id), details={"title": row.get("title", "")})
    return {"status": "success"}


@router.get("/api/crm/leads")
def get_crm_leads(request: Request, search: str = "", stage: str = "", responsible: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "clients", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM crm_leads ORDER BY updated_at DESC, id DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    visible = []
    search_normalized = _normalize_match(search)
    for row in rows:
        if stage and _normalize_match(row.get("stage", "")) != _normalize_match(stage):
            continue
        if responsible and _normalize_match(row.get("responsible", "")) != _normalize_match(responsible):
            continue
        if search_normalized:
            haystack = " ".join([row.get("title", ""), row.get("client_name", ""), row.get("contact_name", ""), row.get("source", ""), row.get("next_action", "")])
            if search_normalized not in _normalize_match(haystack):
                continue
        visible.append(row)
    return _decorate_crm_rows(visible, "lead")


@router.post("/api/crm/leads")
def create_crm_lead(data: CRMLeadData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "clients", "create"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO crm_leads (
            title, client_name, contact_name, contact_email, contact_phone, source, stage, probability, budget, currency,
            responsible, next_action, next_action_date, priority, tags_json, comment, linked_client_id, linked_project_id, linked_deal_id, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _normalize_spaces(data.title),
            _normalize_spaces(data.client_name),
            _normalize_spaces(data.contact_name),
            _normalize_spaces(data.contact_email),
            _normalize_spaces(data.contact_phone),
            _normalize_spaces(data.source),
            _normalize_spaces(data.stage) or "new",
            _safe_float(data.probability),
            _safe_float(data.budget),
            _normalize_spaces(data.currency) or "RUB",
            _normalize_spaces(data.responsible) or actor.get("name", ""),
            _normalize_spaces(data.next_action),
            _normalize_spaces(data.next_action_date),
            _normalize_spaces(data.priority) or "normal",
            json.dumps(data.tags or [], ensure_ascii=False),
            _normalize_spaces(data.comment),
            _safe_int(data.linked_client_id),
            _safe_int(data.linked_project_id),
            _safe_int(data.linked_deal_id),
            actor.get("email", ""),
            now,
            now,
        ),
    )
    lead_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("crm_lead_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="crm_lead", entity_id=str(lead_id), details={"title": data.title, "stage": data.stage})
    return {"status": "success", "id": lead_id}


@router.put("/api/crm/leads/{lead_id}")
def update_crm_lead(lead_id: int, data: CRMLeadData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "clients", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE crm_leads
        SET title=?, client_name=?, contact_name=?, contact_email=?, contact_phone=?, source=?, stage=?, probability=?, budget=?, currency=?,
            responsible=?, next_action=?, next_action_date=?, priority=?, tags_json=?, comment=?, linked_client_id=?, linked_project_id=?, linked_deal_id=?, updated_at=?
        WHERE id=?
        """,
        (
            _normalize_spaces(data.title),
            _normalize_spaces(data.client_name),
            _normalize_spaces(data.contact_name),
            _normalize_spaces(data.contact_email),
            _normalize_spaces(data.contact_phone),
            _normalize_spaces(data.source),
            _normalize_spaces(data.stage) or "new",
            _safe_float(data.probability),
            _safe_float(data.budget),
            _normalize_spaces(data.currency) or "RUB",
            _normalize_spaces(data.responsible),
            _normalize_spaces(data.next_action),
            _normalize_spaces(data.next_action_date),
            _normalize_spaces(data.priority) or "normal",
            json.dumps(data.tags or [], ensure_ascii=False),
            _normalize_spaces(data.comment),
            _safe_int(data.linked_client_id),
            _safe_int(data.linked_project_id),
            _safe_int(data.linked_deal_id),
            now,
            _safe_int(lead_id),
        ),
    )
    conn.commit()
    conn.close()
    audit_log("crm_lead_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="crm_lead", entity_id=str(lead_id), details={"title": data.title, "stage": data.stage})
    return {"status": "success"}


@router.post("/api/crm/leads/{lead_id}/convert")
def convert_lead_to_deal(lead_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "create"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM crm_leads WHERE id=?", (_safe_int(lead_id),))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    lead = dict(row)
    if _safe_int(lead.get("linked_deal_id")):
        conn.close()
        return {"status": "success", "deal_id": _safe_int(lead.get("linked_deal_id"))}
    now = int(time.time())
    c.execute(
        """
        INSERT INTO crm_deals (
            lead_id, title, client_id, client_name, contract_number, stage, amount, currency, margin_percent, probability,
            responsible, next_action, next_action_date, expected_close_date, priority, status_color, tags_json, comment, project_id, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _safe_int(lead_id),
            _normalize_spaces(lead.get("title", "")) or f"Сделка по лиду #{lead_id}",
            _safe_int(lead.get("linked_client_id")),
            _normalize_spaces(lead.get("client_name", "")),
            "",
            "qualification",
            _safe_float(lead.get("budget")),
            _normalize_spaces(lead.get("currency", "")) or "RUB",
            0,
            _safe_float(lead.get("probability")),
            _normalize_spaces(lead.get("responsible", "")),
            _normalize_spaces(lead.get("next_action", "")),
            _normalize_spaces(lead.get("next_action_date", "")),
            _normalize_spaces(lead.get("next_action_date", "")),
            _normalize_spaces(lead.get("priority", "")) or "normal",
            "accent",
            lead.get("tags_json") or "[]",
            _normalize_spaces(lead.get("comment", "")),
            _safe_int(lead.get("linked_project_id")),
            actor.get("email", ""),
            now,
            now,
        ),
    )
    deal_id = c.lastrowid
    c.execute("UPDATE crm_leads SET stage='won', linked_deal_id=?, updated_at=? WHERE id=?", (_safe_int(deal_id), now, _safe_int(lead_id)))
    conn.commit()
    conn.close()
    audit_log("crm_lead_converted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="crm_lead", entity_id=str(lead_id), details={"deal_id": deal_id})
    return {"status": "success", "deal_id": deal_id}


@router.get("/api/crm/deals")
def get_crm_deals(request: Request, search: str = "", stage: str = "", responsible: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM crm_deals ORDER BY updated_at DESC, id DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    visible = []
    search_normalized = _normalize_match(search)
    for row in rows:
        if stage and _normalize_match(row.get("stage", "")) != _normalize_match(stage):
            continue
        if responsible and _normalize_match(row.get("responsible", "")) != _normalize_match(responsible):
            continue
        if search_normalized:
            haystack = " ".join([row.get("title", ""), row.get("client_name", ""), row.get("contract_number", ""), row.get("next_action", "")])
            if search_normalized not in _normalize_match(haystack):
                continue
        visible.append(row)
    return _decorate_crm_rows(visible, "deal")


@router.post("/api/crm/deals")
def create_crm_deal(data: CRMDealData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "create"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO crm_deals (
            lead_id, title, client_id, client_name, contract_number, stage, amount, currency, margin_percent, probability,
            responsible, next_action, next_action_date, expected_close_date, priority, status_color, tags_json, comment, project_id, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _safe_int(data.lead_id),
            _normalize_spaces(data.title),
            _safe_int(data.client_id),
            _normalize_spaces(data.client_name),
            _normalize_spaces(data.contract_number),
            _normalize_spaces(data.stage) or "qualification",
            _safe_float(data.amount),
            _normalize_spaces(data.currency) or "RUB",
            _safe_float(data.margin_percent),
            _safe_float(data.probability),
            _normalize_spaces(data.responsible) or actor.get("name", ""),
            _normalize_spaces(data.next_action),
            _normalize_spaces(data.next_action_date),
            _normalize_spaces(data.expected_close_date),
            _normalize_spaces(data.priority) or "normal",
            _normalize_spaces(data.status_color),
            json.dumps(data.tags or [], ensure_ascii=False),
            _normalize_spaces(data.comment),
            _safe_int(data.project_id),
            actor.get("email", ""),
            now,
            now,
        ),
    )
    deal_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("crm_deal_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="crm_deal", entity_id=str(deal_id), details={"title": data.title, "stage": data.stage})
    return {"status": "success", "id": deal_id}


@router.put("/api/crm/deals/{deal_id}")
def update_crm_deal(deal_id: int, data: CRMDealData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE crm_deals
        SET lead_id=?, title=?, client_id=?, client_name=?, contract_number=?, stage=?, amount=?, currency=?, margin_percent=?, probability=?,
            responsible=?, next_action=?, next_action_date=?, expected_close_date=?, priority=?, status_color=?, tags_json=?, comment=?, project_id=?, updated_at=?
        WHERE id=?
        """,
        (
            _safe_int(data.lead_id),
            _normalize_spaces(data.title),
            _safe_int(data.client_id),
            _normalize_spaces(data.client_name),
            _normalize_spaces(data.contract_number),
            _normalize_spaces(data.stage) or "qualification",
            _safe_float(data.amount),
            _normalize_spaces(data.currency) or "RUB",
            _safe_float(data.margin_percent),
            _safe_float(data.probability),
            _normalize_spaces(data.responsible),
            _normalize_spaces(data.next_action),
            _normalize_spaces(data.next_action_date),
            _normalize_spaces(data.expected_close_date),
            _normalize_spaces(data.priority) or "normal",
            _normalize_spaces(data.status_color),
            json.dumps(data.tags or [], ensure_ascii=False),
            _normalize_spaces(data.comment),
            _safe_int(data.project_id),
            now,
            _safe_int(deal_id),
        ),
    )
    conn.commit()
    conn.close()
    audit_log("crm_deal_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="crm_deal", entity_id=str(deal_id), details={"title": data.title, "stage": data.stage})
    return {"status": "success"}


@router.get("/api/crm/activities")
def get_crm_activities(request: Request, entity_type: str = "", entity_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "clients", "read") or has_permission(actor, "projects", "read")):
        return {"error": "forbidden"}
    return _load_crm_activities(entity_type, entity_id)


@router.post("/api/crm/activities")
def create_crm_activity(data: CRMActivityData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "clients", "update") or has_permission(actor, "projects", "update")):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO crm_activities (
            entity_type, entity_id, activity_type, subject, summary, due_date, status, owner_name, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _normalize_spaces(data.entity_type) or "lead",
            _safe_int(data.entity_id),
            _normalize_spaces(data.activity_type) or "note",
            _normalize_spaces(data.subject),
            _normalize_spaces(data.summary),
            _normalize_spaces(data.due_date),
            _normalize_spaces(data.status) or "open",
            _normalize_spaces(data.owner_name) or actor.get("name", ""),
            actor.get("email", ""),
            now,
            now,
        ),
    )
    activity_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("crm_activity_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="crm_activity", entity_id=str(activity_id), details={"entity_type": data.entity_type, "entity_id": data.entity_id, "subject": data.subject})
    return {"status": "success", "id": activity_id}


@router.put("/api/crm/activities/{activity_id}")
def update_crm_activity(activity_id: int, data: CRMActivityData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "clients", "update") or has_permission(actor, "projects", "update")):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE crm_activities
        SET entity_type=?, entity_id=?, activity_type=?, subject=?, summary=?, due_date=?, status=?, owner_name=?, updated_at=?
        WHERE id=?
        """,
        (
            _normalize_spaces(data.entity_type) or "lead",
            _safe_int(data.entity_id),
            _normalize_spaces(data.activity_type) or "note",
            _normalize_spaces(data.subject),
            _normalize_spaces(data.summary),
            _normalize_spaces(data.due_date),
            _normalize_spaces(data.status) or "open",
            _normalize_spaces(data.owner_name),
            now,
            _safe_int(activity_id),
        ),
    )
    conn.commit()
    conn.close()
    audit_log("crm_activity_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="crm_activity", entity_id=str(activity_id), details={"subject": data.subject, "status": data.status})
    return {"status": "success"}


@router.get("/api/finance/summary")
def get_finance_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    rows = _filter_finance_rows_for_actor(actor, _load_finance_rows())
    return _finance_dashboard_payload(rows)


def _get_finance_payment_row(payment_id: int) -> dict | None:
    rows = [row for row in _load_finance_rows() if _safe_int(row.get("id")) == _safe_int(payment_id)]
    return rows[0] if rows else None


def _get_finance_payment_row_from_conn(conn, payment_id: int) -> dict | None:
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute(
        """
        SELECT
            fp.*,
            COALESCE(p.name, '') AS project_name,
            COALESCE(p.contract, '') AS project_contract,
            COALESCE(cl.name, '') AS client_name,
            COALESCE(le.short_name, le.name, '') AS legal_entity_name,
            COALESCE(bu.name, '') AS business_unit_name,
            COALESCE(ta.name, '') AS treasury_article_name,
            COALESCE(vr.name, '') AS vat_rate_name,
            COALESCE(vr.rate, 0) AS vat_rate_value
        FROM finance_payments fp
        LEFT JOIN projects p ON p.id = fp.project_id
        LEFT JOIN clients cl ON cl.id = fp.client_id
        LEFT JOIN legal_entities le ON le.id = fp.legal_entity_id
        LEFT JOIN business_units bu ON bu.id = fp.business_unit_id
        LEFT JOIN treasury_articles ta ON ta.id = fp.treasury_article_id
        LEFT JOIN vat_rates vr ON vr.id = fp.vat_rate_id
        WHERE fp.id=?
        """,
        (payment_id,),
    )
    row = c.fetchone()
    return dict(row) if row else None


@router.get("/api/finance/master_data")
def get_finance_master_data(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _finance_master_data_for_actor(actor)


def _finance_master_config(entity_type: str) -> dict | None:
    mapping = {
        "legal_entities": {
            "table": "legal_entities",
            "label": "legal_entity",
            "fields": ["name", "short_name", "inn", "kpp", "ogrn", "vat_mode", "default_currency", "is_active", "updated_at"],
            "payload": lambda data: (
                (data.name or "").strip(),
                (data.short_name or "").strip(),
                (data.inn or "").strip(),
                (data.kpp or "").strip(),
                (data.ogrn or "").strip(),
                (data.vat_mode or "osno").strip() or "osno",
                (data.default_currency or "RUB").strip() or "RUB",
                1 if int(data.is_active or 0) else 0,
                int(time.time()),
            ),
        },
        "business_units": {
            "table": "business_units",
            "label": "business_unit",
            "fields": ["legal_entity_id", "name", "code", "manager_name", "is_active", "updated_at"],
            "payload": lambda data: (
                int(data.legal_entity_id or 0),
                (data.name or "").strip(),
                (data.code or "").strip(),
                (data.manager_name or "").strip(),
                1 if int(data.is_active or 0) else 0,
                int(time.time()),
            ),
        },
        "treasury_articles": {
            "table": "treasury_articles",
            "label": "treasury_article",
            "fields": ["name", "code", "flow_kind", "category", "is_active", "updated_at"],
            "payload": lambda data: (
                (data.name or "").strip(),
                (data.code or "").strip(),
                (data.flow_kind or "incoming").strip() or "incoming",
                (data.category or "").strip(),
                1 if int(data.is_active or 0) else 0,
                int(time.time()),
            ),
        },
        "vat_rates": {
            "table": "vat_rates",
            "label": "vat_rate",
            "fields": ["name", "rate", "is_default", "is_active"],
            "payload": lambda data: (
                (data.name or "").strip(),
                round(_safe_float(data.rate), 2),
                1 if int(data.is_default or 0) else 0,
                1 if int(data.is_active or 0) else 0,
            ),
        },
    }
    return mapping.get(entity_type)


def _validate_finance_master_record(entity_type: str, data: FinanceMasterRecordData) -> str | None:
    if entity_type == "legal_entities":
        if not (data.name or "").strip():
            return "name_required"
    elif entity_type == "business_units":
        if not int(data.legal_entity_id or 0):
            return "legal_entity_required"
        if not (data.name or "").strip():
            return "name_required"
    elif entity_type == "treasury_articles":
        if not (data.name or "").strip():
            return "name_required"
        if (data.flow_kind or "").strip() not in {"incoming", "outgoing"}:
            return "flow_kind_invalid"
    elif entity_type == "vat_rates":
        if not (data.name or "").strip():
            return "name_required"
    return None


def _save_finance_master_record(entity_type: str, item_id: int, data: FinanceMasterRecordData, actor: dict):
    config = _finance_master_config(entity_type)
    if not config:
        return {"error": "unsupported_entity"}
    validation_error = _validate_finance_master_record(entity_type, data)
    if validation_error:
        return {"error": validation_error}
    conn = get_connection()
    c = conn.cursor()
    if entity_type == "vat_rates" and int(data.is_default or 0):
        c.execute("UPDATE vat_rates SET is_default=0")
    if item_id:
        placeholders = ", ".join(f"{field}=?" for field in config["fields"])
        c.execute(f"UPDATE {config['table']} SET {placeholders} WHERE id=?", (*config["payload"](data), item_id))
        record_id = item_id
        action = "updated"
    else:
        insert_fields = [field for field in config["fields"] if field != "updated_at"]
        values = list(config["payload"](data))
        if "updated_at" in config["fields"]:
            values = values[:-1]
        if entity_type in {"legal_entities", "business_units", "treasury_articles"}:
            insert_fields.append("created_at")
            values.append(int(time.time()))
        c.execute(
            f"INSERT INTO {config['table']} ({', '.join(insert_fields)}) VALUES ({', '.join(['?'] * len(insert_fields))})",
            tuple(values),
        )
        record_id = c.lastrowid
        action = "created"
    conn.commit()
    conn.close()
    audit_log(
        f"{config['label']}_{action}",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type=config["label"],
        entity_id=str(record_id),
        details={"name": data.name or data.short_name or config["label"]},
    )
    return {"status": "success", "id": record_id}


@router.post("/api/finance/master_data/{entity_type}")
def create_finance_master_record(entity_type: str, data: FinanceMasterRecordData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "manage_master"):
        return {"error": "forbidden"}
    return _save_finance_master_record(entity_type, 0, data, actor)


@router.put("/api/finance/master_data/{entity_type}/{item_id}")
def update_finance_master_record(entity_type: str, item_id: int, data: FinanceMasterRecordData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "manage_master"):
        return {"error": "forbidden"}
    return _save_finance_master_record(entity_type, item_id, data, actor)


@router.delete("/api/finance/master_data/{entity_type}/{item_id}")
def archive_finance_master_record(entity_type: str, item_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "manage_master"):
        return {"error": "forbidden"}
    config = _finance_master_config(entity_type)
    if not config:
        return {"error": "unsupported_entity"}
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"UPDATE {config['table']} SET is_active=0 WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    audit_log(
        f"{config['label']}_archived",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type=config["label"],
        entity_id=str(item_id),
        details={},
    )
    return {"status": "success", "id": item_id}


@router.get("/api/finance/erp_summary")
def get_finance_erp_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    rows = _filter_finance_rows_for_actor(actor, _load_finance_rows())
    return _finance_erp_summary(rows)


@router.get("/api/finance/analytics")
def get_finance_analytics(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    rows = _filter_finance_rows_for_actor(actor, _load_finance_rows())
    return _finance_analytics(rows)


@router.get("/api/finance/journal")
def get_finance_journal(request: Request, limit: int = 120):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _filter_finance_rows_for_actor(actor, _load_accounting_entries(limit))


@router.get("/api/finance/periods")
def get_finance_periods(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_accounting_periods()


@router.post("/api/finance/periods/close")
def close_finance_period(data: FinancePeriodCloseData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "close_period"):
        return {"error": "forbidden"}
    period_key = (data.period_key or "").strip() or _period_key_for_date("")
    conn = get_connection(row_factory=True)
    try:
        result = run_accounting_close_cycle(
            conn,
            actor=actor,
            period_key=period_key,
            comment=data.comment or "",
        )
        conn.commit()
    finally:
        conn.close()
    audit_log(
        "accounting_period_closed",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="accounting_period",
        entity_id=period_key,
        details={
            "comment": data.comment or "",
            "close_run_id": result.get("close_run_id", 0),
            "already_closed": bool(result.get("already_closed")),
            "warnings": result.get("warnings", []),
        },
    )
    return result


@router.get("/api/finance/treasury_limits")
def get_treasury_limits(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _filter_finance_rows_for_actor(actor, _load_treasury_limits())


@router.post("/api/finance/treasury_limits")
def save_treasury_limit(data: TreasuryLimitData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "manage_limits"):
        return {"error": "forbidden"}
    if not _assert_finance_scope(actor, data.legal_entity_id, data.business_unit_id):
        return {"error": "forbidden_scope"}
    period_key = (data.period_key or "").strip() or _period_key_for_date("")
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        INSERT INTO treasury_limits (
            period_key, legal_entity_id, business_unit_id, treasury_article_id, amount_limit,
            status, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(period_key, legal_entity_id, business_unit_id, treasury_article_id)
        DO UPDATE SET amount_limit=excluded.amount_limit, status=excluded.status, updated_at=excluded.updated_at
        """,
        (
            period_key,
            _safe_int(data.legal_entity_id),
            _safe_int(data.business_unit_id),
            _safe_int(data.treasury_article_id),
            _safe_float(data.amount_limit),
            data.status or "active",
            actor.get("email", ""),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    audit_log(
        "treasury_limit_saved",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="treasury_limit",
        entity_id=period_key,
        details={
            "legal_entity_id": data.legal_entity_id,
            "business_unit_id": data.business_unit_id,
            "treasury_article_id": data.treasury_article_id,
            "amount_limit": data.amount_limit,
            "status": data.status,
        },
    )
    return {"status": "success", "period_key": period_key}


@router.get("/api/finance/reconciliation_acts")
def get_reconciliation_acts(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_reconciliation_acts()


@router.post("/api/finance/reconciliation_acts")
def create_reconciliation_act(data: ReconciliationActData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "reconcile"):
        return {"error": "forbidden"}
    period_key = (data.period_key or "").strip() or _period_key_for_date("")
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    act_number = (data.act_number or "").strip() or f"SVR-{period_key}-{now}"
    c.execute(
        """
        INSERT INTO reconciliation_acts (
            client_id, contract_id, period_key, act_number, amount_receivable, amount_payable,
            details, status, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _safe_int(data.client_id),
            _safe_int(data.contract_id),
            period_key,
            act_number,
            _safe_float(data.amount_receivable),
            _safe_float(data.amount_payable),
            json.dumps(data.details or {}, ensure_ascii=False),
            data.status or "draft",
            actor.get("email", ""),
            now,
        ),
    )
    act_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log(
        "reconciliation_act_created",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="reconciliation_act",
        entity_id=str(act_id),
        details={"period_key": period_key, "client_id": data.client_id, "contract_id": data.contract_id},
    )
    return {"status": "success", "id": act_id, "act_number": act_number}


@router.get("/api/finance/sync_queue")
def get_finance_sync_queue(request: Request, limit: int = 120):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_sync_queue_rows(limit)


@router.get("/api/finance/sync_conflicts")
def get_finance_sync_conflicts(request: Request, limit: int = 120):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_sync_conflict_rows(limit)


@router.post("/api/finance/sync_queue/inbound/preview")
def preview_finance_inbound_sync(data: FinanceInboundSyncData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    if len(data.items or []) > 500:
        return {"status": "validation_failed", "error": "too_many_items", "message": "В одном пакете можно проверить до 500 строк."}
    return _preview_inbound_batch(data.items or [], "finance_payment")


@router.post("/api/finance/sync_queue/inbound")
def apply_finance_inbound_sync(data: FinanceInboundSyncData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    if len(data.items or []) > 500:
        return {"status": "validation_failed", "error": "too_many_items", "message": "В одном пакете можно применить до 500 строк."}
    normalized_items = _normalize_inbound_items(data.items or [], "finance_payment")
    validation_errors = [
        {"index": idx + 1, "errors": item.get("_validation_errors") or []}
        for idx, item in enumerate(normalized_items)
        if item.get("_validation_errors")
    ]
    if validation_errors:
        preview = _preview_inbound_batch(data.items or [], "finance_payment")
        return {"status": "validation_failed", "error": "validation_failed", "message": "Пакет не применён: сначала исправь ошибки структуры.", **preview}
    conn = get_connection()
    applied = 0
    conflicts = 0
    results = []
    batch_payload = {
        "items": [{key: value for key, value in item.items() if not key.startswith("_")} for item in normalized_items],
        "source_system": data.source_system or "1C",
        "actor_note": data.actor_note or "",
    }
    batch_key = _integration_idempotency_key(data.source_system or "1C", "finance_payment_batch", len(batch_payload["items"]), "inbound", batch_payload, data.idempotency_key)
    batch_hash = _payload_checksum(batch_payload)
    try:
        existing = _get_idempotency_record(conn, data.source_system or "1C", batch_key)
        if existing and existing.get("request_hash") == batch_hash and existing.get("status") in {"applied", "inbound_applied"}:
            if _integration_batch_state_already_applied(conn, batch_payload["items"]):
                cached = _json_load(existing.get("response_payload"), {})
                cached["idempotent"] = True
                return cached
        if existing and existing.get("request_hash") and existing.get("request_hash") != batch_hash:
            _record_integration_error_event(conn, _safe_int(existing.get("queue_id")), data.source_system or "1C", "finance_payment_batch", 0, "Повторный batch idempotency_key пришёл с другим payload", batch_payload, "critical", "idempotency_hash_mismatch")
            conn.commit()
            return {"status": "conflict", "error": "idempotency_hash_mismatch"}
        for payload in batch_payload["items"]:
            outcome = _apply_inbound_finance_sync_item(conn, payload, actor.get("email", ""), data.source_system or "1C")
            results.append(outcome)
            if outcome.get("state") == "applied":
                applied += 1
            else:
                conflicts += 1
        response = {"status": "success", "applied": applied, "conflicts": conflicts, "results": results[:50]}
        _upsert_idempotency_record(conn, data.source_system or "1C", batch_key, "inbound", 0, batch_hash, "applied", response)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit_log(
        "finance_inbound_sync_applied",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_sync_queue",
        entity_id="1C-INBOUND",
        details={"applied": applied, "conflicts": conflicts, "source_system": data.source_system, "note": data.actor_note},
    )
    return response


@router.post("/api/documents/1c/import/preview")
def preview_documents_1c_import(data: IntegrationSyncBatchData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", "create"):
        return {"error": "forbidden"}
    if len(data.items or []) > 500:
        return {"status": "validation_failed", "error": "too_many_items", "message": "В одном пакете можно проверить до 500 документов."}
    return _preview_document_import_batch(data.items or [])


@router.post("/api/documents/1c/import")
def apply_documents_1c_import(data: IntegrationSyncBatchData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "documents", "create") and has_permission(actor, "documents", "update")):
        return {"error": "forbidden"}
    if len(data.items or []) > 500:
        return {"status": "validation_failed", "error": "too_many_items", "message": "В одном пакете можно перенести до 500 документов."}
    normalized_items = _normalize_inbound_items(data.items or [], "document")
    validation_errors = [
        {"index": idx + 1, "errors": item.get("_validation_errors") or []}
        for idx, item in enumerate(normalized_items)
        if item.get("_validation_errors")
    ]
    if validation_errors:
        preview = _preview_document_import_batch(data.items or [])
        return {"status": "validation_failed", "error": "validation_failed", "message": "Документы не перенесены: сначала исправь ошибки структуры.", **preview}
    conn = get_connection(row_factory=True)
    applied = 0
    conflicts = 0
    created = 0
    updated = 0
    results = []
    try:
        for payload in normalized_items:
            outcome = _apply_inbound_document_sync_item(conn, payload, actor.get("email", ""), data.source_system or "1C")
            results.append(outcome)
            if outcome.get("state") == "applied":
                applied += 1
                if outcome.get("action") == "created":
                    created += 1
                if outcome.get("action") == "updated":
                    updated += 1
            else:
                conflicts += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit_log("documents_1c_import_applied", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="document_import", entity_id="1C", details={"applied": applied, "created": created, "updated": updated, "conflicts": conflicts, "note": data.actor_note})
    return {"status": "success", "applied": applied, "created": created, "updated": updated, "conflicts": conflicts, "results": results[:100]}


@router.get("/api/integration/1c/queue")
def get_global_sync_queue(request: Request, limit: int = 150):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "nsi", "read")):
        return {"error": "forbidden"}
    return _load_sync_queue_rows(limit)


@router.get("/api/integration/1c/monitoring")
def get_global_sync_monitoring(request: Request, limit: int = 150):
    actor = require_director(request)
    if not actor or not has_permission(actor, "executive", "read"):
        return {"error": "forbidden"}
    return _integration_monitoring_payload(limit)


@router.get("/api/integration/production/health")
def get_integration_production_health(request: Request, limit: int = 150):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    return {"status": "success", "quality": _integration_production_quality_payload(limit)}


@router.get("/api/integration/production/errors")
def get_integration_production_errors(request: Request, limit: int = 120, status: str = "open"):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        params = []
        query = "SELECT * FROM integration_error_events"
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        rows = [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]
    finally:
        conn.close()
    for row in rows:
        row["payload"] = _json_load(row.get("payload"), {})
    return {"status": "success", "errors": rows}


@router.post("/api/integration/production/errors/{error_id}/resolve")
def resolve_integration_production_error(error_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    conn = get_connection()
    now = int(time.time())
    try:
        conn.execute(
            "UPDATE integration_error_events SET status='resolved', resolved_at=?, resolved_by=? WHERE id=?",
            (now, actor.get("email", ""), _safe_int(error_id)),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("integration_error_resolved", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_error_event", entity_id=str(error_id), details={})
    return {"status": "success", "id": _safe_int(error_id), "resolved_at": now}


@router.get("/api/integration/production/idempotency")
def get_integration_idempotency_keys(request: Request, limit: int = 120):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM integration_idempotency_keys ORDER BY updated_at DESC, id DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        ]
    finally:
        conn.close()
    for row in rows:
        row["response_payload"] = _json_load(row.get("response_payload"), {})
    return {"status": "success", "items": rows}


@router.post("/api/integration/production/consistency/run")
def run_integration_production_consistency(request: Request, limit: int = 200):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    result = _run_integration_consistency_checks(actor, limit)
    audit_log("integration_consistency_run", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_consistency", entity_id="1C", details=result)
    return {"status": "success", **result}


@router.post("/api/integration/production/queue/{queue_id}/retry")
def retry_integration_production_queue(queue_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        row = dict(conn.execute("SELECT * FROM integration_sync_queue WHERE id=?", (_safe_int(queue_id),)).fetchone() or {})
        if not row:
            return {"error": "queue_not_found"}
        conn.execute(
            """
            UPDATE integration_sync_queue
            SET state='retry', last_error='', next_retry_at=?, locked_at=0,
                consistency_state='pending', updated_at=?
            WHERE id=?
            """,
            (now, now, _safe_int(queue_id)),
        )
        _log_sync_event(conn, _safe_int(queue_id), row.get("system_name") or "1C", row.get("entity_type") or "", _safe_int(row.get("entity_id")), "retry", "Оператор вернул обмен в retry", _json_load(row.get("payload"), {}))
        if row.get("idempotency_key"):
            _upsert_idempotency_record(conn, row.get("system_name") or "1C", row.get("idempotency_key"), row.get("direction") or "outbound", _safe_int(queue_id), row.get("checksum") or "", "retry", {"queue_id": _safe_int(queue_id)})
        conn.commit()
    finally:
        conn.close()
    audit_log("integration_queue_retry", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="integration_sync_queue", entity_id=str(queue_id), details={})
    return {"status": "success", "id": _safe_int(queue_id)}


@router.post("/api/integration/1c/inbound/preview")
def preview_integration_batch_sync(data: IntegrationSyncBatchData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    if len(data.items or []) > 500:
        return {"status": "validation_failed", "error": "too_many_items", "message": "В одном пакете можно проверить до 500 строк."}
    return _preview_inbound_batch(data.items or [], "")


@router.post("/api/integration/1c/inbound")
def apply_integration_batch_sync(data: IntegrationSyncBatchData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    if len(data.items or []) > 500:
        return {"status": "validation_failed", "error": "too_many_items", "message": "В одном пакете можно применить до 500 строк."}
    normalized_items = _normalize_inbound_items(data.items or [], "")
    validation_errors = [
        {"index": idx + 1, "errors": item.get("_validation_errors") or []}
        for idx, item in enumerate(normalized_items)
        if item.get("_validation_errors")
    ]
    if validation_errors:
        preview = _preview_inbound_batch(data.items or [], "")
        return {"status": "validation_failed", "error": "validation_failed", "message": "Пакет не применён: сначала исправь ошибки структуры.", **preview}
    conn = get_connection()
    applied = 0
    conflicts = 0
    results = []
    batch_payload = {
        "items": [{key: value for key, value in item.items() if not key.startswith("_")} for item in normalized_items],
        "source_system": data.source_system or "1C",
        "actor_note": data.actor_note or "",
    }
    batch_key = _integration_idempotency_key(data.source_system or "1C", "integration_batch", len(batch_payload["items"]), "inbound", batch_payload, data.idempotency_key)
    batch_hash = _payload_checksum(batch_payload)
    try:
        existing = _get_idempotency_record(conn, data.source_system or "1C", batch_key)
        if existing and existing.get("request_hash") == batch_hash and existing.get("status") in {"applied", "inbound_applied"}:
            if _integration_batch_state_already_applied(conn, batch_payload["items"]):
                cached = _json_load(existing.get("response_payload"), {})
                cached["idempotent"] = True
                return cached
        if existing and existing.get("request_hash") and existing.get("request_hash") != batch_hash:
            _record_integration_error_event(conn, _safe_int(existing.get("queue_id")), data.source_system or "1C", "integration_batch", 0, "Повторный batch idempotency_key пришёл с другим payload", batch_payload, "critical", "idempotency_hash_mismatch")
            conn.commit()
            return {"status": "conflict", "error": "idempotency_hash_mismatch"}
        for payload in batch_payload["items"]:
            entity_type = (payload.get("entity_type") or "").strip()
            if entity_type == "finance_payment":
                outcome = _apply_inbound_finance_sync_item(conn, payload, actor.get("email", ""), data.source_system or "1C")
            elif entity_type == "document":
                outcome = _apply_inbound_document_sync_item(conn, payload, actor.get("email", ""), data.source_system or "1C")
            else:
                outcome = _apply_generic_inbound_sync_item(conn, payload, actor.get("email", ""), data.source_system or "1C")
            results.append(outcome)
            if outcome.get("state") == "applied":
                applied += 1
            else:
                conflicts += 1
        response = {"status": "success", "applied": applied, "conflicts": conflicts, "results": results[:80]}
        _upsert_idempotency_record(conn, data.source_system or "1C", batch_key, "inbound", 0, batch_hash, "applied", response)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit_log(
        "integration_batch_sync_applied",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_sync_queue",
        entity_id="1C-BATCH",
        details={"applied": applied, "conflicts": conflicts, "source_system": data.source_system, "note": data.actor_note},
    )
    return response


@router.post("/api/integration/1c/process")
def process_global_sync_queue(request: Request, limit: int = 40):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    result = process_due_1c_sync_queue(limit)
    audit_log(
        "integration_sync_queue_processed",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_sync_queue",
        entity_id="1C-GLOBAL",
        details=result,
    )
    return {"status": "success", **result}


@router.post("/api/integration/1c/recover")
def recover_global_sync_queue(request: Request, force_failed: int = 0, stale_only: int = 1):
    actor = require_director(request)
    if not actor or not has_permission(actor, "executive", "read"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    stale_threshold = now - 900
    recovered = 0
    retried_failed = 0
    if stale_only:
        c.execute(
            """
            UPDATE integration_sync_queue
            SET state='retry', locked_at=0, last_error=CASE WHEN last_error='' THEN 'auto-recovered stale lock' ELSE last_error END, next_retry_at=?, updated_at=?
            WHERE system_name='1C' AND state='processing' AND locked_at>0 AND locked_at<?
            """,
            (now, now, stale_threshold),
        )
        recovered = c.rowcount or 0
    if force_failed:
        c.execute(
            """
            UPDATE integration_sync_queue
            SET state='retry', locked_at=0, next_retry_at=?, updated_at=?
            WHERE system_name='1C' AND state IN ('failed', 'conflict')
            """,
            (now, now),
        )
        retried_failed = c.rowcount or 0
    conn.commit()
    conn.close()
    result = {"status": "success", "recovered": recovered, "retried_failed": retried_failed}
    audit_log(
        "integration_sync_queue_recovered",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_sync_queue",
        entity_id="1C-RECOVERY",
        details=result,
    )
    return result


@router.post("/api/finance/sync_queue/process")
def process_finance_sync_queue(request: Request, limit: int = 20):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    result = process_due_1c_sync_queue(limit)
    audit_log(
        "finance_sync_queue_processed",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_sync_queue",
        entity_id="1C",
        details=result,
    )
    return {"status": "success", **result}


@router.post("/api/finance/sync_queue/{sync_id}/retry")
def retry_finance_sync(sync_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sync_1c"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        UPDATE integration_sync_queue
        SET state='retry', next_retry_at=?, locked_at=0, updated_at=?
        WHERE id=?
        """,
        (now, now, sync_id),
    )
    conn.commit()
    conn.close()
    audit_log(
        "finance_sync_retry_requested",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_sync_queue",
        entity_id=str(sync_id),
        details={},
    )
    return {"status": "success"}


@router.get("/api/finance/edo_signatures")
def get_finance_edo_signatures(request: Request, limit: int = 120):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_edo_signature_rows(limit)


@router.post("/api/finance/edo_signatures")
def create_edo_signature(data: EDOSignatureData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "sign_edo"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO edo_signature_registry (
            entity_type, entity_id, signer_name, signer_role, certificate_thumbprint,
            signature_provider, signature_status, signed_at, comment, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.entity_type or "finance_payment",
            _safe_int(data.entity_id),
            data.signer_name or actor.get("name", ""),
            data.signer_role or actor.get("role", ""),
            data.certificate_thumbprint or "",
            data.signature_provider or "1С-ЭДО",
            data.signature_status or "signed",
            data.signed_at or _today_display(),
            data.comment or "",
            actor.get("email", ""),
            int(time.time()),
        ),
    )
    signature_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log(
        "edo_signature_created",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type=data.entity_type or "finance_payment",
        entity_id=str(data.entity_id),
        details={"signature_id": signature_id, "signer_role": data.signer_role, "provider": data.signature_provider},
    )
    return {"status": "success", "id": signature_id}


@router.get("/api/finance/payments")
def get_finance_payments(request: Request, client_id: int = 0, project_id: int = 0, status: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    rows = _filter_finance_rows_for_actor(actor, _load_finance_rows())
    if client_id:
        rows = [row for row in rows if int(row.get("client_id") or 0) == client_id]
    if project_id:
        rows = [row for row in rows if int(row.get("project_id") or 0) == project_id]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    return rows


@router.post("/api/finance/payments")
def create_finance_payment(data: FinancePaymentData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "create"):
        return {"error": "forbidden"}
    permission_error = _enforce_field_permissions(
        actor,
        "finance",
        "finance_payment",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        {},
    )
    if permission_error:
        return permission_error
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    dims = _resolve_finance_dimensions(conn, data, context)
    if not _assert_finance_scope(actor, dims["legal_entity_id"], dims["business_unit_id"]):
        conn.close()
        return {"error": "forbidden_scope"}
    if data.kind == "outgoing":
        limit_check = _check_treasury_limit(conn, dims, data.amount, data.due_date or data.paid_date)
        if not limit_check["ok"]:
            conn.close()
            return {"error": f"Лимит по статье ДДС превышен. План: {limit_check['planned_total']}, лимит: {limit_check['amount_limit']}"}
    c.execute(
        """
        INSERT INTO finance_payments (
            project_id, client_id, contract_id, object_id, legal_entity_id, business_unit_id, treasury_article_id,
            vat_rate_id, source_document_type, source_document_id, title, kind, category, amount, currency, due_date,
            paid_date, status, comment, exchange_state, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dims["project_id"],
            dims["client_id"],
            dims["contract_id"],
            dims["object_id"],
            dims["legal_entity_id"],
            dims["business_unit_id"],
            dims["treasury_article_id"],
            dims["vat_rate_id"],
            dims["source_document_type"],
            dims["source_document_id"],
            data.title,
            data.kind,
            data.category,
            data.amount,
            data.currency,
            data.due_date,
            data.paid_date,
            data.status,
            data.comment,
            _payment_exchange_state(data.status),
            actor.get("email", ""),
            now,
            now,
        ),
    )
    payment_id = c.lastrowid
    payment = _get_finance_payment_row_from_conn(conn, payment_id)
    accounting_warning = ""
    if payment:
        try:
            _rebuild_finance_accounting_entries(conn, payment, actor.get("email", ""))
        except HTTPException as exc:
            if exc.status_code != 400 or "Период закрыт" not in str(exc.detail):
                conn.close()
                raise
            accounting_warning = str(exc.detail)
        _upsert_finance_sync_job(conn, payment, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("finance_payment_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="finance_payment", entity_id=str(payment_id), details={"title": data.title, "amount": data.amount, "kind": data.kind, "status": data.status, "legal_entity_id": dims["legal_entity_id"], "business_unit_id": dims["business_unit_id"], "treasury_article_id": dims["treasury_article_id"]})
    payload = {"status": "success", "id": payment_id}
    if accounting_warning:
        payload["warning"] = accounting_warning
    return payload


@router.put("/api/finance/payments/{payment_id}")
def update_finance_payment(payment_id: int, data: FinancePaymentData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "finance_payment", payment_id)
    if lock:
        return {"error": "locked", "lock": lock}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    dims = _resolve_finance_dimensions(conn, data, context)
    existing_payment = _get_finance_payment_row_from_conn(conn, payment_id)
    permission_error = _enforce_field_permissions(
        actor,
        "finance",
        "finance_payment",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        existing_payment or {},
    )
    if permission_error:
        conn.close()
        return permission_error
    if existing_payment and not _assert_finance_scope(actor, existing_payment.get("legal_entity_id"), existing_payment.get("business_unit_id")):
        conn.close()
        return {"error": "forbidden_scope"}
    if not _assert_finance_scope(actor, dims["legal_entity_id"], dims["business_unit_id"]):
        conn.close()
        return {"error": "forbidden_scope"}
    if data.kind == "outgoing":
        limit_check = _check_treasury_limit(conn, dims, data.amount, data.due_date or data.paid_date, payment_id)
        if not limit_check["ok"]:
            conn.close()
            return {"error": f"Лимит по статье ДДС превышен. План: {limit_check['planned_total']}, лимит: {limit_check['amount_limit']}"}
    c.execute(
        """
        UPDATE finance_payments
        SET project_id=?, client_id=?, contract_id=?, object_id=?, legal_entity_id=?, business_unit_id=?, treasury_article_id=?,
            vat_rate_id=?, source_document_type=?, source_document_id=?, title=?, kind=?, category=?, amount=?, currency=?, due_date=?,
            paid_date=?, status=?, comment=?, exchange_state=?, updated_at=?
        WHERE id=?
        """,
        (
            dims["project_id"],
            dims["client_id"],
            dims["contract_id"],
            dims["object_id"],
            dims["legal_entity_id"],
            dims["business_unit_id"],
            dims["treasury_article_id"],
            dims["vat_rate_id"],
            dims["source_document_type"],
            dims["source_document_id"],
            data.title,
            data.kind,
            data.category,
            data.amount,
            data.currency,
            data.due_date,
            data.paid_date,
            data.status,
            data.comment,
            _payment_exchange_state(data.status),
            now,
            payment_id,
        ),
    )
    payment = _get_finance_payment_row_from_conn(conn, payment_id)
    accounting_warning = ""
    if payment:
        try:
            _rebuild_finance_accounting_entries(conn, payment, actor.get("email", ""))
        except HTTPException as exc:
            if exc.status_code != 400 or "Период закрыт" not in str(exc.detail):
                conn.close()
                raise
            accounting_warning = str(exc.detail)
        _upsert_finance_sync_job(conn, payment, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("finance_payment_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="finance_payment", entity_id=str(payment_id), details={"title": data.title, "amount": data.amount, "kind": data.kind, "status": data.status, "legal_entity_id": dims["legal_entity_id"], "business_unit_id": dims["business_unit_id"], "treasury_article_id": dims["treasury_article_id"]})
    old_status = (existing_payment or {}).get("status", "")
    if old_status != data.status:
        notify_entity_watchers(
            "finance_payment",
            str(payment_id),
            "Платёж оплачен" if data.status == "paid" else "Статус платежа изменился",
            f"{data.title or f'Платёж #{payment_id}'}: {old_status or '—'} → {data.status or '—'}",
            event_key="paid" if data.status == "paid" else "status_changed",
            event_value=data.status,
            actor_email=actor.get("email", ""),
            actor_name=actor.get("name", ""),
            category="finance",
        )
    payload = {"status": "success"}
    if accounting_warning:
        payload["warning"] = accounting_warning
    return payload


@router.post("/api/finance/payments/{payment_id}/post")
def post_finance_payment(payment_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "post"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "finance_payment", payment_id)
    if lock:
        return {"error": "locked", "lock": lock}
    conn = get_connection()
    payment = _get_finance_payment_row_from_conn(conn, payment_id)
    if not payment:
        conn.close()
        return {"error": "not_found"}
    if not _assert_finance_scope(actor, payment.get("legal_entity_id"), payment.get("business_unit_id")):
        conn.close()
        return {"error": "forbidden_scope"}
    result = _rebuild_finance_accounting_entries(conn, payment, actor.get("email", ""))
    _upsert_finance_sync_job(conn, payment, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log(
        "finance_payment_posted",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="finance_payment",
        entity_id=str(payment_id),
        details=result,
    )
    return {"status": "success", **result}


@router.delete("/api/finance/payments/{payment_id}")
def delete_finance_payment(payment_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "delete"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "finance_payment", payment_id)
    if lock:
        return {"error": "locked", "lock": lock}
    conn = get_connection()
    payment = _get_finance_payment_row_from_conn(conn, payment_id)
    if payment and not _assert_finance_scope(actor, payment.get("legal_entity_id"), payment.get("business_unit_id")):
        conn.close()
        return {"error": "forbidden_scope"}
    c = conn.cursor()
    c.execute("DELETE FROM accounting_entries WHERE source_type='finance_payment' AND source_id=?", (payment_id,))
    c.execute("DELETE FROM integration_sync_log WHERE queue_id IN (SELECT id FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?)", (payment_id,))
    c.execute("DELETE FROM integration_sync_queue WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
    c.execute("DELETE FROM edo_signature_registry WHERE entity_type='finance_payment' AND entity_id=?", (payment_id,))
    c.execute("DELETE FROM finance_payments WHERE id=?", (payment_id,))
    conn.commit()
    conn.close()
    audit_log("finance_payment_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="finance_payment", entity_id=str(payment_id))
    return {"status": "success"}


@router.get("/api/supply/summary")
def get_supply_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "supply", "read"):
        return {"error": "forbidden"}
    purchases = _filter_scope_rows_for_actor(actor, _load_purchase_rows())
    reservations = _enrich_stock_reservation_rows(_filter_scope_rows_for_actor(actor, _load_stock_reservations()))
    lots = _load_inventory_lots()
    reserved_qty = round(sum(_safe_float(row.get("remaining_qty")) for row in reservations if row.get("status") in {"reserved", "partial"}), 2)
    total_stock_qty = round(sum(_safe_float(row.get("qty")) for row in lots), 2)
    return {
        "metrics": {
            "planned_purchases": round(sum(_safe_float(row.get("total_amount")) for row in purchases if row.get("status") in {"planned", "ordered"}), 2),
            "in_transit": round(sum(_safe_float(row.get("total_amount")) for row in purchases if row.get("status") == "in_transit"), 2),
            "received_total": round(sum(_safe_float(row.get("total_amount")) for row in purchases if row.get("status") == "received"), 2),
            "reserved_positions": len([row for row in reservations if row.get("status") == "reserved"]),
            "reserved_qty": reserved_qty,
            "free_stock_qty": round(total_stock_qty - reserved_qty, 2),
            "lot_positions": len([row for row in lots if _safe_float(row.get("qty")) > 0]),
            "shortages": len([row for row in reservations if row.get("status") == "shortage"]),
        },
        "recent_purchases": purchases[:10],
        "reservations": reservations[:10],
    }


@router.get("/api/purchases")
def get_purchases(request: Request, project_id: int = 0, client_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "supply", "read"):
        return {"error": "forbidden"}
    rows = _filter_scope_rows_for_actor(actor, _load_purchase_rows())
    if project_id:
        rows = [row for row in rows if int(row.get("project_id") or 0) == project_id]
    if client_id:
        rows = [row for row in rows if int(row.get("client_id") or 0) == client_id]
    for row in rows:
        if row.get("status") != "received" and _is_overdue("issued", row.get("expected_date", "")):
            title = row.get("item_name") or f"Закупка #{row.get('id')}"
            notify_entity_watchers(
                "purchase_order",
                str(row.get("id") or ""),
                "Поставка просрочилась",
                f"{title} должна была прийти {row.get('expected_date') or 'без даты'}.",
                event_key="overdue",
                event_value=row.get("expected_date") or "overdue",
                category="supply",
            )
    return rows


@router.post("/api/purchases")
def create_purchase(data: PurchaseOrderData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "supply", "create"):
        return {"error": "forbidden"}
    permission_error = _enforce_field_permissions(
        actor,
        "supply",
        "purchase_order",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        {},
    )
    if permission_error:
        return permission_error
    now = int(time.time())
    total_amount = round((_safe_float(data.qty) * _safe_float(data.unit_price)), 2)
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    scope = _resolve_ops_scope_dimensions(conn, data.legal_entity_id, data.business_unit_id)
    if not _assert_finance_scope(actor, scope["legal_entity_id"], scope["business_unit_id"]):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute(
        """
        INSERT INTO purchase_orders (
            project_id, client_id, contract_id, object_id, legal_entity_id, business_unit_id, item_article, item_name, supplier, supplier_id, qty, unit, unit_price, planned_unit_price,
            total_amount, status, expected_date, planned_delivery_date, received_date, delivered_qty, request_status, approval_status, schedule_status, lead_time_days, comment, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context["project_id"], context["client_id"], context["contract_id"], context["object_id"], scope["legal_entity_id"], scope["business_unit_id"], data.item_article, data.item_name, data.supplier, data.supplier_id, data.qty, data.unit,
            data.unit_price, getattr(data, "planned_unit_price", 0), total_amount, data.status, data.expected_date, getattr(data, "planned_delivery_date", data.expected_date), data.received_date, getattr(data, "delivered_qty", 0), getattr(data, "request_status", "draft"), getattr(data, "approval_status", "not_required"), getattr(data, "schedule_status", "planned"), getattr(data, "lead_time_days", 0), data.comment,
            actor.get("email", ""), now, now,
        ),
    )
    purchase_id = c.lastrowid
    linked_payment_id = _sync_purchase_finance_link(conn, purchase_id, actor.get("email", ""))
    _upsert_entity_sync_job(conn, "purchase_order", purchase_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("purchase_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="purchase", entity_id=str(purchase_id), details={"item": data.item_name, "supplier": data.supplier, "status": data.status, "linked_payment_id": linked_payment_id, "legal_entity_id": scope["legal_entity_id"], "business_unit_id": scope["business_unit_id"]})
    return {"status": "success", "id": purchase_id, "linked_payment_id": linked_payment_id}


@router.put("/api/purchases/{purchase_id}")
def update_purchase(purchase_id: int, data: PurchaseOrderData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "supply", "update"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "purchase_order", purchase_id)
    if lock:
        return {"error": "locked", "lock": lock}
    now = int(time.time())
    total_amount = round((_safe_float(data.qty) * _safe_float(data.unit_price)), 2)
    conn = get_connection()
    c = conn.cursor()
    existing_payload = {}
    c.execute("SELECT * FROM purchase_orders WHERE id=?", (purchase_id,))
    existing_row = c.fetchone()
    if existing_row:
        columns = [col[0] for col in c.description]
        existing_payload = dict(zip(columns, existing_row))
        permission_error = _enforce_field_permissions(
            actor,
            "supply",
            "purchase_order",
            data.model_dump() if hasattr(data, "model_dump") else data.dict(),
            existing_payload,
        )
        if permission_error:
            conn.close()
            return permission_error
    c.execute("SELECT legal_entity_id, business_unit_id FROM purchase_orders WHERE id=?", (purchase_id,))
    existing_scope = c.fetchone()
    if existing_scope and not _assert_finance_scope(actor, _safe_int(existing_scope[0]), _safe_int(existing_scope[1])):
        conn.close()
        return {"error": "forbidden_scope"}
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    scope = _resolve_ops_scope_dimensions(conn, data.legal_entity_id, data.business_unit_id)
    if not _assert_finance_scope(actor, scope["legal_entity_id"], scope["business_unit_id"]):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute(
        """
        UPDATE purchase_orders
        SET project_id=?, client_id=?, contract_id=?, object_id=?, legal_entity_id=?, business_unit_id=?, item_article=?, item_name=?, supplier=?, supplier_id=?, qty=?, unit=?, unit_price=?, planned_unit_price=?, total_amount=?,
            status=?, expected_date=?, planned_delivery_date=?, received_date=?, delivered_qty=?, request_status=?, approval_status=?, schedule_status=?, lead_time_days=?, comment=?, updated_at=?
        WHERE id=?
        """,
        (
            context["project_id"], context["client_id"], context["contract_id"], context["object_id"], scope["legal_entity_id"], scope["business_unit_id"], data.item_article, data.item_name, data.supplier, data.supplier_id, data.qty, data.unit,
            data.unit_price, getattr(data, "planned_unit_price", 0), total_amount, data.status, data.expected_date, getattr(data, "planned_delivery_date", data.expected_date), data.received_date, getattr(data, "delivered_qty", 0), getattr(data, "request_status", "draft"), getattr(data, "approval_status", "not_required"), getattr(data, "schedule_status", "planned"), getattr(data, "lead_time_days", 0), data.comment, now, purchase_id,
        ),
    )
    linked_payment_id = _sync_purchase_finance_link(conn, purchase_id, actor.get("email", ""))
    _upsert_entity_sync_job(conn, "purchase_order", purchase_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("purchase_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="purchase", entity_id=str(purchase_id), details={"item": data.item_name, "status": data.status, "linked_payment_id": linked_payment_id, "legal_entity_id": scope["legal_entity_id"], "business_unit_id": scope["business_unit_id"]})
    old_status = existing_payload.get("status", "")
    if old_status != data.status:
        notify_entity_watchers(
            "purchase_order",
            str(purchase_id),
            "Статус поставки изменился",
            f"{data.item_name or f'Закупка #{purchase_id}'}: {old_status or '—'} → {data.status or '—'}",
            event_key="status_changed",
            event_value=data.status,
            actor_email=actor.get("email", ""),
            actor_name=actor.get("name", ""),
            category="supply",
        )
    was_overdue = bool(existing_payload) and existing_payload.get("status") != "received" and _is_overdue("issued", existing_payload.get("expected_date", ""))
    is_overdue_now = data.status != "received" and _is_overdue("issued", data.expected_date)
    if is_overdue_now and not was_overdue:
        notify_entity_watchers(
            "purchase_order",
            str(purchase_id),
            "Поставка просрочилась",
            f"{data.item_name or f'Закупка #{purchase_id}'} должна была прийти {data.expected_date or 'без даты'}.",
            event_key="overdue",
            event_value=data.expected_date or data.status,
            actor_email=actor.get("email", ""),
            actor_name=actor.get("name", ""),
            category="supply",
        )
    return {"status": "success", "linked_payment_id": linked_payment_id}


@router.delete("/api/purchases/{purchase_id}")
def delete_purchase(purchase_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "supply", "delete"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "purchase_order", purchase_id)
    if lock:
        return {"error": "locked", "lock": lock}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT item_name, legal_entity_id, business_unit_id FROM purchase_orders WHERE id=?", (purchase_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    if not _assert_finance_scope(actor, _safe_int(row[1]), _safe_int(row[2])):
        conn.close()
        return {"error": "forbidden_scope"}
    linked_payment_id = _delete_source_finance_payment(conn, "purchase_order", purchase_id)
    _delete_entity_runtime_links(conn, "purchase", purchase_id)
    _delete_sync_entity_cascade(conn, "purchase_order", purchase_id)
    c.execute("DELETE FROM purchase_orders WHERE id=?", (purchase_id,))
    conn.commit()
    conn.close()
    audit_log("purchase_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="purchase", entity_id=str(purchase_id), details={"item": row[0] or "", "linked_payment_id": linked_payment_id})
    return {"status": "success", "linked_payment_id": linked_payment_id}


@router.get("/api/stock/reservations")
def get_stock_reservations(request: Request, project_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "supply", "read"):
        return {"error": "forbidden"}
    rows = _enrich_stock_reservation_rows(_filter_scope_rows_for_actor(actor, _load_stock_reservations()))
    if project_id:
        rows = [row for row in rows if int(row.get("project_id") or 0) == project_id]
    return rows


@router.post("/api/stock/reservations")
def create_stock_reservation(data: StockReservationData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "supply", "create"):
        return {"error": "forbidden"}
    permission_error = _enforce_field_permissions(
        actor,
        "supply",
        "stock_reservation",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        {},
    )
    if permission_error:
        return permission_error
    now = int(time.time())
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    scope = _resolve_ops_scope_dimensions(conn, data.legal_entity_id, data.business_unit_id)
    if not _assert_finance_scope(actor, scope["legal_entity_id"], scope["business_unit_id"]):
        conn.close()
        return {"error": "forbidden_scope"}
    article = _normalize_spaces(data.nomenclature_article)
    warehouse = _normalize_spaces(data.warehouse)
    bin_code = _normalize_spaces(data.bin_code)
    batch_code = _normalize_spaces(data.batch_code)
    serial_no = _normalize_spaces(data.serial_no)
    source = None
    if article and not (warehouse or bin_code or batch_code or serial_no):
        source = _pick_inventory_source(c, article, _safe_float(data.qty))
        if source:
            warehouse = source["warehouse"]
            bin_code = source["bin_code"]
            batch_code = source["batch_code"]
            serial_no = source["serial_no"]
    available_free_qty = 0.0
    if article and warehouse:
        _bootstrap_inventory_lots_for_article(c, article)
        c.execute(
            """
            SELECT COALESCE(SUM(qty), 0)
            FROM inventory_lots
            WHERE article=? AND warehouse=? AND bin_code=? AND batch_code=? AND serial_no=?
            """,
            (article, warehouse, bin_code or "A-01", batch_code, serial_no),
        )
        raw_available = _safe_float(c.fetchone()[0])
        reserved_at_source = _available_reserved_qty(c, article, warehouse, bin_code or "A-01", batch_code, serial_no)
        available_free_qty = round(raw_available - reserved_at_source, 3)
    elif source:
        available_free_qty = round(_safe_float(source.get("free_qty")), 3)
    status = data.status or "reserved"
    if article and available_free_qty < _safe_float(data.qty):
        status = "shortage"
    c.execute(
        """
        INSERT INTO stock_reservations (
            project_id, legal_entity_id, business_unit_id, nomenclature_article, nomenclature_name, qty, status, comment, created_by, created_at,
            warehouse, bin_code, batch_code, serial_no, fulfilled_qty, released_at, released_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.project_id, scope["legal_entity_id"], scope["business_unit_id"], article, data.nomenclature_name, data.qty, status, data.comment, actor.get("email", ""), now,
            warehouse, bin_code, batch_code, serial_no, 0, 0, "",
        ),
    )
    reservation_id = c.lastrowid
    _upsert_entity_sync_job(conn, "stock_reservation", reservation_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log(
        "stock_reserved",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="stock_reservation",
        entity_id=str(reservation_id),
        details={
            "item": data.nomenclature_name,
            "qty": data.qty,
            "status": status,
            "warehouse": warehouse,
            "bin_code": bin_code,
            "batch_code": batch_code,
            "serial_no": serial_no,
            "available_free_qty": available_free_qty,
            "legal_entity_id": scope["legal_entity_id"],
            "business_unit_id": scope["business_unit_id"],
        },
    )
    return {"status": "success", "id": reservation_id, "reservation_status": status, "warehouse": warehouse, "bin_code": bin_code, "batch_code": batch_code, "serial_no": serial_no, "available_free_qty": available_free_qty}


@router.get("/api/sales/summary")
def get_sales_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "sales", "read"):
        return {"error": "forbidden"}
    rows = _filter_scope_rows_for_actor(actor, _load_sales_rows())
    return {
        "metrics": {
            "drafts": len([row for row in rows if row.get("status") == "draft"]),
            "issued": len([row for row in rows if row.get("status") == "issued"]),
            "signed": len([row for row in rows if row.get("status") == "signed"]),
            "amount_total": round(sum(_safe_float(row.get("amount")) for row in rows), 2),
        },
        "recent": rows[:10],
    }


@router.get("/api/manager/workbench")
def get_manager_workbench(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    actor_name = actor.get("name", "")
    actor_role = actor.get("role", "")
    if actor_role not in {"Менеджер", "Директор"}:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    project_rows = []
    c.execute("SELECT * FROM projects")
    for row in c.fetchall():
        project = _project_payload(dict(row))
        if not can_access_project(actor, project):
            continue
        team = project.get("team") or []
        if actor_role == "Директор" or project.get("manager") == actor_name or actor_name in team:
            project_rows.append(project)
    project_ids = {int(item.get("id") or 0) for item in project_rows}
    purchases = [dict(row) for row in c.execute("SELECT * FROM purchase_orders ORDER BY updated_at DESC, id DESC").fetchall()]
    sales_docs = [dict(row) for row in c.execute("SELECT * FROM sales_documents_extended ORDER BY updated_at DESC, id DESC").fetchall()]
    finance_rows = [dict(row) for row in c.execute("SELECT * FROM finance_payments ORDER BY updated_at DESC, id DESC").fetchall()]
    document_rows = [dict(row) for row in c.execute("SELECT id, project_id, number, subject, status, d_date, type FROM documents ORDER BY id DESC").fetchall()]
    quote_rows = [dict(row) for row in c.execute("SELECT * FROM sales_quotes ORDER BY updated_at DESC, id DESC").fetchall()]
    order_rows = [dict(row) for row in c.execute("SELECT * FROM sales_customer_orders ORDER BY updated_at DESC, id DESC").fetchall()]
    shipment_rows = [dict(row) for row in c.execute("SELECT * FROM sales_shipments ORDER BY updated_at DESC, id DESC").fetchall()]
    conn.close()

    purchases = [row for row in purchases if _safe_int(row.get("project_id")) in project_ids]
    sales_docs = [row for row in sales_docs if _safe_int(row.get("project_id")) in project_ids]
    finance_rows = [row for row in finance_rows if _safe_int(row.get("project_id")) in project_ids]
    document_rows = [row for row in document_rows if _safe_int(row.get("project_id")) in project_ids]
    quote_rows = [row for row in quote_rows if _safe_int(row.get("project_id")) in project_ids]
    order_rows = [row for row in order_rows if _safe_int(row.get("project_id")) in project_ids]
    shipment_rows = [row for row in shipment_rows if _safe_int(row.get("customer_order_id")) in {int(item.get("id") or 0) for item in order_rows} or _safe_int(row.get("sales_document_id")) in {int(item.get("id") or 0) for item in sales_docs}]

    sales_doc_by_id = {int(item.get("id") or 0): item for item in sales_docs}
    project_cards = []
    for project in project_rows:
        project_id = int(project.get("id") or 0)
        project_quotes = [row for row in quote_rows if _safe_int(row.get("project_id")) == project_id]
        project_orders = [row for row in order_rows if _safe_int(row.get("project_id")) == project_id]
        project_purchases = [row for row in purchases if _safe_int(row.get("project_id")) == project_id]
        project_sales = [row for row in sales_docs if _safe_int(row.get("project_id")) == project_id]
        project_finance = [row for row in finance_rows if _safe_int(row.get("project_id")) == project_id]
        order_ids = {int(item.get("id") or 0) for item in project_orders}
        sales_ids = {int(item.get("id") or 0) for item in project_sales}
        project_shipments = [row for row in shipment_rows if _safe_int(row.get("customer_order_id")) in order_ids or _safe_int(row.get("sales_document_id")) in sales_ids]
        project_documents = [row for row in document_rows if _safe_int(row.get("project_id")) == project_id]
        receivable_open = round(sum(_safe_float(item.get("amount")) for item in project_finance if item.get("kind") == "incoming" and item.get("status") != "paid"), 2)
        overdue_receivable = round(sum(_safe_float(item.get("amount")) for item in project_finance if item.get("kind") == "incoming" and _is_overdue(item.get("status", ""), item.get("due_date", ""))), 2)
        pending_shipment = len([row for row in project_shipments if row.get("status") not in {"shipped", "delivered"}])
        pending_purchase = len([row for row in project_purchases if row.get("status") not in {"received", "cancelled"}])
        open_documents = len([row for row in project_documents if row.get("status") not in {"archived", "closed"}])
        quote_amount = round(sum(_safe_float(item.get("amount")) for item in project_quotes), 2)
        card = {
            "project_id": project_id,
            "project_name": project.get("name", ""),
            "contract": project.get("contract", ""),
            "client": project.get("client", ""),
            "manager": project.get("manager", ""),
            "status": project.get("status", ""),
            "progress": int(project.get("progress") or 0),
            "quotes_total": len(project_quotes),
            "quote_amount": quote_amount,
            "customer_orders_total": len(project_orders),
            "sales_documents_total": len(project_sales),
            "purchases_in_progress": pending_purchase,
            "shipments_pending": pending_shipment,
            "receivable_open": receivable_open,
            "overdue_receivable": overdue_receivable,
            "documents_open": open_documents,
            "last_document_number": (project_documents[0].get("number", "") if project_documents else ""),
            "last_sales_document": (project_sales[0].get("doc_number", "") if project_sales else ""),
            "last_purchase_supplier": (project_purchases[0].get("supplier", "") if project_purchases else ""),
        }
        card["risk_score"] = pending_purchase + pending_shipment + open_documents + (2 if overdue_receivable > 0 else 0)
        project_cards.append(card)
    project_cards.sort(key=lambda item: (item.get("risk_score", 0), item.get("receivable_open", 0), item.get("quote_amount", 0)), reverse=True)

    return {
        "metrics": {
            "active_deals": len([item for item in project_rows if item.get("status") == "active"]),
            "quotes_pipeline": round(sum(_safe_float(item.get("amount")) for item in quote_rows), 2),
            "purchases_in_progress": len([item for item in purchases if item.get("status") not in {"received", "cancelled"}]),
            "shipments_pending": len([item for item in shipment_rows if item.get("status") not in {"shipped", "delivered"}]),
            "receivable_open": round(sum(_safe_float(item.get("amount")) for item in finance_rows if item.get("kind") == "incoming" and item.get("status") != "paid"), 2),
            "overdue_receivable": round(sum(_safe_float(item.get("amount")) for item in finance_rows if item.get("kind") == "incoming" and _is_overdue(item.get("status", ""), item.get("due_date", ""))), 2),
            "documents_open": len([item for item in document_rows if item.get("status") not in {"archived", "closed"}]),
        },
        "focus_projects": project_cards[:8],
        "recent_documents": document_rows[:8],
        "recent_sales_documents": sales_docs[:8],
        "recent_purchases": purchases[:8],
        "recent_shipments": [
            {
                **item,
                "sales_doc_number": sales_doc_by_id.get(int(item.get("sales_document_id") or 0), {}).get("doc_number", ""),
            }
            for item in shipment_rows[:8]
        ],
    }


@router.get("/api/sales/documents")
def get_sales_documents(request: Request, project_id: int = 0, client_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "sales", "read"):
        return {"error": "forbidden"}
    rows = _filter_scope_rows_for_actor(actor, _load_sales_rows())
    if project_id:
        rows = [row for row in rows if int(row.get("project_id") or 0) == project_id]
    if client_id:
        rows = [row for row in rows if int(row.get("client_id") or 0) == client_id]
    return rows


@router.post("/api/sales/documents")
def create_sales_document(data: SalesDocumentData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "sales", "create"):
        return {"error": "forbidden"}
    permission_error = _enforce_field_permissions(
        actor,
        "sales",
        "sales_document",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        {},
    )
    if permission_error:
        return permission_error
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    scope = _resolve_ops_scope_dimensions(conn, data.legal_entity_id, data.business_unit_id)
    if not _assert_finance_scope(actor, scope["legal_entity_id"], scope["business_unit_id"]):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute(
        """
        INSERT INTO sales_documents_extended (
            project_id, client_id, contract_id, object_id, legal_entity_id, business_unit_id, doc_type, doc_number, doc_date, amount, currency, status,
            payment_status, linked_payment_id, customer_order_no, shipment_status, payment_due_date, planned_ship_date, shipped_at, reserve_status, reserve_qty, price_list_id, discount_percent, discount_amount,
            comment, recipient_email, sent_status, sent_at, delivered_at, confirmed_at, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context["project_id"], context["client_id"], context["contract_id"], context["object_id"], scope["legal_entity_id"], scope["business_unit_id"], data.doc_type, data.doc_number, data.doc_date, data.amount, data.currency,
            data.status, data.payment_status, data.linked_payment_id, getattr(data, "customer_order_no", ""), getattr(data, "shipment_status", "not_shipped"), getattr(data, "payment_due_date", ""), getattr(data, "planned_ship_date", ""), getattr(data, "shipped_at", ""), getattr(data, "reserve_status", "none"), getattr(data, "reserve_qty", 0), getattr(data, "price_list_id", 0), getattr(data, "discount_percent", 0), getattr(data, "discount_amount", 0), data.comment,
            getattr(data, "recipient_email", ""), getattr(data, "sent_status", "draft"),
            getattr(data, "sent_at", ""), getattr(data, "delivered_at", ""), getattr(data, "confirmed_at", ""),
            actor.get("email", ""), now, now,
        ),
    )
    document_id = c.lastrowid
    linked_payment_id = _sync_sales_finance_link(conn, document_id, actor.get("email", ""))
    _upsert_entity_sync_job(conn, "sales_document", document_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("sales_document_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="sales_document", entity_id=str(document_id), details={"doc_type": data.doc_type, "number": data.doc_number, "amount": data.amount, "linked_payment_id": linked_payment_id, "legal_entity_id": scope["legal_entity_id"], "business_unit_id": scope["business_unit_id"]})
    return {"status": "success", "id": document_id, "linked_payment_id": linked_payment_id}


@router.put("/api/sales/documents/{document_id}")
def update_sales_document(document_id: int, data: SalesDocumentData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "sales", "update"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "sales_document", document_id)
    if lock:
        return {"error": "locked", "lock": lock}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM sales_documents_extended WHERE id=?", (document_id,))
    existing_row = c.fetchone()
    if existing_row:
        columns = [col[0] for col in c.description]
        existing_payload = dict(zip(columns, existing_row))
        permission_error = _enforce_field_permissions(
            actor,
            "sales",
            "sales_document",
            data.model_dump() if hasattr(data, "model_dump") else data.dict(),
            existing_payload,
        )
        if permission_error:
            conn.close()
            return permission_error
    c.execute("SELECT legal_entity_id, business_unit_id FROM sales_documents_extended WHERE id=?", (document_id,))
    existing_scope = c.fetchone()
    if existing_scope and not _assert_finance_scope(actor, _safe_int(existing_scope[0]), _safe_int(existing_scope[1])):
        conn.close()
        return {"error": "forbidden_scope"}
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    scope = _resolve_ops_scope_dimensions(conn, data.legal_entity_id, data.business_unit_id)
    if not _assert_finance_scope(actor, scope["legal_entity_id"], scope["business_unit_id"]):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute(
        """
        UPDATE sales_documents_extended
        SET project_id=?, client_id=?, contract_id=?, object_id=?, legal_entity_id=?, business_unit_id=?, doc_type=?, doc_number=?, doc_date=?, amount=?, currency=?, status=?,
            payment_status=?, linked_payment_id=?, customer_order_no=?, shipment_status=?, payment_due_date=?, planned_ship_date=?, shipped_at=?, reserve_status=?, reserve_qty=?, price_list_id=?, discount_percent=?, discount_amount=?, comment=?, recipient_email=?, sent_status=?, sent_at=?, delivered_at=?, confirmed_at=?, updated_at=?
        WHERE id=?
        """,
        (
            context["project_id"], context["client_id"], context["contract_id"], context["object_id"], scope["legal_entity_id"], scope["business_unit_id"], data.doc_type, data.doc_number, data.doc_date, data.amount, data.currency,
            data.status, data.payment_status, data.linked_payment_id, getattr(data, "customer_order_no", ""), getattr(data, "shipment_status", "not_shipped"), getattr(data, "payment_due_date", ""), getattr(data, "planned_ship_date", ""), getattr(data, "shipped_at", ""), getattr(data, "reserve_status", "none"), getattr(data, "reserve_qty", 0), getattr(data, "price_list_id", 0), getattr(data, "discount_percent", 0), getattr(data, "discount_amount", 0), data.comment,
            getattr(data, "recipient_email", ""), getattr(data, "sent_status", "draft"),
            getattr(data, "sent_at", ""), getattr(data, "delivered_at", ""), getattr(data, "confirmed_at", ""),
            now, document_id,
        ),
    )
    linked_payment_id = _sync_sales_finance_link(conn, document_id, actor.get("email", ""))
    _upsert_entity_sync_job(conn, "sales_document", document_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("sales_document_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="sales_document", entity_id=str(document_id), details={"doc_type": data.doc_type, "number": data.doc_number, "status": data.status, "linked_payment_id": linked_payment_id, "legal_entity_id": scope["legal_entity_id"], "business_unit_id": scope["business_unit_id"]})
    return {"status": "success", "linked_payment_id": linked_payment_id}


@router.delete("/api/sales/documents/{document_id}")
def delete_sales_document(document_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "sales", "delete"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "sales_document", document_id)
    if lock:
        return {"error": "locked", "lock": lock}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT doc_type, doc_number, legal_entity_id, business_unit_id FROM sales_documents_extended WHERE id=?", (document_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    if not _assert_finance_scope(actor, _safe_int(row[2]), _safe_int(row[3])):
        conn.close()
        return {"error": "forbidden_scope"}
    linked_payment_id = _delete_source_finance_payment(conn, "sales_document", document_id)
    _delete_entity_runtime_links(conn, "sales_document", document_id)
    _delete_sync_entity_cascade(conn, "sales_document", document_id)
    c.execute("DELETE FROM sales_documents_extended WHERE id=?", (document_id,))
    conn.commit()
    conn.close()
    audit_log("sales_document_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="sales_document", entity_id=str(document_id), details={"doc_type": row[0] or "", "doc_number": row[1] or "", "linked_payment_id": linked_payment_id})
    return {"status": "success", "linked_payment_id": linked_payment_id}


@router.get("/api/stock/movements")
def get_stock_movements(request: Request, article: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    return _load_stock_movements(article)


@router.get("/api/stock/balances")
def get_stock_balances(request: Request, article: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    return _load_inventory_balances(article)


@router.get("/api/stock/lots")
def get_stock_lots(request: Request, article: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    return _load_inventory_lots(article)


@router.post("/api/nomenclature/{article}/movement_detailed")
async def move_stock_detailed(article: str, data: StockMovementDetailedData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "update"):
        return {"error": "forbidden"}
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute("SELECT * FROM nomenclature WHERE article=?", (article,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Товар не найден")
    item = dict(row)
    qty = _safe_float(data.qty)
    if qty <= 0:
        conn.close()
        return {"error": "qty_required"}
    current_stock = _safe_float(item.get("stock"))
    new_stock = current_stock
    movement_type = data.type or "add"
    source_wh = (data.from_warehouse or "").strip()
    source_bin = (data.from_bin or "").strip()
    target_wh = (data.to_warehouse or "").strip()
    target_bin = (data.to_bin or "").strip()
    batch_code = (data.batch_code or "").strip()
    serial_no = (data.serial_no or "").strip()
    if movement_type == "add":
        new_stock = current_stock + qty
    elif movement_type == "remove":
        new_stock = current_stock - qty
    elif movement_type == "transfer":
        new_stock = current_stock
    else:
        conn.close()
        return {"error": "invalid_type"}
    c.execute("UPDATE nomenclature SET stock=? WHERE article=?", (new_stock, article))
    if movement_type == "add":
        dest_wh, dest_bin = _normalize_stock_location(target_wh or source_wh, target_bin or source_bin)
        _upsert_inventory_balance(c, article, dest_wh, dest_bin, qty)
        _upsert_inventory_lot(c, article, dest_wh, dest_bin, batch_code, serial_no, qty)
        receipt_cost_layer(conn, article, item.get("name", ""), dest_wh, dest_bin, batch_code, serial_no, qty, _safe_float(getattr(data, "unit_cost", 0)) or _safe_float(item.get("price")), actor.get("email", ""), "stock_movement", 0, getattr(data, "lot_expiration_date", ""), getattr(data, "unit", "шт"), {"movement_type": movement_type})
    elif movement_type == "remove":
        src_wh, src_bin = _normalize_stock_location(source_wh, source_bin)
        cost_allocations, cost_missing = consume_cost_layers(conn, article, qty, src_wh, src_bin, batch_code, serial_no, actor.get("email", ""), "stock_movement", 0, details={"movement_type": movement_type})
        if cost_missing > 0:
            conn.close()
            return {"error": "insufficient_cost_layers"}
        allocations, remaining = _consume_inventory_lots(c, article, qty, src_wh, src_bin, batch_code, serial_no)
        if remaining > 0:
            conn.close()
            return {"error": "insufficient_stock"}
        _upsert_inventory_balance(c, article, src_wh, src_bin, -qty)
        if allocations:
            batch_code = allocations[0].get("batch_code", batch_code)
            serial_no = allocations[0].get("serial_no", serial_no)
    elif movement_type == "transfer":
        src_wh, src_bin = _normalize_stock_location(source_wh, source_bin)
        dst_wh, dst_bin = _normalize_stock_location(target_wh or "Транзит", target_bin or "T-01")
        cost_allocations, cost_missing = consume_cost_layers(conn, article, qty, src_wh, src_bin, batch_code, serial_no, actor.get("email", ""), "stock_movement", 0, details={"movement_type": movement_type})
        if cost_missing > 0:
            conn.close()
            return {"error": "insufficient_cost_layers"}
        allocations, remaining = _consume_inventory_lots(c, article, qty, src_wh, src_bin, batch_code, serial_no)
        if remaining > 0:
            conn.close()
            return {"error": "insufficient_stock"}
        _upsert_inventory_balance(c, article, src_wh, src_bin, -qty)
        _upsert_inventory_balance(c, article, dst_wh, dst_bin, qty)
        for allocation in allocations or [{"batch_code": batch_code, "serial_no": serial_no, "qty": qty}]:
            _upsert_inventory_lot(c, article, dst_wh, dst_bin, allocation.get("batch_code", ""), allocation.get("serial_no", ""), allocation.get("qty", qty), allocation.get("lot_expiration_date", ""))
        transfer_cost_layers(conn, cost_allocations, article, item.get("name", ""), dst_wh, dst_bin, actor.get("email", ""), "stock_movement", 0)

    _cleanup_inventory_tables(c)
    c.execute(
        """
        INSERT INTO stock_movements (article, name, qty, movement_type, from_warehouse, from_bin, to_warehouse, to_bin, comment, actor_email, created_at, batch_code, serial_no, reservation_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            article, item.get("name", ""), qty, movement_type, source_wh, source_bin, target_wh, target_bin,
            data.comment, actor.get("email", ""), int(time.time()), batch_code, serial_no
        ),
    )
    _upsert_entity_sync_job(conn, "nomenclature", article, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("stock_movement_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="stock_movement", entity_id=article, details={"type": movement_type, "qty": qty, "from": f"{source_wh}/{source_bin}", "to": f"{target_wh}/{target_bin}", "batch_code": batch_code, "serial_no": serial_no})
    return {"status": "success", "new_stock": new_stock}


@router.post("/api/stock/reservations/{reservation_id}/fulfill")
def fulfill_stock_reservation(reservation_id: int, data: StockReservationFulfillData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "supply", "receive") or has_permission(actor, "supply", "update") or has_permission(actor, "nsi", "update")):
        return {"error": "forbidden"}
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute("SELECT * FROM stock_reservations WHERE id=?", (reservation_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    reservation = dict(row)
    if reservation.get("status") in {"fulfilled", "cancelled"}:
        conn.close()
        return {"error": "already_closed"}
    remaining_qty = round(max(_safe_float(reservation.get("qty")) - _safe_float(reservation.get("fulfilled_qty")), 0), 3)
    if remaining_qty <= 0:
        conn.close()
        return {"error": "nothing_to_fulfill"}
    fulfill_qty = round(_safe_float(data.qty) or remaining_qty, 3)
    if fulfill_qty <= 0:
        conn.close()
        return {"error": "qty_required"}
    if fulfill_qty > remaining_qty:
        conn.close()
        return {"error": "qty_exceeds_remaining"}
    article = reservation.get("nomenclature_article", "")
    warehouse = _normalize_spaces(data.warehouse) or reservation.get("warehouse", "")
    bin_code = _normalize_spaces(data.bin_code) or reservation.get("bin_code", "")
    batch_code = _normalize_spaces(data.batch_code) or reservation.get("batch_code", "")
    serial_no = _normalize_spaces(data.serial_no) or reservation.get("serial_no", "")
    source = None
    if article and not (warehouse or bin_code or batch_code or serial_no):
        source = _pick_inventory_source(c, article, fulfill_qty)
        if source:
            warehouse = source["warehouse"]
            bin_code = source["bin_code"]
            batch_code = source["batch_code"]
            serial_no = source["serial_no"]
    if not warehouse:
        conn.close()
        return {"error": "source_required"}
    item_name = reservation.get("nomenclature_name", article)
    c.execute("SELECT stock FROM nomenclature WHERE article=?", (article,))
    stock_row = c.fetchone()
    current_stock = _safe_float(stock_row[0]) if stock_row else 0
    allocations, missing = _consume_inventory_lots(c, article, fulfill_qty, warehouse, bin_code, batch_code, serial_no)
    if missing > 0:
        conn.close()
        return {"error": "insufficient_stock"}
    src_wh, src_bin = _normalize_stock_location(warehouse, bin_code)
    _upsert_inventory_balance(c, article, src_wh, src_bin, -fulfill_qty)
    _cleanup_inventory_tables(c)
    c.execute("UPDATE nomenclature SET stock=? WHERE article=?", (round(current_stock - fulfill_qty, 3), article))
    fulfilled_total = round(_safe_float(reservation.get("fulfilled_qty")) + fulfill_qty, 3)
    new_status = "fulfilled" if fulfilled_total >= _safe_float(reservation.get("qty")) else "partial"
    c.execute(
        """
        UPDATE stock_reservations
        SET fulfilled_qty=?, status=?, released_at=?, released_by=?, warehouse=?, bin_code=?, batch_code=?, serial_no=?, comment=?
        WHERE id=?
        """,
        (
            fulfilled_total, new_status, int(time.time()), actor.get("email", ""), src_wh, src_bin, batch_code, serial_no,
            ((reservation.get("comment") or "").strip() + ("\n" if reservation.get("comment") and data.comment else "") + (data.comment or "")).strip(),
            reservation_id,
        ),
    )
    c.execute(
        """
        INSERT INTO stock_movements (article, name, qty, movement_type, from_warehouse, from_bin, to_warehouse, to_bin, comment, actor_email, created_at, batch_code, serial_no, reservation_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            article, item_name, fulfill_qty, "remove", src_wh, src_bin, f"Проект #{int(reservation.get('project_id') or 0)}", "Резерв исполнен",
            data.comment or f"Исполнение резерва #{reservation_id}", actor.get("email", ""), int(time.time()), batch_code, serial_no, reservation_id,
        ),
    )
    _upsert_entity_sync_job(conn, "stock_reservation", reservation_id, actor.get("email", ""))
    _upsert_entity_sync_job(conn, "nomenclature", article, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log(
        "stock_reservation_fulfilled",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="stock_reservation",
        entity_id=str(reservation_id),
        details={
            "article": article,
            "qty": fulfill_qty,
            "fulfilled_qty": fulfilled_total,
            "status": new_status,
            "warehouse": src_wh,
            "bin_code": src_bin,
            "batch_code": batch_code,
            "serial_no": serial_no,
        },
    )
    return {"status": "success", "id": reservation_id, "fulfilled_qty": fulfilled_total, "reservation_status": new_status}


@router.get("/api/projects/{proj_id}/spec_versions")
def get_specification_versions(proj_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    existing = _load_project_row(proj_id)
    if not existing:
        return {"error": "not_found"}
    project = _project_payload(existing)
    if not can_access_project(actor, project):
        return {"error": "forbidden"}
    return _load_specification_versions(proj_id)


@router.post("/api/projects/{proj_id}/spec_versions")
def create_specification_version(proj_id: int, data: SpecificationVersionData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    existing = _load_project_row(proj_id)
    if not existing:
        return {"error": "not_found"}
    project = _project_payload(existing)
    if not can_edit_project(actor, project):
        return {"error": "forbidden"}
    snapshot = data.items if data.items else (project.get("nomenclature") or [])
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO specification_versions (project_id, label, comment, snapshot, actor_email, actor_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (proj_id, data.label or f"Версия {int(time.time())}", data.comment, json.dumps(snapshot), actor.get("email", ""), actor.get("name", ""), int(time.time()))
    )
    version_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("specification_version_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="specification_version", entity_id=str(version_id), details={"project_id": proj_id, "items": len(snapshot), "label": data.label})
    return {"status": "success", "id": version_id}


@router.get("/api/production/summary")
def get_production_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    rows = _filter_scope_rows_for_actor(actor, _load_production_rows())
    allowed_order_ids = {int(row.get("id") or 0) for row in rows}
    operations = [row for row in _load_production_operation_rows() if int(row.get("order_id") or 0) in allowed_order_ids]
    bom_items = [row for row in _load_production_bom_rows() if int(row.get("order_id") or 0) in allowed_order_ids]
    route_templates = [row for row in _load_production_route_rows() if int(row.get("order_id") or 0) in allowed_order_ids]
    bottlenecks = {}
    for item in operations:
        key = item.get("work_center") or "Без участка"
        entry = bottlenecks.setdefault(key, {"work_center": key, "operations": 0, "hours": 0.0, "in_progress": 0})
        entry["operations"] += 1
        entry["hours"] += _safe_float(item.get("planned_hours"))
        if item.get("status") in {"in_progress", "otk"}:
            entry["in_progress"] += 1
    bottleneck_rows = sorted(bottlenecks.values(), key=lambda item: (item["in_progress"], item["hours"]), reverse=True)
    return {
        "metrics": {
            "queue": len([row for row in rows if row.get("stage") == "queue"]),
            "in_work": len([row for row in rows if row.get("stage") == "in_work"]),
            "done": len([row for row in rows if row.get("stage") == "done"]),
            "avg_progress": round(sum(int(row.get("progress") or 0) for row in rows) / len(rows), 1) if rows else 0,
            "operations_total": len(operations),
            "bom_items_total": len(bom_items),
            "route_templates_total": len(route_templates),
            "labor_hours_fact": round(sum(_safe_float(item.get("actual_hours")) for item in operations), 2),
            "actual_cost_total": round(sum(_safe_float(item.get("actual_cost")) for item in operations), 2),
            "planned_material_cost": round(sum(_safe_float(item.get("planned_cost")) for item in bom_items), 2),
            "actual_material_cost": round(sum(_safe_float(item.get("actual_cost")) for item in bom_items), 2),
            "scrap_qty_total": round(sum(_safe_float(item.get("scrap_qty")) for item in operations), 2),
        },
        "recent": rows[:10],
        "bottlenecks": bottleneck_rows[:8],
    }


@router.get("/api/production/orders")
def get_production_orders(request: Request, project_id: int = 0, client_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    rows = _filter_scope_rows_for_actor(actor, _load_production_rows())
    if project_id:
        rows = [row for row in rows if int(row.get("project_id") or 0) == project_id]
    if client_id:
        rows = [row for row in rows if int(row.get("client_id") or 0) == client_id]
    return rows


@router.get("/api/production/operations")
def get_production_operations(request: Request, order_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    scoped_orders = _filter_scope_rows_for_actor(actor, _load_production_rows())
    allowed_order_ids = {int(row.get("id") or 0) for row in scoped_orders}
    if order_id and order_id not in allowed_order_ids:
        return {"error": "forbidden_scope"}
    return [row for row in _load_production_operation_rows(order_id) if int(row.get("order_id") or 0) in allowed_order_ids]


@router.get("/api/production/bom")
def get_production_bom(request: Request, order_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    scoped_orders = _filter_scope_rows_for_actor(actor, _load_production_rows())
    allowed_order_ids = {int(row.get("id") or 0) for row in scoped_orders}
    if order_id and order_id not in allowed_order_ids:
        return {"error": "forbidden_scope"}
    return [row for row in _load_production_bom_rows(order_id) if int(row.get("order_id") or 0) in allowed_order_ids]


@router.get("/api/production/routes")
def get_production_routes(request: Request, order_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "read"):
        return {"error": "forbidden"}
    scoped_orders = _filter_scope_rows_for_actor(actor, _load_production_rows())
    allowed_order_ids = {int(row.get("id") or 0) for row in scoped_orders}
    if order_id and order_id not in allowed_order_ids:
        return {"error": "forbidden_scope"}
    return [row for row in _load_production_route_rows(order_id) if int(row.get("order_id") or 0) in allowed_order_ids]


@router.post("/api/production/orders")
def create_production_order(data: ProductionOrderData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "create"):
        return _api_error(403, "forbidden")
    permission_error = _enforce_field_permissions(
        actor,
        "production",
        "production_order",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        {},
    )
    if permission_error:
        return permission_error
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    scope = _resolve_ops_scope_dimensions(conn, data.legal_entity_id, data.business_unit_id)
    if not _assert_finance_scope(actor, scope["legal_entity_id"], scope["business_unit_id"]):
        conn.close()
        return _api_error(403, "forbidden_scope")
    c.execute(
        """
        INSERT INTO production_orders (
            project_id, client_id, contract_id, object_id, legal_entity_id, business_unit_id, order_name, stage, priority, planned_start, planned_finish,
            actual_finish, progress, responsible, route_name, planned_qty, produced_qty, scrap_qty,
            planned_cost, actual_cost, labor_hours_plan, labor_hours_fact, comment, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context["project_id"], context["client_id"], context["contract_id"], context["object_id"], scope["legal_entity_id"], scope["business_unit_id"], data.order_name, data.stage, data.priority, data.planned_start,
            data.planned_finish, data.actual_finish, data.progress, data.responsible, data.route_name, data.planned_qty, data.produced_qty,
            data.scrap_qty, data.planned_cost, data.actual_cost, data.labor_hours_plan, data.labor_hours_fact, data.comment,
            actor.get("email", ""), now, now,
        ),
    )
    order_id = c.lastrowid
    _upsert_entity_sync_job(conn, "production_order", order_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_order_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_order", entity_id=str(order_id), details={"order_name": data.order_name, "stage": data.stage, "progress": data.progress, "planned_qty": data.planned_qty, "planned_cost": data.planned_cost, "legal_entity_id": scope["legal_entity_id"], "business_unit_id": scope["business_unit_id"]})
    return {"status": "success", "id": order_id}


@router.put("/api/production/orders/{order_id}")
def update_production_order(order_id: int, data: ProductionOrderData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "production_order", order_id)
    if lock:
        return {"error": "locked", "lock": lock}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    existing_payload = {}
    c.execute("SELECT * FROM production_orders WHERE id=?", (order_id,))
    existing_row = c.fetchone()
    if existing_row:
        columns = [col[0] for col in c.description]
        existing_payload = dict(zip(columns, existing_row))
        permission_error = _enforce_field_permissions(
            actor,
            "production",
            "production_order",
            data.model_dump() if hasattr(data, "model_dump") else data.dict(),
            existing_payload,
        )
        if permission_error:
            conn.close()
            return permission_error
    c.execute("SELECT legal_entity_id, business_unit_id FROM production_orders WHERE id=?", (order_id,))
    existing_scope = c.fetchone()
    if existing_scope and not _assert_finance_scope(actor, _safe_int(existing_scope[0]), _safe_int(existing_scope[1])):
        conn.close()
        return {"error": "forbidden_scope"}
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    scope = _resolve_ops_scope_dimensions(conn, data.legal_entity_id, data.business_unit_id)
    if not _assert_finance_scope(actor, scope["legal_entity_id"], scope["business_unit_id"]):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute(
        """
        UPDATE production_orders
        SET project_id=?, client_id=?, contract_id=?, object_id=?, legal_entity_id=?, business_unit_id=?, order_name=?, stage=?, priority=?, planned_start=?, planned_finish=?,
            actual_finish=?, progress=?, responsible=?, route_name=?, planned_qty=?, produced_qty=?, scrap_qty=?,
            planned_cost=?, actual_cost=?, labor_hours_plan=?, labor_hours_fact=?, comment=?, updated_at=?
        WHERE id=?
        """,
        (
            context["project_id"], context["client_id"], context["contract_id"], context["object_id"], scope["legal_entity_id"], scope["business_unit_id"], data.order_name, data.stage, data.priority, data.planned_start,
            data.planned_finish, data.actual_finish, data.progress, data.responsible, data.route_name, data.planned_qty, data.produced_qty,
            data.scrap_qty, data.planned_cost, data.actual_cost, data.labor_hours_plan, data.labor_hours_fact, data.comment, now, order_id,
        ),
    )
    _upsert_entity_sync_job(conn, "production_order", order_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_order_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_order", entity_id=str(order_id), details={"order_name": data.order_name, "stage": data.stage, "progress": data.progress, "planned_qty": data.planned_qty, "planned_cost": data.planned_cost, "legal_entity_id": scope["legal_entity_id"], "business_unit_id": scope["business_unit_id"]})
    old_stage = existing_payload.get("stage", "")
    if old_stage != data.stage:
        notify_entity_watchers(
            "production_order",
            str(order_id),
            "Производственный заказ сменил этап",
            f"{data.order_name or f'Заказ #{order_id}'}: {old_stage or '—'} → {data.stage or '—'}",
            event_key="stage_changed",
            event_value=data.stage,
            actor_email=actor.get("email", ""),
            actor_name=actor.get("name", ""),
            category="production",
        )
    return {"status": "success"}


@router.post("/api/production/orders/{order_id}/apply_route")
def apply_route_to_production_order(order_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    conn = get_connection()
    if not _production_order_in_scope(conn, actor, order_id):
        conn.close()
        return {"error": "forbidden_scope"}
    result = _apply_route_templates_to_order(conn, order_id, actor.get("email", ""))
    _upsert_entity_sync_job(conn, "production_order", order_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_route_applied", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_order", entity_id=str(order_id), details=result)
    return {"status": "success", **result}


@router.post("/api/production/operations")
def create_production_operation(data: ProductionOperationData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return _api_error(403, "forbidden")
    permission_error = _enforce_field_permissions(
        actor,
        "production",
        "production_operation",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        {},
    )
    if permission_error:
        return permission_error
    if not _safe_int(data.order_id) or not (data.operation_name or "").strip():
        return _api_error(400, "invalid_operation")
    now = int(time.time())
    conn = get_connection()
    if not _production_order_in_scope(conn, actor, _safe_int(data.order_id)):
        conn.close()
        return _api_error(403, "forbidden_scope")
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO production_operations (
            order_id, sequence_no, operation_name, work_center, status, planned_hours, actual_hours,
            planned_qty, completed_qty, scrap_qty, labor_rate, material_cost, overhead_cost,
            started_at, finished_at, note, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _safe_int(data.order_id), _safe_int(data.sequence_no) or 1, data.operation_name, data.work_center, data.status,
            data.planned_hours, data.actual_hours, data.planned_qty, data.completed_qty, data.scrap_qty,
            data.labor_rate, data.material_cost, data.overhead_cost, data.started_at, data.finished_at,
            data.note, actor.get("email", ""), now, now,
        ),
    )
    operation_id = c.lastrowid
    costing_result = {}
    if (data.status or "").strip().lower() in {"done", "completed", "finished", "closed"}:
        costing_result = complete_operation_costing(conn, operation_id, actor.get("email", ""))
    _sync_production_order_rollup(conn, _safe_int(data.order_id))
    _upsert_entity_sync_job(conn, "production_order", _safe_int(data.order_id), actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_operation_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_operation", entity_id=str(operation_id), details={"order_id": data.order_id, "operation_name": data.operation_name, "status": data.status})
    return {"status": "success", "id": operation_id, "costing": costing_result}


@router.put("/api/production/operations/{operation_id}")
def update_production_operation(operation_id: int, data: ProductionOperationData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "production_operation", operation_id)
    if lock:
        return {"error": "locked", "lock": lock}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM production_operations WHERE id=?", (operation_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    columns = [col[0] for col in c.description]
    existing_payload = dict(zip(columns, row))
    permission_error = _enforce_field_permissions(
        actor,
        "production",
        "production_operation",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        existing_payload,
    )
    if permission_error:
        conn.close()
        return permission_error
    order_id = _safe_int(existing_payload.get("order_id"))
    target_order_id = _safe_int(data.order_id) or order_id
    if not _production_order_in_scope(conn, actor, order_id) or not _production_order_in_scope(conn, actor, target_order_id):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute(
        """
        UPDATE production_operations
        SET order_id=?, sequence_no=?, operation_name=?, work_center=?, status=?, planned_hours=?, actual_hours=?,
            planned_qty=?, completed_qty=?, scrap_qty=?, labor_rate=?, material_cost=?, overhead_cost=?,
            started_at=?, finished_at=?, note=?, updated_at=?
        WHERE id=?
        """,
        (
            target_order_id, _safe_int(data.sequence_no) or 1, data.operation_name, data.work_center, data.status,
            data.planned_hours, data.actual_hours, data.planned_qty, data.completed_qty, data.scrap_qty,
            data.labor_rate, data.material_cost, data.overhead_cost, data.started_at, data.finished_at,
            data.note, int(time.time()), operation_id,
        ),
    )
    costing_result = {}
    if (data.status or "").strip().lower() in {"done", "completed", "finished", "closed"}:
        costing_result = complete_operation_costing(conn, operation_id, actor.get("email", ""))
    _sync_production_order_rollup(conn, target_order_id)
    if target_order_id != order_id:
        _sync_production_order_rollup(conn, order_id)
    _upsert_entity_sync_job(conn, "production_order", target_order_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_operation_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_operation", entity_id=str(operation_id), details={"order_id": target_order_id, "operation_name": data.operation_name, "status": data.status})
    return {"status": "success", "costing": costing_result}


@router.delete("/api/production/operations/{operation_id}")
def delete_production_operation(operation_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "delete"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "production_operation", operation_id)
    if lock:
        return {"error": "locked", "lock": lock}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT order_id, operation_name FROM production_operations WHERE id=?", (operation_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    order_id = _safe_int(row[0])
    if not _production_order_in_scope(conn, actor, order_id):
        conn.close()
        return {"error": "forbidden_scope"}
    operation_name = row[1] or ""
    c.execute("DELETE FROM wip_register WHERE operation_id=?", (operation_id,))
    c.execute("DELETE FROM production_cost_layers WHERE operation_id=?", (operation_id,))
    c.execute("DELETE FROM production_operations WHERE id=?", (operation_id,))
    _sync_production_order_rollup(conn, order_id)
    _upsert_entity_sync_job(conn, "production_order", order_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_operation_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_operation", entity_id=str(operation_id), details={"order_id": order_id, "operation_name": operation_name})
    return {"status": "success"}


@router.post("/api/production/bom")
def create_production_bom_item(data: ProductionBOMItemData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return _api_error(403, "forbidden")
    permission_error = _enforce_field_permissions(
        actor,
        "production",
        "production_bom_item",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        {},
    )
    if permission_error:
        return permission_error
    if not _safe_int(data.order_id) or not (data.article or data.item_name).strip():
        return _api_error(400, "invalid_bom_item")
    conn = get_connection()
    if not _production_order_in_scope(conn, actor, _safe_int(data.order_id)):
        conn.close()
        return _api_error(403, "forbidden_scope")
    c = conn.cursor()
    article = (data.article or "").strip()
    item_name = (data.item_name or "").strip()
    unit = (data.unit or "шт").strip() or "шт"
    unit_cost = _safe_float(data.unit_cost)
    if article and unit_cost <= 0:
        c.execute("SELECT price, name, unit FROM nomenclature WHERE article=?", (article,))
        row = c.fetchone()
        if row:
            unit_cost = _safe_float(row[0])
            item_name = item_name or (row[1] or "")
            unit = unit or (row[2] or "шт")
    now = int(time.time())
    c.execute(
        """
        INSERT INTO production_bom_items (
            order_id, article, item_name, unit, qty_per_unit, planned_qty, actual_qty, unit_cost, warehouse, bin_code, note, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (_safe_int(data.order_id), article, item_name, unit, data.qty_per_unit, data.planned_qty, data.actual_qty, unit_cost, data.warehouse, data.bin_code, data.note, actor.get("email", ""), now, now),
    )
    bom_id = c.lastrowid
    _rebuild_production_bom_rollup(conn, _safe_int(data.order_id))
    _upsert_entity_sync_job(conn, "production_order", _safe_int(data.order_id), actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_bom_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_bom_item", entity_id=str(bom_id), details={"order_id": data.order_id, "article": article, "item_name": item_name})
    return {"status": "success", "id": bom_id}


@router.put("/api/production/bom/{bom_id}")
def update_production_bom_item(bom_id: int, data: ProductionBOMItemData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "production_bom_item", bom_id)
    if lock:
        return {"error": "locked", "lock": lock}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM production_bom_items WHERE id=?", (bom_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    columns = [col[0] for col in c.description]
    existing_payload = dict(zip(columns, row))
    permission_error = _enforce_field_permissions(
        actor,
        "production",
        "production_bom_item",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        existing_payload,
    )
    if permission_error:
        conn.close()
        return permission_error
    existing_order_id = _safe_int(existing_payload.get("order_id"))
    order_id = _safe_int(data.order_id) or existing_order_id
    if not _production_order_in_scope(conn, actor, existing_order_id) or not _production_order_in_scope(conn, actor, order_id):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute(
        """
        UPDATE production_bom_items
        SET order_id=?, article=?, item_name=?, unit=?, qty_per_unit=?, planned_qty=?, actual_qty=?, unit_cost=?, warehouse=?, bin_code=?, note=?, updated_at=?
        WHERE id=?
        """,
        (order_id, data.article, data.item_name, data.unit or "шт", data.qty_per_unit, data.planned_qty, data.actual_qty, data.unit_cost, data.warehouse, data.bin_code, data.note, int(time.time()), bom_id),
    )
    _rebuild_production_bom_rollup(conn, order_id)
    _upsert_entity_sync_job(conn, "production_order", order_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_bom_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_bom_item", entity_id=str(bom_id), details={"order_id": order_id})
    return {"status": "success"}


@router.delete("/api/production/bom/{bom_id}")
def delete_production_bom_item(bom_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "delete"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "production_bom_item", bom_id)
    if lock:
        return {"error": "locked", "lock": lock}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT order_id, article, item_name FROM production_bom_items WHERE id=?", (bom_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    order_id = _safe_int(row[0])
    if not _production_order_in_scope(conn, actor, order_id):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute("DELETE FROM production_bom_items WHERE id=?", (bom_id,))
    _rebuild_production_bom_rollup(conn, order_id)
    _upsert_entity_sync_job(conn, "production_order", order_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_bom_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_bom_item", entity_id=str(bom_id), details={"order_id": order_id, "article": row[1] or "", "item_name": row[2] or ""})
    return {"status": "success"}


@router.post("/api/production/routes")
def create_production_route_item(data: ProductionRouteTemplateData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return _api_error(403, "forbidden")
    permission_error = _enforce_field_permissions(
        actor,
        "production",
        "production_route_template",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        {},
    )
    if permission_error:
        return permission_error
    if not _safe_int(data.order_id) or not (data.operation_name or "").strip():
        return _api_error(400, "invalid_route_template")
    conn = get_connection()
    if not _production_order_in_scope(conn, actor, _safe_int(data.order_id)):
        conn.close()
        return _api_error(403, "forbidden_scope")
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        INSERT INTO production_route_templates (
            order_id, sequence_no, operation_name, work_center, planned_hours, planned_qty, labor_rate, note, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (_safe_int(data.order_id), _safe_int(data.sequence_no) or 1, data.operation_name, data.work_center, data.planned_hours, data.planned_qty, data.labor_rate, data.note, actor.get("email", ""), now, now),
    )
    route_id = c.lastrowid
    _upsert_entity_sync_job(conn, "production_order", _safe_int(data.order_id), actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_route_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_route_template", entity_id=str(route_id), details={"order_id": data.order_id, "operation_name": data.operation_name})
    return {"status": "success", "id": route_id}


@router.put("/api/production/routes/{route_id}")
def update_production_route_item(route_id: int, data: ProductionRouteTemplateData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "update"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "production_route_template", route_id)
    if lock:
        return {"error": "locked", "lock": lock}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM production_route_templates WHERE id=?", (route_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    columns = [col[0] for col in c.description]
    existing_payload = dict(zip(columns, row))
    permission_error = _enforce_field_permissions(
        actor,
        "production",
        "production_route_template",
        data.model_dump() if hasattr(data, "model_dump") else data.dict(),
        existing_payload,
    )
    if permission_error:
        conn.close()
        return permission_error
    existing_order_id = _safe_int(existing_payload.get("order_id"))
    order_id = _safe_int(data.order_id) or existing_order_id
    if not _production_order_in_scope(conn, actor, existing_order_id) or not _production_order_in_scope(conn, actor, order_id):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute(
        """
        UPDATE production_route_templates
        SET order_id=?, sequence_no=?, operation_name=?, work_center=?, planned_hours=?, planned_qty=?, labor_rate=?, note=?, updated_at=?
        WHERE id=?
        """,
        (order_id, _safe_int(data.sequence_no) or 1, data.operation_name, data.work_center, data.planned_hours, data.planned_qty, data.labor_rate, data.note, int(time.time()), route_id),
    )
    _upsert_entity_sync_job(conn, "production_order", order_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_route_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_route_template", entity_id=str(route_id), details={"order_id": order_id})
    return {"status": "success"}


@router.delete("/api/production/routes/{route_id}")
def delete_production_route_item(route_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "delete"):
        return {"error": "forbidden"}
    lock = _assert_entity_lock(request, actor, "production_route_template", route_id)
    if lock:
        return {"error": "locked", "lock": lock}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT order_id, operation_name FROM production_route_templates WHERE id=?", (route_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    order_id = _safe_int(row[0])
    if not _production_order_in_scope(conn, actor, order_id):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute("DELETE FROM production_route_templates WHERE id=?", (route_id,))
    _upsert_entity_sync_job(conn, "production_order", order_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("production_route_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_route_template", entity_id=str(route_id), details={"order_id": order_id, "operation_name": row[1] or ""})
    return {"status": "success"}


@router.delete("/api/production/orders/{order_id}")
def delete_production_order(order_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "production", "delete"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    if not _production_order_in_scope(conn, actor, order_id):
        conn.close()
        return {"error": "forbidden_scope"}
    c.execute("SELECT order_name FROM production_orders WHERE id=?", (order_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    _delete_entity_runtime_links(conn, "production_order", order_id)
    _delete_sync_entity_cascade(conn, "production_order", order_id)
    c.execute("DELETE FROM production_bom_items WHERE order_id=?", (order_id,))
    c.execute("DELETE FROM production_route_templates WHERE order_id=?", (order_id,))
    c.execute("DELETE FROM production_operations WHERE order_id=?", (order_id,))
    c.execute("DELETE FROM production_orders WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    audit_log("production_order_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_order", entity_id=str(order_id), details={"order_name": row[0] or ""})
    return {"status": "success"}


@router.get("/api/expenses/summary")
def get_expense_requests_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "expenses", "read"):
        return {"error": "forbidden"}
    rows = _load_expense_request_rows()
    return {
        "metrics": {
            "draft": len([row for row in rows if row.get("status") == "draft"]),
            "pending": len([row for row in rows if row.get("status") == "pending"]),
            "approved": len([row for row in rows if row.get("status") == "approved"]),
            "paid": len([row for row in rows if row.get("status") == "paid"]),
            "pending_amount": round(sum(_safe_float(row.get("amount")) for row in rows if row.get("status") in {"pending", "approved"}), 2),
        },
        "recent": rows[:10],
    }


@router.get("/api/expenses/requests")
def get_expense_requests(request: Request, project_id: int = 0, client_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "expenses", "read"):
        return {"error": "forbidden"}
    rows = _load_expense_request_rows()
    if project_id:
        rows = [row for row in rows if int(row.get("project_id") or 0) == project_id]
    if client_id:
        rows = [row for row in rows if int(row.get("client_id") or 0) == client_id]
    return rows


@router.post("/api/expenses/requests")
def create_expense_request(data: ExpenseApprovalData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "expenses", "create"):
        return {"error": "forbidden"}
    now = int(time.time())
    status = data.status or "draft"
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    c.execute(
        """
        INSERT INTO expense_requests (
            project_id, client_id, contract_id, object_id, title, request_type, amount, currency, approver_role, approver_name,
            due_date, linked_payment_id, status, comment, created_by, approved_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context["project_id"], context["client_id"], context["contract_id"], context["object_id"], data.title, data.request_type, data.amount, data.currency,
            data.approver_role, data.approver_name, data.due_date, data.linked_payment_id, status,
            data.comment, actor.get("email", ""), "", now, now,
        ),
    )
    request_id = c.lastrowid
    linked_payment_id = _sync_expense_finance_link(conn, request_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("expense_request_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="expense_request", entity_id=str(request_id), details={"title": data.title, "amount": data.amount, "status": status, "linked_payment_id": linked_payment_id})
    approver_name = data.approver_name or data.approver_role
    if status == "pending" and approver_name:
        create_notification("Новый запрос на оплату", f"{actor.get('name', 'Система')} отправил(а) запрос «{data.title}» на {int(_safe_float(data.amount)):,} ₽".replace(",", " "), user_name=approver_name, category="expense", entity_type="expense_request", entity_id=str(request_id))
    return {"status": "success", "id": request_id, "linked_payment_id": linked_payment_id}


@router.put("/api/expenses/requests/{request_id}")
def update_expense_request(request_id: int, data: ExpenseApprovalData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "expenses", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    approved_by = actor.get("email", "") if data.status in {"approved", "paid", "rejected"} else ""
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    c.execute(
        """
        UPDATE expense_requests
        SET project_id=?, client_id=?, contract_id=?, object_id=?, title=?, request_type=?, amount=?, currency=?, approver_role=?, approver_name=?,
            due_date=?, linked_payment_id=?, status=?, comment=?, approved_by=?, updated_at=?
        WHERE id=?
        """,
        (
            context["project_id"], context["client_id"], context["contract_id"], context["object_id"], data.title, data.request_type, data.amount, data.currency,
            data.approver_role, data.approver_name, data.due_date, data.linked_payment_id, data.status,
            data.comment, approved_by, now, request_id,
        ),
    )
    linked_payment_id = _sync_expense_finance_link(conn, request_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("expense_request_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="expense_request", entity_id=str(request_id), details={"title": data.title, "status": data.status, "amount": data.amount, "linked_payment_id": linked_payment_id})
    return {"status": "success", "linked_payment_id": linked_payment_id}


@router.delete("/api/expenses/requests/{request_id}")
def delete_expense_request(request_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "expenses", "delete"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT title FROM expense_requests WHERE id=?", (request_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    linked_payment_id = _delete_source_finance_payment(conn, "expense_request", request_id)
    _delete_entity_runtime_links(conn, "expense_request", request_id)
    c.execute("DELETE FROM expense_requests WHERE id=?", (request_id,))
    conn.commit()
    conn.close()
    audit_log("expense_request_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="expense_request", entity_id=str(request_id), details={"title": row[0] or "", "linked_payment_id": linked_payment_id})
    return {"status": "success", "linked_payment_id": linked_payment_id}


@router.get("/api/internal_requests/summary")
def get_internal_requests_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "requests", "read"):
        return {"error": "forbidden"}
    rows = _load_internal_request_rows()
    return {
        "metrics": {
            "new": len([row for row in rows if row.get("status") == "new"]),
            "in_work": len([row for row in rows if row.get("status") == "in_work"]),
            "done": len([row for row in rows if row.get("status") == "done"]),
            "high_priority": len([row for row in rows if row.get("priority") in {"high", "critical"}]),
        },
        "recent": rows[:10],
    }


@router.get("/api/internal_requests")
def get_internal_requests(request: Request, project_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "requests", "read"):
        return {"error": "forbidden"}
    rows = _load_internal_request_rows()
    if project_id:
        rows = [row for row in rows if int(row.get("project_id") or 0) == project_id]
    return rows


@router.post("/api/internal_requests")
def create_internal_request(data: InternalRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "requests", "create"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, 0, data.contract_id, data.object_id)
    c.execute(
        """
        INSERT INTO internal_requests (
            project_id, contract_id, object_id, title, request_type, target_role, assignee_name, priority, status, deadline,
            comment, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context["project_id"], context["contract_id"], context["object_id"], data.title, data.request_type, data.target_role, data.assignee_name, data.priority,
            data.status, data.deadline, data.comment, actor.get("email", ""), now, now,
        ),
    )
    internal_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("internal_request_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="internal_request", entity_id=str(internal_id), details={"title": data.title, "type": data.request_type, "status": data.status})
    if data.assignee_name:
        create_notification("Новая внутренняя заявка", f"{actor.get('name', 'Система')} создал(а) заявку «{data.title}»", user_name=data.assignee_name, category="request", entity_type="internal_request", entity_id=str(internal_id))
    return {"status": "success", "id": internal_id}


@router.put("/api/internal_requests/{request_id}")
def update_internal_request(request_id: int, data: InternalRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "requests", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, 0, data.contract_id, data.object_id)
    c.execute(
        """
        UPDATE internal_requests
        SET project_id=?, contract_id=?, object_id=?, title=?, request_type=?, target_role=?, assignee_name=?, priority=?, status=?, deadline=?, comment=?, updated_at=?
        WHERE id=?
        """,
        (
            context["project_id"], context["contract_id"], context["object_id"], data.title, data.request_type, data.target_role, data.assignee_name, data.priority,
            data.status, data.deadline, data.comment, now, request_id,
        ),
    )
    conn.commit()
    conn.close()
    audit_log("internal_request_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="internal_request", entity_id=str(request_id), details={"title": data.title, "status": data.status})
    return {"status": "success"}


@router.delete("/api/internal_requests/{request_id}")
def delete_internal_request(request_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "requests", "delete"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT title FROM internal_requests WHERE id=?", (request_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    _delete_entity_runtime_links(conn, "internal_request", request_id)
    c.execute("DELETE FROM internal_requests WHERE id=?", (request_id,))
    conn.commit()
    conn.close()
    audit_log("internal_request_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="internal_request", entity_id=str(request_id), details={"title": row[0] or ""})
    return {"status": "success"}


@router.get("/api/erp/summary")
def get_erp_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "requests", "read"):
        return {"error": "forbidden"}
    rows = list_erp_process_runs(limit=300)
    rows = [row for row in rows if _can_access_process(actor, row)]
    finance_rows = _load_finance_rows() if has_permission(actor, "finance", "read") else []
    resource_rows = _load_resource_allocations() if has_permission(actor, "resources", "read") else []
    reservations = _load_stock_reservations() if has_permission(actor, "supply", "read") else []
    quality = _build_erp_data_quality() if actor.get("role") == "Директор" or has_permission(actor, "nsi", "cleanup") or has_permission(actor, "nsi", "read") else {"counts": {"clients": 0, "nomenclature": 0, "orphans_total": 0}, "clients_duplicates": [], "clients_duplicate_inn": [], "nomenclature_duplicates": [], "orphans": {}}
    overdue = [row for row in rows if row.get("status") not in {"done", "cancelled"} and _is_overdue(row.get("status", ""), row.get("due_date", ""))]
    stage_counts = {}
    for row in rows:
        stage = row.get("current_stage") or "request"
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    return {
        "metrics": {
            "processes_total": len(rows),
            "active": len([row for row in rows if row.get("status") in {"new", "pending", "in_progress"}]),
            "blocked_approvals": len([row for row in rows if row.get("current_stage") == "approval" and row.get("status") != "done"]),
            "stock_reserved_qty": round(sum(_safe_float(row.get("qty")) for row in reservations if row.get("status") == "reserved"), 2),
            "open_money": round(sum(_safe_float(row.get("amount")) for row in finance_rows if row.get("status") != "paid"), 2),
            "overdue_processes": len(overdue),
            "avg_load": round(sum(_safe_int(row.get("load_percent")) for row in resource_rows) / len(resource_rows), 1) if resource_rows else 0,
            "data_issues": int(quality.get("counts", {}).get("orphans_total", 0)) + len(quality.get("clients_duplicates", [])) + len(quality.get("nomenclature_duplicates", [])),
        },
        "stage_counts": stage_counts,
        "pipeline_amount": round(sum(_safe_float(row.get("amount")) for row in rows if row.get("status") != "done"), 2),
        "recent": _enrich_process_rows(rows[:12]),
        "overdue": _enrich_process_rows(overdue[:8]),
        "quality": quality,
    }


@router.get("/api/erp/data_quality")
def get_erp_data_quality(request: Request):
    actor = require_approved_user(request)
    if not actor or not (actor.get("role") == "Директор" or has_permission(actor, "nsi", "read")):
        return {"error": "forbidden"}
    return _build_erp_data_quality()


@router.get("/api/erp/export")
def export_erp_snapshot(request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "requests", "export") or has_permission(actor, "finance", "export") or has_permission(actor, "nsi", "export") or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    rows = list_erp_process_runs(limit=500)
    rows = [row for row in rows if _can_access_process(actor, row)]
    return {
        "exported_at": time.strftime("%d.%m.%Y %H:%M"),
        "actor": {"email": actor.get("email", ""), "name": actor.get("name", ""), "role": actor.get("role", "")},
        "summary": get_erp_summary(request),
        "processes": _enrich_process_rows(rows),
        "quality": _build_erp_data_quality() if actor.get("role") == "Директор" or has_permission(actor, "nsi", "read") else {},
        "audit_sample": get_audit_logs(limit=120) if actor.get("role") == "Директор" else [],
    }


@router.get("/api/erp/processes")
def get_erp_processes(request: Request, project_id: int = 0, client_id: int = 0, status: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "requests", "read"):
        return {"error": "forbidden"}
    rows = list_erp_process_runs(project_id=project_id, client_id=client_id, status=status, limit=300)
    rows = [row for row in rows if _can_access_process(actor, row)]
    return _enrich_process_rows(rows)


@router.get("/api/erp/processes/{process_id}")
def get_erp_process_detail(process_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "requests", "read"):
        return {"error": "forbidden"}
    process = get_erp_process_run(process_id)
    if not process:
        return {"error": "not_found"}
    if not _can_access_process(actor, process):
        return {"error": "forbidden"}
    process = _enrich_process_rows([process])[0]
    return {
        "process": process,
        "links": list_erp_links(process_id),
        "audit": list_erp_process_audit(process_id),
    }


@router.post("/api/erp/processes/start")
def start_erp_process(data: ERPFlowStartData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "requests", "route") or has_permission(actor, "requests", "create")):
        return {"error": "forbidden"}
    result = start_erp_process_record_service(
        data,
        actor=actor,
        load_project_payload_fn=lambda project_id: _project_payload(_load_project_row(project_id)) if project_id else None,
        can_edit_project_fn=can_edit_project,
        resolve_master_context_fn=_resolve_master_context,
        default_scenario_fn=_default_scenario_for_request_type,
        autoroute_fn=_autoroute_process_via_rules,
        request_obj=request,
    )
    if result.get("error"):
        return result
    if result.get("process"):
        result["process"] = _enrich_process_rows([result["process"]])[0]
    return result


@router.post("/api/erp/processes/{process_id}/autoroute")
def autoroute_erp_process(process_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "requests", "route"):
        return {"error": "forbidden"}
    result = _autoroute_process_via_rules(process_id, actor, request)
    if result.get("process"):
        result["process"] = _enrich_process_rows([result["process"]])[0]
    return result


@router.post("/api/erp/processes/{process_id}/advance")
def advance_erp_process(process_id: int, data: ERPFlowAdvanceData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "requests", "route"):
        return {"error": "forbidden"}
    actor_flags = dict(actor)
    actor_flags["_can_mark_paid"] = has_permission(actor, "finance", "mark_paid")
    actor_flags["_can_approval_route"] = has_permission(actor, "approvals", "route") or has_permission(actor, "approvals", "create")
    actor_flags["_can_supply_reserve"] = has_permission(actor, "supply", "reserve") or has_permission(actor, "supply", "create")
    actor_flags["_can_supply_write"] = has_permission(actor, "supply", "create") or has_permission(actor, "supply", "update")
    actor_flags["_can_production_write"] = has_permission(actor, "production", "release") or has_permission(actor, "production", "create")
    actor_flags["_can_sales_ship"] = has_permission(actor, "sales", "ship") or has_permission(actor, "sales", "create")
    actor_flags["_can_finance_write"] = has_permission(actor, "finance", "create") or has_permission(actor, "finance", "mark_paid")
    result = advance_erp_process_record_service(
        process_id,
        data,
        actor=actor_flags,
        can_access_process_fn=_can_access_process,
        resolve_master_context_fn=_resolve_master_context,
        insert_approval_step_fn=_insert_approval_step,
        stage_label_fn=_erp_stage_label,
    )
    if result.get("process"):
        result["process"] = _enrich_process_rows([result["process"]])[0]
    return result


@router.get("/api/resources/summary")
def get_resources_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "resources", "read"):
        return {"error": "forbidden"}
    rows = _load_resource_allocations()
    department_load = {}
    overloaded = 0
    for row in rows:
        department = row.get("department") or "Без отдела"
        department_load[department] = department_load.get(department, 0) + int(row.get("load_percent") or 0)
        if int(row.get("load_percent") or 0) >= 85:
            overloaded += 1
    return {
        "metrics": {
            "allocations_total": len(rows),
            "overloaded": overloaded,
            "departments": len({row.get("department") or "" for row in rows}),
            "avg_load": round(sum(int(row.get("load_percent") or 0) for row in rows) / len(rows), 1) if rows else 0,
        },
        "department_load": department_load,
        "recent": rows[:12],
    }


@router.get("/api/resources/allocations")
def get_resource_allocations(request: Request, project_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "resources", "read"):
        return {"error": "forbidden"}
    rows = _load_resource_allocations()
    if project_id:
        rows = [row for row in rows if int(row.get("project_id") or 0) == project_id]
    return rows


@router.post("/api/resources/allocations")
def create_resource_allocation(data: ResourceAllocationData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "resources", "create"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, 0, data.contract_id, data.object_id)
    c.execute(
        """
        INSERT INTO resource_allocations (
            project_id, contract_id, object_id, department, resource_name, role_name, load_percent, date_from, date_to,
            status, comment, crew_name, crew_type, location, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context["project_id"], context["contract_id"], context["object_id"], data.department, data.resource_name, data.role_name, data.load_percent,
            data.date_from, data.date_to, data.status, data.comment, data.crew_name, data.crew_type, data.location, actor.get("email", ""), now, now,
        ),
    )
    allocation_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("resource_allocation_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="resource_allocation", entity_id=str(allocation_id), details={"resource": data.resource_name, "department": data.department, "load_percent": data.load_percent})
    return {"status": "success", "id": allocation_id}


@router.put("/api/resources/allocations/{allocation_id}")
def update_resource_allocation(allocation_id: int, data: ResourceAllocationData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "resources", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, 0, data.contract_id, data.object_id)
    c.execute(
        """
        UPDATE resource_allocations
        SET project_id=?, contract_id=?, object_id=?, department=?, resource_name=?, role_name=?, load_percent=?, date_from=?, date_to=?, status=?, comment=?, crew_name=?, crew_type=?, location=?, updated_at=?
        WHERE id=?
        """,
        (
            context["project_id"], context["contract_id"], context["object_id"], data.department, data.resource_name, data.role_name, data.load_percent,
            data.date_from, data.date_to, data.status, data.comment, data.crew_name, data.crew_type, data.location, now, allocation_id,
        ),
    )
    conn.commit()
    conn.close()
    audit_log("resource_allocation_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="resource_allocation", entity_id=str(allocation_id), details={"resource": data.resource_name, "load_percent": data.load_percent, "status": data.status})
    return {"status": "success"}


@router.delete("/api/resources/allocations/{allocation_id}")
def delete_resource_allocation(allocation_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "resources", "delete"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT resource_name FROM resource_allocations WHERE id=?", (allocation_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    _delete_entity_runtime_links(conn, "resource_allocation", allocation_id)
    c.execute("DELETE FROM resource_allocations WHERE id=?", (allocation_id,))
    conn.commit()
    conn.close()
    audit_log("resource_allocation_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="resource_allocation", entity_id=str(allocation_id), details={"resource": row[0] or ""})
    return {"status": "success"}


@router.get("/api/service/summary")
def get_service_summary(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "service", "read"):
        return {"error": "forbidden"}
    rows = _load_service_cases()
    return {
        "metrics": {
            "open": len([row for row in rows if row.get("status") in {"open", "in_work"}]),
            "overdue_sla": len([row for row in rows if _is_overdue(row.get("status", ""), row.get("sla_deadline", ""))]),
            "warranty": len([row for row in rows if row.get("case_type") == "warranty"]),
            "closed": len([row for row in rows if row.get("status") == "closed"]),
        },
        "recent": rows[:10],
    }


@router.get("/api/service/cases")
def get_service_cases(request: Request, project_id: int = 0, client_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "service", "read"):
        return {"error": "forbidden"}
    rows = _load_service_cases()
    if project_id:
        rows = [row for row in rows if int(row.get("project_id") or 0) == project_id]
    if client_id:
        rows = [row for row in rows if int(row.get("client_id") or 0) == client_id]
    return rows


@router.post("/api/service/cases")
def create_service_case(data: ServiceCaseData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "service", "create"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    c.execute(
        """
        INSERT INTO service_cases (
            project_id, client_id, contract_id, object_id, case_number, title, case_type, status, priority, defect,
            warranty_until, sla_deadline, responsible, resolution, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context["project_id"], context["client_id"], context["contract_id"], context["object_id"], data.case_number, data.title, data.case_type, data.status,
            data.priority, data.defect, data.warranty_until, data.sla_deadline, data.responsible,
            data.resolution, actor.get("email", ""), now, now,
        ),
    )
    case_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("service_case_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="service_case", entity_id=str(case_id), details={"title": data.title, "status": data.status, "case_type": data.case_type})
    if data.responsible:
        create_notification("Новый сервисный кейс", f"{actor.get('name', 'Система')} создал(а) кейс «{data.title}»", user_name=data.responsible, category="service", entity_type="service_case", entity_id=str(case_id))
    return {"status": "success", "id": case_id}


@router.put("/api/service/cases/{case_id}")
def update_service_case(case_id: int, data: ServiceCaseData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "service", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
    c.execute(
        """
        UPDATE service_cases
        SET project_id=?, client_id=?, contract_id=?, object_id=?, case_number=?, title=?, case_type=?, status=?, priority=?, defect=?,
            warranty_until=?, sla_deadline=?, responsible=?, resolution=?, updated_at=?
        WHERE id=?
        """,
        (
            context["project_id"], context["client_id"], context["contract_id"], context["object_id"], data.case_number, data.title, data.case_type, data.status,
            data.priority, data.defect, data.warranty_until, data.sla_deadline, data.responsible,
            data.resolution, now, case_id,
        ),
    )
    conn.commit()
    conn.close()
    audit_log("service_case_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="service_case", entity_id=str(case_id), details={"title": data.title, "status": data.status})
    return {"status": "success"}


@router.delete("/api/service/cases/{case_id}")
def delete_service_case(case_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "service", "delete"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT title FROM service_cases WHERE id=?", (case_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    _delete_entity_runtime_links(conn, "service_case", case_id)
    c.execute("DELETE FROM service_cases WHERE id=?", (case_id,))
    conn.commit()
    conn.close()
    audit_log("service_case_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="service_case", entity_id=str(case_id), details={"title": row[0] or ""})
    return {"status": "success"}


@router.get("/api/budget/summary")
def get_budget_summary(request: Request, project_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    lines = _load_budget_lines()
    if project_id:
        lines = [row for row in lines if int(row.get("project_id") or 0) == project_id]
    return {
        "metrics": {
            "plan_total": round(sum(_safe_float(row.get("plan_amount")) for row in lines), 2),
            "fact_total": round(sum(_safe_float(row.get("fact_amount")) for row in lines), 2),
            "variance_total": round(sum(_safe_float(row.get("fact_amount")) - _safe_float(row.get("plan_amount")) for row in lines), 2),
            "lines_total": len(lines),
        },
        "lines": lines[:50],
    }


@router.get("/api/budget/lines")
def get_budget_lines(request: Request, project_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    rows = _load_budget_lines()
    if project_id:
        rows = [row for row in rows if int(row.get("project_id") or 0) == project_id]
    return rows


@router.post("/api/budget/lines")
def create_budget_line(data: BudgetLineData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "create"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO project_budget_lines (
            project_id, line_type, category, plan_amount, fact_amount, comment, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (data.project_id, data.line_type, data.category, data.plan_amount, data.fact_amount, data.comment, actor.get("email", ""), now, now),
    )
    line_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("budget_line_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="budget_line", entity_id=str(line_id), details={"category": data.category, "plan": data.plan_amount, "fact": data.fact_amount})
    return {"status": "success", "id": line_id}


@router.put("/api/budget/lines/{line_id}")
def update_budget_line(line_id: int, data: BudgetLineData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE project_budget_lines
        SET project_id=?, line_type=?, category=?, plan_amount=?, fact_amount=?, comment=?, updated_at=?
        WHERE id=?
        """,
        (data.project_id, data.line_type, data.category, data.plan_amount, data.fact_amount, data.comment, now, line_id),
    )
    conn.commit()
    conn.close()
    audit_log("budget_line_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="budget_line", entity_id=str(line_id), details={"category": data.category, "plan": data.plan_amount, "fact": data.fact_amount})
    return {"status": "success"}


@router.delete("/api/budget/lines/{line_id}")
def delete_budget_line(line_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "delete"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT category FROM project_budget_lines WHERE id=?", (line_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not_found"}
    _delete_entity_runtime_links(conn, "budget_line", line_id)
    c.execute("DELETE FROM project_budget_lines WHERE id=?", (line_id,))
    conn.commit()
    conn.close()
    audit_log("budget_line_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="budget_line", entity_id=str(line_id), details={"category": row[0] or ""})
    return {"status": "success"}


def _seed_full_erp_demo_data(actor: dict, force: bool = False) -> dict:
    actor_email = actor.get("email", "")
    actor_name = actor.get("name", "") or "Демо менеджер"
    now = int(time.time())
    today = datetime.now().strftime("%d.%m.%Y")
    conn = get_connection()
    touched: dict[str, int] = {}
    created = 0
    updated = 0

    def ensure(table_name: str, lookup: dict, payload: dict, entity: str) -> int:
        nonlocal created, updated
        record_id, was_created = _ensure_demo_row(conn, table_name, lookup, payload)
        touched[entity] = touched.get(entity, 0) + 1
        if was_created:
            created += 1
        else:
            updated += 1
        return record_id

    legal_entity_id = ensure("legal_entities", {"inn": "2309001122"}, {"name": "ООО Демо Контур ERP", "short_name": "Демо ERP", "inn": "2309001122", "kpp": "230901001", "ogrn": "1262309001122", "vat_mode": "osno", "default_currency": "RUB", "is_active": 1, "created_at": now, "updated_at": now}, "legal_entities")
    business_unit_id = ensure("business_units", {"code": "DEMO-BU-ERP"}, {"legal_entity_id": legal_entity_id, "name": "Демо проектный офис ERP", "code": "DEMO-BU-ERP", "manager_name": actor_name, "is_active": 1, "created_at": now, "updated_at": now}, "business_units")
    warehouse_id = ensure("warehouse_master", {"code": "DEMO-WH-ERP"}, {"name": "Демо центральный склад", "code": "DEMO-WH-ERP", "is_active": 1, "comment": "ERP demo", "created_at": now, "updated_at": now}, "warehouse_master")
    ensure("position_master", {"code": "DEMO-PM"}, {"name": "Демо менеджер проекта", "code": "DEMO-PM", "department_name": "ERP demo", "is_active": 1, "comment": "", "created_at": now, "updated_at": now}, "position_master")
    ensure("nomenclature", {"article": "DEMO-CABLE-001"}, {"name": "Кабель demo 3x2.5", "article": "DEMO-CABLE-001", "unit": "шт", "price": 1850}, "nomenclature")
    ensure("nomenclature", {"article": "DEMO-SHIELD-001"}, {"name": "Щит demo 24 модуля", "article": "DEMO-SHIELD-001", "unit": "шт", "price": 12400}, "nomenclature")
    client_id = ensure("clients", {"name": ERP_FULL_DEMO_CLIENT_NAME}, {"name": ERP_FULL_DEMO_CLIENT_NAME, "inn": "2310012233", "contact": "demo.erp@korda.local"}, "clients")
    ensure("contacts", {"client_id": client_id, "email": "director@demo-erp.local"}, {"client_id": client_id, "name": "Илья Демов", "phone": "+79991112233", "email": "director@demo-erp.local", "position": "Директор клиента"}, "contacts")
    bank_account_id = ensure("bank_accounts", {"account_number": "40702810900000077777"}, {"name": "Демо расчётный счёт", "bank_name": "Демо Банк", "account_number": "40702810900000077777", "bik": "044525777", "currency": "RUB", "legal_entity_id": legal_entity_id, "is_active": 1, "created_by": actor_email, "created_at": now, "updated_at": now}, "bank_accounts")
    project_ids = {}
    for spec in ERP_FULL_DEMO_PROJECTS:
        row = conn.execute("SELECT id FROM projects WHERE contract=? LIMIT 1", (spec["contract"],)).fetchone()
        project_id = _safe_int(row[0] if row else 0) or _next_table_id(conn, "projects")
        project_ids[spec["key"]] = ensure("projects", {"contract": spec["contract"]}, {"id": project_id, "name": spec["name"], "contract": spec["contract"], "client": ERP_FULL_DEMO_CLIENT_NAME, "manager": actor_name, "status": "active", "progress": spec["progress"], "checkedState": "{}", "comments": "{}", "deadlines": "{}", "budget": spec["budget"], "costs": spec["costs"], "chat": "[]", "files": "[]", "logs": "[]", "team": json.dumps([actor_name, "Мария Демо", "Павел Демо"], ensure_ascii=False), "checklist": json.dumps(["Старт", "Согласование", "Исполнение", "Закрытие"], ensure_ascii=False), "escalations": "{}", "archive_details": "{}", "taskFiles": "{}", "subtasks": "{}", "time_logs": "[]", "allowed_roles": json.dumps(["Директор", "Менеджер", "Бухгалтерия"], ensure_ascii=False), "nomenclature": json.dumps(["DEMO-CABLE-001", "DEMO-SHIELD-001"], ensure_ascii=False)}, "projects")
        object_id = ensure("business_objects", {"code": f"DEMO-OBJ-{spec['key'].upper()}"}, {"client_id": client_id, "name": f"{spec['name']} · Площадка", "code": f"DEMO-OBJ-{spec['key'].upper()}", "address": "Краснодар, ул. Демо, 10", "city": "Краснодар", "region": "Краснодарский край", "responsible_name": actor_name, "responsible_email": actor_email, "comment": "Демо объект", "created_by": actor_email, "created_at": now, "updated_at": now}, "business_objects")
        contract_id = ensure("contract_master", {"contract_number": spec["contract"]}, {"project_id": project_ids[spec["key"]], "client_id": client_id, "object_id": object_id, "contract_number": spec["contract"], "title": spec["name"], "status": "active", "amount": spec["budget"], "currency": "RUB", "start_date": "01.04.2026", "end_date": "31.12.2026", "manager_name": actor_name, "manager_email": actor_email, "comment": "Демо договор", "custom_fields": "[]", "created_by": actor_email, "created_at": now, "updated_at": now}, "contract_master")
        conn.execute("UPDATE projects SET contract_id=?, object_id=? WHERE id=?", (contract_id, object_id, project_ids[spec["key"]]))

    sales_project_id = project_ids["sales"]
    production_project_id = project_ids["production"]
    finance_project_id = project_ids["finance"]
    service_project_id = project_ids["service"]
    docflow_project_id = project_ids["docflow"]
    sales_doc_id = ensure("sales_documents_extended", {"doc_number": "DEMO-SALE-001"}, {"project_id": sales_project_id, "client_id": client_id, "legal_entity_id": legal_entity_id, "business_unit_id": business_unit_id, "doc_type": "invoice", "doc_number": "DEMO-SALE-001", "doc_date": today, "amount": 985000, "currency": "RUB", "status": "shipped", "payment_status": "partial", "linked_payment_id": 0, "comment": "Демо реализация", "created_by": actor_email, "created_at": now, "updated_at": now}, "sales_documents_extended")
    ensure("sales_quotes", {"quote_number": "DEMO-QUOTE-001"}, {"project_id": sales_project_id, "client_id": client_id, "contract_id": 0, "object_id": 0, "title": "Коммерческое предложение на монтаж", "quote_number": "DEMO-QUOTE-001", "stage": "proposal", "amount": 1450000, "currency": "RUB", "valid_until": "31.05.2026", "responsible": actor_name, "probability": 80, "comment": "Демо КП", "created_by": actor_email, "created_at": now, "updated_at": now}, "sales_quotes")
    ensure("purchase_orders", {"project_id": sales_project_id, "item_article": "DEMO-CABLE-001", "supplier": "ООО Демо Снабжение"}, {"project_id": sales_project_id, "client_id": client_id, "legal_entity_id": legal_entity_id, "business_unit_id": business_unit_id, "item_article": "DEMO-CABLE-001", "item_name": "Кабель demo 3x2.5", "supplier": "ООО Демо Снабжение", "qty": 180, "unit": "шт", "unit_price": 1425, "total_amount": 256500, "status": "ordered", "expected_date": "25.04.2026", "received_date": "", "comment": "Демо закупка", "created_by": actor_email, "created_at": now, "updated_at": now}, "purchase_orders")
    ensure("stock_reservations", {"project_id": production_project_id, "nomenclature_article": "DEMO-CABLE-001"}, {"project_id": production_project_id, "legal_entity_id": legal_entity_id, "business_unit_id": business_unit_id, "nomenclature_article": "DEMO-CABLE-001", "nomenclature_name": "Кабель demo 3x2.5", "qty": 42, "status": "reserved", "comment": "Демо резерв", "created_by": actor_email, "created_at": now}, "stock_reservations")
    ensure("inventory_balances", {"article": "DEMO-CABLE-001", "warehouse": "Демо центральный склад", "bin_code": "DEMO-A1"}, {"article": "DEMO-CABLE-001", "warehouse": "Демо центральный склад", "bin_code": "DEMO-A1", "qty": 117, "updated_at": now}, "inventory_balances")
    ensure("inventory_documents", {"doc_number": "DEMO-INV-001"}, {"doc_type": "inventory", "doc_number": "DEMO-INV-001", "article": "DEMO-CABLE-001", "warehouse": "Демо центральный склад", "bin_code": "DEMO-A1", "batch_code": "DEMO-BATCH-01", "serial_no": "", "target_warehouse": "", "target_bin": "", "qty": 117, "counted_qty": 116, "adjustment_qty": -1, "reason": "Контрольный пересчёт", "comment": "Демо инвентаризация", "status": "posted", "actor_email": actor_email, "created_at": now, "updated_at": now}, "inventory_documents")
    production_order_id = ensure("production_orders", {"order_name": "Демо сборка шкафов"}, {"project_id": production_project_id, "client_id": client_id, "legal_entity_id": legal_entity_id, "business_unit_id": business_unit_id, "order_name": "Демо сборка шкафов", "stage": "in_progress", "priority": "high", "planned_start": "18.04.2026", "planned_finish": "30.04.2026", "actual_finish": "", "progress": 58, "responsible": "Павел Демо", "comment": "Демо производственный заказ", "created_by": actor_email, "created_at": now, "updated_at": now}, "production_orders")
    ensure("production_operations", {"order_id": production_order_id, "sequence_no": 1}, {"order_id": production_order_id, "sequence_no": 1, "operation_name": "Резка кабеля", "work_center": "Цех кабельной сборки", "status": "done", "planned_hours": 6, "actual_hours": 5.5, "planned_qty": 120, "completed_qty": 120, "scrap_qty": 1, "labor_rate": 850, "material_cost": 82000, "overhead_cost": 12000, "started_at": "18.04.2026 09:00", "finished_at": "18.04.2026 15:00", "note": "Демо операция", "created_by": actor_email, "created_at": now, "updated_at": now}, "production_operations")
    ensure("production_route_templates", {"order_id": production_order_id, "sequence_no": 1}, {"order_id": production_order_id, "sequence_no": 1, "operation_name": "Резка кабеля", "work_center": "Цех кабельной сборки", "planned_hours": 6, "planned_qty": 120, "labor_rate": 850, "note": "Демо маршрут", "created_by": actor_email, "created_at": now, "updated_at": now}, "production_route_templates")
    ensure("finance_payments", {"title": "Демо исходящий платёж поставщику"}, {"project_id": finance_project_id, "client_id": client_id, "title": "Демо исходящий платёж поставщику", "kind": "outgoing", "category": "payment", "amount": 256500, "currency": "RUB", "due_date": "22.04.2026", "paid_date": "", "status": "approved", "comment": "Демо платёж", "created_by": actor_email, "created_at": now, "updated_at": now}, "finance_payments")
    ensure("finance_payment_requests", {"title": "Демо заявка на оплату поставщику"}, {"project_id": finance_project_id, "client_id": client_id, "legal_entity_id": legal_entity_id, "business_unit_id": business_unit_id, "title": "Демо заявка на оплату поставщику", "amount": 256500, "currency": "RUB", "due_date": "22.04.2026", "approver_name": actor_name, "approval_status": "approved", "request_status": "approved", "linked_payment_id": 0, "comment": "Демо заявка на оплату", "created_by": actor_email, "created_at": now, "updated_at": now}, "finance_payment_requests")
    ensure("finance_budgets", {"budget_type": "dds", "period_key": "2026-04", "project_id": finance_project_id, "article_name": "Операционный cashflow"}, {"budget_type": "dds", "period_key": "2026-04", "project_id": finance_project_id, "business_unit_id": business_unit_id, "article_name": "Операционный cashflow", "plan_amount": 780000, "fact_amount": 542000, "status": "in_work", "comment": "Демо бюджет ДДС", "created_by": actor_email, "created_at": now, "updated_at": now}, "finance_budgets")
    ensure("bank_statement_lines", {"external_line_id": "DEMO-STMT-001"}, {"bank_account_id": bank_account_id, "line_date": today, "amount": 985000, "direction": "incoming", "counterparty": ERP_FULL_DEMO_CLIENT_NAME, "purpose": "Оплата по DEMO-SALE-001", "client_id": client_id, "linked_payment_id": 0, "external_line_id": "DEMO-STMT-001", "status": "imported", "comment": "Демо выписка банка", "created_by": actor_email, "created_at": now, "updated_at": now}, "bank_statement_lines")
    ensure("expense_requests", {"title": "Демо заявка на расход по проекту"}, {"project_id": service_project_id, "client_id": client_id, "title": "Демо заявка на расход по проекту", "request_type": "expense", "amount": 42000, "currency": "RUB", "approver_role": "Директор", "approver_name": actor_name, "due_date": "24.04.2026", "linked_payment_id": 0, "status": "approved", "comment": "Демо расход", "created_by": actor_email, "approved_by": actor_email, "created_at": now, "updated_at": now}, "expense_requests")
    request_id = ensure("internal_requests", {"title": "Демо внутренняя заявка на материалы"}, {"project_id": service_project_id, "title": "Демо внутренняя заявка на материалы", "request_type": "purchase", "target_role": "Снабжение", "assignee_name": "Мария Демо", "priority": "high", "status": "in_work", "deadline": "23.04.2026", "comment": "Демо внутренняя заявка", "created_by": actor_email, "created_at": now, "updated_at": now}, "internal_requests")
    ensure("resource_allocations", {"project_id": service_project_id, "resource_name": "Павел Демо"}, {"project_id": service_project_id, "department": "Сервис и монтаж", "resource_name": "Павел Демо", "role_name": "Инженер", "load_percent": 78, "date_from": "18.04.2026", "date_to": "27.04.2026", "status": "planned", "comment": "Демо загрузка ресурса", "created_by": actor_email, "created_at": now, "updated_at": now}, "resource_allocations")
    ensure("service_cases", {"case_number": "DEMO-SVC-001"}, {"project_id": service_project_id, "client_id": client_id, "case_number": "DEMO-SVC-001", "title": "Демо сервисный кейс по щиту", "case_type": "maintenance", "status": "waiting_client", "priority": "high", "defect": "Повторный выезд после монтажа", "warranty_until": "31.12.2026", "sla_deadline": "25.04.2026", "responsible": "Павел Демо", "resolution": "", "created_by": actor_email, "created_at": now, "updated_at": now}, "service_cases")
    ensure("project_budget_lines", {"project_id": service_project_id, "category": "Демо сервисные расходы"}, {"project_id": service_project_id, "line_type": "cost", "category": "Демо сервисные расходы", "plan_amount": 125000, "fact_amount": 84000, "comment": "Демо бюджетная строка", "created_by": actor_email, "created_at": now, "updated_at": now}, "project_budget_lines")
    process_id = ensure("erp_process_runs", {"title": "Демо ERP-процесс закупки"}, {"title": "Демо ERP-процесс закупки", "project_id": sales_project_id, "client_id": client_id, "request_type": "purchase", "scenario": json.dumps(["request", "approval", "purchase"], ensure_ascii=False), "due_date": "28.04.2026", "amount": 256500, "currency": "RUB", "status": "in_progress", "current_stage": "purchase", "request_id": request_id, "approval_id": 0, "reservation_id": 0, "purchase_id": 0, "production_id": 0, "sales_doc_id": sales_doc_id, "payment_id": 0, "created_by": actor_email, "updated_by": actor_email, "payload": json.dumps({"demo": True}, ensure_ascii=False), "created_at": now, "updated_at": now}, "erp_process_runs")
    ensure("document_templates", {"title": "Демо шаблон УПД", "version_label": "v1"}, {"title": "Демо шаблон УПД", "doc_type": "outgoing", "template_kind": "editable", "version_label": "v1", "body_text": "Демо шаблон УПД для презентации", "variables_json": json.dumps(["client", "contract", "amount"], ensure_ascii=False), "status": "active", "comment": "Демо шаблон документа", "created_by": actor_email, "created_at": now, "updated_at": now}, "document_templates")
    document_id = ensure("documents", {"number": "DEMO-DOC-001"}, {"id": 0, "type": "outgoing", "number": "DEMO-DOC-001", "d_date": today, "correspondent": ERP_FULL_DEMO_CLIENT_NAME, "subject": "Демо пакет документов по сделке", "status": "approved", "file_url": "/generated/demo-doc-001.pdf", "qr_code": "", "resolution": "Подготовить и подписать", "resolution_author": actor_name, "resolution_deadline": "26.04.2026", "resolution_assignee": "Мария Демо", "resolution_task_id": 0}, "documents")
    task_id = ensure("tasks", {"title": "Демо поручение по документам"}, {"id": 0, "title": "Демо поручение по документам", "description": "Подготовить комплект УПД и архив", "author": actor_name, "executor": "Мария Демо", "deadline": "26.04.2026", "status": "В работе", "created_at": today}, "tasks")
    conn.execute("UPDATE documents SET resolution_task_id=? WHERE id=?", (task_id, document_id))
    ensure("document_versions", {"document_id": document_id, "version_label": "v1"}, {"document_id": document_id, "version_no": 1, "version_label": "v1", "version_status": "approved", "payload": json.dumps({"subject": "Демо пакет документов по сделке"}, ensure_ascii=False), "file_url": "/generated/demo-doc-001-v1.docx", "comment": "Демо версия", "created_by": actor_email, "created_at": now}, "document_versions")
    ensure("edo_certificates", {"thumbprint": "DEMO-CERT-001"}, {"owner_name": actor_name, "owner_email": actor_email, "signer_role": "Директор", "provider_name": "1С-ЭДО", "thumbprint": "DEMO-CERT-001", "serial_number": "SERIAL-DEMO-001", "valid_from": "01.01.2026", "valid_to": "31.12.2026", "status": "active", "comment": "Демо сертификат", "created_by": actor_email, "created_at": now, "updated_at": now}, "edo_certificates")
    ensure("integration_field_mappings", {"system_name": "1C", "entity_type": "sales_document", "local_field": "doc_number", "external_field": "Number"}, {"system_name": "1C", "entity_type": "sales_document", "local_field": "doc_number", "external_field": "Number", "direction": "bidirectional", "transform_rule": "", "is_required": 1, "is_active": 1, "created_by": actor_email, "created_at": now, "updated_at": now}, "integration_field_mappings")
    ensure("integration_connectors", {"connector_type": "1c", "provider_name": "Демо обмен 1С"}, {"connector_type": "1c", "provider_name": "Демо обмен 1С", "status": "active", "settings_json": json.dumps({"mode": "demo"}, ensure_ascii=False), "scope_json": json.dumps({"projects": list(project_ids.values())}, ensure_ascii=False), "last_sync_at": now, "last_error": "", "created_by": actor_email, "created_at": now, "updated_at": now}, "integration_connectors")
    ensure("integration_sync_queue", {"entity_type": "sales_document", "entity_id": sales_doc_id}, {"system_name": "1C", "entity_type": "sales_document", "entity_id": sales_doc_id, "direction": "outbound", "payload": json.dumps({"doc_number": "DEMO-SALE-001"}, ensure_ascii=False), "mapping_key": "sales_document", "state": "queued", "retry_count": 0, "last_error": "", "external_id": "", "next_retry_at": 0, "locked_at": 0, "created_by": actor_email, "created_at": now, "updated_at": now}, "integration_sync_queue")
    telephony_account_id = ensure("telephony_accounts", {"provider_name": "Демо АТС", "line_name": "Линия отдела продаж"}, {"provider_name": "Демо АТС", "line_name": "Линия отдела продаж", "external_line_id": "DEMO-LINE-001", "is_active": 1, "created_by": actor_email, "created_at": now, "updated_at": now}, "telephony_accounts")
    ensure("telephony_calls", {"account_id": telephony_account_id, "phone_number": "+79991112233", "call_at": "17.04.2026 11:20"}, {"account_id": telephony_account_id, "client_id": client_id, "project_id": sales_project_id, "contact_name": "Илья Демов", "phone_number": "+79991112233", "direction": "inbound", "status": "answered", "duration_sec": 352, "call_at": "17.04.2026 11:20", "summary": "Уточнение по КП и срокам поставки", "recording_url": "", "created_by": actor_email, "created_at": now}, "telephony_calls")
    ensure("saved_reports", {"title": "Пример панели директора"}, {"report_type": "executive", "title": "Пример панели директора", "filters": json.dumps({"project_ids": list(project_ids.values())}, ensure_ascii=False), "layout": json.dumps({"widgets": ["pnl", "cash_gap", "service_deadlines"]}, ensure_ascii=False), "scope": "company", "owner_email": actor_email, "created_at": now, "updated_at": now}, "saved_reports")
    conn.commit()
    conn.close()
    return {"status": "success", "created": created, "updated": updated, "client_id": client_id, "projects": [{"key": spec["key"], "id": project_ids[spec["key"]], "name": spec["name"], "contract": spec["contract"]} for spec in ERP_FULL_DEMO_PROJECTS], "touched": touched, "message": "Пример ERP-данных подготовлен. Можно открывать продажи, закупки, склад, производство, финансы и сервис."}


@router.post("/api/demo/full-seed")
def seed_full_demo(request: Request, force: int = 0):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    result = _seed_full_erp_demo_data(actor, bool(force))
    audit_log("erp_full_demo_seed", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="erp_demo", entity_id=str(result.get("client_id") or 0), details={"force": bool(force), "created": result.get("created"), "updated": result.get("updated"), "projects": result.get("projects", [])})
    return result


def _load_executive_boardroom(finance_rows: list[dict], resource_rows: list[dict], service_rows: list[dict]) -> dict:
    now_ts = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        approval_rows = []
        integration_rows = []
        if _table_exists(conn, "approvals"):
            approval_rows = [dict(row) for row in conn.execute("SELECT * FROM approvals WHERE status IN ('pending', 'rework') ORDER BY due_at ASC, id DESC LIMIT 120").fetchall()]
        if _table_exists(conn, "integration_sync_queue"):
            integration_rows = [dict(row) for row in conn.execute("SELECT * FROM integration_sync_queue WHERE state IN ('queued', 'retry', 'failed', 'processing', 'conflict') ORDER BY updated_at DESC, id DESC LIMIT 120").fetchall()]
    finally:
        conn.close()

    overdue_receivables = [row for row in finance_rows if row.get("kind") == "incoming" and _is_overdue(row.get("status", ""), row.get("due_date", ""))]
    overdue_payables = [row for row in finance_rows if row.get("kind") == "outgoing" and _is_overdue(row.get("status", ""), row.get("due_date", ""))]
    approval_overdue = [row for row in approval_rows if _safe_int(row.get("due_at")) and _safe_int(row.get("due_at")) <= now_ts]
    approval_due_soon = [row for row in approval_rows if _safe_int(row.get("due_at")) and now_ts < _safe_int(row.get("due_at")) <= now_ts + 4 * 3600]
    service_sla_breached = [row for row in service_rows if row.get("status") in {"open", "in_work", "waiting_client"} and _is_overdue("issued", row.get("sla_deadline", ""))]
    resource_hotspots = [row for row in resource_rows if _safe_int(row.get("load_percent")) >= 100]
    resource_watch = [row for row in resource_rows if 85 <= _safe_int(row.get("load_percent")) < 100]
    integration_incidents = [row for row in integration_rows if row.get("state") in {"failed", "retry", "conflict"}]

    bottlenecks = []
    for row in sorted(approval_overdue, key=lambda item: _safe_int(item.get("due_at")) or now_ts)[:4]:
        assignees = _json_load(row.get("current_assignees"), [])
        bottlenecks.append({
            "category": "approval",
            "priority": 100,
            "title": row.get("title") or f"Согласование #{row.get('id')}",
            "meta": f"Этап согласования · назначено {', '.join(assignees[:2]) if assignees else 'без исполнителя'}",
            "severity": "critical",
            "target_view": "approvals",
            "action_label": "Согласования",
            "amount": 0,
        })
    for row in sorted(service_sla_breached, key=lambda item: _parse_ru_date(item.get("sla_deadline", "")) or datetime.max)[:4]:
        bottlenecks.append({
            "category": "sla",
            "priority": 90,
            "title": row.get("title") or row.get("case_number") or "Сервисный кейс",
            "meta": f"Срок реакции до {row.get('sla_deadline') or 'не задан'} · ответственный {row.get('responsible') or 'не назначен'}",
            "severity": "critical",
            "target_view": "services",
            "action_label": "Сервис",
            "amount": 0,
        })
    for row in sorted(overdue_receivables, key=lambda item: _safe_float(item.get("amount")), reverse=True)[:4]:
        bottlenecks.append({
            "category": "cash",
            "priority": 80,
            "title": row.get("title") or "Просроченная дебиторка",
            "meta": f"Входящий платёж просрочен до {row.get('due_date') or 'дата не задана'}",
            "severity": "warning",
            "target_view": "finance",
            "action_label": "Финансы",
            "amount": round(_safe_float(row.get("amount")), 2),
        })
    for row in sorted(resource_hotspots + resource_watch, key=lambda item: _safe_int(item.get("load_percent")), reverse=True)[:4]:
        bottlenecks.append({
            "category": "resource",
            "priority": 70,
            "title": row.get("resource_name") or "Ресурс",
            "meta": f"{row.get('department') or 'Команда'} · загрузка {_safe_int(row.get('load_percent'))}%",
            "severity": "critical" if _safe_int(row.get("load_percent")) >= 100 else "warning",
            "target_view": "resources",
            "action_label": "Ресурсы",
            "amount": _safe_int(row.get("load_percent")),
        })
    for row in integration_incidents[:4]:
        bottlenecks.append({
            "category": "integration",
            "priority": 60,
            "title": f"{row.get('system_name') or 'Интеграция'} · {_entity_label(row.get('entity_type') or 'entity')}",
            "meta": row.get("last_error") or f"Состояние {_status_label(row.get('state'))}",
            "severity": "warning",
            "target_view": "operations",
            "action_label": "Операционный центр",
            "amount": 0,
        })
    bottlenecks.sort(key=lambda item: (item.get("priority", 0), item.get("amount", 0)), reverse=True)
    heatmap = [
        {"category": "approval", "label": "Согласования", "critical": len(approval_overdue), "warning": len(approval_due_soon), "target_view": "approvals"},
        {"category": "sla", "label": "Сервисные сроки", "critical": len(service_sla_breached), "warning": len([row for row in service_rows if row.get("status") in {"open", "in_work"}]), "target_view": "services"},
        {"category": "cash", "label": "Кассовые риски", "critical": len(overdue_receivables), "warning": len(overdue_payables), "target_view": "finance"},
        {"category": "resource", "label": "Ресурсная перегрузка", "critical": len(resource_hotspots), "warning": len(resource_watch), "target_view": "resources"},
        {"category": "integration", "label": "Интеграции", "critical": len([row for row in integration_incidents if row.get("state") in {"failed", "conflict"}]), "warning": len([row for row in integration_rows if row.get("state") in {"queued", "processing", "retry"}]), "target_view": "operations"},
    ]
    return {
        "metrics": {
            "approval_overdue": len(approval_overdue),
            "approval_due_soon": len(approval_due_soon),
            "service_sla_breached": len(service_sla_breached),
            "cash_overdue_receivables": round(sum(_safe_float(row.get("amount")) for row in overdue_receivables), 2),
            "cash_overdue_payables": round(sum(_safe_float(row.get("amount")) for row in overdue_payables), 2),
            "resource_hotspots": len(resource_hotspots),
            "resource_watch": len(resource_watch),
            "integration_incidents": len(integration_incidents),
        },
        "bottlenecks": bottlenecks[:10],
        "heatmap": heatmap,
    }


@router.get("/api/executive/summary")
def get_executive_summary(request: Request):
    actor = require_director(request)
    if not actor or not has_permission(actor, "executive", "read"):
        return {"error": "forbidden"}
    projects = get_projs(request)
    if isinstance(projects, dict) and projects.get("error"):
        return projects
    finance_rows = _load_finance_rows()
    expense_rows = _load_expense_request_rows()
    request_rows = _load_internal_request_rows()
    resource_rows = _load_resource_allocations()
    service_rows = _load_service_cases()
    purchase_rows = _load_purchase_rows()
    sales_rows = _load_sales_rows()
    budget_lines = _load_budget_lines()
    production_rows = _load_production_rows()
    discrepancy_rows = _load_inventory_discrepancy_rows(limit=200)
    boardroom = _load_executive_boardroom(finance_rows, resource_rows, service_rows)
    bottleneck_map = {}
    for item in _load_production_operation_rows():
        key = item.get("work_center") or "Без участка"
        entry = bottleneck_map.setdefault(key, {"work_center": key, "operations": 0, "hours": 0.0, "active": 0})
        entry["operations"] += 1
        entry["hours"] += _safe_float(item.get("planned_hours"))
        if item.get("status") in {"in_progress", "otk"}:
            entry["active"] += 1
    bottleneck_rows = sorted(bottleneck_map.values(), key=lambda item: (item["active"], item["hours"]), reverse=True)

    project_cards = []
    for project in projects[:]:
        project_id = int(project.get("id") or 0)
        incoming_open = sum(_safe_float(row.get("amount")) for row in finance_rows if int(row.get("project_id") or 0) == project_id and row.get("kind") == "incoming" and row.get("status") != "paid")
        outgoing_open = sum(_safe_float(row.get("amount")) for row in finance_rows if int(row.get("project_id") or 0) == project_id and row.get("kind") == "outgoing" and row.get("status") != "paid")
        purchase_total = sum(_safe_float(row.get("total_amount")) for row in purchase_rows if int(row.get("project_id") or 0) == project_id)
        budget_plan = sum(_safe_float(row.get("plan_amount")) for row in budget_lines if int(row.get("project_id") or 0) == project_id)
        budget_fact = sum(_safe_float(row.get("fact_amount")) for row in budget_lines if int(row.get("project_id") or 0) == project_id)
        margin = _safe_float(project.get("budget")) - max(_safe_float(project.get("costs")), purchase_total, budget_fact)
        risk_score = 0
        if incoming_open < outgoing_open:
            risk_score += 1
        if project.get("status") == "active" and int(project.get("progress") or 0) < 50 and outgoing_open > 0:
            risk_score += 1
        if any(_is_overdue(row.get("status", ""), row.get("due_date", "")) for row in finance_rows if int(row.get("project_id") or 0) == project_id):
            risk_score += 1
        project_cards.append({
            "id": project_id,
            "name": project.get("name", "Проект"),
            "contract": project.get("contract", "—"),
            "manager": project.get("manager", ""),
            "incoming_open": round(incoming_open, 2),
            "outgoing_open": round(outgoing_open, 2),
            "purchase_total": round(purchase_total, 2),
            "budget_plan": round(budget_plan, 2),
            "budget_fact": round(budget_fact, 2),
            "margin": round(margin, 2),
            "risk_score": risk_score,
        })
    project_cards.sort(key=lambda item: (-item["risk_score"], item["margin"]))
    overloaded = sorted(resource_rows, key=lambda row: int(row.get("load_percent") or 0), reverse=True)
    return {
        "metrics": {
            "projects_active": len([project for project in projects if project.get("status") == "active"]),
            "cash_gap": round(sum(_safe_float(row.get("amount")) for row in finance_rows if row.get("kind") == "incoming") - sum(_safe_float(row.get("amount")) for row in finance_rows if row.get("kind") == "outgoing"), 2),
            "expense_pending": round(sum(_safe_float(row.get("amount")) for row in expense_rows if row.get("status") in {"pending", "approved"}), 2),
            "resource_overloaded": len([row for row in resource_rows if int(row.get("load_percent") or 0) >= 85]),
            "service_open": len([row for row in service_rows if row.get("status") in {"open", "in_work"}]),
            "production_overdue": len([row for row in production_rows if row.get("stage") != "done" and (row.get("planned_finish") or "") and _is_overdue("issued", row.get("planned_finish") or "")]),
            "inventory_discrepancies": len(discrepancy_rows),
            "blocked_approvals": boardroom["metrics"]["approval_overdue"],
            "approval_due_soon": boardroom["metrics"]["approval_due_soon"],
            "service_sla_breached": boardroom["metrics"]["service_sla_breached"],
            "cash_overdue_receivables": boardroom["metrics"]["cash_overdue_receivables"],
            "cash_overdue_payables": boardroom["metrics"]["cash_overdue_payables"],
            "resource_hotspots": boardroom["metrics"]["resource_hotspots"],
            "integration_incidents": boardroom["metrics"]["integration_incidents"],
        },
        "risk_projects": project_cards[:8],
        "overloaded_resources": overloaded[:8],
        "pending_expenses": [row for row in expense_rows if row.get("status") in {"pending", "approved"}][:8],
        "internal_requests": [row for row in request_rows if row.get("status") in {"new", "in_work"}][:8],
        "service_cases": [row for row in service_rows if row.get("status") in {"open", "in_work"}][:8],
        "production_bottlenecks": bottleneck_rows[:8],
        "inventory_discrepancies": discrepancy_rows[:8],
        "boardroom_bottlenecks": boardroom["bottlenecks"],
        "boardroom_heatmap": boardroom["heatmap"],
        "sales_total": round(sum(_safe_float(row.get("amount")) for row in sales_rows), 2),
    }


@router.get("/api/projects/{proj_id}/ops")
def get_project_ops_summary(proj_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    existing = _load_project_row(proj_id)
    if not existing:
        return {"error": "not_found"}
    project = _project_payload(existing)
    if not can_access_project(actor, project):
        return {"error": "forbidden"}
    finance = [row for row in _load_finance_rows() if int(row.get("project_id") or 0) == proj_id]
    purchases = [row for row in _load_purchase_rows() if int(row.get("project_id") or 0) == proj_id]
    sales = [row for row in _load_sales_rows() if int(row.get("project_id") or 0) == proj_id]
    production = [row for row in _load_production_rows() if int(row.get("project_id") or 0) == proj_id]
    reservations = [row for row in _load_stock_reservations() if int(row.get("project_id") or 0) == proj_id]
    expenses = [row for row in _load_expense_request_rows() if int(row.get("project_id") or 0) == proj_id]
    requests = [row for row in _load_internal_request_rows() if int(row.get("project_id") or 0) == proj_id]
    resources = [row for row in _load_resource_allocations() if int(row.get("project_id") or 0) == proj_id]
    service = [row for row in _load_service_cases() if int(row.get("project_id") or 0) == proj_id]
    epl_waybills = [row for row in _load_epl_waybill_rows() if int(row.get("project_id") or 0) == proj_id]
    budget_lines = [row for row in _load_budget_lines() if int(row.get("project_id") or 0) == proj_id]
    purchase_total = round(sum(_safe_float(row.get("total_amount")) for row in purchases), 2)
    budget_plan = round(sum(_safe_float(row.get("plan_amount")) for row in budget_lines), 2)
    budget_fact = round(sum(_safe_float(row.get("fact_amount")) for row in budget_lines), 2)
    open_expenses = round(sum(_safe_float(row.get("amount")) for row in expenses if row.get("status") in {"pending", "approved"}), 2)
    return {
        "finance": {
            "incoming_open": round(sum(_safe_float(row.get("amount")) for row in finance if row.get("kind") == "incoming" and row.get("status") != "paid"), 2),
            "outgoing_open": round(sum(_safe_float(row.get("amount")) for row in finance if row.get("kind") == "outgoing" and row.get("status") != "paid"), 2),
            "paid_total": round(sum(_safe_float(row.get("amount")) for row in finance if row.get("status") == "paid"), 2),
        },
        "budget": {
            "contract_total": round(_safe_float(project.get("budget")), 2),
            "project_costs": round(_safe_float(project.get("costs")), 2),
            "purchase_total": purchase_total,
            "budget_plan": budget_plan,
            "budget_fact": budget_fact,
            "open_expenses": open_expenses,
            "margin_estimate": round(_safe_float(project.get("budget")) - max(_safe_float(project.get("costs")), purchase_total, budget_fact), 2),
        },
        "purchases": purchases[:6],
        "sales": sales[:6],
        "production": production[:6],
        "reservations": reservations[:6],
        "expenses": expenses[:6],
        "requests": requests[:6],
        "resources": resources[:6],
        "service": service[:6],
        "epl_waybills": epl_waybills[:6],
        "epl_metrics": {
            "total": len(epl_waybills),
            "on_route": len([row for row in epl_waybills if row.get("status") == "on_route"]),
            "ready": len([row for row in epl_waybills if row.get("integration_status") == "ready"]),
            "blocked": len([row for row in epl_waybills if row.get("missing_stages")]),
        },
    }

# === РОУТЕРЫ НСИ И СКЛАДА ===
@router.get("/api/nsi/master_data")
def get_nsi_master_data(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    return _load_nsi_master_data(actor)


def _validate_nsi_master_record(entity_type: str, data: NSIMasterRecordData) -> str | None:
    if entity_type in {"warehouses", "units", "groups", "positions", "characteristics", "income_expense_articles", "operation_types"} and not _normalize_spaces(data.name):
        return "name_required"
    if entity_type == "employees":
        if not _normalize_spaces(data.name):
            return "name_required"
        if not _safe_int(data.legal_entity_id):
            return "legal_entity_required"
        if not _safe_int(data.position_id):
            return "position_required"
    if entity_type == "storage_cells":
        if not _safe_int(data.warehouse_id):
            return "warehouse_required"
        if not _normalize_spaces(data.name):
            return "name_required"
    if entity_type == "income_expense_articles" and _normalize_spaces(data.article_kind) not in {"income", "expense"}:
        return "article_kind_invalid"
    if entity_type == "financial_responsibility_centers":
        if not _normalize_spaces(data.name):
            return "name_required"
        if not _safe_int(data.legal_entity_id):
            return "legal_entity_required"
        if not _safe_int(data.business_unit_id):
            return "business_unit_required"
    if entity_type == "operation_types":
        if not _normalize_spaces(data.module_name):
            return "module_name_required"
        if not _normalize_spaces(data.flow_kind):
            return "flow_kind_required"
    if entity_type == "bank_accounts":
        if not _safe_int(data.legal_entity_id):
            return "legal_entity_required"
        if not _normalize_spaces(data.bank_name):
            return "bank_name_required"
        if not _normalize_spaces(data.account_number):
            return "account_number_required"
        if not _normalize_spaces(data.bik):
            return "bik_required"
        if not _normalize_spaces(data.name):
            return "name_required"
    return None


def _save_nsi_master_record(entity_type: str, item_id: int, data: NSIMasterRecordData, actor: dict):
    config = _nsi_master_config(entity_type)
    if not config:
        return {"error": "invalid_entity_type"}
    if config.get("finance_only") and not (has_permission(actor, "finance", "manage_master") or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    validation_error = _validate_nsi_master_record(entity_type, data)
    if validation_error:
        return {"error": validation_error}
    if entity_type in {"bank_accounts", "financial_responsibility_centers", "employees"} and (_safe_int(data.legal_entity_id) or _safe_int(data.business_unit_id)) and not _assert_finance_scope(actor, _safe_int(data.legal_entity_id), _safe_int(data.business_unit_id)):
        return {"error": "forbidden_scope"}
    conn = get_connection()
    try:
        c = conn.cursor()
        values = list(config["payload"](data))
        candidate = dict(zip(config["fields"], values))
        gate = _nsi_mdm_validate_row(conn, entity_type, candidate, item_id)
        if gate.get("duplicates"):
            return {"error": "duplicate_candidate", "duplicates": gate.get("duplicates", [])}
        blocking_issues = [issue for issue in gate.get("issues", []) if issue.get("severity") == "error"]
        if blocking_issues:
            return {"error": "validation_error", "issues": blocking_issues}
        if item_id:
            placeholders = ", ".join(f"{field}=?" for field in config["fields"])
            c.execute(f"UPDATE {config['table']} SET {placeholders} WHERE id=?", (*values, item_id))
            record_id = item_id
            action = "updated"
        else:
            insert_fields = [field for field in config["fields"] if field != "updated_at"]
            insert_values = values[:-1] if "updated_at" in config["fields"] else values[:]
            insert_fields.append("created_at")
            insert_values.append(int(time.time()))
            c.execute(
                f"INSERT INTO {config['table']} ({', '.join(insert_fields)}) VALUES ({', '.join(['?'] * len(insert_fields))})",
                tuple(insert_values),
            )
            record_id = c.lastrowid
            action = "created"
        report = _nsi_mdm_validate_row(conn, entity_type, _nsi_mdm_load_row(conn, entity_type, record_id), record_id)
        _nsi_mdm_update_row_state(conn, entity_type, record_id, report)
        version_no = _record_nsi_mdm_version(conn, entity_type, record_id, actor, action)
        if _sync_entity_meta(entity_type):
            _upsert_entity_sync_job(conn, entity_type, record_id, actor.get("email", ""))
        conn.commit()
    except DatabaseIntegrityError as exc:
        conn.rollback()
        detail = str(exc).lower()
        if "unique constraint failed" in detail or "duplicate key" in detail:
            raise HTTPException(status_code=409, detail="duplicate_code")
        raise HTTPException(status_code=400, detail="nsi_master_save_failed")
    finally:
        conn.close()
    audit_log(
        f"{config['label']}_{action}",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type=config["label"],
        entity_id=str(record_id),
        details={"name": _normalize_spaces(data.name), "code": _normalize_spaces(data.code)},
    )
    return {"status": "success", "id": record_id, "mdm_status": "pending_approval", "version_no": version_no}


def _can_manage_nsi_entity(actor: dict, entity_type: str, config: dict | None = None) -> bool:
    config = config or _nsi_master_config(entity_type)
    if not config:
        return False
    if not has_permission(actor, "nsi", "update") and actor.get("role") != "Директор":
        return False
    if config.get("finance_only") and not (has_permission(actor, "finance", "manage_master") or actor.get("role") == "Директор"):
        return False
    return True


def _queue_nsi_master_sync_job(conn, entity_type: str, item_id: int, actor: dict):
    config = _nsi_master_config(entity_type)
    if not config:
        return {"error": "invalid_entity_type"}
    if not _can_manage_nsi_entity(actor, entity_type, config):
        return {"error": "forbidden"}
    if not _sync_entity_meta(entity_type):
        return {"error": "sync_not_supported"}
    entity = _load_sync_entity_row(conn, entity_type, item_id)
    if not entity:
        return {"error": "not_found"}
    legal_entity_id = _safe_int(entity.get("legal_entity_id"))
    business_unit_id = _safe_int(entity.get("business_unit_id"))
    if entity_type in {"bank_accounts", "financial_responsibility_centers", "employees"} and (legal_entity_id or business_unit_id):
        if not _assert_finance_scope(actor, legal_entity_id, business_unit_id):
            return {"error": "forbidden_scope"}
    queue_id = _upsert_entity_sync_job(conn, entity_type, item_id, actor.get("email", ""))
    return {"status": "success", "queue_id": queue_id, "entity": entity}


def _nsi_hierarchy_parent_path(conn, hierarchy_type: str, entity_type: str, parent_entity_id: int) -> tuple[str, int]:
    if not _safe_int(parent_entity_id):
        return "", 0
    row = _select_one_dict(
        conn,
        """
        SELECT path_code, level_no
        FROM nsi_hierarchies
        WHERE hierarchy_type=? AND entity_type=? AND entity_id=? AND is_active=1
        ORDER BY updated_at DESC, id DESC LIMIT 1
        """,
        (hierarchy_type, entity_type, _safe_int(parent_entity_id)),
    )
    return row.get("path_code", ""), _safe_int(row.get("level_no"))


def _nsi_classifier_item(data: NSIExternalClassifierImportData, raw: dict) -> dict:
    classifier_type = _normalize_spaces(data.classifier_type).lower()
    code = _normalize_spaces(raw.get("external_code") or raw.get("code") or raw.get("bik") or raw.get("fias_id") or raw.get("kladr_code") or raw.get("okei_code") or raw.get("okved") or raw.get("okpd2"))
    name = _normalize_spaces(raw.get("name") or raw.get("bank_name") or raw.get("address") or raw.get("full_name") or raw.get("title"))
    parent_code = _normalize_spaces(raw.get("external_parent_code") or raw.get("parent_code") or raw.get("parent"))
    if classifier_type in {"banks", "bank", "bik"}:
        classifier_type = "banks"
        code = code or _normalize_spaces(raw.get("bic"))
        name = name or _normalize_spaces(raw.get("bank"))
    elif classifier_type in {"addresses", "address", "fias", "kladr"}:
        classifier_type = "addresses"
        code = code or hashlib.sha1(name.encode("utf-8")).hexdigest()[:16] if name else ""
    elif classifier_type in {"units", "unit", "okei"}:
        classifier_type = "units"
    elif classifier_type in {"okved", "okved2"}:
        classifier_type = "okved"
    elif classifier_type in {"okpd", "okpd2"}:
        classifier_type = "okpd2"
    return {
        "classifier_type": classifier_type,
        "source_system": _normalize_spaces(data.source_system) or "manual",
        "external_code": code,
        "external_parent_code": parent_code,
        "name": name,
        "short_name": _normalize_spaces(raw.get("short_name")),
        "entity_type": _normalize_spaces(raw.get("entity_type")),
        "entity_id": _safe_int(raw.get("entity_id")),
        "effective_from": _normalize_spaces(raw.get("effective_from")),
        "effective_to": _normalize_spaces(raw.get("effective_to")),
        "version_tag": _normalize_spaces(data.version_tag or raw.get("version_tag")),
        "status": _normalize_spaces(raw.get("status")) or "active",
        "data_json": json.dumps(raw, ensure_ascii=False),
    }


def _upsert_nsi_classifier(conn, item: dict, actor: dict) -> int:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO nsi_external_classifiers (
            classifier_type, source_system, external_code, external_parent_code, name, short_name,
            entity_type, entity_id, effective_from, effective_to, version_tag, status, data_json,
            imported_by, imported_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(classifier_type, source_system, external_code)
        DO UPDATE SET
            external_parent_code=excluded.external_parent_code,
            name=excluded.name,
            short_name=excluded.short_name,
            entity_type=excluded.entity_type,
            entity_id=excluded.entity_id,
            effective_from=excluded.effective_from,
            effective_to=excluded.effective_to,
            version_tag=excluded.version_tag,
            status=excluded.status,
            data_json=excluded.data_json,
            imported_by=excluded.imported_by,
            updated_at=excluded.updated_at
        """,
        (
            item.get("classifier_type", ""),
            item.get("source_system", "manual"),
            item.get("external_code", ""),
            item.get("external_parent_code", ""),
            item.get("name", ""),
            item.get("short_name", ""),
            item.get("entity_type", ""),
            _safe_int(item.get("entity_id")),
            item.get("effective_from", ""),
            item.get("effective_to", ""),
            item.get("version_tag", ""),
            item.get("status", "active"),
            item.get("data_json", "{}"),
            actor.get("email", ""),
            now,
            now,
        ),
    )
    row = _select_one_dict(
        conn,
        "SELECT id FROM nsi_external_classifiers WHERE classifier_type=? AND source_system=? AND external_code=?",
        (item.get("classifier_type", ""), item.get("source_system", "manual"), item.get("external_code", "")),
    )
    return _safe_int(row.get("id"))


def _sync_imported_unit_classifier(conn, item: dict, actor: dict) -> int:
    if item.get("classifier_type") != "units" or not item.get("external_code") or not item.get("name"):
        return 0
    now = int(time.time())
    existing = _select_one_dict(conn, "SELECT id FROM unit_master WHERE code=? LIMIT 1", (item.get("external_code"),))
    if existing:
        unit_id = _safe_int(existing.get("id"))
        conn.execute("UPDATE unit_master SET name=?, comment=?, mdm_status='pending_approval', lifecycle_state='draft', is_active=0, updated_at=? WHERE id=?", (item.get("name"), "Импорт ОКЕИ/единиц измерения", now, unit_id))
    else:
        unit_id = next_safe_table_id(conn, "unit_master")
        conn.execute(
            """
            INSERT INTO unit_master (id, name, code, is_active, comment, mdm_status, lifecycle_state, created_at, updated_at)
            VALUES (?, ?, ?, 0, 'Импорт ОКЕИ/единиц измерения', 'pending_approval', 'draft', ?, ?)
            """,
            (unit_id, item.get("name"), item.get("external_code"), now, now),
        )
    report = _nsi_mdm_validate_row(conn, "units", _nsi_mdm_load_row(conn, "units", unit_id), unit_id)
    _nsi_mdm_update_row_state(conn, "units", unit_id, report, mdm_status=("needs_fix" if any(issue.get("severity") == "error" for issue in report.get("issues", [])) else "pending_approval"), lifecycle_state=("blocked" if any(issue.get("severity") == "error" for issue in report.get("issues", [])) else "draft"))
    _record_nsi_mdm_version(conn, "units", unit_id, actor, "classifier_import")
    conn.execute("UPDATE nsi_external_classifiers SET entity_type='units', entity_id=? WHERE classifier_type=? AND source_system=? AND external_code=?", (unit_id, item.get("classifier_type", ""), item.get("source_system", "manual"), item.get("external_code", "")))
    return unit_id


def _nsi_bulk_preview(conn, entity_type: str, filter_payload: dict) -> list[dict]:
    config = _nsi_mdm_config(entity_type)
    if not config:
        return []
    params = []
    where = ["1=1"]
    ids = [_safe_int(item) for item in (filter_payload.get("ids") or []) if _safe_int(item)]
    if ids:
        where.append(f"id IN ({', '.join('?' for _ in ids)})")
        params.extend(ids)
    if filter_payload.get("mdm_status"):
        where.append("mdm_status=?")
        params.append(_normalize_spaces(filter_payload.get("mdm_status")))
    if filter_payload.get("code_prefix"):
        code_column = config["code_column"]
        where.append(f"LOWER(COALESCE({code_column}, '')) LIKE LOWER(?)")
        params.append(f"{_normalize_spaces(filter_payload.get('code_prefix'))}%")
    return _select_all_dicts(conn, f"SELECT * FROM {config['table']} WHERE {' AND '.join(where)} ORDER BY id LIMIT 500", tuple(params))


def _apply_nsi_bulk_change(conn, request_row: dict, actor: dict) -> dict:
    entity_type = request_row.get("entity_type", "")
    config = _nsi_mdm_config(entity_type)
    if not config:
        return {"error": "invalid_entity_type"}
    operation = request_row.get("operation") or "update_fields"
    changes = _json_load(request_row.get("changes_json"), {})
    preview = _json_load(request_row.get("preview_json"), [])
    target_ids = [_safe_int(item.get("id")) for item in preview if _safe_int(item.get("id"))]
    if not target_ids:
        preview = _nsi_bulk_preview(conn, entity_type, _json_load(request_row.get("filter_json"), {}))
        target_ids = [_safe_int(item.get("id")) for item in preview if _safe_int(item.get("id"))]
    allowed_columns = set(config.get("required", [])) | set((_nsi_master_config(entity_type) or {}).get("fields", [])) | {"is_active", "comment"}
    applied = 0
    now = int(time.time())
    for item_id in target_ids:
        assignments = {}
        if operation in {"activate", "approve_activate"}:
            assignments["is_active"] = 1
            assignments["mdm_status"] = "approved"
            assignments["lifecycle_state"] = "active"
            assignments["approved_by"] = actor.get("email", "")
            assignments["approved_at"] = now
        elif operation in {"deactivate", "archive"}:
            assignments["is_active"] = 0
            assignments["lifecycle_state"] = "archived"
        else:
            for key, value in changes.items():
                if key in allowed_columns:
                    assignments[key] = value
            assignments["mdm_status"] = "pending_approval"
            assignments["lifecycle_state"] = "draft"
        assignments["updated_at"] = now
        if not assignments:
            continue
        set_clause = ", ".join(f"{field}=?" for field in assignments)
        conn.execute(f"UPDATE {config['table']} SET {set_clause} WHERE id=?", (*assignments.values(), item_id))
        row = _nsi_mdm_load_row(conn, entity_type, item_id)
        report = _nsi_mdm_validate_row(conn, entity_type, row, item_id)
        if operation not in {"activate", "approve_activate"}:
            _nsi_mdm_update_row_state(conn, entity_type, item_id, report)
        _record_nsi_mdm_version(conn, entity_type, item_id, actor, f"bulk_change:{request_row.get('request_number') or request_row.get('id')}")
        applied += 1
    conn.execute("UPDATE nsi_bulk_change_requests SET status='applied', applied_count=?, approved_by=?, applied_at=?, updated_at=? WHERE id=?", (applied, actor.get("email", ""), now, now, _safe_int(request_row.get("id"))))
    return {"status": "success", "applied_count": applied}


@router.get("/api/nsi/mdm/governance")
def get_nsi_mdm_governance(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        payload = _run_nsi_mdm_controls(conn, actor, persist=False)
    finally:
        conn.close()
    return payload


@router.post("/api/nsi/mdm/controls/run")
def run_nsi_mdm_controls(request: Request):
    actor = require_approved_user(request)
    if not actor or not _can_manage_nsi_entity(actor, "warehouses"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        payload = _run_nsi_mdm_controls(conn, actor, persist=True)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit_log(
        "nsi_mdm_controls_run",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="nsi_mdm",
        entity_id="controls",
        details=payload.get("metrics", {}),
    )
    return payload


@router.get("/api/nsi/mdm/issues")
def get_nsi_mdm_issues(request: Request, status: str = "open", limit: int = 200):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    status = (status or "open").strip()
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    if status == "all":
        c.execute("SELECT * FROM nsi_mdm_issues ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),))
    else:
        c.execute("SELECT * FROM nsi_mdm_issues WHERE status=? ORDER BY created_at DESC, id DESC LIMIT ?", (status, max(1, min(limit, 500))))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["details"] = _json_load(row.get("details_json"), {})
    return rows


@router.get("/api/nsi/mdm/hierarchies")
def get_nsi_hierarchies(request: Request, entity_type: str = "", hierarchy_type: str = "mdm"):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    params = []
    where = ["1=1"]
    if entity_type:
        where.append("entity_type=?")
        params.append(entity_type)
    if hierarchy_type:
        where.append("hierarchy_type=?")
        params.append(hierarchy_type)
    conn = get_connection()
    try:
        rows = _select_all_dicts(conn, f"SELECT * FROM nsi_hierarchies WHERE {' AND '.join(where)} ORDER BY path_code, sort_order, node_name", tuple(params))
    finally:
        conn.close()
    for row in rows:
        row["details"] = _json_load(row.get("details_json"), {})
    return rows


@router.post("/api/nsi/mdm/hierarchies")
def save_nsi_hierarchy(data: NSIHierarchyData, request: Request):
    actor = require_approved_user(request)
    if not actor or not _can_manage_nsi_entity(actor, data.entity_type):
        return {"error": "forbidden"}
    config = _nsi_mdm_config(data.entity_type)
    if not config:
        return {"error": "invalid_entity_type"}
    conn = get_connection()
    try:
        entity = _nsi_mdm_load_row(conn, data.entity_type, data.entity_id)
        if not entity:
            return {"error": "entity_not_found"}
        if data.parent_entity_id and not _nsi_mdm_load_row(conn, data.entity_type, data.parent_entity_id):
            return {"error": "parent_not_found"}
        now = int(time.time())
        parent_path, parent_level = _nsi_hierarchy_parent_path(conn, data.hierarchy_type, data.entity_type, data.parent_entity_id)
        node_code = _normalize_spaces(data.node_code) or _normalize_spaces(entity.get(config["code_column"])) or str(data.entity_id)
        node_name = _normalize_spaces(data.node_name) or _normalize_spaces(entity.get(config["name_column"])) or node_code
        path_code = f"{parent_path}/{node_code}" if parent_path else node_code
        row_id = next_safe_table_id(conn, "nsi_hierarchies")
        conn.execute(
            """
            INSERT INTO nsi_hierarchies (
                id, hierarchy_type, entity_type, entity_id, parent_entity_id, node_code, node_name,
                path_code, level_no, sort_order, is_active, valid_from, valid_to, details_json,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                data.hierarchy_type or "mdm",
                data.entity_type,
                _safe_int(data.entity_id),
                _safe_int(data.parent_entity_id),
                node_code,
                node_name,
                path_code,
                parent_level + 1 if data.parent_entity_id else 0,
                _safe_int(data.sort_order),
                1 if _safe_int(data.is_active) else 0,
                data.valid_from or "",
                data.valid_to or "",
                json.dumps(data.details or {}, ensure_ascii=False),
                actor.get("email", ""),
                now,
                now,
            ),
        )
        _record_nsi_mdm_version(conn, data.entity_type, data.entity_id, actor, "hierarchy_linked")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit_log("nsi_hierarchy_saved", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=data.entity_type, entity_id=str(data.entity_id), details={"hierarchy_id": row_id, "path_code": path_code})
    return {"status": "success", "id": row_id, "path_code": path_code}


@router.get("/api/nsi/mdm/external_classifiers")
def get_nsi_external_classifiers(request: Request, classifier_type: str = "", source_system: str = "", limit: int = 200):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    params = []
    where = ["1=1"]
    if classifier_type:
        where.append("classifier_type=?")
        params.append(classifier_type)
    if source_system:
        where.append("source_system=?")
        params.append(source_system)
    params.append(max(1, min(limit, 1000)))
    conn = get_connection()
    try:
        rows = _select_all_dicts(conn, f"SELECT * FROM nsi_external_classifiers WHERE {' AND '.join(where)} ORDER BY imported_at DESC, id DESC LIMIT ?", tuple(params))
    finally:
        conn.close()
    for row in rows:
        row["data"] = _json_load(row.get("data_json"), {})
    return rows


@router.post("/api/nsi/mdm/external_classifiers")
def save_nsi_external_classifier(data: NSIExternalClassifierData, request: Request):
    actor = require_approved_user(request)
    if not actor or not _can_manage_nsi_entity(actor, "units"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        item = {
            "classifier_type": _normalize_spaces(data.classifier_type).lower(),
            "source_system": _normalize_spaces(data.source_system) or "manual",
            "external_code": _normalize_spaces(data.external_code),
            "external_parent_code": _normalize_spaces(data.external_parent_code),
            "name": _normalize_spaces(data.name),
            "short_name": _normalize_spaces(data.short_name),
            "entity_type": _normalize_spaces(data.entity_type),
            "entity_id": _safe_int(data.entity_id),
            "effective_from": data.effective_from or "",
            "effective_to": data.effective_to or "",
            "version_tag": data.version_tag or "",
            "status": data.status or "active",
            "data_json": json.dumps(data.data or {}, ensure_ascii=False),
        }
        if not item["classifier_type"] or not item["external_code"] or not item["name"]:
            return {"error": "classifier_type_code_name_required"}
        row_id = _upsert_nsi_classifier(conn, item, actor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"status": "success", "id": row_id}


@router.post("/api/nsi/mdm/external_classifiers/import")
def import_nsi_external_classifiers(data: NSIExternalClassifierImportData, request: Request):
    actor = require_approved_user(request)
    if not actor or not _can_manage_nsi_entity(actor, "units"):
        return {"error": "forbidden"}
    source_meta = {}
    items = list(data.items or [])
    if not items:
        source_meta = fetch_external_classifier_items(
            data.classifier_type,
            source_url=data.source_url,
            token=data.token,
            headers=data.headers or {},
            limit=data.limit,
        )
        if source_meta.get("status") != "success":
            return source_meta
        items = source_meta.get("items") or []
    if not items:
        return {"error": "items_required"}
    conn = get_connection()
    created_or_updated = 0
    linked_units = 0
    try:
        for raw in items[:max(1, min(_safe_int(data.limit) or 2000, 10000))]:
            item = _nsi_classifier_item(data, raw)
            if not item.get("classifier_type") or not item.get("external_code") or not item.get("name"):
                continue
            _upsert_nsi_classifier(conn, item, actor)
            if _sync_imported_unit_classifier(conn, item, actor):
                linked_units += 1
            created_or_updated += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit_log("nsi_external_classifiers_imported", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="nsi_external_classifier", entity_id=data.classifier_type, details={"count": created_or_updated, "linked_units": linked_units, "source_url": source_meta.get("source_url", "")})
    return {"status": "success", "count": created_or_updated, "linked_units": linked_units, "source": {key: source_meta.get(key) for key in ("source_url", "source_format") if source_meta.get(key)}}


@router.get("/api/nsi/mdm/duplicate_rules")
def get_nsi_duplicate_rules(request: Request, entity_type: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        rows = _select_all_dicts(conn, "SELECT * FROM nsi_duplicate_rules WHERE (?='' OR entity_type=?) ORDER BY entity_type, id", (entity_type, entity_type))
    finally:
        conn.close()
    for row in rows:
        row["fields"] = _json_load(row.get("fields_json"), [])
    return rows


@router.post("/api/nsi/mdm/duplicate_rules")
def save_nsi_duplicate_rule(data: NSIDuplicateRuleData, request: Request):
    actor = require_approved_user(request)
    if not actor or not _can_manage_nsi_entity(actor, data.entity_type):
        return {"error": "forbidden"}
    if not _nsi_mdm_config(data.entity_type) or not data.fields:
        return {"error": "entity_type_and_fields_required"}
    conn = get_connection()
    now = int(time.time())
    row_id = next_safe_table_id(conn, "nsi_duplicate_rules")
    conn.execute(
        """
        INSERT INTO nsi_duplicate_rules (id, entity_type, rule_name, fields_json, match_mode, severity, is_active, comment, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (row_id, data.entity_type, data.rule_name or f"{data.entity_type}_rule", json.dumps(data.fields, ensure_ascii=False), data.match_mode or "all", data.severity or "error", 1 if _safe_int(data.is_active) else 0, data.comment or "", actor.get("email", ""), now, now),
    )
    conn.commit()
    conn.close()
    return {"status": "success", "id": row_id}


@router.get("/api/nsi/mdm/bulk_change_requests")
def get_nsi_bulk_change_requests(request: Request, status: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        rows = _select_all_dicts(conn, "SELECT * FROM nsi_bulk_change_requests WHERE (?='' OR status=?) ORDER BY updated_at DESC, id DESC", (status, status))
    finally:
        conn.close()
    for row in rows:
        row["filter"] = _json_load(row.get("filter_json"), {})
        row["changes"] = _json_load(row.get("changes_json"), {})
        row["preview"] = _json_load(row.get("preview_json"), [])
    return rows


@router.post("/api/nsi/mdm/bulk_change_requests")
def create_nsi_bulk_change_request(data: NSIBulkChangeRequestData, request: Request):
    actor = require_approved_user(request)
    if not actor or not _can_manage_nsi_entity(actor, data.entity_type):
        return {"error": "forbidden"}
    if not _nsi_mdm_config(data.entity_type):
        return {"error": "invalid_entity_type"}
    conn = get_connection()
    try:
        preview = _nsi_bulk_preview(conn, data.entity_type, data.filter or {})
        now = int(time.time())
        request_id = next_safe_table_id(conn, "nsi_bulk_change_requests")
        request_number = f"NSI-BULK-{request_id}"
        conn.execute(
            """
            INSERT INTO nsi_bulk_change_requests (
                id, request_number, entity_type, operation, filter_json, changes_json, preview_json, status,
                target_count, requested_by, comment, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?)
            """,
            (request_id, request_number, data.entity_type, data.operation or "update_fields", json.dumps(data.filter or {}, ensure_ascii=False), json.dumps(data.changes or {}, ensure_ascii=False), json.dumps(preview, ensure_ascii=False), len(preview), actor.get("email", ""), data.comment or "", now, now),
        )
        approval_id = next_safe_table_id(conn, "nsi_mdm_approvals")
        conn.execute(
            """
            INSERT INTO nsi_mdm_approvals (id, entity_type, entity_id, target_state, status, requested_by, comment, created_at)
            VALUES (?, 'nsi_bulk_change', ?, ?, 'requested', ?, ?, ?)
            """,
            (approval_id, request_id, data.operation or "update_fields", actor.get("email", ""), data.comment or "", now),
        )
        conn.execute("UPDATE nsi_bulk_change_requests SET approval_id=? WHERE id=?", (approval_id, request_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"status": "success", "id": request_id, "approval_id": approval_id, "target_count": len(preview), "preview": preview[:20]}


@router.post("/api/nsi/mdm/bulk_change_requests/{request_id}/approve")
def approve_nsi_bulk_change_request(request_id: int, data: MDMGovernanceActionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not _can_manage_nsi_entity(actor, "warehouses"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        request_row = _select_one_dict(conn, "SELECT * FROM nsi_bulk_change_requests WHERE id=?", (_safe_int(request_id),))
        if not request_row:
            return {"error": "not_found"}
        if not _can_manage_nsi_entity(actor, request_row.get("entity_type", "")):
            return {"error": "forbidden"}
        now = int(time.time())
        conn.execute("UPDATE nsi_mdm_approvals SET status='approved', decided_by=?, comment=?, decided_at=? WHERE id=?", (actor.get("email", ""), data.comment or "", now, _safe_int(request_row.get("approval_id"))))
        conn.execute("UPDATE nsi_bulk_change_requests SET status='approved', approved_by=?, approved_at=?, updated_at=? WHERE id=?", (actor.get("email", ""), now, now, _safe_int(request_id)))
        request_row["status"] = "approved"
        applied = _apply_nsi_bulk_change(conn, request_row, actor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"status": "success", "id": _safe_int(request_id), **applied}


@router.get("/api/nsi/master_data/{entity_type}/{item_id}/versions")
def get_nsi_master_record_versions(entity_type: str, item_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    if not _nsi_mdm_config(entity_type):
        return {"error": "invalid_entity_type"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT *
        FROM nsi_mdm_versions
        WHERE entity_type=? AND entity_id=?
        ORDER BY version_no DESC, id DESC
        """,
        (entity_type, _safe_int(item_id)),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["payload"] = _json_load(row.get("payload"), {})
    return rows


@router.get("/api/nsi/master_data/{entity_type}/{item_id}/duplicates")
def get_nsi_master_record_duplicates(entity_type: str, item_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        row = _nsi_mdm_load_row(conn, entity_type, item_id)
        if not row:
            return {"error": "not_found"}
        duplicates = _nsi_mdm_duplicate_candidates(conn, entity_type, item_id, row)
        report = _nsi_mdm_validate_row(conn, entity_type, row, item_id)
    finally:
        conn.close()
    return {"status": "success", "duplicates": duplicates, "quality_score": report.get("quality_score", 0), "issues": report.get("issues", [])}


@router.post("/api/nsi/master_data/{entity_type}/{item_id}/approve")
def approve_nsi_master_record(entity_type: str, item_id: int, data: MDMGovernanceActionData, request: Request):
    actor = require_approved_user(request)
    config = _nsi_master_config(entity_type)
    if not actor or not _can_manage_nsi_entity(actor, entity_type, config):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        row = _nsi_mdm_load_row(conn, entity_type, item_id)
        if not row:
            return {"error": "not_found"}
        report = _nsi_mdm_validate_row(conn, entity_type, row, item_id)
        blocking_issues = [issue for issue in report.get("issues", []) if issue.get("severity") == "error"]
        if blocking_issues:
            _nsi_mdm_update_row_state(conn, entity_type, item_id, report)
            conn.commit()
            return {"error": "validation_error", "issues": blocking_issues}
        c = conn.cursor()
        c.execute(
            f"UPDATE {_nsi_mdm_config(entity_type)['table']} SET mdm_status='approved', lifecycle_state=?, is_active=1, approved_by=?, approved_at=?, quality_score=?, validation_errors='[]' WHERE id=?",
            ((data.target_state or "active").strip() or "active", actor.get("email", ""), int(time.time()), _safe_int(report.get("quality_score")), _safe_int(item_id)),
        )
        c.execute(
            """
            INSERT INTO nsi_mdm_approvals (entity_type, entity_id, target_state, status, requested_by, decided_by, comment, created_at, decided_at)
            VALUES (?, ?, ?, 'approved', ?, ?, ?, ?, ?)
            """,
            (entity_type, _safe_int(item_id), (data.target_state or "active").strip() or "active", actor.get("email", ""), actor.get("email", ""), data.comment or "", int(time.time()), int(time.time())),
        )
        version_no = _record_nsi_mdm_version(conn, entity_type, item_id, actor, data.comment or "approved")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit_log("nsi_mdm_approved", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=entity_type, entity_id=str(item_id), details={"version_no": version_no})
    return {"status": "success", "id": _safe_int(item_id), "mdm_status": "approved", "version_no": version_no}


@router.post("/api/nsi/master_data/{entity_type}/{item_id}/reject")
def reject_nsi_master_record(entity_type: str, item_id: int, data: MDMGovernanceActionData, request: Request):
    actor = require_approved_user(request)
    config = _nsi_master_config(entity_type)
    if not actor or not _can_manage_nsi_entity(actor, entity_type, config):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        row = _nsi_mdm_load_row(conn, entity_type, item_id)
        if not row:
            return {"error": "not_found"}
        c = conn.cursor()
        c.execute(
            f"UPDATE {_nsi_mdm_config(entity_type)['table']} SET mdm_status='rejected', lifecycle_state='rejected', validation_errors=? WHERE id=?",
            (json.dumps([{"issue_type": "governance_reject", "severity": "warning", "message": data.comment or "Отклонено steward-контролем"}], ensure_ascii=False), _safe_int(item_id)),
        )
        c.execute(
            """
            INSERT INTO nsi_mdm_approvals (entity_type, entity_id, target_state, status, requested_by, decided_by, comment, created_at, decided_at)
            VALUES (?, ?, 'rejected', 'rejected', ?, ?, ?, ?, ?)
            """,
            (entity_type, _safe_int(item_id), actor.get("email", ""), actor.get("email", ""), data.comment or "", int(time.time()), int(time.time())),
        )
        version_no = _record_nsi_mdm_version(conn, entity_type, item_id, actor, data.comment or "rejected")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit_log("nsi_mdm_rejected", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=entity_type, entity_id=str(item_id), details={"version_no": version_no})
    return {"status": "success", "id": _safe_int(item_id), "mdm_status": "rejected", "version_no": version_no}


@router.post("/api/nsi/master_data/{entity_type}")
def create_nsi_master_record(entity_type: str, data: NSIMasterRecordData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "create"):
        return {"error": "forbidden"}
    return _save_nsi_master_record(entity_type, 0, data, actor)


@router.put("/api/nsi/master_data/{entity_type}/{item_id}")
def update_nsi_master_record(entity_type: str, item_id: int, data: NSIMasterRecordData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "update"):
        return {"error": "forbidden"}
    return _save_nsi_master_record(entity_type, item_id, data, actor)


@router.delete("/api/nsi/master_data/{entity_type}/{item_id}")
def archive_nsi_master_record(entity_type: str, item_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "delete"):
        return {"error": "forbidden"}
    config = _nsi_master_config(entity_type)
    if not config:
        return {"error": "invalid_entity_type"}
    if config.get("finance_only") and not (has_permission(actor, "finance", "manage_master") or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"UPDATE {config['table']} SET is_active=0, updated_at=? WHERE id=?", (int(time.time()), item_id))
    if _sync_entity_meta(entity_type):
        _upsert_entity_sync_job(conn, entity_type, item_id, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("nsi_master_archived", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=entity_type, entity_id=str(item_id), details={})
    return {"status": "success"}


@router.post("/api/nsi/master_data/{entity_type}/{item_id}/sync")
def queue_nsi_master_record_sync(entity_type: str, item_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        result = _queue_nsi_master_sync_job(conn, entity_type, item_id, actor)
        if result.get("error"):
            return result
        conn.commit()
    finally:
        conn.close()
    audit_log(
        "nsi_master_sync_queued",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type=entity_type,
        entity_id=str(item_id),
        details={"queue_id": result.get("queue_id", 0)},
    )
    return {"status": "success", "queue_id": result.get("queue_id", 0)}


@router.post("/api/nsi/master_data/{entity_type}/sync_failed")
def queue_failed_nsi_master_records(entity_type: str, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    config = _nsi_master_config(entity_type)
    if not config:
        return {"error": "invalid_entity_type"}
    if not _can_manage_nsi_entity(actor, entity_type, config):
        return {"error": "forbidden"}
    meta = _reconciliation_entity_config().get(entity_type)
    if not meta:
        return {"error": "sync_not_supported"}
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    queued = 0
    try:
        c = conn.cursor()
        _, issues = _collect_reconciliation_entity_issues(c, entity_type, meta)
        seen_ids = set()
        for issue in issues:
            row_id = _safe_int(issue.get("row_id"))
            if not row_id or row_id in seen_ids:
                continue
            result = _queue_nsi_master_sync_job(conn, entity_type, row_id, actor)
            if result.get("status") == "success" and result.get("queue_id"):
                queued += 1
                seen_ids.add(row_id)
        conn.commit()
    finally:
        conn.close()
    audit_log(
        "nsi_master_failed_sync_requeued",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type=entity_type,
        entity_id=entity_type,
        details={"queued": queued},
    )
    return {"status": "success", "queued": queued}


@router.get("/api/stock/documents")
def get_inventory_documents(request: Request, limit: int = 120):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    return _load_inventory_document_rows(limit)


@router.get("/api/stock/discrepancy_acts")
def get_inventory_discrepancy_acts(request: Request, limit: int = 120):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    return _load_inventory_discrepancy_rows(limit)


@router.post("/api/stock/documents")
def create_inventory_document(data: InventoryDocumentData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "update"):
        return _api_error(403, "forbidden")
    article = _normalize_spaces(data.article)
    if not article:
        return _api_error(400, "article_required")
    conn = get_connection()
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute("SELECT * FROM nomenclature WHERE article=?", (article,))
    row = c.fetchone()
    if not row:
        now = int(time.time())
        c.execute(
            """
            INSERT INTO nomenclature (
                article, name, unit, price, stock, currency, group_name, default_warehouse, exchange_state, external_sync_id
            ) VALUES (?, ?, 'шт', 0, 0, 'RUB', '', '', 'queued', '')
            """,
            (article, article),
        )
        c.execute("SELECT * FROM nomenclature WHERE article=?", (article,))
        row = c.fetchone()
    now = int(time.time())
    doc_number = (data.doc_number or "").strip() or _next_inventory_doc_number(data.doc_type)
    c.execute(
        """
        INSERT INTO inventory_documents (
            doc_type, doc_number, article, warehouse, bin_code, batch_code, serial_no, lot_expiration_date,
            target_warehouse, target_bin, qty, counted_qty, adjustment_qty, unit, package_code, package_qty, unit_cost, reason,
            comment, status, actor_email, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
        """,
        (
            data.doc_type or "inventory",
            doc_number,
            article,
            data.warehouse or "",
            data.bin_code or "",
            data.batch_code or "",
            data.serial_no or "",
            data.lot_expiration_date or "",
            data.target_warehouse or "",
            data.target_bin or "",
            data.qty,
            data.counted_qty,
            data.unit or "шт",
            data.package_code or "",
            data.package_qty,
            data.unit_cost,
            data.reason or "",
            data.comment or "",
            actor.get("email", ""),
            now,
            now,
        ),
    )
    doc_id = c.lastrowid
    result = _apply_inventory_document(conn, doc_id, article, dict(row).get("name", article), data, actor.get("email", ""))
    _upsert_entity_sync_job(conn, "nomenclature", article, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("inventory_document_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="inventory_document", entity_id=str(doc_id), details={"doc_type": data.doc_type, "article": article, "doc_number": doc_number, "reason": data.reason})
    return {"status": "success", "id": doc_id, "doc_number": doc_number, **result}


@router.get("/api/nomenclature")
def get_nomenclature(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True); c = conn.cursor(); c.execute("SELECT * FROM nomenclature ORDER BY name ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

@router.post("/api/nomenclature")
async def create_nomenclature(data: NomenclatureData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "create"):
        return {"error": "forbidden"}
    conn = get_connection(); c = conn.cursor()
    candidate = {
        "name": data.name,
        "article": data.article,
        "unit": data.unit,
        "price": data.price,
        "stock": data.stock,
        "currency": data.currency,
        "group_name": data.group_name or "",
        "default_warehouse": data.default_warehouse or "",
    }
    gate = _nsi_mdm_validate_row(conn, "nomenclature", candidate, 0)
    if gate.get("duplicates"):
        conn.close()
        return {"error": "duplicate_candidate", "duplicates": gate.get("duplicates", [])}
    c.execute(
        """
        INSERT INTO nomenclature (name, article, unit, price, stock, currency, group_name, default_warehouse, exchange_state, external_sync_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', '')
        """,
        (data.name, data.article, data.unit, data.price, data.stock, data.currency, data.group_name or "", data.default_warehouse or ""),
    )
    nomenclature_id = c.lastrowid
    report = _nsi_mdm_validate_row(conn, "nomenclature", _nsi_mdm_load_row(conn, "nomenclature", nomenclature_id), nomenclature_id)
    _nsi_mdm_update_row_state(conn, "nomenclature", nomenclature_id, report)
    _record_nsi_mdm_version(conn, "nomenclature", nomenclature_id, actor, "created")
    if (data.article or "").strip():
        _upsert_entity_sync_job(conn, "nomenclature", (data.article or "").strip(), actor.get("email", ""))
    conn.commit()
    conn.close()
    return {"status": "success", "id": nomenclature_id}


@router.post("/api/nomenclature/import")
async def import_nomenclature(request: Request, upload: UploadFile = File(...)):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "nsi", "import") or has_permission(actor, "nsi", "create") or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    rows = _load_import_rows(upload)
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM nomenclature")
    existing = [dict(row) for row in c.fetchall()]
    by_article = {_normalize_duplicate_key(row.get("article") or ""): row for row in existing if row.get("article")}
    by_name = {_normalize_duplicate_key(row.get("name") or ""): row for row in existing if row.get("name")}
    created = 0
    updated = 0
    skipped = 0
    for raw in rows:
        item = _normalize_nomenclature_row(raw)
        if not item["name"]:
            skipped += 1
            continue
        article_key = _normalize_duplicate_key(item["article"])
        name_key = _normalize_duplicate_key(item["name"])
        match = (article_key and by_article.get(article_key)) or by_name.get(name_key)
        if match:
            new_article = item["article"] or match.get("article") or ""
            c.execute(
                "UPDATE nomenclature SET name=?, article=?, unit=?, price=?, stock=?, currency=?, group_name=?, default_warehouse=?, exchange_state='queued' WHERE id=?",
                (item["name"], new_article, item["unit"], item["price"], item["stock"], item["currency"], item["group_name"], item["default_warehouse"], match["id"]),
            )
            updated += 1
            normalized = {"id": match["id"], **item, "article": new_article}
            by_name[name_key] = normalized
            if new_article:
                by_article[_normalize_duplicate_key(new_article)] = normalized
                _upsert_entity_sync_job(conn, "nomenclature", new_article, actor.get("email", ""))
        else:
            c.execute(
                "INSERT INTO nomenclature (name, article, unit, price, stock, currency, group_name, default_warehouse, exchange_state, external_sync_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', '')",
                (item["name"], item["article"], item["unit"], item["price"], item["stock"], item["currency"], item["group_name"], item["default_warehouse"]),
            )
            created += 1
            normalized = {"id": c.lastrowid, **item}
            by_name[name_key] = normalized
            if item["article"]:
                by_article[article_key] = normalized
                _upsert_entity_sync_job(conn, "nomenclature", item["article"], actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("nomenclature_imported", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="nomenclature_import", entity_id=upload.filename or "nomenclature", details={"created": created, "updated": updated, "skipped": skipped})
    return {"status": "success", "created": created, "updated": updated, "skipped": skipped}


@router.post("/api/nomenclature/merge")
def merge_nomenclature(data: NomenclatureMergeData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "nsi", "cleanup") or has_permission(actor, "nsi", "delete") or actor.get("role") == "Директор"):
        return {"error": "forbidden"}
    master_article = _normalize_spaces(data.master_article)
    duplicate_articles = [_normalize_spaces(item) for item in data.duplicate_articles if _normalize_spaces(item) and _normalize_spaces(item) != master_article]
    if not master_article or not duplicate_articles:
        return {"error": "duplicates_required"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM nomenclature WHERE article=?", (master_article,))
    master = c.fetchone()
    if not master:
        conn.close()
        return {"error": "master_not_found"}
    c.execute(f"SELECT * FROM nomenclature WHERE article IN ({','.join('?' for _ in duplicate_articles)})", tuple(duplicate_articles))
    duplicates = [dict(row) for row in c.fetchall()]
    if not duplicates:
        conn.close()
        return {"error": "duplicates_not_found"}
    master = dict(master)
    total_stock = _safe_float(master.get("stock")) + sum(_safe_float(row.get("stock")) for row in duplicates)
    merged_name = master.get("name") or next((row.get("name", "") for row in duplicates if row.get("name")), "")
    c.execute("UPDATE nomenclature SET name=?, stock=?, exchange_state='queued' WHERE article=?", (merged_name, total_stock, master_article))
    c.execute(f"UPDATE stock_reservations SET nomenclature_article=?, nomenclature_name=? WHERE nomenclature_article IN ({','.join('?' for _ in duplicate_articles)})", (master_article, merged_name, *duplicate_articles))
    c.execute(f"UPDATE stock_movements SET article=?, name=? WHERE article IN ({','.join('?' for _ in duplicate_articles)})", (master_article, merged_name, *duplicate_articles))
    c.execute(f"UPDATE inventory_balances SET article=? WHERE article IN ({','.join('?' for _ in duplicate_articles)})", (master_article, *duplicate_articles))
    c.execute(f"UPDATE inventory_lots SET article=? WHERE article IN ({','.join('?' for _ in duplicate_articles)})", (master_article, *duplicate_articles))
    c.execute("SELECT warehouse, bin_code, SUM(qty) FROM inventory_balances WHERE article=? GROUP BY warehouse, bin_code", (master_article,))
    balances = c.fetchall()
    c.execute("DELETE FROM inventory_balances WHERE article=?", (master_article,))
    for warehouse, bin_code, qty in balances:
        c.execute("INSERT INTO inventory_balances (article, warehouse, bin_code, qty, updated_at) VALUES (?, ?, ?, ?, ?)", (master_article, warehouse, bin_code, qty, int(time.time())))
    c.execute("SELECT warehouse, bin_code, batch_code, serial_no, SUM(qty) FROM inventory_lots WHERE article=? GROUP BY warehouse, bin_code, batch_code, serial_no", (master_article,))
    lots = c.fetchall()
    c.execute("DELETE FROM inventory_lots WHERE article=?", (master_article,))
    for warehouse, bin_code, batch_code, serial_no, qty in lots:
        c.execute("INSERT INTO inventory_lots (article, warehouse, bin_code, batch_code, serial_no, qty, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (master_article, warehouse, bin_code, batch_code, serial_no, qty, int(time.time())))
    article_map = {article: {"article": master_article, "name": merged_name} for article in duplicate_articles}
    _rewrite_project_nomenclature_articles(conn, article_map)
    _rewrite_erp_payload_articles(conn, article_map)
    _delete_sync_entity_cascade(conn, "nomenclature", master.get("id"))
    for duplicate in duplicates:
        _delete_sync_entity_cascade(conn, "nomenclature", duplicate.get("id"))
    c.execute(f"DELETE FROM nomenclature WHERE article IN ({','.join('?' for _ in duplicate_articles)})", tuple(duplicate_articles))
    _upsert_entity_sync_job(conn, "nomenclature", master_article, actor.get("email", ""))
    conn.commit()
    conn.close()
    audit_log("nomenclature_merged", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="nomenclature", entity_id=master_article, details={"duplicates": duplicate_articles, "merged_name": merged_name})
    return {"status": "success", "master_article": master_article, "merged": len(duplicate_articles)}

@router.delete("/api/nomenclature/{article}")
async def delete_nomenclature(article: str, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "delete"):
        return {"error": "forbidden"}
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT id FROM nomenclature WHERE article=?", (article,))
    row = c.fetchone()
    if row:
        _delete_sync_entity_cascade(conn, "nomenclature", _safe_int(row[0]))
    c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
    conn.commit()
    conn.close()
    return {"status": "success"}

# === ВОТ ЭТОТ МАРШРУТ БЫЛ ПОТЕРЯН! ===
@router.post("/api/nomenclature/{article}/movement")
async def move_stock(article: str, data: StockMovement, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "nsi", "update"):
        return {"error": "forbidden"}
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT stock FROM nomenclature WHERE article=?", (article,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Товар не найден")
    
    current_stock = row[0] or 0
    new_stock = current_stock + data.qty if data.type == 'add' else current_stock - data.qty
    
    c.execute("UPDATE nomenclature SET stock=?, exchange_state='queued' WHERE article=?", (new_stock, article))
    _upsert_entity_sync_job(conn, "nomenclature", article, actor.get("email", ""))
    conn.commit()
    conn.close()
    return {"status": "success", "new_stock": new_stock}
# ====================================

@router.get("/api/contacts")
def get_contacts(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "clients", "read"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True); c = conn.cursor(); c.execute("SELECT * FROM contacts ORDER BY name ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

@router.post("/api/contacts")
def create_contact(data: ContactData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "clients", "create"):
        return {"error": "forbidden"}
    conn = get_connection(); c = conn.cursor(); c.execute("INSERT INTO contacts (client_id, name, phone, email, position) VALUES (?, ?, ?, ?, ?)", (data.client_id, data.name, data.phone, data.email, data.position)); conn.commit(); conn.close(); return {"status": "success"}
# =========================

@router.get("/api/projects")
def get_projs(request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    user_name = actor.get("name", "")
    user_role = actor.get("role", "")
    is_head = int(actor.get("is_head") or 0)
    conn = get_connection(row_factory=True); c = conn.cursor()
    subordinates = []
    if is_head == 1 and user_role != 'Директор':
        c.execute("SELECT name FROM users WHERE role=?", (user_role,))
        subordinates = [r['name'] for r in c.fetchall()]

    c.execute("SELECT * FROM projects")
    projs = []
    for p in c.fetchall():
        d = dict(p)
        d = _project_payload(d)
        
        team = d.get('team', [])
        manager_name = d.get('manager', '')
        allowed_roles = d.get('allowed_roles', [])
        checked = d.get('checkedState', {})
        
        allowed = False
        
        if user_role == 'Директор': allowed = True
        elif user_name == manager_name or user_name in team: allowed = True
        elif user_role in allowed_roles: allowed = True
        elif is_head == 1 and (manager_name in subordinates or any(t in subordinates for t in team)): allowed = True
        elif user_role == 'Юрист' and "task_4_1" in checked: allowed = True
        elif user_role == 'Бухгалтерия' and "task_2_1" in checked: allowed = True
        elif user_role in ['Конструкторское бюро', 'Производство и ОТК']: allowed = True
        elif not team and not allowed_roles: allowed = True
        
        if allowed: projs.append(d)
    conn.close()
    return projs

@router.post("/api/tenders/parse")
def parse_tender(data: TenderParseData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "create"):
        return {"error": "forbidden"}
    return _parse_tender_payload(data.source, data.text)

@router.post("/api/projects")
async def create_proj(data: ProjectData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "projects", "create"):
        return {"error": "forbidden"}
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM projects WHERE id < 2147483647")
    row = c.fetchone()
    proj_id = _safe_int(row[0] if row else 1)
    if proj_id <= 0:
        proj_id = 1
    manager_name = data.manager or actor.get("name", "")
    c.execute("INSERT INTO projects (id, name, contract, client, manager, status, progress, checkedState, comments, deadlines, budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles, subtasks, time_logs, allowed_roles, nomenclature) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
              (proj_id, data.name, data.contract, data.client, manager_name, 'active', 0, '{}', '{}', '{}', data.budget, data.costs, '[]', '[]', '[]', json.dumps(data.team), json.dumps(data.checklist), '{}', json.dumps(data.archive_details or {}), '{}', '{}', '[]', json.dumps(data.allowed_roles), json.dumps(data.nomenclature)))
    conn.commit()
    conn.close()
    audit_log("project_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="project", entity_id=str(proj_id), details={"name": data.name, "manager": manager_name})
    if manager_name and manager_name != actor.get("name", ""):
        create_notification("Новый проект", f"{actor.get('name', 'Система')} создал(а) проект «{data.name}» и назначил(а) вас менеджером", user_name=manager_name, category="project", entity_type="project", entity_id=str(proj_id))
    await manager.broadcast({"type": "projects"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success"}

@router.put("/api/projects/{proj_id}")
async def update_proj(proj_id: int, data: ProjectUpdate, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    existing = _load_project_row(proj_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Проект не найден")
    existing_project = _project_payload(existing)
    if not can_edit_project(actor, existing_project):
        return {"error": "forbidden"}
    conn = get_connection(); c = conn.cursor()
    c.execute("UPDATE projects SET name=?, contract=?, client=?, manager=?, progress=?, status=?, checkedState=?, comments=?, deadlines=?, budget=?, costs=?, chat=?, files=?, logs=?, team=?, checklist=?, escalations=?, archive_details=?, taskFiles=?, subtasks=?, time_logs=?, allowed_roles=?, nomenclature=? WHERE id=?", 
              (data.name, data.contract, data.client, data.manager, data.progress, data.status, json.dumps(data.checkedState), json.dumps(data.comments), json.dumps(data.deadlines), data.budget, data.costs, json.dumps(data.chat), json.dumps(data.files), json.dumps(data.logs), json.dumps(data.team), json.dumps(data.checklist), json.dumps(data.escalations), json.dumps(data.archive_details), json.dumps(data.taskFiles), json.dumps(data.subtasks), json.dumps(data.time_logs), json.dumps(data.allowed_roles), json.dumps(data.nomenclature), proj_id))
    conn.commit()
    conn.close()
    audit_log("project_updated", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="project", entity_id=str(proj_id), details={"name": data.name, "status": data.status, "progress": data.progress})
    if data.manager and data.manager != actor.get("name", ""):
        create_notification("Проект обновлён", f"В проекте «{data.name}» появились изменения. Проверь карточку проекта.", user_name=data.manager, category="project", entity_type="project", entity_id=str(proj_id))
    await manager.broadcast({"type": "projects"})
    await manager.broadcast({"type": "notifications"})
    return {"status": "success"}

@router.post("/api/projects/{proj_id}/guest_portal")
async def create_guest_portal(proj_id: int, request: Request, regenerate: int = 0):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM projects WHERE id=?", (proj_id,))
    row = c.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Проект не найден")

    project_payload = _project_payload(dict(row))
    if not can_edit_project(actor, project_payload):
        return {"error": "forbidden"}

    archive_details = _json_load(row["archive_details"], {})
    logs = _json_load(row["logs"], [])
    portal = archive_details.get("guest_portal", {})

    if regenerate == 1 or not portal.get("token"):
        portal["token"] = secrets.token_urlsafe(18)
        portal["created_at"] = time.strftime("%d.%m.%Y %H:%M")
        logs.insert(0, {"time": time.strftime("%d.%m.%Y %H:%M"), "user": "Система", "action": "Сгенерирована гостевая ссылка для заказчика"})

    archive_details["guest_portal"] = portal
    c.execute("UPDATE projects SET archive_details=?, logs=? WHERE id=?", (json.dumps(archive_details), json.dumps(logs), proj_id))
    conn.commit()
    conn.close()
    await manager.broadcast({"type": "projects"})
    return {"status": "success", "token": portal["token"], "url": f"/portal/{portal['token']}"}


@router.post("/api/projects/{proj_id}/contract_scan")
async def contract_scan(proj_id: int, data: ContractScanData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM projects WHERE id=?", (proj_id,))
    row = c.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Проект не найден")

    project_payload = _project_payload(dict(row))
    if not can_edit_project(actor, project_payload):
        return {"error": "forbidden"}

    result = _scan_contract_text(data.text)
    archive_details = _json_load(row["archive_details"], {})
    logs = _json_load(row["logs"], [])
    archive_details["contract_scan"] = result
    logs.insert(0, {"time": time.strftime("%d.%m.%Y %H:%M"), "user": "AI-сканер", "action": f"Проверен договор: {result['status']} ({result['score']}/100)"})

    c.execute("UPDATE projects SET archive_details=?, logs=? WHERE id=?", (json.dumps(archive_details), json.dumps(logs), proj_id))
    conn.commit()
    conn.close()
    await manager.broadcast({"type": "projects"})
    return {"status": "success", "result": result}

@router.post("/api/projects/{proj_id}/upload")
async def upload_file(proj_id: int, request: Request, file: UploadFile = File(...), user: str = Form(...), doc_type: str = Form(""), parent_file: str = Form("")):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT files, logs FROM projects WHERE id=?", (proj_id,))
        row = c.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Проект не найден")
        project_payload = _project_payload(dict(row) | {"id": proj_id})
        if not can_edit_project(actor, project_payload):
            return {"error": "forbidden"}
        actual_user = actor.get("name", user)

        safe_filename = _safe_upload_filename(file.filename)
        if os.path.splitext(safe_filename)[1].lower() in BLOCKED_PROJECT_UPLOAD_EXTENSIONS:
            return {"error": "file_validation_failed", "message": "extension_not_allowed"}
        payload = await file.read()
        if not payload:
            return {"error": "file_validation_failed", "message": "empty_file"}
        if len(payload) > MAX_PROJECT_UPLOAD_BYTES:
            return {"error": "file_validation_failed", "message": "file_too_large"}

        files = json.loads(row['files']) if row['files'] else []
        logs = json.loads(row['logs']) if row['logs'] else []

        base_filename = safe_filename
        existing_files = [f for f in files if f.get('base_name', f['name']) == base_filename]
        version = len(existing_files) + 1

        if existing_files:
            latest_file = sorted(existing_files, key=lambda x: x.get('version', 1))[-1]
            if latest_file.get('lockedBy') and latest_file.get('lockedBy') != actual_user:
                raise HTTPException(status_code=403, detail=f"Файл захвачен пользователем: {latest_file.get('lockedBy')}. Дождитесь освобождения.")

        os.makedirs(UPLOADS_DIR, exist_ok=True)
        checksum = hashlib.sha256(payload).hexdigest()[:12]
        stored_filename = f"{int(time.time())}_{int(proj_id or 0)}_{checksum}_{safe_filename}"
        file_path = os.path.join(UPLOADS_DIR, stored_filename)
        with open(file_path, "wb") as buffer:
            buffer.write(payload)

        display_name = f"{base_filename} (v.{version})" if version > 1 else base_filename

        for f in files:
            if f.get('base_name', f['name']) == base_filename:
                f['lockedBy'] = None

        f_obj = {"name": display_name, "base_name": base_filename, "url": f"/uploads/{stored_filename}", "user": actual_user, "time": time.strftime("%d.%m.%Y %H:%M"), "version": version, "lockedBy": None, "doc_type": doc_type, "parent": parent_file}
        files.append(f_obj)

        logs.insert(0, {"time": time.strftime("%d.%m.%Y %H:%M"), "user": actual_user, "action": f"Загрузил файл: {display_name}" if version == 1 else f"Обновил версию файла: {display_name}"})

        c.execute("UPDATE projects SET files=?, logs=? WHERE id=?", (json.dumps(files), json.dumps(logs), proj_id))
        conn.commit()
    finally:
        conn.close()
    
    await manager.broadcast({"type": "projects"}) 
    return {"status": "success", "file": f_obj}

@router.post("/api/projects/{proj_id}/1c_invoice")
async def generate_1c_invoice(proj_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True); c = conn.cursor()
    c.execute("SELECT * FROM projects WHERE id=?", (proj_id,))
    row = c.fetchone()
    if not row: raise HTTPException(status_code=404)
    if not can_edit_project(actor, _project_payload(dict(row))):
        return {"error": "forbidden"}
    
    import asyncio; await asyncio.sleep(1.5) # Эмуляция задержки шлюза REST 1С
    
    filename = f"Счет_1С_{proj_id}_{int(time.time())}.txt"
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    filepath = os.path.join(UPLOADS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"СЧЕТ НА ОПЛАТУ (СГЕНЕРИРОВАНО ИНТЕГРАЦИЕЙ 1С:Предприятие)\nПроект: {row['name']}\nЗаказчик: {row['client']}\nСумма: {row['budget']} руб.\n\nСтатус: Ожидает оплаты")
    runtime_uploads_dir = os.path.join(BASE_DIR, "uploads")
    if os.path.abspath(runtime_uploads_dir) != os.path.abspath(UPLOADS_DIR):
        try:
            os.makedirs(runtime_uploads_dir, exist_ok=True)
            runtime_file_path = os.path.join(runtime_uploads_dir, filename)
            with open(runtime_file_path, "w", encoding="utf-8") as f:
                f.write(f"СЧЕТ НА ОПЛАТУ (СГЕНЕРИРОВАНО ИНТЕГРАЦИЕЙ 1С:Предприятие)\nПроект: {row['name']}\nЗаказчик: {row['client']}\nСумма: {row['budget']} руб.\n\nСтатус: Ожидает оплаты")
        except OSError:
            pass
    
    files = json.loads(row['files']) if row['files'] else []
    logs = json.loads(row['logs']) if row['logs'] else []
    
    f_obj = {"name": filename, "base_name": "Счет_1С", "url": f"/uploads/{filename}", "user": "Интеграция 1С", "time": time.strftime("%d.%m.%Y %H:%M"), "version": 1, "lockedBy": None, "doc_type": "Счет на оплату", "parent": ""}
    files.append(f_obj)
    logs.insert(0, {"time": time.strftime("%d.%m.%Y %H:%M"), "user": "Система 1С", "action": f"🤖 Получен счет из 1С:Бухгалтерии"})
    
    c.execute("UPDATE projects SET files=?, logs=? WHERE id=?", (json.dumps(files), json.dumps(logs), proj_id))
    conn.commit()
    conn.close()
    await manager.broadcast({"type": "projects"})
    return {"status": "success"}


def _load_saved_reports(owner_email: str = "", report_type: str = ""):
    return load_saved_reports_service(
        db_name=DB_NAME,
        json_load=_json_load,
        owner_email=owner_email,
        report_type=report_type,
    )


def _run_saved_report_payload(report: dict, actor: dict):
    return run_saved_report_payload_service(
        report,
        actor,
        finance_analytics_fn=lambda current_actor: _finance_analytics(_filter_finance_rows_for_actor(current_actor, _load_finance_rows())),
        analytics_deep_fn=_analytics_deep_summary,
        dashboard_hub_fn=_analytics_dashboard_hub,
        analytics_drilldown_fn=_analytics_drilldown_payload,
        integration_monitoring_fn=_integration_monitoring_payload,
        operations_monitoring_fn=_operations_monitoring_payload,
        reliability_dashboard_fn=_reliability_dashboard_payload,
    )


def _reconciliation_entity_config():
    return reconciliation_entity_config_service()


def _find_reconciliation_queue_row(c, entity_type: str, queue_entity_id, display_key: str = "", external_id: str = ""):
    if str(queue_entity_id or "").isdigit():
        c.execute(
            """
            SELECT state, external_id, last_error, mapping_key
            FROM integration_sync_queue
            WHERE system_name='1C' AND entity_type=? AND entity_id=?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (entity_type, _safe_int(queue_entity_id)),
        )
        row = c.fetchone()
        if row:
            return row
    mapping_candidates = [
        f"{entity_type}:{display_key}" if display_key else "",
        f"{entity_type}:{queue_entity_id}" if str(queue_entity_id or "") else "",
    ]
    for mapping_key in [item for item in mapping_candidates if item]:
        c.execute(
            """
            SELECT state, external_id, last_error, mapping_key
            FROM integration_sync_queue
            WHERE system_name='1C' AND entity_type=? AND mapping_key=?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (entity_type, mapping_key),
        )
        row = c.fetchone()
        if row:
            return row
    if external_id:
        c.execute(
            """
            SELECT state, external_id, last_error, mapping_key
            FROM integration_sync_queue
            WHERE system_name='1C' AND entity_type=? AND external_id=?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (entity_type, external_id),
        )
        row = c.fetchone()
        if row:
            return row
    return None


def _collect_reconciliation_entity_issues(c, entity_type: str, meta: dict):
    return collect_reconciliation_entity_issues_service(
        c,
        entity_type,
        meta,
        normalize_spaces_fn=_normalize_spaces,
        safe_int_fn=_safe_int,
    )


def _run_integration_reconciliation(actor: dict):
    return run_integration_reconciliation_service(
        get_connection=get_connection,
        actor_email=actor.get("email", ""),
        normalize_spaces_fn=_normalize_spaces,
        safe_int_fn=_safe_int,
    )


def _load_reconciliation_runs(limit: int = 20):
    return load_reconciliation_runs_service(
        get_connection=get_connection,
        json_load_fn=_json_load,
        limit=limit,
    )


def _operations_monitoring_payload(actor: dict):
    return build_operations_monitoring(
        actor,
        db_name=DB_NAME,
        filter_rows_by_scope=filter_rows_by_scope,
        integration_monitoring_payload=_integration_monitoring_payload,
        list_entity_locks=list_entity_locks,
        load_reconciliation_runs=_load_reconciliation_runs,
        reliability_dashboard_payload=_reliability_dashboard_payload,
    )


@router.get("/api/integration/1c/reconciliation")
def get_integration_reconciliation_runs(request: Request, limit: int = 20):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    return _load_reconciliation_runs(limit)


@router.post("/api/integration/1c/reconciliation/run")
def run_integration_reconciliation(request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "finance", "sync_1c") or has_permission(actor, "executive", "read")):
        return {"error": "forbidden"}
    result = _run_integration_reconciliation(actor)
    audit_log(
        "integration_reconciliation_run",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_reconciliation",
        entity_id=str(result.get("run_id") or ""),
        details={"mismatch_count": result.get("mismatch_count", 0)},
    )
    record_domain_event(
        "integration",
        "reconciliation_run",
        entity_type="integration_reconciliation",
        entity_id=str(result.get("run_id") or ""),
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        payload={"mismatch_count": result.get("mismatch_count", 0)},
    )
    return {"status": "success", **result}


@router.get("/api/banking/accounts")
def get_banking_accounts(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return list_bank_accounts_service(get_connection=get_connection, filter_rows_by_scope_fn=filter_rows_by_scope, actor=actor)


@router.post("/api/banking/accounts")
def create_banking_account(data: BankAccountData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "manage_master"):
        return {"error": "forbidden"}
    if not _assert_finance_scope(actor, data.legal_entity_id, 0):
        return {"error": "forbidden_scope"}
    account_id = create_bank_account_record_service(get_connection=get_connection, actor=actor, data=data, safe_int_fn=_safe_int)
    audit_log("bank_account_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="bank_account", entity_id=str(account_id), details={"name": data.name, "bank_name": data.bank_name})
    record_domain_event("banking", "bank_account_created", entity_type="bank_account", entity_id=str(account_id), actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), payload={"name": data.name, "bank_name": data.bank_name})
    return {"status": "success", "id": account_id}


@router.get("/api/banking/statements")
def get_bank_statement_lines(request: Request, unreconciled: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return list_bank_statement_lines_service(get_connection=get_connection, unreconciled=unreconciled)


@router.post("/api/banking/statements/import")
def import_bank_statement_lines(data: BankStatementImportData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "create"):
        return {"error": "forbidden"}
    created = import_bank_statement_records_service(
        get_connection=get_connection,
        actor=actor,
        data=data,
        safe_int_fn=_safe_int,
        safe_float_fn=_safe_float,
        today_display_fn=_today_display,
    )
    audit_log("bank_statement_imported", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="bank_statement", entity_id=",".join(str(item) for item in created[:10]), details={"count": len(created)})
    record_domain_event("banking", "statement_imported", entity_type="bank_statement", entity_id=",".join(str(item) for item in created[:10]), actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), payload={"count": len(created)})
    return {"status": "success", "created": len(created), "ids": created[:50]}


@router.post("/api/banking/statements/{line_id}/reconcile")
def reconcile_bank_statement_line(line_id: int, data: BankStatementReconcileData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "update"):
        return {"error": "forbidden"}
    result = reconcile_bank_statement_record_service(
        get_connection=get_connection,
        line_id=line_id,
        payment_id=_safe_int(data.payment_id),
        safe_int_fn=_safe_int,
        safe_float_fn=_safe_float,
        today_display_fn=_today_display,
        get_finance_payment_row_fn=_get_finance_payment_row_from_conn,
        rebuild_finance_accounting_entries_fn=_rebuild_finance_accounting_entries,
        upsert_finance_sync_job_fn=_upsert_finance_sync_job,
        actor_email=actor.get("email", ""),
    )
    if result.get("error"):
        return result
    payment_id = _safe_int(result.get("payment_id"))
    audit_log("bank_statement_reconciled", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="bank_statement_line", entity_id=str(line_id), details={"payment_id": payment_id})
    record_domain_event("banking", "statement_reconciled", entity_type="bank_statement_line", entity_id=str(line_id), actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), payload={"payment_id": payment_id})
    return {"status": "success", "payment_id": payment_id}


@router.get("/api/telephony/accounts")
def get_telephony_accounts(request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "read"):
        return {"error": "forbidden"}
    return list_telephony_accounts_service(get_connection=get_connection)


@router.post("/api/telephony/accounts")
def create_telephony_account(data: TelephonyAccountData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (has_permission(actor, "chats", "create") or has_permission(actor, "chats", "update")):
        return {"error": "forbidden"}
    account_id = create_telephony_account_record_service(get_connection=get_connection, actor=actor, data=data)
    audit_log("telephony_account_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="telephony_account", entity_id=str(account_id), details={"line_name": data.line_name})
    record_domain_event("telephony", "account_created", entity_type="telephony_account", entity_id=str(account_id), actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), payload={"line_name": data.line_name})
    return {"status": "success", "id": account_id}


@router.get("/api/telephony/calls")
def get_telephony_calls(request: Request, client_id: int = 0):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "read"):
        return {"error": "forbidden"}
    return list_telephony_calls_service(get_connection=get_connection, client_id=client_id)


@router.post("/api/telephony/calls")
def create_telephony_call(data: TelephonyCallData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "chats", "create"):
        return {"error": "forbidden"}
    now = int(time.time())
    call_at = (data.call_at or "").strip() or datetime.now().strftime("%d.%m.%Y %H:%M")
    result = create_telephony_call_record_service(
        get_connection=get_connection,
        actor=actor,
        data=data,
        safe_int_fn=_safe_int,
        now_timestamp=now,
        call_at=call_at,
    )
    call_id = _safe_int(result.get("id"))
    resolved_client_id = _safe_int(result.get("client_id"))
    resolved_project_id = _safe_int(result.get("project_id"))
    if (data.status or "") in {"missed", "failed"}:
        create_notification(
            "Пропущенный звонок",
            f"{result.get('contact_name') or data.phone_number or 'Контакт'} · {data.summary or 'Проверь карточку звонка и перезвони.'}",
            user_email=actor.get("email", ""),
            category="chat",
            entity_type="telephony_call",
            entity_id=str(call_id),
        )
    audit_log("telephony_call_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="telephony_call", entity_id=str(call_id), details={"client_id": resolved_client_id, "project_id": resolved_project_id, "status": data.status, "direction": data.direction, "auto_linked": int(result.get("auto_linked") or 0)})
    record_domain_event("telephony", "call_created", entity_type="telephony_call", entity_id=str(call_id), actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), payload={"client_id": resolved_client_id, "project_id": resolved_project_id, "auto_linked": int(result.get("auto_linked") or 0)})
    return {"status": "success", "id": call_id}


@router.get("/api/analytics/reports")
def get_saved_reports(request: Request, report_type: str = ""):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    return _load_saved_reports(actor.get("email", ""), report_type)


@router.get("/api/analytics/deep")
def get_analytics_deep(request: Request):
    actor = require_approved_user(request)
    if not actor or not (
        has_permission(actor, "finance", "read")
        or has_permission(actor, "executive", "read")
        or actor.get("role") == "Директор"
    ):
        return {"error": "forbidden"}
    return _analytics_deep_summary(actor)


@router.get("/api/analytics/dashboards")
def get_analytics_dashboards(request: Request):
    actor = require_approved_user(request)
    if not actor or not (
        has_permission(actor, "finance", "read")
        or has_permission(actor, "executive", "read")
        or actor.get("role") == "Директор"
    ):
        return {"error": "forbidden"}
    return _analytics_dashboard_hub(actor)


@router.get("/api/analytics/drilldown")
def get_analytics_drilldown(request: Request, dimension: str = "", value: str = "", value_id: int = 0, limit: int = 50):
    actor = require_approved_user(request)
    if not actor or not (
        has_permission(actor, "finance", "read")
        or has_permission(actor, "executive", "read")
        or actor.get("role") == "Директор"
    ):
        return {"error": "forbidden"}
    if not (dimension or value_id or value):
        return {"error": "dimension_required"}
    return _analytics_drilldown_payload(actor, dimension, value, value_id, limit)


@router.post("/api/analytics/reports")
def create_saved_report(data: SavedReportData, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "export"):
        return {"error": "forbidden"}
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    c.execute(
        """
        INSERT INTO saved_reports (report_type, title, filters, layout, scope, owner_email, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.report_type or "finance_analytics",
            data.title or "Новый ERP-отчет",
            json.dumps(data.filters or {}, ensure_ascii=False),
            json.dumps(data.layout or {}, ensure_ascii=False),
            data.scope or "private",
            actor.get("email", ""),
            now,
            now,
        ),
    )
    report_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log("saved_report_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="saved_report", entity_id=str(report_id), details={"report_type": data.report_type, "title": data.title})
    return {"status": "success", "id": report_id}


@router.post("/api/analytics/reports/{report_id}/run")
def run_saved_report(report_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "read"):
        return {"error": "forbidden"}
    reports = [row for row in _load_saved_reports(actor.get("email", "")) if _safe_int(row.get("id")) == _safe_int(report_id)]
    if not reports:
        return {"error": "not_found"}
    payload = _run_saved_report_payload(reports[0], actor)
    return {"status": "success", "report": reports[0], "payload": payload}


@router.delete("/api/analytics/reports/{report_id}")
def delete_saved_report(report_id: int, request: Request):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "finance", "export"):
        return {"error": "forbidden"}
    reports = [row for row in _load_saved_reports(actor.get("email", "")) if _safe_int(row.get("id")) == _safe_int(report_id)]
    if not reports:
        return {"error": "not_found"}
    report = reports[0]
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM saved_reports WHERE id=?", (report_id,))
    conn.commit()
    conn.close()
    audit_log(
        "saved_report_deleted",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="saved_report",
        entity_id=str(report_id),
        details={"report_type": report.get("report_type"), "title": report.get("title")},
    )
    return {"status": "success", "id": report_id}


@router.get("/api/locks")
def get_operational_locks(request: Request, entity_type: str = "", limit: int = 80):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    return list_entity_locks(limit=limit, entity_type=entity_type)


@router.post("/api/locks/acquire")
def acquire_operational_lock(data: EntityLockData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    result = acquire_entity_lock(
        entity_type=(data.entity_type or "").strip(),
        entity_id=str(data.entity_id or "").strip(),
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        session_id=_request_session_id(request),
        force=int(data.force or 0),
    )
    if result.get("error"):
        return result
    audit_log("entity_lock_acquired", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=data.entity_type, entity_id=str(data.entity_id), details={"force": int(data.force or 0)})
    return result


@router.post("/api/locks/release")
def release_operational_lock(data: EntityLockData, request: Request):
    actor = require_approved_user(request)
    if not actor:
        return {"error": "forbidden"}
    deleted = release_entity_lock(
        entity_type=(data.entity_type or "").strip(),
        entity_id=str(data.entity_id or "").strip(),
        actor_email=actor.get("email", ""),
        session_id=_request_session_id(request),
        force=int(data.force or 0),
    )
    audit_log("entity_lock_released", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type=data.entity_type, entity_id=str(data.entity_id), details={"deleted": deleted})
    return {"status": "success", "deleted": deleted}


@router.get("/api/operations/monitoring")
def get_operations_monitoring(request: Request):
    actor = require_approved_user(request)
    if not actor or not (
        has_permission(actor, "executive", "read")
        or has_permission(actor, "finance", "read")
        or has_permission(actor, "chats", "read")
        or actor.get("role") == "Директор"
    ):
        return {"error": "forbidden"}
    return _operations_monitoring_payload(actor)


@router.get("/api/system/reliability")
def get_system_reliability(request: Request):
    actor = require_approved_user(request)
    if not actor or not (
        has_permission(actor, "executive", "read")
        or has_permission(actor, "finance", "read")
        or actor.get("role") == "Директор"
    ):
        return {"error": "forbidden"}
    return _reliability_dashboard_payload(actor)


@router.get("/api/system/runtime")
def get_system_runtime(request: Request):
    actor = require_approved_user(request)
    if not actor or not (
        has_permission(actor, "executive", "read")
        or has_permission(actor, "finance", "read")
        or actor.get("role") == "Директор"
    ):
        return {"error": "forbidden"}
    return _system_runtime_payload(actor)


@router.get("/api/system/events")
def get_system_events(request: Request, limit: int = 120, entity_type: str = ""):
    actor = require_approved_user(request)
    if not actor or not (
        has_permission(actor, "executive", "read")
        or has_permission(actor, "finance", "read")
        or has_permission(actor, "chats", "read")
        or actor.get("role") == "Директор"
    ):
        return {"error": "forbidden"}
    return _system_event_stream_payload(limit=limit, entity_type=entity_type)


@router.post("/api/system/recovery/run")
def run_system_recovery(data: SystemRecoveryActionData, request: Request):
    actor = require_approved_user(request)
    if not actor or not (
        has_permission(actor, "executive", "update")
        or has_permission(actor, "finance", "update")
        or actor.get("role") == "Директор"
    ):
        return {"error": "forbidden"}
    result = _run_system_recovery_action(actor, data)
    audit_log(
        "system_recovery_run",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="system_recovery",
        entity_id=str(result.get("run_id") or ""),
        details=result,
    )
    return {"status": "success" if not result.get("error") else "failed", **result}


from routers.ops_extensions import register_extended_ops_routes
register_extended_ops_routes(router, globals())
