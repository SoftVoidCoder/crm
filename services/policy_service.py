STATUS_GUARDED_FIELDS = {
    "status",
    "payment_status",
    "integration_status",
    "exchange_state",
    "stage",
    "sent_status",
    "shipment_status",
    "reserve_status",
    "request_status",
    "version_status",
    "archive_status",
}


def build_field_policy_map(rules: list[dict] | None) -> dict:
    result: dict[str, dict[str, dict[str, dict]]] = {}
    for row in rules or []:
        module = str(row.get("module") or row.get("module_name") or "").strip()
        entity_type = str(row.get("entity_type") or "").strip()
        field_name = str(row.get("field_name") or "").strip()
        if not module or not entity_type or not field_name:
            continue
        result.setdefault(module, {}).setdefault(entity_type, {})[field_name] = {
            "can_view": int(row.get("can_view") or 0),
            "can_edit": int(row.get("can_edit") or 0),
            "allowed_statuses": [str(item) for item in (row.get("allowed_statuses") or []) if str(item).strip()],
            "is_active": int(row.get("is_active") or 0),
        }
    return result


def build_form_policy_payload(user: dict, module: str, entity_type: str, get_field_permissions_fn) -> dict:
    field_permissions = get_field_permissions_fn(user, module, entity_type)
    hidden_fields = []
    readonly_fields = []
    restricted_status_fields = {}
    messages = {}
    status_fields = []
    for field_name, meta in field_permissions.items():
        can_view = int(meta.get("can_view") or 0) == 1
        can_edit = int(meta.get("can_edit") or 0) == 1
        allowed_statuses = [str(item) for item in (meta.get("allowed_statuses") or []) if str(item).strip()]
        if not can_view:
            hidden_fields.append(field_name)
            messages[field_name] = "Поле скрыто политикой доступа"
            continue
        if not can_edit:
            readonly_fields.append(field_name)
            messages[field_name] = "Поле доступно только для просмотра"
        if allowed_statuses:
            restricted_status_fields[field_name] = allowed_statuses
            if field_name in STATUS_GUARDED_FIELDS:
                status_fields.append(field_name)
            suffix = f"Разрешённые статусы: {', '.join(allowed_statuses)}"
            messages[field_name] = f"{messages.get(field_name, '')}. {suffix}".strip(". ").replace("..", ".")
    return {
        "module": module,
        "entity_type": entity_type,
        "fields": field_permissions,
        "hidden_fields": hidden_fields,
        "readonly_fields": readonly_fields,
        "restricted_status_fields": restricted_status_fields,
        "messages": messages,
        "status_fields": sorted(set(status_fields)),
        "policy_hints": {
            "has_hidden_fields": bool(hidden_fields),
            "has_readonly_fields": bool(readonly_fields),
            "has_status_restrictions": bool(restricted_status_fields),
        },
    }


def explain_policy_error(error_payload: dict | None) -> str:
    payload = error_payload or {}
    error_code = str(payload.get("error") or "").strip()
    if error_code == "forbidden_field":
        field_name = str(payload.get("field") or "поле")
        return f"Поле «{field_name}» нельзя менять по текущей policy."
    if error_code == "forbidden_status":
        field_name = str(payload.get("field") or "статус")
        allowed = [str(item) for item in (payload.get("allowed_statuses") or []) if str(item).strip()]
        suffix = f" Разрешено: {', '.join(allowed)}." if allowed else ""
        return f"Поле «{field_name}» нельзя перевести в этот статус.{suffix}"
    if error_code == "policy_blocked":
        return str(payload.get("message") or "Действие запрещено policy-layer.")
    if error_code == "danger_blocked":
        return str(payload.get("message") or "Опасная операция заблокирована для этой роли.")
    if error_code == "two_factor_required":
        return str(payload.get("message") or "Для этого действия нужно включить 2FA.")
    if error_code == "reason_required":
        return str(payload.get("message") or "Для опасной операции нужно указать причину.")
    return str(payload.get("message") or error_code or "")


