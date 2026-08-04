from fastapi import APIRouter, Body, Request

from permissions import has_permission, require_approved_user
from services.bitrix24_service import (
    _bitrix_call,
    bitrix24_config_status,
    import_selected_bitrix24_clients,
    save_bitrix24_webhook_url,
    search_bitrix24_clients,
    sync_bitrix24_to_outreach,
)


router = APIRouter()


def _can_manage_bitrix(actor: dict) -> bool:
    return bool(actor) and (
        actor.get("role") == "Директор"
        or actor.get("role") == "Р”РёСЂРµРєС‚РѕСЂ"
        or has_permission(actor, "integrations", "manage")
        or has_permission(actor, "integrations", "update")
    )


@router.get("/api/integrations/bitrix24/status")
def get_bitrix24_status(request: Request):
    actor = require_approved_user(request)
    if not _can_manage_bitrix(actor):
        return {"error": "forbidden"}
    return {"status": "success", **bitrix24_config_status()}


@router.post("/api/integrations/bitrix24/test")
def test_bitrix24_connection(request: Request, payload: dict = Body(default={})):
    actor = require_approved_user(request)
    if not _can_manage_bitrix(actor):
        return {"error": "forbidden"}
    webhook_url = str((payload or {}).get("webhook_url") or "").strip()
    try:
        profile = _bitrix_call(webhook_url, "profile", {})
    except Exception as exc:
        return {"status": "failed", "error": str(exc)[:300], **bitrix24_config_status(webhook_url)}
    return {"status": "success", "profile": profile.get("result") or profile, **bitrix24_config_status(webhook_url)}


@router.post("/api/integrations/bitrix24/configure")
def configure_bitrix24(request: Request, payload: dict = Body(default={})):
    actor = require_approved_user(request)
    if not _can_manage_bitrix(actor):
        return {"error": "forbidden"}
    webhook_url = str((payload or {}).get("webhook_url") or "").strip()
    try:
        profile = _bitrix_call(webhook_url, "profile", {})
    except Exception as exc:
        return {"status": "failed", "error": str(exc)[:300], **bitrix24_config_status(webhook_url)}
    saved = save_bitrix24_webhook_url(webhook_url, actor)
    return {**saved, "profile": profile.get("result") or profile}


@router.post("/api/integrations/bitrix24/sync")
def sync_bitrix24(request: Request, payload: dict = Body(default={})):
    actor = require_approved_user(request)
    if not _can_manage_bitrix(actor):
        return {"error": "forbidden"}
    webhook_url = str((payload or {}).get("webhook_url") or "").strip()
    limit = int((payload or {}).get("limit") or 0) or None
    try:
        result = sync_bitrix24_to_outreach(webhook_url=webhook_url, actor=actor, limit=limit)
    except Exception as exc:
        return {"status": "failed", "error": str(exc)[:500], **bitrix24_config_status(webhook_url)}
    return result


@router.post("/api/integrations/bitrix24/search")
def search_bitrix24(request: Request, payload: dict = Body(default={})):
    actor = require_approved_user(request)
    if not _can_manage_bitrix(actor):
        return {"error": "forbidden"}
    webhook_url = str((payload or {}).get("webhook_url") or "").strip()
    query = str((payload or {}).get("query") or "").strip()
    limit = int((payload or {}).get("limit") or 20)
    try:
        return search_bitrix24_clients(query=query, limit=limit, webhook_url=webhook_url)
    except Exception as exc:
        return {"status": "failed", "error": str(exc)[:500], **bitrix24_config_status(webhook_url)}


@router.post("/api/integrations/bitrix24/import_selected")
def import_selected_bitrix24(request: Request, payload: dict = Body(default={})):
    actor = require_approved_user(request)
    if not _can_manage_bitrix(actor):
        return {"error": "forbidden"}
    webhook_url = str((payload or {}).get("webhook_url") or "").strip()
    items = (payload or {}).get("items") or []
    if not isinstance(items, list):
        return {"status": "failed", "error": "items_required", "message": "Выберите клиентов из Bitrix24."}
    try:
        return import_selected_bitrix24_clients(items=items, actor=actor, webhook_url=webhook_url)
    except Exception as exc:
        return {"status": "failed", "error": str(exc)[:500], **bitrix24_config_status(webhook_url)}
