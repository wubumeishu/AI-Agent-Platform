"""API integration tests for the Decision Engine router (schema + service wiring).

Follows the convention of tests/test_intent_api.py and tests/test_memory_api.py:
schema validation, service-level integration (with MockDBSession), and route
registration. No real DB / no live LLM.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.schemas.decision import (
    DecisionRequest,
    DecisionResponse,
    PersonaStyleRequest,
    ContextBuildRequest,
    ValidationRequest,
    FallbackDecisionResponse,
)
from app.services.decision_service import DecisionService
from app.routers.decision import router as decision_router


class MockDBSession:
    def __init__(self):
        self.commits = 0
        self.added = []

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, query):
        class MockResult:
            def scalar_one_or_none(self):
                return None

            def scalars(self):
                class MockScalars:
                    def all(self):
                        return []
                return MockScalars()

            def scalar(self):
                return 0
        return MockResult()


# =====================================================================
# Schema validation
# =====================================================================

class TestDecisionSchemaValidation:
    def test_decision_request_requires_message(self):
        req = DecisionRequest(message="你好")
        assert req.message == "你好"
        assert req.use_llm is False

    def test_decision_request_rejects_empty_message(self):
        with pytest.raises(Exception):
            DecisionRequest(message="")

    def test_decision_request_max_length(self):
        with pytest.raises(Exception):
            DecisionRequest(message="x" * 5001)

    def test_intent_confidence_range(self):
        with pytest.raises(Exception):
            DecisionRequest(message="x", intent_type="q", intent_confidence=1.5)
        ok = DecisionRequest(message="x", intent_type="q", intent_confidence=0.9)
        assert ok.intent_confidence == 0.9

    def test_persona_style_request_min_name(self):
        req = PersonaStyleRequest(persona_name="A")
        assert req.personality == {}

    def test_context_build_request_bounds(self):
        req = ContextBuildRequest(conversation_id=uuid4(), current_message="hi")
        assert req.max_tokens == 4000
        with pytest.raises(Exception):
            ContextBuildRequest(conversation_id=uuid4(), current_message="hi", max_tokens=100)

    def test_validation_request_requires_fields(self):
        req = ValidationRequest(response_text="ok", user_message="hi", intent_type="question")
        assert req.intent_type == "question"
        with pytest.raises(Exception):
            ValidationRequest(response_text="", user_message="hi", intent_type="q")

    def test_fallback_response_shape(self):
        f = FallbackDecisionResponse(success=True, action_type="a", response_text="t", reason="r")
        assert f.strategy == "fallback"


# =====================================================================
# Service-level integration (DB + no-DB)
# =====================================================================

class TestDecisionServiceIntegration:
    @pytest.mark.asyncio
    async def test_decide_returns_full_decision(self):
        svc = DecisionService(db=MockDBSession())
        r = await svc.decide(DecisionRequest(
            message="你好", intent_type="greeting", intent_confidence=0.95,
            context={"persona_name": "小助手"},
        ))
        assert r.success is True
        assert r.strategy in ("rule_based", "llm", "fallback")
        assert r.explanation.reasoning_steps
        assert r.quality_score is not None

    @pytest.mark.asyncio
    async def test_decide_high_stakes_escalates(self):
        svc = DecisionService(db=None)
        r = await svc.decide(DecisionRequest(
            message="我要投诉", intent_type="complaint", intent_confidence=0.95,
        ))
        assert r.strategy == "fallback"
        assert r.explanation.fallback_used is True

    @pytest.mark.asyncio
    async def test_persona_style_with_db(self):
        svc = DecisionService(db=MockDBSession())
        out = await svc.generate_persona_style(
            PersonaStyleRequest(persona_name="S", personality={"casual": True})
        )
        assert out.persona_name == "S"
        assert out.system_prompt

    def test_build_context_sync(self):
        svc = DecisionService(db=None)
        out = svc.build_context(ContextBuildRequest(
            conversation_id=uuid4(), current_message="hi"))
        assert out.conversation_id

    def test_validate_response_sync(self):
        svc = DecisionService(db=None)
        out = svc.validate_response(ValidationRequest(
            response_text="您好，为您办理。", user_message="帮我办理", intent_type="command"))
        assert out.overall_score is not None
        assert out.dimensions

    def test_get_fallback_sync(self):
        svc = DecisionService(db=None)
        out = svc.get_fallback("thanks", persona_name="A")
        assert out.action_type == "acknowledge_thanks"

    @pytest.mark.asyncio
    async def test_decision_history_returns_list(self):
        svc = DecisionService(db=MockDBSession())
        out = await svc.get_decision_history(uuid4(), limit=10)
        assert out == []


# =====================================================================
# Router registration
# =====================================================================

class TestDecisionRouter:
    def test_expected_routes_present(self):
        paths = [r.path for r in decision_router.routes]
        assert "/api/v1/decision/decide" in paths
        assert "/api/v1/decision/persona-style" in paths
        assert "/api/v1/decision/context" in paths
        assert "/api/v1/decision/validate" in paths
        assert "/api/v1/decision/fallback" in paths
        assert "/api/v1/decision/health" in paths
        assert "/api/v1/decision/history/{conversation_id}" in paths

    def test_router_tags(self):
        assert "Decision Engine" in decision_router.tags

    def test_router_paths_are_wellformed(self):
        """My router is self-contained and well-formed.

        NOTE: we deliberately do NOT import `app.main` here. `main.py` is a
        shared file that parallel tasks keep editing; a sibling task's not-yet-
        landed schema (e.g. app.schemas.workflow) can break its import at any
        moment, which must not destabilize this module's own tests.
        """
        decision_paths = [r.path for r in decision_router.routes]
        assert decision_paths, "decision router has no routes"
        for p in decision_paths:
            assert p.startswith("/api/v1/decision"), f"unexpected prefix: {p}"

    def test_service_dependency_resolves(self):
        from app.routers.decision import get_decision_service
        # The dependency factory should construct a service (DB may be None in tests).
        svc = get_decision_service(db=None)
        assert isinstance(svc, DecisionService)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
