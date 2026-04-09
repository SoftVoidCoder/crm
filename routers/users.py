import sqlite3
from fastapi import APIRouter, BackgroundTasks
from database import DB_NAME
from schemas import AuthData, RoleData, SignatureData, RemoveUserData, VacationData
from utils import send_email_task, DEPT_EMAILS

router = APIRouter()

@router.post("/api/register")
def register(data: AuthData, bg_tasks: BackgroundTasks):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (data.email,))
    if c.fetchone(): return {"error": "Email занят"}
    c.execute("INSERT INTO users (email, password, name, role, status) VALUES (?, ?, ?, ?, ?)", (data.email, data.password, data.name, None, 'pending'))
    conn.commit(); bg_tasks.add_task(send_email_task, DEPT_EMAILS["Директор"], 'Новая заявка', f'Пользователь {data.name} ждет одобрения.'); return {"status": "success"}

@router.post("/api/login")
def login(data: AuthData):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=? AND password=?", (data.email, data.password))
    user = c.fetchone(); return dict(user) if user else {"error": "Ошибка входа"}

@router.post("/api/recover")
def recover(data: AuthData, bg_tasks: BackgroundTasks):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (data.email,))
    if c.fetchone():
        new_p = "123456"; c.execute("UPDATE users SET password=? WHERE email=?", (new_p, data.email)); conn.commit()
        bg_tasks.add_task(send_email_task, data.email, "Восстановление пароля", f"Временный пароль: {new_p}")
    return {"status": "success"}

@router.get("/api/status/{email}")
def get_status(email: str):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT status, role, is_head, hourly_rate FROM users WHERE email=?", (email,)); user = c.fetchone()
    return dict(user) if user else {"error": "Not found"}

@router.get("/api/users/pending")
def pending():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT email, name, status FROM users WHERE status='pending'"); return [dict(r) for r in c.fetchall()]

@router.get("/api/users/all")
def all_users():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT email, name, role, status, signature, password, deputy, abs_start, abs_end, abs_type, abs_reason, is_head, hourly_rate FROM users"); return [dict(r) for r in c.fetchall()]

@router.post("/api/users/approve")
def approve(data: RoleData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("UPDATE users SET role=?, status='approved', is_head=? WHERE email=?", (data.role, data.is_head, data.email)); conn.commit(); return {"status": "success"}

@router.post("/api/users/make_head")
def make_head(data: RoleData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("UPDATE users SET is_head=? WHERE email=?", (data.is_head, data.email)); conn.commit(); return {"status": "success"}

@router.post("/api/users/remove")
def remove_user(data: RemoveUserData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("UPDATE users SET status='banned' WHERE email=?", (data.email,)); conn.commit(); return {"status": "success"}

@router.post("/api/users/restore")
def restore_user(data: RemoveUserData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("UPDATE users SET status='approved' WHERE email=?", (data.email,)); conn.commit(); return {"status": "success"}

@router.post("/api/users/signature")
def update_signature(data: SignatureData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("UPDATE users SET signature=? WHERE email=?", (data.signature, data.email)); conn.commit(); return {"status": "success"}

@router.post("/api/users/vacation")
def update_vacation(data: VacationData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("UPDATE users SET abs_start=?, abs_end=?, abs_type=?, abs_reason=?, deputy=? WHERE email=?", (data.abs_start, data.abs_end, data.abs_type, data.abs_reason, data.deputy, data.email)); conn.commit(); return {"status": "success"}