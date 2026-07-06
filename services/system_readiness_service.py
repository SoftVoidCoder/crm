import os
import time

from database import get_backups, get_connection, get_database_runtime_info, get_error_logs
from services.crypto_signature_service import crypto_runtime_status
from services.document_content_index_service import content_extraction_runtime_status
from services.integration_sync_service import json_load, safe_int
from services.one_c_connector_service import one_c_readiness_summary
from settings import APP_ENV, using_insecure_defaults


def _status(ok: bool, warning: bool = False) -> str:
    if ok and not warning:
        return "green"
    if ok or warning:
        return "yellow"
    return "red"


def _check_database() -> dict:
    started = time.time()
    runtime = get_database_runtime_info()
    latency_ms = round((time.time() - started) * 1000, 2)
    pending = safe_int(runtime.get("migrations_pending"))
    return {
        "key": "database",
        "title": "База и миграции",
        "status": _status(pending == 0),
        "message": "Миграции применены" if pending == 0 else f"Ожидают применения: {pending}",
        "details": {
            "backend": runtime.get("backend"),
            "db_name": runtime.get("current_database") or runtime.get("db_name"),
            "latency_ms": latency_ms,
            "migrations_applied": runtime.get("migrations_applied", 0),
            "migrations_pending": pending,
            "pending_migrations": runtime.get("pending_migrations", []),
        },
    }


def _check_one_c() -> dict:
    readiness = one_c_readiness_summary()
    ready = safe_int(readiness.get("ready_connectors")) > 0
    active = safe_int(readiness.get("active_connectors"))
    demo_checks = [item for item in readiness.get("checks", []) if item.get("transport") == "demo" or item.get("mode") == "demo"]
    is_production = APP_ENV == "production"
    warning = bool(demo_checks) or (active == 0)
    if is_production and demo_checks:
        return {
            "key": "one_c",
            "title": "1C обмен",
            "status": "red",
            "message": "В боевом режиме включён тестовый обмен 1С. Боевой коннектор не настроен.",
            "details": readiness,
        }
    return {
        "key": "one_c",
        "title": "1C обмен",
        "status": _status(ready, warning=warning),
        "message": "Боевой endpoint 1С доступен" if ready and not demo_checks else ("Активен тестовый режим 1С" if demo_checks else "Коннектор 1С не настроен"),
        "details": readiness,
    }


def _check_crypto() -> dict:
    runtime = crypto_runtime_status()
    ready = bool(runtime.get("ready"))
    return {
        "key": "crypto",
        "title": "CryptoPro / CAdES",
        "status": _status(ready, warning=not ready),
        "message": runtime.get("message") or ("CryptoPro найден" if ready else "CryptoPro не найден"),
        "details": runtime,
    }


def _check_content_runtime() -> tuple[dict, dict]:
    runtime = content_extraction_runtime_status()
    pdf_ready = bool((runtime.get("pdf_text") or {}).get("available"))
    ocr_ready = bool((runtime.get("ocr") or {}).get("available"))
    av_ready = bool((runtime.get("antivirus") or {}).get("available"))
    content = {
        "key": "content_index",
        "title": "OCR и полнотекст",
        "status": _status(pdf_ready or ocr_ready, warning=not (pdf_ready and ocr_ready)),
        "message": "PDF/OCR инструменты доступны" if pdf_ready and ocr_ready else runtime.get("message", ""),
        "details": runtime,
    }
    antivirus = {
        "key": "antivirus",
        "title": "Антивирус файлов",
        "status": _status(av_ready, warning=not av_ready),
        "message": "ClamAV доступен" if av_ready else "ClamAV не найден, файлы проходят MIME/checksum без антивирусной проверки",
        "details": runtime.get("antivirus") or {},
    }
    return content, antivirus


def _check_mail() -> dict:
    conn = get_connection(row_factory=True)
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM email_accounts ORDER BY is_default DESC, updated_at DESC, id DESC LIMIT 20").fetchall()]
    finally:
        conn.close()
    active = [row for row in rows if safe_int(row.get("is_active"))]
    errors = [row for row in active if str(row.get("last_error") or "").strip()]
    return {
        "key": "mail",
        "title": "Почта",
        "status": _status(bool(active), warning=bool(errors) or not active),
        "message": f"Активных ящиков: {len(active)}" if active else "Почтовые ящики не настроены",
        "details": {"accounts_total": len(rows), "active_accounts": len(active), "accounts_with_errors": len(errors), "errors": errors[:5]},
    }


