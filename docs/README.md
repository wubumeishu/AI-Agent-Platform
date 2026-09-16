# docs/ 文档索引

> 52 份文档，2026-09-16 整理（目录重构 + 索引）。
> 入口三件套：**`CURRENT_FOCUS.md`**（现状锚点）· **`PROJECT.md`**（项目定义）· **`ROADMAP.md`**（阶段路线）。

## 顶层 · 活文档（日常维护，agent / SOUL.md 会引用）

| 文件 | 用途 |
|---|---|
| `CURRENT_FOCUS.md` | **当前阶段唯一目标 + 成功标准**（2026-09-16 已刷新：Phase 6 全收口） |
| `PROJECT.md` | 项目身份 / 配置（V1 浏览器仅 BitBrowser 等边界） |
| `ROADMAP.md` | Phase 0-7 路线 + 各 Phase 完成标记 |
| `DECISIONS.md` | ADR 决策日志（ADR-001…ADR-019） |
| `ARCHITECTURE.md` | 总体架构 |
| `AGENTS.md` | 给 agent 的项目约定 |
| `BOARD.md` | 看板工作规则 |
| `DEVELOPMENT_RULES.md` | 开发规范 |
| `EPIC-ISSUE.md` | 问题池（Orchestrator 维护） |
| 《AI 智能获客与私域运营平台 V1.0 产品与系统设计书》.md | 产品与系统设计书（2044 行，需求源头） |

## phases/ · 阶段文档（规格 + 总结）

| 文件 | 内容 |
|---|---|
| `P0-002.md` … `P0-005.md` | Phase 0 四张卡的任务规格 |
| `PHASE-0-SUMMARY.md` / `PHASE-1-SUMMARY.md` | Phase 0 / 1 阶段总结 |
| `PHASE-2-START.md` | Phase 2 启动说明 |
| `PHASE-3-SUMMARY.md` / `PHASE-5-SUMMARY.md` / `PHASE-6-SUMMARY.md` | Phase 3 / 5 / 6 总结 |
| `PHASE1-ARCHITECTURE.md` / `PHASE1-API-SPEC.md` / `PHASE1-DB-SCHEMA.sql` | Phase 1 架构 / API / 库表规格 |

> ⚠️ **已知缺口**：`PHASE-4-SUMMARY.md` 不存在（Phase 4 工作见 `features/` workflow 系列 + `qa-reviews/QA-REGRESSION-PHASE5-P0P1.md`）。

## features/ · 功能实现说明

| 文件 | 内容 |
|---|---|
| `conversation-system-implementation.md` | 会话系统 |
| `WORKFLOW-CONVERSATION-INTEGRATION.md` / `WORKFLOW-CRM-INTEGRATION.md` / `WORKFLOW-DB-SCHEMA.md` | 工作流 × 会话 / CRM / 库表 |
| `P6AN-02-dashboard-overview.md` | P6AN-02 Dashboard 概览 API 规格 |
| `content-generation-implementation.md` / `prompt-template-implementation.md` | 内容生成 / 提示词模板 |
| `decision-engine-implementation.md` / `intent-classification-evaluation.md` | 决策引擎 / 意图分类评估 |
| `memory-system-implementation.md` | 记忆系统 |
| `CRM-LIFECYCLE-IMPLEMENTATION.md` | CRM 生命周期 |

> `WORKFLOW-CONFIG-API.md` 保留在**顶层**：被 `frontend/src/api/*.ts` 代码注释引用（勿移动）。

## qa-reviews/ · QA / 审查 / 审计记录（一次性报告）

| 文件 | 内容 |
|---|---|
| `P0-002-FINAL-REPORT-v2.md` | P0-002 最终验收（**v2 为权威版**；v1 在 `archive/`） |
| `QA-REPORT-P0-002.md` / `-SUPPLEMENT.md` / `QA-REPORT-P0-005.md` | P0 QA 报告 |
| `AUDIT-P0-002.md` / `AUDIT-SUMMARY-P0-002.md` / `REVIEWER-REPORT-P0-002.md` / `P0-002-FIX.md` | P0-002 审计 / 复核 / 修复 |
| `QA-REGRESSION-PHASE5-P0P1.md` / `QA-REPORT-PHASE5-PRIVATE-DOMAIN.md` | Phase 5 回归 / 私域 QA |
| `qa-phase2-ai-integration-t_3eb34805.md` / `-regression-t_85fb6e58.md` / `qa-sse-p1003-shim-t_fbc8d986.md` | Phase 2 QA + SSE shim |
| `REVIEW-P0-SECURITY-DATA-PROTECTION-t_f1f591ab.md` / `-CLOSURE-t_d304b83e.md` | P0 安全审查 + 闭合复审 |
| `REVIEW-WORKFLOW-ARCHITECTURE.md` / `-RELIABILITY.md` | 工作流架构 / 可靠性审查 |

## archive/ · 已归档（被取代 / 临时）

| 文件 | 原因 |
|---|---|
| `P0-002-FINAL-REPORT.md` | 被 `qa-reviews/P0-002-FINAL-REPORT-v2.md` 取代 |
| `CONTEXT-SNAPSHOT.md` | t_437d6607 的一次性上下文快照 |
| `FIRST_TASK.md` | 首卡引导说明，已完成使命 |

---

## 维护约定

1. 阶段完成 → 新增 `phases/PHASE-N-SUMMARY.md`；一次性 QA/审查报告进 `qa-reviews/`，被取代文件进 `archive/`（不要删除）。
2. `CURRENT_FOCUS.md` 是 kanban 派发的**状态锚点**——阶段收口时必须刷新（9/14 曾因过期误导过 agent）。
3. 顶层文件里含 `docs/xxx.md` 路径引用的，移动文件后须同步更新（9/16 重构时已批量修正 7 处）。
4. `ROADMAP.md` / `DECISIONS.md` 被各 profile 的 `SOUL.md` 引用，**保持在顶层**。
