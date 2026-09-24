import base64
import email
import time
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import urlencode

import httpx

from services.mail_service import (
    EMAIL_PROVIDER_DEFAULTS,
    decode_mime_value,
    email_account_defaults,
    extract_plain_body,
    format_email_date,
    safe_text,
)


OAUTH_PROVIDERS = {
    "google": {
        "label": "Google",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
        ],
    },
    "microsoft": {
        "label": "Microsoft",
        "scopes": ["offline_access", "User.Read", "Mail.ReadWrite", "Mail.Send"],
    },
    "yandex": {
        "label": "Yandex",
        "auth_url": "https://oauth.yandex.ru/authorize",
        "token_url": "https://oauth.yandex.ru/token",
        "scopes": ["mail:imap_full", "mail:smtp"],
    },
}


class MailOAuthError(Exception):
    pass


def provider_credentials(provider: str, settings_module) -> dict:
    if provider == "google":
        return {
            "client_id": settings_module.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings_module.GOOGLE_OAUTH_CLIENT_SECRET,
        }
    if provider == "microsoft":
        tenant = settings_module.MICROSOFT_OAUTH_TENANT or "common"
        return {
            "client_id": settings_module.MICROSOFT_OAUTH_CLIENT_ID,
            "client_secret": settings_module.MICROSOFT_OAUTH_CLIENT_SECRET,
            "tenant": tenant,
            "auth_url": f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
            "token_url": f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        }
    if provider == "yandex":
        return {
            "client_id": settings_module.YANDEX_OAUTH_CLIENT_ID,
            "client_secret": settings_module.YANDEX_OAUTH_CLIENT_SECRET,
        }
    return {"client_id": "", "client_secret": ""}


def provider_status(settings_module) -> list[dict]:
    result = []
    for provider, meta in OAUTH_PROVIDERS.items():
        creds = provider_credentials(provider, settings_module)
        result.append(
            {
                "provider": provider,
                "label": meta["label"],
                "configured": bool(creds.get("client_id") and creds.get("client_secret")),
            }
        )
    return result


def build_redirect_uri(base_url: str, provider: str) -> str:
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/api/email/oauth/{provider}/callback"


