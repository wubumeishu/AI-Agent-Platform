# Phase 1 数据库迁移与初始化 — 交付说明

任务: t_9c06e99a
完成时间: 2026-09-14
后端: H:/AI-Agent-Platform/backend
验收测试: `pytest tests/test_phase1_db.py -q` → **10 passed**

---

## 结论（TL;DR）

Phase 1 资源层的表 / 索引 / 触发器 / 种子数据**早已由前序迁移 `002_account_resource_layer` 建立**，
实机库当前已处于 head。本次验收**未发现结构缺口**（9 表 + 3 绑定 + 7 索引 + 3 种子全部就位），
但发现一个**真实触发器缺口**并幂等修复：

> `002` 的触发器循环 `for table in ['agent','account','browser_profile','proxy']` **漏掉了 persona**，
> 因此纯 Alembic 从零建库的路径不会创建 `update_persona_updated_at`。
> 新增迁移 `021_phase1_persona_trigger` 以 `IF NOT EXISTS` 守卫补齐该缺口
> （legacy 库是安全 no-op，fresh 库则补上）。

---

## 改动文件清单

### 新增
| 文件 | 说明 |
|------|------|
| `alembic/versions/021_phase1_persona_trigger.py` | 幂等补齐 `update_persona_updated_at`（`DO $$ IF NOT EXISTS $$` 守卫） |
| `tests/test_phase1_db.py` | Phase 1 专属验收测试：结构层（离线扫迁移链，恒跑）+ 集成层（连真实库，不可达自动 skip） |
| `DATABASE.md` | Phase 1 数据库 Schema / 迁移链路 / 初始化数据 / 索引 / 触发器契约文档 |

### 已有（非本次创建，复用为基线）
- `alembic/versions/002_account_resource_layer.py` — Phase 1 资源层主迁移（建表/索引/种子/函数/4 触发器）
- `docs/PHASE1-DB-SCHEMA.sql` — 权威 Schema 定义
- 实机库 `ai_agent_platform`（localhost:5432）已含全部 Phase 1 对象

---

## 7 条验收标准核对

| # | 验收项 | 状态 |
|---|--------|------|
| 1 | 9 张主表创建成功（6 主表 + 3 绑定表） | ✅ `002` 建表，实机 `pg_tables` 9 表齐全，集成测试 `test_tables_exist` 通过 |
| 2 | 3 张绑定表创建成功 | ✅ 同上（`agent_persona_binding` / `account_browser_binding` / `account_proxy_binding`） |
| 3 | 7 个索引创建成功 | ✅ 实机 `pg_indexes` 7 项全部存在，集成测试 `test_indexes_exist` 通过 |
| 4 | 5 个触发器创建成功 | ✅ 实机 `pg_trigger` 5 项齐全；`021` 补齐 persona 缺口；集成测试 `test_triggers_exist` 通过 |
| 5 | 3 个内置平台数据插入成功 | ✅ 实机 `platform` 表 wechat/douyin/xiaohongshu 三条 `status=active`，集成测试 `test_platform_seeds_present` 通过 |
| 6 | SELECT 查询验证数据正确性 | ✅ 集成测试逐条 SELECT 验证 |
| 7 | updated_at 触发器正常工作 | ✅ 集成测试 `test_updated_at_trigger_fires`：`autocommit` 下 INSERT→UPDATE，`updated_at` 严格前进 |

---

## 实机验证记录

```
alembic current  → 021_phase1_persona_trigger (head)
alembic heads    → 单 head（021），无多头冲突
alembic upgrade head → 幂等（020→021 已应用；再跑为空操作）
pytest tests/test_phase1_db.py -q → 10 passed
python -c "import app.main"      → OK（未破坏可导入性）
```

排查要点：Postgres `NOW()` 是**事务常量**——同一事务内多次 `NOW()` 返回相同值。
初版触发器测试在单事务里比较 before/after，误判为“未前进”；改为 `autocommit=True`
（每个语句独立事务）后 5 个触发器全部验证为正常推进。

---

## 范围外 / 未改动

- 未重建 `002` 已建的表/索引/种子（避免 fresh 库 `relation already exists`）。
- 未改前端、未改其它迁移、未引入新依赖。
- 备份策略 / 集群配置 / 历史数据迁移不在本卡范围。

---

## 关于 “PR 已提交” (DoD #5)

本任务 `completion_contract = local-only`。`backend/` 目录**未被 git 跟踪**
（仓库仅跟踪 docs/frontend/src-tauri，`git check-ignore backend` 返回 1、`git ls-files backend/` 为 0）。
因此无法就 backend 文件提真实 GitHub PR；持久化交付物为磁盘上的
迁移脚本 + 验收测试 + DATABASE.md。如后续需要将 backend 纳入版本控制并走 PR，
建议单独立一张卡（涉及 `.gitignore` / 仓库布局决策，超出本卡范围）。

---

## Follow-up（非阻塞）

- 若要消除对 021 幂等守卫的依赖，可回补 `002_account_resource_layer` 的触发器循环
  加入 `persona`（属历史迁移修订，需单独评审，故本次仅以 021 增量补齐）。
