"""P1-003 gap tests: restore endpoint, deleted filter, search, sort/order, auto-subject, message_count maintenance.

Follows the mock/AsyncMock style of test_message_management.py / test_conversation_api.py.
Query-shape assertions use compiled Postgres SQL (ILIKE / NULLS LAST / is_deleted)
which is the only stable way to introspect SQLAlchemy queries in unit tests.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects import postgresql

# Import the model package (not just conversation) so all mappers
# (DecisionLog, Intent, etc.) are registered — required when this file
# runs standalone.
import app.db.models  # noqa: F401

from app.schemas.conversation import MessageCreate, ConversationResponse
from app.services.conversation_service import ConversationService


def _compiled(query) -> str:
    """Compile a SQLAlchemy query to Postgres SQL with literal binds."""
    return str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.fixture
def mock_db():
    """Create a mock database session"""
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _make_conversation_mock(**kwargs):
    """Helper to create a conversation mock with proper defaults"""
    now = datetime.now(timezone.utc)
    conversation = MagicMock()
    conversation.id = kwargs.get('id', uuid4())
    conversation.customer_id = kwargs.get('customer_id', uuid4())
    conversation.channel = kwargs.get('channel', 'web')
    conversation.subject = kwargs.get('subject', None)
    conversation.status = kwargs.get('status', 'active')
    conversation.summary = kwargs.get('summary', None)
    conversation.sentiment = kwargs.get('sentiment', None)
    conversation.duration_seconds = kwargs.get('duration_seconds', None)
    conversation.message_count = kwargs.get('message_count', 0)
    conversation.last_message_at = kwargs.get('last_message_at', None)
    conversation.tags = kwargs.get('tags', [])
    conversation.metadata_ = kwargs.get('metadata_', None)
    conversation.created_at = kwargs.get('created_at', now)
    conversation.updated_at = kwargs.get('updated_at', now)
    conversation.is_deleted = kwargs.get('is_deleted', False)
    return conversation


def _list_mocks(mock_db, conversations):
    """Wire count + list execute results for list_conversations"""
    count_result = MagicMock()
    count_result.scalar_one.return_value = len(conversations)
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = conversations
    mock_db.execute.side_effect = [count_result, list_result]


def _list_query(mock_db):
    """Return the compiled SQL of the paginated list query (2nd execute call)"""
    return _compiled(mock_db.execute.call_args_list[1][0][0])


def _full_message_refresh(mock_db):
    """refresh() side effect that fully initializes a real Message model."""
    def refresh(obj):
        obj.id = uuid4()
        obj.created_at = datetime.now(timezone.utc)
        obj.updated_at = datetime.now(timezone.utc)
        obj.edit_count = 0
    mock_db.refresh.side_effect = refresh


class TestRestoreConversation:
    """POST /{id}/restore service behavior"""

    @pytest.mark.asyncio
    async def test_restore_sets_flags(self, mock_db):
        """Restore reverts is_deleted and sets status to active"""
        conversation = _make_conversation_mock(is_deleted=True, status='archived')

        result = MagicMock()
        result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        restored = await service.restore_conversation(conversation.id)

        assert restored is not None
        assert conversation.is_deleted is False
        assert conversation.status == 'active'
        mock_db.commit.assert_awaited()
        mock_db.refresh.assert_awaited()

    @pytest.mark.asyncio
    async def test_restore_not_found(self, mock_db):
        """Restore of a non-existent conversation returns None (router -> 404)"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        assert await service.restore_conversation(uuid4()) is None
        mock_db.commit.assert_not_awaited()

    def test_router_registers_restore_route(self):
        """The router exposes POST /conversations/{id}/restore"""
        from app.routers.conversations import router

        matches = [r for r in router.routes if r.path == "/conversations/{conversation_id}/restore"]
        assert len(matches) == 1
        assert "POST" in matches[0].methods


