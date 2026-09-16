"""
Platform Router Structure Tests
"""
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

from app.routers.platforms import router
from app.services.platform_service import PlatformService


@pytest.fixture
def mock_platform():
    """Create a mock platform object"""
    platform = MagicMock()
    platform.id = uuid4()
    platform.code = "wechat"
    platform.name = "微信"
    platform.capabilities = ["messaging", "friend_management"]
    platform.adapter_class = "platforms.wechat.WeChatAdapter"
    platform.config = {}
    platform.status = "active"
    platform.created_at = datetime.now(timezone.utc)
    return platform


class TestPlatformRouter:
    """Test cases for Platform router structure"""

    def test_router_prefix(self):
        """Test router has correct prefix"""
        assert router.prefix == "/platforms"

    def test_router_tag(self):
        """Test router has correct tag"""
        assert "Platforms" in router.tags

    def test_has_list_endpoint(self):
        """Test list endpoint exists"""
        # Check all routes for GET method on platforms path
        get_routes = [r for r in router.routes if hasattr(r, 'methods') and 'GET' in r.methods]
        assert len(get_routes) >= 1

    def test_has_create_endpoint(self):
        """Test create endpoint exists"""
        post_routes = [r for r in router.routes if hasattr(r, 'methods') and 'POST' in r.methods]
        assert len(post_routes) >= 1

    def test_has_get_by_id_endpoint(self):
        """Test get by ID endpoint exists"""
        routes = [r for r in router.routes if hasattr(r, 'path') and '/{platform_id}' in r.path]
        get_routes = [r for r in routes if 'GET' in r.methods and '/test' not in r.path]
        assert len(get_routes) == 1

    def test_has_update_endpoint(self):
        """Test update endpoint exists"""
        routes = [r for r in router.routes if hasattr(r, 'path') and '/{platform_id}' in r.path]
        put_routes = [r for r in routes if 'PUT' in r.methods]
        assert len(put_routes) == 1

    def test_has_delete_endpoint(self):
        """Test delete endpoint exists"""
        routes = [r for r in router.routes if hasattr(r, 'path') and '/{platform_id}' in r.path]
        delete_routes = [r for r in routes if 'DELETE' in r.methods]
        assert len(delete_routes) == 1

    def test_has_test_connection_endpoint(self):
        """Test test connection endpoint exists"""
        routes = [r for r in router.routes if hasattr(r, 'path') and '/{platform_id}/test' in r.path]
        post_routes = [r for r in routes if 'POST' in r.methods]
        assert len(post_routes) == 1


class TestPlatformService:
    """Test cases for Platform service methods"""

    def test_list_platforms_method_exists(self):
        """Test list_platforms method exists"""
        assert hasattr(PlatformService, 'list_platforms')

    def test_get_platform_method_exists(self):
        """Test get_platform method exists"""
        assert hasattr(PlatformService, 'get_platform')

    def test_create_platform_method_exists(self):
        """Test create_platform method exists"""
        assert hasattr(PlatformService, 'create_platform')

    def test_update_platform_method_exists(self):
        """Test update_platform method exists"""
        assert hasattr(PlatformService, 'update_platform')

    def test_delete_platform_method_exists(self):
        """Test delete_platform method exists"""
        assert hasattr(PlatformService, 'delete_platform')

    def test_test_connection_method_exists(self):
        """Test test_connection method exists"""
        assert hasattr(PlatformService, 'test_connection')

    def test_seed_default_platforms_exists(self):
        """Test seed function exists"""
        from app.services.platform_service import seed_default_platforms
        assert callable(seed_default_platforms)


class TestPlatformSchemas:
    """Test platform schema validation"""

    def test_platform_create_valid(self):
        """Test valid platform create data"""
        from app.schemas.platform import PlatformCreate
        data = PlatformCreate(
            code="test_platform",
            name="测试平台",
            capabilities=["test"],
        )
        assert data.code == "test_platform"
        assert data.name == "测试平台"

    def test_platform_create_missing_code(self):
        """Test validation: code is required"""
        from app.schemas.platform import PlatformCreate
        with pytest.raises(Exception):
            PlatformCreate(name="测试平台")

    def test_platform_create_invalid_code_length(self):
        """Test validation: code max length"""
        from app.schemas.platform import PlatformCreate
        with pytest.raises(Exception):
            PlatformCreate(code="a" * 51, name="测试平台")

    def test_platform_update_partial(self):
        """Test partial update"""
        from app.schemas.platform import PlatformUpdate
        update = PlatformUpdate(name="更新名称")
        assert update.name == "更新名称"
        assert update.capabilities is None

    def test_test_connection_response_model(self):
        """Test test connection response model"""
        from app.schemas.platform import TestConnectionResponse
        response = TestConnectionResponse(
            success=True,
            message="Connected",
            status="connected",
            platform_code="wechat",
            timestamp=datetime.now(timezone.utc),
        )
        assert response.success is True


class TestPlatformIntegration:
    """Integration tests for Platform module"""

    def test_router_registration(self):
        """Test router is properly structured"""
        endpoint_count = len([r for r in router.routes if hasattr(r, 'path')])
        assert endpoint_count == 6  # list, create, get, update, delete, test

    def test_service_dependencies(self):
        """Test service has proper dependencies"""
        from unittest.mock import AsyncMock
        mock_db = AsyncMock()
        service = PlatformService(mock_db)
        assert service.db == mock_db
