/**
 * 轻量级全局 Toast 通知（无第三方依赖）。
 * 用法: showToast('创建失败', 'error')
 */
export type ToastType = 'success' | 'error' | 'info'

const ICONS: Record<ToastType, string> = {
  success: '✅',
  error: '⚠️',
  info: 'ℹ️',
}

const CLASSES: Record<ToastType, string> = {
  success: 'toast--success',
  error: 'toast--error',
  info: 'toast--info',
}

export function showToast(message: string, type: ToastType = 'info', duration = 3200): void {
  let container = document.querySelector<HTMLElement>('#app-toast-container')
  if (!container) {
    container = document.createElement('div')
    container.id = 'app-toast-container'
    container.style.cssText =
      'position:fixed;top:16px;right:16px;z-index:10000;display:flex;flex-direction:column;gap:8px;pointer-events:none'
    document.body.appendChild(container)
  }

  const el = document.createElement('div')
  el.className = `toast ${CLASSES[type]}`
  el.style.cssText = [
    'max-width:360px',
    'padding:10px 14px',
    'border-radius:8px',
    'font-size:14px',
    'line-height:1.4',
    'box-shadow:0 4px 16px rgba(0,0,0,0.15)',
    'background:#fff',
    'color:#333',
    'border:1px solid #eee',
    'pointer-events:auto',
    'opacity:0',
    'transform:translateY(-8px)',
    'transition:opacity .2s ease, transform .2s ease',
  ].join(';')
  if (type === 'error') {
    el.style.background = '#fff5f5'
    el.style.borderColor = '#f5c2c7'
    el.style.color = '#c0392b'
  } else if (type === 'success') {
    el.style.background = '#f0faf2'
    el.style.borderColor = '#b7e4c7'
    el.style.color = '#1e7e45'
  }
  el.textContent = `${ICONS[type]} ${message}`
  container.appendChild(el)
  requestAnimationFrame(() => {
    el.style.opacity = '1'
    el.style.transform = 'translateY(0)'
  })
  setTimeout(() => {
    el.style.opacity = '0'
    el.style.transform = 'translateY(-8px)'
    setTimeout(() => el.remove(), 250)
  }, duration)
}
