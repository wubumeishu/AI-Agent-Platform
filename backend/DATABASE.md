# DATABASE.md — Phase 1 数据库 Schema 与迁移说明

项目: AI Agent Platform
后端: `H:/AI-Agent-Platform/backend`
目标库: `postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform`
权威 Schema: [`docs/PHASE1-DB-SCHEMA.sql`](../../docs/PHASE1-DB-SCHEMA.sql)

本文档描述 Phase 1 资源层的数据库结构、迁移链路、初始化数据、索引与触发器契约，
以及如何在本地复现 / 验证。任务: t_9c06e99a。

---

## 1. 概览

Phase 1 资源层共 **9 张主表 + 3 张绑定表 + 7 个索引 + 5 个触发器 + 1 个共享函数 + 3 条内置平台种子数据**。

### 主表（6 张业务主表）

| 表 | 说明 | 关键字段 |
|----|------|----------|
| `agent` | AI Agent 主表 | id, name, description, status(running/stopped/error), created_at, updated_at, is_deleted |
| `persona` | Persona 风格定义表 | id, name, personality(JSONB), version, parent_id(自引用), created_at, updated_at, is_deleted |
| `account` | 平台账号表 | id, platform_id, name, username, password_encrypted, status(connected/disconnected/failed), last_login, created_at, updated_at, is_deleted |
| `platform` | 平台注册表 | id, code(唯一), name, capabilities(JSONB), adapter_class, config(JSONB), status, created_at, is_deleted |
| `browser_profile` | 浏览器 Profile 表 | id, provider, profile_id, name, connection_status, created_at, updated_at, is_deleted |
| `proxy` | 代理服务器表 | id, name, type(http/https/socks5), host, port, username, password_encrypted, status, last_tested, created_at, updated_at, is_deleted |

### 绑定表（3 张）

| 表 | 主键 | 说明 |
|----|------|------|
| `agent_persona_binding` | (agent_id, persona_id) | Agent ↔ Persona 多对多绑定（含 is_primary / bound_at） |
| `account_browser_binding` | (account_id, profile_id) | 账号 ↔ 浏览器 Profile 绑定 |
| `account_proxy_binding` | (account_id, proxy_id) | 账号 ↔ 代理绑定 |

> 任务卡所称 “9 张主表” = 上述 6 张主表 + 3 张绑定表（绑定表在卡片统计口径里并入主表计数）。
> 三张绑定表均带 `ON DELETE CASCADE` 外键。

---

## 2. 迁移链路（Alembic）

当前 head: **`021_phase1_persona_trigger`**。

Phase 1 资源层由下列迁移承载（`002_add_platform` 为旧 stub 链，实际建表逻辑在 `002_account_resource_layer`）：

| 迁移 | 说明 |
|------|------|
| `002_account_resource_layer` | 创建 platform / agent / persona / account / browser_profile / proxy + 3 张绑定表 + 7 个索引 + 内置平台种子 + 共享 `update_updated_at_column()` 函数 + **4 个触发器**（agent/account/browser_profile/proxy，经 f-string 循环；循环**漏掉 persona**） |
| `021_phase1_persona_trigger` | **幂等补齐 persona 触发器**：若 `update_persona_updated_at` 不存在则创建，确保“仅通过 Alembic 从零建库”的路径也能得到完整 Phase 1 触发器集 |

> 关键缺口与修复：`002` 的触发器循环 `for table in ['agent','account','browser_profile','proxy']`
> 漏了 `persona`，因此 **fresh（纯 Alembic）库里原本不会有 `update_persona_updated_at`**。
> 本次新增的 `021` 用 `DO $$ ... IF NOT EXISTS ... $$` 守卫补齐该缺口：
> 对 legacy（`create_all` 旁路建库、已手工装好 persona 触发器）是安全 no-op；对 fresh 库则补上。

### 复现 / 验证命令

```bash
cd H:/AI-Agent-Platform/backend
python -m alembic current          # 应显示 021_phase1_persona_trigger (head)
python -m alembic upgrade head     # 幂等；已在 head 时为空操作
python -m alembic heads           # 应只有一个 head
```

---

## 3. 初始化数据（内置平台）

| code | name | capabilities | adapter_class |
|------|------|--------------|---------------|
| `wechat` | 微信 | messaging, friend_management, moment, group | `platforms.wechat.WeChatAdapter` |
| `douyin` | 抖音 | messaging, comment_reply | `platforms.douyin.DouyinAdapter` |
| `xiaohongshu` | 小红书 | messaging, comment_reply | `platforms.xiaohongshu.XiaoHongShuAdapter` |

三条均由 `002_account_resource_layer` 通过 `INSERT` 写入（fresh 库），legacy 库已存在。

---

## 4. 索引（7 个）

均为部分索引（`WHERE is_deleted = FALSE`）：

| 索引 | 表 | 列 |
|------|----|----|
| `idx_agent_status` | agent | status |
| `idx_agent_name` | agent | name |
| `idx_persona_version` | persona | (parent_id, version) |
| `idx_account_platform` | account | platform_id |
| `idx_account_status` | account | status |
| `idx_browser_profile_provider` | browser_profile | provider |
| `idx_proxy_status` | proxy | status |

---

## 5. 触发器（5 个）+ 共享函数

共享函数 `update_updated_at_column()`：`BEFORE UPDATE` 时将 `NEW.updated_at = NOW()`。

| 触发器 | 表 | 创建来源 |
|--------|----|----------|
| `update_agent_updated_at` | agent | 002（触发器循环） |
| `update_account_updated_at` | account | 002（触发器循环） |
| `update_browser_profile_updated_at` | browser_profile | 002（触发器循环） |
| `update_proxy_updated_at` | proxy | 002（触发器循环） |
| `update_persona_updated_at` | persona | 021（幂等补齐；002 循环漏掉 persona） |

> 验证方式见 §6。注意：Postgres 的 `NOW()` 是**事务常量**——同一事务内多次 `NOW()` 返回相同值。
> 因此“updated_at 是否前进”必须放在**不同事务**（autocommit 或分别 commit）中测量，
> 否则 before/after 会看似相等（这是本次排查中踩到的坑，验收测试已用 `autocommit=True` 处理）。

---

## 6. 验收与测试

专属验收测试: [`tests/test_phase1_db.py`](tests/test_phase1_db.py)

```bash
cd H:/AI-Agent-Platform/backend
python -m pytest tests/test_phase1_db.py -q
```

测试分两层：

1. **结构层（离线、恒跑）**：静态扫描整条迁移链，断言 9 张表、7 个索引、5 个触发器、
   共享函数、uuid-ossp 扩展、3 条平台种子全部有 DDL 覆盖。无需连库。
2. **集成层（Postgres 可达才跑，否则自动 skip）**：连真实库确认表 / 索引 / 触发器 / 种子存在，
   并用 `autocommit` 实测 `update_agent_updated_at` 触发器在 UPDATE 时推进 `updated_at`。

**2026-09-14 实机结果：10 passed**（结构层 5 项 + 集成层 5 项，库为 head 021）。

---

## 7. 变更记录

| 日期 | 变更 | 任务 |
|------|------|------|
| 2026-09-14 | Phase 1 迁移验收 + 新增 `021_phase1_persona_trigger`（幂等补齐 persona 触发器缺口）+ 新增 `tests/test_phase1_db.py` 验收测试 + 本 DATABASE.md | t_9c06e99a |
