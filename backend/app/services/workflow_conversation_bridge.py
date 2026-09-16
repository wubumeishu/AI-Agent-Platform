"""Workflow <-> Conversation integration service (Phase 4 / t_cc6aa406).

Bridges the Phase 4 workflow engine with the Phase 2 conversation module
on top of the platform in-process bus (``app.events.domain_events``):

    DomainEvent (conversation.created / message.created / intent.classified)
        |
        v
    WorkflowConversationBridge.handle_domain_event
        |  1. find active workflows whose event trigger matches the event
        |     (spec.event == event_type; spec.topic == entity_type when set)
        |  2. evaluate the trigger's conditions against the event payload
        |  3. run each passing condition's actions:
        |       - conversation  -> create a conversation record
        |       - message       -> generate a reply (AI, or deterministic
        |                           template when no AI provider is wired)
        |                           and append it to a conversation
        |       - tag           -> attach a tag to the customer
        |       - notification / custom -> recorded, deferred to later waves
        v
    ExecutionLog (one row per trigger hit: input, output, status, error)

Architecture-separation rules (per SOUL / ARCHITECTURE.md):
- This module depends on abstractions (the platform event bus, the
  ConversationService, an injectable AIResponder) — it never imports
  BitBrowser or a concrete AI vendor.
- AI generation is pluggable: pass an ``AIResponder`` to the bridge.
  The default responder uses a deterministic template so the chain works
  end-to-end with no model configured; an LLM adapter slots in without
  touching this module.
- Conversation-side producers publish through ``get_event_bus().publish``
  (immediate dispatch, awaited inline) so the trigger -> action chain runs
  in-process. CRM producers use the fire-and-forget queue
  (``publish_nowait`` + flush point) — the two modes coexist on the same
  bus; a subscriber's failure never rolls back the publisher's request.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow import (
    ExecutionLog,
    Workflow,
    WorkflowAction,
    WorkflowCondition,
    WorkflowTrigger,
)
from app.events.domain_events import (
    CONVERSATION_EVENT_TYPES,
    DomainEvent,
    get_event_bus,
)
from app.services.conversation_service import ConversationService
from app.schemas.conversation import ConversationCreate, MessageCreate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AI responder abstraction (provider isolation)
# ---------------------------------------------------------------------------

class AIResponder:
    """Protocol-level interface for generating a conversation reply.

    Implementations:
      - ``TemplateResponder`` (default, no external dependency)
      - a thin adapter over any LLM provider (OpenAI/Anthropic/local)

    Keeps the workflow engine free of vendor-specific code, mirroring the
    existing ``LLMProvider`` protocol in decision_engine.
    """

    async def generate_reply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return ``{"content": str, "strategy": str, "metadata": dict}``."""
        raise NotImplementedError


class TemplateResponder(AIResponder):
    """Deterministic, intent-aware reply generator (no LLM call).

    Safe default for V1: never fabricates facts, layers a persona name in,
    and escalates high-stakes intents to a human handoff notice.
    """

    _HIGH_STAKES = {"complaint", "escalation", "callback_request"}
    _TEMPLATES = {
        "greeting": "您好！很高兴见到您，请问有什么可以帮您的吗？",
        "question": "收到您的问题，我们会尽快为您答复，请稍候。",
        "thanks": "不客气，很高兴能帮到您！还有什么需要吗？",
        "farewell": "祝您一切顺利，期待再次为您服务，再见！",
        "complaint": "非常抱歉给您带来不好的体验，我们已记录您的问题并将尽快升级处理。",
        "escalation": "明白，正在为您转接人工客服，请稍候。",
        "callback_request": "好的，已记录您的回电请求，我们会尽快联系您。",
        "unknown": "感谢您的消息，我们已收到并会尽快跟进。",
    }

    async def generate_reply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        intent_type = str(context.get("intent_type") or "unknown").lower()
        template = self._TEMPLATES.get(intent_type, self._TEMPLATES["unknown"])
        content = f"{context.get('persona_name') or 'AI 助手'}：{template}"
        if intent_type in self._HIGH_STAKES:
            content += " 如需人工处理，我们将优先为您转接。"
        return {
            "content": content,
            "strategy": "template",
            "metadata": {
                "intent_type": intent_type,
                "escalate": intent_type in self._HIGH_STAKES,
                "workflow_id": context.get("workflow_id"),
            },
        }


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

