"""
Tests for Phase 5 Integration Service: Cross-module integration.
Focus on core functionality with simplified mocking.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4, UUID
from datetime import datetime

from app.db.models.customer import Customer
from app.db.models.lead import Lead
from app.db.models.private_domain import PrivateChannel, NurturePlan, DealItem


# Fixtures
@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# Tests for validate_data_consistency
class TestDataConsistency:
    async def test_validate_consistency_no_issues(self, mock_db):
        from app.services.integration_service import validate_data_consistency
        
        # All queries return empty results (no issues)
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = empty_result
        
        result = await validate_data_consistency(mock_db, uuid4())
        
        assert result["is_consistent"] == True
        assert result["issues_count"] == 0
    
    async def test_validate_consistency_with_orphaned_leads(self, mock_db):
        from app.services.integration_service import validate_data_consistency
        
        # Create an orphaned lead
        orphaned_lead = Lead(
            id=uuid4(),
            customer_id=uuid4(),  # points to non-existent customer
            status="converted",
        )
        
        # First query returns leads
        leads_result = MagicMock()
        leads_result.scalars.return_value.all.return_value = [orphaned_lead]
        
        # Subsequent queries return None (customer not found)
        customer_not_found = MagicMock()
        customer_not_found.scalar_one_or_none.return_value = None
        
        call_count = [0]
        def mock_execute(query):
            call_count[0] += 1
            if call_count[0] == 1:
                return leads_result
            return customer_not_found
        
        mock_db.execute.side_effect = mock_execute
        
        result = await validate_data_consistency(mock_db, uuid4())
        
        assert result["is_consistent"] == False
        assert result["issues_count"] > 0
        assert any(issue["type"] == "orphaned_lead_customer" for issue in result["issues"])


# Tests for get_integration_stats
class TestIntegrationStats:
    async def test_get_integration_stats(self, mock_db):
        from app.services.integration_service import get_integration_stats
        
        # Mock all count queries to return 0
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        mock_db.execute.return_value = count_result
        
        result = await get_integration_stats(mock_db, uuid4())
        
        assert "statistics" in result
        assert "leads" in result["statistics"]
        assert "customers" in result["statistics"]
        assert "deals" in result["statistics"]
        assert result["statistics"]["leads"]["total"] == 0


# Tests for associate_customer_with_channel
class TestCustomerChannelAssociation:
    async def test_associate_customer_with_channel_success(self, mock_db):
        from app.services.integration_service import associate_customer_with_channel
        
        customer = Customer(id=uuid4(), name="Test Customer", extra_info={})
        channel = PrivateChannel(
            id=uuid4(),
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
            status="active",
        )
        
        # First query: get customer
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer
        
        # Second query: get channel
        channel_result = MagicMock()
        channel_result.scalar_one_or_none.return_value = channel
        
        call_count = [0]
        def mock_execute(query):
            call_count[0] += 1
            if call_count[0] == 1:
                return customer_result
            return channel_result
        
        mock_db.execute.side_effect = mock_execute
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        result = await associate_customer_with_channel(mock_db, customer.id, channel.id)
        
        assert result["channel_id"] == str(channel.id)
        assert result["channel_name"] == channel.name
        assert result["channel_type"] == channel.channel_type
    
    async def test_associate_customer_not_found(self, mock_db):
        from app.services.integration_service import associate_customer_with_channel
        
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = customer_result
        
        with pytest.raises(ValueError, match="Customer.*not found"):
            await associate_customer_with_channel(mock_db, uuid4(), uuid4())
    
    async def test_associate_channel_not_found(self, mock_db):
        from app.services.integration_service import associate_customer_with_channel
        
        customer = Customer(id=uuid4(), name="Test Customer")
        
        # First query: get customer
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer
        
        # Second query: get channel (not found)
        channel_result = MagicMock()
        channel_result.scalar_one_or_none.return_value = None
        
        call_count = [0]
        def mock_execute(query):
            call_count[0] += 1
            if call_count[0] == 1:
                return customer_result
            return channel_result
        
        mock_db.execute.side_effect = mock_execute
        
        with pytest.raises(ValueError, match="Private channel.*not found"):
            await associate_customer_with_channel(mock_db, customer.id, uuid4())


# Tests for apply_nurture_plan_to_customer
class TestNurturePlanApplication:
    async def test_apply_nurture_plan_success(self, mock_db):
        from app.services.integration_service import apply_nurture_plan_to_customer
        
        plan = NurturePlan(
            id=uuid4(),
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Onboarding Sequence",
            status="active",
            schedule_type="drip",
            target_segment_id=uuid4(),
            performance_metrics={},
        )
        customer = Customer(id=uuid4(), name="Test Customer")
        
        # Query 1: get plan
        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        
        # Query 2: get customer
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer
        
        # Query 3: check segment member (not exists)
        member_result = MagicMock()
        member_result.scalar_one_or_none.return_value = None
        
        call_count = [0]
        def mock_execute(query):
            call_count[0] += 1
            if call_count[0] == 1:
                return plan_result
            elif call_count[0] == 2:
                return customer_result
            else:
                return member_result
        
        mock_db.execute.side_effect = mock_execute
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        result = await apply_nurture_plan_to_customer(mock_db, plan.id, customer.id)
        
        assert result["success"] == True
        assert result["added_to_segment"] == True
    
    async def test_apply_plan_not_found(self, mock_db):
        from app.services.integration_service import apply_nurture_plan_to_customer
        
        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = plan_result
        
        with pytest.raises(ValueError, match="Nurture plan.*not found"):
            await apply_nurture_plan_to_customer(mock_db, uuid4(), uuid4())
    
    async def test_apply_inactive_plan(self, mock_db):
        from app.services.integration_service import apply_nurture_plan_to_customer
        
        plan = NurturePlan(
            id=uuid4(),
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Draft Plan",
            status="draft",  # Not active
            schedule_type="fixed",
        )
        
        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        mock_db.execute.return_value = plan_result
        
        with pytest.raises(ValueError, match="not active"):
            await apply_nurture_plan_to_customer(mock_db, plan.id, uuid4())


# Tests for get_customer_channel
class TestGetCustomerChannel:
    async def test_get_customer_channel_found(self, mock_db):
        from app.services.integration_service import get_customer_channel
        
        customer = Customer(
            id=uuid4(),
            name="Test Customer",
            extra_info={"private_channel_id": str(uuid4())},
        )
        channel = PrivateChannel(
            id=UUID(customer.extra_info["private_channel_id"]),
            account_id=uuid4(),
            platform_id="wechat",
            channel_type="wechat",
            name="Test Channel",
            status="active",
        )
        
        # Query 1: get customer
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer
        
        # Query 2: get channel
        channel_result = MagicMock()
        channel_result.scalar_one_or_none.return_value = channel
        
        call_count = [0]
        def mock_execute(query):
            call_count[0] += 1
            if call_count[0] == 1:
                return customer_result
            return channel_result
        
        mock_db.execute.side_effect = mock_execute
        
        result = await get_customer_channel(mock_db, customer.id)
        
        assert result["id"] == str(channel.id)
        assert result["channel_type"] == channel.channel_type
    
    async def test_get_customer_channel_not_found(self, mock_db):
        from app.services.integration_service import get_customer_channel
        
        # Customer with no channel reference
        customer = Customer(id=uuid4(), name="Test Customer", extra_info={})
        
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer
        mock_db.execute.return_value = customer_result
        
        result = await get_customer_channel(mock_db, customer.id)
        assert result is None


# Tests for create_deal_with_customer
class TestDealCreationWithCustomer:
    async def test_create_deal_with_invalid_customer(self, mock_db):
        from app.services.integration_service import create_deal_with_customer
        
        # Mock customer not found
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = customer_result
        
        with pytest.raises(ValueError, match="Customer.*not found"):
            await create_deal_with_customer(
                mock_db,
                pipeline_id=uuid4(),
                account_id=uuid4(),
                customer_id=uuid4(),
            )
