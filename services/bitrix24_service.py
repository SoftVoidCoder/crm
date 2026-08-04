import json
import re
import ssl
import subprocess
import time
from difflib import SequenceMatcher
from urllib.parse import urlparse

import httpx

from database import audit_log, get_connection
from routers.projects import (
    _json_load,
    _normalize_outreach_priority,
    _normalize_outreach_status,
    _normalize_match,
    _normalize_spaces,
    _outreach_existing_key_map,
    _outreach_item_lookup_keys,
)
from settings import BITRIX24_SYNC_ENTITIES, BITRIX24_SYNC_LIMIT, BITRIX24_WEBHOOK_URL


BITRIX24_SOURCE_NAME = "Bitrix24 API"
BITRIX24_FULL_SYNC_LIMIT = 2000


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
                connector_type, provider_name, status, settings_json, scope_json, last_sync_at, last_error, created_by, created_at, updated_at
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


def _add_existing_bitrix24_keys(existing_keys: dict[str, dict], rows: list[dict]) -> None:
    for row in rows:
        extra = _json_load(row.get("extra_json"), {}) or {}
        raw = extra.get("bitrix24") if isinstance(extra, dict) else {}
        raw_id = _normalize_spaces(raw.get("ID") if isinstance(raw, dict) else "")
        if raw_id:
            existing_keys[f"bitrix24:{raw_id}"] = row


def _is_generic_bitrix24_name(value: str) -> bool:
    return _normalize_spaces(value).casefold() in {"без названия", "безназвания"}


