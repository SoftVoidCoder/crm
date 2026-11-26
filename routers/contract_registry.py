import datetime
import os
import random
import re
import secrets
import time

from fastapi import APIRouter, Body, File, Request, UploadFile

from database import get_connection, audit_log
from permissions import require_approved_user, has_permission
from routers.projects import _lookup_company_by_inn

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES_DIR = os.path.join(BASE_DIR, "uploads", "contract_registry")
MAX_FILE_BYTES = 25 * 1024 * 1024

CONTRACT_TEXT_FIELDS = {
    "number", "extra_number", "incoming_number", "gov_reg_number", "created_date", "concluded_date", "end_date",
    "currency", "kind", "responsible", "initiator", "tender", "category", "subject", "note", "basis", "notify_date",
    "prolongation_terms", "sent_for_signing_date", "signed_date", "signing_method", "sent_to_counterparty_date",
    "original_status",
}
CONTRACT_INT_FIELDS = {
    "doc_type_id", "folder_id", "seq_no", "flagged", "vat_enabled", "vat_manual", "notify_enabled", "notify_days",
    "internal_only", "payment_deferral", "framework", "prolongation", "indefinite", "on_counterparty_signing",
    "signed", "on_counterparty_review",
}
CONTRACT_REAL_FIELDS = {"amount", "vat_rate", "vat_amount"}
COUNTERPARTY_FIELDS = {"name", "short_name", "inn", "kpp", "ogrn", "legal_address", "director", "phone", "email", "status", "note"}
APPROVAL_STATUSES = {"pending", "approved", "approved_with_notes", "rejected"}
KINDS = {"other", "expense", "income"}
DATE_FIELDS = {"created_date", "concluded_date", "end_date", "notify_date", "sent_for_signing_date", "signed_date", "sent_to_counterparty_date"}


def _actor(request: Request, action: str = "read"):
    actor = require_approved_user(request)
    if not actor or not has_permission(actor, "documents", action):
        return None
    return actor


def _text(value, limit: int = 4000) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _real(value) -> float:
    try:
        return round(float(str(value or 0).replace(",", ".").replace(" ", "")), 2)
    except (TypeError, ValueError):
        return 0.0


