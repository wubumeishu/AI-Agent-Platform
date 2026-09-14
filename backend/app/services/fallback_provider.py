"""Fallback Mechanism - Stable behavior when the LLM is unavailable

Provides deterministic, safe, helpful responses for each intent type when
the LLM provider is unavailable, times out, or returns an unusable result.

Design principles:
- Pure Python: no external dependencies, fully testable offline.
- Explainable: each fallback records the reason it was used.
- Persona-aware: can layer a persona's name into the response.
- Safe: never fabricates facts; escalates appropriately for high-stakes intents
  (complaint, escalation, callback_request).

This is the last-resort half of the core pipeline:
    LLM unavailable → [Fallback] → safe default response
"""
import logging
from typing import List, Dict, Any, Optional

from app.schemas.decision import FallbackDecisionResponse

logger = logging.getLogger(__name__)


# Per-intent fallback templates. Each maps an intent type to a safe default
# response and the action type that downstream systems should execute.
# `{name}` is replaced with the persona name when provided.
_FALLBACK_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "greeting": {
        "response_template": "{name}：您好！很高兴见到您，请问有什么可以帮您的吗？",
        "action_type": "respond_greeting",
        "escalate": False,
    },
    "question": {
        "response_template": (
            "{name}：收到您的问题。我暂时无法直接给出完整答案，"
            "建议您可以先查看帮助中心，或留下联系方式，我们会尽快回复您。"
        ),
        "action_type": "answer_question",
        "escalate": False,
    },
    "command": {
        "response_template": (
            "{name}：您的指令我已记录。当前暂时无法自动执行，"
            "请稍候，或稍后再试一次，我会为您跟进。"
        ),
        "action_type": "execute_command",
        "escalate": False,
    },
    "complaint": {
        "response_template": (
            "{name}：非常抱歉给您带来不好的体验。我已记录您的问题，"
            "将尽快为您升级处理。若需要，我可以为您转接人工客服。"
        ),
        "action_type": "handle_complaint",
        "escalate": True,
    },
    "thanks": {
        "response_template": "{name}：不客气，很高兴能帮到您！还有什么需要吗？",
        "action_type": "acknowledge_thanks",
        "escalate": False,
    },
    "farewell": {
        "response_template": "{name}：祝您一切顺利，期待再次为您服务，再见！",
        "action_type": "respond_farewell",
        "escalate": False,
    },
    "clarification": {
        "response_template": (
            "{name}：请允许我再说明一下。由于暂时无法展开详细解释，"
            "我可以先为您转接人工客服，由专人为您逐项说明。"
        ),
        "action_type": "provide_clarification",
        "escalate": False,
    },
    "escalation": {
        "response_template": (
            "{name}：明白，正在为您转接人工客服，请稍候。"
            "您的请求已被标记为优先处理。"
        ),
        "action_type": "escalate",
        "escalate": True,
    },
    "callback_request": {
        "response_template": (
            "{name}：好的，收到您的回电请求。请提供方便联系的电话和时间段，"
            "我们会尽快安排。"
        ),
        "action_type": "schedule_callback",
        "escalate": True,
    },
    "follow_up": {
        "response_template": (
            "{name}：好的，我们继续之前的话题。由于上下文较长，"
            "能否请您简要重述一下关键信息？我接着为您解答。"
        ),
        "action_type": "continue_conversation",
        "escalate": False,
    },
    "feedback": {
        "response_template": (
            "{name}：感谢您的反馈！已记录，我们会认真考虑并持续改进。"
        ),
        "action_type": "collect_feedback",
        "escalate": False,
    },
    "task_completion": {
        "response_template": "{name}：好的，任务已完成！还有其他需要帮助的吗？",
        "action_type": "confirm_completion",
        "escalate": False,
    },
    "unknown": {
        "response_template": (
            "{name}：抱歉，我暂时没能理解您的意思。能否请您换个说法，"
            "或告诉我更多细节？我也可以为您转接人工客服。"
        ),
        "action_type": "unknown",
        "escalate": False,
    },
}

_DEFAULT_REASON = "LLM provider unavailable"


class FallbackProvider:
    """Return safe, intent-appropriate responses when the LLM is down."""

    def __init__(self, reason: str = _DEFAULT_REASON):
        self.reason = reason

    def is_available(self) -> bool:
        """Fallback is always available — that is its whole purpose."""
        return True

    def get_fallback(
        self,
        intent_type: Optional[str] = "unknown",
        *,
        persona_name: Optional[str] = "AI 助手",
        entities: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
    ) -> FallbackDecisionResponse:
        """Build a fallback response for the given intent.

        Args:
            intent_type: which intent this response should satisfy.
            persona_name: persona name to layer into the response.
            entities: extracted entities (currently informational).
            context: additional context (informational, e.g. language hint).
            reason: override for why the fallback fired.
        """
        key = (intent_type or "unknown").strip().lower()
        template = _FALLBACK_TEMPLATES.get(key, _FALLBACK_TEMPLATES["unknown"])

        name = persona_name or "AI 助手"
        response_text = template["response_template"].format(name=name)

        metadata: Dict[str, Any] = {
            "fallback": True,
            "intent_type": key,
            "escalate": template["escalate"],
            "entities": entities or {},
        }
        if context:
            metadata["context"] = context

        logger.warning(
            "Fallback engaged for intent=%s (%s)", key, reason or self.reason
        )

        return FallbackDecisionResponse(
            success=True,
            action_type=template["action_type"],
            response_text=response_text,
            strategy="fallback",
            reason=reason or self.reason,
            metadata=metadata,
        )

    def list_intent_coverage(self) -> List[str]:
        """Return the set of intent types with dedicated fallback templates."""
        return sorted(_FALLBACK_TEMPLATES.keys())

    def health(self) -> Dict[str, Any]:
        """Self-report for observability."""
        return {
            "service": "fallback-provider",
            "available": True,
            "intents_covered": len(_FALLBACK_TEMPLATES),
            "intents": self.list_intent_coverage(),
        }
