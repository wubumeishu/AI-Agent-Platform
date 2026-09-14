# Phase 1 架构设计文档：Resource Layer

**项目**: AI Agent Platform
**版本**: v1.0
**日期**: 2026-09-13
**任务**: t_508443dc

---

## 1. 前端页面路由结构

### 1.1 路由层级图

```
/ (AppLayout)
├── /                          → HomeView（首页）
├── /about                     → AboutView（关于）
├── /dashboard                 → DashboardView（工作台）
│
├── /agents                    → AgentsView（Agent 列表）
│   └── /agents/:id            → AgentDetailView（Agent 详情）
│       ├── /agents/:id/persona  → AgentPersonaView（配置 Persona）
│       └── /agents/:id/accounts → AgentAccountsView（绑定账号）
│
├── /personas                  → PersonasView（Persona 列表）
│   └── /personas/:id          → PersonaDetailView（详情/编辑）
│
├── /accounts                  → AccountsView（账号列表）
│   └── /accounts/:id          → AccountsDetailView（详情）
│       ├── /accounts/:id/agent-binding  → 绑定 Agent
│       ├── /accounts/:id/browser-binding → 绑定 Browser
│       └── /accounts/:id/proxy-binding  → 绑定 Proxy
│
├── /platforms                 → PlatformsView（平台注册表）
│
├── /browsers                  → BrowsersView（浏览器管理）
│
└── /proxies                   → ProxyView（代理管理）

/settings                      → SettingsView（应用设置，已有）
/:pathMatch(.*)*               → NotFoundView
```

### 1.2 路由配置变更（frontend/src/router/index.ts）

新增路由如下（保留现有路由不变）：

| 路径 | Name | 组件 | 说明 |
|------|------|------|------|
| `/agents` | agents | AgentsView | Agent 列表（已有占位） |
| `/agents/:id` | agent-detail | AgentDetailView | Agent 详情 |
| `/agents/:id/persona` | agent-persona | AgentPersonaView | Agent 配置 |
| `/personas` | personas | PersonasView | Persona 列表 |
| `/personas/:id` | persona-detail | PersonaDetailView | Persona 详情 |
| `/accounts` | accounts | AccountsView | 账号列表（已有占位） |
| `/accounts/:id` | account-detail | AccountsDetailView | 账号详情 |
| `/platforms` | platforms | PlatformsView | 平台管理 |
| `/browsers` | browsers | BrowsersView | 浏览器管理 |
| `/proxies` | proxies | ProxyView | 代理管理 |

---

## 2. 各页面组件树

### 2.1 AgentsView（Agent 列表页）

```
AgentsView
├── PageHeader          # 页面标题 + "新建"按钮
├── AgentFilterBar      # 搜索 + 状态筛选
├── AgentList           # 卡片列表
│   └── AgentCard       # 单个 Agent 卡片
│       ├── AgentAvatar
│       ├── AgentName
│       ├── StatusBadge
│       ├── PersonaTag
│       └── ActionMenu  # 编辑/删除/配置
└── AgentCreateDialog   # 创建 Agent 弹窗
```

### 2.2 AgentDetailView（Agent 详情页）

```
AgentDetailView
├── PageHeader          # 返回按钮 + 标题
├── AgentInfoCard       # 基本信息（名称、描述、创建时间）
├── AgentTabs           # 三个子标签页
│   ├── TabPersonas     # 当前 Persona 配置
│   │   ├── PersonaSelector    # Persona 选择器
│   │   └── StyleParamsForm    # 风格参数表单
│   ├── TabAccounts     # 绑定账号
│   │   ├── AccountPicker      # 选择账号弹窗
│   │   └── BoundAccountList   # 已绑定账号列表
│   └── TabConfig       # Agent 参数配置
│       ├── LLMConfig      # AI Provider / Model 配置
│       └── ToolConfig     # 可用工具开关
└── AgentActions        # 启动/停止/删除操作栏
```

### 2.3 PersonasView（Persona 列表页）

```
PersonasView
├── PageHeader
├── PersonaList         # 卡片网格
│   └── PersonaCard
│       ├── PersonaIcon
│       ├── PersonaName
│       ├── StylePreview    # 风格摘要预览
│       └── VersionBadge    # 当前版本号
└── PersonaCreateDialog
```

