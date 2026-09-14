"""Decision Service - orchestration layer for the AI decision engine.

Wires the pure, testable components (DecisionEngine, ContextBuilder,
PersonaStyleGenerator, ResponseValidator, FallbackProvider) to optional
database persistence (DecisionLog, Persona).

Design:
- The service works WITHOUT a DB (db=None): all pure logic still runs.
- When a DB session is provided, decisions are persisted to DecisionLog for
  auditability, and persona entities are resolved by ID for style generation.
- LLM provider is injected optionally; absent → rule/fallback path (safe).

This keeps AI logic separated from platform logic (a core mandate): the pure
engine is the reusable, testable core; this service is the thin platform
adapter.
"""
import logging
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.decision import DecisionLog
from app.db.models.persona import Persona
from app.schemas.decision import (
    DecisionRequest,
    DecisionResponse,
    PersonaStyleRequest,
    PersonaStyleResponse,
    ContextBuildRequest,
    ContextBuildResponse,
    ValidationRequest,
    ValidationResponse,
    FallbackDecisionResponse,
)
from app.services.decision_engine import DecisionEngine
from app.services.context_builder import ContextBuilder
from app.services.persona_style_generator import PersonaStyleGenerator
from app.services.response_validator import ResponseValidator
from app.services.fallback_provider import FallbackProvider

logger = logging.getLogger(__name__)


class DecisionService:
    """Platform adapter over the pure decision engine."""

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        *,
        llm_provider: Optional[Any] = None,
        validator_threshold: Optional[float] = None,
    ):
        self.db = db
        self.validator = ResponseValidator(threshold=validator_threshold)
        self.engine = DecisionEngine(
            validator=self.validator,
            fallback_provider=FallbackProvider(),
            llm_provider=llm_provider,
        )
        self.context_builder = ContextBuilder()
        self.persona_style_generator = PersonaStyleGenerator()
        self.fallback = FallbackProvider()

    # ---------- Decision (with optional persistence) ----------

    async def decide(self, request: DecisionRequest) -> DecisionResponse:
        """Make a decision; persist to DecisionLog when a DB session exists."""
        response = await self.engine.decide(request)

        if self.db is not None:
            try:
                await self._persist_decision(request, response)
            except Exception as exc:  # noqa: BLE001 — persistence must not break decisions
                logger.warning("Failed to persist decision log: %s", exc)

        return response

    async def _persist_decision(
        self, request: DecisionRequest, response: DecisionResponse
    ) -> DecisionLog:
        log = DecisionLog(
            conversation_id=request.conversation_id,
            customer_id=request.customer_id,
            persona_id=request.persona_id,
            intent_type=response.explanation.intent_type,
            intent_confidence=response.explanation.intent_confidence,
            strategy=response.strategy,
            action_type=response.action_type,
            response_text=response.response_text,
            fallback_used=response.explanation.fallback_used,
            fallback_reason=response.explanation.fallback_reason,
            quality_score=response.quality_score,
            quality_passed=response.quality_passed,
            explanation={
                "strategy": response.explanation.strategy,
                "matched_rule": response.explanation.matched_rule,
                "reasoning_steps": response.explanation.reasoning_steps,
                "fallback_used": response.explanation.fallback_used,
                "fallback_reason": response.explanation.fallback_reason,
            },
            input_snapshot={
                "message": request.message,
                "entities": request.entities,
                "context": request.context,
            },
            processing_time_ms=response.processing_time_ms,
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        logger.info("Persisted decision log %s", log.id)
        return log

    # ---------- Persona Style ----------

    async def generate_persona_style(
        self,
        request: PersonaStyleRequest,
    ) -> PersonaStyleResponse:
        """Generate a conversation style from a persona.

        If a persona_id is supplied and a DB session is available, the persona
        is resolved from the database; otherwise the raw fields are used.
        """
        persona_id = request.persona_id
        if persona_id and self.db is not None:
            persona = await self._load_persona(persona_id)
            if persona is not None:
                return self.persona_style_generator.generate(
                    persona_id=persona.id,
                    persona_name=persona.name,
                    description=persona.description,
                    personality=persona.personality or {},
                )
        # No persona resolved → use the raw request fields (graceful).
        return self.persona_style_generator.generate(request)

    async def _load_persona(self, persona_id: UUID) -> Optional[Persona]:
        result = await self.db.execute(
            select(Persona).where(
                Persona.id == persona_id,
                Persona.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    # ---------- Context Building ----------

    def build_context(self, request: ContextBuildRequest) -> ContextBuildResponse:
        """Build a token-budgeted conversation context block."""
        return self.context_builder.build_context(request)

    # ---------- Response Validation ----------

    def validate_response(self, request: ValidationRequest) -> ValidationResponse:
        """Validate a generated response's quality (0-5 score + pass/fail)."""
        return self.validator.validate(request)

    # ---------- Fallback ----------

    def get_fallback(
        self,
        intent_type: str = "unknown",
        *,
        persona_name: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> FallbackDecisionResponse:
        """Return a safe fallback response for an intent (LLM-down path)."""
        return self.fallback.get_fallback(
            intent_type, persona_name=persona_name, reason=reason
        )

    # ---------- Audit / History ----------

    async def get_decision_history(
        self,
        conversation_id: UUID,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return recent decision logs for a conversation (newest first)."""
        if self.db is None:
            return []
        result = await self.db.execute(
            select(DecisionLog)
            .where(
                DecisionLog.conversation_id == conversation_id,
                DecisionLog.is_deleted == False,  # noqa: E712
            )
            .order_by(DecisionLog.created_at.desc())
            .limit(limit)
        )
        logs = result.scalars().all()
        return [self._decision_log_to_dict(l) for l in logs]

    @staticmethod
    def _decision_log_to_dict(log: DecisionLog) -> Dict[str, Any]:
        return {
            "id": str(log.id),
            "conversation_id": str(log.conversation_id) if log.conversation_id else None,
            "persona_id": str(log.persona_id) if log.persona_id else None,
            "intent_type": log.intent_type,
            "intent_confidence": log.intent_confidence,
            "strategy": log.strategy,
            "action_type": log.action_type,
            "response_text": log.response_text,
            "fallback_used": log.fallback_used,
            "fallback_reason": log.fallback_reason,
            "quality_score": log.quality_score,
            "quality_passed": log.quality_passed,
            "explanation": log.explanation,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }

    # ---------- Health ----------

    def health(self) -> Dict[str, Any]:
        """Self-report for observability / integration tests."""
        return {
            "service": "decision-service",
            "engine": self.engine.health(),
            "fallback": self.fallback.health(),
            "db_enabled": self.db is not None,
        }
