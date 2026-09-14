"""
Tests for Tag Service - using mock DB pattern
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tag import Tag
from app.crm.services.tag import (
    get_tag,
    list_tags,
    create_tag,
    update_tag,
    delete_tag,
    add_tags_to_customer,
    add_tags_to_lead,
    remove_tag_from_customer,
    remove_tag_from_lead,
    get_tag_statistics,
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
def sample_tag():
    """Create a sample tag"""
    tag = Tag(
        id=uuid4(),
        name="VIP客户",
        color="#FF6B6B",
        description="高价值客户标签",
        parent_id=None,
        usage_count=10,
        created_at=datetime.now(timezone.utc),
    )
    return tag


class TestTagCRUD:
    """Tag CRUD 测试"""
    
    @pytest.mark.asyncio
    async def test_get_tag(self, mock_db, sample_tag):
        """获取标签"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_tag)
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await get_tag(mock_db, sample_tag.id)
        assert result is not None
        assert result["id"] == str(sample_tag.id)
        assert result["name"] == "VIP客户"
    
    @pytest.mark.asyncio
    async def test_get_tag_not_found(self, mock_db):
        """获取不存在的标签"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await get_tag(mock_db, uuid4())
        assert result is None
    
    @pytest.mark.asyncio
    async def test_list_tags(self, mock_db, sample_tag):
        """列出标签"""
        # Mock count query
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=1)
        
        # Mock list query
        list_result = MagicMock()
        list_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sample_tag])))
        
        mock_db.execute = AsyncMock(side_effect=[count_result, list_result])
        
        result = await list_tags(mock_db)
        assert result["total"] == 1
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "VIP客户"
    
    @pytest.mark.asyncio
    async def test_update_tag(self, mock_db, sample_tag):
        """更新标签"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_tag)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        updates = {"name": "重要客户", "color": "#FF0000"}
        result = await update_tag(mock_db, sample_tag.id, updates)
        assert result is not None
        assert result["name"] == "重要客户"
        assert result["color"] == "#FF0000"
    
    @pytest.mark.asyncio
    async def test_delete_tag(self, mock_db, sample_tag):
        """删除标签（软删除）"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=sample_tag)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await delete_tag(mock_db, sample_tag.id)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_delete_tag_not_found(self, mock_db):
        """删除不存在的标签"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await delete_tag(mock_db, uuid4())
        assert result is False


class TestTagAssociation:
    """标签关联测试"""
    
    @pytest.mark.asyncio
    async def test_add_tags_to_customer(self, mock_db):
        """为 customerId 添加标签"""
        from app.db.models.customer import Customer

        customer_id = uuid4()
        tag_ids = [uuid4(), uuid4()]

        # Mock customer check
        customer_result = MagicMock()
        customer_result.scalar_one_or_none = MagicMock(return_value=Customer(id=customer_id, name="Test"))

        # Mock tag check
        tags_scalars = MagicMock()
        tags_scalars.all.return_value = [Tag(id=tag_ids[0]), Tag(id=tag_ids[1])]
        tags_result = MagicMock()
        tags_result.scalars = MagicMock(return_value=tags_scalars)

        # Mock existing check (no existing associations -> both get inserted)
        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        write_result = MagicMock()

        # Service call sequence:
        # 1 customer check, 2 tag check, 3 existing(t1), 4 insert(t1),
        # 5 existing(t2), 6 insert(t2), 7 usage_count update
        mock_db.execute = AsyncMock(side_effect=[
            customer_result, tags_result,
            existing_result, write_result,
            existing_result, write_result,
            write_result,
        ])

        result = await add_tags_to_customer(mock_db, customer_id, tag_ids)
        assert result["customer_id"] == str(customer_id)
        assert result["inserted"] == 2
        assert result["already_existed"] == 0

    @pytest.mark.asyncio
    async def test_add_tags_to_lead(self, mock_db):
        """为 lead 添加标签"""
        from app.db.models.lead import Lead

        lead_id = uuid4()
        tag_ids = [uuid4(), uuid4()]

        # Mock lead check
        lead_result = MagicMock()
        lead_result.scalar_one_or_none = MagicMock(return_value=Lead(id=lead_id))

        # Mock tag check
        tags_scalars = MagicMock()
        tags_scalars.all.return_value = [Tag(id=tag_ids[0]), Tag(id=tag_ids[1])]
        tags_result = MagicMock()
        tags_result.scalars = MagicMock(return_value=tags_scalars)

        # Mock existing check (no existing associations -> both get inserted)
        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        write_result = MagicMock()

        # Service call sequence:
        # 1 lead check, 2 tag check, 3 existing(t1), 4 insert(t1),
        # 5 existing(t2), 6 insert(t2), 7 usage_count update
        mock_db.execute = AsyncMock(side_effect=[
            lead_result, tags_result,
            existing_result, write_result,
            existing_result, write_result,
            write_result,
        ])

        result = await add_tags_to_lead(mock_db, lead_id, tag_ids)
        assert result["lead_id"] == str(lead_id)
        assert result["inserted"] == 2
    
    @pytest.mark.asyncio
    async def test_remove_tag_from_customer(self, mock_db):
        """从 customerId 移除标签"""
        customer_id = uuid4()
        tag_id = uuid4()
        
        # Mock existing association check
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value={"tag_id": tag_id, "customer_id": customer_id})
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await remove_tag_from_customer(mock_db, customer_id, tag_id)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_remove_tag_from_lead(self, mock_db):
        """从 lead 移除标签"""
        lead_id = uuid4()
        tag_id = uuid4()
        
        # Mock existing association check
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value={"tag_id": tag_id, "lead_id": lead_id})
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await remove_tag_from_lead(mock_db, lead_id, tag_id)
        assert result is True


