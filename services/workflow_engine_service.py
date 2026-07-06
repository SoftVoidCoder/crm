import json
import operator
import time


ACTIVE_TOKEN_STATUSES = {"active", "rework", "escalated", "waiting"}
FINAL_INSTANCE_STATUSES = {"completed", "rejected", "cancelled"}


def _safe_text(value) -> str:
    return str(value or "").strip()


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _row_dict(row) -> dict:
    if not row:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return {}


def _json_dict(raw_value) -> dict:
    if isinstance(raw_value, dict):
        return raw_value
    if not raw_value:
        return {}
    try:
        data = json.loads(raw_value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _json_list(raw_value) -> list:
    if isinstance(raw_value, list):
        return raw_value
    if not raw_value:
        return []
    try:
        data = json.loads(raw_value)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _next_id(cursor, table_name: str) -> int:
    row = cursor.execute(f"SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM {table_name} WHERE id < 2147483647").fetchone()
    data = _row_dict(row)
    if data:
        return _safe_int(next(iter(data.values())))
    if isinstance(row, (list, tuple)):
        return _safe_int(row[0])
    return 1


def _context_value(context: dict, field: str):
    current = context or {}
    for part in _safe_text(field).split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _compare(left, op: str, right) -> bool:
    op = _safe_text(op).lower() or "=="
    if op in {"=", "==", "eq"}:
        return str(left) == str(right)
    if op in {"!=", "<>", "ne"}:
        return str(left) != str(right)
    if op in {">", "gt", ">=", "gte", "<", "lt", "<=", "lte"}:
        actions = {
            ">": operator.gt,
            "gt": operator.gt,
            ">=": operator.ge,
            "gte": operator.ge,
            "<": operator.lt,
            "lt": operator.lt,
            "<=": operator.le,
            "lte": operator.le,
        }
        return actions[op](_safe_float(left), _safe_float(right))
    if op == "in":
        values = right if isinstance(right, list) else [item.strip() for item in str(right or "").split(",")]
        return str(left) in {str(item) for item in values}
    if op == "contains":
        return str(right or "").lower() in str(left or "").lower()
    if op == "exists":
        return left not in {None, ""}
    return False


def evaluate_condition(condition: dict | None, context: dict | None) -> bool:
    condition = condition or {}
    context = context or {}
    if not condition:
        return True
    if isinstance(condition.get("all"), list):
        return all(evaluate_condition(item, context) for item in condition.get("all") or [])
    if isinstance(condition.get("any"), list):
        return any(evaluate_condition(item, context) for item in condition.get("any") or [])
    if condition.get("not"):
        return not evaluate_condition(condition.get("not") or {}, context)
    field = _safe_text(condition.get("field"))
    if not field:
        return True
    return _compare(_context_value(context, field), condition.get("op") or condition.get("operator") or "==", condition.get("value"))


def _history(instance: dict) -> list:
    return _json_list(instance.get("history_json"))


def _append_history(cursor, instance: dict, action: str, actor: dict | None = None, node_key: str = "", comment: str = "", payload: dict | None = None):
    item = {
        "at": int(time.time()),
        "action": _safe_text(action),
        "actor_name": _safe_text((actor or {}).get("name")) or "Система",
        "actor_email": _safe_text((actor or {}).get("email")),
        "node_key": _safe_text(node_key),
        "comment": _safe_text(comment),
        "payload": payload or {},
    }
    history = _history(instance)
    history.append(item)
    instance["history_json"] = json.dumps(history, ensure_ascii=False)
    cursor.execute(
        "UPDATE workflow_instances SET history_json=?, updated_at=? WHERE id=?",
        (instance["history_json"], int(time.time()), _safe_int(instance.get("id"))),
    )


def _load_definition(conn, definition_id: int) -> dict:
    definition = _row_dict(conn.execute("SELECT * FROM workflow_definitions WHERE id=?", (_safe_int(definition_id),)).fetchone())
    if not definition:
        return {}
    nodes = [
        _enrich_node(dict(row))
        for row in conn.execute(
            "SELECT * FROM workflow_nodes WHERE definition_id=? ORDER BY y ASC, x ASC, id ASC",
            (_safe_int(definition_id),),
        ).fetchall()
    ]
    edges = [
        _enrich_edge(dict(row))
        for row in conn.execute(
            "SELECT * FROM workflow_edges WHERE definition_id=? ORDER BY priority ASC, id ASC",
            (_safe_int(definition_id),),
        ).fetchall()
    ]
    definition["conditions"] = _json_dict(definition.get("conditions_json"))
    definition["settings"] = _json_dict(definition.get("settings_json"))
    definition["nodes"] = nodes
    definition["edges"] = edges
    return definition


def _enrich_node(node: dict) -> dict:
    node["config"] = _json_dict(node.get("config_json"))
    return node


def _enrich_edge(edge: dict) -> dict:
    edge["condition"] = _json_dict(edge.get("condition_json"))
    return edge


def _load_instance(conn, instance_id: int) -> dict:
    instance = _row_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (_safe_int(instance_id),)).fetchone())
    if not instance:
        return {}
    instance["context"] = _json_dict(instance.get("context_json"))
    instance["history"] = _json_list(instance.get("history_json"))
    instance["tokens"] = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM workflow_tokens WHERE instance_id=? ORDER BY id ASC",
            (_safe_int(instance_id),),
        ).fetchall()
    ]
    instance["active_tokens"] = [token for token in instance["tokens"] if _safe_text(token.get("token_status")) in ACTIVE_TOKEN_STATUSES]
    return instance


