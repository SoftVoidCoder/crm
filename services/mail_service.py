import imaplib
import re
import smtplib
from email.header import decode_header
from email.utils import parsedate_to_datetime


EMAIL_PROVIDER_DEFAULTS = {
    "yandex": {
        "imap_host": "imap.yandex.ru",
        "imap_port": 993,
        "smtp_host": "smtp.yandex.ru",
        "smtp_port": 465,
        "inbox_folder": "INBOX",
        "archive_folder": "Archive",
    },
    "gmail": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "inbox_folder": "INBOX",
        "archive_folder": "[Gmail]/All Mail",
    },
    "outlook": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 465,
        "inbox_folder": "INBOX",
        "archive_folder": "Archive",
    },
    "mailru": {
        "imap_host": "imap.mail.ru",
        "imap_port": 993,
        "smtp_host": "smtp.mail.ru",
        "smtp_port": 465,
        "inbox_folder": "INBOX",
        "archive_folder": "Archive",
    },
}


def safe_text(value: str, fallback: str = "") -> str:
    return (value or fallback or "").strip()


def email_provider_key(address: str) -> str:
    normalized = safe_text(address)
    domain = normalized.lower().split("@")[-1]
    if not domain or "@" not in normalized:
        return ""
    if domain in {"yandex.ru", "ya.ru", "yandex.com", "yandex.kz", "yandex.by", "yandex.ua", "yandex.uz"}:
        return "yandex"
    if domain == "gmail.com":
        return "gmail"
    if domain in {"outlook.com", "office365.com", "hotmail.com", "live.com", "msn.com"}:
        return "outlook"
    if domain in {"mail.ru", "bk.ru", "inbox.ru", "list.ru"}:
        return "mailru"
    return ""


def email_account_defaults(address: str) -> dict:
    provider = email_provider_key(address)
    defaults = EMAIL_PROVIDER_DEFAULTS.get(provider, EMAIL_PROVIDER_DEFAULTS["yandex"]).copy()
    local_part = safe_text(address).split("@", 1)[0]
    defaults["label"] = local_part or safe_text(address)
    defaults["login"] = safe_text(address)
    defaults["smtp_login"] = safe_text(address)
    return defaults


def normalize_email_account_payload(data, existing: dict | None = None) -> dict:
    existing = existing or {}
    address = safe_text(getattr(data, "address", None), existing.get("address", ""))
    defaults = email_account_defaults(address or existing.get("address", ""))
    label = safe_text(getattr(data, "label", None), defaults["label"] or existing.get("label", ""))
    login = safe_text(getattr(data, "login", None), defaults["login"] or address or existing.get("login", ""))
    smtp_login = safe_text(getattr(data, "smtp_login", None), login)
    imap_host = safe_text(getattr(data, "imap_host", None), defaults["imap_host"] or existing.get("imap_host", "imap.yandex.ru"))
    smtp_host = safe_text(getattr(data, "smtp_host", None), defaults["smtp_host"] or existing.get("smtp_host", "smtp.yandex.ru"))
    inbox_folder = safe_text(getattr(data, "inbox_folder", None), defaults["inbox_folder"] or existing.get("inbox_folder", "INBOX")) or "INBOX"
    archive_folder = safe_text(getattr(data, "archive_folder", None), defaults["archive_folder"] or existing.get("archive_folder", "Archive")) or "Archive"
    password = safe_text(getattr(data, "password", None), existing.get("password", ""))
    smtp_password = safe_text(getattr(data, "smtp_password", None), existing.get("smtp_password", "")) or password

    return {
        "label": label or address,
        "address": address,
        "login": login or address,
        "password": password,
        "imap_host": imap_host,
        "imap_port": int(getattr(data, "imap_port", None) or defaults["imap_port"]),
        "smtp_host": smtp_host,
        "smtp_port": int(getattr(data, "smtp_port", None) or defaults["smtp_port"]),
        "smtp_login": smtp_login or login or address,
        "smtp_password": smtp_password,
        "inbox_folder": inbox_folder,
        "archive_folder": archive_folder,
        "is_default": int(getattr(data, "is_default", 0)),
        "is_active": int(getattr(data, "is_active", 0)),
    }


