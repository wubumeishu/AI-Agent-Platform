"""Tests for Agent module - CRM integration"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentCustomerBindingCreate,
)
from app.services.agent_service import AgentService


@pytest.fixture
def mock_db():
    """Create a mock database session"""
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def sample_agent():
    """Create a sample agent for testing"""
    agent = MagicMock()
    agent.id = uuid4()
    agent.name = "Test Agent"
    agent.description = "Test description"
    agent.status = "active"
    agent.created_at = datetime.now(timezone.utc)
    agent.updated_at = datetime.now(timezone.utc)
    agent.is_deleted = False
    return agent


@pytest.fixture
def sample_agent_create():
    """Create a sample agent creation request"""
    return AgentCreate(
        name="New Agent",
        description="New agent description",
        status="active",
    )


@pytest.fixture
def sample_customer():
    """Create a sample customer for testing"""
    customer = MagicMock()
    customer.id = uuid4()
    customer.name = "Test Customer"
    customer.email = "test@example.com"
    customer.phone = "1234567890"
    customer.is_deleted = False
    return customer


@pytest.fixture
def sample_binding():
    """Create a sample agent-customer binding"""
    binding = MagicMock()
    binding.id = uuid4()
    binding.agent_id = uuid4()
    binding.customer_id = uuid4()
    binding.assigned_at = datetime.now(timezone.utc)
    binding.assigned_by = None
    binding.notes = "Test note"
    binding.is_deleted = False
    binding.customer = MagicMock()
    binding.customer.name = "Test Customer"
    binding.customer.email = "test@example.com"
    binding.customer.phone = "1234567890"
    return binding


class TestAgentService:
    """Test cases for AgentService"""

    @pytest.mark.asyncio
    async def test_list_agents(self, mock_db, sample_agent):
        """Test listing agents"""
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [sample_agent]
        
        mock_db.execute.side_effect = [count_result, list_result]

        service = AgentService(mock_db)
        agents, total = await service.list_agents()

        assert total == 1
        assert len(agents) == 1
        assert agents[0].name == "Test Agent"
        assert agents[0].status == "active"

    @pytest.mark.asyncio
    async def test_get_agent_found(self, mock_db, sample_agent):
        """Test getting an existing agent"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_agent
        mock_db.execute.return_value = result

        service = AgentService(mock_db)
        agent = await service.get_agent(sample_agent.id)

        assert agent is not None
        assert agent.id == sample_agent.id
        assert agent.name == "Test Agent"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, mock_db):
        """Test getting a non-existent agent"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = AgentService(mock_db)
        agent = await service.get_agent(uuid4())

        assert agent is None

    @pytest.mark.asyncio
    async def test_create_agent(self, mock_db, sample_agent_create):
        """Test creating a new agent"""
        mock_agent = MagicMock()
        mock_agent.id = uuid4()
        mock_agent.name = "New Agent"
        mock_agent.description = "New agent description"
        mock_agent.status = "active"
        mock_agent.created_at = datetime.now(timezone.utc)
        mock_agent.updated_at = datetime.now(timezone.utc)
        mock_agent.is_deleted = False
        
        async def mock_refresh(obj):
            obj.id = mock_agent.id
            obj.created_at = mock_agent.created_at
            obj.updated_at = mock_agent.updated_at
        
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=mock_refresh)
        
        service = AgentService(mock_db)
        agent = await service.create_agent(sample_agent_create)

        assert agent is not None
        assert agent.name == "New Agent"
        assert agent.status == "active"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_agent(self, mock_db, sample_agent, sample_agent_create):
        """Test updating an agent"""
        update_data = AgentUpdate(name="Updated Agent", status="inactive")
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_agent
        mock_db.execute.return_value = result
        mock_db.commit = AsyncMock()

        service = AgentService(mock_db)
        updated = await service.update_agent(sample_agent.id, update_data)

        assert updated is not None
        assert updated.name == "Updated Agent"
        assert updated.status == "inactive"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_agent_not_found(self, mock_db, sample_agent_create):
        """Test updating a non-existent agent"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = AgentService(mock_db)
        updated = await service.update_agent(uuid4(), sample_agent_create)

        assert updated is None

    @pytest.mark.asyncio
    async def test_delete_agent(self, mock_db, sample_agent):
        """Test soft deleting an agent"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_agent
        mock_db.execute.return_value = result
        mock_db.commit = AsyncMock()

        service = AgentService(mock_db)
        success = await service.delete_agent(sample_agent.id)

        assert success is True
        assert sample_agent.is_deleted is True
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_agent_not_found(self, mock_db):
        """Test deleting a non-existent agent"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = AgentService(mock_db)
        success = await service.delete_agent(uuid4())

        assert success is False


