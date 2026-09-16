<script setup>
import Icon from './Icon.vue'

defineProps({
  status: { type: Object, default: () => ({ ports: [], watchdog: {}, proxy_ports: [] }) },
  versions: { type: Object, default: () => ({}) },
})
</script>

<template>
  <div>
    <div v-for="p in status.ports" :key="p.name" class="row">
      <span class="led" :class="p.up ? 'ok' : 'fail'"></span>
      <Icon class="rico" name="server" :size="14" />
      <span class="nm">{{ p.name }} <span class="sub">{{ p.desc }}</span></span>
      <span class="tail">:{{ p.port }}</span>
      <span class="state" :class="p.up ? 'on' : 'off'">{{ p.up ? '运行中' : '未运行' }}</span>
    </div>

    <div class="row">
      <span class="led" :class="status.watchdog && status.watchdog.alive ? 'ok' : 'fail'"></span>
      <Icon class="rico" name="shield" :size="14" />
      <span class="nm">守护进程 <span class="sub">网关挂掉自动拉起</span></span>
      <span class="tail">{{ status.watchdog && status.watchdog.alive ? 'pid ' + status.watchdog.pid : '—' }}</span>
      <span class="state" :class="status.watchdog && status.watchdog.alive ? 'on' : 'off'">
        {{ status.watchdog && status.watchdog.alive ? '运行中' : '未运行' }}
      </span>
    </div>

    <div v-for="p in status.proxy_ports" :key="p.name" class="row">
      <span class="led" :class="p.up ? 'ok' : 'warn'"></span>
      <Icon class="rico" name="globe" :size="14" />
      <span class="nm">{{ p.name }} <span class="sub">{{ p.desc }}</span></span>
      <span class="tail">:{{ p.port }}</span>
      <span class="state" :class="p.up ? 'on' : 'warnstate'">{{ p.up ? '已启用' : '未启用' }}</span>
    </div>

    <div v-if="versions && versions.console" class="version-line">
      控制台 v{{ versions.console }} · 网关协议 {{ versions.gateway_protocol ?? '未上报' }} · 配置 schema {{ versions.config_schema }}
    </div>
  </div>
</template>

<style scoped>
.rico { color: var(--fg-3); }
.state {
  font-size: 11px;
  font-family: var(--font-mono);
  padding: 1px 8px;
  border-radius: 20px;
  flex-shrink: 0;
}
.state.on        { background: var(--ok-soft);   color: var(--ok); }
.state.off       { background: var(--fail-soft); color: var(--fail); }
.state.warnstate { background: var(--warn-soft); color: var(--warn); }
.version-line { margin-top: 10px; padding-top: 9px; border-top: 1px solid var(--border); color: var(--fg-3); font-size: 11px; }
</style>
