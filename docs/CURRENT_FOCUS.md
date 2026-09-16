# CURRENT FOCUS

## 当前阶段

Phase 6 — Analytics & Optimization（**已全部收口**）→ 等待 Owner 开启 Phase 7

> 说明：本文件 9/16 刷新：原写"在途 t_dc92c614 / t_645352c1 + 4 张 P2 跟进卡"，实测这些卡已**全部 done**（见下），Phase 6 无遗留。

## 当前状态

- **Phase 6 实现层完成**：9 后端（基础层 + Dashboard + 漏斗 + 对话 + 线索转化 + 私有域 + Agent 绩效 + 实验 + ROI）+ 3 前端。
- **E2E QA（P6AN-15）PASS**：DB→API→UI 全链路绿，无 P0/P1 遗留。
- **架构审查（P6AN-16）CHANGES_REQUIRED → 已闭合**：
  - 唯一 P1（analytics 未认证 + 无租户隔离）：t_3e806a29 修复（ADR-018，顺带修 P2-4 CORS 白名单）✅
  - 4 张 P2 跟进卡（P6AN-17）全部 done：
    - P2-1 成交口径统一（单一 SoT + caliber 回显）→ `t_548dd92e` done ✅
    - P2-2 共享 analytics.py 热点冻结 + 逐波 router 拆分 → `t_ed331329` done ✅
    - P2-3 源表时间列归一 aware-UTC timestamptz → `t_ccd4f521` done ✅
    - P2-5 生产库 alembic 追平 028/029 → `t_474490ff` done ✅
  - 2 张在途缺陷卡已闭环：DEF-3 aware-UTC 边界 500（`t_dc92c614`）、DEF-8 测试器 nit（`t_645352c1`）均 done ✅
- **看板全局**：237 done / 8 archived / 0 blocked / 0 未完成。

阶段总结：`docs/phases/PHASE-6-SUMMARY.md`。

## 当前只允许处理

1. **等待开启的 Phase 7**（见 `docs/ROADMAP.md`「Phase 7 — Future」，Owner 明确开启后才进看板）：
   - AdsPower Provider / LocalChromium Provider
   - 更多平台
   - 插件市场
   - 云端服务 / 团队协作 / 多租户 SaaS / 移动端

## 暂时禁止

在未获 Owner 明确开启对应 Epic 前，不主动实现 Phase 7 新功能。

## 当前成功标准

1. ✅ Phase 6 P2 跟进卡 + 在途缺陷卡全部闭环（已完成）
2. ✅ 生产库 alembic 028/029，analytics 端点 200（已完成）
3. Phase 7 由 Owner 明确开启后再进入看板

---

## 当前唯一目标

> Phase 6 技术债全部收口；待 Owner 开启 Phase 7 后扩展 Provider / 平台 / 插件市场。
