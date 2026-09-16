# QA Regression Acceptance — Phase 2 AI 集成（BUG-1..4 修复后）· t_85fb6e58

QA owner: qa-engineer · 日期: 2026-09-14 · 结论: **PASS**（4 缺陷清零，回归无新增失败；P5MSG-09 SSE 层 2 条为测试基建缺口，非本 4 缺陷回归，已路由）

---

## 0. 前置确认

本任务 4 个父任务（BUG-1..4 修复）全部 done：
- t_acffd4d0 (BUG-1 双前缀) / t_3a619441 (BUG-2 memory catch-all) / t_664792dd (BUG-3 inject 500) / t_d91feb2a (BUG-4 缺失 provider)

## 1. 方法与环境

- 共享树 `H:/AI-Agent-Platform/backend`，venv Python 3.11.16 + pytest 9.1.1。
- DB：真实 PostgreSQL `ai_agent_platform_test`（55 表，memory/conversation/decision_log 齐全；`NullPool`）。
- 说明：首轮的 seed 客户 `c1a00092…` 已被删除（现 514 客户，FK 目标消失）→ 属**测试数据漂移**，非产品缺陷。已把 `test_phase2_integration_qa.py` 的 `USE_CUSTOMER_ID` 改指一个现存客户 `340a5812-0b54-40aa-bd68-ff5593a2fea3`，让 E2E 对话流能真正跑通。

## 2. 4 缺陷逐项验收（实测证据）

| 缺陷 | 验收项 | 结果 | 证据 |
|---|---|---|---|
| BUG-1 双前缀 | main.py 挂载下 `GET /api/v1/{decision,intents,memory}/health` = 200；`/api/v1/api/v1/…` 不再存在 | **PASS** | 真实 `app.main` OpenAPI：3 个 health + `/statistics/{customer_id}` 全部在册；`doubled_count=0`（无任何 /api/v1 出现 2 次的路径） |
| BUG-2 catch-all 遮蔽 | memory `/health`、`/statistics/{id}` 可达 | **PASS** | `/api/v1/memory/health`、`/api/v1/memory/statistics/{customer_id}` 均在真实 app 注册表内；30-case 套件 `TestMemoryConsistency::test_statistics_unknown_customer`、`test_get_unknown_memory_404` 全绿 |
| BUG-3 inject 空上下文 | `POST /memory/inject` 空 `recent_messages` = 200（injection_count=0） | **PASS** | 30-case 套件 `TestMemoryConsistency::test_inject_unknown_customer` 绿；`tests/test_memory_inject_empty_context.py` 9/9 绿；路由前缀已还原为 `/api/v1/memory` |
| BUG-4 缺失 provider | 意图 LLM 路径：有 key 可用 / 无 key 静默回落规则，且不再刷 ModuleNotFound error | **PASS** | `app/providers/openai_provider.py` + `exceptions.py` 已落地并 importable；无 key 下 `OpenAIProvider().is_available()=False`、`intent_service` 静默回落规则（success=True, type=greeting）；捕获日志 `ERROR/CRITICAL=0`、`ModuleNotFound mentions=0` |

## 3. 回归测试

| 套件 | 结果 |
|---|---|
| **30 用例集成** `tests/test_phase2_integration_qa.py` | **30/30 PASS**（重跑 2 次稳定，2.76s） |
| 4 缺陷单测 `test_openai_provider_bug4(9) + test_decision_api + test_intent_api + test_memory_api + test_memory_inject_empty_context + test_memory` | **83/83 PASS** |
| Phase-2 回归扫（decision/intent/memory/conversation/prompt/persona） | **256 通过 / 2 失败** |
| 意图准确率基线 `_qa_intent_accuracy.py` | 11/12 = **91%**，与首轮一致（唯一误判 callback_request→command 为规则回退既有局限，非回归） |

## 4. 那 2 个失败（明确归因：非本 4 缺陷回归）

`tests/test_conversation_sse.py::TestP003ProviderSSE::{test_stream_event_sequence_matches_contract, test_stream_failure_emits_error_event}`

- 失败点：测试 setup 里 `monkeypatch.setattr(ai_agent.ai_config, …)` → `AttributeError: module 'app.services.ai.agent_service' has no attribute 'ai_config'`。
- 根因：`agent_service.py` 现为 **P1-003 QA shim**（文件头明确 “QA-ONLY, do not treat as a P1-003 deliverable”），只保留 `TokenUsage` / `AIAgentService` 的 import 面，故意不暴露 `ai_config` 配置面；而该 SSE 测试写于 shim 之前（mtime 18:18 < shim 20:22），仍按旧 API patch `ai_config`。
- 与 BUG-1..4 无关：4 个修复文件（`routers/memory.py`、`services/memory_service.py`、`providers/openai_provider.py`、`services/intent_service.py`）**均不出现在该 SSE 测试的 import 面**（grep 无命中）。SSE 相关 5 条里其余 5 条（endpoint_exists / validates / event_format / done / context_window ×2）全绿。
- 归属：P5MSG-09 线（t_bda104f0，当前第 6 次运行中，由我 qa-engineer 负责）的 AI SSE provider 测试基建缺口 → 已建独立卡路由，不属于本轮 4 缺陷回归判定范围。

## 5. 判定

- 30/30 集成测试全过 ✓
- 4 缺陷逐项验收全绿 ✓
- 回归无**新增**失败（唯一 2 失败为 P5MSG-09 测试基建，非 BUG-1..4 引入）✓
- 对话流 E2E、性能基准（规则意图 <500ms / 无 LLM 决策 <1s）、provider 故障注入回归均通过 ✓

**QA 签名：qa-engineer · 判定 PASS** — Phase 2 AI 集成在 4 个缺陷修复后通过回归验收。已改判由首轮 FAIL（有条件）→ PASS。
（P5MSG-09 SSE provider 测试基建缺口另建卡处理，不阻塞本回归门。）
