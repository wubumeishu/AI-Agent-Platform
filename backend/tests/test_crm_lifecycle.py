"""
CRM Tests: Lifecycle Stage + Funnel Pipeline
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

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
def sample_stage_data():
    return {
        "code": "高意向",
        "name": "高意向客户",
        "description": "强烈购买意向",
        "sort_order": 3,
        "config": {"auto_transition_rules": []}
    }


@pytest.fixture
def lifecycle_stage(sample_stage_data):
    stage = LifecycleStage(**sample_stage_data)
    stage.id = uuid4()
    return stage


@pytest.fixture
def lifecycle_log():
    log = LifecycleStageLog(
        lead_id=uuid4(),
        old_stage_code="潜客",
        new_stage_code="高意向",
        transition_reason="manual",
        operator="admin",
        extra_data={"score": 92}
    )
    log.id = uuid4()
    return log


# Tests for LifecycleStage
class TestLifecycleStage:
    async def test_get_lifecycle_stages(self, mock_db, lifecycle_stage):
        """测试获取生命周期阶段列表"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [lifecycle_stage]
        mock_db.execute.return_value = mock_result
        
        from app.crm.services import get_lifecycle_stages
        stages = await get_lifecycle_stages(mock_db)
        
        assert len(stages) == 1
        assert stages[0]["code"] == "高意向"
        assert stages[0]["name"] == "高意向客户"
    
    async def test_get_lifecycle_stage_by_code(self, mock_db, lifecycle_stage):
        """测试按 code 获取生命周期阶段"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = lifecycle_stage
        mock_db.execute.return_value = mock_result
        
        from app.crm.services import get_lifecycle_stage
        stage = await get_lifecycle_stage(mock_db, "高意向")
        
        assert stage is not None
        assert stage["code"] == "高意向"
    
    async def test_get_lifecycle_stage_not_found(self, mock_db):
        """测试获取不存在的阶段"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        from app.crm.services import get_lifecycle_stage
        stage = await get_lifecycle_stage(mock_db, "不存在")
        
        assert stage is None
    
    async def test_create_lifecycle_stage(self, mock_db, sample_stage_data):
        """测试创建生命周期阶段"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        from app.crm.services import create_lifecycle_stage
        stage = await create_lifecycle_stage(mock_db, sample_stage_data)
        
        assert stage["code"] == "高意向"
        assert stage["id"] is not None
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
    
    async def test_create_lifecycle_stage_duplicate(self, mock_db, sample_stage_data):
        """测试创建重复的阶段编码"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = LifecycleStage(**sample_stage_data)
        mock_db.execute.return_value = mock_result
        
        from app.crm.services import create_lifecycle_stage
        with pytest.raises(ValueError, match="已存在"):
            await create_lifecycle_stage(mock_db, sample_stage_data)
    
    async def test_update_lifecycle_stage(self, mock_db, lifecycle_stage):
        """测试更新生命周期阶段"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = lifecycle_stage
        mock_db.execute.return_value = mock_result
        
        from app.crm.services import update_lifecycle_stage
        updates = {"name": "更新后的高意向", "description": "新描述"}
        stage = await update_lifecycle_stage(mock_db, "高意向", updates)
        
        assert stage["name"] == "更新后的高意向"
        assert stage["description"] == "新描述"
        mock_db.commit.assert_called_once()
    
    async def test_delete_lifecycle_stage(self, mock_db, lifecycle_stage):
        """测试删除生命周期阶段（软删除）"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = lifecycle_stage
        mock_db.execute.return_value = mock_result
        
        from app.crm.services import delete_lifecycle_stage
        success = await delete_lifecycle_stage(mock_db, "高意向")
        
        assert success is True
        assert lifecycle_stage.is_deleted is True
        mock_db.commit.assert_called_once()
    
    async def test_delete_lifecycle_stage_not_found(self, mock_db):
        """测试删除不存在的阶段"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        from app.crm.services import delete_lifecycle_stage
        success = await delete_lifecycle_stage(mock_db, "不存在")
        
        assert success is False


# Tests for LifecycleStageLog
class TestLifecycleStageLog:
    async def test_get_lifecycle_stage_logs(self, mock_db, lifecycle_log):
        """测试获取阶段变更日志"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [lifecycle_log]
        mock_db.execute.return_value = mock_result
        
        from app.crm.services import get_lifecycle_stage_logs
        logs = await get_lifecycle_stage_logs(mock_db, "高意向")
        
        assert len(logs) == 1
        assert logs[0]["new_stage_code"] == "高意向"
    
    async def test_get_lifecycle_stage_logs_with_lead_id(self, mock_db, lifecycle_log):
        """测试按 lead_id 筛选日志"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [lifecycle_log]
        mock_db.execute.return_value = mock_result
        
        from app.crm.services import get_lifecycle_stage_logs
        logs = await get_lifecycle_stage_logs(mock_db, "高意向", lead_id=lifecycle_log.lead_id)
        
        assert len(logs) == 1


# Tests for Funnel Pipeline
class TestFunnelPipeline:
    async def test_get_funnel_stats(self, mock_db):
        """测试漏斗统计数据"""
        from app.crm.services import get_funnel_stats
        from app.db.models.lifecycle import LifecycleStage

        # 模拟阶段
        stage1 = LifecycleStage(code="陌生", name="陌生", sort_order=0)
        stage2 = LifecycleStage(code="成交", name="成交", sort_order=5)

        # 模拟查询 - stages查询返回结果
        stages_result = MagicMock()
        stages_result.scalars.return_value.all.return_value = [stage1, stage2]

        # 模拟每个阶段的count查询返回结果
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        # side_effect需要为每个execute调用提供返回值
        mock_db.execute.side_effect = [stages_result, count_result, count_result]

        stats = await get_funnel_stats(mock_db)

        assert len(stats) == 2
        assert stats[0]["code"] == "陌生"
        assert stats[1]["code"] == "成交"
    
    async def test_init_default_stages_empty_db(self, mock_db):
        """测试空数据库初始化"""
        from app.crm.services import init_default_stages
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        await init_default_stages(mock_db)
        
        assert mock_db.add.call_count == 6  # 6 个默认阶段
        mock_db.commit.assert_called_once()
    
    async def test_init_default_stages_existing(self, mock_db):
        """测试已有数据时不重复初始化"""
        from app.crm.services import init_default_stages
        from app.db.models.lifecycle import LifecycleStage
        
        existing = LifecycleStage(code="陌生", name="陌生")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result
        
        await init_default_stages(mock_db)
        
        mock_db.add.assert_not_called()
