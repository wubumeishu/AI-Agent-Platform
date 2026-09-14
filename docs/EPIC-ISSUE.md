# EPIC-ISSUE — 问题池 (Issue Pool)

## 概述

**状态**: Draft  
**创建日期**: 2026-09-13  
**维护者**: Project Orchestrator  

本 Epic 用于收集开发过程中发现的非阻塞性问题，建立统一的问题池管理机制。

---

## 1. Issue 字段规范

每个 Issue 必须包含以下 12 个字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `issue_id` | 字符串 | ✅ | 唯一标识，格式：`ISS-{YYYY}-{NNN}`，如 `ISS-2026-001` |
| `type` | 枚举 | ✅ | 问题类型（见下文） |
| `severity` | 枚举 | ✅ | 严重程度（P0-P3，见下文） |
| `source_task` | 字符串 | ✅ | 发现问题时的源任务 ID |
| `affected_module` | 字符串 | ✅ | 受影响的模块/子系统 |
| `problem` | 文本 | ✅ | 问题描述（简洁清晰） |
| `expected_behavior` | 文本 | ✅ | 预期行为 |
| `actual_behavior` | 文本 | ✅ | 实际行为 |
| `impact` | 文本 | ✅ | 影响范围评估 |
| `suggested_solution` | 文本 | ❌ | 建议解决方案（如有） |
| `dependencies` | 数组 | ❌ | 前置依赖 Issue ID |
| `acceptance_criteria` | 文本 | ✅ | 验收标准（修复后如何验证） |

---

## 2. 问题类型 (Type)

| 类型 | 标识 | 说明 |
|------|------|------|
| Bug | `bug` | 功能缺陷、行为错误 |
| 技术债 | `tech-debt` | 代码质量问题、待重构 |
| UX 问题 | `ux` | 用户体验缺陷、交互问题 |
| 性能问题 | `performance` | 响应慢、资源占用过高 |
| 安全问题 | `security` | 安全隐患、漏洞 |
| 文档缺失 | `docs` | 文档不全、过时 |
| 测试覆盖 | `test` | 缺少测试用例 |

---

## 3. 严重程度标准 (Severity)

### P0 — 阻塞级 (Blocker)

**定义**: 核心流程无法运行、数据损坏、安全风险

**典型场景**:
- 应用无法启动
- 数据库连接失败
- 关键业务流程阻断
- 数据丢失或损坏
- 安全漏洞导致凭证泄露

**处理规则**:
- ✅ 必须停止相关任务链
- ✅ 必须立即修复
- ❌ 不得进入下一阶段

---

### P1 — 严重级 (Critical)

**定义**: 严重功能问题，影响核心使用

**典型场景**:
- 核心功能异常但可绕过的
- 性能严重下降影响使用
- 重要模块功能失效

**处理规则**:
- ⚠️ 暂停受影响模块
- ✅ 独立任务可继续
- 📅 应在当前 Sprint 内修复

---

### P2 — 普通级 (Normal)

**定义**: 普通 Bug、技术债、UX 问题

**典型场景**:
- 非核心功能异常
- 界面显示问题
- 文案错误
- 可优化的体验细节

**处理规则**:
- ✅ 进入问题池
- ✅ 不影响独立任务
- 📅 按需安排修复

---

### P3 — 轻微级 (Minor)

**定义**: 轻微优化、文案、视觉细节

**典型场景**:
- 界面美化需求
- 文案优化
- 非阻塞性建议

**处理规则**:
- ✅ 进入待优化池
- ✅ 有空闲时处理
- 📅 不强制修复

---

## 4. Issue 状态机

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   OPEN ──→ TRIAGE ──→ READY ──→ IN PROGRESS ──→ QA ──→ DONE │
│                                                             │
│    ↑                                                       │
│    │                                                        │
│    └────────────────────────────────────────────────────────┘
│              （可能循环回 TRIAGE 或 DONE）
│
│  可选终止状态:
│    WONT FIX — 决定不修复
│    DUPLICATE — 重复 Issue
└─────────────────────────────────────────────────────────────┘
```

### 状态定义

| 状态 | 说明 | 转换条件 |
|------|------|----------|
| `OPEN` | 新发现的问题，尚未评审 | 自动创建 |
| `TRIAGE` | 正在分类和评估 | P0/P1 自动进入；P2/P3 由 Orchestrator 评审 |
| `READY` | 已准备好修复 | TRIAGE 评审通过后 |
| `IN PROGRESS` | 正在修复 | 分配给开发者 |
| `QA` | 等待验证 | 开发完成 |
| `DONE` | 已修复并验证通过 | QA 验证通过后 |
| `WONT FIX` | 决定不修复 | 评审后决策 |
| `DUPLICATE` | 重复 Issue | 发现重复时标记 |

---

## 5. 工作流程规则

### 5.1 问题发现

```
主任务执行中发现问题
    ↓
判断严重程度 (P0-P3)
    ↓
搜索现有 Issue（避免重复）
    ↓
