# QA Report — Phase 2 AI + Backend 集成测试 (t_3eb34805)

QA owner: qa-engineer · 日期: 2026-09-14 · 结论: **FAIL（有条件）— 核心 AI 层可用，但存在 4 个真实缺陷，其中 3 个 P1 直接阻塞「所有 AI 接口响应正常」验收**

---

## 0. 环境与方法

- 6 个并行后端任务正在同时写 `app/main.py` / `app/services/workflow.py` / `app/schemas/workflow.py` 等共享文件，`import app.main` 间歇抛 `NameError(WorkflowDetailResponse)`（属 workflow 任务未落地 schema，不在本任务范围）。
- 为把「AI 集成」从 workflow 热点中解耦，QA 建立独立测试应用 `qa_phase2_app.py`（Phase-2 AI 路由 + 单前缀），并另建 `_build_main_style_app()` 复刻 `main.py` 的双重前缀挂载，以确定性复现集成缺陷。
- DB：默认 `DATABASE_URL`（ai_agent_platform）无表；改用 `ai_agent_platform_test`（全表 + 2 个种子 customer，经 `get_db` 依赖覆盖 + `NullPool`——Starlette TestClient 每请求新事件循环，连接池必须用 NullPool）。
- 证据文件：`_qa_double_prefix_paths.json`、`_qa_double_prefix_404.json`、`_qa_intent_latency_ms.json`、`_qa_decision_latency_ms.json`、`_qa_intent_accuracy.json`（均在 backend/）。

## 1. 通过项（实测证据）

| 验收项 | 结果 | 证据 |
|---|---|---|
| 完整对话流程可跑通 | **PASS** | 真实 PG test-DB：create conv → add message → list → stats → delete 全 201/200/204；空消息 422 拒绝；未知会话 404。 |
| 决策引擎可解释 + 质量评分 | **PASS** | decide/validate/persona-style/fallback 全 200；explanation.reasoning_steps + quality_score(0-5) 均返回。 |
| 高危意图永不走 LLM | **PASS** | complaint/escalation/callback_request 强制 fallback；即使注入 healthy LLM provider 也走安全兜底（`test_high_risk_intent_never_llm`）。 |
| LLM Provider 故障注入 | **PASS** | provider=None → rule_based；exploding provider(503) → 透明 fallback，不崩；低置信度<0.6 → fallback 且记录原因。 |
| 意图识别准确性 | **PASS（规则基线）** | 12 意图采样 11/12 = **91%**（规则回退）；唯一误判 callback_request→command。 |
| 性能基准 | **PASS** | 规则意图均值 **4.1ms**（<500ms）；无 LLM 决策均值 **204ms**（<1000ms）。 |
| 资源消耗合理 | **PASS** | NullPool 每请求独立会话、无连接泄漏、无 N+1；决策/意图内存计算。 |
| Phase-2 回归 | **PASS** | decision/intent/memory/conversation(SSE)/prompt/persona 共 **255 个单测全过**；本任务 30 个集成测试 **28 过 / 2 失败=两个真实 bug**。 |

## 2. 发现缺陷（4 个，均真实、可复现、非测试脚本问题）

### BUG-1 · P1 · AI 层双重 `/api/v1` 前缀（集成缺陷，阻塞全部 AI 端点）
- 复现：在 `app.main` 挂载下 `GET /api/v1/decision/health` → **404**；只有 `GET /api/v1/api/v1/decision/health` → **200**。共 **20** 条 AI 路由受影响（decision 7 / intents 5 / memory 8）。
- 根因：`decision.py`/`intents.py`/`memory.py` 的 `APIRouter` 自带 `prefix="/api/v1/<mod>"`，而 `main.py` 又用 `prefix="/api/v1"` 挂载 → 叠加。其余路由（conversations 等）用裸 `"/<mod>"`，不受影响。
- 影响：真实应用下整个 Phase-2 AI 层（决策引擎/意图/记忆）在文档 URL 上全部 404 → 直接违反「所有 AI 接口响应正常」。
- 这正是 t_91bc7e7f hotspot 已标记的「全仓 router 双重前缀(/api/v1/api/v1/) 为 tag 404 根因，属平台/infra 清理项」。
- 建议修复：让这三个 router 统一改为裸前缀 `"/decision" "/intents" "/memory"`（与 conversations 对齐），由 main.py 统一加 `/api/v1`。

### BUG-4 · P1 · 缺失 LLM Provider：`app/providers/openai_provider.py` 不存在
- `app/services/intent_service.py:83` `from app.providers.openai_provider import OpenAIProvider`，该文件**在仓库/任意 worktree/git 历史中均不存在**（已核实）。
- 影响：LLM 意图分类**每次**都抛 `ModuleNotFoundError`（被捕获→回落规则），即 AI/LLM 路径为死代码，意图识别只能靠关键词（91%）；每次分类还打一条 error 日志。
- 归属：P2-001 / t_831bce34「AI Provider 抽象层」标记 done，但具体 OpenAI provider 文件从未落地共享树。属 ai-agent-engineer 交付缺口。
- 影响面：决策引擎是 provider-agnostic（可注入 protocol）且兜底正确，故决策层无恙；坏的是**意图层的 LLM 路径**。

### BUG-2 · P1 · memory 路由遮蔽：`GET /{memory_id}` 抢走 `/health`、`/statistics/{id}`
- `app/routers/memory.py`：`@router.get("/{memory_id}")`（行 70）定义在 `/health`（行 189）与 `/statistics/{customer_id}`（行 178）**之前**，FastAPI 按定义顺序匹配 → 被 UUID catch-all 捕获。
- 复现：`GET /api/v1/memory/health` → **422** `uuid_parsing ... input='health'`。
- 影响：记忆健康检查 + 统计端点不可达（BUG-1 修好后会立刻暴露）。
- 建议修复：把 `/health`、`/statistics/{id}`、`/search`、`/inject` 等具体路径定义到 `/{memory_id}` 之前。

### BUG-3 · P2 · memory inject 空上下文 → 500
- `app/services/memory_service.py inject_memories_into_context`：`recent_messages` 为空时 `recent_context=""` → `get_relevant_memories` 构造 `MemorySearchRequest(query="")` 违反 `query min_length=1` → 未捕获 `ValidationError` → **500**。
- 复现：`POST /api/v1/memory/inject {"recent_messages": []}` → 500（首轮对话即此场景，合法边界）。
- 建议修复：空上下文时跳过语义检索、直接返回空注入（或给默认查询）。

## 3. 验收结论

- 完整对话流程可跑通：**PASS**
- 所有 AI 接口响应正常：**BLOCKED**（BUG-1 双前缀 + BUG-2 memory 遮蔽 + BUG-4 LLM 缺失）
- 错误场景处理正确：**PARTIAL**（决策/意图兜底 PASS；memory inject 崩 500、意图 LLM 每次 ModuleNotFound）
- 性能指标达标：**PASS**
- 资源消耗合理：**PASS**

**QA 签名：qa-engineer · 判定 FAIL（有条件）** — 决策引擎、意图规则回退、对话流、性能均健康；但 4 个真实缺陷（3×P1）阻塞 AI 接口可用性与错误处理验收，需上述修复任务落地后回归。
