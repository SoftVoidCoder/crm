import base64
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import time

from database import get_connection


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
SIGNATURE_UPLOADS_DIR = os.path.join(UPLOADS_DIR, "signatures")


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
    try:
        return dict(row)
    except Exception:
        return {}


def _load_json(raw_value, default):
    if not raw_value:
        return default
    try:
        data = json.loads(raw_value)
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def _today_protocol_number(prefix: str, record_id: int) -> str:
    return f"{prefix}-{datetime.datetime.now().strftime('%Y%m%d')}-{int(record_id or 0)}"


def _parse_display_datetime(value: str) -> datetime.datetime | None:
    raw = _safe_text(value)
    if not raw:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def _signature_legal_force(signature_kind: str) -> str:
    raw = _safe_text(signature_kind).lower()
    if any(token in raw for token in ("кэп", "укэп", "qualified")):
        return "qualified"
    if any(token in raw for token in ("нэп", "унэп", "enhanced", "unqualified")):
        return "enhanced"
    return "simple"


def _certificate_status_snapshot(certificate: dict) -> tuple[str, str]:
    if not certificate:
        return "missing_certificate", "Сертификат не найден"
    if _safe_int(certificate.get("revoked_at")) or _safe_text(certificate.get("status")).lower() in {"revoked", "blocked"}:
        return "revoked", "Сертификат отозван или заблокирован"
    now_dt = datetime.datetime.now()
    grace_days = max(1, _safe_int(os.getenv("KORDA_CERTIFICATE_GRACE_DAYS") or 365))
    valid_from = _parse_display_datetime(certificate.get("valid_from", ""))
    valid_to = _parse_display_datetime(certificate.get("valid_to", ""))
    if valid_from and now_dt < valid_from:
        return "not_active_yet", "Сертификат еще не вступил в силу"
    if valid_to and now_dt > valid_to + datetime.timedelta(days=grace_days):
        return "expired", "Срок действия сертификата истек"
    if _safe_text(certificate.get("status")).lower() not in {"", "active", "issued", "valid"}:
        return "inactive", "Сертификат неактивен"
    return "valid", "Сертификат действителен"


def _certificate_owned_by_actor(certificate: dict, actor: dict, signer_name: str = "") -> bool:
    owner_email = _safe_text(certificate.get("owner_email"))
    owner_name = _safe_text(certificate.get("owner_name"))
    actor_email = _safe_text(actor.get("email"))
    actor_name = _safe_text(actor.get("name"))
    signer_name = _safe_text(signer_name)
    if owner_email and owner_email == actor_email:
        return True
    if owner_name and owner_name in {actor_name, signer_name}:
        return True
    return not owner_email and not owner_name


def _resolve_certificate(cursor, data: dict, actor: dict) -> dict:
    certificate_id = _safe_int(data.get("certificate_id"))
    thumbprint = _safe_text(data.get("certificate_thumbprint"))
    if certificate_id:
        return _row_dict(cursor.execute("SELECT * FROM edo_certificates WHERE id=?", (certificate_id,)).fetchone())
    if thumbprint:
        return _row_dict(cursor.execute("SELECT * FROM edo_certificates WHERE thumbprint=? ORDER BY updated_at DESC, id DESC LIMIT 1", (thumbprint,)).fetchone())
    return _row_dict(cursor.execute("SELECT * FROM edo_certificates WHERE owner_email=? ORDER BY updated_at DESC, id DESC LIMIT 1", (_safe_text(actor.get("email")),)).fetchone())


def _resolve_document_revision(cursor, document_id: int, file_revision_id: int = 0) -> dict:
    if file_revision_id:
        return _row_dict(
            cursor.execute(
                "SELECT * FROM document_file_revisions WHERE id=? AND document_id=?",
                (int(file_revision_id or 0), int(document_id or 0)),
            ).fetchone()
        )
    return _row_dict(
        cursor.execute(
            """
            SELECT *
            FROM document_file_revisions
            WHERE document_id=?
            ORDER BY is_current DESC, revision_no DESC, uploaded_at DESC, id DESC
            LIMIT 1
            """,
            (int(document_id or 0),),
        ).fetchone()
    )


