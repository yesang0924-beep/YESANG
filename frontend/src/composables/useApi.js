/**
 * pywebview 桥接层。
 *
 * pywebview 在页面加载后才注入 window.pywebview.api，所以必须等
 * 'pywebviewready' 事件；在此之前调用一律排队等待。
 */
import { ref } from 'vue'

const ready = ref(!!window.pywebview?.api)
let waiters = []

window.addEventListener('pywebviewready', () => {
  ready.value = true
  waiters.forEach((fn) => fn())
  waiters = []
})

function whenReady() {
  if (ready.value) return Promise.resolve()
  return new Promise((resolve) => waiters.push(resolve))
}

export async function call(fn, ...args) {
  await whenReady()
  const api = window.pywebview?.api
  if (!api || typeof api[fn] !== 'function') {
    throw new Error(`后端接口 ${fn} 不可用`)
  }
  return api[fn](...args)
}

export function useReady() {
  return ready
}

/** 简易 toast：全局单例，供各组件共享 */
const toastMsg = ref('')
let toastTimer = null

export function toast(message) {
  toastMsg.value = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastMsg.value = ''), 3200)
}

export function useToast() {
  return toastMsg
}
