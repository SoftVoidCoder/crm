import json
import time


def record_domain_event(
    *,
    get_connection,
    domain_name: str,
    event_name: str,
    entity_type: str = "",
    entity_id: str = "",
    actor_email: str = "",
    actor_name: str = "",
    payload: dict | None = None,
    severity: str = "info",
):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO domain_events (
                domain_name, event_name, entity_type, entity_id, actor_email, actor_name,
                payload, severity, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                domain_name,
                event_name,
                entity_type,
                str(entity_id or ""),
                actor_email,
                actor_name,
                json.dumps(payload or {}, ensure_ascii=False),
                severity,
                int(time.time()),
            ),
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


def list_domain_events(*, get_connection, limit: int = 120, entity_type: str = "", entity_id: str = ""):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        clauses = []
        params = []
        if entity_type:
            clauses.append("entity_type=?")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id=?")
            params.append(str(entity_id))
        sql = "SELECT * FROM domain_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        c.execute(sql, params)
        rows = [dict(row) for row in c.fetchall()]
    finally:
        conn.close()
    for row in rows:
        try:
            row["payload"] = json.loads(row.get("payload") or "{}")
        except Exception:
            row["payload"] = {}
    return rows