def _current_revision(cursor, document_id: int) -> dict:
    return _row_dict(
        cursor.execute(
            """
            SELECT *
            FROM document_file_revisions
            WHERE document_id=? AND is_current=1
            ORDER BY revision_no DESC, id DESC
            LIMIT 1
            """,
            (int(document_id or 0),),
        ).fetchone()
    )


def _file_path_from_revision(revision: dict) -> str:
    stored = _safe_text(revision.get("stored_filename"))
    if stored:
        return os.path.join(UPLOADS_DIR, stored)
    file_url = _safe_text(revision.get("file_url"))
    if file_url.startswith("/uploads/"):
        return os.path.join(BASE_DIR, file_url.lstrip("/"))
    return ""


def _signature_payload(document: dict, revision: dict, certificate: dict, data: dict) -> dict:
    return {
        "payload_version": 1,
        "signature_format": _safe_text(data.get("signature_format")) or "CAdES detached",
        "document_id": _safe_int(document.get("id")),
        "document_number": _safe_text(document.get("number")),
        "document_subject": _safe_text(document.get("subject")),
        "file_revision_id": _safe_int(revision.get("id")),
        "revision_label": _safe_text(revision.get("revision_label")),
        "original_filename": _safe_text(revision.get("original_filename")),
        "checksum_algorithm": "SHA-256",
        "checksum": _safe_text(revision.get("checksum")),
        "certificate_id": _safe_int(certificate.get("id")),
        "certificate_thumbprint": _safe_text(certificate.get("thumbprint")),
        "signer_name": _safe_text(data.get("signer_name")) or _safe_text(certificate.get("owner_name")),
        "signer_role": _safe_text(data.get("signer_role")) or _safe_text(certificate.get("signer_role")),
        "created_at": int(time.time()),
    }


def _parse_detached_signature(signature_bytes: bytes) -> dict:
    text = ""
    try:
        text = (signature_bytes or b"").decode("utf-8").strip()
    except Exception:
        text = ""
    if text:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {
        "raw_base64": base64.b64encode(signature_bytes or b"").decode("ascii"),
        "raw_text": text,
    }


def _cryptopro_bin() -> str:
    configured = _safe_text(os.getenv("KORDA_CRYPTCP_BIN")) or _safe_text(os.getenv("CRYPTCP_BIN"))
    if configured:
        return configured
    return shutil.which("cryptcp") or ""


def _tool_version(command: list[str], timeout: int = 8) -> dict:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        return {"ok": completed.returncode == 0, "returncode": completed.returncode, "output": output[:2000]}
    except Exception as exc:
        return {"ok": False, "returncode": -1, "output": str(exc)}


def crypto_runtime_status() -> dict:
    cryptcp = _cryptopro_bin()
    csptest = _safe_text(os.getenv("KORDA_CSPTEST_BIN")) or shutil.which("csptest") or ""
    timeout = max(5, _safe_int(os.getenv("KORDA_CRYPTCP_TIMEOUT") or 30))
    cryptcp_version = _tool_version([cryptcp, "-version"], timeout=timeout) if cryptcp else {"ok": False, "output": "cryptcp не найден"}
    if cryptcp and not cryptcp_version.get("ok"):
        cryptcp_version = _tool_version([cryptcp, "--version"], timeout=timeout)
    csptest_version = _tool_version([csptest, "-keyset", "-enum_cont", "-verifycontext"], timeout=timeout) if csptest else {"ok": False, "output": "csptest не найден"}
    return {
        "status": "success",
        "ready": bool(cryptcp),
        "cryptcp": {
            "available": bool(cryptcp),
            "path": cryptcp,
            "version_check": cryptcp_version,
        },
        "csptest": {
            "available": bool(csptest),
            "path": csptest,
            "version_check": csptest_version,
        },
        "env": {
            "KORDA_CRYPTCP_BIN": bool(os.getenv("KORDA_CRYPTCP_BIN")),
            "CRYPTCP_BIN": bool(os.getenv("CRYPTCP_BIN")),
            "KORDA_CSPTEST_BIN": bool(os.getenv("KORDA_CSPTEST_BIN")),
        },
        "message": "CryptoPro runtime найден" if cryptcp else "CryptoPro cryptcp не найден: задайте KORDA_CRYPTCP_BIN/CRYPTCP_BIN или установите CryptoPro CSP.",
    }


