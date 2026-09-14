"""
API Tests for Tag Router
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, sentinel
from uuid import uuid4
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Create mock database session"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def test_health_check(client):
    """测试健康检查接口"""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_tags(client, mock_db):
    """测试列出标签接口"""
    from app.crm.services import list_tags as list_tags_service

    expected_data = {
        "total": 2,
        "skip": 0,
        "limit": 100,
        "data": [
            {
                "id": str(uuid4()),
                "name": "VIP客户",
                "color": "#FF6B6B",
                "description": "高价值客户",
                "parent_id": None,
                "usage_count": 10,
                "child_count": 1,
                "customer_count": 5,
                "lead_count": 3,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ],
    }

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.list_tags", new=AsyncMock(return_value=expected_data)):
            response = client.get("/api/v1/crm/tags")
            assert response.status_code == 200
            assert response.json()["total"] == 2
            assert len(response.json()["data"]) == 1


def test_get_tag(client, mock_db):
    """测试获取单个标签接口"""
    from app.crm.services import get_tag as get_tag_service

    expected_tag = {
        "id": str(uuid4()),
        "name": "VIP客户",
        "color": "#FF6B6B",
        "description": "高价值客户",
        "parent_id": None,
        "usage_count": 10,
        "children": [],
        "customer_count": 5,
        "lead_count": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.get_tag", new=AsyncMock(return_value=expected_tag)):
            response = client.get(f"/api/v1/crm/tags/{expected_tag['id']}")
            assert response.status_code == 200
            assert response.json()["name"] == "VIP客户"


def test_get_tag_not_found(client, mock_db):
    """测试获取不存在的标签"""
    from app.crm.services import get_tag as get_tag_service

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.get_tag", new=AsyncMock(return_value=None)):
            response = client.get(f"/api/v1/crm/tags/{uuid4()}")
            assert response.status_code == 404


def test_create_tag(client, mock_db):
    """测试创建标签接口"""
    from app.crm.services import create_tag as create_tag_service

    tag_data = {
        "name": "新客户",
        "color": "#9B59B6",
        "description": "最近添加的新客户",
    }

    expected_tag = {
        "id": str(uuid4()),
        "name": "新客户",
        "color": "#9B59B6",
        "description": "最近添加的新客户",
        "parent_id": None,
        "usage_count": 0,
        "children": [],
        "customer_count": 0,
        "lead_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.create_tag", new=AsyncMock(return_value=expected_tag)):
            response = client.post("/api/v1/crm/tags", json=tag_data)
            assert response.status_code == 201
            assert response.json()["name"] == "新客户"
            assert response.json()["usage_count"] == 0


def test_update_tag(client, mock_db):
    """测试更新标签接口"""
    from app.crm.services import update_tag as update_tag_service

    updates = {"name": "重要客户", "color": "#E74C3C"}

    expected_tag = {
        "id": str(uuid4()),
        "name": "重要客户",
        "color": "#E74C3C",
        "parent_id": None,
        "usage_count": 10,
        "children": [],
        "customer_count": 5,
        "lead_count": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.update_tag", new=AsyncMock(return_value=expected_tag)):
            response = client.put(f"/api/v1/crm/tags/{uuid4()}", json=updates)
            assert response.status_code == 200
            assert response.json()["name"] == "重要客户"


def test_delete_tag(client, mock_db):
    """测试删除标签接口"""
    from app.crm.services import delete_tag as delete_tag_service

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.delete_tag", new=AsyncMock(return_value=True)):
            response = client.delete(f"/api/v1/crm/tags/{uuid4()}")
            assert response.status_code == 204


def test_delete_tag_not_found(client, mock_db):
    """测试删除不存在的标签"""
    from app.crm.services import delete_tag as delete_tag_service

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.delete_tag", new=AsyncMock(return_value=False)):
            response = client.delete(f"/api/v1/crm/tags/{uuid4()}")
            assert response.status_code == 404


def test_get_tag_statistics(client, mock_db):
    """测试获取标签统计接口"""
    from app.crm.services import get_tag_statistics as stats_service

    expected_stats = {
        "total_tags": 10,
        "root_tags": 6,
        "child_tags": 4,
        "top_tags": [
            {"id": str(uuid4()), "name": "VIP", "usage_count": 100},
            {"id": str(uuid4()), "name": "新客", "usage_count": 50},
        ],
        "recent_tags": [],
    }

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.get_tag_statistics", new=AsyncMock(return_value=expected_stats)):
            response = client.get("/api/v1/crm/tags/statistics")
            assert response.status_code == 200
            assert response.json()["data"]["total_tags"] == 10


def test_add_tags_to_customer(client, mock_db):
    """测试为 customerId 批量添加标签"""
    from app.crm.services import add_tags_to_customer as add_service

    customer_id = uuid4()
    tag_ids = [str(uuid4()), str(uuid4())]

    expected_result = {
        "customer_id": str(customer_id),
        "tag_ids": tag_ids,
        "inserted": 2,
        "already_existed": 0,
    }

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.add_tags_to_customer", new=AsyncMock(return_value=expected_result)):
            response = client.post(
                f"/api/v1/crm/tags/customers/{customer_id}/tags?tag_ids={tag_ids[0]}&tag_ids={tag_ids[1]}"
            )
            assert response.status_code == 200
            assert response.json()["inserted"] == 2


def test_remove_tag_from_customer(client, mock_db):
    """测试从 customerId 移除标签"""
    from app.crm.services import remove_tag_from_customer as remove_service

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.remove_tag_from_customer", new=AsyncMock(return_value=True)):
            response = client.delete(f"/api/v1/crm/tags/customers/{uuid4()}/tags/{uuid4()}")
            assert response.status_code == 204


def test_remove_tag_not_found(client, mock_db):
    """测试移除不存在的标签关联"""
    from app.crm.services import remove_tag_from_customer as remove_service

    with patch("app.crm.routers.tag.get_db", return_value=mock_db):
        with patch("app.crm.services.tag.remove_tag_from_customer", new=AsyncMock(return_value=False)):
            response = client.delete(f"/api/v1/crm/tags/customers/{uuid4()}/tags/{uuid4()}")
            assert response.status_code == 404