### 2.4 PersonaDetailView（Persona 详情/编辑）

```
PersonaDetailView
├── PageHeader
├── PersonaEditor
│   ├── BasicInfoSection    # 名称、描述、图标
│   ├── StyleParamsSection  # 性格参数（语气/长度/主动性）
│   ├── VersionHistory      # 版本记录（baseline）
│   └── TestChatSection     # 预览效果
└── SaveCancelActions
```

### 2.5 AccountsView（账号列表页）

```
AccountsView
├── PageHeader
├── AccountFilterBar      # 平台筛选 + 状态筛选
├── AccountList
│   └── AccountCard
│       ├── PlatformIcon  # 平台类型标识
│       ├── AccountName
│       ├── StatusDot     # 在线/离线/异常
│       ├── BoundAgentTag # 已绑 Agent
│       └── ConnectionBtn # 连接测试
└── AccountCreateDialog
```

### 2.6 AccountsDetailView（账号详情）

```
AccountsDetailView
├── PageHeader
├── AccountInfoCard       # 账号基本信息
├── AccountTabs
│   ├── TabAgentBinding   # Agent 绑定管理
│   │   └── AgentBindingList
│   ├── TabBrowserBinding # Browser 绑定
│   │   └── BrowserProfileSelector
│   └── TabProxyBinding   # Proxy 绑定
│       └── ProxySelector
└── ConnectionStatusCard  # 实时连接状态
```

### 2.7 PlatformsView（平台注册表）

```
PlatformsView
├── PageHeader
├── PlatformRegistry      # 平台卡片列表
│   └── PlatformCard
│       ├── PlatformLogo
│       ├── PlatformName
│       ├── CapabilitiesTags  # 能力标签
│       └── AdapterStatus     # 适配器状态
└── PlatformAddModal
```

### 2.8 BrowsersView（浏览器管理）

```
BrowsersView
├── PageHeader
├── BrowserProviderBanner  # BitBrowser 连接状态横幅
├── BrowserProfileList    # Profile 列表
│   └── BrowserProfileCard
│       ├── ProfileName
│       ├── ProfileId
│       ├── StatusIndicator
│       └── ConnectionBtn
└── ProfileCreateModal
```

### 2.9 ProxyView（代理管理）

```
ProxyView
├── PageHeader
├── ProxyList
│   └── ProxyCard
│       ├── ProxyType     # HTTP/SOCKS5
│       ├── ProxyAddress
│       ├── StatusDot
│       └── TestConnBtn
└── ProxyCreateDialog
```

---

## 3. 后端 API 接口列表（RESTful）

> 基础路径：`/api/v1`

### 3.1 Agent 相关

```
GET    /api/v1/agents                    # 列出所有 Agent（支持分页/筛选）
POST   /api/v1/agents                    # 创建 Agent
GET    /api/v1/agents/{id}               # 获取 Agent 详情
PUT    /api/v1/agents/{id}               # 更新 Agent 基本信息
DELETE /api/v1/agents/{id}               # 删除 Agent（软删除）
POST   /api/v1/agents/{id}/start         # 启动 Agent
POST   /api/v1/agents/{id}/stop          # 停止 Agent
GET    /api/v1/agents/{id}/status        # 获取 Agent 运行状态
```

### 3.2 Persona 相关

```
GET    /api/v1/personas                  # 列出所有 Persona
POST   /api/v1/personas                  # 创建 Persona
GET    /api/v1/personas/{id}             # 获取 Persona 详情
PUT    /api/v1/personas/{id}             # 更新 Persona
DELETE /api/v1/personas/{id}             # 删除 Persona
GET    /api/v1/personas/{id}/versions    # 获取版本历史
POST   /api/v1/personas/{id}/clone       # 克隆 Persona（创建新版本）
```

### 3.3 Account 相关

```
GET    /api/v1/accounts                  # 列出所有账号
POST   /api/v1/accounts                  # 创建账号
GET    /api/v1/accounts/{id}             # 获取账号详情
PUT    /api/v1/accounts/{id}             # 更新账号
DELETE /api/v1/accounts/{id}             # 删除账号
POST   /api/v1/accounts/{id}/test-conn   # 测试账号连接
```

### 3.4 绑定关系

