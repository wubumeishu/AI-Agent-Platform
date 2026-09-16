"""
Tests for Nurture Plan module with step management and state transitions
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.db.models.private_domain import (
    NurturePlan,
    NurturePlanItem,
    CustomerSegment,
)
from app.schemas.private_domain import (
    NurturePlanCreate,
    NurturePlanUpdate,
)


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

    ``db = AsyncMock()`` auto-generates AsyncMock attributes, so attribute
    access returns AsyncMock instances instead of the assigned values.
    (The original mock_db fixture has this latent defect; tests that assert
    on call counts keep using it - it still works because AsyncMock
    auto-attribute access returns AsyncMocks, not the assigned values.)
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
def nurture_plan_create_data():
    return NurturePlanCreate(
        channel_id=uuid4(),
        account_id=uuid4(),
        name="Onboarding Plan",
        description="Welcome sequence for new customers",
        schedule_type="drip",
        sequence_steps=[
            {"step": 1, "delay_hours": 0},
            {"step": 2, "delay_hours": 24},
            {"step": 3, "delay_hours": 48},
        ],
        trigger_conditions=[
            {"type": "signup", "field": "created_at"}
        ],
        target_segment_id=uuid4(),
    )


@pytest.fixture
def nurture_plan_update_data():
    return NurturePlanUpdate(
        name="Updated Onboarding Plan",
        description="Updated description",
        status="active",
    )


# Tests for NurturePlan
class TestNurturePlan:
    async def test_create_nurture_plan(self, mock_db2, nurture_plan_create_data):
        """Test creating a nurture plan (Contract B: steps -> nurture_plan_item)"""
        from app.services.nurture_plan_service import create_nurture_plan
        from app.db.models.private_domain import NurturePlanItem

        plan = await create_nurture_plan(mock_db2, nurture_plan_create_data)

        assert plan is not None
        assert plan["name"] == "Onboarding Plan"
        # Status defaults to 'draft' in model but may not be set in mock
        assert plan["schedule_type"] == "drip"
        # Legacy JSON column is retired: steps surface from the SoT table,
        # never as sequence_steps in the payload.
        assert "sequence_steps" not in plan
        # 3 step rows staged for insert (3-step fixture)
        items = [
            c.args[0]
            for c in mock_db2.add.call_args_list
            if c.args and isinstance(c.args[0], NurturePlanItem)
        ]
        assert len(items) == 3
        mock_db2.commit.assert_called_once()
    
    async def test_get_nurture_plans(self, mock_db, nurture_plan_create_data):
        """Test getting list of nurture plans"""
        from app.services.nurture_plan_service import get_nurture_plans
        
        plan = NurturePlan(**nurture_plan_create_data.model_dump())
        plan.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [plan]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await get_nurture_plans(
            mock_db,
            channel_id=nurture_plan_create_data.channel_id,
            account_id=nurture_plan_create_data.account_id,
        )
        
        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "Onboarding Plan"
    
    async def test_get_nurture_plans_with_status_filter(self, mock_db, nurture_plan_create_data):
        """Test getting nurture plans with status filter"""
        from app.services.nurture_plan_service import get_nurture_plans
        
        plan = NurturePlan(**nurture_plan_create_data.model_dump())
        plan.id = uuid4()
        plan.status = "active"
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [plan]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await get_nurture_plans(mock_db, status="active")
        
        assert result["total"] == 1
        assert result["items"][0]["status"] == "active"
    
    async def test_update_nurture_plan(self, mock_db, nurture_plan_create_data):
        """Test updating a nurture plan"""
        from app.services.nurture_plan_service import update_nurture_plan
        
        plan = NurturePlan(**nurture_plan_create_data.model_dump())
        plan.id = uuid4()
        plan.status = "draft"
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = plan
        mock_db.execute.return_value = mock_result
        
        update_data = NurturePlanUpdate(name="Updated Plan", status="active")
        result = await update_nurture_plan(mock_db, plan.id, update_data)
        
        assert result is not None
        assert result["name"] == "Updated Plan"
        assert result["status"] == "active"
        mock_db.commit.assert_called_once()
    
    async def test_update_nurture_plan_not_found(self, mock_db):
        """Test updating non-existent nurture plan"""
        from app.services.nurture_plan_service import update_nurture_plan
        from app.schemas.private_domain import NurturePlanUpdate
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        update_data = NurturePlanUpdate(name="Updated Plan")
        result = await update_nurture_plan(mock_db, uuid4(), update_data)
        
        assert result is None
    
    async def test_delete_nurture_plan(self, mock_db, nurture_plan_create_data):
        """Test deleting a nurture plan"""
        from app.services.nurture_plan_service import delete_nurture_plan
        
        plan = NurturePlan(**nurture_plan_create_data.model_dump())
        plan.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = plan
        mock_db.execute.return_value = mock_result
        
        success = await delete_nurture_plan(mock_db, plan.id)
        
        assert success is True
        mock_db.commit.assert_called_once()
    
    async def test_delete_nurture_plan_not_found(self, mock_db):
        """Test deleting non-existent nurture plan"""
        from app.services.nurture_plan_service import delete_nurture_plan
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        success = await delete_nurture_plan(mock_db, uuid4())
        
        assert success is False


# Tests for NurturePlan Detail with Steps
class TestNurturePlanDetail:
    async def test_get_nurture_plan_with_steps(self, mock_db):
        """Test getting nurture plan detail with related steps"""
        from app.services.nurture_plan_service import get_nurture_plan
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
            status="draft",
        )
        plan.id = uuid4()
        
        step1 = NurturePlanItem(
            plan_id=plan.id,
            step_order=1,
            delay_hours=0,
            trigger_type="time_based",
        )
        step1.id = uuid4()
        
        step2 = NurturePlanItem(
            plan_id=plan.id,
            step_order=2,
            delay_hours=24,
            trigger_type="time_based",
        )
        step2.id = uuid4()
        
        # Mock plan query
        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        mock_db.execute.side_effect = [
            plan_result,
            MagicMock(scalars=lambda: MagicMock(all=lambda: [step1, step2])),
        ]
        
        result = await get_nurture_plan(mock_db, plan.id)
        
        assert result is not None
        assert result["id"] == plan.id
        assert result["name"] == "Test Plan"
        assert len(result["steps"]) == 2
        assert result["steps"][0]["step_order"] == 1
        assert result["steps"][1]["step_order"] == 2
    
    async def test_get_nurture_plan_not_found(self, mock_db):
        """Test getting non-existent nurture plan"""
        from app.services.nurture_plan_service import get_nurture_plan
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        result = await get_nurture_plan(mock_db, uuid4())
        
        assert result is None


# Tests for State Transitions
class TestNurturePlanStateTransitions:
    async def test_transition_draft_to_active(self, mock_db):
        """Test transitioning plan from draft to active"""
        from app.services.nurture_plan_service import transition_nurture_plan_status
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
            status="draft",
        )
        plan.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = plan
        mock_db.execute.return_value = mock_result
        
        result = await transition_nurture_plan_status(mock_db, plan.id, "active")
        
        assert result is not None
        assert result["status"] == "active"
        assert result["previous_status"] == "draft"
        mock_db.commit.assert_called_once()
    
    async def test_transition_active_to_paused(self, mock_db):
        """Test transitioning plan from active to paused"""
        from app.services.nurture_plan_service import transition_nurture_plan_status
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
            status="active",
        )
        plan.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = plan
        mock_db.execute.return_value = mock_result
        
        result = await transition_nurture_plan_status(mock_db, plan.id, "paused")
        
        assert result["status"] == "paused"
        assert result["previous_status"] == "active"
    
    async def test_transition_paused_to_completed(self, mock_db):
        """Test transitioning plan from paused to completed"""
        from app.services.nurture_plan_service import transition_nurture_plan_status
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
            status="paused",
        )
        plan.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = plan
        mock_db.execute.return_value = mock_result
        
        result = await transition_nurture_plan_status(mock_db, plan.id, "completed")
        
        assert result["status"] == "completed"
        assert result["previous_status"] == "paused"
    
    async def test_transition_invalid(self, mock_db):
        """Test invalid status transition"""
        from app.services.nurture_plan_service import transition_nurture_plan_status
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
            status="completed",
        )
        plan.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = plan
        mock_db.execute.return_value = mock_result
        
        with pytest.raises(ValueError, match="Cannot transition"):
            await transition_nurture_plan_status(mock_db, plan.id, "active")
    
    async def test_transition_archived_final_state(self, mock_db):
        """Test that archived is a final state"""
        from app.services.nurture_plan_service import transition_nurture_plan_status
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
            status="archived",
        )
        plan.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = plan
        mock_db.execute.return_value = mock_result
        
        with pytest.raises(ValueError, match="Cannot transition"):
            await transition_nurture_plan_status(mock_db, plan.id, "active")
    
    async def test_transition_not_found(self, mock_db):
        """Test transitioning non-existent plan"""
        from app.services.nurture_plan_service import transition_nurture_plan_status
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        result = await transition_nurture_plan_status(mock_db, uuid4(), "active")
        
        assert result is None


# Tests for NurturePlanItem (Step) Management
class TestNurturePlanStep:
    async def test_create_nurture_plan_step(self, mock_db):
        """Test creating a nurture plan step"""
        from app.services.nurture_plan_service import create_nurture_plan_step
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
            status="draft",
        )
        plan.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = plan
        mock_db.execute.return_value = mock_result
        
        result = await create_nurture_plan_step(
            mock_db,
            plan.id,
            step_order=1,
            delay_hours=0,
            trigger_type="time_based",
        )
        
        assert result is not None
        assert result["step_order"] == 1
        assert result["delay_hours"] == 0
        assert result["trigger_type"] == "time_based"
        mock_db.add.assert_called_once()
    
    async def test_create_step_plan_not_found(self, mock_db):
        """Test creating step for non-existent plan"""
        from app.services.nurture_plan_service import create_nurture_plan_step
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        with pytest.raises(ValueError, match="not found"):
            await create_nurture_plan_step(mock_db, uuid4(), step_order=1)
    
    async def test_update_nurture_plan_step(self, mock_db):
        """Test updating a nurture plan step"""
        from app.services.nurture_plan_service import update_nurture_plan_step
        
        step = NurturePlanItem(
            plan_id=uuid4(),
            step_order=1,
            delay_hours=0,
            trigger_type="time_based",
        )
        step.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = step
        mock_db.execute.return_value = mock_result
        
        result = await update_nurture_plan_step(mock_db, step.id, {"delay_hours": 24})
        
        assert result is not None
        assert result["delay_hours"] == 24
        mock_db.commit.assert_called_once()
    
    async def test_delete_nurture_plan_step(self, mock_db):
        """Test deleting a nurture plan step"""
        from app.services.nurture_plan_service import delete_nurture_plan_step
        
        step = NurturePlanItem(
            plan_id=uuid4(),
            step_order=1,
            delay_hours=0,
        )
        step.id = uuid4()
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = step
        mock_db.execute.return_value = mock_result
        
        success = await delete_nurture_plan_step(mock_db, step.id)
        
        assert success is True
        mock_db.commit.assert_called_once()
    
    async def test_delete_step_not_found(self, mock_db):
        """Test deleting non-existent step"""
        from app.services.nurture_plan_service import delete_nurture_plan_step
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        success = await delete_nurture_plan_step(mock_db, uuid4())
        
        assert success is False


# Tests for Step Reordering
class TestNurturePlanStepReorder:
    async def test_reorder_steps(self, mock_db):
        """Test reordering steps in a nurture plan"""
        from app.services.nurture_plan_service import reorder_nurture_plan_steps
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
            status="draft",
        )
        plan.id = uuid4()
        
        step1 = NurturePlanItem(plan_id=plan.id, step_order=0, delay_hours=0)
        step1.id = uuid4()
        
        step2 = NurturePlanItem(plan_id=plan.id, step_order=1, delay_hours=24)
        step2.id = uuid4()
        
        # Mock plan query
        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        
        # Mock step queries for updates
        step_result = MagicMock()
        step_result.scalar_one_or_none.side_effect = [step1, step2]
        
        # Mock final steps query
        final_result = MagicMock()
        final_result.scalars.return_value.all.return_value = [step1, step2]
        
        mock_db.execute.side_effect = [
            plan_result,
            step_result,
            step_result,
            final_result,
        ]
        
        result = await reorder_nurture_plan_steps(
            mock_db,
            plan.id,
            [
                {"id": step1.id, "step_order": 1},
                {"id": step2.id, "step_order": 0},
            ]
        )
        
        assert result["plan_id"] == plan.id
        assert len(result["steps"]) == 2
    
    async def test_reorder_steps_plan_not_found(self, mock_db):
        """Test reordering steps for non-existent plan"""
        from app.services.nurture_plan_service import reorder_nurture_plan_steps
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        with pytest.raises(ValueError, match="not found"):
            await reorder_nurture_plan_steps(mock_db, uuid4(), [])


# Tests for NurturePlan Statistics
class TestNurturePlanStats:
    async def test_get_nurture_plan_stats(self, mock_db):
        """Test getting nurture plan statistics"""
        from app.services.nurture_plan_service import get_nurture_plan_stats
        
        plan = NurturePlan(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Test Plan",
            status="active",
        )
        plan.id = uuid4()
        
        # Mock plan query
        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        
        # Mock step count queries
        count_result = MagicMock()
        count_result.scalar.return_value = 5
        
        mock_db.execute.side_effect = [
            plan_result,
            count_result,
            count_result,
            count_result,
        ]
        
        result = await get_nurture_plan_stats(mock_db, plan.id)
        
        assert result is not None
        assert result["plan_id"] == plan.id
        assert result["plan_name"] == "Test Plan"
        assert result["status"] == "active"
        assert result["total_steps"] == 5
    
    async def test_get_nurture_plan_stats_not_found(self, mock_db):
        """Test getting stats for non-existent plan"""
        from app.services.nurture_plan_service import get_nurture_plan_stats
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        result = await get_nurture_plan_stats(mock_db, uuid4())
        
        assert result is None


# Tests for Integration with CustomerSegment
class TestNurturePlanSegmentIntegration:
    async def test_create_nurture_plan_with_segment(self, mock_db2):
        """Test creating nurture plan linked to customer segment"""
        from app.services.nurture_plan_service import create_nurture_plan
        from app.schemas.private_domain import NurturePlanCreate
        from app.db.models.private_domain import NurturePlan

        segment_id = uuid4()
        data = NurturePlanCreate(
            channel_id=uuid4(),
            account_id=uuid4(),
            name="Segment-based Plan",
            target_segment_id=segment_id,
        )
        
        plan = await create_nurture_plan(mock_db2, data)
        
        assert plan is not None
        assert plan["target_segment_id"] == segment_id
        # Legacy JSON column retired (Contract B): no sequence_steps in payload
        assert "sequence_steps" not in plan
        plan_row = [
            c.args[0]
            for c in mock_db2.add.call_args_list
            if c.args and isinstance(c.args[0], NurturePlan)
        ][0]
        assert plan_row.sequence_steps == []
    
    async def test_update_nurture_plan_segment(self, mock_db, nurture_plan_create_data):
        """Test updating nurture plan's target segment"""
        from app.services.nurture_plan_service import update_nurture_plan
        from app.schemas.private_domain import NurturePlanUpdate
        
        plan = NurturePlan(**nurture_plan_create_data.model_dump())
        plan.id = uuid4()
        plan.target_segment_id = None
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = plan
        mock_db.execute.return_value = mock_result
        
        new_segment_id = uuid4()
        update_data = NurturePlanUpdate(target_segment_id=new_segment_id)
        result = await update_nurture_plan(mock_db, plan.id, update_data)
        
        assert result is not None
        assert result["target_segment_id"] == new_segment_id
