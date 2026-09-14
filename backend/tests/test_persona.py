"""Tests for Persona module"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.persona import PersonaCreate, PersonaUpdate
from app.services.persona_service import PersonaService


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
def sample_persona():
    """Create a sample persona for testing"""
    now = datetime.now(timezone.utc)
    persona = MagicMock()
    persona.id = uuid4()
    persona.name = "Test Persona"
    persona.description = "A test persona"
    persona.personality = {"trait1": "value1", "trait2": "value2"}
    persona.version = 1
    persona.parent_id = None
    persona.created_at = now
    persona.updated_at = now
    persona.is_deleted = False
    return persona


@pytest.fixture
def sample_persona_create():
    """Create a sample persona creation request"""
    return PersonaCreate(
        name="New Persona",
        description="A new test persona",
        personality={"friendly": True, "professional": False},
    )


@pytest.fixture
def sample_persona_update():
    """Create a sample persona update request"""
    return PersonaUpdate(
        name="Updated Persona",
        description="An updated description",
    )


def _make_persona_mock(**kwargs):
    """Helper to create a persona mock with proper defaults"""
    now = datetime.now(timezone.utc)
    persona = MagicMock()
    persona.id = kwargs.get('id', uuid4())
    persona.name = kwargs.get('name', 'Test Persona')
    persona.description = kwargs.get('description', 'Test')
    persona.personality = kwargs.get('personality', {"trait": "value"})
    persona.version = kwargs.get('version', 1)
    persona.parent_id = kwargs.get('parent_id', None)
    persona.created_at = kwargs.get('created_at', now)
    persona.updated_at = kwargs.get('updated_at', now)
    persona.is_deleted = kwargs.get('is_deleted', False)
    return persona


class TestPersonaService:
    """Test cases for PersonaService"""

    @pytest.mark.asyncio
    async def test_list_personas(self, mock_db, sample_persona):
        """Test listing personas"""
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [sample_persona]

        mock_db.execute.side_effect = [count_result, list_result]

        service = PersonaService(mock_db)
        personas, total = await service.list_personas()

        assert total == 1
        assert len(personas) == 1
        assert personas[0].name == "Test Persona"
        assert personas[0].version == 1

    @pytest.mark.asyncio
    async def test_get_persona_found(self, mock_db, sample_persona):
        """Test getting an existing persona"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_persona
        mock_db.execute.return_value = result

        service = PersonaService(mock_db)
        persona = await service.get_persona(sample_persona.id)

        assert persona is not None
        assert persona.id == sample_persona.id
        assert persona.name == "Test Persona"

    @pytest.mark.asyncio
    async def test_get_persona_not_found(self, mock_db):
        """Test getting a non-existent persona"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = PersonaService(mock_db)
        persona = await service.get_persona(uuid4())

        assert persona is None

    @pytest.mark.asyncio
    async def test_create_persona(self, mock_db, sample_persona_create):
        """Test creating a new persona"""
        new_persona = _make_persona_mock(
            name=sample_persona_create.name,
            description=sample_persona_create.description,
            personality=sample_persona_create.personality,
            version=1,
        )

        # Mock db.add to capture the persona
        captured = []
        def capture_add(obj):
            captured.append(obj)
        mock_db.add.side_effect = capture_add

        # Mock db.refresh to set attributes on the captured object
        def refresh(obj):
            obj.id = new_persona.id
            obj.name = new_persona.name
            obj.description = new_persona.description
            obj.personality = new_persona.personality
            obj.version = new_persona.version
            obj.parent_id = new_persona.parent_id
            obj.created_at = new_persona.created_at
            obj.updated_at = new_persona.updated_at
        mock_db.refresh.side_effect = refresh

        service = PersonaService(mock_db)
        result = await service.create_persona(sample_persona_create)

        assert result is not None
        assert result.name == "New Persona"
        assert result.version == 1
        assert result.personality == {"friendly": True, "professional": False}

    @pytest.mark.asyncio
    async def test_update_persona(self, mock_db, sample_persona, sample_persona_update):
        """Test updating a persona"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_persona
        mock_db.execute.return_value = result

        service = PersonaService(mock_db)
        updated = await service.update_persona(sample_persona.id, sample_persona_update)

        assert updated is not None
        assert updated.name == "Updated Persona"

    @pytest.mark.asyncio
    async def test_delete_persona(self, mock_db, sample_persona):
        """Test soft deleting a persona"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_persona
        mock_db.execute.return_value = result

        service = PersonaService(mock_db)
        success = await service.delete_persona(sample_persona.id)

        assert success is True
        assert sample_persona.is_deleted is True

    @pytest.mark.asyncio
    async def test_clone_persona(self, mock_db, sample_persona):
        """Test cloning a persona creates a new version"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_persona
        mock_db.execute.return_value = result

        # Mock add and refresh for the new cloned persona
        mock_db.add = MagicMock()
        cloned_persona = _make_persona_mock(
            name=sample_persona.name,
            version=2,
            parent_id=sample_persona.id,
            personality=sample_persona.personality,
        )
        def refresh(obj):
            obj.id = cloned_persona.id
            obj.name = cloned_persona.name
            obj.version = cloned_persona.version
            obj.parent_id = cloned_persona.parent_id
            obj.personality = cloned_persona.personality
            obj.created_at = cloned_persona.created_at
            obj.updated_at = cloned_persona.updated_at
        mock_db.refresh.side_effect = refresh

        service = PersonaService(mock_db)
        cloned = await service.clone_persona(sample_persona.id)

        assert cloned is not None
        assert cloned.version == 2
        assert cloned.parent_id == sample_persona.id
        assert cloned.personality == sample_persona.personality

    @pytest.mark.asyncio
    async def test_get_version_history(self, mock_db, sample_persona):
        """Test getting version history"""
        # First query gets the root persona
        root_result = MagicMock()
        root_result.scalar_one_or_none.return_value = sample_persona

        # Second query gets child versions
        versions_result = MagicMock()
        versions_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [root_result, versions_result]

        service = PersonaService(mock_db)
        history = await service.get_version_history(sample_persona.id)

        assert history.total == 1
        assert len(history.items) == 1
        assert history.items[0].version == 1

    @pytest.mark.asyncio
    async def test_personality_jsonb_read_write(self, mock_db):
        """Test that personality JSONB field is correctly handled"""
        create_data = PersonaCreate(
            name="JSON Test",
            personality={"nested": {"key": "value"}, "list": [1, 2, 3]},
        )

        new_persona = _make_persona_mock(
            name=create_data.name,
            personality=create_data.personality,
            version=1,
        )

        # Mock add and refresh
        mock_db.add = MagicMock()
        def refresh(obj):
            obj.id = new_persona.id
            obj.name = new_persona.name
            obj.personality = new_persona.personality
            obj.version = new_persona.version
            obj.parent_id = new_persona.parent_id
            obj.created_at = new_persona.created_at
            obj.updated_at = new_persona.updated_at
        mock_db.refresh.side_effect = refresh

        service = PersonaService(mock_db)
        result = await service.create_persona(create_data)

        assert result.personality == {"nested": {"key": "value"}, "list": [1, 2, 3]}
        assert isinstance(result.personality, dict)
