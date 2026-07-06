import time


TASK_DONE_STATUSES = {"done", "completed", "closed", "finished"}
APPROVAL_DONE_STATUSES = {"completed", "approved"}
APPROVAL_BLOCKED_STATUSES = {"rejected", "cancelled"}


def _safe_text(value) -> str:
    return str(value or "").strip()


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _row_dict(row) -> dict:
    if not row:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return {}


def _workflow_progress(stage: str, status: str) -> int:
    if status == "completed":
        return 100
    if stage == "incoming":
        return 10
    if stage == "task":
        return 30
    if stage == "approval":
        return 55
    if stage == "execution":
        return 80
    if stage == "archive":
        return 95 if status == "ready" else 100
    return 0


def _workflow_steps(document: dict, task: dict, approval: dict, archive_total: int, incoming_complete: bool) -> list[dict]:
    task_status = _safe_text(task.get("status")).lower()
    approval_status = _safe_text(approval.get("status")).lower()
    return [
        {"step": "incoming", "label": "Входящий", "status": "completed" if incoming_complete else "pending"},
        {"step": "task", "label": "Поручение", "status": "completed" if task_status in TASK_DONE_STATUSES else ("in_progress" if task else "pending")},
        {"step": "approval", "label": "Согласование", "status": "completed" if approval_status in APPROVAL_DONE_STATUSES else ("blocked" if approval_status in APPROVAL_BLOCKED_STATUSES else ("in_progress" if approval else "pending"))},
        {"step": "execution", "label": "Исполнение", "status": "completed" if task_status in TASK_DONE_STATUSES else ("in_progress" if task else "pending")},
        {"step": "archive", "label": "Архив", "status": "completed" if archive_total else "pending"},
    ]


def _load_task_for_document(conn, document: dict) -> dict:
    task_id = _safe_int(document.get("resolution_task_id"))
    if task_id:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        task = _row_dict(row)
        if task:
            return task
    row = conn.execute(
        """
        SELECT t.*
        FROM document_linked_tasks l
        LEFT JOIN tasks t ON t.id = l.task_id
        WHERE l.document_id=?
        ORDER BY l.updated_at DESC, l.id DESC
        LIMIT 1
        """,
        (_safe_int(document.get("id")),),
    ).fetchone()
    return _row_dict(row)


def _load_approval_for_document(conn, document: dict) -> dict:
    approval_id = _safe_int(document.get("approval_id"))
    if approval_id:
        row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        approval = _row_dict(row)
        if approval:
            return approval
    row = conn.execute(
        """
        SELECT *
        FROM approvals
        WHERE entity_type='document' AND entity_id=?
        ORDER BY last_action_at DESC, id DESC
        LIMIT 1
        """,
        (str(_safe_int(document.get("id"))),),
    ).fetchone()
    return _row_dict(row)


def compose_document_workflow(conn, document_id: int) -> dict:
    document = _row_dict(conn.execute("SELECT * FROM documents WHERE id=?", (_safe_int(document_id),)).fetchone())
    if not document:
        return {}
    task = _load_task_for_document(conn, document)
    approval = _load_approval_for_document(conn, document)
    archive_row = _row_dict(
        conn.execute(
            "SELECT * FROM document_legal_archive WHERE document_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
            (_safe_int(document_id),),
        ).fetchone()
    )
    archive_count_row = conn.execute("SELECT COUNT(*) AS cnt FROM document_legal_archive WHERE document_id=?", (_safe_int(document_id),)).fetchone()
    archive_total = _safe_int(_row_dict(archive_count_row).get("cnt") if archive_count_row else 0)
    lifecycle_state = _safe_text(document.get("lifecycle_state")).lower()
    status_state = _safe_text(document.get("status")).lower()
    incoming_complete = bool(
        _safe_text(document.get("registration_number"))
        or _safe_int(document.get("registered_at"))
        or lifecycle_state in {"registered", "review", "approved", "signed", "archived"}
        or status_state in {"registered", "review", "approved", "signed", "archived"}
    )
    current_state = lifecycle_state or status_state
    workflow_started = bool(_safe_int(document.get("workflow_started_at")))
    task_status = _safe_text(task.get("status")).lower()
    approval_status = _safe_text(approval.get("status")).lower()
    task_exists = bool(task)
    approval_exists = bool(approval)
    task_completed = task_status in TASK_DONE_STATUSES
    approval_completed = approval_status in APPROVAL_DONE_STATUSES
    approval_blocked = approval_status in APPROVAL_BLOCKED_STATUSES
    archived = archive_total > 0 or current_state == "archived"

    stage = _safe_text(document.get("workflow_stage")) or "incoming"
    status = _safe_text(document.get("workflow_status")) or ("idle" if not workflow_started else "blocked")
    blocking_reason = _safe_text(document.get("workflow_block_reason"))
    if workflow_started:
        if not incoming_complete:
            stage = "incoming"
            status = "blocked"
            blocking_reason = "registration_required"
        elif not task_exists:
            stage = "task"
            status = "blocked"
            blocking_reason = "resolution_task_required"
        elif approval_blocked:
            stage = "approval"
            status = "blocked"
            blocking_reason = "approval_rejected"
        elif not approval_exists:
            stage = "approval"
            status = "blocked"
            blocking_reason = "approval_required"
        elif not approval_completed:
            stage = "approval"
            status = "in_progress"
            blocking_reason = "approval_pending"
        elif not task_completed:
            stage = "execution"
            status = "in_progress"
            blocking_reason = "task_execution_pending"
        elif not archived:
            stage = "archive"
            status = "ready"
            blocking_reason = "legal_archive_pending"
        else:
            stage = "archive"
            status = "completed"
            blocking_reason = ""
    elif archived:
        stage = "archive"
        status = "completed"
        blocking_reason = ""
    approval_id = _safe_int(approval.get("id") or document.get("approval_id"))
    return {
        "document_id": _safe_int(document_id),
        "started": workflow_started,
        "stage": stage,
        "status": status,
        "blocking_reason": blocking_reason,
        "progress_percent": _workflow_progress(stage, status),
        "can_archive": bool(workflow_started and incoming_complete and task_exists and approval_exists and approval_completed and task_completed),
        "task": {
            "id": _safe_int(task.get("id")),
            "status": task_status or ("pending" if workflow_started else ""),
            "executor": _safe_text(task.get("executor")),
            "deadline": _safe_text(task.get("deadline")),
        },
        "approval": {
            "id": approval_id,
            "status": approval_status or ("pending" if workflow_started else ""),
            "current_stage_key": _safe_text(approval.get("current_stage_key")),
            "current_assignees": _safe_text(approval.get("current_assignees")),
        },
        "archive": {
            "id": _safe_int(archive_row.get("id")),
            "status": _safe_text(archive_row.get("archive_status")),
            "archive_code": _safe_text(archive_row.get("archive_code")),
        },
        "steps": _workflow_steps(document, task, approval, archive_total, incoming_complete),
    }


