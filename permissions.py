import json

from auth_security import get_request_user
from database import get_field_access_rules
from services.policy_service import build_field_policy_map
from utils import normalize_email


DIRECTOR_ROLE = "Директор"
MANAGER_ROLE = "Менеджер"
ENGINEERING_ROLE = "Конструкторское бюро"
PRODUCTION_ROLE = "Производство и ОТК"
WAREHOUSE_ROLE = "Склад"
ACCOUNTING_ROLE = "Бухгалтерия"
LEGAL_ROLE = "Юрист"
EMPLOYEE_ROLE = "Сотрудник"
SECRETARY_ROLE = "Секретарь / Канцелярия"

CANONICAL_ROLES = [
    DIRECTOR_ROLE,
    MANAGER_ROLE,
    ENGINEERING_ROLE,
    PRODUCTION_ROLE,
    WAREHOUSE_ROLE,
    ACCOUNTING_ROLE,
    LEGAL_ROLE,
    SECRETARY_ROLE,
    EMPLOYEE_ROLE,
]

PERMISSION_MATRIX = {
    DIRECTOR_ROLE: {
        "projects": ["read", "create", "update", "delete", "finance", "share"],
        "finance": ["read", "create", "update", "delete", "mark_paid", "export", "reconcile", "post", "close_period", "sync_1c", "manage_master", "manage_limits", "sign_edo"],
        "supply": ["read", "create", "update", "delete", "reserve", "receive", "export"],
        "sales": ["read", "create", "update", "delete", "ship", "confirm", "export"],
        "production": ["read", "create", "update", "delete", "release", "complete"],
        "expenses": ["read", "create", "update", "approve", "delete", "route", "pay"],
        "requests": ["read", "create", "update", "approve", "delete", "route", "link", "export"],
        "resources": ["read", "create", "update", "delete", "assign"],
        "service": ["read", "create", "update", "delete"],
        "executive": ["read"],
        "documents": ["read", "create", "update", "delete"],
        "tasks": ["read", "create", "update", "delete", "assign"],
        "knowledge": ["read", "create", "update", "delete"],
        "approvals": ["read", "create", "update", "approve", "route"],
        "meetings": ["read", "create", "update"],
        "chats": ["read", "create", "update", "delete"],
        "emails": ["read", "reply", "archive", "delete", "manage_accounts"],
        "clients": ["read", "create", "update", "merge", "export", "import"],
        "nsi": ["read", "create", "update", "delete", "cleanup", "export", "import"],
        "users": ["read", "approve", "update", "block", "restore"],
        "system": ["audit", "errors", "backup", "download_backup"],
    },
    MANAGER_ROLE: {
        "projects": ["read", "create", "update", "finance"],
        "finance": ["read", "create", "update", "export"],
        "supply": ["read", "create", "update", "reserve"],
        "sales": ["read", "create", "update", "ship"],
        "production": ["read", "create", "update"],
        "expenses": ["read", "create", "update", "route"],
        "requests": ["read", "create", "update", "route", "link", "export"],
        "resources": ["read", "create", "update", "assign"],
        "service": ["read", "create", "update"],
        "executive": [],
        "documents": ["read", "create", "update"],
        "tasks": ["read", "create", "update"],
        "knowledge": ["read", "create"],
        "approvals": ["read", "create", "update", "route"],
        "meetings": ["read", "create", "update"],
        "chats": ["read", "create"],
        "emails": ["read", "reply", "archive", "manage_accounts"],
        "clients": ["read", "create", "update"],
        "nsi": ["read", "create", "update", "export"],
        "users": [],
        "system": [],
    },
    ENGINEERING_ROLE: {
        "projects": ["read", "update"],
        "finance": ["read"],
        "supply": ["read", "reserve"],
        "sales": ["read"],
        "production": ["read", "update", "release"],
        "expenses": ["read"],
        "requests": ["read", "create", "update", "route"],
        "resources": ["read", "update", "assign"],
        "service": ["read", "update"],
        "executive": [],
        "documents": ["read", "create", "update"],
        "tasks": ["read", "update"],
        "knowledge": ["read"],
        "approvals": ["read", "approve", "route"],
        "meetings": ["read"],
        "chats": ["read", "create"],
        "emails": ["read"],
        "clients": ["read"],
        "nsi": ["read", "update"],
        "users": [],
        "system": [],
    },
    PRODUCTION_ROLE: {
        "projects": ["read", "update"],
        "finance": ["read"],
        "supply": ["read", "update", "reserve", "receive"],
        "sales": ["read"],
        "production": ["read", "create", "update", "release", "complete"],
        "expenses": ["read"],
        "requests": ["read", "create", "update", "route"],
        "resources": ["read", "update", "assign"],
        "service": ["read", "create", "update"],
        "executive": [],
        "documents": ["read"],
        "tasks": ["read", "update"],
        "knowledge": ["read"],
        "approvals": ["read", "approve"],
        "meetings": ["read"],
        "chats": ["read", "create"],
        "emails": ["read"],
        "clients": ["read"],
        "nsi": ["read", "update"],
        "users": [],
        "system": [],
    },
    WAREHOUSE_ROLE: {
        "projects": ["read", "update"],
        "finance": ["read"],
        "supply": ["read", "create", "update", "reserve", "receive", "export"],
        "sales": ["read"],
        "production": ["read", "update"],
        "expenses": ["read"],
        "requests": ["read", "create", "update", "route"],
        "resources": ["read"],
        "service": ["read", "create", "update"],
        "executive": [],
        "documents": ["read", "create", "update"],
        "tasks": ["read", "update"],
        "knowledge": ["read"],
        "approvals": ["read", "approve"],
        "meetings": ["read"],
        "chats": ["read", "create"],
        "emails": ["read"],
        "clients": ["read"],
        "nsi": ["read", "update"],
        "users": [],
        "system": [],
    },
    ACCOUNTING_ROLE: {
        "projects": ["read", "update", "finance"],
        "finance": ["read", "create", "update", "mark_paid", "reconcile", "export", "post", "close_period", "sync_1c", "manage_master", "manage_limits", "sign_edo"],
        "supply": ["read"],
        "sales": ["read", "create", "update", "confirm", "export"],
        "production": ["read"],
        "expenses": ["read", "create", "update", "approve", "route", "pay"],
        "requests": ["read", "create", "update", "route"],
        "resources": ["read"],
        "service": ["read"],
        "executive": [],
        "documents": ["read", "create", "update"],
        "tasks": ["read", "update"],
        "knowledge": ["read"],
        "approvals": ["read", "approve", "route"],
        "meetings": ["read"],
        "chats": ["read", "create"],
        "emails": ["read", "manage_accounts"],
        "clients": ["read"],
        "nsi": ["read"],
        "users": [],
        "system": [],
    },
    LEGAL_ROLE: {
        "projects": ["read", "update"],
        "finance": ["read"],
        "supply": ["read"],
        "sales": ["read"],
        "production": ["read"],
        "expenses": ["read"],
        "requests": ["read", "create", "update", "approve", "route"],
        "resources": ["read"],
        "service": ["read", "create", "update"],
        "executive": [],
        "documents": ["read", "create", "update"],
        "tasks": ["read", "update"],
        "knowledge": ["read"],
        "approvals": ["read", "approve", "route"],
        "meetings": ["read"],
        "chats": ["read", "create"],
        "emails": ["read"],
        "clients": ["read"],
        "nsi": ["read"],
        "users": [],
        "system": [],
    },
    SECRETARY_ROLE: {
        "projects": ["read"],
        "finance": ["read"],
        "supply": ["read"],
        "sales": ["read"],
        "production": ["read"],
        "expenses": ["read"],
        "requests": ["read", "create", "update", "route"],
        "resources": ["read"],
        "service": ["read"],
        "executive": [],
        "documents": ["read", "create", "update", "delete"],
        "tasks": ["read", "create", "update", "assign"],
        "knowledge": ["read"],
        "approvals": ["read", "create", "update", "route"],
        "meetings": ["read", "create", "update"],
        "chats": ["read", "create"],
        "emails": ["read", "reply", "archive", "delete", "manage_accounts"],
        "clients": ["read", "create", "update", "merge", "import", "export"],
        "nsi": ["read"],
        "users": [],
        "system": [],
    },
    EMPLOYEE_ROLE: {
        "projects": ["read"],
        "finance": [],
        "supply": ["read"],
        "sales": ["read"],
        "production": ["read"],
        "expenses": ["read", "create"],
        "requests": ["read", "create", "update"],
        "resources": ["read"],
        "service": ["read", "create"],
        "executive": [],
        "documents": ["read", "create"],
        "tasks": ["read", "create", "update"],
        "knowledge": ["read"],
        "approvals": ["read"],
        "meetings": ["read"],
        "chats": ["read", "create"],
        "emails": ["read"],
        "clients": ["read"],
        "nsi": ["read"],
        "users": [],
        "system": [],
    },
}


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _try_redecode(value: str, source_encoding: str, target_encoding: str) -> str:
    try:
        return value.encode(source_encoding).decode(target_encoding)
    except Exception:
        return value


