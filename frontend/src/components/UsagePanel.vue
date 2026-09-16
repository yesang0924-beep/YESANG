<script setup>
import { computed } from 'vue'

const props = defineProps({
  usage: { type: Object, default: () => ({ models: [] }) },
  metrics: { type: Object, default: () => ({ points: [], totals: {} }) },
})

const rows = computed(() =>
  [...(props.usage.models || [])].sort((a, b) => b.requests - a.requests))

const totalReq = computed(() => rows.value.reduce((a, b) => a + b.requests, 0))
const totalCost = computed(() => rows.value.reduce((a, b) => a + b.cost, 0))
const maxReq = computed(() => Math.max(1, ...rows.value.map((r) => r.requests)))
const hourly = computed(() => props.metrics.points || [])
const maxHourReq = computed(() => Math.max(1, ...hourly.value.map((p) => p.requests)))

/** 按上游前缀聚合，看哪条线路在承压 */
const byUpstream = computed(() => {
  const acc = {}
  for (const r of rows.value) {
    const g = groupOf(r.model)
    acc[g] = acc[g] || { req: 0, cost: 0, models: 0 }
    acc[g].req += r.requests
    acc[g].cost += r.cost
    acc[g].models += 1
  }
  return Object.entries(acc)
    .map(([name, v]) => ({ name, ...v }))
    .sort((a, b) => b.req - a.req)
})

const maxGroupReq = computed(() => Math.max(1, ...byUpstream.value.map((g) => g.req)))

function groupOf(model) {
  const m = String(model || '')
  if (m.startsWith('go/')) return '[Go]'
  if (m.startsWith('local/')) return '[Local]'
  if (m.startsWith('yhds/')) return '[YS-DS]'
  if (m.startsWith('yh/')) return '[Yoshub]'
  return '其他'
}

function pct(v, max) {
  return Math.max(2, Math.round((v / max) * 100)) + '%'
}
</script>

<template>
  <div v-if="!rows.length && !hourly.length" class="empty">暂无统计数据</div>

  <template v-else>
    <div v-if="hourly.length" class="trend-wrap">
      <div class="section-title">最近 24 小时</div>
      <div class="trend">
        <div v-for="p in hourly" :key="p.hour" class="tcol" :title="`${p.hour} · ${p.requests} 次 · $${p.cost.toFixed(4)}`">
          <div class="tbar" :class="{ bad: p.err > p.ok }" :style="{ height: pct(p.requests, maxHourReq) }"></div>
          <span class="thour">{{ p.hour.slice(11) }}</span>
        </div>
      </div>
      <div class="trend-sum">请求 {{ metrics.totals.requests || 0 }} · 失败 {{ metrics.totals.err || 0 }} · ${{ (metrics.totals.cost || 0).toFixed(4) }}</div>
    </div>
    <template v-if="rows.length">
    <!-- 按上游聚合 -->
    <div class="section-title">按上游</div>
    <div v-for="g in byUpstream" :key="g.name" class="bar-row">
      <span class="bname">{{ g.name }}</span>
      <div class="track">
        <div class="fill up" :style="{ width: pct(g.req, maxGroupReq) }"></div>
      </div>
      <span class="bval">{{ g.req.toLocaleString() }} 次 · {{ g.models }} 模型</span>
    </div>

    <!-- 按模型 TOP -->
    <div class="section-title">按模型</div>
    <div v-for="m in rows" :key="m.model" class="bar-row">
      <span class="bname mono" :title="m.model">{{ m.model }}</span>
      <div class="track">
        <div
          class="fill"
          :class="{ err: m.err > 0 && m.ok === 0 }"
          :style="{ width: pct(m.requests, maxReq) }"
        ></div>
      </div>
      <span class="bval">
        {{ m.requests.toLocaleString() }} 次<template v-if="m.err"> · 失败 {{ m.err }}</template>
        · ${{ m.cost.toFixed(4) }}
      </span>
    </div>

    <!-- 明细表 -->
    <div class="section-title">明细</div>
    <table>
      <thead>
        <tr>
          <th>模型</th><th>请求</th><th>成功</th><th>失败</th>
          <th>输出 tokens</th><th>≈ 花费</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="m in rows" :key="m.model">
          <td>{{ m.model }}</td>
          <td>{{ m.requests }}</td>
          <td>{{ m.ok }}</td>
          <td>{{ m.err || '—' }}</td>
          <td>{{ m.out_tokens.toLocaleString() }}</td>
          <td>${{ m.cost.toFixed(4) }}</td>
        </tr>
        <tr class="total">
          <td>合计</td>
          <td>{{ totalReq.toLocaleString() }}</td>
          <td></td><td></td><td></td>
          <td>${{ totalCost.toFixed(4) }}</td>
        </tr>
      </tbody>
    </table>
    </template>
  </template>
</template>

<style scoped>
.section-title {
  color: var(--fg-3);
  font-size: 11.5px;
  letter-spacing: .4px;
  margin: 14px 0 8px;
}
.section-title:first-child { margin-top: 2px; }

.bar-row {
  display: grid;
  grid-template-columns: 200px 1fr 210px;
  align-items: center;
  gap: 11px;
  padding: 4px 0;
}
.bname {
  font-size: 12px;
  color: var(--fg-2);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.bname.mono { font-family: Consolas, monospace; font-size: 11.5px; }
.track {
  height: 8px;
  background: var(--card-3);
  border-radius: 5px;
  overflow: hidden;
}
.fill {
  height: 100%;
  border-radius: 5px;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  transition: width .3s;
}
.fill.up { background: linear-gradient(90deg, #0f6e56, var(--ok)); }
.fill.err { background: linear-gradient(90deg, #791f1f, var(--fail)); }
.bval {
  font-size: 11.5px;
  color: var(--fg-3);
  font-variant-numeric: tabular-nums;
  text-align: right;
  white-space: nowrap;
}
table { margin-top: 2px; }
tr.total td { font-weight: 600; }
.trend-wrap { margin-bottom: 4px; }
.trend { display: flex; align-items: flex-end; gap: 4px; height: 70px; padding: 6px 0; }
.tcol { flex: 1; min-width: 5px; height: 58px; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; }
.tbar { width: 100%; min-height: 2px; border-radius: 3px 3px 0 0; background: linear-gradient(180deg, var(--accent), var(--accent-2)); }
.tbar.bad { background: linear-gradient(180deg, var(--fail), #b33); }
.thour { margin-top: 4px; font-size: 9px; color: var(--fg-3); font-family: var(--font-mono); }
.trend-sum { text-align: right; color: var(--fg-3); font-size: 11px; }
</style>
