<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { call, toast, useToast } from './composables/useApi.js'
import Icon from './components/Icon.vue'
import HealthBanner from './components/HealthBanner.vue'
import StatBar from './components/StatBar.vue'
import CollapsibleCard from './components/CollapsibleCard.vue'
import StatusPanel from './components/StatusPanel.vue'
import UpstreamPanel from './components/UpstreamPanel.vue'
import ModelPool from './components/ModelPool.vue'
import UsagePanel from './components/UsagePanel.vue'
import LogPanel from './components/LogPanel.vue'
import AdvancedPanel from './components/AdvancedPanel.vue'
import UpstreamConfig from './components/UpstreamConfig.vue'
import ModelSync from './components/ModelSync.vue'

const health = ref({ level: 'warn', problems: [] })
const status = ref({ ports: [], watchdog: {}, proxy_ports: [], autostart: false })
const models = ref([])
const usage = ref({ models: [] })
const upstreamConfigs = ref([])
const upstreamCfgRef = ref(null)
const upstreamResults = ref([])
const probing = ref({})
const busy = ref(false)
const upstreamOk = ref(null)

const logRef = ref(null)
const toastMsg = useToast()

/* ---------------- 主题 ---------------- */
const theme = ref('light')

function applyTheme() {
  document.documentElement.setAttribute('data-theme', theme.value)
  try {
    localStorage.setItem('rc-theme-v2', theme.value)
  } catch (e) { /* 隐私模式等场景忽略 */ }
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  applyTheme()
}

let timer = null

/* ---------------- 数据加载 ---------------- */
async function refreshHealth() {
  try {
    const h = await call('get_health')
    health.value = h
    status.value = h.status
  } catch (e) {
    health.value = { level: 'warn', problems: ['状态读取失败：' + e] }
  }
}

async function loadModels() {
  try {
    models.value = await call('get_models')
  } catch (e) { /* 静默，界面保持上一次数据 */ }
}

async function loadUsage() {
  try {
    usage.value = await call('get_usage')
  } catch (e) { /* 同上 */ }
}

async function loadUpstreams() {
  try {
    const u = await call('get_upstream_configs')
    upstreamConfigs.value = u.upstreams || []
  } catch (e) { /* 同上 */ }
}

async function saveUpstream({ name, base, use_proxy, key }) {
  try {
    const r = await call('update_upstream', name, base, use_proxy, key || null)
    toast(r.msg)
    if (r.configs) upstreamConfigs.value = r.configs.upstreams
    if (r.need_restart) {
      if (confirm('接口地址已修改，需要重启模型网关才能生效。\n\n现在重启？')) {
        await restartGateway()
      }
    }
  } catch (e) {
    toast('保存失败：' + e)
  }
}

async function testUpstreamConfig({ name, base, key, use_proxy }) {
  try {
    const r = await call('test_upstream_config', base, key, '', use_proxy, name)
    upstreamCfgRef.value?.setResult(name, r)
  } catch (e) {
    upstreamCfgRef.value?.setResult(name, { ok: false, text: String(e) })
  }
}

async function probeUpstreams() {
  try {
    upstreamResults.value = await call('test_upstreams')
    upstreamOk.value = upstreamResults.value.filter((r) => r.state === 'ok').length
  } catch (e) {
    toast('上游测试失败：' + e)
  }
}

/* ---------------- 操作 ---------------- */
async function oneClick() {
  if (busy.value) return
  busy.value = true
  try {
    const r = await call('one_click')
    toast('已完成：' + (r.actions || []).join('、'))
    await refreshHealth()
    await loadModels()
    await loadUsage()
  } catch (e) {
    toast('操作失败：' + e)
  }
  busy.value = false
}

async function restartGateway() {
  try {
    toast('正在重启模型网关…')
    await call('restart_gateway')
    toast('模型网关已重启')
    await refreshHealth()
  } catch (e) { toast('重启失败：' + e) }
}

async function stopAll() {
  if (!confirm('停止网关与守护进程？\nCodex 将暂时无法调用任何模型。')) return
  try {
    await call('stop_all')
    toast('已全部停止')
    await refreshHealth()
  } catch (e) { toast('停止失败：' + e) }
}

async function toggleAutostart(on) {
  try {
    const r = await call('set_autostart', on)
    status.value = { ...status.value, autostart: r.enabled }
    toast(on ? '已开启开机自启' : '已关闭开机自启')
  } catch (e) { toast('设置失败：' + e) }
}

