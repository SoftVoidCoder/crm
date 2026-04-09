import sqlite3, json, time, imaplib, email, datetime, asyncio
from email.header import decode_header
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import APIRouter
from database import DB_NAME
from schemas import MeetingData, MeetingUpdate, GlobalChatData, GlobalMessageData, TaskData, TaskUpdate

# === ПОДКЛЮЧАЕМ МЕНЕДЖЕР WEBSOCKETS ===
from utils import SMTP_USER, SMTP_PASS, manager

router = APIRouter()

# Настоящая отправка SMTP-писем (ТЗ 2.7.2)
def send_smtp_notification(to_email, subject, text):
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(text, 'plain', 'utf-8'))
        server = smtplib.SMTP_SSL('smtp.yandex.ru', 465)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to_email, msg.as_string())
        server.quit()
    except Exception as e:
        print("SMTP Error:", e)

@router.get("/api/meetings")
def get_meetings():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM meetings ORDER BY id DESC")
    res = []
    for r in c.fetchall():
        d = dict(r); d['participants'] = json.loads(d['participants']); d['agenda'] = json.loads(d['agenda']); d['decisions'] = json.loads(d['decisions'])
        res.append(d)
    return res

@router.post("/api/meetings")
async def create_meeting(data: MeetingData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("INSERT INTO meetings (id, title, m_date, m_time, participants, agenda, decisions, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (int(time.time() * 1000), data.title, data.m_date, data.m_time, json.dumps(data.participants), json.dumps(data.agenda), '{}', 'planned')); conn.commit()
    await manager.broadcast({"type": "meetings"})
    return {"status": "success"}

@router.put("/api/meetings/{m_id}")
async def update_meeting(m_id: int, data: MeetingUpdate):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("UPDATE meetings SET title=?, m_date=?, m_time=?, participants=?, agenda=?, decisions=?, status=? WHERE id=?", (data.title, data.m_date, data.m_time, json.dumps(data.participants), json.dumps(data.agenda), json.dumps(data.decisions), data.status, m_id)); conn.commit()
    await manager.broadcast({"type": "meetings"})
    return {"status": "success"}

@router.get("/api/chats")
def get_chats(user_name: str, user_role: str):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM global_chats ORDER BY id ASC")
    all_chats = c.fetchall(); user_chats = []
    for ch in all_chats:
        d = dict(ch); parts = json.loads(d['participants'])
        if d['type'] == 'system': user_chats.append(d)
        elif d['type'] == 'role':
            if user_role == 'Директор' or user_role in parts: user_chats.append(d)
        elif d['type'] == 'custom':
            if user_name == d['creator'] or user_name in parts or user_role == 'Директор': user_chats.append(d)
    return user_chats

@router.post("/api/chats")
async def create_chat(data: GlobalChatData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("INSERT INTO global_chats (id, name, type, creator, participants) VALUES (?, ?, ?, ?, ?)", (int(time.time() * 1000), data.name, 'custom', data.creator, json.dumps(data.participants))); conn.commit()
    await manager.broadcast({"type": "chats"})
    return {"status": "success"}

@router.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: int):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("DELETE FROM global_chats WHERE id=?", (chat_id,)); c.execute("DELETE FROM global_messages WHERE chat_id=?", (chat_id,)); conn.commit()
    await manager.broadcast({"type": "chats"})
    return {"status": "success"}

@router.get("/api/chats/{chat_id}/messages")
def get_messages(chat_id: int):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM global_messages WHERE chat_id=? ORDER BY id ASC", (chat_id,)); return [dict(r) for r in c.fetchall()]

@router.post("/api/chats/{chat_id}/messages")
async def post_message(chat_id: int, data: GlobalMessageData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("INSERT INTO global_messages (chat_id, user, role, text, time) VALUES (?, ?, ?, ?, ?)", (chat_id, data.user, data.role, data.text, time.strftime("%d.%m.%Y %H:%M"))); conn.commit()
    await manager.broadcast({"type": "chats"})
    return {"status": "success"}

@router.get("/api/emails")
def get_emails():
    try:
        mail = imaplib.IMAP4_SSL('imap.yandex.ru'); mail.login(SMTP_USER, SMTP_PASS); mail.select('inbox'); status, data = mail.search(None, 'ALL'); mail_ids = data[0].split()[-10:]; emails = []
        for i in reversed(mail_ids):
            status, msg_data = mail.fetch(i, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes): subject = subject.decode(encoding if encoding else 'utf-8', errors='ignore')
                    from_h, from_enc = decode_header(msg.get("From", ""))[0]
                    if isinstance(from_h, bytes): from_h = from_h.decode(from_enc if from_enc else 'utf-8', errors='ignore')
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain": body = part.get_payload(decode=True).decode(errors='ignore'); break
                    else: body = msg.get_payload(decode=True).decode(errors='ignore')
                    emails.append({"id": int(i), "subject": subject, "sender": from_h, "body": body[:200] + "..." if len(body)>200 else body})
        mail.logout(); return emails
    except Exception as e: return [{"id": 0, "subject": "Не удалось подключиться к почте", "sender": "Система", "body": str(e)}]

@router.get("/api/tasks")
def get_tasks():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM tasks ORDER BY id DESC")
    res = []
    for r in c.fetchall():
        d = dict(r); d['history'] = json.loads(d.get('history', '[]')) if d.get('history') else []
        res.append(d)
    return res

@router.post("/api/tasks")
async def create_task(data: TaskData):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    
    # Матрица авто-делегирования
    actual_executor = data.executor
    c.execute("SELECT abs_start, abs_end, deputy FROM users WHERE name=?", (data.executor,))
    u_row = c.fetchone()
    if u_row and u_row['deputy'] and u_row['abs_start'] and u_row['abs_end']:
        try:
            today = datetime.datetime.now()
            d_start = datetime.datetime.strptime(u_row['abs_start'], "%d.%m.%Y")
            d_end = datetime.datetime.strptime(u_row['abs_end'], "%d.%m.%Y")
            if d_start <= today <= d_end:
                actual_executor = f"{u_row['deputy']} (И.О. {data.executor})"
        except: pass

    # Отправка E-mail уведомления исполнителю
    c.execute("SELECT email FROM users WHERE name=?", (actual_executor.split(' (И.О.')[0].strip(),))
    exec_row = c.fetchone()
    if exec_row and exec_row['email']:
        mail_text = f"Здравствуйте!\n\nВам назначена новая задача в Korda CRM:\n\nТема: {data.title}\nДедлайн: {data.deadline}\nОписание: {data.description}\n\nС уважением,\nСистема уведомлений Korda CRM"
        asyncio.create_task(asyncio.to_thread(send_smtp_notification, exec_row['email'], f"Новое поручение: {data.title}", mail_text))

    c.execute("INSERT INTO tasks (id, title, description, author, executor, deadline, status, created_at, recurrence, priority, project_id, history) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (int(time.time() * 1000), data.title, data.description, data.author, actual_executor, data.deadline, 'active', time.strftime("%d.%m.%Y %H:%M"), data.recurrence, data.priority, data.project_id, '[]')); conn.commit()
    await manager.broadcast({"type": "tasks"})
    return {"status": "success"}

@router.put("/api/tasks/{task_id}")
async def update_task(task_id: int, data: TaskUpdate):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    if data.executor and data.history is not None:
        c.execute("UPDATE tasks SET status=?, executor=?, history=? WHERE id=?", (data.status, data.executor, json.dumps(data.history), task_id))
    else:
        c.execute("UPDATE tasks SET status=? WHERE id=?", (data.status, task_id))
    conn.commit()
    await manager.broadcast({"type": "tasks"})
    return {"status": "success"}