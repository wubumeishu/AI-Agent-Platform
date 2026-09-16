"""Tests for Intent API endpoints - Schema and service integration tests"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone


def _make_intent_response(**kwargs):
    """Helper to create an intent response mock"""
    now = datetime.now(timezone.utc)
    intent = MagicMock()
    for key, value in kwargs.items():
        setattr(intent, key, value)
    intent.id = kwargs.get('id', uuid4())
    intent.intent_type = kwargs.get('intent_type', 'greeting')
    intent.intent_name = kwargs.get('intent_name', '问候')
    intent.confidence = kwargs.get('confidence', 0.9)
    intent.raw_input = kwargs.get('raw_input', '你好')
    intent.extracted_entities = kwargs.get('extracted_entities', {})
    intent.context = kwargs.get('context', {})
    intent.matched_action = kwargs.get('matched_action', None)
    intent.created_at = kwargs.get('created_at', now)
    intent.updated_at = kwargs.get('updated_at', now)
    return intent


class TestIntentSchemaValidation:
    """Test intent schema validation"""

    def test_classification_request_schema(self):
        """Test IntentClassificationRequest schema"""
        from app.schemas.intent import IntentClassificationRequest
        
        data = IntentClassificationRequest(
            message="你好，有什么帮助？",
            context={"user_id": str(uuid4())},
        )
        assert data.message == "你好，有什么帮助？"
        assert data.context["user_id"] is not None

    def test_classification_request_empty_message_raises(self):
        """Test empty message raises validation error"""
        from app.schemas.intent import IntentClassificationRequest
        
        with pytest.raises(Exception):
            IntentClassificationRequest(message="")

    def test_intent_result_schema(self):
        """Test IntentResult schema"""
        from app.schemas.intent import IntentResult
        
        result = IntentResult(
            intent_type="greeting",
            intent_name="问候",
            confidence=0.95,
            entities={"matched_keywords": ["你好"]},
        )
        assert result.intent_type == "greeting"
        assert result.confidence == 0.95

    def test_intent_result_confidence_range(self):
        """Test confidence is within valid range"""
        from app.schemas.intent import IntentResult
        
        # Valid confidence
        result = IntentResult(intent_type="test", intent_name="测试", confidence=0.8)
        assert result.confidence == 0.8
        
        # Invalid confidence should raise
        with pytest.raises(Exception):
            IntentResult(intent_type="test", intent_name="测试", confidence=1.5)
        
        with pytest.raises(Exception):
            IntentResult(intent_type="test", intent_name="测试", confidence=-0.1)


class TestIntentActionMappingService:
    """Test intent-to-action mapping service"""

    @pytest.mark.asyncio
    async def test_map_greeting_action(self):
        """Test mapping greeting intent to action"""
        from app.schemas.intent import IntentActionRequest
        from app.services.intent_service import IntentService
        
        # Use the proper mock DB session like test_intent.py does
        class MockDBSession:
            def __init__(self):
                self.commits = []
            
            async def commit(self):
                self.commits.append("commit")
            
            async def refresh(self, obj):
                pass
            
            def add(self, obj):
                pass
        
        service = IntentService(MockDBSession())
        request = IntentActionRequest(
            intent_type="greeting",
            intent_name="问候",
            entities={},
            context={},
        )
        
        result = await service.map_intent_to_action(request)
        
        assert result.success is True
        assert result.action_type == "respond_greeting"

    @pytest.mark.asyncio
    async def test_map_question_action(self):
        """Test mapping question intent to action"""
        from app.schemas.intent import IntentActionRequest
        from app.services.intent_service import IntentService
        
        class MockDBSession:
            def __init__(self):
                self.commits = []
            
            async def commit(self):
                self.commits.append("commit")
            
            async def refresh(self, obj):
                pass
            
            def add(self, obj):
                pass
        
        service = IntentService(MockDBSession())
        request = IntentActionRequest(
            intent_type="question",
            intent_name="提问",
            entities={"query": "产品功能"},
            context={},
        )
        
        result = await service.map_intent_to_action(request)
        
        assert result.success is True
        assert result.action_type == "answer_question"
        assert result.action_params.get("search_knowledge_base") is True

    @pytest.mark.asyncio
    async def test_map_complaint_action(self):
        """Test mapping complaint intent to action"""
        from app.schemas.intent import IntentActionRequest
        from app.services.intent_service import IntentService
        
        class MockDBSession:
            def __init__(self):
                self.commits = []
            
            async def commit(self):
                self.commits.append("commit")
            
            async def refresh(self, obj):
                pass
            
            def add(self, obj):
                pass
        
        service = IntentService(MockDBSession())
        request = IntentActionRequest(
            intent_type="complaint",
            intent_name="投诉",
            entities={"issue": "服务质量"},
            context={},
        )
        
        result = await service.map_intent_to_action(request)
        
        assert result.success is True
        assert result.action_type == "handle_complaint"
        assert result.action_params.get("escalate_to_human") is True
        assert result.action_params.get("priority") == "high"

    @pytest.mark.asyncio
    async def test_map_unknown_intent(self):
        """Test mapping unknown intent type"""
        from app.schemas.intent import IntentActionRequest
        from app.services.intent_service import IntentService
        
        service = IntentService(MagicMock())
        request = IntentActionRequest(
            intent_type="unknown_type",
            intent_name="未知类型",
            entities={},
            context={},
        )
        
        result = await service.map_intent_to_action(request)
        
        assert result.success is False
        assert result.fallback_message is not None

    @pytest.mark.asyncio
    async def test_map_escalation_action(self):
        """Test mapping escalation intent to action"""
        from app.schemas.intent import IntentActionRequest
        from app.services.intent_service import IntentService
        
        class MockDBSession:
            def __init__(self):
                self.commits = []
            
            async def commit(self):
                self.commits.append("commit")
            
            async def refresh(self, obj):
                pass
            
            def add(self, obj):
                pass
        
        service = IntentService(MockDBSession())
        request = IntentActionRequest(
            intent_type="escalation",
            intent_name="升级",
            entities={"reason": "多次未解决问题"},
            context={},
        )
        
        result = await service.map_intent_to_action(request)
        
        assert result.success is True
        assert result.action_type == "escalate"
        assert result.action_params.get("transfer_to_human") is True
        assert result.action_params.get("priority") == "urgent"

    @pytest.mark.asyncio
    async def test_map_callback_request(self):
        """Test mapping callback request to action"""
        from app.schemas.intent import IntentActionRequest
        from app.services.intent_service import IntentService
        
        class MockDBSession:
            def __init__(self):
                self.commits = []
            
            async def commit(self):
                self.commits.append("commit")
            
            async def refresh(self, obj):
                pass
            
            def add(self, obj):
                pass
        
        service = IntentService(MockDBSession())
        request = IntentActionRequest(
            intent_type="callback_request",
            intent_name="回电请求",
            entities={"phone": "13800138000"},
            context={},
        )
        
        result = await service.map_intent_to_action(request)
        
        assert result.success is True
        assert result.action_type == "schedule_callback"
        assert result.action_params.get("schedule_callback") is True


class TestIntentClassificationService:
    """Test intent classification service"""

    @pytest.mark.asyncio
    async def test_classify_greeting_via_service(self):
        """Test greeting classification via service"""
        from app.schemas.intent import IntentClassificationRequest
        from app.services.intent_service import IntentService
        
        class MockDBSession:
            def __init__(self):
                self.commits = []
            
            async def commit(self):
                self.commits.append("commit")
            
            async def refresh(self, obj):
                pass
            
            def add(self, obj):
                pass
            
            async def execute(self, query):
                class MockResult:
                    def scalars(self):
                        class MockScalars:
                            def all(self):
                                return []
                        return MockScalars()
                return MockResult()
        
        service = IntentService(MockDBSession())
        request = IntentClassificationRequest(
            message="你好，请问有什么帮助？",
            context={"user_id": str(uuid4())},
        )
        
        result = await service.classify_intent(request)
        
        assert result.success is True
        assert result.intent is not None
        assert result.intent.intent_type == "greeting"

    @pytest.mark.asyncio
    async def test_classify_question_via_service(self):
        """Test question classification via service"""
        from app.schemas.intent import IntentClassificationRequest
        from app.services.intent_service import IntentService
        
        class MockDBSession:
            def __init__(self):
                self.commits = []
            
            async def commit(self):
                self.commits.append("commit")
            
            async def refresh(self, obj):
                pass
            
            def add(self, obj):
                pass
            
            async def execute(self, query):
                class MockResult:
                    def scalars(self):
                        class MockScalars:
                            def all(self):
                                return []
                        return MockScalars()
                return MockResult()
        
        service = IntentService(MockDBSession())
        request = IntentClassificationRequest(message="这个产品多少钱？")
        
        result = await service.classify_intent(request)
        
        assert result.success is True
        assert result.intent is not None
        assert result.intent.intent_type == "question"

    @pytest.mark.asyncio
    async def test_classify_with_keywords_only(self):
        """Test classification falls back to keyword matching when LLM unavailable"""
        from app.schemas.intent import IntentClassificationRequest
        from app.services.intent_service import IntentService
        
        class MockDBSession:
            def __init__(self):
                self.commits = []
            
            async def commit(self):
                self.commits.append("commit")
            
            async def refresh(self, obj):
                pass
            
            def add(self, obj):
                pass
            
            async def execute(self, query):
                class MockResult:
                    def scalars(self):
                        class MockScalars:
                            def all(self):
                                return []
                        return MockScalars()
                return MockResult()
        
        service = IntentService(MockDBSession())
        request = IntentClassificationRequest(message="我要投诉你们的服务")
        
        result = await service.classify_intent(request)
        
        assert result.success is True
        assert result.intent is not None
        assert result.intent.intent_type == "complaint"


class TestIntentHistoryService:
    """Test intent history service"""

    @pytest.mark.asyncio
    async def test_get_history_empty(self):
        """Test getting empty intent history"""
        from app.services.intent_service import IntentService
        from sqlalchemy.ext.asyncio import AsyncSession
        
        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        
        service = IntentService(mock_db)
        conversation_id = uuid4()
        
        result = await service.get_intent_history(conversation_id)
        
        assert result.total == 0
        assert len(result.intents) == 0

    @pytest.mark.asyncio
    async def test_get_history_with_results(self):
        """Test getting intent history with results"""
        from app.services.intent_service import IntentService
        from sqlalchemy.ext.asyncio import AsyncSession
        
        mock_db = AsyncMock(spec=AsyncSession)
        
        # Create mock intent records with all required attributes
        now = datetime.now(timezone.utc)
        mock_intent = MagicMock()
        mock_intent.id = uuid4()
        mock_intent.conversation_id = uuid4()
        mock_intent.intent_type = "question"
        mock_intent.intent_name = "提问"
        mock_intent.confidence = 0.85
        mock_intent.raw_input = "产品功能是什么？"
        mock_intent.extracted_entities = {}
        mock_intent.context = {}
        mock_intent.matched_action = None
        mock_intent.created_at = now
        mock_intent.is_deleted = False
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_intent]
        mock_db.execute.return_value = mock_result
        
        service = IntentService(mock_db)
        conversation_id = uuid4()
        
        result = await service.get_intent_history(conversation_id)
        
        assert result.total == 1
        assert len(result.intents) == 1
        assert result.intents[0].intent_type == "question"


class TestIntentStatisticsService:
    """Test intent statistics service"""

    @pytest.mark.asyncio
    async def test_get_statistics_empty(self):
        """Test getting empty statistics"""
        from app.services.intent_service import IntentService
        from sqlalchemy.ext.asyncio import AsyncSession
        
        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        
        service = IntentService(mock_db)
        stats = await service.get_intent_statistics(days=30)
        
        assert stats.total_classifications == 0
        assert stats.avg_confidence == 0.0
        assert stats.top_intents == []

    @pytest.mark.asyncio
    async def test_get_statistics_with_data(self):
        """Test getting statistics with data"""
        from app.services.intent_service import IntentService
        from sqlalchemy.ext.asyncio import AsyncSession
        
        mock_db = AsyncMock(spec=AsyncSession)
        
        # Create mock intent records
        now = datetime.now(timezone.utc)
        mock_intents = [
            MagicMock(intent_type="greeting", confidence=0.95, created_at=now),
            MagicMock(intent_type="question", confidence=0.85, created_at=now),
            MagicMock(intent_type="greeting", confidence=0.9, created_at=now),
        ]
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_intents
        mock_db.execute.return_value = mock_result
        
        service = IntentService(mock_db)
        stats = await service.get_intent_statistics(days=30)
        
        assert stats.total_classifications == 3
        assert stats.avg_confidence > 0
        assert len(stats.top_intents) > 0
        assert "greeting" in stats.intent_distribution
        assert "question" in stats.intent_distribution


class TestIntentHealthCheck:
    """Test intent service health check"""

    def test_health_check_endpoint_exists(self):
        """Test health check endpoint is registered"""
        from app.routers.intents import router
        
        routes = [route.path for route in router.routes]
        assert "/api/v1/intents/health" in routes


class TestIntentPromptTemplate:
    """Test intent prompt template rendering"""

    @pytest.mark.asyncio
    async def test_build_intent_prompt(self):
        """Test building intent classification prompt"""
        from app.schemas.intent import IntentClassificationRequest
        from app.services.intent_service import IntentService
        
        service = IntentService(MagicMock())
        request = IntentClassificationRequest(
            message="你好",
            context={"user_id": str(uuid4())},
            previous_intents=[
                {"created_at": "2024-01-01", "intent_name": "greeting"}
            ],
        )
        
        prompt = service._build_intent_prompt(request)
        
        assert "你好" in prompt
        assert "意图类型" in prompt or "intent_type" in prompt.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
