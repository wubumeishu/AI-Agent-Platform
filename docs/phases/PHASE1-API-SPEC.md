# Phase 1 API 接口详细规范

**基于**: PHASE1-ARCHITECTURE.md
**版本**: v1.0

---

## 通用规范

### Base URL
```
http://localhost:8000/api/v1
```

### 认证方式
- 暂无（V1 本地桌面应用，暂不实现认证）
- 预留 `Authorization: Bearer <token>` 头

### 响应格式
```json
{
  "code": 0,
  "message": "success",
  "data": { }
}
```

### 错误码
| code | 含义 |
|------|------|
| 0 | 成功 |
| 4001 | 资源不存在 |
| 4002 | 参数错误 |
| 4003 | 重复创建 |
| 5001 | 外部服务连接失败 |
| 5002 | 外部服务超时 |

---

## Agent 接口

### GET /api/v1/agents
列出 Agent 列表（分页）

**Query Params:**
- `page`: int, 默认 1
- `page_size`: int, 默认 20
- `status`: string, 可选 (running/stopped/error)
- `search`: string, 名称模糊搜索

**Response:**
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "name": "客服小助手",
        "description": "微信私域运营助手",
        "status": "stopped",
        "persona_name": "专业客服",
        "created_at": "2026-09-13T10:00:00Z"
      }
    ],
    "total": 10,
    "page": 1,
    "page_size": 20
  }
}
```

### POST /api/v1/agents
创建 Agent

**Request Body:**
```json
{
  "name": "客服小助手",
  "description": "负责微信私域运营"
}
```

### GET /api/v1/agents/{id}
获取 Agent 详情

**Response:**
```json
{
  "code": 0,
  "data": {
    "id": "uuid",
    "name": "客服小助手",
    "description": "负责微信私域运营",
    "status": "stopped",
    "persona": {
      "id": "uuid",
      "name": "专业客服",
      "personality": { "tone": "professional", "length": "concise" }
    },
    "accounts": [],
    "created_at": "...",
    "updated_at": "..."
  }
}
```

### PUT /api/v1/agents/{id}
更新 Agent 基本信息

**Request Body:**
```json
{
  "name": "客服小助手 v2",
  "description": "升级版"
}
```

### DELETE /api/v1/agents/{id}
软删除 Agent

### POST /api/v1/agents/{id}/start
启动 Agent

### POST /api/v1/agents/{id}/stop
停止 Agent

### GET /api/v1/agents/{id}/status
获取 Agent 运行状态

---

## Persona 接口

### GET /api/v1/personas
列出 Persona

**Response:**
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "name": "专业客服",
        "description": "热情专业的客服风格",
        "version": 3,
        "personality": {
          "tone": "professional",
          "reply_length": "concise",
          "proactiveness": "medium",
          "style_boundaries": ["不主动推销", "不承诺优惠"]
        },
        "created_at": "..."
      }
    ],
    "total": 5
  }
}
```

### POST /api/v1/personas
创建 Persona

**Request Body:**
```json
{
  "name": "专业客服",
  "description": "热情专业",
  "personality": {
    "tone": "professional",
    "reply_length": "concise",
    "proactiveness": "medium",
    "style_boundaries": []
  }
}
```

### PUT /api/v1/personas/{id}
更新 Persona

### DELETE /api/v1/personas/{id}
软删除

### GET /api/v1/personas/{id}/versions
获取版本历史

### POST /api/v1/personas/{id}/clone
克隆为新版

---

## Account 接口

### GET /api/v1/accounts
列出账号

**Query Params:**
- `platform`: string, 平台筛选
- `status`: string, 状态筛选

### POST /api/v1/accounts
创建账号

**Request Body:**
```json
{
  "platform_id": "wechat",
  "name": "我的微信号",
  "username": "wechat_user",
  "password": "encrypted_or_plain",
  "profile_id": "uuid"  // 可选，绑定 Browser
}
```

### GET /api/v1/accounts/{id}
获取详情（含绑定信息）

### PUT /api/v1/accounts/{id}
更新账号

### DELETE /api/v1/accounts/{id}
软删除

### POST /api/v1/accounts/{id}/test-conn
测试账号连接状态

---

## 绑定接口

### Agent-Persona 绑定
```
GET    /api/v1/agents/{id}/personas          # 获取绑定列表
POST   /api/v1/agents/{id}/personas          # 绑定（body: { persona_id, is_primary }）
DELETE /api/v1/agents/{id}/personas/{persona_id}  # 解除绑定
```

### Account-Browser 绑定
```
GET    /api/v1/accounts/{id}/browser-bindings
POST   /api/v1/accounts/{id}/browser-bindings
DELETE /api/v1/accounts/{id}/browser-bindings/{profile_id}
```

### Account-Proxy 绑定
```
GET    /api/v1/accounts/{id}/proxy-bindings
POST   /api/v1/accounts/{id}/proxy-bindings
DELETE /api/v1/accounts/{id}/proxy-bindings/{proxy_id}
```

---

## Platform 接口

### GET /api/v1/platforms
列出已注册平台

### POST /api/v1/platforms
注册平台

**Request Body:**
```json
{
  "code": "wechat",
  "name": "微信",
  "capabilities": ["messaging", "friend_management", "moment"],
  "adapter_class": "platforms.wechat.WeChatAdapter"
}
```

### GET /api/v1/platforms/{id}
获取详情

### PUT /api/v1/platforms/{id}
更新

### DELETE /api/v1/platforms/{id}
注销

### POST /api/v1/platforms/{id}/test
测试连接

---

## Browser 接口

### GET /api/v1/browsers/providers
列出可用 Provider（V1 仅 bitbrowser）

### GET /api/v1/browsers/providers/bitbrowser/status
BitBrowser 连接状态

### POST /api/v1/browsers/providers/bitbrowser/test
测试 BitBrowser 连接

**Response:**
```json
{
  "code": 0,
  "data": {
    "connected": true,
    "version": "8.0.0",
    "profiles_count": 3
  }
}
```

### GET /api/v1/browsers/profiles
获取 Profile 列表

### POST /api/v1/browsers/profiles
创建 Profile（调用 BitBrowser API）

**Request Body:**
```json
{
  "name": "我的浏览器配置",
  "provider": "bitbrowser"
}
```

### PUT /api/v1/browsers/profiles/{id}
更新 Profile

### DELETE /api/v1/browsers/profiles/{id}
删除 Profile

---

## Proxy 接口

### GET /api/v1/proxies
列出代理

### POST /api/v1/proxies
创建代理

**Request Body:**
```json
{
  "name": "公司代理",
  "type": "http",
  "host": "proxy.example.com",
  "port": 7890,
  "username": "user",
  "password": "pass"
}
```

### GET /api/v1/proxies/{id}
获取详情

### PUT /api/v1/proxies/{id}
更新

### DELETE /api/v1/proxies/{id}
删除

### POST /api/v1/proxies/{id}/test
测试连通性

---

## 错误响应示例

```json
{
  "code": 4001,
  "message": "Agent not found",
  "detail": {
    "agent_id": "non-existent-uuid"
  }
}
```

```json
{
  "code": 5001,
  "message": "BitBrowser connection failed",
  "detail": {
    "endpoint": "http://127.0.0.1:19000",
    "error": "Connection refused"
  }
}
```
