# Workflow 子系统数据库 Schema 设计（Phase 4 / t_wf_001）

> 卡片：Workflow 后端框架 + 数据库 Schema（`t_wf_001`）
> 目标：定义 Workflow / Trigger / Condition / Action 等核心实体及运行时
> 执行实体的数据库表结构，并提供 Alembic 迁移 + FastAPI CRUD 骨架。

## 1. 范围与非范围

**范围（本卡片交付）**
- 9 个 Workflow 配置 + 运行时 ORM 模型
- 1 个 Alembic 迁移（`015_workflow_framework`）创建全部 9 张表
- FastAPI CRUD 骨架：`/api/v1/workflow-*` + `/api/v1/workflows`
- 分页、筛选（等值）、排序、软删除
- 单元测试（mock 层，无 live DB）+ 迁移可执行性验证（scratch DB）

**非范围（后续 wave）**
- 工作流执行引擎 / cron 解析 / 任务分发（`t_wf_003`、`t_wf_004`）
- 复杂条件表达式解析（本卡片只存储 `expression` JSONB，不解析）
- 与 CRM / Conversation 的集成（`t_wf_006`、`t_wf_007`）
- 前端页面

## 2. 实体与关系

```
Workflow (1) ──< (N) WorkflowTrigger (1) ──< (N) WorkflowCondition (1) ──< (N) WorkflowAction
   │
   ├─< WorkflowDelay        (workflow_id, action_id?)
   ├─< WorkflowBranch       (workflow_id)
   ├─< WorkflowScheduler    (workflow_id?, trigger_id?)
   └─< WorkflowQueue        (workflow_id?)
            └─< WorkflowWorker (queue_id?)

ExecutionLog（t_wf_005，已落地于 014）── 逻辑引用 workflow_id/queue_id/worker_id/task_id
```

- **配置层（t_wf_002 拥有，本卡片迁移建表）**：`workflow` /
  `workflow_trigger` / `workflow_condition` / `workflow_action`。
  层级关系 Workflow → Trigger → Condition → Action，父级删除时级联删除
  子级（`ondelete=CASCADE` + ORM `cascade="all, delete-orphan"`）。
- **运行时层（本卡片 t_wf_001 拥有）**：`workflow_delay` /
  `workflow_branch` / `workflow_scheduler` / `workflow_queue` /
  `workflow_worker`。这些是执行、调度、队列管理所需，尚未被任何卡片实现。

> 说明：核心配置模型（Workflow/Trigger/Condition/Action）的 ORM 类由
> 兄弟卡片 `t_wf_002` 在 `app.db.models.workflow` 中落地；本卡片以「schema
> + 迁移」职责把这 4 张表连同 5 张运行时表**一次性建表**，让整个子系统的
> ORM 模型都可经由 Alembic 创建（满足验收标准 2），避免半套表可迁移、
> 半套不可迁移。

## 3. 表结构

| 表 | 关键字段 | 约束 / 索引 |
|----|----------|-------------|
| workflow | id, name, description, workflow_type(auto/manual), status(draft/active/paused/archived), config JSONB, execution_policy JSONB, version int | idx_workflow_status_name, idx_workflow_type |
| workflow_trigger | id, workflow_id(FK), name, trigger_type(manual/scheduled/cron/event), spec JSONB, enabled bool | idx_trigger_workflow; FK→workflow CASCADE |
| workflow_condition | id, trigger_id(FK), name, expression JSONB, logic(and/or), priority int | idx_condition_trigger; FK→trigger CASCADE |
| workflow_action | id, condition_id(FK), name, action_type(conversation/message/tag/status_change/notification/custom), params JSONB, priority int | idx_action_condition, idx_action_type; FK→condition CASCADE |
| workflow_delay | id, workflow_id(FK), action_id(FK,可空), delay_amount int, unit(seconds/minutes/hours/days), config JSONB | idx_delay_workflow; FK→workflow CASCADE, FK→action SET NULL |
| workflow_branch | id, workflow_id(FK), name, rule JSONB, config JSONB | idx_branch_workflow; FK→workflow CASCADE |
| workflow_scheduler | id, workflow_id(FK,可空), trigger_id(FK,可空), name, schedule_type(cron/interval), cron_expression, interval_seconds, timezone, enabled, last_run_at, next_run_at | idx_scheduler_workflow, idx_scheduler_enabled(部分); FK→workflow CASCADE, FK→trigger SET NULL |
| workflow_queue | id, workflow_id(FK,可空), name(unique), type(fifo/priority), max_concurrency, retry_limit, timeout_seconds, status(idle/running/paused) | idx_queue_name(unique), idx_queue_workflow, idx_queue_status(部分) |
| workflow_worker | id, queue_id(FK,可空), name, status(idle/busy/stopped), config JSONB, last_heartbeat_at | idx_worker_queue, idx_worker_status(部分) |