def _run_cryptopro_verification(revision: dict, signature_path: str) -> dict:
    cryptcp = _cryptopro_bin()
    file_path = _file_path_from_revision(revision)
    if not cryptcp or not file_path or not os.path.exists(file_path) or not signature_path or not os.path.exists(signature_path):
        return {"available": False}
    timeout = max(5, _safe_int(os.getenv("KORDA_CRYPTCP_TIMEOUT") or 30))
    commands = [
        [cryptcp, "-verify", "-detached", "-der", signature_path, file_path],
        [cryptcp, "-verify", "-detached", signature_path, file_path],
    ]
    for command in commands:
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except Exception as exc:
            return {"available": True, "ok": False, "message": str(exc), "command": command}
        output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        if completed.returncode == 0:
            return {"available": True, "ok": True, "message": "CryptoPro/CAdES проверка выполнена", "output": output, "command": command}
    return {"available": True, "ok": False, "message": output or "CryptoPro/CAdES проверка не пройдена", "output": output, "command": commands[-1]}


def _local_detached_verification(session: dict, revision: dict, certificate: dict, signature_bytes: bytes, signature_path: str) -> dict:
    signature_payload = _parse_detached_signature(signature_bytes)
    certificate_status, certificate_message = _certificate_status_snapshot(certificate)
    current_checksum = _safe_text(revision.get("checksum"))
    signed_checksum = (
        _safe_text(signature_payload.get("document_checksum"))
        or _safe_text(signature_payload.get("checksum"))
        or _safe_text(signature_payload.get("revision_checksum"))
        or _safe_text(session.get("revision_checksum"))
    )
    payload_thumbprint = _safe_text(signature_payload.get("certificate_thumbprint")) or _safe_text(certificate.get("thumbprint"))
    ocsp_status = _safe_text(signature_payload.get("ocsp_status")) or ("revoked" if certificate_status == "revoked" else "good")
    crl_status = _safe_text(signature_payload.get("crl_status")) or ("revoked" if certificate_status == "revoked" else "clear")
    time_stamp_status = _safe_text(signature_payload.get("timestamp_status")) or ("present" if signature_payload.get("timestamp") else "not_provided")
    checks = {
        "certificate": {"status": certificate_status, "message": certificate_message},
        "detached_signature": {"status": "present" if signature_bytes else "missing", "sha256": hashlib.sha256(signature_bytes or b"").hexdigest()},
        "checksum_binding": {"expected": current_checksum, "signed": signed_checksum},
        "certificate_thumbprint": {"expected": _safe_text(certificate.get("thumbprint")), "signed": payload_thumbprint},
        "time_stamp": {"status": time_stamp_status, "value": _safe_text(signature_payload.get("timestamp"))},
        "ocsp": {"status": ocsp_status},
        "crl": {"status": crl_status},
        "cryptopro": _run_cryptopro_verification(revision, signature_path),
        "signature_payload": signature_payload,
    }
    if certificate_status != "valid":
        return {
            "status": certificate_status,
            "message": certificate_message,
            "checks": checks,
            "ocsp_status": ocsp_status,
            "crl_status": crl_status,
            "time_stamp_status": time_stamp_status,
        }
    if not signature_bytes:
        return {"status": "signature_missing", "message": "Detached .sig не загружен", "checks": checks, "ocsp_status": ocsp_status, "crl_status": crl_status, "time_stamp_status": time_stamp_status}
    if not current_checksum or not signed_checksum or current_checksum != signed_checksum:
        return {
            "status": "hash_mismatch",
            "message": "Detached подпись не покрывает checksum выбранной версии файла",
            "checks": checks,
            "ocsp_status": ocsp_status,
            "crl_status": crl_status,
            "time_stamp_status": time_stamp_status,
        }
    if payload_thumbprint and _safe_text(certificate.get("thumbprint")) and payload_thumbprint != _safe_text(certificate.get("thumbprint")):
        return {
            "status": "certificate_mismatch",
            "message": "Отпечаток сертификата в подписи не совпадает с выбранным сертификатом",
            "checks": checks,
            "ocsp_status": ocsp_status,
            "crl_status": crl_status,
            "time_stamp_status": time_stamp_status,
        }
    cryptopro = checks.get("cryptopro") or {}
    if cryptopro.get("available") and not cryptopro.get("ok"):
        return {
            "status": "invalid",
            "message": cryptopro.get("message") or "CryptoPro/CAdES проверка не пройдена",
            "checks": checks,
            "ocsp_status": ocsp_status,
            "crl_status": crl_status,
            "time_stamp_status": time_stamp_status,
        }
    if ocsp_status in {"revoked", "bad"} or crl_status in {"revoked", "bad"}:
        return {
            "status": "revoked",
            "message": "OCSP/CRL сообщает об отзыве сертификата",
            "checks": checks,
            "ocsp_status": ocsp_status,
            "crl_status": crl_status,
            "time_stamp_status": time_stamp_status,
        }
    return {
        "status": "valid",
        "message": "Detached подпись подтверждена и строго связана с checksum версии файла",
        "checks": checks,
        "ocsp_status": ocsp_status,
        "crl_status": crl_status,
        "time_stamp_status": time_stamp_status,
    }


