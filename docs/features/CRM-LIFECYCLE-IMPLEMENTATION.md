# CRM Lifecycle + Funnel Pipeline - Implementation Summary

## 已完成的工作 (t_crm_005 最终状态)

### 1. 数据库模型 (Database Models)
- `LifecycleStage` - 生命周期阶段表
  - code: 阶段编码 (陌生/潜客/有效线索/高意向/商机/成交)
  - name: 阶段名称
  - sort_order: 排序顺序
  - config: 配置JSON（**`rules` 数组存放可配置的自动流转规则**）
  
- `LifecycleStageLog` - 阶段变更日志表
  - lead_id: 关联Lead
  - old_stage_code: 原阶段
  - new_stage_code: 新阶段
  - transition_reason: 流转原因 (`manual` / `auto_rule`)
  - operator: 操作者 (auto 时固定为 `system`)
  - extra_data / metadata: 扩展元数据（auto 时记录触发信号快照）

### 2. API 接口 (API Endpoints)

#### 阶段管理 (阶段配置 API，Pydantic 校验规则)
- `GET /api/v1/crm/lifecycle/stages` - 获取所有阶段
- `POST /api/v1/crm/lifecycle/stages` - 创建阶段（`LifecycleStageCreate`，`auto_transition_rules` 经校验，脏规则 400/422 拒绝入库）
- `GET /api/v1/crm/lifecycle/stages/{stage_code}` - 获取单阶段
- `PUT /api/v1/crm/lifecycle/stages/{stage_code}` - 更新阶段/规则（`auto_transition_rules` 优先于 `config`）
- `DELETE /api/v1/crm/lifecycle/stages/{stage_code}` - 删除阶段（软删除）

#### 阶段日志
- `GET /api/v1/crm/lifecycle/stages/{stage_code}/logs` - 获取阶段变更日志（支持按 lead_id 筛选）

#### 阶段流转
- `POST /api/v1/crm/lifecycle/stages/transition` - 手动执行阶段流转
- `POST /api/v1/crm/lifecycle/stages/auto-transition?lead_id=` - **按已配置规则自动评估并流转单个 Lead**

#### 漏斗统计
- `GET /api/v1/crm/lifecycle/funnel` - 各阶段客户数量 + 相对顶部的累计转化率

### 3. 自动流转规则引擎 (Auto-Transition Engine)
- `app/crm/services/auto.py` - 规则存于各阶段 `config.rules`，三种触发器：
  - `intent_score`：当 `Lead.intent_score >= min_intent_score` 命中
  - `status_change`：当 `Lead.status == when_status` 命中（缺省匹配 contacted/qualified/converted）
  - `conversation_activity`：近 7 天对话消息数 `>= min_messages` 命中
  - 命中后经 `transition_lifecycle_stage` 写日志 + 发 `lead.stage_changed` 领域事件；目标阶段必须是当前活跃阶段。
- `update_lead`（status / intent_score 变化时）自动触发规则评估；可被 `skip_stages` 排除刚手动设置的阶段，防止规则立刻反弹。
- 对话行为信号通过可插拔的 `ConversationActivityProvider` 适配器读取（业务不直接依赖 Conversation ORM）。

### 4. 默认生命周期阶段
```
陌生 → 潜客 → 有效线索 → 高意向 → 商机 → 成交
```

### 5. 测试 (tests/test_lifecycle_auto.py，23 项全绿)
- 纯规则引擎：build_signals / match_stage_for_signals / 规则容错 / 未知触发器跳过
- 降级保护：无规则 / 异常结果形状时安全返回 `[]`
- 真库集成 (ai_agent_platform_test)：三种触发器自动流转、日志落库、漏斗单次 GROUP BY + 转化率、阶段配置 API 校验脏规则、软删除

### 6. 验收标准
- [x] Lifecycle Stage 枚举符合产品定义（陌生→潜客→有效线索→高意向→商机→成交）
- [x] 阶段流转规则可配置（`config.rules` JSON + Pydantic 校验，经 PUT/POST 配置）
- [x] Funnel 统计接口返回正确数据（各阶段客户数量 + 转化率，单次 GROUP BY）
- [x] 阶段变更有日志记录（manual + auto_rule，含信号快照）
- [x] 阶段配置 API 可用（创建/读取/更新/删除/自动流转/漏斗）

## 已知跨模块发现（非本卡范围，已记录待架构处理）
- **ORM 类名冲突**：`app/db/models/conversation.py` 的 `Message`(表 `message`) 与 `app/db/models/messages.py` 的平台 `Message`(表 `messages`) 同名。测试库无 `messages` 表，`Conversation.messages` 字符串关系在整包导入时被解析到平台侧，`refresh(conv)` 触发 `SELECT ... FROM messages` 报 UndefinedTableError。本卡测试通过显式主键 + 避免关系加载规避；根因需架构/平台侧收口。
- **生产库缺 CRM 表**：`ai_agent_platform`(prod) 无 lead/customer/tag/lifecycle 等表，`alembic upgrade` 未在该库跑通（`001_crm_lifecycle` 与 ORM 列名/外键定义不一致：迁移用 `order`/`customer_id`/`from_stage_code`，ORM 用 `sort_order`/`lead_id`/`old_stage_code`）。本卡以 `ai_agent_platform_test`(create_all 建表、与 ORM 一致) 为可跑 schema 验证。

## 下一步
1. 收口 ORM 同名 `Message` 冲突（架构）
2. 迁移 `001_crm_lifecycle` 与 ORM 对齐后在 prod 跑通 `alembic upgrade`
3. 前端集成（阶段可视化图表）
