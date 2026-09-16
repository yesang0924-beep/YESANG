<script setup>
import { ref, onMounted } from 'vue'
import { call } from '../composables/useApi.js'
import Icon from './Icon.vue'

const events = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await call('get_audit', 60)
    events.value = r.events || []
  } catch (e) {
    events.value = []
  }
  loading.value = false
}
onMounted(load)
defineExpose({ load })
</script>

<template>
  <div>
    <div class="hline">
      <span class="tag-note">记录模型池、路由、自启动和用量基线的本机变更</span>
      <span class="spacer"></span>
      <button class="btn sm" :disabled="loading" @click="load">
        <Icon name="refresh" :size="12" />{{ loading ? '读取中' : '刷新' }}
      </button>
    </div>
    <div v-if="!events.length" class="empty">暂无变更记录</div>
    <div v-else class="list">
      <div v-for="(e, i) in events" :key="i" class="event">
        <span class="time">{{ e.ts }}</span>
        <span class="action">{{ e.action }}</span>
        <span class="target">{{ e.target }}</span>
        <span class="detail">{{ e.detail || '—' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hline { display: flex; align-items: center; margin-bottom: 10px; }
.hline .spacer { flex: 1; }
.list { display: flex; flex-direction: column; gap: 6px; max-height: 260px; overflow-y: auto; }
.event {
  display: grid; grid-template-columns: 145px 130px 160px 1fr; gap: 8px;
  padding: 7px 9px; border-radius: 8px; background: var(--card-2);
  font-size: 11.5px; color: var(--fg-2); align-items: center;
}
.time, .action, .target { font-family: var(--font-mono); }
.action { color: var(--accent); }
.detail { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
