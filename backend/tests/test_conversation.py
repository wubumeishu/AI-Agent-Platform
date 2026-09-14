"""Tests for Conversation module - Unit tests only"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessageUpdate,
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


class TestConversationService:
    """Test cases for ConversationService"""

    @pytest.mark.asyncio
    async def test_create_conversation(self, mock_db):
        """Test creating a new conversation"""
        conversation_data = ConversationCreate(
            customer_id=uuid4(),
            channel="web",
            subject="Test Conversation",
            status="active",
        )

        # Mock the add and refresh calls
        captured = []
        def capture_add(obj):
            captured.append(obj)
        mock_db.add.side_effect = capture_add

        def refresh(obj):
            obj.id = uuid4()
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
            obj.edit_count = 0
            obj.parent_id = None
        mock_db.refresh.side_effect = refresh

        # Mock count query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_db.execute.return_value = count_result

        service = ConversationService(mock_db)
        result = await service.create_conversation(conversation_data)

        assert result is not None
        assert result.subject == "Test Conversation"
        assert result.channel == "web"
        assert result.message_count == 0

    @pytest.mark.asyncio
    async def test_get_conversation_found(self, mock_db):
        """Test getting an existing conversation"""
        conversation = _make_conversation_mock()

        # Mock execution: get conversation + count messages
        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = conversation
        
        count_result = MagicMock()
        count_result.scalar_one.return_value = 5
        
        mock_db.execute.side_effect = [get_result, count_result]

        service = ConversationService(mock_db)
        fetched = await service.get_conversation(conversation.id)

        assert fetched is not None
        assert fetched.id == conversation.id
        assert fetched.subject == conversation.subject

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self, mock_db):
        """Test getting a non-existent conversation"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        fetched = await service.get_conversation(uuid4())

        assert fetched is None

    @pytest.mark.asyncio
    async def test_list_conversations(self, mock_db):
        """Test listing conversations with pagination"""
        conversations = [_make_conversation_mock() for _ in range(3)]

        # Count query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3
        
        # List query
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = conversations
        
        # Count for each conversation
        conv_count = MagicMock()
        conv_count.scalar_one.return_value = 0
        
        mock_db.execute.side_effect = [
            count_result, 
            list_result,
            conv_count, conv_count, conv_count
        ]

        service = ConversationService(mock_db)
        items, total = await service.list_conversations(page=1, page_size=10)

        assert total == 3
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_list_conversations_with_filters(self, mock_db):
        """Test listing conversations with filters"""
        conversations = [_make_conversation_mock(status='active')]

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = conversations
        
        conv_count = MagicMock()
        conv_count.scalar_one.return_value = 0
        
        mock_db.execute.side_effect = [count_result, list_result, conv_count]

        service = ConversationService(mock_db)
        items, total = await service.list_conversations(
            customer_id=conversations[0].customer_id,
            status='active',
        )

        assert total == 1
        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_update_conversation(self, mock_db):
        """Test updating a conversation"""
        conversation = _make_conversation_mock()

        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = conversation
        
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        
        mock_db.execute.side_effect = [get_result, count_result]

        service = ConversationService(mock_db)
        updated = await service.update_conversation(
            conversation.id,
            ConversationUpdate(subject="Updated Subject")
        )

        assert updated is not None
        assert updated.subject == "Updated Subject"

    @pytest.mark.asyncio
    async def test_delete_conversation(self, mock_db):
        """Test soft deleting a conversation"""
        conversation = _make_conversation_mock()

        result = MagicMock()
        result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        success = await service.delete_conversation(conversation.id)

        assert success is True
        assert conversation.is_deleted is True

    @pytest.mark.asyncio
    async def test_delete_conversation_not_found(self, mock_db):
        """Test deleting a non-existent conversation"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        success = await service.delete_conversation(uuid4())

        assert success is False


class TestMessageService:
    """Test cases for Message operations"""

    @pytest.mark.asyncio
    async def test_create_message(self, mock_db):
        """Test creating a new message"""
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
        assert result.edit_count == 0

    @pytest.mark.asyncio
    async def test_create_message_conversation_not_found(self, mock_db):
        """Test creating message with non-existent conversation"""
        message_data = MessageCreate(
            conversation_id=uuid4(),
            role="user",
            content="Hello!",
        )

        # Mock conversation check - not found
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        with pytest.raises(ValueError, match="Conversation not found"):
            await service.create_message(message_data)

    @pytest.mark.asyncio
    async def test_list_messages(self, mock_db):
        """Test listing messages in a conversation"""
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

        # Mock conversation check
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        # Mock count query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3
        mock_db.execute.side_effect = [conv_result, count_result]

        # Mock list query
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = messages
        mock_db.execute.side_effect = [conv_result, count_result, list_result]

        service = ConversationService(mock_db)
        items, total = await service.list_messages(
            conversation.id,
            role="assistant"
        )

        assert total == 3
        assert all(m.role == "assistant" for m in items)

    @pytest.mark.asyncio
    async def test_update_message(self, mock_db):
        """Test updating a message"""
        message = _make_message_mock()

        result = MagicMock()
        result.scalar_one_or_none.return_value = message
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        updated = await service.update_message(
            message.id,
            MessageUpdate(content="Updated content")
        )

        assert updated is not None
        assert updated.content == "Updated content"

    @pytest.mark.asyncio
    async def test_delete_message(self, mock_db):
        """Test soft deleting a message"""
        message = _make_message_mock()

        result = MagicMock()
        result.scalar_one_or_none.return_value = message
        mock_db.execute.return_value = result

        service = ConversationService(mock_db)
        success = await service.delete_message(message.id)

        assert success is True
        assert message.is_deleted is True


class TestConversationHistory:
    """Test conversation history and context window management"""

    @pytest.mark.asyncio
    async def test_get_conversation_history(self, mock_db):
        """Test getting conversation history"""
        conversation = _make_conversation_mock()
        messages = [
            _make_message_mock(
                conversation_id=conversation.id,
                role="user",
                content=f"Message {i}"
            ) for i in range(5)
        ]

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
        history = await service.get_conversation_history(conversation.id, limit=10)

        assert len(history) == 5
        assert all(m.role == "user" for m in history)

    @pytest.mark.asyncio
    async def test_compress_conversation_history(self, mock_db):
        """Test compressing conversation history"""
        conversation = _make_conversation_mock()
        messages = [
            _make_message_mock(
                conversation_id=conversation.id,
                content=f"Old message {i}"
            ) for i in range(150)  # More than MAX_MESSAGES_PER_CONVERSATION
        ]

        call_count = [0]
        def execute_side_effect(query):
            call_count[0] += 1
            # First call: _get_by_id in list_messages
            if call_count[0] == 1:
                result = MagicMock()
                result.scalar_one_or_none.return_value = conversation
                return result
            # Second call: count query in list_messages
            elif call_count[0] == 2:
                result = MagicMock()
                result.scalar_one.return_value = 150
                return result
            # Third call: list query in list_messages
            elif call_count[0] == 3:
                result = MagicMock()
                result.scalars.return_value.all.return_value = messages
                return result
            # Fourth call: _get_by_id for updating summary
            elif call_count[0] == 4:
                result = MagicMock()
                result.scalar_one_or_none.return_value = conversation
                return result
            return MagicMock(scalar_one=MagicMock(return_value=0))

        mock_db.execute.side_effect = execute_side_effect

        service = ConversationService(mock_db)
        stats = await service.compress_conversation_history(conversation.id)

        assert stats["compressed"] is True
        assert stats["compressed_count"] == 50  # 150 - 100 (MAX_MESSAGES_PER_CONVERSATION)

    @pytest.mark.asyncio
    async def test_get_context_window(self, mock_db):
        """Test getting context window status"""
        conversation = _make_conversation_mock()
        messages = [
            _make_message_mock(
                conversation_id=conversation.id,
                content="Short message"
            ) for _ in range(10)
        ]

        # Mock conversation check
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        # Mock count query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 10
        mock_db.execute.side_effect = [conv_result, count_result]

        # Mock list query
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = messages
        mock_db.execute.side_effect = [conv_result, count_result, list_result]

        service = ConversationService(mock_db)
        context = await service.get_context_window(conversation.id)

        assert context["total_messages"] == 10
        assert context["context_messages"] == 10
        assert context["max_tokens"] == 4000

    @pytest.mark.asyncio
    async def test_get_conversation_stats(self, mock_db):
        """Test getting conversation statistics"""
        conversation = _make_conversation_mock()
        now = datetime.now(timezone.utc)
        messages = [
            _make_message_mock(
                conversation_id=conversation.id,
                role="user",
                created_at=now - timedelta(minutes=10)
            ),
            _make_message_mock(
                conversation_id=conversation.id,
                role="assistant",
                created_at=now
            ),
        ]

        call_count = [0]
        def execute_side_effect(query):
            call_count[0] += 1
            stmt = str(query).lower()

            if 'conversation' in stmt and 'id' in stmt:
                result = MagicMock()
                result.scalar_one_or_none.return_value = conversation
                return result

            if 'count' in stmt:
                result = MagicMock()
                result.scalar_one.return_value = 2
                return result

            if 'min' in stmt:
                result = MagicMock()
                result.scalar_one.return_value = messages[0].created_at
                return result

            if 'max' in stmt:
                result = MagicMock()
                result.scalar_one.return_value = messages[1].created_at
                return result

            if 'select' in stmt and 'message' in stmt:
                result = MagicMock()
                result.scalars.return_value.all.return_value = messages
                return result

            return MagicMock(scalar_one=MagicMock(return_value=0))

        mock_db.execute.side_effect = execute_side_effect

        service = ConversationService(mock_db)
        stats = await service.get_conversation_stats(conversation.id)

        assert stats is not None
        assert stats.user_messages == 1
        assert stats.assistant_messages == 1


class TestConversationServiceIntegration:
    """Integration-style tests for ConversationService"""

    @pytest.mark.asyncio
    async def test_full_conversation_lifecycle(self, mock_db):
        """Test full lifecycle: create, update, message, delete"""
        # Create conversation
        create_data = ConversationCreate(
            customer_id=uuid4(),
            channel="web",
            subject="Test Lifecycle",
        )

        def refresh(obj):
            if hasattr(obj, 'id'):
                obj.id = uuid4()
            if hasattr(obj, 'created_at'):
                obj.created_at = datetime.now(timezone.utc)
            if hasattr(obj, 'updated_at'):
                obj.updated_at = datetime.now(timezone.utc)
        mock_db.refresh.side_effect = refresh

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_db.execute.return_value = count_result

        service = ConversationService(mock_db)
        conversation = await service.create_conversation(create_data)
        assert conversation is not None

        # Create message
        message_data = MessageCreate(
            conversation_id=conversation.id,
            role="user",
            content="Hello!",
        )

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = conv_result

        def msg_refresh(obj):
            obj.id = uuid4()
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
            obj.edit_count = 0
            obj.parent_id = None
        mock_db.refresh.side_effect = msg_refresh

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

        message = await service.create_message(message_data)
        assert message is not None
        assert message.conversation_id == conversation.id
        assert message.edit_count == 0

        # List messages
        messages = [_make_message_mock(conversation_id=conversation.id)]

        list_count = MagicMock()
        list_count.scalar_one.return_value = 1
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = messages

        mock_db.execute.side_effect = [conv_result, list_count, list_result]

        items, total = await service.list_messages(conversation.id)
        assert total == 1
        assert len(items) == 1

        # Delete conversation - need to use a mock with is_deleted attribute
        mock_db.execute.side_effect = None
        delete_conv = _make_conversation_mock(id=conversation.id)
        delete_result = MagicMock()
        delete_result.scalar_one_or_none.return_value = delete_conv
        mock_db.execute.return_value = delete_result
        success = await service.delete_conversation(conversation.id)
        assert success is True