def _canonical_role_name(role: str) -> str:
    normalized = _normalize_text(role)
    if not normalized:
        return ""
    if normalized in PERMISSION_MATRIX:
        return normalized

    candidates = {
        normalized,
        _try_redecode(normalized, "latin1", "utf-8"),
        _try_redecode(normalized, "cp1252", "utf-8"),
        _try_redecode(normalized, "latin1", "cp1251"),
        _try_redecode(normalized, "cp1252", "cp1251"),
    }
    normalized_candidates = {_normalize_text(item) for item in candidates if _normalize_text(item)}
    canonical_index = {_normalize_text(item): item for item in CANONICAL_ROLES}
    for candidate in normalized_candidates:
        if candidate in canonical_index:
            return canonical_index[candidate]
    return normalized


def require_approved_user(request):
    user = get_request_user(request)
    if not user or user.get("status") != "approved":
        return None
    actor = dict(user)
    actor["role"] = _canonical_role_name(actor.get("role", ""))
    return actor


def require_director(request):
    user = require_approved_user(request)
    if not user or _canonical_role_name(user.get("role", "")) != DIRECTOR_ROLE:
        return None
    return user


def has_permission(user: dict, module: str, action: str) -> bool:
    if not user:
        return False
    role = _canonical_role_name(user.get("role", ""))
    permissions = PERMISSION_MATRIX.get(role, {})
    allowed_actions = permissions.get(module, [])
    return action in allowed_actions


