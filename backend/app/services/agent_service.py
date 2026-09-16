"""Agent service layer - CRM integration"""
import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agent import Agent, AgentCustomerBinding
from app.db.models.customer import Customer
from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentCustomerBindingCreate,
    AgentCustomerBindingResponse,
    AgentPerformanceStats,
)

logger = logging.getLogger(__name__)


class AgentService:
    """Service for Agent CRUD and Customer-Agent integration"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- Agent CRUD ----------

    async def list_agents(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        name: Optional[str] = None,
    ) -> tuple[List[AgentResponse], int]:
        """List agents with pagination and filters"""
        query = select(Agent).where(Agent.is_deleted == False)
        total_query = select(func.count()).where(Agent.is_deleted == False)

        if status:
            query = query.where(Agent.status == status)
            total_query = total_query.where(Agent.status == status)

        if name:
            query = query.where(Agent.name.ilike(f"%{name}%"))
            total_query = total_query.where(Agent.name.ilike(f"%{name}%"))

        # Get total count
        total_result = await self.db.execute(total_query)
        total = total_result.scalar() or 0

        # Apply pagination
        query = query.order_by(Agent.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        agents = result.scalars().all()

        return [self._agent_to_response(a) for a in agents], total

    async def get_agent(self, agent_id: UUID) -> Optional[AgentResponse]:
        """Get agent by ID"""
        result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.is_deleted == False)
        )
        agent = result.scalar_one_or_none()
        return self._agent_to_response(agent) if agent else None

    async def create_agent(self, data: AgentCreate) -> AgentResponse:
        """Create a new agent"""
        agent = Agent(
            name=data.name,
            description=data.description,
            status=data.status or "active",
        )
        self.db.add(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        logger.info(f"Created agent: {agent.id}")
        return self._agent_to_response(agent)

    async def update_agent(self, agent_id: UUID, data: AgentUpdate) -> Optional[AgentResponse]:
        """Update an agent"""
        result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.is_deleted == False)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(agent, field, value)

        await self.db.commit()
        await self.db.refresh(agent)
        logger.info(f"Updated agent: {agent_id}")
        return self._agent_to_response(agent)

    async def delete_agent(self, agent_id: UUID) -> bool:
        """Soft delete an agent"""
        result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.is_deleted == False)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return False

        agent.is_deleted = True
        agent.updated_at = datetime.now(tz=agent.updated_at.tzinfo)
        await self.db.commit()
        logger.info(f"Deleted agent: {agent_id}")
        return True

    # ---------- Agent lifecycle (V1: status transitions only) ----------

    async def start_agent(self, agent_id: UUID) -> Optional[AgentResponse]:
        """Start an agent (V1: transitions status to 'active')."""
        agent = await self._get_active_agent(agent_id)
        if agent is None:
            return None
        agent.status = "active"
        agent.updated_at = datetime.now(tz=agent.updated_at.tzinfo)
        await self.db.commit()
        await self.db.refresh(agent)
        logger.info(f"Started agent: {agent_id}")
        return self._agent_to_response(agent)

    async def stop_agent(self, agent_id: UUID) -> Optional[AgentResponse]:
        """Stop an agent (V1: transitions status to 'inactive')."""
        agent = await self._get_active_agent(agent_id)
        if agent is None:
            return None
        agent.status = "inactive"
        agent.updated_at = datetime.now(tz=agent.updated_at.tzinfo)
        await self.db.commit()
        await self.db.refresh(agent)
        logger.info(f"Stopped agent: {agent_id}")
        return self._agent_to_response(agent)

    async def _get_active_agent(self, agent_id: UUID) -> Optional[Agent]:
        result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.is_deleted == False)
        )
        return result.scalar_one_or_none()

    # ---------- Agent-Customer Bindings ----------

    async def list_agent_customers(
        self,
        agent_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[AgentCustomerBindingResponse], int]:
        """List all customers assigned to an agent"""
        # Verify agent exists
        agent_result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.is_deleted == False)
        )
        if not agent_result.scalar_one_or_none():
            raise ValueError(f"Agent {agent_id} not found")

        query = (
            select(AgentCustomerBinding)
            .join(Customer, Customer.id == AgentCustomerBinding.customer_id)
            .where(
                and_(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.is_deleted == False,
                    Customer.is_deleted == False,
                )
            )
        )
        total_query = select(func.count()).select_from(query.subquery())

        total_result = await self.db.execute(total_query)
        total = total_result.scalar() or 0

        query = query.order_by(AgentCustomerBinding.assigned_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        bindings = result.scalars().all()

        return [self._binding_to_response(b) for b in bindings], total

    async def assign_customer_to_agent(
        self,
        agent_id: UUID,
        data: AgentCustomerBindingCreate,
        assigned_by: Optional[UUID] = None,
    ) -> AgentCustomerBindingResponse:
        """Assign a customer to an agent"""
        # Verify agent exists
        agent_result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.is_deleted == False)
        )
        if not agent_result.scalar_one_or_none():
            raise ValueError(f"Agent {agent_id} not found")

        # Verify customer exists
        customer_result = await self.db.execute(
            select(Customer).where(Customer.id == data.customer_id, Customer.is_deleted == False)
        )
        if not customer_result.scalar_one_or_none():
            raise ValueError(f"Customer {data.customer_id} not found")

        # Check if already assigned
        existing = await self.db.execute(
            select(AgentCustomerBinding).where(
                and_(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.customer_id == data.customer_id,
                    AgentCustomerBinding.is_deleted == False,
                )
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Customer {data.customer_id} is already assigned to agent {agent_id}")

        # Create binding
        binding = AgentCustomerBinding(
            agent_id=agent_id,
            customer_id=data.customer_id,
            assigned_by=assigned_by,
            notes=data.notes,
        )
        self.db.add(binding)
        await self.db.commit()
        await self.db.refresh(binding)
        logger.info(f"Assigned customer {data.customer_id} to agent {agent_id}")
        return self._binding_to_response(binding)

    async def remove_customer_from_agent(
        self,
        agent_id: UUID,
        customer_id: UUID,
    ) -> bool:
        """Remove a customer from an agent"""
        result = await self.db.execute(
            select(AgentCustomerBinding).where(
                and_(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.customer_id == customer_id,
                    AgentCustomerBinding.is_deleted == False,
                )
            )
        )
        binding = result.scalar_one_or_none()
        if not binding:
            return False

        binding.is_deleted = True
        binding.updated_at = datetime.now(tz=binding.updated_at.tzinfo)
        await self.db.commit()
        logger.info(f"Removed customer {customer_id} from agent {agent_id}")
        return True

    # ---------- Agent Performance ----------

    async def get_agent_performance(self, agent_id: UUID) -> Optional[AgentPerformanceStats]:
        """Get agent performance statistics"""
        # Verify agent exists
        agent_result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.is_deleted == False)
        )
        agent = agent_result.scalar_one_or_none()
        if not agent:
            return None

        # Count total customers
        customers_result = await self.db.execute(
            select(func.count())
            .select_from(AgentCustomerBinding)
            .where(
                and_(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.is_deleted == False,
                )
            )
        )
        total_customers = customers_result.scalar() or 0

        # Count active customers (customers with leads in active stages)
        from app.db.models.lead import Lead
        active_result = await self.db.execute(
            select(func.count())
            .select_from(AgentCustomerBinding)
            .join(Lead, Lead.customer_id == AgentCustomerBinding.customer_id)
            .where(
                and_(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.is_deleted == False,
                    Lead.is_deleted == False,
                    Lead.lifecycle_stage_code.notin_(["closed_lost", "deleted"]),
                )
            )
        )
        active_customers = active_result.scalar() or 0

        # Count leads
        leads_result = await self.db.execute(
            select(func.count())
            .select_from(AgentCustomerBinding)
            .join(Lead, Lead.customer_id == AgentCustomerBinding.customer_id)
            .where(
                and_(
                    AgentCustomerBinding.agent_id == agent_id,
                    AgentCustomerBinding.is_deleted == False,
                    Lead.is_deleted == False,
                )
            )
        )
        leads_count = leads_result.scalar() or 0

        # Calculate conversion rate (placeholder - can be enhanced with actual funnel data)
        conversion_rate = None
        if leads_count > 0:
            # This would need deal pipeline data for accurate calculation
            conversion_rate = 0.0

        return AgentPerformanceStats(
            agent_id=agent_id,
            agent_name=agent.name,
            total_customers=total_customers,
            active_customers=active_customers,
            conversion_rate=conversion_rate,
            leads_count=leads_count,
            deals_count=0,  # Would need deal pipeline integration
            deals_value=0.0,  # Would need deal pipeline integration
        )

    # ---------- Helpers ----------

    def _agent_to_response(self, agent: Agent) -> AgentResponse:
        """Convert Agent model to response schema"""
        return AgentResponse(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            status=agent.status,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    def _binding_to_response(self, binding: AgentCustomerBinding) -> AgentCustomerBindingResponse:
        """Convert binding to response schema"""
        customer_name = None
        customer_email = None
        customer_phone = None
        if binding.customer:
            customer_name = binding.customer.name
            customer_email = binding.customer.email
            customer_phone = binding.customer.phone

        return AgentCustomerBindingResponse(
            id=binding.id,
            agent_id=binding.agent_id,
            customer_id=binding.customer_id,
            notes=binding.notes,
            assigned_at=binding.assigned_at,
            assigned_by=binding.assigned_by,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
        )
