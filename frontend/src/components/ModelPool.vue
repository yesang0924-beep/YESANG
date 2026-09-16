<script setup>
import { computed, ref } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  models: { type: Array, default: () => [] },
  probing: { type: Object, default: () => ({}) },
  results: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['probe', 'probe-all', 'remove', 'add', 'move', 'rename'])

const GROUPS = [
  { value: 'go/', label: '[Go] OpenCode Go' },
  { value: 'local/', label: '[Local] 本地反代' },
  { value: 'yh/', label: '[Yoshub] 中转站' },
  { value: 'yhds/', label: '[YS-DS] 中转站 DeepSeek' },
]

const newSlug = ref('')
const newGroup = ref('go/')

/* 改名：行内编辑 —— pywebview 不支持 window.prompt，只能这么干 */
const editing = ref(null)
const editName = ref('')

const grouped = computed(() => {
  const out = {}
  for (const m of props.models) {
    ;(out[m.group] = out[m.group] || []).push(m)
  }
  return out
})

function tagOf(display) {
  return (String(display || '').match(/^\[[^\]]*\]\s*/) || [''])[0]
}

function stripTag(display) {
  return String(display || '').replace(/^\[[^\]]*\]\s*/, '')
}

function startEdit(m) {
  editing.value = m.slug
  editName.value = stripTag(m.display)
}

function commitEdit(m) {
  const name = editName.value.trim()
  // 保留原有 [组] 前缀，客户端菜单里分组标识不丢
  if (name && name !== stripTag(m.display)) {
    emit('rename', { slug: m.slug, display: tagOf(m.display) + name })
  }
  editing.value = null
}

function submit() {
  if (!newSlug.value.trim()) return
  emit('add', { slug: newSlug.value.trim(), group: newGroup.value })
  newSlug.value = ''
}
</script>

<template>
  <div>
    <div class="hline">
      <input
        v-model="newSlug"
        type="text"
        placeholder="模型 id，如 qwen3.8-max"
        style="width: 230px"
        @keyup.enter="submit"
      >
      <select v-model="newGroup">
        <option v-for="g in GROUPS" :key="g.value" :value="g.value">{{ g.label }}</option>
      </select>
      <button class="btn accent sm" @click="submit">
        <Icon name="plus" :size="13" />添加
      </button>
      <span class="spacer"></span>
      <button class="btn sm" title="并发测试模型池内所有模型的实时连通性" @click="emit('probe-all')">
        <Icon name="zap" :size="12" />全部测活
      </button>
      <span class="tag-note">↑↓ 排序 · 双击改名</span>
    </div>

    <div v-if="!models.length" class="empty">模型池为空</div>

    <div v-for="(list, group) in grouped" :key="group" class="group">
      <div class="group-title">
        <span class="glabel">{{ group }}</span>
        <span class="gcount">{{ list.length }}</span>
      </div>
      <div class="mgrid">
        <div v-for="m in list" :key="m.slug" class="mitem">
          <div class="top">
            <input
              v-if="editing === m.slug"
              v-model="editName"
              class="rename-input"
              type="text"
              @keyup.enter="commitEdit(m)"
              @keyup.esc="editing = null"
              @blur="commitEdit(m)"
            >
            <span v-else class="nm" title="双击改名" @dblclick="startEdit(m)">{{ stripTag(m.display) }}</span>
            <span v-if="m.ctx" class="ctx">{{ Math.round(m.ctx / 1000) }}K</span>
            <span
              v-if="results[m.slug]"
              class="state-pill"
              :class="results[m.slug].ok ? 'ok' : 'fail'"
              :title="String(results[m.slug].text || '')"
            >
              <span class="led" :class="results[m.slug].ok ? 'ok' : 'fail'"></span>
              {{ results[m.slug].ok ? ((results[m.slug].latency_ms || 0) + 'ms') : (results[m.slug].text ? String(results[m.slug].text).slice(0, 14) : '不可用') }}
            </span>
          </div>
          <div class="id">{{ m.slug }}</div>
          <div class="btns">
            <button
              class="btn accent sm"
              :disabled="probing[m.slug]"
              @click="emit('probe', m.slug)"
            >
              <span v-if="probing[m.slug]" class="spin"></span>
              <Icon v-else name="zap" :size="12" />
              {{ probing[m.slug] ? '测试中' : '测试' }}
            </button>
            <button
              class="btn sm"
              title="上移（客户端下拉里更靠前）"
              @click="emit('move', { slug: m.slug, direction: 'up' })"
            >
              <Icon name="up" :size="12" />
            </button>
            <button class="btn sm" title="下移" @click="emit('move', { slug: m.slug, direction: 'down' })">
              <Icon name="down" :size="12" />
            </button>
            <button class="btn sm" title="改显示名" @click="startEdit(m)">
              <Icon name="pencil" :size="12" />
            </button>
            <button class="btn sm" @click="emit('remove', m.slug)">
              <Icon name="trash" :size="12" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hline {
  display: flex;
  gap: 9px;
  align-items: center;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.hline .spacer { flex: 1; }

.group { margin-bottom: 16px; }
.group:last-child { margin-bottom: 0; }

.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 9px;
}
.glabel {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .4px;
  color: var(--accent);
}
.gcount {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--fg-3);
  background: var(--card-3);
  border-radius: 20px;
  padding: 0 7px;
}

.mgrid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 9px;
}
.mitem {
  background: var(--card-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  transition: border-color .15s, background .15s;
}
.mitem:hover {
  border-color: var(--accent);
  background: var(--card-3);
}
.mitem .top {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mitem .nm {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--fg);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: text;
}
.rename-input {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  padding: 2px 7px;
}
.ctx {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--fg-3);
  background: var(--card-3);
  border-radius: 4px;
  padding: 1px 6px;
  flex-shrink: 0;
}
.mitem .id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--fg-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mitem .btns { display: flex; gap: 6px; }

.state-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  max-width: 130px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: help;
}
.state-pill.ok {
  background: var(--ok-bg, rgba(34, 197, 94, 0.12));
  color: var(--ok, #16a34a);
  border: 1px solid rgba(34, 197, 94, 0.25);
}
.state-pill.fail {
  background: var(--fail-bg, rgba(239, 68, 68, 0.12));
  color: var(--fail, #dc2626);
  border: 1px solid rgba(239, 68, 68, 0.25);
}
.state-pill .led {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.state-pill .led.ok {
  background: #16a34a;
  box-shadow: 0 0 5px rgba(22, 163, 74, 0.6);
}
.state-pill .led.fail {
  background: #dc2626;
  box-shadow: 0 0 5px rgba(220, 38, 38, 0.6);
}

</style>
