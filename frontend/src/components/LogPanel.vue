<script setup>
import { computed, ref, onMounted, watch, nextTick } from 'vue'
import { call } from '../composables/useApi.js'

const TABS = [
  { key: 'go-proxy', label: '模型网关' },
  { key: 'watchdog', label: '守护进程' },
]

const tab = ref('go-proxy')
const box = ref(null)
const lines = ref([])
const loading = ref(false)
const follow = ref(true)     // 跟随：刷新后自动滚到最新
const kw = ref('')           // 关键字过滤

const shown = computed(() => {
  const k = kw.value.trim().toLowerCase()
  if (!k) return lines.value
  return lines.value.filter((l) => l.toLowerCase().includes(k))
})

async function load() {
  loading.value = true
  try {
    const r = await call('get_logs', tab.value, 220)
    lines.value = r.lines || []
    if (follow.value) {
      await nextTick()
      if (box.value) box.value.scrollTop = box.value.scrollHeight
    }
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
    <span class="spacer"></span>
    <input v-model="kw" type="text" class="filter" placeholder="过滤关键字">
    <button
      class="btn sm"
      :class="{ accent: follow }"
      title="刷新后自动滚动到最新一行"
      @click="follow = !follow"
    >跟随</button>
    <button class="btn sm" :disabled="loading" @click="load">刷新</button>
  </div>
  <pre ref="box" class="logbox">{{ shown.join('\n') || (kw ? '(无匹配行)' : '(空)') }}</pre>
  <div v-if="kw" class="fcount">{{ shown.length }} / {{ lines.length }} 行</div>
</template>

<style scoped>
.tabs { display: flex; gap: 6px; margin-bottom: 11px; align-items: center; }
.tabs .spacer { flex: 1; }
.filter { width: 160px; padding: 4px 10px; font-size: 12px; }
.fcount {
  margin-top: 6px;
  font-size: 11px;
  color: var(--fg-3);
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>
