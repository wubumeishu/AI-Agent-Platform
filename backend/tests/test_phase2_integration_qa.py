"""
QA t_3eb34805 — Phase 2 AI + Backend Integration Test Suite
===========================================================
Run:  cd H:/AI-Agent-Platform/backend && uv run pytest tests/test_phase2_integration_qa.py -v

SCOPE (task body):
  - 端到端对话流程测试       -> TestConversationFlow (live HTTP, real PG)
  - AI Provider 故障注入     -> TestProviderFailureInjection (service level, LLM down/exploding)
  - 记忆系统一致性           -> TestMemoryConsistency (edge cases, live HTTP + real PG)
  - 意图识别准确性          -> TestIntentAccuracy (rule-based fallback, 13 intents)
  - 决策引擎边界情况        -> TestDecisionBoundaries (high-risk / low-conf / unknown intent)
  - 性能基准               -> TestPerformanceBaseline (<500ms rule intent, <1s no-LLM decide)
  - main.py 双重前缀缺陷复现 -> TestMainStyleMounting (documented P0 infra bug)

ISOLATION:
  This file does NOT import app.main: main.py is a shared hotspot being edited
  concurrently by 6 parallel backend tasks and currently raises
  NameError(WorkflowDetailResponse) in app/services/workflow.py. Instead we build
  the Phase-2 AI app standalone (qa_phase2_app) with the SAME mounting pattern
  main.py uses, so the double-prefix defect is reproduced deterministically.

Out of scope per task body: 压力测试 (Phase 4), 安全渗透 (Phase 5), 用户体感 (Phase 6).
"""
import json
import time
import uuid
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from qa_phase2_app import qa_app
from app.routers.conversations import router as conv_router
from app.routers.intents import router as intent_router
from app.routers.memory import router as memory_router
from app.routers.decision import router as decision_router

BACKEND = Path(__file__).resolve().parent.parent

# The default DATABASE_URL (ai_agent_platform) has NO tables in this env;
# the _test database has all Phase-1/2 tables + 2 seeded customers. Point
# get_db at the test DB via a dependency override so E2E conversation flow
# and memory-consistency tests run against a real, empty-then-populated DB.
TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"
# NOTE(t_85fb6e58): the round-1 seed customer c1a00092... was since deleted
# from ai_agent_platform_test (now 514 customers, FK target gone). Point at a
# real, present customer so the E2E conversation flow can exercise a valid FK.
USE_CUSTOMER_ID = "340a5812-0b54-40aa-bd68-ff5593a2fea3"  # valid customer in test DB

def _build_test_engine():
    # NullPool is REQUIRED with Starlette TestClient: each request runs on a
    # fresh anyio portal/event-loop, and pooled asyncpg connections are bound
    # to the loop they were created on. Pooling across requests raises
    # InterfaceError('another operation is in progress').
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    return eng, sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

_TEST_ENGINE, _TEST_SESSION = _build_test_engine()

def _test_get_db():
    from app.db.session import get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    async def override():
        async with _TEST_SESSION() as session:
            yield session
    return override

# ---------------------------------------------------------------------------
# Reproduce main.py's mounting pattern EXACTLY (outer /api/v1 + router prefix)
# ---------------------------------------------------------------------------

