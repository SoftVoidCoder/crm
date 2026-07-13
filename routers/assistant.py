from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth_security import get_request_user
from database import audit_log
from services.gemini_service import GeminiUnavailableError, ask_gemini


router = APIRouter()


class AssistantAskData(BaseModel):
    question: str = ""
    context: dict = {}


@router.post("/api/assistant/ask")
def ask_assistant(data: AssistantAskData, request: Request):
    actor = get_request_user(request)
    if not actor or actor.get("status") != "approved":
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    question = (data.question or "").strip()
    if not question:
        return {"error": "empty_question"}
    try:
        result = ask_gemini(question, data.context or {})
        audit_log(
            "assistant_ai_answered",
            actor_email=actor.get("email", ""),
            actor_name=actor.get("name", ""),
            entity_type="assistant",
            entity_id="gemini",
            details={"model": result.get("model"), "key_index": result.get("key_index")},
        )
        return {
            "status": "success",
            "answer": result.get("answer", ""),
            "model": result.get("model", ""),
            "provider": result.get("provider", "gemini"),
        }
    except GeminiUnavailableError:
        return JSONResponse(status_code=503, content={"error": "ai_unavailable"})
    except Exception:
        return JSONResponse(status_code=500, content={"error": "assistant_failed"})