def _build_stamp(document: dict, revision: dict, certificate: dict, session: dict) -> dict:
    thumbprint = _safe_text(certificate.get("thumbprint")) or _safe_text(session.get("certificate_thumbprint"))
    return {
        "stamp_label": f"{_safe_text(session.get('signature_kind')) or 'ЭП'} подписан",
        "document_number": _safe_text(document.get("number")) or f"#{_safe_int(document.get('id'))}",
        "document_subject": _safe_text(document.get("subject")),
        "revision_label": _safe_text(revision.get("revision_label")) or f"file-v{_safe_int(revision.get('revision_no'))}",
        "original_filename": _safe_text(revision.get("original_filename")),
        "checksum": _safe_text(revision.get("checksum")),
        "signer_name": _safe_text(session.get("signer_name")) or _safe_text(certificate.get("owner_name")),
        "signer_role": _safe_text(session.get("signer_role")) or _safe_text(certificate.get("signer_role")),
        "signed_at": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
        "provider": _safe_text(session.get("signature_provider")) or "КриптоПро",
        "signature_format": _safe_text(session.get("signature_format")) or "CAdES detached",
        "certificate_id": _safe_int(certificate.get("id")),
        "thumbprint": thumbprint,
        "thumbprint_short": thumbprint[:12],
        "serial_number": _safe_text(certificate.get("serial_number")),
        "valid_to": _safe_text(certificate.get("valid_to")),
        "legal_force": _signature_legal_force(session.get("signature_kind")),
    }


