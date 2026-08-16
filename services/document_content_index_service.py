import html
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from xml.etree import ElementTree

from database import get_connection


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")


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


def _normalize_text(value: str) -> str:
    # PostgreSQL rejects NUL characters in text columns. They can legitimately
    # appear in fallback extraction from binary PDF/Office files, so remove
    # them before the extracted content is written to the search index.
    cleaned = _safe_text(value).replace("\x00", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _file_path_from_revision(revision: dict) -> str:
    stored = _safe_text(revision.get("stored_filename"))
    if stored:
        return os.path.join(UPLOADS_DIR, stored)
    file_url = _safe_text(revision.get("file_url"))
    if file_url.startswith("/uploads/"):
        return os.path.join(BASE_DIR, file_url.lstrip("/"))
    return ""


def _read_text_file(path: str) -> str:
    with open(path, "rb") as buffer:
        raw = buffer.read()
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _extract_docx_text(path: str) -> str:
    with zipfile.ZipFile(path) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_bytes)
    chunks = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            chunks.append(node.text)
        elif node.tag.endswith("}tab"):
            chunks.append("\t")
        elif node.tag.endswith("}br"):
            chunks.append("\n")
    return " ".join(chunks)


def _extract_pdf_text(path: str) -> tuple[str, str]:
    tool = shutil.which("pdftotext")
    if tool:
        completed = subprocess.run([tool, "-layout", path, "-"], capture_output=True, text=True, timeout=45)
        if completed.returncode == 0 and _safe_text(completed.stdout):
            return completed.stdout, "pdftotext"
    raw = open(path, "rb").read().decode("latin-1", errors="ignore")
    chunks = []
    for match in re.finditer(r"\(([^()]{2,500})\)", raw):
        chunks.append(match.group(1).replace("\\)", ")").replace("\\(", "("))
    return html.unescape(" ".join(chunks)), "pdf_stream_fallback"


def _extract_image_text(path: str, language: str = "rus+eng") -> tuple[str, str, str]:
    tool = shutil.which("tesseract")
    if not tool:
        return "", "ocr_unavailable", "tesseract не установлен"
    completed = subprocess.run([tool, path, "stdout", "-l", language or "rus+eng"], capture_output=True, text=True, timeout=90)
    if completed.returncode != 0:
        return "", "ocr_failed", (completed.stderr or completed.stdout or "").strip()
    return completed.stdout or "", "tesseract", ""


def _runtime_tool_status(binary_name: str, command_args: list[str]) -> dict:
    path = shutil.which(binary_name)
    if not path:
        return {"available": False, "path": "", "ok": False, "output": f"{binary_name} не найден"}
    try:
        completed = subprocess.run([path, *command_args], capture_output=True, text=True, timeout=12)
        output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        return {"available": True, "path": path, "ok": completed.returncode == 0, "returncode": completed.returncode, "output": output[:2000]}
    except Exception as exc:
        return {"available": True, "path": path, "ok": False, "returncode": -1, "output": str(exc)}


def content_extraction_runtime_status() -> dict:
    pdftotext = _runtime_tool_status("pdftotext", ["-v"])
    tesseract = _runtime_tool_status("tesseract", ["--version"])
    clamscan = _runtime_tool_status("clamscan", ["--version"])
    langs = {"available": False, "items": []}
    tesseract_path = tesseract.get("path") or ""
    if tesseract_path:
        try:
            completed = subprocess.run([tesseract_path, "--list-langs"], capture_output=True, text=True, timeout=12)
            lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip() and not line.lower().startswith("list of")]
            langs = {"available": completed.returncode == 0, "items": lines[:80]}
        except Exception as exc:
            langs = {"available": False, "items": [], "error": str(exc)}
    return {
        "status": "success",
        "ready": bool(pdftotext.get("available") or tesseract.get("available")),
        "pdf_text": pdftotext,
        "ocr": {**tesseract, "languages": langs},
        "antivirus": clamscan,
        "message": "OCR/PDF extraction runtime найден" if (pdftotext.get("available") or tesseract.get("available")) else "pdftotext/tesseract не найдены; текстовые DOCX/TXT будут индексироваться, OCR/PDF ограничены.",
    }


def extract_text_from_revision(revision: dict, language: str = "rus+eng") -> dict:
    path = _file_path_from_revision(revision)
    mime_type = _safe_text(revision.get("mime_type")).lower()
    filename = _safe_text(revision.get("original_filename")).lower()
    if not path or not os.path.exists(path):
        return {"text": "", "status": "file_missing", "method": "none", "message": "Файл ревизии не найден", "confidence": 0}
    try:
        if mime_type.startswith("text/") or filename.endswith((".txt", ".csv", ".md", ".log")):
            text = _read_text_file(path)
            return {"text": _normalize_text(text), "status": "indexed", "method": "text", "message": "", "confidence": 0.98}
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or filename.endswith(".docx"):
            text = _extract_docx_text(path)
            return {"text": _normalize_text(text), "status": "indexed", "method": "docx", "message": "", "confidence": 0.95}
        if mime_type == "application/pdf" or filename.endswith(".pdf"):
            text, method = _extract_pdf_text(path)
            text = _normalize_text(text)
            return {"text": text, "status": "indexed" if text else "empty", "method": method, "message": "" if text else "PDF не содержит извлекаемого текста", "confidence": 0.9 if text else 0.2}
        if mime_type.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
            text, method, message = _extract_image_text(path, language)
            text = _normalize_text(text)
            return {"text": text, "status": "indexed" if text else method, "method": method, "message": message, "confidence": 0.82 if text else 0.1}
    except Exception as exc:
        return {"text": "", "status": "extract_error", "method": "exception", "message": str(exc), "confidence": 0}
    return {"text": "", "status": "unsupported_mime", "method": "none", "message": f"Тип файла не поддержан для извлечения текста: {mime_type}", "confidence": 0}