@dataclass
class TriggerMatch:
    """One event-trigger hit inside an active workflow."""

    workflow: Workflow
    trigger: WorkflowTrigger
    conditions: List[WorkflowCondition] = field(default_factory=list)


class WorkflowConversationBridge:
    """Matches conversation domain events against workflow event triggers,
    evaluates conditions and executes the resulting actions."""

    SUPPORTED_ACTION_TYPES = ("conversation", "message", "tag",
                              "notification", "custom")
    # Only these entity types are in this bridge's domain; a conversation
    # event carrying any other entity type is ignored (the CRM bridge owns
    # lead/customer events, so the two executors never fight over an event).
    CONVERSATION_ENTITY_TYPES = ("conversation", "message", "intent")

    def __init__(
        self,
        db: AsyncSession,
        responder: Optional[AIResponder] = None,
    ) -> None:
        self.db = db
        self.responder = responder or TemplateResponder()

    # ---------------- event ingestion ----------------

    async def handle_domain_event(self, event: DomainEvent) -> None:
        """Bus handler: run matching workflows, never raise (bus-safe)."""
        if event.entity_type not in self.CONVERSATION_ENTITY_TYPES:
            return
        try:
            matches = await self.find_trigger_matches(event)
        except Exception:
            logger.exception("Trigger match lookup failed for %s", event.event_type)
            return

        if not matches:
            return

        for match in matches:
            try:
                await self._execute_workflow_for_event(match, event)
            except Exception:
                # One workflow failing must not break the others.
                logger.exception(
                    "Workflow execution failed for workflow=%s event=%s",
                    match.workflow.id, event.event_type,
                )

    # ---------------- scheduled entry point (P1-R1 consumer) ----------------

    async def run_scheduled(
        self,
        workflow_id: UUID,
        params: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Execute a workflow's active action graph for a *time-triggered* fire.

        The counterpart of :meth:`handle_domain_event` for the scheduler path:
        a SchedulerEngine fire has already been enqueued (P1-2) and claimed by
        a consumer — there is no inbound event to match. This method runs the
        workflow's enabled triggers' condition/action graphs in a synthetic
        scheduled context built from ``params`` (the fire's input parameters,
        e.g. ``intent_type`` / ``customer_id`` / ``channel``), so a timed
        workflow performs its real actions instead of being a record-only shell.

        It deliberately reuses the same :meth:`evaluate_condition` and
        :meth:`execute_action` business logic as the event path — no platform
        logic is duplicated here. Returns a JSON-safe summary
        (``{"ok": bool, "workflow_id", "triggers", "conditions", "actions"}``)
        for the task's ``result`` column; hard action failures make ``ok``
        False. A workflow with no enabled triggers/actions yields an explicit,
        observable no-op (``note`` field) rather than a silent drop.
        """
        from app.db.models.workflow import (
            Workflow,
            WorkflowCondition,
            WorkflowTrigger,
        )

        now = now or datetime.now(timezone.utc)
        params = dict(params or {})

        wf = (
            await self.db.execute(
                select(Workflow).where(
                    Workflow.id == workflow_id,
                    Workflow.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if wf is None:
            return {
                "ok": True,
                "workflow_id": str(workflow_id),
                "note": "workflow not found (or deleted); nothing to run",
            }

        # Load the workflow's enabled triggers with their conditions (any
        # trigger type — a schedule runs the workflow's whole active action
        # set; which trigger a schedule is "for" is a product decision the
        # operator expresses by editing the workflow, not by this executor).
        triggers = list(
            (
                await self.db.execute(
                    select(WorkflowTrigger).where(
                        WorkflowTrigger.workflow_id == workflow_id,
                        WorkflowTrigger.enabled == True,  # noqa: E712
                        WorkflowTrigger.is_deleted == False,  # noqa: E712
                    )
                )
            ).scalars().all()
        )
        cond_ids = [t.id for t in triggers]
        conditions: List[WorkflowCondition] = []
        actions_by_cond: Dict[UUID, List] = {}
        if cond_ids:
            from app.db.models.workflow import WorkflowAction

            conds = list(
                (
                    await self.db.execute(
                        select(WorkflowCondition).where(
                            WorkflowCondition.trigger_id.in_(cond_ids),
                            WorkflowCondition.is_deleted == False,  # noqa: E712
                        )
                    )
                ).scalars().all()
            )
            conditions = conds
            acts = list(
                (
                    await self.db.execute(
                        select(WorkflowAction).where(
                            WorkflowAction.condition_id.in_([c.id for c in conds]),
                            WorkflowAction.is_deleted == False,  # noqa: E712
                        )
                    )
                ).scalars().all()
            )
            for a in acts:
                actions_by_cond.setdefault(a.condition_id, []).append(a)

        ctx: Dict[str, Any] = {
            "event": None,
            "event_type": "scheduler.fire",
            "entity_type": "scheduler",
            "entity_id": None,
            "workflow_id": str(wf.id),
            "persona_name": (wf.config or {}).get("persona_name"),
            "customer_id": (wf.config or {}).get("customer_id"),
            "channel": (wf.config or {}).get("channel"),
            # Fire-supplied input parameters are the scheduled source of truth
            # for the synthetic context.
            "intent_type": params.get("intent_type"),
            "intent_confidence": params.get("confidence"),
            "conversation_id": params.get("conversation_id"),
            "message_id": params.get("message_id"),
            "payload": params,
            **{k: v for k, v in params.items() if k not in (
                "intent_type", "confidence", "conversation_id", "message_id",
            )},
        }

        conditions_run: List[Dict[str, Any]] = []
        actions_run: List[Dict[str, Any]] = []
        for trig in triggers:
            trig_conds = [c for c in conditions if c.trigger_id == trig.id]
            for cond in trig_conds:
                ok = self.evaluate_condition(cond, ctx)
                conditions_run.append({"condition_id": str(cond.id), "passed": ok})
                if not ok:
                    continue
                for action in actions_by_cond.get(cond.id, []):
                    rec = await self.execute_action(action, ctx)
                    rec.setdefault("action_id", str(action.id))
                    actions_run.append(rec)

        hard_failures = [a for a in actions_run if a.get("status") == "failed"]
        summary = {
            "ok": not hard_failures,
            "workflow_id": str(wf.id),
            "triggers": len(triggers),
            "conditions": conditions_run,
            "actions": actions_run,
            "failed_actions": len(hard_failures),
        }
        if not triggers and not conditions_run and not actions_run:
            summary["note"] = (
                "no enabled triggers/actions on this workflow; recorded no-op "
                "(nothing was executed — see note field so this is not a "
                "silent success)"
            )
        logger.info(
            "Scheduled fire for workflow %s: %d trigger(s), %d action(s), ok=%s",
            wf.id, len(triggers), len(actions_run), summary["ok"],
        )
        return summary


    async def find_trigger_matches(self, event: DomainEvent) -> List[TriggerMatch]:
        """Active workflows whose event trigger matches this domain event.

        A trigger matches when:
          - trigger_type == "event" and it is enabled
          - its spec.event equals the incoming event type
            (spec.event in (None, "*") matches any event, mirroring the
            CRM executor's wildcard semantics)
          - when the spec names a topic, it must equal the event's
            entity_type
          - the parent workflow is active and not deleted
        """
        q = (
            select(Workflow, WorkflowTrigger, WorkflowCondition)
            .join(WorkflowTrigger, WorkflowTrigger.workflow_id == Workflow.id)
            .outerjoin(
                WorkflowCondition,
                (WorkflowCondition.trigger_id == WorkflowTrigger.id)
                & (WorkflowCondition.is_deleted == False),  # noqa: E712
            )
            .where(
                WorkflowTrigger.is_deleted == False,  # noqa: E712
                WorkflowTrigger.enabled == True,  # noqa: E712
                WorkflowTrigger.trigger_type == "event",
                Workflow.is_deleted == False,  # noqa: E712
                Workflow.status == "active",
            )
        )
        rows = (await self.db.execute(q)).all()

        matches: Dict[UUID, TriggerMatch] = {}
        for wf, trigger, condition in rows:
            spec = trigger.spec or {}
            spec_event = spec.get("event")
            if spec_event not in (None, "*", event.event_type):
                continue
            topic_spec = spec.get("topic")
            if topic_spec is not None and topic_spec != event.entity_type:
                continue
            entry = matches.setdefault(
                trigger.workflow_id,
                TriggerMatch(workflow=wf, trigger=trigger),
            )
            if condition is not None:
                entry.conditions.append(condition)
        return list(matches.values())

    # ---------------- execution chain ----------------

    async def _execute_workflow_for_event(
        self, match: TriggerMatch, event: DomainEvent
    ) -> Optional[ExecutionLog]:
        """Run conditions + actions for one trigger hit and log the result."""
        wf = match.workflow
        started_at = datetime.now(timezone.utc)

        # Snapshot conditions + their actions up front so a failing action
        # cannot leave us holding a half-evaluated ORM tree.
        cond_ids = [c.id for c in match.conditions]
        actions_by_cond: Dict[UUID, List[WorkflowAction]] = {}
        if cond_ids:
            acts = (
                await self.db.execute(
                    select(WorkflowAction).where(
                        WorkflowAction.condition_id.in_(cond_ids),
                        WorkflowAction.is_deleted == False,  # noqa: E712
                    )
                )
            ).scalars().all()
            for a in acts:
                actions_by_cond.setdefault(a.condition_id, []).append(a)

        context = self._build_action_context(match, event)

        condition_results: List[Dict[str, Any]] = []
        actions_run: List[Dict[str, Any]] = []

        for cond in match.conditions:
            ok = self.evaluate_condition(cond, context)
            condition_results.append({"condition_id": str(cond.id), "passed": ok})
            if not ok:
                continue
            for action in actions_by_cond.get(cond.id, []):
                result = await self.execute_action(action, context)
                result.setdefault("action_id", str(action.id))
                actions_run.append(result)

        # No conditions -> no actions are reachable (model is strictly
        # Workflow->Trigger->Condition->Action), so the run is a no-op but
        # still logged.

        output = {
            "conditions": condition_results,
            "actions": actions_run,
            "matched_event": event.event_type,
        }

        hard_failures = [a for a in actions_run if a.get("status") == "failed"]
        error = (
            f"{len(hard_failures)} action(s) failed: "
            + "; ".join(a.get("note", a.get("detail", "")) for a in hard_failures)
        ) if hard_failures else None
        succeeded = not hard_failures

        log = await self._write_execution_log(
            workflow=wf,
            trigger=match.trigger,
            event=event,
            started_at=started_at,
            output=output,
            error=error,
            succeeded=succeeded,
        )
        logger.info(
            "Workflow %s (%s) fired on event=%s: %d condition(s), %d action(s)",
            wf.id, wf.name, event.event_type,
            len(condition_results), len(actions_run),
        )
        return log

    def _build_action_context(
        self, match: TriggerMatch, event: DomainEvent
    ) -> Dict[str, Any]:
        """Merge event + trigger/workflow config into the action context.

        Config keys (workflow.config / trigger.spec):
          - persona_name: persona to sign AI replies
          - customer_id:  customer the conversation action targets
          - channel:      default channel for created conversations
        The event payload carries no message text — only ids, the intent
        type/confidence and channel context (secrets/PII stay out of the bus).
        """
        wf_cfg = (match.workflow.config or {})
        spec = (match.trigger.spec or {})
        payload = event.payload or {}
        ctx: Dict[str, Any] = {
            "event": event,
            "event_type": event.event_type,
            "entity_type": event.entity_type,
            "entity_id": str(event.entity_id) if event.entity_id else None,
            "workflow_id": str(match.workflow.id),
            "trigger_id": str(match.trigger.id),
            "persona_name": wf_cfg.get("persona_name") or spec.get("persona_name"),
            "customer_id": wf_cfg.get("customer_id") or payload.get("customer_id"),
            "channel": wf_cfg.get("channel") or spec.get("channel") or payload.get("channel"),
            "intent_type": payload.get("intent_type"),
            "intent_confidence": payload.get("confidence"),
            "conversation_id": payload.get("conversation_id"),
            "message_id": payload.get("message_id"),
            "payload": payload,
        }
        return ctx

    def evaluate_condition(
        self, cond: WorkflowCondition, context: Dict[str, Any]
    ) -> bool:
        """Evaluate one condition expression against the action context.

        Expression shape (per WorkflowCondition docstring):
            {"field": "<dotted.path>", "operator": "eq", "value": ...}

        Fields resolve against the context (event payload, intent
        type/confidence, channel, customer id, ...). ``contains`` on a
        string field does a substring match; ``regex`` uses re.search.
        Unknown fields fail strictly; unknown operators fail.
        """
        expr = cond.expression or {}
        if not expr:
            return True  # no expression -> vacuous pass

        actual = self._resolve_field(expr.get("field"), context)
        if actual is None and expr.get("field"):
            # Unknown field -> condition cannot be satisfied (strict).
            return False
        return self._compare(actual, expr.get("operator", "eq"), expr.get("value"))

    def _resolve_field(self, field: Optional[str], context: Dict[str, Any]) -> Any:
        """Resolve a dotted field path from the context (dict-level only)."""
        if not field:
            return None
        node: Any = context
        for part in field.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(part)
            if node is None:
                return None
        return node

    def _compare(self, actual: Any, operator: str, expected: Any) -> bool:
        try:
            if operator == "eq":
                return actual == expected
            if operator == "neq":
                return actual != expected
            if operator == "gt":
                return actual is not None and actual > expected
            if operator == "gte":
                return actual is not None and actual >= expected
            if operator == "lt":
                return actual is not None and actual < expected
            if operator == "lte":
                return actual is not None and actual <= expected
            if operator == "in":
                return actual in (expected or [])
            if operator == "not_in":
                return actual not in (expected or [])
            if operator == "contains":
                if isinstance(actual, (list, tuple, set)):
                    return expected in actual
                if isinstance(actual, str) and isinstance(expected, str):
                    return expected in actual
                return False
            if operator == "regex":
                if not isinstance(actual, str):
                    return False
                return re.search(expected or "", actual) is not None
            logger.warning("Unknown condition operator %r; treating as fail", operator)
            return False
        except Exception:
            logger.exception("Condition comparison raised; treating as fail")
            return False

    # ---------------- actions ----------------

    async def execute_action(
        self, action: WorkflowAction, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute one workflow action. Returns a result record.

        Action-level exceptions are captured as ``status="failed"`` records
        (never raised) so one bad action cannot abort the rest of the
        trigger's action list; the failure is observable in the ExecutionLog.
        """
        try:
            return await self._dispatch_action(action, context)
        except Exception as exc:
            logger.exception(
                "Action %s (%s) failed during execution",
                action.id, action.action_type,
            )
            return {
                "action_id": str(action.id) if action.id else None,
                "action_type": action.action_type,
                "status": "failed",
                "note": f"{type(exc).__name__}: {exc}",
            }

    async def _dispatch_action(
        self, action: WorkflowAction, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Dispatch to the concrete action handler."""
        action_type = action.action_type
        params = action.params or {}

        if action_type == "conversation":
            return await self._action_create_conversation(context, params)
        if action_type == "message":
            return await self._action_send_message(context, params)
        if action_type == "tag":
            return await self._action_tag(context, params)
        if action_type in ("notification", "custom"):
            return {
                "action_type": action_type,
                "status": "recorded",
                "note": "deferred to later wave; recorded in execution log only",
                "params_keys": sorted(params.keys()),
            }
        logger.warning("Unsupported action type %r; skipping", action_type)
        return {"action_type": action_type, "status": "skipped", "note": "unsupported"}

    async def _action_create_conversation(
        self, context: Dict[str, Any], params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a conversation record (customer scoping from context)."""
        customer_id = context.get("customer_id")
        if not customer_id:
            return {
                "action_type": "conversation",
                "status": "skipped",
                "note": "no customer_id available in context",
            }
        try:
            customer_uuid = self._coerce_uuid(customer_id)
        except (ValueError, TypeError):
            return {
                "action_type": "conversation",
                "status": "failed",
                "note": f"invalid customer_id: {customer_id!r}",
            }
        if customer_uuid is None:
            return {
                "action_type": "conversation",
                "status": "failed",
                "note": f"invalid customer_id: {customer_id!r}",
            }

        svc = ConversationService(self.db)
        data = ConversationCreate(
            customer_id=customer_uuid,
            channel=params.get("channel") or context.get("channel") or "web",
            subject=params.get("subject")
            or f"[workflow:{context['workflow_id']}] auto",
            metadata={
                "source": "workflow",
                "workflow_id": context["workflow_id"],
                "triggered_by_event": context["event"].event_type,
            },
        )
        conv = await svc.create_conversation(data)
        return {
            "action_type": "conversation",
            "status": "success",
            "conversation_id": str(conv.id),
            "channel": conv.channel,
        }

    async def _action_send_message(
        self, context: Dict[str, Any], params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate a reply and append it to a conversation.

        Target resolution order:
          1. params.conversation_id (explicit)
          2. context.conversation_id (from the triggering event payload)
          3. context.customer_id (create a fresh conversation first)
        """
        conv_id = params.get("conversation_id") or context.get("conversation_id")
        conversation: Optional[Dict[str, Any]] = None

        if conv_id:
            conversation = {"id": conv_id}
        elif context.get("customer_id"):
            sub = await self._action_create_conversation(context, params)
            if sub.get("status") != "success":
                return {**sub, "action_type": "message"}
            conversation = {"id": sub["conversation_id"]}
        else:
            return {
                "action_type": "message",
                "status": "skipped",
                "note": "no target conversation or customer in context",
            }

        # Prefer explicit template text; otherwise ask the AI responder.
        if params.get("template"):
            content = str(params["template"])
            strategy = "template-explicit"
        else:
            generated = await self.responder.generate_reply(context)
            content = generated["content"]
            strategy = generated.get("strategy", "ai")

        svc = ConversationService(self.db)
        data = MessageCreate(
            conversation_id=self._coerce_uuid(conversation["id"]),
            role="assistant",
            content=content,
            metadata={
                "source": "workflow",
                "workflow_id": context["workflow_id"],
                "strategy": strategy,
            },
        )
        msg = await svc.create_message(data)
        return {
            "action_type": "message",
            "status": "success",
            "conversation_id": str(msg.conversation_id),
            "message_id": str(msg.id),
            "strategy": strategy,
            "content_preview": content[:120],
        }

    async def _action_tag(
        self, context: Dict[str, Any], params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Attach a tag name to the customer in context."""
        from app.db.models.tag import Tag
        from app.db.models.customer import Customer

        customer_id = context.get("customer_id")
        tag_name = params.get("tag_name") or params.get("name")
        if not customer_id or not tag_name:
            return {"action_type": "tag", "status": "skipped",
                    "note": "needs customer_id + tag_name"}
        cust_uuid = self._coerce_uuid(customer_id)
        if cust_uuid is None:
            return {"action_type": "tag", "status": "failed",
                    "note": f"invalid customer_id: {customer_id!r}"}

        existing = (
            await self.db.execute(
                select(Tag).where(Tag.name == tag_name, Tag.is_deleted == False)  # noqa: E712
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = Tag(name=tag_name)
            self.db.add(existing)
            await self.db.flush()

        cust = (
            await self.db.execute(select(Customer).where(Customer.id == cust_uuid))
        ).scalar_one_or_none()
        if cust is None:
            return {"action_type": "tag", "status": "failed",
                    "note": f"customer {cust_uuid} not found"}
        if existing not in cust.tags:
            cust.tags.append(existing)
        await self.db.commit()
        return {
            "action_type": "tag",
            "status": "success",
            "tag_name": tag_name,
            "customer_id": str(cust_uuid),
        }

    @staticmethod
    def _coerce_uuid(value: Any) -> Optional[UUID]:
        """Best-effort UUID coercion; returns None instead of raising."""
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None

    # ---------------- execution logging ----------------

    async def _write_execution_log(
        self,
        workflow: Workflow,
        trigger: WorkflowTrigger,
        event: DomainEvent,
        started_at: datetime,
        output: Dict[str, Any],
        error: Optional[str],
        succeeded: bool,
    ) -> ExecutionLog:
        """Persist an ExecutionLog row for one trigger hit (observability)."""
        finished_at = datetime.now(timezone.utc)
        log = ExecutionLog(
            execution_type="workflow",
            trigger_type="event",
            status="success" if succeeded else "failed",
            workflow_id=workflow.id,
            task_id=trigger.id,
            input_params={
                "event_type": event.event_type,
                "entity_type": event.entity_type,
                "entity_id": str(event.entity_id) if event.entity_id else None,
                "payload": event.payload or {},
            },
            output_result=output,
            error_message=error,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=(finished_at - started_at).total_seconds() * 1000.0,
            metadata_={
                "bridge": "workflow-conversation",
                "trigger_id": str(trigger.id) if trigger.id else None,
                "workflow_name": workflow.name,
            },
        )
        self.db.add(log)
        await self.db.commit()
        try:
            await self.db.refresh(log)
        except Exception:  # noqa: BLE001 - refresh is best-effort after commit
            pass
        return log

    # ---------------- health ----------------

    def health(self) -> Dict[str, Any]:
        return {
            "service": "workflow-conversation-bridge",
            "supported_actions": list(self.SUPPORTED_ACTION_TYPES),
            "entity_types": list(self.CONVERSATION_ENTITY_TYPES),
        }


# =====================================================================
# Event-bus wiring
# =====================================================================

_subscribed = False


def register_workflow_conversation_subscriber() -> int:
    """Subscribe the bridge to conversation domain events (idempotent).

    Mirrors ``register_workflow_crm_subscriber``: each event is handled in
    its own DB session so the workflow side can never hold the publisher's
    transaction open. Returns the number of event types subscribed.
    """
    global _subscribed
    if _subscribed:
        return len(CONVERSATION_EVENT_TYPES)
    from app.db.session import AsyncSessionLocal

    bus = get_event_bus()

    async def _on_event(event: DomainEvent) -> None:
        db = AsyncSessionLocal()
        try:
            await WorkflowConversationBridge(db).handle_domain_event(event)
        finally:
            await db.close()

    for event_type in CONVERSATION_EVENT_TYPES:
        bus.subscribe(event_type, _on_event)
    _subscribed = True
    logger.info(
        "workflow-conversation: subscribed to %d conversation event types",
        len(CONVERSATION_EVENT_TYPES),
    )
    return len(CONVERSATION_EVENT_TYPES)


def _is_subscribed() -> bool:
    return _subscribed


def reset_workflow_conversation_subscriber() -> None:
    """Test helper: forget that the bus was wired."""
    global _subscribed
    _subscribed = False