def _insert_protocol(cursor, session: dict, signature_id: int, verification: dict, actor: dict, override: dict | None = None) -> dict:
    override = override or {}
    now = int(time.time())
    checks = override.get("checks") if isinstance(override.get("checks"), dict) else verification.get("checks", {})
    raw_protocol = override.get("raw_protocol") if isinstance(override.get("raw_protocol"), dict) else {
        "generated_by": "korda.crypto_signature_service",
        "result": verification.get("status"),
        "message": verification.get("message"),
    }
    protocol_status = _safe_text(override.get("protocol_status")) or ("valid" if verification.get("status") == "valid" else "invalid")
    validation_result = _safe_text(override.get("validation_result")) or _safe_text(verification.get("status"))
    validation_message = _safe_text(override.get("validation_message")) or _safe_text(verification.get("message"))
    cursor.execute(
        """
        INSERT INTO signature_validation_protocols (
            session_id, signature_id, document_id, file_revision_id, revision_checksum, protocol_status,
            protocol_number, validation_result, validation_message, provider, checks_json, raw_protocol_json,
            attached_file_url, attached_file_checksum, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _safe_int(session.get("id")),
            int(signature_id or 0),
            _safe_int(session.get("document_id")),
            _safe_int(session.get("file_revision_id")),
            _safe_text(session.get("revision_checksum")),
            protocol_status,
            _safe_text(override.get("protocol_number")) or _today_protocol_number("SIG-PROTOCOL", _safe_int(session.get("id"))),
            validation_result,
            validation_message,
            _safe_text(override.get("provider")) or _safe_text(session.get("signature_provider")) or "КриптоПро",
            json.dumps(checks or {}, ensure_ascii=False),
            json.dumps(raw_protocol or {}, ensure_ascii=False),
            _safe_text(override.get("attached_file_url")),
            _safe_text(override.get("attached_file_checksum")),
            _safe_text(actor.get("email")),
            now,
        ),
    )
    protocol_id = int(cursor.lastrowid or 0)
    return {
        "id": protocol_id,
        "protocol_status": protocol_status,
        "protocol_number": _safe_text(override.get("protocol_number")) or _today_protocol_number("SIG-PROTOCOL", _safe_int(session.get("id"))),
        "validation_result": validation_result,
        "validation_message": validation_message,
    }


def _upsert_signature_registry(cursor, document: dict, revision: dict, certificate: dict, session: dict, verification: dict, protocol_id: int, actor: dict) -> int:
    now = int(time.time())
    legal_force = _signature_legal_force(session.get("signature_kind"))
    stamp = _build_stamp(document, revision, certificate, session)
    verification_details = dict(verification.get("checks") or {})
    verification_details["validation_protocol_id"] = int(protocol_id or 0)
    cursor.execute(
        """
        INSERT INTO edo_signature_registry (
            entity_type, entity_id, signer_name, signer_role, certificate_thumbprint, signature_provider,
            signature_status, signed_at, comment, created_by, created_at, certificate_id, document_revision_id,
            signature_kind, verification_status, verification_message, stamp_json, signed_hash, verification_details,
            revoked_at, legal_force, signature_session_id, validation_protocol_id, detached_signature_url,
            detached_signature_checksum, signature_format, time_stamp_status, ocsp_status, crl_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "document",
            _safe_int(document.get("id")),
            _safe_text(session.get("signer_name")) or _safe_text(certificate.get("owner_name")),
            _safe_text(session.get("signer_role")) or _safe_text(certificate.get("signer_role")),
            _safe_text(certificate.get("thumbprint")),
            _safe_text(session.get("signature_provider")) or "КриптоПро",
            "verified" if verification.get("status") == "valid" else "invalid",
            datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
            _safe_text(session.get("comment")),
            _safe_text(actor.get("email")),
            now,
            _safe_int(certificate.get("id")),
            _safe_int(revision.get("id")),
            _safe_text(session.get("signature_kind")) or "КЭП",
            _safe_text(verification.get("status")),
            _safe_text(verification.get("message")),
            json.dumps(stamp, ensure_ascii=False),
            _safe_text(revision.get("checksum")),
            json.dumps(verification_details, ensure_ascii=False),
            legal_force,
            _safe_int(session.get("id")),
            int(protocol_id or 0),
            _safe_text(session.get("detached_signature_url")),
            _safe_text(session.get("detached_signature_checksum")),
            _safe_text(session.get("signature_format")) or "CAdES detached",
            _safe_text(verification.get("time_stamp_status")),
            _safe_text(verification.get("ocsp_status")),
            _safe_text(verification.get("crl_status")),
        ),
    )
    return int(cursor.lastrowid or 0)