def _node_map(definition: dict) -> dict:
    return {_safe_text(node.get("node_key")): node for node in definition.get("nodes") or []}


def _outgoing(definition: dict, source_node_key: str, context: dict) -> list[dict]:
    edges = [
        edge for edge in definition.get("edges") or []
        if _safe_text(edge.get("source_node_key")) == _safe_text(source_node_key)
    ]
    matched = [edge for edge in edges if evaluate_condition(edge.get("condition"), context)]
    return matched


def _incoming_keys(definition: dict) -> set[str]:
    return {_safe_text(edge.get("target_node_key")) for edge in definition.get("edges") or [] if _safe_text(edge.get("target_node_key"))}


def _start_nodes(definition: dict) -> list[dict]:
    starts = [node for node in definition.get("nodes") or [] if _safe_text(node.get("node_type")) == "start"]
    if starts:
        return starts
    incoming = _incoming_keys(definition)
    return [node for node in definition.get("nodes") or [] if _safe_text(node.get("node_key")) not in incoming][:1]


def _find_role_user(cursor, role_name: str) -> str:
    if not _safe_text(role_name):
        return ""
    row = cursor.execute(
        "SELECT name FROM users WHERE role=? AND status='approved' ORDER BY is_head DESC, email ASC LIMIT 1",
        (_safe_text(role_name),),
    ).fetchone()
    data = _row_dict(row)
    return _safe_text(data.get("name"))


def _resolve_assignee(cursor, node: dict, context: dict) -> str:
    config = node.get("config") or {}
    assignee = _safe_text(node.get("assignee_name")) or _safe_text(config.get("assignee_name"))
    if assignee:
        return assignee
    context_field = _safe_text(config.get("assignee_context_field"))
    if context_field:
        assignee = _safe_text(_context_value(context, context_field))
        if assignee:
            return assignee
    return _find_role_user(cursor, node.get("role_name"))


def _create_token(cursor, instance: dict, definition: dict, node: dict, actor: dict | None = None, status: str = "active", parent_token_id: int = 0, branch_key: str = "") -> int:
    now = int(time.time())
    config = node.get("config") or {}
    node_type = _safe_text(node.get("node_type")) or "approval"
    token_status = _safe_text(status) or ("waiting" if node_type == "timer" else "active")
    due_at = 0
    if node_type == "timer":
        due_at = now + _safe_int(node.get("timer_seconds") or config.get("timer_seconds"))
    elif token_status in {"active", "rework", "escalated"}:
        if "sla_seconds" in config:
            due_at = now + _safe_int(config.get("sla_seconds"))
        else:
            due_at = now + max(0, _safe_int(node.get("sla_hours") or config.get("sla_hours") or 24)) * 3600
    token_id = _next_id(cursor, "workflow_tokens")
    cursor.execute(
        """
        INSERT INTO workflow_tokens (
            id, instance_id, definition_id, node_key, node_type, token_status, assignee_name,
            role_name, due_at, parent_token_id, branch_key, started_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            token_id,
            _safe_int(instance.get("id")),
            _safe_int(definition.get("id")),
            _safe_text(node.get("node_key")),
            node_type,
            token_status,
            _resolve_assignee(cursor, node, _json_dict(instance.get("context_json"))),
            _safe_text(node.get("role_name")),
            due_at,
            _safe_int(parent_token_id),
            _safe_text(branch_key),
            now if token_status != "queued" else 0,
            now,
            now,
        ),
    )
    cursor.execute(
        "UPDATE workflow_instances SET current_node_key=?, updated_at=? WHERE id=?",
        (_safe_text(node.get("node_key")), now, _safe_int(instance.get("id"))),
    )
    _append_history(cursor, instance, f"token_{token_status}", actor, node.get("node_key"), payload={"node_type": node_type, "due_at": due_at})
    return token_id


def _complete_instance_if_ready(cursor, instance: dict):
    row = cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM workflow_tokens
        WHERE instance_id=? AND token_status IN ('active', 'rework', 'escalated', 'waiting', 'queued')
        """,
        (_safe_int(instance.get("id")),),
    ).fetchone()
    active_total = _safe_int(_row_dict(row).get("cnt"))
    if active_total:
        return
    now = int(time.time())
    instance["status"] = "completed"
    cursor.execute(
        "UPDATE workflow_instances SET status='completed', completed_at=?, updated_at=? WHERE id=?",
        (now, now, _safe_int(instance.get("id"))),
    )
    _append_history(cursor, instance, "completed")