def _date(value) -> str:
    raw = _text(value, 20)
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _rows(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def format_contract_number(doc_type: dict, seq_no: int, year: int | None = None) -> str:
    digits = max(0, min(12, _int(doc_type.get("digits"))))
    core = str(seq_no).zfill(digits) if digits else str(seq_no)
    number = f"{doc_type.get('prefix') or ''}{core}{doc_type.get('postfix') or ''}"
    if _int(doc_type.get("add_year")):
        number += str(year or datetime.date.today().year)
    return number


def _vat(amount: float, rate: float) -> float:
    # Contract amount is VAT-inclusive, as in the registry columns "Сумма / Сумма НДС / Сумма без НДС".
    return round(amount * rate / (100 + rate), 2) if rate > 0 else 0.0


def contract_flags(contract: dict, approvals: list[dict], today: datetime.date | None = None) -> dict:
    today = today or datetime.date.today()
    flags = {"overdue": False, "expiring": False, "approvals_open": False, "approvals_overdue": False}
    end = _date(contract.get("end_date"))
    if end and not _int(contract.get("indefinite")):
        end_date = datetime.date.fromisoformat(end)
        horizon = max(_int(contract.get("notify_days")), 30)
        flags["overdue"] = end_date < today
        flags["expiring"] = today <= end_date <= today + datetime.timedelta(days=horizon)
    for item in approvals:
        if item.get("status") == "pending":
            flags["approvals_open"] = True
            due = _date(item.get("due_date"))
            if due and datetime.date.fromisoformat(due) < today:
                flags["approvals_overdue"] = True
    return flags


def _contract_payload(contract: dict) -> dict:
    amount = _real(contract.get("amount"))
    vat_amount = _real(contract.get("vat_amount")) if _int(contract.get("vat_enabled")) else 0.0
    contract["amount_without_vat"] = round(amount - vat_amount, 2)
    return contract


def _load_contract(c, contract_id: int) -> dict | None:
    c.execute(
        """
        SELECT k.*, t.name AS doc_type_name, f.name AS folder_name
        FROM cr_contracts k
        LEFT JOIN cr_doc_types t ON t.id = k.doc_type_id
        LEFT JOIN cr_folders f ON f.id = k.folder_id
        WHERE k.id=?
        """,
        (contract_id,),
    )
    row = c.fetchone()
    return _contract_payload(dict(row)) if row else None


# ---------- folders ----------

@router.get("/api/cr/meta")
def registry_meta(request: Request):
    if not _actor(request):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT id, name, sort_order FROM cr_folders ORDER BY sort_order, name")
        folders = _rows(c)
        c.execute("SELECT folder_id, COUNT(*) AS n FROM cr_contracts WHERE is_deleted=0 GROUP BY folder_id")
        counts = {row["folder_id"]: row["n"] for row in _rows(c)}
        c.execute("SELECT COUNT(*) AS n FROM cr_contracts WHERE is_deleted=0")
        total = c.fetchone()["n"]
        c.execute("SELECT COUNT(*) AS n FROM cr_contracts WHERE is_deleted=1")
        deleted = c.fetchone()["n"]
    finally:
        conn.close()
    for folder in folders:
        folder["count"] = counts.get(folder["id"], 0)
    return {"folders": folders, "total": total, "deleted": deleted}


@router.post("/api/cr/folders")
def create_folder(request: Request, payload: dict = Body(...)):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    name = _text(payload.get("name"), 120)
    if not name:
        return {"error": "name_required", "message": "Укажи название папки."}
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO cr_folders (name, sort_order, created_at) VALUES (?, ?, ?)", (name, _int(payload.get("sort_order")) or 100, int(time.time())))
        folder_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "id": folder_id}


@router.put("/api/cr/folders/{folder_id}")
def rename_folder(folder_id: int, request: Request, payload: dict = Body(...)):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    name = _text(payload.get("name"), 120)
    if not name:
        return {"error": "name_required", "message": "Укажи название папки."}
    conn = get_connection()
    try:
        conn.execute("UPDATE cr_folders SET name=? WHERE id=?", (name, folder_id))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