def begin_signature_session(document_id: int, data: dict, actor: dict) -> dict:
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        document = _row_dict(cursor.execute("SELECT * FROM documents WHERE id=?", (int(document_id or 0),)).fetchone())
        if not document:
            return {"error": "document_not_found"}
        revision = _resolve_document_revision(cursor, document_id, _safe_int(data.get("file_revision_id")))
        if not revision:
            return {"error": "document_file_revision_required"}
        certificate = _resolve_certificate(cursor, data, actor)
        if not certificate:
            return {"error": "certificate_not_found"}
        if not _certificate_owned_by_actor(certificate, actor, data.get("signer_name", "")):
            return {"error": "certificate_owner_mismatch"}
        certificate_status, certificate_message = _certificate_status_snapshot(certificate)
        if certificate_status != "valid":
            return {"error": certificate_status, "message": certificate_message}
        signing_payload = _signature_payload(document, revision, certificate, data)
        now = int(time.time())
        cursor.execute(
            """
            INSERT INTO signature_sessions (
                document_id, file_revision_id, revision_checksum, certificate_id, certificate_thumbprint,
                signer_name, signer_role, signature_kind, signature_provider, signature_format, status,
                certificate_status, signing_payload_json, comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, ?, ?, ?, ?, ?)
            """,
            (
                int(document_id or 0),
                _safe_int(revision.get("id")),
                _safe_text(revision.get("checksum")),
                _safe_int(certificate.get("id")),
                _safe_text(certificate.get("thumbprint")),
                _safe_text(data.get("signer_name")) or _safe_text(certificate.get("owner_name")) or _safe_text(actor.get("name")),
                _safe_text(data.get("signer_role")) or _safe_text(certificate.get("signer_role")) or _safe_text(actor.get("role")),
                _safe_text(data.get("signature_kind")) or "КЭП",
                _safe_text(data.get("signature_provider")) or "КриптоПро",
                _safe_text(data.get("signature_format")) or "CAdES detached",
                certificate_status,
                json.dumps(signing_payload, ensure_ascii=False),
                _safe_text(data.get("comment")),
                _safe_text(actor.get("email")),
                now,
                now,
            ),
        )
        session_id = int(cursor.lastrowid or 0)
        conn.commit()
        return {
            "status": "success",
            "session_id": session_id,
            "session": get_signature_session(session_id),
            "signing_payload": signing_payload,
        }
    finally:
        conn.close()


def get_signature_session(session_id: int) -> dict:
    conn = get_connection(row_factory=True)
    try:
        row = _row_dict(conn.execute("SELECT * FROM signature_sessions WHERE id=?", (int(session_id or 0),)).fetchone())
        if not row:
            return {}
        row["signing_payload"] = _load_json(row.get("signing_payload_json"), {})
        return row
    finally:
        conn.close()


def list_document_signature_sessions(document_id: int) -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM signature_sessions WHERE document_id=? ORDER BY created_at DESC, id DESC",
                (int(document_id or 0),),
            ).fetchall()
        ]
        for row in rows:
            row["signing_payload"] = _load_json(row.get("signing_payload_json"), {})
        return rows
    finally:
        conn.close()


def list_document_signature_protocols(document_id: int) -> list[dict]:
    conn = get_connection(row_factory=True)
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM signature_validation_protocols WHERE document_id=? ORDER BY created_at DESC, id DESC",
                (int(document_id or 0),),
            ).fetchall()
        ]
        for row in rows:
            row["checks"] = _load_json(row.get("checks_json"), {})
            row["raw_protocol"] = _load_json(row.get("raw_protocol_json"), {})
        return rows
    finally:
        conn.close()


