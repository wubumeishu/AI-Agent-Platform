"""Test persona router endpoints - structure tests only"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from app.services.persona_service import PersonaService
from app.routers.personas import router


@pytest.fixture
def mock_persona_service():
    """Create mock persona service"""
    service = MagicMock(spec=PersonaService)

    # Mock list_personas
    service.list_personas = AsyncMock(return_value=([], 0))

    # Mock get_persona
    persona = MagicMock()
    persona.id = uuid4()
    persona.name = "Test Persona"
    persona.description = "Test"
    persona.personality = {"trait": "value"}
    persona.version = 1
    persona.parent_id = None
    persona.created_at = datetime.now(timezone.utc)
    persona.updated_at = datetime.now(timezone.utc)

    service.get_persona = AsyncMock(return_value=persona)
    service.create_persona = AsyncMock(return_value=persona)
    service.update_persona = AsyncMock(return_value=persona)
    service.delete_persona = AsyncMock(return_value=True)
    service.get_version_history = AsyncMock(return_value=MagicMock(items=[], total=1))
    service.clone_persona = AsyncMock(return_value=persona)

    return service


class TestPersonaRouter:
    """Test cases for Persona router structure"""

    def test_router_prefix(self):
        """Test router has correct prefix"""
        assert router.prefix == "/personas"

    def test_router_tag(self):
        """Test router has correct tag"""
        assert "Personas" in router.tags

    def test_has_list_endpoint(self):
        """Test list endpoint exists"""
        # The router has prefix "/personas", so the path should be "/personas/"
        routes = [r for r in router.routes if hasattr(r, 'path') and r.path == "/personas/"]
        get_routes = [r for r in routes if 'GET' in r.methods]
        assert len(get_routes) >= 1

    def test_has_create_endpoint(self):
        """Test create endpoint exists"""
        routes = [r for r in router.routes if hasattr(r, 'path') and r.path == "/personas/"]
        post_routes = [r for r in routes if 'POST' in r.methods]
        assert len(post_routes) >= 1

    def test_has_get_by_id_endpoint(self):
        """Test get by ID endpoint exists"""
        routes = [r for r in router.routes if hasattr(r, 'path') and '/{persona_id}' in r.path]
        get_routes = [r for r in routes if 'GET' in r.methods and '/versions' not in r.path and '/clone' not in r.path]
        assert len(get_routes) == 1

    def test_has_update_endpoint(self):
        """Test update endpoint exists"""
        routes = [r for r in router.routes if hasattr(r, 'path') and '/{persona_id}' in r.path]
        put_routes = [r for r in routes if 'PUT' in r.methods]
        assert len(put_routes) == 1

    def test_has_delete_endpoint(self):
        """Test delete endpoint exists"""
        routes = [r for r in router.routes if hasattr(r, 'path') and '/{persona_id}' in r.path]
        delete_routes = [r for r in routes if 'DELETE' in r.methods and '/clone' not in r.path]
        assert len(delete_routes) == 1

    def test_has_versions_endpoint(self):
        """Test versions endpoint exists"""
        routes = [r for r in router.routes if hasattr(r, 'path') and '/{persona_id}/versions' in r.path]
        assert len(routes) == 1
        assert 'GET' in routes[0].methods

    def test_has_clone_endpoint(self):
        """Test clone endpoint exists"""
        routes = [r for r in router.routes if hasattr(r, 'path') and '/{persona_id}/clone' in r.path]
        assert len(routes) == 1
        assert 'POST' in routes[0].methods

    def test_total_endpoints(self):
        """Test we have exactly 7 endpoints"""
        endpoint_count = sum(1 for r in router.routes if hasattr(r, 'path'))
        assert endpoint_count == 7
