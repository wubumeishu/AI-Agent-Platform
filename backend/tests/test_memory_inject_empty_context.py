"""
Regression tests for Phase 2 BUG-3: memory inject with empty context -> 500.

BUG-3 (QA t_3eb34805):
    POST /api/v1/memory/inject {"conversation_id":..., "customer_id":..., "recent_messages": []}
    returned 500 because an empty recent_messages -> empty conversation_context ->
    MemorySearchRequest(query="") which violates query min_length=1 (uncaught
    ValidationError -> 500).

Fix under test:
    - inject_memories_into_context skips semantic search on empty/whitespace
      context and returns an empty injection (injection_count=0).
    - get_relevant_memories is defensive against empty/whitespace query.
    - With real content, search still runs and returns results.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory import Memory
from app.schemas.memory import MemoryInjectionRequest
from app.services.memory_service import MemoryService


@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def service(mock_db):
    return MemoryService(mock_db)


def _make_memory(content: str, customer_id, importance=10, confidence=1.0) -> Memory:
    now = datetime.now(timezone.utc)
    return Memory(
        id=uuid4(),
        customer_id=customer_id,
        memory_type="preference",
        category="general",
        content=content,
        source="conversation",
        importance=importance,
        confidence=confidence,
        tags=[],
        metadata_={},
        created_at=now,
        updated_at=now,
        is_deleted=False,
    )


def _db_execute_returns(mock_db, memories: list):
    """Point mock_db.execute at a result whose .scalars().all() yields `memories`.

    Service call chain: result.scalars() -> scalars ; scalars.all() -> [memories].
    """
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = memories
    result.scalars.return_value = scalars
    mock_db.execute = AsyncMock(return_value=result)
    return mock_db


class TestInjectEmptyContext:
    """inject_memories_into_context must not 500 on empty/whitespace context."""

    async def test_empty_recent_messages(self, service):
        """No recent messages at all -> empty injection, no exception."""
        request = MemoryInjectionRequest(
            conversation_id=uuid4(),
            customer_id=uuid4(),
            recent_messages=[],
            max_memory_count=5,
        )
        # db.execute should never be hit for semantic search in this boundary.
        service.db.execute = AsyncMock()

        resp = await service.inject_memories_into_context(request)

        assert resp.injected_memories == []
        assert resp.injection_count == 0
        assert resp.context_tokens_added == 0
        service.db.execute.assert_not_called()

    async def test_whitespace_only_content(self, service):
        """recent_messages present but every content is blank -> empty injection."""
        request = MemoryInjectionRequest(
            conversation_id=uuid4(),
            customer_id=uuid4(),
            recent_messages=[
                {"role": "user", "content": "   "},
                {"role": "assistant", "content": "\n\t"},
            ],
        )
        service.db.execute = AsyncMock()

        resp = await service.inject_memories_into_context(request)

        assert resp.injected_memories == []
        assert resp.injection_count == 0
        assert resp.context_tokens_added == 0
        service.db.execute.assert_not_called()

    async def test_none_content_key(self, service):
        """A message missing the content key is treated as empty, not an error."""
        request = MemoryInjectionRequest(
            conversation_id=uuid4(),
            customer_id=uuid4(),
            recent_messages=[{"role": "user"}],
        )
        service.db.execute = AsyncMock()

        resp = await service.inject_memories_into_context(request)

        assert resp.injection_count == 0
        assert resp.injected_memories == []


class TestGetRelevantMemoriesEmptyQuery:
    """get_relevant_memories is defensive against empty/whitespace context."""

    async def test_empty_context_returns_empty(self, service):
        assert await service.get_relevant_memories(uuid4(), "", max_count=5) == []

    async def test_whitespace_context_returns_empty(self, service):
        assert await service.get_relevant_memories(uuid4(), "   \n\t ", max_count=5) == []

    async def test_truncation_to_empty_returns_empty(self, service):
        # Only the first 200 chars are used; if they are all whitespace, skip.
        assert await service.get_relevant_memories(uuid4(), " " * 250, max_count=5) == []


class TestInjectWithContentStillSearches:
    """When there is real context, search still runs and results are injected."""

    async def test_search_results_injected(self, mock_db, service):
        customer_id = uuid4()
        memory = _make_memory("客户偏好使用优惠和折扣活动", customer_id)
        _db_execute_returns(mock_db, [memory])

        request = MemoryInjectionRequest(
            conversation_id=uuid4(),
            customer_id=customer_id,
            recent_messages=[{"role": "user", "content": "优惠 折扣 活动"}],
            max_memory_count=5,
        )

        resp = await service.inject_memories_into_context(request)

        # importance=10, confidence=1.0, keyword "优惠" in content -> score 1.0 >= 0.7
        assert resp.injection_count == 1
        assert resp.injected_memories[0]["type"] == "preference"
        assert "优惠" in resp.injected_memories[0]["content"]
        assert mock_db.execute.called

    async def test_max_count_caps_results(self, mock_db, service):
        customer_id = uuid4()
        memories = [
            _make_memory(f"客户偏好优惠{ i }折扣活动", customer_id) for i in range(10)
        ]
        _db_execute_returns(mock_db, memories)

        request = MemoryInjectionRequest(
            conversation_id=uuid4(),
            customer_id=customer_id,
            recent_messages=[{"role": "user", "content": "优惠 折扣"}],
            max_memory_count=3,
        )

        resp = await service.inject_memories_into_context(request)
        assert resp.injection_count == 3


class TestInjectEmptyContextContractPath:
    """BUG-3 (QA t_3eb34805) end-to-end: POST /api/v1/memory/inject with an
    empty recent_messages list (first-round conversation, a legal boundary)
    must return 200 with injection_count=0 — NOT 500.

    This is the exact QA scenario. It also pins the P0 contract path
    (p0_openapi_paths.json /api/v1/memory/inject): the memory router
    self-carries its /api/v1/memory prefix and is mounted bare in main.py.
    """

    def test_empty_recent_messages_returns_200(self, mock_db):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.routers.memory import router as memory_router, get_memory_service

        probe_app = FastAPI()
        probe_app.include_router(memory_router)
        probe_app.dependency_overrides[get_memory_service] = lambda: MemoryService(mock_db)
        client = TestClient(probe_app)

        response = client.post(
            "/api/v1/memory/inject",
            json={
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "recent_messages": [],
                "max_memory_count": 5,
            },
        )

        assert response.status_code == 200, f"got {response.status_code}: {response.text}"
        data = response.json()
        assert data["injected_memories"] == []
        assert data["injection_count"] == 0
        assert data["context_tokens_added"] == 0