def _activate_node(cursor, instance: dict, definition: dict, node_key: str, actor: dict | None = None, parent_token_id: int = 0, branch_key: str = ""):
    nodes = _node_map(definition)
    node = nodes.get(_safe_text(node_key))
    if not node:
        _append_history(cursor, instance, "missing_node", actor, node_key)
        return
    node_type = _safe_text(node.get("node_type")) or "approval"
    context = _json_dict(instance.get("context_json"))
    if node_type in {"start", "script"}:
        _create_token(cursor, instance, definition, node, actor, status="completed", parent_token_id=parent_token_id, branch_key=branch_key)
        _advance_from_node(cursor, instance, definition, node.get("node_key"), actor, parent_token_id, branch_key)
        return
    if node_type == "exclusive_gateway":
        edges = _outgoing(definition, node.get("node_key"), context)
        if edges:
            _append_history(cursor, instance, "exclusive_branch", actor, node.get("node_key"), payload={"target": edges[0].get("target_node_key")})
            _activate_node(cursor, instance, definition, edges[0].get("target_node_key"), actor, parent_token_id, branch_key or node.get("node_key"))
        return
    if node_type == "parallel_gateway":
        edges = _outgoing(definition, node.get("node_key"), context)
        if not edges:
            edges = [edge for edge in definition.get("edges") or [] if _safe_text(edge.get("source_node_key")) == _safe_text(node.get("node_key"))]
        _append_history(cursor, instance, "parallel_split", actor, node.get("node_key"), payload={"branches": [edge.get("target_node_key") for edge in edges]})
        for edge in edges:
            _activate_node(cursor, instance, definition, edge.get("target_node_key"), actor, parent_token_id, edge.get("target_node_key"))
        return
    if node_type == "timer":
        _create_token(cursor, instance, definition, node, actor, status="waiting", parent_token_id=parent_token_id, branch_key=branch_key)
        return
    if node_type == "end":
        _create_token(cursor, instance, definition, node, actor, status="completed", parent_token_id=parent_token_id, branch_key=branch_key)
        _complete_instance_if_ready(cursor, instance)
        return
    _create_token(cursor, instance, definition, node, actor, status="active", parent_token_id=parent_token_id, branch_key=branch_key)


def _advance_from_node(cursor, instance: dict, definition: dict, node_key: str, actor: dict | None = None, parent_token_id: int = 0, branch_key: str = ""):
    context = _json_dict(instance.get("context_json"))
    edges = _outgoing(definition, node_key, context)
    if not edges:
        _complete_instance_if_ready(cursor, instance)
        return
    for edge in edges:
        _activate_node(cursor, instance, definition, edge.get("target_node_key"), actor, parent_token_id, branch_key)