def attach_detached_signature(session_id: int, filename: str, signature_bytes: bytes, actor: dict, comment: str = "") -> dict:
    session = get_signature_session(session_id)
    if not session:
        return {"error": "signature_session_not_found"}
    os.makedirs(SIGNATURE_UPLOADS_DIR, exist_ok=True)
    safe_name = os.path.basename(_safe_text(filename)) or f"signature_{int(session_id or 0)}.sig"
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in safe_name).strip("._") or "detached.sig"
    stored_name = f"{int(time.time())}_session_{int(session_id or 0)}_{safe_name[:100]}"
    disk_path = os.path.join(SIGNATURE_UPLOADS_DIR, stored_name)
    with open(disk_path, "wb") as buffer:
        buffer.write(signature_bytes or b"")
    signature_checksum = hashlib.sha256(signature_bytes or b"").hexdigest()
    signature_url = f"/uploads/signatures/{stored_name}"
    now = int(time.time())
    conn = get_connection(row_factory=True)
    try:
        conn.execute(
            """
            UPDATE signature_sessions
            SET status='signature_uploaded', detached_signature_filename=?, detached_signature_url=?,
                detached_signature_checksum=?, comment=?, updated_at=?
            WHERE id=?
            """,
            (safe_name, signature_url, signature_checksum, _safe_text(comment) or _safe_text(session.get("comment")), now, int(session_id or 0)),
        )
        conn.commit()
    finally:
        conn.close()
    updated = get_signature_session(session_id)
    return {"status": "success", "session": updated}


