import base64
import hashlib
import hmac
import re
import os
import secrets
import smtplib
from email.message import EmailMessage
from fastapi import WebSocket
from typing import List
import json
from app_logging import get_logger


def load_env_file(path: str = ".env"):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


load_env_file()

SMTP_USER = os.getenv("KORDA_SMTP_USER", "")
SMTP_PASS = os.getenv("KORDA_SMTP_PASS", "")
SMTP_HOST = os.getenv("KORDA_SMTP_HOST", "smtp.yandex.ru")
SMTP_PORT = int(os.getenv("KORDA_SMTP_PORT", "465"))
COOKIE_SECURE = os.getenv("KORDA_COOKIE_SECURE", "0") == "1"
DEPT_EMAILS = {"Директор": os.getenv("KORDA_DIRECTOR_EMAIL", "")}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
APP_SECRET = os.getenv("KORDA_APP_SECRET", "")
logger = get_logger("utils")


def hash_password(password: str, iterations: int = 310000) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii")
    )


def is_password_hashed(password: str) -> bool:
    return isinstance(password, str) and password.startswith("pbkdf2_sha256$")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    if not is_password_hashed(password_hash):
        return hmac.compare_digest(password_hash, password or "")

    try:
        _algo, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        digest = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        candidate = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(candidate, digest)
    except Exception:
        return False


def generate_temporary_password(length: int = 12) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(normalize_email(email)))


def validate_password_strength(password: str) -> str:
    password = password or ""
    if len(password) < 8:
        return "Пароль должен быть не короче 8 символов"
    if not any(ch.isalpha() for ch in password):
        return "Пароль должен содержать хотя бы одну букву"
    if not any(ch.isdigit() for ch in password):
        return "Пароль должен содержать хотя бы одну цифру"
    return ""


def _qr_signing_secret() -> str:
    return APP_SECRET or "korda-qr-fallback-secret"


def make_document_qr_token(document_id: int) -> str:
    payload = f"document:{int(document_id or 0)}".encode("utf-8")
    digest = hmac.new(_qr_signing_secret().encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return digest[:32]


def verify_document_qr_token(document_id: int, token: str) -> bool:
    candidate = str(token or "").strip()
    if not candidate:
        return False
    expected = make_document_qr_token(document_id)
    return hmac.compare_digest(expected, candidate)


def _derive_secret_key(salt: bytes, iterations: int = 200000) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", APP_SECRET.encode("utf-8"), salt, iterations, dklen=32)


def is_secret_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith("kordaenc$")


def encrypt_secret(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    if is_secret_encrypted(value):
        return value
    salt = secrets.token_bytes(16)
    key = _derive_secret_key(salt)
    raw = value.encode("utf-8")
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    mac = hmac.new(key, salt + encrypted, hashlib.sha256).digest()
    return "kordaenc${}${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(encrypted).decode("ascii"),
        base64.urlsafe_b64encode(mac).decode("ascii"),
    )


def decrypt_secret(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    if not is_secret_encrypted(value):
        return value
    try:
        _prefix, salt_b64, encrypted_b64, mac_b64 = value.split("$", 3)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        encrypted = base64.urlsafe_b64decode(encrypted_b64.encode("ascii"))
        mac = base64.urlsafe_b64decode(mac_b64.encode("ascii"))
        key = _derive_secret_key(salt)
        expected_mac = hmac.new(key, salt + encrypted, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected_mac):
            return ""
        raw = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted))
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""

def send_email_task(to_email: str, subject: str, body: str):
    if not SMTP_USER or not SMTP_PASS:
        logger.warning("SMTP is not configured, email was skipped for %s", to_email)
        return False
    try:
        msg = EmailMessage(); msg.set_content(body); msg['Subject'] = subject; msg['From'] = SMTP_USER; msg['To'] = to_email
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT); server.login(SMTP_USER, SMTP_PASS); server.send_message(msg); server.quit()
        return True
    except Exception as e:
        logger.exception("SMTP email send failed: %s", e)
        return False

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
