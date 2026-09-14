"""
Lifecycle Auto-Transition Rule Engine (t_crm_005)

The stage transition *rules* live in each stage's ``config`` JSON column
(``lifecycle_stage.config``), making them fully configurable through the
stage config API (PUT /crm/lifecycle/stages/{code}) without schema changes::

    {
        "rules": [
            {
                "on_trigger": "intent_score",
                "min_intent_score": 70,
                "target_stage_code": "高意向"
            },
            {
                "on_trigger": "status_change",
                "when_status": "qualified",
                "target_stage_code": "有效线索"
            }
        ]
    }

Signal collection is intentionally data-driven (Lead.intent_score, Lead.status)
plus a pluggable conversation-activity counter that counts recent
non-system messages. The engine is a pure function over ``(stage_configs,
signals)`` so it is unit-testable without a database.
"""
import logging
from typing import Any, Dict, List, Optional, Protocol, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.models.lifecycle import LifecycleStage
from app.db.models.lead import Lead
from app.crm.services.lifecycle import transition_lifecycle_stage

logger = logging.getLogger(__name__)

# Lead.status values that map to at least one lifecycle stage. Triggers only
# fire for these; a Lead sitting in "new" does not move automatically.
STATUS_TRIGGER_STATUSES = frozenset({"contacted", "qualified", "converted"})

# conversation_activity counts messages within this many days
CONVERSATION_ACTIVITY_DAYS = 7


class ConversationActivityProvider(Protocol):
    """Adapter interface for conversation-behavior signals.

    Business code depends on this protocol, never on the Conversation ORM
    model directly, so the signal source can be swapped without touching the
    rule engine.
    """

    async def count_recent_messages(
        self, db: AsyncSession, lead: "Lead", days: int = CONVERSATION_ACTIVITY_DAYS
    ) -> int:
        """Number of recent user/assistant messages for the lead's conversation."""
        ...


class DefaultConversationActivityProvider:
    """SQLAlchemy implementation of :class:`ConversationActivityProvider`.

    Lead.source_type == 'conversation' and Lead.source_id is the
    conversation id. Counts non-system messages in the last N days.
    """

    async def count_recent_messages(
        self, db: AsyncSession, lead: "Lead", days: int = CONVERSATION_ACTIVITY_DAYS
    ) -> int:
        if lead.source_type != "conversation" or not lead.source_id:
            return 0
        from datetime import datetime, timedelta, timezone
        from uuid import UUID as _UUID
        from app.db.models.conversation import Message

        since = datetime.now(timezone.utc) - timedelta(days=days)
        try:
            conv_uuid = _UUID(lead.source_id)
        except (ValueError, AttributeError, TypeError):
            return 0
        result = await db.execute(
            select(func.count(Message.id))
            .where(
                Message.conversation_id == conv_uuid,
                Message.created_at >= since,
                Message.role != "system",
            )
        )
        return int(result.scalar() or 0)


def build_signals(
    intent_score: Optional[int],
    status: Optional[str],
    conversation_activity: int = 0,
) -> Dict[str, Any]:
    """Collect the signal set the rule engine evaluates against."""
    return {
        "intent_score": intent_score if intent_score is not None else 0,
        "status": status,
        "conversation_activity": conversation_activity,
    }


def match_stage_for_signals(
    stage_configs: Dict[str, List[Dict[str, Any]]],
    signals: Dict[str, Any],
) -> Optional[str]:
    """Return the target stage code for the first matching rule, else None.

    ``stage_configs`` maps ``stage_code -> list of rule dicts`` (the
    ``rules`` array of each stage's config). Rules are evaluated in
    declaration order per stage, stages in their stored order; the FIRST
    matching rule wins and its ``target_stage_code`` is returned.
    """
    intent_score = int(signals.get("intent_score") or 0)
    status = signals.get("status")
    activity = int(signals.get("conversation_activity") or 0)

    for rules in stage_configs.values():
        for rule in rules:
            trigger = rule.get("on_trigger")
            matched = False
            if trigger == "intent_score":
                matched = intent_score >= int(rule.get("min_intent_score", 0))
            elif trigger == "status_change":
                when_status = rule.get("when_status")
                matched = (
                    status == when_status
                    if when_status is not None
                    else status in STATUS_TRIGGER_STATUSES
                )
            elif trigger == "conversation_activity":
                matched = activity >= int(rule.get("min_messages", 1))
            else:
                # Unknown trigger type: log and skip, never crash the flow.
                logger.warning(
                    "unknown lifecycle auto-transition trigger '%s'; rule skipped",
                    trigger,
                )
                continue
            if matched:
                target = rule.get("target_stage_code")
                if target:
                    return target
    return None


def stage_config_rules(config: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract the validated rules array from a stage config, tolerating garbage."""
    if not isinstance(config, dict):
        return []
    rules = config.get("rules")
    if not isinstance(rules, list):
        return []
    return [r for r in rules if isinstance(r, dict)]


async def apply_auto_transitions(
    db: AsyncSession,
    lead: "Lead",
    activity_provider: Optional[ConversationActivityProvider] = None,
    skip_stages: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Evaluate configured auto-transition rules and apply matching ones.

    Returns the list of transition log dicts that were created (empty when
    no rule matched or nothing changed). A failed transition is logged and
    re-raised so the caller (which shares the same session/commit) can roll
    back the lead update that triggered it.

    ``skip_stages`` lists stage codes to exclude from evaluation — used when
    the caller just set the lead to that stage and wants to avoid the rule
    that produced it firing immediately.
    """
    # 1) Load active stage configs (single query). Defensive: a result that is
    # not a normal SQLAlchemy RowMapping (e.g. an AsyncMock in unit tests)
    # degrades to "no rules" instead of raising.
    stages_result = await db.execute(
        select(LifecycleStage.code, LifecycleStage.config).where(
            LifecycleStage.is_deleted == False
        )
    )
    try:
        rows = stages_result.all()
        stage_configs: Dict[str, List[Dict[str, Any]]] = {
            code: stage_config_rules(config) for code, config in rows
        }
    except Exception:
        logger.debug("stage config query returned unexpected shape; auto-transition skipped")
        return []

    # If no stage carries any rule, nothing can match — bail out without
    # building signals. This also keeps the function side-effect free on
    # systems where rule configuration has not been seeded yet.
    if not any(stage_configs.values()):
        return []

    # 2) Collect signals.
    provider = activity_provider or DefaultConversationActivityProvider()
    activity = await provider.count_recent_messages(db, lead)
    signals = build_signals(lead.intent_score, lead.status, activity)

    # 3) Match the first applicable rule.
    skip = set(skip_stages or [])
    candidate_configs = {k: v for k, v in stage_configs.items() if k not in skip}
    target = match_stage_for_signals(candidate_configs, signals)

    if not target or target == lead.lifecycle_stage_code:
        return []

    # Guard: the matched target must be a currently-active stage, otherwise a
    # stale rule pointing at a soft-deleted/nonexistent code would write a
    # dangling lifecycle_stage_code onto the Lead.
    active_codes = set(stage_configs.keys())
    if target not in active_codes:
        logger.warning(
            "auto-transition target stage '%s' is not an active stage; skipping",
            target,
        )
        return []

    # 4) Apply via the standard transition service (logs + domain event).
    return [
        await transition_lifecycle_stage(
            db,
            lead.id,
            target,
            reason="auto_rule",
            operator="system",
            metadata={
                "signals": signals,
                "applied_rule_target": target,
            },
        )
    ]
