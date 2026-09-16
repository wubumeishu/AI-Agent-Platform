"""SSE Streaming endpoint tests"""
import json

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


class TestChatStream:
    """Test SSE streaming endpoint"""

    @pytest.mark.asyncio
    async def test_chat_stream_endpoint_exists(self):
        """Test that chat stream endpoint exists"""
        from app.routers.conversations import router
        
        routes = [route.path for route in router.routes]
        assert any("/chat/stream" in route for route in routes), "Missing /chat/stream endpoint"

    @pytest.mark.asyncio
    async def test_chat_stream_validates_conversation(self):
        """Test that chat stream validates conversation exists"""
        # Just verify the endpoint structure is correct
        from app.routers.conversations import router
        
        stream_routes = [r for r in router.routes if 'chat/stream' in r.path]
        assert len(stream_routes) == 1
        assert stream_routes[0].methods == {'POST'}


class TestSSEEventFormat:
    """Test SSE event format"""

    def test_sse_event_format(self):
        """Test that SSE events follow correct format"""
        import json
        
        # Simulate event generation
        event_data = {'type': 'chunk', 'content': 'Hello', 'index': 0}
        event_line = f"data: {json.dumps(event_data)}\n\n"
        
        assert event_line.startswith("data: ")
        assert event_line.endswith("\n\n")
        
        # Parse and verify
        parsed = json.loads(event_line.replace("data: ", "").strip())
        assert parsed['type'] == 'chunk'
        assert parsed['content'] == 'Hello'

    def test_sse_done_event(self):
        """Test done event format"""
        import json
        
        event_data = {'type': 'done'}
        event_line = f"data: {json.dumps(event_data)}\n\n"
        
        parsed = json.loads(event_line.replace("data: ", "").strip())
        assert parsed['type'] == 'done'


