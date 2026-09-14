"""Tests for PromptTemplate API endpoints"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from app.schemas.prompt_template import PromptTemplateCreate, PromptTemplateUpdate


def _make_template_response(**kwargs):
    """Helper to create a template response mock with proper attribute setting"""
    now = datetime.now(timezone.utc)
    template = MagicMock()
    # Set actual values, not Mocks
    for key, value in kwargs.items():
        setattr(template, key, value)
    # Ensure required fields have real values
    template.id = kwargs.get('id', uuid4())
    template.name = kwargs.get('name', 'Test Template')
    template.description = kwargs.get('description', 'Test')
    template.content = kwargs.get('content', 'Hello {{name}}!')
    template.template_type = kwargs.get('template_type', 'custom')
    template.category = kwargs.get('category', None)
    template.variables = kwargs.get('variables', ['name'])
    template.version = kwargs.get('version', 1)
    template.parent_id = kwargs.get('parent_id', None)
    template.is_baseline = kwargs.get('is_baseline', True)
    template.created_at = kwargs.get('created_at', now)
    template.updated_at = kwargs.get('updated_at', now)
    return template


class TestPromptTemplateService:
    """Test cases for PromptTemplateService"""

    @pytest.mark.asyncio
    async def test_list_templates(self, mock_db):
        """Test listing templates"""
        from app.services.prompt_template_service import PromptTemplateService
        
        sample_template = _make_template_response()
        
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [sample_template]
        
        mock_db.execute.side_effect = [count_result, list_result]
        
        service = PromptTemplateService(mock_db)
        templates, total = await service.list_templates()
        
        assert total == 1
        assert len(templates) == 1
        assert templates[0].name == "Test Template"

    @pytest.mark.asyncio
    async def test_get_template_found(self, mock_db):
        """Test getting an existing template"""
        from app.services.prompt_template_service import PromptTemplateService
        
        sample_template = _make_template_response()
        
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result
        
        service = PromptTemplateService(mock_db)
        template = await service.get_template(sample_template.id)
        
        assert template is not None
        assert template.id == sample_template.id
        assert template.name == "Test Template"

    @pytest.mark.asyncio
    async def test_get_template_not_found(self, mock_db):
        """Test getting a non-existent template"""
        from app.services.prompt_template_service import PromptTemplateService
        
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result
        
        service = PromptTemplateService(mock_db)
        template = await service.get_template(uuid4())
        
        assert template is None

    @pytest.mark.asyncio
    async def test_create_template_baseline(self, mock_db):
        """Test creating a new baseline template"""
        from app.services.prompt_template_service import PromptTemplateService
        
        create_data = PromptTemplateCreate(
            name="New Template",
            content="Hello {{name}}!",
            template_type="greeting",
            is_baseline=True,
        )
        
        new_template = _make_template_response(
            name=create_data.name,
            content=create_data.content,
            version=1,
            is_baseline=True,
        )
        
        service = PromptTemplateService(mock_db)
        service._get_by_name = AsyncMock(return_value=None)
        
        # Mock db.add to capture the template
        captured = []
        def capture_add(obj):
            captured.append(obj)
        mock_db.add.side_effect = capture_add
        
        def refresh(obj):
            obj.id = new_template.id
            obj.name = new_template.name
            obj.content = new_template.content
            obj.version = new_template.version
            obj.is_baseline = new_template.is_baseline
            obj.created_at = new_template.created_at
            obj.updated_at = new_template.updated_at
        mock_db.refresh.side_effect = refresh
        
        result = await service.create_template(create_data)
        
        assert result is not None
        assert result.name == "New Template"
        assert result.version == 1
        assert result.is_baseline is True

    @pytest.mark.asyncio
    async def test_create_template_version(self, mock_db):
        """Test creating a new version of a template"""
        from app.services.prompt_template_service import PromptTemplateService
        
        sample_template = _make_template_response(version=1)
        
        service = PromptTemplateService(mock_db)
        service._find_parent = MagicMock(return_value=sample_template.id)
        
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result
        
        new_version = _make_template_response(
            name=sample_template.name,
            version=2,
            parent_id=sample_template.id,
            is_baseline=False,
        )
        
        def refresh(obj):
            obj.id = new_version.id
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
    async def test_update_template(self, mock_db):
        """Test updating a template"""
        from app.services.prompt_template_service import PromptTemplateService
        
        sample_template = _make_template_response()
        
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result
        
        service = PromptTemplateService(mock_db)
        updated = await service.update_template(
            sample_template.id,
            PromptTemplateUpdate(name="Updated Template")
        )
        
        assert updated is not None
        assert updated.name == "Updated Template"

    @pytest.mark.asyncio
    async def test_delete_template(self, mock_db):
        """Test soft deleting a template"""
        from app.services.prompt_template_service import PromptTemplateService
        
        sample_template = _make_template_response()
        
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result
        
        service = PromptTemplateService(mock_db)
        success = await service.delete_template(sample_template.id)
        
        assert success is True
        assert sample_template.is_deleted is True

    @pytest.mark.asyncio
    async def test_get_version_history(self, mock_db):
        """Test getting version history"""
        from app.services.prompt_template_service import PromptTemplateService
        
        sample_template = _make_template_response()
        
        root_result = MagicMock()
        root_result.scalar_one_or_none.return_value = sample_template
        
        versions_result = MagicMock()
        versions_result.scalars.return_value.all.return_value = [sample_template]
        
        mock_db.execute.side_effect = [root_result, versions_result]
        
        service = PromptTemplateService(mock_db)
        history = await service.get_version_history(sample_template.id)
        
        assert history.total >= 1
        assert len(history.items) >= 1

    @pytest.mark.asyncio
    async def test_render_template(self, mock_db):
        """Test rendering a template with variable substitution"""
        from app.services.prompt_template_service import PromptTemplateService
        
        sample_template = _make_template_response(
            content="Hello {{name}}, welcome!"
        )
        
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result
        
        service = PromptTemplateService(mock_db)
        rendered = await service.render_template(
            sample_template.id,
            {"name": "Alice"}
        )
        
        assert rendered is not None
        assert "Alice" in rendered.content
        assert "{{name}}" not in rendered.content

    @pytest.mark.asyncio
    async def test_extract_variables(self, mock_db):
        """Test extracting variables from template content"""
        from app.services.prompt_template_service import PromptTemplateService
        
        sample_template = _make_template_response(
            content="Hello {{name}}, your order {{order_id}} is ready.",
            variables=["name", "order_id"]
        )
        
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = result
        
        service = PromptTemplateService(mock_db)
        variables = await service.get_template_variables(sample_template.id)
        
        assert len(variables.variables) >= 2
        var_names = [v.name for v in variables.variables]
        assert "name" in var_names
        assert "order_id" in var_names


@pytest.fixture
def mock_db():
    """Create a mock database session"""
    from unittest.mock import AsyncMock
    from sqlalchemy.ext.asyncio import AsyncSession
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db
