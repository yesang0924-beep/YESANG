<script setup>
import { computed } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  health: { type: Object, default: () => ({ level: 'warn', problems: [] }) },
  busy: { type: Boolean, default: false },
})
defineEmits(['fix'])

const TITLES = { ok: '一切正常', warn: '能跑，但有隐患', fail: '服务未运行' }
const ICONS = { ok: 'check', warn: 'alert', fail: 'close' }
// 图标底座配色：正常=绿，异常=琥珀，宕机=红
const TONES = { ok: 'green', warn: 'amber', fail: 'red' }

const title = computed(() => TITLES[props.health.level] || '正在检查…')
const iconName = computed(() => ICONS[props.health.level] || 'activity')
const tone = computed(() => TONES[props.health.level] || 'blue')
const actionText = computed(() => (props.health.level === 'fail' ? '一键启动' : '一键修复'))
</script>

<template>
  <header class="hero">
    <div class="hero-inner">
      <span class="icon-box" :class="tone">
        <Icon :name="iconName" :size="18" :stroke-width="2.25" />
      </span>

      <div class="hero-text">
        <h1 class="hero-title">{{ title }}</h1>
        <div class="hero-sub">
          <template v-if="health.problems && health.problems.length">
            <div v-for="(p, i) in health.problems" :key="i" class="problem">· {{ p }}</div>
          </template>
          <span v-else>网关、守护进程、本地反代均在正常运行</span>
        </div>
      </div>

      <div class="hero-actions">
        <slot name="extra" />
        <button v-if="health.level !== 'ok'" class="btn-xl" :disabled="busy" @click="$emit('fix')">
          <span v-if="busy" class="spin"></span>
          <Icon v-else :name="health.level === 'fail' ? 'play' : 'zap'" :size="15" />
          {{ busy ? '处理中…' : actionText }}
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.hero {
  padding: 26px 28px 22px;
  background: var(--bg);
  flex-shrink: 0;
  transition: background .25s;
}
.hero-inner {
  display: flex;
  align-items: center;
  gap: 16px;
  max-width: 1200px;
  margin: 0 auto;
}
.hero-inner .icon-box {
  width: 44px;
  height: 44px;
  border-radius: 13px;
}
.hero-text { flex: 1; min-width: 0; }
.hero-title {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -.3px;
  line-height: 1.2;
  margin-bottom: 4px;
}
.hero-sub {
  color: var(--fg-2);
  font-size: 13px;
  line-height: 1.6;
}
.problem { color: var(--warn); }
.hero-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
</style>
