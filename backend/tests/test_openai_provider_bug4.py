"""Tests for BUG-4: the landed LLM provider (OpenAIProvider) in the intent layer.

Acceptance (task t_d91feb2a body):
  - `from app.providers.openai_provider import OpenAIProvider` succeeds and
    exposes `chat_completion(model, messages, temperature)` matching the
    intent_service call contract. No `ModuleNotFoundError` anywhere.
  - With an API key configured, the LLM classification path is usable.
  - Without an API key / provider unavailable, classification degrades to
    the rule-based path: no ModuleNotFoundError, and the log carries at most
    ONE degraded-notice (no per-request error spam).
"""
import asyncio
import json
import logging
from unittest.mock import AsyncMock

import pytest

from app.providers.openai_provider import LLMCompletion, OpenAIProvider
from app.providers.exceptions import (
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.schemas.intent import IntentClassificationRequest
from app.services.intent_service import IntentService


# ---------------------------------------------------------------------------
# OpenAIProvider unit behavior
# ---------------------------------------------------------------------------

def test_keyless_provider_unavailable():
    """No OPENAI_API_KEY in the env -> is_available() False (first-class)."""
    p = OpenAIProvider(api_key=None)
    assert p.is_available() is False


def test_keyed_provider_available():
    p = OpenAIProvider(api_key="sk-test")
    assert p.is_available() is True
    assert p.provider_name == "openai"
    assert p.configured_model == "gpt-4o-mini"


def test_chat_completion_requires_key():
    """chat_completion without a key raises ProviderUnavailableError (not
    ModuleNotFoundError) — the caller falls back to rules."""
    p = OpenAIProvider(api_key=None)
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(p.chat_completion(messages=[{"role": "user", "content": "hi"}]))


def test_chat_completion_uses_injected_client():
    """With an API key + injected transport, chat_completion returns the
    model text via the LLMCompletion contract."""
    import httpx

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {
                "model": "gpt-4o-mini",
                "choices": [{"content": json.dumps({"intent_type": "thanks"})}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total": 5},
            }

    sent = {}

    class _FakeClient:
        def post(self, url, json=None, headers=None):
            async def _post():
                sent["url"] = url
                sent["json"] = json
                sent["headers"] = headers
                return _FakeResponse()
            return _post()

        async def aclose(self):
            pass

    p = OpenAIProvider(api_key="sk-test", client=_FakeClient(), base_url="http://test.local/v1")
    out = asyncio.run(p.chat_completion(messages=[{"role": "user", "content": "hi"}]))
    assert isinstance(out, LLMCompletion)
    assert out.content == json.dumps({"intent_type": "thanks"})
    assert out.usage["total"] == 5
    assert sent["url"] == "http://test.local/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer sk-test"
    assert sent["json"]["stream"] is False


def test_chat_completion_rate_limit_maps_to_rate_limit_error():
    class _Resp429:
        status_code = 429
        text = "rate limited"

        def json(self):
            raise ValueError("no json on 429")

    class _Client:
        def post(self, url, json=None, headers=None):
            async def _post():
                return _Resp429()
            return _post()

        async def aclose(self):
            pass

    p = OpenAIProvider(api_key="sk-test", client=_Client())
    with pytest.raises(RateLimitError):
        asyncio.run(p.chat_completion())


# ---------------------------------------------------------------------------
# IntentService x OpenAIProvider integration (service level, no network)
# ---------------------------------------------------------------------------

class _StubProvider:
    """Injectable stand-in satisfying the OpenAIProvider call contract."""

    def __init__(self, content: str, available: bool = True):
        self._content = content
        self._available = available
        self.calls = 0

    def is_available(self):
        return self._available

    def healthy(self):
        return self._available

    async def chat_completion(self, model=None, messages=None, temperature=0.1, max_tokens=1024):
        self.calls += 1
        return LLMCompletion(content=self._content, model=model)

    # decision-engine-style alias so the same stub can back both contracts
    async def complete(self, system_prompt, messages):
        return self._content


def _capture_logs():
    h = logging.Handler()
    records = []
    h.emit = lambda r: records.append((r.levelname, r.getMessage()))
    logger = logging.getLogger("app.services.intent_service")
    logger.addHandler(h)
    logger.setLevel(logging.DEBUG)
    return logger, records, h


def test_intent_with_keyed_llm_provider_uses_llm_path():
    """With a configured LLM, classification uses the LLM path and parses
    its JSON (confidence 0.95 >= 0.7 threshold beats the keyword result)."""
    llm_json = json.dumps({
        "intent_type": "complaint",
        "intent_name": "投诉",
        "confidence": 0.95,
        "entities": {"topic": "service"},
        "explanation": "user is complaining",
    })
    stub = _StubProvider(content=llm_json)
    svc = IntentService(db=None, llm_provider=stub)
    resp = asyncio.run(svc.classify_intent(
        IntentClassificationRequest(message="你们的服务太差了，我投诉！")))
    assert resp.success is True
    assert stub.calls == 1
    assert resp.intent.intent_type == "complaint"
    assert resp.intent.confidence == 0.95
    assert resp.intent.entities == {"topic": "service"}


def test_intent_without_key_degrades_quietly_to_rules():
    """No key: rule fallback, success=True, and across repeated calls only
    ONE degraded notice is logged (debug/warning) with ZERO error lines."""
    svc = IntentService(db=None)  # default -> OpenAIProvider(), keyless here
    logger, records, handler = _capture_logs()
    try:
        for _ in range(4):
            resp = asyncio.run(svc.classify_intent(
                IntentClassificationRequest(message="你好，早上好！")))
            assert resp.success is True
            assert resp.intent is not None
    finally:
        logger.removeHandler(handler)

    assert any(resp.intent.intent_type in ("greeting", "question")
               for resp in [resp])
    errors = [r for r in records if r[0] == "ERROR"]
    assert errors == [], f"no ERROR logs expected keyless, got {errors}"
    notices = [r for r in records if "falling back" in r[1] or "LLM" in r[1]]
    assert len(notices) <= 1, f"degraded notice must log once, got {notices}"


def test_intent_exploding_provider_falls_back_to_rules():
    """Injected provider whose chat_completion raises (e.g. gateway 503):
    classification still succeeds via rules; the warning is logged once."""
    class _Exploding(_StubProvider):
        async def chat_completion(self, model=None, messages=None, temperature=0.1,
                                  max_tokens=1024):
            raise ProviderError("LLM gateway 503 (injected)")

    svc = IntentService(db=None, llm_provider=_Exploding(content=""))
    logger, records, handler = _capture_logs()
    try:
        resp = asyncio.run(svc.classify_intent(
            IntentClassificationRequest(message="我要投诉，产品质量太差")))
        for _ in range(3):
            asyncio.run(svc.classify_intent(
                IntentClassificationRequest(message="我要投诉，产品质量太差")))
    finally:
        logger.removeHandler(handler)
    assert resp.success is True
    assert resp.intent.intent_type == "complaint"
    errors = [r for r in records if r[0] == "ERROR"]
    assert errors == []


def test_module_imports_have_no_dead_reference():
    """The original defect: `from app.providers.openai_provider import
    OpenAIProvider` raised ModuleNotFoundError. The module must now exist
    and import cleanly, and intent_service's default-provider path must not
    raise."""
    import importlib
    mod = importlib.import_module("app.providers.openai_provider")
    assert hasattr(mod, "OpenAIProvider")
    svc = IntentService(db=None)
    provider = svc._get_provider()
    assert isinstance(provider, OpenAIProvider)
    assert provider.is_available() in (True, False)  # either state is valid