def sync_document_workflow(conn, document_id: int, actor: dict | None = None, comment: str = "", action_name: str = "workflow_sync") -> dict:
    payload = compose_document_workflow(conn, document_id)
    if not payload:
        return {}
    document = _row_dict(conn.execute("SELECT * FROM documents WHERE id=?", (_safe_int(document_id),)).fetchone())
    previous_stage = _safe_text(document.get("workflow_stage"))
    previous_status = _safe_text(document.get("workflow_status"))
    previous_block = _safe_text(document.get("workflow_block_reason"))
    completed_at = _safe_int(document.get("workflow_completed_at"))
    if payload.get("status") == "completed" and not completed_at:
        completed_at = int(time.time())
    elif payload.get("status") != "completed":
        completed_at = 0
    conn.execute(
        """
        UPDATE documents
        SET workflow_stage=?, workflow_status=?, approval_id=?, workflow_block_reason=?, workflow_completed_at=?
        WHERE id=?
        """,
        (
            _safe_text(payload.get("stage")),
            _safe_text(payload.get("status")),
            _safe_int(payload.get("approval", {}).get("id")),
            _safe_text(payload.get("blocking_reason")),
            completed_at,
            _safe_int(document_id),
        ),
    )
    if _safe_int(document.get("workflow_started_at")) and (
        previous_stage != _safe_text(payload.get("stage"))
        or previous_status != _safe_text(payload.get("status"))
        or previous_block != _safe_text(payload.get("blocking_reason"))
    ):
        conn.execute(
            """
            INSERT INTO document_lifecycle_events (
                document_id, from_state, to_state, action_name, actor_email, actor_name, comment, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _safe_int(document_id),
                f"workflow:{previous_stage or 'none'}:{previous_status or 'none'}",
                f"workflow:{_safe_text(payload.get('stage'))}:{_safe_text(payload.get('status'))}",
                _safe_text(action_name) or "workflow_sync",
                _safe_text((actor or {}).get("email")),
                _safe_text((actor or {}).get("name")) or "Система",
                _safe_text(comment) or _safe_text(payload.get("blocking_reason")),
                int(time.time()),
            ),
        )
    return payload


def list_documents_for_task(conn, task_id: int) -> list[int]:
    document_ids = {
        _safe_int(_row_dict(row).get("id"))
        for row in conn.execute("SELECT id FROM documents WHERE resolution_task_id=?", (_safe_int(task_id),)).fetchall()
    }
    document_ids.update(
        _safe_int(_row_dict(row).get("document_id"))
        for row in conn.execute("SELECT document_id FROM document_linked_tasks WHERE task_id=?", (_safe_int(task_id),)).fetchall()
    )
    return sorted(doc_id for doc_id in document_ids if doc_id)


def list_documents_for_approval(conn, approval_id: int) -> list[int]:
    document_ids = {
        _safe_int(_row_dict(row).get("id"))
        for row in conn.execute("SELECT id FROM documents WHERE approval_id=?", (_safe_int(approval_id),)).fetchall()
    }
    approval = _row_dict(conn.execute("SELECT entity_type, entity_id FROM approvals WHERE id=?", (_safe_int(approval_id),)).fetchone())
    if _safe_text(approval.get("entity_type")) == "document":
        document_ids.add(_safe_int(approval.get("entity_id")))
    return sorted(doc_id for doc_id in document_ids if doc_id)
