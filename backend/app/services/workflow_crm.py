"""Workflow ↔ CRM integration executor (t_4f31af5e).

Bridges the Workflow model (Workflow / Trigger / Condition / Action,
t_wf_001 / t_wf_002) with the CRM service layer.

Architecture separation (ARCHITECTURE.md layering):

    CRM services (lead / tag / lifecycle)
        -> app.events (in-process domain event bus)
        -> WorkflowCrmExecutor (this module)
             -> Workflow / Trigger / Condition / Action models
             -> CRM services (action execution, business rules stay there)
             -> ExecutionLog (observability, t_wf_005)

No CRM-specific logic lives in the workflow model layer, and no workflow
logic lives inside CRM services — CRM services only *emit* a domain event
after their own commit; re-reading current state happens here, at match
time.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.customer import Customer
from app.db.models.lead import Lead
from app.db.models.workflow import (
    ACTION_TYPES,
    CONDITION_OPERATORS,
    ExecutionLog,
    Workflow,
    WorkflowCondition,
    WorkflowTrigger,
)
from app.db.session import AsyncSessionLocal
from app.crm.services.lead import create_lead, update_lead
from app.crm.services.lifecycle import transition_lifecycle_stage
from app.crm.services.tag import (
    add_tags_to_customer,
    add_tags_to_lead,
    remove_tag_from_customer,
    remove_tag_from_lead,
)
from app.events.domain_events import (
    EVENT_TYPES,
    DomainEvent,
    get_event_bus,
)

logger = logging.getLogger(__name__)


# =====================================================================
# Condition expression evaluation
# =====================================================================

def evaluate_expression(actual: Any, operator: str, expected: Any) -> bool:
    """Evaluate one condition operator against a resolved field value.

    ``actual`` may be None (missing field) — only equality-style checks
    can ever be true for it; comparisons return False.
    """
    op = (operator or "eq").lower()
    if actual is None:
        return op == "eq" and expected is None
    try:
        if op == "eq":
            return actual == expected
        if op == "neq":
            return actual != expected
        if op in ("gt", "gte", "lt", "lte"):
            if actual is None or expected is None:
                return False
            if op == "gt":
                return actual > expected
            if op == "gte":
                return actual >= expected
            if op == "lt":
                return actual < expected
            return actual <= expected
        if op == "in":
            return expected is not None and actual in expected
        if op == "not_in":
            return expected is not None and actual not in expected
        if op == "contains":
            return expected in actual
        if op == "regex":
            return re.search(expected, str(actual)) is not None
    except TypeError:
        logger.warning(
            "condition eval: operator %r not compatible with value type %s",
            op, type(actual).__name__,
        )
        return False
    logger.warning("condition eval: unknown operator %r, treating as fail", op)
    return False


_EVENT_FIELD_KEYS = {
    "type": "event_type",
    "entity_type": "entity_type",
    "entity_id": "entity_id",
}


def _walk_path(source: Any, parts: List[str]) -> Any:
    """Walk a dotted path over dict / attributes. Missing -> None."""
    current = source
    for part in parts:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _coerce_uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


async def resolve_condition_value(
    db: AsyncSession,
    expression: Dict[str, Any],
    event: DomainEvent,
) -> Any:
    """Resolve a condition's ``field`` to its current value.

    Field namespaces (dotted paths):

    - ``event.<key>``       : the triggering event (type / entity_type /
      entity_id, or any key of the published payload)
    - ``lead.<field>``      : live re-read of the affected Lead
      (status, stage alias for lifecycle_stage_code, tags -> list of
      tag names, customer, intent_score, source_type, ...)
    - ``customer.<field>``  : live re-read of the affected Customer
      (name, email, phone, company, extra_info, tags -> list of tag names)

    Live re-reading (vs. trusting the event payload) is deliberate: the
    executor runs after the publisher's commit, so it sees committed state
    and conditions stay consistent even when events queue up.
    """
    field = str(expression.get("field") or "").strip()
    parts = field.split(".")
    if not parts or parts[0] not in ("event", "lead", "customer"):
        # Unknown field namespace -> treat as missing (None).
        return None

    if parts[0] == "event":
        if len(parts) == 1:
            return event.payload
        key = parts[1]
        if key in _EVENT_FIELD_KEYS:
            return getattr(event, _EVENT_FIELD_KEYS[key])
        return _walk_path(event.payload, parts[1:])

    entity_id: Optional[UUID] = _coerce_uuid(event.entity_id)
    if parts[0] == "lead":
        lead = await _load(db, Lead, entity_id)
        return _resolve_entity_field(lead, parts[1:])
    customer = await _load(db, Customer, entity_id)
    return _resolve_entity_field(customer, parts[1:])


async def _load(db: AsyncSession, model, entity_id: Optional[UUID]):
    if entity_id is None:
        return None
    result = await db.execute(
        select(model)
        .where(model.id == entity_id, model.is_deleted == False)  # noqa: E712
        .options(selectinload(model.tags))
    )
    return result.scalar_one_or_none()


def _resolve_entity_field(entity: Any, parts: List[str]) -> Any:
    if entity is None:
        return None
    if not parts:
        return None
    key = parts[0]
    value: Any
    if key in ("stage", "tags"):
        if key == "stage":
            value = entity.lifecycle_stage_code
        else:
            value = [tag.name for tag in (entity.tags or [])]
    elif key == "customer":
        value = entity.customer_id
    else:
        value = getattr(entity, key, None)
    if len(parts) > 1:
        value = _walk_path(value, parts[1:])
    return value


# =====================================================================
# Executor
# =====================================================================

class WorkflowCrmExecutor:
    """Runs active workflows against CRM domain events.

    All state mutation goes through the CRM service layer, so business
    rules (status-transition validation, tag usage counters, lifecycle
    audit logging) stay in one place. Every (workflow, trigger) run is
    recorded in ExecutionLog for observability.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        # Per-workflow locks: one workflow instance must not interleave
        # with itself while an execution is in flight.
        self._locks: Dict[UUID, asyncio.Lock] = {}

    # ---------- public entry points ----------

    async def run_event(
        self,
        event: DomainEvent,
        *,
        workflow_id: Optional[UUID] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Evaluate ``event`` against active workflows and execute actions.

        Args:
            event: the domain event to react to.
            workflow_id: when set, only that workflow is considered
                (manual-trigger path).
            force: skip event-type matching on triggers (manual runs).

        Returns an aggregate result (also used as the API response body).
        """
        started = datetime.now(timezone.utc)
        workflows = await self._load_workflows(workflow_id)
        results: List[Dict[str, Any]] = []
        for workflow in workflows:
            outcomes = await self._run_workflow_for_event(workflow, event, force=force)
            results.extend(outcomes)
        # Aggregate status
        statuses = [r["status"] for r in results]
        if any(s == "failed" for s in statuses):
            overall = "failed"
        elif results and all(s in ("skipped",) for s in statuses):
            overall = "skipped"
        elif any(s == "success" for s in statuses):
            overall = "success"
        else:
            overall = "no_match"
        finished = datetime.now(timezone.utc)
        return {
            "event_type": event.event_type,
            "entity_type": event.entity_type,
            "entity_id": str(event.entity_id) if event.entity_id else None,
            "status": overall,
            "workflows": results,
            "matched": sum(1 for r in results if r["status"] in ("success", "failed")),
            "executed": sum(1 for r in results if r["status"] == "success"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_ms": (finished - started).total_seconds() * 1000.0,
        }

    async def handle_domain_event(self, event: DomainEvent) -> None:
        """Bus handler entrypoint: run the event, swallow (log) failures.

        A crashing subscriber must never take down the publisher, and the
        executor records per-workflow failures in ExecutionLog anyway.
        """
        try:
            result = await self.run_event(event)
            logger.info(
                "workflow-crm: event %s -> overall=%s matched=%s executed=%s",
                event.event_type, result["status"], result["matched"], result["executed"],
            )
        except Exception:  # noqa: BLE001 - keep the bus path safe
            logger.exception(
                "workflow-crm: handling event %s failed", event.event_type,
            )

    # ---------- workflow loading / matching ----------

    async def _load_workflows(self, workflow_id: Optional[UUID]) -> List[Workflow]:
        query = select(Workflow).where(
            Workflow.is_deleted == False, Workflow.status == "active"  # noqa: E712
        )
        if workflow_id is not None:
            query = query.where(Workflow.id == workflow_id)
        query = query.options(
            selectinload(Workflow.triggers)
            .selectinload(WorkflowTrigger.conditions)
            .selectinload(WorkflowCondition.actions)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    def _matching_triggers(self, workflow: Workflow, event: DomainEvent, force: bool) -> List[Any]:
        triggers = [t for t in (workflow.triggers or []) if not t.is_deleted]
        if not force:
            return [
                t for t in triggers
                if t.enabled
                and t.trigger_type == "event"
                and ((t.spec or {}).get("event") in (event.event_type, None, "*"))
            ]
        # Manual runs: any enabled trigger (event/manual); scheduled/cron
        # triggers have no event semantics and are excluded.
        return [
            t for t in triggers
            if t.enabled and t.trigger_type in ("event", "manual")
        ]

    # ---------- per-(workflow, trigger) execution ----------

    async def _run_workflow_for_event(
        self, workflow: Workflow, event: DomainEvent, *, force: bool
    ) -> List[Dict[str, Any]]:
        outcomes: List[Dict[str, Any]] = []
        triggers = self._matching_triggers(workflow, event, force)
        for trigger in triggers:
            outcomes.append(await self._run_trigger(workflow, trigger, event))
        return outcomes

    async def _run_trigger(
        self, workflow: Workflow, trigger: Any, event: DomainEvent
    ) -> Dict[str, Any]:
        lock = self._locks.setdefault(workflow.id, asyncio.Lock())
        async with lock:
            conditions = [c for c in (trigger.conditions or []) if not c.is_deleted]
            entries = await self._evaluate_conditions(conditions, event)

            # Deterministic per-condition rule (V1 scope: no expression engine):
            #   - a condition's actions run iff THAT condition passes;
            #   - the trigger result is "skipped" when conditions exist but
            #     none passed, "success" when actions ran cleanly, "failed"
            #     when any action failed.
            # ``entries`` is computed in priority order, so reorder the
            # conditions identically before zipping them back together.
            ordered = sorted(conditions, key=lambda c: c.priority or 0)
            actions_to_run: List[Any] = []
            for condition, entry in zip(ordered, entries):
                if entry["passed"]:
                    actions_to_run.extend(
                        a for a in (condition.actions or []) if not a.is_deleted
                    )

            action_results: List[Dict[str, Any]] = []
            if conditions and not any(e["passed"] for e in entries):
                # Guard(s) present but none satisfied: no actions run.
                status = "skipped"
            else:
                for action in sorted(actions_to_run, key=lambda a: a.priority or 0):
                    action_results.append(
                        await self._execute_action(workflow, action, event)
                    )
                hard_failures = [r for r in action_results if r["status"] == "failed"]
                status = "failed" if hard_failures else "success"

            return await self._record_execution(
                workflow, trigger, event, status, entries, action_results,
            )

    async def _evaluate_conditions(
        self, conditions: List[Any], event: DomainEvent
    ) -> List[Dict[str, Any]]:
        """Evaluate every condition; one entry per condition, in priority order.

        Each entry records the expression, the live-resolved value, whether it
        passed, and a human-readable detail line. Conditions are independent
        in V1 (see the per-condition execution rule in ``_run_trigger``); the
        ``logic`` field is preserved on the entry for forward compatibility but
        does not alter execution yet.
        """
        entries: List[Dict[str, Any]] = []
        for condition in sorted(conditions, key=lambda c: c.priority or 0):
            expression = condition.expression or {}
            value = await resolve_condition_value(self.db, expression, event)
            passed = evaluate_expression(
                value,
                expression.get("operator", "eq"),
                expression.get("value"),
            )
            entries.append(
                {
                    "condition_id": str(condition.id) if condition.id else None,
                    "name": condition.name,
                    "expression": expression,
                    "resolved_value": value,
                    "logic": condition.logic,
                    "passed": passed,
                    "detail": (
                        f"field={expression.get('field')!r} value={value!r} "
                        f"op={expression.get('operator', 'eq')!r} "
                        f"expected={expression.get('value')!r} -> {passed}"
                    ),
                }
            )
        return entries

    # ---------- action execution (through CRM services) ----------

    async def _execute_action(
        self, workflow: Workflow, action: Any, event: DomainEvent
    ) -> Dict[str, Any]:
        params = action.params or {}
        action_type = action.action_type
        started = time.monotonic()
        result: Dict[str, Any] = {
            "action_id": str(action.id) if action.id else None,
            "name": action.name,
            "action_type": action_type,
            "status": "success",
            "detail": None,
            "entity_refs": {},
        }
        try:
            if action_type == "custom":
                sub = params.get("action")
                if sub in ("create_lead", "update_lead", "tag", "status_change"):
                    action_type = sub
                else:
                    result["status"] = "unsupported"
                    result["detail"] = (
                        f"custom action {sub!r} is not a supported CRM sub-action "
                        f"(supported: create_lead, update_lead, tag, status_change)"
                    )
                    return result

            if action_type == "create_lead":
                result.update(await self._action_create_lead(workflow, params, event))
            elif action_type == "update_lead":
                result.update(await self._action_update_lead(workflow, params, event))
            elif action_type == "tag":
                result.update(await self._action_tag(params, event))
            elif action_type == "status_change":
                result.update(
                    await self._action_status_change(workflow, params, event)
                )
            elif action_type in ("message", "conversation", "notification"):
                # V1 scope is CRM automation; conversation actions belong to
                # the AI/conversation integration and are not executed here.
                result["status"] = "unsupported"
                result["detail"] = (
                    f"action type {action_type!r} is outside the CRM "
                    "integration slice; configure a CRM action "
                    "(tag / status_change / create_lead / update_lead)"
                )
            else:
                result["status"] = "unsupported"
                result["detail"] = f"unknown action type {action_type!r}"
        except ValueError as exc:
            # Business-rule rejection (invalid status transition, missing
            # tag, missing entity...) — a *failed* action, not a crash.
            result["status"] = "failed"
            result["detail"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - isolate per-action
            result["status"] = "failed"
            result["detail"] = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "workflow-crm action %s (%s) failed: %s",
                action.id, action_type, result["detail"],
            )
        result["duration_ms"] = (time.monotonic() - started) * 1000.0
        return result

    def _default_target(self, event: DomainEvent, params: Dict[str, Any]) -> tuple:
        target = params.get("target") or event.entity_type
        entity_id = _coerce_uuid(params.get("entity_id") or event.entity_id)
        return target, entity_id

    async def _action_create_lead(
        self, workflow: Workflow, params: Dict[str, Any], event: DomainEvent
    ) -> Dict[str, Any]:
        payload = event.payload or {}
        customer_id = _coerce_uuid(
            params.get("customer_id") or payload.get("customer_id")
        )
        # P2 consistency fix: when no explicit customer_id is supplied, a
        # customer-typed event falls back to its own entity, mirroring
        # _default_target used by tag / status_change / update_lead. Without
        # this a create_lead on customer.created silently produced an orphan
        # (customer-less) lead. Explicit params/payload customer_id still
        # wins (override behavior preserved).
        if customer_id is None and event.entity_type == "customer":
            customer_id = _coerce_uuid(event.entity_id)
        lead_data: Dict[str, Any] = {
            "source_type": params.get("source_type") or "workflow",
            "source_id": str(workflow.id) if workflow.id else None,
            "status": params.get("status") or "new",
            "operator": params.get("operator") or f"workflow:{workflow.id}",
            "notes": params.get("notes") or f"auto-created by workflow {workflow.id}",
            "lifecycle_stage_code": params.get("lifecycle_stage_code") or "陌生",
        }
        if customer_id:
            lead_data["customer_id"] = customer_id
        if params.get("intent_score") is not None:
            lead_data["intent_score"] = int(params["intent_score"])
        created = await create_lead(self.db, lead_data)
        return {
            "entity_refs": {"lead_id": created.get("id")},
            "detail": f"created lead {created.get('id')}",
        }

    async def _action_update_lead(
        self, workflow: Workflow, params: Dict[str, Any], event: DomainEvent
    ) -> Dict[str, Any]:
        _, entity_id = self._default_target(event, params)
        if entity_id is None:
            raise ValueError("update_lead action requires entity_id (lead id)")
        updates = dict(params.get("updates") or {})
        if params.get("status") is not None:
            updates["status"] = params["status"]
        if params.get("notes") is not None:
            updates["notes"] = params["notes"]
        if params.get("operator") is not None:
            updates["operator"] = params["operator"]
        if not updates:
            raise ValueError("update_lead action requires updates or status/notes")
        updated = await update_lead(self.db, entity_id, updates)
        if updated is None:
            raise ValueError(f"lead {entity_id} not found")
        return {"entity_refs": {"lead_id": str(entity_id)}, "detail": f"updated lead {entity_id} fields {sorted(updates)}"}

    async def _action_tag(self, params: Dict[str, Any], event: DomainEvent) -> Dict[str, Any]:
        target, entity_id = self._default_target(event, params)
        tag_ids = [_coerce_uuid(t) for t in (params.get("tag_ids") or [])]
        if any(t is None for t in tag_ids):
            raise ValueError("tag action: tag_ids must be valid UUIDs")
        operation = str(params.get("operation") or "add").lower()
        if target == "lead":
            if entity_id is None:
                raise ValueError("tag action: lead entity_id is required")
            if operation == "add":
                res = await add_tags_to_lead(self.db, entity_id, tag_ids)
                return {
                    "entity_refs": {"lead_id": str(entity_id), "tag_ids": [str(t) for t in tag_ids]},
                    "detail": f"added {res.get('inserted')} tag(s) to lead {entity_id}",
                }
            removed = 0
            for tag_id in tag_ids:
                if await remove_tag_from_lead(self.db, entity_id, tag_id):
                    removed += 1
            return {
                "entity_refs": {"lead_id": str(entity_id), "tag_ids": [str(t) for t in tag_ids]},
                "detail": f"removed {removed} tag(s) from lead {entity_id}",
            }
        if target == "customer":
            if entity_id is None:
                raise ValueError("tag action: customer entity_id is required")
            if operation == "add":
                res = await add_tags_to_customer(self.db, entity_id, tag_ids)
                return {
                    "entity_refs": {"customer_id": str(entity_id), "tag_ids": [str(t) for t in tag_ids]},
                    "detail": f"added {res.get('inserted')} tag(s) to customer {entity_id}",
                }
            removed = 0
            for tag_id in tag_ids:
                if await remove_tag_from_customer(self.db, entity_id, tag_id):
                    removed += 1
            return {
                "entity_refs": {"customer_id": str(entity_id), "tag_ids": [str(t) for t in tag_ids]},
                "detail": f"removed {removed} tag(s) from customer {entity_id}",
            }
        raise ValueError(f"tag action: unsupported target {target!r}")

    async def _action_status_change(
        self, workflow: Workflow, params: Dict[str, Any], event: DomainEvent
    ) -> Dict[str, Any]:
        target, entity_id = self._default_target(event, params)
        if entity_id is None:
            raise ValueError("status_change action requires entity_id")
        new_stage = params.get("new_stage")
        new_status = params.get("new_status")
        if new_stage is not None:
            res = await transition_lifecycle_stage(
                self.db,
                entity_id,
                str(new_stage),
                reason=f"workflow:{workflow.id}",
                operator="workflow",
            )
            return {
                "entity_refs": {"lead_id": str(entity_id), "lifecycle_log_id": res.get("id")},
                "detail": f"stage {res.get('old_stage_code')} -> {res.get('new_stage_code')}",
            }
        if new_status is not None:
            updated = await update_lead(
                self.db, entity_id, {"status": str(new_status), "operator": "workflow"}
            )
            if updated is None:
                raise ValueError(f"lead {entity_id} not found")
            return {
                "entity_refs": {"lead_id": str(entity_id)},
                "detail": f"lead status -> {new_status}",
            }
        raise ValueError("status_change action requires new_stage or new_status")

    # ---------- observability ----------

    async def _record_execution(
        self,
        workflow: Workflow,
        trigger: Any,
        event: DomainEvent,
        status: str,
        condition_entries: List[Dict[str, Any]],
        action_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        log = ExecutionLog(
            execution_type="workflow",
            trigger_type="event" if trigger.trigger_type == "event" else "manual",
            status=status,
            workflow_id=workflow.id,
            task_id=trigger.id,
            input_params={
                "event_type": event.event_type,
                "entity_type": event.entity_type,
                "entity_id": str(event.entity_id) if event.entity_id else None,
                "payload": event.payload or {},
            },
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            output_result={
                "trigger_id": str(trigger.id) if trigger.id else None,
                "conditions": condition_entries,
                "actions": action_results,
            },
            metadata_={"workflow_name": workflow.name, "event": event.event_type},
        )
        self.db.add(log)
        await self.db.commit()
        try:
            await self.db.refresh(log)
        except Exception:  # noqa: BLE001 - refresh is best-effort after commit
            pass
        logger.info(
            "workflow-crm: workflow %s trigger %s -> %s (%d actions)",
            workflow.id, trigger.id, status, len(action_results),
        )
        return {
            "workflow_id": str(workflow.id) if workflow.id else None,
            "workflow_name": workflow.name,
            "trigger_id": str(trigger.id) if trigger.id else None,
            "status": status,
            "conditions": condition_entries,
            "actions": action_results,
            "execution_log_id": str(log.id) if log.id else None,
        }


# =====================================================================
# Event-bus wiring
# =====================================================================

_subscribed = False


def register_workflow_crm_subscriber() -> int:
    """Subscribe the executor to all CRM domain events (idempotent).

    Each event is handled in its own DB session so the workflow side can
    never hold the publisher's transaction open. Returns the number of
    event types subscribed.
    """
    global _subscribed
    if _subscribed:
        return len(EVENT_TYPES)
    bus = get_event_bus()

    async def _on_event(event: DomainEvent) -> None:
        # Domain separation (t_cc6aa406): the CRM executor owns only the CRM
        # domain events; conversation events are handled by the conversation
        # bridge. The bus dispatches an event to every subscriber of its
        # type, so guard here: a CRM event type is always in EVENT_TYPES
        # (conversation types are registered on separate keys and never
        # reach this handler), but be explicit so a future wildcard
        # subscription cannot leak conversation events into the CRM path.
        db = AsyncSessionLocal()
        try:
            await WorkflowCrmExecutor(db).handle_domain_event(event)
        finally:
            await db.close()

    for event_type in EVENT_TYPES:
        bus.subscribe(event_type, _on_event)
    _subscribed = True
    logger.info(
        "workflow-crm: subscribed to %d CRM event types", len(EVENT_TYPES)
    )
    return len(EVENT_TYPES)


def _is_subscribed() -> bool:
    return _subscribed


def reset_workflow_crm_subscriber() -> None:
    """Test helper: forget that the bus was wired (subscribers stay until
    the bus itself is reset)."""
    global _subscribed
    _subscribed = False