class TestListConversationsFilters:
    """list_conversations: status=deleted, search, sort/order"""

    @pytest.mark.asyncio
    async def test_deleted_status_queries_is_deleted_true(self, mock_db):
        """status=deleted selects is_deleted=True and does NOT hit the status column"""
        convs = [_make_conversation_mock(is_deleted=True, status='archived')]
        _list_mocks(mock_db, convs)

        service = ConversationService(mock_db)
        items, total = await service.list_conversations(status='deleted')

        assert total == 1 and len(items) == 1
        sql = _list_query(mock_db).lower()
        assert "is_deleted = true" in sql
        assert "status = " not in sql  # 'deleted' must not become a status-column filter

    @pytest.mark.asyncio
    async def test_non_deleted_status_excludes_deleted_rows(self, mock_db):
        """Any real status filter keeps is_deleted=False and adds status column filter"""
        _list_mocks(mock_db, [])

        service = ConversationService(mock_db)
        await service.list_conversations(status='active')

        sql = _list_query(mock_db).lower()
        assert "is_deleted = false" in sql
        assert "status = 'active'" in sql

    @pytest.mark.asyncio
    async def test_no_status_keeps_live_rows(self, mock_db):
        """Default (no status) still filters is_deleted=False — no regression"""
        _list_mocks(mock_db, [])

        service = ConversationService(mock_db)
        await service.list_conversations()

        assert "is_deleted = false" in _list_query(mock_db).lower()

    @pytest.mark.asyncio
    async def test_search_uses_ilike_on_subject(self, mock_db):
        """search parameter fuzzy-matches subject via ILIKE"""
        _list_mocks(mock_db, [])

        service = ConversationService(mock_db)
        await service.list_conversations(search='报价')

        query = mock_db.execute.call_args_list[1][0][0]
        sql = str(query.compile(dialect=postgresql.dialect())).lower()
        params = query.compile(dialect=postgresql.dialect()).params
        # ILIKE on the subject column: Postgres may render native ILIKE or the
        # ANSI-emulated "lower(x) like lower(y)" form depending on compilation
        # flags; both are case-insensitive matching on subject.
        assert "subject" in sql
        assert "ilike" in sql or "like lower" in sql
        bound = [p for p in params.values() if isinstance(p, str) and p.startswith("%") and p.endswith("%")]
        assert any("报价" in p for p in bound), f"expected %-wrapped ILIKE bound value containing 报价, got {params}"

    @pytest.mark.asyncio
    async def test_default_sort_is_last_message_at_desc_nulls_last(self, mock_db):
        """Default ordering: last_message_at DESC with NULLs last"""
        _list_mocks(mock_db, [])

        service = ConversationService(mock_db)
        await service.list_conversations()

        sql = _list_query(mock_db).lower()
        assert "order by conversation.last_message_at desc nulls last" in sql

    @pytest.mark.asyncio
    async def test_sort_created_at_asc_nulls_last(self, mock_db):
        """Explicit sort=created_at&order=asc honored, NULLs still last"""
        _list_mocks(mock_db, [])

        service = ConversationService(mock_db)
        await service.list_conversations(sort='created_at', order='asc')

        sql = _list_query(mock_db).lower()
        assert "order by conversation.created_at asc nulls last" in sql


