# ARCHITECTURE.md
## AI Agent Platform Architecture Baseline v1.0

## 1. Architecture Goal

建立一个可维护、可测试、可扩展的 Windows AI Agent 应用。

第一阶段优先考虑：

- 清晰边界
- 本地可运行
- 可观察
- 可测试
- 易于替换 AI Provider
- 易于替换 Browser Provider
- 易于扩展 Platform Adapter

不为尚未确认的未来需求进行过度工程化。

---

## 2. High-Level Architecture

```text
Windows Desktop Application
        │
      Tauri
        │
     Vue 3 UI
        │
   Application API
        │
     FastAPI
        │
 ┌──────┼──────────────┐
 │      │              │
AI    Domain        Automation
 │      │              │
 │   ┌──┼───────┐      │
 │   │  │  │    │      │
 │ Agent CRM Message   │
 │   │               Workflow
 │   │               Scheduler
 │   │                   │
 │   └──── Memory        │
 │        Knowledge     │
 │                     Browser Provider
 │                          │
 │                    BitBrowserProvider
 │                          │
 │                       Playwright
 │
AI Provider Layer
```

---

## 3. Desktop Layer

### Tauri

职责：

- Windows desktop shell
- application lifecycle
- system integration
- local process coordination where appropriate

### Vue 3

职责：

- UI
- routing
- state
- user interaction
- visual feedback

前端禁止直接访问数据库。

---

## 4. Backend Layer

FastAPI 作为应用服务层。

建议分层：

```text
API / Router
    ↓
Application Service
    ↓
Domain / Business Logic
    ↓
Data Access
    ↓
PostgreSQL
```

后台任务：

```text
API
 ↓
Task Record
 ↓
Redis / Queue
 ↓
Worker
 ↓
Service / Automation
```

---

## 5. AI Layer

```text
AIProvider
   ↓
Model
   ↓
Context Builder
   ↓
Agent Service
   ↓
Decision / Tool Call
```

必须支持 Provider 替换。

AI Provider 不应该直接知道：

- PostgreSQL 细节
- BitBrowser 细节
- UI 细节

---

## 6. Agent Architecture

Agent 是业务智能主体。

```text
Agent
├── Persona
├── Memory
├── Knowledge
├── Strategy
├── Goal
├── Tools
├── Accounts
└── Workflows
```

Agent 负责：

- 理解上下文
- 判断意图
- 判断对话状态
- 选择策略
- 选择行动

执行动作由工具与 Automation Layer 完成。

---

## 7. Persona Architecture

Persona 描述：

- 身份
- 性格
- 语气
- 用词习惯
- 回复长度
- 主动程度
- 风格边界

Persona 不等于 Agent。

一个 Agent 可以使用一个主 Persona，并允许未来支持版本管理。

---

## 8. Memory Architecture

Memory 分层：

- Short-Term
- Conversation
- Customer
- Episodic
- Long-Term

Memory 记录“发生过什么、知道什么、与谁相关”。

---

## 9. Knowledge Architecture

Knowledge 表示可查询的业务知识：

- 产品
- FAQ
- 行业资料
- 公司资料
- 销售资料
- 培训资料

Knowledge 与 Memory 必须保持概念分离。

---

## 10. Platform Adapter

平台必须通过 Adapter 接入。

```text
PlatformService
   ↓
PlatformAdapter
   ├── Platform A
   ├── Platform B
   └── ...
```

业务逻辑不能直接写平台特定选择器或流程。

---

## 11. Browser Provider

V1：

```text
BrowserProvider
└── BitBrowserProvider
```

业务层只依赖 BrowserProvider 接口。

BitBrowser 的 API / CDP / Playwright 细节只存在于 Provider 层。

---

## 12. Automation Layer

```text
Agent Decision
      ↓
Action
      ↓
Automation Engine
      ↓
Browser Provider
      ↓
BitBrowser
      ↓
Playwright
```

Automation Layer 负责：

- 打开页面
- 执行操作
- 读取结果
- 返回结构化结果
- 记录执行状态

不负责决定业务目标。

---

## 13. CRM / Customer Architecture

```text
Customer
├── CustomerIdentity
├── Conversation
├── Message
├── Memory
├── Lead
├── Deal
└── Activity
```

支持一个 Customer 对应多个平台身份。

---

## 14. Workflow Architecture

Workflow：

```text
Trigger
 ↓
Condition
 ↓
Action
 ↓
Delay
 ↓
Branch
 ↓
Action
```

Workflow 不应该硬编码到某个平台实现中。

---

## 15. Scheduler Architecture

```text
Scheduler
 ↓
Task Queue
 ↓
Worker
 ↓
Execution
 ↓
Result
```

任务必须具有可观察状态，例如：

PENDING
RUNNING
SUCCESS
FAILED
CANCELLED

---

## 16. Security Boundaries

敏感数据包括：

- API Key
- Cookie
- Token
- Password
- Proxy credential
- Customer data

不得进入普通日志。

---

## 17. V1 Non-Goals

当前不实现：

- 多 Browser Provider
- 大规模云端集群
- 微服务拆分
- Kubernetes
- SaaS 多租户
- 跨平台移动客户端

除非以后有明确产品需求。

---

## 18. Architecture Change Rule

重大架构变更必须：

1. 说明问题
2. 提出方案
3. 说明替代方案
4. 说明影响
5. 更新 ADR

不能因为实现方便而偷偷改变架构。