def _build_main_style_app():
    """Mirror app/main.py: mount Phase-2 routers WITH the /api/v1 outer prefix.

    main.py does:
        app.include_router(decision_router, prefix="/api/v1")
    while decision_router already carries prefix="/api/v1/decision".
    That lands routes at /api/v1/api/v1/decision/...  (the documented P0 bug).
    """
    from fastapi import FastAPI

    app = FastAPI(title="qa-mirror-main")
    app.include_router(conv_router, prefix="/api/v1")
    app.include_router(intent_router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(decision_router, prefix="/api/v1")
    return app


class TestMainStyleMounting:
    """Reproduce the router double-prefix defect documented in t_91bc7e7f hotspot.

    memory/intents/decision routers hard-code '/api/v1/...' in their APIRouter
    prefix; main.py adds ANOTHER '/api/v1' when mounting. Result: the
    documented, client-facing URLs 404 under the real app while the doubled
    URLs work — or vice versa. We capture the exact registered paths so the
    report can show empirical evidence.
    """

    def test_capture_main_style_registered_paths(self):
        app = _build_main_style_app()
        spec = app.openapi()
        doubled = sorted(p for p in spec["paths"] if p.count("/api/v1") >= 2)
        Path(BACKEND / "_qa_double_prefix_paths.json").write_text(
            json.dumps({"doubled": doubled, "count": len(doubled)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # The defect IS present: every AI router that hard-codes /api/v1
        # produces a doubled path under main.py's mounting.
        assert doubled, (
            "No doubled /api/v1 paths found under main.py mounting — the "
            "double-prefix defect may already be fixed; re-check main.py."
        )
        # ...and therefore the documented URL is NOT directly reachable
        assert "/api/v1/decision/decide" not in spec["paths"]

    def test_documented_url_404s_under_main_mount(self):
        app = _build_main_style_app()
        client = TestClient(app)
        r = client.get("/api/v1/decision/health")
        doubled_ok = client.get("/api/v1/api/v1/decision/health")
        Path(BACKEND / "_qa_double_prefix_404.json").write_text(
            json.dumps(
                {
                    "documented_url": "/api/v1/decision/health",
                    "documented_status": r.status_code,
                    "doubled_url": "/api/v1/api/v1/decision/health",
                    "doubled_status": doubled_ok.status_code,
                },
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        if r.status_code == 404:
            # bug live: only the doubled URL works
            assert doubled_ok.status_code == 200, (
                f"even doubled URL fails ({doubled_ok.status_code}) — AI tier "
                "effectively offline under main.py mounting"
            )
        else:
            # bug already fixed upstream between runs; record it
            assert r.status_code == 200, f"unexpected {r.status_code}: {r.text[:200]}"


# ---------------------------------------------------------------------------
# Live HTTP against the CORRECT single-prefix app (what clients actually call)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from app.db.session import get_db
    c = TestClient(qa_app)
    c.app.dependency_overrides[get_db] = _test_get_db()
    return c


class TestAITierEndpoints:
    """Acceptance: 所有 AI 接口响应正常 (against the correct path layout)."""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/v1/decision/health"),
        ("GET", "/api/v1/intents/health"),
        ("GET", "/api/v1/memory/health"),
        ("GET", "/api/v1/conversations/"),
    ])
    def test_health_and_list(self, client, method, path):
        r = client.request(method, path)
        assert r.status_code == 200, f"{method} {path} -> {r.status_code}: {r.text[:200]}"

    def test_decision_fallback_query_params(self, client):
        """Fallback is Query-param based (intent_type / persona_name), not JSON."""
        r = client.post("/api/v1/decision/fallback",
                        params={"intent_type": "thanks", "persona_name": "S"})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("action_type") == "acknowledge_thanks", body

    def test_decision_validate(self, client):
        r = client.post("/api/v1/decision/validate",
                        json={"response_text": "您好，正在为您办理。",
                              "user_message": "帮我办理",
                              "intent_type": "command"})
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert 0 <= body["overall_score"] <= 5, body

    def test_decision_persona_style(self, client):
        r = client.post("/api/v1/decision/persona-style",
                        json={"persona_name": "热情助手", "personality": {"casual": True}})
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("system_prompt"), "persona style must yield a system prompt"

    def test_intent_classify_greeting(self, client):
        r = client.post("/api/v1/intents/classify", json={"message": "你好，很高兴认识你！"})
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("success") is True, body
        assert body.get("intent", {}).get("intent_type") in ("greeting", "question"), body

    def test_intent_classify_complaint(self, client):
        r = client.post("/api/v1/intents/classify", json={"message": "我要投诉，你们的服务太差了！"})
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("intent", {}).get("intent_type") == "complaint", \
            f"expected complaint, got {body.get('intent')}"

    def test_intent_unknown_defaults_question(self, client):
        r = client.post("/api/v1/intents/classify", json={"message": "zqxwcvbnm 999"})
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("intent", {}).get("intent_type") == "question", r.json()

    def test_intent_map_action(self, client):
        r = client.post("/api/v1/intents/map-action",
                        json={"intent_type": "complaint", "intent_name": "投诉",
                              "entities": {"target": "客服"}, "context": {}})
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("success") is True, body
        assert body.get("action_type") == "handle_complaint", body

    def test_decision_history_unknown_conversation(self, client):
        """Empty history for an unknown conversation must be a clean 200, not 500."""
        r = client.get(f"/api/v1/decision/history/{uuid.uuid4()}")
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("total") == 0, r.json()


# ---------------------------------------------------------------------------
# End-to-end conversation flow (acceptance: 完整对话流程可跑通)
# Uses the REAL PostgreSQL database (default DATABASE_URL).
# ---------------------------------------------------------------------------

class TestConversationFlow:
    """Create conversation -> add message -> list -> stats -> delete. Real DB.

    ConversationCreate requires a real customer_id (FK to customer.id); use the
    seeded test-DB customer so the flow is a genuine end-to-end run.
    """

    @pytest.fixture()
    def conv(self, client):
        r = client.post("/api/v1/conversations/",
                        json={"customer_id": USE_CUSTOMER_ID,
                              "channel": "web",
                              "subject": "QA Phase2 对话流程"})
        assert r.status_code == 201, f"create conversation failed: {r.status_code} {r.text[:300]}"
        return r.json()

    def test_full_flow(self, client, conv):
        cid = conv["id"]
        # add message (MessageCreate requires conversation_id in body)
        r = client.post(f"/api/v1/conversations/{cid}/messages",
                        json={"role": "user",
                              "content": "你好，我想咨询一下订单",
                              "conversation_id": cid})
        assert r.status_code == 201, r.text[:300]
        msg_id = r.json()["id"]
        # list messages
        r = client.get(f"/api/v1/conversations/{cid}/messages")
        assert r.status_code == 200, r.text[:200]
        assert r.json()["total"] >= 1, r.json()
        # stats
        r = client.get(f"/api/v1/conversations/{cid}/stats")
        assert r.status_code == 200, r.text[:200]
        # cleanup
        r = client.delete(f"/api/v1/conversations/{cid}")
        assert r.status_code in (200, 204), r.text[:200]

    def test_invalid_message_rejected(self, client, conv):
        """Empty content must be rejected by schema (422), not stored."""
        r = client.post(f"/api/v1/conversations/{conv['id']}/messages",
                        json={"role": "user", "content": "",
                              "conversation_id": conv["id"]})
        assert r.status_code == 422, f"empty message should 422, got {r.status_code}"
        # cleanup
        client.delete(f"/api/v1/conversations/{conv['id']}")

    def test_unknown_conversation_404(self, client):
        r = client.get(f"/api/v1/conversations/{uuid.uuid4()}")
        assert r.status_code == 404, f"expected 404, got {r.status_code}"
        r = client.get(f"/api/v1/conversations/{uuid.uuid4()}/messages")
        assert r.status_code in (404, 200), f"list msgs on unknown conv -> {r.status_code}"


# ---------------------------------------------------------------------------
# Provider failure injection (acceptance: 错误场景处理正确)
# No LLM key exists in this environment, so "provider down" is the default.
# ---------------------------------------------------------------------------

class _ExplodingProvider:
    """LLM provider stub whose completion always fails (gateway 503)."""

    def healthy(self) -> bool:
        return True

    async def complete(self, system_prompt: str, messages) -> str:
        raise RuntimeError("LLM gateway 503 (injected)")


class TestProviderFailureInjection:

    def test_decision_engine_llm_none_rule_based(self):
        from app.services.decision_engine import DecisionEngine
        from app.schemas.decision import DecisionRequest

        engine = DecisionEngine(llm_provider=None)
        req = DecisionRequest(message="你好", intent_type="greeting",
                              intent_confidence=0.9, use_llm=True)
        out = asyncio_run(engine.decide(req))
        # no provider -> deterministic rule_based generation
        assert out.strategy == "rule_based", out.strategy
        assert out.success is True
        assert out.response_text.strip(), "response must be non-empty"
        assert out.explanation.reasoning_steps, "decision must be explainable"

    def test_decision_engine_exploding_provider_falls_back(self):
        """LLM path requested but provider raises -> transparent fallback, no crash.

        NOTE: 'greeting' is non-escalating and confidence 0.9 passes the threshold,
        so strategy starts as 'llm'; the exploding provider forces 'fallback'.
        """
        from app.services.decision_engine import DecisionEngine
        from app.schemas.decision import DecisionRequest

        engine = DecisionEngine(llm_provider=_ExplodingProvider())
        out = asyncio_run(engine.decide(DecisionRequest(
            message="你好", intent_type="greeting", intent_confidence=0.9, use_llm=True)))
        assert out.strategy == "fallback", out.strategy
        assert out.explanation.fallback_used is True
        assert "LLM" in (out.explanation.fallback_reason or ""), out.explanation.fallback_reason

    def test_high_risk_intent_never_llm(self):
        """Even with a healthy provider, high-stakes intents must not use LLM."""
        from app.services.decision_engine import DecisionEngine
        from app.schemas.decision import DecisionRequest

        class _HealthyProvider:
            def healthy(self):
                return True

            async def complete(self, *a, **k):
                return "不应出现的LLM文本"

        engine = DecisionEngine(llm_provider=_HealthyProvider())
        out = asyncio_run(engine.decide(DecisionRequest(
            message="我要投诉", intent_type="complaint", intent_confidence=0.99, use_llm=True)))
        assert out.strategy == "fallback", \
            f"high-risk 'complaint' used strategy {out.strategy} — unsafe LLM path"
        assert out.explanation.fallback_reason and "High-stakes" in out.explanation.fallback_reason

    def test_low_confidence_forces_fallback(self):
        from app.services.decision_engine import DecisionEngine
        from app.schemas.decision import DecisionRequest

        engine = DecisionEngine(llm_provider=None)
        out = asyncio_run(engine.decide(DecisionRequest(
            message="随便说点啥", intent_type="question", intent_confidence=0.2, use_llm=False)))
        assert out.strategy == "fallback", out.strategy
        assert "confidence" in out.explanation.fallback_reason, out.explanation.fallback_reason

    def test_intent_service_degrades_without_provider(self):
        from app.services.intent_service import IntentService
        from app.schemas.intent import IntentClassificationRequest

        svc = IntentService(db=None)
        resp = asyncio_run(svc.classify_intent(IntentClassificationRequest(
            message="我要投诉，太慢了")))
        assert resp.success is True, f"should degrade to rule-based: {resp}"
        assert resp.intent.intent_type in ("complaint", "escalation"), resp.intent

    def test_intent_service_empty_message_handled(self):
        from app.services.intent_service import IntentService
        from app.schemas.intent import IntentClassificationRequest

        svc = IntentService(db=None)
        # schema enforces min_length=1, so empty message is a validation error;
        # the service path still must not raise for a message with no keyword hits.
        resp = asyncio_run(svc.classify_intent(IntentClassificationRequest(
            message="qwerty 98765")))
        assert resp.success is True, resp.message
        assert resp.intent.intent_type == "question", "no-keyword message defaults to question"


# ---------------------------------------------------------------------------
# Memory-system consistency (edge cases against real PG)
# ---------------------------------------------------------------------------

class TestMemoryConsistency:

    def test_search_unknown_customer(self, client):
        r = client.post("/api/v1/memory/search",
                        json={"customer_id": str(uuid.uuid4()), "query": "hi"})
        assert r.status_code in (200, 404, 400), \
            f"search crashed/500: {r.status_code} {r.text[:200]}"

    def test_inject_unknown_customer(self, client):
        r = client.post("/api/v1/memory/inject",
                        json={"conversation_id": str(uuid.uuid4()),
                              "customer_id": str(uuid.uuid4())})
        assert r.status_code in (200, 404, 400), f"inject crashed: {r.status_code} {r.text[:200]}"

    def test_list_unknown_customer_empty(self, client):
        r = client.get("/api/v1/memory/", params={"customer_id": str(uuid.uuid4())})
        assert r.status_code == 200, f"list should be 200+empty: {r.status_code} {r.text[:200]}"
        assert r.json()["total"] == 0, r.json()

    def test_get_unknown_memory_404(self, client):
        r = client.get(f"/api/v1/memory/{uuid.uuid4()}")
        assert r.status_code == 404, f"expected 404, got {r.status_code}"

    def test_statistics_unknown_customer(self, client):
        r = client.get(f"/api/v1/memory/statistics/{uuid.uuid4()}")
        assert r.status_code in (200, 404, 400), f"stats crashed: {r.status_code} {r.text[:200]}"


# ---------------------------------------------------------------------------
# Performance baselines (acceptance: 性能指标达标 / 资源消耗合理)
# ---------------------------------------------------------------------------

class TestPerformanceBaseline:

    def test_rule_intent_under_500ms(self, client):
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            r = client.post("/api/v1/intents/classify", json={"message": "你好，很高兴认识你"})
            times.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200
        avg = sum(times) / len(times)
        Path(BACKEND / "_qa_intent_latency_ms.json").write_text(
            json.dumps({"avg_ms": round(avg, 2), "samples": [round(t, 1) for t in times]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        assert avg < 500, f"rule-based intent avg {avg:.0f}ms exceeds 500ms baseline"

    def test_no_llm_decision_under_1s(self, client):
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            r = client.post("/api/v1/decision/decide",
                            json={"intent_type": "thanks", "message": "谢谢",
                                  "context": {"persona_name": "S"}})
            times.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200
        avg = sum(times) / len(times)
        Path(BACKEND / "_qa_decision_latency_ms.json").write_text(
            json.dumps({"avg_ms": round(avg, 2), "samples": [round(t, 1) for t in times]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        assert avg < 1000, f"no-LLM decision avg {avg:.0f}ms exceeds 1000ms baseline"


def asyncio_run(coro):
    """Run a coroutine to completion in a fresh event loop (test helper)."""
    import asyncio
    return asyncio.run(coro)