```
GET    /api/v1/accounts/{id}/agent-bindings    # 获取账号的 Agent 绑定列表
POST   /api/v1/accounts/{id}/agent-bindings    # 绑定 Agent
DELETE /api/v1/accounts/{id}/agent-bindings/{bind_id}  # 解除绑定

GET    /api/v1/accounts/{id}/browser-profiles  # 获取可用 Browser Profile
POST   /api/v1/accounts/{id}/browser-bindings  # 绑定 Browser
DELETE /api/v1/accounts/{id}/browser-bindings/{bind_id}

GET    /api/v1/accounts/{id}/proxy-bindings    # 获取 Proxy 绑定
POST   /api/v1/accounts/{id}/proxy-bindings    # 绑定 Proxy
DELETE /api/v1/accounts/{id}/proxy-bindings/{bind_id}
```

### 3.5 Platform 相关

```
GET    /api/v1/platforms                   # 列出已注册平台
POST   /api/v1/platforms                   # 注册新平台
GET    /api/v1/platforms/{id}              # 获取平台详情
PUT    /api/v1/platforms/{id}              # 更新平台配置
DELETE /api/v1/platforms/{id}              # 注销平台
POST   /api/v1/platforms/{id}/test         # 测试平台连接
```

### 3.6 Browser Provider 相关

```
GET    /api/v1/browsers/providers          # 列出可用 Provider（V1 仅 BitBrowser）
GET    /api/v1/browsers/providers/bitbrowser/status  # BitBrowser 连接状态
POST   /api/v1/browsers/providers/bitbrowser/test    # 测试 BitBrowser 连接
GET    /api/v1/browsers/profiles         # 获取 Profile 列表
POST   /api/v1/browsers/profiles         # 创建 Profile
PUT    /api/v1/browsers/profiles/{id}    # 更新 Profile
DELETE /api/v1/browsers/profiles/{id}    # 删除 Profile
```

### 3.7 Proxy 相关

```
GET    /api/v1/proxies                     # 列出所有代理
POST   /api/v1/proxies                     # 创建代理
GET    /api/v1/proxies/{id}                # 获取代理详情
PUT    /api/v1/proxies/{id}                # 更新代理
DELETE /api/v1/proxies/{id}                # 删除代理
POST   /api/v1/proxies/{id}/test           # 测试代理连通性
```

### 3.8 响应格式规范

```json
// 成功响应
{
  "code": 0,
  "message": "success",
  "data": { ... }
}

// 分页响应
{
  "code": 0,
  "data": {
    "items": [...],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}

// 错误响应
{
  "code": 4001,
  "message": "Agent not found",
  "detail": { ... }
}
```

---

## 4. 数据库模型设计

### 4.1 实体关系总览

```
Agent (1) ──M┐
              ├──→ AccountBinding ──→ Account (M)
Personа (1) ──M┘
              │
              └──→ Agent (1)

Account ──M──→ BrowserBinding ──→ BrowserProfile (1)
Account ──M──→ ProxyBinding   ──→ Proxy (1)

Platform ──M──→ AccountBinding（多平台支持时扩展）
```

### 4.2 数据表设计

#### agent（Agent 表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 主键 |
| name | VARCHAR(100) | NOT NULL | Agent 名称 |
| description | TEXT | | 描述 |
| status | VARCHAR(20) | NOT NULL | running/stopped/error |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | 更新时间 |
| is_deleted | BOOLEAN | DEFAULT false | 软删除标记 |

#### persona（Persona 表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 主键 |
| name | VARCHAR(100) | NOT NULL | Persona 名称 |
| description | TEXT | | 描述 |
| personality | JSONB | NOT NULL | 性格参数（语气/长度/主动性等）|
| version | INTEGER | DEFAULT 1 | 版本号 |
| parent_id | UUID | FK → persona.id | 父版本（用于版本历史）|
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | 更新时间 |
| is_deleted | BOOLEAN | DEFAULT false | 软删除标记 |

#### account（账号表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 主键 |
| platform_id | VARCHAR(50) | NOT NULL | 平台标识（如 wechat, douyin）|
| name | VARCHAR(100) | NOT NULL | 账号名称 |
| username | VARCHAR(200) | | 登录用户名 |
| password_encrypted | TEXT | | 加密密码 |
| status | VARCHAR(20) | NOT NULL | connected/disconnected/failed |
| last_login | TIMESTAMPTZ | | 最后登录时间 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | 更新时间 |
| is_deleted | BOOLEAN | DEFAULT false | 软删除标记 |