def _check_backups() -> dict:
    backups = get_backups(limit=5)
    latest = backups[0] if backups else {}
    age_hours = None
    if latest.get("created_at"):
        age_hours = round((int(time.time()) - safe_int(latest.get("created_at"))) / 3600, 1)
    ok = bool(latest) and (age_hours is None or age_hours <= 48)
    return {
        "key": "backup",
        "title": "Резервные копии",
        "status": _status(ok, warning=bool(latest) and not ok),
        "message": f"Последняя backup: {age_hours} ч назад" if latest else "Backup ещё не создавался",
        "details": {"latest": latest, "age_hours": age_hours, "count": len(backups)},
    }


def _check_demo_modes() -> dict:
    conn = get_connection(row_factory=True)
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM integration_connectors WHERE status='active' ORDER BY updated_at DESC, id DESC").fetchall()]
    finally:
        conn.close()
    demo = []
    for row in rows:
        settings = json_load(row.get("settings_json"), {})
        transport = (settings.get("transport") or settings.get("mode") or "").strip().lower()
        if row.get("connector_type") == "1c" and transport in {"", "demo"}:
            demo.append({"id": row.get("id"), "provider_name": row.get("provider_name"), "transport": transport or "demo"})
    production = APP_ENV == "production"
    return {
        "key": "demo_modes",
        "title": "Тестовые режимы",
        "status": "red" if production and demo else ("yellow" if demo else "green"),
        "message": "Тестовые режимы запрещены в боевой среде" if production and demo else (f"Активных тестовых коннекторов: {len(demo)}" if demo else "Опасные тестовые режимы не активны"),
        "details": {"app_env": APP_ENV, "demo_connectors": demo},
    }


def _latest_errors() -> dict:
    conn = get_connection(row_factory=True)
    try:
        integration_errors = [dict(row) for row in conn.execute(
            "SELECT * FROM integration_error_events WHERE status='open' ORDER BY created_at DESC, id DESC LIMIT 10"
        ).fetchall()]
    finally:
        conn.close()
    system_errors = get_error_logs(limit=10)
    total = len(integration_errors) + len(system_errors)
    return {
        "key": "errors",
        "title": "Последние ошибки",
        "status": "red" if any((row.get("severity") or "") in {"critical", "fatal"} for row in integration_errors + system_errors) else ("yellow" if total else "green"),
        "message": f"Открытых ошибок: {total}" if total else "Критичных ошибок нет",
        "details": {"system_errors": system_errors, "integration_errors": integration_errors},
    }


def build_system_readiness() -> dict:
    checks = []
    for builder in (_check_database, _check_one_c, _check_crypto, _check_mail, _check_backups, _check_demo_modes, _latest_errors):
        try:
            checks.append(builder())
        except Exception as exc:
            checks.append({"key": getattr(builder, "__name__", "check"), "title": "Проверка", "status": "red", "message": str(exc)[:500], "details": {}})
    try:
        content, antivirus = _check_content_runtime()
        checks.extend([content, antivirus])
    except Exception as exc:
        checks.append({"key": "content_index", "title": "OCR и файлы", "status": "red", "message": str(exc)[:500], "details": {}})
    if using_insecure_defaults():
        checks.append({"key": "app_secret", "title": "Секрет приложения", "status": "red", "message": "KORDA_APP_SECRET не настроен", "details": {}})
    red = sum(1 for item in checks if item.get("status") == "red")
    yellow = sum(1 for item in checks if item.get("status") == "yellow")
    return {
        "status": "red" if red else ("yellow" if yellow else "green"),
        "app_env": APP_ENV,
        "generated_at": int(time.time()),
        "summary": {"red": red, "yellow": yellow, "green": sum(1 for item in checks if item.get("status") == "green"), "total": len(checks)},
        "checks": checks,
    }
