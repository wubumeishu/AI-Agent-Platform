"""Tests for PromptTemplate module"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateUpdate,
)
from app.services.prompt_template_service import PromptTemplateService


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
def sample_template():
    """Create a sample template for testing"""
    now = datetime.now(timezone.utc)
    template = MagicMock()
    template.id = uuid4()
    template.name = "Test Template"
    template.description = "A test template"
    template.content = "Hello {{name}}, welcome to {{place}}!"
    template.template_type = "conversation"
    template.category = "test"
    template.variables = ["name", "place"]  # List of strings, not dicts
    template.version = 1
    template.parent_id = None
    template.is_baseline = True
    template.created_at = now
    template.updated_at = now
    template.is_deleted = False
    return template


@pytest.fixture
def sample_template_create():
    """Create a sample template creation request"""
    return PromptTemplateCreate(
        name="New Template",
        description="A new test template",
        content="Hello {{name}}!",
        template_type="greeting",
        category="test",
        variables=["name"],
        is_baseline=True,
    )


@pytest.fixture
def sample_template_update():
    """Create a sample template update request"""
    return PromptTemplateUpdate(
        name="Updated Template",
        description="An updated description",
    )


def _make_template_mock(**kwargs):
    """Helper to create a template mock with proper defaults"""
    now = datetime.now(timezone.utc)
    template = MagicMock()
    template.id = kwargs.get('id', uuid4())
    template.name = kwargs.get('name', 'Test Template')
    template.description = kwargs.get('description', 'Test')
    template.content = kwargs.get('content', 'Hello {{name}}!')
    template.template_type = kwargs.get('template_type', 'custom')
    template.category = kwargs.get('category', None)
    template.variables = kwargs.get('variables', ["name"])
    template.version = kwargs.get('version', 1)
    template.parent_id = kwargs.get('parent_id', None)
    template.is_baseline = kwargs.get('is_baseline', True)
    template.created_at = kwargs.get('created_at', now)
    template.updated_at = kwargs.get('updated_at', now)
    template.is_deleted = kwargs.get('is_deleted', False)
    return template


class TestPromptTemplateService:
    """Test cases for PromptTemplateService"""

    @pytest.mark.asyncio
    async def test_list_templates(self, mock_db, sample_template):
        """Test listing templates"""
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [sample_template]

        mock_db.execute.side_effect = [count_result, list_result]

        # Set created_at and updated_at on sample_template
        now = datetime.now(timezone.utc)
        sample_template.created_at = now
        sample_template.updated_at = now

        service = PromptTemplateService(mock_db)
        templates, total = await service.list_templates()

        assert total == 1
        assert len(templates) == 1
        assert templates[0].name == "Test Template"
        assert templates[0].version == 1

    @pytest.mark.asyncio
    async def test_get_template_found(self, mock_db, sample_template):
        """Test getting an existing template"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result

        # Set created_at and updated_at on sample_template
        now = datetime.now(timezone.utc)
        sample_template.created_at = now
        sample_template.updated_at = now

        service = PromptTemplateService(mock_db)
        template = await service.get_template(sample_template.id)

        assert template is not None
        assert template.id == sample_template.id
        assert template.name == "Test Template"

    @pytest.mark.asyncio
    async def test_get_template_not_found(self, mock_db):
        """Test getting a non-existent template"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = PromptTemplateService(mock_db)
        template = await service.get_template(uuid4())

        assert template is None

    @pytest.mark.asyncio
    async def test_create_template_baseline(self, mock_db, sample_template_create):
        """Test creating a new baseline template"""
        new_template = _make_template_mock(
            name=sample_template_create.name,
            description=sample_template_create.description,
            content=sample_template_create.content,
            template_type=sample_template_create.template_type,
            category=sample_template_create.category,
            variables=sample_template_create.variables,
            version=1,
            is_baseline=True,
        )

        # Mock _get_by_name to return None (no existing template)
        service = PromptTemplateService(mock_db)
        service._get_by_name = AsyncMock(return_value=None)

        # Mock db.add to capture the template
        captured = []
        def capture_add(obj):
            captured.append(obj)
        mock_db.add.side_effect = capture_add

        # Mock db.refresh to set attributes on the captured object
        def refresh(obj):
            obj.id = new_template.id
            obj.name = new_template.name
            obj.description = new_template.description
            obj.content = new_template.content
            obj.template_type = new_template.template_type
            obj.category = new_template.category
            obj.variables = new_template.variables
            obj.version = new_template.version
            obj.parent_id = new_template.parent_id
            obj.is_baseline = new_template.is_baseline
            obj.created_at = new_template.created_at
            obj.updated_at = new_template.updated_at
        mock_db.refresh.side_effect = refresh

        result = await service.create_template(sample_template_create)

        assert result is not None
        assert result.name == "New Template"
        assert result.version == 1
        assert result.is_baseline is True

    @pytest.mark.asyncio
    async def test_create_template_version(self, mock_db, sample_template):
        """Test creating a new version of a template"""
        service = PromptTemplateService(mock_db)

        # Mock _find_parent to return the sample_template id
        service._find_parent = MagicMock(return_value=sample_template.id)

        # Mock _get_by_id to return the parent template
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result

        # Set version on sample_template
        sample_template.version = 1

        # Create new version mock with proper datetime
        new_version = _make_template_mock(
            name=sample_template.name,
            version=2,
            parent_id=sample_template.id,
            is_baseline=False,
            content="Updated content",
        )

        def refresh(obj):
            obj.id = new_version.id
            obj.name = new_version.name
            obj.content = new_version.content
            obj.version = new_version.version
            obj.parent_id = new_version.parent_id
            obj.is_baseline = new_version.is_baseline
            obj.created_at = new_version.created_at
            obj.updated_at = new_version.updated_at
        mock_db.refresh.side_effect = refresh

        result = await service.create_template(PromptTemplateCreate(
            name=sample_template.name,
            content="Updated content",
            is_baseline=False,
            parent_id=sample_template.id,
        ))

        assert result is not None
        assert result.version == 2
        assert result.parent_id == sample_template.id
        assert result.is_baseline is False

    @pytest.mark.asyncio
    async def test_update_template(self, mock_db, sample_template, sample_template_update):
        """Test updating a template"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result

        # Set created_at and updated_at on sample_template
        now = datetime.now(timezone.utc)
        sample_template.created_at = now
        sample_template.updated_at = now

        service = PromptTemplateService(mock_db)
        updated = await service.update_template(sample_template.id, sample_template_update)

        assert updated is not None
        assert updated.name == "Updated Template"

    @pytest.mark.asyncio
    async def test_delete_template(self, mock_db, sample_template):
        """Test soft deleting a template"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result

        service = PromptTemplateService(mock_db)
        success = await service.delete_template(sample_template.id)

        assert success is True
        assert sample_template.is_deleted is True

    @pytest.mark.asyncio
    async def test_get_version_history(self, mock_db, sample_template):
        """Test getting version history"""
        # First query gets the root template
        root_result = MagicMock()
        root_result.scalar_one_or_none.return_value = sample_template

        # Second query gets child versions
        versions_result = MagicMock()
        versions_result.scalars.return_value.all.return_value = [sample_template]

        mock_db.execute.side_effect = [root_result, versions_result]

        service = PromptTemplateService(mock_db)
        history = await service.get_version_history(sample_template.id)

        assert history.total >= 1
        assert len(history.items) >= 1

    @pytest.mark.asyncio
    async def test_render_template(self, mock_db, sample_template):
        """Test rendering a template with variable substitution"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result

        service = PromptTemplateService(mock_db)
        rendered = await service.render_template(
            sample_template.id,
            {"name": "Alice", "place": "Wonderland"}
        )

        assert rendered is not None
        assert rendered.template_id == sample_template.id
        assert "Alice" in rendered.content
        assert "Wonderland" in rendered.content
        assert "{{name}}" not in rendered.content
        assert "{{place}}" not in rendered.content

    @pytest.mark.asyncio
    async def test_extract_variables(self, mock_db, sample_template):
        """Test extracting variables from template content"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result

        service = PromptTemplateService(mock_db)
        variables = await service.get_template_variables(sample_template.id)

        assert len(variables.variables) >= 2
        var_names = [v.name for v in variables.variables]
        assert "name" in var_names
        assert "place" in var_names

    @pytest.mark.asyncio
    async def test_compare_versions(self, mock_db, sample_template):
        """Test comparing two versions of a template"""
        # Create version 2 mock
        version2 = _make_template_mock(
            name=sample_template.name,
            version=2,
            content="Updated content with new features",
        )

        result = MagicMock()
        result.scalars.return_value.all.return_value = [sample_template, version2]
        mock_db.execute.return_value = result

        service = PromptTemplateService(mock_db)
        comparison = await service.compare_versions(
            sample_template.id,
            version1=1,
            version2=2,
        )

        assert comparison is not None
        assert comparison["version1"]["version"] == 1
        assert comparison["version2"]["version"] == 2
        assert "diff" in comparison

    @pytest.mark.asyncio
    async def test_variable_extraction_simple(self, mock_db):
        """Test variable extraction from simple template"""
        template = _make_template_mock(
            content="Hello {{name}}, your order {{order_id}} is ready.",
            variables=["name", "order_id"],
        )

        result = MagicMock()
        result.scalar_one_or_none.return_value = template
        mock_db.execute.return_value = result

        service = PromptTemplateService(mock_db)
        variables = await service.get_template_variables(template.id)

        assert len(variables.variables) == 2
        var_names = {v.name for v in variables.variables}
        assert var_names == {"name", "order_id"}

    @pytest.mark.asyncio
    async def test_variable_extraction_empty(self, mock_db):
        """Test variable extraction from template without variables"""
        template = _make_template_mock(
            content="This is a static message.",
            variables=[],
        )

        result = MagicMock()
        result.scalar_one_or_none.return_value = template
        mock_db.execute.return_value = result

        service = PromptTemplateService(mock_db)
        variables = await service.get_template_variables(template.id)

        assert len(variables.variables) == 0

    @pytest.mark.asyncio
    async def test_duplicate_name_baseline(self, mock_db, sample_template):
        """Test creating duplicate baseline updates existing"""
        service = PromptTemplateService(mock_db)
        
        # Mock _get_by_name to return existing template
        service._get_by_name = AsyncMock(return_value=sample_template)
        
        # Set created_at and updated_at
        now = datetime.now(timezone.utc)
        sample_template.created_at = now
        sample_template.updated_at = now

        # Create same name but different content
        result = await service.create_template(PromptTemplateCreate(
            name=sample_template.name,
            content="Different content",
            is_baseline=True,
        ))

        # Should update existing
        assert result.id == sample_template.id
        assert result.content == "Different content"