def _extract_inn_from_text(value: str) -> str:
    match = re.search(r"(?:^|\b)(?:ИНН|INN)\D{0,8}(\d{10}|\d{12})(?:\b|$)", str(value or ""), flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _strip_inn_from_title(value: str) -> str:
    clean = re.sub(r"[\s,;]*(?:ИНН|INN)\D{0,8}(?:\d{10}|\d{12})(?:\b|$)", "", str(value or ""), flags=re.IGNORECASE)
    return _normalize_spaces(clean).strip(" ,;")


def _bitrix_row_quality(row: dict) -> int:
    return (
        (8 if _normalize_spaces(row.get("phone") or "") else 0)
        + (8 if _normalize_spaces(row.get("email") or "") else 0)
        + (5 if _normalize_spaces(row.get("contact_name") or "") else 0)
        + (4 if _normalize_spaces(row.get("company_inn") or "") else 0)
        + (2 if _normalize_spaces(row.get("website") or "") else 0)
        + (1 if _normalize_spaces(row.get("notes") or "") else 0)
    )


def _merge_bitrix_duplicate_prospects(c) -> int:
    rows = [dict(row) for row in c.execute("SELECT * FROM outreach_prospects WHERE source_name=?", (BITRIX24_SOURCE_NAME,)).fetchall()]
    groups: dict[str, list[dict]] = {}
    for row in rows:
        inn = _normalize_match(row.get("company_inn") or "")
        name = _normalize_match(row.get("company_name") or "")
        key = f"inn:{inn}" if inn else f"company:{name}" if name else ""
        if key:
            groups.setdefault(key, []).append(row)
    removed = 0
    for group_rows in groups.values():
        if len(group_rows) < 2:
            continue
        group_rows.sort(key=lambda row: (_bitrix_row_quality(row), int(row.get("updated_at") or 0), int(row.get("id") or 0)), reverse=True)
        keeper = group_rows[0]
        merged = dict(keeper)
        for row in group_rows[1:]:
            for field in ("company_inn", "contact_name", "position", "phone", "email", "website", "contact_method", "notes"):
                if not _normalize_spaces(merged.get(field) or "") and _normalize_spaces(row.get(field) or ""):
                    merged[field] = row.get(field) or ""
        c.execute(
            """
            UPDATE outreach_prospects
            SET company_inn=?, contact_name=?, position=?, phone=?, email=?, website=?, contact_method=?, notes=?
            WHERE id=?
            """,
            (
                merged.get("company_inn") or "",
                merged.get("contact_name") or "",
                merged.get("position") or "",
                merged.get("phone") or "",
                merged.get("email") or "",
                merged.get("website") or "",
                merged.get("contact_method") or "",
                merged.get("notes") or "",
                int(keeper.get("id") or 0),
            ),
        )
        duplicate_ids = [int(row.get("id") or 0) for row in group_rows[1:] if int(row.get("id") or 0)]
        if duplicate_ids:
            placeholders = ",".join("?" for _ in duplicate_ids)
            c.execute(f"DELETE FROM outreach_prospects WHERE id IN ({placeholders})", tuple(duplicate_ids))
            removed += len(duplicate_ids)
    return removed


def _method_url(webhook_url: str, method: str) -> str:
    base = _configured_webhook_url(webhook_url)
    if not base:
        raise ValueError("bitrix24_webhook_required")
    return f"{base}/{method}.json"


def _bitrix_curl_call(url: str, method: str, payload: dict, timeout_seconds: int) -> dict:
    completed = None
    for attempt in range(2):
        try:
            completed = subprocess.run(
                [
                    "curl",
                    "-4",
                    "-sS",
                    "--connect-timeout",
                    str(max(5, min(8, timeout_seconds))),
                    "--max-time",
                    str(max(12, min(24, timeout_seconds * 2))),
                    "-X",
                    "POST",
                    url,
                    "-H",
                    "Content-Type: application/json",
                    "--data-binary",
                    "@-",
                ],
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            raise
        if completed.returncode == 0:
            break
        if attempt < 1:
            time.sleep(1)
    if completed is None or completed.returncode != 0:
        stderr = completed.stderr[:200] if completed else ""
        raise RuntimeError(f"{method}: curl_failed {stderr}")
    data = json.loads(completed.stdout or "{}")
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"{method}: {data.get('error_description') or data.get('error')}")
    return data if isinstance(data, dict) else {"result": data}


def _bitrix_call(webhook_url: str, method: str, payload: dict, timeout_seconds: int = 30, attempts: int = 2) -> dict:
    url = _method_url(webhook_url, method)
    request_timeout = httpx.Timeout(timeout_seconds, connect=min(6, timeout_seconds), write=8, pool=8)
    last_error: Exception | None = None
    max_attempts = max(1, min(3, int(attempts or 1)))
    for attempt in range(max_attempts):
        try:
            return _bitrix_curl_call(url, method, payload, timeout_seconds)
        except FileNotFoundError:
            pass
        except Exception as exc:
            last_error = exc
        try:
            with httpx.Client(timeout=request_timeout, follow_redirects=True) as client:
                response = client.post(url, json=payload)
            if response.status_code >= 400:
                raise RuntimeError(f"{method}: http_{response.status_code}")
            data = response.json()
            if isinstance(data, dict) and data.get("error"):
                raise RuntimeError(f"{method}: {data.get('error_description') or data.get('error')}")
            return data if isinstance(data, dict) else {"result": data}
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError, ssl.SSLError) as exc:
            last_error = exc
        if attempt < max_attempts - 1:
            time.sleep(1 + attempt)
    raise last_error or RuntimeError(f"{method}: request_failed")


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


def _fetch_filtered_list(webhook_url: str, method: str, select: list[str], filter_payload: dict, limit: int, timeout_seconds: int = 8) -> list[dict]:
    rows: list[dict] = []
    start: int | str = 0
    while len(rows) < limit:
        data = _bitrix_call(
            webhook_url,
            method,
            {
                "select": select,
                "filter": filter_payload or {},
                "order": {"DATE_MODIFY": "DESC", "ID": "DESC"},
                "start": start,
            },
            timeout_seconds=timeout_seconds,
            attempts=1,
        )
        result = data.get("result") or []
        if not isinstance(result, list):
            break
        rows.extend([item for item in result if isinstance(item, dict)])
        if "next" not in data or len(result) == 0:
            break
        start = data.get("next")
    return rows[:limit]


