"""P1-003 AIAgentService unit tests.

Exercises the full provider -> agent-service chain with in-memory fakes (no
real API requests), covering:

* non-streaming generation (default provider, explicit provider/model, usage
  accounting, usage-fallback estimate, degradation, all-fail, none-configured,
  rate-limit retry, timeout partial-result)
* streaming generation (chunk + terminal result, usage from stream, error
  result, none-configured)
* message-metadata builder (decision #5 shape incl. ``token_count``)

Patches are applied to ``app.services.ai.agent_service.ai_config`` via
``monkeypatch`` so they auto-restore per test.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

import app.services.ai.agent_service as ai_agent
from app.services.ai.agent_service import AIAgentService, AgentResult, TokenUsage
from app.services.ai.exceptions import (
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
def _sse(piece: str) -> str:
    return "data: " + json.dumps({"choices": [{"delta": {"content": piece}}]})


def _sse_usage(usage: Dict[str, int]) -> str:
    return "data: " + json.dumps({"choices": [], "usage": usage})


class FakeProvider:
    """In-memory provider implementing the adapter contract.

    Non-stream returns an envelope dict; stream=True returns an async
    iterator of raw SSE ``data:`` lines (the httpx-adapter shape).  A
    ``behavior`` callable can override per-call outcomes and raise.
    """

    def __init__(
        self,
        name: str = "openai",
        content: str = "Hello world",
        usage: Optional[Dict[str, int]] = None,
        stream_usage: Optional[Dict[str, int]] = None,
        behavior=None,
        report_usage: bool = True,
    ):
        self._name = name
        self._content = content
        self._usage = usage or {"prompt_tokens": 4, "completion_tokens": 6, "total": 10}
        self._stream_usage = stream_usage if stream_usage is not None else self._usage
        self._behavior = behavior
        self._report_usage = report_usage
        self.calls = 0
        self.stream_calls = 0
        self.last_model: Optional[str] = None

    @property
    def provider_name(self) -> str:
        return self._name

    async def chat(self, messages, model=None, temperature=0.7,
                   max_tokens=1024, stream=False):
        self.last_model = model
        if stream:
            self.stream_calls += 1
            idx = self.stream_calls - 1
        else:
            self.calls += 1
            idx = self.calls - 1
        if self._behavior is not None:
            out = self._behavior(idx, stream)
            if isinstance(out, Exception):
                raise out
            return out
        if stream:
            return self._stream_gen()
        return {
            "model": "m",
            "choices": [{"role": "assistant", "content": self._content}],
            "usage": self._usage if self._report_usage else None,
        }

    async def _stream_gen(self):
        yield _sse("Hello ")
        yield _sse("world")
        if self._report_usage:
            yield _sse_usage(self._stream_usage)

    async def list_models(self):
        return ["m"]

    async def test_connection(self):
        return {"success": True}


class _NoProvider:
    """Marker returned when a provider is not configured."""
    pass


class _P003StreamFakeProvider:
    """Non-stream provider returning a full envelope with reported usage.

    Used by the router integration tests: ``content`` is the assistant text and
    ``usage`` total 6 so the response + persisted metadata can be asserted.
    """

    provider_name = "openai"

    def __init__(self):
        self.content = "Hello world"
        self.usage = {"prompt_tokens": 3, "completion_tokens": 3, "total": 6}

    async def chat(self, messages, model=None, temperature=0.7,
                   max_tokens=1024, stream=False):
        if stream:
            async def _gen():
                yield self.content
            return _gen()
        return {
            "model": "gpt-4o",
            "choices": [{"role": "assistant", "content": self.content}],
            "usage": self.usage,
        }

    async def list_models(self):
        return ["gpt-4o"]

    async def test_connection(self):
        return {"success": True}


def _install_config(
    monkeypatch,
    configured: Optional[List[str]] = None,
    providers: Optional[Dict[str, FakeProvider]] = None,
    default: Optional[FakeProvider] = None,
):
    """Point agent_service's config view at in-memory fakes."""
    providers = providers or {}
    if configured is None:
        configured = list(providers.keys())

    def _get_provider(name):
        return providers.get(name)

    def _get_default():
        return default

    def _names():
        return list(configured)

    monkeypatch.setattr(ai_agent.ai_config, "get_provider", _get_provider)
    monkeypatch.setattr(ai_agent.ai_config, "get_default_provider", _get_default)
    monkeypatch.setattr(ai_agent.ai_config, "configured_provider_names", _names)


