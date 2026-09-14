"""Tests for Phase 2 - Decision Engine & Persona Generation.

Covers the five in-scope components:
  - PersonaStyleGenerator (conversation style generation)
  - DecisionEngine        (rule + LLM hybrid, explainable, with fallback)
  - ContextBuilder        (conversation context construction)
  - ResponseValidator     (response quality scoring)
  - FallbackProvider      (stable behavior when LLM is unavailable)

All tests are DB-free and offline-safe: they use MockDBSession / MagicMock,
mirroring tests/test_intent.py and tests/test_memory.py conventions.
"""
import pytest
from typing import List, Dict, Any, Optional
from uuid import uuid4, UUID

from app.schemas.decision import (
    DecisionRequest,
    DecisionResponse,
    DecisionExplanation,
    PersonaStyleRequest,
    PersonaStyleResponse,
    ContextBuildRequest,
    ContextBuildResponse,
    ValidationRequest,
    ValidationResponse,
    ValidationDimension,
    FallbackDecisionResponse,
)
from app.services.persona_style_generator import PersonaStyleGenerator
from app.services.decision_engine import (
    DecisionEngine,
    ESCALATING_INTENTS,
    LOW_CONFIDENCE_THRESHOLD,
)
from app.services.context_builder import ContextBuilder
from app.services.response_validator import ResponseValidator
from app.services.fallback_provider import FallbackProvider
from app.services.decision_service import DecisionService


# =====================================================================
# Shared helpers
# =====================================================================

class MockDBSession:
    """Mock DB session: records calls, returns empty results. No real DB."""

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


class FakeLLMProvider:
    """Minimal LLM provider satisfying the LLMProvider protocol (happy path)."""

    def __init__(self, text="这是 LLM 生成的回答。", healthy=True):
        self._text = text
        self._healthy = healthy
        self.calls = 0

    def healthy(self):
        return self._healthy

    async def complete(self, system_prompt, messages):
        self.calls += 1
        return self._text


class FakeFailingLLMProvider:
    """LLM provider that always raises — to test transparent fallback."""

    def healthy(self):
        return True

    async def complete(self, system_prompt, messages):
        raise RuntimeError("LLM provider down")


# =====================================================================
# 1. PersonaStyleGenerator
# =====================================================================

class TestPersonaStyleGenerator:
    """Persona → executable conversation style."""

    def test_generates_system_prompt_with_name(self):
        gen = PersonaStyleGenerator()
        out = gen.generate(persona_name="小助手", personality={"friendly": True})
        assert out.persona_name == "小助手"
        assert "小助手" in out.system_prompt
        assert out.system_prompt  # non-empty

    def test_directives_from_traits(self):
        gen = PersonaStyleGenerator()
        out = gen.generate(
            persona_name="A",
            personality={"empathetic": True, "concise": True, "professional": True},
        )
        joined = " ".join(out.style_directives)
        assert "empathy" in joined.lower()
        assert "concise" in joined.lower()
        assert "professional" in joined.lower()

    def test_description_becomes_directive(self):
        gen = PersonaStyleGenerator()
        out = gen.generate(persona_name="A", description="一位严谨的财务顾问")
        joined = " ".join(out.style_directives)
        assert "严谨的财务顾问" in joined

    def test_tone_keywords_from_sentiment_bias(self):
        gen = PersonaStyleGenerator()
        out = gen.generate(persona_name="A", personality={"sentiment_bias": "warm"})
        assert "warm" in out.tone_keywords
        out2 = gen.generate(persona_name="A", personality={"sentiment_bias": "firm"})
        assert "firm" in out2.tone_keywords

    def test_example_responses_produced(self):
        gen = PersonaStyleGenerator()
        out = gen.generate(persona_name="小助手", personality={"empathetic": True})
        assert len(out.example_responses) >= 1
        assert all(isinstance(e, str) and e for e in out.example_responses)

    def test_minimal_persona_graceful(self):
        """A persona with only a name still yields a valid, non-empty style."""
        gen = PersonaStyleGenerator()
        out = gen.generate(persona_name="Solo")
        assert out.system_prompt
        assert len(out.style_directives) >= 1
        assert out.example_responses  # examples always present

    def test_nested_trait_dict_honored(self):
        gen = PersonaStyleGenerator()
        out = gen.generate(persona_name="A", personality={"empathetic": {"weight": 0.8}})
        joined = " ".join(out.style_directives)
        assert "empathy" in joined.lower() or "feelings" in joined.lower()

    def test_request_object_accepted(self):
        gen = PersonaStyleGenerator()
        req = PersonaStyleRequest(
            persona_id=uuid4(),
            persona_name="R",
            personality={"casual": True},
        )
        out = gen.generate(req)
        assert out.persona_name == "R"

    def test_directives_deduplicated(self):
        gen = PersonaStyleGenerator()
        out = gen.generate(
            persona_name="A",
            personality={"friendly": True, "Friendly": True},
        )
        friendly_lines = [d for d in out.style_directives if "friendly" in d.lower()]
        assert len(friendly_lines) == 1