def _dedupe_bitrix_items(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        key = (item.get("type"), str(item.get("id") or ""))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _search_normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", " ", str(value or "").casefold()).strip()


def _safe_positive_int(value) -> int:
    try:
        result = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return result if result > 0 else 0


def _bitrix_search_terms(query: str) -> list[str]:
    clean_query = _normalize_spaces(query)
    if not clean_query:
        return []
    terms = [clean_query]
    tokens = [token for token in re.split(r"\s+", clean_query) if len(token) >= 3]
    terms.extend(tokens[:1])
    if tokens and len(tokens[0]) >= 5:
        terms.append(tokens[0][: max(3, len(tokens[0]) - 1)])
    compact_digits = re.sub(r"\D+", "", clean_query)
    if len(compact_digits) >= 5:
        terms.append(compact_digits[-10:])
    if "@" in clean_query:
        terms.append(clean_query.split("@", 1)[0])
    result = []
    seen = set()
    for term in terms:
        normalized = _normalize_spaces(term)
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
        if len(result) >= 3:
            break
    return result


def _bitrix_search_score(item: dict, query: str) -> float:
    if not query:
        return 0
    query_key = _search_normalize(query)
    haystack = _search_normalize(
        " ".join(
            [
                item.get("title", ""),
                item.get("contact_name", ""),
                item.get("phone", ""),
                item.get("email", ""),
            ]
        )
    )
    if not query_key or not haystack:
        return 0
    score = 0.0
    if query_key in haystack:
        score += 100
    query_tokens = [token for token in query_key.split() if len(token) >= 2]
    haystack_tokens = [token for token in haystack.split() if len(token) >= 2]
    for token in query_tokens:
        if any(token in target or target in token for target in haystack_tokens):
            score += 24
        else:
            score += max((SequenceMatcher(None, token, target).ratio() for target in haystack_tokens), default=0) * 18
    score += SequenceMatcher(None, query_key, haystack[: max(len(query_key), 1)]).ratio() * 12
    return score


def _safe_fetch_filtered_list(webhook_url: str, method: str, select: list[str], filter_payload: dict, limit: int) -> list[dict]:
    try:
        return _fetch_filtered_list(webhook_url, method, select, filter_payload, limit, timeout_seconds=8)
    except Exception:
        return []


def _bitrix_search_item(entity_type: str, raw: dict, company_map: dict[str, dict] | None = None) -> dict:
    company_map = company_map or {}
    if entity_type == "lead":
        row = _lead_to_import_row(raw)
    elif entity_type == "contact":
        row = _contact_to_import_row(raw, company_map)
    else:
        row = _company_to_import_row(raw)
    return {
        "type": entity_type,
        "id": _normalize_spaces(raw.get("ID") or ""),
        "title": _normalize_spaces(row.get("COMPANY_TITLE") or row.get("TITLE") or row.get("CONTACT_NAME") or ""),
        "contact_name": _normalize_spaces(row.get("CONTACT_NAME") or ""),
        "phone": _normalize_spaces(row.get("PHONE") or ""),
        "email": _normalize_spaces(row.get("EMAIL") or ""),
        "date_modify": _normalize_spaces(row.get("DATE_MODIFY") or ""),
    }


def _loaded_bitrix_search_item(row: dict) -> dict:
    extra = _json_load(row.get("extra_json"), {}) or {}
    raw = extra.get("bitrix24") if isinstance(extra, dict) else {}
    raw_id = _normalize_spaces(raw.get("ID") if isinstance(raw, dict) else "")
    entity_type = "prospect"
    entity_id = str(row.get("id") or "")
    if ":" in raw_id:
        entity_type, entity_id = raw_id.split(":", 1)
    return {
        "type": entity_type,
        "id": entity_id,
        "prospect_id": int(row.get("id") or 0),
        "already_loaded": True,
        "title": _normalize_spaces(row.get("company_name") or ""),
        "contact_name": _normalize_spaces(row.get("contact_name") or ""),
        "phone": _normalize_spaces(row.get("phone") or ""),
        "email": _normalize_spaces(row.get("email") or ""),
        "date_modify": _normalize_spaces(raw.get("DATE_MODIFY") if isinstance(raw, dict) else "") or str(row.get("updated_at") or ""),
    }


def _search_loaded_bitrix_clients(query: str, limit: int) -> list[dict]:
    clean_query = _normalize_spaces(query)
    if not clean_query:
        return []
    try:
        conn = get_connection(row_factory=True)
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM outreach_prospects
                WHERE source_name=?
                ORDER BY updated_at DESC, id DESC
                LIMIT 2000
                """,
                (BITRIX24_SOURCE_NAME,),
            ).fetchall()
        ]
        conn.close()
    except Exception:
        return []
    items = [_loaded_bitrix_search_item(row) for row in rows]
    scored = [(item, _bitrix_search_score(item, clean_query)) for item in items]
    scored = [pair for pair in scored if pair[1] >= 12]
    scored.sort(key=lambda pair: (pair[1], pair[0].get("date_modify", "")), reverse=True)
    return [item for item, _score in scored[:limit]]


def search_bitrix24_clients(query: str = "", limit: int = 20, webhook_url: str = "") -> dict:
    clean_query = _normalize_spaces(query)
    row_limit = max(1, min(30, int(limit or 20)))
    if len(clean_query) < 3:
        return {
            "status": "success",
            "query": clean_query,
            "items": [],
            "source": "query_too_short",
            "message": "Введите минимум 3 символа для поиска в Bitrix24.",
        }
    loaded_items = _search_loaded_bitrix_clients(clean_query, row_limit)
    if loaded_items:
        return {"status": "success", "query": clean_query, "items": loaded_items, "source": "crm_cache"}
    company_select = ["ID", "TITLE", "PHONE", "EMAIL", "WEB", "COMMENTS", "DATE_CREATE", "DATE_MODIFY"]
    contact_select = ["ID", "NAME", "LAST_NAME", "SECOND_NAME", "POST", "COMPANY_ID", "PHONE", "EMAIL", "WEB", "COMMENTS", "DATE_CREATE", "DATE_MODIFY"]
    lead_select = [
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
    ]
    if clean_query:
        search_limit = max(row_limit, 8)
        companies = []
        contacts = []
        leads = []
        for term in _bitrix_search_terms(clean_query)[:1]:
            companies.extend(_safe_fetch_filtered_list(webhook_url, "crm.company.list", company_select, {"%TITLE": term}, search_limit))
            contacts.extend(_safe_fetch_filtered_list(webhook_url, "crm.contact.list", contact_select, {"%NAME": term}, search_limit))
            contacts.extend(_safe_fetch_filtered_list(webhook_url, "crm.contact.list", contact_select, {"%LAST_NAME": term}, search_limit))
            leads.extend(_safe_fetch_filtered_list(webhook_url, "crm.lead.list", lead_select, {"%TITLE": term}, search_limit))
    else:
        return {"status": "success", "query": clean_query, "items": []}
    company_map = {_normalize_spaces(item.get("ID") or ""): item for item in companies}
    items = []
    items.extend(_bitrix_search_item("company", item) for item in companies)
    items.extend(_bitrix_search_item("contact", item, company_map) for item in contacts)
    items.extend(_bitrix_search_item("lead", item) for item in leads)
    found = _dedupe_bitrix_items(items)
    if clean_query:
        found.sort(key=lambda item: (_bitrix_search_score(item, clean_query), item.get("date_modify", "")), reverse=True)
    return {"status": "success", "query": clean_query, "items": found[:row_limit]}


def _bitrix_get_entity(entity_type: str, entity_id: str, webhook_url: str = "") -> dict | None:
    clean_type = _normalize_spaces(entity_type).lower()
    clean_id = _normalize_spaces(entity_id)
    if clean_type not in {"lead", "contact", "company"} or not clean_id:
        return None
    method = {"lead": "crm.lead.get", "contact": "crm.contact.get", "company": "crm.company.get"}[clean_type]
    data = _bitrix_call(webhook_url, method, {"id": clean_id}, timeout_seconds=20)
    raw = data.get("result") if isinstance(data, dict) else None
    return raw if isinstance(raw, dict) else None


def import_selected_bitrix24_clients(items: list[dict], actor: dict | None = None, webhook_url: str = "") -> dict:
    rows = []
    already_loaded = 0
    company_cache: dict[str, dict] = {}
    for item in items or []:
        if _safe_positive_int(item.get("prospect_id") or 0):
            already_loaded += 1
            continue
        entity_type = _normalize_spaces(item.get("type") or "").lower()
        entity_id = _normalize_spaces(item.get("id") or "")
        raw = _bitrix_get_entity(entity_type, entity_id, webhook_url)
        if not raw:
            continue
        if entity_type == "lead":
            rows.append(_lead_to_import_row(raw))
        elif entity_type == "contact":
            company_id = _normalize_spaces(raw.get("COMPANY_ID") or "")
            if company_id and company_id not in company_cache:
                company_raw = _bitrix_get_entity("company", company_id, webhook_url)
                if company_raw:
                    company_cache[company_id] = company_raw
            rows.append(_contact_to_import_row(raw, company_cache))
        elif entity_type == "company":
            rows.append(_company_to_import_row(raw))
    if not rows and already_loaded:
        return {"status": "success", "rows_total": already_loaded, "created": 0, "updated": already_loaded, "skipped": 0}
    if not rows:
        return {"status": "failed", "error": "empty_selection", "message": "Выберите клиента из Bitrix24."}
    imported = import_bitrix24_rows(rows, actor=actor, filename=f"bitrix24-selected-{int(time.time())}")
    return {"status": "success", "rows_total": len(rows) + already_loaded, **imported}


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
    row_limit = max(1, min(BITRIX24_FULL_SYNC_LIMIT, int(limit or BITRIX24_FULL_SYNC_LIMIT)))
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
        "rows": rows,
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
    _add_existing_bitrix24_keys(existing_keys, existing_rows)
    created = updated = skipped = 0
    for raw in rows:
        item = {
            "company_name": _strip_inn_from_title(raw.get("COMPANY_TITLE") or raw.get("TITLE") or ""),
            "company_inn": _normalize_spaces(raw.get("INN") or raw.get("RQ_INN") or _extract_inn_from_text(raw.get("COMPANY_TITLE") or raw.get("TITLE") or "")),
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
        if _is_generic_bitrix24_name(item["company_name"]):
            lookup_keys = [key for key in lookup_keys if not key.startswith("company:")]
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
    duplicates_removed = _merge_bitrix_duplicate_prospects(c)
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
        details={"rows_total": len(rows), "created": created, "updated": updated, "skipped": skipped, "duplicates_removed": duplicates_removed},
    )
    return {"status": "success", "batch_id": batch_id, "created": created, "updated": updated, "skipped": skipped, "duplicates_removed": duplicates_removed}


def sync_bitrix24_to_outreach(webhook_url: str = "", actor: dict | None = None, limit: int | None = None) -> dict:
    if not _configured_webhook_url(webhook_url):
        return {"status": "skipped", "reason": "bitrix24_webhook_required", **bitrix24_config_status(webhook_url)}
    fetched = fetch_bitrix24_rows(webhook_url=webhook_url, limit=limit)
    imported = import_bitrix24_rows(fetched["rows"], actor=actor, filename=f"bitrix24-api-{int(time.time())}")
    return {"status": "success", "rows_total": len(fetched["rows"]), "fetched": fetched["fetched"], **imported}


def clear_bitrix24_outreach_clients(actor: dict | None = None) -> dict:
    actor = actor or {"email": "system@korda.local", "name": "Bitrix24"}
    conn = get_connection(row_factory=True)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM outreach_prospects WHERE source_name=?",
            (BITRIX24_SOURCE_NAME,),
        ).fetchone()
        removed = int((row or {}).get("n") or 0)
        conn.execute("DELETE FROM outreach_prospects WHERE source_name=?", (BITRIX24_SOURCE_NAME,))
        conn.execute("DELETE FROM outreach_import_batches WHERE source_name=?", (BITRIX24_SOURCE_NAME,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit_log(
        "bitrix24_outreach_cleared",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="outreach_import",
        entity_id="bitrix24",
        details={"removed": removed},
    )
    return {"status": "success", "removed": removed}