def decode_mime_value(value):
    if not value:
        return ""
    chunks = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            chunks.append(part.decode(encoding or "utf-8", errors="ignore"))
        else:
            chunks.append(str(part))
    return "".join(chunks).strip()


def extract_plain_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/plain" and "attachment" not in disposition.lower():
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="ignore").strip()
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="ignore").strip()


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Zа-яА-Я0-9._-]+", "_", value or "attachment")
    return cleaned[:120] or "attachment"


def format_email_date(raw_date):
    if not raw_date:
        return ""
    try:
        return parsedate_to_datetime(raw_date).astimezone().strftime("%d.%m.%Y %H:%M")
    except Exception:
        return raw_date


def parse_imap_list_line(line: bytes | str):
    text = line.decode("utf-8", errors="ignore") if isinstance(line, bytes) else str(line or "")
    match = re.match(r'^\((?P<flags>.*)\)\s+"(?P<sep>.*)"\s+"(?P<name>.*)"\s*$', text)
    if not match:
        return {"flags": "", "name": text.strip()}
    return {"flags": match.group("flags"), "name": match.group("name")}


def find_imap_folder_by_flag(mail, flag: str, fallback: str = "Archive") -> str:
    try:
        status, boxes = mail.list()
        if status != "OK":
            return fallback
        for box in boxes or []:
            parsed = parse_imap_list_line(box)
            flags = parsed.get("flags", "")
            name = parsed.get("name", "")
            if flag in flags and name:
                return name
    except Exception:
        pass
    return fallback


def quote_imap_mailbox(mail, mailbox: str) -> str:
    mailbox = mailbox or ""
    try:
        return mail._quote(mailbox)
    except Exception:
        return mailbox


def connect_imap_account(account: dict, *, decrypt_secret, imap_timeout: int):
    mailbox = imaplib.IMAP4_SSL(
        account["imap_host"],
        int(account.get("imap_port") or 993),
        timeout=imap_timeout,
    )
    mailbox.login(account["login"], decrypt_secret(account["password"]))
    return mailbox


def smtp_credentials(
    account: dict,
    *,
    decrypt_secret,
    default_host,
    default_port,
    default_user,
    default_pass,
):
    return (
        account.get("smtp_host") or default_host,
        int(account.get("smtp_port") or default_port),
        account.get("smtp_login") or account.get("login") or account.get("address") or default_user,
        decrypt_secret(account.get("smtp_password") or account.get("password") or "") or default_pass,
        account.get("address") or default_user,
    )


def test_email_account_connection(account: dict, *, connect_imap_account_fn, smtp_credentials_fn, smtp_timeout: int, logger):
    result = {
        "status": "success",
        "imap": {"ok": False, "error": ""},
        "smtp": {"ok": False, "error": ""},
    }

    mail = None
    try:
        mail = connect_imap_account_fn(account)
        result["imap"]["ok"] = True
    except Exception as exc:
        result["status"] = "error"
        result["imap"]["error"] = str(exc)
        logger.warning("IMAP test failed for %s: %s", account.get("address"), exc)
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass

    server = None
    try:
        smtp_host, smtp_port, smtp_login, smtp_pass, _sender_address = smtp_credentials_fn(account)
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=smtp_timeout)
        server.login(smtp_login, smtp_pass)
        server.noop()
        server.quit()
        server = None
        result["smtp"]["ok"] = True
    except Exception as exc:
        result["status"] = "error"
        result["smtp"]["error"] = str(exc)
        logger.warning("SMTP test failed for %s: %s", account.get("address"), exc)
    finally:
        if server is not None:
            try:
                server.close()
            except Exception:
                pass

    return result