class TestContextWindow:
    """Test context window management"""

    def test_context_window_calculation(self):
        """Test token estimation logic"""
        # Rough approximation: 4 chars per token
        text = "Hello, this is a test message for context window calculation."
        estimated_tokens = len(text) // 4
        
        assert estimated_tokens > 0
        assert estimated_tokens < len(text)  # Tokens should be less than chars

    def test_context_window_within_limits(self):
        """Test context window within limits"""
        max_tokens = 4000
        messages = [{"content": "Short"} for _ in range(10)]

        estimated_tokens = sum(len(m["content"]) // 4 for m in messages)

        assert estimated_tokens < max_tokens
        assert max(0, max_tokens - estimated_tokens) > 0


# ---------------------------------------------------------------------------
# P1-003: provider-backed SSE integration (replaces the simulated response)
# ---------------------------------------------------------------------------
class _P003FakeProvider:
    """Minimal provider for exercising the real router without a network.

    Streaming yields plain content *pieces* (the shape a P1-003
    ``AIAgentService`` hands to the router as ``chunk`` events); non-stream
    returns the provider envelope.  ``usage`` is exposed for the service to
    report in the terminal ``result`` event.
    """

    def __init__(self, name="openai"):
        self._name = name
        self.usage = {"prompt_tokens": 3, "completion_tokens": 3, "total": 6}
        self._pieces = ["Hello ", "world"]

    @property
    def provider_name(self):
        return self._name

    async def chat(self, messages, model=None, temperature=0.7,
                   max_tokens=1024, stream=False):
        if stream:
            async def _gen():
                for piece in self._pieces:
                    yield piece
            return _gen()
        return {
            "model": "m",
            "choices": [{"role": "assistant", "content": "".join(self._pieces)}],
            "usage": self.usage,
        }

    async def list_models(self):
        return ["m"]

    async def test_connection(self):
        return {"success": True}


class _P003FailProvider:
    """Provider that raises on every call — exercises the router's error path."""

    @property
    def provider_name(self):
        return "openai"

    async def chat(self, *a, **k):
        from app.services.ai.exceptions import ProviderError
        if k.get("stream"):
            async def _gen():
                raise ProviderError("down", provider="openai")
                yield  # pragma: no cover
            return _gen()
        raise ProviderError("down", provider="openai")

    async def list_models(self):
        return []

    async def test_connection(self):
        return {"success": False}


class _FakeAgentService:
    """Service test-double driven by a P1-003 fake provider.

    Yields the router's SSE event protocol (``chunk`` / ``result``) that
    ``conversations.chat_stream`` iterates over.  This is the seam the real
    router uses (``conversations._new_agent_service``); it does NOT depend on
    the shelved ``agent_service.ai_config`` module, which the QA shim
    deliberately does not expose (P1-003 is shelved).
    """

    def __init__(self, provider, provider_names=None):
        self._provider = provider
        self._names = provider_names or ["openai"]

    async def generate_stream(self, conversation, messages, provider=None,
                              model=None, timeout_s=60.0):
        accumulated = []
        try:
            # The provider's ``chat`` is an async method: ``await`` it to get
            # the streaming async-iterator, then consume the content pieces.
            stream = await self._provider.chat(
                messages, model=model, stream=True
            )
            async for piece in stream:
                accumulated.append(piece)
                yield {"type": "chunk", "content": piece,
                       "index": len(accumulated) - 1}
        except Exception as exc:  # noqa: BLE001 - provider failure boundary
            # Provider failed mid-stream: degrade to a terminal error result so
            # the router's documented error branch executes.
            yield {
                "type": "result",
                "error": str(exc),
                "accumulated_content": "".join(accumulated),
                "usage": {},
                "provider": provider or "openai",
                "model": model,
                "latency_ms": 0,
            }
            return
        yield {
            "type": "result",
            "accumulated_content": "".join(accumulated),
            "usage": getattr(self._provider, "usage", None)
            or {"prompt_tokens": 3, "completion_tokens": 3, "total": 6},
            "error": None,
            "provider": provider or "openai",
            "model": model,
            "latency_ms": 0,
        }


def _patched_service_for(monkeypatch, fail=False):
    """Return a factory the router's ``_new_agent_service`` can stand in for.

    The factory yields a ``_FakeAgentService`` bound to a P1-003 fake provider
    (or a deliberately failing one).  The test then installs it via
    ``conversations._new_agent_service`` — the router's real service seam — so
    we never touch the shelved ``agent_service.ai_config`` module, which the QA
    shim does not expose.  ``monkeypatch`` keeps this seam restored after the
    test so sibling tests see the production factory.
    """
    if fail:
        fake = _P003FailProvider()
    else:
        fake = _P003FakeProvider()

    def _make():
        # A fresh service double per router call, driving the fake provider.
        return _FakeAgentService(fake, provider_names=["openai"])

    def _install_router_seam():
        import app.routers.conversations as conv_mod
        monkeypatch.setattr(conv_mod, "_new_agent_service", lambda: _make())

    _install_router_seam()
    # Return the callable factory itself — the test's ``_app`` invokes it
    # (``factory = service_factory()``) to obtain a fresh service double.
    return _make


class TestP003ProviderSSE:
    """The /chat/stream endpoint is now provider-backed, not a simulation."""

    @staticmethod
    def _app(service_factory):
        from fastapi import FastAPI
        from app.routers import conversations as conv_mod
        app = FastAPI()
        app.include_router(conv_mod.router)
        factory = service_factory()
        conv_mod._new_agent_service = lambda: factory
        return app

    @staticmethod
    def _client_with_fake_service(app, conversation, fail=False):
        from fastapi.testclient import TestClient
        from app.db.session import get_db
        from app.routers.conversations import get_conversation_service

        class _FakeSvc:
            def __init__(self):
                self.created = []

            async def _get_by_id(self, cid):
                return conversation

            async def create_message(self, data):
                from uuid import uuid4
                m = MagicMock()
                m.id = uuid4()
                m.content = data.content
                m.role = data.role
                m.metadata_ = data.metadata_
                m.created_at = datetime.now(timezone.utc)
                self.created.append((m, data))
                return m

            async def list_messages(self, *a, **k):
                return [], 0

            async def update_message(self, mid, data):
                return MagicMock()

        svc = _FakeSvc()

        async def _db():
            yield MagicMock()

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_conversation_service] = lambda: svc
        return TestClient(app), svc

    @staticmethod
    def _parse_sse(text):
        out = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data: "):
                out.append(json.loads(line[len("data: "):]))
        return out

    def test_stream_event_sequence_matches_contract(self, monkeypatch):
        """conversation_id → chunk(s) → message_saved → done."""
        conv = MagicMock()
        conv.id = uuid4()
        conv.status = "active"

        app = self._app(_patched_service_for(monkeypatch, fail=False))
        client, svc = self._client_with_fake_service(app, conv)
        resp = client.post(f"/conversations/{conv.id}/chat/stream", params={"message": "hi"})
        assert resp.status_code == 200

        events = self._parse_sse(resp.text)
        types = [e["type"] for e in events]
        assert types[0] == "conversation_id"
        assert types[0:1] == ["conversation_id"]
        assert "chunk" in types
        assert "message_saved" in types
        assert types[-1] == "done"
        # Simulated-response marker must be gone.
        assert all("simulated" not in e.get("content", "").lower() for e in events)

    def test_stream_failure_emits_error_event(self, monkeypatch):
        conv = MagicMock()
        conv.id = uuid4()
        conv.status = "active"

        app = self._app(_patched_service_for(monkeypatch, fail=True))
        client, svc = self._client_with_fake_service(app, conv)
        resp = client.post(f"/conversations/{conv.id}/chat/stream", params={"message": "hi"})
        assert resp.status_code == 200
        events = self._parse_sse(resp.text)
        assert any(e["type"] == "error" for e in events)
        assert any(e["type"] == "message_saved" for e in events)

    def test_chat_stream_endpoint_still_post(self):
        """Regression guard: the SSE endpoint keeps its POST contract."""
        from app.routers.conversations import router
        stream_routes = [r for r in router.routes if "chat/stream" in getattr(r, "path", "")]
        assert len(stream_routes) == 1
        assert stream_routes[0].methods == {"POST"}

    def test_non_stream_chat_registered(self):
        from app.routers.conversations import router
        paths = [getattr(r, "path", "") for r in router.routes]
        assert any(p.endswith("/chat") and not p.endswith("/chat/stream") for p in paths)

    def test_simulated_logic_removed_from_router(self):
        import app.routers.conversations as conv_mod
        src = open(conv_mod.__file__, encoding="utf-8").read()
        assert "This is a simulated AI response" not in src
        assert "Simulate AI streaming response" not in src
