/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 API 基址 (默认 http://localhost:8001/api/v1 — canonical AI Agent Platform 服务) */
  readonly VITE_API_BASE_URL?: string
  /**
   * P5MSG-06: 实时写端点 (POST /realtime/read | /publish) 受信任生产者鉴权
   * (P5MSG-FIX P0-2, 后端 REALTIME_PUBLISH_TOKENS)。
   * 前后端共用同一 token 时, 在此配置同值 (本地开发; 生产由部署注入)。
   * 未配置 → 标已读/发布端点返回 401/403, UI 显示错误横幅。
   */
  readonly VITE_REALTIME_PUBLISH_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
