# CURRENT FOCUS

## 当前阶段

Phase 6 — Analytics & Optimization（已收口）→ 待 Phase 7 开启

> 说明：本文件原停留在 "Phase 2 / 暂时禁止 Analytics"，与看板 Phase 3-6 并行推进的实际状态不符（属文档过期，见 PHASE-3-SUMMARY §8 / PHASE-6-SUMMARY §8）。本卡（t_adcbbb97）已更新。

## 当前状态

- **Phase 6 Analytics & Optimization 实现层完成**：9 后端（基础层 + Dashboard + 漏斗 + 对话 + 线索转化 + 私有域 + Agent 绩效 + 实验 + ROI）+ 3 前端。
- **E2E QA（P6AN-15）判定 PASS**：DB→API→UI 全链路绿，无 P0/P1 遗留。
- **架构审查（P6AN-16）判定 CHANGES_REQUIRED**：无 P0；唯一 P1（analytics 表面未认证 + 无租户隔离）已在 t_3e806a29 修复（ADR-018，同卡顺手修 P2-4 CORS 白名单）；P2-1/2/3/5 已建 4 张 P2 跟进卡（P6AN-17）。
- **在途**：t_dc92c614（DEF-3 P2 aware-UTC 边界 500）、t_645352c1（DEF-8 P3 测试器 nit）。

阶段总结：`docs/PHASE-6-SUMMARY.md`。

## 当前只允许处理

1. **Phase 6 收口遗留**：4 张 P2 跟进卡（P2-1 成交口径 / P2-2 挂载热点 / P2-3 时间列归一 / P2-5 生产库 alembic 028-029）+ 2 张在途缺陷卡（DEF-3 / DEF-8）。
2. **等待开启的 Phase 7**（见 ROADMAP「Phase 7 — Future」，Owner 明确开启后才进看板）：
   - AdsPower Provider / LocalChromium Provider
   - 更多平台
   - 插件市场
   - 云端服务 / 团队协作 / 多租户 SaaS / 移动端

## 暂时禁止

在未获 Owner 明确开启对应 Epic 前，不主动实现 Phase 7 新功能；不把在途 P2/P3 技术债扩散到无关模块。

## 当前成功标准

1. Phase 6 P2 跟进卡 + 在途缺陷卡闭环
2. 生产库 alembic 至 028/029 后 analytics 端点 200（非 500）
3. Phase 7 由 Owner 明确开启后再进入看板

---

## 当前唯一目标

> 收口 Phase 6 Analytics 技术债，待 Owner 开启 Phase 7 后扩展 Provider / 平台 / 插件市场。
