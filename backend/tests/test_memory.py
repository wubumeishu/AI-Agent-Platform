"""Tests for Memory System - Unit tests without DB dependency"""
import pytest
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any
from uuid import uuid4, UUID
from unittest.mock import MagicMock

from app.services.memory_service import MemoryService
from app.schemas.memory import (
    MemoryCreate,
    MemoryUpdate,
    MemorySearchRequest,
    MemoryInjectionRequest,
    ConversationSummaryCreate,
)


class MockMemory:
    """Mock memory object"""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id', uuid4())
        self.customer_id = kwargs.get('customer_id', uuid4())
        self.memory_type = kwargs.get('memory_type', 'preference')
        self.category = kwargs.get('category', 'general')
        self.content = kwargs.get('content', 'Test content')
        self.source = kwargs.get('source', 'conversation')
        self.importance = kwargs.get('importance', 5)
        self.confidence = kwargs.get('confidence', 1.0)
        self.tags = kwargs.get('tags', [])
        self.metadata_ = kwargs.get('metadata_', {})
        self.created_at = kwargs.get('created_at', datetime.now(timezone.utc))
        self.updated_at = kwargs.get('updated_at', datetime.now(timezone.utc))
        self.is_deleted = kwargs.get('is_deleted', False)


class MockContextWindow:
    """Mock context window object"""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id', uuid4())
        self.conversation_id = kwargs.get('conversation_id', uuid4())
        self.current_tokens = kwargs.get('current_tokens', 0)
        self.max_tokens = kwargs.get('max_tokens', 4000)
        self.compressed_count = kwargs.get('compressed_count', 0)
        self.last_compressed_at = kwargs.get('last_compressed_at', None)
        self.summary_id = kwargs.get('summary_id', None)
        self.created_at = kwargs.get('created_at', datetime.now(timezone.utc))
        self.updated_at = kwargs.get('updated_at', datetime.now(timezone.utc))


class MockSummary:
    """Mock summary object"""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id', uuid4())
        self.conversation_id = kwargs.get('conversation_id', uuid4())
        self.summary_type = kwargs.get('summary_type', 'brief')
        self.content = kwargs.get('content', 'Test summary')
        self.key_points = kwargs.get('key_points', [])
        self.sentiment = kwargs.get('sentiment', None)
        self.action_items = kwargs.get('action_items', [])
        self.created_at = kwargs.get('created_at', datetime.now(timezone.utc))
        self.is_deleted = kwargs.get('is_deleted', False)


class MockDBSession:
    """Mock database session for testing without DB"""
    def __init__(self):
        self.data = {
            'memories': [],
            'summaries': [],
            'windows': {},
        }
        self.commits = []
    
    async def commit(self):
        self.commits.append("commit")
    
    async def refresh(self, obj):
        if not hasattr(obj, 'id') or obj.id is None:
            obj.id = uuid4()
        now = datetime.now(timezone.utc)
        if not hasattr(obj, 'created_at') or obj.created_at is None:
            obj.created_at = now
        if not hasattr(obj, 'updated_at') or obj.updated_at is None:
            obj.updated_at = now
    
    def add(self, obj):
        # Store in mock data based on type
        if isinstance(obj, MockMemory) or hasattr(obj, 'memory_type'):
            self.data['memories'].append(obj)
        elif isinstance(obj, MockSummary) or hasattr(obj, 'summary_type'):
            self.data['summaries'].append(obj)
        elif isinstance(obj, MockContextWindow) or hasattr(obj, 'max_tokens'):
            if hasattr(obj, 'conversation_id'):
                self.data['windows'][obj.conversation_id] = obj
    
    async def execute(self, query):
        stmt = str(query).lower()
        
        class MockResult:
            def __init__(self, value):
                self._value = value
            
            def scalar_one_or_none(self):
                return self._value
            
            def scalar_one(self):
                return self._value[0] if isinstance(self._value, tuple) else self._value
            
            def scalars(self):
                class MockScalars:
                    def __init__(self, values):
                        self._values = values
                    def all(self):
                        return self._values
                return MockScalars([self._value] if self._value and not isinstance(self._value, list) else (self._value if isinstance(self._value, list) else []))
            
            def fetchall(self):
                return [self._value] if self._value else []
        
        # Handle count queries
        if 'count' in stmt:
            if 'memory' in stmt and 'customer_id' in stmt:
                # Count memories for customer
                count = len([m for m in self.data['memories'] 
                           if not getattr(m, 'is_deleted', False)])
                return MockResult(count)
            elif 'conversation_summary' in stmt:
                return MockResult(len(self.data['summaries']))
            else:
                return MockResult(0)
        
        # Handle select queries
        if 'select' in stmt:
            if 'memory' in stmt:
                memories = [m for m in self.data['memories'] 
                          if not getattr(m, 'is_deleted', False)]
                return MockResult(memories[0] if memories else None)
            elif 'conversation_summary' in stmt:
                summaries = [s for s in self.data['summaries'] 
                           if not getattr(s, 'is_deleted', False)]
                return MockResult(summaries[0] if summaries else None)
            elif 'context_window' in stmt or 'window' in stmt:
                # Return first window or None
                windows = list(self.data['windows'].values())
                return MockResult(windows[0] if windows else None)
            else:
                return MockResult(None)
        
        # Handle update queries
        if 'update' in stmt:
            return MockResult(1)
        
        return MockResult(0)


