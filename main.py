import os, asyncio, datetime, time, json, traceback, html
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from database import (
    create_notification,
    init_db,
    record_error_log,
    get_connection,
    next_safe_table_id,
    start_background_job_run,
    heartbeat_background_job_run,
    finish_background_job_run,
)
from app_logging import init_app_logging, get_logger
from settings import using_insecure_defaults
from utils import manager, verify_document_qr_token  # Подключаем наш менеджер WebSockets

# Импортируем наши роутеры из папки routers
from routers import users, projects, docs, communications, accounting, erp_deep, erp_ops_plus, workbench, integration_1c

PROJECT_JSON_OBJECT_FIELDS = {
    "checkedState",
    "comments",
    "deadlines",
    "escalations",
    "archive_details",
    "taskFiles",
    "subtasks",
}
PROJECT_JSON_FIELDS = [
    "checkedState",
    "comments",
    "deadlines",
    "chat",
    "files",
    "logs",
    "team",
    "checklist",
    "escalations",
    "archive_details",
    "taskFiles",
    "subtasks",
    "time_logs",
    "allowed_roles",
    "nomenclature",
]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")


def _load_json_value(raw_value, default):
    if not raw_value:
        return default
    try:
        return json.loads(raw_value)
    except Exception:
        return default


def _project_field_default(field_name: str):
    return {} if field_name in PROJECT_JSON_OBJECT_FIELDS else []


def _deserialize_project_row(row) -> dict:
    project = dict(row)
    for field_name in PROJECT_JSON_FIELDS:
        project[field_name] = _load_json_value(
            project.get(field_name),
            _project_field_default(field_name),
        )
    return project


def _find_guest_portal_project(token: str):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM projects WHERE archive_details LIKE ?", (f"%{token}%",))
        for row in c.fetchall():
            project = _deserialize_project_row(row)
            portal = (project.get("archive_details") or {}).get("guest_portal", {})
            if portal.get("token") == token:
                return project
    finally:
        conn.close()
    return None


def _is_public_document_file_url(file_url: str) -> bool:
    raw = str(file_url or "").strip()
    if not raw:
        return False
    if raw.startswith(("http://", "https://")):
        return True
    if raw.startswith("/uploads/"):
        local_path = os.path.join(UPLOADS_DIR, raw.removeprefix("/uploads/"))
        return os.path.exists(local_path)
    return False


def _parse_ru_date(value: str):
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    return None


def _contract_reminder_notification_exists(conn, entity_id: str) -> bool:
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM notifications WHERE entity_type='contract_reminder' AND entity_id=? LIMIT 1",
        (str(entity_id or ""),),
    )
    return bool(c.fetchone())