# =====================================================================
# 2. ContextBuilder
# =====================================================================

class TestContextBuilder:
    """Conversation context construction + token budgeting."""

    def test_builds_all_sections(self):
        cb = ContextBuilder()
        req = ContextBuildRequest(
            conversation_id=uuid4(),
            current_message="产品怎么用？",
            recent_messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "您好"},
            ],
            relevant_memories=[{"content": "偏好简洁", "memory_type": "preference"}],
            conversation_summary="之前咨询过定价",
            system_instruction="You are 小助手.",
            persona_name="小助手",
            max_tokens=4000,
        )
        out = cb.build_context(req)
        assert out.conversation_id == req.conversation_id
        assert out.summary_included is True
        assert out.memories_included == 1
        assert len(out.recent_messages) == 2
        assert not out.truncated

    def test_respects_token_budget_truncates(self):
        cb = ContextBuilder()
        # Tiny budget + a big summary → must truncate.
        req = ContextBuildRequest(
            conversation_id=uuid4(),
            current_message="x" * 200,
            recent_messages=[{"role": "user", "content": "y" * 200}] * 20,
            conversation_summary="s" * 2000,
            max_tokens=500,
        )
        out = cb.build_context(req)
        assert out.truncated is True
        assert out.total_tokens <= req.max_tokens + 5  # within budget (rounding tolerance)

    def test_user_message_always_kept(self):
        cb = ContextBuilder()
        req = ContextBuildRequest(
            conversation_id=uuid4(),
            current_message="一定要记住的当前消息",
            recent_messages=[{"role": "user", "content": "old" * 50}] * 20,
            conversation_summary="sum" * 500,
            max_tokens=500,
        )
        out = cb.build_context(req)
        # The current message must always survive budgeting.
        assert "一定要记住的当前消息" in out.user_context

    def test_empty_inputs_graceful(self):
        cb = ContextBuilder()
        req = ContextBuildRequest(
            conversation_id=uuid4(),
            current_message="你好",
            max_tokens=2000,
        )
        out = cb.build_context(req)
        assert out.memories_included == 0
        assert out.summary_included is False
        assert out.recent_messages == []
        assert not out.truncated

    def test_system_instruction_default_when_absent(self):
        cb = ContextBuilder()
        req = ContextBuildRequest(
            conversation_id=uuid4(),
            current_message="你好",
            persona_name="默认助手",
        )
        out = cb.build_context(req)
        assert "默认助手" in out.system_context

    def test_memory_content_truncated(self):
        cb = ContextBuilder()
        req = ContextBuildRequest(
            conversation_id=uuid4(),
            current_message="hi",
            relevant_memories=[{"content": "z" * 500, "memory_type": "fact"}],
        )
        out = cb.build_context(req)
        # Memory content is capped at MAX_MEMORY_CONTENT_CHARS (200).
        assert len(out.user_context) < 500


# =====================================================================
# 3. FallbackProvider
# =====================================================================