@router.delete("/api/cr/folders/{folder_id}")
def delete_folder(folder_id: int, request: Request):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        # Contracts stay; they just move to "Все" (no folder).
        conn.execute("UPDATE cr_contracts SET folder_id=0 WHERE folder_id=?", (folder_id,))
        conn.execute("DELETE FROM cr_folders WHERE id=?", (folder_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


# ---------- document types (auto-numbering) ----------

def _doc_type_values(payload: dict) -> tuple:
    return (
        _text(payload.get("name"), 300),
        _text(payload.get("prefix"), 40),
        max(0, _int(payload.get("counter"))),
        max(0, min(12, _int(payload.get("digits")))),
        _text(payload.get("postfix"), 40),
        1 if _int(payload.get("add_year")) else 0,
        _int(payload.get("counterparty_id")),
    )


@router.get("/api/cr/doc_types")
def list_doc_types(request: Request):
    if not _actor(request):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT t.*, COALESCE(p.short_name, p.name, '') AS counterparty_name
            FROM cr_doc_types t LEFT JOIN cr_counterparties p ON p.id = t.counterparty_id
            ORDER BY t.name
            """
        )
        items = _rows(c)
    finally:
        conn.close()
    for item in items:
        item["next_number"] = format_contract_number(item, _int(item.get("counter")) + 1)
    return items


@router.post("/api/cr/doc_types")
def create_doc_type(request: Request, payload: dict = Body(...)):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    values = _doc_type_values(payload)
    if not values[0]:
        return {"error": "name_required", "message": "Укажи наименование типа документа."}
    now = int(time.time())
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO cr_doc_types (name, prefix, counter, digits, postfix, add_year, counterparty_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*values, now, now),
        )
        type_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "id": type_id}


@router.put("/api/cr/doc_types/{type_id}")
def update_doc_type(type_id: int, request: Request, payload: dict = Body(...)):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    values = _doc_type_values(payload)
    if not values[0]:
        return {"error": "name_required", "message": "Укажи наименование типа документа."}
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE cr_doc_types SET name=?, prefix=?, counter=?, digits=?, postfix=?, add_year=?, counterparty_id=?, updated_at=? WHERE id=?",
            (*values, int(time.time()), type_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


@router.delete("/api/cr/doc_types/{type_id}")
def delete_doc_type(type_id: int, request: Request):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        used = conn.execute("SELECT COUNT(*) AS n FROM cr_contracts WHERE doc_type_id=?", (type_id,)).fetchone()["n"]
        if used:
            return {"error": "in_use", "message": f"Тип используется в {used} договорах, удалить нельзя."}
        conn.execute("DELETE FROM cr_doc_types WHERE id=?", (type_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


# ---------- contracts ----------

@router.get("/api/cr/contracts")
def list_contracts(request: Request, folder: str = "all", period: str = "all", date_from: str = "", date_to: str = "", q: str = ""):
    if not _actor(request):
        return {"error": "forbidden"}
    where, params = [], []
    if folder == "deleted":
        where.append("k.is_deleted=1")
    else:
        where.append("k.is_deleted=0")
        if folder not in ("", "all"):
            where.append("k.folder_id=?")
            params.append(_int(folder))
    if period == "year":
        where.append("k.created_date >= ?")
        params.append((datetime.date.today() - datetime.timedelta(days=365)).isoformat())
    elif period == "range":
        if _date(date_from):
            where.append("k.created_date >= ?")
            params.append(_date(date_from))
        if _date(date_to):
            where.append("k.created_date <= ?")
            params.append(_date(date_to))
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            f"""
            SELECT k.*, t.name AS doc_type_name, f.name AS folder_name
            FROM cr_contracts k
            LEFT JOIN cr_doc_types t ON t.id = k.doc_type_id
            LEFT JOIN cr_folders f ON f.id = k.folder_id
            WHERE {' AND '.join(where)}
            ORDER BY k.id DESC
            """,
            params,
        )
        contracts = [_contract_payload(row) for row in _rows(c)]
        ids = [row["id"] for row in contracts] or [0]
        marks = ",".join("?" * len(ids))
        c.execute(
            f"""
            SELECT pp.contract_id, pp.role, COALESCE(NULLIF(p.short_name, ''), p.name) AS name, p.inn
            FROM cr_contract_parties pp JOIN cr_counterparties p ON p.id = pp.counterparty_id
            WHERE pp.contract_id IN ({marks}) ORDER BY pp.id
            """,
            ids,
        )
        parties = {}
        for row in _rows(c):
            parties.setdefault(row["contract_id"], []).append(row)
        c.execute(f"SELECT contract_id, status, due_date FROM cr_approvals WHERE contract_id IN ({marks})", ids)
        approvals = {}
        for row in _rows(c):
            approvals.setdefault(row["contract_id"], []).append(row)
    finally:
        conn.close()
    needle = _text(q, 200).lower()
    result = []
    for contract in contracts:
        contract["parties"] = parties.get(contract["id"], [])
        contract["flags"] = contract_flags(contract, approvals.get(contract["id"], []))
        if needle:
            haystack = " ".join(
                [str(contract.get(key) or "") for key in ("number", "extra_number", "incoming_number", "gov_reg_number", "subject", "responsible", "doc_type_name", "category")]
                + [f"{p['name']} {p['inn']}" for p in contract["parties"]]
            ).lower()
            if needle not in haystack:
                continue
        result.append(contract)
    return result


@router.post("/api/cr/contracts")
def create_contract(request: Request, payload: dict = Body(...)):
    actor = _actor(request, "create")
    if not actor:
        return {"error": "forbidden"}
    type_id = _int(payload.get("doc_type_id"))
    number = _text(payload.get("number"), 120)
    now = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        doc_type = None
        seq_no = 0
        if type_id:
            c.execute("SELECT * FROM cr_doc_types WHERE id=? FOR UPDATE", (type_id,))
            row = c.fetchone()
            if not row:
                return {"error": "doc_type_not_found", "message": "Тип документа не найден."}
            doc_type = dict(row)
        if payload.get("random"):
            number = f"{(doc_type or {}).get('prefix') or ''}{random.randint(100000, 999999)}"
        elif doc_type and (not number or number == format_contract_number(doc_type, _int(doc_type["counter"]) + 1)):
            seq_no = _int(doc_type["counter"]) + 1
            number = format_contract_number(doc_type, seq_no)
            c.execute("UPDATE cr_doc_types SET counter=?, updated_at=? WHERE id=?", (seq_no, now, type_id))
        if not number:
            return {"error": "number_required", "message": "Выбери тип документа или укажи номер."}
        c.execute(
            """
            INSERT INTO cr_contracts (doc_type_id, folder_id, number, seq_no, created_date, currency, kind, vat_rate, responsible, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'RUB', 'other', 20, ?, ?, ?, ?, ?)
            """,
            (type_id, _int(payload.get("folder_id")), number, seq_no, datetime.date.today().isoformat(), _text(actor.get("name"), 200), actor.get("email", ""), actor.get("email", ""), now, now),
        )
        contract_id = c.lastrowid
        if doc_type and _int(doc_type.get("counterparty_id")):
            c.execute(
                "INSERT INTO cr_contract_parties (contract_id, counterparty_id, role, auto_mailing, created_at) VALUES (?, ?, ?, 0, ?)",
                (contract_id, doc_type["counterparty_id"], "Наша организация", now),
            )
        conn.commit()
    finally:
        conn.close()
    audit_log("cr_contract_created", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="cr_contract", entity_id=str(contract_id), details={"number": number})
    return {"status": "success", "id": contract_id, "number": number}


@router.get("/api/cr/contracts/{contract_id}")
def get_contract(contract_id: int, request: Request):
    if not _actor(request):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        contract = _load_contract(c, contract_id)
        if not contract:
            return {"error": "not_found"}
        c.execute(
            """
            SELECT pp.*, p.name, p.short_name, p.inn, p.kpp
            FROM cr_contract_parties pp JOIN cr_counterparties p ON p.id = pp.counterparty_id
            WHERE pp.contract_id=? ORDER BY pp.id
            """,
            (contract_id,),
        )
        contract["parties"] = _rows(c)
        c.execute("SELECT * FROM cr_approvals WHERE contract_id=? ORDER BY id", (contract_id,))
        contract["approvals"] = _rows(c)
        c.execute("SELECT * FROM cr_contract_files WHERE contract_id=? ORDER BY id DESC", (contract_id,))
        contract["files"] = _rows(c)
    finally:
        conn.close()
    contract["flags"] = contract_flags(contract, contract["approvals"])
    return contract


@router.put("/api/cr/contracts/{contract_id}")
def update_contract(contract_id: int, request: Request, payload: dict = Body(...)):
    actor = _actor(request, "update")
    if not actor:
        return {"error": "forbidden"}
    values = {}
    for key, raw in payload.items():
        if key in DATE_FIELDS:
            values[key] = _date(raw)
        elif key in CONTRACT_TEXT_FIELDS:
            values[key] = _text(raw)
        elif key in CONTRACT_INT_FIELDS:
            values[key] = _int(raw)
        elif key in CONTRACT_REAL_FIELDS:
            values[key] = _real(raw)
    if "kind" in values and values["kind"] not in KINDS:
        values["kind"] = "other"
    if "number" in values and not values["number"]:
        return {"error": "number_required", "message": "Номер договора не может быть пустым."}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        current = _load_contract(c, contract_id)
        if not current:
            return {"error": "not_found"}
        merged = {**current, **values}
        if _int(merged.get("vat_enabled")) and not _int(merged.get("vat_manual")):
            values["vat_amount"] = _vat(_real(merged.get("amount")), _real(merged.get("vat_rate")))
        values["updated_by"] = actor.get("email", "")
        values["updated_at"] = int(time.time())
        assignments = ", ".join(f"{key}=?" for key in values)
        c.execute(f"UPDATE cr_contracts SET {assignments} WHERE id=?", (*values.values(), contract_id))
        conn.commit()
        contract = _load_contract(c, contract_id)
    finally:
        conn.close()
    return {"status": "success", "contract": contract}


@router.delete("/api/cr/contracts/{contract_id}")
def delete_contract(contract_id: int, request: Request):
    actor = _actor(request, "update")
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        conn.execute("UPDATE cr_contracts SET is_deleted=1, updated_at=?, updated_by=? WHERE id=?", (int(time.time()), actor.get("email", ""), contract_id))
        conn.commit()
    finally:
        conn.close()
    audit_log("cr_contract_deleted", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="cr_contract", entity_id=str(contract_id))
    return {"status": "success"}


@router.post("/api/cr/contracts/{contract_id}/restore")
def restore_contract(contract_id: int, request: Request):
    actor = _actor(request, "update")
    if not actor:
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        conn.execute("UPDATE cr_contracts SET is_deleted=0, updated_at=?, updated_by=? WHERE id=?", (int(time.time()), actor.get("email", ""), contract_id))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


@router.post("/api/cr/contracts/{contract_id}/copy")
def copy_contract(contract_id: int, request: Request):
    actor = _actor(request, "create")
    if not actor:
        return {"error": "forbidden"}
    now = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        source = _load_contract(c, contract_id)
        if not source:
            return {"error": "not_found"}
        skip = {"id", "doc_type_name", "folder_name", "amount_without_vat", "is_deleted", "created_at", "updated_at", "created_by", "updated_by", "seq_no", "signed", "signed_date"}
        data = {k: v for k, v in source.items() if k not in skip}
        data.update(number=f"{source['number']} (копия)", created_date=datetime.date.today().isoformat(), created_by=actor.get("email", ""), updated_by=actor.get("email", ""), created_at=now, updated_at=now)
        c.execute(f"INSERT INTO cr_contracts ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})", tuple(data.values()))
        new_id = c.lastrowid
        c.execute(
            "INSERT INTO cr_contract_parties (contract_id, counterparty_id, role, auto_mailing, created_at) SELECT ?, counterparty_id, role, auto_mailing, ? FROM cr_contract_parties WHERE contract_id=?",
            (new_id, now, contract_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "id": new_id}


# ---------- parties ----------

@router.post("/api/cr/contracts/{contract_id}/parties")
def add_party(contract_id: int, request: Request, payload: dict = Body(...)):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    counterparty_id = _int(payload.get("counterparty_id"))
    if not counterparty_id:
        return {"error": "counterparty_required", "message": "Выбери контрагента."}
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO cr_contract_parties (contract_id, counterparty_id, role, auto_mailing, created_at) VALUES (?, ?, ?, ?, ?)",
            (contract_id, counterparty_id, _text(payload.get("role"), 120), 1 if _int(payload.get("auto_mailing")) else 0, int(time.time())),
        )
        party_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "id": party_id}


@router.put("/api/cr/parties/{party_id}")
def update_party(party_id: int, request: Request, payload: dict = Body(...)):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE cr_contract_parties SET role=?, auto_mailing=? WHERE id=?",
            (_text(payload.get("role"), 120), 1 if _int(payload.get("auto_mailing")) else 0, party_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


@router.delete("/api/cr/parties/{party_id}")
def delete_party(party_id: int, request: Request):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        conn.execute("DELETE FROM cr_contract_parties WHERE id=?", (party_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


# ---------- approvals ----------

@router.post("/api/cr/contracts/{contract_id}/approvals")
def add_approval(contract_id: int, request: Request, payload: dict = Body(...)):
    actor = _actor(request, "update")
    if not actor:
        return {"error": "forbidden"}
    approver = _text(payload.get("approver"), 200)
    if not approver:
        return {"error": "approver_required", "message": "Укажи согласующего."}
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO cr_approvals (contract_id, approver, department, position, status, due_date, comment, created_by, created_at) VALUES (?, ?, ?, ?, 'pending', ?, '', ?, ?)",
            (contract_id, approver, _text(payload.get("department"), 200), _text(payload.get("position"), 200), _date(payload.get("due_date")), actor.get("email", ""), int(time.time())),
        )
        approval_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "id": approval_id}


@router.put("/api/cr/approvals/{approval_id}")
def decide_approval(approval_id: int, request: Request, payload: dict = Body(...)):
    actor = _actor(request, "update")
    if not actor:
        return {"error": "forbidden"}
    status = _text(payload.get("status"), 40)
    if status not in APPROVAL_STATUSES:
        return {"error": "invalid_status"}
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE cr_approvals SET status=?, comment=?, decided_at=? WHERE id=?",
            (status, _text(payload.get("comment"), 2000), 0 if status == "pending" else int(time.time()), approval_id),
        )
        conn.commit()
    finally:
        conn.close()
    audit_log("cr_approval_decided", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="cr_approval", entity_id=str(approval_id), details={"status": status})
    return {"status": "success"}


@router.delete("/api/cr/approvals/{approval_id}")
def delete_approval(approval_id: int, request: Request):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    conn = get_connection()
    try:
        conn.execute("DELETE FROM cr_approvals WHERE id=?", (approval_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


# ---------- files ----------

@router.post("/api/cr/contracts/{contract_id}/files")
async def upload_contract_file(contract_id: int, request: Request, file: UploadFile = File(...)):
    actor = _actor(request, "update")
    if not actor:
        return {"error": "forbidden"}
    data = await file.read()
    if not data:
        return {"error": "empty_file", "message": "Файл пустой."}
    if len(data) > MAX_FILE_BYTES:
        return {"error": "file_too_large", "message": "Файл больше 25 МБ."}
    original = os.path.basename(file.filename or "file")[:180] or "file"
    safe = re.sub(r"[^\w.\-]+", "_", original, flags=re.UNICODE).strip("._") or "file"
    folder = os.path.join(FILES_DIR, str(contract_id))
    os.makedirs(folder, exist_ok=True)
    stored = f"{secrets.token_hex(6)}_{safe}"
    with open(os.path.join(folder, stored), "wb") as handle:
        handle.write(data)
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO cr_contract_files (contract_id, filename, file_url, size_bytes, uploaded_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (contract_id, original, f"/uploads/contract_registry/{contract_id}/{stored}", len(data), actor.get("name") or actor.get("email", ""), int(time.time())),
        )
        file_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "id": file_id}


@router.delete("/api/cr/files/{file_id}")
def delete_contract_file(file_id: int, request: Request):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        row = conn.execute("SELECT file_url FROM cr_contract_files WHERE id=?", (file_id,)).fetchone()
        conn.execute("DELETE FROM cr_contract_files WHERE id=?", (file_id,))
        conn.commit()
    finally:
        conn.close()
    if row and str(row["file_url"]).startswith("/uploads/contract_registry/"):
        path = os.path.normpath(os.path.join(BASE_DIR, row["file_url"].lstrip("/")))
        if path.startswith(FILES_DIR) and os.path.isfile(path):
            os.remove(path)
    return {"status": "success"}


# ---------- counterparties ----------

def _counterparty_values(payload: dict) -> dict:
    values = {key: _text(payload.get(key), 1000) for key in COUNTERPARTY_FIELDS}
    values["inn"] = re.sub(r"\D+", "", values["inn"])[:12]
    values["is_own"] = 1 if _int(payload.get("is_own")) else 0
    return values


@router.get("/api/cr/counterparties")
def list_counterparties(request: Request, q: str = ""):
    if not _actor(request):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT p.*, (SELECT COUNT(DISTINCT pp.contract_id) FROM cr_contract_parties pp JOIN cr_contracts k ON k.id = pp.contract_id AND k.is_deleted=0 WHERE pp.counterparty_id = p.id) AS contracts_count
            FROM cr_counterparties p ORDER BY p.is_own DESC, p.name
            """
        )
        items = _rows(c)
    finally:
        conn.close()
    needle = _text(q, 200).lower()
    if needle:
        items = [item for item in items if needle in f"{item['name']} {item['short_name']} {item['inn']} {item['ogrn']}".lower()]
    return items


@router.get("/api/cr/counterparties/lookup")
def lookup_counterparty(request: Request, inn: str = ""):
    if not _actor(request):
        return {"error": "forbidden"}
    result = _lookup_company_by_inn(inn)
    if result.get("status") == "integration_not_configured":
        return {"error": "integration_not_configured", "message": "Поиск по ИНН ещё не подключён. Заполни карточку вручную — сервис подключим позже."}
    messages = {"inn_required": "Введи ИНН.", "inn_invalid": "ИНН должен содержать 10 или 12 цифр.", "not_found": "Организация с таким ИНН не найдена."}
    if result.get("error"):
        return {"error": result["error"], "message": messages.get(result["error"], "Сервис поиска по ИНН не ответил. Попробуй позже.")}
    client = result["client"]
    return {
        "status": "success",
        "counterparty": {
            "name": client.get("name", ""),
            "short_name": client.get("name", ""),
            "inn": client.get("inn", ""),
            "kpp": client.get("kpp", ""),
            "ogrn": client.get("ogrn", ""),
            "legal_address": client.get("legal_address", ""),
            "director": client.get("contact", ""),
            "status": client.get("status", ""),
        },
    }


@router.post("/api/cr/counterparties")
def create_counterparty(request: Request, payload: dict = Body(...)):
    actor = _actor(request, "create")
    if not actor:
        return {"error": "forbidden"}
    values = _counterparty_values(payload)
    if not values["name"]:
        return {"error": "name_required", "message": "Укажи наименование контрагента."}
    if values["inn"] and len(values["inn"]) not in (10, 12):
        return {"error": "inn_invalid", "message": "ИНН должен содержать 10 или 12 цифр."}
    now = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        if values["inn"]:
            existing = c.execute("SELECT id FROM cr_counterparties WHERE inn=? AND kpp=?", (values["inn"], values["kpp"])).fetchone()
            if existing:
                return {"error": "duplicate", "message": "Контрагент с таким ИНН и КПП уже есть.", "id": existing["id"]}
        values.update(created_by=actor.get("email", ""), created_at=now, updated_at=now)
        c.execute(f"INSERT INTO cr_counterparties ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", tuple(values.values()))
        counterparty_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "id": counterparty_id}