#### agent_persona_binding（Agent-Persona 绑定表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| agent_id | UUID | FK → agent.id, PK | Agent ID |
| persona_id | UUID | FK → persona.id, PK | Persona ID |
| is_primary | BOOLEAN | DEFAULT false | 是否为主 Persona |
| bound_at | TIMESTAMPTZ | NOT NULL | 绑定时间 |

#### browser_profile（浏览器 Profile 表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 主键 |
| provider | VARCHAR(50) | NOT NULL | Provider 类型（bitbrowser）|
| profile_id | VARCHAR(100) | NOT NULL | BitBrowser Profile ID |
| name | VARCHAR(100) | | Profile 名称 |
| connection_status | VARCHAR(20) | | connected/disconnected |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | 更新时间 |
| is_deleted | BOOLEAN | DEFAULT false | 软删除标记 |

#### account_browser_binding（账号-Browser 绑定表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| account_id | UUID | FK → account.id, PK | 账号 ID |
| profile_id | UUID | FK → browser_profile.id, PK | Profile ID |
| bound_at | TIMESTAMPTZ | NOT NULL | 绑定时间 |

#### proxy（代理表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 主键 |
| name | VARCHAR(100) | NOT NULL | 代理名称 |
| type | VARCHAR(10) | NOT NULL | http/https/socks5 |
| host | VARCHAR(200) | NOT NULL | 主机地址 |
| port | INTEGER | NOT NULL | 端口 |
| username | VARCHAR(100) | | 认证用户名 |
| password_encrypted | TEXT | | 认证密码 |
| status | VARCHAR(20) | | active/inactive/failed |
| last_tested | TIMESTAMPTZ | | 最后测试时间 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | 更新时间 |
| is_deleted | BOOLEAN | DEFAULT false | 软删除标记 |

#### account_proxy_binding（账号-Proxy 绑定表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| account_id | UUID | FK → account.id, PK | 账号 ID |
| proxy_id | UUID | FK → proxy.id, PK | 代理 ID |
| bound_at | TIMESTAMPTZ | NOT NULL | 绑定时间 |

#### platform（平台注册表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 主键 |
| code | VARCHAR(50) | UNIQUE NOT NULL | 平台编码 |
| name | VARCHAR(100) | NOT NULL | 平台名称 |
| capabilities | JSONB | | 支持的能力列表 |
| adapter_class | VARCHAR(200) | | 适配器类路径 |
| config | JSONB | | 平台配置 |
| status | VARCHAR(20) | DEFAULT active | 启用状态 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |
| is_deleted | BOOLEAN | DEFAULT false | 软删除标记 |

---

## 5. 依赖关系与并行开发指南

### 5.1 任务依赖图

```
                    t_508443dc (本任务 - 架构设计)
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         t_07952902   t_8b485ac7   (独立)
         后端框架      前端框架
              │          │
         ┌────┴────┬────┴────┐
         ▼         ▼         ▼
      API实现    页面实现   Store/Client
    (Agent等)  (Agent等)  (Axios配置)
```

### 5.2 可并行任务

以下模块在 **架构设计确认后** 可以并行开发：

| 模块 | 说明 | 并行性 |
|------|------|--------|
| Agent CRUD | 独立的 CRUD 逻辑 | ✅ 可并行 |
| Persona CRUD | 独立的 CRUD 逻辑 | ✅ 可并行 |
| Account CRUD | 独立的 CRUD 逻辑 | ✅ 可并行 |
| Platform 注册 | 独立的 CRUD 逻辑 | ✅ 可并行 |
| Browser 管理 | 依赖 BitBrowser SDK | ⚠️ 需确认 SDK |
| Proxy CRUD | 独立的 CRUD 逻辑 | ✅ 可并行 |

### 5.3 阻塞依赖

| 任务 | 阻塞于 | 原因 |
|------|--------|------|
| 前端页面实现 | 本任务（路由设计） | 需要路由和组件结构 |
| 后端 API 实现 | 本任务（接口设计） | 需要接口定义 |
| Browser 管理 | BitBrowser SDK 安装 | 需要确认 API |
| 数据库迁移 | 本任务（模型设计） | 需要 Schema |