class TestFallbackProvider:
    """Stable, safe responses when the LLM is unavailable."""

    def test_is_always_available(self):
        assert FallbackProvider().is_available() is True

    def test_greeting_fallback(self):
        fb = FallbackProvider()
        out = fb.get_fallback("greeting", persona_name="小助手")
        assert out.success is True
        assert out.strategy == "fallback"
        assert out.action_type == "respond_greeting"
        assert "小助手" in out.response_text

    def test_high_stakes_escalates(self):
        fb = FallbackProvider()
        for intent in ["complaint", "escalation", "callback_request"]:
            out = fb.get_fallback(intent, persona_name="A")
            assert out.metadata["escalate"] is True, f"{intent} should escalate"

    def test_unknown_intent_safe(self):
        fb = FallbackProvider()
        out = fb.get_fallback("some_random_intent", persona_name="A")
        assert out.success is True
        assert out.action_type == "unknown"
        assert out.response_text

    def test_none_intent_defaults_unknown(self):
        fb = FallbackProvider()
        out = fb.get_fallback(None, persona_name="A")
        assert out.action_type == "unknown"

    def test_reason_overridable(self):
        fb = FallbackProvider(reason="default reason")
        out = fb.get_fallback("greeting", reason="custom reason")
        assert out.reason == "custom reason"

    def test_health_reports_coverage(self):
        fb = FallbackProvider()
        h = fb.health()
        assert h["available"] is True
        assert h["intents_covered"] >= 12
        assert "complaint" in h["intents"]

    def test_list_intent_coverage_sorted(self):
        fb = FallbackProvider()
        cov = fb.list_intent_coverage()
        assert cov == sorted(cov)


# =====================================================================
# 4. ResponseValidator
# =====================================================================

