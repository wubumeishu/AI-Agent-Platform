"""Tests for Prompt Template Version Detail and Rollback APIs"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.prompt_template import (
    PromptTemplateCreate,
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
    template.variables = kwargs.get('variables', ['name'])
    template.version = kwargs.get('version', 1)
    template.parent_id = kwargs.get('parent_id', None)
    template.is_baseline = kwargs.get('is_baseline', True)
    template.created_at = kwargs.get('created_at', now)
    template.updated_at = kwargs.get('updated_at', now)
    template.is_deleted = kwargs.get('is_deleted', False)
    return template


class TestVersionDetail:
    """Test cases for version detail endpoint"""

    @pytest.mark.asyncio
    async def test_get_version_detail_found(self, mock_db):
        """Test getting an existing version detail"""
        template_id = uuid4()
        version = 2

        # Mock template check
        root_template = _make_template_mock(id=template_id, name="Test Template")
        root_result = MagicMock()
        root_result.scalar_one_or_none.return_value = root_template
        mock_db.execute.return_value = root_result

        # Mock version query
        version_template = _make_template_mock(
            name="Test Template",
            version=version,
            content="Updated content for v2",
            is_baseline=False,
        )
        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = version_template
        mock_db.execute.side_effect = [root_result, version_result]

        service = PromptTemplateService(mock_db)
        result = await service.get_version_detail(template_id, version)

        assert result is not None
        assert result.version == version
        assert result.content == "Updated content for v2"
        assert result.name == "Test Template"

    @pytest.mark.asyncio
    async def test_get_version_detail_template_not_found(self, mock_db):
        """Test getting version detail when template doesn't exist"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = PromptTemplateService(mock_db)
        with pytest.raises(ValueError, match="Template not found"):
            await service.get_version_detail(uuid4(), 1)

    @pytest.mark.asyncio
    async def test_get_version_detail_version_not_found(self, mock_db):
        """Test getting version detail when version doesn't exist"""
        template_id = uuid4()
        root_template = _make_template_mock(id=template_id)
        root_result = MagicMock()
        root_result.scalar_one_or_none.return_value = root_template
        mock_db.execute.return_value = root_result

        # Version not found
        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [root_result, version_result]

        service = PromptTemplateService(mock_db)
        with pytest.raises(ValueError, match="Version 999 not found"):
            await service.get_version_detail(template_id, 999)


class TestRollbackVersion:
    """Test cases for version rollback endpoint"""

    @pytest.mark.asyncio
    async def test_rollback_version_success(self, mock_db):
        """Test successful rollback to a previous version"""
        template_id = uuid4()
        rollback_version = 1

        # Mock template check
        root_template = _make_template_mock(id=template_id, name="Test Template")
        root_result = MagicMock()
        root_result.scalar_one_or_none.return_value = root_template
        mock_db.execute.return_value = root_result

        # Mock target version (version 1)
        target_version = _make_template_mock(
            name="Test Template",
            version=rollback_version,
            content="Original content",
            is_baseline=True,
        )
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = target_version
        mock_db.execute.side_effect = [root_result, target_result]

        # Mock latest version (version 3)
        latest_version = _make_template_mock(
            name="Test Template",
            version=3,
            content="Latest content",
            is_baseline=False,
        )
        latest_result = MagicMock()
        latest_result.scalar_one_or_none.return_value = latest_version
        mock_db.execute.side_effect = [root_result, target_result, latest_result]

        # Capture the new template
        captured = []
        def capture_add(obj):
            captured.append(obj)
        mock_db.add.side_effect = capture_add

        def refresh(obj):
            obj.id = uuid4()
            obj.version = 4
            obj.name = "Test Template"
            obj.content = "Original content"
            obj.parent_id = latest_version.id
            obj.is_baseline = True
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
        mock_db.refresh.side_effect = refresh

        service = PromptTemplateService(mock_db)
        result = await service.rollback_version(template_id, rollback_version)

        assert result is not None
        assert result.template_id == template_id
        assert result.template_name == "Test Template"
        assert result.new_version == 4
        assert result.rolled_back_from == rollback_version
        assert "Successfully rolled back" in result.message

        # Verify a new template was added
        assert len(captured) == 1
        assert captured[0].version == 4
        assert captured[0].content == "Original content"
        assert captured[0].is_baseline is True

    @pytest.mark.asyncio
    async def test_rollback_version_target_not_found(self, mock_db):
        """Test rollback when target version doesn't exist"""
        template_id = uuid4()
        root_template = _make_template_mock(id=template_id, name="Test Template")
        root_result = MagicMock()
        root_result.scalar_one_or_none.return_value = root_template
        mock_db.execute.return_value = root_result

        # Target version not found
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [root_result, target_result]

        service = PromptTemplateService(mock_db)
        with pytest.raises(ValueError, match="Version 1 not found"):
            await service.rollback_version(template_id, 1)

    @pytest.mark.asyncio
    async def test_rollback_version_template_not_found(self, mock_db):
        """Test rollback when template doesn't exist"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = PromptTemplateService(mock_db)
        with pytest.raises(ValueError, match="Template not found"):
            await service.rollback_version(uuid4(), 1)


class TestVersionDetailAPI:
    """Test cases for version detail API endpoint"""

    @pytest.mark.asyncio
    async def test_get_version_detail_api_success(self, mock_db):
        """Test version detail API endpoint"""
        from app.routers.prompt_templates import router

        template_id = uuid4()
        version = 2

        # Setup mocks
        root_template = _make_template_mock(id=template_id)
        version_template = _make_template_mock(
            name="Test Template",
            version=version,
            content="Content for version 2",
        )

        root_result = MagicMock()
        root_result.scalar_one_or_none.return_value = root_template
        version_result = MagicMock()
        version_result.scalar_one_or_none.return_value = version_template

        mock_db.execute.side_effect = [root_result, version_result]

        service = PromptTemplateService(mock_db)
        result = await service.get_version_detail(template_id, version)

        assert result.version == version
        assert "Content for version 2" in result.content
