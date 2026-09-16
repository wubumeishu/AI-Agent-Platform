"""
Tests for Customer Service - using mock DB pattern
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.customer import Customer
from app.db.models.customer_identity import CustomerIdentity
from app.crm.services.customer import (
    get_customer,
    list_customers,
    create_customer,
    update_customer,
    delete_customer,
    add_customer_identity,
    list_customer_identities,
    get_customer_identity,
    update_customer_identity,
    delete_customer_identity,
    resolve_customer_by_phone,
    resolve_customer_by_email,
    merge_customers,
)


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
def sample_customer():
    """Create a sample customer"""
    customer = Customer(
        id=uuid4(),
        name="Test Customer",
        email="test@example.com",
        phone="13800138000",
        company="Test Company",
    )
    return customer


@pytest.fixture
def sample_identity():
    """Create a sample identity"""
    identity = CustomerIdentity(
        id=uuid4(),
        customer_id=uuid4(),
        platform="wechat",
        platform_account_id="openid_123",
        platform_username="测试用户",
        phone="13800138000",
        email="test@example.com",
    )
    return identity


class TestCustomerCRUD:
    """Customer CRUD 测试"""
    
    @pytest.mark.asyncio
    async def test_create_customer(self, mock_db):
        """创建客户"""
        customer_data = {
            "name": "New Customer",
            "email": "new@example.com",
            "phone": "13900139000",
        }

        # Mock refresh to set ID and timestamps
        async def refresh(obj):
            obj.id = uuid4()
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
            # Set attributes from customer_data
            obj.name = customer_data.get("name", obj.name)
            obj.email = customer_data.get("email", obj.email)
            obj.phone = customer_data.get("phone", obj.phone)

        mock_db.refresh = AsyncMock(side_effect=refresh)
        mock_db.add = MagicMock()

        # Mock the get_customer call - return a properly constructed result
        new_id = uuid4()
        mock_result = MagicMock()
        mock_customer = MagicMock()
        mock_customer.id = new_id
        mock_customer.name = "New Customer"
        mock_customer.email = "new@example.com"
        mock_customer.phone = "13900139000"
        mock_customer.company = None
        mock_customer.avatar_url = None
        mock_customer.extra_info = {}
        mock_customer.identities = []
        mock_customer.tags = []
        mock_customer.created_at = datetime.now(timezone.utc)
        mock_customer.updated_at = datetime.now(timezone.utc)
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_customer)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await create_customer(mock_db, customer_data)
        assert result["name"] == "New Customer"
        assert result["email"] == "new@example.com"
        assert result["id"] == str(new_id)
    
    @pytest.mark.asyncio
    async def test_get_customer(self, mock_db, sample_customer):
        """获取客户"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_customer)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await get_customer(mock_db, sample_customer.id)
        assert result is not None
        assert result["id"] == str(sample_customer.id)
        assert result["name"] == "Test Customer"
    
    @pytest.mark.asyncio
    async def test_list_customers(self, mock_db, sample_customer):
        """列出客户"""
        # Mock count query
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=1)
        
        # Mock list query
        list_result = MagicMock()
        list_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sample_customer])))
        
        mock_db.execute = AsyncMock(side_effect=[count_result, list_result])
        
        result = await list_customers(mock_db)
        assert result["total"] == 1
        assert len(result["data"]) == 1
    
    @pytest.mark.asyncio
    async def test_update_customer(self, mock_db, sample_customer):
        """更新客户"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_customer)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        updates = {"name": "Updated Name", "company": "Updated Company"}
        result = await update_customer(mock_db, sample_customer.id, updates)
        assert result["name"] == "Updated Name"
        assert result["company"] == "Updated Company"
    
    @pytest.mark.asyncio
    async def test_delete_customer(self, mock_db, sample_customer):
        """删除客户（软删除）"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_customer)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await delete_customer(mock_db, sample_customer.id)
        assert result is True