@router.put("/api/cr/counterparties/{counterparty_id}")
def update_counterparty(counterparty_id: int, request: Request, payload: dict = Body(...)):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    values = _counterparty_values(payload)
    if not values["name"]:
        return {"error": "name_required", "message": "Укажи наименование контрагента."}
    if values["inn"] and len(values["inn"]) not in (10, 12):
        return {"error": "inn_invalid", "message": "ИНН должен содержать 10 или 12 цифр."}
    values["updated_at"] = int(time.time())
    conn = get_connection()
    try:
        conn.execute(f"UPDATE cr_counterparties SET {', '.join(f'{k}=?' for k in values)} WHERE id=?", (*values.values(), counterparty_id))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}


@router.delete("/api/cr/counterparties/{counterparty_id}")
def delete_counterparty(counterparty_id: int, request: Request):
    if not _actor(request, "update"):
        return {"error": "forbidden"}
    conn = get_connection(row_factory=True)
    try:
        used = conn.execute("SELECT COUNT(*) AS n FROM cr_contract_parties WHERE counterparty_id=?", (counterparty_id,)).fetchone()["n"]
        if used:
            return {"error": "in_use", "message": f"Контрагент указан в {used} договорах, удалить нельзя."}
        conn.execute("DELETE FROM cr_counterparties WHERE id=?", (counterparty_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "success"}
