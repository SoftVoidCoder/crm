def build_unified_event_stream(*, audit_rows: list[dict], field_changes: list[dict], domain_rows: list[dict] | None = None, limit: int = 120, entity_type: str = ""):
    events = []
    normalized_entity_type = str(entity_type or "").strip()
    for row in audit_rows or []:
        if normalized_entity_type and str(row.get("entity_type") or "") != normalized_entity_type:
            continue
        details = row.get("details") or {}
        events.append(
            {
                "stream_type": "audit",
                "timestamp": int(row.get("created_at") or 0),
                "entity_type": row.get("entity_type") or "",
                "entity_id": row.get("entity_id") or "",
                "title": row.get("action") or "event",
                "message": details.get("message") if isinstance(details, dict) else "",
                "actor_email": row.get("actor_email") or "",
                "actor_name": row.get("actor_name") or "",
                "details": details,
            }
        )
    for row in field_changes or []:
        if normalized_entity_type and str(row.get("entity_type") or "") != normalized_entity_type:
            continue
        events.append(
            {
                "stream_type": "field_change",
                "timestamp": int(row.get("created_at") or 0),
                "entity_type": row.get("entity_type") or "",
                "entity_id": row.get("entity_id") or "",
                "title": f"Изменено поле {row.get('field_name') or ''}".strip(),
                "message": "",
                "actor_email": row.get("actor_email") or "",
                "actor_name": row.get("actor_name") or "",
                "details": {
                    "field_name": row.get("field_name") or "",
                    "old_value": row.get("old_value") or "",
                    "new_value": row.get("new_value") or "",
                },
            }
        )
    for row in domain_rows or []:
        if normalized_entity_type and str(row.get("entity_type") or "") != normalized_entity_type:
            continue
        payload = row.get("payload") or {}
        events.append(
            {
                "stream_type": "domain_event",
                "timestamp": int(row.get("created_at") or 0),
                "entity_type": row.get("entity_type") or "",
                "entity_id": row.get("entity_id") or "",
                "title": row.get("event_name") or "domain_event",
                "message": payload.get("message") if isinstance(payload, dict) else "",
                "actor_email": row.get("actor_email") or "",
                "actor_name": row.get("actor_name") or "",
                "details": {
                    "domain_name": row.get("domain_name") or "",
                    "severity": row.get("severity") or "info",
                    "payload": payload,
                },
            }
        )
    events.sort(key=lambda item: (int(item.get("timestamp") or 0), str(item.get("stream_type") or "")), reverse=True)
    return events[: max(1, min(limit, 500))]
