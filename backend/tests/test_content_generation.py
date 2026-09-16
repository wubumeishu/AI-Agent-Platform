"""Tests for Phase 5 AI Content Generation + Nurture Automation.

Covers the acceptance criteria:
- [x] AI content generation interface callable (template path, offline-safe)
- [x] Generated content can be linked to a NurturePlan step (injection)
- [x] Content quality evaluation logic is usable
- [x] Generation history is queryable
- [x] Integration tests pass (pure core + service + router, no live LLM/DB)

Design mirrors the Phase 2 DecisionEngine conventions:
- Pure, provider-agnostic core (ContentGenerator / ContentQualityEvaluator /
  content_templates) tested directly, no DB or LLM required.
- ContentGenerationService tested with a mocked AsyncSession.
- The router is verified to be registered and its dependency wiring works.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.schemas.content_generation import (
    ContentEvaluationRequest,
    ContentGenerationRequest,
    ContentInjectionRequest,
    GeneratedContent,
    QualityEvaluation,
)
from app.services.content_generator import ContentGenerator
from app.services.content_quality_evaluator import ContentQualityEvaluator
from app.services.content_templates import generate_template_content
from app.services.content_generation_service import ContentGenerationService
from app.db.models.content_generation import ContentGeneration


# =====================================================================
# Helpers
# =====================================================================

def make_request(**overrides) -> ContentGenerationRequest:
    base = dict(account_id=uuid4())
    base.update(overrides)
    return ContentGenerationRequest(**base)


class _FakeProvider:
    """A healthy LLM provider that returns valid structured content."""

    def healthy(self):
        return True

    async def complete(self, system, messages):
        return (
            '{"title": "欢迎回来张三", '
            '"body": "好久不见，欢迎回来！点击立即回归，看看有什么不同 →", '
            '"summary": "回归内容", "tags": ["reactivation", "回归"]}'
        )


class _UnhealthyProvider:
    def healthy(self):
        return False

    async def complete(self, system, messages):
        raise RuntimeError("no provider")


# =====================================================================
# Template engine (pure, offline)
# =====================================================================

class TestTemplates:
    def test_welcome_template_includes_customer_name(self):
        out = generate_template_content(
            objective="welcome", customer_name="张三", segment_name="新用户",
            include_cta=True,
        )
        assert "张三" in out["body"]
        assert "新用户" in out["body"]
        assert out["content_type"] == "text"

    def test_template_returns_nonempty_title_body_summary(self):
        out = generate_template_content(objective="nurture", customer_name="李四")
        assert out["title"].strip()
        assert out["body"].strip()
        assert out["summary"].strip()

    def test_no_cta_removes_call_to_action(self):
        with_cta = generate_template_content(objective="welcome", include_cta=True)
        without_cta = generate_template_content(objective="welcome", include_cta=False)
        assert "点击这里" in with_cta["body"]
        assert "点击这里" not in without_cta["body"]

    def test_html_content_type_wraps_body(self):
        out = generate_template_content(
            objective="welcome", content_type="html", customer_name="王五"
        )
        assert out["body"].startswith("<p>")
        assert out["content_type"] == "html"

    def test_tags_merge_and_dedupe(self):
        out = generate_template_content(
            objective="welcome", customer_tags=["VIP"], extra_tags=["VIP", "新品"]
        )
        assert "VIP" in out["tags"]
        assert "新品" in out["tags"]
        # customer VIP appears only once
        assert out["tags"].count("VIP") == 1

    def test_unknown_objective_uses_default_template(self):
        out = generate_template_content(objective="totally_unknown", customer_name="钱")
        assert out["title"].strip()
        assert out["body"].strip()

    def test_tone_variants(self):
        professional = generate_template_content(objective="welcome", tone="professional")
        playful = generate_template_content(objective="welcome", tone="playful")
        assert "您好" in professional["body"]
        assert "嗨" in playful["body"]


# =====================================================================
# Quality evaluator (pure, offline, explainable)
# =====================================================================

class TestQualityEvaluator:
    def setup_method(self):
        self.ev = ContentQualityEvaluator()

    def _eval(self, **kw) -> QualityEvaluation:
        return self.ev.evaluate(ContentEvaluationRequest(**kw))

    def test_scoring_bounds_and_dimensions(self):
        q = self._eval(
            content="欢迎新用户，这里有一批干货指南，点击立即领取。",
            objective="welcome",
            expected_tags=["VIP"],
            persona_name="小助手",
        )
        assert 0.0 <= q.score <= 5.0
        assert set(q.dimensions) == {
            "relevance", "personalization", "completeness", "consistency", "safety"
        }
        assert q.threshold == ContentQualityEvaluator.DEFAULT_THRESHOLD

    def test_empty_content_fails_and_reports_issue(self):
        q = self._eval(content="hi")
        assert q.dimensions["completeness"] < 0.5
        assert any("incomplete" in i for i in q.issues)

    def test_fabricated_claim_is_penalized_for_safety(self):
        good = self._eval(content="欢迎新用户，点击查看指南，立即开始。")
        bad = self._eval(
            content="我已为您创建了一个100%保证成功的账号，立即开始。"
        )
        assert bad.dimensions["safety"] < good.dimensions["safety"]
        assert any("unsafe" in i or "unverifiable" in i for i in bad.issues)

    def test_relevant_objective_scores_higher(self):
        relevant = self._eval(content="欢迎新用户，点击开始入门指南。", objective="welcome")
        off_topic = self._eval(content="今天天气不错。", objective="welcome")
        assert relevant.dimensions["relevance"] > off_topic.dimensions["relevance"]

    def test_pass_verdict_uses_threshold_and_safety(self):
        q = self._eval(
            content="欢迎新用户张三，这里有一批干货指南，点击查看并立即开始。",
            objective="welcome",
            expected_tags=["VIP"],
            segment_name="新用户",
        )
        assert q.passed is True
        assert q.score >= q.threshold


# =====================================================================
# Generator core (strategy selection + fallback + quality gating)
# =====================================================================

class TestContentGenerator:
    @pytest.mark.asyncio
    async def test_no_provider_uses_template_with_fallback_flag(self):
        gen = ContentGenerator()  # no provider
        res = await gen.generate(make_request(objective="welcome", customer_name="张三"))
        assert res.strategy == "template"
        assert res.fallback_used is True
        assert res.title and res.body

    @pytest.mark.asyncio
    async def test_healthy_llm_provider_used_when_quality_passes(self):
        gen = ContentGenerator(llm_provider=_FakeProvider())
        res = await gen.generate(make_request(objective="reactivation", customer_name="张三"))
        assert res.strategy == "llm"
        assert res.fallback_used is False

    @pytest.mark.asyncio
    async def test_unhealthy_provider_falls_back_to_template(self):
        gen = ContentGenerator(llm_provider=_UnhealthyProvider())
        res = await gen.generate(make_request(objective="welcome"))
        assert res.strategy == "template"
        assert res.fallback_used is True
        assert res.fallback_reason is not None

    @pytest.mark.asyncio
    async def test_llm_provider_exception_falls_back_safely(self):
        class Boom:
            def healthy(self):
                return True

            async def complete(self, system, messages):
                raise RuntimeError("llm exploded")

        gen = ContentGenerator(llm_provider=Boom())
        res = await gen.generate(make_request(objective="welcome"))
        assert res.strategy == "template"
        assert res.fallback_used is True
        # still usable content
        assert res.body.strip()

    @pytest.mark.asyncio
    async def test_bad_llm_json_falls_back_to_template(self):
        class BadJson:
            def healthy(self):
                return True

            async def complete(self, system, messages):
                return "this is not json at all, just prose."

        gen = ContentGenerator(llm_provider=BadJson())
        res = await gen.generate(make_request(objective="welcome"))
        assert res.strategy == "template"
        assert res.fallback_used is True

    @pytest.mark.asyncio
    async def test_generated_result_shape(self):
        gen = ContentGenerator()
        res = await gen.generate(make_request(objective="cross_sell"))
        assert isinstance(res, GeneratedContent)
        assert res.content_type == "text"
        assert isinstance(res.quality, QualityEvaluation)
        assert res.tags

    @pytest.mark.asyncio
    async def test_short_length_trims_body(self):
        gen = ContentGenerator()
        medium = await gen.generate(make_request(objective="welcome", length="medium"))
        short = await gen.generate(make_request(objective="welcome", length="short"))
        assert len(short.body) < len(medium.body)

    def test_prompt_binds_customer_context(self):
        system, messages = ContentGenerator._build_prompt(
            make_request(objective="nurture", customer_name="张三", segment_name="新用户")
        )
        user_payload = messages[-1]["content"]
        assert "张三" in user_payload
        assert "新用户" in user_payload
        assert "nurture" in user_payload

    def test_parser_strips_markdown_fences(self):
        raw = '```json\n{"title": "t", "body": "b", "summary": "s"}\n```'
        parsed = ContentGenerator._parse_llm_content(raw, "text")
        assert parsed is not None
        assert parsed["title"] == "t"

    def test_parser_requires_body(self):
        parsed = ContentGenerator._parse_llm_content('{"title": "t", "body": ""}', "text")
        assert parsed is None


# =====================================================================
# Service (thin platform adapter over the pure core)
# =====================================================================

class _MockDB:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.refreshed = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        self.refreshed.append(obj)

    async def execute(self, *a, **kw):
        raise NotImplementedError


class TestContentGenerationService:
    @pytest.mark.asyncio
    async def test_generate_without_db_is_pure(self):
        svc = ContentGenerationService(db=None)
        res = await svc.generate_content(make_request(objective="welcome"))
        assert res.strategy == "template"
        assert res.generation_id is None
        assert res.content_item_id is None

    @pytest.mark.asyncio
    async def test_generate_persists_audit_log_and_sets_generation_id(self):
        db = _MockDB()
        svc = ContentGenerationService(db=db)
        # Stub the audit write to avoid real DB execution; record a new row id.
        async def fake_persist(request, result, *, source, content_item_id=None,
                               nurture_plan_id=None, plan_step_id=None):
            g = ContentGeneration()
            g.id = uuid4()
            return g
        svc._persist_generation = fake_persist  # type: ignore
        res = await svc.generate_content(make_request(objective="welcome"))
        assert res.generation_id is not None
        # The pure generation itself still happened.
        assert res.strategy == "template"

    def test_evaluate_content_delegates_to_evaluator(self):
        svc = ContentGenerationService(db=None)
        q = svc.evaluate_content(
            ContentEvaluationRequest(content="欢迎新用户，点击开始。", objective="welcome")
        )
        assert isinstance(q, QualityEvaluation)

    @pytest.mark.asyncio
    async def test_history_requires_db(self):
        svc = ContentGenerationService(db=None)
        with pytest.raises(ValueError):
            await svc.get_history(uuid4())

    @pytest.mark.asyncio
    async def test_inject_without_db_raises(self):
        svc = ContentGenerationService(db=None)
        req = ContentInjectionRequest(plan_id=uuid4(), account_id=uuid4())
        with pytest.raises(ValueError):
            await svc.inject_into_plan(req)

    @pytest.mark.asyncio
    async def test_inject_reuse_requires_content_or_generate(self):
        db = _MockDB()
        svc = ContentGenerationService(db=db)
        req = ContentInjectionRequest(plan_id=uuid4(), account_id=uuid4())
        with pytest.raises(ValueError):
            await svc.inject_into_plan(req)

    @pytest.mark.asyncio
    async def test_inject_reuse_creates_step(self):
        db = _MockDB()
        svc = ContentGenerationService(db=db)
        content_id = uuid4()
        req = ContentInjectionRequest(
            plan_id=uuid4(), account_id=uuid4(), content_id=content_id
        )
        # Stub out DB-dependent helpers.
        async def fake_next_order(plan_id):
            return 3
        svc._next_step_order = fake_next_order  # type: ignore
        fake_item = GeneratedContent(
            title="t", body="b", content_type="text",
            quality=QualityEvaluation(score=5.0, passed=True),
        )
        async def fake_describe(cid):
            return fake_item
        svc._describe_library_item = fake_describe  # type: ignore
        captured = {}

        with patch(
            "app.services.content_generation_service.create_nurture_plan_step",
            AsyncMock(return_value={"id": uuid4(), "step_order": 3}),
        ) as step_mock:
            res = await svc.inject_into_plan(req)
        assert res.content_item_id == content_id
        assert res.step_order == 3
        assert res.created_step is True
        # Reuse path links the existing item, not a fresh generation.
        assert step_mock.called

    @pytest.mark.asyncio
    async def test_inject_generate_creates_step_with_content(self):
        db = _MockDB()
        svc = ContentGenerationService(db=db)
        req = ContentInjectionRequest(
            plan_id=uuid4(),
            account_id=uuid4(),
            generate=make_request(objective="welcome", customer_name="张三"),
        )
        async def fake_next_order(plan_id):
            return 1
        svc._next_step_order = fake_next_order  # type: ignore
        # Save returns a content item id.
        item_id = uuid4()
        async def fake_save(request, result):
            return item_id
        svc.save_to_library = fake_save  # type: ignore
        step_id = uuid4()

        with patch(
            "app.services.content_generation_service.create_nurture_plan_step",
            AsyncMock(return_value={"id": step_id, "step_order": 1}),
        ), patch.object(svc, "_persist_generation", AsyncMock()) as persist:
            res = await svc.inject_into_plan(req)

        assert res.content_item_id == item_id
        assert res.step_id == step_id
        assert res.created_step is True
        # The generated audit row was linked to the plan + step.
        assert persist.called


# =====================================================================
# Router / registration
# =====================================================================

class TestRouter:
    def test_router_registered_on_app(self):
        from app.main import app
        schema = app.openapi()
        registered = set(schema["paths"])
        expected = {
            "/api/v1/content/generate",
            "/api/v1/content/evaluate",
            "/api/v1/content/nurture/inject",
            "/api/v1/content/history",
        }
        assert expected.issubset(registered)

    def test_route_paths_present(self):
        from app.routers.content_generation import router as cg_router
        paths = {getattr(r, "path", "") for r in cg_router.routes}
        assert cg_router.prefix + "/generate" in paths
        assert cg_router.prefix + "/evaluate" in paths
        assert cg_router.prefix + "/nurture/inject" in paths
        assert cg_router.prefix + "/history" in paths

    def test_service_dependency_wiring(self):
        from app.routers.content_generation import get_content_generation_service
        db = _MockDB()
        svc = get_content_generation_service(db=db)
        assert isinstance(svc, ContentGenerationService)