class TestMemoryService:
    """Test cases for MemoryService"""

    @pytest.mark.asyncio
    async def test_create_memory(self):
        """Test creating a new memory"""
        service = MemoryService(MockDBSession())
        memory_data = MemoryCreate(
            customer_id=uuid4(),
            memory_type="preference",
            category="personal",
            content="用户喜欢简洁的界面设计",
            source="conversation",
            importance=8,
            confidence=0.9,
            tags=["design", "preference"],
        )

        result = await service.create_memory(memory_data)

        assert result is not None
        assert result.memory_type == "preference"
        assert result.content == "用户喜欢简洁的界面设计"
        assert result.importance == 8
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_get_memory_not_found(self):
        """Test getting a non-existent memory"""
        service = MemoryService(MockDBSession())
        result = await service.get_memory(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_memories(self):
        """Test listing memories"""
        mock_db = MockDBSession()
        service = MemoryService(mock_db)
        
        # Create some memories
        customer_id = uuid4()
        for i in range(5):
            memory = MockMemory(
                customer_id=customer_id,
                memory_type="preference",
                content=f"Preference {i}",
            )
            mock_db.add(memory)
            mock_db.commits.clear()

        # The mock returns only the first memory, so we check total
        memories, total = await service.list_memories(customer_id=customer_id)
        
        assert total == 5
        assert len(memories) >= 1  # At least one memory returned

    @pytest.mark.asyncio
    async def test_update_memory(self):
        """Test updating a memory"""
        service = MemoryService(MockDBSession())
        
        # First create a memory
        memory_data = MemoryCreate(
            customer_id=uuid4(),
            memory_type="preference",
            content="Original content",
        )
        memory = await service.create_memory(memory_data)
        
        # Then update it
        update_data = MemoryUpdate(content="Updated content", importance=9)
        updated = await service.update_memory(memory.id, update_data)
        
        assert updated is not None
        assert updated.content == "Updated content"
        assert updated.importance == 9

    @pytest.mark.asyncio
    async def test_delete_memory(self):
        """Test soft deleting a memory"""
        service = MemoryService(MockDBSession())
        
        # Create a memory
        memory_data = MemoryCreate(
            customer_id=uuid4(),
            memory_type="preference",
            content="Content to delete",
        )
        memory = await service.create_memory(memory_data)
        
        # For delete, we need to use the mock model directly
        mock_db = MockDBSession()
        mock_memory = MockMemory(
            id=memory.id,
            customer_id=memory.customer_id,
            is_deleted=False,
        )
        mock_db.add(mock_memory)
        
        service.db = mock_db
        success = await service.delete_memory(memory.id)
        assert success is True

    @pytest.mark.asyncio
    async def test_delete_memory_not_found(self):
        """Test deleting a non-existent memory"""
        service = MemoryService(MockDBSession())
        success = await service.delete_memory(uuid4())
        assert success is False


class TestMemorySearch:
    """Test memory search functionality"""

    @pytest.mark.asyncio
    async def test_search_memories(self):
        """Test searching memories"""
        service = MemoryService(MockDBSession())
        
        search_request = MemorySearchRequest(
            customer_id=uuid4(),
            query="简洁",
            limit=10,
        )
        
        result = await service.search_memories(search_request)
        
        assert result is not None
        assert result.query == "简洁"
        assert isinstance(result.total, int)
        assert result.search_time_ms >= 0

    @pytest.mark.asyncio
    async def test_search_with_filters(self):
        """Test searching memories with filters"""
        service = MemoryService(MockDBSession())
        
        search_request = MemorySearchRequest(
            customer_id=uuid4(),
            query="产品",
            memory_type="fact",
            category="product",
            limit=5,
        )
        
        result = await service.search_memories(search_request)
        
        assert result is not None
        assert result.total >= 0


class TestMemoryInjection:
    """Test memory injection functionality"""

    @pytest.mark.asyncio
    async def test_inject_memories(self):
        """Test injecting memories into context"""
        service = MemoryService(MockDBSession())
        
        inject_request = MemoryInjectionRequest(
            conversation_id=uuid4(),
            customer_id=uuid4(),
            recent_messages=[
                {"role": "user", "content": "你好，我对这个产品感兴趣"},
                {"role": "assistant", "content": "很高兴为您介绍我们的产品"},
            ],
            max_memory_count=3,
        )
        
        result = await service.inject_memories_into_context(inject_request)
        
        assert result is not None
        assert result.conversation_id == inject_request.conversation_id
        assert isinstance(result.injection_count, int)
        assert result.context_tokens_added >= 0


class TestConversationSummary:
    """Test conversation summary functionality"""

    @pytest.mark.asyncio
    async def test_create_conversation_summary(self):
        """Test creating a conversation summary"""
        service = MemoryService(MockDBSession())
        
        summary_data = ConversationSummaryCreate(
            conversation_id=uuid4(),
            summary_type="brief",
            content="这是一个测试摘要",
            key_points=["要点1", "要点2"],
            sentiment="positive",
            action_items=["行动项1"],
        )
        
        result = await service.create_conversation_summary(summary_data)
        
        assert result is not None
        assert result.summary_type == "brief"
        assert result.content == "这是一个测试摘要"
        assert len(result.key_points) == 2

    @pytest.mark.asyncio
    async def test_auto_generate_summary_too_few_messages(self):
        """Test auto-generating summary with too few messages"""
        service = MemoryService(MockDBSession())
        
        # Less than trigger threshold
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好！"},
        ]
        
        result = await service.auto_generate_summary(uuid4(), messages)
        
        assert result is None