async function probeModel(slug) {
  probing.value = { ...probing.value, [slug]: true }
  try {
    const r = await call('probe_model', slug)
    toast(slug + ' → ' + (r.ok ? '✓ 可用：' + String(r.text).slice(0, 70)
                                : '✕ ' + String(r.text).slice(0, 110)))
  } catch (e) {
    toast('测试失败：' + e)
  }
  probing.value = { ...probing.value, [slug]: false }
}

async function removeModel(slug) {
  if (!confirm('从模型池移除 ' + slug + ' ？\n（会自动备份 catalog）')) return
  try {
    const r = await call('remove_model', slug)
    toast(r.msg)
    if (r.models) models.value = r.models
  } catch (e) { toast('移除失败：' + e) }
}

async function addModel({ slug, group }) {
  try {
    const r = await call('add_model', slug, slug, group)
    toast(r.msg)
    if (r.models) models.value = r.models
  } catch (e) { toast('添加失败：' + e) }
}

function openFolder() {
  call('open_folder', 'bin').catch(() => {})
}

/* ---------------- 诊断包 / 告警 ---------------- */
const alerts = ref([])

async function exportDiag() {
  toast('正在打包诊断信息…')
  try {
    const r = await call('export_diagnostics')
    toast(r.msg)
  } catch (e) {
    toast('导出失败：' + e)
  }
}

async function loadAlerts() {
  try {
    const r = await call('get_alerts', 20)
    alerts.value = r.alerts || []
  } catch (e) { /* 静默 */ }
}

async function clearAlerts() {
  try {
    await call('clear_alerts')
    alerts.value = []
    toast('已清空告警')
  } catch (e) { toast('清空失败：' + e) }
}

/* ---------------- 模型池同步 ---------------- */
const syncRef = ref(null)

async function fetchUpstreamModels(name) {
  syncRef.value?.setLoading(true)
  try {
    const r = await call('fetch_upstream_models', name)
    syncRef.value?.setResult(r)
  } catch (e) {
    syncRef.value?.setResult({ ok: false, msg: String(e) })
  }
}

async function importModels({ name, ids }) {
  try {
    const r = await call('import_models', name, ids)
    toast(r.msg)
    if (r.models) models.value = r.models
    if (r.ok) await fetchUpstreamModels(name)
  } catch (e) {
    toast('导入失败：' + e)
  }
}

/* ---------------- 计算属性 ---------------- */
const stats = computed(() => {
  const up = upstreamOk.value
  const totalReq = usage.value.models.reduce((a, b) => a + b.requests, 0)
  const totalCost = usage.value.models.reduce((a, b) => a + b.cost, 0)
  return [
    { value: models.value.length || '–', label: '可用模型', icon: 'layers', tone: 'blue' },
    {
      value: up === null ? '–' : up + ' / 4',
      label: '上游连通',
      icon: 'route',
      tone: 'green',                     // 图标底座配色
      status: up === null ? '' : (up === 4 ? '全部可用' : up ? '部分可用' : '全部不可用'),
      statusTone: up === null ? '' : (up === 4 ? 'ok' : up ? 'warn' : 'fail'),
    },
    { value: totalReq.toLocaleString(), label: '累计请求', icon: 'activity', tone: 'purple' },
    { value: '$' + totalCost.toFixed(3), label: '累计花费', icon: 'gauge', tone: 'cyan' },
  ]
})

/* ---------------- 生命周期 ---------------- */
onMounted(async () => {
  try {
    const saved = localStorage.getItem('rc-theme-v2')
    if (saved === 'light' || saved === 'dark') theme.value = saved
  } catch (e) { /* ignore */ }
  applyTheme()

  await refreshHealth()
  loadModels()
  loadUsage()
  loadUpstreams()
  loadAlerts()
  // 等后端就绪后再跑一次上游实测，避免和首屏渲染抢时间
  setTimeout(probeUpstreams, 1200)
  timer = setInterval(() => {
    if (!busy.value) refreshHealth()
  }, 12000)
})

onUnmounted(() => clearInterval(timer))
</script>