def _fast_sleep(monkeypatch):
    """No-op sleep so rate-limit backoff tests don't actually wait 1/2/4s."""
    async def _no_sleep(_delay):
        return None
    monkeypatch.setattr(ai_agent.asyncio, "sleep", _no_sleep)


def _conv():
    class _C:
        id = "conv-1"
    return _C()


# --------------------------------------------------------------------------- #
# TokenUsage
# --------------------------------------------------------------------------- #
class TestTokenUsage:
    def test_as_dict_total(self):
        u = TokenUsage(prompt_tokens=3, completion_tokens=5)
        assert u.as_dict() == {"prompt_tokens": 3, "completion_tokens": 5, "total": 8}
        assert u.total == 8

    def test_zero(self):
        assert TokenUsage().as_dict() == {
            "prompt_tokens": 0, "completion_tokens": 0, "total": 0,
        }


# --------------------------------------------------------------------------- #
# Non-streaming generation
# --------------------------------------------------------------------------- #
class TestGenerateResponse:
    async def test_success_uses_provider_usage(self, monkeypatch):
        p = FakeProvider(name="openai", content="Hi", usage={
            "prompt_tokens": 2, "completion_tokens": 3, "total": 5})
        _install_config(monkeypatch, providers={"openai": p}, default=p)
        svc = AIAgentService()
        res = await svc.generate_response(_conv(), [{"role": "user", "content": "hi"}])
        assert res.content == "Hi"
        assert res.provider == "openai"
        assert res.model == "m"
        assert isinstance(res.usage, TokenUsage)
        assert res.usage.as_dict() == {"prompt_tokens": 2, "completion_tokens": 3, "total": 5}
        assert res.error is None
        assert res.latency_ms >= 0

    async def test_usage_falls_back_to_estimate(self, monkeypatch):
        # provider reports no usage -> completion estimated from content
        p = FakeProvider(name="local", content="0123456789", report_usage=False)
        _install_config(monkeypatch, providers={"local": p}, default=p)
        svc = AIAgentService()
        res = await svc.generate_response(_conv(), [{"role": "user", "content": "x"}])
        # ceil(10/4) = 3
        assert res.usage.as_dict()["completion_tokens"] == 3
        assert res.usage.as_dict()["prompt_tokens"] == 0

    async def test_explicit_provider_and_model(self, monkeypatch):
        a = FakeProvider(name="openai", content="A")
        b = FakeProvider(name="local", content="B")
        _install_config(monkeypatch, providers={"openai": a, "local": b}, default=a)
        svc = AIAgentService()
        res = await svc.generate_response(
            _conv(), [{"role": "user", "content": "x"}], provider="local", model="llama"
        )
        assert res.provider == "local"
        assert b.last_model == "llama"
        assert a.calls == 0  # openai never touched

    async def test_default_provider_selected(self, monkeypatch):
        a = FakeProvider(name="openai", content="A")
        b = FakeProvider(name="local", content="B")
        _install_config(monkeypatch, providers={"openai": a, "local": b}, default=a)
        res = await AIAgentService().generate_response(_conv(), [{"role": "user", "content": "x"}])
        assert res.provider == "openai"

    async def test_degrades_to_next_provider(self, monkeypatch):
        bad = FakeProvider(name="openai", behavior=lambda i, s: ProviderError(
            "boom", provider="openai"))
        good = FakeProvider(name="local", content="Recovered")
        _install_config(monkeypatch, providers={"openai": bad, "local": good}, default=bad)
        res = await AIAgentService().generate_response(_conv(), [{"role": "user", "content": "x"}])
        assert res.provider == "local"
        assert res.content == "Recovered"
        assert res.error is None

    async def test_all_providers_fail_raises(self, monkeypatch):
        bad1 = FakeProvider(name="openai", behavior=lambda i, s: ProviderError("x"))
        bad2 = FakeProvider(name="local", behavior=lambda i, s: ProviderError("y"))
        _install_config(monkeypatch, providers={"openai": bad1, "local": bad2}, default=bad1)
        with pytest.raises(ProviderUnavailableError):
            await AIAgentService().generate_response(_conv(), [{"role": "user", "content": "x"}])

    async def test_no_provider_raises(self, monkeypatch):
        _install_config(monkeypatch, providers={}, default=None)
        with pytest.raises(ProviderUnavailableError):
            await AIAgentService().generate_response(_conv(), [{"role": "user", "content": "x"}])

    async def test_rate_limit_retries_then_succeeds(self, monkeypatch):
        # first call rate-limited; the backoff probe (2nd call) succeeds.
        def behavior(idx, stream):
            if idx == 0:
                raise RateLimitError("429", provider="openai")
            return {"model": "m", "choices": [{"role": "assistant", "content": "ok"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total": 2}}
        p = FakeProvider(name="openai", behavior=behavior)
        _fast_sleep(monkeypatch)
        _install_config(monkeypatch, providers={"openai": p}, default=p)
        res = await AIAgentService().generate_response(_conv(), [{"role": "user", "content": "x"}])
        assert res.content == "ok"
        assert res.error is None
        assert res.provider == "openai"

    async def test_rate_limit_exhausted_degrades(self, monkeypatch):
        # always rate-limited -> backoff never recovers -> next provider
        def behavior(idx, stream):
            raise RateLimitError("429", provider="openai")
        bad = FakeProvider(name="openai", behavior=behavior)
        good = FakeProvider(name="local", content="local-ok")
        _fast_sleep(monkeypatch)
        _install_config(monkeypatch, providers={"openai": bad, "local": good}, default=bad)
        res = await AIAgentService().generate_response(_conv(), [{"role": "user", "content": "x"}])
        assert res.provider == "local"
        assert res.content == "local-ok"

    async def test_timeout_returns_partial_flagged(self, monkeypatch):
        def behavior(idx, stream):
            raise ProviderTimeoutError("took too long", provider="openai")
        p = FakeProvider(name="openai", behavior=behavior)
        _install_config(monkeypatch, providers={"openai": p}, default=p)
        res = await AIAgentService().generate_response(_conv(), [{"role": "user", "content": "x"}])
        # Timeout is terminal (not a provider switch): flagged, no raise.
        assert res.error is not None
        assert "timeout" in res.error
        assert res.provider == "openai"


# --------------------------------------------------------------------------- #
# Streaming generation
# --------------------------------------------------------------------------- #
class TestGenerateStream:
    async def _collect(self, monkeypatch, **kw):
        p = FakeProvider(**kw) if kw else FakeProvider()
        _install_config(monkeypatch, providers={"openai": p}, default=p)
        svc = AIAgentService()
        events = [e async for e in svc.generate_stream(_conv(), [{"role": "user", "content": "x"}])]
        return events, p

    async def test_stream_chunks_then_result(self, monkeypatch):
        events, p = await self._collect(monkeypatch)
        types = [e["type"] for e in events]
        # two content chunks then one terminal result
        assert types.count("chunk") == 2
        assert types[-1] == "result"
        result = events[-1]
        assert result["accumulated_content"] == "Hello world"
        assert result["error"] is None
        # usage recovered from the stream usage line
        assert result["usage"]["completion_tokens"] == 6
        assert result["provider"] == "openai"

    async def test_stream_error_result_on_provider_down(self, monkeypatch):
        def behavior(idx, stream):
            raise ProviderError("downstream", provider="openai")
        p = FakeProvider(behavior=behavior)
        _install_config(monkeypatch, providers={"openai": p}, default=p)
        svc = AIAgentService()
        events = [e async for e in svc.generate_stream(_conv(), [{"role": "user", "content": "x"}])]
        result = events[-1]
        assert result["type"] == "result"
        assert result["error"] is not None
        assert "provider error" in result["error"]

    async def test_stream_no_provider_yields_error(self, monkeypatch):
        _install_config(monkeypatch, providers={}, default=None)
        svc = AIAgentService()
        events = [e async for e in svc.generate_stream(_conv(), [{"role": "user", "content": "x"}])]
        assert len(events) == 1
        assert events[0]["type"] == "result"
        assert "no AI provider available" in events[0]["error"]

    async def test_stream_degrades_to_next(self, monkeypatch):
        bad = FakeProvider(name="openai", behavior=lambda i, s: ProviderError("down"))
        good = FakeProvider(name="local", content="local-stream",
                            stream_usage={"prompt_tokens": 1, "completion_tokens": 2, "total": 3})
        _install_config(monkeypatch, providers={"openai": bad, "local": good}, default=bad)
        svc = AIAgentService()
        events = [e async for e in svc.generate_stream(_conv(), [{"role": "user", "content": "x"}])]
        result = events[-1]
        assert result["provider"] == "local"
        assert result["error"] is None
        assert result["usage"]["total"] == 3


# --------------------------------------------------------------------------- #
# message-metadata builder (decision #5)
# --------------------------------------------------------------------------- #
class TestBuildMessageMetadata:
    def test_success_shape(self):
        meta = AIAgentService.build_message_metadata(
            status="success", provider="openai", model="gpt-4o",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=7),
            latency_ms=120, stream=True,
        )
        assert meta["status"] == "success"
        assert meta["provider"] == "openai"
        assert meta["model"] == "gpt-4o"
        assert meta["stream"] is True
        assert meta["latency_ms"] == 120
        assert meta["token_count"] == 10
        assert meta["usage"]["total"] == 10
        assert "error" not in meta

    def test_error_includes_error_key(self):
        meta = AIAgentService.build_message_metadata(
            status="error", provider="openai", error="boom",
        )
        assert meta["status"] == "error"
        assert meta["error"] == "boom"
        assert meta["token_count"] == 0

    def test_dict_usage_accepted(self):
        meta = AIAgentService.build_message_metadata(
            status="success", usage={"prompt_tokens": 1, "completion_tokens": 2, "total": 3},
        )
        assert meta["usage"]["total"] == 3
        assert meta["token_count"] == 3


# --------------------------------------------------------------------------- #
# package import surface
# --------------------------------------------------------------------------- #
class TestPackageImport:
    def test_top_level_exports(self):
        import app.services.ai as ai
        assert hasattr(ai, "AIAgentService")
        assert hasattr(ai, "AgentResult")
        assert hasattr(ai, "TokenUsage")
        assert hasattr(ai, "ProviderAdapter")
        assert hasattr(ai, "get_provider")
        assert hasattr(ai, "ProviderError")


# --------------------------------------------------------------------------- #
# Non-stream router integration (POST /conversations/{id}/chat)
# --------------------------------------------------------------------------- #
class TestNonStreamRouterIntegration:
    """Drive the real POST /{id}/chat handler through the real AIAgentService.

    Uses a fake provider (patched onto ``agent_service.ai_config``) and a fake
    conversation service, so the full ``generate_response -> AgentResult ->
    message persistence`` chain runs without a network or a database.
    """

    @staticmethod
    def _conversation():
        class _C:
            id = "conv-p003"
            status = "active"
        return _C()

    @staticmethod
    def _fake_conversation_service():
        from uuid import uuid4

        class _FakeSvc:
            def __init__(self):
                self.created = []

            async def _get_by_id(self, cid):
                class _C:
                    id = cid
                    status = "active"
                return _C()

            async def create_message(self, data):
                from unittest.mock import MagicMock
                from datetime import datetime as _dt, timezone as _tz
                m = MagicMock()
                m.id = uuid4()
                m.content = data.content
                m.role = data.role
                m.metadata_ = data.metadata_
                m.created_at = _dt.now(_tz.utc)
                m.model_dump = lambda by_alias=True: {
                    "id": str(m.id), "role": m.role, "content": m.content,
                    "metadata": m.metadata_, "created_at": m.created_at.isoformat(),
                }
                self.created.append((m, data))
                return m

            async def list_messages(self, *a, **k):
                return [], 0

            async def update_message(self, mid, data):
                from unittest.mock import MagicMock
                return MagicMock()

        return _FakeSvc()

    def test_chat_success_returns_usage(self, monkeypatch):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers import conversations as conv_mod
        from app.routers.conversations import get_conversation_service
        from app.db.session import get_db

        # Real AIAgentService driving a fake provider.
        fake = _P003StreamFakeProvider()  # non-stream envelope with usage
        import app.services.ai.agent_service as ai_agent
        monkeypatch.setattr(ai_agent.ai_config, "get_provider", lambda n: fake)
        monkeypatch.setattr(ai_agent.ai_config, "configured_provider_names",
                            lambda: ["openai"])
        monkeypatch.setattr(ai_agent.ai_config, "get_default_provider",
                            lambda: fake)

        app = FastAPI()
        app.include_router(conv_mod.router)
        svc = self._fake_conversation_service()
        async def _db():
            yield MagicMock()
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_conversation_service] = lambda: svc

        client = TestClient(app)
        conv_id = "b6e9f0c1-0000-4000-8000-000000000001"
        resp = client.post(
            f"/conversations/{conv_id}/chat",
            json={"message": "hi", "provider": "openai"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["provider"] == "openai"
        assert body["usage"]["total"] == 6
        assert body["assistant_message"]["content"] == "Hello world"
        # assistant persisted with status=success + usage in metadata
        assistant = next(m for m, _ in svc.created if m.role == "assistant")
        assert assistant.metadata_["status"] == "success"
        assert assistant.metadata_["usage"]["total"] == 6
        assert assistant.metadata_["token_count"] == 6

    def test_chat_provider_down_returns_502(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers import conversations as conv_mod
        from app.routers.conversations import get_conversation_service
        from app.db.session import get_db
        from unittest.mock import MagicMock

        import app.services.ai.agent_service as ai_agent
        from app.services.ai.exceptions import ProviderError

        class _Fail:
            provider_name = "openai"

            async def chat(self, *a, **k):
                raise ProviderError("down", provider="openai")

            async def list_models(self):
                return []

            async def test_connection(self):
                return {"success": False}

        fail = _Fail()
        monkeypatch.setattr(ai_agent.ai_config, "get_provider", lambda n: fail)
        monkeypatch.setattr(ai_agent.ai_config, "configured_provider_names",
                            lambda: ["openai"])
        monkeypatch.setattr(ai_agent.ai_config, "get_default_provider",
                            lambda: fail)

        app = FastAPI()
        app.include_router(conv_mod.router)
        svc = self._fake_conversation_service()
        async def _db():
            yield MagicMock()
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_conversation_service] = lambda: svc

        client = TestClient(app)
        conv_id = "b6e9f0c1-0000-4000-8000-000000000001"
        resp = client.post(f"/conversations/{conv_id}/chat", json={"message": "hi"})
        assert resp.status_code == 502
        assert "AI provider error" in resp.json()["detail"]
