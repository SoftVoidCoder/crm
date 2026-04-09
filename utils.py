import smtplib
from email.message import EmailMessage
from fastapi import WebSocket
from typing import List
import json

SMTP_USER = "kordacrm@yandex.com"
SMTP_PASS = "dverktybmuypguxe" 
DEPT_EMAILS = {"Директор": "ilyu5haosipow@yandex.ru"}

def send_email_task(to_email: str, subject: str, body: str):
    try:
        msg = EmailMessage(); msg.set_content(body); msg['Subject'] = subject; msg['From'] = SMTP_USER; msg['To'] = to_email
        server = smtplib.SMTP_SSL('smtp.yandex.ru', 465); server.login(SMTP_USER, SMTP_PASS); server.send_message(msg); server.quit()
    except Exception as e: print(f"Ошибка email: {e}")

# === WEBSOCKET MANAGER ===
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        msg_str = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(msg_str)
            except Exception:
                pass

manager = ConnectionManager()