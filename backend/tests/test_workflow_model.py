"""Model + schema tests for the workflow configuration model (t_wf_002).

Covers:
- vocabulary constants
- ORM model table/column sanity
- schema validation (trigger spec by type, condition operator, action type)
"""
import pytest
from uuid import uuid4

from app.db.models.workflow import (
    WORKFLOW_TYPES,
    WORKFLOW_STATUSES,
    ACTION_TYPES,
    CONDITION_OPERATORS,
    TRIGGER_TYPES,
    Workflow,
    WorkflowTrigger,
    WorkflowCondition,
    WorkflowAction,
)
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowUpdate,
    TriggerCreate,
    TriggerUpdate,
    ConditionCreate,
    ConditionUpdate,
    ActionCreate,
    ActionUpdate,
)


class TestVocabulary:
    def test_trigger_types(self):
        assert set(TRIGGER_TYPES) == {"manual", "scheduled", "event", "cron"}

    def test_action_types(self):
        assert {"conversation", "message", "tag", "status_change"} <= set(ACTION_TYPES)

    def test_condition_operators(self):
        assert "gte" in CONDITION_OPERATORS
        assert "contains" in CONDITION_OPERATORS

    def test_workflow_statuses(self):
        assert set(WORKFLOW_STATUSES) == {"draft", "active", "paused", "archived"}


class TestModels:
    def test_tablenames(self):
        assert Workflow.__tablename__ == "workflow"
        assert WorkflowTrigger.__tablename__ == "workflow_trigger"
        assert WorkflowCondition.__tablename__ == "workflow_condition"
        assert WorkflowAction.__tablename__ == "workflow_action"

    def test_foreign_keys(self):
        assert "workflow_id" in [c.name for c in WorkflowTrigger.__table__.columns]
        assert "trigger_id" in [c.name for c in WorkflowCondition.__table__.columns]
        assert "condition_id" in [c.name for c in WorkflowAction.__table__.columns]

    def test_trigger_cascade(self):
        rel = WorkflowTrigger.__mapper__.relationships["conditions"]
        assert "delete-orphan" in rel.cascade
        cond_rel = WorkflowCondition.__mapper__.relationships["actions"]
        assert "delete-orphan" in cond_rel.cascade
        wf_rel = Workflow.__mapper__.relationships["triggers"]
        assert "delete-orphan" in wf_rel.cascade


class TestWorkflowSchemas:
    def test_create_defaults(self):
        wf = WorkflowCreate(name="Test")
        assert wf.workflow_type == "auto"
        assert wf.status == "draft"
        assert wf.config == {}
        assert wf.execution_policy == {}

    def test_create_rejects_bad_type(self):
        with pytest.raises(ValueError):
            WorkflowCreate(name="X", workflow_type="nope")

    def test_create_rejects_bad_status(self):
        with pytest.raises(ValueError):
            WorkflowCreate(name="X", status="bogus")

    def test_create_rejects_empty_name(self):
        with pytest.raises(ValueError):
            WorkflowCreate(name="")

    def test_update_all_optional(self):
        up = WorkflowUpdate()
        assert up.name is None
        assert up.status is None


class TestTriggerSchemas:
    def test_scheduled_requires_run_at(self):
        with pytest.raises(ValueError):
            TriggerCreate(trigger_type="scheduled", spec={})

    def test_scheduled_with_run_at(self):
        t = TriggerCreate(trigger_type="scheduled", spec={"run_at": "2026-09-15T00:00:00Z"})
        assert t.trigger_type == "scheduled"

    def test_cron_requires_cron(self):
        with pytest.raises(ValueError):
            TriggerCreate(trigger_type="cron", spec={"timezone": "UTC"})

    def test_cron_ok(self):
        t = TriggerCreate(trigger_type="cron", spec={"cron": "*/5 * * * *"})
        assert t.spec["cron"] == "*/5 * * * *"

    def test_event_requires_event(self):
        with pytest.raises(ValueError):
            TriggerCreate(trigger_type="event", spec={})

    def test_manual_no_spec_needed(self):
        t = TriggerCreate(trigger_type="manual")
        assert t.spec == {}

    def test_update_spec_validated_with_type(self):
        with pytest.raises(ValueError):
            TriggerUpdate(trigger_type="cron", spec={})

    def test_update_spec_skipped_without_type(self):
        up = TriggerUpdate(spec={"anything": 1})  # type resolved service-side after merge
        assert up.spec == {"anything": 1}


class TestConditionSchemas:
    def test_valid_operator(self):
        c = ConditionCreate(expression={"field": "a.b", "operator": "gte", "value": 3})
        assert c.expression["operator"] == "gte"

    def test_unknown_operator_rejected(self):
        with pytest.raises(ValueError):
            ConditionCreate(expression={"field": "x", "operator": "approx", "value": 1})

    def test_free_form_expression_ok(self):
        c = ConditionCreate(expression={"custom": "payload", "no": "operator key"})
        assert c.expression == {"custom": "payload", "no": "operator key"}

    def test_logic_must_be_and_or(self):
        with pytest.raises(ValueError):
            ConditionCreate(expression={"field": "x"}, logic="xor")

    def test_update_expression_validated(self):
        with pytest.raises(ValueError):
            ConditionUpdate(expression={"operator": "weird"})


class TestActionSchemas:
    def test_default_type(self):
        a = ActionCreate()
        assert a.action_type == "message"
        assert a.params == {}

    def test_rejects_bad_type(self):
        with pytest.raises(ValueError):
            ActionCreate(action_type="hack")

    def test_tag_action_params(self):
        a = ActionCreate(action_type="tag", params={"tag_ids": ["t1"]})
        assert a.params == {"tag_ids": ["t1"]}

    def test_update_partial(self):
        up = ActionUpdate(priority=5)
        assert up.priority == 5
        assert up.params is None