def verify_signature_session(session_id: int, actor: dict, force: int = 0, protocol_override: dict | None = None) -> dict:
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        session = _row_dict(cursor.execute("SELECT * FROM signature_sessions WHERE id=?", (int(session_id or 0),)).fetchone())
        if not session:
            return {"error": "signature_session_not_found"}
        if _safe_text(session.get("verification_status")) == "valid" and not int(force or 0):
            return {"status": "success", "session": session, "already_verified": 1}
        document = _row_dict(cursor.execute("SELECT * FROM documents WHERE id=?", (_safe_int(session.get("document_id")),)).fetchone())
        revision = _row_dict(cursor.execute("SELECT * FROM document_file_revisions WHERE id=?", (_safe_int(session.get("file_revision_id")),)).fetchone())
        certificate = _row_dict(cursor.execute("SELECT * FROM edo_certificates WHERE id=?", (_safe_int(session.get("certificate_id")),)).fetchone())
        if not document:
            return {"error": "document_not_found"}
        if not revision:
            return {"error": "document_file_revision_required"}
        if not certificate:
            return {"error": "certificate_not_found"}
        signature_path = ""
        if _safe_text(session.get("detached_signature_url")).startswith("/uploads/"):
            signature_path = os.path.join(BASE_DIR, _safe_text(session.get("detached_signature_url")).lstrip("/"))
        signature_bytes = b""
        if signature_path and os.path.exists(signature_path):
            with open(signature_path, "rb") as buffer:
                signature_bytes = buffer.read()
        verification = _local_detached_verification(session, revision, certificate, signature_bytes, signature_path)
        now = int(time.time())
        cursor.execute(
            """
            UPDATE signature_sessions
            SET status=?, verification_status=?, verification_message=?, certificate_status=?,
                ocsp_status=?, crl_status=?, time_stamp_status=?, updated_at=?, completed_at=CASE WHEN ?=1 THEN ? ELSE completed_at END
            WHERE id=?
            """,
            (
                "verified" if verification.get("status") == "valid" else "verification_failed",
                _safe_text(verification.get("status")),
                _safe_text(verification.get("message")),
                _safe_text((verification.get("checks") or {}).get("certificate", {}).get("status")),
                _safe_text(verification.get("ocsp_status")),
                _safe_text(verification.get("crl_status")),
                _safe_text(verification.get("time_stamp_status")),
                now,
                1 if verification.get("status") == "valid" else 0,
                now,
                int(session_id or 0),
            ),
        )
        session = _row_dict(cursor.execute("SELECT * FROM signature_sessions WHERE id=?", (int(session_id or 0),)).fetchone())
        signature_id = 0
        protocol = _insert_protocol(cursor, session, 0, verification, actor, protocol_override)
        protocol_id = int(protocol.get("id") or 0)
        if verification.get("status") == "valid":
            signature_id = _upsert_signature_registry(cursor, document, revision, certificate, session, verification, protocol_id, actor)
            cursor.execute(
                "UPDATE signature_validation_protocols SET signature_id=? WHERE id=?",
                (int(signature_id or 0), protocol_id),
            )
            current_state = _safe_text(document.get("lifecycle_state")) or _safe_text(document.get("status")) or "draft"
            target_legal_significance = "qualified_signature" if _signature_legal_force(session.get("signature_kind")) == "qualified" else "signed"
            cursor.execute(
                "UPDATE documents SET lifecycle_state='signed', status='signed', legal_significance=? WHERE id=?",
                (target_legal_significance, _safe_int(document.get("id"))),
            )
            cursor.execute(
                """
                INSERT INTO document_lifecycle_events (
                    document_id, from_state, to_state, action_name, actor_email, actor_name, comment, created_at
                ) VALUES (?, ?, 'signed', 'detached_signature_verified', ?, ?, ?, ?)
                """,
                (
                    _safe_int(document.get("id")),
                    current_state,
                    _safe_text(actor.get("email")),
                    _safe_text(actor.get("name")),
                    _safe_text(session.get("comment")),
                    now,
                ),
            )
        cursor.execute(
            """
            UPDATE signature_sessions
            SET validation_protocol_id=?, signature_registry_id=?, updated_at=?
            WHERE id=?
            """,
            (protocol_id, signature_id, now, int(session_id or 0)),
        )
        if _safe_int(certificate.get("id")):
            cursor.execute(
                "UPDATE edo_certificates SET last_checked_at=?, last_verified_result=?, updated_at=? WHERE id=?",
                (now, _safe_text(verification.get("status")), now, _safe_int(certificate.get("id"))),
            )
        conn.commit()
        session = get_signature_session(session_id)
        return {
            "status": "success",
            "session": session,
            "signature_id": signature_id,
            "protocol_id": protocol_id,
            "verification": verification,
            "protocol": protocol,
        }
    finally:
        conn.close()


def attach_validation_protocol(session_id: int, data: dict, actor: dict) -> dict:
    conn = get_connection(row_factory=True)
    try:
        cursor = conn.cursor()
        session = _row_dict(cursor.execute("SELECT * FROM signature_sessions WHERE id=?", (int(session_id or 0),)).fetchone())
        if not session:
            return {"error": "signature_session_not_found"}
        verification = {
            "status": _safe_text(data.get("validation_result")) or _safe_text(session.get("verification_status")) or "attached",
            "message": _safe_text(data.get("validation_message")) or _safe_text(session.get("verification_message")) or "Протокол приложен",
            "checks": data.get("checks") if isinstance(data.get("checks"), dict) else {},
        }
        protocol = _insert_protocol(cursor, session, _safe_int(session.get("signature_registry_id")), verification, actor, data)
        protocol_id = int(protocol.get("id") or 0)
        cursor.execute(
            "UPDATE signature_sessions SET validation_protocol_id=?, updated_at=? WHERE id=?",
            (protocol_id, int(time.time()), int(session_id or 0)),
        )
        if _safe_int(session.get("signature_registry_id")):
            cursor.execute(
                "UPDATE edo_signature_registry SET validation_protocol_id=? WHERE id=?",
                (protocol_id, _safe_int(session.get("signature_registry_id"))),
            )
        conn.commit()
        return {"status": "success", "protocol_id": protocol_id, "protocol": protocol}
    finally:
        conn.close()
