<script setup>
import { ref, onMounted } from 'vue'
import { call } from '../composables/useApi.js'
import Icon from './Icon.vue'

const hourly = ref(0)
const daily = ref(0)
const status = ref(null)
const saving = ref(false)

async function load() {
  try {
    status.value = await call('get_budget')
    hourly.value = status.value.hourly_usd || 0
    daily.value = status.value.daily_usd || 0
  } catch (e) { status.value = null }
}
async function save() {
  saving.value = true
  try {
    const r = await call('set_budget', Number(hourly.value), Number(daily.value))
    if (r.budget) status.value = r.budget
  } catch (e) { /* feedback handled by parent toast on next save */ }
  saving.value = false
}
onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="budget">
    <div class="row">
      <label>本小时上限（USD）<input v-model.number="hourly" type="number" min="0" step="0.01"></label>
      <label>今日上限（USD）<input v-model.number="daily" type="number" min="0" step="0.01"></label>
      <button class="btn accent sm" :disabled="saving" @click="save">
        <Icon name="check" :size="12" />{{ saving ? '保存中' : '保存预算' }}
      </button>
    </div>
    <div v-if="status" class="status" :class="status.ok ? 'good' : 'bad'">{{ status.message }}</div>
    <div v-else class="empty">预算读取失败</div>
  </div>
</template>

<style scoped>
.budget .row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.budget label { display: flex; flex-direction: column; gap: 5px; color: var(--fg-3); font-size: 11.5px; }
.budget input { width: 150px; }
.status { margin-top: 10px; padding: 8px 10px; border-radius: 8px; font-size: 12px; }
.status.good { background: var(--ok-soft); color: var(--ok); }
.status.bad { background: var(--fail-soft); color: var(--fail); }
</style>
