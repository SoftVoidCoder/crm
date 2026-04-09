import os, asyncio, datetime, sqlite3, time
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from database import init_db, DB_NAME
from utils import manager  # Подключаем наш менеджер WebSockets

# Импортируем наши роутеры из папки routers
from routers import users, projects, docs, communications

app = FastAPI(title="Korda CRM API")

# Создаем папки для файлов и монтируем статику
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Настраиваем шаблонизатор Jinja2
templates = Jinja2Templates(directory="templates")

@app.get("/")
def read_root(): 
    # При входе кидаем на страницу логина
    return RedirectResponse(url="/static/login.html")

# ЭНДПОИНТ: Отдает склеенный интерфейс CRM
@app.get("/app")
def read_app(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

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

# Фоновая задача для регулярных (периодических) поручений Бухгалтерии и др.
async def periodic_task_runner():
    while True:
        await asyncio.sleep(3600) # Проверяем каждый час
        try:
            conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
            c.execute("SELECT * FROM tasks WHERE recurrence != 'none' AND status != 'canceled'")
            tasks = c.fetchall()
            today = datetime.datetime.now()
            for t in tasks:
                if t['recurrence'].startswith('monthly_'):
                    target_day = int(t['recurrence'].split('_')[1])
                    if today.day == target_day:
                        clone_title = f"{t['title']} ({today.strftime('%B %Y')})"
                        c.execute("SELECT id FROM tasks WHERE title=? AND author=?", (clone_title, t['author']))
                        if not c.fetchone():
                            c.execute("INSERT INTO tasks (id, title, description, author, executor, deadline, status, created_at, recurrence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                                (int(time.time() * 1000), clone_title, t['description'], t['author'], t['executor'], today.strftime("%d.%m.%Y"), 'active', today.strftime("%d.%m.%Y %H:%M"), 'none'))
            conn.commit(); conn.close()
        except Exception as e:
            print(f"Ошибка periodic_task_runner: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(periodic_task_runner())

# Подключаем все наши модули с функционалом
app.include_router(users.router)
app.include_router(projects.router)
app.include_router(docs.router)
app.include_router(communications.router)