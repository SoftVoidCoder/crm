import json
import time

from database import get_connection, ROW_FACTORY_DICT


def ensure_client_reference(conn, client_name: str, *, normalize_spaces, match_client_id) -> int:
    client_name = normalize_spaces(client_name)
    if not client_name:
        return 0
    existing_id = match_client_id(conn, client_name)
    if existing_id:
        return existing_id
    c = conn.cursor()
    c.execute("INSERT INTO clients (name, inn, contact) VALUES (?, '', '')", (client_name,))
    return c.lastrowid


def user_email_by_name(conn, user_name: str, *, normalize_spaces) -> str:
    user_name = normalize_spaces(user_name)
    if not user_name:
        return ""
    c = conn.cursor()
    c.execute("SELECT email FROM users WHERE name=?", (user_name,))
    row = c.fetchone()
    return row[0] if row else ""


def extract_project_object_payload(project: dict, *, normalize_spaces, custom_fields_map) -> dict:
    archive_details = project.get("archive_details") or {}
    contract_meta = archive_details.get("contract_meta") or {}
    custom_map = custom_fields_map(contract_meta.get("custom_fields") or [])
    object_name = normalize_spaces(
        contract_meta.get("object_name")
        or archive_details.get("object_name")
        or custom_map.get("объект")
        or custom_map.get("объект поставки")
        or project.get("name", "")
    )
    return {
        "name": object_name,
        "address": normalize_spaces(
            contract_meta.get("object_address")
            or archive_details.get("object_address")
            or custom_map.get("адрес объекта")
            or custom_map.get("адрес")
            or ""
        ),
        "city": normalize_spaces(contract_meta.get("object_city") or custom_map.get("город") or ""),
        "region": normalize_spaces(contract_meta.get("object_region") or custom_map.get("регион") or ""),
        "responsible_name": normalize_spaces(
            contract_meta.get("object_responsible")
            or custom_map.get("ответственный на объекте")
            or project.get("manager", "")
        ),
        "comment": normalize_spaces(contract_meta.get("object_comment") or archive_details.get("object_comment") or ""),
    }


def propagate_project_master_links(conn, project_id: int, client_id: int, contract_id: int, object_id: int):
    if not project_id:
        return
    c = conn.cursor()
    c.execute("UPDATE projects SET contract_id=?, object_id=? WHERE id=?", (contract_id, object_id, project_id))
    for table in ("finance_payments", "purchase_orders", "sales_documents_extended", "production_orders", "expense_requests", "service_cases", "erp_process_runs", "epl_waybills"):
        c.execute(
            f"UPDATE {table} SET client_id=?, contract_id=?, object_id=? WHERE project_id=?",
            (client_id, contract_id, object_id, project_id),
        )
    for table in ("internal_requests", "resource_allocations"):
        c.execute(
            f"UPDATE {table} SET contract_id=?, object_id=? WHERE project_id=?",
            (contract_id, object_id, project_id),
        )
    c.execute("UPDATE documents SET contract_id=?, object_id=? WHERE project_id=?", (contract_id, object_id, project_id))