class TestRouterListParams:
    """The list endpoint exposes the new query parameters and validates them."""

    def test_list_endpoint_has_new_params(self):
        from app.routers.conversations import router

        list_route = next(r for r in router.routes if r.path == "/conversations/")
        # FastAPI stores the endpoint function directly; pull the Python signature
        import inspect
        params = set(inspect.signature(list_route.endpoint).parameters)
        for expected in ("search", "sort", "order", "status", "customer_id", "channel"):
            assert expected in params, f"missing list param: {expected}"

    @pytest.mark.asyncio
    async def test_list_rejects_bad_sort(self):
        """Invalid sort value -> 400 (FastAPI-level guard in the router)"""
        from app.routers.conversations import list_conversations
        from fastapi import HTTPException

        class _Svc:
            async def list_conversations(self, **kw):
                return [], 0

        with pytest.raises(HTTPException) as exc:
            await list_conversations(
                customer_id=None, status=None, channel=None,
                search=None, sort="bogus", order="desc",
                page=1, page_size=20, service=_Svc(),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_list_rejects_bad_order(self):
        from app.routers.conversations import list_conversations
        from fastapi import HTTPException

        class _Svc:
            async def list_conversations(self, **kw):
                return [], 0

        with pytest.raises(HTTPException) as exc:
            await list_conversations(
                customer_id=None, status=None, channel=None,
                search=None, sort="created_at", order="sideways",
                page=1, page_size=20, service=_Svc(),
            )
        assert exc.value.status_code == 400


class TestAutoSubject:
    """create_message auto-generates the conversation title"""

    async def _create(self, mock_db, conversation, content, role="user"):
        data = MessageCreate(conversation_id=conversation.id, role=role, content=content)
        _full_message_refresh(mock_db)

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        # execute order: _get_by_id, stats(count), stats(max), stats(update)
        mock_db.execute.side_effect = [
            conv_result,
            MagicMock(scalar_one=MagicMock(return_value=1)),
            MagicMock(scalar_one=MagicMock(return_value=datetime.now(timezone.utc))),
            MagicMock(),
        ]

        service = ConversationService(mock_db)
        return await service.create_message(data)

    @pytest.mark.asyncio
    async def test_subject_generated_for_user_message(self, mock_db):
        """Empty subject + user message -> subject = first 80 chars of content"""
        conversation = _make_conversation_mock(subject=None)
        content = "帮" * 100

        await self._create(mock_db, conversation, content)
        assert conversation.subject == "帮" * 80
        assert len(conversation.subject) == 80

    @pytest.mark.asyncio
    async def test_short_content_kept_whole(self, mock_db):
        """Content shorter than 80 chars is stored as-is"""
        conversation = _make_conversation_mock(subject=None)
        await self._create(mock_db, conversation, "你好")
        assert conversation.subject == "你好"

    @pytest.mark.asyncio
    async def test_subject_not_overwritten(self, mock_db):
        """An existing subject is never replaced"""
        conversation = _make_conversation_mock(subject="已有标题")
        await self._create(mock_db, conversation, "新内容")
        assert conversation.subject == "已有标题"

    @pytest.mark.asyncio
    async def test_no_subject_for_assistant_message(self, mock_db):
        """Auto-title only applies to user messages"""
        conversation = _make_conversation_mock(subject=None)
        await self._create(mock_db, conversation, "助手回复", role="assistant")
        assert conversation.subject is None


class TestMessageCountMaintenance:
    """Denormalized conversation.message_count upkeep (migration 012)"""

    @pytest.mark.asyncio
    async def test_create_message_updates_denormalized_count(self, mock_db):
        """create_message recomputes message_count/last_message_at via UPDATE"""
        conversation = _make_conversation_mock(subject=None)
        _full_message_refresh(mock_db)

        data = MessageCreate(conversation_id=conversation.id, role="user", content="hi")
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.side_effect = [
            conv_result,
            MagicMock(scalar_one=MagicMock(return_value=3)),
            MagicMock(scalar_one=MagicMock(return_value=datetime.now(timezone.utc))),
            MagicMock(),
        ]

        service = ConversationService(mock_db)
        await service.create_message(data)

        update_sql = _compiled(mock_db.execute.call_args_list[3][0][0])
        assert "UPDATE conversation" in update_sql
        assert "message_count" in update_sql
        assert "last_message_at" in update_sql

    @pytest.mark.asyncio
    async def test_delete_message_updates_denormalized_count(self, mock_db):
        """Soft-deleting a message recomputes the denormalized counters"""
        message = _make_message_deleted_mock()

        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = message
        mock_db.execute.side_effect = [
            get_result,
            MagicMock(scalar_one=MagicMock(return_value=0)),
            MagicMock(scalar_one=MagicMock(return_value=None)),
            MagicMock(),
        ]

        service = ConversationService(mock_db)
        success = await service.delete_message(message.id)

        assert success is True
        assert message.is_deleted is True
        update_sql = _compiled(mock_db.execute.call_args_list[3][0][0])
        assert "UPDATE conversation" in update_sql and "message_count" in update_sql

    @pytest.mark.asyncio
    async def test_batch_delete_maintains_counters(self, mock_db):
        """batch_delete_messages recomputes stats only when rows were deleted"""
        conversation = _make_conversation_mock()
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation

        update_result = MagicMock()
        update_result.rowcount = 2
        mock_db.execute.side_effect = [
            conv_result,
            update_result,
            MagicMock(scalar_one=MagicMock(return_value=1)),
            MagicMock(scalar_one=MagicMock(return_value=None)),
            MagicMock(),
        ]

        service = ConversationService(mock_db)
        deleted = await service.batch_delete_messages(conversation.id, [uuid4(), uuid4()])

        assert deleted == 2
        update_sql = _compiled(mock_db.execute.call_args_list[4][0][0])
        assert "UPDATE conversation" in update_sql and "message_count" in update_sql

    def test_response_schema_reads_denormalized_column(self):
        """ConversationResponse exposes message_count/last_message_at fields"""
        fields = ConversationResponse.model_fields
        assert "message_count" in fields
        assert "last_message_at" in fields


def _make_message_deleted_mock():
    now = datetime.now(timezone.utc)
    m = MagicMock()
    m.id = uuid4()
    m.conversation_id = uuid4()
    m.role = "user"
    m.content = "x"
    m.is_deleted = False
    m.created_at = now
    m.updated_at = now
    return m


class TestMigration012:
    """Alembic 012 migration integrity (message_count denormalization)"""

    def test_migration_012_exists(self):
        import os
        path = "H:/AI-Agent-Platform/backend/alembic/versions/012_message_management.py"
        assert os.path.exists(path)

    def test_migration_012_adds_message_count(self):
        import importlib.util
        path = "H:/AI-Agent-Platform/backend/alembic/versions/012_message_management.py"
        spec = importlib.util.spec_from_file_location("migration_012", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert module.down_revision == "011_memory_system"
        assert hasattr(module, "upgrade")
        assert hasattr(module, "downgrade")
        src = open(path, encoding="utf-8").read()
        assert "message_count" in src
        assert "last_message_at" in src