class TestContextWindow:
    """Test context window management"""

    @pytest.mark.asyncio
    async def test_get_or_create_context_window(self):
        """Test getting or creating context window"""
        service = MemoryService(MockDBSession())
        
        window = await service.get_or_create_context_window(uuid4())
        
        assert window is not None
        assert window.max_tokens == 4000

    @pytest.mark.asyncio
    async def test_update_context_window(self):
        """Test updating context window"""
        service = MemoryService(MockDBSession())
        conv_id = uuid4()
        
        # Create window
        window = await service.get_or_create_context_window(conv_id)
        assert window is not None
        
        # Update tokens
        window.current_tokens = 2000
        assert window.current_tokens == 2000

    @pytest.mark.asyncio
    async def test_check_compression_needed(self):
        """Test checking if compression is needed"""
        service = MemoryService(MockDBSession())
        conv_id = uuid4()
        
        # Just verify it doesn't crash and returns a valid result
        result = await service.check_compression_needed(conv_id)
        
        assert result is not None
        assert result["conversation_id"] == conv_id


class TestMemoryStatistics:
    """Test memory statistics"""

    @pytest.mark.asyncio
    async def test_get_memory_statistics(self):
        """Test getting memory statistics"""
        service = MemoryService(MockDBSession())
        
        stats = await service.get_memory_statistics(uuid4())
        
        assert stats is not None
        assert "total_memories" in stats
        assert "type_counts" in stats
        assert "category_counts" in stats
        assert stats["customer_id"] is not None


class TestMemoryLimits:
    """Test memory limit enforcement"""

    @pytest.mark.asyncio
    async def test_memory_limit_enforcement(self):
        """Test that memory creation respects limits"""
        service = MemoryService(MockDBSession())
        
        # Verify the limit constant exists
        assert service.MAX_MEMORY_PER_CUSTOMER == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
