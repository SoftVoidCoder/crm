import json
import time
from urllib.parse import urlparse

import httpx

from database import audit_log, get_connection
from routers.projects import (
    _json_load,
    _normalize_outreach_priority,
    _normalize_outreach_status,
    _normalize_spaces,
    _outreach_existing_key_map,
    _outreach_item_lookup_keys,
)
from settings import BITRIX24_SYNC_ENTITIES, BITRIX24_SYNC_LIMIT, BITRIX24_WEBHOOK_URL


BITRIX24_SOURCE_NAME = "Bitrix24 API"


def _configured_webhook_url(webhook_url: str = "") -> str:
    return (webhook_url or BITRIX24_WEBHOOK_URL or _load_saved_webhook_url()).strip().rstrip("/")


def _load_saved_webhook_url() -> str:
    try:
        conn = get_connection(row_factory=True)
        row = conn.execute(
            """
            SELECT cred.secret_value
            FROM integration_connectors con
            JOIN integration_connector_credentials cred ON cred.connector_id=con.id
            WHERE con.connector_type='bitrix24' AND con.status='active' AND cred.is_active=1
            ORDER BY con.updated_at DESC, cred.updated_at DESC, cred.id DESC
            LIMIT 1
            """
        ).fetchone()
        conn.close()
    except Exception:
        return ""
    return _normalize_spaces(dict(row).get("secret_value") if row else "")