def can_access_project(user: dict, project: dict) -> bool:
    if not user or not project:
        return False
    user_name = user.get("name", "")
    user_role = _canonical_role_name(user.get("role", ""))
    is_head = int(user.get("is_head") or 0)
    team = project.get("team") or []
    manager_name = project.get("manager", "")
    allowed_roles = [_canonical_role_name(item) for item in (project.get("allowed_roles") or [])]
    checked = project.get("checkedState") or {}
    if user_role == DIRECTOR_ROLE:
        return True
    if user_name == manager_name or user_name in team:
        return True
    if user_role in allowed_roles:
        return True
    if user_role == LEGAL_ROLE and "task_4_1" in checked:
        return True
    if user_role == ACCOUNTING_ROLE and "task_2_1" in checked:
        return True
    if user_role in [ENGINEERING_ROLE, PRODUCTION_ROLE, WAREHOUSE_ROLE]:
        return True
    if is_head == 1 and manager_name:
        return True
    if not team and not allowed_roles:
        return True
    return False


def can_edit_project(user: dict, project: dict) -> bool:
    if not can_access_project(user, project):
        return False
    role = _canonical_role_name((user or {}).get("role", ""))
    if role == DIRECTOR_ROLE:
        return True
    if user.get("name") == project.get("manager"):
        return True
    if user.get("name") in (project.get("team") or []):
        return True
    return role in [MANAGER_ROLE, ENGINEERING_ROLE, PRODUCTION_ROLE, WAREHOUSE_ROLE, LEGAL_ROLE, ACCOUNTING_ROLE]