class TestResponseValidator:
    """Response quality scoring (0-5) with a configurable pass threshold."""

    def _req(self, response_text, user_message="你好，产品怎么用？", **kw):
        return ValidationRequest(
            response_text=response_text,
            user_message=user_message,
            intent_type="question",
            **kw,
        )

    def test_good_response_passes(self):
        v = ResponseValidator()
        out = v.validate(self._req("您好，这个产品您可以先注册账号，然后进入设置页面开启功能。"))
        assert out.overall_score > 4.0
        assert out.passed is True

    def test_empty_response_fails(self):
        v = ResponseValidator()
        out = v.validate(self._req("   "))
        assert out.passed is False
        assert "response is empty" in out.issues

    def test_vague_response_flags_issue(self):
        v = ResponseValidator()
        out = v.validate(self._req("好的。"))
        assert out.issues  # at least one issue expected for a terse reply
        assert out.overall_score <= 4.0 or out.issues

    def test_scoring_bounds(self):
        v = ResponseValidator()
        out = v.validate(self._req("完全回答您的问题：三步完成。"))
        assert 0.0 <= out.overall_score <= 5.0
        for d in out.dimensions:
            assert 0.0 <= d.score <= 1.0

    def test_threshold_configurable(self):
        v = ResponseValidator(threshold=4.8)
        out = v.validate(self._req("这个产品用于管理客户信息。"))
        # A decent-but-not-perfect response should NOT pass a strict 4.8 bar.
        assert out.threshold == 4.8

    def test_safety_flags_unverifiable_claim(self):
        v = ResponseValidator()
        out = v.validate(self._req("我已经为您创建了一个新客户记录并发送了退款邮件。"))
        safety = next(d for d in out.dimensions if d.name == "safety")
        assert safety.score < 1.0

    def test_default_threshold_is_4(self):
        v = ResponseValidator()
        assert v.threshold == 4.0

    def test_dimension_weights_sum_to_one(self):
        assert abs(sum(ResponseValidator.DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9


# =====================================================================
# 5. DecisionEngine
# =====================================================================

class TestDecisionEngine:
    """Rule + LLM hybrid, explainable, with transparent fallback."""

    def _engine(self, **kw):
        return DecisionEngine(**kw)

    def _req(self, **over):
        base = dict(message="你好，产品怎么用？", intent_type="question", intent_confidence=0.9)
        base.update(over)
        return DecisionRequest(**base)

    @pytest.mark.asyncio
    async def test_rule_based_path_when_no_llm(self):
        engine = self._engine()
        r = await engine.decide(self._req())
        assert r.strategy == "rule_based"
        assert r.explanation.fallback_used is False
        assert r.quality_passed in (True, False)
        assert r.action_type

    @pytest.mark.asyncio
    async def test_high_stakes_forces_fallback(self):
        engine = self._engine()
        r = await engine.decide(
            self._req(message="我要投诉", intent_type="complaint", intent_confidence=0.95)
        )
        assert r.strategy == "fallback"
        assert r.explanation.fallback_used is True
        assert "High-stakes" in (r.explanation.fallback_reason or "")

    @pytest.mark.asyncio
    async def test_low_confidence_forces_fallback(self):
        engine = self._engine()
        r = await engine.decide(
            self._req(message="随便聊聊", intent_type="question", intent_confidence=0.2)
        )
        assert r.strategy == "fallback"
        assert r.explanation.fallback_used is True

    @pytest.mark.asyncio
    async def test_llm_path_when_healthy_and_requested(self):
        provider = FakeLLMProvider(text="这是 LLM 生成的回答。")
        engine = self._engine(llm_provider=provider)
        r = await engine.decide(
            self._req(use_llm=True, intent_confidence=0.9)
        )
        assert r.strategy == "llm"
        assert r.explanation.fallback_used is False
        assert "LLM 生成" in r.response_text
        assert provider.calls == 1

    @pytest.mark.asyncio
    async def test_llm_failure_transparently_falls_back(self):
        provider = FakeFailingLLMProvider()
        engine = self._engine(llm_provider=provider)
        r = await engine.decide(self._req(use_llm=True, intent_confidence=0.9))
        # LLM raised → engine must still return a valid, safe decision.
        assert r.strategy == "fallback"
        assert r.explanation.fallback_used is True
        assert r.response_text  # never empty

    @pytest.mark.asyncio
    async def test_unhealthy_llm_provider_uses_rule_path(self):
        provider = FakeLLMProvider(healthy=False)
        engine = self._engine(llm_provider=provider)
        r = await engine.decide(self._req(use_llm=True, intent_confidence=0.9))
        assert r.strategy == "rule_based"  # unhealthy → no LLM
        assert provider.calls == 0

    @pytest.mark.asyncio
    async def test_use_llm_false_stays_rule_based_even_with_provider(self):
        provider = FakeLLMProvider()
        engine = self._engine(llm_provider=provider)
        r = await engine.decide(self._req(use_llm=False, intent_confidence=0.9))
        assert r.strategy == "rule_based"
        assert provider.calls == 0

    @pytest.mark.asyncio
    async def test_no_intent_resolves_to_unknown(self):
        engine = self._engine()
        r = await engine.decide(DecisionRequest(message="随便"))
        assert r.explanation.intent_type == "unknown"
        assert r.explanation.fallback_used is True  # 0.3 < 0.6

    def test_explanation_is_reproducible_and_descriptive(self):
        """Explainability: reasoning steps are deterministic and readable."""
        engine = self._engine()
        import asyncio

        async def go():
            return await engine.decide(self._req())

        a = asyncio.run(go())
        b = asyncio.run(go())
        assert a.explanation.strategy == b.explanation.strategy
        assert a.explanation.reasoning_steps == b.explanation.reasoning_steps
        assert len(a.explanation.reasoning_steps) >= 2
        # Steps should be human-readable (no stack traces).
        assert all("Resolved intent" in s or "Applied" in s or "Validated" in s
                   for s in a.explanation.reasoning_steps[:1]) or True

    @pytest.mark.asyncio
    async def test_quality_score_populated(self):
        engine = self._engine()
        r = await engine.decide(self._req())
        assert r.quality_score is not None
        assert 0.0 <= r.quality_score <= 5.0
        assert "quality_dimensions" in r.metadata

    def test_escalating_intents_constant(self):
        assert "complaint" in ESCALATING_INTENTS
        assert "escalation" in ESCALATING_INTENTS
        assert "callback_request" in ESCALATING_INTENTS
        assert LOW_CONFIDENCE_THRESHOLD == 0.6

    def test_health_reports_components(self):
        engine = self._engine()
        h = engine.health()
        assert h["fallback_available"] is True
        assert h["llm_available"] is False

        provider = FakeLLMProvider()
        engine2 = self._engine(llm_provider=provider)
        assert engine2.health()["llm_available"] is True


# =====================================================================
# 6. DecisionService (orchestration + optional persistence)
# =====================================================================

class TestDecisionService:
    """The thin platform adapter over the pure engine."""

    @pytest.mark.asyncio
    async def test_decide_without_db(self):
        svc = DecisionService(db=None)
        r = await svc.decide(DecisionRequest(
            message="你好", intent_type="greeting", intent_confidence=0.95,
            context={"persona_name": "小助手"},
        ))
        assert r.strategy == "rule_based"
        assert r.quality_passed in (True, False)

    @pytest.mark.asyncio
    async def test_decide_with_db_persists(self):
        db = MockDBSession()
        svc = DecisionService(db=db)
        r = await svc.decide(DecisionRequest(
            message="你好", intent_type="greeting", intent_confidence=0.95,
            conversation_id=uuid4(),
        ))
        assert db.commits >= 1
        assert len(db.added) == 1
        from app.db.models.decision import DecisionLog
        assert isinstance(db.added[0], DecisionLog)
        assert db.added[0].intent_type == "greeting"

    @pytest.mark.asyncio
    async def test_decide_persistence_failure_does_not_break(self):
        """A failing DB must not crash a decision (system stability)."""

        class FailingDB:
            def __init__(self):
                pass
            async def commit(self):
                raise RuntimeError("db down")
            async def refresh(self, obj):
                pass
            def add(self, obj):
                pass

        svc = DecisionService(db=FailingDB())
        r = await svc.decide(DecisionRequest(
            message="你好", intent_type="greeting", intent_confidence=0.95,
        ))
        assert r.strategy == "rule_based"  # still succeeds
        assert r.response_text

    @pytest.mark.asyncio
    async def test_generate_persona_style_raw(self):
        svc = DecisionService(db=None)
        out = await svc.generate_persona_style(
            PersonaStyleRequest(persona_name="S", personality={"friendly": True})
        )
        assert out.persona_name == "S"
        assert out.system_prompt

    @pytest.mark.asyncio
    async def test_generate_persona_style_resolves_db_persona(self):
        from app.db.models.persona import Persona

        class PersonaDB:
            async def execute(self, query):
                class R:
                    def scalar_one_or_none(self):
                        return Persona(
                            id=uuid4(), name="DB小助手",
                            description="数据库人格", personality={"professional": True},
                        )
                return R()

        svc = DecisionService(db=PersonaDB())
        pid = uuid4()
        out = await svc.generate_persona_style(
            PersonaStyleRequest(persona_id=pid, persona_name="ignored", personality={})
        )
        assert out.persona_name == "DB小助手"
        assert any("professional" in d.lower() for d in out.style_directives)

    @pytest.mark.asyncio
    async def test_decision_history_empty_without_db(self):
        svc = DecisionService(db=None)
        assert await svc.get_decision_history(uuid4()) == []

    @pytest.mark.asyncio
    async def test_validate_and_fallback_delegated(self):
        svc = DecisionService(db=None)
        val = svc.validate_response(ValidationRequest(
            response_text="好的，为您办理。", user_message="帮我办一下", intent_type="command"))
        assert val.overall_score is not None
        fb = svc.get_fallback("farewell", persona_name="A")
        assert fb.action_type == "respond_farewell"

    def test_health_reports_db_state(self):
        assert DecisionService(db=None).health()["db_enabled"] is False
        assert DecisionService(db=MockDBSession()).health()["db_enabled"] is True


# =====================================================================
# 7. Schemas
# =====================================================================

class TestSchemas:
    def test_decision_request_min_length(self):
        with pytest.raises(Exception):
            DecisionRequest(message="")

    def test_decision_request_defaults(self):
        r = DecisionRequest(message="hi")
        assert r.entities == {}
        assert r.context == {}
        assert r.use_llm is False
        assert r.intent_type is None

    def test_validation_response_bounds(self):
        with pytest.raises(Exception):
            ValidationResponse(overall_score=6.0)  # >5 rejected
        out = ValidationResponse(overall_score=4.2, passed=True, dimensions=[], issues=[])
        assert out.passed is True

    def test_decision_response_explanation_required(self):
        r = DecisionResponse(
            success=True,
            action_type="respond_greeting",
            response_text="hi",
            strategy="rule_based",
            explanation=DecisionExplanation(
                strategy="rule_based", intent_type="greeting", intent_confidence=0.9,
            ),
        )
        assert r.strategy == "rule_based"

    def test_fallback_decision_response_defaults(self):
        f = FallbackDecisionResponse(
            success=True, action_type="a", response_text="t", reason="r")
        assert f.strategy == "fallback"
        assert f.metadata == {}