┌─ P0/P1 ───→ 创建 Issue → 关联 Source Task → 阻塞相关任务
├─ P2 ──────→ 创建 Issue → 关联 Source Task → 主任务继续
└─ P3 ──────→ 创建 Issue → 关联 Source Task → 进入待优化池
```

### 5.2 Issue 创建规则

1. **必须关联 Source Task**: 每个 Issue 必须记录发现来源
2. **保留上下文**: 记录复现步骤、错误日志、截图路径
3. **避免重复**: 创建前搜索同类 Issue
4. **字段完整**: 必填字段缺失不得创建

### 5.3 修复流程

```
READY → IN PROGRESS → QA → DONE
                ↓
           修复完成
                ↓
         执行验证测试
                ↓
        ┌───────┴───────┐
        ↓               ↓
     通过 QA          未通过
        ↓               ↓
      DONE            IN PROGRESS (重新修复)
```

### 5.4 状态变更规则

| 变更 | 执行者 | 条件 |
|------|--------|------|
| OPEN → TRIAGE | Orchestrator | Issue 创建后 |
| TRIAGE → READY | Orchestrator | 评审通过，优先级确定 |
| READY → IN PROGRESS | Developer | 开始修复 |
| IN PROGRESS → QA | Developer | 修复完成，提交代码 |
| QA → DONE | QA Engineer | 验证通过 |
| QA → IN PROGRESS | QA Engineer | 验证未通过 |
| 任意 → WONT FIX | Orchestrator | 评审决定 |
| 任意 → DUPLICATE | Orchestrator | 发现重复 |

---

## 6. Issue 模板

### Markdown Issue 模板

```markdown
## ISS-{YYYY}-{NNN}: {问题标题}

**Type:** bug | tech-debt | ux | performance | security | docs | test
**Severity:** P0 | P1 | P2 | P3
**Source Task:** {task_id}
**Affected Module:** {module_name}

### Problem
{问题描述}

### Expected Behavior
{预期行为}

### Actual Behavior
{实际行为}

### Impact
{影响范围}

### Steps to Reproduce
1. ...
2. ...
3. ...

### Suggested Solution
{建议方案}

### Dependencies
- {依赖 Issue ID}

### Acceptance Criteria
- [ ] {验收标准1}
- [ ] {验收标准2}
```

---

## 7. 问题池管理规范

### 7.1 评审机制

- **P0/P1**: 每个 Issue 必须经过评审
- **P2/P3**: 按批次评审，合并处理

### 7.2 清理机制

- 已完成 Issue 保留历史记录，不得删除
- 重复 Issue 合并，保留最早创建的
- 未修复 Issue 定期回顾（建议每 Sprint）

### 7.3 报告机制

- 每周生成 Issue 统计报告
- 追踪修复趋势
- 识别高频问题模块

---

## 8. 示例 Issue

### 示例 1: P2 Bug

```markdown
## ISS-2026-001: Dashboard 加载时闪烁问题

**Type:** bug
**Severity:** P2
**Source Task:** t_032b0f54
**Affected Module:** frontend/dashboard

### Problem
Dashboard 页面在数据加载过程中出现明显闪烁，影响用户体验

### Expected Behavior
数据加载过程平滑过渡，无闪烁

### Actual Behavior
页面内容在加载完成后突然替换，产生闪烁感

### Impact
中等 — 影响首屏体验，但不阻断核心流程

### Steps to Reproduce
1. 打开 Dashboard
2. 等待数据加载完成
3. 观察页面渲染过程

### Acceptance Criteria
- [ ] 加载过程使用骨架屏或渐进式加载
- [ ] 无明显视觉闪烁
```

### 示例 2: P1 Performance

```markdown
## ISS-2026-002: Agent 列表页面滚动性能差

**Type:** performance
**Severity:** P1
**Source Task:** t_xxx
**Affected Module:** frontend/agent-list

### Problem
Agent 列表超过 50 条时滚动卡顿明显

### Expected Behavior
流畅滚动，无卡顿

### Actual Behavior
滚动帧率降至 30fps 以下

### Impact
严重 — 影响大数据量下的可用性

### Acceptance Criteria
- [ ] 滚动帧率保持在 60fps
- [ ] 支持虚拟滚动或分页
```

---

## 9. 与看板的集成

### 9.1 Issue 卡创建

- Issue 作为独立 Kanban Card 管理
- 标签包含: `ISS-{ID}`, `P{N}`, 类型标签
- 优先级字段映射到 severity

### 9.2 状态同步

- Kanban 状态与 Issue 状态机保持同步
- 状态变更需记录原因

### 9.3 关联关系

- Issue → Source Task (父关联)
- Issue → Fix Task (子关联)
- Issue ↔ Issue (依赖关联)

---

## 10. 生效条件

- [x] 文档定义完成
- [ ] Project Orchestrator 确认
- [ ] 团队培训完成
- [ ] 看板集成配置完成

---

*文档版本: 1.0*
*最后更新: 2026-09-13*
