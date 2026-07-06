import json
import time

from database import get_connection
from services.integration_sync_service import json_load, safe_int


ENTITY_CONFIG = {
    "finance_payment": {
        "table": "finance_payments",
        "id_column": "id",
        "title_fields": ("title",),
        "status_field": "status",
        "comment_fields": ("comment",),
        "audit_types": ("finance_payment",),
        "exchange_fields": ("exchange_state", "external_sync_id"),
        "module": "finance",
    },
    "purchase_order": {
        "table": "purchase_orders",
        "id_column": "id",
        "title_fields": ("item_name", "item_article"),
        "status_field": "status",
        "comment_fields": ("comment",),
        "audit_types": ("purchase", "purchase_order"),
        "exchange_fields": ("exchange_state", "external_sync_id"),
        "module": "supply",
    },
    "sales_document": {
        "table": "sales_documents_extended",
        "id_column": "id",
        "title_fields": ("doc_number", "doc_type"),
        "status_field": "status",
        "comment_fields": ("comment",),
        "audit_types": ("sales_document",),
        "exchange_fields": ("exchange_state", "external_sync_id"),
        "module": "sales",
    },
    "production_order": {
        "table": "production_orders",
        "id_column": "id",
        "title_fields": ("order_name",),
        "status_field": "stage",
        "comment_fields": ("comment",),
        "audit_types": ("production_order",),
        "exchange_fields": ("exchange_state", "external_sync_id"),
        "module": "production",
    },
    "inventory_document": {
        "table": "inventory_documents",
        "id_column": "id",
        "title_fields": ("doc_number", "article"),
        "status_field": "status",
        "comment_fields": ("comment", "reason"),
        "audit_types": ("inventory_document", "stock_document"),
        "exchange_fields": ("exchange_state", "external_sync_id"),
        "module": "stock",
    },
    "stock_document": {
        "alias": "inventory_document",
    },
    "epl_waybill": {
        "table": "epl_waybills",
        "id_column": "id",
        "title_fields": ("number", "route_text"),
        "status_field": "status",
        "comment_fields": ("notes",),
        "audit_types": ("epl_waybill",),
        "exchange_fields": ("integration_status", "external_document_id"),
        "module": "accounting",
    },
}


def _clean(value) -> str:
    return str(value or "").strip()


def _row_dict(row) -> dict:
    return dict(row) if row else {}


def _config(entity_type: str) -> dict:
    raw = _clean(entity_type)
    config = ENTITY_CONFIG.get(raw) or {}
    if config.get("alias"):
        config = ENTITY_CONFIG.get(config["alias"]) or {}
        config = {**config, "canonical_type": config.get("canonical_type") or config.get("alias") or raw}
    return {**config, "canonical_type": config.get("canonical_type") or raw}


def _title(config: dict, row: dict) -> str:
    for field in config.get("title_fields") or ():
        if _clean(row.get(field)):
            return _clean(row.get(field))
    return f"{config.get('canonical_type', 'object')} #{row.get(config.get('id_column', 'id')) or ''}"


def _comments(config: dict, row: dict) -> list[dict]:
    comments = []
    for field in config.get("comment_fields") or ():
        if _clean(row.get(field)):
            comments.append({"source": field, "text": _clean(row.get(field)), "created_at": safe_int(row.get("updated_at") or row.get("created_at"))})
    return comments


def _audit_rows(conn, config: dict, entity_id: int) -> list[dict]:
    audit_types = config.get("audit_types") or (config.get("canonical_type"),)
    placeholders = ",".join("?" for _ in audit_types)
    rows = [
        _row_dict(row)
        for row in conn.execute(
            f"""
            SELECT *
            FROM audit_log
            WHERE entity_type IN ({placeholders}) AND entity_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT 25
            """,
            (*audit_types, str(entity_id)),
        ).fetchall()
    ]
    for row in rows:
        row["details"] = json_load(row.get("details"), {})
    return rows