def build_authorization_url(provider: str, *, state: str, redirect_uri: str, settings_module) -> str:
    if provider not in OAUTH_PROVIDERS:
        raise MailOAuthError("unsupported_provider")
    creds = provider_credentials(provider, settings_module)
    if not creds.get("client_id") or not creds.get("client_secret"):
        raise MailOAuthError("provider_not_configured")
    meta = OAUTH_PROVIDERS[provider]
    auth_url = creds.get("auth_url") or meta["auth_url"]
    params = {
        "client_id": creds["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if provider == "google":
        params.update(
            {
                "scope": " ".join(meta["scopes"]),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
            }
        )
    elif provider == "microsoft":
        params["scope"] = " ".join(meta["scopes"])
        params["response_mode"] = "query"
    elif provider == "yandex":
        params["scope"] = " ".join(meta["scopes"])
        params["force_confirm"] = "yes"
    return f"{auth_url}?{urlencode(params)}"


def exchange_code(provider: str, *, code: str, redirect_uri: str, settings_module) -> dict:
    creds = provider_credentials(provider, settings_module)
    meta = OAUTH_PROVIDERS[provider]
    token_url = creds.get("token_url") or meta["token_url"]
    data = {
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=30) as client:
        response = client.post(token_url, data=data)
    if response.status_code >= 400:
        raise MailOAuthError(f"token_exchange_failed:{response.text[:300]}")
    payload = response.json()
    payload["expires_at"] = int(time.time()) + int(payload.get("expires_in") or 3600) - 60
    return payload


def refresh_access_token(provider: str, account: dict, *, decrypt_secret, encrypt_secret, settings_module, save_token_fn=None) -> str:
    access_token = decrypt_secret(account.get("oauth_access_token") or "")
    expires_at = int(account.get("oauth_expires_at") or 0)
    if access_token and expires_at > int(time.time()) + 90:
        return access_token

    refresh_token = decrypt_secret(account.get("oauth_refresh_token") or "")
    if not refresh_token:
        raise MailOAuthError("missing_refresh_token")
    creds = provider_credentials(provider, settings_module)
    meta = OAUTH_PROVIDERS[provider]
    token_url = creds.get("token_url") or meta["token_url"]
    data = {
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if provider == "microsoft":
        data["scope"] = " ".join(meta["scopes"])
    with httpx.Client(timeout=30) as client:
        response = client.post(token_url, data=data)
    if response.status_code >= 400:
        raise MailOAuthError(f"token_refresh_failed:{response.text[:300]}")
    payload = response.json()
    access_token = payload.get("access_token") or ""
    expires_at = int(time.time()) + int(payload.get("expires_in") or 3600) - 60
    if save_token_fn:
        save_token_fn(account["id"], encrypt_secret(access_token), expires_at)
    return access_token


def fetch_oauth_identity(provider: str, token_payload: dict) -> dict:
    access_token = token_payload.get("access_token") or ""
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=30, headers=headers) as client:
        if provider == "google":
            response = client.get("https://gmail.googleapis.com/gmail/v1/users/me/profile")
            if response.status_code >= 400:
                raise MailOAuthError(f"profile_failed:{response.text[:300]}")
            data = response.json()
            return {"address": data.get("emailAddress") or "", "provider_account_id": data.get("emailAddress") or ""}
        if provider == "microsoft":
            response = client.get("https://graph.microsoft.com/v1.0/me")
            if response.status_code >= 400:
                raise MailOAuthError(f"profile_failed:{response.text[:300]}")
            data = response.json()
            address = data.get("mail") or data.get("userPrincipalName") or ""
            return {"address": address, "provider_account_id": data.get("id") or address}
        if provider == "yandex":
            response = client.get("https://login.yandex.ru/info?format=json")
            if response.status_code >= 400:
                raise MailOAuthError(f"profile_failed:{response.text[:300]}")
            data = response.json()
            address = data.get("default_email") or ""
            if not address and data.get("emails"):
                address = data["emails"][0]
            return {"address": address, "provider_account_id": data.get("id") or address}
    raise MailOAuthError("unsupported_provider")


def build_oauth_account_payload(provider: str, identity: dict, token_payload: dict, *, encrypt_secret) -> dict:
    address = safe_text(identity.get("address"))
    defaults = email_account_defaults(address)
    provider_defaults = EMAIL_PROVIDER_DEFAULTS.get("yandex" if provider == "yandex" else "gmail", {})
    if provider == "microsoft":
        provider_defaults = EMAIL_PROVIDER_DEFAULTS["outlook"]
    return {
        "label": defaults.get("label") or address,
        "address": address,
        "login": address,
        "password": "",
        "imap_host": provider_defaults.get("imap_host", ""),
        "imap_port": provider_defaults.get("imap_port", 993),
        "smtp_host": provider_defaults.get("smtp_host", ""),
        "smtp_port": provider_defaults.get("smtp_port", 465),
        "smtp_login": address,
        "smtp_password": "",
        "inbox_folder": provider_defaults.get("inbox_folder", "INBOX"),
        "archive_folder": provider_defaults.get("archive_folder", "Archive"),
        "auth_type": "oauth",
        "oauth_provider": provider,
        "oauth_access_token": encrypt_secret(token_payload.get("access_token") or ""),
        "oauth_refresh_token": encrypt_secret(token_payload.get("refresh_token") or ""),
        "oauth_expires_at": int(token_payload.get("expires_at") or 0),
        "oauth_scope": token_payload.get("scope") or " ".join(OAUTH_PROVIDERS[provider]["scopes"]),
        "provider_account_id": safe_text(identity.get("provider_account_id")),
    }


def _gmail_header(headers: list[dict], name: str) -> str:
    for item in headers or []:
        if str(item.get("name") or "").lower() == name.lower():
            return item.get("value") or ""
    return ""


def _decode_base64url(value: str) -> bytes:
    raw = (value or "").encode("utf-8")
    raw += b"=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw)


def _gmail_plain_body(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    parts = list(payload.get("parts") or [])
    if not parts:
        data = payload.get("body", {}).get("data") or ""
        return _decode_base64url(data).decode("utf-8", errors="ignore").strip() if data else ""
    stack = parts[:]
    while stack:
        part = stack.pop(0)
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return _decode_base64url(part["body"]["data"]).decode("utf-8", errors="ignore").strip()
        stack.extend(part.get("parts") or [])
    return ""


def sync_google_account(account: dict, *, access_token: str, batch_size: int, save_message_fn) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=40, headers=headers) as client:
        listing = client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params={"maxResults": batch_size, "labelIds": "INBOX"},
        )
        if listing.status_code >= 400:
            raise MailOAuthError(f"gmail_list_failed:{listing.text[:300]}")
        messages = listing.json().get("messages") or []
        for item in messages:
            message_id = item.get("id")
            if not message_id:
                continue
            response = client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                params={"format": "full"},
            )
            if response.status_code >= 400:
                continue
            payload = response.json()
            headers_list = payload.get("payload", {}).get("headers") or []
            sender = decode_mime_value(_gmail_header(headers_list, "From")) or "Неизвестный отправитель"
            body_text = _gmail_plain_body(payload.get("payload") or "")
            save_message_fn(
                {
                    "account_id": account["id"],
                    "uid": message_id,
                    "folder": "INBOX",
                    "subject": decode_mime_value(_gmail_header(headers_list, "Subject")) or "Без темы",
                    "sender": sender,
                    "sender_email": parseaddr(sender)[1],
                    "body_text": body_text,
                    "received_at": format_email_date(_gmail_header(headers_list, "Date")),
                    "is_read": 1 if "UNREAD" not in payload.get("labelIds", []) else 0,
                    "is_archived": 0,
                    "message_id_header": (_gmail_header(headers_list, "Message-ID") or "")[:500],
                    "reply_to_email": parseaddr(_gmail_header(headers_list, "Reply-To") or sender)[1],
                }
            )
    return {"status": "success"}