def _dispatch_contract_deadline_notifications(conn) -> int:
    reminder_days = {30, 15, 5}
    today = datetime.date.today()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            cm.id,
            cm.contract_number,
            cm.title,
            cm.end_date,
            cm.manager_name,
            cm.manager_email,
            cm.status,
            cl.name AS client_name
        FROM contract_master cm
        LEFT JOIN clients cl ON cl.id = cm.client_id
        """
    )
    rows = c.fetchall()
    director_rows = []
    try:
        c.execute("SELECT email, name FROM users WHERE role='Директор' AND status='approved'")
        director_rows = c.fetchall()
    except Exception:
        director_rows = []
    created = 0
    for row in rows:
        data = dict(row)
        end_date = _parse_ru_date(data.get("end_date", ""))
        if not end_date:
            continue
        if str(data.get("status") or "").lower() in {"archived", "closed", "cancelled", "canceled", "terminated"}:
            continue
        days_left = (end_date - today).days
        if days_left not in reminder_days:
            continue
        contract_label = data.get("contract_number") or f"#{data.get('id')}"
        client_label = data.get("client_name") or "контрагент не указан"
        message = f"Договор {contract_label} ({client_label}) заканчивается {data.get('end_date')}. До срока осталось {days_left} дн."
        recipients = []
        if data.get("manager_email") or data.get("manager_name"):
            recipients.append({
                "user_email": str(data.get("manager_email") or "").strip(),
                "user_name": str(data.get("manager_name") or "").strip(),
            })
        for director in director_rows:
            director_data = dict(director)
            recipients.append({
                "user_email": str(director_data.get("email") or "").strip(),
                "user_name": str(director_data.get("name") or "").strip(),
            })
        dedupe = set()
        for recipient in recipients:
            target_key = recipient["user_email"] or recipient["user_name"]
            if not target_key or target_key in dedupe:
                continue
            dedupe.add(target_key)
            entity_id = f"{data.get('id')}:{days_left}:{target_key}"
            if _contract_reminder_notification_exists(conn, entity_id):
                continue
            create_notification(
                f"Срок договора через {days_left} дн.",
                message,
                user_email=recipient["user_email"],
                user_name=recipient["user_name"],
                category="contract",
                entity_type="contract_reminder",
                entity_id=entity_id,
            )
            created += 1
    return created


# Фоновая задача для регулярных (периодических) поручений Бухгалтерии и др.
async def periodic_task_runner():
    while True:
        await asyncio.sleep(3600) # Проверяем каждый час
        run_id = 0
        try:
            run_id = start_background_job_run("periodic_task_runner", "scheduler", details={"sleep_seconds": 3600})
            conn = get_connection(row_factory=True)
            try:
                c = conn.cursor()
                c.execute("SELECT * FROM tasks WHERE recurrence != 'none' AND status != 'canceled'")
                tasks = c.fetchall()
                heartbeat_background_job_run(run_id, {"tasks_total": len(tasks), "phase": "clone_recurring"})
                today = datetime.datetime.now()
                created = 0
                for t in tasks:
                    recurrence = t["recurrence"] or ""
                    if not recurrence.startswith("monthly_"):
                        continue

                    try:
                        target_day = int(recurrence.split("_", 1)[1])
                    except (IndexError, ValueError):
                        logger.warning("Skipping malformed recurrence value for task %s: %s", t["id"], recurrence)
                        continue

                    if today.day != target_day:
                        continue

                    clone_title = f"{t['title']} ({today.strftime('%B %Y')})"
                    c.execute("SELECT id FROM tasks WHERE title=? AND author=?", (clone_title, t["author"]))
                    if c.fetchone():
                        continue

                    c.execute(
                        """
                        INSERT INTO tasks (
                            id, title, description, author, executor, deadline, status, created_at, recurrence
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            next_safe_table_id(conn, "tasks"),
                            clone_title,
                            t["description"],
                            t["author"],
                            t["executor"],
                            today.strftime("%d.%m.%Y"),
                            "active",
                            today.strftime("%d.%m.%Y %H:%M"),
                            "none",
                        ),
                    )
                    created += 1
                contract_reminders = _dispatch_contract_deadline_notifications(conn)
                conn.commit()
                if contract_reminders:
                    await manager.broadcast({"type": "notifications"})
                finish_background_job_run(run_id, "success", {"tasks_total": len(tasks), "created": created, "contract_reminders": contract_reminders})
            finally:
                conn.close()
        except Exception as e:
            if run_id:
                finish_background_job_run(run_id, "failed", {"error": str(e)[:500]})
            logger.exception("periodic_task_runner failed: %s", e)


async def integration_sync_runner():
    while True:
        await asyncio.sleep(300)
        run_id = 0
        try:
            run_id = start_background_job_run("integration_sync_runner", "integration", details={"limit": 25, "sleep_seconds": 300})
            heartbeat_background_job_run(run_id, {"phase": "process_queue"})
            result = projects.process_due_1c_sync_queue(limit=25)
            finish_background_job_run(run_id, "success", result)
            if result.get("processed"):
                logger.info("integration_sync_runner processed=%s success=%s failed=%s", result.get("processed"), result.get("success"), result.get("failed"))
        except Exception as e:
            if run_id:
                finish_background_job_run(run_id, "failed", {"error": str(e)[:500]})
            logger.exception("integration_sync_runner failed: %s", e)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    periodic_task = asyncio.create_task(periodic_task_runner())
    integration_task = asyncio.create_task(integration_sync_runner())
    try:
        yield
    finally:
        periodic_task.cancel()
        integration_task.cancel()
        try:
            await periodic_task
        except asyncio.CancelledError:
            pass
        try:
            await integration_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Korda CRM API", lifespan=lifespan)
init_app_logging()
logger = get_logger("main")

# Создаем папки для файлов и монтируем статику
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(BACKUPS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Настраиваем шаблонизатор Jinja2
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception as exc:
        record_error_log(
            source="middleware",
            message=str(exc),
            path=request.url.path,
            method=request.method,
            traceback_text=traceback.format_exc(),
        )
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "internal_server_error"}, status_code=500)
        raise
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

    sensitive_prefixes = (
        "/app",
        "/portal/",
        "/api/login",
        "/api/register",
        "/api/recover",
        "/api/audit",
    )
    if request.url.path == "/" or request.url.path.startswith(sensitive_prefixes):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    record_error_log(
        source="exception_handler",
        message=str(exc),
        path=request.url.path,
        method=request.method,
        traceback_text=traceback.format_exc(),
    )
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "internal_server_error"}, status_code=500)
    return HTMLResponse("<h1>500</h1><p>Внутренняя ошибка сервера</p>", status_code=500)

@app.get("/")
def read_root(): 
    # При входе кидаем на страницу логина
    return RedirectResponse(url="/static/login.html")

