"""
Tests for Customer 360 API
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.db.models.customer import Customer
from app.db.models.lead import Lead
from app.db.models.tag import Tag
from app.db.models.lifecycle import LifecycleStage
from app.db.models.conversation import Conversation
from app.db.models.memory import Memory, ActivityLog


# Fixtures
@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def sample_customer():
    customer = Customer(
        id=uuid4(),
        name="张三",
        email="zhangsan@example.com",
        phone="13800138000",
        company="示例公司",
        extra_info={"vip": True}
    )
    return customer


@pytest.fixture
def sample_lead():
    lead = Lead(
        id=uuid4(),
        customer_id=uuid4(),
        lifecycle_stage_code="高意向",
        intent_score=85,
        status="active",
    )
    return lead


@pytest.fixture
def sample_tag():
    tag = Tag(id=uuid4(), name="VIP", color="#FFD700")
    return tag


@pytest.fixture
def sample_conversation():
    conversation = Conversation(
        id=uuid4(),
        customer_id=uuid4(),
        channel="web",
        subject="咨询产品",
        status="active",
        sentiment="positive",
    )
    return conversation


@pytest.fixture
def sample_memory():
    memory = Memory(
        id=uuid4(),
        customer_id=uuid4(),
        category="preference",
        content="喜欢技术类产品",
        importance=7,
        source="conversation",
    )
    return memory


@pytest.fixture
def sample_activity():
    activity = ActivityLog(
        id=uuid4(),
        customer_id=uuid4(),
        activity_type="call",
        title="电话沟通",
        description="询问产品细节",
    )
    return activity


def _make_mock_result(scalars_result):
    """Helper to create a mock result with scalars() method"""
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = scalars_result
    mock_result.scalars.return_value = mock_scalars
    return mock_result


def _make_scalar_result(value):
    """Helper to create a mock result with scalar_one_or_none() method"""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = value
    return mock_result


# Tests for Customer 360
class TestCustomer360:
    async def test_get_customer_360_success(self, mock_db, sample_customer, sample_lead, sample_tag, sample_conversation, sample_memory, sample_activity):
        """测试获取 Customer 360 成功"""
        from app.crm.services.customer_360 import get_customer_360
        
        # 模拟查询结果
        mock_db.execute.side_effect = [
            _make_scalar_result(sample_customer),  # Customer query
            _make_mock_result([]),  # Tags query
            _make_mock_result([sample_lead]),  # Leads query
            _make_mock_result([sample_conversation]),  # Conversations query
            _make_mock_result([sample_memory]),  # Memories query
            _make_mock_result([sample_activity]),  # Activities query
            _make_mock_result([LifecycleStage(code="高意向", name="高意向客户")]),  # Lifecycle stages
            _make_mock_result([]),  # Message counts query (no messages)
        ]
        
        data = await get_customer_360(mock_db, sample_customer.id)
        
        assert data is not None
        assert data["name"] == "张三"
        assert data["email"] == "zhangsan@example.com"
    
    async def test_get_customer_360_not_found(self, mock_db):
        """测试获取不存在的客户"""
        from app.crm.services.customer_360 import get_customer_360
        
        mock_result = _make_scalar_result(None)
        mock_db.execute.return_value = mock_result
        
        data = await get_customer_360(mock_db, uuid4())
        
        assert data is None
    
    async def test_get_customer_conversations(self, mock_db, sample_conversation):
        """测试获取客户对话历史"""
        from app.crm.services.customer_360 import get_customer_conversations
        
        # 模拟总数查询
        total_result = MagicMock()
        total_result.scalar.return_value = 1
        # 模拟列表查询
        list_result = _make_mock_result([sample_conversation])
        
        mock_db.execute.side_effect = [total_result, list_result]
        
        data = await get_customer_conversations(mock_db, sample_conversation.customer_id)
        
        assert data["total"] == 1
        assert len(data["conversations"]) == 1
        assert data["conversations"][0]["channel"] == "web"
    
    async def test_get_customer_memories(self, mock_db, sample_memory):
        """测试获取客户记忆"""
        from app.crm.services.customer_360 import get_customer_memories
        
        total_result = MagicMock()
        total_result.scalar.return_value = 1
        list_result = _make_mock_result([sample_memory])
        
        mock_db.execute.side_effect = [total_result, list_result]
        
        data = await get_customer_memories(mock_db, sample_memory.customer_id)
        
        assert data["total"] == 1
        assert len(data["memories"]) == 1
        assert data["memories"][0]["category"] == "preference"
    
    async def test_get_customer_activities(self, mock_db, sample_activity):
        """测试获取客户活动记录"""
        from app.crm.services.customer_360 import get_customer_activities
        
        total_result = MagicMock()
        total_result.scalar.return_value = 1
        list_result = _make_mock_result([sample_activity])
        
        mock_db.execute.side_effect = [total_result, list_result]
        
        data = await get_customer_activities(mock_db, sample_activity.customer_id)
        
        assert data["total"] == 1
        assert len(data["activities"]) == 1
        assert data["activities"][0]["activity_type"] == "call"
    
    async def test_add_activity(self, mock_db, sample_activity):
        """测试添加活动记录"""
        from app.crm.services.customer_360 import add_activity
        
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_refresh = AsyncMock()
        mock_refresh.return_value = None
        mock_db.refresh = mock_refresh
        
        sample_activity.id = uuid4()
        sample_activity.created_at = MagicMock()
        sample_activity.created_at.isoformat.return_value = "2026-09-14T10:00:00"
        
        result = await add_activity(
            mock_db,
            sample_activity.customer_id,
            "call",
            "电话沟通",
            description="询问产品细节",
        )
        
        assert result["activity_type"] == "call"
        assert result["title"] == "电话沟通"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