def save_bitrix24_webhook_url(webhook_url: str, actor: dict) -> dict:
    clean_url = _normalize_spaces(webhook_url).rstrip("/")
    if not clean_url.startswith("https://") or "/rest/" not in clean_url:
        return {"status": "failed", "error": "invalid_webhook_url"}
    now = int(time.time())
    conn = get_connection(row_factory=True)
    row = conn.execute(
        "SELECT * FROM integration_connectors WHERE connector_type='bitrix24' ORDER BY updated_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if row:
        connector_id = int(dict(row).get("id") or 0)
        conn.execute(
            "UPDATE integration_connectors SET provider_name='Bitrix24', status='active', updated_at=?, last_error='' WHERE id=?",
            (now, connector_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO integration_connectors (
                connector_type, provider_name, status, settings, scope, last_sync_at, last_error, created_by, created_at, updated_at
            ) VALUES ('bitrix24', 'Bitrix24', 'active', '{}', '{}', 0, '', ?, ?, ?)
            """,
            (actor.get("email", ""), now, now),
        )
        connector_id = int(conn.execute("SELECT lastval()").fetchone()[0])
    conn.execute("UPDATE integration_connector_credentials SET is_active=0, updated_at=? WHERE connector_id=?", (now, connector_id))
    conn.execute(
        """
        INSERT INTO integration_connector_credentials (
            connector_id, credential_kind, username, secret_value, secret_ref, is_active, created_by, created_at, updated_at
        ) VALUES (?, 'webhook', ?, ?, '', 1, ?, ?, ?)
        """,
        (connector_id, actor.get("email", ""), clean_url, actor.get("email", ""), now, now),
    )
    conn.commit()
    conn.close()
    return {"status": "success", "connector_id": connector_id, **bitrix24_config_status(clean_url)}


def bitrix24_config_status(webhook_url: str = "") -> dict:
    url = _configured_webhook_url(webhook_url)
    parsed = urlparse(url) if url else None
    return {
        "configured": bool(url),
        "portal": f"{parsed.scheme}://{parsed.netloc}" if parsed and parsed.scheme and parsed.netloc else "",
        "entities": [item.strip() for item in BITRIX24_SYNC_ENTITIES.split(",") if item.strip()],
        "limit": BITRIX24_SYNC_LIMIT,
    }


def _method_url(webhook_url: str, method: str) -> str:
    base = _configured_webhook_url(webhook_url)
    if not base:
        raise ValueError("bitrix24_webhook_required")
    return f"{base}/{method}.json"


def _bitrix_call(webhook_url: str, method: str, payload: dict, timeout_seconds: int = 30) -> dict:
    url = _method_url(webhook_url, method)
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        response = client.post(url, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"{method}: http_{response.status_code}")
    data = response.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"{method}: {data.get('error_description') or data.get('error')}")
    return data if isinstance(data, dict) else {"result": data}


def _first_multifield(item: dict, field: str) -> str:
    values = item.get(field) or []
    if isinstance(values, dict):
        values = list(values.values())
    if not isinstance(values, list):
        return _normalize_spaces(str(values or ""))
    for value in values:
        if isinstance(value, dict):
            clean = _normalize_spaces(value.get("VALUE") or value.get("value") or "")
        else:
            clean = _normalize_spaces(value)
        if clean:
            return clean
    return ""


def _fetch_list(webhook_url: str, method: str, select: list[str], limit: int) -> list[dict]:
    rows: list[dict] = []
    start: int | str = 0
    while len(rows) < limit:
        data = _bitrix_call(
            webhook_url,
            method,
            {
                "select": select,
                "order": {"DATE_MODIFY": "DESC", "ID": "DESC"},
                "start": start,
            },
        )
        result = data.get("result") or []
        if not isinstance(result, list):
            break
        rows.extend([item for item in result if isinstance(item, dict)])
        if "next" not in data or len(result) == 0:
            break
        start = data.get("next")
    return rows[:limit]


def _lead_to_import_row(item: dict) -> dict:
    title = _normalize_spaces(item.get("TITLE") or "")
    company = _normalize_spaces(item.get("COMPANY_TITLE") or title)
    contact = " ".join(
        part
        for part in [
            _normalize_spaces(item.get("LAST_NAME") or ""),
            _normalize_spaces(item.get("NAME") or ""),
            _normalize_spaces(item.get("SECOND_NAME") or ""),
        ]
        if part
    )
    return {
        "ID": f"lead:{item.get('ID') or ''}",
        "COMPANY_TITLE": company,
        "CONTACT_NAME": contact,
        "PHONE": _first_multifield(item, "PHONE"),
        "EMAIL": _first_multifield(item, "EMAIL"),
        "WEB": _first_multifield(item, "WEB"),
        "SOURCE_DESCRIPTION": _normalize_spaces(item.get("SOURCE_DESCRIPTION") or item.get("SOURCE_ID") or ""),
        "STATUS_ID": _normalize_spaces(item.get("STATUS_ID") or ""),
        "ASSIGNED_BY_ID": _normalize_spaces(item.get("ASSIGNED_BY_ID") or ""),
        "COMMENTS": _normalize_spaces(item.get("COMMENTS") or ""),
        "DATE_MODIFY": _normalize_spaces(item.get("DATE_MODIFY") or item.get("DATE_CREATE") or ""),
    }


def _contact_to_import_row(item: dict, companies: dict[str, dict]) -> dict:
    company_id = _normalize_spaces(item.get("COMPANY_ID") or "")
    company = companies.get(company_id) or {}
    contact = " ".join(
        part
        for part in [
            _normalize_spaces(item.get("LAST_NAME") or ""),
            _normalize_spaces(item.get("NAME") or ""),
            _normalize_spaces(item.get("SECOND_NAME") or ""),
        ]
        if part
    )
    return {
        "ID": f"contact:{item.get('ID') or ''}",
        "COMPANY_ID": company_id,
        "COMPANY_TITLE": _normalize_spaces(company.get("TITLE") or item.get("COMPANY_TITLE") or contact),
        "CONTACT_NAME": contact,
        "POST": _normalize_spaces(item.get("POST") or ""),
        "PHONE": _first_multifield(item, "PHONE"),
        "EMAIL": _first_multifield(item, "EMAIL"),
        "WEB": _first_multifield(item, "WEB"),
        "COMMENTS": _normalize_spaces(item.get("COMMENTS") or ""),
        "DATE_MODIFY": _normalize_spaces(item.get("DATE_MODIFY") or item.get("DATE_CREATE") or ""),
    }


def _company_to_import_row(item: dict) -> dict:
    return {
        "ID": f"company:{item.get('ID') or ''}",
        "COMPANY_ID": _normalize_spaces(item.get("ID") or ""),
        "COMPANY_TITLE": _normalize_spaces(item.get("TITLE") or ""),
        "PHONE": _first_multifield(item, "PHONE"),
        "EMAIL": _first_multifield(item, "EMAIL"),
        "WEB": _first_multifield(item, "WEB"),
        "COMMENTS": _normalize_spaces(item.get("COMMENTS") or ""),
        "DATE_MODIFY": _normalize_spaces(item.get("DATE_MODIFY") or item.get("DATE_CREATE") or ""),
    }


def fetch_bitrix24_rows(webhook_url: str = "", limit: int | None = None) -> dict:
    row_limit = max(1, min(2000, int(limit or BITRIX24_SYNC_LIMIT)))
    entities = {item.strip().lower() for item in BITRIX24_SYNC_ENTITIES.split(",") if item.strip()}
    companies = []
    company_map: dict[str, dict] = {}
    if "companies" in entities or "contacts" in entities:
        companies = _fetch_list(
            webhook_url,
            "crm.company.list",
            ["ID", "TITLE", "PHONE", "EMAIL", "WEB", "COMMENTS", "DATE_CREATE", "DATE_MODIFY"],
            row_limit,
        )
        company_map = {_normalize_spaces(item.get("ID") or ""): item for item in companies}
    leads = (
        _fetch_list(
            webhook_url,
            "crm.lead.list",
            [
                "ID",
                "TITLE",
                "NAME",
                "LAST_NAME",
                "SECOND_NAME",
                "COMPANY_TITLE",
                "PHONE",
                "EMAIL",
                "WEB",
                "SOURCE_ID",
                "SOURCE_DESCRIPTION",
                "STATUS_ID",
                "ASSIGNED_BY_ID",
                "COMMENTS",
                "DATE_CREATE",
                "DATE_MODIFY",
            ],
            row_limit,
        )
        if "leads" in entities
        else []
    )
    contacts = (
        _fetch_list(
            webhook_url,
            "crm.contact.list",
            [
                "ID",
                "NAME",
                "LAST_NAME",
                "SECOND_NAME",
                "POST",
                "COMPANY_ID",
                "PHONE",
                "EMAIL",
                "WEB",
                "COMMENTS",
                "DATE_CREATE",
                "DATE_MODIFY",
            ],
            row_limit,
        )
        if "contacts" in entities
        else []
    )
    rows = [_lead_to_import_row(item) for item in leads]
    rows.extend(_contact_to_import_row(item, company_map) for item in contacts)
    rows.extend(_company_to_import_row(item) for item in companies if "companies" in entities)
    return {
        "rows": rows[:row_limit],
        "fetched": {"leads": len(leads), "contacts": len(contacts), "companies": len(companies)},
    }


def import_bitrix24_rows(rows: list[dict], actor: dict | None = None, filename: str = "bitrix24-api") -> dict:
    actor = actor or {"email": "system@korda.local", "name": "Bitrix24 Sync"}
    now = int(time.time())
    conn = get_connection(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM outreach_prospects")
    existing_rows = [dict(row) for row in c.fetchall()]
    existing_keys = _outreach_existing_key_map(existing_rows)
    created = updated = skipped = 0
    for raw in rows:
        item = {
            "company_name": _normalize_spaces(raw.get("COMPANY_TITLE") or raw.get("TITLE") or ""),
            "company_inn": _normalize_spaces(raw.get("INN") or ""),
            "contact_name": _normalize_spaces(raw.get("CONTACT_NAME") or ""),
            "position": _normalize_spaces(raw.get("POST") or ""),
            "phone": _normalize_spaces(raw.get("PHONE") or ""),
            "email": _normalize_spaces(raw.get("EMAIL") or ""),
            "website": _normalize_spaces(raw.get("WEB") or ""),
            "city": "",
            "contact_method": "phone" if raw.get("PHONE") else "email" if raw.get("EMAIL") else "",
            "source_name": BITRIX24_SOURCE_NAME,
            "status": _normalize_outreach_status(raw.get("STATUS_ID") or "") or "new",
            "priority": _normalize_outreach_priority("normal"),
            "manager_name": "",
            "manager_email": "",
            "planned_contact_date": "",
            "next_action": "",
            "next_action_date": "",
            "notes": _normalize_spaces(raw.get("COMMENTS") or ""),
            "tags": ["Bitrix24"],
            "do_not_contact": 0,
            "extra": {"bitrix24": raw},
        }
        if not item["company_name"] and not item["phone"] and not item["email"]:
            skipped += 1
            continue
        lookup_keys = _outreach_item_lookup_keys(item)
        bitrix_key = f"bitrix24:{_normalize_spaces(raw.get('ID') or '')}"
        match = next((existing_keys.get(key) for key in [bitrix_key, *lookup_keys] if key and existing_keys.get(key)), None)
        if match:
            merged_status = match.get("status") if match.get("status") in {"converted", "warm", "meeting", "do_not_contact"} else item["status"]
            c.execute(
                """
                UPDATE outreach_prospects
                SET company_name=?, company_inn=?, contact_name=?, position=?, phone=?, email=?, website=?, contact_method=?, source_name=?, source_file=?,
                    status=?, priority=?, notes=?, tags_json=?, extra_json=?, updated_at=?
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
                    item["contact_method"] or match.get("contact_method") or "",
                    BITRIX24_SOURCE_NAME,
                    filename,
                    merged_status,
                    item["priority"],
                    item["notes"] or match.get("notes") or "",
                    json.dumps(list(set((_json_load(match.get("tags_json"), []) or []) + item["tags"])), ensure_ascii=False),
                    json.dumps(item["extra"], ensure_ascii=False),
                    now,
                    int(match.get("id") or 0),
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, '', '', '', '', '', '', '', '', 0, 0, 0, 0, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["company_name"],
                    item["company_inn"],
                    item["contact_name"],
                    item["position"],
                    item["phone"],
                    item["email"],
                    item["website"],
                    item["contact_method"],
                    BITRIX24_SOURCE_NAME,
                    filename,
                    item["status"],
                    item["priority"],
                    json.dumps(item["tags"], ensure_ascii=False),
                    item["notes"],
                    json.dumps(item["extra"], ensure_ascii=False),
                    actor.get("email", ""),
                    now,
                    now,
                ),
            )
            new_id = c.lastrowid
            created += 1
            virtual_row = {"id": new_id, **item}
            for key in [bitrix_key, *lookup_keys]:
                if key:
                    existing_keys[key] = virtual_row
    c.execute(
        """
        INSERT INTO outreach_import_batches (
            source_filename, source_name, rows_total, created_total, updated_total, skipped_total,
            default_manager_name, actor_email, actor_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?)
        """,
        (filename, BITRIX24_SOURCE_NAME, len(rows), created, updated, skipped, actor.get("email", ""), actor.get("name", ""), now),
    )
    batch_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log(
        "bitrix24_imported",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="outreach_import",
        entity_id=str(batch_id),
        details={"rows_total": len(rows), "created": created, "updated": updated, "skipped": skipped},
    )
    return {"status": "success", "batch_id": batch_id, "created": created, "updated": updated, "skipped": skipped}


def sync_bitrix24_to_outreach(webhook_url: str = "", actor: dict | None = None, limit: int | None = None) -> dict:
    if not _configured_webhook_url(webhook_url):
        return {"status": "skipped", "reason": "bitrix24_webhook_required", **bitrix24_config_status(webhook_url)}
    fetched = fetch_bitrix24_rows(webhook_url=webhook_url, limit=limit)
    imported = import_bitrix24_rows(fetched["rows"], actor=actor, filename=f"bitrix24-api-{int(time.time())}")
    return {"status": "success", **fetched, **imported}