def upsert_document_content_index(cursor, document: dict, revision: dict, blob_id: int = 0, extracted: dict | None = None, source_type: str = "file") -> dict:
    extracted = extracted or extract_text_from_revision(revision)
    text = _normalize_text(extracted.get("text"))
    excerpt = text[:500]
    now = int(time.time())
    cursor.execute(
        """
        INSERT INTO document_content_index (
            document_id, file_revision_id, blob_id, source_type, content_text, content_excerpt,
            language, extraction_status, extraction_method, confidence, checksum_sha256, indexed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'simple', ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_revision_id, source_type)
        DO UPDATE SET
            blob_id=excluded.blob_id,
            content_text=excluded.content_text,
            content_excerpt=excluded.content_excerpt,
            extraction_status=excluded.extraction_status,
            extraction_method=excluded.extraction_method,
            confidence=excluded.confidence,
            checksum_sha256=excluded.checksum_sha256,
            indexed_at=excluded.indexed_at,
            updated_at=excluded.updated_at
        """,
        (
            _safe_int(document.get("id")),
            _safe_int(revision.get("id")),
            _safe_int(blob_id),
            _safe_text(source_type) or "file",
            text,
            excerpt,
            _safe_text(extracted.get("status")) or "pending",
            _safe_text(extracted.get("method")),
            float(extracted.get("confidence") or 0),
            _safe_text(revision.get("checksum")),
            now,
            now,
            now,
        ),
    )
    index_row = _row_dict(
        cursor.execute(
            "SELECT * FROM document_content_index WHERE file_revision_id=? AND source_type=?",
            (_safe_int(revision.get("id")), _safe_text(source_type) or "file"),
        ).fetchone()
    )
    index_row["extraction_message"] = _safe_text(extracted.get("message"))
    return index_row


def extract_text_for_revision_id(file_revision_id: int, language: str = "rus+eng") -> dict:
    conn = get_connection(row_factory=True)
    try:
        revision = _row_dict(conn.execute("SELECT * FROM document_file_revisions WHERE id=?", (_safe_int(file_revision_id),)).fetchone())
        if not revision:
            return {"text": "", "status": "revision_not_found", "method": "none", "message": "Ревизия файла не найдена", "confidence": 0}
        return extract_text_from_revision(revision, language=language)
    finally:
        conn.close()


def upsert_index_from_text(conn, document_id: int, file_revision_id: int, text: str, confidence: float = 0.9, source_type: str = "ocr") -> dict:
    revision = _row_dict(conn.execute("SELECT * FROM document_file_revisions WHERE id=?", (_safe_int(file_revision_id),)).fetchone()) if file_revision_id else {}
    document = _row_dict(conn.execute("SELECT * FROM documents WHERE id=?", (_safe_int(document_id),)).fetchone()) if document_id else {}
    if not revision:
        revision = {"id": 0, "checksum": ""}
    if not document:
        document = {"id": _safe_int(document_id)}
    return upsert_document_content_index(
        conn.cursor(),
        document,
        revision,
        0,
        {"text": text, "status": "indexed", "method": source_type, "confidence": confidence},
        source_type=source_type,
    )


def search_document_content(conn, query: str, limit: int = 8) -> list[dict]:
    query = _safe_text(query)
    if not query:
        return []
    max_rows = max(1, min(_safe_int(limit) or 8, 30))
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT d.id, d.number, d.subject, d.correspondent, d.type, d.status,
                       r.original_filename, r.revision_label, i.content_excerpt,
                       ts_rank(i.search_vector, websearch_to_tsquery('simple', ?)) AS rank
                FROM document_content_index i
                JOIN documents d ON d.id = i.document_id
                LEFT JOIN document_file_revisions r ON r.id = i.file_revision_id
                WHERE i.search_vector @@ websearch_to_tsquery('simple', ?)
                ORDER BY rank DESC, i.indexed_at DESC, i.id DESC
                LIMIT ?
                """,
                (query, query, max_rows),
            ).fetchall()
        ]
        if rows:
            return rows
    except Exception:
        pass
    like = f"%{query.lower()}%"
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT d.id, d.number, d.subject, d.correspondent, d.type, d.status,
                   r.original_filename, r.revision_label, i.content_excerpt, 0 AS rank
            FROM document_content_index i
            JOIN documents d ON d.id = i.document_id
            LEFT JOIN document_file_revisions r ON r.id = i.file_revision_id
            WHERE LOWER(COALESCE(i.content_text, '')) LIKE ?
            ORDER BY i.indexed_at DESC, i.id DESC
            LIMIT ?
            """,
            (like, max_rows),
        ).fetchall()
    ]
