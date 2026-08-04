import json
import base64
import time
from dataclasses import dataclass

import httpx

from app_logging import get_logger
from settings import (
    KORDA_AI_MODEL,
    KORDA_AI_MODELS,
    KORDA_AI_TIMEOUT_SECONDS,
    KORDA_AUDIO_AI_MODELS,
    KORDA_GEMINI_API_KEYS,
)


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


def _model_list(raw_value: str) -> list[str]:
    raw = raw_value or KORDA_AI_MODEL or ""
    normalized = raw.replace("\n", ",").replace(";", ",")
    models = []
    for item in normalized.split(","):
        value = item.strip()
        if value and value not in models:
            models.append(value)
    return models or [KORDA_AI_MODEL]


def _text_models() -> list[str]:
    return _model_list(KORDA_AI_MODELS)


def _audio_models() -> list[str]:
    return _model_list(KORDA_AUDIO_AI_MODELS)


def _should_try_next_model(status_code: int) -> bool:
    return status_code in {0, 500, 502, 503, 504}


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

    for model in _text_models():
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
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
                            "model": model,
                            "provider": "gemini",
                            "key_index": index + 1,
                            "attempts": [item.__dict__ for item in attempts],
                        }
                    attempts.append(GeminiAttempt(index + 1, response.status_code, f"{model}: empty_response", latency_ms))
                    continue
                error_text = response.text[:400]
                attempts.append(GeminiAttempt(index + 1, response.status_code, f"{model}: {error_text}", latency_ms))
                if _should_try_next_model(response.status_code):
                    break
                if response.status_code in {400, 401, 403}:
                    logger.warning("Gemini key %s rejected with %s", index + 1, response.status_code)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                attempts.append(GeminiAttempt(index + 1, 0, f"{model}: {exc.__class__.__name__}", int((time.time() - started) * 1000)))
                break
            except Exception as exc:
                attempts.append(GeminiAttempt(index + 1, 0, f"{model}: {exc.__class__.__name__}", int((time.time() - started) * 1000)))
                break

    raise GeminiUnavailableError(json.dumps([item.__dict__ for item in attempts], ensure_ascii=False))


CALL_ANALYSIS_SCHEMA = {
    "transcript": "полная расшифровка разговора на русском, по возможности с репликами",
    "dialog": [
        {
            "speaker": "manager|customer|unknown",
            "text": "реплика",
            "confidence": 0.0,
        }
    ],
    "summary": "короткий итог звонка",
    "customer_need": "что нужно клиенту",
    "manager_errors": [
        {
            "type": "не выявил потребность|не назначил следующий шаг|перебивал|не отработал возражение|не назвал срок|ошибка речи|другое",
            "quote": "фрагмент разговора или пусто",
            "severity": "low|medium|high",
            "recommendation": "как исправить",
        }
    ],
    "next_step": "что сделать дальше",
    "deal_signal": "cold|neutral|warm|hot|risk",
    "role_confidence": 0.0,
    "transcription_confidence": 0.0,
}


def _extract_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.removeprefix("json").strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            return {}
    return {}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_call_analysis(payload: dict, fallback_name: str = "") -> dict:
    payload = payload if isinstance(payload, dict) else {}
    dialog = payload.get("dialog") if isinstance(payload.get("dialog"), list) else []
    normalized_dialog = []
    for item in dialog[:120]:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker") or "unknown").strip().lower()
        if speaker not in {"manager", "customer", "unknown"}:
            speaker = "unknown"
        normalized_dialog.append({
            "speaker": speaker,
            "text": str(item.get("text") or "").strip()[:2000],
            "confidence": max(0.0, min(1.0, _safe_float(item.get("confidence")))),
        })
    errors = payload.get("manager_errors") if isinstance(payload.get("manager_errors"), list) else []
    normalized_errors = []
    for item in errors[:12]:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "medium").strip().lower()
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        normalized_errors.append({
            "type": str(item.get("type") or "другое").strip()[:120],
            "quote": str(item.get("quote") or "").strip()[:700],
            "severity": severity,
            "recommendation": str(item.get("recommendation") or "").strip()[:900],
        })
    signal = str(payload.get("deal_signal") or "neutral").strip().lower()
    if signal not in {"cold", "neutral", "warm", "hot", "risk"}:
        signal = "neutral"
    transcript = str(payload.get("transcript") or "").strip()
    if not transcript and normalized_dialog:
        transcript = "\n".join(f"{item['speaker']}: {item['text']}" for item in normalized_dialog if item["text"])
    return {
        "transcript": transcript,
        "dialog": normalized_dialog,
        "summary": str(payload.get("summary") or f"Расшифровка звонка {fallback_name}".strip()).strip()[:1500],
        "customer_need": str(payload.get("customer_need") or "").strip()[:1000],
        "manager_errors": normalized_errors,
        "next_step": str(payload.get("next_step") or "").strip()[:1000],
        "deal_signal": signal,
        "role_confidence": max(0.0, min(1.0, _safe_float(payload.get("role_confidence")))),
        "transcription_confidence": max(0.0, min(1.0, _safe_float(payload.get("transcription_confidence")))),
    }


