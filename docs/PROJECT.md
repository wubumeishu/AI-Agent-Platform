# AI Agent Platform
## Project Configuration v1.0

## 1. Project Identity

**中文名称：** AI 智能获客与私域运营平台

**英文名称：** AI Agent Growth Platform

**产品形态：** Windows 桌面应用优先，后续可扩展云端服务。

**V1 浏览器：** 仅支持 BitBrowser（比特浏览器）。

**核心定位：** AI Agent 驱动的公域获客、智能对话、客户沉淀、私域培育、商机转化与数据优化平台。

---

## 2. Product Vision

本产品不是简单的自动点击、群控或批量消息工具。

核心闭环：

公域发现 → 内容理解 → 意向判断 → 对话 → 客户画像 → CRM → 私域承接 → 持续培育 → 商机 → 成交 → 数据分析 → 策略优化。

最终目标是形成可管理、可审计、可测试、可扩展的 AI Agent 工作平台。

---

## 3. Product Principles

1. Agent 与执行器分离。
2. Persona 与 Agent 分离。
3. AI 逻辑与平台逻辑分离。
4. Platform Adapter 与业务逻辑分离。
5. Browser Provider 与业务逻辑分离。
6. Memory 与 Knowledge 分离。
7. Product、Architecture、Implementation、QA、Review 职责分离。
8. 代码存在不等于功能完成。
9. 真实运行结果优先于文字汇报。
10. 小步开发、可验证、可回退。

---

## 4. V1 Core Modules

- Dashboard
- Agent
- Persona
- Account
- Platform
- BitBrowser
- Proxy
- AI Center
- Memory
- Knowledge
- Intent
- Strategy
- Conversation / Message
- Workflow
- Scheduler
- CRM / Lead
- Customer 360
- Private Domain
- Content / Nurture
- Deal / Sales
- Analytics
- Security
- Logs / Audit
- Settings

---

## 5. V1 Technology Direction

### Desktop

- Tauri 2
- Vue 3
- TypeScript
- Vite
- Pinia
- Vue Router

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy

### Data

- PostgreSQL
- Redis

### Automation

- Playwright
- BitBrowser Provider

### AI

- Provider-agnostic architecture
- 支持云端模型与本地模型
- AI Provider 必须通过抽象层接入

---

## 6. Browser Strategy

V1 只支持 BitBrowser。

内部使用：

BrowserProvider
└── BitBrowserProvider

未来再扩展：

- AdsPowerProvider
- LocalChromiumProvider
- OtherBrowserProvider

任何业务模块不得直接依赖 BitBrowser API。

---

## 7. Core Domain Model

### Agent

Agent
├── Persona
├── Accounts
├── Platforms
├── Knowledge
├── Memory
├── Strategy
├── Goals
├── Tools
└── Workflows

### Account

Account
├── Platform
├── BrowserProfile
└── Proxy

### Customer

Customer
├── CustomerIdentity
├── Conversations
├── Messages
├── Memory
├── Leads
├── Deals
└── Activities

---

## 8. Current Development Scope

### Phase 0 — Team & Foundation

- AI 员工体系
- Soul.md
- 协作规则
- 项目配置
- Tauri/Vue 基础壳
- 基础导航

### Phase 1 — Core Resource Layer

- Agent
- Persona
- Account
- Platform
- BitBrowser
- Proxy

### Phase 2 — AI & Conversation

- AI Provider
- Model Router
- Conversation
- Persona response
- Memory
- Intent

### Phase 3 — Automation

> Status (2026-09-15): Workflow / Scheduler module complete (9 tables, nested config API + flat runtime CRUD, cron/interval scheduler with autostart, queue/worker engine with crash recovery, execution log, CRM + Conversation event bridges, 3 frontend views). QA E2E 72/72 live PASS; architecture + reliability reviews closed via t_a3f82e43 APPROVED (regression 357/357, real-Postgres E2E 9/9). ADRs this phase: ADR-013 (ExecutionLog no-FK), ADR-014 (QueueDispatcher + autostart), ADR-015 (CORS handoff to security lane). Summary + reports: `.cache/phases/phase4-workflow-summary/`.

- Workflow
- Scheduler
- Task Queue
- Browser execution

### Phase 4  CRM

> Status (2026-09-14): CRM / Lead implementation layer complete (Customer, CustomerIdentity, Lead + Intent Scoring, Tags, Lifecycle, Customer 360, integrations; 13/14 board tasks done). Open P0 follow-ups: prod DB missing 7 CRM tables, security (auth/RBAC + PII masking, ADR-011), E2E re-run pending. See docs/PHASE-3-SUMMARY.md.

- Customer
- Lead
- Customer 360
- Tags
- Pipeline

### Phase 5 — Private Domain

> Status (2026-09-14): Private Domain module implementation complete. See docs/PHASE-5-SUMMARY.md; open P0 follow-ups: security (auth/RBAC + sensitive-data protection) and NurturePlan execution engine.

- Private Domain
- Nurture
- Content
- Follow-up
- Deal

### Phase 6 — Analytics

> Status (2026-09-15): Phase 6 Analytics & Optimization complete (9 backend + 3 frontend cards). E2E QA P6AN-15 verdict PASS; architecture review P6AN-16 verdict CHANGES_REQUIRED (no P0; P1 analytics-surface auth/tenant isolation FIXED in t_3e806a29 = ADR-018, with P2-4 CORS whitelist; P2-1/2/3/5 filed as P2 follow-up cards P6AN-17). See docs/PHASE-6-SUMMARY.md.

- Dashboard
- Conversion
- ROI
- Experiment
- Optimization

---

## 9. Explicit V1 Exclusions

当前阶段不得主动实现：

- 多浏览器 Provider
- 多平台大规模同时接入
- 自动注册账号
- 绕过验证码
- 绕过平台风控或封禁
- 无差别垃圾群发
- 规避平台限制的机制
- SaaS 多租户
- 移动端 App
- 复杂计费系统
- 云端集群

除非项目 Owner 明确开启对应 Epic。

---

## 10. Definition of Done

任务只有满足其适用的全部条件后才能进入 Done：

- 实现完成
- 构建成功
- 应用/服务可启动
- 核心用户路径实际可操作
- 相关测试通过
- 无阻塞性运行错误
- 文档更新
- QA 验证通过（需要时）
- Reviewer 审核通过（需要时）
- 看板状态真实更新

---

## 11. User Experience Principle

Project Owner 非程序员。

因此进度判断必须优先通过：

- 可运行页面
- 可操作功能
- 清晰状态
- 可见错误
- 可复现结果

而不是只通过代码量或技术汇报判断进度。

---

## 12. Source of Truth

任务状态：Hermes 看板

项目原则：本项目配置文档

架构决策：ARCHITECTURE.md + ADR

角色职责：各角色 SOUL.md

需求与验收：产品任务卡

任何冲突必须升级给 Project Orchestrator，由其根据决策层级处理。