---

## 6. 前端文件变更清单

### 6.1 新增文件

```
frontend/src/
├── router/index.ts              # 更新：新增路由
├── views/
│   ├── AgentsView.vue           # 已有（需增强）
│   ├── AgentDetailView.vue      # 新增
│   ├── AgentPersonaView.vue     # 新增
│   ├── AgentAccountsView.vue    # 新增
│   ├── PersonasView.vue         # 新增
│   ├── PersonaDetailView.vue    # 新增
│   ├── AccountsView.vue         # 已有（需增强）
│   ├── AccountsDetailView.vue   # 新增
│   ├── PlatformsView.vue        # 新增
│   ├── BrowsersView.vue         # 新增
│   └── ProxyView.vue            # 新增
├── components/
│   ├── agent/
│   │   ├── AgentCard.vue
│   │   ├── AgentFilterBar.vue
│   │   └── AgentCreateDialog.vue
│   ├── persona/
│   │   ├── PersonaCard.vue
│   │   └── PersonaEditor.vue
│   ├── account/
│   │   ├── AccountCard.vue
│   │   └── AccountCreateDialog.vue
│   └── browser/
│       ├── BrowserProfileCard.vue
│       └── BrowserStatusBanner.vue
├── stores/
│   ├── agent.ts                 # 新增：Agent store
│   ├── persona.ts               # 新增：Persona store
│   ├── account.ts               # 新增：Account store
│   ├── browser.ts               # 新增：Browser store
│   └── proxy.ts                 # 新增：Proxy store
└── api/
    └── client.ts                # 新增：Axios 客户端配置
```

### 6.2 修改文件

```
frontend/src/router/index.ts     # 新增路由定义
frontend/src/components/layout/Sidebar.vue  # 新增菜单项
```

---

## 7. 后端文件变更清单（供参考）

```
backend/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   ├── base.py          # 已有
│   │   ├── agent.py         # 新增
│   │   ├── persona.py       # 新增
│   │   ├── account.py       # 新增
│   │   ├── platform.py      # 新增
│   │   ├── browser.py       # 新增
│   │   └── proxy.py         # 新增
│   ├── schemas/
│   │   ├── agent.py         # 新增
│   │   ├── persona.py       # 新增
│   │   ├── account.py       # 新增
│   │   └── common.py        # 新增（分页/错误响应）
│   ├── routers/
│   │   ├── agents.py        # 新增
│   │   ├── personas.py      # 新增
│   │   ├── accounts.py      # 新增
│   │   ├── platforms.py     # 新增
│   │   ├── browsers.py      # 新增
│   │   └── proxies.py       # 新增
│   └── services/
│       ├── agent_service.py
│       ├── persona_service.py
│       ├── account_service.py
│       └── browser_service.py
└── alembic/
    └── versions/              # 数据库迁移文件
```

---

## 8. 设计决策记录（ADR）

### ADR-009: Phase 1 Resource Layer 路由命名

**问题**: 如何组织 Resource Layer 的前端路由？

**决策**: 使用平铺式命名（`/agents`, `/personas`, `/accounts`），详情页使用路径参数（`/agents/:id`）。子功能通过 tabs 内嵌在详情页中，不单独建路由层级。

**理由**: 
- 平铺路由易于理解和维护
- 详情页 tabs 减少路由复杂度
- 符合常见管理后台模式

**替代方案**: 嵌套路由（如 `/agents/:id/config`）→ 路由层级过深，不利于 SEO 和 bookmark

### ADR-010: 单 Provider 限制

**问题**: V1 是否支持多 Browser Provider？

**决策**: V1 仅支持 BitBrowser，但架构上通过 BrowserProvider 接口层隔离，未来可平滑扩展。

**理由**: 符合 ARCHITECTURE.md V1 Non-Goals，避免过度工程化。

---

## 9. 交付物清单

| 文件 | 路径 | 内容 |
|------|------|------|
| 本文档 | `docs/PHASE1-ARCHITECTURE.md` | 完整架构设计 |
| API 设计 | `docs/PHASE1-API-SPEC.md` | 详细接口规范 |
| DB Schema | `docs/PHASE1-DB-SCHEMA.md` | SQL 建表语句 |