def sync_microsoft_account(account: dict, *, access_token: str, batch_size: int, save_message_fn) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "$top": min(max(int(batch_size or 40), 1), 100),
        "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,internetMessageId,replyTo",
        "$orderby": "receivedDateTime DESC",
    }
    with httpx.Client(timeout=40, headers=headers) as client:
        response = client.get("https://graph.microsoft.com/v1.0/me/mailFolders/Inbox/messages", params=params)
        if response.status_code >= 400:
            raise MailOAuthError(f"graph_list_failed:{response.text[:300]}")
        for item in response.json().get("value") or []:
            sender_info = ((item.get("from") or {}).get("emailAddress") or {})
            sender = sender_info.get("name") or sender_info.get("address") or "Неизвестный отправитель"
            reply_to = ""
            reply_items = item.get("replyTo") or []
            if reply_items:
                reply_to = ((reply_items[0] or {}).get("emailAddress") or {}).get("address") or ""
            save_message_fn(
                {
                    "account_id": account["id"],
                    "uid": item.get("id") or "",
                    "folder": "INBOX",
                    "subject": item.get("subject") or "Без темы",
                    "sender": sender,
                    "sender_email": sender_info.get("address") or "",
                    "body_text": item.get("bodyPreview") or "",
                    "received_at": item.get("receivedDateTime") or "",
                    "is_read": 1 if item.get("isRead") else 0,
                    "is_archived": 0,
                    "message_id_header": (item.get("internetMessageId") or "")[:500],
                    "reply_to_email": reply_to or sender_info.get("address") or "",
                }
            )
    return {"status": "success"}


def build_raw_email_message(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8").rstrip("=")
