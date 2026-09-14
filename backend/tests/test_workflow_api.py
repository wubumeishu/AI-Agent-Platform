"""API tests for the Workflow configuration router (t_wf_002).

Service behavior is injected through ``app.dependency_overrides`` (the
standard FastAPI override mechanism; patching the module attribute would
not affect already-registered routes).

The tests mount ONLY the workflow_config router on a minimal FastAPI app
so they are isolated from unrelated global router imports (and stay fast).
"""
import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.workflow_config import router as workflow_config_router, get_workflow_service


@pytest.fixture(scope="module")
def app():
    """Minimal app carrying just the workflow configuration router."""
    a = FastAPI(title="workflow-config-test")
    a.include_router(workflow_config_router, prefix="/api/v1")
    return a


@pytest.fixture
def client(app):
    return TestClient(app)


def mock_service(**methods) -> MagicMock:
    """A MagicMock standing in for WorkflowService with named method mocks."""
    svc = MagicMock()
    for name, value in methods.items():
        setattr(svc, name, value)
    return svc


def override(client, svc):
    """Register a dependency override on the app behind the TestClient."""
    client.app.dependency_overrides[get_workflow_service] = lambda: svc


@pytest.fixture(autouse=True)
def _clear_overrides(client):
    yield
    client.app.dependency_overrides.pop(get_workflow_service, None)


def _wf_dict(over=None):
    d = {
        "id": str(uuid4()), "name": "WF", "description": None,
        "workflow_type": "auto", "status": "draft",
        "config": {}, "execution_policy": {}, "version": 1,
        "created_at": "2026-09-14T00:00:00Z", "updated_at": "2026-09-14T00:00:00Z",
        "is_deleted": False,
    }
    d.update(over or {})
    return d


def _trig_dict(wf_id, **over):
    d = {
        "id": str(uuid4()), "workflow_id": str(wf_id), "name": None,
        "trigger_type": "manual", "spec": {}, "enabled": True,
        "created_at": "2026-09-14T00:00:00Z", "updated_at": "2026-09-14T00:00:00Z",
    }
    d.update(over)
    return d


def _cond_dict(trig_id, **over):
    d = {
        "id": str(uuid4()), "trigger_id": str(trig_id), "name": None,
        "expression": {"field": "x", "operator": "eq", "value": 1},
        "logic": "and", "priority": 0,
        "created_at": "2026-09-14T00:00:00Z", "updated_at": "2026-09-14T00:00:00Z",
    }
    d.update(over)
    return d


def _act_dict(cond_id, **over):
    d = {
        "id": str(uuid4()), "condition_id": str(cond_id), "name": None,
        "action_type": "message", "params": {}, "priority": 0,
        "created_at": "2026-09-14T00:00:00Z", "updated_at": "2026-09-14T00:00:00Z",
    }
    d.update(over)
    return d


class TestRouterWiring:
    def test_openapi_paths_single_prefix(self, app):
        paths = app.openapi()["paths"]
        assert "/api/v1/workflows" in paths
        assert "/api/v1/workflows/{workflow_id}" in paths
        assert "/api/v1/api/v1/workflows" not in paths
        assert "/api/v1/workflows/{workflow_id}/triggers" in paths
        assert (
            "/api/v1/workflows/{workflow_id}/triggers/{trigger_id}/conditions"
            in paths
        )
        assert (
            "/api/v1/workflows/{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}/actions"
            in paths
        )

    def test_detail_route_not_shadowed(self, app):
        paths = app.openapi()["paths"]
        assert "/api/v1/workflows/{workflow_id}/detail" in paths


