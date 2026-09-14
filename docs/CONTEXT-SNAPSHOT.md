# AI Agent Platform - 上下文快照
**生成时间**: 2026-09-13
**任务**: t_437d6607

---

## 关键架构约束

### 技术栈
- **桌面**: Tauri 2 + Vue 3 + TypeScript + Vite + Pinia + Vue Router
- **后端**: FastAPI + SQLAlchemy（尚未实现）
- **数据库**: PostgreSQL + Redis（尚未实现）
- **浏览器自动化**: Playwright + BitBrowser Provider

### 核心原则
1. Agent 与执行器分离
2. Persona 与 Agent 分离
3. AI 逻辑与平台逻辑分离
4. Platform Adapter 与业务逻辑分离
5. Browser Provider 与业务逻辑分离
6. Memory 与 Knowledge 分离
7. Product、Architecture、Implementation、QA、Review 职责分离

### V1 限制
- 仅支持 BitBrowser
- 单平台（暂不支持多平台并发）
- 无 SaaS 多租户
- 无移动端 App

---

## 当前状态

### Phase 0 完成情况

| 任务 | 状态 | 说明 |
|------|------|------|
| P0-001 | ✅ DONE | Tauri + Vue 3 基础骨架 |
| P0-002 | ✅ DONE | 应用 Layout（Sidebar + AppLayout） |
| P0-003 | ✅ DONE | 基础路由配置 |
| P0-004 | ✅ DONE | Dashboard 空状态页面 |
| P0-005 | ⚠️ IN_PROGRESS | Settings 页面（有代码 bug 刚修复） |

### 已实现的模块
- `frontend/src/components/layout/Sidebar.vue` - 侧边导航栏
- `frontend/src/components/layout/AppLayout.vue` - 主布局
- `frontend/src/router/index.ts` - 路由配置
- `frontend/src/views/DashboardView.vue` - 工作台页面
- `frontend/src/views/SettingsView.vue` - 设置页面
- `frontend/src/stores/settings.ts` - Pinia 设置状态管理

### 待完成的模块
- Backend（FastAPI）- Phase 1 开始实现
- Database Schema
- 更多前端页面（Agent、Persona、Account 等）

---

## 已决策事项

### ADR-001
V1 使用 Tauri 作为桌面框架（已接受）

### ADR-002
V1 只支持 BitBrowser（已接受）

### ADR-003
Agent 与 Persona 分离（已接受）

### ADR-004
Platform Adapter 与业务逻辑分离（已接受）

### ADR-005
Browser Provider 与业务逻辑分离（已接受）

### ADR-006
Memory 与 Knowledge 分离（已接受）

### ADR-007
QA 与 Reviewer 独立于开发角色（已接受）

### ADR-008
Project Orchestrator 负责调度而非万能开发（已接受）

---

## 优先级规则

1. P0 - 必须完成（Phase 0 基础功能）
2. P1 - 核心产品功能
3. P2 - 增强功能
4. P3 - 以后处理

---

## 下一步行动

1. 完成 P0-005 的 QA 验证
2. 进入 Phase 1：Agent、Persona、Account、Platform、Browser、Proxy 的 CRUD 实现
3. 实现 Backend FastAPI 基础框架
4. 设计数据库 Schema

---

## 风险与问题

### P2 - 已知问题
- SettingsStore 存在语法错误（已修复）
- 缺少后端 API，所有功能目前为前端 Mock 状态
- 暂无真实数据持久化方案

### 阻塞项
- 无（P0 阶段无外部依赖）

---

**快照生成者**: project-orchestrator
