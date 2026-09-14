"""Tests for Account module - simplified to avoid circular imports"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.account import (
    AccountCreate,
    AccountUpdate,
    AgentBindingCreate,
    BrowserBindingCreate,
    ProxyBindingCreate,
)
from app.services.account_service import AccountService


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
def sample_account():
    """Create a sample account for testing"""
    account = MagicMock()
    account.id = uuid4()
    account.platform_id = "wechat"
    account.name = "Test Account"
    account.username = "test_user"
    account.password_encrypted = "encrypted_password"
    account.status = "connected"
    account.last_login = datetime.now(timezone.utc)
    account.created_at = datetime.now(timezone.utc)
    account.updated_at = datetime.now(timezone.utc)
    account.is_deleted = False
    return account


@pytest.fixture
def sample_account_create():
    """Create a sample account creation request"""
    return AccountCreate(
        platform_id="wechat",
        name="New Account",
        username="new_user",
        password_encrypted="new_password",
    )


@pytest.fixture
def sample_account_update():
    """Create a sample account update request"""
    return AccountUpdate(
        name="Updated Account",
        status="disconnected",
    )


class TestAccountService:
    """Test cases for AccountService"""

    @pytest.mark.asyncio
    async def test_list_accounts(self, mock_db, sample_account):
        """Test listing accounts"""
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [sample_account]
        
        mock_db.execute.side_effect = [count_result, list_result]

        service = AccountService(mock_db)
        accounts, total = await service.list_accounts()

        assert total == 1
        assert len(accounts) == 1
        assert accounts[0].name == "Test Account"
        assert accounts[0].platform_id == "wechat"

    @pytest.mark.asyncio
    async def test_get_account_found(self, mock_db, sample_account):
        """Test getting an existing account"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_account
        mock_db.execute.return_value = result

        service = AccountService(mock_db)
        account = await service.get_account(sample_account.id)

        assert account is not None
        assert account.id == sample_account.id
        assert account.name == "Test Account"

    @pytest.mark.asyncio
    async def test_get_account_not_found(self, mock_db):
        """Test getting a non-existent account"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = AccountService(mock_db)
        account = await service.get_account(uuid4())

        assert account is None

    @pytest.mark.asyncio
    async def test_create_account(self, mock_db, sample_account_create):
        """Test creating a new account"""
        # Create a proper mock that simulates the Account model after refresh
        mock_account = MagicMock()
        mock_account.id = uuid4()
        mock_account.platform_id = "wechat"
        mock_account.name = "New Account"
        mock_account.username = "new_user"
        mock_account.password_encrypted = "new_password"
        mock_account.status = "disconnected"
        mock_account.last_login = None
        mock_account.created_at = datetime.now(timezone.utc)
        mock_account.updated_at = datetime.now(timezone.utc)
        mock_account.is_deleted = False
        
        # Configure mock_db to return our mock account after refresh
        async def mock_refresh(obj):
            obj.id = mock_account.id
            obj.created_at = mock_account.created_at
            obj.updated_at = mock_account.updated_at
        
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=mock_refresh)
        
        service = AccountService(mock_db)
        account = await service.create_account(sample_account_create)

        assert account is not None
        assert account.platform_id == "wechat"
        assert account.name == "New Account"
        assert account.username == "new_user"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_account(self, mock_db, sample_account, sample_account_update):
        """Test updating an account"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_account
        mock_db.execute.return_value = result
        mock_db.commit = AsyncMock()

        service = AccountService(mock_db)
        updated = await service.update_account(sample_account.id, sample_account_update)

        assert updated is not None
        assert updated.name == "Updated Account"
        assert updated.status == "disconnected"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_account_not_found(self, mock_db, sample_account_update):
        """Test updating a non-existent account"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = AccountService(mock_db)
        updated = await service.update_account(uuid4(), sample_account_update)

        assert updated is None

    @pytest.mark.asyncio
    async def test_delete_account(self, mock_db, sample_account):
        """Test soft deleting an account"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_account
        mock_db.execute.return_value = result
        mock_db.commit = AsyncMock()

        service = AccountService(mock_db)
        success = await service.delete_account(sample_account.id)

        assert success is True
        assert sample_account.is_deleted is True
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_account_not_found(self, mock_db):
        """Test deleting a non-existent account"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = AccountService(mock_db)
        success = await service.delete_account(uuid4())

        assert success is False

    @pytest.mark.asyncio
    async def test_test_connection_success(self, mock_db, sample_account):
        """Test connection test (mock success)"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_account
        mock_db.execute.return_value = result
        mock_db.commit = AsyncMock()

        service = AccountService(mock_db)
        response = await service.test_connection(sample_account.id)

        assert response.success is True
        assert response.status == "connected"
        assert response.message == "Connection test successful (mock)"

    @pytest.mark.asyncio
    async def test_test_connection_not_found(self, mock_db):
        """Test connection test for non-existent account"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        service = AccountService(mock_db)
        response = await service.test_connection(uuid4())

        assert response.success is False
        assert response.status == "not_found"


class TestAgentBindingService:
    """Test cases for Agent binding management"""

    @pytest.mark.asyncio
    async def test_list_agent_bindings(self, mock_db, sample_account):
        """Test listing agent bindings"""
        binding = MagicMock()
        binding.account_id = sample_account.id
        binding.agent_id = uuid4()
        binding.persona_id = uuid4()
        binding.is_primary = True
        binding.bound_at = datetime.now(timezone.utc)

        result = MagicMock()
        result.scalars.return_value.all.return_value = [binding]
        mock_db.execute.return_value = result

        service = AccountService(mock_db)
        bindings = await service.list_agent_bindings(sample_account.id)

        assert len(bindings) == 1
        assert bindings[0].is_primary is True
        assert bindings[0].account_id == sample_account.id

    @pytest.mark.asyncio
    async def test_create_agent_binding(self, mock_db, sample_account):
        """Test creating agent binding"""
        create_data = AgentBindingCreate(
            agent_id=uuid4(),
            persona_id=uuid4(),
            is_primary=True,
        )
        
        # Mock refresh to set bound_at
        async def mock_refresh(obj):
            obj.bound_at = datetime.now(timezone.utc)
        
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=mock_refresh)
        
        service = AccountService(mock_db)
        result = await service.create_agent_binding(sample_account.id, create_data)

        assert result is not None
        assert result.account_id == sample_account.id
        assert result.agent_id == create_data.agent_id
        assert result.persona_id == create_data.persona_id
        assert result.is_primary is True
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_agent_binding(self, mock_db, sample_account):
        """Test deleting agent binding"""
        binding = MagicMock()
        binding.id = uuid4()
        binding.account_id = sample_account.id
        binding.agent_id = uuid4()
        binding.persona_id = uuid4()
        
        result = MagicMock()
        result.scalar_one_or_none.return_value = binding
        mock_db.execute.return_value = result
        mock_db.commit = AsyncMock()
        mock_db.delete = AsyncMock()

        service = AccountService(mock_db)
        success = await service.delete_agent_binding(
            sample_account.id,
            binding.agent_id,
            binding.persona_id,
        )

        assert success is True
        mock_db.delete.assert_called_once()


class TestBrowserBindingService:
    """Test cases for Browser binding management"""

    @pytest.mark.asyncio
    async def test_create_browser_binding(self, mock_db, sample_account):
        """Test creating browser binding"""
        create_data = BrowserBindingCreate(
            profile_id=uuid4(),
        )
        
        # Mock refresh to set bound_at
        async def mock_refresh(obj):
            obj.bound_at = datetime.now(timezone.utc)
        
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=mock_refresh)
        
        service = AccountService(mock_db)
        result = await service.create_browser_binding(sample_account.id, create_data)

        assert result is not None
        assert result.account_id == sample_account.id
        assert result.profile_id == create_data.profile_id
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()


class TestProxyBindingService:
    """Test cases for Proxy binding management"""

    @pytest.mark.asyncio
    async def test_create_proxy_binding(self, mock_db, sample_account):
        """Test creating proxy binding"""
        create_data = ProxyBindingCreate(
            proxy_id=uuid4(),
        )
        
        # Mock refresh to set bound_at
        async def mock_refresh(obj):
            obj.bound_at = datetime.now(timezone.utc)
        
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=mock_refresh)
        
        service = AccountService(mock_db)
        result = await service.create_proxy_binding(sample_account.id, create_data)

        assert result is not None
        assert result.account_id == sample_account.id
        assert result.proxy_id == create_data.proxy_id
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
