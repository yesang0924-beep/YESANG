<script setup>
import { ref, onMounted } from 'vue'
import { call } from '../composables/useApi.js'
import Icon from './Icon.vue'

const items = ref([])
const loading = ref(false)
const LABELS = {
  rate_limit: '限流 / 额度', dns: 'DNS', tls: 'TLS / 证书', timeout: '超时',
  auth: '鉴权', request: '请求格式', network: '网络连接', other: '其他',
}
async function load() {
  loading.value = true
  try { items.value = (await call('get_error_summary')).items || [] }
  catch (e) { items.value = [] }
  loading.value = false
}
onMounted(load)
</script>

<template>
  <div>
    <div class="hline">
      <span class="tag-note">从网关和守护日志尾部聚类，快速定位问题类型</span>
      <span class="spacer"></span>
      <button class="btn sm" :disabled="loading" @click="load">
        <Icon name="refresh" :size="12" />{{ loading ? '分析中' : '刷新' }}
      </button>
    </div>
    <div v-if="!items.length" class="empty">暂未发现错误特征</div>
    <div v-else class="list">
      <div v-for="x in items" :key="x.category" class="item" :title="(x.samples || []).join('\n')">
        <span class="cat">{{ LABELS[x.category] || x.category }}</span>
        <span class="count">{{ x.count }} 条</span>
        <span class="sample">{{ (x.samples && x.samples[0]) || '—' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hline { display: flex; align-items: center; margin-bottom: 10px; }
.hline .spacer { flex: 1; }
.list { display: flex; flex-direction: column; gap: 6px; }
.item { display: grid; grid-template-columns: 130px 60px 1fr; gap: 8px; align-items: center;
  padding: 7px 9px; border-radius: 8px; background: var(--card-2); font-size: 11.5px; }
.cat { color: var(--warn); font-weight: 600; }
.count { font-family: var(--font-mono); color: var(--fg-3); }
.sample { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--fg-3); }
</style>