# ЭНДПОИНТ: Отдает склеенный интерфейс CRM
@app.get("/app")
def read_app(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/qr/doc/{doc_id}")
def open_document_by_qr(doc_id: int, token: str = ""):
    if not verify_document_qr_token(doc_id, token):
        return HTMLResponse("<h1>403</h1><p>QR-ссылка недействительна или устарела.</p>", status_code=403)
    conn = get_connection(row_factory=True)
    try:
        row = conn.execute(
            "SELECT id, number, d_date, correspondent, subject, file_url FROM documents WHERE id=?",
            (int(doc_id or 0),),
        ).fetchone()
        document = dict(row) if row else {}
    finally:
        conn.close()
    if not document:
        return HTMLResponse("<h1>404</h1><p>Документ не найден.</p>", status_code=404)
    file_url = str(document.get("file_url") or "").strip()
    if _is_public_document_file_url(file_url):
        return RedirectResponse(url=file_url, status_code=307)
    title = html.escape(document.get("number") or f"#{doc_id}")
    subject = html.escape(document.get("subject") or "Тема не указана")
    correspondent = html.escape(document.get("correspondent") or "Не указан")
    d_date = html.escape(document.get("d_date") or "Не указана")
    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang="ru">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Документ {title}</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f3f6fb; margin:0; padding:24px; color:#183153; }}
                .card {{ max-width:720px; margin:0 auto; background:#fff; border:1px solid #dbe4f0; border-radius:20px; padding:28px; box-shadow:0 20px 60px rgba(24,49,83,.08); }}
                .eyebrow {{ font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.12em; color:#5b6f8f; margin-bottom:10px; }}
                h1 {{ margin:0 0 8px; font-size:32px; line-height:1.1; }}
                .meta {{ color:#5b6f8f; margin-bottom:18px; font-size:15px; }}
                .box {{ background:#f7faff; border:1px solid #dbe4f0; border-radius:14px; padding:18px; line-height:1.6; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="eyebrow">Korda CRM · QR-документ</div>
                <h1>Документ № {title}</h1>
                <div class="meta">Дата: {d_date} · Корреспондент: {correspondent}</div>
                <div class="box">
                    <strong>Файл пока не прикреплен.</strong><br>
                    Тема документа: {subject}
                </div>
            </div>
        </body>
        </html>
        """,
        status_code=200,
    )


@app.get("/api/health")
def healthcheck():
    return {"status": "ok", "service": "korda-crm", "time": int(time.time())}


@app.get("/api/health/deep")
def deep_healthcheck():
    checks = {
        "database": False,
        "uploads_dir": os.path.isdir(os.path.join(BASE_DIR, "uploads")),
        "backups_dir": os.path.isdir(os.path.join(BASE_DIR, "backups")),
        "logs_dir": os.path.isdir(os.path.join(BASE_DIR, "logs")),
        "app_secret_configured": not using_insecure_defaults(),
    }
    db_latency_ms = None
    try:
        started = time.time()
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        db_latency_ms = round((time.time() - started) * 1000, 2)
        checks["database"] = True
    except Exception as exc:
        logger.exception("Deep healthcheck failed: %s", exc)

    status = "ok" if all(checks.values()) else "degraded"
    return {
        "status": status,
        "checks": checks,
        "db_latency_ms": db_latency_ms,
        "time": int(time.time()),
    }


@app.get("/portal/{token}")
def read_guest_portal(request: Request, token: str):
    project = _find_guest_portal_project(token)

    if not project:
        raise HTTPException(status_code=404, detail="Ссылка портала недействительна")

    checklist_summary = []
    for s_idx, section in enumerate(project.get("checklist", [])):
        tasks = section.get("tasks", [])
        done = 0
        for t_idx, _task in enumerate(tasks):
            state = (project.get("checkedState") or {}).get(f"task_{s_idx}_{t_idx}", "")
            if str(state).startswith("DONE"):
                done += 1
        checklist_summary.append({
            "title": section.get("title", "Этап"),
            "done": done,
            "total": len(tasks)
        })

    files = sorted(project.get("files", []), key=lambda item: item.get("time", ""), reverse=True)[:8]
    logs = project.get("logs", [])[:8]

    return templates.TemplateResponse(request, "portal.html", {
        "project": project,
        "checklist_summary": checklist_summary,
        "files": files,
        "logs": logs
    })

# === НОВЫЙ ЭНДПОИНТ WEBSOCKET ===
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Просто держим соединение открытым и слушаем (если клиент что-то пришлет)
            await websocket.receive_text() 
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Инициализируем базу данных при старте
init_db()

# Подключаем все наши модули с функционалом
app.include_router(users.router)
app.include_router(projects.router)
app.include_router(docs.router)
app.include_router(communications.router)
app.include_router(accounting.router)
app.include_router(erp_deep.router)
app.include_router(erp_ops_plus.router)
app.include_router(workbench.router)
app.include_router(integration_1c.router)
