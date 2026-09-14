"""Decision Engine - Rule + LLM Hybrid Decision & Conversation Generation

The orchestrator of the AI intelligence layer. Implements the core pipeline:

    Understand (intent) → Remember (context/memories) → Determine state
    → Select strategy (rule | LLM | fallback) → Select action
    → Generate response → Evaluate (validate quality)

Strategy selection (deterministic, explainable):
    1. If `use_llm=True` AND a healthy LLM provider is wired AND rules do not
       say to escalate → try the LLM path; on any failure → fallback.
    2. If intent confidence is low (< 0.6) OR intent says escalate
       (complaint/escalation/callback_request) → rule-based safe fallback
       (never risk an LLM hallucination on high-stakes intents).
    3. Default: rule/template-based response (fast, deterministic, offline-safe).

The LLM provider is an *optional injected dependency*. When absent or failing,
the engine falls back transparently. This makes the engine fully testable
offline (no live LLM) and robust in production (always a safe answer).

Every decision returns a DecisionResponse that carries an explainable
`explanation` (strategy, reasoning steps, fallback reason) and a
`quality_score` from the ResponseValidator.
"""
import logging
import time
from typing import List, Optional, Dict, Any, Protocol

from app.schemas.decision import (
    DecisionRequest,
    DecisionResponse,
    DecisionExplanation,
)
from app.services.fallback_provider import FallbackProvider
from app.services.response_validator import ResponseValidator
from app.schemas.decision import ValidationRequest

logger = logging.getLogger(__name__)


# Intents that are high-stakes: for these, the rule-based fallback is the
# *safe* path (we would rather hand off to a human than risk an LLM error).
ESCALATING_INTENTS = {"complaint", "escalation", "callback_request"}

# Below this intent confidence we distrust auto-generation and use a safe
# clarification/escalation fallback instead.
LOW_CONFIDENCE_THRESHOLD = 0.6


class LLMProvider(Protocol):
    """Minimal protocol for an injectable LLM provider.

    A provider must expose:
      - `healthy() -> bool`  (is the provider currently usable?)
      - `complete(system_prompt, messages) -> str`  (non-streaming completion)

    This lets the Decision Engine stay provider-agnostic: any provider that
    satisfies this protocol (or a thin adapter) can be wired in.
"""
    def healthy(self) -> bool: ...
    async def complete(self, system_prompt: str, messages: List[Dict[str, Any]]) -> str: ...