class TestAgentCustomerBindingService:
    """Test cases for Agent-Customer binding management"""

    @pytest.mark.asyncio
    async def test_list_agent_customers(self, mock_db, sample_agent, sample_binding):
        """Test listing customers for an agent"""
        # Mock agent existence check
        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = sample_agent
        
        # Mock count query
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        
        # Mock list query
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [sample_binding]
        
        mock_db.execute.side_effect = [agent_result, count_result, list_result]

        service = AgentService(mock_db)
        customers, total = await service.list_agent_customers(sample_agent.id)

        assert total == 1
        assert len(customers) == 1
        assert customers[0].customer_name == "Test Customer"

    @pytest.mark.asyncio
    async def test_list_agent_customers_agent_not_found(self, mock_db):
        """Test listing customers for non-existent agent"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = AgentService(mock_db)
        with pytest.raises(ValueError, match="not found"):
            await service.list_agent_customers(uuid4())

    @pytest.mark.asyncio
    async def test_assign_customer_to_agent(self, mock_db, sample_agent, sample_customer, sample_binding):
        """Test assigning customer to agent"""
        # Mock agent check
        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = sample_agent
        
        # Mock customer check
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = sample_customer
        
        # Mock existing check
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        
        # Mock list result for binding
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [sample_binding]
        
        async def mock_refresh(obj):
            obj.id = sample_binding.id
            obj.assigned_at = sample_binding.assigned_at
        
        mock_db.execute.side_effect = [agent_result, customer_result, existing_result, list_result]
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=mock_refresh)
        mock_db.add = MagicMock()

        create_data = AgentCustomerBindingCreate(
            customer_id=sample_customer.id,
            notes="Test note",
        )
        
        service = AgentService(mock_db)
        binding = await service.assign_customer_to_agent(sample_agent.id, create_data)

        assert binding is not None
        assert binding.agent_id == sample_agent.id
        assert binding.customer_id == sample_customer.id
        assert binding.notes == "Test note"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_assign_customer_to_agent_already_assigned(self, mock_db, sample_agent, sample_customer):
        """Test assigning already assigned customer"""
        # Mock agent check
        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = sample_agent
        
        # Mock customer check
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = sample_customer
        
        # Mock existing binding
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = MagicMock()

        mock_db.execute.side_effect = [agent_result, customer_result, existing_result]

        create_data = AgentCustomerBindingCreate(
            customer_id=sample_customer.id,
        )
        
        service = AgentService(mock_db)
        with pytest.raises(ValueError, match="already assigned"):
            await service.assign_customer_to_agent(sample_agent.id, create_data)

    @pytest.mark.asyncio
    async def test_remove_customer_from_agent(self, mock_db, sample_binding):
        """Test removing customer from agent"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_binding
        mock_db.execute.return_value = result
        mock_db.commit = AsyncMock()
        
        # Fix the MagicMock timezone issue
        sample_binding.updated_at.tzinfo = timezone.utc

        service = AgentService(mock_db)
        success = await service.remove_customer_from_agent(
            sample_binding.agent_id,
            sample_binding.customer_id,
        )

        assert success is True
        assert sample_binding.is_deleted is True
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_customer_from_agent_not_found(self, mock_db):
        """Test removing non-existent binding"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = AgentService(mock_db)
        success = await service.remove_customer_from_agent(uuid4(), uuid4())

        assert success is False


class TestAgentPerformance:
    """Test cases for Agent performance statistics"""

    @pytest.mark.asyncio
    async def test_get_agent_performance(self, mock_db, sample_agent):
        """Test getting agent performance stats"""
        # Mock agent check
        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = sample_agent
        
        # Mock customer count
        customers_result = MagicMock()
        customers_result.scalar.return_value = 5
        
        # Mock active customers count
        active_result = MagicMock()
        active_result.scalar.return_value = 3
        
        # Mock leads count
        leads_result = MagicMock()
        leads_result.scalar.return_value = 10
        
        mock_db.execute.side_effect = [
            agent_result,
            customers_result,
            active_result,
            leads_result,
        ]

        service = AgentService(mock_db)
        stats = await service.get_agent_performance(sample_agent.id)

        assert stats is not None
        assert stats.agent_id == sample_agent.id
        assert stats.total_customers == 5
        assert stats.active_customers == 3
        assert stats.leads_count == 10

    @pytest.mark.asyncio
    async def test_get_agent_performance_not_found(self, mock_db):
        """Test getting performance for non-existent agent"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = AgentService(mock_db)
        stats = await service.get_agent_performance(uuid4())

        assert stats is None
