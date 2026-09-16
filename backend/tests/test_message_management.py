"""Tests for Message Management API - Complete coverage"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessageUpdate,
    MessageResponse,
    RedoResponse,
)
from app.services.conversation_service import ConversationService


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
    conversation.subject = kwargs.get('subject', 'Test Subject')
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


def _make_message_mock(**kwargs):
    """Helper to create a message mock with proper defaults"""
    now = datetime.now(timezone.utc)
    message = MagicMock()
    message.id = kwargs.get('id', uuid4())
    message.conversation_id = kwargs.get('conversation_id', uuid4())
    message.parent_id = kwargs.get('parent_id', None)
    message.role = kwargs.get('role', 'user')
    message.content = kwargs.get('content', 'Test message content')
    message.edit_count = kwargs.get('edit_count', 0)
    message.metadata_ = kwargs.get('metadata_', None)
    message.created_at = kwargs.get('created_at', now)
    message.updated_at = kwargs.get('updated_at', now)
    message.is_deleted = kwargs.get('is_deleted', False)
    # Ensure edit_count is always an int
    if message.edit_count is None:
        message.edit_count = 0
    return message


class TestMessageCreate:
    """Test message creation with all features"""

    @pytest.mark.asyncio
    async def test_create_user_message(self, mock_db):
        """Test creating a user message"""
        conversation = _make_conversation_mock()
        message_data = MessageCreate(
            conversation_id=conversation.id,
            role="user",
            content="Hello, AI!",
        )

        # Mock conversation check
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        # Mock refresh
        def refresh(obj):
            obj.id = uuid4()
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
            obj.edit_count = 0
        mock_db.refresh.side_effect = refresh

        # Mock stats update
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        last_result = MagicMock()
        last_result.scalar_one.return_value = datetime.now(timezone.utc)
        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute.side_effect = [
            conv_result,
            count_result,
            last_result,
            update_result,
        ]

        service = ConversationService(mock_db)
        result = await service.create_message(message_data)

        assert result is not None
        assert result.role == "user"
        assert result.content == "Hello, AI!"
        assert result.parent_id is None
        assert result.edit_count == 0

    @pytest.mark.asyncio
    async def test_create_message_with_parent(self, mock_db):
        """Test creating a message with parent_id"""
        conversation = _make_conversation_mock()
        parent_message = _make_message_mock(role="user")
        
        message_data = MessageCreate(
            conversation_id=conversation.id,
            role="user",
            content="Reply to parent",
            parent_id=parent_message.id,
        )

        # Mock conversation check
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        def refresh(obj):
            obj.id = uuid4()
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
            obj.edit_count = 0
        mock_db.refresh.side_effect = refresh

        # Mock stats update
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        last_result = MagicMock()
        last_result.scalar_one.return_value = datetime.now(timezone.utc)
        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute.side_effect = [
            conv_result,
            count_result,
            last_result,
            update_result,
        ]

        service = ConversationService(mock_db)
        result = await service.create_message(message_data)

        assert result.parent_id == parent_message.id

    @pytest.mark.asyncio
    async def test_create_message_invalid_role(self, mock_db):
        """Test creating message with invalid role fails at schema validation"""
        with pytest.raises(Exception):  # Pydantic validation error
            MessageCreate(
                conversation_id=uuid4(),
                role="invalid_role",
                content="Test",
            )

    @pytest.mark.asyncio
    async def test_create_message_empty_content(self, mock_db):
        """Test creating message with empty content fails"""
        with pytest.raises(Exception):  # Pydantic validation error
            MessageCreate(
                conversation_id=uuid4(),
                role="user",
                content="",
            )

    @pytest.mark.asyncio
    async def test_create_message_xss_protection(self, mock_db):
        """Test XSS protection in content"""
        # Test that HTML tags are removed
        xss_content = '<script>alert("xss")</script>Hello'
        message_data = MessageCreate(
            conversation_id=uuid4(),
            role="user",
            content=xss_content,
        )
        # The validator should have sanitized the content
        assert "<script>" not in message_data.content
        assert "</script>" not in message_data.content
        assert "Hello" in message_data.content


class TestMessageList:
    """Test message listing with filters"""

    @pytest.mark.asyncio
    async def test_list_messages_basic(self, mock_db):
        """Test listing messages without filters"""
        conversation = _make_conversation_mock()
        messages = [_make_message_mock(conversation_id=conversation.id) for _ in range(5)]

        # Mock conversation check
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        # Mock count query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 5
        mock_db.execute.side_effect = [conv_result, count_result]

        # Mock list query
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = messages
        mock_db.execute.side_effect = [conv_result, count_result, list_result]

        service = ConversationService(mock_db)
        items, total = await service.list_messages(conversation.id)

        assert total == 5
        assert len(items) == 5

    @pytest.mark.asyncio
    async def test_list_messages_filtered_by_role(self, mock_db):
        """Test listing messages filtered by role"""
        conversation = _make_conversation_mock()
        messages = [_make_message_mock(conversation_id=conversation.id, role="assistant") for _ in range(3)]

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        count_result = MagicMock()
        count_result.scalar_one.return_value = 3
        mock_db.execute.side_effect = [conv_result, count_result]

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = messages
        mock_db.execute.side_effect = [conv_result, count_result, list_result]

        service = ConversationService(mock_db)
        items, total = await service.list_messages(conversation.id, role="assistant")

        assert total == 3
        assert all(m.role == "assistant" for m in items)

    @pytest.mark.asyncio
    async def test_list_messages_with_time_range(self, mock_db):
        """Test listing messages with time range filter"""
        conversation = _make_conversation_mock()
        messages = [_make_message_mock(conversation_id=conversation.id) for _ in range(2)]
        
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        end_time = datetime.now(timezone.utc)

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        mock_db.execute.side_effect = [conv_result, count_result]

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = messages
        mock_db.execute.side_effect = [conv_result, count_result, list_result]

        service = ConversationService(mock_db)
        items, total = await service.list_messages(
            conversation.id,
            start_time=start_time,
            end_time=end_time,
        )

        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_list_messages_pagination(self, mock_db):
        """Test message pagination"""
        conversation = _make_conversation_mock()
        messages = [_make_message_mock(conversation_id=conversation.id) for _ in range(10)]

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        count_result = MagicMock()
        count_result.scalar_one.return_value = 10
        mock_db.execute.side_effect = [conv_result, count_result]

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = messages[:5]
        mock_db.execute.side_effect = [conv_result, count_result, list_result]

        service = ConversationService(mock_db)
        items, total = await service.list_messages(conversation.id, page=1, page_size=5)

        assert total == 10
        assert len(items) == 5


class TestMessageUpdate:
    """Test message editing with restrictions"""

    @pytest.mark.asyncio
    async def test_update_user_message_success(self, mock_db):
        """Test updating a user message"""
        message = _make_message_mock(role="user", edit_count=0)

        result = MagicMock()
        result.scalar_one_or_none.return_value = message
        mock_db.execute.return_value = result

        def refresh(obj):
            obj.updated_at = datetime.now(timezone.utc)
            obj.edit_count = 1
        mock_db.refresh.side_effect = refresh

        service = ConversationService(mock_db)
        updated = await service.update_message(
            message.id,
            MessageUpdate(content="Updated content")
        )

        assert updated is not None
        assert updated.content == "Updated content"
        assert updated.edit_count == 1

    @pytest.mark.asyncio
    async def test_update_message_edit_limit(self, mock_db):
        """Test message edit limit (max 3 times)"""
        message = _make_message_mock(role="user", edit_count=3)

        result = MagicMock()
        result.scalar_one_or_none.return_value = message
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        
        with pytest.raises(ValueError, match="only be edited 3 times"):
            await service.update_message(
                message.id,
                MessageUpdate(content="Too many edits")
            )

    @pytest.mark.asyncio
    async def test_update_assistant_message_blocked(self, mock_db):
        """Test that assistant messages cannot be edited"""
        message = _make_message_mock(role="assistant", edit_count=0)

        result = MagicMock()
        result.scalar_one_or_none.return_value = message
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        
        with pytest.raises(ValueError, match="Only user messages can be edited"):
            await service.update_message(
                message.id,
                MessageUpdate(content="Should not work")
            )

    @pytest.mark.asyncio
    async def test_update_system_message_blocked(self, mock_db):
        """Test that system messages cannot be edited"""
        message = _make_message_mock(role="system", edit_count=0)

        result = MagicMock()
        result.scalar_one_or_none.return_value = message
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        
        with pytest.raises(ValueError, match="Only user messages can be edited"):
            await service.update_message(
                message.id,
                MessageUpdate(content="Should not work")
            )


class TestMessageDelete:
    """Test message deletion"""

    @pytest.mark.asyncio
    async def test_delete_single_message(self, mock_db):
        """Test soft deleting a single message"""
        message = _make_message_mock()

        result = MagicMock()
        result.scalar_one_or_none.return_value = message
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        success = await service.delete_message(message.id)

        assert success is True
        assert message.is_deleted is True

    @pytest.mark.asyncio
    async def test_batch_delete_messages(self, mock_db):
        """Test batch deleting multiple messages"""
        conversation = _make_conversation_mock()
        messages = [_make_message_mock(conversation_id=conversation.id) for _ in range(3)]
        message_ids = [m.id for m in messages]

        # Mock conversation check
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        # Mock batch delete
        delete_result = MagicMock()
        delete_result.rowcount = 3

        # Mock stats update calls
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        last_result = MagicMock()
        last_result.scalar_one.return_value = datetime.now(timezone.utc)
        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute.side_effect = [
            conv_result,  # conversation check
            delete_result,  # batch delete
            count_result,  # count messages
            last_result,  # last message time
            update_result,  # update conversation
        ]

        service = ConversationService(mock_db)
        deleted_count = await service.batch_delete_messages(conversation.id, message_ids)

        assert deleted_count == 3

    @pytest.mark.asyncio
    async def test_batch_delete_empty_list(self, mock_db):
        """Test batch delete with empty list"""
        conversation = _make_conversation_mock()

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        service = ConversationService(mock_db)
        deleted_count = await service.batch_delete_messages(conversation.id, [])

        assert deleted_count == 0


class TestRedoMessage:
    """Test redo functionality"""

    @pytest.mark.asyncio
    async def test_redo_assistant_message(self, mock_db):
        """Test redoing an assistant message"""
        conversation = _make_conversation_mock()
        original_message = _make_message_mock(
            conversation_id=conversation.id,
            role="assistant",
            content="Original AI response"
        )

        # Mock conversation check
        conv_result1 = MagicMock()
        conv_result1.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result1

        # Mock message retrieval
        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = original_message

        # Mock stats update
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        last_result = MagicMock()
        last_result.scalar_one.return_value = datetime.now(timezone.utc)
        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute.side_effect = [
            conv_result1,  # conversation check
            msg_result,  # get message
            count_result,  # count
            last_result,  # last time
            update_result,  # update
        ]

        # Mock refresh for new message
        def refresh(obj):
            if hasattr(obj, 'id'):
                obj.id = uuid4()
            if hasattr(obj, 'created_at'):
                obj.created_at = datetime.now(timezone.utc)
        mock_db.refresh.side_effect = refresh
        mock_db.add = MagicMock()

        service = ConversationService(mock_db)
        result = await service.redo_message(conversation.id, original_message.id)

        assert result.original_id == original_message.id
        assert result.new_id is not None
        assert result.original_role == "assistant"
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_redo_user_message_blocked(self, mock_db):
        """Test that user messages cannot be redone"""
        conversation = _make_conversation_mock()
        user_message = _make_message_mock(
            conversation_id=conversation.id,
            role="user",
            content="User message"
        )

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = user_message
        mock_db.execute.side_effect = [conv_result, msg_result]

        service = ConversationService(mock_db)
        
        with pytest.raises(ValueError, match="Only assistant messages can be redone"):
            await service.redo_message(conversation.id, user_message.id)


class TestConversationStatsUpdate:
    """Test conversation statistics auto-update"""

    @pytest.mark.asyncio
    async def test_create_message_updates_stats(self, mock_db):
        """Test that creating a message updates conversation stats"""
        conversation = _make_conversation_mock(message_count=0)
        message_data = MessageCreate(
            conversation_id=conversation.id,
            role="user",
            content="Hello",
        )

        # Mock conversation check
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        # Mock refresh - ensure all attributes are set
        def refresh(obj):
            obj.id = uuid4()
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
            obj.edit_count = 0
            obj.parent_id = None
        mock_db.refresh.side_effect = refresh

        # Mock stats update
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        last_result = MagicMock()
        last_result.scalar_one.return_value = datetime.now(timezone.utc)
        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute.side_effect = [
            conv_result,  # conversation check
            count_result,  # message count
            last_result,  # last message time
            update_result,  # update conversation
        ]

        service = ConversationService(mock_db)
        result = await service.create_message(message_data)

        assert result is not None
        assert result.edit_count == 0
        # Verify update_conversation_message_stats was called
        assert mock_db.execute.call_count >= 4

    @pytest.mark.asyncio
    async def test_delete_message_updates_stats(self, mock_db):
        """Test that deleting a message updates conversation stats"""
        conversation = _make_conversation_mock(message_count=5)
        message = _make_message_mock(conversation_id=conversation.id)

        # Mock message retrieval
        result = MagicMock()
        result.scalar_one_or_none.return_value = message
        mock_db.execute.return_value = result

        # Mock stats update
        count_result = MagicMock()
        count_result.scalar_one.return_value = 4
        last_result = MagicMock()
        last_result.scalar_one.return_value = datetime.now(timezone.utc)
        update_result = MagicMock()
        update_result.rowcount = 1
        
        mock_db.execute.side_effect = [
            result,  # get message
            count_result,  # count messages
            last_result,  # last message time
            update_result,  # update conversation
        ]

        service = ConversationService(mock_db)
        success = await service.delete_message(message.id)

        assert success is True


class TestXSSProtection:
    """Test XSS protection"""

    def test_script_tag_removal(self):
        """Test script tag removal"""
        from app.schemas.conversation import MessageCreate
        
        content = '<script>alert("xss")</script>Hello World'
        data = MessageCreate(
            conversation_id=uuid4(),
            role="user",
            content=content,
        )
        assert "<script>" not in data.content
        assert "</script>" not in data.content
        assert "Hello World" in data.content

    def test_html_tag_removal(self):
        """Test HTML tag removal"""
        from app.schemas.conversation import MessageCreate
        
        content = '<b>Bold</b> and <i>italic</i>'
        data = MessageCreate(
            conversation_id=uuid4(),
            role="user",
            content=content,
        )
        assert "<b>" not in data.content
        assert "<i>" not in data.content
        assert "Bold" in data.content
        assert "italic" in data.content

    def test_javascript_protocol_removal(self):
        """Test javascript: protocol removal"""
        from app.schemas.conversation import MessageCreate
        
        content = '<a href="javascript:alert(1)">Click</a>'
        data = MessageCreate(
            conversation_id=uuid4(),
            role="user",
            content=content,
        )
        assert "javascript:" not in data.content
        assert "alert" not in data.content


class TestRouterEndpoints:
    """Test router endpoint configuration"""

    def test_router_exists(self):
        """Test that router module exists"""
        from app.routers.conversations import router
        assert router is not None

    def test_router_prefix(self):
        """Test router prefix"""
        from app.routers.conversations import router
        assert router.prefix == "/conversations"

    def test_all_endpoints_registered(self):
        """Test that all expected endpoints are registered"""
        from app.routers.conversations import router
        
        routes = [route.path for route in router.routes]
        
        expected_routes = [
            "/",  # List conversations
            "/{conversation_id}",  # Get/update/delete conversation
            "/{conversation_id}/messages",  # List/create/batch delete messages
            "/{conversation_id}/messages/history",  # Get history
            "/{conversation_id}/context-window",  # Get context window
            "/{conversation_id}/compress",  # Compress history
            "/{conversation_id}/stats",  # Get stats
            "/messages/{message_id}",  # Get/update/delete message
            "/{conversation_id}/messages/{message_id}/redo",  # Redo message
        ]
        
        for expected in expected_routes:
            assert any(expected in route for route in routes), f"Missing route: {expected}"


class TestServiceMethods:
    """Test service method signatures"""

    def test_service_class_exists(self):
        """Test that ConversationService exists"""
        from app.services.conversation_service import ConversationService
        assert ConversationService is not None

    def test_service_methods(self):
        """Test that all expected methods exist"""
        from app.services.conversation_service import ConversationService
        
        methods = [
            'create_conversation',
            'get_conversation',
            'list_conversations',
            'update_conversation',
            'delete_conversation',
            'update_conversation_message_stats',
            'create_message',
            'get_message',
            'list_messages',
            'update_message',
            'delete_message',
            'batch_delete_messages',
            'redo_message',
            'get_conversation_history',
            'compress_conversation_history',
            'get_context_window',
            'get_conversation_stats',
        ]
        
        for method in methods:
            assert hasattr(ConversationService, method), f"Missing method: {method}"

    def test_service_constants(self):
        """Test service constants"""
        from app.services.conversation_service import ConversationService
        
        assert hasattr(ConversationService, 'MAX_EDIT_COUNT')
        assert ConversationService.MAX_EDIT_COUNT == 3


class TestMigration:
    """Test database migration"""

    def test_migration_file_exists(self):
        """Test migration file exists"""
        import os
        migration_path = "H:/AI-Agent-Platform/backend/alembic/versions/012_message_management.py"
        assert os.path.exists(migration_path), f"Migration file not found: {migration_path}"

    def test_migration_has_upgrade(self):
        """Test migration has upgrade function"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration",
            "H:/AI-Agent-Platform/backend/alembic/versions/012_message_management.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, 'upgrade')
        assert hasattr(module, 'downgrade')
