/**
 * 全局 v-loading 指令
 * 用法: v-loading="isLoading" / v-loading="{ loading: true, text: '加载中…' }"
 * 在目标元素内部叠加一个半透明遮罩 + 加载文本。
 */
import type { Directive, DirectiveBinding } from 'vue'

interface LoadingBinding {
  loading: boolean
  text?: string
}

function normalize(value: unknown): LoadingBinding {
  if (typeof value === 'object' && value !== null) {
    const v = value as Partial<LoadingBinding>
    return { loading: !!v.loading, text: v.text }
  }
  return { loading: !!value, text: undefined }
}

function addOverlay(el: HTMLElement, text?: string): void {
  if (el.querySelector<HTMLElement>(':scope > .v-loading-overlay')) return
  const overlay = document.createElement('div')
  overlay.className = 'v-loading-overlay'
  overlay.style.cssText =
    'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;' +
    'background:rgba(255,255,255,0.6);z-index:2000;border-radius:inherit;'
  const spinner = document.createElement('div')
  spinner.className = 'v-loading-spinner'
  spinner.style.cssText =
    'width:28px;height:28px;border:3px solid #d0d0d0;border-top-color:#B8935A;' +
    'border-radius:50%;animation:v-loading-spin .8s linear infinite'
  if (!document.getElementById('v-loading-keyframes')) {
    const style = document.createElement('style')
    style.id = 'v-loading-keyframes'
    style.textContent =
      '@keyframes v-loading-spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}'
    document.head.appendChild(style)
  }
  overlay.appendChild(spinner)
  if (text) {
    const label = document.createElement('div')
    label.className = 'v-loading-text'
    label.style.cssText =
      'margin-left:8px;font-size:13px;color:#888;background:rgba(255,255,255,0.8);padding:2px 8px;border-radius:4px'
    label.textContent = text
    overlay.appendChild(label)
  }
  if (getComputedStyle(el).position === 'static') {
    el.style.position = 'relative'
  }
  el.appendChild(overlay)
}

function removeOverlay(el: HTMLElement): void {
  const overlay = el.querySelector<HTMLElement>(':scope > .v-loading-overlay')
  if (overlay) overlay.remove()
}

const loadingDirective: Directive = {
  mounted(el: HTMLElement, binding: DirectiveBinding) {
    const v = normalize(binding.value)
    if (v.loading) addOverlay(el, v.text)
  },
  updated(el: HTMLElement, binding: DirectiveBinding) {
    const v = normalize(binding.value)
    if (v.loading) addOverlay(el, v.text)
    else removeOverlay(el)
  },
  unmounted(el: HTMLElement) {
    removeOverlay(el)
  },
}

export default loadingDirective
