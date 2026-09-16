"""
Comprehensive tests for Content Library module:
- ContentItem CRUD with usage tracking
- Search and filtering
- Usage statistics
- Category management
- Tag management
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def sample_content_item():
    from app.db.models.private_domain import ContentItem
    item = ContentItem(
        account_id=uuid4(),
        channel_id=uuid4(),
        content_type="text",
        title="Welcome Email Template",
        summary="A warm welcome message",
        body="Hello and welcome to our platform!",
        tags=["onboarding", "welcome"],
        category="email",
        status="published",
        version=1,
        usage_count=5,
        last_used_at=datetime.now(timezone.utc),
    )
    item.id = uuid4()
    return item


@pytest.fixture
def content_create_data():
    from app.schemas.private_domain import ContentItemCreate
    return ContentItemCreate(
        account_id=uuid4(),
        content_type="text",
        title="Test Content",
        summary="Test summary",
        body="Test body content",
        tags=["test", "example"],
        category="general",
    )


class TestContentItemCRUD:
    """Test ContentItem CRUD operations with usage tracking"""
    
    async def test_create_content_item(self, mock_db, content_create_data):
        """Test creating a content item with default usage stats"""
        from app.services.private_domain import create_content_item
        
        # Mock the create flow
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        
        item = await create_content_item(mock_db, content_create_data)
        
        assert item is not None
        assert item["title"] == "Test Content"
        assert item["usage_count"] == 0
        assert item["last_used_at"] is None
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
    
    async def test_get_content_items_with_usage_stats(self, mock_db, sample_content_item):
        """Test getting content items includes usage stats"""
        from app.services.private_domain import get_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await get_content_items(mock_db, sample_content_item.account_id)
        
        assert result["total"] == 1
        assert result["items"][0]["usage_count"] == 5
        assert result["items"][0]["last_used_at"] is not None
        assert result["items"][0]["title"] == "Welcome Email Template"
    
    async def test_update_content_item_increments_version(self, mock_db, sample_content_item):
        """Test that updating content increments version"""
        from app.services.private_domain import update_content_item
        from app.schemas.private_domain import ContentItemUpdate
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_content_item
        mock_db.execute.return_value = mock_result
        
        update_data = ContentItemUpdate(title="Updated Title")
        result = await update_content_item(mock_db, sample_content_item.id, update_data)
        
        assert result is not None
        assert result["title"] == "Updated Title"
        # Version was incremented in the service
        assert result["version"] == 2
    
    async def test_delete_content_item_marks_deleted(self, mock_db, sample_content_item):
        """Test soft delete sets is_deleted=True and status=deleted"""
        from app.services.private_domain import delete_content_item
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_content_item
        mock_db.execute.return_value = mock_result
        
        success = await delete_content_item(mock_db, sample_content_item.id)
        
        assert success is True
        assert sample_content_item.is_deleted is True
        assert sample_content_item.status == "deleted"


class TestContentSearch:
    """Test content search and filtering functionality"""
    
    async def test_search_by_keyword(self, mock_db, sample_content_item):
        """Test searching by keyword in title"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db, 
            sample_content_item.account_id,
            keyword="welcome"
        )
        
        assert result["total"] == 1
        assert result["keywords"] == "welcome"
        assert result["items"][0]["title"] == "Welcome Email Template"
    
    async def test_filter_by_content_type(self, mock_db, sample_content_item):
        """Test filtering by content type"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            content_type="text"
        )
        
        assert result["total"] == 1
        assert result["items"][0]["content_type"] == "text"
    
    async def test_filter_by_category(self, mock_db, sample_content_item):
        """Test filtering by category"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            category="email"
        )
        
        assert result["total"] == 1
        assert result["items"][0]["category"] == "email"
    
    async def test_filter_by_status(self, mock_db, sample_content_item):
        """Test filtering by status"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            status="published"
        )
        
        assert result["total"] == 1
        assert result["items"][0]["status"] == "published"
    
    async def test_filter_by_tag(self, mock_db, sample_content_item):
        """Test filtering by tag"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            tag="onboarding"
        )
        
        assert result["total"] == 1
        assert "onboarding" in result["items"][0]["tags"]
    
    async def test_filter_by_usage_count_range(self, mock_db, sample_content_item):
        """Test filtering by usage count range"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        # Filter for items with at least 3 uses
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            min_usage_count=3
        )
        
        assert result["total"] == 1
    
    async def test_sort_by_usage_count_desc(self, mock_db, sample_content_item):
        """Test sorting by usage count descending"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            sort_by="usage_count",
            sort_order="desc"
        )
        
        assert result["total"] == 1
    
    async def test_pagination(self, mock_db, sample_content_item):
        """Test pagination works correctly"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            page=1,
            page_size=10
        )
        
        assert result["page"] == 1
        assert result["page_size"] == 10
        assert result["total"] == 1


class TestContentUsageTracking:
    """Test content usage tracking functionality"""
    
    async def test_track_content_usage(self, mock_db, sample_content_item):
        """Test incrementing usage count"""
        from app.services.content_library import track_content_usage
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_content_item
        mock_db.execute.return_value = mock_result
        
        result = await track_content_usage(mock_db, sample_content_item.id, sample_content_item.account_id)
        
        assert result is not None
        assert result["usage_count"] == 6  # 5 + 1
        assert result["last_used_at"] is not None
    
    async def test_track_usage_returns_none_for_deleted(self, mock_db):
        """Test that tracking usage on deleted content returns None"""
        from app.services.content_library import track_content_usage
        
        deleted_item = MagicMock()
        deleted_item.is_deleted = True
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        result = await track_content_usage(mock_db, uuid4(), uuid4())
        
        assert result is None


class TestContentStatistics:
    """Test content statistics functionality"""
    
    async def test_get_usage_stats(self, mock_db, sample_content_item):
        """Test getting usage statistics"""
        from app.services.content_library import get_content_usage_stats
        
        # Track call order and return appropriate results
        call_sequence = [
            ("content_query", None),  # First: get content items
            ("count_query", None),    # Second: count nurture plans
        ]
        call_index = [0]
        
        async def mock_execute(query):
            call_idx = call_index[0]
            call_index[0] += 1
            
            result = MagicMock()
            if call_idx == 0:
                # Content query - return the sample item
                result.scalars.return_value.all.return_value = [sample_content_item]
            elif call_idx == 1:
                # Count query for nurture plans
                result.scalar.return_value = 2
            else:
                result.scalar.return_value = 0
            return result
        
        mock_db.execute = mock_execute
        
        result = await get_content_usage_stats(mock_db, sample_content_item.account_id)
        
        assert "stats" in result
        assert len(result["stats"]) == 1
        assert result["stats"][0]["content_id"] == sample_content_item.id
        assert result["stats"][0]["usage_count"] == 5
        assert result["stats"][0]["used_in_plans"] == 2
    
    async def test_get_content_type_stats(self, mock_db, sample_content_item):
        """Test getting statistics grouped by content type"""
        from app.services.content_library import get_content_type_stats
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("text", 1, 5)]
        mock_db.execute.return_value = mock_result
        
        result = await get_content_type_stats(mock_db, sample_content_item.account_id)
        
        assert len(result) == 1
        assert result[0]["content_type"] == "text"
        assert result[0]["count"] == 1
        assert result[0]["total_usage"] == 5
    
    async def test_get_content_category_stats(self, mock_db, sample_content_item):
        """Test getting statistics grouped by category"""
        from app.services.content_library import get_content_category_stats
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("email", 1, 5)]
        mock_db.execute.return_value = mock_result
        
        result = await get_content_category_stats(mock_db, sample_content_item.account_id)
        
        assert len(result) == 1
        assert result[0]["category"] == "email"
        assert result[0]["count"] == 1
    
    async def test_get_content_categories(self, mock_db, sample_content_item):
        """Test getting unique categories"""
        from app.services.content_library import get_content_categories
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("email",), ("pdf",), ("html",)]
        mock_db.execute.return_value = mock_result
        
        categories = await get_content_categories(mock_db, sample_content_item.account_id)
        
        assert len(categories) == 3
        assert "email" in categories
        assert "pdf" in categories
    
    async def test_get_content_tags(self, mock_db, sample_content_item):
        """Test getting unique tags"""
        from app.services.content_library import get_content_tags
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [["onboarding", "welcome"], ["test"]]
        mock_db.execute.return_value = mock_result
        
        tags = await get_content_tags(mock_db, sample_content_item.account_id)
        
        assert len(tags) == 3
        assert "onboarding" in tags
        assert "welcome" in tags
        assert "test" in tags
    
    async def test_get_top_used_content(self, mock_db, sample_content_item):
        """Test getting top used content items"""
        from app.services.content_library import get_top_used_content
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_db.execute.return_value = mock_result
        
        result = await get_top_used_content(mock_db, sample_content_item.account_id, limit=10)
        
        assert len(result) == 1
        assert result[0]["usage_count"] == 5
        assert result[0]["title"] == "Welcome Email Template"
    
    async def test_get_content_by_category(self, mock_db, sample_content_item):
        """Test getting content filtered by category"""
        from app.services.content_library import get_content_by_category
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await get_content_by_category(mock_db, sample_content_item.account_id, "email")
        
        assert result["category"] == "email"
        assert result["total"] == 1
        assert len(result["items"]) == 1


class TestContentSearchAdvanced:
    """Test advanced search scenarios"""
    
    async def test_search_multiple_filters(self, mock_db, sample_content_item):
        """Test searching with multiple filters combined"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            keyword="welcome",
            content_type="text",
            status="published"
        )
        
        assert result["total"] == 1
        assert result["keywords"] == "welcome"
    
    async def test_empty_search_results(self, mock_db):
        """Test search with no results"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            uuid4(),
            keyword="nonexistent"
        )
        
        assert result["total"] == 0
        assert result["items"] == []
    
    async def test_date_range_filter(self, mock_db, sample_content_item):
        """Test filtering by date range"""
        from app.services.content_library import search_content_items
        from datetime import datetime, timedelta
        
        start_date = datetime.now(timezone.utc) - timedelta(days=7)
        end_date = datetime.now(timezone.utc)
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            date_from=start_date,
            date_to=end_date
        )
        
        assert result["total"] == 1
    
    async def test_max_usage_count_filter(self, mock_db, sample_content_item):
        """Test filtering by max usage count"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            max_usage_count=10
        )
        
        assert result["total"] == 1
    
    async def test_sort_by_title_ascending(self, mock_db, sample_content_item):
        """Test sorting by title ascending"""
        from app.services.content_library import search_content_items
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_content_item]
        mock_result.scalar.return_value = 1
        mock_db.execute.return_value = mock_result
        
        result = await search_content_items(
            mock_db,
            sample_content_item.account_id,
            sort_by="title",
            sort_order="asc"
        )
        
        assert result["total"] == 1