def sync_project_master_data(
    conn,
    project: dict,
    actor: dict | None = None,
    *,
    safe_int,
    safe_float,
    normalize_spaces,
    ensure_client_reference_fn,
    extract_project_object_payload_fn,
    user_email_by_name_fn,
    propagate_project_master_links_fn,
):
    project_id = safe_int(project.get("id"))
    client_id = ensure_client_reference_fn(conn, project.get("client", ""))
    object_payload = extract_project_object_payload_fn(project)
    now = int(time.time())
    actor_email = (actor or {}).get("email", "")
    c = conn.cursor()

    object_id = safe_int(project.get("object_id"))
    if object_payload["name"]:
        if object_id:
            c.execute("SELECT id FROM business_objects WHERE id=?", (object_id,))
            if not c.fetchone():
                object_id = 0
        if not object_id:
            c.execute("SELECT id FROM business_objects WHERE client_id=? AND name=?", (client_id, object_payload["name"]))
            row = c.fetchone()
            object_id = int(row[0] or 0) if row else 0
        if object_id:
            c.execute(
                """
                UPDATE business_objects
                SET client_id=?, name=?, address=?, city=?, region=?, responsible_name=?, responsible_email=?, comment=?, updated_at=?
                WHERE id=?
                """,
                (
                    client_id,
                    object_payload["name"],
                    object_payload["address"],
                    object_payload["city"],
                    object_payload["region"],
                    object_payload["responsible_name"],
                    user_email_by_name_fn(conn, object_payload["responsible_name"]),
                    object_payload["comment"],
                    now,
                    object_id,
                ),
            )
        else:
            c.execute(
                """
                INSERT INTO business_objects (
                    client_id, name, code, address, city, region, responsible_name, responsible_email,
                    comment, created_by, created_at, updated_at
                ) VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    object_payload["name"],
                    object_payload["address"],
                    object_payload["city"],
                    object_payload["region"],
                    object_payload["responsible_name"],
                    user_email_by_name_fn(conn, object_payload["responsible_name"]),
                    object_payload["comment"],
                    actor_email,
                    now,
                    now,
                ),
            )
            object_id = c.lastrowid

    archive_details = project.get("archive_details") or {}
    contract_meta = archive_details.get("contract_meta") or {}
    custom_fields = contract_meta.get("custom_fields") or []
    manager_name = normalize_spaces(project.get("manager", ""))
    contract_number = normalize_spaces(project.get("contract") or f"PROJECT-{project_id}")
    contract_comment_parts = [
        f"Доп. номер: {normalize_spaces(contract_meta.get('add_num'))}" if normalize_spaces(contract_meta.get("add_num")) else "",
        f"Входящий номер: {normalize_spaces(contract_meta.get('inc_num'))}" if normalize_spaces(contract_meta.get("inc_num")) else "",
    ]
    contract_comment = "\n".join(part for part in contract_comment_parts if part).strip()

    contract_id = safe_int(project.get("contract_id"))
    if contract_id:
        c.execute("SELECT id FROM contract_master WHERE id=?", (contract_id,))
        if not c.fetchone():
            contract_id = 0
    if not contract_id:
        c.execute("SELECT id FROM contract_master WHERE project_id=? OR (client_id=? AND contract_number=?) ORDER BY updated_at DESC, id DESC LIMIT 1", (project_id, client_id, contract_number))
        row = c.fetchone()
        contract_id = int(row[0] or 0) if row else 0
    contract_values = (
        project_id,
        client_id,
        object_id,
        contract_number,
        normalize_spaces(project.get("name", "")),
        normalize_spaces(project.get("status", "") or "active"),
        safe_float(project.get("budget")),
        normalize_spaces(contract_meta.get("currency") or "RUB") or "RUB",
        normalize_spaces(contract_meta.get("start_date") or ""),
        normalize_spaces(contract_meta.get("end_date") or ""),
        manager_name,
        user_email_by_name_fn(conn, manager_name),
        contract_comment,
        json.dumps(custom_fields, ensure_ascii=False),
        now,
    )
    if contract_id:
        c.execute(
            """
            UPDATE contract_master
            SET project_id=?, client_id=?, object_id=?, contract_number=?, title=?, status=?, amount=?, currency=?,
                start_date=?, end_date=?, manager_name=?, manager_email=?, comment=?, custom_fields=?, updated_at=?
            WHERE id=?
            """,
            (*contract_values, contract_id),
        )
    else:
        c.execute(
            """
            INSERT INTO contract_master (
                project_id, client_id, object_id, contract_number, title, status, amount, currency,
                start_date, end_date, manager_name, manager_email, comment, custom_fields, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*contract_values[:-1], actor_email, now, now),
        )
        contract_id = c.lastrowid

    propagate_project_master_links_fn(conn, project_id, client_id, contract_id, object_id)
    return {"client_id": client_id, "contract_id": contract_id, "object_id": object_id}


def resolve_master_context(
    conn,
    project_id: int = 0,
    client_id: int = 0,
    contract_id: int = 0,
    object_id: int = 0,
    autocreate: bool = True,
    *,
    safe_int,
    load_project_row,
    project_payload,
    match_client_id,
    sync_project_master_data_fn,
):
    c = conn.cursor()
    project = None
    if project_id:
        c.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        row = c.fetchone()
        if row:
            if isinstance(row, dict):
                project = project_payload(dict(row))
            else:
                columns = [col[0] for col in c.description]
                project = project_payload(dict(zip(columns, row)))
            client_id = client_id or match_client_id(conn, project.get("client", ""))
            contract_id = contract_id or safe_int(project.get("contract_id"))
            object_id = object_id or safe_int(project.get("object_id"))
            if autocreate and project_id and (not contract_id or not object_id):
                synced = sync_project_master_data_fn(conn, project)
                client_id = client_id or safe_int(synced.get("client_id"))
                contract_id = contract_id or safe_int(synced.get("contract_id"))
                object_id = object_id or safe_int(synced.get("object_id"))
    if contract_id:
        c.execute("SELECT client_id, object_id FROM contract_master WHERE id=?", (contract_id,))
        row = c.fetchone()
        if row:
            client_id = client_id or safe_int(row[0])
            object_id = object_id or safe_int(row[1])
    if object_id and not client_id:
        c.execute("SELECT client_id FROM business_objects WHERE id=?", (object_id,))
        row = c.fetchone()
        if row:
            client_id = safe_int(row[0])
    return {
        "project": project,
        "project_id": safe_int(project_id),
        "client_id": safe_int(client_id),
        "contract_id": safe_int(contract_id),
        "object_id": safe_int(object_id),
    }


