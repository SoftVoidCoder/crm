from fastapi import Request
from database import create_user_session, delete_user_session, get_session_user
from settings import COOKIE_SECURE

SESSION_COOKIE_NAME = "korda_session_id"
SESSION_TTL_SECONDS = 60 * 60 * 12


def _request_meta(request: Request):
    ip_address = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")[:500]
    return ip_address, user_agent


def issue_session_for_user(request: Request, user_email: str) -> str:
    ip_address, user_agent = _request_meta(request)
    return create_user_session(
        user_email=user_email,
        ip_address=ip_address,
        user_agent=user_agent,
        ttl_seconds=SESSION_TTL_SECONDS,
    )


def get_request_user(request: Request):
    session_id = request.cookies.get(SESSION_COOKIE_NAME, "")
    return get_session_user(session_id)


def destroy_request_session(request: Request):
    session_id = request.cookies.get(SESSION_COOKIE_NAME, "")
    if session_id:
        delete_user_session(session_id)


def apply_session_cookie(response, session_id: str):
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )


def clear_session_cookie(response):
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