class TestCustomerIdentity:
    """CustomerIdentity 测试"""
    
    @pytest.mark.asyncio
    async def test_add_identity(self, mock_db, sample_customer):
        """添加身份"""
        # Mock customer check
        customer_result = MagicMock()
        customer_result.scalar_one_or_none = MagicMock(return_value=sample_customer)

        # Mock identity uniqueness check
        identity_result = MagicMock()
        identity_result.scalar_one_or_none = MagicMock(return_value=None)

        # Mock get_customer_identity call
        get_result = MagicMock()
        get_result.scalar_one_or_none = MagicMock(return_value=sample_customer)

        # Create a mock identity for the final get call
        new_identity = CustomerIdentity(
            id=uuid4(),
            customer_id=sample_customer.id,
            platform="douyin",
            platform_account_id="douyin_123",
            platform_username="抖音用户",
            phone="13800138000",
        )
        identity_get_result = MagicMock()
        identity_get_result.scalar_one_or_none = MagicMock(return_value=new_identity)

        mock_db.execute = AsyncMock(
            side_effect=[customer_result, identity_result, identity_get_result]
        )

        # Mock refresh
        async def refresh(obj):
            obj.id = uuid4()
            obj.created_at = datetime.now(timezone.utc)

        mock_db.refresh = AsyncMock(side_effect=refresh)

        identity_data = {
            "platform": "douyin",
            "platform_account_id": "douyin_123",
            "platform_username": "抖音用户",
            "phone": "13800138000",
        }
        result = await add_customer_identity(mock_db, sample_customer.id, identity_data)
        assert result["platform"] == "douyin"
        assert result["id"] is not None
    
    @pytest.mark.asyncio
    async def test_list_identities(self, mock_db, sample_identity):
        """列出身份"""
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sample_identity])))
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await list_customer_identities(mock_db, sample_identity.customer_id)
        assert len(result) == 1
        assert result[0]["platform"] == "wechat"
    
    @pytest.mark.asyncio
    async def test_get_identity(self, mock_db, sample_identity):
        """获取身份"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_identity)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await get_customer_identity(mock_db, sample_identity.id)
        assert result is not None
        assert result["id"] == str(sample_identity.id)
    
    @pytest.mark.asyncio
    async def test_update_identity(self, mock_db, sample_identity):
        """更新身份"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_identity)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        updates = {"phone": "13900139000"}
        result = await update_customer_identity(mock_db, sample_identity.id, updates)
        assert result["phone"] == "13900139000"
    
    @pytest.mark.asyncio
    async def test_delete_identity(self, mock_db, sample_identity):
        """删除身份（软删除）"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_identity)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await delete_customer_identity(mock_db, sample_identity.id)
        assert result is True


class TestIdentityResolution:
    """身份解析测试"""
    
    @pytest.mark.asyncio
    async def test_resolve_by_phone(self, mock_db, sample_identity):
        """通过手机号解析"""
        # Mock identity query
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_identity)
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock get_customer call for the nested call in resolve
        customer_result = MagicMock()
        customer_result.scalar_one_or_none = MagicMock(return_value=sample_identity.customer if hasattr(sample_identity, 'customer') and sample_identity.customer else None)
        # Need to provide a proper customer
        mock_customer = Customer(id=sample_identity.customer_id, name="Test Customer")
        customer_result = MagicMock()
        customer_result.scalar_one_or_none = MagicMock(return_value=mock_customer)
        mock_db.execute = AsyncMock(side_effect=[mock_result, customer_result])

        result = await resolve_customer_by_phone(mock_db, "13800138000")
        assert result is not None
        assert result["matched_identity"]["phone"] == "13800138000"
    
    @pytest.mark.asyncio
    async def test_merge_customers(self, mock_db):
        """合并客户"""
        c1 = Customer(id=uuid4(), name="Customer 1", phone="13800138001")
        c2 = Customer(id=uuid4(), name="Customer 2", phone="13800138002")
        
        # Mock customer checks
        result1 = MagicMock()
        result1.scalar_one_or_none = MagicMock(return_value=c1)
        result2 = MagicMock()
        result2.scalar_one_or_none = MagicMock(return_value=c2)
        
        # Mock identities query
        id_result = MagicMock()
        id_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        
        mock_db.execute = AsyncMock(side_effect=[result1, result2, id_result])
        
        result = await merge_customers(mock_db, c1.id, c2.id)
        assert result["migrated_identities"] == 0


class TestPagination:
    """分页测试"""
    
    @pytest.mark.asyncio
    async def test_pagination(self, mock_db):
        """测试分页"""
        customers = [Customer(id=uuid4(), name=f"Customer {i}") for i in range(5)]
        
        # Mock count query
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=5)
        
        # Mock list query with pagination
        list_result = MagicMock()
        list_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=customers[:2])))
        
        mock_db.execute = AsyncMock(side_effect=[count_result, list_result])
        
        result = await list_customers(mock_db, skip=0, limit=2)
        assert result["total"] == 5
        assert len(result["data"]) == 2