def evaluate_security_gate(
    actor: dict,
    module_name: str,
    entity_type: str,
    action_name: str,
    *,
    status_name: str = "",
    reason: str = "",
    get_policy_fn,
    get_danger_rule_fn,
) -> dict | None:
    policy = get_policy_fn(actor, module_name, entity_type, action_name, status_name)
    if policy and int(policy.get("allow_execute") or 0) != 1:
        return {"error": "policy_blocked", "message": "Действие запрещено policy-layer.", "policy": policy}
    if policy and int(policy.get("require_2fa") or 0) == 1 and int(actor.get("two_factor_enabled") or 0) != 1:
        return {"error": "two_factor_required", "message": "Для этого действия нужно включить 2FA.", "policy": policy}
    if policy and int(policy.get("require_reason") or 0) == 1 and not str(reason or "").strip():
        return {"error": "reason_required", "message": "Для этого действия policy требует указать причину.", "policy": policy, "needs_reason": True}

    danger = get_danger_rule_fn(module_name, entity_type, action_name)
    if danger:
        blocked_roles = {str(item) for item in danger.get("blocked_roles") or []}
        if actor.get("role") in blocked_roles:
            return {"error": "danger_blocked", "message": "Опасная операция заблокирована для этой роли.", "danger_rule": danger}
        if int(danger.get("require_2fa") or 0) == 1 and int(actor.get("two_factor_enabled") or 0) != 1:
            return {"error": "two_factor_required", "message": "Для опасной операции нужно включить 2FA.", "danger_rule": danger}
        if int(danger.get("require_reason") or 0) == 1 and not str(reason or "").strip():
            return {"error": "reason_required", "message": "Для опасной операции нужно указать причину.", "danger_rule": danger, "needs_reason": True}
    return None


def build_security_matrix_snapshot(*, permission_matrix: dict, field_rules: list[dict] | None = None, action_policies: list[dict] | None = None, danger_rules: list[dict] | None = None) -> dict:
    field_rules = field_rules or []
    action_policies = action_policies or []
    danger_rules = danger_rules or []
    rows = []
    seen = set()

    def _append_row(role_name: str, module_name: str, actions: list | None):
        key = (str(role_name), str(module_name))
        if key in seen:
            return
        seen.add(key)
        scoped_field_rules = [
            row for row in field_rules
            if str(row.get("role") or row.get("role_name") or "") == str(role_name)
            and str(row.get("module") or row.get("module_name") or "") == str(module_name)
        ]
        scoped_policies = [row for row in action_policies if str(row.get("role_name") or "") == str(role_name) and str(row.get("module_name") or "") == str(module_name)]
        scoped_danger = [row for row in danger_rules if str(row.get("module_name") or "") == str(module_name) and str(role_name) in {str(item) for item in (row.get("blocked_roles") or [])}]
        rows.append({
            "role_name": role_name,
            "module_name": module_name,
            "actions_total": len(actions or []),
            "field_rules_total": len(scoped_field_rules),
            "status_rules_total": len([row for row in scoped_field_rules if row.get("allowed_statuses")]),
            "action_policies_total": len(scoped_policies),
            "danger_rules_total": len(scoped_danger),
            "covered": bool(scoped_field_rules or scoped_policies or scoped_danger),
        })

    for role_name, modules in (permission_matrix or {}).items():
        for module_name, actions in (modules or {}).items():
            _append_row(role_name, module_name, actions or [])
    for row in field_rules:
        _append_row(
            str(row.get("role") or row.get("role_name") or ""),
            str(row.get("module") or row.get("module_name") or ""),
            [],
        )
    for row in action_policies:
        _append_row(str(row.get("role_name") or ""), str(row.get("module_name") or ""), [])
    for row in danger_rules:
        for role_name in [str(item) for item in (row.get("blocked_roles") or []) if str(item).strip()] or ["*"]:
            _append_row(role_name, str(row.get("module_name") or ""), [])
    covered_rows = [row for row in rows if row["covered"]]
    return {
        "rows": rows,
        "metrics": {
            "matrix_rows_total": len(rows),
            "matrix_rows_covered": len(covered_rows),
            "matrix_coverage_percent": round((len(covered_rows) / len(rows) * 100), 1) if rows else 0,
        },
    }


def enforce_field_update_permissions(
    actor: dict,
    module: str,
    entity_type: str,
    incoming: dict,
    existing: dict | None,
    *,
    has_field_permission_fn,
    get_allowed_statuses_fn,
):
    existing = existing or {}
    for field_name, new_value in (incoming or {}).items():
        if str(field_name).startswith("_"):
            continue
        old_value = existing.get(field_name)
        if existing and old_value == new_value:
            continue
        if not has_field_permission_fn(actor, module, entity_type, field_name, "edit"):
            return {"error": "forbidden_field", "field": field_name}
        if field_name in STATUS_GUARDED_FIELDS:
            allowed_statuses = get_allowed_statuses_fn(actor, module, entity_type, field_name)
            if allowed_statuses and str(new_value or "") not in allowed_statuses:
                return {"error": "forbidden_status", "field": field_name, "allowed_statuses": allowed_statuses}
    return None
