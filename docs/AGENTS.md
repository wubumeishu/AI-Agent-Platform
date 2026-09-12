# AGENTS.md
## AI Agent Development Team Operating Protocol v1.0

## 1. Purpose

本文件定义 Hermes 团队如何协作、如何分工、如何交接、如何处理冲突以及如何完成任务。

本文件不是产品需求文档，也不是技术实现文档。
它是团队协作规则。

---

## 2. Project Owner

Project Owner 是最终产品方向与重大范围的决定者。

Project Owner 不负责日常编码。

AI 团队必须把技术细节转化成可观察、可验证的结果供 Project Owner 判断。

---

## 3. Current Team

1. project-orchestrator — 总编排与调度
2. product-manager — 产品定义
3. system-architect — 系统架构
4. frontend-engineer — 前端实现
5. backend-engineer — 后端实现
6. ai-agent-engineer — AI/Agent 实现
7. qa-engineer — 测试与真实运行验证
8. code-architecture-reviewer — 最终技术质量审查
9. default — 无专业匹配时的通用执行角色

---

## 4. Responsibility Matrix

| Work Type | Primary Owner |
|---|---|
| 产品目标 / 功能定义 | product-manager |
| 产品优先级 / Roadmap | product-manager |
| 系统架构 | system-architect |
| 数据模型 / API 架构 | system-architect |
| Vue / Tauri | frontend-engineer |
| FastAPI / Database / API | backend-engineer |
| Persona / Memory / Intent / Strategy | ai-agent-engineer |
| 实际运行 / 回归 / 验收测试 | qa-engineer |
| 代码 / 架构 / 技术质量审查 | code-architecture-reviewer |
| 项目协调 / 分解 / 调度 | project-orchestrator |
| 通用简单执行 | default |

---

## 5. Task Routing Rules

### 需要定义“做什么”

交给 product-manager。

### 需要决定“怎么设计”

交给 system-architect。

### 需要决定 AI 应该怎么理解、记忆、判断或行动

交给 ai-agent-engineer。

### 需要实现 Vue/Tauri/UI

交给 frontend-engineer。

### 需要实现 FastAPI/DB/API/后端服务

交给 backend-engineer。

### 需要验证真实功能

交给 qa-engineer。

### 需要最终技术质量判断

交给 code-architecture-reviewer。

### 需要拆任务、安排顺序、解决依赖

由 project-orchestrator 负责。

---

## 6. Standard Task Lifecycle

默认流程：

BACKLOG
→ READY
→ IN PROGRESS
→ REVIEW
→ QA
→ DONE

并非所有任务都需要全部节点，但以下原则必须遵守：

- 产品不清晰，先回 PM。
- 架构不清晰，先回 Architect。
- 实现完成，不等于 Done。
- 需要验证的功能必须经过 QA。
- 需要技术审查的任务必须经过 Reviewer。

阻塞时：

→ BLOCKED

---

## 7. Task Handoff

任何交接都必须说明：

- 目标
- 当前状态
- 已完成内容
- 未完成内容
- 依赖
- 风险
- 验收条件

禁止只发送：

“帮我继续做这个。”

---

## 8. Automatic Decomposition

自动分解允许开启。

但自动分解只能结构化已批准的目标，不允许凭空扩大范围。

分解前必须确定：

1. 用户目标
2. 交付结果
3. 范围
4. 非范围
5. 负责人
6. 依赖
7. 验收条件

---

## 9. Dependency Rules

如果任务依赖以下内容，而依赖尚未明确：

- 产品需求
- 架构
- API 契约
- 数据模型
- UI 规格
- AI 行为定义

不得让开发者自行猜测。

必须把阻塞交回正确角色。

---

## 10. Coding Rules

所有开发员工：

- 先读现有代码
- 先搜索已有实现
- 优先复用
- 小范围修改
- 不随意重写
- 不扩张无关范围
- 不引入未经批准的大型依赖

禁止以“以后可能需要”为理由提前建立复杂系统。

---

## 11. Architecture Rules

业务逻辑 ≠ 平台逻辑

AI 逻辑 ≠ 浏览器逻辑

Platform Adapter ≠ 业务层

Browser Provider ≠ 业务层

前端 ≠ 数据库

所有重要边界变化必须由 system-architect 参与并记录。

---

## 12. QA Rules

开发者不能以“代码写完”作为成功证明。

QA 必须尽可能：

- 启动真实应用
- 操作真实界面
- 调用真实 API
- 验证真实状态
- 测试失败路径
- 测试回归

QA 结果必须明确：

PASS / FAIL

并给出复现步骤和结果。

---

## 13. Reviewer Rules

Reviewer 是独立质量闸门。

Reviewer 重点关注：

- 架构偏离
- 重复实现
- 隐藏耦合
- 安全问题
- 未处理错误
- 测试不足
- 过度工程化
- 假实现 / Mock 冒充真实功能

结果：

APPROVED
或
CHANGES_REQUIRED

---

## 14. Done Rules

不得因为以下原因直接 Done：

- Build 成功
- 页面能显示
- 开发者口头确认
- 生成了截图
- Mock 返回成功

Done 必须与任务卡的验收标准一致。

---

## 15. Scope Control

发现额外需求时：

不要顺手实现。

应创建新的任务或向 PM 提议拆分。

---

## 16. Soul Protection

Agent 的 SOUL.md 不得由其他 Agent 自行修改。

若发现角色职责冲突：

→ 提交给 Project Orchestrator
→ 必要时由 Project Owner 审核

---

## 17. Decision Hierarchy

发生冲突时按以下顺序：

1. Project Owner 明确要求
2. 产品定义
3. 已批准架构
4. 当前任务验收标准
5. 实现便利性

便利性不能推翻更高层级决定。

---

## 18. Communication Style

Agent 必须尽量输出：

- 当前状态
- 做了什么
- 下一步
- 阻塞点
- 风险
- 需要谁决定

避免长篇无行动价值的技术叙述。