def _integration_state(conn, entity_type: str, config: dict, entity_id: int, row: dict) -> dict:
    state_field, external_field = (config.get("exchange_fields") or ("", ""))[:2]
    external_object = _row_dict(
        conn.execute(
            """
            SELECT *
            FROM integration_external_objects
            WHERE entity_type=? AND entity_id=?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (entity_type, str(entity_id)),
        ).fetchone()
    )
    messages = [
        _row_dict(item)
        for item in conn.execute(
            """
            SELECT *
            FROM integration_exchange_messages
            WHERE entity_type=? AND entity_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT 10
            """,
            (entity_type, str(entity_id)),
        ).fetchall()
    ]
    for item in messages:
        item["request_payload"] = json_load(item.get("request_payload"), {})
        item["response_payload"] = json_load(item.get("response_payload"), {})
    state = _clean(row.get(state_field)) if state_field else ""
    external_id = _clean(row.get(external_field)) if external_field else ""
    if external_object:
        state = state or _clean(external_object.get("exchange_state"))
        external_id = external_id or _clean(external_object.get("external_id"))
    return {
        "state": state or "draft",
        "external_id": external_id,
        "external_object": external_object,
        "messages": messages,
        "last_error": next((_clean(item.get("error_message")) for item in messages if _clean(item.get("error_message"))), ""),
    }


def _links(conn, entity_type: str, entity_id: int) -> list[dict]:
    rows = [
        _row_dict(row)
        for row in conn.execute(
            """
            SELECT *
            FROM erp_entity_links
            WHERE (source_type=? AND source_id=?) OR (target_type=? AND target_id=?)
            ORDER BY created_at DESC, id DESC
            LIMIT 30
            """,
            (entity_type, str(entity_id), entity_type, str(entity_id)),
        ).fetchall()
    ]
    for row in rows:
        row["details"] = json_load(row.get("details"), {})
    return rows


def _documents_and_files(conn, entity_type: str, entity_id: int, row: dict) -> dict:
    relations = [
        _row_dict(item)
        for item in conn.execute(
            """
            SELECT *
            FROM document_relations
            WHERE (source_entity_type=? AND source_entity_id=?) OR (target_entity_type=? AND target_entity_id=?)
            ORDER BY created_at DESC, id DESC
            LIMIT 25
            """,
            (entity_type, entity_id, entity_type, entity_id),
        ).fetchall()
    ]
    document_ids = set()
    for rel in relations:
        if rel.get("source_entity_type") == "document":
            document_ids.add(safe_int(rel.get("source_entity_id")))
        if rel.get("target_entity_type") == "document":
            document_ids.add(safe_int(rel.get("target_entity_id")))
        rel["meta"] = json_load(rel.get("meta_json"), {})
    if entity_type == "sales_document" and _clean(row.get("doc_number")):
        for item in conn.execute("SELECT id FROM documents WHERE number=? ORDER BY id DESC LIMIT 5", (_clean(row.get("doc_number")),)).fetchall():
            document_ids.add(safe_int(item[0] if not isinstance(item, dict) else item.get("id")))
    docs = []
    files = []
    for document_id in [item for item in document_ids if item][:20]:
        doc = _row_dict(conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone())
        if not doc:
            continue
        docs.append(doc)
        revisions = [
            _row_dict(rev)
            for rev in conn.execute(
                "SELECT * FROM document_file_revisions WHERE document_id=? ORDER BY is_current DESC, revision_no DESC, id DESC LIMIT 5",
                (document_id,),
            ).fetchall()
        ]
        files.extend(revisions)
    return {"documents": docs, "files": files, "relations": relations}


def _favorite_and_watch(conn, actor: dict, entity_type: str, entity_id: int) -> dict:
    favorite = _row_dict(
        conn.execute(
            "SELECT * FROM user_favorite_items WHERE user_email=? AND entity_type=? AND entity_id=? LIMIT 1",
            (_clean(actor.get("email")), entity_type, str(entity_id)),
        ).fetchone()
    )
    watch = _row_dict(
        conn.execute(
            "SELECT * FROM entity_watchers WHERE user_email=? AND entity_type=? AND entity_id=? AND is_active=1 LIMIT 1",
            (_clean(actor.get("email")), entity_type, str(entity_id)),
        ).fetchone()
    )
    return {"favorite": favorite, "watch": watch}


def build_entity_card(entity_type: str, entity_id: int, actor: dict) -> dict:
    config = _config(entity_type)
    if not config:
        return {"error": "unsupported_entity"}
    entity_id = safe_int(entity_id)
    conn = get_connection(row_factory=True)
    try:
        row = _row_dict(conn.execute(
            f"SELECT * FROM {config['table']} WHERE {config['id_column']}=? LIMIT 1",
            (entity_id,),
        ).fetchone())
        if not row:
            return {"error": "not_found"}
        canonical_type = config.get("canonical_type") or entity_type
        files = _documents_and_files(conn, canonical_type, entity_id, row)
        fav_watch = _favorite_and_watch(conn, actor, canonical_type, entity_id)
        return {
            "status": "success",
            "entity_type": canonical_type,
            "entity_id": entity_id,
            "title": _title(config, row),
            "state": _clean(row.get(config.get("status_field"))) or "",
            "module": config.get("module") or "",
            "record": row,
            "comments": _comments(config, row),
            "audit": _audit_rows(conn, config, entity_id),
            "integration": _integration_state(conn, canonical_type, config, entity_id, row),
            "links": _links(conn, canonical_type, entity_id),
            **files,
            **fav_watch,
            "generated_at": int(time.time()),
        }
    finally:
        conn.close()
