import json
import time
from dataclasses import dataclass

import httpx

from app_logging import get_logger
from settings import KORDA_AI_MODEL, KORDA_AI_TIMEOUT_SECONDS, KORDA_GEMINI_API_KEYS


logger = get_logger("gemini_service")


class GeminiUnavailableError(RuntimeError):
    pass


@dataclass
class GeminiAttempt:
    key_index: int
    status_code: int = 0
    error: str = ""
    latency_ms: int = 0


def _gemini_keys() -> list[str]:
    raw = KORDA_GEMINI_API_KEYS or ""
    normalized = raw.replace("\n", ",").replace(";", ",")
    keys = []
    for item in normalized.split(","):
        value = item.strip()
        if value and value not in keys:
            keys.append(value)
    return keys


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        return ""
    chunks: list[str] = []
    for candidate in candidates:
        parts = ((candidate or {}).get("content") or {}).get("parts") or []
        if not isinstance(parts, list):
            continue
        for part in parts:
            text = (part or {}).get("text", "")
            if text:
                chunks.append(str(text))
    return "\n".join(chunks).strip()


def _safe_context(context: dict | None) -> str:
    if not isinstance(context, dict):
        return "{}"
    try:
        return json.dumps(context, ensure_ascii=False, separators=(",", ":"))[:24000]
    except Exception:
        return "{}"


def ask_gemini(question: str, context: dict | None = None) -> dict:
    keys = _gemini_keys()
    if not keys:
        raise GeminiUnavailableError("gemini_keys_not_configured")

    prompt = f"""
Ты встроенный ИИ-помощник Korda CRM. Твоя область работы строго ограничена CRM-системой и рабочими процессами компании.

Разрешённые темы:
- как пользоваться Korda CRM;
- где найти раздел, карточку, документ, проект, клиента, задачу, платёж, отчёт или настройку;
- какие у пользователя сроки, задачи, поручения, согласования, встречи, уведомления и просрочки;
- что происходит по проектам, договорам, документам, финансам, складу, производству, сервису, менеджерам, базе развития и директорской панели;
- как выполнить действие внутри системы: создать, загрузить, назначить, согласовать, отфильтровать, экспортировать, проверить, перевести в лид и т.д.;
- краткие управленческие выводы только на основе CRM-контекста.

Запрещённые темы:
- бытовые, учебные, развлекательные и общие вопросы не про Korda CRM;
- внешние знания, философия, история, природа, еда, медицина, право, новости, программирование вне этой CRM;
- любые ответы, где нужно выдумывать факты не из CRM-контекста.

Если вопрос вне Korda CRM, не отвечай по сути вопроса. Ответь коротко:
"Я отвечаю только по Korda CRM: разделы, задачи, сроки, документы, проекты, клиенты, финансы и рабочие процессы. Сформулируй вопрос по системе."

Если вопрос связан с Korda CRM, отвечай на русском, строго и по делу. Используй только CRM-контекст ниже и вопрос пользователя.
Если данных не хватает, прямо скажи, какой раздел CRM нужно открыть или какие данные загрузить.
Не выдумывай суммы, статусы, документы, клиентов, сроки, ответственных и даты.
Если в CRM-контексте есть блок navigation, используй только эти реальные названия и пути разделов. Не заменяй их похожими словами и не придумывай пункты меню.
Различай:
- "Поручения" — раздел задач и сроков;
- "Мессенджер" → вкладка "Корпоративные чаты" — общение и чаты;
- "Сделки" — карточки сделок и pipeline;
- "Продажи" — счета, акты, УПД, отгрузка и реализация.

Вопрос пользователя:
{question.strip()[:4000]}

CRM-контекст JSON:
{_safe_context(context)}
""".strip()
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{KORDA_AI_MODEL}:generateContent"
    request_body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "maxOutputTokens": 1200,
        },
    }
    attempts: list[GeminiAttempt] = []
    timeout = httpx.Timeout(float(KORDA_AI_TIMEOUT_SECONDS), connect=5.0)

    for index, api_key in enumerate(keys):
        started = time.time()
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    endpoint,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=request_body,
                )
            latency_ms = int((time.time() - started) * 1000)
            if response.status_code == 200:
                payload = response.json()
                text = _extract_text(payload)
                if text:
                    return {
                        "answer": text,
                        "model": KORDA_AI_MODEL,
                        "provider": "gemini",
                        "key_index": index + 1,
                        "attempts": [item.__dict__ for item in attempts],
                    }
                attempts.append(GeminiAttempt(index + 1, response.status_code, "empty_response", latency_ms))
                continue
            error_text = response.text[:400]
            attempts.append(GeminiAttempt(index + 1, response.status_code, error_text, latency_ms))
            if response.status_code in {400, 401, 403}:
                logger.warning("Gemini key %s rejected with %s", index + 1, response.status_code)
            continue
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            attempts.append(GeminiAttempt(index + 1, 0, exc.__class__.__name__, int((time.time() - started) * 1000)))
            continue
        except Exception as exc:
            attempts.append(GeminiAttempt(index + 1, 0, exc.__class__.__name__, int((time.time() - started) * 1000)))
            continue

    raise GeminiUnavailableError(json.dumps([item.__dict__ for item in attempts], ensure_ascii=False))
