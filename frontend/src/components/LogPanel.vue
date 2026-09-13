<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import { call } from '../composables/useApi.js'

const TABS = [
  { key: 'go-proxy', label: '模型网关' },
  { key: 'watchdog', label: '守护进程' },
]

const tab = ref('go-proxy')
const box = ref(null)
const lines = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await call('get_logs', tab.value, 220)
    lines.value = r.lines || []
    await nextTick()
    if (box.value) box.value.scrollTop = box.value.scrollHeight
  } catch (e) {
    lines.value = ['读取失败：' + e]
  }
  loading.value = false
}

function switchTo(k) {
  if (tab.value === k) return
  tab.value = k
  load()
}

watch(tab, load)
onMounted(load)

defineExpose({ load })
</script>

<template>
  <div class="tabs">
    <button
      v-for="t in TABS"
      :key="t.key"
      class="btn sm"
      :class="{ accent: tab === t.key }"
      @click="switchTo(t.key)"
    >{{ t.label }}</button>
    <span style="flex: 1"></span>
    <button class="btn sm" :disabled="loading" @click="load">刷新</button>
  </div>
  <pre ref="box" class="logbox">{{ lines.join('\n') || '(空)' }}</pre>
</template>

<style scoped>
.tabs { display: flex; gap: 6px; margin-bottom: 11px; }
</style>
