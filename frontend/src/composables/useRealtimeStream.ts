/**
 * P5MSG-06 — 实时通道订阅 (SSE /api/v1/realtime, P5MSG-04)
 *
 * 职责 (与 UI 组件解耦):
 *  - EventSource 订阅 + ``since`` 游标 (lastSeq, sessionStorage 持久化 → 刷新/离线补发)
 *  - 事件去重: ``seq <= lastSeq`` 的帧直接丢弃 (重连重放窗口)
 *  - 断线指数退避重连 (1s → 2s → … cap 15s); hello.gap → 通知调用方走 REST 全量重取
 *  - 状态机: connecting / connected / reconnecting / closed
 *
 * 用法 (组件 setup 内, 随组件卸载自动 close):
 *   const { status, lastSeq } = useRealtimeStream({
 *     conversationId: route.params.id,            // 省略 = 全局流
 *     onEvent: handleEvent,
 *     onGap: () => refetchEverything(),
 *   })
 */
import { onScopeDispose, ref } from 'vue'
import type { RealtimeEvent, RealtimeHello } from '@/api/channel-message-types'

export type RealtimeStatus = 'connecting' | 'connected' | 'reconnecting' | 'closed'

const SEQ_STORAGE_KEY = 'p5msg-realtime-last-seq'
const MAX_BACKOFF_MS = 15_000

export interface UseRealtimeStreamOptions {
  /** 省略 = 订阅全局流 (所有会话) */
  conversationId?: string
  /** 每收到一个未去重的实时事件回调 (payload 仅 ids/status, 不含正文) */
  onEvent?: (ev: RealtimeEvent) => void
  /** hello.gap = true: since 早于服务端保留窗口 → 调用方应 REST 全量重取 */
  onGap?: () => void
}

function apiBase(): string {
  return import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001/api/v1'
}

function readStoredSeq(): number {
  const raw = sessionStorage.getItem(SEQ_STORAGE_KEY)
  const n = raw ? Number.parseInt(raw, 10) : 0
  return Number.isFinite(n) && n >= 0 ? n : 0
}

export function useRealtimeStream(options: UseRealtimeStreamOptions = {}) {
  const status = ref<RealtimeStatus>('connecting')
  const lastSeq = ref(readStoredSeq())

  let es: EventSource | null = null
  let disposed = false
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let attempts = 0

  function saveSeq(): void {
    sessionStorage.setItem(SEQ_STORAGE_KEY, String(lastSeq.value))
  }

  function handleFrame(raw: string): void {
    let ev: RealtimeEvent
    try {
      ev = JSON.parse(raw) as RealtimeEvent
    } catch {
      return // 非 JSON 帧 (keep-alive 注释行等) — 忽略
    }
    if (typeof ev.seq !== 'number' || ev.seq <= lastSeq.value) return // 去重
    lastSeq.value = ev.seq
    saveSeq()
    options.onEvent?.(ev)
  }

  function connect(): void {
    if (disposed) return
    es?.close()
    es = null
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }

    const since = lastSeq.value
    const scope = options.conversationId ? `&conversation_id=${options.conversationId}` : ''
    const url = `${apiBase()}/realtime?since=${since}${scope}`
    es = new EventSource(url, { withCredentials: false })

    status.value = attempts === 0 ? 'connecting' : 'reconnecting'

    const onHello = (e: MessageEvent) => {
      let hello: RealtimeHello
      try {
        hello = JSON.parse(e.data) as RealtimeHello
      } catch {
        return
      }
      if (hello.gap) options.onGap?.()
    }
    es.addEventListener('hello', onHello as EventListener)
    es.addEventListener('replay', (e: MessageEvent) => handleFrame(e.data))
    es.addEventListener('message', (e: MessageEvent) => handleFrame(e.data))

    es.onopen = () => {
      attempts = 0
      status.value = 'connected'
    }
    es.onerror = () => {
      // EventSource 自身也会尝试自动重连 (URL 不变 → 游标过期),
      // 所以主动 close 并用「新 since + 退避」重建连接。
      es?.close()
      es = null
      if (disposed) return
      status.value = 'reconnecting'
      attempts += 1
      const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** (attempts - 1))
      reconnectTimer = setTimeout(connect, delay)
    }
  }

  function close(): void {
    disposed = true
    status.value = 'closed'
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    es?.close()
    es = null
  }

  onScopeDispose(close)
  connect()

  return { status, lastSeq, reconnect: connect, close }
}