class TestTagStatistics:
    """标签统计测试"""
    
    @pytest.mark.asyncio
    async def test_get_statistics(self, mock_db):
        """获取标签统计"""
        # Mock total count
        total_result = MagicMock()
        total_result.scalar = MagicMock(return_value=10)
        
        # Mock root tags count
        root_result = MagicMock()
        root_result.scalar = MagicMock(return_value=6)
        
        # Mock top tags query
        top_scalars = MagicMock()
        top_scalars.all.return_value = [
            Tag(id=uuid4(), name="VIP", usage_count=100),
            Tag(id=uuid4(), name="新客", usage_count=50),
        ]
        top_result = MagicMock()
        top_result.scalars = MagicMock(return_value=top_scalars)

        # Mock recent tags query
        recent_scalars = MagicMock()
        recent_scalars.all.return_value = [
            Tag(id=uuid4(), name="最新标签", created_at=datetime.now(timezone.utc)),
        ]
        recent_result = MagicMock()
        recent_result.scalars = MagicMock(return_value=recent_scalars)

        mock_db.execute = AsyncMock(side_effect=[total_result, root_result, top_result, recent_result])
        
        result = await get_tag_statistics(mock_db)
        assert result["total_tags"] == 10
        assert result["root_tags"] == 6
        assert result["child_tags"] == 4
        assert len(result["top_tags"]) == 2


class TestValidationError:
    """错误验证测试"""
    
    @pytest.mark.asyncio
    async def test_create_tag_duplicate_name(self, mock_db):
        """创建重名标签"""
        from app.db.models.tag import Tag as TagModel
        
        tag_data = {
            "name": "重复标签",
            "color": "#FF0000",
        }

        # No parent_id in tag_data -> create_tag skips the parent check and
        # makes exactly ONE db.execute call: the name-uniqueness check.
        # That call must report an existing same-level tag.
        name_result = MagicMock()
        duplicate_tag = TagModel(id=uuid4(), name="重复标签")
        name_result.scalar_one_or_none = MagicMock(return_value=duplicate_tag)

        mock_db.execute = AsyncMock(return_value=name_result)

        with pytest.raises(ValueError, match="同层级下已存在同名标签"):
            await create_tag(mock_db, tag_data)
    
    @pytest.mark.asyncio
    async def test_create_tag_invalid_parent(self, mock_db):
        """创建标签时父标签不存在"""
        from app.db.models.tag import Tag as TagModel
        
        tag_data = {
            "name": "子标签",
            "parent_id": uuid4(),
        }
        
        # Mock parent check - not found
        parent_result = MagicMock()
        parent_result.scalar_one_or_none = MagicMock(return_value=None)
        
        mock_db.execute = AsyncMock(return_value=parent_result)
        
        with pytest.raises(ValueError, match="父标签 .* 不存在"):
            await create_tag(mock_db, tag_data)