class DecisionEngine:
    """Rule + LLM hybrid decision engine with explainable, validated output."""

    def __init__(
        self,
        *,
        fallback_provider: Optional[FallbackProvider] = None,
        validator: Optional[ResponseValidator] = None,
        llm_provider: Optional[Any] = None,
        low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
    ):
        self.fallback = fallback_provider or FallbackProvider()
        self.validator = validator or ResponseValidator()
        self.llm_provider = llm_provider
        self.low_confidence_threshold = low_confidence_threshold

    # ---------- Public API ----------

    async def decide(self, request: DecisionRequest) -> DecisionResponse:
        """Produce an explainable, validated decision for the request."""
        start = time.time()

        # Step 1: Determine intent (from pre-classified request, or a default).
        intent_type, intent_confidence = self._resolve_intent(request)

        # Step 2: Select strategy.
        strategy, fallback_reason = self._select_strategy(intent_type, intent_confidence, request)

        # Step 3: Generate the response per the selected strategy.
        reasoning: List[str] = []
        reasoning.append(f"Resolved intent: {intent_type} (confidence {intent_confidence:.2f})")

        if strategy == "llm":
            response_text, action_type, llm_ok = await self._llm_complete(request, intent_type)
            if llm_ok and response_text:
                reasoning.append("Generated response via LLM provider")
            else:
                # LLM failed → transparently fall back (explainability).
                strategy = "fallback"
                fallback_reason = fallback_reason or "LLM provider returned no usable result"
                reasoning.append(f"LLM unavailable/failed → fallback ({fallback_reason})")

        if strategy in ("fallback", "rule_based"):
            fb = self.fallback.get_fallback(
                intent_type,
                persona_name=self._persona_name(request),
                entities=request.entities,
                context=request.context,
                reason=fallback_reason,
            )
            response_text = fb.response_text
            action_type = fb.action_type
            reasoning.append(
                f"Applied rule/template fallback for '{intent_type}' "
                f"(strategy={strategy})"
            )

        # Step 4: Evaluate the response quality.
        quality = self.validator.validate(
            ValidationRequest(
                response_text=response_text,
                user_message=request.message,
                intent_type=intent_type,
                persona_name=self._persona_name(request),
                personality=request.context.get("personality", {}),
            )
        )
        reasoning.append(
            f"Validated quality: {quality.overall_score:.2f}/5 "
            f"(passed={quality.passed}, issues={len(quality.issues)})"
        )

        explanation = DecisionExplanation(
            strategy=strategy,
            intent_type=intent_type,
            intent_confidence=intent_confidence,
            matched_rule=f"{intent_type} → {action_type}" if strategy in ("fallback", "rule_based") else None,
            reasoning_steps=reasoning,
            fallback_used=strategy == "fallback",
            fallback_reason=fallback_reason,
        )

        processing_ms = (time.time() - start) * 1000

        return DecisionResponse(
            success=True,
            action_type=action_type,
            response_text=response_text,
            strategy=strategy,
            explanation=explanation,
            quality_score=quality.overall_score,
            quality_passed=quality.passed,
            metadata={
                "quality_issues": quality.issues,
                "quality_dimensions": {
                    d.name: round(d.score, 2) for d in quality.dimensions
                },
            },
            processing_time_ms=round(processing_ms, 2),
        )

    def health(self) -> Dict[str, Any]:
        """Self-report for observability / integration tests."""
        return {
            "service": "decision-engine",
            "llm_available": self.llm_provider is not None and self._llm_healthy(),
            "fallback_available": self.fallback.is_available(),
            "validator_threshold": self.validator.threshold,
        }

    # ---------- Strategy selection (deterministic, explainable) ----------

    def _resolve_intent(self, request: DecisionRequest) -> tuple[str, float]:
        """Resolve intent from the request (pre-classified, else default)."""
        if request.intent_type:
            confidence = request.intent_confidence
            if confidence is None:
                # No confidence given; trust the explicit intent at a moderate floor.
                confidence = 0.8
            return request.intent_type.strip().lower(), confidence
        # No intent supplied → treat as unknown and let the fallback clarify.
        return "unknown", 0.3

    def _select_strategy(
        self,
        intent_type: str,
        intent_confidence: float,
        request: DecisionRequest,
    ) -> tuple[str, Optional[str]]:
        """Pick the strategy and the reason any fallback was forced.

        Returns (strategy, fallback_reason). strategy is one of:
          - "llm": use the LLM provider (must be healthy and requested/allowed)
          - "rule_based": use rule/template generation (deterministic)
          - "fallback": force a safe fallback (high-stakes or low-confidence)
        """
        fallback_reason: Optional[str] = None

        # High-stakes intents always go to a safe fallback for stability.
        if intent_type in ESCALATING_INTENTS:
            return "fallback", f"High-stakes intent '{intent_type}': forced safe fallback"

        # Low confidence → don't trust auto-generation; use a safe fallback.
        if intent_confidence < self.low_confidence_threshold:
            return "fallback", (
                f"Intent confidence {intent_confidence:.2f} < "
                f"{self.low_confidence_threshold}: forced safe fallback"
            )

        # LLM path only when explicitly requested AND a healthy provider is wired.
        if request.use_llm and self.llm_provider is not None and self._llm_healthy():
            return "llm", None

        # Default: deterministic rule/template generation (offline-safe).
        return "rule_based", None

    # ---------- LLM path (optional, provider-agnostic) ----------

    async def _llm_complete(
        self, request: DecisionRequest, intent_type: str
    ) -> tuple[str, str, bool]:
        """Await the LLM provider; return (text, action_type, ok). Never raises."""
        if self.llm_provider is None:
            return "", intent_type, False
        try:
            if not self._llm_healthy():
                return "", intent_type, False
            system_prompt = self._build_llm_system_prompt(request, intent_type)
            messages = self._build_llm_messages(request, intent_type)
            text = await self.llm_provider.complete(system_prompt, messages)
            if not text or not text.strip():
                return "", intent_type, False
            return text.strip(), intent_type, True
        except Exception as exc:  # noqa: BLE001 — provider failure must not crash the engine
            logger.warning("LLM completion failed, falling back: %s", exc)
            return "", intent_type, False

    def _build_llm_system_prompt(self, request: DecisionRequest, intent_type: str) -> str:
        name = self._persona_name(request)
        personality = request.context.get("personality", {})
        trait_lines = "\n".join(f"- {k}: {v}" for k, v in (personality or {}).items())
        return (
            f"You are {name}, replying to a customer whose intent is '{intent_type}'.\n"
            f"{trait_lines}\n"
            "Be accurate and helpful; never fabricate facts. "
            "If you cannot answer confidently, say so plainly."
        )

    def _build_llm_messages(
        self, request: DecisionRequest, intent_type: str
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        ctx_messages = request.context.get("messages") or []
        for m in ctx_messages[-10:]:
            messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        messages.append({"role": "user", "content": request.message})
        return messages

    def _llm_healthy(self) -> bool:
        if self.llm_provider is None:
            return False
        healthy = getattr(self.llm_provider, "healthy", None)
        if callable(healthy):
            try:
                return bool(healthy())
            except Exception:  # noqa: BLE001
                return False
        return True

    def _persona_name(self, request: DecisionRequest) -> str:
        return request.context.get("persona_name") or "AI 助手"
