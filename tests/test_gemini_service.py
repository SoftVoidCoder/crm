import json
import unittest
from unittest.mock import patch

from services import gemini_service


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    responses = []
    requested_urls = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        self.requested_urls.append(url)
        return self.responses.pop(0)


class GeminiFallbackTests(unittest.TestCase):
    def setUp(self):
        _FakeClient.responses = []
        _FakeClient.requested_urls = []

    @patch.object(gemini_service, "KORDA_GEMINI_API_KEYS", "key-1,key-2")
    @patch.object(gemini_service, "KORDA_AI_MODELS", "busy-model,fallback-model")
    @patch.object(gemini_service.httpx, "Client", _FakeClient)
    def test_text_request_switches_model_after_503(self):
        _FakeClient.responses = [
            _FakeResponse(503, text="busy"),
            _FakeResponse(200, payload={
                "candidates": [{"content": {"parts": [{"text": "Готово"}]}}],
            }),
        ]

        result = gemini_service.ask_gemini("Где поручения?", {"navigation": {}})

        self.assertEqual(result["answer"], "Готово")
        self.assertEqual(result["model"], "fallback-model")
        self.assertEqual(len(_FakeClient.requested_urls), 2)

    @patch.object(gemini_service, "KORDA_GEMINI_API_KEYS", "key-1,key-2")
    @patch.object(gemini_service, "KORDA_AUDIO_AI_MODELS", "busy-audio,fallback-audio")
    @patch.object(gemini_service.httpx, "Client", _FakeClient)
    def test_audio_request_switches_model_and_normalizes_result(self):
        analysis = {
            "transcript": "Менеджер: Добрый день. Клиент: Нужен кожух.",
            "dialog": [
                {"speaker": "manager", "text": "Добрый день.", "confidence": 0.9},
                {"speaker": "customer", "text": "Нужен кожух.", "confidence": 0.8},
            ],
            "summary": "Клиент запросил кожух.",
            "customer_need": "Шумозащитный кожух.",
            "manager_errors": [],
            "next_step": "Подготовить КП.",
            "deal_signal": "warm",
            "role_confidence": 0.8,
            "transcription_confidence": 0.9,
        }
        _FakeClient.responses = [
            _FakeResponse(503, text="busy"),
            _FakeResponse(200, payload={
                "candidates": [{"content": {"parts": [{"text": json.dumps(analysis, ensure_ascii=False)}]}}],
            }),
        ]

        result = gemini_service.transcribe_call_audio(b"RIFF0000WAVEdata", "audio/wav", "call.wav")

        self.assertEqual(result["model"], "fallback-audio")
        self.assertEqual(result["dialog"][0]["speaker"], "manager")
        self.assertEqual(result["deal_signal"], "warm")
        self.assertEqual(len(_FakeClient.requested_urls), 2)

    def test_transport_errors_are_classified_as_model_failures(self):
        self.assertTrue(gemini_service._should_try_next_model(503))
        self.assertTrue(gemini_service._should_try_next_model(0))
        self.assertFalse(gemini_service._should_try_next_model(429))


if __name__ == "__main__":
    unittest.main()
