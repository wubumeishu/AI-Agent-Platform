"""
Lead Service Tests: CRUD + Intent Scoring + Status Transitions
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime
from typing import List, Optional, Dict, Any

from app.db.models.lead import Lead
from app.db.models.lifecycle import LifecycleStage, LifecycleStageLog


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
def sample_lead():
    lead = Lead(
        id=uuid4(),
        customer_id=uuid4(),
        lifecycle_stage_code="潜客",
        intent_score=75,
        source_type="conversation",
        source_id=str(uuid4()),
        status="new",
        notes="测试 Lead",
        operator="test_user",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        is_deleted=False,
    )
    return lead


@pytest.fixture
def sample_lead_data():
    return {
        "customer_id": str(uuid4()),
        "lifecycle_stage_code": "潜客",
        "intent_score": 75,
        "source_type": "conversation",
        "source_id": str(uuid4()),
        "status": "new",
        "notes": "测试 Lead",
        "operator": "test_user",
    }


# Tests for Lead CRUD
class TestLeadCRUD:
    async def test_get_lead_found(self, mock_db, sample_lead):
        """测试获取存在的 Lead"""
        from app.crm.services.lead import get_lead

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lead
        mock_db.execute.return_value = mock_result

        lead = await get_lead(mock_db, sample_lead.id)

        assert lead is not None
        assert lead["id"] == str(sample_lead.id)
        assert lead["status"] == "new"
        assert lead["intent_score"] == 75
    
    async def test_get_lead_not_found(self, mock_db):
        """测试获取不存在的 Lead"""
        from app.crm.services.lead import get_lead
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        lead = await get_lead(mock_db, uuid4())
        
        assert lead is None
    
    async def test_list_leads(self, mock_db, sample_lead):
        """测试列出 Lead 列表"""
        from app.crm.services.lead import list_leads
        
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1  # total
        mock_db.execute.return_value = mock_result
        
        # 第二个 execute 用于获取数据
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [sample_lead]
        mock_db.execute.side_effect = [mock_result, data_result]
        
        result = await list_leads(mock_db, skip=0, limit=10)
        
        assert result["total"] == 1
        assert len(result["data"]) == 1
        assert result["data"][0]["id"] == str(sample_lead.id)
    
    async def test_list_leads_with_filters(self, mock_db):
        """测试带筛选条件的 Lead 列表"""
        from app.crm.services.lead import list_leads
        
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_db.execute.return_value = mock_result
        
        result = await list_leads(
            mock_db,
            customer_id=uuid4(),
            status="new",
            lifecycle_stage="潜客",
            skip=0,
            limit=10
        )
        
        assert result["total"] == 0
        assert len(result["data"]) == 0
    
    async def test_create_lead_success(self, mock_db, sample_lead_data):
        """测试成功创建 Lead"""
        from app.crm.services.lead import create_lead
        
        # refresh 后的 lead
        sample_lead_data["id"] = uuid4()
        sample_lead_data["created_at"] = datetime.utcnow()
        sample_lead_data["updated_at"] = datetime.utcnow()
        new_lead = Lead(**sample_lead_data)
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = new_lead
        mock_db.execute.return_value = mock_result
        
        lead = await create_lead(mock_db, sample_lead_data)
        
        assert lead is not None
        assert lead["status"] == "new"
        assert lead["intent_score"] == 75
    
    async def test_create_lead_invalid_status(self, mock_db, sample_lead_data):
        """测试创建 Lead 时状态值非法"""
        from app.crm.services.lead import create_lead
        
        sample_lead_data["status"] = "invalid_status"
        
        with pytest.raises(ValueError, match="无效的状态值"):
            await create_lead(mock_db, sample_lead_data)
    
    async def test_create_lead_invalid_source_type(self, mock_db, sample_lead_data):
        """测试创建 Lead 时来源类型非法"""
        from app.crm.services.lead import create_lead
        
        sample_lead_data["source_type"] = "invalid_source"
        
        with pytest.raises(ValueError, match="无效的来源类型"):
            await create_lead(mock_db, sample_lead_data)
    
    async def test_update_lead_success(self, mock_db, sample_lead):
        """测试更新 Lead"""
        from app.crm.services.lead import update_lead
        
        # 第一次 execute: 获取 Lead
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lead
        mock_db.execute.return_value = mock_result
        
        updates = {
            "status": "contacted",
            "notes": "已联系",
            "operator": "admin"
        }
        
        lead = await update_lead(mock_db, sample_lead.id, updates)
        
        assert lead is not None
        assert lead["status"] == "contacted"
        assert "已联系" in lead["notes"]
    
    async def test_update_lead_invalid_status_transition(self, mock_db, sample_lead):
        """测试无效的 Lead 状态流转"""
        from app.crm.services.lead import update_lead
        
        # Lead 当前状态是 new，不能直接跳转到 qualified
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lead
        mock_db.execute.return_value = mock_result
        
        updates = {"status": "qualified"}  # new -> qualified 无效
        
        with pytest.raises(ValueError, match="状态流转无效"):
            await update_lead(mock_db, sample_lead.id, updates)
    
    async def test_update_lead_not_found(self, mock_db):
        """测试更新不存在的 Lead"""
        from app.crm.services.lead import update_lead
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        lead = await update_lead(mock_db, uuid4(), {"status": "new"})
        
        assert lead is None
    
    async def test_delete_lead_success(self, mock_db, sample_lead):
        """测试删除 Lead"""
        from app.crm.services.lead import delete_lead
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lead
        mock_db.execute.return_value = mock_result
        
        success = await delete_lead(mock_db, sample_lead.id)
        
        assert success is True
        assert sample_lead.is_deleted is True
    
    async def test_delete_lead_not_found(self, mock_db):
        """测试删除不存在的 Lead"""
        from app.crm.services.lead import delete_lead
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        success = await delete_lead(mock_db, uuid4())
        
        assert success is False


# Tests for Status Transitions
class TestStatusTransitions:
    async def test_valid_transition_new_to_contacted(self, mock_db, sample_lead):
        """测试有效的状态流转: new -> contacted"""
        from app.crm.services.lead import update_lead
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lead
        mock_db.execute.return_value = mock_result
        
        lead = await update_lead(mock_db, sample_lead.id, {"status": "contacted"})
        
        assert lead["status"] == "contacted"
    
    async def test_valid_transition_contacted_to_qualified(self, mock_db):
        """测试有效的状态流转: contacted -> qualified"""
        from app.crm.services.lead import update_lead
        
        lead = Lead(
            id=uuid4(),
            lifecycle_stage_code="潜客",
            status="contacted",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_deleted=False,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = lead
        mock_db.execute.return_value = mock_result
        
        lead = await update_lead(mock_db, lead.id, {"status": "qualified"})
        
        assert lead["status"] == "qualified"
    
    async def test_invalid_transition_new_to_qualified(self, mock_db, sample_lead):
        """测试无效的状态流转: new -> qualified"""
        from app.crm.services.lead import update_lead
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lead
        mock_db.execute.return_value = mock_result
        
        with pytest.raises(ValueError, match="状态流转无效"):
            await update_lead(mock_db, sample_lead.id, {"status": "qualified"})
    
    async def test_invalid_transition_to_converted_from_new(self, mock_db, sample_lead):
        """测试从 new 直接到 converted 无效"""
        from app.crm.services.lead import update_lead
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lead
        mock_db.execute.return_value = mock_result
        
        with pytest.raises(ValueError, match="状态流转无效"):
            await update_lead(mock_db, sample_lead.id, {"status": "converted"})


# Tests for Intent Scoring
class TestIntentScoring:
    async def test_calculate_intent_score_default(self, mock_db):
        """测试默认意向分数计算"""
        from app.crm.services.lead import calculate_intent_score

        # 模拟对话不存在
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        score = await calculate_intent_score(mock_db, uuid4())

        assert score == 50  # 默认中等分数

    async def test_calculate_intent_score_long_conversation(self, mock_db):
        """测试长对话的高意向评分"""
        from app.crm.services.lead import calculate_intent_score

        conversation = MagicMock()
        conversation.duration_seconds = 600  # 10分钟
        conversation.sentiment = "positive"
        conversation.messages = list(range(25))  # 25条消息

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = mock_result

        score = await calculate_intent_score(mock_db, uuid4())

        # 基准50 + 时长30 + 消息30 + 情感20 = 130，上限100
        assert score == 100

    async def test_calculate_intent_score_short_conversation(self, mock_db):
        """测试短对话的低意向评分"""
        from app.crm.services.lead import calculate_intent_score

        conversation = MagicMock()
        conversation.duration_seconds = 60  # 1分钟
        conversation.sentiment = "negative"
        conversation.messages = list(range(3))  # 3条消息

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = mock_result

        score = await calculate_intent_score(mock_db, uuid4())

        # 基准50 = 50
        assert score == 50


# Tests for Lead from Conversation
class TestLeadFromConversation:
    async def test_create_lead_from_conversation_success(self, mock_db):
        """测试从对话成功创建 Lead"""
        from app.crm.services.lead import create_lead_from_conversation
        
        conversation = MagicMock()
        conversation.id = uuid4()
        conversation.metadata_ = {"intent_score": 85}
        conversation.sentiment = "positive"
        conversation.subject = "产品咨询"
        
        mock_conv_result = MagicMock()
        mock_conv_result.scalar_one_or_none.return_value = conversation
        mock_db.execute.return_value = mock_conv_result
        
        # 检查重复 Lead
        mock_dup_result = MagicMock()
        mock_dup_result.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [mock_conv_result, mock_dup_result]
        
        # 创建 Lead 后的 refresh
        new_lead = Lead(
            id=uuid4(),
            customer_id=conversation.customer_id,
            lifecycle_stage_code="高意向",
            intent_score=85,
            source_type="conversation",
            source_id=str(conversation.id),
            status="new",
            notes="自动从对话创建，来源：产品咨询",
            operator="system",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_deleted=False,
        )
        mock_db.refresh.side_effect = lambda obj: setattr(obj, 'id', new_lead.id)
        
        # get_lead
        mock_get_result = MagicMock()
        mock_get_result.scalar_one_or_none.return_value = new_lead
        mock_db.execute.side_effect = [mock_conv_result, mock_dup_result, mock_get_result]
        
        lead = await create_lead_from_conversation(mock_db, conversation.id)
        
        assert lead is not None
        assert lead["status"] == "new"
        assert lead["intent_score"] == 85
        assert lead["source_type"] == "conversation"
    
    async def test_create_lead_from_conversation_not_found(self, mock_db):
        """测试从不存在的对话创建 Lead"""
        from app.crm.services.lead import create_lead_from_conversation
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        with pytest.raises(ValueError, match="对话 .* 不存在"):
            await create_lead_from_conversation(mock_db, uuid4())
    
    async def test_auto_generate_leads(self, mock_db):
        """测试批量自动生成 Lead"""
        from app.crm.services.lead import auto_generate_leads_for_conversations

        # 使用固定的 UUID
        conversation_id = uuid4()

        conversation1 = MagicMock()
        conversation1.id = conversation_id
        conversation1.metadata_ = {"intent_score": 85}
        conversation1.status = "active"
        conversation1.is_deleted = False
        conversation1.sentiment = "positive"

        # Mock execute 的所有调用
        mock_existing_result = MagicMock()
        mock_existing_result.fetchall.return_value = []  # 没有已存在的 lead

        mock_conv_result = MagicMock()
        mock_conv_result.scalars.return_value.all.return_value = [conversation1]

        # 第三个 execute: 获取对话（在 create_lead_from_conversation 内部）
        mock_conv_get_result = MagicMock()
        mock_conv_get_result.scalar_one_or_none.return_value = conversation1

        # 第四个 execute: 检查重复 Lead
        mock_dup_result = MagicMock()
        mock_dup_result.scalar_one_or_none.return_value = None

        # 第五个 execute: get_lead（在 create_lead_from_conversation 内部）
        mock_get_result = MagicMock()
        mock_get_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [
            mock_existing_result,
            mock_conv_result,
            mock_conv_get_result,
            mock_dup_result,
            mock_get_result
        ]

        count = await auto_generate_leads_for_conversations(mock_db, min_intent_score=70)

        assert count == 1  # conversation1 满足条件


# Tests for Intent Score configuration (configurability acceptance criterion)
class TestIntentScoreConfig:
    def test_config_constants_are_exported(self):
        """Intent 计算逻辑可配置: 常量从服务包导出, 可被 monkeypatch"""
        from app.crm.services import (
            HIGH_INTENT_THRESHOLD,
            MEDIUM_INTENT_THRESHOLD,
            INTENT_SCORE_MIN,
            INTENT_SCORE_MAX,
            INTENT_BASE_SCORE,
            INTENT_SCORE_WEIGHTS,
            VALID_STATUS_TRANSITIONS,
        )

        assert HIGH_INTENT_THRESHOLD == 70
        assert MEDIUM_INTENT_THRESHOLD < HIGH_INTENT_THRESHOLD
        assert INTENT_SCORE_MIN == 0
        assert INTENT_SCORE_MAX == 100
        # 权重合计为 1.0, 各维度齐全
        assert set(INTENT_SCORE_WEIGHTS) == {
            "conversation_quality",
            "interaction_frequency",
            "response_time",
            "sentiment",
        }
        assert abs(sum(INTENT_SCORE_WEIGHTS.values()) - 1.0) < 1e-9
        # 状态机: new -> contacted -> qualified -> converted
        assert "contacted" in VALID_STATUS_TRANSITIONS["new"]
        assert "qualified" in VALID_STATUS_TRANSITIONS["contacted"]
        assert "converted" in VALID_STATUS_TRANSITIONS["qualified"]
        assert VALID_STATUS_TRANSITIONS["converted"] == []

    async def test_calculate_intent_score_uses_configurable_bounds(self, mock_db, monkeypatch):
        """分数上下界来自模块配置, 可被 monkeypatch 覆盖"""
        import app.crm.services.lead as lead_svc

        conv = MagicMock()
        conv.duration_seconds = 0
        conv.sentiment = None
        conv.messages = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = conv
        mock_db.execute.return_value = mock_result

        async def _calc(db, cid):
            return await lead_svc.calculate_intent_score(db, cid)

        # 默认基准分
        assert await _calc(mock_db, uuid4()) == 50

        # 可配置: 修改基准分/上限, 算法立即跟随
        monkeypatch.setattr(lead_svc, "INTENT_BASE_SCORE", 30)
        monkeypatch.setattr(lead_svc, "INTENT_SCORE_MAX", 90)
        conv2 = MagicMock()
        conv2.duration_seconds = 9999
        conv2.sentiment = "positive"
        conv2.messages = list(range(30))
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = conv2
        mock_db.execute.return_value = mock_result2
        assert await _calc(mock_db, uuid4()) == 90  # 30+30+30+20=110 -> 上限 90

    def test_intent_config_schema_matches_service(self):
        """GET /intent-config 的 schema 与服务配置一致"""
        import app.crm.services.lead as lead_svc
        from app.schemas.lead import IntentScoreConfig

        cfg = IntentScoreConfig(
            threshold_high=lead_svc.HIGH_INTENT_THRESHOLD,
            threshold_medium=lead_svc.MEDIUM_INTENT_THRESHOLD,
            max_score=lead_svc.INTENT_SCORE_MAX,
            weights=lead_svc.INTENT_SCORE_WEIGHTS,
        )
        dumped = cfg.model_dump()
        assert dumped["threshold_high"] == 70
        assert dumped["threshold_medium"] == 60
        assert dumped["max_score"] == 100
        assert dumped["weights"]["sentiment"] == 0.1


# Tests for router response envelope (PHASE1-API-SPEC: code/message/data)
class TestLeadRouterEnvelope:
    def test_router_registers_static_paths_before_dynamic(self):
        """/intent-config、/duplicate-check 等静态路径必须先于 /{lead_id} 注册"""
        from app.main import app

        order = []
        for r in app.routes:
            p = getattr(r, "path", "")
            if "/crm/leads" in p:
                order.append(p)
        assert order.index("/api/v1/crm/leads/intent-config") < order.index(
            "/api/v1/crm/leads/{lead_id}"
        )
        assert order.index("/api/v1/crm/leads/duplicate-check") < order.index(
            "/api/v1/crm/leads/{lead_id}"
        )

    def test_lead_create_schema_validates_source_and_status(self):
        from pydantic import ValidationError
        from app.schemas.lead import LeadCreate

        # source_type 必填
        with pytest.raises(ValidationError):
            LeadCreate(source_type=None)
        lead = LeadCreate(
            source_type="campaign",
            source_id="cmp-001",
            intent_score=88,
            status="new",
        )
        assert lead.status == "new"
        # intent_score 越界应被拒绝
        with pytest.raises(ValidationError):
            LeadCreate(source_type="manual", intent_score=150)


# Regression tests: bugs found during t_20d0231a completion
# 1) list_leads returned slim dicts that failed LeadListResponse validation
#    (notes/operator/updated_at missing) -> LeadListItem slim schema introduced
# 2) GET /intent-config and /duplicate-check were shadowed by GET /{lead_id}
#    (registered after the UUID path param) -> static routes must precede dynamic
class TestLeadListSchema:
    def test_list_item_schema_accepts_service_list_shape(self):
        """list_leads service returns slim dicts; LeadListItem must accept them."""
        from app.schemas.lead import LeadListItem, LeadListResponse

        slim = {
            "id": "0f8f6f2b-57b2-4a33-a2ee-6a5b1b1a9c5a",
            "customer_id": None,
            "lifecycle_stage_code": "潜客",
            "intent_score": 75,
            "source_type": "campaign",
            "source_id": "cmp-1",
            "status": "new",
            "tags": [{"id": "x", "name": "高价值"}],
            "created_at": "2026-09-14T00:00:00",
        }
        item = LeadListItem(**slim)
        assert item.status == "new"
        # full LeadResponse must still reject the slim shape (notes/operator
        # are required there) -> proving the two shapes are distinct
        from app.schemas.lead import LeadResponse
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LeadResponse(**slim)
        resp = LeadListResponse(total=1, skip=0, limit=10, data=[slim])
        assert resp.data[0].intent_score == 75

    def test_list_response_serialization(self):
        from app.schemas.lead import LeadListResponse

        resp = LeadListResponse(total=0, skip=0, limit=20, data=[])
        dumped = resp.model_dump(mode="json")
        assert dumped["data"] == []


class TestRouteRegistrationOrder:
    def test_lead_static_routes_precede_dynamic(self):
        """GET /{lead_id} must be registered AFTER /intent-config & /duplicate-check,
        otherwise the UUID param swallows the static paths (422/404)."""
        from app.main import app

        paths = [
            getattr(r, "path", "")
            for r in app.routes
            if "/crm/leads" in getattr(r, "path", "")
        ]
        dynamic = "/api/v1/crm/leads/{lead_id}"
        assert dynamic in paths
        for static in (
            "/api/v1/crm/leads/intent-config",
            "/api/v1/crm/leads/duplicate-check",
        ):
            assert static in paths, f"{static} not registered"
            assert paths.index(static) < paths.index(dynamic), (
                f"{static} must be registered before {dynamic}"
            )