def format_call_analysis_summary(analysis: dict) -> str:
    dialog_lines = []
    role_label = {"manager": "Менеджер", "customer": "Клиент", "unknown": "Не определено"}
    for item in analysis.get("dialog") or []:
        text = str(item.get("text") or "").strip()
        if text:
            dialog_lines.append(f"{role_label.get(item.get('speaker'), 'Не определено')}: {text}")
    errors = []
    for item in analysis.get("manager_errors") or []:
        line = f"- {item.get('type') or 'Ошибка'} ({item.get('severity') or 'medium'}): {item.get('recommendation') or 'Нужна ручная проверка'}"
        quote = str(item.get("quote") or "").strip()
        if quote:
            line += f" | Фрагмент: {quote}"
        errors.append(line)
    parts = [
        "ИИ-расшифровка звонка",
        f"Итог: {analysis.get('summary') or 'Не определено'}",
        f"Потребность клиента: {analysis.get('customer_need') or 'Не определена'}",
        f"Сигнал сделки: {analysis.get('deal_signal') or 'neutral'}",
        f"Следующий шаг: {analysis.get('next_step') or 'Нужно назначить вручную'}",
        f"Уверенность ролей: {round(float(analysis.get('role_confidence') or 0) * 100)}%",
        f"Уверенность распознавания: {round(float(analysis.get('transcription_confidence') or 0) * 100)}%",
        "",
        "Диалог:",
        "\n".join(dialog_lines) or (analysis.get("transcript") or "Расшифровка не получена"),
        "",
        "Ошибки менеджера:",
        "\n".join(errors) or "Критичных ошибок не найдено.",
    ]
    return "\n".join(parts).strip()


def transcribe_call_audio(audio_bytes: bytes, mime_type: str, filename: str = "") -> dict:
    keys = _gemini_keys()
    if not keys:
        raise GeminiUnavailableError("gemini_keys_not_configured")
    if not audio_bytes:
        raise GeminiUnavailableError("empty_audio")

    prompt = f"""
Ты анализируешь запись звонка отдела продаж Korda CRM. Верни только валидный JSON без markdown.

Задачи:
1. Распознай речь в текст на русском. Если язык другой, переведи смысл на русский.
2. Раздели реплики по ролям: manager — продавец/менеджер, customer — покупатель/клиент, unknown — если роль неясна.
3. Определи ошибки менеджера: не выявил потребность, не назначил следующий шаг, перебивал, не отработал возражение, не назвал срок, ошибка речи, другое.
4. Дай краткий итог, потребность клиента, сигнал сделки и следующий шаг.
5. Не выдумывай реплики. Если качество записи плохое, снизь confidence и прямо укажи это.

Имя файла: {filename}

JSON-схема:
{json.dumps(CALL_ANALYSIS_SCHEMA, ensure_ascii=False)}
""".strip()
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{KORDA_AI_MODEL}:generateContent"
    request_body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio_bytes).decode("ascii")}},
            ],
        }],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.85,
            "maxOutputTokens": 8000,
            "responseMimeType": "application/json",
        },
    }
    attempts: list[GeminiAttempt] = []
    timeout = httpx.Timeout(max(float(KORDA_AI_TIMEOUT_SECONDS), 60.0), connect=10.0)

    for model in _audio_models():
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
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
                    analysis = _normalize_call_analysis(_extract_json_object(text), fallback_name=filename)
                    analysis["provider"] = "gemini"
                    analysis["model"] = model
                    analysis["key_index"] = index + 1
                    analysis["attempts"] = [item.__dict__ for item in attempts]
                    return analysis
                attempt = GeminiAttempt(index + 1, response.status_code, response.text[:500], latency_ms)
                attempt.error = f"{model}: {attempt.error}"
                attempts.append(attempt)
                if _should_try_next_model(response.status_code):
                    break
                continue
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                attempts.append(GeminiAttempt(index + 1, 0, f"{model}: {exc.__class__.__name__}", int((time.time() - started) * 1000)))
                break
            except Exception as exc:
                attempts.append(GeminiAttempt(index + 1, 0, f"{model}: {exc.__class__.__name__}", int((time.time() - started) * 1000)))
                break

    raise GeminiUnavailableError(json.dumps([item.__dict__ for item in attempts], ensure_ascii=False))