所有表：
- `id` UUID 主键（应用侧 `uuid4` 生成）
- `created_at` / `updated_at` timestamptz
- `is_deleted` bool，软删除默认值 `false`
- 部分索引 `postgresql_where is_deleted = false` 用于高频状态过滤

## 4. 迁移

`alembic/versions/015_workflow_framework.py`
- `revision = 015_workflow_framework`
- `down_revision = 014_execution_log`
- `upgrade()`：按依赖顺序创建 9 张表 + 索引 + 唯一约束
- `downgrade()`：逆序删除

已在 scratch Postgres 数据库实测通过：9 张表、9 个唯一索引、10 个外键约束
全部建出（`_run_migration_check.py`，验证后已删除脚本，DB 已清理）。

> 共享 dev 库（`ai_agent_platform`）当前未应用任何 alembic 迁移
> （无 `alembic_version`），且各兄弟卡片迁移图存在分叉，故本卡片**不**向
> dev 库应用迁移；可执行性以 scratch DB 验证为准。真正 `alembic upgrade`
> 的编排属于后续集成/发布环节。

## 5. CRUD API 骨架（P1-1 收敛后 / t_c94bba06）

收敛前的 `workflow_framework` 扁平路由同时声明了配置实体与运行时实体，与
嵌套的 `workflow_config` 路由在 `/api/v1/workflows` 上重叠（后者先注册而遮蔽
前者，OpenAPI 出现重复 operation id）。按架构审查 t_c81d72fe P1-1 已收敛为
**单一规范 `/workflows` API 面**：

- **配置实体**（Workflow / Trigger / Condition / Action）→ 嵌套
  `workflow_config` 路由（`/api/v1/workflows` + `/detail` + `/triggers/fire`）。
- **运行时实体** → `workflow_framework.py`，经 `main.py` 挂载在 `/api/v1`，
  仅保留以下 5 类实体的 CRUD：

| 资源 | 集合端点 | 单项端点 |
|------|----------|----------|
| /workflow-delays | GET, POST | GET/PUT/DELETE /{id} |
| /workflow-branches | GET, POST | GET/PUT/DELETE /{id} |
| /workflow-schedulers | GET, POST | GET/PUT/DELETE /{id} |
| /workflow-queues | GET, POST | GET/PUT/DELETE /{id} |
| /workflow-workers | GET, POST | GET/PUT/DELETE /{id} |

（`/workflow-triggers`、`/workflow-conditions`、`/workflow-actions` 已不再由
`workflow_framework` 声明，统一走 `workflow_config` 嵌套面。）

- 服务层：`app/services/workflow_framework.py`（通用 `_GenericCRUD` 引擎 +
  每实体薄封装；P2-3 已加 `_SYSTEM_UPDATE_DENYLIST` 防 update 越权写系统列），
  `app/schemas/workflow_framework.py`（Pydantic 校验 + 值域约束）。
- 分页：`page` / `page_size`（1..100）
- 筛选：对声明为 filter 的标量列做等值过滤
- 排序：默认 `created_at desc`，支持 `order_by` + `ascending`
- 软删除：DELETE 置 `is_deleted=true`，列表/单项自动排除已删除
- OpenAPI 可构建，**无重复 operation id**（326/326 唯一）

## 6. 验证状态

- [x] 全部 9 个 ORM 模型注册无冲突（`Base.metadata` 唯一）
- [x] 015 迁移在 scratch Postgres 可执行
- [x] `tests/test_workflow_framework.py` 29 用例全绿
- [x] `app.main` 可 import，OpenAPI 可生成
- [ ] 共享 dev 库应用迁移（属后续集成/发布环节）
