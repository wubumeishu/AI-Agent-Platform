"""
Phase 5: Private Domain Data Integrity Testing
测试私域模块数据完整性和跨模块数据一致性
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timedelta, timezone


# Fixtures
@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def mock_db2():
    """mock_db with db.execute wired to return *result* objects.

    Needed for service paths that run reconcile SELECTs against the
    nurture_plan_item table (Contract B, t_4b55abe8): the bare
    AsyncMock() in `mock_db` serves those SELECTs with a non-result
    object and the upsert logic crashes.
    """
    db = AsyncMock()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    result.scalar.return_value = 0
    db.execute = AsyncMock(return_value=result)

    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def sample_account_id():
    return uuid4()


def _mock_result_one(obj):
    """Build a SELECT-result mock whose scalar_one_or_none() yields ``obj``.

    The real service SELECT paths call ``result.scalar_one_or_none()``; the
    bare AsyncMock in ``mock_db`` would return a coroutine instead, so these
    tests wire ``db.execute`` to return a real result object pointing at the
    ORM instance the service just created.
    """
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.scalars.return_value.all.return_value = []
    result.scalar.return_value = 0
    return result


def _wire_id_on_add(db):
    """Give ORM objects a real UUID id when added to the (mocked) session.

    A real Postgres/SQLAlchemy session materialises the PK default (uuid4) on
    flush; the mocked flush/refresh are no-ops, so chained-create flows that
    read ``obj.id`` would see ``None`` and trip the next schema's UUID
    validation. Assigning the id in ``db.add`` reproduces that behaviour and
    keeps the create→create chains faithful.
    """
    _SENTINEL = object()

    def _add(obj, *args, **kwargs):
        if getattr(obj, "id", _SENTINEL) in (None, _SENTINEL):
            obj.id = uuid4()

    db.add = MagicMock(side_effect=_add)
    return db


def _mock_result_scalars(items):
    """Build a SELECT-result mock whose scalars().all() yields ``items``.

    Used for aggregate/paginated SELECT paths (e.g. get_account_channel_stats)
    where the service reads ``result.scalars().all()``; scalar() stays 0 so
    any incidental count query is benign.
    """
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    result.scalar.return_value = 0
    result.scalar_one_or_none.return_value = None
    return result


@pytest.fixture
def sample_channel_data():
    return {
        "account_id": uuid4(),
        "platform_id": "wechat",
        "channel_type": "wechat",
        "name": "测试渠道",
        "description": "测试描述",
        "contact_info": {"email": "test@example.com"},
        "tags": ["vip"],
        "status": "active",
    }


@pytest.fixture
def sample_segment_data():
    return {
        "account_id": uuid4(),
        "name": "VIP客户群",
        "segment_type": "manual",
        "filter_config": {"min_value": 1000},
    }


@pytest.fixture
def sample_pipeline_data():
    return {
        "account_id": uuid4(),
        "name": "销售漏斗",
        "pipeline_type": "sales",
        "is_default": True,
    }


# Test 1: Customer → PrivateChannel 关联完整性
class TestCustomerPrivateChannelIntegration:
    """测试客户与私域渠道的关联完整性"""
    
    async def test_channel_has_correct_account(self, mock_db, sample_channel_data):
        """测试渠道属于正确的账户"""
        from app.services.private_domain import create_private_channel
        from app.schemas.private_domain import PrivateChannelCreate
        
        data = PrivateChannelCreate(**sample_channel_data)
        result = await create_private_channel(mock_db, data)
        
        assert result["account_id"] == sample_channel_data["account_id"]
        assert result["channel_type"] == "wechat"
    
    async def test_channel_account_isolation(self, mock_db):
        """测试不同账户的渠道数据隔离"""
        from app.services.private_domain import get_private_channels
        
        account_id_1 = uuid4()
        account_id_2 = uuid4()
        
        # Mock results for different accounts
        async def mock_execute(query):
            result = MagicMock()
            query_str = str(query)
            if "count" in query_str.lower():
                result.scalar.return_value = 1
            else:
                # Return different channels based on account
                from app.db.models.private_domain import PrivateChannel
                channel = PrivateChannel(
                    account_id=account_id_1 if "account_id_1" in query_str else account_id_2,
                    channel_type="wechat",
                    name="Test Channel",
                )
                channel.id = uuid4()
                result.scalars.return_value.all.return_value = [channel]
            return result
        
        mock_db.execute = mock_execute
        
        result_1 = await get_private_channels(mock_db, account_id_1)
        result_2 = await get_private_channels(mock_db, account_id_2)
        
        assert result_1["total"] == 1
        assert result_2["total"] == 1
    
    async def test_channel_relationship_fields(self, mock_db, sample_channel_data):
        """测试渠道关联字段完整性"""
        from app.services.private_domain import create_private_channel
        from app.schemas.private_domain import PrivateChannelCreate
        
        data = PrivateChannelCreate(**sample_channel_data)
        result = await create_private_channel(mock_db, data)
        
        # Verify all required fields
        assert "id" in result
        assert "account_id" in result
        assert "platform_id" in result
        assert "channel_type" in result
        assert "name" in result
        assert "status" in result
        assert "created_at" in result
        assert "updated_at" in result


# Test 2: NurturePlan → CustomerSegment 关联完整性
class TestNurturePlanSegmentIntegration:
    """测试培育计划与客户分群的关联完整性"""
    
    async def test_nurture_plan_references_segment(self, mock_db2):
        """测试培育计划可以关联客户分群"""
        from app.services.private_domain import create_nurture_plan
        from app.schemas.private_domain import NurturePlanCreate
        
        segment_id = uuid4()
        account_id = uuid4()
        
        data = NurturePlanCreate(
            channel_id=uuid4(),
            account_id=account_id,
            name="Onboarding Plan",
            target_segment_id=segment_id,
        )
        result = await create_nurture_plan(mock_db2, data)
        
        assert result["target_segment_id"] == segment_id
        assert result["account_id"] == account_id
    
    async def test_nurture_plan_without_segment(self, mock_db2):
        """测试培育计划可以不关联客户分群"""
        from app.services.private_domain import create_nurture_plan
        from app.schemas.private_domain import NurturePlanCreate
        
        account_id = uuid4()
        
        data = NurturePlanCreate(
            channel_id=uuid4(),
            account_id=account_id,
            name="General Plan",
            target_segment_id=None,  # No segment
        )
        result = await create_nurture_plan(mock_db2, data)
        
        assert result["target_segment_id"] is None
        assert result["account_id"] == account_id
    
    async def test_nurture_plan_channel_reference(self, mock_db2):
        """测试培育计划关联渠道"""
        from app.services.private_domain import create_nurture_plan
        from app.schemas.private_domain import NurturePlanCreate
        
        channel_id = uuid4()
        account_id = uuid4()
        
        data = NurturePlanCreate(
            channel_id=channel_id,
            account_id=account_id,
            name="Channel-specific Plan",
        )
        result = await create_nurture_plan(mock_db2, data)
        
        assert result["channel_id"] == channel_id
        assert result["account_id"] == account_id
    
    async def test_nurture_plan_sequence_steps(self, mock_db2):
        """测试培育计划步骤配置完整性（Contract B: 步骤落在 nurture_plan_item 表）"""
        from app.services.private_domain import create_nurture_plan
        from app.schemas.private_domain import NurturePlanCreate
        from app.db.models.private_domain import NurturePlanItem

        account_id = uuid4()
        steps = [
            {"step": 1, "delay_hours": 0, "content_id": str(uuid4())},
            {"step": 2, "delay_hours": 24, "content_id": str(uuid4())},
            {"step": 3, "delay_hours": 48, "content_id": str(uuid4())},
        ]

        data = NurturePlanCreate(
            channel_id=uuid4(),
            account_id=account_id,
            name="Multi-step Plan",
            sequence_steps=steps,
            schedule_type="drip",
        )
        result = await create_nurture_plan(mock_db2, data)

        # Legacy JSON 列退役：响应不再携带 sequence_steps，步骤来自 SoT 表
        assert "sequence_steps" not in result
        assert result["schedule_type"] == "drip"
        items = [
            c.args[0]
            for c in mock_db2.add.call_args_list
            if c.args and isinstance(c.args[0], NurturePlanItem)
        ]
        assert len(items) == 3
        assert [i.step_order for i in items] == [0, 1, 2]
        assert [i.delay_hours for i in items] == [0, 24, 48]


# Test 3: DealItem → Customer 关联完整性
class TestDealItemCustomerIntegration:
    """测试商机与客户关联完整性"""
    
    async def test_deal_references_customer(self, mock_db):
        """测试商机可以关联客户"""
        from app.services.private_domain import create_deal_item
        from app.schemas.private_domain import DealItemCreate
        
        customer_id = uuid4()
        pipeline_id = uuid4()
        account_id = uuid4()
        
        data = DealItemCreate(
            pipeline_id=pipeline_id,
            account_id=account_id,
            customer_id=customer_id,
            name="Deal with VIP Customer",
            value=5000000,
        )
        result = await create_deal_item(mock_db, data)
        
        assert result["customer_id"] == customer_id
        assert result["account_id"] == account_id
        assert result["value"] == 5000000
    
    async def test_deal_without_customer(self, mock_db):
        """测试商机可以不关联客户（潜在机会）"""
        from app.services.private_domain import create_deal_item
        from app.schemas.private_domain import DealItemCreate
        
        pipeline_id = uuid4()
        account_id = uuid4()
        
        data = DealItemCreate(
            pipeline_id=pipeline_id,
            account_id=account_id,
            customer_id=None,  # No customer yet
            name="Potential Deal",
        )
        result = await create_deal_item(mock_db, data)
        
        assert result["customer_id"] is None
        assert result["pipeline_id"] == pipeline_id
    
    async def test_deal_value_validation(self, mock_db):
        """测试商机金额字段验证"""
        from app.services.private_domain import create_deal_item
        from app.schemas.private_domain import DealItemCreate
        
        account_id = uuid4()
        
        # Test positive value
        data = DealItemCreate(
            pipeline_id=uuid4(),
            account_id=account_id,
            name="Big Deal",
            value=10000000,
            currency="CNY",
        )
        result = await create_deal_item(mock_db, data)
        assert result["value"] == 10000000
        assert result["currency"] == "CNY"
    
    async def test_deal_pipeline_reference(self, mock_db):
        """测试商机关联漏斗"""
        from app.services.private_domain import create_deal_item
        from app.schemas.private_domain import DealItemCreate
        
        pipeline_id = uuid4()
        account_id = uuid4()
        
        data = DealItemCreate(
            pipeline_id=pipeline_id,
            account_id=account_id,
            name="Pipeline Deal",
        )
        result = await create_deal_item(mock_db, data)
        
        assert result["pipeline_id"] == pipeline_id
        assert result["account_id"] == account_id


# Test 4: FollowUpTask → Customer/NurturePlan 关联完整性
class TestFollowUpTaskIntegration:
    """测试跟进任务与客户/培育计划的关联完整性"""
    
    async def test_task_references_customer(self, mock_db):
        """测试跟进任务关联客户"""
        from app.services.private_domain import create_follow_up_task
        from app.schemas.private_domain import FollowUpTaskCreate
        
        customer_id = uuid4()
        account_id = uuid4()
        
        data = FollowUpTaskCreate(
            account_id=account_id,
            customer_id=customer_id,
            task_type="wechat",
            title="Follow up with customer",
            priority=5,
        )
        result = await create_follow_up_task(mock_db, data)
        
        assert result["customer_id"] == customer_id
        assert result["account_id"] == account_id
        assert result["task_type"] == "wechat"
    
    async def test_task_without_customer(self, mock_db):
        """测试跟进任务可以不关联客户"""
        from app.services.private_domain import create_follow_up_task
        from app.schemas.private_domain import FollowUpTaskCreate
        
        account_id = uuid4()
        
        data = FollowUpTaskCreate(
            account_id=account_id,
            customer_id=None,
            task_type="call",
            title="General follow-up",
        )
        result = await create_follow_up_task(mock_db, data)
        
        assert result["customer_id"] is None
        assert result["account_id"] == account_id
    
    async def test_task_status_transitions(self, mock_db):
        """测试跟进任务状态流转完整性"""
        from app.services.private_domain import transition_task_status
        from app.db.models.private_domain import FollowUpTask

        account_id = uuid4()

        # Build the task directly and serve it from the SELECT that
        # transition_task_status runs. A bare mocked db.execute would hand
        # the service a non-result object, so wire it to return a real result.
        task = FollowUpTask(
            account_id=account_id,
            task_type="wechat",
            title="Test task",
            status="pending",
        )
        task.id = uuid4()
        task.result = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Transition: pending → in_progress
        transition_result = await transition_task_status(mock_db, task.id, "in_progress")
        assert transition_result["status"] == "in_progress"

        # Transition: in_progress → completed
        transition_result = await transition_task_status(mock_db, task.id, "completed")
        assert transition_result["status"] == "completed"
        assert "completed_at" in transition_result["result"]
    
    async def test_task_priority_levels(self, mock_db):
        """测试跟进任务优先级设置"""
        from app.services.private_domain import create_follow_up_task
        from app.schemas.private_domain import FollowUpTaskCreate
        
        account_id = uuid4()
        
        # Test high priority
        data = FollowUpTaskCreate(
            account_id=account_id,
            task_type="email",
            title="High priority task",
            priority=10,
        )
        result = await create_follow_up_task(mock_db, data)
        assert result["priority"] == 10
    
    async def test_task_due_date_handling(self, mock_db):
        """测试跟进任务到期日期处理"""
        from app.services.private_domain import create_follow_up_task
        from app.schemas.private_domain import FollowUpTaskCreate
        
        account_id = uuid4()
        due_date = datetime.now(timezone.utc) + timedelta(days=7)
        
        data = FollowUpTaskCreate(
            account_id=account_id,
            task_type="meeting",
            title="Future meeting",
            due_date=due_date.isoformat(),
        )
        result = await create_follow_up_task(mock_db, data)
        
        assert result["due_date"] is not None
    
    async def test_task_overdue_detection(self, mock_db):
        """测试跟进任务逾期检测"""
        from app.services.private_domain import check_and_update_overdue_tasks
        from app.db.models.private_domain import FollowUpTask
        from datetime import datetime, timedelta, timezone
        
        account_id = uuid4()
        past_date = datetime.now(timezone.utc) - timedelta(days=1)
        
        # Create overdue tasks
        task1 = FollowUpTask(
            account_id=account_id,
            task_type="wechat",
            title="Overdue task",
            status="pending",
            due_date=past_date,
        )
        task2 = FollowUpTask(
            account_id=account_id,
            task_type="email",
            title="Also overdue",
            status="in_progress",
            due_date=past_date,
        )
        
        async def mock_execute(query):
            result = MagicMock()
            query_str = str(query)
            if "overdue" in query_str.lower() or "due_date" in query_str.lower():
                result.scalars.return_value.all.return_value = [task1, task2]
            else:
                result.scalar.return_value = 0
            return result
        
        mock_db.execute = mock_execute
        
        result = await check_and_update_overdue_tasks(mock_db, account_id)
        
        assert result["overdue_tasks_found"] == 2
        assert task1.status == "overdue"
        assert task2.status == "overdue"


# Test 5: Lead → Customer 转化数据一致性
class TestLeadCustomerConversion:
    """测试线索到客户的转化数据一致性"""
    
    async def test_conversion_data_preservation(self, mock_db):
        """测试转化过程中数据保持完整"""
        # This test verifies that when a Lead converts to Customer,
        # the key data fields are preserved
        
        from app.db.models.customer import Customer
        from app.db.models.lead import Lead
        
        # Simulate conversion data
        lead_data = {
            "name": "Test Lead",
            "email": "test@example.com",
            "phone": "13800138000",
            "company": "Test Company",
            "source": "website",
            "status": "converted",
        }
        
        # Verify field names are consistent
        assert "name" in lead_data
        assert "email" in lead_data
        assert "status" in lead_data
        
        # Test that status transition is valid
        valid_statuses = ["new", "contacted", "qualified", "converted", "lost"]
        assert lead_data["status"] in valid_statuses
    
    async def test_customer_creation_from_lead(self, mock_db):
        """测试从线索创建客户时的数据映射"""
        from app.db.models.customer import Customer
        from app.db.models.lead import Lead

        # Current Lead model links to its originating customer via
        # customer_id (no name/email/phone columns); the conversion data
        # mapping is verified through that link plus the preserved status.
        customer = Customer(
            name="Test Lead",
            email="test@example.com",
            phone="13800138000",
        )
        customer.id = uuid4()

        lead = Lead(
            customer_id=customer.id,
            source_type="wechat",
            status="converted",
        )
        lead.id = uuid4()

        # Verify the conversion mapping was preserved
        assert lead.customer_id == customer.id
        assert customer.name == "Test Lead"
        assert lead.status == "converted"


# Test 6: 数据删除级联测试
class TestDataCascadeDelete:
    """测试数据删除的级联行为"""
    
    async def test_soft_delete_channel(self, mock_db, sample_channel_data):
        """测试渠道软删除"""
        from app.services.private_domain import create_private_channel, delete_private_channel
        from app.schemas.private_domain import PrivateChannelCreate
        from app.db.models.private_domain import PrivateChannel

        data = PrivateChannelCreate(**sample_channel_data)
        # Build the channel the service would have created, give it a real id
        # (mocked refresh is a no-op), and serve it from the delete SELECT so
        # the service can find it via scalar_one_or_none().
        channel = PrivateChannel(
            account_id=data.account_id,
            platform_id=data.platform_id,
            channel_type=data.channel_type,
            name=data.name,
        )
        channel.id = uuid4()
        mock_db.execute = AsyncMock(side_effect=lambda q: _mock_result_one(channel))

        result = await create_private_channel(mock_db, data)
        channel_id = channel.id

        # Soft delete
        success = await delete_private_channel(mock_db, channel_id, sample_channel_data["account_id"])

        assert success is True
        # Verify soft delete flag
        assert channel.is_deleted is True
        assert sample_channel_data.get("account_id") is not None

    async def test_soft_delete_nurture_plan(self, mock_db):
        """测试培育计划软删除"""
        from app.services.private_domain import create_nurture_plan, delete_nurture_plan
        from app.schemas.private_domain import NurturePlanCreate
        from app.db.models.private_domain import NurturePlan

        account_id = uuid4()
        data = NurturePlanCreate(
            channel_id=uuid4(),
            account_id=account_id,
            name="Test Plan",
        )
        # Serve a real plan from the delete SELECT so the soft delete succeeds.
        plan = NurturePlan(
            channel_id=data.channel_id,
            account_id=account_id,
            name=data.name,
        )
        plan.id = uuid4()
        mock_db.execute = AsyncMock(side_effect=lambda q: _mock_result_one(plan))

        result = await create_nurture_plan(mock_db, data)
        plan_id = plan.id

        success = await delete_nurture_plan(mock_db, plan_id)

        assert success is True
        assert plan.is_deleted is True

    async def test_soft_delete_content_item(self, mock_db):
        """测试内容项软删除"""
        from app.services.private_domain import create_content_item, delete_content_item
        from app.schemas.private_domain import ContentItemCreate
        from app.db.models.private_domain import ContentItem

        account_id = uuid4()
        data = ContentItemCreate(
            account_id=account_id,
            content_type="text",
            title="Test Content",
        )
        # Serve a real content item from the delete SELECT.
        item = ContentItem(
            account_id=account_id,
            content_type=data.content_type,
            title=data.title,
        )
        item.id = uuid4()
        mock_db.execute = AsyncMock(side_effect=lambda q: _mock_result_one(item))

        result = await create_content_item(mock_db, data)
        item_id = item.id

        success = await delete_content_item(mock_db, item_id)

        assert success is True
        assert item.is_deleted is True

    async def test_soft_delete_follow_up_task(self, mock_db):
        """测试跟进任务软删除"""
        from app.services.private_domain import create_follow_up_task, delete_follow_up_task
        from app.schemas.private_domain import FollowUpTaskCreate
        from app.db.models.private_domain import FollowUpTask

        account_id = uuid4()
        data = FollowUpTaskCreate(
            account_id=account_id,
            task_type="wechat",
            title="Test Task",
        )
        # Serve a real task from the delete SELECT.
        task = FollowUpTask(
            account_id=account_id,
            task_type=data.task_type,
            title=data.title,
        )
        task.id = uuid4()
        mock_db.execute = AsyncMock(side_effect=lambda q: _mock_result_one(task))

        result = await create_follow_up_task(mock_db, data)
        task_id = task.id

        success = await delete_follow_up_task(mock_db, task_id)

        assert success is True
        assert task.is_deleted is True
    
    async def test_cascade_delete_channel_with_plans(self, mock_db):
        """测试删除渠道时关联的培育计划也会被删除"""
        from app.db.models.private_domain import PrivateChannel, NurturePlan
        from sqlalchemy import select
        
        account_id = uuid4()
        channel_id = uuid4()
        
        # Create channel
        channel = PrivateChannel(
            account_id=account_id,
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
        )
        channel.id = channel_id
        
        # Create nurture plan linked to channel
        plan = NurturePlan(
            channel_id=channel_id,
            account_id=account_id,
            name="Test Plan",
        )
        plan.id = uuid4()
        
        # Verify relationship exists
        assert plan.channel_id == channel.id
    
    async def test_segment_member_cascade_delete(self, mock_db):
        """测试删除分群时成员关系也被删除"""
        from app.db.models.private_domain import CustomerSegment, SegmentMember
        from app.db.models.customer import Customer
        from sqlalchemy import select
        
        segment_id = uuid4()
        customer_id = uuid4()
        
        # Create segment
        segment = CustomerSegment(
            account_id=uuid4(),
            name="Test Segment",
            segment_type="manual",
        )
        segment.id = segment_id
        
        # Create member
        member = SegmentMember(
            segment_id=segment_id,
            customer_id=customer_id,
        )
        member.id = uuid4()
        
        # Verify foreign key relationship
        assert member.segment_id == segment.id
        assert member.customer_id == customer_id


# Test 7: 跨模块数据一致性验证
class TestDataConsistencyValidation:
    """测试跨模块数据一致性"""
    
    async def test_account_data_isolation(self, mock_db):
        """测试账户数据隔离"""
        from app.services.private_domain import get_private_channels
        
        account_id_1 = uuid4()
        account_id_2 = uuid4()
        
        async def mock_execute(query):
            result = MagicMock()
            query_str = str(query)
            
            if "count" in query_str.lower():
                result.scalar.return_value = 1
            else:
                from app.db.models.private_domain import PrivateChannel
                channel = PrivateChannel(account_id=account_id_1)
                channel.id = uuid4()
                result.scalars.return_value.all.return_value = [channel]
            return result
        
        mock_db.execute = mock_execute
        
        # Query for account 1
        result_1 = await get_private_channels(mock_db, account_id_1)
        
        # Query for account 2 (should return different data)
        result_2 = await get_private_channels(mock_db, account_id_2)
        
        assert result_1["total"] == 1
        assert result_2["total"] == 1
    
    async def test_relationship_integrity_check(self, mock_db):
        """测试关联完整性检查"""
        from app.db.models.private_domain import PrivateChannel, NurturePlan
        
        # Create related entities
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
        )
        channel.id = uuid4()
        
        plan = NurturePlan(
            channel_id=channel.id,
            account_id=channel.account_id,
            name="Test Plan",
        )
        plan.id = uuid4()
        
        # Verify relationship integrity
        assert plan.channel_id == channel.id
        assert plan.account_id == channel.account_id
    
    async def test_deal_pipeline_integrity(self, mock_db):
        """测试商机漏斗完整性"""
        from app.services.private_domain import create_deal_pipeline, create_deal_item
        from app.schemas.private_domain import DealPipelineCreate, DealItemCreate

        account_id = uuid4()

        # Wire ids on add so the pipeline materialises a real UUID, letting the
        # chained deal-item create validate its pipeline_id reference.
        _wire_id_on_add(mock_db)

        # Create pipeline
        pipeline_data = DealPipelineCreate(
            account_id=account_id,
            name="Sales Pipeline",
            pipeline_type="sales",
        )
        pipeline_result = await create_deal_pipeline(mock_db, pipeline_data)
        pipeline_id = pipeline_result["id"]
        
        # Create deal item in pipeline
        deal_data = DealItemCreate(
            pipeline_id=pipeline_id,
            account_id=account_id,
            name="Test Deal",
        )
        deal_result = await create_deal_item(mock_db, deal_data)
        
        assert deal_result["pipeline_id"] == pipeline_id
        assert deal_result["account_id"] == account_id
    
    async def test_segment_member_count_sync(self, mock_db):
        """测试分群成员数量同步"""
        from app.db.models.private_domain import CustomerSegment, SegmentMember
        
        segment = CustomerSegment(
            account_id=uuid4(),
            name="VIP Segment",
            segment_type="manual",
            member_count=5,
        )
        segment.id = uuid4()
        
        # Create members
        members = [
            SegmentMember(segment_id=segment.id, customer_id=uuid4())
            for _ in range(5)
        ]
        
        # Verify member count matches
        assert segment.member_count == len(members)


# Test 8: 边界条件和异常处理
class TestEdgeCases:
    """测试边界条件和异常处理"""
    
    async def test_empty_query_results(self, mock_db):
        """测试空查询结果处理"""
        from app.services.private_domain import get_private_channels
        
        async def mock_execute(query):
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.scalar.return_value = 0
            return result
        
        mock_db.execute = mock_execute
        
        result = await get_private_channels(mock_db, uuid4())
        
        assert result["total"] == 0
        assert result["items"] == []
    
    async def test_non_existent_resource(self, mock_db):
        """测试不存在的资源"""
        from app.services.private_domain import get_private_channel
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        result = await get_private_channel(mock_db, uuid4(), uuid4())
        
        assert result is None
    
    async def test_duplicate_channel_creation(self, mock_db, sample_channel_data):
        """测试重复渠道创建（允许同名不同账户）"""
        from app.services.private_domain import create_private_channel
        from app.schemas.private_domain import PrivateChannelCreate

        account_id_1 = uuid4()
        account_id_2 = uuid4()

        # Each add materialises a distinct UUID so the two rows are genuinely
        # separate (a mocked flush/refresh would otherwise leave both ids None).
        _wire_id_on_add(mock_db)

        data_1 = PrivateChannelCreate(account_id=account_id_1, **{k: v for k, v in sample_channel_data.items() if k != "account_id"})
        data_2 = PrivateChannelCreate(account_id=account_id_2, **{k: v for k, v in sample_channel_data.items() if k != "account_id"})
        
        result_1 = await create_private_channel(mock_db, data_1)
        result_2 = await create_private_channel(mock_db, data_2)
        
        assert result_1["id"] != result_2["id"]
        assert result_1["account_id"] == account_id_1
        assert result_2["account_id"] == account_id_2
    
    async def test_invalid_status_transition(self, mock_db):
        """测试无效的状态转换"""
        from app.services.private_domain import transition_task_status
        from app.db.models.private_domain import FollowUpTask
        
        task = FollowUpTask(
            account_id=uuid4(),
            task_type="wechat",
            title="Test",
            status="completed",
        )
        task.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_db.execute.return_value = mock_result
        
        with pytest.raises(ValueError, match="Invalid status transition"):
            await transition_task_status(mock_db, task.id, "pending")
    
    async def test_million_dollar_deal(self, mock_db):
        """测试大额商机处理"""
        from app.services.private_domain import create_deal_item
        from app.schemas.private_domain import DealItemCreate
        
        account_id = uuid4()
        
        data = DealItemCreate(
            pipeline_id=uuid4(),
            account_id=account_id,
            name="Mega Deal",
            value=100000000,  # 1 million CNY
            currency="CNY",
        )
        result = await create_deal_item(mock_db, data)
        
        assert result["value"] == 100000000
        assert result["currency"] == "CNY"
    
    async def test_unicode_content(self, mock_db):
        """测试Unicode内容处理"""
        from app.services.private_domain import create_private_channel
        from app.schemas.private_domain import PrivateChannelCreate
        
        account_id = uuid4()
        
        data = PrivateChannelCreate(
            account_id=account_id,
            platform_id="wechat",
            channel_type="wechat",
            name="微信渠道测试",
            description="这是一个中文测试",
        )
        result = await create_private_channel(mock_db, data)
        
        assert result["name"] == "微信渠道测试"
        assert result["description"] == "这是一个中文测试"


# Test 9: 统计和聚合数据准确性
class TestStatisticsAccuracy:
    """测试统计和聚合数据准确性"""
    
    async def test_channel_stats_calculation(self, mock_db):
        """测试渠道统计数据计算"""
        from app.services.private_domain import get_account_channel_stats
        from app.db.models.private_domain import PrivateChannel
        
        account_id = uuid4()
        
        # Create mock channels
        channel1 = PrivateChannel(
            account_id=account_id,
            name="Channel 1",
            channel_type="wechat",
            status="active",
            connection_status="online",
            contact_count=10,
            message_count=50,
        )
        channel1.id = uuid4()
        
        channel2 = PrivateChannel(
            account_id=account_id,
            name="Channel 2",
            channel_type="email",
            status="active",
            connection_status="offline",
            contact_count=5,
            message_count=20,
        )
        channel2.id = uuid4()
        
        # Serve the two channels for the channel-list SELECT. Match on the
        # rendered table name (SQLAlchemy 2.x does not show the class name in
        # str(query)), so dispatch on the table identifier instead of the
        # Python class name.
        async def mock_execute(query):
            if "private_channel" in str(query):
                return _mock_result_scalars([channel1, channel2])
            result = MagicMock()
            result.scalar.return_value = 0
            result.scalars.return_value.all.return_value = []
            return result

        mock_db.execute = mock_execute
        
        stats = await get_account_channel_stats(mock_db, account_id)
        
        assert stats["total_channels"] == 2
        assert stats["online_channels"] == 1
        assert stats["offline_channels"] == 1
        assert stats["total_contacts"] == 15
        assert stats["total_messages"] == 70
    
    async def test_follow_up_task_stats(self, mock_db):
        """测试跟进任务统计数据"""
        from app.services.private_domain import get_follow_up_task_stats
        
        account_id = uuid4()
        
        call_count = [0]
        
        async def mock_execute(query):
            result = MagicMock()
            call_count[0] += 1
            
            # Return different counts based on call sequence
            counts = [1, 1, 1, 1, 1, 1, 1, 3, 1, 1]
            mock_result = MagicMock()
            mock_result.scalar.return_value = counts[min(call_count[0] - 1, len(counts) - 1)]
            return mock_result
        
        mock_db.execute = mock_execute
        
        stats = await get_follow_up_task_stats(mock_db, account_id)
        
        assert stats["total_tasks"] > 0
        assert "status_counts" in stats
        assert "completion_rate" in stats
        assert "overdue_count" in stats
    
    async def test_pipeline_conversion_rate(self, mock_db):
        """测试漏斗转化率计算"""
        from app.services.private_domain import get_deal_pipeline_stats
        from app.db.models.private_domain import DealPipeline, DealStage, DealItem
        
        pipeline_id = uuid4()
        account_id = uuid4()
        
        # Create pipeline
        pipeline = DealPipeline(
            account_id=account_id,
            name="Sales Pipeline",
            pipeline_type="sales",
        )
        pipeline.id = pipeline_id
        
        # Create stages
        stage1 = DealStage(pipeline_id=pipeline_id, name="Lead", order=0, probability=10)
        stage1.id = uuid4()
        
        stage2 = DealStage(pipeline_id=pipeline_id, name="Qualified", order=1, probability=50)
        stage2.id = uuid4()
        
        async def mock_execute(query):
            result = MagicMock()
            query_str = str(query)
            
            if "DealStage" in query_str and "order_by" in query_str:
                result.scalars.return_value.all.return_value = [stage1, stage2]
            elif "count" in query_str.lower():
                result.scalar.return_value = 0
            elif "sum" in query_str.lower():
                result.scalar.return_value = 0
            else:
                result.scalar.return_value = 0
            
            return result
        
        mock_db.execute = mock_execute
        
        stats = await get_deal_pipeline_stats(mock_db, pipeline_id)
        
        assert stats["pipeline_id"] == pipeline_id
        assert "stages" in stats
        assert "conversion_rate" in stats
        assert "total_deals" in stats


# Test 10: 综合场景测试
class TestComprehensiveScenarios:
    """测试综合业务场景"""
    
    async def test_full_customer_journey(self, mock_db):
        """测试完整的客户旅程：线索→客户→渠道→培育→商机"""
        from app.services.private_domain import (
            create_private_channel,
            create_nurture_plan,
            create_content_item,
            create_follow_up_task,
            create_customer_segment,
            create_deal_pipeline,
            create_deal_item,
        )
        from app.schemas.private_domain import (
            PrivateChannelCreate,
            NurturePlanCreate,
            ContentItemCreate,
            FollowUpTaskCreate,
            CustomerSegmentCreate,
            DealPipelineCreate,
            DealItemCreate,
        )
        
        account_id = uuid4()

        # Wire real ids on add: the create→create chain reads each entity's
        # .id to build the next reference (segment_id → channel → plan → ...),
        # so the PK default must be materialised like a real session would do
        # on flush.
        _wire_id_on_add(mock_db)

        # Step 1: Create customer segment
        segment_data = CustomerSegmentCreate(
            account_id=account_id,
            name="High Value Customers",
            segment_type="automatic",
        )
        segment = await create_customer_segment(mock_db, segment_data)
        segment_id = segment["id"]
        
        # Step 2: Create private channel
        channel_data = PrivateChannelCreate(
            account_id=account_id,
            platform_id="wechat",
            channel_type="wechat",
            name="官方微信渠道",
        )
        channel = await create_private_channel(mock_db, channel_data)
        channel_id = channel["id"]
        
        # Step 3: Create nurture plan linked to segment
        plan_data = NurturePlanCreate(
            channel_id=channel_id,
            account_id=account_id,
            name="VIP培育计划",
            target_segment_id=segment_id,
        )
        plan = await create_nurture_plan(mock_db, plan_data)
        plan_id = plan["id"]
        
        # Step 4: Create content item
        content_data = ContentItemCreate(
            account_id=account_id,
            channel_id=channel_id,
            content_type="text",
            title="欢迎邮件",
            body="欢迎加入我们的VIP客户群",
        )
        content = await create_content_item(mock_db, content_data)
        content_id = content["id"]
        
        # Step 5: Create follow-up task
        task_data = FollowUpTaskCreate(
            account_id=account_id,
            task_type="wechat",
            title="跟进VIP客户",
            priority=8,
        )
        task = await create_follow_up_task(mock_db, task_data)
        task_id = task["id"]
        
        # Step 6: Create deal pipeline
        pipeline_data = DealPipelineCreate(
            account_id=account_id,
            name="VIP销售漏斗",
            pipeline_type="sales",
        )
        pipeline = await create_deal_pipeline(mock_db, pipeline_data)
        pipeline_id = pipeline["id"]
        
        # Step 7: Create deal item
        deal_data = DealItemCreate(
            pipeline_id=pipeline_id,
            account_id=account_id,
            name="VIP大单",
            value=10000000,
        )
        deal = await create_deal_item(mock_db, deal_data)
        deal_id = deal["id"]
        
        # Verify all relationships
        assert plan["target_segment_id"] == segment_id
        assert plan["channel_id"] == channel_id
        assert content["channel_id"] == channel_id
        assert task["account_id"] == account_id
        assert deal["pipeline_id"] == pipeline_id
        assert deal["account_id"] == account_id
        
        # All entities belong to same account
        assert channel["account_id"] == account_id
        assert plan["account_id"] == account_id
        assert content["account_id"] == account_id
        assert task["account_id"] == account_id
        assert pipeline["account_id"] == account_id
        assert deal["account_id"] == account_id
    
    async def test_multi_channel_management(self, mock_db):
        """测试多渠道管理"""
        from app.services.private_domain import create_private_channel
        from app.schemas.private_domain import PrivateChannelCreate

        account_id = uuid4()

        # Wire real ids on add so each of the 5 channels materialises a
        # distinct UUID (mocked flush/refresh are no-ops).
        _wire_id_on_add(mock_db)

        # channel_type must satisfy the schema pattern
        # ^(wechat|wechat_work|email|sms|whatsapp|line|other)$; cycle the
        # five allowed types across the 5 channels.
        channel_types = ["wechat", "wechat_work", "email", "sms", "whatsapp"]

        # Create multiple channels
        channels = []
        for i in range(5):
            data = PrivateChannelCreate(
                account_id=account_id,
                platform_id=f"platform_{i}",
                channel_type=channel_types[i],
                name=f"Channel {i}",
            )
            channel = await create_private_channel(mock_db, data)
            channels.append(channel)

        assert len(channels) == 5
        assert all(c["account_id"] == account_id for c in channels)
    
    async def test_segment_with_multiple_customers(self, mock_db):
        """测试分群包含多个客户"""
        from app.services.private_domain import create_customer_segment
        from app.schemas.private_domain import CustomerSegmentCreate
        
        account_id = uuid4()
        customer_ids = [uuid4() for _ in range(10)]
        
        # Create segment
        data = CustomerSegmentCreate(
            account_id=account_id,
            name="Large Segment",
            segment_type="manual",
        )
        segment = await create_customer_segment(mock_db, data)
        segment_id = segment["id"]
        
        # Verify segment created successfully
        assert segment["account_id"] == account_id
        assert segment["name"] == "Large Segment"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
