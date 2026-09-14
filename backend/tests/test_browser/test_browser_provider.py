"""Tests for Browser Provider module"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.browser_provider import BrowserProvider
from app.providers.bitbrowser_provider import BitBrowserProvider
from app.schemas.browser import (
    BrowserProfileCreate,
    BrowserProfileUpdate,
    ProviderStatus,
    TestConnectionResponse,
)
from app.services.browser_service import BrowserService


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
def sample_profile():
    """Create a sample browser profile"""
    profile = MagicMock()
    profile.id = uuid4()
    profile.provider = "bitbrowser"
    profile.profile_id = "bitbrowser_001"
    profile.name = "Test Profile"
    profile.connection_status = "disconnected"
    profile.created_at = datetime.now(timezone.utc)
    profile.updated_at = datetime.now(timezone.utc)
    profile.is_deleted = False
    return profile


@pytest.fixture
def sample_profile_create():
    """Create a sample browser profile creation request"""
    return BrowserProfileCreate(
        provider="bitbrowser",
        profile_id="bitbrowser_001",
        name="New Profile",
        connection_status="disconnected",
    )


class TestBitBrowserProvider:
    """Test cases for BitBrowserProvider"""

    def test_provider_name(self):
        """Test provider name property"""
        provider = BitBrowserProvider()
        assert provider.provider_name == "bitbrowser"

    def test_is_mock_mode_when_sdk_not_available(self):
        """Test mock mode when SDK is not available"""
        with patch('app.providers.bitbrowser_provider.httpx') as mock_httpx:
            mock_httpx.get.side_effect = Exception("Connection refused")
            provider = BitBrowserProvider()
            assert provider.is_mock_mode() is True

    @pytest.mark.asyncio
    async def test_test_connection_mock_mode(self):
        """Test connection test in mock mode"""
        with patch('app.providers.bitbrowser_provider.httpx') as mock_httpx:
            mock_httpx.get.side_effect = Exception("Connection refused")
            provider = BitBrowserProvider()
            result = await provider.test_connection()
            
            assert result["connected"] is False
            assert result["status"] == "mock_mode"
            assert "BitBrowser SDK 未安装" in result["message"]

    @pytest.mark.asyncio
    async def test_list_profiles_mock_mode(self):
        """Test listing profiles in mock mode"""
        with patch('app.providers.bitbrowser_provider.httpx') as mock_httpx:
            mock_httpx.get.side_effect = Exception("Connection refused")
            provider = BitBrowserProvider()
            profiles = await provider.list_profiles()
            
            assert len(profiles) == 2  # Default mock profiles
            assert profiles[0]["name"] == "演示配置-微信"

    @pytest.mark.asyncio
    async def test_get_profile_mock_mode(self):
        """Test getting profile in mock mode"""
        with patch('app.providers.bitbrowser_provider.httpx') as mock_httpx:
            mock_httpx.get.side_effect = Exception("Connection refused")
            provider = BitBrowserProvider()
            profile = await provider.get_profile("mock_001")
            
            assert profile is not None
            assert profile["name"] == "演示配置-微信"

    @pytest.mark.asyncio
    async def test_get_profile_not_found_mock_mode(self):
        """Test getting non-existent profile in mock mode"""
        with patch('app.providers.bitbrowser_provider.httpx') as mock_httpx:
            mock_httpx.get.side_effect = Exception("Connection refused")
            provider = BitBrowserProvider()
            profile = await provider.get_profile("nonexistent")
            
            assert profile is None

    @pytest.mark.asyncio
    async def test_create_profile_mock_mode(self):
        """Test creating profile in mock mode"""
        with patch('app.providers.bitbrowser_provider.httpx') as mock_httpx:
            mock_httpx.get.side_effect = Exception("Connection refused")
            provider = BitBrowserProvider()
            profile = await provider.create_profile("New Test Profile")
            
            assert profile["name"] == "New Test Profile"
            assert "id" in profile
            assert "created_at" in profile

    @pytest.mark.asyncio
    async def test_delete_profile_mock_mode(self):
        """Test deleting profile in mock mode"""
        with patch('app.providers.bitbrowser_provider.httpx') as mock_httpx:
            mock_httpx.get.side_effect = Exception("Connection refused")
            provider = BitBrowserProvider()
            result = await provider.delete_profile("mock_001")
            
            assert result is True


class TestBrowserService:
    """Test cases for BrowserService"""

    @pytest.mark.asyncio
    async def test_list_providers(self, mock_db):
        """Test listing providers"""
        service = BrowserService(mock_db)
        providers = await service.list_providers()
        
        assert providers == ["bitbrowser"]
        assert len(providers) == 1

    @pytest.mark.asyncio
    async def test_get_provider_status_bitbrowser(self, mock_db):
        """Test getting provider status"""
        with patch('app.providers.bitbrowser_provider.BitBrowserProvider') as MockProvider:
            mock_provider = MagicMock()
            mock_provider.test_connection.return_value = {
                "connected": False,
                "provider": "bitbrowser",
                "status": "mock_mode",
                "message": "BitBrowser SDK 未安装，使用模拟模式",
                "endpoint": "http://127.0.0.1:1922",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            MockProvider.return_value = mock_provider
            
            service = BrowserService(mock_db)
            status = await service.get_provider_status("bitbrowser")
            
            assert status is not None
            assert status.provider == "bitbrowser"
            assert status.connected is False

    @pytest.mark.asyncio
    async def test_get_provider_status_unknown(self, mock_db):
        """Test getting unknown provider status"""
        service = BrowserService(mock_db)
        status = await service.get_provider_status("unknown")
        
        assert status is None

    @pytest.mark.asyncio
    async def test_test_connection(self, mock_db):
        """Test testing connection"""
        with patch('app.services.browser_service.BitBrowserProvider') as MockProvider:
            mock_provider = MagicMock()
            mock_provider.test_connection = AsyncMock(return_value={
                "connected": True,
                "provider": "bitbrowser",
                "status": "connected",
                "message": "BitBrowser 连接正常",
                "endpoint": "http://127.0.0.1:1922",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            MockProvider.return_value = mock_provider
            
            service = BrowserService(mock_db)
            result = await service.test_provider_connection("bitbrowser")
            
            assert result.success is True
            assert result.status == "connected"

    @pytest.mark.asyncio
    async def test_list_profiles_empty(self, mock_db):
        """Test listing profiles when empty"""
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []
        
        mock_db.execute.side_effect = [count_result, list_result]
        
        service = BrowserService(mock_db)
        profiles, total = await service.list_profiles()
        
        assert total == 0
        assert len(profiles) == 0

    @pytest.mark.asyncio
    async def test_get_profile_found(self, mock_db, sample_profile):
        """Test getting existing profile"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_profile
        mock_db.execute.return_value = result
        
        service = BrowserService(mock_db)
        profile = await service.get_profile(sample_profile.id)
        
        assert profile is not None
        assert profile.id == sample_profile.id
        assert profile.name == "Test Profile"

    @pytest.mark.asyncio
    async def test_get_profile_not_found(self, mock_db):
        """Test getting non-existent profile"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result
        
        service = BrowserService(mock_db)
        profile = await service.get_profile(uuid4())
        
        assert profile is None

    @pytest.mark.asyncio
    async def test_create_profile(self, mock_db, sample_profile_create):
        """Test creating a new profile"""
        mock_profile = MagicMock()
        mock_profile.id = uuid4()
        mock_profile.provider = "bitbrowser"
        mock_profile.profile_id = "bitbrowser_001"
        mock_profile.name = "New Profile"
        mock_profile.connection_status = "disconnected"
        mock_profile.created_at = datetime.now(timezone.utc)
        mock_profile.updated_at = datetime.now(timezone.utc)
        mock_profile.is_deleted = False
        
        async def mock_refresh(obj):
            obj.id = mock_profile.id
            obj.created_at = mock_profile.created_at
            obj.updated_at = mock_profile.updated_at
        
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=mock_refresh)
        
        service = BrowserService(mock_db)
        profile = await service.create_profile(sample_profile_create)
        
        assert profile is not None
        assert profile.provider == "bitbrowser"
        assert profile.name == "New Profile"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_profile(self, mock_db, sample_profile):
        """Test updating a profile"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_profile
        mock_db.execute.return_value = result
        mock_db.commit = AsyncMock()
        
        update_data = BrowserProfileUpdate(name="Updated Name")
        
        service = BrowserService(mock_db)
        updated = await service.update_profile(sample_profile.id, update_data)
        
        assert updated is not None
        assert updated.name == "Updated Name"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_profile_not_found(self, mock_db):
        """Test updating non-existent profile"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result
        
        service = BrowserService(mock_db)
        updated = await service.update_profile(uuid4(), BrowserProfileUpdate(name="Test"))
        
        assert updated is None

    @pytest.mark.asyncio
    async def test_delete_profile(self, mock_db, sample_profile):
        """Test deleting a profile"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_profile
        mock_db.execute.return_value = result
        mock_db.commit = AsyncMock()
        
        service = BrowserService(mock_db)
        success = await service.delete_profile(sample_profile.id)
        
        assert success is True
        assert sample_profile.is_deleted is True
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_profile_not_found(self, mock_db):
        """Test deleting non-existent profile"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result
        
        service = BrowserService(mock_db)
        success = await service.delete_profile(uuid4())
        
        assert success is False
