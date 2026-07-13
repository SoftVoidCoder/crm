import os

from utils import load_env_file


load_env_file()


APP_ENV = os.getenv("KORDA_ENV", "development").strip().lower() or "development"
APP_SECRET = os.getenv("KORDA_APP_SECRET", "").strip()
PUBLIC_BASE_URL = os.getenv("KORDA_PUBLIC_BASE_URL", "").strip().rstrip("/")
DIRECTOR_EMAIL = os.getenv("KORDA_DIRECTOR_EMAIL", "").strip()
DEFAULT_ADMIN_LOGIN = os.getenv("KORDA_DEFAULT_ADMIN_LOGIN", "Admin").strip() or "Admin"
DEFAULT_ADMIN_PASSWORD = os.getenv("KORDA_DEFAULT_ADMIN_PASSWORD", "").strip()
COOKIE_SECURE = os.getenv("KORDA_COOKIE_SECURE", "0") == "1"
BACKUP_RETENTION_COUNT = max(3, int(os.getenv("KORDA_BACKUP_RETENTION_COUNT", "14")))
MAIL_SYNC_BATCH = max(10, int(os.getenv("KORDA_MAIL_SYNC_BATCH", "40")))
MAIL_IMAP_TIMEOUT = max(5, int(os.getenv("KORDA_MAIL_IMAP_TIMEOUT", "20")))
MAIL_SMTP_TIMEOUT = max(5, int(os.getenv("KORDA_MAIL_SMTP_TIMEOUT", "20")))
DADATA_TOKEN = os.getenv("KORDA_DADATA_TOKEN", "").strip()
DADATA_SECRET = os.getenv("KORDA_DADATA_SECRET", "").strip()
KORDA_GEMINI_API_KEYS = os.getenv("KORDA_GEMINI_API_KEYS", "").strip()
KORDA_AI_MODEL = os.getenv("KORDA_AI_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"
KORDA_AI_TIMEOUT_SECONDS = max(5, int(os.getenv("KORDA_AI_TIMEOUT_SECONDS", "8")))


def using_insecure_defaults() -> bool:
    return not APP_SECRET or APP_SECRET == "change-me-to-a-long-random-string"
