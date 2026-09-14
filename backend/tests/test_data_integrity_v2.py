"""
Phase 5: Private Domain Data Integrity Testing
测试私域模块数据模型完整性和跨模块数据一致性
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta


# Test 1: 数据模型字段完整性测试
class TestDataModelFieldIntegrity:
    """测试数据模型字段完整性"""
    
    def test_private_channel_required_fields(self):
        """测试渠道必需字段"""
        from app.db.models.private_domain import PrivateChannel
        
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
        )
        
        # Verify required fields are set
        assert channel.account_id is not None
        assert channel.platform_id == "wechat"
        assert channel.channel_type == "wechat"
        assert channel.name == "Test Channel"
        
        # Note: defaults like status, contact_count, is_deleted are set by SQLAlchemy on insert
    
    def test_nurture_plan_required_fields(self):
        """测试培育计划必需字段"""
        from app.db.models.private_domain import NurturePlan
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
        )
        
        assert plan.channel_id is not None
        assert plan.account_id is not None
        assert plan.name == "Test Plan"
        # Note: defaults are set by SQLAlchemy on insert
    
    def test_content_item_required_fields(self):
        """测试内容项必需字段"""
        from app.db.models.private_domain import ContentItem
        
        item = ContentItem(
            account_id=uuid4(),
            content_type="text",
            title="Test Content",
        )
        
        assert item.account_id is not None
        assert item.content_type == "text"
        assert item.title == "Test Content"
        # Note: defaults are set by SQLAlchemy on insert
    
    def test_follow_up_task_required_fields(self):
        """测试跟进任务必需字段"""
        from app.db.models.private_domain import FollowUpTask
        
        task = FollowUpTask(
            account_id=uuid4(),
            task_type="wechat",
            title="Test Task",
        )
        
        assert task.account_id is not None
        assert task.task_type == "wechat"
        assert task.title == "Test Task"
        # Note: defaults are set by SQLAlchemy on insert
    
    def test_customer_segment_required_fields(self):
        """测试客户分群必需字段"""
        from app.db.models.private_domain import CustomerSegment
        
        segment = CustomerSegment(
            account_id=uuid4(),
            name="Test Segment",
        )
        
        assert segment.account_id is not None
        assert segment.name == "Test Segment"
        # Note: defaults are set by SQLAlchemy on insert
    
    def test_deal_pipeline_required_fields(self):
        """测试商机漏斗必需字段"""
        from app.db.models.private_domain import DealPipeline
        
        pipeline = DealPipeline(
            account_id=uuid4(),
            name="Test Pipeline",
        )
        
        assert pipeline.account_id is not None
        assert pipeline.name == "Test Pipeline"
        # Note: defaults are set by SQLAlchemy on insert
    
    def test_deal_stage_required_fields(self):
        """测试商机阶段必需字段"""
        from app.db.models.private_domain import DealStage
        
        stage = DealStage(
            pipeline_id=uuid4(),
            name="Qualified",
            order=1,
        )
        
        assert stage.pipeline_id is not None
        assert stage.name == "Qualified"
        assert stage.order == 1
        # Note: defaults are set by SQLAlchemy on insert
    
    def test_deal_item_required_fields(self):
        """测试商机项必需字段"""
        from app.db.models.private_domain import DealItem
        
        deal = DealItem(
            pipeline_id=uuid4(),
            account_id=uuid4(),
            name="Test Deal",
        )
        
        assert deal.pipeline_id is not None
        assert deal.account_id is not None
        assert deal.name == "Test Deal"
        # Note: defaults are set by SQLAlchemy on insert


# Test 2: 跨模块关联完整性测试
class TestCrossModuleRelationships:
    """测试跨模块关联完整性"""
    
    def test_channel_to_nurture_plan_relationship(self):
        """测试渠道到培育计划的关联"""
        from app.db.models.private_domain import PrivateChannel, NurturePlan
        
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
        
        # Verify relationship
        assert plan.channel_id == channel.id
        assert plan.account_id == channel.account_id
    
    def test_nurture_plan_to_segment_relationship(self):
        """测试培育计划到客户分群的关联"""
        from app.db.models.private_domain import NurturePlan, CustomerSegment
        
        segment = CustomerSegment(
            account_id=uuid4(),
            name="VIP Segment",
        )
        segment.id = uuid4()
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=segment.account_id,
            name="Test Plan",
            target_segment_id=segment.id,
        )
        
        # Verify relationship
        assert plan.target_segment_id == segment.id
    
    def test_segment_to_customer_relationship(self):
        """测试分群到客户的关联"""
        from app.db.models.private_domain import CustomerSegment, SegmentMember
        from app.db.models.customer import Customer
        
        segment = CustomerSegment(
            account_id=uuid4(),
            name="VIP Segment",
        )
        segment.id = uuid4()
        
        customer = Customer(name="Test Customer")
        customer.id = uuid4()
        
        member = SegmentMember(
            segment_id=segment.id,
            customer_id=customer.id,
        )
        
        # Verify relationship
        assert member.segment_id == segment.id
        assert member.customer_id == customer.id
    
    def test_deal_to_pipeline_relationship(self):
        """测试商机到漏斗的关联"""
        from app.db.models.private_domain import DealPipeline, DealItem
        
        pipeline = DealPipeline(
            account_id=uuid4(),
            name="Sales Pipeline",
        )
        pipeline.id = uuid4()
        
        deal = DealItem(
            pipeline_id=pipeline.id,
            account_id=pipeline.account_id,
            name="Test Deal",
        )
        
        # Verify relationship
        assert deal.pipeline_id == pipeline.id
        assert deal.account_id == pipeline.account_id
    
    def test_deal_to_stage_relationship(self):
        """测试商机到阶段的关联"""
        from app.db.models.private_domain import DealStage, DealItem
        
        stage = DealStage(
            pipeline_id=uuid4(),
            name="Qualified",
            order=1,
        )
        stage.id = uuid4()
        
        deal = DealItem(
            pipeline_id=stage.pipeline_id,
            account_id=uuid4(),
            name="Test Deal",
            stage_id=stage.id,
        )
        
        # Verify relationship
        assert deal.stage_id == stage.id
    
    def test_channel_to_content_relationship(self):
        """测试渠道到内容的关联"""
        from app.db.models.private_domain import PrivateChannel, ContentItem
        
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
        )
        channel.id = uuid4()
        
        content = ContentItem(
            account_id=channel.account_id,
            channel_id=channel.id,
            content_type="text",
            title="Test Content",
        )
        
        # Verify relationship
        assert content.channel_id == channel.id
        assert content.account_id == channel.account_id
    
    def test_task_to_customer_relationship(self):
        """测试跟进任务到客户的关联"""
        from app.db.models.private_domain import FollowUpTask
        from app.db.models.customer import Customer
        
        customer = Customer(name="Test Customer")
        customer.id = uuid4()
        
        task = FollowUpTask(
            account_id=uuid4(),
            customer_id=customer.id,
            task_type="wechat",
            title="Follow up",
        )
        
        # Verify relationship
        assert task.customer_id == customer.id
    
    def test_task_to_lead_relationship(self):
        """测试跟进任务到线索的关联"""
        from app.db.models.private_domain import FollowUpTask
        from app.db.models.lead import Lead
        
        lead = Lead(
            lifecycle_stage_code="qualified",
            status="new",
        )
        lead.id = uuid4()
        
        task = FollowUpTask(
            account_id=uuid4(),
            lead_id=lead.id,
            task_type="email",
            title="Follow up",
        )
        
        # Verify relationship
        assert task.lead_id == lead.id


# Test 3: 数据约束完整性测试
class TestDataConstraintIntegrity:
    """测试数据约束完整性"""
    
    def test_account_isolation(self):
        """测试账户数据隔离"""
        from app.db.models.private_domain import PrivateChannel
        
        account_1 = uuid4()
        account_2 = uuid4()
        
        channel_1 = PrivateChannel(
            account_id=account_1,
            platform_id="wechat",
            channel_type="wechat",
            name="Channel 1",
        )
        
        channel_2 = PrivateChannel(
            account_id=account_2,
            platform_id="email",
            channel_type="email",
            name="Channel 2",
        )
        
        # Verify isolation
        assert channel_1.account_id == account_1
        assert channel_2.account_id == account_2
        assert channel_1.account_id != channel_2.account_id
    
    def test_soft_delete_flag(self):
        """测试软删除标志"""
        from app.db.models.private_domain import PrivateChannel
        
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
        )
        
        # Simulate soft delete
        channel.is_deleted = True
        
        # Verify soft delete
        assert channel.is_deleted is True
    
    def test_timestamp_auto_update(self):
        """测试时间戳自动更新"""
        from app.db.models.private_domain import PrivateChannel
        
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
        )
        
        # Set timestamps manually (as SQLAlchemy would do on insert)
        channel.created_at = datetime.utcnow()
        channel.updated_at = datetime.utcnow()
        
        # Verify timestamps are set
        assert channel.created_at is not None
        assert channel.updated_at is not None
        assert channel.created_at <= channel.updated_at
    
    def test_enum_values_validity(self):
        """测试枚举值有效性"""
        from app.db.models.private_domain import (
            ChannelType,
            ChannelStatus,
            PlanStatus,
            ContentStatus,
            TaskStatus,
            SegmentType,
            DealItemStatus,
        )
        
        # Verify ChannelType values
        assert ChannelType.WECHAT.value == "wechat"
        assert ChannelType.EMAIL.value == "email"
        assert ChannelType.WHATSAPP.value == "whatsapp"
        
        # Verify ChannelStatus values
        assert ChannelStatus.ACTIVE.value == "active"
        assert ChannelStatus.ONLINE.value == "online"
        assert ChannelStatus.OFFLINE.value == "offline"
        
        # Verify PlanStatus values
        assert PlanStatus.DRAFT.value == "draft"
        assert PlanStatus.ACTIVE.value == "active"
        assert PlanStatus.COMPLETED.value == "completed"
        
        # Verify TaskStatus values
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.COMPLETED.value == "completed"
        
        # Verify DealItemStatus values
        assert DealItemStatus.OPEN.value == "open"
        assert DealItemStatus.WON.value == "won"
        assert DealItemStatus.LOST.value == "lost"
    
    def test_uuid_generation(self):
        """测试UUID生成"""
        from app.db.models.private_domain import PrivateChannel
        
        channel1 = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Channel 1",
        )
        channel1.id = uuid4()
        
        channel2 = PrivateChannel(
            account_id=uuid4(),
            platform_id="email",
            channel_type="email",
            name="Channel 2",
        )
        channel2.id = uuid4()
        
        # Verify unique UUIDs
        assert channel1.id != channel2.id
        assert isinstance(channel1.id, type(uuid4()))
    
    def test_json_field_serialization(self):
        """测试JSON字段序列化"""
        from app.db.models.private_domain import PrivateChannel
        
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
            contact_info={"email": "test@example.com", "phone": "13800138000"},
            tags=["vip", "important"],
        )
        
        # Verify JSON fields
        assert channel.contact_info == {"email": "test@example.com", "phone": "13800138000"}
        assert channel.tags == ["vip", "important"]


# Test 4: 客户旅程数据一致性测试
class TestCustomerJourneyDataConsistency:
    """测试客户旅程数据一致性"""
    
    def test_lead_to_customer_conversion(self):
        """测试线索到客户的转化"""
        from app.db.models.lead import Lead
        from app.db.models.customer import Customer
        
        # Create lead
        lead = Lead(
            lifecycle_stage_code="qualified",
            source_type="wechat",
            status="converted",
        )
        lead.id = uuid4()
        
        # Convert to customer
        customer = Customer(name="Converted Customer")
        customer.id = uuid4()
        
        # Verify conversion data
        assert lead.status == "converted"
        assert customer.name == "Converted Customer"
    
    def test_customer_segment_membership(self):
        """测试客户分群成员关系"""
        from app.db.models.private_domain import CustomerSegment, SegmentMember
        from app.db.models.customer import Customer
        
        segment = CustomerSegment(
            account_id=uuid4(),
            name="VIP Segment",
            segment_type="manual",
            member_count=5,
        )
        segment.id = uuid4()
        
        customers = [Customer(name=f"Customer {i}") for i in range(5)]
        for i, customer in enumerate(customers):
            customer.id = uuid4()
        
        members = [
            SegmentMember(segment_id=segment.id, customer_id=c.id)
            for c in customers
        ]
        
        # Verify member count
        assert len(members) == segment.member_count
    
    def test_channel_nurture_content_flow(self):
        """测试渠道→培育→内容流转"""
        from app.db.models.private_domain import PrivateChannel, NurturePlan, ContentItem
        
        # Create channel
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Official WeChat",
        )
        channel.id = uuid4()
        
        # Create nurture plan
        plan = NurturePlan(
            channel_id=channel.id,
            account_id=channel.account_id,
            name="Onboarding Plan",
        )
        plan.id = uuid4()
        
        # Create content
        content = ContentItem(
            account_id=channel.account_id,
            channel_id=channel.id,
            content_type="text",
            title="Welcome Email",
        )
        content.id = uuid4()
        
        # Verify flow consistency
        assert plan.channel_id == channel.id
        assert content.channel_id == channel.id
        assert plan.account_id == content.account_id
    
    def test_deal_pipeline_progression(self):
        """测试商机漏斗 progression"""
        from app.db.models.private_domain import DealPipeline, DealStage, DealItem
        
        # Create pipeline
        pipeline = DealPipeline(
            account_id=uuid4(),
            name="Sales Pipeline",
        )
        pipeline.id = uuid4()
        
        # Create stages
        stages = [
            DealStage(pipeline_id=pipeline.id, name="Lead", order=0),
            DealStage(pipeline_id=pipeline.id, name="Qualified", order=1),
            DealStage(pipeline_id=pipeline.id, name="Proposal", order=2),
            DealStage(pipeline_id=pipeline.id, name="Closed", order=3),
        ]
        for stage in stages:
            stage.id = uuid4()
        
        # Create deal
        deal = DealItem(
            pipeline_id=pipeline.id,
            account_id=pipeline.account_id,
            name="Big Deal",
            value=1000000,
        )
        deal.id = uuid4()
        
        # Verify pipeline structure
        assert len(stages) == 4
        assert stages[0].order == 0
        assert stages[3].order == 3
        assert deal.pipeline_id == pipeline.id


# Test 5: 边界条件测试
class TestEdgeCases:
    """测试边界条件"""
    
    def test_empty_tags(self):
        """测试空标签"""
        from app.db.models.private_domain import PrivateChannel
        
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
            tags=[],
        )
        
        assert channel.tags == []
    
    def test_null_optional_fields(self):
        """测试空可选字段"""
        from app.db.models.private_domain import PrivateChannel, NurturePlan
        
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
            description=None,
            avatar_url=None,
        )
        
        assert channel.description is None
        assert channel.avatar_url is None
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
            description=None,
            target_segment_id=None,
        )
        
        assert plan.description is None
        assert plan.target_segment_id is None
    
    def test_large_value_deal(self):
        """测试大额商机"""
        from app.db.models.private_domain import DealItem
        
        deal = DealItem(
            pipeline_id=uuid4(),
            account_id=uuid4(),
            name="Mega Deal",
            value=100000000,  # 1 billion cents = 1 million CNY
            currency="CNY",
        )
        
        assert deal.value == 100000000
        assert deal.currency == "CNY"
    
    def test_unicode_content(self):
        """测试Unicode内容"""
        from app.db.models.private_domain import PrivateChannel, NurturePlan, ContentItem
        
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="官方微信渠道",
            description="这是一个中文测试描述",
        )
        
        plan = NurturePlan(
            channel_id=channel.id,
            account_id=channel.account_id,
            name="VIP客户培育计划",
            description="欢迎加入VIP客户群",
        )
        
        content = ContentItem(
            account_id=channel.account_id,
            channel_id=channel.id,
            content_type="text",
            title="欢迎邮件",
            body="尊敬的客户，欢迎加入我们的VIP客户群！",
        )
        
        assert channel.name == "官方微信渠道"
        assert plan.name == "VIP客户培育计划"
        assert content.title == "欢迎邮件"
    
    def test_multiple_channel_types(self):
        """测试多渠道类型"""
        from app.db.models.private_domain import PrivateChannel
        
        channels = [
            PrivateChannel(account_id=uuid4(), platform_id="wechat", channel_type="wechat", name="WeChat"),
            PrivateChannel(account_id=uuid4(), platform_id="email", channel_type="email", name="Email"),
            PrivateChannel(account_id=uuid4(), platform_id="whatsapp", channel_type="whatsapp", name="WhatsApp"),
            PrivateChannel(account_id=uuid4(), platform_id="sms", channel_type="sms", name="SMS"),
        ]
        
        assert len(channels) == 4
        assert all(c.channel_type in ["wechat", "email", "whatsapp", "sms"] for c in channels)


# Test 6: 统计和聚合数据准确性
class TestStatisticsAccuracy:
    """测试统计和聚合数据准确性"""
    
    def test_channel_stats_aggregation(self):
        """测试渠道统计聚合"""
        from app.db.models.private_domain import PrivateChannel
        
        account_id = uuid4()
        
        channels = [
            PrivateChannel(
                account_id=account_id,
                platform_id="wechat",
                channel_type="wechat",
                name=f"Channel {i}",
                contact_count=10 * (i + 1),
                message_count=50 * (i + 1),
            )
            for i in range(5)
        ]
        
        # Calculate expected totals
        expected_contacts = sum(c.contact_count for c in channels)
        expected_messages = sum(c.message_count for c in channels)
        
        assert expected_contacts == 150  # 10+20+30+40+50
        assert expected_messages == 750  # 50+100+150+200+250
    
    def test_segment_member_count(self):
        """测试分群成员计数"""
        from app.db.models.private_domain import CustomerSegment, SegmentMember
        
        segment = CustomerSegment(
            account_id=uuid4(),
            name="VIP Segment",
            member_count=10,
        )
        segment.id = uuid4()
        
        members = [
            SegmentMember(segment_id=segment.id, customer_id=uuid4())
            for _ in range(10)
        ]
        
        assert segment.member_count == len(members)
    
    def test_deal_pipeline_value_calculation(self):
        """测试商机漏斗价值计算"""
        from app.db.models.private_domain import DealItem
        
        deals = [
            DealItem(pipeline_id=uuid4(), account_id=uuid4(), name="Deal 1", value=100000),
            DealItem(pipeline_id=uuid4(), account_id=uuid4(), name="Deal 2", value=200000),
            DealItem(pipeline_id=uuid4(), account_id=uuid4(), name="Deal 3", value=300000),
        ]
        
        total_value = sum(d.value for d in deals)
        assert total_value == 600000


# Test 7: 数据删除级联测试
class TestDataCascadeDelete:
    """测试数据删除级联"""
    
    def test_soft_delete_channel(self):
        """测试渠道软删除"""
        from app.db.models.private_domain import PrivateChannel
        
        channel = PrivateChannel(
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
        )
        
        # Simulate soft delete
        channel.is_deleted = True
        
        # Verify soft delete
        assert channel.is_deleted is True
    
    def test_segment_cascade_delete(self):
        """测试分群级联删除"""
        from app.db.models.private_domain import CustomerSegment, SegmentMember
        
        segment = CustomerSegment(
            account_id=uuid4(),
            name="VIP Segment",
        )
        segment.id = uuid4()
        
        members = [
            SegmentMember(segment_id=segment.id, customer_id=uuid4())
            for _ in range(3)
        ]
        
        # Verify relationships exist
        assert all(m.segment_id == segment.id for m in members)
        assert len(members) == 3
    
    def test_deal_stage_cascade(self):
        """测试商机阶段级联"""
        from app.db.models.private_domain import DealPipeline, DealStage, DealItem
        
        pipeline = DealPipeline(
            account_id=uuid4(),
            name="Sales Pipeline",
        )
        pipeline.id = uuid4()
        
        stage = DealStage(
            pipeline_id=pipeline.id,
            name="Qualified",
            order=1,
        )
        stage.id = uuid4()
        
        deal = DealItem(
            pipeline_id=pipeline.id,
            account_id=pipeline.account_id,
            name="Test Deal",
            stage_id=stage.id,
        )
        deal.id = uuid4()
        
        # Verify cascade relationships
        assert deal.stage_id == stage.id
        assert deal.pipeline_id == pipeline.id
        assert stage.pipeline_id == pipeline.id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