def load_contract_directory(db_name: str, *, json_load):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            cm.*,
            COALESCE(cl.name, '') AS client_name,
            COALESCE(bo.name, '') AS object_name,
            COALESCE(p.name, '') AS project_name
        FROM contract_master cm
        LEFT JOIN clients cl ON cl.id = cm.client_id
        LEFT JOIN business_objects bo ON bo.id = cm.object_id
        LEFT JOIN projects p ON p.id = cm.project_id
        ORDER BY cm.updated_at DESC, cm.id DESC
        """
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    for row in rows:
        row["custom_fields"] = json_load(row.get("custom_fields"), [])
    return rows


def load_business_objects_directory(db_name: str, client_id: int = 0):
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    if client_id:
        c.execute("SELECT * FROM business_objects WHERE client_id=? ORDER BY updated_at DESC, id DESC", (client_id,))
    else:
        c.execute("SELECT * FROM business_objects ORDER BY updated_at DESC, id DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def sync_contract_back_to_project(
    conn,
    contract_id: int,
    *,
    safe_int,
    safe_float,
    project_payload,
):
    if not contract_id:
        return
    conn.row_factory = ROW_FACTORY_DICT
    c = conn.cursor()
    c.execute("SELECT * FROM contract_master WHERE id=?", (contract_id,))
    contract = c.fetchone()
    if not contract:
        return
    contract = dict(contract)
    project_id = safe_int(contract.get("project_id"))
    if not project_id:
        return
    c.execute("SELECT * FROM projects WHERE id=?", (project_id,))
    project = c.fetchone()
    if not project:
        return
    project = project_payload(dict(project))
    archive_details = project.get("archive_details") or {}
    contract_meta = archive_details.get("contract_meta") or {}
    contract_meta["currency"] = contract.get("currency", "RUB") or "RUB"
    contract_meta["start_date"] = contract.get("start_date", "") or ""
    contract_meta["end_date"] = contract.get("end_date", "") or ""
    try:
        contract_meta["custom_fields"] = json.loads(contract.get("custom_fields") or "[]")
    except Exception:
        contract_meta["custom_fields"] = []
    archive_details["contract_meta"] = contract_meta
    if safe_int(contract.get("object_id")):
        c.execute("SELECT * FROM business_objects WHERE id=?", (contract.get("object_id"),))
        object_row = c.fetchone()
        if object_row:
            object_row = dict(object_row)
            archive_details["object_name"] = object_row.get("name", "") or ""
            archive_details["object_address"] = object_row.get("address", "") or ""
            archive_details["object_comment"] = object_row.get("comment", "") or ""
    client_name = project.get("client", "")
    if safe_int(contract.get("client_id")):
        c.execute("SELECT name FROM clients WHERE id=?", (contract.get("client_id"),))
        client_row = c.fetchone()
        if client_row:
            client_name = client_row["name"]
    c.execute(
        """
        UPDATE projects
        SET contract=?, client=?, manager=?, status=?, budget=?, archive_details=?, contract_id=?, object_id=?
        WHERE id=?
        """,
        (
            contract.get("contract_number", "") or project.get("contract", ""),
            client_name,
            contract.get("manager_name", "") or project.get("manager", ""),
            contract.get("status", "") or project.get("status", ""),
            safe_float(contract.get("amount")) or safe_float(project.get("budget")),
            json.dumps(archive_details, ensure_ascii=False),
            contract_id,
            safe_int(contract.get("object_id")),
            project_id,
        ),
    )


def replace_project_client_name(conn, old_names: list[str], new_name: str):
    if not old_names:
        return
    c = conn.cursor()
    for old_name in old_names:
        c.execute("UPDATE projects SET client=? WHERE client=?", (new_name, old_name))