<template>
  <HealthBanner :health="health" :busy="busy" @fix="oneClick">
    <template #extra>
      <button
        class="theme-btn"
        :title="theme === 'dark' ? '切换到亮色主题' : '切换到深色主题'"
        @click="toggleTheme"
      >
        <Icon :name="theme === 'dark' ? 'sun' : 'moon'" :size="16" />
      </button>
    </template>
  </HealthBanner>
  <!-- 告警条：只在看门狗自愈失败时出现，正常情况不占位置 -->
  <div v-if="alerts.length" class="alerts">
    <div class="alerts-inner">
      <Icon name="alert" :size="15" />
      <span class="atitle">{{ alerts.length }} 条待处理告警</span>
      <span class="alast">{{ alerts[0].ts }} · {{ alerts[0].target }} · {{ alerts[0].detail }}</span>
      <button class="btn sm ghost" @click="clearAlerts">知道了</button>
    </div>
  </div>

  <StatBar :stats="stats" />

  <main>
    <div class="wrap">
      <CollapsibleCard title="服务状态" tone="green" icon="server" default-open :note="status.time">
        <template #actions>
          <button class="btn sm" @click="refreshHealth">刷新</button>
        </template>
        <StatusPanel :status="status" />
      </CollapsibleCard>

      <CollapsibleCard title="上游连通性" tone="blue" icon="globe" note="点右上角逐个实测">
        <template #actions>
          <button class="btn sm" @click="probeUpstreams">开始测试</button>
        </template>
        <UpstreamPanel :results="upstreamResults" />
      </CollapsibleCard>

      <CollapsibleCard title="模型池" tone="purple" icon="layers" :badge="models.length ? models.length + ' 个' : null">
        <ModelPool
          :models="models"
          :probing="probing"
          @probe="probeModel"
          @remove="removeModel"
          @add="addModel"
        />
      </CollapsibleCard>

      <CollapsibleCard
        title="从上游同步模型"
        icon="refresh"
        tone="green"
        note="拉取上游模型列表，勾选导入"
      >
        <ModelSync
          ref="syncRef"
          :upstreams="upstreamConfigs"
          @fetch="fetchUpstreamModels"
          @import="importModels"
        />
      </CollapsibleCard>

      <CollapsibleCard title="用量统计" tone="cyan" icon="database" note="累计自网关启动">
        <template #actions>
          <button class="btn sm" @click="loadUsage">刷新</button>
        </template>
        <UsagePanel :usage="usage" />
      </CollapsibleCard>

      <CollapsibleCard title="日志" tone="amber" icon="terminal">
        <LogPanel ref="logRef" />
      </CollapsibleCard>

      <CollapsibleCard title="上游配置" tone="pink" icon="route" note="改接口地址后需重启网关生效">
        <UpstreamConfig
          ref="upstreamCfgRef"
          :configs="upstreamConfigs"
          @save="saveUpstream"
          @test="testUpstreamConfig"
        />
      </CollapsibleCard>

      <CollapsibleCard title="高级" tone="red" icon="shield" note="一般用不到">
        <AdvancedPanel
          :autostart="!!status.autostart"
          @toggle-autostart="toggleAutostart"
          @restart="restartGateway"
          @stop="stopAll"
          @open-folder="openFolder"
          @export-diag="exportDiag"
        />
      </CollapsibleCard>
    </div>
  </main>

  <transition name="fade">
    <div v-if="toastMsg" class="toast">{{ toastMsg }}</div>
  </transition>
</template>

<style scoped>
main { flex: 1; overflow-y: auto; padding: 18px 26px 30px; }
.wrap { max-width: 1180px; margin: 0 auto; display: grid; gap: var(--gap); }

.alerts {
  padding: 0 28px 12px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  flex-shrink: 0;
}
.alerts-inner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-radius: var(--r-md);
  background: var(--fail-soft);
  border: 1px solid var(--fail);
  color: var(--fail);
  font-size: 12.5px;
}
.atitle { font-weight: 600; flex-shrink: 0; }
.alast {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--fg-2);
  font-family: var(--font-mono);
  font-size: 11.5px;
}

.theme-btn {
  width: 38px; height: 38px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--card-2);
  color: var(--fg-2);
  margin-right: 8px;
}
.theme-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-soft);
}

.toast {
  position: fixed; bottom: 26px; left: 50%;
  transform: translateX(-50%);
  background: var(--card-2);
  border: 1px solid var(--accent);
  color: var(--fg);
  padding: 11px 22px; border-radius: 11px;
  font-size: 13px; max-width: 76vw;
  box-shadow: var(--shadow); z-index: 99;
}
.fade-enter-active, .fade-leave-active { transition: opacity .22s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