class TestWorkflowEndpoints:
    def test_create_workflow_201(self, client):
        wf = _wf_dict()

        async def create_workflow(data):
            assert data.name == "WF"
            assert data.status == "draft"
            assert data.workflow_type == "auto"
            return wf

        svc = mock_service(create_workflow=create_workflow)
        override(client, svc)
        resp = client.post("/api/v1/workflows", json={"name": "WF"})
        assert resp.status_code == 201
        assert resp.json() == wf

    def test_create_rejects_bad_workflow_type(self, client):
        resp = client.post("/api/v1/workflows", json={"name": "WF", "workflow_type": "nope"})
        assert resp.status_code == 422

    def test_create_rejects_bad_status(self, client):
        resp = client.post("/api/v1/workflows", json={"name": "WF", "status": "bogus"})
        assert resp.status_code == 422

    def test_list_workflows(self, client):
        async def list_workflows(**kw):
            return [], 0
        svc = mock_service(list_workflows=list_workflows)
        override(client, svc)
        resp = client.get("/api/v1/workflows?page=1&page_size=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["page"] == 1
        assert body["items"] == []

    def test_get_workflow_404(self, client):
        async def get_workflow(wf_id):
            return None
        svc = mock_service(get_workflow=get_workflow)
        override(client, svc)
        resp = client.get(f"/api/v1/workflows/{uuid4()}")
        assert resp.status_code == 404

    def test_get_workflow_detail_404(self, client):
        async def get_workflow_detail(wf_id):
            return None
        svc = mock_service(get_workflow_detail=get_workflow_detail)
        override(client, svc)
        resp = client.get(f"/api/v1/workflows/{uuid4()}/detail")
        assert resp.status_code == 404

    def test_delete_workflow_204(self, client):
        async def delete_workflow(wf_id):
            return True
        svc = mock_service(delete_workflow=delete_workflow)
        override(client, svc)
        resp = client.delete(f"/api/v1/workflows/{uuid4()}")
        assert resp.status_code == 204

    def test_delete_workflow_404(self, client):
        async def delete_workflow(wf_id):
            return False
        svc = mock_service(delete_workflow=delete_workflow)
        override(client, svc)
        resp = client.delete(f"/api/v1/workflows/{uuid4()}")
        assert resp.status_code == 404


class TestTriggerEndpoints:
    def test_add_trigger(self, client):
        wf_id, wf = uuid4(), _wf_dict()

        async def create_trigger(workflow_id, data):
            assert workflow_id == wf_id
            return _trig_dict(workflow_id, trigger_type="cron", spec={"cron": "* * * * *"})

        svc = mock_service(create_trigger=create_trigger)
        override(client, svc)
        resp = client.post(
            f"/api/v1/workflows/{wf_id}/triggers",
            json={"trigger_type": "cron", "spec": {"cron": "* * * * *"}},
        )
        assert resp.status_code == 201
        assert resp.json()["trigger_type"] == "cron"
        assert resp.json()["spec"] == {"cron": "* * * * *"}

    def test_add_trigger_scheduled_missing_spec_422(self, client):
        resp = client.post(
            f"/api/v1/workflows/{uuid4()}/triggers",
            json={"trigger_type": "scheduled", "spec": {}},
        )
        assert resp.status_code == 422

    def test_add_trigger_missing_workflow_404(self, client):
        from app.services.workflow import WorkflowNotFoundError

        async def create_trigger(workflow_id, data):
            raise WorkflowNotFoundError("Workflow", workflow_id)

        svc = mock_service(create_trigger=create_trigger)
        override(client, svc)
        resp = client.post(f"/api/v1/workflows/{uuid4()}/triggers", json={})
        assert resp.status_code == 404

    def test_list_triggers(self, client):
        wf_id = uuid4()

        async def list_triggers(workflow_id):
            return [_trig_dict(workflow_id)]

        svc = mock_service(list_triggers=list_triggers)
        override(client, svc)
        resp = client.get(f"/api/v1/workflows/{wf_id}/triggers")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["trigger_type"] == "manual"


class TestConditionEndpoints:
    def test_add_condition(self, client):
        wf_id, trig_id = uuid4(), uuid4()

        async def create_condition(trigger_id, data):
            assert trigger_id == trig_id
            return _cond_dict(trig_id, expression={"field": "orders", "operator": "gte", "value": 3})

        svc = mock_service(create_condition=create_condition)
        override(client, svc)
        resp = client.post(
            f"/api/v1/workflows/{wf_id}/triggers/{trig_id}/conditions",
            json={"expression": {"field": "orders", "operator": "gte", "value": 3}},
        )
        assert resp.status_code == 201
        assert resp.json()["expression"]["operator"] == "gte"

    def test_add_condition_bad_operator_422(self, client):
        resp = client.post(
            f"/api/v1/workflows/{uuid4()}/triggers/{uuid4()}/conditions",
            json={"expression": {"field": "x", "operator": "approx", "value": 1}},
        )
        assert resp.status_code == 422

    def test_condition_missing_trigger_404(self, client):
        from app.services.workflow import WorkflowNotFoundError

        async def create_condition(trigger_id, data):
            raise WorkflowNotFoundError("WorkflowTrigger", trigger_id)

        svc = mock_service(create_condition=create_condition)
        override(client, svc)
        resp = client.post(
            f"/api/v1/workflows/{uuid4()}/triggers/{uuid4()}/conditions",
            json={"expression": {"field": "x"}},
        )
        assert resp.status_code == 404


class TestActionEndpoints:
    def test_add_action(self, client):
        wf_id, trig_id, cond_id = uuid4(), uuid4(), uuid4()

        async def create_action(condition_id, data):
            assert condition_id == cond_id
            return _act_dict(cond_id, action_type="tag", params={"tag_ids": ["vip"]})

        svc = mock_service(create_action=create_action)
        override(client, svc)
        resp = client.post(
            f"/api/v1/workflows/{wf_id}/triggers/{trig_id}/conditions/{cond_id}/actions",
            json={"action_type": "tag", "params": {"tag_ids": ["vip"]}},
        )
        assert resp.status_code == 201
        assert resp.json()["action_type"] == "tag"
        assert resp.json()["params"] == {"tag_ids": ["vip"]}

    def test_add_action_bad_type_422(self, client):
        resp = client.post(
            f"/api/v1/workflows/{uuid4()}/triggers/{uuid4()}/conditions/{uuid4()}/actions",
            json={"action_type": "explode"},
        )
        assert resp.status_code == 422

    def test_action_missing_condition_404(self, client):
        from app.services.workflow import WorkflowNotFoundError

        async def create_action(condition_id, data):
            raise WorkflowNotFoundError("WorkflowCondition", condition_id)

        svc = mock_service(create_action=create_action)
        override(client, svc)
        resp = client.post(
            f"/api/v1/workflows/{uuid4()}/triggers/{uuid4()}/conditions/{uuid4()}/actions",
            json={},
        )
        assert resp.status_code == 404
