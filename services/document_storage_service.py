import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import time


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")

MAX_DOCUMENT_UPLOAD_BYTES = int(os.getenv("KORDA_MAX_DOCUMENT_UPLOAD_BYTES", str(50 * 1024 * 1024)))
BLOCKED_DOCUMENT_EXTENSIONS = {
    ".app",
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".dmg",
    ".exe",
    ".hta",
    ".htm",
    ".html",
    ".jar",
    ".js",
    ".jse",
    ".mjs",
    ".msi",
    ".ps1",
    ".reg",
    ".scr",
    ".sh",
    ".svg",
    ".vb",
    ".vbe",
    ".vbs",
    ".wsf",
}
ALLOWED_MIME_PREFIXES = ("text/", "image/")
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
}


def _safe_text(value) -> str:
    return str(value or "").strip()


def _safe_filename(value: str) -> str:
    raw = os.path.basename(_safe_text(value)) or "document.bin"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")
    return cleaned or "document.bin"


def _detect_mime_type(filename: str, declared_mime: str, file_bytes: bytes) -> str:
    head = file_bytes[:16] if file_bytes else b""
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"PK\x03\x04") and filename.lower().endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    guessed = mimetypes.guess_type(filename or "")[0] or ""
    if guessed:
        return guessed
    return _safe_text(declared_mime) or "application/octet-stream"


def _is_allowed_mime(mime_type: str) -> bool:
    mime_type = _safe_text(mime_type).lower()
    return mime_type in ALLOWED_MIME_TYPES or any(mime_type.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES)


def _run_antivirus_scan(file_path: str) -> tuple[str, str]:
    scanner = _safe_text(os.getenv("KORDA_CLAMSCAN_BIN")) or shutil.which("clamscan") or ""
    if not scanner:
        return "not_configured", "clamscan не настроен"
    try:
        completed = subprocess.run([scanner, "--no-summary", file_path], capture_output=True, text=True, timeout=30)
    except Exception as exc:
        return "scan_error", str(exc)
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if completed.returncode == 0:
        return "clean", output or "OK"
    if completed.returncode == 1:
        return "infected", output or "Threat detected"
    return "scan_error", output or f"clamscan exit {completed.returncode}"


def prepare_document_file(document_id: int, revision_no: int, upload_name: str, content_type: str, file_bytes: bytes) -> dict:
    file_bytes = file_bytes or b""
    safe_name = _safe_filename(upload_name)
    name_root, ext = os.path.splitext(safe_name)
    detected_mime = _detect_mime_type(safe_name, content_type, file_bytes)
    validation_errors = []
    if not file_bytes:
        validation_errors.append("empty_file")
    if len(file_bytes) > MAX_DOCUMENT_UPLOAD_BYTES:
        validation_errors.append("file_too_large")
    if ext.lower() in BLOCKED_DOCUMENT_EXTENSIONS:
        validation_errors.append("extension_not_allowed")
    if not _is_allowed_mime(detected_mime):
        validation_errors.append("mime_not_allowed")
    checksum = hashlib.sha256(file_bytes).hexdigest()
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    stored_name = f"{int(time.time())}_doc_{int(document_id or 0)}_v{int(revision_no or 1)}_{checksum[:12]}_{name_root[:70]}{ext[:16]}"
    disk_path = os.path.join(UPLOADS_DIR, stored_name)
    with open(disk_path, "wb") as buffer:
        buffer.write(file_bytes)
    antivirus_status, antivirus_details = _run_antivirus_scan(disk_path)
    if antivirus_status == "infected":
        validation_errors.append("antivirus_infected")
    validation_status = "rejected" if validation_errors else "accepted"
    return {
        "original_filename": safe_name,
        "stored_filename": stored_name,
        "file_url": f"/uploads/{stored_name}",
        "disk_path": disk_path,
        "declared_mime_type": _safe_text(content_type) or "application/octet-stream",
        "detected_mime_type": detected_mime,
        "file_size": len(file_bytes),
        "checksum": checksum,
        "antivirus_status": antivirus_status,
        "antivirus_details": antivirus_details,
        "validation_status": validation_status,
        "validation_errors": validation_errors,
    }


def insert_document_file_blob(cursor, document_id: int, file_revision_id: int, storage: dict, actor_email: str = "") -> dict:
    now = int(time.time())
    cursor.execute(
        """
        INSERT INTO document_file_blobs (
            document_id, file_revision_id, original_filename, stored_filename, file_url, declared_mime_type,
            detected_mime_type, file_size, checksum_sha256, storage_backend, storage_key, antivirus_status,
            antivirus_details, validation_status, validation_errors_json, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'local', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(document_id or 0),
            int(file_revision_id or 0),
            _safe_text(storage.get("original_filename")),
            _safe_text(storage.get("stored_filename")),
            _safe_text(storage.get("file_url")),
            _safe_text(storage.get("declared_mime_type")),
            _safe_text(storage.get("detected_mime_type")),
            int(storage.get("file_size") or 0),
            _safe_text(storage.get("checksum")),
            _safe_text(storage.get("stored_filename")),
            _safe_text(storage.get("antivirus_status")),
            _safe_text(storage.get("antivirus_details")),
            _safe_text(storage.get("validation_status")) or "accepted",
            json.dumps(storage.get("validation_errors") or [], ensure_ascii=False),
            _safe_text(actor_email),
            now,
            now,
        ),
    )
    blob_id = int(cursor.lastrowid or 0)
    return {"id": blob_id, **storage}
