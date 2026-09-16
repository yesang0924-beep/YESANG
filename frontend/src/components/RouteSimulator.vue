<script setup>
import { ref } from 'vue'
import { call } from '../composables/useApi.js'
import Icon from './Icon.vue'

const model = ref('go/deepseek-v4.1-flash')
const result = ref(null)
const loading = ref(false)

async function run() {
  const value = model.value.trim()
  if (!value) return
  loading.value = true
  try {
    result.value = await call('simulate_route', value)
  } catch (e) {
    result.value = { ok: false, message: String(e) }
  }
  loading.value = false
}
</script>

<template>
  <div class="sim">
    <div class="hline">
      <input v-model="model" type="text" placeholder="例如 go/deepseek-v4.1-flash" @keyup.enter="run">
      <button class="btn accent sm" :disabled="loading" @click="run">
        <span v-if="loading" class="spin"></span>
        <Icon v-else name="route" :size="12" />
        {{ loading ? '分析中' : '模拟路由' }}
      </button>
    </div>
    <div v-if="result" class="result" :class="result.ok ? 'good' : 'bad'">
      <div class="main">{{ result.message }}</div>
      <div v-if="result.ok" class="meta">
        实际模型：{{ result.real_model }} · 出口：{{ result.base }} · 密钥：{{ result.has_key ? '已配置' : '缺失' }} ·
        协议：{{ result.chat_only ? '需翻译' : '原生 Responses' }} · 线路：{{ result.use_proxy ? '经出口' : '直连' }}
      </div>
    </div>
    <div v-else class="empty">输入模型名，查看它会命中哪条上游、是否需要协议翻译。</div>
  </div>
</template>

<style scoped>
.sim .hline { display: flex; gap: 8px; }
.sim input { flex: 1; min-width: 0; }
.result { margin-top: 10px; padding: 10px 12px; border-radius: 9px; font-size: 12px; }
.result.good { background: var(--ok-soft); color: var(--ok); }
.result.bad { background: var(--fail-soft); color: var(--fail); }
.result .main { font-weight: 600; }
.result .meta { margin-top: 5px; color: var(--fg-2); line-height: 1.7; }
</style>
