# DECISIONS.md
## Architecture & Product Decision Log

## ADR-001 — V1 使用 Tauri 作为桌面框架

**Status:** Accepted

**Decision:** Windows 桌面端 V1 使用 Tauri + Vue 3。

**Reason:** 需要桌面应用能力，同时希望保持前端开发效率与较低资源开销。

---

## ADR-002 — V1 只支持 BitBrowser

**Status:** Accepted

**Decision:** 第一阶段 BrowserProvider 只实现 BitBrowserProvider。

**Reason:** 降低初期复杂度，先完成真实闭环。

**Future:** 未来可扩展其他 Provider。

---

## ADR-003 — Agent 与 Persona 分离

**Status:** Accepted

**Decision:** Persona 描述“是谁和怎么说”，Agent 描述“谁在工作并拥有何种能力”。

---

## ADR-004 — Platform Adapter 与业务逻辑分离

**Status:** Accepted

**Decision:** 平台差异通过 Adapter 隔离。

---

## ADR-005 — Browser Provider 与业务逻辑分离

**Status:** Accepted

**Decision:** 业务层不得直接依赖 BitBrowser 实现细节。

---

## ADR-006 — Memory 与 Knowledge 分离

**Status:** Accepted

**Decision:** Memory 表示发生过什么及客户相关记忆；Knowledge 表示可查询的业务知识。

---

## ADR-007 — QA 与 Reviewer 独立于开发角色

**Status:** Accepted

**Decision:** 开发员工不应独自完成开发、验收和最终质量确认。

---

## ADR-008 — Project Orchestrator 负责调度而非万能开发

**Status:** Accepted

**Decision:** project-orchestrator 负责任务分解、路由、依赖、流程和看板状态，不作为默认万能开发者。