def sanitize_user_email(value: str) -> str:
    return normalize_email(value)


def safe_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _coerce_scope_ids(value):
    raw = value if isinstance(value, list) else safe_json(value, [])
    if not isinstance(raw, list):
        return set()
    result = set()
    for item in raw:
        try:
            parsed = int(item)
        except Exception:
            continue
        if parsed > 0:
            result.add(parsed)
    return result


def get_user_scope_ids(user: dict):
    actor = user or {}
    return {
        "legal_entities": _coerce_scope_ids(actor.get("allowed_legal_entities")),
        "business_units": _coerce_scope_ids(actor.get("allowed_business_units")),
    }


def can_access_scope(user: dict, legal_entity_id: int = 0, business_unit_id: int = 0) -> bool:
    if not user:
        return False
    if _canonical_role_name(user.get("role", "")) == DIRECTOR_ROLE:
        return True
    legal_entity_id = int(legal_entity_id or 0)
    business_unit_id = int(business_unit_id or 0)
    scope = get_user_scope_ids(user)
    allowed_legal = scope["legal_entities"]
    allowed_bu = scope["business_units"]
    if allowed_legal and not legal_entity_id:
        return False
    if allowed_bu and not business_unit_id:
        return False
    if allowed_legal and legal_entity_id and legal_entity_id not in allowed_legal:
        return False
    if allowed_bu and business_unit_id and business_unit_id not in allowed_bu:
        return False
    return True


def filter_rows_by_scope(user: dict, rows: list[dict], legal_field: str = "legal_entity_id", bu_field: str = "business_unit_id"):
    if not rows:
        return []
    return [
        row for row in rows
        if can_access_scope(user, row.get(legal_field) or 0, row.get(bu_field) or 0)
    ]


def get_role_permissions(user: dict):
    role = _canonical_role_name((user or {}).get("role", ""))
    permissions = PERMISSION_MATRIX.get(role, {})
    scope = get_user_scope_ids(user)
    field_rules = get_field_access_rules(role=role, is_active=1)
    field_policy_map = build_field_policy_map(field_rules)
    return {
        "role": role,
        "permissions": permissions,
        "field_permissions": field_rules,
        "field_policy_map": field_policy_map,
        "scope": {
            "legal_entities": sorted(scope["legal_entities"]),
            "business_units": sorted(scope["business_units"]),
        },
        "two_factor_enabled": int((user or {}).get("two_factor_enabled") or 0),
    }


def get_field_permissions(user: dict, module: str, entity_type: str) -> dict:
    role = _canonical_role_name((user or {}).get("role", ""))
    rules = get_field_access_rules(role=role, module=module, entity_type=entity_type, is_active=1)
    result = {}
    for row in rules:
        result[row.get("field_name", "")] = {
            "can_view": int(row.get("can_view") or 0),
            "can_edit": int(row.get("can_edit") or 0),
            "allowed_statuses": row.get("allowed_statuses") or [],
        }
    return result


def has_field_permission(user: dict, module: str, entity_type: str, field_name: str, mode: str = "edit") -> bool:
    if not user:
        return False
    if _canonical_role_name(user.get("role", "")) == DIRECTOR_ROLE:
        return True
    rule = get_field_permissions(user, module, entity_type).get(field_name)
    if not rule:
        return True
    if mode == "view":
        return bool(rule.get("can_view"))
    return bool(rule.get("can_edit"))


def get_allowed_statuses(user: dict, module: str, entity_type: str, field_name: str = "status") -> list[str]:
    if not user or _canonical_role_name(user.get("role", "")) == DIRECTOR_ROLE:
        return []
    rule = get_field_permissions(user, module, entity_type).get(field_name) or {}
    allowed = rule.get("allowed_statuses") or []
    return [str(item) for item in allowed if str(item).strip()]
