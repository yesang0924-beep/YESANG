<script setup>
import { computed, ref } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  models: { type: Array, default: () => [] },
  probing: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['probe', 'remove', 'add'])

const GROUPS = [
  { value: 'go/', label: '[Go] OpenCode Go' },
  { value: 'local/', label: '[Local] 本地反代' },
  { value: 'yh/', label: '[Yoshub] 中转站' },
  { value: 'yhds/', label: '[YS-DS] 中转站 DeepSeek' },
]

const newSlug = ref('')
const newGroup = ref('go/')

const grouped = computed(() => {
  const out = {}
  for (const m of props.models) {
    ;(out[m.group] = out[m.group] || []).push(m)
  }
  return out
})

function stripTag(display) {
  return String(display || '').replace(/^\[[^\]]*\]\s*/, '')
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
      <span class="tag-note">增删自动备份 catalog</span>
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
            <span class="nm">{{ stripTag(m.display) }}</span>
            <span v-if="m.ctx" class="ctx">{{ Math.round(m.ctx / 1000) }}K</span>
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
</style>