def create_definition(conn, data: dict, actor: dict) -> dict:
    cursor = conn.cursor()
    now = int(time.time())
    definition_id = _next_id(cursor, "workflow_definitions")
    workflow_code = _safe_text(data.get("workflow_code")) or f"WF-{now}-{definition_id}"
    version = max(1, _safe_int(data.get("version") or 1))
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    if not nodes:
        return {"error": "workflow_nodes_required"}
    cursor.execute(
        """
        INSERT INTO workflow_definitions (
            id, workflow_code, workflow_name, entity_type, trigger_event, version, status,
            conditions_json, settings_json, is_active, comment, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            definition_id,
            workflow_code,
            _safe_text(data.get("workflow_name")) or workflow_code,
            _safe_text(data.get("entity_type")),
            _safe_text(data.get("trigger_event")) or "manual",
            version,
            _safe_text(data.get("status")) or "active",
            json.dumps(data.get("conditions") or {}, ensure_ascii=False),
            json.dumps(data.get("settings") or {}, ensure_ascii=False),
            _safe_int(data.get("is_active") if data.get("is_active") is not None else 1),
            _safe_text(data.get("comment")),
            _safe_text(actor.get("email")),
            now,
            now,
        ),
    )
    for index, node in enumerate(nodes, 1):
        node_key = _safe_text(node.get("node_key")) or f"node_{index}"
        cursor.execute(
            """
            INSERT INTO workflow_nodes (
                definition_id, node_key, node_type, title, role_name, assignee_name,
                parallel_mode, sla_hours, timer_seconds, config_json, x, y, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                definition_id,
                node_key,
                _safe_text(node.get("node_type")) or "approval",
                _safe_text(node.get("title")) or node_key,
                _safe_text(node.get("role_name")),
                _safe_text(node.get("assignee_name")),
                _safe_text(node.get("parallel_mode")) or "all",
                _safe_int(node.get("sla_hours") or 24),
                _safe_int(node.get("timer_seconds")),
                json.dumps(node.get("config") or node.get("config_json") or {}, ensure_ascii=False),
                _safe_int(node.get("x")),
                _safe_int(node.get("y")),
                now,
                now,
            ),
        )
    for index, edge in enumerate(edges, 1):
        cursor.execute(
            """
            INSERT INTO workflow_edges (
                definition_id, source_node_key, target_node_key, condition_json,
                condition_label, priority, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                definition_id,
                _safe_text(edge.get("source_node_key") or edge.get("source")),
                _safe_text(edge.get("target_node_key") or edge.get("target")),
                json.dumps(edge.get("condition") or edge.get("condition_json") or {}, ensure_ascii=False),
                _safe_text(edge.get("condition_label")),
                _safe_int(edge.get("priority") or index),
                now,
                now,
            ),
        )
    return {"status": "success", "id": definition_id, "workflow_code": workflow_code, "definition": _load_definition(conn, definition_id)}


def list_definitions(conn, entity_type: str = "", include_inactive: bool = False) -> list[dict]:
    clauses = []
    params = []
    if _safe_text(entity_type):
        clauses.append("entity_type=?")
        params.append(_safe_text(entity_type))
    if not include_inactive:
        clauses.append("is_active=1")
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM workflow_definitions {where_sql} ORDER BY updated_at DESC, id DESC",
        tuple(params),
    ).fetchall()
    items = []
    for row in rows:
        item = _load_definition(conn, _safe_int(_row_dict(row).get("id")))
        if item:
            items.append(item)
    return items


def get_definition(conn, definition_id: int) -> dict:
    return _load_definition(conn, definition_id)


def start_instance(conn, definition_id: int, data: dict, actor: dict) -> dict:
    cursor = conn.cursor()
    definition = _load_definition(conn, definition_id)
    if not definition:
        return {"error": "workflow_definition_not_found"}
    context = data.get("context") or {}
    context.setdefault("entity_type", _safe_text(data.get("entity_type")) or definition.get("entity_type"))
    context.setdefault("entity_id", _safe_text(data.get("entity_id")))
    if not evaluate_condition(definition.get("conditions"), context):
        return {"error": "workflow_conditions_not_matched"}
    now = int(time.time())
    instance_id = _next_id(cursor, "workflow_instances")
    cursor.execute(
        """
        INSERT INTO workflow_instances (
            id, definition_id, workflow_code, entity_type, entity_id, title, status,
            current_node_key, context_json, history_json, started_by, started_at, completed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'running', '', ?, '[]', ?, ?, 0, ?)
        """,
        (
            instance_id,
            _safe_int(definition.get("id")),
            _safe_text(definition.get("workflow_code")),
            _safe_text(data.get("entity_type")) or _safe_text(definition.get("entity_type")),
            _safe_text(data.get("entity_id")),
            _safe_text(data.get("title")) or _safe_text(definition.get("workflow_name")),
            json.dumps(context, ensure_ascii=False),
            _safe_text(actor.get("email")),
            now,
            now,
        ),
    )
    instance = _row_dict(cursor.execute("SELECT * FROM workflow_instances WHERE id=?", (instance_id,)).fetchone())
    _append_history(cursor, instance, "started", actor, comment=data.get("comment", ""), payload={"definition_id": definition_id})
    starts = _start_nodes(definition)
    if not starts:
        return {"error": "workflow_start_node_required"}
    for start_node in starts:
        _activate_node(cursor, instance, definition, start_node.get("node_key"), actor)
    return {"status": "success", "id": instance_id, "instance": _load_instance(conn, instance_id)}


def list_instances(conn, status: str = "", limit: int = 80) -> list[dict]:
    params = []
    where_sql = ""
    if _safe_text(status):
        where_sql = "WHERE status=?"
        params.append(_safe_text(status))
    params.append(max(1, min(_safe_int(limit or 80), 200)))
    rows = conn.execute(
        f"SELECT * FROM workflow_instances {where_sql} ORDER BY updated_at DESC, id DESC LIMIT ?",
        tuple(params),
    ).fetchall()
    return [_load_instance(conn, _safe_int(_row_dict(row).get("id"))) for row in rows]


def get_instance(conn, instance_id: int) -> dict:
    return _load_instance(conn, instance_id)


def apply_token_action(conn, token_id: int, data: dict, actor: dict) -> dict:
    cursor = conn.cursor()
    token = _row_dict(cursor.execute("SELECT * FROM workflow_tokens WHERE id=?", (_safe_int(token_id),)).fetchone())
    if not token:
        return {"error": "workflow_token_not_found"}
    instance = _row_dict(cursor.execute("SELECT * FROM workflow_instances WHERE id=?", (_safe_int(token.get("instance_id")),)).fetchone())
    if not instance or _safe_text(instance.get("status")) in FINAL_INSTANCE_STATUSES:
        return {"error": "workflow_instance_closed"}
    definition = _load_definition(conn, _safe_int(instance.get("definition_id")))
    action = _safe_text(data.get("action_name")).lower()
    actor_name = _safe_text(actor.get("name"))
    can_override = _safe_text(actor.get("role")) == "Директор"
    if action in {"approve", "reject", "return_rework", "delegate"} and actor_name != _safe_text(token.get("assignee_name")) and not can_override:
        return {"error": "workflow_action_forbidden", "assignee_name": token.get("assignee_name")}
    now = int(time.time())
    comment = _safe_text(data.get("comment"))
    if action == "approve":
        cursor.execute(
            """
            UPDATE workflow_tokens
            SET token_status='completed', decision='approved', comment=?, completed_by=?,
                completed_at=?, updated_at=?
            WHERE id=?
            """,
            (comment, actor_name, now, now, _safe_int(token_id)),
        )
        cursor.execute(
            "UPDATE workflow_instances SET status='running', completed_at=0, updated_at=? WHERE id=? AND status='rework'",
            (now, _safe_int(instance.get("id"))),
        )
        if _safe_text(instance.get("status")) == "rework":
            instance["status"] = "running"
        _append_history(cursor, instance, "approved", actor, token.get("node_key"), comment, {"token_id": token_id})
        _advance_from_node(cursor, instance, definition, token.get("node_key"), actor, _safe_int(token_id), token.get("branch_key"))
    elif action == "reject":
        cursor.execute(
            """
            UPDATE workflow_tokens
            SET token_status='rejected', decision='rejected', comment=?, completed_by=?,
                completed_at=?, updated_at=?
            WHERE id=?
            """,
            (comment, actor_name, now, now, _safe_int(token_id)),
        )
        cursor.execute(
            "UPDATE workflow_instances SET status='rejected', completed_at=?, updated_at=? WHERE id=?",
            (now, now, _safe_int(instance.get("id"))),
        )
        _append_history(cursor, instance, "rejected", actor, token.get("node_key"), comment, {"token_id": token_id})
    elif action == "return_rework":
        target_node_key = _safe_text(data.get("target_node_key"))
        if not target_node_key:
            nodes = definition.get("nodes") or []
            target_node_key = _safe_text((nodes[0] if nodes else {}).get("node_key"))
        if not target_node_key:
            return {"error": "target_node_required"}
        cursor.execute(
            "UPDATE workflow_tokens SET token_status='returned', decision='return_rework', comment=?, completed_by=?, completed_at=?, updated_at=? WHERE id=?",
            (comment, actor_name, now, now, _safe_int(token_id)),
        )
        cursor.execute(
            "UPDATE workflow_tokens SET token_status='cancelled', updated_at=? WHERE instance_id=? AND token_status IN ('active', 'rework', 'escalated', 'waiting', 'queued')",
            (now, _safe_int(instance.get("id"))),
        )
        cursor.execute(
            "UPDATE workflow_instances SET status='rework', completed_at=0, updated_at=? WHERE id=?",
            (now, _safe_int(instance.get("id"))),
        )
        _append_history(cursor, instance, "return_rework", actor, token.get("node_key"), comment, {"target_node_key": target_node_key})
        _activate_node(cursor, instance, definition, target_node_key, actor, _safe_int(token_id), "rework")
    elif action == "delegate":
        target_user = _safe_text(data.get("target_user"))
        if not target_user:
            return {"error": "target_user_required"}
        cursor.execute(
            """
            UPDATE workflow_tokens
            SET assignee_name=?, delegated_from=?, token_status='active', comment=?, updated_at=?
            WHERE id=?
            """,
            (target_user, _safe_text(token.get("assignee_name")), comment, now, _safe_int(token_id)),
        )
        _append_history(cursor, instance, "delegated", actor, token.get("node_key"), comment, {"token_id": token_id, "target_user": target_user})
    else:
        return {"error": "unsupported_workflow_action", "allowed": ["approve", "reject", "return_rework", "delegate"]}
    return {"status": "success", "instance": _load_instance(conn, _safe_int(instance.get("id")))}


def process_automation(conn, actor: dict) -> dict:
    cursor = conn.cursor()
    now = int(time.time())
    processed = []
    rows = [
        dict(row)
        for row in cursor.execute(
            """
            SELECT *
            FROM workflow_tokens
            WHERE token_status IN ('active', 'waiting', 'escalated') AND due_at>0 AND due_at<=?
            ORDER BY due_at ASC, id ASC
            """,
            (now,),
        ).fetchall()
    ]
    for token in rows:
        instance = _row_dict(cursor.execute("SELECT * FROM workflow_instances WHERE id=?", (_safe_int(token.get("instance_id")),)).fetchone())
        if not instance or _safe_text(instance.get("status")) in FINAL_INSTANCE_STATUSES:
            continue
        definition = _load_definition(conn, _safe_int(instance.get("definition_id")))
        if _safe_text(token.get("token_status")) == "waiting" and _safe_text(token.get("node_type")) == "timer":
            cursor.execute(
                "UPDATE workflow_tokens SET token_status='completed', decision='timer_elapsed', completed_by='system', completed_at=?, updated_at=? WHERE id=?",
                (now, now, _safe_int(token.get("id"))),
            )
            _append_history(cursor, instance, "timer_elapsed", actor, token.get("node_key"), payload={"token_id": token.get("id")})
            _advance_from_node(cursor, instance, definition, token.get("node_key"), actor, _safe_int(token.get("id")), token.get("branch_key"))
            processed.append({"token_id": _safe_int(token.get("id")), "action": "timer_elapsed"})
            continue
        if _safe_text(token.get("token_status")) in {"active", "escalated"}:
            escalation_target = ""
            assignee = _safe_text(token.get("assignee_name")).split(" (И.О.")[0]
            if assignee:
                deputy = _row_dict(cursor.execute("SELECT deputy FROM users WHERE name=?", (assignee,)).fetchone())
                escalation_target = _safe_text(deputy.get("deputy"))
            if not escalation_target:
                escalation_target = _find_role_user(cursor, "Директор")
            if not escalation_target:
                continue
            cursor.execute(
                """
                UPDATE workflow_tokens
                SET token_status='escalated', escalated_to=?, assignee_name=?, due_at=?, updated_at=?
                WHERE id=?
                """,
                (escalation_target, escalation_target, now + 24 * 3600, now, _safe_int(token.get("id"))),
            )
            _append_history(cursor, instance, "escalated", actor, token.get("node_key"), payload={"token_id": token.get("id"), "target_user": escalation_target})
            processed.append({"token_id": _safe_int(token.get("id")), "action": "escalated", "target_user": escalation_target})
    return {"status": "success", "processed": processed, "count": len(processed)}
