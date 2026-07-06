from fastapi import APIRouter, Request

from database import audit_log
from permissions import has_permission, require_approved_user
from schemas import OneCBatchExportData, OneCConnectorCredentialData, OneCConnectorData
from services.one_c_connector_service import (
    check_one_c_connector_health,
    create_or_update_connector,
    enqueue_one_c_export,
    list_connectors,
    list_exchange_messages,
    list_external_objects,
    one_c_readiness_summary,
    process_due_1c_sync_queue,
    save_connector_credential,
)


router = APIRouter()


def _can_manage_1c(actor: dict) -> bool:
    return bool(actor and (actor.get("role") == "Директор" or has_permission(actor, "finance", "sync_1c")))


@router.get("/api/integration/1c/connectors")
def get_one_c_connectors(request: Request, limit: int = 100):
    actor = require_approved_user(request)
    if not _can_manage_1c(actor):
        return {"error": "forbidden"}
    return {"status": "success", "connectors": list_connectors(limit)}


@router.post("/api/integration/1c/connectors")
def save_one_c_connector(data: OneCConnectorData, request: Request):
    actor = require_approved_user(request)
    if not _can_manage_1c(actor):
        return {"error": "forbidden"}
    payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
    result = create_or_update_connector(payload, actor.get("email", ""))
    audit_log(
        "one_c_connector_saved",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_connector",
        entity_id=str(result.get("id", "")),
        details={"provider_name": data.provider_name, "transport": data.transport or data.mode or data.settings.get("transport", "demo")},
    )
    return result


@router.post("/api/integration/1c/connectors/{connector_id}/credentials")
def save_one_c_connector_credentials(connector_id: int, data: OneCConnectorCredentialData, request: Request):
    actor = require_approved_user(request)
    if not _can_manage_1c(actor):
        return {"error": "forbidden"}
    payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
    result = save_connector_credential(connector_id, payload, actor.get("email", ""))
    audit_log(
        "one_c_connector_credentials_saved",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_connector",
        entity_id=str(connector_id),
        details={"credential_kind": data.credential_kind, "has_secret_ref": bool(data.secret_ref)},
    )
    return result


@router.get("/api/integration/1c/connectors/{connector_id}/health")
def get_one_c_connector_health(connector_id: int, request: Request):
    actor = require_approved_user(request)
    if not _can_manage_1c(actor):
        return {"error": "forbidden"}
    result = check_one_c_connector_health(connector_id)
    audit_log(
        "one_c_connector_health_checked",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_connector",
        entity_id=str(connector_id),
        details={"ready": result.get("ready"), "transport": result.get("transport"), "http_status": result.get("http_status")},
    )
    return result


@router.get("/api/integration/1c/readiness")
def get_one_c_readiness(request: Request):
    actor = require_approved_user(request)
    if not _can_manage_1c(actor):
        return {"error": "forbidden"}
    return one_c_readiness_summary()


@router.post("/api/integration/1c/transport/process")
def process_one_c_transport_queue(request: Request, limit: int = 40):
    actor = require_approved_user(request)
    if not _can_manage_1c(actor):
        return {"error": "forbidden"}
    result = process_due_1c_sync_queue(limit)
    audit_log(
        "one_c_transport_queue_processed",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="integration_sync_queue",
        entity_id="1C-TRANSPORT",
        details=result,
    )
    return {"status": "success", **result}


@router.post("/api/integration/1c/export_batch")
def queue_one_c_export_batch(data: OneCBatchExportData, request: Request):
    actor = require_approved_user(request)
    if not _can_manage_1c(actor):
        return {"error": "forbidden"}
    queued = []
    failed = []
    for entity_id in data.entity_ids or []:
        outcome = enqueue_one_c_export(data.entity_type, entity_id, actor.get("email", ""), data.connector_id, data.idempotency_key)
        if outcome.get("status") == "success":
            queued.append(outcome)
        else:
            failed.append(outcome)
    result = {"status": "success", "queued": len(queued), "failed": len(failed), "items": queued[:80], "errors": failed[:50]}
    audit_log(
        "one_c_export_batch_queued",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type=data.entity_type or "integration_batch",
        entity_id=",".join(str(item) for item in (data.entity_ids or [])[:20]),
        details={"queued": len(queued), "failed": len(failed), "connector_id": data.connector_id},
    )
    return result


@router.get("/api/integration/1c/external_objects")
def get_one_c_external_objects(request: Request, limit: int = 120, entity_type: str = "", entity_id: str = ""):
    actor = require_approved_user(request)
    if not _can_manage_1c(actor):
        return {"error": "forbidden"}
    return {"status": "success", "items": list_external_objects(limit, entity_type, entity_id)}


@router.get("/api/integration/1c/exchange_messages")
def get_one_c_exchange_messages(request: Request, limit: int = 120, entity_type: str = "", entity_id: str = ""):
    actor = require_approved_user(request)
    if not _can_manage_1c(actor):
        return {"error": "forbidden"}
    return {"status": "success", "items": list_exchange_messages(limit, entity_type, entity_id)}
